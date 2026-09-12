"""Focused contract tests for the local-only FastCore V3 V0 runner."""

from __future__ import annotations

import pandas as pd

from scripts import run_fastcore_v3_simple_v00 as runner


def test_period_and_entry_contract_are_frozen() -> None:
    assert runner.START_DATE == pd.Timestamp("2021-04-01")
    assert runner.SIGNAL_CUTOFF == pd.Timestamp("2026-08-14")
    assert runner.SUPPORT_END == pd.Timestamp("2026-08-21")
    assert runner.MARKET_CAP_THRESHOLD == 100_000_000_000.0
    assert runner.LOSS_GUARD_ENABLED is False
    assert runner.EXIT3_ENABLED is False
    assert runner.EXIT4_ENABLED is False


def test_market_cap_gate_is_inclusive() -> None:
    assert runner.market_cap_pass(99_999_999_999) is False
    assert runner.market_cap_pass(100_000_000_000) is True
    assert runner.market_cap_pass(100_000_000_001) is True
    assert runner.market_cap_pass(None) is False


def test_mfe_tier_boundaries_are_exact() -> None:
    assert runner.mfe_tier(19.99) is None
    assert runner.mfe_tier(20.0) == (-10.0, -20.0, "MFE_20_TO_50")
    assert runner.mfe_tier(49.99) == (-10.0, -20.0, "MFE_20_TO_50")
    assert runner.mfe_tier(50.0) == (-15.0, -25.0, "MFE_50_TO_100")
    assert runner.mfe_tier(99.99) == (-15.0, -25.0, "MFE_50_TO_100")
    assert runner.mfe_tier(100.0) == (-20.0, -30.0, "MFE_100_TO_200")
    assert runner.mfe_tier(199.99) == (-20.0, -30.0, "MFE_100_TO_200")
    assert runner.mfe_tier(200.0) == (-25.0, -35.0, "MFE_200_TO_400")
    assert runner.mfe_tier(399.99) == (-25.0, -35.0, "MFE_200_TO_400")
    assert runner.mfe_tier(400.0) == (-30.0, -40.0, "MFE_400_PLUS")


def test_below_winner_mode_never_exits() -> None:
    assert runner.exit_decision(
        mfe_pct=19.99, hwm_price=100.0, current_close=1.0, fast_state="SETUP"
    )[0] is None


def test_soft_exit_requires_weak_fast_state() -> None:
    weak = runner.exit_decision(
        mfe_pct=20.0, hwm_price=120.0, current_close=108.0, fast_state="WATCH"
    )
    strong = runner.exit_decision(
        mfe_pct=20.0, hwm_price=120.0, current_close=108.0, fast_state="TREND"
    )
    assert weak[0] == "SOFT_EXIT"
    assert strong[0] is None


def test_hard_exit_is_fast_state_independent() -> None:
    for state in (None, "SETUP", "WATCH", "TREND", "EXTENDED"):
        assert runner.exit_decision(
            mfe_pct=20.0, hwm_price=120.0, current_close=96.0, fast_state=state
        )[0] == "HARD_EXIT"


def test_latest_fast_state_does_not_look_ahead() -> None:
    states = [
        (pd.Timestamp("2021-04-09"), "TREND"),
        (pd.Timestamp("2021-04-16"), "WATCH"),
    ]
    assert runner.latest_fast_state(states, pd.Timestamp("2021-04-08")) is None
    assert runner.latest_fast_state(states, pd.Timestamp("2021-04-12")) == "TREND"
    assert runner.latest_fast_state(states, pd.Timestamp("2021-04-16")) == "WATCH"


def test_exit_execution_uses_next_local_open_and_open_cutoff(monkeypatch) -> None:
    monkeypatch.setattr(runner, "SUPPORT_END", pd.Timestamp("2021-04-08"))
    daily = pd.DataFrame(
        {
            "open": [100.0, 110.0, 105.0],
            "high": [100.0, 112.0, 106.0],
            "low": [99.0, 109.0, 104.0],
            "close": [100.0, 110.0, 105.0],
        },
        index=pd.to_datetime(["2021-04-06", "2021-04-07", "2021-04-08"]),
    )
    row = {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "name": "TEST",
        "signal_date": "2021-04-05",
        "signal_information_date": "2021-04-05",
        "identity_effective_from": "2021-04-01",
        "identity_effective_to": "2021-04-08",
        "market_cap": 100_000_000_000.0,
        "market_cap_source": "TEST",
        "pattern_a_stage": "TRANSITION",
        "fast_machine_stage": "TRIGGER",
        "fast_machine_stage_status": "READY",
        "monthly_permission_state": "PERMITTED_REGIME",
        "daily_risk_state": "NORMAL",
        "fast_score": 1.0,
        "fast_score_status": "READY",
    }
    trade = runner.simulate_trade(row, daily, [], 1)
    assert trade is not None
    assert trade["trade_status"] == "OPEN_AT_CUTOFF"
    assert trade["매도일자"] is None
    assert trade["매도금액"] is None
    assert trade["매도 사유"] == "OPEN_AT_CUTOFF"
