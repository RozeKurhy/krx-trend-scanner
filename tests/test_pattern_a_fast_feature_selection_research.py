"""Phase 13G-1 research-selection artifact contracts.

These tests verify that the new artifacts only assign candidate roles from the
frozen Phase 13C--13F evidence.  They intentionally do not test a score,
threshold, classifier, entry, or production integration because none exists
in this phase.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd


BASE_COMMIT = "505c412f504dbb1a5a475e2562a0a1749eaa6508"
RESEARCH_DIR = Path("artifacts/pattern_a_fast/research")
REGISTRY = RESEARCH_DIR / "pattern_a_fast_feature_role_registry_v01.csv"
REDUNDANCY = RESEARCH_DIR / "pattern_a_fast_cross_timeframe_redundancy_v01.csv"
SELECTED_MATRIX = RESEARCH_DIR / "pattern_a_fast_selected_feature_matrix_v01.csv"
ARCHITECTURE = RESEARCH_DIR / "pattern_a_fast_candidate_architecture_v01.json"
SCRIPT = Path("scripts/research_pattern_a_fast_feature_selection.py")

MONTHLY = {
    "range_position_24m", "drawdown_from_12m_high", "close_vs_ma24_pct",
    "ma_alignment_score", "monthly_down_month_ratio_12m",
    "higher_monthly_low_count_12m", "recent_3m_return",
}
WEEKLY = {
    "post_breakout_min_low_vs_level_pct_26w", "close_vs_wma200_pct",
    "distance_to_prior_26w_high_pct", "higher_weekly_low_count_13w",
    "wma52_slope_1w", "wma12_vs_wma26_pct", "rolling_low_4w_change",
}
DAILY = {
    "close_vs_dma200_pct", "dma20_vs_dma60_pct",
    "recent_5d_max_gap_abs_pct", "higher_daily_low_count_10d",
    "gap_from_prev_close_pct", "lower_wick_pct", "atr_14_pct",
}
ROLE_ENUM = {
    "MONTHLY_PERMISSION", "WEEKLY_CORE", "DAILY_TIMING_RISK",
    "CONDITIONAL_STRUCTURE", "DIAGNOSTIC", "HOLD_RESEARCH", "DROP_REDUNDANT",
}
STATUS_ENUM = {"PRIMARY", "SECONDARY", "CONDITIONAL", "DIAGNOSTIC", "HOLD", "DROP"}


def _registry() -> pd.DataFrame:
    return pd.read_csv(REGISTRY, keep_default_na=False)


def _architecture() -> dict:
    return json.loads(ARCHITECTURE.read_text(encoding="utf-8"))


def _all_architecture_features(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        if "feature_name" in value:
            found.add(value["feature_name"])
        for child in value.values():
            found |= _all_architecture_features(child)
    elif isinstance(value, list):
        for child in value:
            found |= _all_architecture_features(child)
    return found


def _all_json_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        keys |= set(value)
        for child in value.values():
            keys |= _all_json_keys(child)
    elif isinstance(value, list):
        for child in value:
            keys |= _all_json_keys(child)
    return keys


def test_input_inventory_is_exactly_7_by_7_by_7_and_registry_is_21_rows():
    registry = _registry()
    assert len(MONTHLY) == len(WEEKLY) == len(DAILY) == 7
    assert len(registry) == 21
    assert set(registry.loc[registry.timeframe == "MONTHLY", "feature_name"]) == MONTHLY
    assert set(registry.loc[registry.timeframe == "WEEKLY", "feature_name"]) == WEEKLY
    assert set(registry.loc[registry.timeframe == "DAILY", "feature_name"]) == DAILY
    assert not registry.duplicated(["timeframe", "feature_name"]).any()


def test_registry_has_complete_allowed_role_and_status_assignments():
    registry = _registry()
    assert registry.candidate_role.notna().all()
    assert registry.selection_status.notna().all()
    assert set(registry.candidate_role) <= ROLE_ENUM
    assert set(registry.selection_status) <= STATUS_ENUM
    assert (registry.loc[registry.timeframe == "DAILY", "candidate_role"] == "MONTHLY_PERMISSION").sum() == 0
    assert (registry.loc[registry.timeframe == "MONTHLY", "candidate_role"] == "WEEKLY_CORE").sum() == 0
    assert (registry.loc[registry.timeframe == "WEEKLY", "selection_status"] == "PRIMARY").sum() > 0


def test_selected_matrix_is_40_unique_labeled_samples_and_matches_registry():
    registry = _registry()
    selected = pd.read_csv(SELECTED_MATRIX, keep_default_na=False)
    assert len(selected) == 40
    assert selected.sample_id.nunique() == 40
    assert not (selected.human_label == "UNLABELED").any()
    expected = set(registry.loc[registry.selection_status.isin({"PRIMARY", "SECONDARY", "CONDITIONAL"}), "feature_name"])
    assert expected <= set(selected.columns)
    assert set(registry.loc[registry.selection_status == "DROP", "feature_name"]).isdisjoint(selected.columns)
    feature_columns = selected.columns[6:]
    assert len(feature_columns) == len(set(feature_columns))


def test_event_missingness_and_architecture_hierarchy_are_preserved():
    registry = _registry().set_index("feature_name")
    breakout = registry.loc["post_breakout_min_low_vs_level_pct_26w"]
    assert breakout.event_conditioned == "YES"
    assert breakout.missing_semantics == "EVENT_NOT_OBSERVED"
    assert breakout.candidate_role == "CONDITIONAL_STRUCTURE"
    assert breakout.selection_status == "CONDITIONAL"
    assert (registry.loc[registry.timeframe == "DAILY", "candidate_role"] == "WEEKLY_CORE").sum() == 0

    architecture = _architecture()
    assert architecture["architecture_status"] == "CANDIDATE_ARCHITECTURE_COMPLETE_ADVISOR_REVIEW_PENDING"
    assert _all_architecture_features(architecture) == set(registry.index)
    assert {entry["feature_name"] for entry in architecture["daily_timing_features"]} == {
        "recent_5d_max_gap_abs_pct", "atr_14_pct"
    }


def test_cross_timeframe_redundancy_artifact_and_decisions_exist():
    redundancy = pd.read_csv(REDUNDANCY)
    assert len(redundancy) == 147
    assert set(redundancy.columns) == {
        "feature_a", "timeframe_a", "feature_b", "timeframe_b", "spearman_corr",
        "abs_corr", "semantic_overlap", "recommended_action", "notes",
    }
    assert (redundancy.timeframe_a != redundancy.timeframe_b).all()
    assert (redundancy.abs_corr >= 0).all()
    assert (redundancy.recommended_action == "STRONG_REDUNDANCY_REVIEWED").any()


def test_no_contract_fields_or_production_integration_are_introduced():
    architecture = _architecture()
    forbidden = {"threshold", "weight", "score", "stage", "buy", "sell", "optimal_entry"}
    assert forbidden.isdisjoint({key.lower() for key in _all_json_keys(architecture)})
    source = SCRIPT.read_text(encoding="utf-8")
    assert "load_raw_daily" not in source
    assert "ParquetCache" not in source
    assert "trend_scanner.pattern" not in source
    assert "requests" not in source
    assert "urllib" not in source


def test_frozen_inputs_are_unchanged_since_base_commit():
    frozen = [
        "artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv",
        "artifacts/pattern_a_fast/research/monthly_regime_feature_matrix_v01.csv",
        "artifacts/pattern_a_fast/research/weekly_trigger_feature_matrix_v01.csv",
        "artifacts/pattern_a_fast/research/daily_timing_feature_matrix_v01.csv",
    ]
    result = subprocess.run(
        ["git", "diff", "--name-only", BASE_COMMIT, "--", *frozen],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.stdout == ""
