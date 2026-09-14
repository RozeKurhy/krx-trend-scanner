from __future__ import annotations

import pandas as pd
import pytest

from scripts.run_fastcore_v4_matched_ab_official_v01 import (
    EXPECTED_PRE_WINNER_COUNT,
    EXPECTED_TRADES,
    EXPECTED_UNIQUE_TICKERS,
    PRE_WINNER_BASELINE,
    WINNER_TAIL_BASELINE,
    build_representative_cases,
    evaluate_preregistered_criteria,
    evaluate_repair_gates,
    mfe_tier,
    validate_matched_integrity,
    v4_exit_decision,
)


def test_full_path_cohort_and_winner_boundary() -> None:
    from scripts.run_fastcore_v4_matched_ab_official_v01 import classify_full_path_mfe

    assert classify_full_path_mfe(19.999999) == "PRE_WINNER_LT_20"
    assert classify_full_path_mfe(20.0) == "WINNER_CAPABLE_GE_20"


def test_exact_20_uses_winner_rule_before_pre_winner_rule() -> None:
    decision, soft, hard, tier = v4_exit_decision(
        mfe_pct=20.0,
        hwm_price=120.0,
        current_close=102.0,
        entry_open=100.0,
        fast_state="WATCH",
    )
    assert decision == "WINNER_SOFT_WATCH_EXIT"
    assert (soft, hard, tier) == (-10.0, -20.0, "MFE_20_TO_50")


def test_pre_winner_requires_exact_price_and_watch_state() -> None:
    exit_result = v4_exit_decision(
        mfe_pct=19.99,
        hwm_price=100.0,
        current_close=85.0,
        entry_open=100.0,
        fast_state="WATCH",
    )
    assert exit_result[0] == "PRE_WINNER_PRICE_STRUCTURE_FAILURE"

    assert v4_exit_decision(
        mfe_pct=19.99,
        hwm_price=100.0,
        current_close=85.0,
        entry_open=100.0,
        fast_state="UNAVAILABLE",
    )[0] is None
    assert v4_exit_decision(
        mfe_pct=19.99,
        hwm_price=100.0,
        current_close=85.01,
        entry_open=100.0,
        fast_state="WATCH",
    )[0] is None
    assert v4_exit_decision(
        mfe_pct=19.99,
        hwm_price=100.0,
        current_close=85.0,
        entry_open=100.0,
        fast_state="SETUP",
    )[0] is None


def test_winner_soft_requires_watch_and_not_setup_or_unavailable() -> None:
    kwargs = dict(mfe_pct=20.0, hwm_price=120.0, current_close=108.0, entry_open=100.0)
    assert v4_exit_decision(**kwargs, fast_state="WATCH")[0] == "WINNER_SOFT_WATCH_EXIT"
    assert v4_exit_decision(**kwargs, fast_state="SETUP")[0] is None
    assert v4_exit_decision(**kwargs, fast_state="UNAVAILABLE")[0] is None


def test_winner_hard_is_fast_independent_and_has_priority() -> None:
    kwargs = dict(mfe_pct=20.0, hwm_price=120.0, current_close=95.0, entry_open=100.0)
    assert v4_exit_decision(**kwargs, fast_state="UNAVAILABLE")[0] == "WINNER_HARD_EXIT"
    assert v4_exit_decision(**kwargs, fast_state="WATCH")[0] == "WINNER_HARD_EXIT"


def test_mfe_boundary_ownership() -> None:
    assert mfe_tier(49.999999)[2] == "MFE_20_TO_50"
    assert mfe_tier(50.0)[2] == "MFE_50_TO_100"
    assert mfe_tier(100.0)[2] == "MFE_100_TO_200"
    assert mfe_tier(200.0)[2] == "MFE_200_TO_400"
    assert mfe_tier(400.0)[2] == "MFE_400_PLUS"


def _integrity_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "control_trade_id": [f"T{i:04d}" for i in range(EXPECTED_TRADES)],
            "ticker": [f"{i % EXPECTED_UNIQUE_TICKERS:06d}" for i in range(EXPECTED_TRADES)],
            "entry_signal_date_match": [True] * EXPECTED_TRADES,
            "entry_execution_date_match": [True] * EXPECTED_TRADES,
            "entry_open_match": [True] * EXPECTED_TRADES,
            "v4_exit_execution_date": [None] * EXPECTED_TRADES,
        }
    )


