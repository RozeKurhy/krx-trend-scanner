"""Pattern A Data Quality & Universe Auditor.

개별 종목 및 전체 KRX Universe에 대해 데이터 정합성, 히스토리 충분성, 신선도,
그리고 Feature/Score/Stage/Evaluator 준비도를 감사(Audit)한다.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly
from trend_scanner.data.validator import REQUIRED_COLUMNS, REQUIRED_NON_NULL_COLUMNS
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.universe.asset_classifier import classify_asset_type
from trend_scanner.universe.models import (
    AssetType,
    FreshnessStatus,
    MarketType,
    QualityStatus,
    TickerQualityRecord,
    UniverseQualitySummary,
    UniverseSecurity,
)
from trend_scanner.validation.historical_snapshot import (
    _drop_incomplete_current_month,
    build_historical_snapshot,
)

# Pattern A Feature 및 Stage Classifier가 요구하는 최소 완성 월봉 수 (36 completed monthly bars)
MIN_HISTORY_MONTHS: int = 36


def _is_missing(val: Any) -> bool:
    try:
        return bool(pd.isna(val))
    except (TypeError, ValueError):
        return False


def audit_ticker_quality(
    ticker: str,
    name: str,
    market: MarketType,
    daily: pd.DataFrame | None,
    reference_market_date: str | pd.Timestamp | None = None,
    metadata_source: str = "OFFICIAL_KRX",
    min_history_months: int = MIN_HISTORY_MONTHS,
) -> TickerQualityRecord:
    """단일 종목에 대해 데이터 품질 및 Evaluator 준비도를 감사한다.

    Score 낮음, Stage WEAK, Candidate State BLOCKED 등은 투자 판단 신호이므로
    Universe 제외 사유(Hard exclusion)로 삼지 않는다.
    """
    clean_ticker = str(ticker).strip().zfill(6)
    clean_name = str(name).strip()
    asset_type = classify_asset_type(clean_ticker, clean_name)

    quality_flags: list[str] = []
    exclusion_reasons: list[str] = []

    # 1. Asset Type & Market 정책 점검
    if asset_type == AssetType.UNKNOWN:
        quality_flags.append("UNKNOWN_ASSET_TYPE")
        exclusion_reasons.append("UNKNOWN_ASSET_TYPE")
    elif asset_type != AssetType.COMMON:
        exclusion_reasons.append(f"UNSUPPORTED_ASSET_{asset_type.value}")

    if market == MarketType.KONEX:
        exclusion_reasons.append("EXCLUDED_MARKET_KONEX")
    elif market not in (MarketType.KOSPI, MarketType.KOSDAQ):
        exclusion_reasons.append(f"UNSUPPORTED_MARKET_{market.value}")

    # 2. 캐시 가용성 점검
    cache_present = daily is not None and not daily.empty
    if not cache_present or daily is None:
        quality_flags.append("MISSING_CACHE")
        exclusion_reasons.append("MISSING_CACHE")
        return TickerQualityRecord(
            ticker=clean_ticker,
            name=clean_name,
            market=market,
            asset_type=asset_type,
            metadata_source=metadata_source,
            data_available=False,
            cache_present=False,
            first_date=None,
            last_date=None,
            rows=0,
            history_days=0,
            history_months=0,
            required_history_sufficient=False,
            freshness_status=FreshnessStatus.UNKNOWN,
            staleness_trading_days=-1,
            raw_data_ready=False,
            feature_ready=False,
            score_ready=False,
            stage_ready=False,
            evaluator_ready=False,
            included_in_pattern_a_universe=False,
            quality_status=QualityStatus.MISSING_CACHE,
            quality_flags=tuple(quality_flags),
            exclusion_reasons=tuple(exclusion_reasons),
        )

    # 3. 날짜 구조 및 정합성 검사
    first_date_str = str(daily.index.min().strftime("%Y-%m-%d")) if len(daily) else None
    last_date_ts = daily.index.max() if len(daily) else None
    last_date_str = str(last_date_ts.strftime("%Y-%m-%d")) if last_date_ts is not None else None

    # 중복 날짜
    if daily.index.duplicated().any():
        quality_flags.append("DUPLICATE_DATE")
        exclusion_reasons.append("DUPLICATE_DATE")

    # 날짜 정렬
    if not daily.index.is_monotonic_increasing:
        quality_flags.append("UNSORTED_DATE")
        exclusion_reasons.append("UNSORTED_DATE")

    # 미래 날짜 (Authoritative Reference Market Date 초과 여부)
    ref_ts = pd.Timestamp(reference_market_date) if reference_market_date else None
    if ref_ts is not None and (daily.index > ref_ts).any():
        quality_flags.append("FUTURE_DATE")
        exclusion_reasons.append("FUTURE_DATE")

    # 4. 컬럼 및 값 결측치 검사
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in daily.columns]
    if missing_cols:
        quality_flags.append("MISSING_COLUMNS")
        exclusion_reasons.append("MISSING_COLUMNS")

    # OHLC 가격 관계 및 음수 검사
    invalid_ohlc = False
    if set(["open", "high", "low", "close"]).issubset(daily.columns):
        if (daily[["open", "high", "low", "close"]] <= 0).any().any():
            invalid_ohlc = True
        if (
            (daily["high"] < daily["low"]).any()
            or (daily["high"] < daily["open"]).any()
            or (daily["high"] < daily["close"]).any()
        ):
            invalid_ohlc = True
        if (daily["low"] > daily["open"]).any() or (daily["low"] > daily["close"]).any():
            invalid_ohlc = True

    if "volume" in daily.columns and (daily["volume"] < 0).any():
        invalid_ohlc = True

    if invalid_ohlc:
        quality_flags.append("INVALID_OHLC")
        exclusion_reasons.append("INVALID_OHLC")

    # 결측치(NaN) 확인
    null_cols = [
        c for c in REQUIRED_NON_NULL_COLUMNS if c in daily.columns and daily[c].isna().any()
    ]
    if null_cols:
        quality_flags.append("MISSING_VALUES")
        exclusion_reasons.append("MISSING_VALUES")

    # 극단 일간 수익률 진단 (35% 초과 jump 등 - Diagnostic only, Hard exclusion 아님)
    if "close" in daily.columns and len(daily) > 1:
        daily_pct = daily["close"].pct_change().dropna()
        if (daily_pct.abs() > 0.35).any():
            quality_flags.append("DIAGNOSTIC_EXTREME_DAILY_RETURN")

    # 0 거래량 일수 진단
    if "volume" in daily.columns and len(daily) > 0:
        zero_vol_ratio = (daily["volume"] == 0).mean()
        if zero_vol_ratio > 0.10:
            quality_flags.append("DIAGNOSTIC_HIGH_ZERO_VOLUME_DAYS")

    # 5. 완성 월봉(Completed Monthly Bars) 개수 산출
    monthly_completed_df = pd.DataFrame()
    if not daily.empty and not missing_cols:
        try:
            raw_monthly = to_monthly(daily)
            if last_date_ts is not None:
                monthly_completed_df = _drop_incomplete_current_month(raw_monthly, last_date_ts)
            else:
                monthly_completed_df = raw_monthly
        except Exception:
            monthly_completed_df = pd.DataFrame()

    history_days = len(daily)
    history_months = len(monthly_completed_df)
    required_history_sufficient = history_months >= min_history_months

    if not required_history_sufficient and not missing_cols:
        quality_flags.append("INSUFFICIENT_HISTORY")
        exclusion_reasons.append("INSUFFICIENT_HISTORY")

    # 6. 절대 시장 신선도 (Absolute Market Freshness) 계산
    staleness_days = 0
    freshness = FreshnessStatus.FRESH
    if ref_ts is not None and last_date_ts is not None:
        # 거래일 근사 지연 계산 (business days)
        staleness_days = max(0, len(pd.bdate_range(last_date_ts, ref_ts)) - 1)
        if staleness_days <= 1:
            freshness = FreshnessStatus.FRESH
        elif staleness_days <= 5:
            freshness = FreshnessStatus.STALE
            quality_flags.append("STALE_DATA")
        else:
            freshness = FreshnessStatus.VERY_STALE
            quality_flags.append("VERY_STALE_DATA")
            exclusion_reasons.append("VERY_STALE_DATA")

    # 7. 준비도(Readiness) 계층별 평가 (UNSORTED_DATE 시 raw_data_ready = False)
    raw_data_ready = (
        len(daily) > 0
        and "MISSING_COLUMNS" not in quality_flags
        and "INVALID_OHLC" not in quality_flags
        and "DUPLICATE_DATE" not in quality_flags
        and "UNSORTED_DATE" not in quality_flags
        and "FUTURE_DATE" not in quality_flags
        and "MISSING_VALUES" not in quality_flags
    )

    feature_ready = False
    score_ready = False
    stage_ready = False
    evaluator_ready = False
    error_type = None
    error_message = None

    if raw_data_ready and required_history_sufficient:
        try:
            snapshot = build_historical_snapshot(
                ticker=clean_ticker,
                name=clean_name,
                daily=daily,
                snapshot_date=last_date_str,
                include_incomplete_periods=False,
            )

            # Feature Readiness: required anchors(range_36m, ma24_slope) 확인
            if (
                snapshot.features is not None
                and not _is_missing(snapshot.features.range_36m)
                and not _is_missing(snapshot.features.ma24_slope)
            ):
                feature_ready = True

            # Score Readiness
            score_res = score_pattern_a(snapshot.features)
            if score_res.pattern_a_score is not None:
                score_ready = True

            # Stage Readiness (공식 stage_result.stage 사용)
            stage_res = classify_pattern_a_stage(snapshot)
            if stage_res.stage is not None:
                stage_ready = True

            # Evaluator Readiness
            eval_res = evaluate_pattern_a(snapshot)
            if eval_res.score is not None and eval_res.lifecycle_stage is not None:
                evaluator_ready = True

        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
            quality_flags.append(f"EXCEPTION_{error_type}")
            exclusion_reasons.append("EVALUATOR_EXCEPTION")

    if not feature_ready and raw_data_ready and required_history_sufficient:
        quality_flags.append("FEATURE_NOT_READY")
        exclusion_reasons.append("FEATURE_NOT_READY")

    # 8. 최종 Quality Status 및 Universe Inclusion 결정
    included_in_universe = len(exclusion_reasons) == 0 and evaluator_ready

    if included_in_universe:
        final_quality_status = QualityStatus.OK
    elif "MISSING_CACHE" in exclusion_reasons:
        final_quality_status = QualityStatus.MISSING_CACHE
    elif "INSUFFICIENT_HISTORY" in exclusion_reasons:
        final_quality_status = QualityStatus.INSUFFICIENT_HISTORY
    elif "UNSUPPORTED_ASSET" in str(exclusion_reasons) or "UNKNOWN_ASSET_TYPE" in exclusion_reasons:
        final_quality_status = QualityStatus.UNSUPPORTED_ASSET
    elif "MISSING_COLUMNS" in exclusion_reasons:
        final_quality_status = QualityStatus.MISSING_COLUMNS
    elif "INVALID_OHLC" in exclusion_reasons:
        final_quality_status = QualityStatus.INVALID_OHLC
    elif "DUPLICATE_DATE" in exclusion_reasons:
        final_quality_status = QualityStatus.DUPLICATE_DATE
    elif "UNSORTED_DATE" in exclusion_reasons:
        final_quality_status = QualityStatus.UNSORTED_DATE
    elif "FUTURE_DATE" in exclusion_reasons:
        final_quality_status = QualityStatus.FUTURE_DATE
    elif "VERY_STALE_DATA" in exclusion_reasons:
        final_quality_status = QualityStatus.STALE_DATA
    elif "FEATURE_NOT_READY" in exclusion_reasons:
        final_quality_status = QualityStatus.FEATURE_NOT_READY
    elif error_type is not None:
        final_quality_status = QualityStatus.UNKNOWN_ERROR
    else:
        final_quality_status = QualityStatus.EVALUATOR_NOT_READY

    return TickerQualityRecord(
        ticker=clean_ticker,
        name=clean_name,
        market=market,
        asset_type=asset_type,
        metadata_source=metadata_source,
        data_available=True,
        cache_present=True,
        first_date=first_date_str,
        last_date=last_date_str,
        rows=len(daily),
        history_days=history_days,
        history_months=history_months,
        required_history_sufficient=required_history_sufficient,
        freshness_status=freshness,
        staleness_trading_days=staleness_days,
        raw_data_ready=raw_data_ready,
        feature_ready=feature_ready,
        score_ready=score_ready,
        stage_ready=stage_ready,
        evaluator_ready=evaluator_ready,
        included_in_pattern_a_universe=included_in_universe,
        quality_status=final_quality_status,
        quality_flags=tuple(quality_flags),
        exclusion_reasons=tuple(exclusion_reasons),
        error_type=error_type,
        error_message=error_message,
    )


def audit_universe_quality(
    ticker_metadata: list[UniverseSecurity] | list[dict[str, Any]],
    cache_dir: Path | str,
    reference_market_date: str | None = None,
    min_history_months: int = MIN_HISTORY_MONTHS,
) -> tuple[list[TickerQualityRecord], UniverseQualitySummary]:
    """전체 종목 메타데이터와 로컬 캐시를 바탕으로 Universe Data Quality 감사를 수행한다."""
    cache_path = Path(cache_dir)
    cache = ParquetCache(base_dir=cache_path)

    # 로컬 캐시 파일 전체 수 및 고유 티커 목록 파악
    local_cache_files = list(cache_path.glob("*.parquet")) if cache_path.exists() else []
    local_cache_tickers = set(p.stem for p in local_cache_files)
    local_cache_file_count = len(local_cache_files)

    # Reference Market Date 결정
    if reference_market_date is not None:
        official_ref_date = str(reference_market_date).strip()
        ref_source = "OFFICIAL_KRX"
    else:
        # Fallback (Cache Relative)
        all_last_dates: list[pd.Timestamp] = []
        for item in ticker_metadata:
            t = item.ticker if isinstance(item, UniverseSecurity) else item["ticker"]
            d = cache.load(t)
            if d is not None and not d.empty and not d.index.empty:
                all_last_dates.append(d.index.max())
        official_ref_date = (
            str(max(all_last_dates).strftime("%Y-%m-%d")) if all_last_dates else "2024-03-29"
        )
        ref_source = "CACHE_RELATIVE"

    records: list[TickerQualityRecord] = []
    audited_official_tickers: set[str] = set()

    for item in ticker_metadata:
        if isinstance(item, UniverseSecurity):
            ticker = item.ticker
            name = item.name
            market = item.market
            meta_source = item.metadata_source
        else:
            ticker = item["ticker"]
            name = item.get("name", "")
            market_str = item.get("market", "UNKNOWN").upper()
            meta_source = item.get("metadata_source", "OFFICIAL_KRX")
            try:
                market = MarketType(market_str)
            except ValueError:
                market = MarketType.UNKNOWN

        audited_official_tickers.add(ticker)

        try:
            daily = cache.load(ticker)
            record = audit_ticker_quality(
                ticker=ticker,
                name=name,
                market=market,
                daily=daily,
                reference_market_date=official_ref_date,
                metadata_source=meta_source,
                min_history_months=min_history_months,
            )
        except Exception as exc:
            record = TickerQualityRecord(
                ticker=ticker,
                name=name,
                market=market,
                asset_type=classify_asset_type(ticker, name),
                metadata_source=meta_source,
                data_available=False,
                cache_present=False,
                first_date=None,
                last_date=None,
                rows=0,
                history_days=0,
                history_months=0,
                required_history_sufficient=False,
                freshness_status=FreshnessStatus.UNKNOWN,
                staleness_trading_days=-1,
                raw_data_ready=False,
                feature_ready=False,
                score_ready=False,
                stage_ready=False,
                evaluator_ready=False,
                included_in_pattern_a_universe=False,
                quality_status=QualityStatus.UNKNOWN_ERROR,
                quality_flags=(f"EXCEPTION_{type(exc).__name__}",),
                exclusion_reasons=("UNKNOWN_ERROR",),
                error_type=type(exc).__name__,
                error_message=str(exc),
            )
        records.append(record)

    # Deterministic 정렬 (market -> ticker)
    records.sort(key=lambda r: (r.market.value, r.ticker))

    # 종합 집계 통계 산출
    total_tickers = len(records)
    kospi_count = sum(1 for r in records if r.market == MarketType.KOSPI)
    kosdaq_count = sum(1 for r in records if r.market == MarketType.KOSDAQ)
    konex_count = sum(1 for r in records if r.market == MarketType.KONEX)

    cache_present_count = sum(1 for r in records if r.cache_present)
    cache_missing_count = total_tickers - cache_present_count
    cache_coverage_pct = (
        (cache_present_count / total_tickers * 100.0) if total_tickers > 0 else 0.0
    )

    orphan_cache_count = len(local_cache_tickers - audited_official_tickers)

    common_stock_count = sum(1 for r in records if r.asset_type == AssetType.COMMON)
    preferred_stock_count = sum(1 for r in records if r.asset_type == AssetType.PREFERRED)
    spac_count = sum(1 for r in records if r.asset_type == AssetType.SPAC)
    reit_count = sum(1 for r in records if r.asset_type == AssetType.REIT)
    etf_etn_count = sum(1 for r in records if r.asset_type in (AssetType.ETF, AssetType.ETN))
    unknown_asset_count = sum(1 for r in records if r.asset_type == AssetType.UNKNOWN)

    raw_data_ready_count = sum(1 for r in records if r.raw_data_ready)
    feature_ready_count = sum(1 for r in records if r.feature_ready)
    score_ready_count = sum(1 for r in records if r.score_ready)
    stage_ready_count = sum(1 for r in records if r.stage_ready)
    evaluator_ready_count = sum(1 for r in records if r.evaluator_ready)

    included_tickers = sum(1 for r in records if r.included_in_pattern_a_universe)
    excluded_tickers = total_tickers - included_tickers

    fresh_count = sum(1 for r in records if r.freshness_status == FreshnessStatus.FRESH)
    stale_count = sum(1 for r in records if r.freshness_status == FreshnessStatus.STALE)
    very_stale_count = sum(1 for r in records if r.freshness_status == FreshnessStatus.VERY_STALE)

    insufficient_history_count = sum(
        1 for r in records if r.data_available and not r.required_history_sufficient
    )
    missing_columns_count = sum(1 for r in records if "MISSING_COLUMNS" in r.quality_flags)
    duplicate_date_count = sum(1 for r in records if "DUPLICATE_DATE" in r.quality_flags)
    unsorted_date_count = sum(1 for r in records if "UNSORTED_DATE" in r.quality_flags)
    invalid_ohlc_count = sum(1 for r in records if "INVALID_OHLC" in r.quality_flags)
    future_date_count = sum(1 for r in records if "FUTURE_DATE" in r.quality_flags)
    extreme_return_count = sum(
        1 for r in records if "DIAGNOSTIC_EXTREME_DAILY_RETURN" in r.quality_flags
    )
    exception_count = sum(1 for r in records if r.error_type is not None)

    # Exclusion reason breakdown
    exclusion_reason_counts: dict[str, int] = {}
    for r in records:
        for reason in r.exclusion_reasons:
            exclusion_reason_counts[reason] = exclusion_reason_counts.get(reason, 0) + 1

    # History distribution
    history_distribution = {
        "< 12m": sum(1 for r in records if r.data_available and r.history_months < 12),
        "12 to 24m": sum(1 for r in records if r.data_available and 12 <= r.history_months < 24),
        "24 to 36m": sum(1 for r in records if r.data_available and 24 <= r.history_months < 36),
        "36 to 48m": sum(1 for r in records if r.data_available and 36 <= r.history_months < 48),
        "48m+": sum(1 for r in records if r.data_available and r.history_months >= 48),
    }

    # Freshness distribution
    freshness_distribution = {
        "0 to 1 days (FRESH)": fresh_count,
        "2 to 5 days (STALE)": stale_count,
        "6+ days (VERY_STALE)": very_stale_count,
    }

    summary = UniverseQualitySummary(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        reference_market_date=official_ref_date,
        reference_date_source=ref_source,
        min_history_months=min_history_months,
        official_universe_count=total_tickers,
        official_kospi_count=kospi_count,
        official_kosdaq_count=kosdaq_count,
        official_konex_count=konex_count,
        local_cache_file_count=local_cache_file_count,
        official_universe_cache_present_count=cache_present_count,
        orphan_cache_count=orphan_cache_count,
        cache_present_count=cache_present_count,
        cache_missing_count=cache_missing_count,
        cache_coverage_pct=cache_coverage_pct,
        common_stock_count=common_stock_count,
        preferred_stock_count=preferred_stock_count,
        spac_count=spac_count,
        reit_count=reit_count,
        etf_etn_count=etf_etn_count,
        unknown_asset_count=unknown_asset_count,
        raw_data_ready_count=raw_data_ready_count,
        feature_ready_count=feature_ready_count,
        score_ready_count=score_ready_count,
        stage_ready_count=stage_ready_count,
        evaluator_ready_count=evaluator_ready_count,
        included_tickers=included_tickers,
        excluded_tickers=excluded_tickers,
        fresh_count=fresh_count,
        stale_count=stale_count,
        very_stale_count=very_stale_count,
        insufficient_history_count=insufficient_history_count,
        missing_columns_count=missing_columns_count,
        duplicate_date_count=duplicate_date_count,
        unsorted_date_count=unsorted_date_count,
        invalid_ohlc_count=invalid_ohlc_count,
        future_date_count=future_date_count,
        extreme_return_count=extreme_return_count,
        exception_count=exception_count,
        exclusion_reason_counts=exclusion_reason_counts,
        history_distribution=history_distribution,
        freshness_distribution=freshness_distribution,
    )

    return records, summary
