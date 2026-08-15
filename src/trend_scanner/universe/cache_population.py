"""KRX Official Common Stock Cache Population Service.

공인 KRX Universe에서 AssetType.COMMON(KOSPI / KOSDAQ 보통주)을 대상으로
최신 일봉 OHLCV / Trading Value 캐시를 안전하고 결정론적으로 구축/갱신하는 Production Pipeline이다.

[핵심 설계 원칙]:
1. Authoritative Target: official KRX 마스터의 KOSPI/KOSDAQ AssetType.COMMON만 수집 대상.
2. Incremental Update: 최신 캐시는 SKIP하고, stale 캐시만 overlap 증분 fetch.
3. Safe Merge: duplicate 제거, date index 정렬, 신규 row 우선 적용.
4. Failure Isolation: 개별 종목 실패 시 전체 중단 없이 failure provenance 기록 후 계속 진행.
5. Idempotent & Resumable: 동일 시점 재실행 시 중복 변경 없이 이어서 처리.
6. Minimum History Target: 6M Momentum contract인 42 completed months 이상(권장 48개월) 확보.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import logging
from pathlib import Path
import time
from typing import Callable

import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.provider import MarketDataProvider
from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.data.repository import DEFAULT_OVERLAP_DAYS
from trend_scanner.data.resampler import to_monthly
from trend_scanner.data.validator import validate_ohlcv
from trend_scanner.universe.asset_classifier import classify_asset_type
from trend_scanner.universe.krx_universe import get_latest_market_trading_date, load_krx_equity_universe
from trend_scanner.universe.models import AssetType, MarketType, UniverseSecurity
from trend_scanner.validation.historical_snapshot import _drop_incomplete_current_month

logger = logging.getLogger(__name__)

# 기본 권장 히스토리 확보 기간 (5년 = 약 60개월, 최소 48 completed months 여유 확보)
DEFAULT_BACKFILL_YEARS: int = 5
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_BACKOFF: float = 0.5


class CachePopulationStatus(str, Enum):
    """개별 종목의 캐시 수집/갱신 결과 상태."""

    SKIPPED_FRESH = "SKIPPED_FRESH"
    UPDATED = "UPDATED"
    CREATED = "CREATED"
    FAILED = "FAILED"
    EXCLUDED_NOT_COMMON = "EXCLUDED_NOT_COMMON"


@dataclass(frozen=True)
class CachePopulationRecord:
    """종목 단위 캐시 수집 실행 상세 기록."""

    ticker: str
    name: str
    market: MarketType
    asset_type: AssetType
    reference_market_date: str
    status: CachePopulationStatus

    cache_existed_before: bool = False
    cache_first_date_before: str | None = None
    cache_last_date_before: str | None = None

    fetch_start_date: str | None = None
    fetch_end_date: str | None = None
    fetched_row_count: int = 0

    cache_first_date_after: str | None = None
    cache_last_date_after: str | None = None
    total_row_count_after: int = 0
    completed_month_count_after: int = 0

    retry_count: int = 0
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class CachePopulationSummary:
    """전체 유니버스 캐시 수집 종합 요약."""

    reference_market_date: str
    official_universe_total: int
    official_common_total: int
    population_target_count: int

    cache_present_before: int
    cache_missing_before: int
    fresh_before: int
    stale_before: int

    created_count: int
    updated_count: int
    skipped_fresh_count: int
    failed_count: int

    cache_present_after: int
    fresh_after: int
    stale_after: int

    minimum_history_ready_after: int  # 36 completed months
    history_42m_ready_after: int      # 42 completed months (6M momentum)
    history_48m_ready_after: int      # 48 completed months (preferred target)

    orphan_cache_count: int

    records: tuple[CachePopulationRecord, ...] = ()
    failed_records: tuple[CachePopulationRecord, ...] = ()
    exceptions: tuple[str, ...] = ()


def _count_completed_months(daily: pd.DataFrame, reference_date: str | pd.Timestamp) -> int:
    """주어진 일봉 데이터로부터 reference_date 기준 완성 월봉 개수를 정확히 산출한다."""
    if daily.empty:
        return 0
    try:
        raw_monthly = to_monthly(daily)
        valid_monthly = raw_monthly.dropna(subset=["close"])
        completed = _drop_incomplete_current_month(valid_monthly, pd.Timestamp(reference_date))
        return len(completed)
    except Exception:
        return 0


def populate_single_ticker(
    security: UniverseSecurity,
    provider: MarketDataProvider,
    cache: ParquetCache,
    reference_market_date: str | pd.Timestamp,
    backfill_years: int = DEFAULT_BACKFILL_YEARS,
    overlap_days: int = DEFAULT_OVERLAP_DAYS,
    max_retries: int = DEFAULT_MAX_RETRIES,
    retry_backoff: float = DEFAULT_RETRY_BACKOFF,
    dry_run: bool = False,
) -> CachePopulationRecord:
    """단일 종목에 대해 캐시 상태를 확인하고 필요한 일봉 데이터를 증분 수집/갱신한다.

    Fail-Closed & Exception Isolation:
    - 오류 발생 시 기존 캐시를 보존하고 FAILED 상태와 에러 provenance를 반환한다.
    """
    clean_ticker = str(security.ticker).strip().zfill(6)
    clean_name = str(security.name).strip()
    market = security.market
    ref_str = pd.Timestamp(reference_market_date).strftime("%Y-%m-%d")
    ref_ts = pd.Timestamp(ref_str)
    asset_type = classify_asset_type(clean_ticker, clean_name)

    # 1. 대상 적격성 확인 (AssetType.COMMON)
    if asset_type != AssetType.COMMON:
        return CachePopulationRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            reference_market_date=ref_str,
            status=CachePopulationStatus.EXCLUDED_NOT_COMMON,
            error_message=f"보통주가 아님 (asset_type={asset_type.value})",
        )

    # 2. 기존 캐시 검사
    cached: pd.DataFrame | None = None
    cache_existed_before = False
    cache_first_before: str | None = None
    cache_last_before: str | None = None
    cached_months_before = 0

    try:
        cached = cache.load(clean_ticker)
        if cached is not None and not cached.empty:
            validate_ohlcv(cached)
            cache_existed_before = True
            cache_first_before = cached.index.min().strftime("%Y-%m-%d")
            cache_last_before = cached.index.max().strftime("%Y-%m-%d")
            cached_months_before = _count_completed_months(cached, ref_ts)
    except Exception as exc:
        logger.warning("기존 캐시 읽기/검증 실패 (%s): %s", clean_ticker, exc)
        cached = None
        cache_existed_before = False

    # 3. 최신 상태 여부 (Freshness & Sufficient History) 확인 -> SKIPPED_FRESH
    # 캐시 마지막 날짜가 reference date와 같고, 42개월 이상 완성 월봉이 이미 있다면 fetch 생략 가능
    is_fresh = False
    if cached is not None and cache_last_before is not None:
        if cache_last_before == ref_str and cached_months_before >= 42:
            is_fresh = True

    if is_fresh:
        return CachePopulationRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            reference_market_date=ref_str,
            status=CachePopulationStatus.SKIPPED_FRESH,
            cache_existed_before=True,
            cache_first_date_before=cache_first_before,
            cache_last_date_before=cache_last_before,
            cache_first_date_after=cache_first_before,
            cache_last_date_after=cache_last_before,
            total_row_count_after=len(cached) if cached is not None else 0,
            completed_month_count_after=cached_months_before,
        )

    # 4. Fetch 구간 산정
    target_start_ts = ref_ts - pd.DateOffset(years=backfill_years)
    target_start_str = target_start_ts.strftime("%Y-%m-%d")

    if cached is None or cached.empty or cached_months_before < 42:
        # 캐시가 없거나 과거 히스토리가 부족한 경우: 전체 구간 fetch
        fetch_start_str = target_start_str
        fetch_end_str = ref_str
    else:
        # 캐시가 있고 과거 히스토리가 충분한 경우: 마지막 날짜부터 overlap 증분 fetch
        overlap_ts = cached.index.max() - pd.Timedelta(days=overlap_days)
        fetch_start_str = max(overlap_ts, target_start_ts).strftime("%Y-%m-%d")
        fetch_end_str = ref_str

    if dry_run:
        return CachePopulationRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            reference_market_date=ref_str,
            status=CachePopulationStatus.CREATED if not cache_existed_before else CachePopulationStatus.UPDATED,
            cache_existed_before=cache_existed_before,
            cache_first_date_before=cache_first_before,
            cache_last_date_before=cache_last_before,
            fetch_start_date=fetch_start_str,
            fetch_end_date=fetch_end_str,
        )

    # 5. Network Fetch with Retry
    fetched_df: pd.DataFrame | None = None
    last_error: Exception | None = None
    retries_used = 0

    for attempt in range(max_retries):
        try:
            fetched_df = provider.load_daily(clean_ticker, fetch_start_str, fetch_end_str)
            if fetched_df is None or fetched_df.empty:
                raise ValueError("Provider가 빈 일봉 데이터를 반환했습니다 (EMPTY_RESPONSE).")
            validate_ohlcv(fetched_df)
            break
        except Exception as exc:
            last_error = exc
            retries_used = attempt + 1
            if attempt < max_retries - 1 and retry_backoff > 0:
                time.sleep(retry_backoff * (2**attempt))

    if fetched_df is None or fetched_df.empty:
        err_type = type(last_error).__name__ if last_error else "EmptyResponseError"
        err_msg = str(last_error) if last_error else "빈 일봉 데이터"
        return CachePopulationRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            reference_market_date=ref_str,
            status=CachePopulationStatus.FAILED,
            cache_existed_before=cache_existed_before,
            cache_first_date_before=cache_first_before,
            cache_last_date_before=cache_last_before,
            fetch_start_date=fetch_start_str,
            fetch_end_date=fetch_end_str,
            retry_count=retries_used,
            error_type=err_type,
            error_message=err_msg,
            cache_first_date_after=cache_first_before,
            cache_last_date_after=cache_last_before,
            total_row_count_after=len(cached) if cached is not None else 0,
            completed_month_count_after=cached_months_before,
        )

    # 6. Future Date Protection
    future_rows = fetched_df.loc[fetched_df.index > ref_ts]
    if not future_rows.empty:
        return CachePopulationRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            reference_market_date=ref_str,
            status=CachePopulationStatus.FAILED,
            cache_existed_before=cache_existed_before,
            cache_first_date_before=cache_first_before,
            cache_last_date_before=cache_last_before,
            fetch_start_date=fetch_start_str,
            fetch_end_date=fetch_end_str,
            fetched_row_count=len(fetched_df),
            retry_count=retries_used,
            error_type="FutureDateError",
            error_message=f"reference_date({ref_str})보다 미래 데이터 발견 ({future_rows.index.max().strftime('%Y-%m-%d')})",
            cache_first_date_after=cache_first_before,
            cache_last_date_after=cache_last_before,
            total_row_count_after=len(cached) if cached is not None else 0,
            completed_month_count_after=cached_months_before,
        )

    # 7. Merge & Safe Atomic Save
    try:
        if cached is None or cached.empty:
            merged = fetched_df
        else:
            combined = pd.concat([cached, fetched_df])
            # duplicate date 제거 (신규 fetched 데이터 우선)
            merged = combined[~combined.index.duplicated(keep="last")]

        # Date index 정렬 보장
        merged = merged.sort_index()
        validate_ohlcv(merged)

        # Cache 파일 저장 (ParquetCache)
        cache.save(clean_ticker, merged)

        after_first = merged.index.min().strftime("%Y-%m-%d")
        after_last = merged.index.max().strftime("%Y-%m-%d")
        after_months = _count_completed_months(merged, ref_ts)

        final_status = (
            CachePopulationStatus.CREATED
            if not cache_existed_before
            else CachePopulationStatus.UPDATED
        )

        return CachePopulationRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            reference_market_date=ref_str,
            status=final_status,
            cache_existed_before=cache_existed_before,
            cache_first_date_before=cache_first_before,
            cache_last_date_before=cache_last_before,
            fetch_start_date=fetch_start_str,
            fetch_end_date=fetch_end_str,
            fetched_row_count=len(fetched_df),
            cache_first_date_after=after_first,
            cache_last_date_after=after_last,
            total_row_count_after=len(merged),
            completed_month_count_after=after_months,
            retry_count=retries_used,
        )
    except Exception as exc:
        logger.error("캐시 병합/저장 실패 (%s): %s", clean_ticker, exc)
        return CachePopulationRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            reference_market_date=ref_str,
            status=CachePopulationStatus.FAILED,
            cache_existed_before=cache_existed_before,
            cache_first_date_before=cache_first_before,
            cache_last_date_before=cache_last_before,
            fetch_start_date=fetch_start_str,
            fetch_end_date=fetch_end_str,
            fetched_row_count=len(fetched_df),
            retry_count=retries_used,
            error_type=type(exc).__name__,
            error_message=str(exc),
            cache_first_date_after=cache_first_before,
            cache_last_date_after=cache_last_before,
            total_row_count_after=len(cached) if cached is not None else 0,
            completed_month_count_after=cached_months_before,
        )


def populate_common_stock_cache(
    cache: ParquetCache | None = None,
    provider: MarketDataProvider | None = None,
    reference_market_date: str | pd.Timestamp | None = None,
    universe_securities: list[UniverseSecurity] | None = None,
    limit: int | None = None,
    tickers: list[str] | None = None,
    market: MarketType | None = None,
    delay_seconds: float = 0.0,
    dry_run: bool = False,
    progress_callback: Callable[[CachePopulationRecord, int, int], None] | None = None,
) -> CachePopulationSummary:
    """공인 KRX COMMON 주식 유니버스 전체 또는 지정 종목에 대해 캐시 수집/갱신을 수행한다."""
    if cache is None:
        cache = ParquetCache()
    if provider is None:
        provider = PyKrxDataProvider(adjusted=True)

    # 1. Reference Market Date 확인
    if reference_market_date is None:
        ref_date_str = get_latest_market_trading_date()
    else:
        ref_date_str = pd.Timestamp(reference_market_date).strftime("%Y-%m-%d")

    # 2. Official Universe 로딩
    if universe_securities is None:
        universe_securities = load_krx_equity_universe(as_of=ref_date_str)

    official_universe_total = len(universe_securities)

    # 3. COMMON 주식 및 필터 적용
    common_targets: list[UniverseSecurity] = []
    for s in universe_securities:
        atype = classify_asset_type(s.ticker, s.name)
        if atype != AssetType.COMMON:
            continue
        if market is not None and s.market != market:
            continue
        if tickers is not None:
            clean_tickers = [t.strip().zfill(6) for t in tickers]
            if s.ticker not in clean_tickers:
                continue
        common_targets.append(s)

    official_common_total = len([s for s in universe_securities if classify_asset_type(s.ticker, s.name) == AssetType.COMMON])

    if limit is not None and limit > 0:
        common_targets = common_targets[:limit]

    population_target_count = len(common_targets)

    # 4. Before 상태 측정
    local_cached_tickers = set(cache.list_cached_tickers()) if hasattr(cache, "list_cached_tickers") else set()
    official_ticker_set = {s.ticker for s in universe_securities}
    orphan_cache_count = len([t for t in local_cached_tickers if t not in official_ticker_set])

    cache_present_before = 0
    cache_missing_before = 0
    fresh_before = 0
    stale_before = 0

    for s in common_targets:
        if s.ticker in local_cached_tickers:
            cache_present_before += 1
            # freshness 검사
            try:
                c_df = cache.load(s.ticker)
                if c_df is not None and not c_df.empty:
                    if c_df.index.max().strftime("%Y-%m-%d") == ref_date_str:
                        fresh_before += 1
                    else:
                        stale_before += 1
                else:
                    stale_before += 1
            except Exception:
                stale_before += 1
        else:
            cache_missing_before += 1

    # 5. Population Loop 실행
    records: list[CachePopulationRecord] = []
    failed_records: list[CachePopulationRecord] = []
    exceptions_list: list[str] = []

    created_cnt = 0
    updated_cnt = 0
    skipped_fresh_cnt = 0
    failed_cnt = 0

    for idx, sec in enumerate(common_targets, start=1):
        record = populate_single_ticker(
            security=sec,
            provider=provider,
            cache=cache,
            reference_market_date=ref_date_str,
            dry_run=dry_run,
        )
        records.append(record)

        if record.status == CachePopulationStatus.CREATED:
            created_cnt += 1
        elif record.status == CachePopulationStatus.UPDATED:
            updated_cnt += 1
        elif record.status == CachePopulationStatus.SKIPPED_FRESH:
            skipped_fresh_cnt += 1
        elif record.status == CachePopulationStatus.FAILED:
            failed_cnt += 1
            failed_records.append(record)
            if record.error_message:
                exceptions_list.append(f"{record.ticker}({record.name}): {record.error_type} - {record.error_message}")

        if progress_callback is not None:
            progress_callback(record, idx, population_target_count)

        if delay_seconds > 0 and not dry_run and record.status in (CachePopulationStatus.CREATED, CachePopulationStatus.UPDATED):
            time.sleep(delay_seconds)

    # 6. After 상태 측정
    cache_present_after = 0
    fresh_after = 0
    stale_after = 0
    min_history_ready_after = 0
    history_42m_ready_after = 0
    history_48m_ready_after = 0

    for rec in records:
        if rec.status in (CachePopulationStatus.CREATED, CachePopulationStatus.UPDATED, CachePopulationStatus.SKIPPED_FRESH):
            cache_present_after += 1
            if rec.cache_last_date_after == ref_date_str:
                fresh_after += 1
            else:
                stale_after += 1

            if rec.completed_month_count_after >= 36:
                min_history_ready_after += 1
            if rec.completed_month_count_after >= 42:
                history_42m_ready_after += 1
            if rec.completed_month_count_after >= 48:
                history_48m_ready_after += 1
        elif rec.cache_existed_before:
            cache_present_after += 1
            stale_after += 1
            if rec.completed_month_count_after >= 36:
                min_history_ready_after += 1
            if rec.completed_month_count_after >= 42:
                history_42m_ready_after += 1
            if rec.completed_month_count_after >= 48:
                history_48m_ready_after += 1

    return CachePopulationSummary(
        reference_market_date=ref_date_str,
        official_universe_total=official_universe_total,
        official_common_total=official_common_total,
        population_target_count=population_target_count,
        cache_present_before=cache_present_before,
        cache_missing_before=cache_missing_before,
        fresh_before=fresh_before,
        stale_before=stale_before,
        created_count=created_cnt,
        updated_count=updated_cnt,
        skipped_fresh_count=skipped_fresh_cnt,
        failed_count=failed_cnt,
        cache_present_after=cache_present_after,
        fresh_after=fresh_after,
        stale_after=stale_after,
        minimum_history_ready_after=min_history_ready_after,
        history_42m_ready_after=history_42m_ready_after,
        history_48m_ready_after=history_48m_ready_after,
        orphan_cache_count=orphan_cache_count,
        records=tuple(records),
        failed_records=tuple(failed_records),
        exceptions=tuple(exceptions_list),
    )
