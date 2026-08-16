"""Unit and Integration Tests for Phase 10A Investability Distribution Audit (Single Canonical Pipeline)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.validation.pattern_a_investability_audit import (
    run_investability_audit,
    load_canonical_mcap_snapshot,
    calculate_distribution_stats,
    CANONICAL_AS_OF,
    CANONICAL_MCAP_SHA256,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/investability"


@pytest.fixture(scope="module")
def canonical_audit_result() -> dict:
    """Execute canonical investability audit pipeline."""
    return run_investability_audit(_REPO_ROOT, as_of=CANONICAL_AS_OF)


def test_gate1_no_lookahead_and_dates(canonical_audit_result: dict):
    """Gate 1: Verify as_of is strictly 2026-08-14 and all data sources are lookahead-free."""
    assert canonical_audit_result["as_of"] == "2026-08-14"
    assert canonical_audit_result["data_provenance"]["lookahead_free"] is True
    assert canonical_audit_result["hard_gates"]["gate_01_no_lookahead_pass"] is True


def test_gate2_universe_identity(canonical_audit_result: dict):
    """Gate 2: Verify Universe count is exactly 2,528."""
    assert canonical_audit_result["universe_count"] == 2528
    assert canonical_audit_result["hard_gates"]["gate_02_universe_identity_pass"] is True
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_universe_20260814.csv"
    assert csv_path.exists()
    df_u = pd.read_csv(csv_path, dtype={"ticker": str})
    assert len(df_u) == 2528


def test_gate3_candidate_identity(canonical_audit_result: dict):
    """Gate 3: Verify Candidate count is exactly 180."""
    assert canonical_audit_result["candidate_count"] == 180
    assert canonical_audit_result["hard_gates"]["gate_03_candidate_identity_pass"] is True
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv"
    assert csv_path.exists()
    df_c = pd.read_csv(csv_path, dtype={"ticker": str})
    assert len(df_c) == 180


def test_gate4_stage_split(canonical_audit_result: dict):
    """Gate 4: Verify stage split is 168 Transition and 12 Early."""
    assert canonical_audit_result["transition_count"] == 168
    assert canonical_audit_result["early_count"] == 12
    assert canonical_audit_result["hard_gates"]["gate_04_stage_split_pass"] is True


def test_gate5_human42_identity(canonical_audit_result: dict):
    """Gate 5: Verify Human42 count is exactly 42."""
    assert canonical_audit_result["human42_count"] == 42
    assert canonical_audit_result["hard_gates"]["gate_05_human42_identity_pass"] is True


def test_gate6_market_cap_pit_provenance_and_snapshot(canonical_audit_result: dict):
    """Gate 6: Verify market cap snapshot provenance and sha256."""
    assert canonical_audit_result["hard_gates"]["gate_06_market_cap_pit_provenance_pass"] is True
    df_mcap, sha256 = load_canonical_mcap_snapshot(_REPO_ROOT, as_of="2026-08-14")
    assert len(df_mcap) == 2872
    assert sha256 == CANONICAL_MCAP_SHA256


def test_gate7_candidate_market_cap_coverage(canonical_audit_result: dict):
    """Gate 7: Verify candidate market cap missing is 0."""
    assert canonical_audit_result["hard_gates"]["gate_07_candidate_market_cap_coverage_pass"] is True
    assert canonical_audit_result["missing_audit"]["candidate_mcap_missing_count"] == 0


def test_gate8_candidate_metric_availability_policy(canonical_audit_result: dict):
    """Gate 8: Verify candidate metric availability policy (missing <= 5%)."""
    assert canonical_audit_result["hard_gates"]["gate_08_candidate_metric_availability_policy_pass"] is True
    assert canonical_audit_result["missing_audit"]["candidate_close_missing_count"] == 4


def test_gate9_early_and_human42_full_coverage(canonical_audit_result: dict):
    """Gate 9: Verify EARLY 12 and Human42 have 100% complete metrics."""
    assert canonical_audit_result["hard_gates"]["gate_09_early_and_human42_full_coverage_pass"] is True


def test_gate10_disk_artifact_consistency(canonical_audit_result: dict):
    """Gate 10: Verify disk artifact consistency across summary, universe, candidates, scenarios, doc."""
    assert canonical_audit_result["hard_gates"]["gate_10_artifact_consistency_pass"] is True
    
    # Read actual disk files and verify values
    df_cand_disk = pd.read_csv(_ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv", dtype={"ticker": str})
    df_sc_disk = pd.read_csv(_ARTIFACTS_DIR / "pattern_a_investability_scenarios_20260814.csv")
    dist_disk = json.loads((_ARTIFACTS_DIR / "pattern_a_investability_distribution_20260814.json").read_text(encoding="utf-8"))
    doc_text = (_REPO_ROOT / "docs/validation/pattern_a_investability_distribution_v01.md").read_text(encoding="utf-8")

    assert len(df_cand_disk) == 180
    assert (df_cand_disk["as_of"] == "2026-08-14").all()

    # Percentile checks from disk
    assert dist_disk["candidates_raw"]["market_cap_eok"]["p01"] == 228.30
    assert dist_disk["candidates_raw"]["market_cap_eok"]["p25"] == 1037.63
    assert dist_disk["candidates_raw"]["market_cap_eok"]["median"] == 2288.79

    # Scenario checks from disk
    m1000 = df_sc_disk[df_sc_disk["scenario_id"] == "MCAP_1000"].iloc[0]
    assert m1000["universe_remaining"] == 1299
    assert m1000["candidate_remaining"] == 135
    assert m1000["early_remaining"] == 10

    tv500 = df_sc_disk[df_sc_disk["scenario_id"] == "TV20_500M"].iloc[0]
    assert tv500["universe_remaining"] == 1142
    assert tv500["candidate_remaining"] == 91
    assert tv500["candidate_unavailable"] == 4
    assert tv500["candidate_threshold_failed"] == 85
    assert tv500["early_remaining"] == 9

    # Markdown doc content check
    assert "2288.79" in doc_text
    assert "404.7" in doc_text
    assert "READY_FOR_THRESHOLD_DESIGN" in doc_text


def test_canonical_metrics_086060():
    """Verify exact canonical values for 086060 진바이오텍."""
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv"
    df_c = pd.read_csv(csv_path, dtype={"ticker": str})
    jin = df_c[df_c["ticker"] == "086060"].iloc[0]
    assert jin["market_cap_eok"] == 404.7
    assert jin["close"] == 4700.0
    assert jin["avg_trading_value_20d_eok"] == 1.12
    assert jin["avg_trading_value_60d_eok"] == 1.46


def test_fail_closed_negative_cases_in_isolated_tmp(tmp_path: Path):
    """Verify that failing any gate results in HOLD_DATA_QUALITY in an ISOLATED tmp directory."""
    # Capture pre-test hash of official summary
    summary_path = _ARTIFACTS_DIR / "pattern_a_investability_summary_20260814.json"
    pre_hash = hashlib.sha256(summary_path.read_bytes()).hexdigest()

    tmp_out = tmp_path / "artifacts"
    tmp_doc = tmp_path / "doc.md"

    # Test 1: Empty distribution stats
    empty_stats = calculate_distribution_stats(pd.Series([], dtype=float))
    assert empty_stats["count"] == 0
    assert empty_stats["available_count"] == 0
    assert empty_stats["min"] is None

    # Test 2: Invalid as_of triggers Gate 1 failure and HOLD decision in isolated tmp
    res_bad_date = run_investability_audit(
        _REPO_ROOT,
        as_of="2026-08-15",
        output_dir=tmp_out,
        doc_path=tmp_doc,
        write_artifacts=True,
    )
    assert res_bad_date["hard_gates"]["gate_01_no_lookahead_pass"] is False
    assert res_bad_date["phase_10a_decision"] == "HOLD_DATA_QUALITY"
    assert tmp_doc.exists()
    assert "HOLD_DATA_QUALITY" in tmp_doc.read_text(encoding="utf-8")

    # Verify that official artifact was NOT overwritten or contaminated
    post_hash = hashlib.sha256(summary_path.read_bytes()).hexdigest()
    assert pre_hash == post_hash, "Official artifact must NOT be contaminated by negative test!"
