"""Unit tests for Relative Strength (RS) confirmation feature computation engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.relative_strength.relative_strength import (
    HORIZON_SESSIONS_3M,
    HORIZON_SESSIONS_6M,
    HORIZON_SESSIONS_12M,
    RelativeStrengthDataStatus,
    RelativeStrengthFeatureResult,
    compute_relative_strength_features,
)
from trend_scanner.universe.models import MarketType


def _make_dummy_benchmark_df(
    index_code: str,
    dates: list[str],
    closes: list[float],
) -> pd.DataFrame:
    """Create a dummy benchmark DataFrame for testing."""
    return pd.DataFrame({
        "date": dates,
        "index_code": [str(index_code)] * len(dates),
        "index_name": "코스피" if str(index_code) == "1001" else "코스닥",
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [1000000] * len(dates),
        "trading_value": [100000000.0] * len(dates),
    })


def _make_dummy_stock_df(
    dates: list[str],
    closes: list[float],
) -> pd.DataFrame:
    """Create a dummy stock DataFrame with DatetimeIndex."""
    idx = pd.DatetimeIndex(dates)
    return pd.DataFrame({
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": [10000] * len(dates),
        "trading_value": [1000000.0] * len(dates),
    }, index=idx)


def test_relative_strength_arithmetic_basic():
    """Gate 6: Verify canonical Relative Strength formula (Relative Price Ratio - 1)."""
    # 253 trading days (0 to 252)
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-1]

    # Benchmark: 100 at anchor_3m (index -64), 110 at end (index -1) -> Ret = +10.0%
    b_closes = [100.0] * len(dates)
    b_closes[-1] = 110.0
    bench_df = _make_dummy_benchmark_df("1001", dates, b_closes)

    # Stock: 1000 at anchor_3m, 1200 at end -> Ret = +20.0%
    s_closes = [1000.0] * len(dates)
    s_closes[-1] = 1200.0
    stock_df = _make_dummy_stock_df(dates, s_closes)

    res = compute_relative_strength_features(
        ticker="005930",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSPI,
    )

    assert res.market_rs_data_status == RelativeStrengthDataStatus.READY
    assert res.stock_return_3m == pytest.approx(0.20, abs=1e-6)
    assert res.market_return_3m == pytest.approx(0.10, abs=1e-6)
    # Expected RS = (1 + 0.20) / (1 + 0.10) - 1 = 1.2 / 1.1 - 1 = 0.09090909...
    assert res.market_rs_3m == pytest.approx((1.2 / 1.1) - 1.0, abs=1e-6)


def test_relative_strength_underperformance():
    """Verify RS when stock underperforms benchmark."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-1]

    # Benchmark +20%
    b_closes = [100.0] * len(dates)
    b_closes[-1] = 120.0
    bench_df = _make_dummy_benchmark_df("1001", dates, b_closes)

    # Stock -10%
    s_closes = [1000.0] * len(dates)
    s_closes[-1] = 900.0
    stock_df = _make_dummy_stock_df(dates, s_closes)

    res = compute_relative_strength_features(
        ticker="005930",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSPI,
    )

    assert res.stock_return_3m == pytest.approx(-0.10, abs=1e-6)
    assert res.market_return_3m == pytest.approx(0.20, abs=1e-6)
    # Expected RS = (1 - 0.10) / (1 + 0.20) - 1 = 0.9 / 1.2 - 1 = -0.25
    assert res.market_rs_3m == pytest.approx(-0.25, abs=1e-6)


def test_relative_strength_outperformance_negative_market():
    """Verify positive RS in a falling market when stock falls less than market."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-1]

    # Benchmark -30%
    b_closes = [100.0] * len(dates)
    b_closes[-1] = 70.0
    bench_df = _make_dummy_benchmark_df("2001", dates, b_closes)

    # Stock -10%
    s_closes = [1000.0] * len(dates)
    s_closes[-1] = 900.0
    stock_df = _make_dummy_stock_df(dates, s_closes)

    res = compute_relative_strength_features(
        ticker="035720",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSDAQ,
    )

    assert res.stock_return_3m == pytest.approx(-0.10, abs=1e-6)
    assert res.market_return_3m == pytest.approx(-0.30, abs=1e-6)
    # Expected RS = (1 - 0.10) / (1 - 0.30) - 1 = 0.9 / 0.7 - 1 = +0.285714...
    assert res.market_rs_3m == pytest.approx((0.9 / 0.7) - 1.0, abs=1e-6)
    assert res.market_rs_3m > 0.0


def test_exact_freshness_requirement():
    """Gate 4: Verify DATA_UNAVAILABLE when benchmark latest observation is stale."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    # as_of is 1 business day ahead of benchmark last date
    as_of = "2026-08-15"

    b_closes = [100.0] * len(dates)
    bench_df = _make_dummy_benchmark_df("1001", dates, b_closes)
    s_closes = [1000.0] * len(dates)
    stock_df = _make_dummy_stock_df(dates, s_closes)

    res = compute_relative_strength_features(
        ticker="005930",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSPI,
    )

    assert res.market_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert res.market_rs_3m is None


