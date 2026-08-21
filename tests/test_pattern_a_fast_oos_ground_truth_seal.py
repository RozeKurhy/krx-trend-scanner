"""Phase 13I-1 human ground-truth seal integrity tests."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
BASE = "3dbdffcb3277a4bb40fa969f3827075514f13f1e"
OOS = ROOT / "artifacts/patterns/pattern_a_fast/validation/oos"
REVIEW = OOS / "pattern_a_fast_oos_human_review_v01.csv"
MANIFEST = OOS / "pattern_a_fast_oos_sample_manifest_v01.csv"
ASSETS = OOS / "pattern_a_fast_oos_blind_asset_manifest_v01.csv"
PROTOCOL = OOS / "pattern_a_fast_oos_evaluation_protocol_v01.json"
SEAL = OOS / "pattern_a_fast_oos_ground_truth_seal_v01.json"
ADJUDICATION = OOS / "pattern_a_fast_oos_outcome_adjudication_v01.csv"
ANCHORS = ROOT / "artifacts/patterns/pattern_a_fast/validation/human_anchors/pattern_a_fast_human_positive_anchor_v01.csv"

EXPECTED_STAGE = {
    "OOS_A_001": ("EXTENDED", "HIGH", "NO", ""), "OOS_A_002": ("EXTENDED", "HIGH", "NO", ""),
    "OOS_A_003": ("WATCH", "HIGH", "NO", ""), "OOS_A_004": ("SETUP", "LOW", "NO", ""),
    "OOS_A_005": ("WATCH", "LOW", "NO", ""), "OOS_A_006": ("WATCH", "HIGH", "NO", ""),
    "OOS_A_007": ("EXTENDED", "HIGH", "NO", ""), "OOS_A_008": ("WATCH", "HIGH", "NO", ""),
    "OOS_A_009": ("WATCH", "HIGH", "NO", ""), "OOS_A_010": ("TREND", "HIGH", "YES", "2025-11-24"),
    "OOS_A_011": ("WATCH", "HIGH", "NO", ""), "OOS_A_012": ("WATCH", "HIGH", "NO", ""),
    "OOS_A_013": ("WATCH", "MEDIUM", "NO", ""), "OOS_A_014": ("EXTENDED", "HIGH", "NO", ""),
    "OOS_A_015": ("WATCH", "HIGH", "NO", ""), "OOS_A_016": ("WATCH", "HIGH", "NO", ""),
    "OOS_A_017": ("WATCH", "HIGH", "NO", ""), "OOS_A_018": ("EXTENDED", "HIGH", "NO", ""),
    "OOS_A_019": ("WATCH", "MEDIUM", "NO", ""), "OOS_A_020": ("EXTENDED", "HIGH", "NO", ""),
}
EXPECTED_OUTCOME = {
    "OOS_A_001": ("TOO_EXTENDED", "HIGH"), "OOS_A_002": ("TOO_EXTENDED", "HIGH"),
    "OOS_A_003": ("NO_SETUP", "HIGH"), "OOS_A_004": ("TOO_EARLY", "HIGH"),
    "OOS_A_005": ("NO_SETUP", "HIGH"), "OOS_A_006": ("FALSE_TRIGGER", "HIGH"),
    "OOS_A_007": ("TOO_EXTENDED", "HIGH"), "OOS_A_008": ("TOO_EARLY", "HIGH"),
    "OOS_A_009": ("TOO_EXTENDED", "HIGH"), "OOS_A_010": ("TOO_LATE", "HIGH"),
    "OOS_A_011": ("TOO_EARLY", "HIGH"), "OOS_A_013": ("NO_SETUP", "HIGH"),
    "OOS_A_014": ("TOO_EXTENDED", "HIGH"), "OOS_A_015": ("TOO_EARLY", "HIGH"),
    "OOS_A_016": ("TOO_EARLY", "HIGH"), "OOS_A_017": ("FALSE_TRIGGER", "MEDIUM"),
    "OOS_A_018": ("TOO_EXTENDED", "HIGH"), "OOS_A_019": ("FALSE_TRIGGER", "HIGH"),
    "OOS_A_020": ("TOO_EXTENDED", "HIGH"),
}


def _review() -> pd.DataFrame:
    return pd.read_csv(REVIEW, dtype=str, keep_default_na=False).set_index("oos_sample_id")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_exact_reserved_oos_stage_freeze_and_single_observed_trigger():
    review = _review()
    assert len(review) == 20
    actual = {
        sample_id: tuple(review.loc[sample_id, ["weekly_stage_at_reference", "weekly_stage_confidence", "human_trigger_event_observed", "human_trigger_event_date"]])
        for sample_id in review.index
    }
    assert actual == EXPECTED_STAGE
    assert review.stage_review_status.eq("COMPLETE").all()
    assert review.human_trigger_event_observed.eq("YES").sum() == 1


def test_exact_outcome_freeze_and_unavailable_row_do_not_create_eighth_label():
    review = _review()
    actual = {
        sample_id: tuple(review.loc[sample_id, ["human_label", "human_outcome_confidence"]])
        for sample_id in EXPECTED_OUTCOME
    }
    assert actual == EXPECTED_OUTCOME
    unavailable = review.loc["OOS_A_012"]
    assert (unavailable.human_label, unavailable.human_outcome_confidence, unavailable.outcome_review_status) == (
        "UNLABELED", "UNLABELED", "DATA_UNAVAILABLE"
    )
    taxonomy = {"GOOD_TRIGGER", "BORDERLINE_TRIGGER", "FALSE_TRIGGER", "TOO_EARLY", "TOO_LATE", "TOO_EXTENDED", "NO_SETUP"}
    labels = set(review.loc[review.outcome_review_status == "COMPLETE", "human_label"])
    assert labels <= taxonomy and len(labels) == 5


def test_outcome_adjudication_is_explicit_and_machine_readable():
    adjudication = pd.read_csv(ADJUDICATION, dtype=str, keep_default_na=False)
    assert adjudication.to_dict(orient="records") == [{
        "oos_sample_id": "OOS_A_012", "ticker": "043220", "name": "티에스넥스젠",
        "reference_date": "2024-12-27", "outcome_review_end": "2025-12-09",
        "adjudication_status": "DATA_UNAVAILABLE", "reason": "TRADING_SUSPENSION_OUTCOME_UNAVAILABLE",
        "human_outcome_label_available": "false", "review_note": "거래정지로 정상적인 가격 outcome을 평가할 수 없음",
    }]


def test_seal_has_exact_distributions_hashes_and_review_order_guarantee():
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    assert seal["base_sha"] == BASE
    assert seal["sample_count"] == 20
    assert seal["stage_review_complete_count"] == 20
    assert seal["outcome_labeled_count"] == 19
    assert seal["outcome_unavailable_sample_ids"] == ["OOS_A_012"]
    assert seal["stage_distribution"] == {"WATCH": 12, "SETUP": 1, "TRIGGER": 0, "TREND": 1, "EXTENDED": 6}
    assert seal["outcome_distribution"] == {"GOOD_TRIGGER": 0, "BORDERLINE_TRIGGER": 0, "FALSE_TRIGGER": 3, "TOO_EARLY": 5, "TOO_LATE": 1, "TOO_EXTENDED": 7, "NO_SETUP": 3}
    assert seal["human_review_csv_sha256"] == _sha256(REVIEW)
    assert seal["sample_manifest_sha256"] == _sha256(MANIFEST)
    assert seal["blind_asset_manifest_sha256"] == _sha256(ASSETS)
    assert seal["evaluation_protocol_sha256"] == _sha256(PROTOCOL)
    assert seal["stage_review_recorded_before_outcome_review"] is True
    assert seal["evaluation_executed"] is False
    assert seal["seal_status"] == "READY_FOR_ADVISOR_GROUND_TRUTH_SEAL_REVIEW"


def test_positive_anchors_are_exact_and_excluded_from_oos_metrics():
    anchors = pd.read_csv(ANCHORS, dtype=str, keep_default_na=False)
    assert len(anchors) == 4
    assert anchors[["anchor_id", "ticker", "human_identified_week", "normalized_completed_week_label"]].to_dict(orient="records") == [
        {"anchor_id": "HPA_001", "ticker": "420770", "human_identified_week": "2026-01-12", "normalized_completed_week_label": "2026-01-16"},
        {"anchor_id": "HPA_002", "ticker": "006110", "human_identified_week": "2023-03-13", "normalized_completed_week_label": "2023-03-17"},
        {"anchor_id": "HPA_003", "ticker": "034020", "human_identified_week": "2025-05-12", "normalized_completed_week_label": "2025-05-16"},
        {"anchor_id": "HPA_004", "ticker": "000660", "human_identified_week": "2024-02-19", "normalized_completed_week_label": "2024-02-23"},
    ]
    assert anchors.weekly_stage_at_reference.eq("TRIGGER").all()
    assert anchors.human_trigger_event_observed.eq("YES").all()
    assert anchors.human_label.eq("GOOD_TRIGGER").all()
    assert anchors.anchor_role.eq("HUMAN_POSITIVE_REFERENCE").all()
    assert anchors.calibration_membership.eq("NONE").all()
    assert anchors.oos_membership.eq("NONE").all()
    assert anchors.evaluation_membership.eq("NONE").all()
    assert not set(anchors.ticker) & set(_review().ticker)


def test_protected_preregistration_artifacts_are_byte_identical_to_base():
    expected_hashes = {
        "artifacts/patterns/pattern_a_fast/validation/oos/pattern_a_fast_oos_sample_manifest_v01.csv": "4f0fa3bf4763fbc7c8efda7324535e92df2325db5616d598c21615e6e8d10b82",
        "artifacts/patterns/pattern_a_fast/validation/oos/pattern_a_fast_oos_blind_asset_manifest_v01.csv": "18891c43f751bb8923b478a53ee5dbc0adf76040874b0e5a1c716d2d4457921e",
        "artifacts/patterns/pattern_a_fast/validation/oos/pattern_a_fast_oos_evaluation_protocol_v01.json": "a0f5d5d93a1adb726d3b5ae75613c7339c0e4ae28adb04626bcdce0c7ad1b3f6",
    }
    import hashlib
    for path_str, expected in expected_hashes.items():
        actual = hashlib.sha256((ROOT / path_str).read_bytes()).hexdigest()
        assert actual == expected, f"{path_str}: expected {expected}, got {actual}"


def test_frozen_13c_to_13h_and_no_oos_evaluation_result_artifact():
    expected_hashes = {
        "artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_ground_truth_source_v01.csv": "62f02794956ceac2edc08d8c5df2b44ad9e06ac98967d1d77e4572ecf2af0005",
        "artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_human_review_v01.csv": "ea71bd1850aa52479d5c09a9d54a45b4f43493147a2bd98a8e93e6ae0d6fed4c",
        "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json": "be0dc21c3764aeb147a3565e65850fc179ecc91e5700e8221932f12ce28ae501",
    }
    import hashlib
    for path_str, expected in expected_hashes.items():
        actual = hashlib.sha256((ROOT / path_str).read_bytes()).hexdigest()
        assert actual == expected, f"{path_str}: expected {expected}, got {actual}"
    forbidden = ["score_result", "stage_result", "candidate_result", "pair_result", "lead_time_result", "evaluation_result"]
    assert not [path for path in OOS.rglob("*") if path.is_file() and any(token in path.name for token in forbidden)]
