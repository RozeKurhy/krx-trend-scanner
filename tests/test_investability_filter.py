"""Unit Tests for Downstream Investability Filter Module (Phase 10C)."""

from __future__ import annotations

import pandas as pd
import pytest

from trend_scanner.filters.investability import (
    InvestabilityEvaluationResult,
    InvestabilityReason,
    InvestabilityStatus,
    MIN_AVG_TRADING_VALUE_20D_KRW,
    MIN_MARKET_CAP_KRW,
    evaluate_investability,
)


@pytest.fixture
def sample_daily_data() -> pd.DataFrame:
    """Create deterministic 60-day daily price and trading value history."""
    dates = pd.bdate_range(end="2026-08-14", periods=60)
    df = pd.DataFrame(
        {
            "open": 10000.0,
            "high": 10500.0,
            "low": 9800.0,
            "close": 10200.0,
            "volume": 100000,
            "trading_value": 500_000_000.0,  # 5.0 억원 daily
        },
        index=dates,
    )
    return df


def test_constants():
    """Verify policy constants match Phase 10B approved values."""
    assert MIN_MARKET_CAP_KRW == 100_000_000_000.0  # 1,000억원
    assert MIN_AVG_TRADING_VALUE_20D_KRW == 300_000_000.0  # 3.0억원


def test_investable_happy_path(sample_daily_data: pd.DataFrame):
    """Verify stock passing all criteria is INVESTABLE."""
    res = evaluate_investability(
        ticker="005930",
        as_of="2026-08-14",
        daily=sample_daily_data,
        market_cap=500_000_000_000.0,  # 5,000억원
    )
    assert res.status == InvestabilityStatus.INVESTABLE
    assert res.reason == InvestabilityReason.PASS_ALL_INVESTABILITY_FILTERS.value
    assert res.market_cap_eok == 5000.0
    assert res.avg_trading_value_20d_eok == 5.0
    assert res.close == 10200.0
    assert res.data_ready is True


def test_boundary_market_cap_exact_1000eok(sample_daily_data: pd.DataFrame):
    """Verify exact 1,000억원 boundary satisfies >= threshold."""
    res = evaluate_investability(
        ticker="000001",
        as_of="2026-08-14",
        daily=sample_daily_data,
        market_cap=100_000_000_000.0,  # exactly 1,000억원
    )
    assert res.status == InvestabilityStatus.INVESTABLE
    assert res.market_cap_ready is True


def test_boundary_market_cap_below_1000eok(sample_daily_data: pd.DataFrame):
    """Verify market cap below 1,000억원 is FILTERED_MARKET_CAP."""
    res = evaluate_investability(
        ticker="000002",
        as_of="2026-08-14",
        daily=sample_daily_data,
        market_cap=99_999_999_999.0,  # 999.999억원
    )
    assert res.status == InvestabilityStatus.FILTERED_MARKET_CAP
    assert "MARKET_CAP_BELOW_1000EOK" in res.reason


def test_boundary_tv20_exact_3eok(sample_daily_data: pd.DataFrame):
    """Verify exact 3.0억원 TV20 boundary satisfies >= threshold."""
    daily = sample_daily_data.copy()
    daily["trading_value"] = 300_000_000.0  # exactly 3.0억원
    res = evaluate_investability(
        ticker="000003",
        as_of="2026-08-14",
        daily=daily,
        market_cap=150_000_000_000.0,
    )
    assert res.status == InvestabilityStatus.INVESTABLE
    assert res.avg_trading_value_20d_eok == 3.0


def test_boundary_tv20_below_3eok(sample_daily_data: pd.DataFrame):
    """Verify TV20 below 3.0억원 is FILTERED_LIQUIDITY."""
    daily = sample_daily_data.copy()
    daily["trading_value"] = 299_000_000.0  # 2.99억원
    res = evaluate_investability(
        ticker="000004",
        as_of="2026-08-14",
        daily=daily,
        market_cap=150_000_000_000.0,
    )
    assert res.status == InvestabilityStatus.FILTERED_LIQUIDITY
    assert "TV20_BELOW_3EOK" in res.reason


def test_precedence_mcap_over_liquidity(sample_daily_data: pd.DataFrame):
    """Verify market cap failure precedes liquidity failure."""
    daily = sample_daily_data.copy()
    daily["trading_value"] = 100_000_000.0  # 1.0억원 (fail)
    res = evaluate_investability(
        ticker="000005",
        as_of="2026-08-14",
        daily=daily,
        market_cap=50_000_000_000.0,  # 500억원 (fail)
    )
    # Market cap checked first -> FILTERED_MARKET_CAP
    assert res.status == InvestabilityStatus.FILTERED_MARKET_CAP


def test_missing_market_cap(sample_daily_data: pd.DataFrame):
    """Verify missing market cap triggers DATA_UNAVAILABLE."""
    res = evaluate_investability(
        ticker="000006",
        as_of="2026-08-14",
        daily=sample_daily_data,
        market_cap=None,
    )
    assert res.status == InvestabilityStatus.DATA_UNAVAILABLE
    assert res.reason == InvestabilityReason.REQUIRED_METRIC_UNAVAILABLE.value
    assert res.data_ready is False


def test_missing_exact_close_on_as_of(sample_daily_data: pd.DataFrame):
    """Verify missing observation on exact as_of date triggers DATA_UNAVAILABLE."""
    # Remove last date (2026-08-14) so as_of observation is missing
    daily = sample_daily_data.iloc[:-1].copy()
    res = evaluate_investability(
        ticker="000007",
        as_of="2026-08-14",
        daily=daily,
        market_cap=200_000_000_000.0,
    )
    assert res.status == InvestabilityStatus.DATA_UNAVAILABLE
    assert res.reason == InvestabilityReason.REQUIRED_METRIC_UNAVAILABLE.value
    assert res.data_ready is False


def test_insufficient_tv20_history():
    """Verify having fewer than 20 trading days triggers DATA_UNAVAILABLE."""
    dates = pd.bdate_range(end="2026-08-14", periods=15)  # only 15 days
    daily = pd.DataFrame(
        {
            "close": 10000.0,
            "trading_value": 500_000_000.0,
        },
        index=dates,
    )
    res = evaluate_investability(
        ticker="000008",
        as_of="2026-08-14",
        daily=daily,
        market_cap=200_000_000_000.0,
    )
    assert res.status == InvestabilityStatus.DATA_UNAVAILABLE
    assert res.trading_value_20d_ready is False
    assert res.data_ready is False


def test_tv60_missing_only_does_not_fail(sample_daily_data: pd.DataFrame):
    """Verify stock with 20-59 days of history is NOT fail closed if TV60 is missing."""
    # Provide 30 days of data (enough for TV20, but TV60 is missing)
    daily = sample_daily_data.iloc[-30:].copy()
    res = evaluate_investability(
        ticker="000009",
        as_of="2026-08-14",
        daily=daily,
        market_cap=200_000_000_000.0,
    )
    assert res.trading_value_20d_ready is True
    assert res.trading_value_60d_ready is False
    assert res.data_ready is True
    assert res.status == InvestabilityStatus.INVESTABLE
    assert res.avg_trading_value_60d is None
