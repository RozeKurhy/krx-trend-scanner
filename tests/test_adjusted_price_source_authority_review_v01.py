"""Unit and regression tests for Source Authority Review FIX03.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX01
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX02
- ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03 (Section 1-85)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.source_authority_review import (
    CANDIDATE_AUTHORITY_ID,
    DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03,
    EXPECTED_PIT_SHA256,
    EXPECTED_POPULATION_SHA256,
    NAVER_SISE_ENDPOINT,
    START_HEAD_FIX03,
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
    derive_historical_only_cohort_at_runtime_fix03,
    evaluate_authority_gates_fix03,
    execute_failure_semantics_validation,
    reconcile_unexpected_dates_generic_fix03,
    validate_parser_negative_matrix,
    validate_provenance_integrity_fix03,
)


def test_network_attempt_in_fix03_offline_mode_fails():
    client = NaverDateRangeAdjustedClient(allow_network=False)
    with pytest.raises(NetworkForbiddenError):
        client.fetch_raw("005930", "2020-01-02", "2020-01-10")


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

    # Shuffle records in reverse order
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

    # Remove 064420
    data_no_064420 = dict(data)
    data_no_064420["records"] = [p for p in data["records"] if p.get("ticker") != "064420"]
    pop_file = tmp_path / "pop_no_064420.json"
    pop_file.write_text(json.dumps(data_no_064420), encoding="utf-8")

    with pytest.raises(ValueError, match="Mandatory historical control '064420' is missing"):
        derive_historical_only_cohort_at_runtime_fix03(pop_path=pop_file)


def test_phantom_reconciliation_requires_pykrx_presence(tmp_path):
    fix02_mock = tmp_path / "source_authority_unexpected_date_reconciliation_fix02.csv"
    fix02_mock.write_text(
        "ticker,date,candidate_open,candidate_high,candidate_low,candidate_close,candidate_volume,pykrx_row_present,pykrx_open,pykrx_high,pykrx_low,pykrx_close,pykrx_volume\n"
        "035720,2021-04-12,0.0,0.0,0.0,112000.0,0.0,False,0.0,0.0,0.0,0.0,0.0\n"
    )
    df = reconcile_unexpected_dates_generic_fix03(fix02_dir=tmp_path)
    assert len(df) == 1
    assert df["reconciliation_status"].iloc[0] == "UNRESOLVED"
    assert "PYKRX_ROW_ABSENT" in df["reconciliation_failure_reason"].iloc[0]


def test_phantom_reconciliation_requires_ohlc_match(tmp_path):
    fix02_mock = tmp_path / "source_authority_unexpected_date_reconciliation_fix02.csv"
    fix02_mock.write_text(
        "ticker,date,candidate_open,candidate_high,candidate_low,candidate_close,candidate_volume,pykrx_row_present,pykrx_open,pykrx_high,pykrx_low,pykrx_close,pykrx_volume\n"
        "035720,2021-04-12,0.0,0.0,0.0,112000.0,0.0,True,0.0,0.0,0.0,110000.0,0.0\n"
    )
    df = reconcile_unexpected_dates_generic_fix03(fix02_dir=tmp_path)
    assert len(df) == 1
    assert df["reconciliation_status"].iloc[0] == "UNRESOLVED"
    assert "OHLCV_MISMATCH" in df["reconciliation_failure_reason"].iloc[0]


def test_phantom_reconciliation_requires_volume_match(tmp_path):
    fix02_mock = tmp_path / "source_authority_unexpected_date_reconciliation_fix02.csv"
    fix02_mock.write_text(
        "ticker,date,candidate_open,candidate_high,candidate_low,candidate_close,candidate_volume,pykrx_row_present,pykrx_open,pykrx_high,pykrx_low,pykrx_close,pykrx_volume\n"
        "035720,2021-04-12,0.0,0.0,0.0,112000.0,0.0,True,0.0,0.0,0.0,112000.0,100.0\n"
    )
    df = reconcile_unexpected_dates_generic_fix03(fix02_dir=tmp_path)
    assert len(df) == 1
    assert df["reconciliation_status"].iloc[0] == "UNRESOLVED"
    assert "OHLCV_MISMATCH" in df["reconciliation_failure_reason"].iloc[0]


def test_corporate_file_exists_but_record_missing_invalid(tmp_path):
    fake_json = tmp_path / "fake_corp.json"
    fake_json.write_text(json.dumps({"unrelated": "data"}), encoding="utf-8")

    res = CorporateActionEvidenceResolver.resolve_control(
        ticker="005930",
        claimed_event_type="STOCK_SPLIT_50_TO_1",
        claimed_event_date="2018-05-04",
        comparison_window_start="2018-01-02",
        comparison_window_end="2018-12-28",
        evidence_path_str=str(fake_json),
    )
    assert res["evidence_valid"] is False


def test_corporate_blocked_record_invalid(tmp_path):
    fake_csv = tmp_path / "cases.csv"
    fake_csv.write_text("ticker,event_type,event_reference,status\n035420,split,2018,NOT_EVALUATED_AUTH_BLOCKED\n", encoding="utf-8")

    res = CorporateActionEvidenceResolver.resolve_control(
        ticker="035420",
        claimed_event_type="STOCK_SPLIT_5_TO_1",
        claimed_event_date="2018-10-12",
        comparison_window_start="2018-01-02",
        comparison_window_end="2018-12-28",
        evidence_path_str=str(fake_csv),
    )
    assert res["evidence_valid"] is False
    assert "BLOCKED" in res["validation_reason"]


def test_corporate_valid_resolved_record_valid():
    res = CorporateActionEvidenceResolver.resolve_control(
        ticker="005930",
        claimed_event_type="STOCK_SPLIT_50_TO_1",
        claimed_event_date="2018-05-04",
        comparison_window_start="2018-01-02",
        comparison_window_end="2018-12-28",
        evidence_path_str="artifacts/data/krx_openapi/v01/corporate_action_validation.json",
    )
    assert res["evidence_valid"] is True
    assert res["ticker_match"] is True
    assert res["event_type_match"] is True


def test_population_authority_physical_mutation_gate14_fail(tmp_path):
    pop_p = tmp_path / "mutated_pop.json"
    pop_p.write_text("mutated bytes\n", encoding="utf-8")
    pit_p = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/pit_common_denominator_v01.json")

    manifest = {"candidate_id": CANDIDATE_AUTHORITY_ID, "start_head": START_HEAD_FIX03, "artifacts": {"a": {"sha256": "x", "size_bytes": 1}}}
    schema = {"endpoint": NAVER_SISE_ENDPOINT, "request_type": "1", "count_parameter": "5000", "field_count_exact": 6}

    res = validate_provenance_integrity_fix03(tmp_path, manifest, schema, pop_path=pop_p, pit_path=pit_p)
    assert res["all_provenance_valid"] is False
    assert res["population_authority_valid"] is False


def test_pit_physical_mutation_gate14_fail(tmp_path):
    pop_p = Path("artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/survivorship_safe_denominator_freeze_v01.json")
    pit_p = tmp_path / "mutated_pit.json"
    pit_p.write_text(json.dumps({"schema": "pit_common_denominator_v01", "pit_common_denominator_sha256": "wrong_sha"}), encoding="utf-8")

    manifest = {"candidate_id": CANDIDATE_AUTHORITY_ID, "start_head": START_HEAD_FIX03, "artifacts": {"a": {"sha256": "x", "size_bytes": 1}}}
    schema = {"endpoint": NAVER_SISE_ENDPOINT, "request_type": "1", "count_parameter": "5000", "field_count_exact": 6}

    res = validate_provenance_integrity_fix03(tmp_path, manifest, schema, pop_path=pop_p, pit_path=pit_p)
    assert res["all_provenance_valid"] is False
    assert res["pit_authority_valid"] is False


def test_parser_negative_matrix_all_pass():
    res = validate_parser_negative_matrix()
    assert len(res) >= 13
    assert all(v == "PASS" for v in res.values())


def test_failure_semantics_executed_and_pass():
    records = execute_failure_semantics_validation()
    assert len(records) == 7
    assert all(r["passed"] is True for r in records)


def test_review_artifacts_fix03_manifest_integrity():
    manifest_p = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03 / "artifact_manifest.json"
    assert manifest_p.exists(), "artifact_manifest.json must exist in FIX03 dir"

    manifest_data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = manifest_data.get("artifacts", {})
    assert len(artifacts) >= 14

    for fname, meta in artifacts.items():
        fp = DEFAULT_REVIEW_ARTIFACTS_DIR_FIX03 / fname
        assert fp.exists(), f"Artifact {fname} missing on disk"
        expected_sha = meta["sha256"]
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == expected_sha, f"SHA256 mismatch for {fname}"
