"""Phase 13G-2 research-prototype contracts (no production rules)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pandas as pd


BASE = "4fc5f9d11c23cd96703c5b066d5f60200fb41703"
R = Path("artifacts/pattern_a_fast/research")
SCRIPT = Path("scripts/research_pattern_a_fast_score_stage_prototype.py")


def _module():
    spec = importlib.util.spec_from_file_location("prototype", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _calibration():
    return pd.read_csv(R / "pattern_a_fast_calibration_score_prototype_v01.csv", dtype={"ticker": str})


def test_frozen_13g1_inputs_and_labeled_population_are_preserved():
    registry = pd.read_csv(R / "pattern_a_fast_feature_role_registry_v01.csv")
    selected = pd.read_csv(R / "pattern_a_fast_selected_feature_matrix_v01.csv")
    calibration = _calibration()
    assert len(registry) == 21
    assert len(selected) == len(calibration) == 40
    assert selected.sample_id.nunique() == calibration.sample_id.nunique() == 40
    assert not (calibration.human_label == "UNLABELED").any()
    assert set(calibration.sample_id) == set(selected.sample_id)


def test_score_inputs_exclude_drop_hold_and_diagnostics():
    source = SCRIPT.read_text(encoding="utf-8")
    for feature in ("close_vs_ma24_pct", "higher_daily_low_count_10d", "recent_3m_return", "rolling_low_4w_change", "close_vs_dma200_pct", "dma20_vs_dma60_pct", "gap_from_prev_close_pct", "lower_wick_pct"):
        assert f"row.{feature}" not in source


def test_stage_is_weekly_only_and_score_stage_are_independent():
    mod = _module()
    source = SCRIPT.read_text(encoding="utf-8")
    stage_source = source[source.index("def stage"):source.index("def candidates")]
    assert "human_label" not in stage_source and "weekly_stage_at_reference" not in stage_source
    assert "monthly_permission_score" not in stage_source and "daily_timing" not in stage_source
    row = pd.Series(dict(close_vs_wma200_pct=0.1,distance_to_prior_26w_high_pct=-0.05,higher_weekly_low_count_13w=6,wma52_slope_1w=.01,wma12_vs_wma26_pct=.02,weeks_since_26w_close_breakout=8))
    assert mod.stage(row) == mod.stage(row)  # current snapshot only; no previous-stage argument exists


def test_missing_semantics_are_safe_and_not_silent_zero():
    mod = _module()
    row = pd.Series(dict(close_vs_wma200_pct=float("nan"),distance_to_prior_26w_high_pct=-.05,higher_weekly_low_count_13w=6,wma52_slope_1w=.01,wma12_vs_wma26_pct=.02,post_breakout_min_low_vs_level_pct_26w=float("nan")))
    weekly_score, weekly_status = mod.weekly(row)
    conditional_status, conditional_score = mod.conditional(row)
    assert weekly_status == "PARTIAL" and pd.notna(weekly_score)
    assert conditional_status == "EVENT_NOT_OBSERVED" and pd.isna(conditional_score)


def test_non_monotonic_monthly_and_daily_risk_invariants():
    mod = _module()
    def month(position): return mod.monthly(pd.Series(dict(range_position_24m=position,monthly_down_month_ratio_12m=.4)))[1]
    assert month(.5) > month(.1) and month(.5) > month(.95)
    low = pd.Series(dict(recent_5d_max_gap_abs_pct=.01,atr_14_pct=.01))
    high = pd.Series(dict(recent_5d_max_gap_abs_pct=.10,atr_14_pct=.10))
    assert mod.daily_risk(high)[1] > mod.daily_risk(low)[1]
    assert mod.aggregate(70,70,float("nan"),mod.daily_risk(high)[1]) < mod.aggregate(70,70,float("nan"),mod.daily_risk(low)[1])


def test_artifacts_are_bounded_and_explicitly_not_production():
    thresholds = pd.read_csv(R / "pattern_a_fast_threshold_candidates_v01.csv")
    assert (thresholds.production_frozen == "NO").all()
    assert thresholds.groupby("feature_name").size().max() <= 3
    score = json.loads((R / "pattern_a_fast_score_prototype_v01.json").read_text())
    stage = json.loads((R / "pattern_a_fast_stage_prototype_v01.json").read_text())
    assert score["production_frozen"] is False and stage["production_frozen"] is False
    assert stage["stage_semantics"] == ["WATCH","SETUP","TRIGGER","TREND","EXTENDED"]
    assert stage["stage_only_semantic_markers"] == ["weeks_since_26w_close_breakout"]


def test_frozen_files_and_prohibited_dependencies_remain_untouched():
    frozen = ["artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv","artifacts/pattern_a_fast/research/pattern_a_fast_feature_role_registry_v01.csv","artifacts/pattern_a_fast/research/pattern_a_fast_selected_feature_matrix_v01.csv"]
    diff = subprocess.run(["git","diff","--name-only",BASE,"--",*frozen],check=True,capture_output=True,text=True)
    assert diff.stdout == ""
    source = SCRIPT.read_text(encoding="utf-8")
    for forbidden in ("load_raw_daily","ParquetCache","sklearn","requests","urllib","optuna"):
        assert forbidden not in source
