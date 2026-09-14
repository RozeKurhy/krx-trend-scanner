"""Focused tests for the official FastCore V3 matched A/B runner."""

from __future__ import annotations

import pandas as pd
import pytest

from scripts import run_fastcore_v3_matched_ab_official_v01 as official


def _side(mean_return: float, median_return: float, tail30: float, tail40: float, winner50: int, winner100: int, holding: float, open_rate: float, mean_giveback: float, median_giveback: float) -> dict[str, float | int]:
    return {
        "mean_terminal_return_pct": mean_return,
        "median_terminal_return_pct": median_return,
        "tail_le_30_rate_pct": tail30,
        "tail_le_40_rate_pct": tail40,
        "winner_ge_50_count": winner50,
        "winner_ge_100_count": winner100,
        "median_holding_days": holding,
        "open_at_cutoff_rate_pct": open_rate,
        "mean_giveback": mean_giveback,
        "median_giveback": median_giveback,
    }


def _robustness() -> pd.DataFrame:
    return pd.DataFrame([
        {"dimension": "market", "group": "KOSPI", "trade_count": 10, "mean_paired_return_delta": 0.1, "median_paired_return_delta": 0.0},
        {"dimension": "market", "group": "KOSDAQ", "trade_count": 10, "mean_paired_return_delta": 0.2, "median_paired_return_delta": 0.0},
        {"dimension": "entry_type", "group": "FIRST_ENTRY", "trade_count": 10, "mean_paired_return_delta": 0.1, "median_paired_return_delta": 0.0},
        {"dimension": "entry_type", "group": "REENTRY", "trade_count": 10, "mean_paired_return_delta": 0.2, "median_paired_return_delta": 0.0},
        {"dimension": "entry_year", "group": "2021", "trade_count": 10, "mean_paired_return_delta": 0.1, "median_paired_return_delta": 0.0},
        {"dimension": "entry_year", "group": "2022", "trade_count": 10, "mean_paired_return_delta": 0.2, "median_paired_return_delta": 0.0},
        {"dimension": "entry_year", "group": "2023", "trade_count": 10, "mean_paired_return_delta": -0.1, "median_paired_return_delta": 0.0},
    ])


def test_full_path_mfe_boundary_is_fixed_at_20_percent() -> None:
    assert official.classify_full_path_mfe(19.999999) == "PRE_WINNER_LT_20"
    assert official.classify_full_path_mfe(20.0) == "WINNER_CAPABLE_GE_20"


def test_preregistered_paths_and_risk_block_are_mechanical() -> None:
    v2 = _side(1.0, 0.0, 5.0, 1.0, 100, 50, 10.0, 5.0, 20.0, 15.0)
    v3 = _side(2.0, 0.0, 6.0, 2.0, 101, 50, 11.0, 6.0, 19.0, 14.0)
    paired = {"mean_delta": 1.0, "median_delta": 0.0}
    decision = official.evaluate_preregistered_criteria(v2, v3, paired, _robustness(), True)
    assert decision["path_a_return_improvement"]["pass"] is True
    assert decision["path_b_winner_preservation"]["pass"] is True
    assert decision["path_c_giveback_improvement"]["pass"] is True
    assert decision["performance_improvement_pass"] is True
    assert decision["large_loss_area_worsened"] is True
    assert decision["capital_lock_area_worsened"] is True
    assert decision["official_strategy_risk_block"] is True
    assert decision["official_adoption_eligible_by_preregistered_criteria"] is False


def test_default_promotion_criterion_8_requires_all_decompositions() -> None:
    v2 = _side(1.0, 0.0, 5.0, 1.0, 100, 50, 10.0, 5.0, 20.0, 15.0)
    v3 = _side(1.0, 0.0, 5.0, 1.0, 101, 50, 10.0, 5.0, 19.0, 14.0)
    paired = {"mean_delta": 0.0, "median_delta": 0.0}
    decision = official.evaluate_preregistered_criteria(v2, v3, paired, _robustness(), True)
    assert decision["default_promotion_robustness"] == {"market": True, "entry_type": True, "entry_year": True}
    assert decision["default_promotion_criteria"]["criterion_8_robustness"] is True
    assert decision["default_promotion_eligible_by_preregistered_criteria"] is True


def test_matched_integrity_fails_closed_on_entry_mismatch() -> None:
    frame = pd.DataFrame([
        {
            "control_trade_id": "T1",
            "ticker": "000001",
            "entry_signal_date_match": True,
            "entry_execution_date_match": False,
            "entry_open_match": True,
        }
    ])
    with pytest.raises(AssertionError):
        official.validate_matched_integrity(frame)


def test_representative_case_tie_breaker_is_deterministic() -> None:
    rows = []
    for ticker in ("000002", "000001"):
        rows.append({
            "ticker": ticker,
            "name": ticker,
            "market": "KOSPI",
            "isu_cd": f"ISU{ticker}",
            "control_trade_id": f"T{ticker}",
            "control_trade_sequence": 1,
            "identity_effective_from": "2021-01-01",
            "identity_effective_to": "2026-08-21",
            "entry_signal_date": "2021-04-02",
            "entry_execution_date": "2021-04-05",
            "entry_open": 100.0,
            "v2_exit_category": "LOSS_GUARD",
            "v2_terminal_return": -10.0,
            "v2_mfe": 1.0,
            "v2_mae": -10.0,
            "v2_holding_days": 3,
            "v2_giveback": 11.0,
            "v3_exit_reason": "OPEN_AT_CUTOFF",
            "v3_terminal_return": -10.0,
            "v3_strategy_path_mfe": 1.0,
            "v3_strategy_path_mae": -10.0,
            "v3_holding_days": 3,
            "v3_giveback": 11.0,
            "full_path_raw_mfe": 10.0,
            "full_path_mfe_cohort": "PRE_WINNER_LT_20",
            "return_delta_v3_minus_v2": 0.0,
        })
    result = official.build_representative_cases(pd.DataFrame(rows), limit=2)
    assert result[result["case_type"] == "PRE_WINNER_WORST_TERMINAL_RETURN"]["ticker"].tolist() == ["000001", "000002"]
