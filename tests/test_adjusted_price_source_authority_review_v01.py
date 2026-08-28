"""Unit and decision-engine tests for Source Authority Review V01.

Directives: Section 33, 59, 60 of ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.source_authority_review import (
    DEFAULT_REVIEW_ARTIFACTS_DIR,
    CoverageStatus,
    NaverDateRangeAdjustedClient,
    ParityStatus,
    ReviewDecision,
    build_review_cohort,
    evaluate_authority_gates,
    run_boundary_semantics_probe,
)


def test_candidate_schema_parsing_valid():
    sample_xml = """
    <protocol>
        <chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102">
            <item data="20200102|55500|56000|55000|55200|12993228" />
            <item data="20200103|56000|56600|54900|55500|15422255" />
        </chartdata>
    </protocol>
    """
    df = NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)
    assert len(df) == 2
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]
    assert df["date"].tolist() == ["2020-01-02", "2020-01-03"]
    assert df["open"].tolist() == [55500.0, 56000.0]
    assert df["close"].tolist() == [55200.0, 55500.0]


def test_duplicate_date_rejection_fail_closed():
    sample_xml = """
    <protocol>
        <chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102">
            <item data="20200102|55500|56000|55000|55200|12993228" />
            <item data="20200102|55500|56000|55000|55200|12993228" />
        </chartdata>
    </protocol>
    """
    with pytest.raises(ValueError, match="Duplicate date 2020-01-02"):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_malformed_xml_fail_closed():
    sample_xml = "<protocol><chartdata symbol='005930'><item data='incomplete"
    with pytest.raises(ValueError, match="Malformed XML response"):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_invalid_field_count_fail_closed():
    sample_xml = """
    <protocol>
        <chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102">
            <item data="20200102|55500|56000|55000" />
        </chartdata>
    </protocol>
    """
    with pytest.raises(ValueError, match="Invalid field count"):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_non_numeric_ohlc_fail_closed():
    sample_xml = """
    <protocol>
        <chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102">
            <item data="20200102|55500|INVALID|55000|55200|12993228" />
        </chartdata>
    </protocol>
    """
    with pytest.raises(ValueError, match="Non-numeric OHLC"):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_unparseable_date_fail_closed():
    sample_xml = """
    <protocol>
        <chartdata symbol="005930" count="5000" timeframe="day" precision="0" origintime="20200102">
            <item data="BAD_DATE|55500|56000|55000|55200|12993228" />
        </chartdata>
    </protocol>
    """
    with pytest.raises(ValueError, match="Unparseable date"):
        NaverDateRangeAdjustedClient.parse_xml_payload(sample_xml)


def test_empty_xml_handling():
    empty_xml = "<protocol><chartdata symbol='000610' count='0' timeframe='day' precision='0' origintime=''></chartdata></protocol>"
    df = NaverDateRangeAdjustedClient.parse_xml_payload(empty_xml)
    assert len(df) == 0
    assert list(df.columns) == ["date", "open", "high", "low", "close", "volume"]


def test_review_cohort_composition():
    cohort_df = build_review_cohort()
    assert len(cohort_df) >= 60
    # Must have all required categories
    categories = set(cohort_df["control_category"])
    assert "LONG_LIVED_CURRENT_COMMON" in categories
    assert "MEDIUM_RECENT_CURRENT_COMMON" in categories
    assert "HISTORICAL_ONLY_DELISTED" in categories
    assert "ALPHA_23_FULL_SET" in categories
    assert "CORPORATE_ACTION_CONTROL" in categories
    assert "EXISTING_EMPTY_CONTROL" in categories
    assert "EXISTING_OHLC_ANOMALY_CONTROL" in categories
    assert "KNOWN_UNSUPPORTED_CONTROL" in categories

    # Verify Alpha-23 count is exactly 23
    alpha_rows = cohort_df[cohort_df["control_category"] == "ALPHA_23_FULL_SET"]
    assert len(alpha_rows) == 23


def test_decision_engine_synthetic_all_pass():
    cohort_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON"},
        {"ticker": "000660", "control_category": "LONG_LIVED_CURRENT_COMMON"},
    ])
    # Build valid mock dataframes
    coverage_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON", "candidate_count": 3000, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"},
        {"ticker": "000660", "control_category": "LONG_LIVED_CURRENT_COMMON", "candidate_count": 3000, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"},
    ] * 5)
    # Add historical controls
    hist_cov = pd.DataFrame([
        {"ticker": f"06442{i}", "control_category": "HISTORICAL_ONLY_DELISTED", "candidate_count": 500, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"}
        for i in range(10)
    ])
    alpha_cov = pd.DataFrame([
        {"ticker": f"000{i}A0", "control_category": "ALPHA_23_FULL_SET", "candidate_count": 0, "first_candidate_date": "", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "LEGITIMATE_NO_DATA"}
        for i in range(23)
    ])
    coverage_df = pd.concat([coverage_df, hist_cov, alpha_cov], ignore_index=True)

    parity_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "CORPORATE_ACTION_CONTROL", "overlap_rows": 100, "parity_status": "MATCH"}
        for _ in range(8)
    ])
    boundary_df = pd.DataFrame([
        {"ticker": "005930", "status": "SUCCESS", "no_out_of_bounds": True}
        for _ in range(7)
    ])
    repeat_summary = {"all_content_hashes_stable": True}

    res = evaluate_authority_gates(cohort_df, coverage_df, parity_df, boundary_df, repeat_summary)
    assert res["all_gates_passed"] is True
    assert res["review_decision"] == ReviewDecision.APPROVED_FOR_PRODUCTION_INTEGRATION.value
    assert res["production_integration_authorized"] is True
    assert res["active_production_authority_changed"] is False
    assert res["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"


def test_decision_engine_synthetic_parity_mismatch_rejects():
    cohort_df = pd.DataFrame([{"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON"}])
    coverage_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON", "candidate_count": 3000, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"}
    ])
    parity_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON", "overlap_rows": 100, "parity_status": "MISMATCH"}
    ])
    boundary_df = pd.DataFrame([{"ticker": "005930", "status": "SUCCESS", "no_out_of_bounds": True}] * 7)
    repeat_summary = {"all_content_hashes_stable": True}

    res = evaluate_authority_gates(cohort_df, coverage_df, parity_df, boundary_df, repeat_summary)
    assert res["all_gates_passed"] is False
    assert res["review_decision"] == ReviewDecision.REJECTED_AS_PRODUCTION_AUTHORITY.value
    assert res["production_integration_authorized"] is False
    assert res["recommended_next_state"] == "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"


def test_decision_engine_synthetic_unresolved_conditions_conditional():
    cohort_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON"},
        {"ticker": "000660", "control_category": "LONG_LIVED_CURRENT_COMMON"},
    ])
    coverage_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "LONG_LIVED_CURRENT_COMMON", "candidate_count": 2500, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"},
        {"ticker": "000660", "control_category": "LONG_LIVED_CURRENT_COMMON", "candidate_count": 3000, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"},
    ] * 5)
    hist_cov = pd.DataFrame([
        {"ticker": f"06442{i}", "control_category": "HISTORICAL_ONLY_DELISTED", "candidate_count": 500, "first_candidate_date": "2010-01-04", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "COVERAGE_VALID"}
        for i in range(10)
    ])
    alpha_cov = pd.DataFrame([
        {"ticker": f"000{i}A0", "control_category": "ALPHA_23_FULL_SET", "candidate_count": 0, "first_candidate_date": "", "pre_listing_rows": 0, "post_delisting_rows": 0, "future_rows": 0, "coverage_status": "LEGITIMATE_NO_DATA"}
        for i in range(23)
    ])
    coverage_df = pd.concat([coverage_df, hist_cov, alpha_cov], ignore_index=True)

    parity_df = pd.DataFrame([
        {"ticker": "005930", "control_category": "CORPORATE_ACTION_CONTROL", "overlap_rows": 100, "parity_status": "MATCH"}
        for _ in range(8)
    ])
    boundary_df = pd.DataFrame([
        {"ticker": "005930", "status": "SUCCESS", "no_out_of_bounds": True}
        for _ in range(7)
    ])
    repeat_summary = {"all_content_hashes_stable": True}

    res = evaluate_authority_gates(cohort_df, coverage_df, parity_df, boundary_df, repeat_summary)
    assert res["all_gates_passed"] is False
    assert res["review_decision"] == ReviewDecision.CONDITIONAL_REVIEW_REQUIRED.value
    assert res["production_integration_authorized"] is False
    assert res["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01"


def test_review_artifacts_provenance_integrity():
    manifest_p = DEFAULT_REVIEW_ARTIFACTS_DIR / "artifact_manifest.json"
    assert manifest_p.exists(), "artifact_manifest.json must exist"

    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = manifest_data.get("artifacts", {})
    assert len(artifacts) >= 10

    for fname, meta in artifacts.items():
        fp = DEFAULT_REVIEW_ARTIFACTS_DIR / fname
        assert fp.exists(), f"Artifact {fname} must exist on disk"
        disk_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert meta["sha256"] == disk_sha, f"SHA256 mismatch for {fname}: recorded={meta['sha256']}, actual={disk_sha}"