def test_stale_stock_observation():
    """Gate 9: Verify DATA_UNAVAILABLE when stock has no price on exact as_of date."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-1]

    b_closes = [100.0] * len(dates)
    bench_df = _make_dummy_benchmark_df("1001", dates, b_closes)

    # Stock is missing observation on the last date (as_of)
    s_dates = dates[:-1]
    s_closes = [1000.0] * len(s_dates)
    stock_df = _make_dummy_stock_df(s_dates, s_closes)

    res = compute_relative_strength_features(
        ticker="005930",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSPI,
    )

    assert res.market_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert res.market_rs_3m is None


def test_future_observation_exclusion():
    """Gate 3: Verify strict PIT filtering excludes future observations."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-5]  # as_of is 4 days before end of dataset

    b_closes = [100.0] * len(dates)
    bench_df = _make_dummy_benchmark_df("1001", dates, b_closes)
    s_closes = [1000.0] * len(dates)
    stock_df = _make_dummy_stock_df(dates, s_closes)

    res = compute_relative_strength_features(
        ticker="005930",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSPI,
    )

    assert res.as_of == as_of
    assert res.market_benchmark_last_observation_date == as_of
    assert res.market_rs_data_status == RelativeStrengthDataStatus.READY


def test_missing_anchor_observation_partial():
    """Verify PARTIAL status when stock has 3M anchor but missing 12M anchor."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-1]

    b_closes = [100.0] * len(dates)
    bench_df = _make_dummy_benchmark_df("1001", dates, b_closes)

    # Stock only exists for the last 80 trading days (has 3M=63D, but not 6M=126D or 12M=252D)
    short_dates = dates[-80:]
    s_closes = [1000.0] * len(short_dates)
    stock_df = _make_dummy_stock_df(short_dates, s_closes)

    res = compute_relative_strength_features(
        ticker="005930",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSPI,
    )

    assert res.market_rs_data_status == RelativeStrengthDataStatus.PARTIAL
    assert res.market_rs_3m is not None
    assert res.market_rs_6m is None
    assert res.market_rs_12m is None


def test_market_benchmark_selection():
    """Gate 5: Verify correct mapping to KOSPI (1001) vs KOSDAQ (2001)."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-1]

    df_kospi = _make_dummy_benchmark_df("1001", dates, [100.0] * len(dates))
    df_kosdaq = _make_dummy_benchmark_df("2001", dates, [200.0] * len(dates))
    combined_bench = pd.concat([df_kospi, df_kosdaq], ignore_index=True)

    stock_df = _make_dummy_stock_df(dates, [1000.0] * len(dates))

    res_kospi = compute_relative_strength_features("005930", as_of, stock_df, combined_bench, MarketType.KOSPI)
    assert res_kospi.market_benchmark_code == "1001"
    assert res_kospi.market_benchmark_name == "코스피"

    res_kosdaq = compute_relative_strength_features("035720", as_of, stock_df, combined_bench, MarketType.KOSDAQ)
    assert res_kosdaq.market_benchmark_code == "2001"
    assert res_kosdaq.market_benchmark_name == "코스닥"


def test_sector_rs_isolation():
    """Gate 8: Verify Sector RS failure/unavailability does not corrupt Market RS."""
    dates = pd.date_range("2025-01-01", periods=260, freq="B").strftime("%Y-%m-%d").tolist()
    as_of = dates[-1]

    bench_df = _make_dummy_benchmark_df("1001", dates, [100.0] * len(dates))
    stock_df = _make_dummy_stock_df(dates, [1000.0] * len(dates))

    # Empty sector DataFrame & missing mapping
    res = compute_relative_strength_features(
        ticker="005930",
        as_of=as_of,
        stock_df=stock_df,
        market_index_df=bench_df,
        market=MarketType.KOSPI,
        sector_index_df=pd.DataFrame(),
        sector_mapping=None,
    )

    assert res.market_rs_data_status == RelativeStrengthDataStatus.READY
    assert res.sector_rs_data_status == RelativeStrengthDataStatus.DATA_UNAVAILABLE
    assert res.sector_rs_3m is None
