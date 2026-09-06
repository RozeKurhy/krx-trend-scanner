"""Julia performance remediation: cache ownership and safe tail reuse."""

from __future__ import annotations

from pathlib import Path
import sys

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import evaluate_julia_strategy_v00_comparison as runner
from trend_scanner.backtest import snapshot_context as snapshot_context_module
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context


def _daily_fixture() -> pd.DataFrame:
    dates = pd.bdate_range("2021-09-01", "2022-03-31")
    close = pd.Series(range(100, 100 + len(dates)), index=dates, dtype=float)
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000_000,
            "trading_value": close * 1_000_000,
        },
        index=dates,
    )


def test_julia_worker_shares_one_cache_pair_across_audit_and_strategies(monkeypatch):
    daily = _daily_fixture()
    score_contract = {"score": "fixture"}
    stage_contract = {"stage": "fixture"}
    registry = object()
    calls: list[dict] = []

    class DummyLoader:
        def load(self, ticker):
            assert ticker == "000001"
            return daily

    class DummyFastCache:
        instances = []

        def __init__(self):
            self.calls = 0
            self.__class__.instances.append(self)

        def get(self, *args, **kwargs):
            self.calls += 1
            return {
                "fast_machine_stage": "WATCH",
                "fast_machine_stage_status": "READY",
                "fast_monthly_permission_state": "PERMITTED_REGIME",
                "fast_daily_risk_state": "NORMAL",
                "fast_score_status": "READY",
                "pattern_a_stage": "WATCH",
            }

    class DummyMonthlyCache:
        instances = []

        def __init__(self):
            self.__class__.instances.append(self)

    def fake_simulate(**kwargs):
        calls.append(kwargs)
        return []

    monkeypatch.setattr(runner, "FastSnapshotCache", DummyFastCache)
    monkeypatch.setattr(runner, "MonthlySnapshotCache", DummyMonthlyCache)
    monkeypatch.setattr(runner, "build_precomputed_ticker_context", lambda *args: object())
    monkeypatch.setattr(runner, "simulate_ticker_strategy_2022", fake_simulate)

    result = runner._worker_simulation(
        ("000001", "fixture", "KOSPI", score_contract, stage_contract, registry),
        DummyLoader(),
    )

    assert result == ([], [], [])
    assert len(DummyFastCache.instances) == 1
    assert len(DummyMonthlyCache.instances) == 1
    assert DummyFastCache.instances[0].calls > 0, "audit must use the shared FAST cache"
    assert len(calls) == 2
    assert calls[0]["fast_snapshot_cache"] is calls[1]["fast_snapshot_cache"]
    assert calls[0]["monthly_snapshot_cache"] is calls[1]["monthly_snapshot_cache"]
    assert calls[0]["snapshot_context"] is calls[1]["snapshot_context"]


def test_context_skips_tail_resample_when_legacy_path_drops_incomplete_period(monkeypatch):
    daily = _daily_fixture()
    context = build_precomputed_ticker_context("000001", "fixture", daily)

    def fail_if_called(_frame):
        raise AssertionError("incomplete tail must not be resampled")

    monkeypatch.setattr(snapshot_context_module, "to_weekly", fail_if_called)
    monkeypatch.setattr(snapshot_context_module, "to_monthly", fail_if_called)
    monkeypatch.setattr(snapshot_context_module, "is_completed_market_month", lambda *args, **kwargs: False)

    snapshot = snapshot_context_module.build_historical_snapshot_from_context(
        context,
        pd.Timestamp("2022-02-10"),
        include_incomplete_periods=False,
    )

    assert snapshot.requested_snapshot_date == pd.Timestamp("2022-02-10")
    assert snapshot.weekly_as_of is not None
    assert snapshot.monthly_as_of is not None