def test_matched_integrity_fails_closed_on_entry_mismatch() -> None:
    frame = _integrity_frame()
    assert validate_matched_integrity(frame)["pass"] is True
    frame.loc[0, "entry_open_match"] = False
    with pytest.raises(AssertionError, match="entry identity mismatch"):
        validate_matched_integrity(frame)


def _gate_frame() -> pd.DataFrame:
    rows = []
    for i in range(EXPECTED_PRE_WINNER_COUNT):
        rows.append(
            {
                "full_path_mfe_cohort": "PRE_WINNER_LT_20",
                "v2_terminal_return": -20.0,
                "v4_terminal_return": -10.0,
                "v2_mfe": 5.0,
                "v4_strategy_path_mfe": 5.0,
                "v2_mae": -20.0,
                "v4_strategy_path_mae": -10.0,
                "v2_holding_days": 468.5,
                "v4_holding_days": 100.0,
                "v2_trade_status": "OPEN_AT_CUTOFF",
                "v4_trade_status": "REALIZED",
                "v2_giveback": 25.0,
                "v4_giveback": 15.0,
                "v4_exit_reason": "PRE_WINNER_PRICE_STRUCTURE_FAILURE",
            }
        )
    for i in range(737):
        rows.append(
            {
                "full_path_mfe_cohort": "WINNER_CAPABLE_GE_20",
                "v2_terminal_return": 120.0 if i == 0 else 60.0,
                "v4_terminal_return": 120.0 if i == 0 else 60.0,
                "v2_mfe": 130.0,
                "v4_strategy_path_mfe": 130.0,
                "v2_mae": -5.0,
                "v4_strategy_path_mae": -5.0,
                "v2_holding_days": 20.0,
                "v4_holding_days": 20.0,
                "v2_trade_status": "REALIZED",
                "v4_trade_status": "REALIZED",
                "v2_giveback": 10.0,
                "v4_giveback": 10.0,
                "v4_exit_reason": "WINNER_HARD_EXIT",
            }
        )
    return pd.DataFrame(rows)


def test_repair_gates_are_mechanical() -> None:
    v3_summary = {
        "pre_winner": {
            "v3": {
                "tail_le_30_rate_pct": PRE_WINNER_BASELINE["tail_le_30_count"] / 236 * 100,
                "tail_le_40_rate_pct": PRE_WINNER_BASELINE["tail_le_40_count"] / 236 * 100,
                "median_holding_days": PRE_WINNER_BASELINE["median_holding_days"],
                "open_at_cutoff_rate_pct": 100.0,
            }
        }
    }
    gates = evaluate_repair_gates(_gate_frame(), v3_summary)
    assert gates["pre_winner_repair"]["decision"] == "PRE_WINNER_REPAIR_PASS"
    assert gates["winner_tail_repair"]["decision"] == "WINNER_TAIL_REPAIR_PASS"
    assert WINNER_TAIL_BASELINE["v2_ge_50_v3_lt_50_count"] == 133


def _positive_robustness() -> pd.DataFrame:
    rows = [
        {"dimension": "market", "group": group, "mean_paired_v4_minus_v2_delta": 1.0}
        for group in ("KOSPI", "KOSDAQ")
    ]
    rows.extend(
        {"dimension": "entry_type", "group": group, "mean_paired_v4_minus_v2_delta": 1.0}
        for group in ("FIRST_ENTRY", "REENTRY")
    )
    rows.extend(
        {"dimension": "entry_year", "group": str(year), "mean_paired_v4_minus_v2_delta": 1.0}
        for year in (2021, 2022, 2023, 2024)
    )
    return pd.DataFrame(rows)


