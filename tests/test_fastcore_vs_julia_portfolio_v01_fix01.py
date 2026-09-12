"""Focused FIX01 regressions for full weekly evaluation and PIT mcap proxying."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import run_fastcore_vs_julia_portfolio_v01 as runner
from trend_scanner.validation.julia_strategy_v00 import HistoricalMarketCapRegistry


class _FakeProxyRegistry:
    def __init__(self, value: float | None, source: str, anchor_date: str | None = None):
        self.official_registry = SimpleNamespace(available_dates={"2025-06-27"})
        self.official_dates = ["2025-06-27"]
        self.missing_dates: set[str] = set()
        self._value = value
        self._source = source
        self._anchor_date = anchor_date

    def get_all_audit_records(self):
        return []

    def get_market_cap_at_reference(self, _ticker: str, _date: str):
        return self._value, {
            "proxy_source_type": self._source,
            "anchor_date": self._anchor_date,
        }


def test_missing_official_week_is_still_a_strategy_evaluation_date():
    weekly_index = pd.DatetimeIndex(["2025-07-04", "2026-08-14"])
    clipped_dates = set(weekly_index)
    result = runner._strategy_valid_week_dates(weekly_index, clipped_dates)
    assert result == list(weekly_index)
    assert pd.Timestamp("2026-08-14") in result


def test_proxy_mcap_threshold_boundaries_and_source():
    date = pd.Timestamp("2025-07-04")
    below = runner._market_cap_resolution(
        _FakeProxyRegistry(99_999_999_999.0, "PROXY_ANCHOR_PRICE_RATIO", "2025-06-27"),
        "005930",
        date,
    )
    pass_value = runner._market_cap_resolution(
        _FakeProxyRegistry(100_000_000_000.0, "PROXY_ANCHOR_PRICE_RATIO", "2025-06-27"),
        "005930",
        date,
    )
    assert below["market_cap_source"] == "PROXY_ANCHOR_PRICE_RATIO"
    assert below["market_cap"] < runner.MARKET_CAP_THRESHOLD
    assert pass_value["market_cap"] >= runner.MARKET_CAP_THRESHOLD


def test_proxy_unavailable_is_reported_after_signal_resolution():
    result = runner._market_cap_resolution(
        _FakeProxyRegistry(None, "PROXY_DATA_UNAVAILABLE"),
        "005930",
        pd.Timestamp("2026-08-14"),
    )
    assert result["market_cap"] is None
    assert result["market_cap_source"] == "MCAP_UNAVAILABLE"


def test_official_mcap_is_preferred_and_future_anchor_is_not_used():
    registry = runner.ProxyHistoricalMarketCapRegistry.load_from_repository(runner.ROOT)
    official_date = pd.Timestamp(registry.official_dates[0])
    official = runner._market_cap_resolution(registry, "005930", official_date)
    official_registry = HistoricalMarketCapRegistry.load_from_repository(runner.ROOT)
    expected, _ = official_registry.get_market_cap_at_reference("005930", official_date.strftime("%Y-%m-%d"))
    assert official["market_cap_source"] == "ACTUAL_KRX"
    assert official["market_cap"] == expected

    proxy = runner._market_cap_resolution(registry, "005930", pd.Timestamp("2025-07-04"))
    assert proxy["market_cap_source"] == "PROXY_ANCHOR_PRICE_RATIO"
    assert proxy["anchor_date"] < "2025-07-04"


def test_mdd_duration_fields_describe_peak_to_trough_and_recovery():
    curve = pd.DataFrame(
        {
            "date": ["2022-02-04", "2022-02-07", "2022-02-08", "2022-02-09"],
            "equity": [100.0, 120.0, 90.0, 125.0],
            "drawdown_pct": [0.0, 0.0, -25.0, 0.0],
        }
    )
    result = runner._risk_metrics(curve)
    assert result["mdd_peak_to_trough_trading_days"] == 1
    assert result["mdd_peak_to_recovery_trading_days"] == 2
    assert "max_drawdown_duration_trading_days" not in result
