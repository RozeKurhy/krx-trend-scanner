"""Focused regression tests for the V00 FIX03 lifecycle execution correction."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from scripts import analyze_fastcore_v1_prewinner_hard_failure_diagnostic_v00 as diagnostic


ROOT = Path(__file__).resolve().parents[1]
OUT = diagnostic.FIX03_OUT_DIR


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


def _dated_row(entry_date: str = "2026-08-10", effective_to: str = "2026-08-21") -> dict[str, object]:
    row = _synthetic_row()
    row.update(
        entry_execution_date=entry_date,
        identity_effective_from=entry_date,
        identity_effective_to=effective_to,
    )
    return row


def _daily(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        rows,
        columns=["date", "open", "high", "low", "close"],
    ).assign(date=lambda frame: pd.to_datetime(frame["date"])).set_index("date")


def test_fixed_counts_partition_and_horizon_invariants() -> None:
    summary = json.loads((OUT / "prewinner_hard_failure_summary.json").read_text())
    trades = pd.read_csv(OUT / "prewinner_trade_diagnostics.csv")
    assert len(trades) == 973
    assert summary["recovery_count"] + summary["never_winner_count"] == 973
    assert summary["recovery_count"] == int((trades["recovery_class"] == "RECOVERY").sum())
    assert summary["never_winner_count"] == int((trades["recovery_class"] == "NEVER_WINNER").sum())

    loss_guard = trades[trades["v2_exit_reason"] == diagnostic.LOSS_GUARD_REASON]
    assert len(loss_guard) == 590
    assert summary["loss_guard_recovery_count"] + summary["loss_guard_never_winner_count"] == 590
    assert summary["loss_guard_recovery_count"] == int((loss_guard["recovery_class"] == "RECOVERY").sum())
    assert summary["loss_guard_never_winner_count"] == int((loss_guard["recovery_class"] == "NEVER_WINNER").sum())

    assert summary["prewinner_observation_end"] == "2026-08-21"
    assert pd.to_datetime(trades["prewinner_end_date"].dropna()).le(pd.Timestamp("2026-08-21")).all()
    first_mfe20 = pd.to_datetime(trades["first_mfe20_date"].dropna())
    assert first_mfe20.le(pd.Timestamp("2026-08-21")).all()


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


def test_post_signal_cutoff_prewinner_observation_and_next_open() -> None:
    row = _dated_row()
    daily = _daily(
        [
            ("2026-08-10", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-14", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-17", 100.0, 100.0, 70.0, 70.0),
            ("2026-08-18", 65.0, 70.0, 60.0, 66.0),
            ("2026-08-21", 66.0, 70.0, 60.0, 65.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    assert path["recovery_class"] == "NEVER_WINNER"
    assert path["prewinner_end_date"] == "2026-08-21"
    assert any(item["date"].strftime("%Y-%m-%d") == "2026-08-17" for item in path["_prewinner_observations"])

    impact = diagnostic._threshold_impact(row, path, -30, daily)
    assert impact["prewinner_breach"] is True
    assert impact["prewinner_breach_date"] == "2026-08-17"
    assert impact["hard_failure_exit_date"] == "2026-08-18"
    assert impact["hard_failure_exit_return"] == -35.0


def test_post_signal_cutoff_recovery_excludes_first_mfe20_day() -> None:
    row = _dated_row()
    daily = _daily(
        [
            ("2026-08-10", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-14", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-17", 100.0, 120.0001, 70.0, 70.0),
            ("2026-08-18", 100.0, 105.0, 95.0, 100.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    assert path["recovery_class"] == "RECOVERY"
    assert path["first_mfe20_date"] == "2026-08-17"
    assert path["prewinner_end_date"] == "2026-08-14"
    assert all(item["date"].strftime("%Y-%m-%d") != "2026-08-17" for item in path["_prewinner_observations"])


def test_support_end_breach_without_next_open_is_not_executable() -> None:
    row = _dated_row()
    daily = _daily(
        [
            ("2026-08-10", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-14", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-21", 100.0, 100.0, 70.0, 70.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    impact = diagnostic._threshold_impact(row, path, -30, daily)
    assert impact["prewinner_breach"] is True
    assert impact["prewinner_breach_date"] == "2026-08-21"
    assert impact["next_local_open_available"] is False
    assert impact["hard_failure_exit_date"] is None
    assert impact["hard_failure_exit_return"] is None
    assert impact["recovery_killed"] is False
    assert impact["failed_trade_captured"] is False


def test_identity_lifecycle_end_blocks_ticker_level_next_open() -> None:
    row = _dated_row(entry_date="2026-08-19", effective_to="2026-08-20")
    daily = _daily(
        [
            ("2026-08-19", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-20", 100.0, 100.0, 70.0, 70.0),
            ("2026-08-21", 65.0, 70.0, 60.0, 66.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    impact = diagnostic._threshold_impact(row, path, -30, daily)
    assert impact["prewinner_breach"] is True
    assert impact["prewinner_breach_date"] == "2026-08-20"
    assert impact["next_local_open_available"] is False
    assert impact["hard_failure_exit_date"] is None
    assert impact["hard_failure_exit_return"] is None
    assert impact["recovery_killed"] is False
    assert impact["failed_trade_captured"] is False


def test_identity_lifecycle_allows_next_open_inside_boundary() -> None:
    row = _dated_row(entry_date="2026-08-19", effective_to="2026-08-21")
    daily = _daily(
        [
            ("2026-08-19", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-20", 100.0, 100.0, 70.0, 70.0),
            ("2026-08-21", 65.0, 70.0, 60.0, 66.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    impact = diagnostic._threshold_impact(row, path, -30, daily)
    assert impact["prewinner_breach"] is True
    assert impact["next_local_open_available"] is True
    assert impact["hard_failure_exit_date"] == "2026-08-21"
    assert impact["hard_failure_exit_return"] == -35.0


def test_no_observation_after_support_end() -> None:
    row = _dated_row(effective_to="2026-08-24")
    daily = _daily(
        [
            ("2026-08-10", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-14", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-21", 100.0, 100.0, 100.0, 100.0),
            ("2026-08-24", 100.0, 130.0, 95.0, 125.0),
        ]
    )
    path = diagnostic._prewinner_path(row, daily)
    assert path["recovery_class"] == "NEVER_WINNER"
    assert path["first_mfe20_date"] is None
    assert path["prewinner_end_date"] == "2026-08-21"
    assert all(item["date"] <= pd.Timestamp("2026-08-21") for item in path["_prewinner_observations"])


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
    assert pd.Timestamp(impact["hard_failure_exit_date"]) <= diagnostic.v3.SUPPORT_END


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
    report = (OUT / "fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix03_report.md").read_text()
    assert summary["hard_failure_threshold_identified"] is False
    assert summary["hard_failure_candidate_threshold_pct"] is None
    assert summary["fixed_threshold_mean_improvement_count"] == sum(
        float(row["hypothetical_mean_terminal_return_pct"]) > float(row["baseline_v0_mean_terminal_return_pct"])
        for row in summary["threshold_sweep_records"]
    )
    assert summary["failure_armed_price_damage_research_region_pct"] == [-25, -30]
    assert summary["failure_armed_region_is_strategy_parameter"] is False
    assert summary["prewinner_observation_end"] == "2026-08-21"
    assert "SUPPORT_END" in summary["prewinner_definition"]
    assert "candidate_threshold_pct" not in summary
    assert "adjacent_candidate_thresholds_pct" not in summary
    assert "V1 backtest candidate threshold: -30%" not in report
    assert "FIX02 → FIX03 lifecycle execution boundary correction impact" in report


def test_key_sweep_invariants_are_preserved() -> None:
    sweep = pd.read_csv(OUT / "prewinner_threshold_sweep.csv")
    v0 = sweep.iloc[0]
    assert v0["baseline_v0_positive_rate_pct"] == 70.914697
    assert v0["baseline_v0_mean_terminal_return_pct"] == 8.666341
    assert v0["baseline_v0_median_terminal_return_pct"] == 9.2
    summary = json.loads((OUT / "prewinner_hard_failure_summary.json").read_text())
    assert sweep["hypothetical_mean_terminal_return_pct"].gt(v0["baseline_v0_mean_terminal_return_pct"]).sum() == summary[
        "fixed_threshold_mean_improvement_count"
    ]


def test_fix03_reports_fix02_lifecycle_deltas() -> None:
    summary = json.loads((OUT / "prewinner_hard_failure_summary.json").read_text())
    fix02 = json.loads((diagnostic.FIX02_OUT_DIR / "prewinner_hard_failure_summary.json").read_text())
    comparison = summary["fix02_comparison"]
    assert comparison["recovery_count_delta"] == summary["recovery_count"] - fix02["recovery_count"]
    assert comparison["never_winner_count_delta"] == summary["never_winner_count"] - fix02["never_winner_count"]
    assert comparison["loss_guard_recovery_count_delta"] == summary["loss_guard_recovery_count"] - fix02["loss_guard_recovery_count"]
    assert comparison["loss_guard_never_winner_count_delta"] == summary["loss_guard_never_winner_count"] - fix02["loss_guard_never_winner_count"]
    assert comparison["fixed_threshold_mean_improvement_count_fix02"] == fix02["fixed_threshold_mean_improvement_count"]
    assert comparison["fixed_threshold_mean_improvement_count_fix03"] == summary["fixed_threshold_mean_improvement_count"]
    assert len(comparison["threshold_sweep_deltas"]) == len(diagnostic.THRESHOLDS)
    assert len(comparison["threshold_changed_execution_counts"]) == len(diagnostic.THRESHOLDS)


def test_fix03_writes_a_distinct_artifact_set() -> None:
    expected = {
        "prewinner_trade_diagnostics.csv",
        "prewinner_drawdown_distribution.csv",
        "prewinner_threshold_sweep.csv",
        "prewinner_threshold_trade_impacts.csv",
        "prewinner_hard_failure_summary.json",
        "fastcore_v1_prewinner_hard_failure_diagnostic_v00_fix03_report.md",
    }
    assert {path.name for path in OUT.iterdir()} == expected
    assert OUT != diagnostic.V00_OUT_DIR
    assert OUT != diagnostic.FIX01_OUT_DIR
    assert OUT != diagnostic.FIX02_OUT_DIR
