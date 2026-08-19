"""Regression gates for Phase 13J-4 frozen Investable OOS-B evaluation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent.parent
OOS = ROOT / "artifacts/pattern_a_fast/investable_oos"
REVIEW = OOS / "pattern_a_fast_investable_oos_human_review_v01.csv"
SEAL = OOS / "pattern_a_fast_investable_oos_human_ground_truth_v01.json"
SUMMARY = OOS / "pattern_a_fast_investable_oos_evaluation_v01.json"
SAMPLES = OOS / "pattern_a_fast_investable_oos_evaluation_samples_v01.csv"
PAIRS = OOS / "pattern_a_fast_investable_oos_evaluation_event_pairs_v01.csv"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_ground_truth_remains_exactly_sealed_before_evaluation():
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    assert sha256(REVIEW) == "c90db38860fc15cfe81eeb4f35e5e7ce0af8bd3c6de1eb1195e9603198d60585"
    assert seal["post_pass_b_human_review_sha256"] == sha256(REVIEW)
    assert seal["pass_a_stage_mutation"] is False
    assert seal["sample_mutation"] is False
    assert seal["oos_evaluation_executed"] is False


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
