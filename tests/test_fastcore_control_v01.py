"""Focused local-only CONTROL boundary and aggregation tests."""

from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from scripts import run_fastcore_control as control
from trend_scanner.backtest import fastcore_fundamentals_simple_v01 as engine


def test_frozen_candidate_id_is_identity_scoped_and_date_normalized():
    assert control.frozen_candidate_id("005930", "KR7005930003", "KOSPI", "2021-04-02") == (
        "005930|KR7005930003|KOSPI|2021-04-02"
    )


def test_control_starts_flat_but_keeps_pre_start_lookback(monkeypatch):
    dates = pd.bdate_range("2020-12-01", "2021-03-31")
    daily = pd.DataFrame(
        {
            "open": 10_000.0,
            "high": 10_500.0,
            "low": 9_500.0,
            "close": 10_000.0,
            "volume": 1_000_000.0,
            "trading_value": 500_000_000.0,
        },
        index=dates,
    )
    raw = pd.DataFrame(
        {
            "close": 10_000.0,
            "market_cap": 400_000_000_000.0,
            "trading_value": 500_000_000.0,
            "avg_trading_value_20d": 500_000_000.0,
        },
        index=dates,
    )
    lifecycle = engine.IdentityLifecycle(
        ticker="000001", isu_cd="KR7000000001", market="KOSPI",
        effective_from=pd.Timestamp("2020-12-01"), effective_to=pd.Timestamp("2021-03-31"),
    )
    observed_daily_mins: list[pd.Timestamp] = []

    def fake_fast(*_args, **kwargs):
        observed_daily_mins.append(kwargs["context"].daily.index.min())
        return {
            "fast_machine_stage": "TRIGGER",
            "fast_machine_stage_status": "READY",
            "fast_monthly_permission_state": "PERMITTED_REGIME",
            "fast_daily_risk_state": "NORMAL",
            "fast_score_status": "READY",
            "fast_score": 75.0,
            "pattern_a_stage": "TRANSITION",
        }

    class _Stage:
        value = "TRANSITION"

    monkeypatch.setattr(engine, "evaluate_pattern_a_fast", fake_fast)
    monkeypatch.setattr(engine, "evaluate_pattern_a", lambda _snapshot: SimpleNamespace(stage=_Stage(), score=1.0))

    records = engine.simulate_ticker_strategy_fundamentals_v01(
        strategy_id="TEST_CONTROL",
        ticker="000001",
        isu_cd="KR7000000001",
        name="Example",
        market="KOSPI",
        daily=daily,
        raw_panel=raw,
        score_contract={},
        stage_contract={},
        loss_guard_enabled=True,
        backtest_end=pd.Timestamp("2021-03-31"),
        entry_eligible_from=pd.Timestamp("2021-02-01"),
        identity_lifecycle=lifecycle,
        entry_gate=lambda _as_of, context: {
            "gate_pass": pd.Timestamp(context["signal_date"]) >= pd.Timestamp("2021-02-01")
        },
    )

    assert records
    assert all(pd.Timestamp(record.entry_signal_information_date) >= pd.Timestamp("2021-02-01") for record in records)
    assert observed_daily_mins
    assert min(observed_daily_mins) == pd.Timestamp("2020-12-01")


def test_summary_keeps_strategy_return_unit_without_rescaling():
    frame = pd.DataFrame([
        {
            "ticker": "000001", "trade_sequence": 1, "trade_status": "REALIZED",
            "terminal_return": 12.5, "mfe": 20.0, "mae": -5.0,
            "holding_trading_days": 10, "loss_guard_triggered": False,
            "exit_type": "EXIT3_PROGRESSED_TO_BASE",
        },
    ])
    summary = control._summary(
        frame,
        raw_sha256="raw",
        validation={"all": 0},
        network_requests=0,
        loader_count=1,
        authority_sha256="authority",
        authority_interval_count=1,
    )
    assert summary["return_unit"] == "percentage_points"
    assert summary["mean_terminal_return"] == 12.5
    assert summary["positive_trade_rate"] == 100.0
