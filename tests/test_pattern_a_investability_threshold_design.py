"""Unit and Integration Tests for Phase 10B Investability Threshold Design & Validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.validation.pattern_a_investability_threshold_design import (
    run_threshold_design_validation,
    calculate_distribution_stats,
    PHASE_10A_CHECKPOINT_SHA,
    PHASE_10A_EXPECTED_HASHES,
    PHASE_10A_SCENARIO_EXPECTED_HASH,
    CANONICAL_AS_OF,
    EXPECTED_UNIVERSE_COUNT,
    EXPECTED_CANDIDATE_COUNT,
    EXPECTED_EARLY_COUNT,
    EXPECTED_HUMAN42_COUNT,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/patterns/pattern_a/production/investability"
_RESEARCH_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/patterns/pattern_a/research/investability_threshold_design"


@pytest.fixture(scope="module")
def threshold_design_result() -> dict:
    """Execute canonical threshold design validation pipeline."""
    return run_threshold_design_validation(_REPO_ROOT)


def test_gate1_phase_10a_source_identity():
    """Gate 1: Verify Phase 10A canonical artifacts are strictly preserved and unmutated."""
    for fname, exp_hash in PHASE_10A_EXPECTED_HASHES.items():
        fpath = _ARTIFACTS_DIR / fname
        assert fpath.exists(), f"Phase 10A production artifact missing: {fname}"
        actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
        assert actual_hash == exp_hash, f"Phase 10A production artifact {fname} was mutated!"

    scenario_fpath = _RESEARCH_ARTIFACTS_DIR / "pattern_a_investability_scenarios_20260814.csv"
    assert scenario_fpath.exists(), "Phase 10A scenario artifact missing in Research!"
    act_sc_hash = hashlib.sha256(scenario_fpath.read_bytes()).hexdigest()
    assert act_sc_hash == PHASE_10A_SCENARIO_EXPECTED_HASH, "Phase 10A scenario artifact was mutated!"


def test_gate2_cohort_identity(threshold_design_result: dict):
    """Gate 2: Verify universe, candidate, early, and human42 counts."""
    assert threshold_design_result["as_of"] == CANONICAL_AS_OF
    assert threshold_design_result["base_checkpoint"] == PHASE_10A_CHECKPOINT_SHA
    assert threshold_design_result["universe_count"] == EXPECTED_UNIVERSE_COUNT
    assert threshold_design_result["candidate_count"] == EXPECTED_CANDIDATE_COUNT
    assert threshold_design_result["early_count"] == EXPECTED_EARLY_COUNT
    assert threshold_design_result["human42_count"] == EXPECTED_HUMAN42_COUNT
    assert threshold_design_result["hard_gates"]["gate_02_cohort_identity_pass"] is True


def test_gate3_scorecard_arithmetic(threshold_design_result: dict):
    """Gate 3: Verify scorecard arithmetic consistency."""
    assert threshold_design_result["hard_gates"]["gate_03_scorecard_arithmetic_pass"] is True
    sc_rows = threshold_design_result["trade_off_scorecard"]
    for r in sc_rows:
        assert r["candidate_remaining"] + (r["candidate_unavailable"] + r["candidate_threshold_failed"]) == r["candidate_total"]


def test_gate4_mcap_1000_evaluation(threshold_design_result: dict):
    """Gate 4: Verify MCAP 1,000억원 evaluation metrics."""
    assert threshold_design_result["hard_gates"]["gate_04_mcap1000_result_pass"] is True
    mcap_eval = threshold_design_result["market_cap_1000_evaluation"]
    assert mcap_eval["decision"] == "SELECT"
    assert mcap_eval["universe_remaining"] == 1299
    assert mcap_eval["candidate_remaining"] == 135
    assert mcap_eval["early_remaining"] == 10
    assert mcap_eval["human42_good_remaining"] == 9
    assert mcap_eval["human42_not_fit_remaining"] == 6
    assert set(mcap_eval["removed_early_tickers"]) == {"086060", "033560"}


def test_gate5_and_6_recommended_scenario_consistency(threshold_design_result: dict):
    """Gate 5 & 6: Verify COMBO_M1000_TV300M scenario existence and dynamic consistency."""
    assert threshold_design_result["hard_gates"]["gate_05_recommended_scenario_exists_pass"] is True
    assert threshold_design_result["hard_gates"]["gate_06_recommended_scenario_consistency_pass"] is True
    rec = threshold_design_result["final_recommendation"]
    assert rec["surviving_candidates_count"] == 103
    assert rec["surviving_early_count"] == 10
    assert rec["surviving_human42_good_count"] == 8
    assert rec["surviving_human42_not_fit_count"] == 1

    ratio_info = threshold_design_result["trading_value_comparison"]["recommended_scenario_ratio_analysis"]
    assert ratio_info["surviving_count"] == 103
    assert ratio_info["tv20_median"] == 19.99
    assert ratio_info["tv60_median"] == 24.02
    assert ratio_info["ratio_in_05_to_20_count"] == 96
    assert ratio_info["ratio_in_05_to_20_pct"] == 93.20


def test_gate7_missing_stale_policy(threshold_design_result: dict):
    """Gate 7: Verify missing/stale policy consistency."""
    assert threshold_design_result["hard_gates"]["gate_07_missing_policy_consistency_pass"] is True
    m_eval = threshold_design_result["missing_stale_policy"]
    assert m_eval["unavailable_candidate_count"] == 4
    assert set(m_eval["unavailable_tickers"]) == {"049180", "286750", "020760", "082640"}


def test_gate8_document_artifact_consistency(threshold_design_result: dict):
    """Gate 8: Verify document and artifact consistency."""
    assert threshold_design_result["hard_gates"]["gate_08_document_artifact_consistency_pass"] is True
    doc_path = _REPO_ROOT / "docs/patterns/pattern_a/validation/investability_threshold_design_v01.md"
    assert doc_path.exists()
    doc_text = doc_path.read_text(encoding="utf-8")
    assert "THRESHOLD_POLICY_READY" in doc_text
    assert "24.02" in doc_text
    assert "19.99" in doc_text


def test_gate9_and_final_status(threshold_design_result: dict):
    """Gate 9 & Final: Verify 9 gates all PASS and status is THRESHOLD_POLICY_READY."""
    assert threshold_design_result["hard_gates"]["gate_09_production_mutation_guard_pass"] is True
    assert threshold_design_result["phase_10b_status"] == "THRESHOLD_POLICY_READY"


def test_fail_closed_negative_cases_in_isolated_tmp(tmp_path: Path):
    """Verify fail-closed behavior when input source is missing or corrupt in isolated tmp_path."""
    tmp_repo = tmp_path / "fake_repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)
    tmp_art = tmp_repo / "artifacts/patterns/pattern_a/production/investability"
    tmp_art.mkdir(parents=True, exist_ok=True)

    # Missing sources trigger fail-closed
    res_missing = run_threshold_design_validation(
        tmp_repo,
        output_dir=tmp_art,
        doc_path=tmp_repo / "doc.md",
        write_artifacts=False,
    )
    assert res_missing["phase_10b_status"] == "HOLD_THRESHOLD_DESIGN"
    assert res_missing["hard_gates"]["gate_01_phase10a_source_identity_pass"] is False
