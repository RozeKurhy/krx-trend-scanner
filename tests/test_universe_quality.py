"""Pattern A Universe & Data Quality Audit 유닛 및 통합 테스트.

검증 항목:
1. AssetType classifier (보통주, 우선주, SPAC, REIT, ETF, ETN, UNKNOWN)
2. Official KOSPI/KOSDAQ metadata preserved without defaults (KOSPI는 KOSPI, KOSDAQ은 KOSDAQ)
3. Missing cache detected from official universe (MISSING_CACHE 식별 및 집계)
4. Future date corrupted ticker cannot move reference market date (미래 날짜 오염 방지)
5. 35 vs 36 completed months requirement (35개 완성 월봉은 미달, 36개 완성 월봉은 충족)
6. 35 completed + 1 incomplete month is insufficient (진행 중인 미완성 월봉으로 36개월 오판 방지)
7. Incomplete current month handling (스냅샷 생성 시 미완성 월봉 안전 제외)
8. Unsorted date forces raw and downstream readiness false (UNSORTED_DATE 시 준비도 계층 일치)
9. Ticker name lookup failure raises MarketDataError (종목명 lookup 실패 시 fail closed)
10. WEAK / PROGRESSED Stage stocks included if data valid (투자 신호와 데이터 품질 분리)
11. Deterministic semantic records (결과 정렬 및 semantic 필드 100% 결정론적 일치)
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.resampler import to_monthly
from trend_scanner.universe import (
    AssetType,
    FreshnessStatus,
    MarketType,
    QualityStatus,
    UniverseSecurity,
    audit_ticker_quality,
    audit_universe_quality,
    classify_asset_type,
    load_krx_equity_universe,
)
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _create_mock_daily(
    months: int = 40,
    start_date: str = "2020-01-01",
    has_ohlc_violation: bool = False,
    has_duplicate_date: bool = False,
    has_unsorted_date: bool = False,
    has_future_date: bool = False,
    missing_columns: list[str] | None = None,
) -> pd.DataFrame:
    """합성 테스트용 일봉 데이터 생성."""
    dates = pd.date_range(start=start_date, periods=months * 21, freq="B")
    n = len(dates)

    df = pd.DataFrame(
        {
            "open": [10000.0 + i * 10 for i in range(n)],
            "high": [10500.0 + i * 10 for i in range(n)],
            "low": [9500.0 + i * 10 for i in range(n)],
            "close": [10200.0 + i * 10 for i in range(n)],
            "volume": [100000 for _ in range(n)],
            "trading_value": [1000000000.0 for _ in range(n)],
        },
        index=dates,
    )

    if has_ohlc_violation and n > 5:
        # high < low 위반
        df.iloc[5, df.columns.get_loc("high")] = df.iloc[5, df.columns.get_loc("low")] - 100

    if has_duplicate_date and n > 10:
        # 인덱스 중복 삽입
        new_index = list(df.index)
        new_index[10] = new_index[9]
        df.index = pd.DatetimeIndex(new_index)

    if has_unsorted_date and n > 10:
        # 인덱스 순서 뒤섞기 (비정렬)
        new_index = list(df.index)
        new_index[5], new_index[10] = new_index[10], new_index[5]
        df.index = pd.DatetimeIndex(new_index)

    if has_future_date and n > 0:
        # 2099년 미래 날짜 삽입
        new_index = list(df.index)
        new_index[-1] = pd.Timestamp("2099-12-31")
        df.index = pd.DatetimeIndex(new_index)

    if missing_columns:
        for col in missing_columns:
            if col in df.columns:
                df = df.drop(columns=[col])

    return df


def test_asset_type_classifier():
    # 1. 보통주 (6자리 일반 종목)
    assert classify_asset_type("005930", "삼성전자") == AssetType.COMMON
    assert classify_asset_type("000660", "SK하이닉스") == AssetType.COMMON

    # 2. 우선주 (우선주 suffix 또는 접미 코드)
    assert classify_asset_type("005935", "삼성전자우") == AssetType.PREFERRED
    assert classify_asset_type("005387", "현대차2우B") == AssetType.PREFERRED
    assert classify_asset_type("00088K", "한화3우B") == AssetType.PREFERRED

    # 3. SPAC
    assert classify_asset_type("456780", "삼성스팩8호") == AssetType.SPAC
    assert classify_asset_type("412340", "하나29호스팩") == AssetType.SPAC

    # 4. REIT
    assert classify_asset_type("293940", "신한알파리츠") == AssetType.REIT
    assert classify_asset_type("395400", "SK리츠") == AssetType.REIT
    assert classify_asset_type("350520", "이지스밸류리츠") == AssetType.REIT

    # 5. ETF
    assert classify_asset_type("069500", "KODEX 200") == AssetType.ETF
    assert classify_asset_type("102110", "TIGER 200") == AssetType.ETF
    assert classify_asset_type("379800", "KODEX 미국나스닥100TR") == AssetType.ETF

    # 6. ETN
    assert classify_asset_type("530063", "삼성 레버리지 WTI원유 선물 ETN") == AssetType.ETN

    # 7. 식별 불가 자산
    assert classify_asset_type("", "") == AssetType.UNKNOWN


def test_official_market_metadata_preserved_without_defaults():
    """KOSPI, KOSDAQ, UNKNOWN 시장 메타데이터가 임의의 default 없이 그대로 보존되는지 검증."""
    securities = [
        UniverseSecurity("005930", "삼성전자", MarketType.KOSPI),
        UniverseSecurity("086520", "에코프로", MarketType.KOSDAQ),
        {"ticker": "999999", "name": "알수없는시장종목", "market": "INVALID_MARKET"},
    ]

    records, summary = audit_universe_quality(
        ticker_metadata=securities,
        cache_dir=_CACHE_DIR,
        reference_market_date="2026-02-27",
    )

    rec_map = {r.ticker: r for r in records}
    assert rec_map["005930"].market == MarketType.KOSPI
    assert rec_map["086520"].market == MarketType.KOSDAQ
    assert rec_map["999999"].market == MarketType.UNKNOWN
    assert summary.official_kospi_count == 1
    assert summary.official_kosdaq_count == 1


def test_missing_cache_detected_from_official_universe():
    """공식 Universe 목록 중 로컬 캐시가 없는 종목이 MISSING_CACHE로 식별되는지 검증."""
    securities = [
        UniverseSecurity("005930", "삼성전자", MarketType.KOSPI),
        UniverseSecurity("999991", "미수집종목A", MarketType.KOSPI),
        UniverseSecurity("999992", "미수집종목B", MarketType.KOSDAQ),
    ]

    records, summary = audit_universe_quality(
        ticker_metadata=securities,
        cache_dir=_CACHE_DIR,
        reference_market_date="2026-02-27",
    )

    assert summary.official_universe_count == 3
    assert summary.cache_present_count >= 1  # 005930 존재
    assert summary.cache_missing_count == 2
    assert summary.cache_coverage_pct < 100.0

    rec_map = {r.ticker: r for r in records}
    assert rec_map["999991"].quality_status == QualityStatus.MISSING_CACHE
    assert "MISSING_CACHE" in rec_map["999991"].exclusion_reasons


def test_future_corrupted_ticker_cannot_move_reference_market_date():
    """2099년 미래 오염 데이터가 있어도 official reference market date가 오염되지 않고 해당 종목만 FUTURE_DATE로 잡힘."""
    corrupted_daily = _create_mock_daily(months=48, has_future_date=True)
    official_ref_date = "2026-02-27"

    record_corrupted = audit_ticker_quality(
        ticker="999999",
        name="미래오염종목",
        market=MarketType.KOSPI,
        daily=corrupted_daily,
        reference_market_date=official_ref_date,
    )

    assert record_corrupted.included_in_pattern_a_universe is False
    assert "FUTURE_DATE" in record_corrupted.quality_flags
    assert "FUTURE_DATE" in record_corrupted.exclusion_reasons

    # 정상 종목 검증
    normal_daily = _create_mock_daily(months=48, start_date="2022-01-01")
    record_normal = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=normal_daily,
        reference_market_date=official_ref_date,
    )
    assert "FUTURE_DATE" not in record_normal.quality_flags


def test_35_vs_36_completed_months_requirement():
    """35개 완성 월봉은 미달, 36개 완성 월봉은 충족함을 HistoricalSnapshot 경로로 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("005930")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=60)

    # 1. 35 completed monthly bars (미달)
    monthly_all = to_monthly(daily)
    monthly_36 = monthly_all.tail(36)
    # 마지막 월봉이 미완성이면 drop되어 35개 completed bars가 남음
    start_36 = monthly_36.index[0] - pd.offsets.MonthBegin(1)
    daily_35_completed = daily.loc[(daily.index >= start_36) & (daily.index <= monthly_36.index[-1])]

    record_35 = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily_35_completed,
        reference_market_date=str(daily_35_completed.index.max().strftime("%Y-%m-%d")),
        min_history_months=36,
    )
    assert record_35.required_history_sufficient is False
    assert record_35.history_months <= 35
    assert "INSUFFICIENT_HISTORY" in record_35.exclusion_reasons
    assert record_35.included_in_pattern_a_universe is False

    # 2. 36 completed monthly bars (충족)
    monthly_37 = monthly_all.tail(37)
    start_37 = monthly_37.index[0] - pd.offsets.MonthBegin(1)
    daily_36_completed = daily.loc[(daily.index >= start_37) & (daily.index <= monthly_37.index[-1])]

    record_36 = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily_36_completed,
        reference_market_date=str(daily_36_completed.index.max().strftime("%Y-%m-%d")),
        min_history_months=36,
    )
    assert record_36.required_history_sufficient is True
    assert record_36.history_months >= 36
    assert record_36.feature_ready is True
    assert record_36.score_ready is True
    assert record_36.stage_ready is True
    assert record_36.evaluator_ready is True
    assert record_36.included_in_pattern_a_universe is True


