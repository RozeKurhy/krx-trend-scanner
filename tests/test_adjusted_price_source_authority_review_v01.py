"""Unit and regression tests for Source Authority Review FIX03_CORRECTION.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION (Section 1-84)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.source_authority_review import (
    CANDIDATE_AUTHORITY_ID,
    DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03_CORRECTION,
    EXPECTED_PIT_PHYSICAL_SHA256,
    EXPECTED_PIT_SEMANTIC_SHA256,
    EXPECTED_POPULATION_PHYSICAL_SHA256,
    EXPECTED_POPULATION_SEMANTIC_SHA256,
    NAVER_SISE_ENDPOINT,
    START_HEAD_FIX03_CORRECTION,
    CandidateBoundaryViolationError,
    CandidateParseError,
    CandidateSchemaError,
    CorporateActionEvidenceResolver,
    CoverageStatus,
    FetchOutcome,
    NaverDateRangeAdjustedClient,
    NetworkForbiddenError,
    OHLCSemanticClassification,
    ParityStatus,
    ReviewDecision,
    build_corporate_action_controls_metadata_fix03,
    build_review_cohort_fix03,
    derive_coverage_results_fix03_correction,
    derive_historical_only_cohort_at_runtime_fix03,
    evaluate_authority_gates_fix03,
    execute_failure_semantics_validation,
    reconcile_unexpected_dates_generic_fix03,
    validate_parser_negative_matrix,
    validate_provenance_integrity_fix03,
)


def test_ticker_identity_normalization():
    assert normalize_ticker("035720") == "035720"
    assert normalize_ticker("35720") == "035720"
    assert normalize_ticker(35720) == "035720"
    assert normalize_ticker("000610") == "000610"
    assert normalize_ticker("610") == "000610"
    assert normalize_ticker(610) == "000610"
    assert normalize_ticker("0001A0") == "0001A0"


def test_network_attempt_in_offline_mode_fails():
    client = NaverDateRangeAdjustedClient(allow_network=False)
    with pytest.raises(NetworkForbiddenError):
        client.fetch_raw("005930", "2020-01-02", "2020-01-10")


def test_historical_selection_no_target_list_behavior():
    controls, meta = derive_historical_only_cohort_at_runtime_fix03()
    assert len(controls) == 10
    assert meta["mandatory_ticker"] == "064420"
    assert "064420" in meta["selected_tickers"]
    assert meta["selection_algorithm"] == "DETERMINISTIC_STRATIFIED_LIFECYCLE_SELECTION_V01"


def test_historical_selection_invariant_to_input_ordering(tmp_path):
    pop_orig = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/historical_common_population_v01.json")
    with open(pop_orig, encoding="utf-8") as f:
        data = json.load(f)

    data_rev = dict(data)
    data_rev["records"] = list(reversed(data["records"]))
    shuffled_pop_file = tmp_path / "pop_shuffled.json"
    shuffled_pop_file.write_text(json.dumps(data_rev), encoding="utf-8")

    controls1, meta1 = derive_historical_only_cohort_at_runtime_fix03(pop_path=pop_orig)
    controls2, meta2 = derive_historical_only_cohort_at_runtime_fix03(pop_path=shuffled_pop_file)

    assert meta1["selected_tickers"] == meta2["selected_tickers"]


def test_mandatory_064420_absence_fails(tmp_path):
    pop_orig = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/historical_common_population_v01.json")
    with open(pop_orig, encoding="utf-8") as f:
        data = json.load(f)

    data_no_064420 = dict(data)
    data_no_064420["records"] = [p for p in data["records"] if normalize_ticker(p.get("ticker")) != "064420"]
    pop_file = tmp_path / "pop_no_064420.json"
    pop_file.write_text(json.dumps(data_no_064420), encoding="utf-8")

    with pytest.raises(ValueError, match="Mandatory historical control '064420' is missing"):
        derive_historical_only_cohort_at_runtime_fix03(pop_path=pop_file)


def test_gate_04_set_mismatch_fails():
    coverage_df = pd.DataFrame([
        {
            "ticker": t,
            "control_category": "HISTORICAL_ONLY_DELISTED",
            "expected_count": 100,
            "candidate_count": 100,
            "missing_expected_count": 0,
            "unreconciled_unexpected_count": 0,
            "pre_listing_rows": 0,
            "post_delisting_rows": 0,
            "future_rows": 0,
            "coverage_status": "COVERAGE_VALID",
        }
        for t in ["000610", "004320", "006580", "008340", "009010", "010670", "012650", "015940", "037510", "064420"]
    ])
    # Selected set has different ticker '999999' instead of '064420'
    mismatched_meta = {"selected_tickers": ["000610", "004320", "006580", "008340", "009010", "010670", "012650", "015940", "037510", "999999"]}

    res = evaluate_authority_gates_fix03(
        cohort_df=pd.DataFrame(),
        coverage_df=coverage_df,
        parity_df=pd.DataFrame(),
        semantic_df=pd.DataFrame(),
        boundary_df=pd.DataFrame(),
        repeatability_summary=None,
        parser_validation=None,
        failure_semantics_records=None,
        provenance_validation=None,
        schema_payload=None,
        corp_action_meta_df=None,
        selected_historical_meta=mismatched_meta,
    )
    assert res["gate_results"]["gate_04_historical_only_controls"] is False
    assert res["historical_gate_identity_match"] is False


def test_gate_10_reconciliation_coverage_inconsistency_fails():
    coverage_df = pd.DataFrame([{
        "ticker": "035720",
        "control_category": "CORPORATE_ACTION_CONTROL",
        "population_class": "CURRENT_COMMON",
        "expected_count": 240,
        "candidate_count": 243,
        "missing_expected_count": 0,
        "raw_unexpected_count": 3,
        "reconciled_unexpected_count": 3,
        "unreconciled_unexpected_count": 0,  # Coverage says 0 unreconciled
        "pre_listing_rows": 0,
        "post_delisting_rows": 0,
        "future_rows": 0,
        "coverage_status": "COVERAGE_VALID",
    }])
    unexp_recon_df = pd.DataFrame([{
        "ticker": "035720",
        "date": "2021-04-12",
        "reconciliation_status": "UNRESOLVED",  # Reconciliation says UNRESOLVED!
    }])

    res = evaluate_authority_gates_fix03(
        cohort_df=pd.DataFrame(),
        coverage_df=coverage_df,
        parity_df=pd.DataFrame(),
        semantic_df=pd.DataFrame(),
        boundary_df=pd.DataFrame(),
        repeatability_summary=None,
        parser_validation=None,
        failure_semantics_records=None,
        provenance_validation=None,
        schema_payload=None,
        corp_action_meta_df=None,
        unexp_recon_df=unexp_recon_df,
    )
    assert res["gate_results"]["gate_10_no_lifecycle_or_future_leakage"] is False
    assert res["reconciliation_coverage_consistency"] is False


def test_reconciliation_success_wiring_passes_gate_10():
    coverage_df = pd.DataFrame([{
        "ticker": "035720",
        "control_category": "CORPORATE_ACTION_CONTROL",
        "population_class": "CURRENT_COMMON",
        "expected_count": 240,
        "candidate_count": 243,
        "missing_expected_count": 0,
        "raw_unexpected_count": 1,
        "reconciled_unexpected_count": 1,
        "unreconciled_unexpected_count": 0,
        "pre_listing_rows": 0,
        "post_delisting_rows": 0,
        "future_rows": 0,
        "coverage_status": "COVERAGE_VALID",
    }])
    unexp_recon_df = pd.DataFrame([{
        "ticker": "035720",
        "date": "2021-04-12",
        "reconciliation_status": "RECONCILED",
    }])

    res = evaluate_authority_gates_fix03(
        cohort_df=pd.DataFrame(),
        coverage_df=coverage_df,
        parity_df=pd.DataFrame(),
        semantic_df=pd.DataFrame(),
        boundary_df=pd.DataFrame(),
        repeatability_summary=None,
        parser_validation=None,
        failure_semantics_records=None,
        provenance_validation=None,
        schema_payload=None,
        corp_action_meta_df=None,
        unexp_recon_df=unexp_recon_df,
    )
    assert res["gate_results"]["gate_10_no_lifecycle_or_future_leakage"] is True
    assert res["reconciliation_coverage_consistency"] is True


def test_old_fix02_category_cannot_override_authority():
    cohort_df = pd.DataFrame([{
        "ticker": "015940",
        "control_category": "HISTORICAL_ONLY_DELISTED",
        "population_class": "HISTORICAL_ONLY",
    }])
    unexp_df = pd.DataFrame()
    cov_df = derive_coverage_results_fix03_correction(cohort_df, unexp_df)
    assert len(cov_df) == 1
    assert cov_df["ticker"].iloc[0] == "015940"
    assert cov_df["control_category"].iloc[0] == "HISTORICAL_ONLY_DELISTED"
    assert cov_df["population_class"].iloc[0] == "HISTORICAL_ONLY"
    assert cov_df["candidate_count"].iloc[0] > 0


def test_physical_only_population_mutation_fails_gate_14(tmp_path):
    pop_orig = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/historical_common_population_v01.json")
    with open(pop_orig, encoding="utf-8") as f:
        data = json.load(f)

    # Indentation changed: semantic records identical, physical bytes altered!
    mutated_pop = tmp_path / "pop_pretty.json"
    mutated_pop.write_text(json.dumps(data, indent=4) + "\n\n", encoding="utf-8")

    pit_orig = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/pit_common_denominator_v01.json")

    manifest = {"candidate_id": CANDIDATE_AUTHORITY_ID, "start_head": START_HEAD_FIX03_CORRECTION, "artifacts": {"a": {"sha256": "x", "size_bytes": 1}}}
    schema = {"endpoint": NAVER_SISE_ENDPOINT, "request_type": "1", "count_parameter": "5000", "field_count_exact": 6}

    res = validate_provenance_integrity_fix03(tmp_path, manifest, schema, pop_path=mutated_pop, pit_path=pit_orig)
    assert res["population_semantic_valid"] is True
    assert res["population_physical_valid"] is False
    assert res["all_provenance_valid"] is False


def test_physical_only_pit_mutation_fails_gate_14(tmp_path):
    pop_orig = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/historical_common_population_v01.json")
    pit_orig = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/pit_common_denominator_v01.json")
    with open(pit_orig, encoding="utf-8") as f:
        data = json.load(f)

    # Indentation changed: semantic records identical, physical bytes altered!
    mutated_pit = tmp_path / "pit_pretty.json"
    mutated_pit.write_text(json.dumps(data, indent=4) + "\n\n", encoding="utf-8")

    manifest = {"candidate_id": CANDIDATE_AUTHORITY_ID, "start_head": START_HEAD_FIX03_CORRECTION, "artifacts": {"a": {"sha256": "x", "size_bytes": 1}}}
    schema = {"endpoint": NAVER_SISE_ENDPOINT, "request_type": "1", "count_parameter": "5000", "field_count_exact": 6}

    res = validate_provenance_integrity_fix03(tmp_path, manifest, schema, pop_path=pop_orig, pit_path=mutated_pit)
    assert res["pit_semantic_valid"] is True
    assert res["pit_physical_valid"] is False
    assert res["all_provenance_valid"] is False


def test_corporate_resolver_035420_blocked_record():
    res = CorporateActionEvidenceResolver.resolve_control(
        ticker="035420",
        claimed_event_type="STOCK_SPLIT_5_TO_1",
        claimed_event_date="2018-10-12",
        comparison_window_start="2018-01-02",
        comparison_window_end="2018-12-28",
        evidence_path_str="artifacts/data_providers/krx_open_api/validation_v01/corporate_action_cases.csv",
    )
    assert res["record_resolved"] is True
    assert res["ticker"] == "035420"
    assert res["authority_status_acceptable"] is False
    assert res["evidence_valid"] is False
    assert "BLOCKED" in res["validation_reason"]


def test_corporate_resolver_005930_valid_record():
    res = CorporateActionEvidenceResolver.resolve_control(
        ticker="005930",
        claimed_event_type="STOCK_SPLIT_50_TO_1",
        claimed_event_date="2018-05-04",
        comparison_window_start="2018-01-02",
        comparison_window_end="2018-12-28",
        evidence_path_str="artifacts/data/krx_openapi/v01/corporate_action_validation.json",
    )
    assert res["record_resolved"] is True
    assert res["evidence_valid"] is True
    assert res["ticker_match"] is True
    assert res["event_type_match"] is True


def test_corporate_resolver_reproducibility():
    df1 = build_corporate_action_controls_metadata_fix03()
    df2 = build_corporate_action_controls_metadata_fix03()
    assert df1.equals(df2)


def test_parser_negative_matrix_all_pass():
    res = validate_parser_negative_matrix()
    assert len(res) >= 13
    assert all(v == "PASS" for v in res.values())


def test_failure_semantics_executed_and_pass():
    records = execute_failure_semantics_validation()
    assert len(records) == 7
    assert all(r["passed"] is True for r in records)


def test_fix03_correction_manifest_integrity():
    manifest_p = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03_CORRECTION / "artifact_manifest.json"
    assert manifest_p.exists(), "artifact_manifest.json must exist in FIX03_CORRECTION dir"

    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = manifest_data.get("artifacts", {})
    assert len(artifacts) >= 15

    for fname, meta in artifacts.items():
        fp = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03_CORRECTION / fname
        assert fp.exists(), f"Artifact {fname} missing on disk"
        expected_sha = meta["sha256"]
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"SHA256 mismatch for {fname}"
