"""Regression gates for Phase 13J-4 frozen Investable OOS-B evaluation."""

from __future__ import annotations

import hashlib
import importlib
import json
from pathlib import Path

import pandas as pd
import pytest


ROOT = Path(__file__).resolve().parent.parent
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
SEAL = OOS / "pattern_a_fast_investable_oos_human_ground_truth_v01.json"
SUMMARY = OOS / "pattern_a_fast_investable_oos_evaluation_v01.json"
SAMPLES = OOS / "pattern_a_fast_investable_oos_evaluation_samples_v01.csv"
PAIRS = OOS / "pattern_a_fast_investable_oos_evaluation_event_pairs_v01.csv"
FROZEN_INPUT_HASHES = {
    REVIEW: "c90db38860fc15cfe81eeb4f35e5e7ce0af8bd3c6de1eb1195e9603198d60585",
    OOS / "pattern_a_fast_investable_oos_human_stage_pass_a_freeze_v01.json": "4c908daa5ab803ccbf20f355027391aaa3f2d63c31e3f60ac60df6e34b9201ea",
    OOS / "pattern_a_fast_investable_oos_human_ground_truth_v01.json": "c626759b046e4a1bc223685c41c3e9744e5fb989c28dbccdf91f8f3794852689",
    OOS / "pattern_a_fast_investable_oos_selection_manifest_v01.csv": "6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825",
    OOS / "pattern_a_fast_investable_oos_blind_asset_manifest_v01.csv": "9d8b03bf597c4520c279d2fdfe02c59df22669e27135adc1b9efa56b611b5ebe",
    OOS / "pattern_a_fast_investable_oos_evaluation_protocol_v01.json": "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d",
}
FROZEN_EVALUATION_HASHES = {
    SUMMARY: "33b3e9f69fa6d1c5bd972a7a15859c94b2d737abecc076bb5b575889ffdfac50",
    SAMPLES: "b3359d442dd6f7338b3eee5848ce2b20e2c9ce9f4c1d281790042c7204bdbe38",
    PAIRS: "acfe8f368d2377019c637f4f251477e94d0952fa207bd991cc405ec4fc009b62",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ground_truth_remains_exactly_sealed_before_evaluation():
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    for path, expected in FROZEN_INPUT_HASHES.items():
        assert sha256(path) == expected
    assert seal["post_pass_b_human_review_sha256"] == sha256(REVIEW)
    assert seal["pass_a_stage_mutation"] is False
    assert seal["sample_mutation"] is False
    assert seal["oos_evaluation_executed"] is False


def test_evaluator_hard_gates_ground_truth_seal_file_hash_without_mutating_inputs(monkeypatch, tmp_path: Path):
    evaluator = importlib.import_module("scripts.evaluate_pattern_a_fast_investable_oos_v01")
    assert evaluator.FROZEN_GROUND_TRUTH_SEAL_SHA == FROZEN_INPUT_HASHES[SEAL]
    forged = tmp_path / "ground_truth_seal.json"
    forged.write_text(SEAL.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    monkeypatch.setattr(evaluator, "GROUND_TRUTH_SEAL", forged)
    with pytest.raises(RuntimeError, match="GROUND_TRUTH_SEAL_HASH_MISMATCH"):
        evaluator.assert_frozen_input_hashes()


def test_frozen_evaluation_artifacts_are_byte_exact():
    for path, expected in FROZEN_EVALUATION_HASHES.items():
        assert sha256(path) == expected


def test_evaluation_reproduces_frozen_population_and_primary_direction_gate():
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    samples = pd.read_csv(SAMPLES, dtype={"ticker": str}, keep_default_na=False)
    assert len(samples) == samples.sample_id.nunique() == summary["sample_count"] == 36
    assert summary["frozen_inputs"]["human_review_sha256"] == sha256(REVIEW)
    assert summary["frozen_inputs"]["evaluation_protocol_sha256"] == "ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d"
    primary = summary["primary_score_comparison"]
    assert primary["positive_labels"] == ["GOOD_TRIGGER", "BORDERLINE_TRIGGER"]
    assert primary["negative_labels"] == ["TOO_EARLY", "NO_SETUP"]
    assert primary["minimum_n_per_group"] == 5
    assert primary["positive"]["n"] == 9
    assert primary["early_or_none"]["n"] == 12
    assert primary["median_difference"] == 21.88499999999999
    assert primary["status"] == "PASS"


def test_evaluation_preserves_pit_as_of_and_frozen_pairing_semantics():
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    samples = pd.read_csv(SAMPLES, dtype={"ticker": str}, keep_default_na=False)
    pairs = pd.read_csv(PAIRS, dtype={"ticker": str}, keep_default_na=False)
    assert (pd.to_datetime(samples.effective_as_of) <= pd.to_datetime(samples.reference_date)).all()
    assert summary["availability"]["stage_ready_count"] == 36
    assert summary["availability"]["score_unavailable_count"] == 7
    assert summary["availability"]["status"] == "PASS"
    assert len(pairs) == summary["event_pairing"]["fast_trigger_event_count"] == 41
    assert set(pairs.pair_status).issubset({
        "DATA_UNAVAILABLE", "SAME_WEEK", "PATTERN_A_ALREADY_ACTIVE",
        "PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT", "FAST_EARLIER_PATTERN_A_LATER",
        "FAST_EVENT_NO_PATTERN_A_CATCHUP",
    })
    assert summary["event_pairing"]["clean_lead"] == {
        "n": 2, "median": 8.5, "mean": 8.5, "q1": 4.75, "q3": 12.25,
        "iqr": 7.5, "min": 1.0, "max": 16.0, "status": "INCONCLUSIVE",
    }
    assert summary["hard_failure_count"] == 0
    assert summary["overall_oos_b_status"] == "INCONCLUSIVE"
