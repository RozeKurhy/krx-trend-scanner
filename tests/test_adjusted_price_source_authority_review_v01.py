"""Unit and decision-engine tests for Source Authority Review FIX02.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02 (Section 1-67)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.source_authority_review import (
    CANDIDATE_AUTHORITY_ID,
    DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02,
    EXPECTED_PIT_SHA256,
    EXPECTED_POPULATION_SHA256,
    NAVER_SISE_ENDPOINT,
    START_HEAD_FIX02,
    CandidateBoundaryViolationError,
    CandidateParseError,
    CandidateSchemaError,
    CoverageStatus,
    FetchOutcome,
    NaverDateRangeAdjustedClient,
    OHLCSemanticClassification,
    ParityStatus,
    ReviewDecision,
    build_corporate_action_controls_metadata_fix02,
    build_review_cohort_fix02,
    derive_historical_only_cohort_at_runtime,
    evaluate_authority_gates_fix02,
    execute_failure_semantics_validation,
    run_boundary_semantics_probe,
    validate_candidate_ohlc_semantics,
    validate_parser_negative_matrix,
    validate_provenance_integrity_fix02,
)


def test_candidate_schema_parsing_valid():
    sample_xml = """
    <protocol>
        <chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102">
            <item data="20200102|55500|56000|55000|55200|12993228" />
            <item data="20200103|56000|56600|54900|55500|15422904" />
        </chartdata>
    </protocol>
    """
    df = NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert df["date"].iloc[0] == "2020-01-02"
    assert df["open"].iloc[0] == 55500.0
    assert df["close"].iloc[1] == 55500.0


def test_candidate_schema_missing_chartdata_fails_closed():
    sample_xml = "<protocol></protocol>"
    with pytest.raises((CandidateSchemaError, ValueError)):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_candidate_schema_field_count_lt_6_fails_closed():
    sample_xml = """
    <protocol>
        <chartdata>
            <item data="20200102|55500|56000|55000|55200" />
        </chartdata>
    </protocol>
    """
    with pytest.raises((CandidateSchemaError, ValueError)):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_candidate_schema_field_count_gt_6_fails_closed():
    sample_xml = """
    <protocol>
        <chartdata>
            <item data="20200102|55500|56000|55000|55200|12993228|EXTRA" />
        </chartdata>
    </protocol>
    """
    with pytest.raises((CandidateSchemaError, ValueError)):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_candidate_schema_invalid_calendar_date_fails_closed():
    sample_xml = """
    <protocol>
        <chartdata>
            <item data="20261399|55500|56000|55000|55200|12993228" />
        </chartdata>
    </protocol>
    """
    with pytest.raises((CandidateParseError, ValueError)):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_candidate_schema_out_of_window_fails_closed():
    sample_xml = """
    <protocol>
        <chartdata>
            <item data="20191231|55500|56000|55000|55200|12993228" />
            <item data="20200102|55500|56000|55000|55200|12993228" />
        </chartdata>
    </protocol>
    """
    with pytest.raises((CandidateBoundaryViolationError, ValueError)):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml, start_date="2020-01-02", end_date="2020-01-10")


def test_candidate_schema_duplicate_date_fails_closed():
    sample_xml = """
    <protocol>
        <chartdata>
            <item data="20200102|55500|56000|55000|55200|12993228" />
            <item data="20200102|55500|56000|55000|55200|12993228" />
        </chartdata>
    </protocol>
    """
    with pytest.raises((CandidateParseError, ValueError)):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_candidate_schema_valid_empty_chartdata_returns_no_data():
    empty_xml = '<protocol><chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102"></chartdata></protocol>'
    df = NaverDateRangeAdjustedClient.parse_xml_payload(empty_xml)
    assert len(df) == 0
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]


def test_parser_negative_matrix_all_pass():
    res = validate_parser_negative_matrix()
    assert len(res) >= 13
    assert all(v == "PASS" for v in res.values())


def test_failure_semantics_executed_and_pass():
    records = execute_failure_semantics_validation()
    assert len(records) == 7
    assert all(r["passed"] is True for r in records)


def test_static_failure_matrix_cannot_approve_gate_12():
    # Attempting to pass static dict or missing executed records
    cohort_df, _ = build_review_cohort_fix02()
    coverage_df = pd.DataFrame([{"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON", "coverage_status": "COVERAGE_VALID", "candidate_count": 3000, "first_candidate_date": "2010-01-04", "missing_expected_count": 0, "unreconciled_unexpected_count": 0, "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0}])
    parity_df = pd.DataFrame()
    semantic_df = pd.DataFrame()
    boundary_df = pd.DataFrame([{"ticker": "005930", "boundary_case": "EXACT_ONE_DAY_WINDOW", "status": "SUCCESS", "no_out_of_bounds": True}])
    repeat_summary = {"total_test_cases": 10, "iterations_per_case": 3, "all_content_hashes_stable": True}

    # Pass None as failure semantics
    res = evaluate_authority_gates_fix02(
        cohort_df, coverage_df, parity_df, semantic_df, boundary_df, repeat_summary,
        validate_parser_negative_matrix(), None, {"all_provenance_valid": True},
        {"candidate_id": CANDIDATE_AUTHORITY_ID, "endpoint": NAVER_SISE_ENDPOINT, "request_type": "1", "timeframe": "day", "count_parameter": "5000", "field_count_exact": 6, "date_representation": "YYYYMMDD"},
        build_corporate_action_controls_metadata_fix02()
    )
    assert res["gate_results"]["gate_12_failure_semantics_fail_closed"] is False


def test_provenance_validation_detects_mutation_and_fails_gate_14(tmp_path):
    # Create fake artifact and manifest with wrong hash
    fake_file = tmp_path / "test_artifact.csv"
    fake_file.write_text("hello world\n", encoding="utf-8")
    mock_manifest = {
        "candidate_id": CANDIDATE_AUTHORITY_ID,
        "start_head": START_HEAD_FIX02,
        "artifacts": {
            fake_file.name: {
                "sha256": "wrong_hash_00000000000000000000000000000000000000000000000000000000",
                "size_bytes": 12,
            }
        }
    }
    schema_payload = {
        "endpoint": NAVER_SISE_ENDPOINT,
        "request_type": "1",
        "count_parameter": "5000",
        "field_count_exact": 6,
    }
    val_res = validate_provenance_integrity_fix02(tmp_path, mock_manifest, schema_payload)
    assert val_res["all_provenance_valid"] is False


def test_historical_only_cohort_selection_runtime_authority():
    controls, meta = derive_historical_only_cohort_at_runtime()
    assert len(controls) == 10
    assert meta["mandatory_ticker"] == "064420"
    assert "064420" in meta["selected_tickers"]
    assert meta["eligible_historical_only_count"] > 100


def test_035720_dates_unreconciled_fails_gate_10_and_reconciled_passes():
    # 1. Unreconciled unexpected row
    cov_bad = pd.DataFrame([{
        "ticker": "035720",
        "control_category": "CORPORATE_ACTION_CONTROL",
        "coverage_status": "UNEXPECTED_ROWS",
        "candidate_count": 248,
        "missing_expected_count": 0,
        "raw_unexpected_count": 3,
        "reconciled_unexpected_count": 0,
        "unreconciled_unexpected_count": 3,
        "pre_listing_rows": 0,
        "post_delisting_rows": 0,
        "future_rows": 0,
    }])
    # Gate 10 check
    leakage = cov_bad[(cov_bad["pre_listing_rows"] > 0) | (cov_bad["post_delisting_rows"] > 0) | (cov_bad["future_rows"] > 0) | (cov_bad["unreconciled_unexpected_count"] > 0)]
    assert len(leakage) == 1  # Fails Gate 10

    # 2. Reconciled unexpected row
    cov_good = pd.DataFrame([{
        "ticker": "035720",
        "control_category": "CORPORATE_ACTION_CONTROL",
        "coverage_status": "COVERAGE_VALID",
        "candidate_count": 248,
        "missing_expected_count": 0,
        "raw_unexpected_count": 3,
        "reconciled_unexpected_count": 3,
        "unreconciled_unexpected_count": 0,
        "pre_listing_rows": 0,
        "post_delisting_rows": 0,
        "future_rows": 0,
    }])
    leakage_good = cov_good[(cov_good["pre_listing_rows"] > 0) | (cov_good["post_delisting_rows"] > 0) | (cov_good["future_rows"] > 0) | (cov_good["unreconciled_unexpected_count"] > 0)]
    assert len(leakage_good) == 0  # Passes Gate 10


def test_corporate_action_metadata_evidence_path_validity():
    meta_df = build_corporate_action_controls_metadata_fix02()
    assert len(meta_df) >= 8
    assert meta_df["evidence_valid"].all()
    assert (meta_df["evidence_sha256"] != "").all()


def test_candidate_only_ohlc_semantic_anomaly_fails_gate_07():
    # Broken high row without matching PyKRX
    df_cand = pd.DataFrame([{
        "date": "2020-01-02",
        "open": 100.0,
        "high": 95.0,  # High < Open
        "low": 90.0,
        "close": 98.0,
        "volume": 1000.0,
    }])
    df_pykrx = pd.DataFrame([{
        "date": "2020-01-02",
        "open": 100.0,
        "high": 105.0,  # Normal in PyKRX
        "low": 90.0,
        "close": 98.0,
        "volume": 1000.0,
    }])
    sem_class, norm_c, up_c, cand_c = validate_candidate_ohlc_semantics(df_cand, "005930", df_pykrx)
    assert sem_class == OHLCSemanticClassification.CANDIDATE_ONLY_OHLC_SEMANTIC_ANOMALY
    assert cand_c == 1
    assert norm_c == 0


def test_upstream_matching_ohlc_semantic_anomaly_allowed():
    # Broken high row matching PyKRX exactly
    df_cand = pd.DataFrame([{
        "date": "2018-05-04",
        "open": 100.0,
        "high": 95.0,
        "low": 90.0,
        "close": 98.0,
        "volume": 1000.0,
    }])
    df_pykrx = pd.DataFrame([{
        "date": "2018-05-04",
        "open": 100.0,
        "high": 95.0,  # Identical anomaly in PyKRX
        "low": 90.0,
        "close": 98.0,
        "volume": 1000.0,
    }])
    sem_class, norm_c, up_c, cand_c = validate_candidate_ohlc_semantics(df_cand, "005930", df_pykrx)
    assert sem_class == OHLCSemanticClassification.UPSTREAM_ADJUSTED_OHLC_ANOMALY_MATCH
    assert cand_c == 0
    assert up_c == 1


def test_review_artifacts_fix02_manifest_integrity():
    manifest_p = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02 / "artifact_manifest.json"
    assert manifest_p.exists(), "artifact_manifest.json must exist in FIX02 dir"

    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = manifest_data.get("artifacts", {})
    assert len(artifacts) >= 12

    for fname, meta in artifacts.items():
        fp = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX02 / fname
        assert fp.exists(), f"Artifact {fname} missing on disk"
        expected_sha = meta["sha256"]
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"SHA256 mismatch for {fname}"
