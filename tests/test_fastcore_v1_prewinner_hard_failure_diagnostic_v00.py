"""Focused regression tests for the V00 FIX01 interpretation correction."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts import analyze_fastcore_v1_prewinner_hard_failure_diagnostic_v00 as diagnostic


ROOT = Path(__file__).resolve().parents[1]
OUT = diagnostic.FIX01_OUT_DIR
V00_OUT = diagnostic.V00_OUT_DIR


def _synthetic_row() -> dict[str, object]:
    return {
        "ticker": "000001",
        "name": "TEST",
        "market": "KOSPI",
        "isu_cd": "KR7000000001",
        "control_trade_id": "TEST_CONTROL_01",
        "control_trade_sequence": 1,
        "entry_execution_date": "2021-04-01",
        "entry_open": 100.0,
        "identity_effective_from": "2021-04-01",
        "identity_effective_to": "2026-08-21",
        "v0_mfe": 0.0,
        "v0_terminal_return": -40.0,
        "v0_holding_days": 100,
        "v2_exit_reason": "TEST",
    }


def _daily(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close"],
    ).assign(date=lambda frame: pd.to_datetime(frame["date"])).set_index("date")


def test_fixed_counts() -> None:
    trades = pd.read_csv(OUT / "prewinner_trade_diagnostics.csv")
    assert len(trades) == 973
    assert trades["recovery_class"].value_counts().to_dict() == {
        "RECOVERY": 737,
        "NEVER_WINNER": 236,
    }
    loss_guard = trades[trades["v2_exit_reason"] == diagnostic.LOSS_GUARD_REASON]
    assert len(loss_guard) == 590
    assert loss_guard["recovery_class"].value_counts().to_dict() == {
        "RECOVERY": 387,
        "NEVER_WINNER": 203,
    }


def test_first_mfe20_same_day_is_excluded_from_prewinner() -> None:
    row = _synthetic_row()
    daily = _daily(
        [
            ("2021-04-01", 100.0, 100.0, 100.0, 100.0),
            ("2021-04-02", 100.0, 120.0001, 60.0, 70.0),
            ("2021-04-05", 100.0, 105.0, 95.0, 100.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    assert path["recovery_class"] == "RECOVERY"
    assert path["first_mfe20_date"] == "2021-04-02"
    assert path["days_to_first_mfe20"] == 1
    assert path["prewinner_end_date"] == "2021-04-01"
    assert path["prewinner_min_close_return_pct"] == 0.0
    impact = diagnostic._threshold_impact(row, path, -30, daily)
    assert impact["prewinner_breach"] is False
    assert impact["hard_failure_exit_date"] is None


def test_close_is_trigger_and_low_is_not() -> None:
    row = _synthetic_row()
    daily = _daily(
        [
            ("2021-04-01", 100.0, 100.0, 100.0, 100.0),
            ("2021-04-02", 100.0, 100.0, 65.0, 80.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    assert path["prewinner_min_low_return_pct"] == -35.0
    assert path["prewinner_min_close_return_pct"] == -20.0
    impact = diagnostic._threshold_impact(row, path, -30, daily)
    assert impact["prewinner_breach"] is False


def test_breach_executes_at_next_local_open() -> None:
    row = _synthetic_row()
    daily = _daily(
        [
            ("2021-04-01", 100.0, 100.0, 100.0, 100.0),
            ("2021-04-02", 100.0, 100.0, 70.0, 70.0),
            ("2021-04-05", 65.0, 70.0, 60.0, 66.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    impact = diagnostic._threshold_impact(row, path, -30, daily)
    assert impact["prewinner_breach"] is True
    assert impact["prewinner_breach_date"] == "2021-04-02"
    assert impact["hard_failure_exit_date"] == "2021-04-05"
    assert impact["hard_failure_exit_return"] == -35.0


def test_threshold_breach_counts_are_monotonic() -> None:
    sweep = pd.read_csv(OUT / "prewinner_threshold_sweep.csv")
    assert sweep["threshold_pct"].tolist() == list(diagnostic.THRESHOLDS)
    for column in ("recovery_breach_count", "never_winner_breach_count"):
        assert sweep[column].diff().dropna().le(0).all()


def test_retrospective_label_does_not_change_breach_or_execution() -> None:
    row = _synthetic_row()
    daily = _daily(
        [
            ("2021-04-01", 100.0, 100.0, 100.0, 100.0),
            ("2021-04-02", 100.0, 100.0, 70.0, 70.0),
            ("2021-04-05", 65.0, 70.0, 60.0, 66.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    relabeled = dict(path)
    relabeled["recovery_class"] = "RECOVERY"
    original = diagnostic._threshold_impact(row, path, -30, daily)
    changed_label = diagnostic._threshold_impact(row, relabeled, -30, daily)
    for field in (
        "prewinner_breach",
        "prewinner_breach_date",
        "next_local_open_available",
        "hard_failure_exit_date",
        "hard_failure_exit_return",
    ):
        assert original[field] == changed_label[field]


def test_corrected_conclusion_is_not_a_candidate_threshold() -> None:
    summary = json.loads((OUT / "prewinner_hard_failure_summary.json").read_text())
    report = (OUT / "fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix01_report.md").read_text()
    assert summary["hard_failure_threshold_identified"] is False
    assert summary["hard_failure_candidate_threshold_pct"] is None
    assert summary["fixed_threshold_mean_improvement_count"] == 0
    assert summary["failure_armed_price_damage_research_region_pct"] == [-25, -30]
    assert summary["failure_armed_region_is_strategy_parameter"] is False
    assert "candidate_threshold_pct" not in summary
    assert "adjacent_candidate_thresholds_pct" not in summary
    assert "V1 backtest candidate threshold: -30%" not in report


def test_key_sweep_invariants_are_preserved() -> None:
    sweep = pd.read_csv(OUT / "prewinner_threshold_sweep.csv")
    v0 = sweep.iloc[0]
    minus_30 = sweep[sweep["threshold_pct"] == -30].iloc[0]
    assert v0["baseline_v0_positive_rate_pct"] == 70.914697
    assert v0["baseline_v0_mean_terminal_return_pct"] == 8.666341
    assert v0["baseline_v0_median_terminal_return_pct"] == 9.2
    assert minus_30["recovery_killed_rate_pct"] == 16.010855
    assert minus_30["failed_trade_captured_rate_pct"] == 75.847458
    assert minus_30["hypothetical_positive_rate_pct"] == 60.226105
    assert minus_30["hypothetical_mean_terminal_return_pct"] == 5.261881
    assert minus_30["hypothetical_median_terminal_return_pct"] == 6.57


def test_fix01_preserves_v00_calculation_artifacts() -> None:
    for name in (
        "prewinner_trade_diagnostics.csv",
        "prewinner_drawdown_distribution.csv",
        "prewinner_threshold_sweep.csv",
        "prewinner_threshold_trade_impacts.csv",
    ):
        left = pd.read_csv(V00_OUT / name)
        right = pd.read_csv(OUT / name)
        pd.testing.assert_frame_equal(left, right, check_dtype=False)
