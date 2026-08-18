"""Phase 13I-2 frozen OOS evaluation integrity and preregistration tests."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE = "94bc7edf2ea959f27d847b5cd9f23cd0cf3521c1"
OOS = ROOT / "artifacts/pattern_a_fast/oos"
RESULTS = OOS / "results"
REVIEW = OOS / "pattern_a_fast_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_oos_sample_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_oos_evaluation_protocol_v01.json"
SUMMARY = RESULTS / "pattern_a_fast_oos_evaluation_summary_v01.json"
SCORE = RESULTS / "pattern_a_fast_oos_score_evaluation_v01.json"
SNAPSHOT = RESULTS / "pattern_a_fast_oos_machine_snapshot_v01.csv"
PAIRS = RESULTS / "pattern_a_fast_oos_event_pairing_v01.csv"
LEAD = RESULTS / "pattern_a_fast_oos_lead_time_v01.csv"
ANCHORS = ROOT / "artifacts/pattern_a_fast/human_anchors/pattern_a_fast_human_positive_anchor_v01.csv"
SCRIPT = ROOT / "scripts/evaluate_pattern_a_fast_oos_v01.py"


def _frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return (
        pd.read_csv(MANIFEST, dtype=str, keep_default_na=False),
        pd.read_csv(REVIEW, dtype=str, keep_default_na=False),
        pd.read_csv(SNAPSHOT, dtype=str, keep_default_na=False),
        pd.read_csv(PAIRS, dtype=str, keep_default_na=False),
    )


def test_exact_oos_population_ground_truth_and_anchor_exclusion():
    manifest, review, snapshot, _ = _frames()
    assert len(manifest) == len(review) == len(snapshot) == 20
    assert manifest.oos_sample_id.tolist() == review.oos_sample_id.tolist() == snapshot.oos_sample_id.tolist()
    assert snapshot.loc[snapshot.oos_sample_id.eq("OOS_A_012"), "human_outcome_available"].iloc[0] == "false"
    assert set(pd.read_csv(ANCHORS, dtype=str).ticker).isdisjoint(set(snapshot.ticker))


def test_contracts_protocol_and_human_labels_are_frozen():
    summary = json.loads(SUMMARY.read_text())
    protocol = json.loads(PROTOCOL.read_text())
    assert summary["base_sha"] == BASE
    assert (summary["fast_contract"], summary["fast_contract_sha"], summary["pattern_a_frozen_sha"]) == (
        "HIERARCHICAL_V01", "2da3fc36744b27ec13edae3f690df72c796906e5", "05d03e16501adbca889488294aaaaa0bd84005de"
    )
    assert summary["protocol_sha256"] == __import__("hashlib").sha256(PROTOCOL.read_bytes()).hexdigest()
    assert protocol["primary_score_comparison"]["positive_labels"] == ["GOOD_TRIGGER", "BORDERLINE_TRIGGER"]
    assert protocol["primary_score_comparison"]["negative_labels"] == ["TOO_EARLY", "NO_SETUP"]


def test_machine_snapshot_is_strict_pit_and_stage_score_are_separate():
    _, _, snapshot, _ = _frames()
    assert snapshot.effective_as_of.le(snapshot.reference_date).all()
    assert snapshot.monthly_as_of.le(snapshot.reference_date).all()
    assert snapshot.weekly_as_of.le(snapshot.reference_date).all()
    assert set(snapshot.machine_stage_status) <= {"READY", "UNAVAILABLE"}
    assert set(snapshot.machine_score_status) <= {"READY", "PARTIAL", "UNAVAILABLE"}
    assert snapshot.machine_stage_status.eq("READY").sum() == 20
    assert snapshot.machine_score_status.value_counts().to_dict() == {"READY": 16, "PARTIAL": 4}
    assert snapshot.loc[snapshot.wma200_status.eq("UNKNOWN"), "machine_score_status"].eq("PARTIAL").all()
    assert snapshot.monthly_component_status.eq("READY").all()
    assert snapshot.daily_component_status.eq("READY").all()


def test_stage_confusion_and_descriptive_call_counts_reconcile():
    summary = json.loads(SUMMARY.read_text())
    _, _, snapshot, _ = _frames()
    assert (summary["exact_match_count"], summary["overcall_count"], summary["undercall_count"]) == (10, 8, 2)
    assert summary["exact_match_count"] + summary["overcall_count"] + summary["undercall_count"] == 20
    assert snapshot.stage_call_type.value_counts().to_dict() == {"EXACT": 10, "OVER_CALL": 8, "UNDER_CALL": 2}
    assert summary["data_coverage_status"] == "PASS"


def test_primary_and_secondary_score_results_are_inconclusive_not_fail():
    score = json.loads(SCORE.read_text())
    summary = json.loads(SUMMARY.read_text())
    assert (score["n_positive"], score["n_early_or_none"]) == (0, 8)
    assert score["positive"]["score_available_n"] == 0
    assert score["early_or_none"]["score_available_n"] == 8
    assert score["primary_status"] == "INCONCLUSIVE"
    assert score["primary_reason"] == "INSUFFICIENT_POSITIVE_STRUCTURE_SAMPLE_SIZE"
    assert all(item["status"] == "INCONCLUSIVE" for item in score["secondary_comparisons"])
    assert summary["primary_score_status"] != "OOS_SCORE_DIRECTION_FAIL"


def test_event_pairing_is_reference_forward_exact_and_reconciled():
    manifest, _, _, pairs = _frames()
    summary = json.loads(SUMMARY.read_text())
    refs = manifest.set_index("oos_sample_id").reference_date
    assert len(pairs) == summary["fast_trigger_event_count"] == 10
    assert pairs.fast_trigger_event_status.eq("OBSERVED").all()
    assert all(row.fast_trigger_event_date >= refs.loc[row.oos_sample_id] for row in pairs.itertuples(index=False))
    assert pairs.groupby(["oos_sample_id", "fast_trigger_event_sequence"]).size().eq(1).all()
    expected = {"DATA_UNAVAILABLE": 0, "SAME_WEEK": 0, "PATTERN_A_ALREADY_ACTIVE": 3, "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT": 6, "FAST_EARLIER_PATTERN_A_LATER": 1, "FAST_EVENT_NO_PATTERN_A_CATCHUP": 0}
    assert summary["pair_status_distribution"] == expected
    assert sum(expected.values()) == len(pairs)
    source = SCRIPT.read_text(encoding="utf-8")
    pairing_block = source[source.index("if not pattern_ready:", source.index("def pair_events")):source.index("lead_days =", source.index("def pair_events"))]
    positions = [pairing_block.index(f'"{status}"') for status in [
        "DATA_UNAVAILABLE", "SAME_WEEK", "PATTERN_A_ALREADY_ACTIVE",
        "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", "FAST_EARLIER_PATTERN_A_LATER",
        "FAST_EVENT_NO_PATTERN_A_CATCHUP",
    ]]
    assert positions == sorted(positions)


def test_lead_population_is_clean_only_and_is_preregistered_inconclusive():
    summary = json.loads(SUMMARY.read_text())
    lead = pd.read_csv(LEAD, dtype=str, keep_default_na=False)
    eligible = lead[lead.primary_lead_eligible.eq("True")]
    assert len(eligible) == summary["clean_primary_lead_n"] == 1
    assert eligible.pair_status.eq("FAST_EARLIER_PATTERN_A_LATER").all()
    assert eligible.lead_weeks.astype(float).tolist() == [3.0]
    assert lead.loc[~lead.primary_lead_eligible.eq("True"), "lead_weeks"].eq("").all()
    assert summary["lead_direction_status"] == "OOS_LEAD_INCONCLUSIVE"


def test_coverage_overall_status_and_no_retuning_are_explicit():
    summary = json.loads(SUMMARY.read_text())
    assert summary["machine_stage_ready_rate"] == 1.0
    assert summary["machine_score_unavailable_rate"] == 0.0
    assert summary["hard_failures"] == []
    assert summary["overall_oos_status"] == "NO_HARD_OOS_FAILURE_BUT_PRIMARY_SCORE_INCONCLUSIVE"
    assert summary["retuning_performed"] is False
    assert summary["production_frozen"] is False
    assert summary["network_requests"] == 0


def test_protected_inputs_and_frozen_13c_to_13h_files_are_unchanged():
    protected = [
        "artifacts/pattern_a_fast/oos/pattern_a_fast_oos_sample_manifest_v01.csv",
        "artifacts/pattern_a_fast/oos/pattern_a_fast_oos_human_review_v01.csv",
        "artifacts/pattern_a_fast/oos/pattern_a_fast_oos_ground_truth_seal_v01.json",
        "artifacts/pattern_a_fast/oos/pattern_a_fast_oos_outcome_adjudication_v01.csv",
        "artifacts/pattern_a_fast/oos/pattern_a_fast_oos_evaluation_protocol_v01.json",
        "artifacts/pattern_a_fast/oos/pattern_a_fast_oos_blind_asset_manifest_v01.csv",
        "artifacts/pattern_a_fast/oos/charts/stage_blind", "artifacts/pattern_a_fast/oos/charts/outcome_blind",
        "artifacts/pattern_a_fast/human_anchors/pattern_a_fast_human_positive_anchor_v01.csv",
        "artifacts/pattern_a_fast/ground_truth", "artifacts/pattern_a_fast/research",
        "scripts/research_pattern_a_fast_lead_time_failure.py", "scripts/research_pattern_a_fast_score_stage_prototype.py", "docs/roadmap.md",
    ]
    result = subprocess.run(["git", "diff", "--quiet", BASE, "--", *protected], cwd=ROOT, check=False)
    assert result.returncode == 0


def test_evaluator_is_cache_only_and_direct_jump_is_not_a_hard_gate():
    source = SCRIPT.read_text(encoding="utf-8")
    assert "ParquetCache" in source and "cache.load" in source
    assert not [token for token in ("import requests", "import urllib", "import yfinance", "from pykrx", "MarketDataRepository") if token in source]
    summary = json.loads(SUMMARY.read_text())
    assert all("DIRECT_JUMP" not in status for status in summary["hard_failures"])
