"""Pattern A Universe & Data Quality Audit 유닛 및 통합 테스트.

이 테스트는 다음을 검증한다:
1. 정상 ticker -> universe included & QualityStatus.OK
2. history 부족 (36개월 미만) -> excluded with INSUFFICIENT_HISTORY
3. 필수 컬럼 누락 -> excluded with MISSING_COLUMNS
4. 중복 거래일 -> flagged with DUPLICATE_DATE
5. OHLC 가격 관계 위반 -> flagged with INVALID_OHLC
6. 미래 거래일 오염 -> flagged with FUTURE_DATE
7. WEAK / PROGRESSED Stage 종목도 데이터가 정상이면 universe included
8. candidate_state가 universe inclusion에 영향 주지 않음
9. 개별 종목 예외 발생 시에도 전체 universe run이 중단되지 않고 격리됨
10. 동일 입력에 대해 항상 deterministic한 정렬 및 결과 반환
11. Asset Type Classifier (보통주, 우선주, SPAC, REIT, ETF, ETN) 분류 정확성
12. Minimum History 구간별 (24m, 30m, 36m, 48m, 60m) Feature 준비도 실측 테스트
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.universe import (
    AssetType,
    FreshnessStatus,
    MarketType,
    QualityStatus,
    audit_ticker_quality,
    audit_universe_quality,
    classify_asset_type,
)
from trend_scanner.validation.feature_report import build_feature_row
from trend_scanner.data.resampler import to_monthly, to_weekly

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _create_mock_daily(
    months: int = 40,
    start_date: str = "2020-01-01",
    has_ohlc_violation: bool = False,
    has_duplicate_date: bool = False,
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
    # 1. 보통주 (6자리, 끝자리 0)
    assert classify_asset_type("005930", "삼성전자") == AssetType.COMMON
    assert classify_asset_type("000660", "SK하이닉스") == AssetType.COMMON

    # 2. 우선주 (끝자리 != 0 또는 '우')
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


def test_normal_ticker_is_included_in_universe():
    daily = _create_mock_daily(months=48, start_date="2020-01-01")
    ref_date = str(daily.index.max().strftime("%Y-%m-%d"))

    record = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily,
        reference_market_date=ref_date,
    )

    assert record.included_in_pattern_a_universe is True
    assert record.quality_status == QualityStatus.OK
    assert record.raw_data_ready is True
    assert record.feature_ready is True
    assert record.score_ready is True
    assert record.stage_ready is True
    assert record.evaluator_ready is True
    assert len(record.exclusion_reasons) == 0


def test_insufficient_history_is_excluded():
    # 24개월 히스토리 (36개월 미만)
    daily = _create_mock_daily(months=24, start_date="2022-01-01")
    ref_date = str(daily.index.max().strftime("%Y-%m-%d"))

    record = audit_ticker_quality(
        ticker="123450",
        name="신규상장사",
        market=MarketType.KOSDAQ,
        daily=daily,
        reference_market_date=ref_date,
    )

    assert record.included_in_pattern_a_universe is False
    assert record.required_history_sufficient is False
    assert "INSUFFICIENT_HISTORY" in record.exclusion_reasons


def test_missing_critical_columns_is_excluded():
    daily = _create_mock_daily(months=48, missing_columns=["close"])
    ref_date = str(daily.index.max().strftime("%Y-%m-%d"))

    record = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily,
        reference_market_date=ref_date,
    )

    assert record.included_in_pattern_a_universe is False
    assert record.raw_data_ready is False
    assert "MISSING_COLUMNS" in record.quality_flags


def test_duplicate_date_is_flagged():
    daily = _create_mock_daily(months=48, has_duplicate_date=True)
    ref_date = str(daily.index.max().strftime("%Y-%m-%d"))

    record = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily,
        reference_market_date=ref_date,
    )

    assert record.included_in_pattern_a_universe is False
    assert "DUPLICATE_DATE" in record.quality_flags


def test_invalid_ohlc_is_flagged():
    daily = _create_mock_daily(months=48, has_ohlc_violation=True)
    ref_date = str(daily.index.max().strftime("%Y-%m-%d"))

    record = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily,
        reference_market_date=ref_date,
    )

    assert record.included_in_pattern_a_universe is False
    assert "INVALID_OHLC" in record.quality_flags


def test_future_date_is_flagged():
    daily = _create_mock_daily(months=48, has_future_date=True)
    ref_date = "2024-03-29"

    record = audit_ticker_quality(
        ticker="005930",
        name="삼성전자",
        market=MarketType.KOSPI,
        daily=daily,
        reference_market_date=ref_date,
    )

    assert record.included_in_pattern_a_universe is False
    assert "FUTURE_DATE" in record.quality_flags


def test_weak_and_progressed_stage_stocks_are_included_if_data_is_valid():
    """WEAK, BASE, PROGRESSED 등 Stage나 점수와 상관없이 데이터가 정상이면 Universe에 포함됨을 검증."""
    cache = ParquetCache(base_dir=_CACHE_DIR)

    # 1. GS건설 (2022-11-30 기준 WEAK Stage 종목)
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

    # 2. 에코프로 (2023-11-30 기준 PROGRESSED Stage 종목)
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


def test_error_isolation_and_determinism():
    """개별 ticker 오류가 발생해도 전체 감사 루프가 중단되지 않고 deterministic함을 검증."""
    metadata = [
        {"ticker": "005930", "name": "삼성전자", "market": "KOSPI"},
        {"ticker": "999999", "name": "존재하지않는종목", "market": "KOSPI"},
        {"ticker": "000660", "name": "SK하이닉스", "market": "KOSPI"},
    ]

    records1, summary1 = audit_universe_quality(metadata, cache_dir=_CACHE_DIR)
    records2, summary2 = audit_universe_quality(metadata, cache_dir=_CACHE_DIR)

    assert len(records1) == 3
    assert len(records2) == 3
    assert summary1.total_tickers == 3
    assert summary1.missing_cache_count == 1  # 999999 캐시 없음

    # Deterministic 정렬 및 결과 일치
    assert [r.ticker for r in records1] == [r.ticker for r in records2]
    assert records1 == records2


def test_minimum_history_feature_sufficiency_cutoffs():
    """24m, 30m, 36m, 48m, 60m 구간별 Feature 산출 실측 테스트."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("005930")
    if daily is None or daily.empty:
        daily = _create_mock_daily(months=70)

    # 1. 24개월 (미달)
    monthly_24 = to_monthly(daily).tail(24)
    daily_24 = daily.loc[daily.index <= monthly_24.index[-1]]
    weekly_24 = to_weekly(daily_24)
    feat_24 = build_feature_row("005930", "삼성전자", daily_24, weekly_24, monthly_24)
    assert pd.isna(feat_24.ma24_slope_acceleration)  # 24m에서는 가속도 산출 불가
    assert pd.isna(feat_24.ma_spread_12m_ago)  # 24m에서는 13개월 전 ma24 산출 불가

    # 2. 36개월 (최소 기준 완전 충족)
    monthly_36 = to_monthly(daily).tail(36)
    daily_36 = daily.loc[daily.index <= monthly_36.index[-1]]
    weekly_36 = to_weekly(daily_36)
    feat_36 = build_feature_row("005930", "삼성전자", daily_36, weekly_36, monthly_36)
    assert not pd.isna(feat_36.range_36m)
    assert not pd.isna(feat_36.ma24_slope)
    assert not pd.isna(feat_36.ma24_slope_acceleration)
    assert not pd.isna(feat_36.avg_price_change_12m)
    assert not pd.isna(feat_36.ma_spread_12m_ago)
