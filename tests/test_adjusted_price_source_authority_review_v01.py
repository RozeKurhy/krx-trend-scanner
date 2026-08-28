"""Unit and decision-engine tests for Source Authority Review FIX01.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01 (Section 18, 39, 52, 53)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.source_authority_review import (
    DEFAULT_REVIEW_ARTIFACTS_DIR_FIX01,
    CandidateBoundaryViolationError,
    CandidateParseError,
    CandidateSchemaError,
    CoverageStatus,
    NaverDateRangeAdjustedClient,
    ParityStatus,
    ReviewDecision,
    build_review_cohort_fix01,
    evaluate_authority_gates_fix01,
    run_boundary_semantics_probe,
    validate_failure_semantics_matrix,
    validate_parser_negative_matrix,
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
    assert len(res) >= 12
    assert all(v == "PASS" for v in res.values())


def test_failure_semantics_matrix_all_pass():
    res = validate_failure_semantics_matrix()
    assert len(res) >= 7
    assert all(v == "PASS" for v in res.values())


def test_build_review_cohort_fix01_composition():
    cohort = build_review_cohort_fix01()
    assert len(cohort) >= 70
    cats = cohort["control_category"].value_counts()
    assert cats.get("LONG_LIVED_CURRENT_COMMON", 0) >= 10
    assert cats.get("MEDIUM_RECENT_CURRENT_COMMON", 0) >= 5
    assert cats.get("HISTORICAL_ONLY_DELISTED", 0) >= 10
    assert cats.get("ALPHA_23_FULL_SET", 0) == 23
    assert cats.get("CORPORATE_ACTION_CONTROL", 0) >= 8

    # Check 064420 is present in historical controls
    hist_tickers = cohort[cohort["control_category"] == "HISTORICAL_ONLY_DELISTED"]["ticker"].tolist()
    assert "064420" in hist_tickers


def test_historical_cohort_regression_one_broken_control_fails_gate_04():
    # 10 historical controls where 1 has zero data / gap
    cohort_df = pd.DataFrame([
        {"ticker": f"00432{i}", "control_category": "HISTORICAL_ONLY_DELISTED"}
        for i in range(10)
    ])
    cov_rows = [
        {"ticker": f"00432{i}", "control_category": "HISTORICAL_ONLY_DELISTED", "expected_count": 500, "candidate_count": (500 if i < 9 else 0), "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": ("COVERAGE_VALID" if i < 9 else "COVERAGE_GAP")}
        for i in range(10)
    ]
    coverage_df = pd.DataFrame(cov_rows)
    parity_df = pd.DataFrame()
    boundary_df = pd.DataFrame([{"ticker": "005930", "status": "SUCCESS", "no_out_of_bounds": True}] * 7)
    repeat_summary = {"all_content_hashes_stable": True}

    res = evaluate_authority_gates_fix01(
        cohort_df, coverage_df, parity_df, boundary_df, repeat_summary,
        validate_parser_negative_matrix(), validate_failure_semantics_matrix()
    )
    assert res["gate_results"]["gate_04_historical_only_controls"] is False
    assert res["all_gates_passed"] is False


def test_corporate_action_regression_one_not_applicable_or_mismatch_fails_gate_06():
    cohort_df = pd.DataFrame([
        {"ticker": f"00593{i}", "control_category": "CORPORATE_ACTION_CONTROL"}
        for i in range(8)
    ])
    coverage_df = pd.DataFrame([
        {"ticker": f"00593{i}", "control_category": "CORPORATE_ACTION_CONTROL", "expected_count": 240, "candidate_count": 240, "first_candidate_date": "2018-01-02", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"}
        for i in range(8)
    ])
    # 7 MATCH and 1 NOT_APPLICABLE
    parity_rows = [
        {"ticker": f"00593{i}", "control_category": "CORPORATE_ACTION_CONTROL", "overlap_rows": (100 if i < 7 else 0), "parity_status": ("MATCH" if i < 7 else "NOT_APPLICABLE")}
        for i in range(8)
    ]
    parity_df = pd.DataFrame(parity_rows)
    boundary_df = pd.DataFrame([{"ticker": "005930", "status": "SUCCESS", "no_out_of_bounds": True}] * 7)
    repeat_summary = {"all_content_hashes_stable": True}

    res = evaluate_authority_gates_fix01(
        cohort_df, coverage_df, parity_df, boundary_df, repeat_summary,
        validate_parser_negative_matrix(), validate_failure_semantics_matrix()
    )
    assert res["gate_results"]["gate_06_corporate_action_parity"] is False
    assert res["all_gates_passed"] is False


def test_comparator_exception_yields_error_and_fails_gate_07():
    cohort_df = pd.DataFrame([{"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON"}])
    coverage_df = pd.DataFrame([{"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON", "expected_count": 100, "candidate_count": 100, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"}])
    parity_df = pd.DataFrame([{"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON", "overlap_rows": 0, "parity_status": "ERROR"}])
    boundary_df = pd.DataFrame([{"ticker": "005930", "status": "SUCCESS", "no_out_of_bounds": True}] * 7)
    repeat_summary = {"all_content_hashes_stable": True}

    res = evaluate_authority_gates_fix01(
        cohort_df, coverage_df, parity_df, boundary_df, repeat_summary,
        validate_parser_negative_matrix(), validate_failure_semantics_matrix()
    )
    assert res["gate_results"]["gate_07_exact_ohlc_overlap_parity"] is False
    assert res["all_gates_passed"] is False


def test_provenance_hash_mismatch_fails_gate_14():
    cohort_df = pd.DataFrame()
    coverage_df = pd.DataFrame()
    parity_df = pd.DataFrame()
    boundary_df = pd.DataFrame()
    repeat_summary = {"all_content_hashes_stable": True}

    # Incomplete manifest (less than 10 artifacts)
    res = evaluate_authority_gates_fix01(
        cohort_df, coverage_df, parity_df, boundary_df, repeat_summary,
        validate_parser_negative_matrix(), validate_failure_semantics_matrix(),
        artifact_manifest={"artifacts": {"only_one.csv": {"sha256": "abc"}}}
    )
    assert res["gate_results"]["gate_14_provenance_complete"] is False


def test_review_artifacts_fix01_provenance_integrity():
    manifest_p = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX01 / "artifact_manifest.json"
    assert manifest_p.exists(), "artifact_manifest.json must exist in FIX01 dir"

    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = manifest_data.get("artifacts", {})
    assert len(artifacts) >= 10

    for fname, meta in artifacts.items():
        fp = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX01 / fname
        assert fp.exists(), f"Artifact {fname} missing on disk"
        expected_sha = meta["sha256"]
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"SHA256 mismatch for {fname}"
