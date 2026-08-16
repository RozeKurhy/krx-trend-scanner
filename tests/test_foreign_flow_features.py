"""Unit tests for Foreign Investor Flow feature computation engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.foreign_flow_provider import ForeignFlowDataProvider
from trend_scanner.flow.foreign_flow import (
    FlowDataStatus,
    ForeignFlowFeatureResult,
    compute_foreign_flow_features,
)


def _make_dummy_flow_df(
    ticker: str,
    dates: list[str],
    net_buys: list[float],
) -> pd.DataFrame:
    """Create a dummy foreign flow DataFrame for testing."""
    return pd.DataFrame({
        "date": dates,
        "ticker": [ticker] * len(dates),
        "foreign_net_buy_value": net_buys,
        "foreign_buy_value": [abs(x) + 1000.0 for x in net_buys],
        "foreign_sell_value": [1000.0 for _ in net_buys],
    })


def _make_dummy_price_df(
    dates: list[str],
    trading_values: list[float],
) -> pd.DataFrame:
    """Create a dummy price/trading_value DataFrame for testing."""
    idx = pd.DatetimeIndex(dates)
    return pd.DataFrame({
        "open": [1000.0] * len(dates),
        "high": [1100.0] * len(dates),
        "low": [950.0] * len(dates),
        "close": [1050.0] * len(dates),
        "volume": [1000] * len(dates),
        "trading_value": trading_values,
    }, index=idx)


def test_signed_flow_arithmetic():
    """Gate 5: Verify signed net buy arithmetic correctly handles positive, negative, and zero flows."""
    ticker = "005930"
    as_of = "2026-08-14"
    # 5 days: +100, -50, +200, 0, -30 -> Sum = 220
    dates = ["2026-08-08", "2026-08-11", "2026-08-12", "2026-08-13", "2026-08-14"]
    net_buys = [100.0, -50.0, 200.0, 0.0, -30.0]
    flow_df = _make_dummy_flow_df(ticker, dates, net_buys)

    res = compute_foreign_flow_features(ticker, as_of, flow_df)
    assert res.foreign_net_buy_value_1d == -30.0
    assert res.foreign_net_buy_value_5d == 220.0
    assert res.foreign_positive_days_5d == 2  # 100 and 200 (> 0)
    assert res.foreign_positive_day_ratio_5d == 0.4


def test_window_boundary_contracts():
    """Gate 4: Verify boundary availability for 5D, 20D, 60D windows."""
    ticker = "005930"

    # Case 1: Exactly 5 observations (latest matches as_of)
    dates_5 = [f"2026-08-{i:02d}" for i in range(1, 6)]
    net_buys_5 = [10.0] * 5
    flow_df_5 = _make_dummy_flow_df(ticker, dates_5, net_buys_5)
    res_5 = compute_foreign_flow_features(ticker, "2026-08-05", flow_df_5)
    assert res_5.data_status == FlowDataStatus.PARTIAL
    assert res_5.foreign_net_buy_value_5d == 50.0
    assert res_5.foreign_net_buy_value_20d is None
    assert res_5.foreign_net_buy_value_60d is None

    # Case 2: Exactly 20 observations (latest matches as_of)
    dates_20 = [f"2026-07-{i:02d}" for i in range(1, 21)]
    net_buys_20 = [10.0] * 20
    flow_df_20 = _make_dummy_flow_df(ticker, dates_20, net_buys_20)
    res_20 = compute_foreign_flow_features(ticker, "2026-07-20", flow_df_20)
    assert res_20.data_status == FlowDataStatus.READY
    assert res_20.foreign_net_buy_value_5d == 50.0
    assert res_20.foreign_net_buy_value_20d == 200.0
    assert res_20.foreign_net_buy_value_60d is None

    # Case 3: Exactly 60 observations (latest matches as_of)
    dates_60 = pd.date_range("2026-05-01", periods=60, freq="B").strftime("%Y-%m-%d").tolist()
    net_buys_60 = [10.0] * 60
    flow_df_60 = _make_dummy_flow_df(ticker, dates_60, net_buys_60)
    res_60 = compute_foreign_flow_features(ticker, dates_60[-1], flow_df_60)
    assert res_60.data_status == FlowDataStatus.READY
    assert res_60.foreign_net_buy_value_5d == 50.0
    assert res_60.foreign_net_buy_value_20d == 200.0
    assert res_60.foreign_net_buy_value_60d == 600.0


def test_stale_latest_observation_fail_closed():
    """Gate 7: Verify 60 observations with stale latest date (< as_of) fails closed to DATA_UNAVAILABLE."""
    ticker = "005930"
    as_of = "2026-08-14"

    # 60 observations ending on 2026-08-12 (2 days stale relative to 2026-08-14)
    dates_stale = pd.date_range("2026-05-01", periods=60, freq="B").strftime("%Y-%m-%d").tolist()
    # Force last date to be 2026-08-12
    dates_stale[-1] = "2026-08-12"
    net_buys = [100.0] * len(dates_stale)
    flow_df = _make_dummy_flow_df(ticker, dates_stale, net_buys)

    res = compute_foreign_flow_features(ticker, as_of, flow_df)
    assert res.data_status == FlowDataStatus.DATA_UNAVAILABLE


def test_future_observation_exclusion_negative_test():
    """Gate 3: Verify strict PIT filtering excludes future observations."""
    ticker = "005930"
    as_of = "2026-08-14"

    # Base valid observations up to 2026-08-14
    dates_valid = pd.date_range("2026-07-15", periods=20, freq="B").strftime("%Y-%m-%d").tolist()
    dates_valid[-1] = "2026-08-14"
    net_buys_valid = [100.0] * 20

    # Add massive future buy on 2026-08-17
    dates_with_future = dates_valid + ["2026-08-17"]
    net_buys_with_future = net_buys_valid + [999999999.0]

    flow_df = _make_dummy_flow_df(ticker, dates_with_future, net_buys_with_future)
    res = compute_foreign_flow_features(ticker, as_of, flow_df)

    # 2026-08-17 observation must be completely ignored
    assert res.foreign_flow_last_observation_date == as_of
    assert res.foreign_net_buy_value_1d == 100.0
    assert res.foreign_net_buy_value_20d == 2000.0
    assert res.foreign_flow_observation_count == 20
    assert res.data_status == FlowDataStatus.READY


def test_duplicate_row_rejection():
    """Gate 7: Verify duplicate date rows trigger validation error."""
    ticker = "005930"
    as_of = "2026-08-14"

    dates = ["2026-08-10", "2026-08-11", "2026-08-11", "2026-08-12", "2026-08-14"]
    net_buys = [100.0, 200.0, 300.0, 400.0, 500.0]
    flow_df = _make_dummy_flow_df(ticker, dates, net_buys)

    with pytest.raises(MarketDataError, match="Duplicate date detected"):
        compute_foreign_flow_features(ticker, as_of, flow_df)


def test_trading_value_normalization():
    """Gate 6: Verify flow intensity correctly normalizes by trading value sum over same window."""
    ticker = "005930"
    as_of = "2026-08-14"

    dates = pd.date_range("2026-07-15", periods=20, freq="B").strftime("%Y-%m-%d").tolist()
    dates[-1] = as_of
    net_buys = [10.0] * 20                               # Sum 20D = 200.0, Sum 5D = 50.0
    trading_values = [100.0] * 20                        # Sum 20D = 2000.0, Sum 5D = 500.0

    flow_df = _make_dummy_flow_df(ticker, dates, net_buys)
    price_df = _make_dummy_price_df(dates, trading_values)

    res = compute_foreign_flow_features(ticker, as_of, flow_df, price_df)
    assert res.foreign_flow_intensity_5d == pytest.approx(50.0 / 500.0, abs=1e-6)
    assert res.foreign_flow_intensity_20d == pytest.approx(200.0 / 2000.0, abs=1e-6)


def test_trading_value_missing_returns_none_not_zero():
    """Gate 6: Verify intensity returns None (never default 0.0) when trading value is unavailable."""
    ticker = "005930"
    as_of = "2026-08-14"

    dates = pd.date_range("2026-07-15", periods=20, freq="B").strftime("%Y-%m-%d").tolist()
    dates[-1] = as_of
    net_buys = [10.0] * 20
    flow_df = _make_dummy_flow_df(ticker, dates, net_buys)

    # No price_df provided
    res = compute_foreign_flow_features(ticker, as_of, flow_df, price_df=None)
    assert res.foreign_flow_intensity_5d is None
    assert res.foreign_flow_intensity_20d is None
    assert res.foreign_flow_intensity_60d is None


def test_missing_or_empty_flow_fails_closed():
    """Gate 7: Verify empty/missing flow returns DATA_UNAVAILABLE."""
    ticker = "005930"
    as_of = "2026-08-14"

    res_none = compute_foreign_flow_features(ticker, as_of, flow_df=None)
    assert res_none.data_status == FlowDataStatus.DATA_UNAVAILABLE
    assert res_none.foreign_flow_observation_count == 0
    assert res_none.foreign_net_buy_value_20d is None

    empty_df = pd.DataFrame(columns=["date", "ticker", "foreign_net_buy_value"])
    res_empty = compute_foreign_flow_features(ticker, as_of, flow_df=empty_df)
    assert res_empty.data_status == FlowDataStatus.DATA_UNAVAILABLE


def test_provider_missing_column_negative_test(monkeypatch):
    """Verify provider raises MarketDataError when required columns are missing in KRX response."""
    fake_df = pd.DataFrame({
        "매수거래대금": [1000.0],
        "매도거래대금": [500.0],
    }, index=["005930"])

    from pykrx import stock
    monkeypatch.setattr(stock, "get_market_net_purchases_of_equities_by_ticker", lambda *args, **kwargs: fake_df)

    provider = ForeignFlowDataProvider()
    with pytest.raises(MarketDataError, match="missing required columns"):
        provider.fetch_date_batch("2026-08-14")


def test_provider_numeric_coercion_negative_test(monkeypatch):
    """Verify provider raises MarketDataError when numeric coercion fails in KRX response."""
    fake_df = pd.DataFrame({
        "매수거래대금": ["INVALID_NUM"],
        "매도거래대금": [500.0],
        "순매수거래대금": [500.0],
    }, index=["005930"])

    from pykrx import stock
    monkeypatch.setattr(stock, "get_market_net_purchases_of_equities_by_ticker", lambda *args, **kwargs: fake_df)

    provider = ForeignFlowDataProvider()
    with pytest.raises(MarketDataError, match="Numeric coercion failure"):
        provider.fetch_date_batch("2026-08-14")

