"""Phase 13H contracts: PIT event semantics and frozen-input guards."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pandas as pd

from tests.helpers.frozen_integrity import PATTERN_A_EVALUATOR_SHA256, assert_file_sha256
from trend_scanner.validation.pattern_a_final_closure import EXPECTED_FROZEN_HASHES


BASE = "2da3fc36744b27ec13edae3f690df72c796906e5"
SCRIPT = Path("scripts/research_pattern_a_fast_lead_time_failure.py")
R = Path("artifacts/pattern_a_fast/research")
GT = Path("artifacts/pattern_a_fast/ground_truth")

# Unchanged since BASE; no separate hash authority for these two research
# artifacts existed before FIX_03.
SCORE_PROTOTYPE_SHA256 = "be0dc21c3764aeb147a3565e65850fc179ecc91e5700e8221932f12ce28ae501"
STAGE_PROTOTYPE_SHA256 = "231cb43e2830017a72a9e8ba8d29296749f8a323e211266035d80cf841b70cf7"
HUMAN_REVIEW_SOURCE_SHA256 = "ea71bd1850aa52479d5c09a9d54a45b4f43493147a2bd98a8e93e6ae0d6fed4c"
GROUND_TRUTH_SOURCE_SHA256 = "62f02794956ceac2edc08d8c5df2b44ad9e06ac98967d1d77e4572ecf2af0005"


def _module():
    spec = importlib.util.spec_from_file_location("lead_time", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _timeline(stages, active=None, pattern_status=None):
    active = active or [False] * len(stages)
    pattern_status = pattern_status or ["READY"] * len(stages)
    dates = pd.date_range("2025-01-03", periods=len(stages), freq="W-FRI")
    return pd.DataFrame({
        "ticker": "000001", "name": "synthetic", "weekly_date": dates.strftime("%Y-%m-%d"),
        "fast_machine_stage": stages, "fast_machine_stage_status": ["READY" if s is not None else "UNAVAILABLE" for s in stages],
        "pattern_a_candidate_active": active, "pattern_a_evaluation_status": pattern_status,
        "fast_score": 50.0, "fast_monthly_permission_state": "PERMITTED_REGIME", "fast_daily_risk_state": "NORMAL",
    })


def test_base_and_frozen_inputs_are_read_only():
    """TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_03: this used to
    `git diff --name-only BASE -- frozen` and assert empty output. That form
    fails the moment pattern_a_score.py/pattern_a_stage.py pick up *any*
    change since BASE, including the non-semantic docstring-path updates from
    the Docs IA reorganization (commit beafd30) -- which is exactly what
    happened here. Replaced with explicit sha256 checks: the 4 frozen
    artifacts and pattern_a_evaluator.py are confirmed unchanged since BASE
    (frozen at their current == historical content); pattern_a_score.py /
    pattern_a_stage.py reuse the existing `EXPECTED_FROZEN_HASHES` authority
    (pattern_a_final_closure.py) instead of a second hardcoded copy.
    """
    mod = _module()
    assert mod.BASE_SHA == BASE
    assert_file_sha256(R / "pattern_a_fast_score_prototype_v01.json", SCORE_PROTOTYPE_SHA256)
    assert_file_sha256(R / "pattern_a_fast_stage_prototype_v01.json", STAGE_PROTOTYPE_SHA256)
    assert_file_sha256(GT / "pattern_a_fast_human_review_v01.csv", HUMAN_REVIEW_SOURCE_SHA256)
    assert_file_sha256(GT / "pattern_a_fast_ground_truth_source_v01.csv", GROUND_TRUTH_SOURCE_SHA256)
    assert_file_sha256(Path("src/trend_scanner/patterns/pattern_a_evaluator.py"), PATTERN_A_EVALUATOR_SHA256)
    assert_file_sha256(Path("src/trend_scanner/patterns/pattern_a_score.py"), EXPECTED_FROZEN_HASHES["pattern_a_score.py"])
    assert_file_sha256(Path("src/trend_scanner/patterns/pattern_a_stage.py"), EXPECTED_FROZEN_HASHES["pattern_a_stage.py"])


def test_labeled_population_is_exactly_40_and_unlabeled_is_excluded():
    samples = _module().load_labeled_samples()
    assert len(samples) == samples.sample_id.nunique() == 40
    assert not (samples.human_label == "UNLABELED").any()
    assert samples.ticker.str.len().eq(6).all()


def test_fast_contract_reproduces_frozen_calibration_artifact():
    mod = _module()
    score, stage = mod.load_contracts()
    # This invokes the same JSON evaluator + PIT feature reconstruction used by
    # the script and fails on either score/status/stage mismatch.
    mod.reproduce_calibration(mod.load_labeled_samples(), score, stage)


def test_fast_stage_missing_required_input_is_unavailable_not_watch():
    mod = _module()
    score, stage = mod.load_contracts()
    base = {
        "range_position_24m": .5, "monthly_down_month_ratio_12m": .4,
        "close_vs_wma200_pct": 0.0, "distance_to_prior_26w_high_pct": -.05,
        "higher_weekly_low_count_13w": 6, "wma52_slope_1w": .01, "wma12_vs_wma26_pct": .02,
        "weeks_since_26w_close_breakout": np.nan, "post_breakout_min_low_vs_level_pct_26w": np.nan,
        "recent_5d_max_gap_abs_pct": .02, "atr_14_pct": .02,
    }
    for field in stage["required_stage_inputs"]:
        got = mod.evaluate_fast_contract({**base, field: np.nan}, score, stage)
        assert got["fast_machine_stage"] is None
        assert got["fast_machine_stage_status"] == "UNAVAILABLE"
    assert mod.evaluate_fast_contract({**base, "close_vs_wma200_pct": np.nan}, score, stage)["fast_machine_stage_status"] == "READY"


def test_fast_trigger_observation_and_direct_jump_semantics():
    mod = _module()
    observed = mod.annotate_event_statuses(_timeline(["WATCH", "SETUP", "TRIGGER", "TRIGGER", "TREND"]))
    assert observed.fast_trigger_event_status.tolist().count("OBSERVED") == 1
    direct = mod.annotate_event_statuses(_timeline(["SETUP", "TREND"]))
    assert set(direct.fast_trigger_event_status) == {"NOT_OBSERVED"}
    assert ("000001", direct.weekly_date.iloc[-1]) in mod.direct_jump_dates(direct)


def test_unavailable_to_trigger_is_left_censored_not_synthetic_event():
    mod = _module()
    frame = mod.annotate_event_statuses(_timeline([None, "TRIGGER"]))
    assert frame.fast_trigger_event_status.tolist() == ["NOT_OBSERVED", "LEFT_CENSORED"]


def test_pattern_a_event_requires_observed_inactive_to_active_transition():
    mod = _module()
    left = mod.annotate_event_statuses(_timeline(["WATCH", "WATCH"], [True, True]))
    assert left.pattern_a_candidate_event_status.tolist()[0] == "LEFT_CENSORED"
    entered = mod.annotate_event_statuses(_timeline(["WATCH", "WATCH"], [False, True]))
    assert entered.pattern_a_candidate_event_status.tolist() == ["NOT_OBSERVED", "OBSERVED"]


def test_conservative_pair_precedence_and_no_catchup_semantics():
    mod = _module()
    samples = pd.DataFrame({"ticker": ["000001"], "outcome_review_end": ["2025-12-26"]})

    # A: inactive at Fast, no earlier activity, later official event.
    later = mod.annotate_event_statuses(_timeline(["WATCH", "TRIGGER", "WATCH", "WATCH"], [False, False, True, True]))
    pairs = mod.build_pairs(later, samples)
    assert pairs.iloc[0].pair_status == "FAST_EARLIER_PATTERN_A_LATER"
    assert pairs.iloc[0].lead_days == 7 and pairs.iloc[0].lead_weeks == 1

    # B: current activity takes precedence over future event.
    active_now = mod.annotate_event_statuses(_timeline(["WATCH", "TRIGGER", "WATCH"], [True, True, True]))
    assert mod.build_pairs(active_now, samples).iloc[0].pair_status == "PATTERN_A_ALREADY_ACTIVE"

    # C: earlier observed activity excludes a currently inactive Fast event.
    prior_observed = mod.annotate_event_statuses(_timeline(["WATCH", "WATCH", "TRIGGER", "WATCH", "WATCH"], [False, True, False, False, True]))
    prior_pair = mod.build_pairs(prior_observed, samples).iloc[0]
    assert prior_pair.pair_status == "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT"
    assert prior_pair.pattern_a_was_active_before_fast_event == "YES"
    assert prior_pair.pattern_a_prior_candidate_event_date == "2025-01-10"

    # D: left-censored active history is also prior activity.
    prior_left_censored = mod.annotate_event_statuses(_timeline(["WATCH", "WATCH", "TRIGGER", "WATCH", "WATCH"], [True, False, False, False, True]))
    left_pair = mod.build_pairs(prior_left_censored, samples).iloc[0]
    assert left_pair.pair_status == "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT"
    assert left_pair.pattern_a_prior_active_date == "2025-01-03"

    # E: unavailable is checked before candidate activity and never coerced.
    unavailable = mod.annotate_event_statuses(_timeline(["WATCH", "TRIGGER", "WATCH"], [False, np.nan, False], ["READY", "UNAVAILABLE", "READY"]))
    unavailable_pair = mod.build_pairs(unavailable, samples).iloc[0]
    assert unavailable_pair.pair_status == "DATA_UNAVAILABLE"
    assert pd.isna(unavailable_pair.pattern_a_active_at_fast_event)

    no_catch = mod.annotate_event_statuses(_timeline(["WATCH", "TRIGGER", "WATCH"], [False, False, False]))
    no_pairs = mod.build_pairs(no_catch, samples)
    assert no_pairs.iloc[0].pair_status == "FAST_EVENT_NO_PATTERN_A_CATCHUP"
    assert pd.isna(no_pairs.iloc[0].lead_weeks)


def test_generated_artifacts_are_complete_and_lead_summary_uses_only_valid_pairs():
    timeline = pd.read_csv(R / "pattern_a_fast_vs_pattern_a_timeline_v01.csv", dtype={"ticker": str})
    reference = pd.read_csv(R / "pattern_a_fast_reference_comparison_v01.csv", dtype={"ticker": str})
    pairs = pd.read_csv(R / "pattern_a_fast_trigger_event_pair_v01.csv", dtype={"ticker": str})
    import json
    summary = json.loads((R / "pattern_a_fast_lead_time_summary_v01.json").read_text())
    assert len(reference) == reference.sample_id.nunique() == 40
    assert timeline.duplicated(["ticker", "weekly_date"]).sum() == 0
    assert pd.to_datetime(timeline.weekly_date).dt.dayofweek.eq(4).all()
    assert reference.loc[reference.sample_id == "012170_20250328", "reference_comparison_status"].item() == "DATA_UNAVAILABLE"
    earlier = pairs[pairs.pair_status == "FAST_EARLIER_PATTERN_A_LATER"].lead_weeks
    assert summary["lead_weeks_summary"]["n"] == len(earlier)
    assert summary["lead_weeks_summary"]["median"] == float(earlier.median())
    assert not pairs.loc[pairs.pair_status == "FAST_EVENT_NO_PATTERN_A_CATCHUP", "lead_weeks"].notna().any()
    assert len(pairs) == summary["fast_trigger_events"] == sum(summary["pair_status_counts"].values())
    fast_earlier = pairs[pairs.pair_status == "FAST_EARLIER_PATTERN_A_LATER"]
    assert fast_earlier.pattern_a_status_at_fast_event.eq("READY").all()
    assert fast_earlier.pattern_a_active_at_fast_event.eq(False).all()
    assert fast_earlier.pattern_a_was_active_before_fast_event.eq("NO").all()
    assert fast_earlier.pattern_a_next_candidate_event_date.notna().all()


def test_script_uses_completed_pit_and_official_pattern_a_evaluator_only():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "include_incomplete_periods=False" in source
    assert "daily[daily.index <= weekly_date]" in source
    assert "evaluate_pattern_a(snapshot)" in source
    assert "bool(" not in source
    for forbidden in ("sklearn", "optuna", "requests", "urllib", "PyKrxDataProvider"):
        assert forbidden not in source
