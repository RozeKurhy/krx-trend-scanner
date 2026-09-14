"""Focused deterministic tests for the frozen FastCore V3 candidate contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trend_scanner.validation import pattern_a_fast_winner_hwm_exit_v01 as evaluator


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/research/candidate/winner_hwm_exit_v01.json"
SPEC_PATH = ROOT / "docs/patterns/pattern_a_fast/strategy/final_v03_candidate.md"


def _contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_prewinner_deep_loss_is_hold() -> None:
    result = evaluator.evaluate_eod(
        entry_open=100.0,
        previous_hwm_price=100.0,
        daily_high=119.99,
        daily_close=1.0,
        fast_state="SETUP",
    )
    assert result.mfe_pct < 20.0
    assert result.decision is None


def test_mfe_exactly_twenty_activates_winner_mode() -> None:
    result = evaluator.evaluate_eod(
        entry_open=100.0,
        previous_hwm_price=100.0,
        daily_high=120.0,
        daily_close=120.0,
        fast_state="TREND",
    )
    assert result.mfe_pct == 20.0
    assert result.mfe_tier == "MFE_20_TO_50"


@pytest.mark.parametrize(
    ("mfe", "label", "soft", "hard"),
    [
        (20.0, "MFE_20_TO_50", -10.0, -20.0),
        (50.0, "MFE_50_TO_100", -15.0, -25.0),
        (100.0, "MFE_100_TO_200", -20.0, -30.0),
        (200.0, "MFE_200_TO_400", -25.0, -35.0),
        (400.0, "MFE_400_PLUS", -30.0, -40.0),
    ],
)
def test_all_band_boundaries_are_owned_by_next_band(mfe: float, label: str, soft: float, hard: float) -> None:
    assert evaluator.mfe_tier(mfe) == (soft, hard, label)


@pytest.mark.parametrize(
    ("mfe", "soft"),
    [(20.0, -10.0), (50.0, -15.0), (100.0, -20.0), (200.0, -25.0), (400.0, -30.0)],
)
def test_each_soft_threshold_requires_weak_fast_state(mfe: float, soft: float) -> None:
    hwm = 100.0 * (1.0 + mfe / 100.0)
    close = hwm * (1.0 + soft / 100.0)
    assert evaluator.exit_decision(mfe_pct=mfe, hwm_price=hwm, current_close=close, fast_state="WATCH")[0] == "SOFT_EXIT"
    assert evaluator.exit_decision(mfe_pct=mfe, hwm_price=hwm, current_close=close, fast_state="SETUP")[0] == "SOFT_EXIT"


def test_soft_breach_in_nonweak_fast_state_holds() -> None:
    assert evaluator.exit_decision(mfe_pct=20.0, hwm_price=120.0, current_close=108.0, fast_state="TREND")[0] is None


@pytest.mark.parametrize(
    ("mfe", "hard"),
    [(20.0, -20.0), (50.0, -25.0), (100.0, -30.0), (200.0, -35.0), (400.0, -40.0)],
)
def test_each_hard_threshold_is_fast_state_independent(mfe: float, hard: float) -> None:
    hwm = 100.0 * (1.0 + mfe / 100.0)
    close = hwm * (1.0 + hard / 100.0)
    for state in (None, "WATCH", "SETUP", "TREND", "EXTENDED"):
        assert evaluator.exit_decision(mfe_pct=mfe, hwm_price=hwm, current_close=close, fast_state=state)[0] == "HARD_EXIT"


def test_simultaneous_soft_and_hard_breach_is_hard() -> None:
    assert evaluator.exit_decision(mfe_pct=20.0, hwm_price=120.0, current_close=96.0, fast_state="WATCH")[0] == "HARD_EXIT"


def test_hwm_highest_daily_high_never_decreases() -> None:
    hwm = evaluator.update_hwm(120.0, 110.0)
    assert hwm == 120.0
    assert evaluator.update_hwm(hwm, 135.0) == 135.0


def test_eod_signal_uses_next_open_execution_contract() -> None:
    contract = _contract()
    assert contract["signal_execution"] == {
        "signal": "COMPLETED_DAILY_EOD",
        "execution": "NEXT_LOCAL_TRADING_DAY_OPEN",
        "no_next_supported_day": "OPEN_AT_CUTOFF",
    }


def test_fixed_guard_exit3_exit4_are_not_in_evaluator_outputs() -> None:
    for state in (None, "WATCH", "SETUP", "TREND"):
        result = evaluator.exit_decision(mfe_pct=19.0, hwm_price=100.0, current_close=1.0, fast_state=state)
        assert result[0] is None
    assert {evaluator.exit_decision(mfe_pct=20.0, hwm_price=120.0, current_close=96.0, fast_state="TREND")[0]} == {"HARD_EXIT"}
    assert "FIXED_NEGATIVE_15_PCT_PRE_WINNER_GUARD" in _contract()["excluded_rules"]
    assert "V2_EXIT3_STAGE_TRANSITION" in _contract()["excluded_rules"]
    assert "V2_EXIT4_SCORE_HWM_15PT" in _contract()["excluded_rules"]


def test_w25_w30_failure_armed_persistence_and_soft_confirm_are_excluded() -> None:
    excluded = set(_contract()["excluded_rules"])
    assert {"W25", "W30", "FAILURE_ARMED", "PERSISTENCE_EXIT", "SOFT_CONFIRM"}.issubset(excluded)


def test_no_strategy_generated_reentry() -> None:
    contract = _contract()
    assert contract["reentry"] == {"generated_by_v3": False, "v2_reentry_modified": False}
    assert contract["next_ab_matched_cohort_requirement"]["reentry_generated"] is False


def test_machine_contract_matches_spec_and_json() -> None:
    contract = _contract()
    spec = SPEC_PATH.read_text(encoding="utf-8")
    assert contract["strategy_id"] == evaluator.STRATEGY_ID == "PATTERN_A_FAST_FINAL_STRATEGY_V03"
    assert contract["base_strategy_id"] == evaluator.BASE_STRATEGY_ID == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert contract["exit_contract_id"] == evaluator.EXIT_CONTRACT_ID == "WINNER_HWM_EXIT_V01"
    assert contract["winner_threshold"]["value"] == evaluator.WINNER_THRESHOLD_PCT == 20.0
    assert contract["hwm"]["price_field"] == evaluator.HWM_PRICE_FIELD == "daily_high"
    assert contract["hwm"]["breach_field"] == evaluator.BREACH_PRICE_FIELD == "daily_close"
    assert set(contract["soft_exit"]["fast_states"]) == set(evaluator.WEAK_FAST_STATES)
    assert [(row["lower_mfe_pct"], row["upper_mfe_pct_exclusive"], row["soft_drawdown_pct"], row["hard_drawdown_pct"], row["label"]) for row in contract["bands"]] == [
        (lower, upper, soft, hard, label) for lower, upper, soft, hard, label in evaluator.MFE_TIERS
    ]
    assert "running_raw_MFE < +20%" in spec
    assert "NEXT_LOCAL_TRADING_DAY_OPEN" in spec
    assert "Pre-Winner에는 강제 청산이 없으므로 장기간 자본이 묶이거나 큰 미실현 손실이 발생할 수 있다." in spec
