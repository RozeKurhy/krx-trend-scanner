"""Unit and Integration Tests for Phase 10B Investability Threshold Design & Validation."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.validation.pattern_a_investability_threshold_design import (
    run_threshold_design_validation,
    PHASE_10A_CHECKPOINT_SHA,
    CANONICAL_AS_OF,
    EXPECTED_UNIVERSE_COUNT,
    EXPECTED_CANDIDATE_COUNT,
    EXPECTED_EARLY_COUNT,
    EXPECTED_HUMAN42_COUNT,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/investability"


@pytest.fixture(scope="module")
def threshold_design_result() -> dict:
    """Execute canonical threshold design validation pipeline."""
    return run_threshold_design_validation(_REPO_ROOT)


def test_phase_10a_input_evidence_invariance():
    """Verify that Phase 10A canonical artifacts are strictly preserved and unmutated."""
    expected_hashes = {
        "pattern_a_investability_universe_20260814.csv": "1aca764fc56d3416b9f10ce418a0deaca5174cb8c32997acfd2df1000987e4c8",
        "pattern_a_investability_candidates_20260814.csv": "02b2c5255db6a63c71d9af0262bdb8f0b4bd93969e4bf987e47b92ec8e0d7dc3",
        "pattern_a_investability_scenarios_20260814.csv": "15e2e02d87e085febb50b6629e704fd06402815df8e5aa157d148be414eb82eb",
        "pattern_a_investability_distribution_20260814.json": "495061598b96ca3fade85a7efe3dc5864324eb9ca177eb807e578562e903d2a9",
        "pattern_a_investability_summary_20260814.json": "d2d7535f34587980899bfc85fc4a68fe3c663f5f708fe75992a631fc8eb2bc92",
    }
    for fname, exp_hash in expected_hashes.items():
        fpath = _ARTIFACTS_DIR / fname
        assert fpath.exists(), f"Phase 10A artifact missing: {fname}"
        actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
        assert actual_hash == exp_hash, f"Phase 10A artifact {fname} was mutated!"


def test_candidate_cohort_identity(threshold_design_result: dict):
    """Verify universe, candidate, early, and human42 counts."""
    assert threshold_design_result["as_of"] == CANONICAL_AS_OF
    assert threshold_design_result["base_checkpoint"] == PHASE_10A_CHECKPOINT_SHA
    assert threshold_design_result["universe_count"] == EXPECTED_UNIVERSE_COUNT
    assert threshold_design_result["candidate_count"] == EXPECTED_CANDIDATE_COUNT
    assert threshold_design_result["early_count"] == EXPECTED_EARLY_COUNT
    assert threshold_design_result["human42_count"] == EXPECTED_HUMAN42_COUNT


def test_mcap_1000_evaluation(threshold_design_result: dict):
    """Verify MCAP 1,000억원 evaluation metrics."""
    mcap_eval = threshold_design_result["market_cap_1000_evaluation"]
    assert mcap_eval["decision"] == "SELECT"
    assert mcap_eval["universe_remaining"] == 1299
    assert mcap_eval["candidate_remaining"] == 135
    assert mcap_eval["early_remaining"] == 10
    assert mcap_eval["human42_good_remaining"] == 9
    assert mcap_eval["human42_not_fit_remaining"] == 6
    assert mcap_eval["removed_early_tickers"] == ["086060", "033560"]


def test_trading_value_comparison(threshold_design_result: dict):
    """Verify TV20 comparison across 1억, 3억, 5억."""
    tv_comp = threshold_design_result["trading_value_comparison"]
    assert tv_comp["selected_threshold"] == "TV20 >= 3.0억원"
    assert tv_comp["decision"] == "SELECT"

    # Verify 3억 threshold stats
    row_300m = next(r for r in tv_comp["comparison_table"] if "3억원" in r["threshold"])
    assert row_300m["candidate_remaining"] == 103
    assert row_300m["early_remaining"] == 10
    assert row_300m["human42_good_remaining"] == 8
    assert row_300m["human42_not_fit_remaining"] == 1
    assert row_300m["evaluation_label"] == "BALANCED"


def test_closing_price_residual_analysis(threshold_design_result: dict):
    """Verify closing price residual analysis."""
    p_eval = threshold_design_result["closing_price_residual_analysis"]
    assert p_eval["decision"] == "PRICE_FILTER_NOT_NEEDED"
    assert p_eval["mcap1000_tv300m_under_1000"] == 0
    assert p_eval["mcap1000_tv300m_under_2000"] == 1


def test_missing_stale_policy(threshold_design_result: dict):
    """Verify missing/stale policy."""
    m_eval = threshold_design_result["missing_stale_policy"]
    assert m_eval["unavailable_candidate_count"] == 4
    assert set(m_eval["unavailable_tickers"]) == {"049180", "286750", "020760", "082640"}


def test_early_preservation_details(threshold_design_result: dict):
    """Verify EARLY 12 preservation and filter reasons."""
    e_eval = threshold_design_result["early_preservation_analysis"]
    assert e_eval["total_early"] == 12
    assert e_eval["investable_under_recommended"] == 10
    assert len(e_eval["early_filtered_details"]) == 12


def test_trade_off_scorecard_structure(threshold_design_result: dict):
    """Verify Trade-off Scorecard CSV artifact on disk."""
    sc_path = _ARTIFACTS_DIR / "pattern_a_investability_threshold_scorecard_20260814.csv"
    assert sc_path.exists()
    df_sc = pd.read_csv(sc_path)
    assert len(df_sc) >= 12
    assert "COMBO_M1000_TV300M" in df_sc["scenario_id"].values


def test_final_recommendation_and_status(threshold_design_result: dict):
    """Verify Phase 10B final status."""
    assert threshold_design_result["phase_10b_status"] == "THRESHOLD_POLICY_READY"
    rec = threshold_design_result["final_recommendation"]
    assert "1000" in rec["market_cap_policy"]
    assert "3.0" in rec["liquidity_policy"]
    assert rec["price_policy"] == "PRICE_FILTER_NOT_NEEDED"
    assert rec["recommended_scenario_id"] == "COMBO_M1000_TV300M"
    assert rec["surviving_candidates_count"] == 103
    assert rec["surviving_early_count"] == 10


def test_isolated_execution_in_tmp_path(tmp_path: Path):
    """Verify that execution with custom output_dir and doc_path works cleanly without polluting repo."""
    tmp_out = tmp_path / "artifacts"
    tmp_doc = tmp_path / "doc.md"
    res = run_threshold_design_validation(
        _REPO_ROOT,
        output_dir=tmp_out,
        doc_path=tmp_doc,
        write_artifacts=True,
    )
    assert res["phase_10b_status"] == "THRESHOLD_POLICY_READY"
    assert (tmp_out / "pattern_a_investability_threshold_scorecard_20260814.csv").exists()
    assert tmp_doc.exists()
    assert "THRESHOLD_POLICY_READY" in tmp_doc.read_text(encoding="utf-8")