def test_35_completed_plus_incomplete_month_is_insufficient():
    """35개 완성 월봉 + 진행 중인 1개 미완성 월봉은 36개월 충족으로 오판되지 않음을 검증."""
    # 2023-01-01부터 35개월 완성 월봉(2025-11-30) + 2025-12-15(15일치 미완성 봉)
    daily = _create_mock_daily(months=36, start_date="2023-01-01")
    # 2025년 12월 15일까지만 자름
    daily_incomplete = daily.loc[daily.index <= "2025-12-15"]

    record = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily_incomplete,
        reference_market_date="2025-12-15",
        min_history_months=36,
    )

    # 완성 월봉은 35개이므로 insufficient
    assert record.required_history_sufficient is False
    assert record.history_months < 36
    assert "INSUFFICIENT_HISTORY" in record.exclusion_reasons
    assert record.included_in_pattern_a_universe is False


def test_incomplete_current_month_handling():
    """월 중순 스냅샷(진행 중인 미완성 월봉)이 있을 때 HistoricalSnapshot이 완성 월봉만 취합함을 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("005930")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=60)

    # 2023-11-15 (월 중순 비완성 시점)
    mid_month_date = "2023-11-15"
    snapshot = build_historical_snapshot(
        ticker="005930",
        name="삼성전자",
        daily=daily,
        snapshot_date=mid_month_date,
        include_incomplete_periods=False,
    )

    # 미완성인 11월 봉은 잘리고 10월 말까지의 완성 월봉만 남아야 함
    assert snapshot.monthly.index.max() <= pd.Timestamp("2023-10-31")


def test_unsorted_date_forces_raw_and_downstream_readiness_false():
    """UNSORTED_DATE가 감지되면 raw_data_ready 및 downstream readiness가 모두 False로 차단됨을 검증."""
    unsorted_daily = _create_mock_daily(months=48, has_unsorted_date=True)

    record = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=unsorted_daily,
        reference_market_date="2026-02-27",
    )

    assert "UNSORTED_DATE" in record.quality_flags
    assert "UNSORTED_DATE" in record.exclusion_reasons
    assert record.raw_data_ready is False
    assert record.feature_ready is False
    assert record.score_ready is False
    assert record.stage_ready is False
    assert record.evaluator_ready is False
    assert record.included_in_pattern_a_universe is False
    assert record.quality_status == QualityStatus.UNSORTED_DATE


def test_ticker_name_lookup_failure_raises_market_data_error():
    """공식 종목명 조회 실패 시 ticker 코드로 fail-open되지 않고 MarketDataError를 발생시킴을 검증."""
    with patch("pykrx.stock.get_market_ticker_list", return_value=["005930"]):
        with patch("pykrx.stock.get_market_ticker_name", return_value=""):
            with pytest.raises(MarketDataError, match="종목명 조회 실패"):
                load_krx_equity_universe(as_of="20260814")


def test_weak_and_progressed_stage_stocks_are_included_if_data_is_valid():
    """WEAK, BASE, PROGRESSED 등 Stage나 점수와 상관없이 데이터가 정상이면 Universe에 포함됨을 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)

    # 1. GS건설 (WEAK Stage 종목)
    daily_gs = cache.load("006360")
    if daily_gs is not None and not daily_gs.empty:
        record_gs = audit_ticker_quality(
            ticker="006360",
            name="GS건설",
            market=MarketType.KOSPI,
            daily=daily_gs,
            reference_market_date=daily_gs.index.max().strftime("%Y-%m-%d"),
        )
        assert record_gs.included_in_pattern_a_universe is True
        assert record_gs.quality_status == QualityStatus.OK

    # 2. 에코프로 (PROGRESSED Stage 종목)
    daily_eco = cache.load("086520")
    if daily_eco is not None and not daily_eco.empty:
        record_eco = audit_ticker_quality(
            ticker="086520",
            name="에코프로",
            market=MarketType.KOSDAQ,
            daily=daily_eco,
            reference_market_date=daily_eco.index.max().strftime("%Y-%m-%d"),
        )
        assert record_eco.included_in_pattern_a_universe is True
        assert record_eco.quality_status == QualityStatus.OK


def test_deterministic_semantic_records():
    """동일 입력 시 generated_at을 제외한 모든 semantic 필드가 100% 동일함을 검증."""
    securities = [
        UniverseSecurity("005930", "삼성전자", MarketType.KOSPI),
        UniverseSecurity("000660", "SK하이닉스", MarketType.KOSPI),
    ]

    records1, summary1 = audit_universe_quality(
        ticker_metadata=securities, cache_dir=_CACHE_DIR, reference_market_date="2026-02-27"
    )
    records2, summary2 = audit_universe_quality(
        ticker_metadata=securities, cache_dir=_CACHE_DIR, reference_market_date="2026-02-27"
    )

    assert records1 == records2
    assert summary1.official_universe_count == summary2.official_universe_count
    assert summary1.included_tickers == summary2.included_tickers
    assert summary1.cache_present_count == summary2.cache_present_count
    assert summary1.exclusion_reason_counts == summary2.exclusion_reason_counts
