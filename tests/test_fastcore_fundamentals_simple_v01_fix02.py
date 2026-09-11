"""Focused FIX02 tests for the OOM-safe FastCore candidate path.

All fixtures are in-memory and the tests never access a market or OpenDART
network endpoint.
"""

from __future__ import annotations

import json

import pandas as pd
import pytest

from trend_scanner.backtest import raw_investability_panel as raw_panel_module
from trend_scanner.backtest.raw_investability_panel import (
    build_raw_investability_panel,
    evaluate_entry_filter,
    iter_raw_investability_panels,
)


def _snapshot(
    day: str,
    ticker: str,
    *,
    market_cap: float = 400_000_000_000.0,
    trading_value: float = 500_000_000.0,
    close: float = 10_000.0,
) -> pd.DataFrame:
    return pd.DataFrame(
        [{
            "date": pd.Timestamp(day), "ticker": ticker, "open": close,
            "high": close, "low": close, "close": close,
            "volume": 1_000_000.0, "trading_value": trading_value,
            "market_cap": market_cap, "listed_shares": 1_000_000.0,
        }]
    )


class _FakeRawStore:
    snapshots: dict[tuple[str, str], pd.DataFrame] = {}

    def __init__(self, _root):
        pass

    def list_dates(self, market: str) -> list[str]:
        return sorted(day for item_market, day in self.snapshots if item_market == market)

    def load_snapshot(self, market: str, day: str) -> pd.DataFrame:
        return self.snapshots[(market, day)].copy()


@pytest.fixture
def fake_store(monkeypatch):
    snapshots: dict[tuple[str, str], pd.DataFrame] = {}
    for offset in range(40):
        day = (pd.Timestamp("2020-01-01") + pd.Timedelta(offset, unit="D")).strftime("%Y-%m-%d")
        snapshots[("KOSPI", day)] = _snapshot(day, "000001")
    _FakeRawStore.snapshots = snapshots
    monkeypatch.setattr(raw_panel_module, "KrxRawStockStore", _FakeRawStore)
    return snapshots


def test_streaming_iterator_matches_materialized_compatibility_wrapper(fake_store):
    tickers = {"000001"}
    materialized = build_raw_investability_panel(tickers, end="2020-02-09")
    streamed = dict(iter_raw_investability_panels(tickers, end="2020-02-09"))
    pd.testing.assert_frame_equal(materialized["000001"], streamed["000001"])
    assert len(streamed["000001"]) == 40
    assert streamed["000001"]["avg_trading_value_20d"].iloc[:19].isna().all()
    assert streamed["000001"]["avg_trading_value_20d"].iloc[19] == pytest.approx(500_000_000.0)


def test_identity_scoped_panel_resets_successor_window(fake_store):
    intervals = {
        ("000001", "OLD", "KOSPI"): [("2020-01-01", "2020-01-20")],
        ("000001", "NEW", "KOSPI"): [("2020-01-21", "2020-02-09")],
    }
    panel = build_raw_investability_panel(
        {"000001"}, end="2020-02-09", identity_intervals=intervals,
    )["000001"]
    assert panel["avg_trading_value_20d"].iloc[:19].isna().all()
    assert panel["avg_trading_value_20d"].iloc[19] == pytest.approx(500_000_000.0)
    # The successor starts at 2020-01-11 and therefore cannot inherit the
    # predecessor's 20-day observations.
    assert panel["avg_trading_value_20d"].iloc[20:39].isna().all()
    assert panel["avg_trading_value_20d"].iloc[39] == pytest.approx(500_000_000.0)


def test_same_day_cross_market_collision_fails_closed(fake_store):
    fake_store[("KOSDAQ", "2020-01-05")] = _snapshot("2020-01-05", "000001")
    panel = build_raw_investability_panel({"000001"}, end="2020-01-31")["000001"]
    assert panel.index.has_duplicates
    assert panel.index[4] == panel.index[5]


def test_entry_filter_never_uses_future_raw_observation():
    panel = pd.DataFrame(
        {
            "close": [10_000.0, 20_000.0],
            "market_cap": [400_000_000_000.0, 400_000_000_000.0],
            "trading_value": [500_000_000.0, 500_000_000.0],
            "avg_trading_value_20d": [500_000_000.0, 500_000_000.0],
        },
        index=pd.to_datetime(["2020-01-01", "2020-01-03"]),
    )
    result = evaluate_entry_filter(
        panel, pd.Timestamp("2020-01-02"), market_cap_threshold=300_000_000_000.0,
        avg_trading_value_threshold=300_000_000.0, close_threshold=5_000.0,
    )
    assert result["entry_filter_raw_date"] == "2020-01-01"
    assert result["entry_signal_close"] == 10_000.0


def test_fix02_checkpoint_contract_is_bounded_and_resumable(tmp_path):
    from scripts import run_fastcore_fundamentals_simple_v01 as runner

    original = runner.RAW_CANDIDATE_CHECKPOINT_PATH
    runner.RAW_CANDIDATE_CHECKPOINT_PATH = tmp_path / "scan_checkpoint.json"
    try:
        runner._write_scan_checkpoint(
            completed_tickers={"000001"}, completed_task_keys={"000001|A|KOSPI|2020-01-01|2020-12-31"},
            completed_identity_count=1, prefiltered_identity_count=1, candidate_count=2,
            status="RUNNING", total_identity_intervals=3,
        )
        payload = json.loads((tmp_path / "scan_checkpoint.json").read_text(encoding="utf-8"))
    finally:
        runner.RAW_CANDIDATE_CHECKPOINT_PATH = original
    assert payload["max_workers"] == 1
    assert payload["batch_size"] <= 50
    assert payload["completed_identity_count"] == 1
    assert payload["completed_task_keys"] == ["000001|A|KOSPI|2020-01-01|2020-12-31"]