def _passing_stats() -> tuple[dict, dict, dict, dict]:
    v2 = {
        "mean_terminal_return_pct": 10.0,
        "median_terminal_return_pct": 5.0,
        "tail_le_30_rate_pct": 20.0,
        "tail_le_40_rate_pct": 10.0,
        "median_holding_days": 100.0,
        "open_at_cutoff_rate_pct": 20.0,
        "winner_ge_50_count": 100,
        "winner_ge_100_count": 40,
        "mean_giveback": 20.0,
        "median_giveback": 15.0,
    }
    v4 = {
        "mean_terminal_return_pct": 11.0,
        "median_terminal_return_pct": 5.0,
        "tail_le_30_rate_pct": 19.0,
        "tail_le_40_rate_pct": 9.0,
        "median_holding_days": 99.0,
        "open_at_cutoff_rate_pct": 19.0,
        "winner_ge_50_count": 101,
        "winner_ge_100_count": 40,
        "mean_giveback": 19.0,
        "median_giveback": 14.0,
    }
    paired = {"mean_delta": 1.0, "median_delta": 0.0}
    gates = {"pre_winner_repair": {"pass": True}, "winner_tail_repair": {"pass": True}}
    return v2, v4, paired, gates


def test_paths_risk_block_and_official_eligibility_are_mechanical() -> None:
    v2, v4, paired, gates = _passing_stats()
    decision = evaluate_preregistered_criteria(v2, v4, paired, _positive_robustness(), True, gates)
    assert decision["path_a_return_improvement"]["pass"] is True
    assert decision["path_b_winner_preservation"]["pass"] is True
    assert decision["path_c_giveback_improvement"]["pass"] is True
    assert decision["official_adoption_risk_block"] is False
    assert decision["official_adoption_eligible"] is True
    assert decision["default_promotion_eligible"] is True

    blocked_v4 = {**v4, "tail_le_30_rate_pct": 21.0, "tail_le_40_rate_pct": 11.0, "median_holding_days": 101.0, "open_at_cutoff_rate_pct": 21.0}
    blocked = evaluate_preregistered_criteria(v2, blocked_v4, paired, _positive_robustness(), True, gates)
    assert blocked["official_adoption_risk_block"] is True
    assert blocked["official_adoption_eligible"] is False


def test_official_eligibility_fails_closed_on_integrity_failure() -> None:
    v2, v4, paired, gates = _passing_stats()
    decision = evaluate_preregistered_criteria(v2, v4, paired, _positive_robustness(), False, gates)
    assert decision["official_adoption_eligible"] is False
    assert decision["default_promotion_eligible"] is False


def test_robustness_requirement_needs_all_required_groups_and_half_years() -> None:
    v2, v4, paired, gates = _passing_stats()
    robustness = _positive_robustness()
    robustness.loc[robustness["group"] == "KOSDAQ", "mean_paired_v4_minus_v2_delta"] = -0.01
    decision = evaluate_preregistered_criteria(v2, v4, paired, robustness, True, gates)
    assert decision["default_promotion_robustness"]["market"] is False
    assert decision["default_promotion_eligible"] is False


def test_representative_case_tie_break_is_deterministic() -> None:
    base = {
        "ticker": "000001",
        "name": "A",
        "market": "KOSPI",
        "isu_cd": "ISU1",
        "control_trade_id": "T2",
        "control_trade_sequence": 1,
        "entry_signal_date": "2021-04-01",
        "entry_execution_date": "2021-04-02",
        "entry_open": 100.0,
        "full_path_raw_mfe": 10.0,
        "full_path_mfe_cohort": "PRE_WINNER_LT_20",
        "v2_exit_category": "OPEN_AT_CUTOFF",
        "v2_terminal_return": -20.0,
        "v2_mfe": 10.0,
        "v2_mae": -20.0,
        "v2_holding_days": 10,
        "v2_giveback": 30.0,
        "v3_exit_reason": "OPEN_AT_CUTOFF",
        "v3_terminal_return": -20.0,
        "v4_exit_reason": "PRE_WINNER_PRICE_STRUCTURE_FAILURE",
        "v4_terminal_return": -10.0,
        "v4_strategy_path_mfe": 10.0,
        "v4_strategy_path_mae": -10.0,
        "v4_holding_days": 5,
        "v4_giveback": 20.0,
        "return_delta_v4_minus_v2": 10.0,
    }
    other = {**base, "control_trade_id": "T1", "ticker": "000000"}
    frame = pd.DataFrame([base, other])
    first = build_representative_cases(frame, limit=2)
    second = build_representative_cases(frame, limit=2)
    assert first.equals(second)
    reduced = first[first["case_type"] == "PRE_WINNER_EXIT_REDUCED_LARGE_LOSS"]
    assert reduced.iloc[0]["control_trade_id"] == "T1"
