"""Unit and regression tests for Corporate Action Authority Evidence Acquisition FIX01.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX01 (Section 53-62)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.corporate_action_authority import (
    DEFAULT_CORP_EVIDENCE_DIR_FIX01,
    PARENT_FIX03_CORRECTION_DIR,
    START_HEAD_CORP_EVIDENCE_FIX01,
    AuthoritySourceTier,
    ClaimAdjudicationStatus,
    CorporateActionNetworkAccounting,
    OfficialEvidenceContentParser,
    get_prior_claim_definitions,
    run_corporate_action_evidence_acquisition_fix01,
    verify_parent_authority_freeze,
)


def test_parent_authority_freeze_validation():
    res = verify_parent_authority_freeze()
    assert res["all_parent_inputs_unchanged"] is True
    assert res["parent_artifacts_verified_count"] == 8
    assert len(res["mismatches"]) == 0


def test_dart_denial_page_rejected_blocked_page():
    raw_denial = "<html><head><title>거부</title></head><body><p>검토중인 문서입니다. 조회할 수 없습니다.</p></body></html>".encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_denial,
        claimed_ticker="035720",
        claimed_issuer="카카오",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2021-04-15",
        claimed_window_start="2021-01-04",
        claimed_window_end="2021-12-30",
        source_id="DART_OFFICIAL_DISCLOSURE",
        record_id="DART_RCP_20210225001089",
    )
    assert parsed["blocked_page_detected"] is True
    assert parsed["document_valid"] is False
    assert parsed["authority_valid"] is False
    assert parsed["validation_reason"] == "BLOCKED_PAGE_DETECTED"


def test_wrong_issuer_rejected_wrong_document():
    raw_wrong = "<html><head><title>교보악사자산운용/투자설명서/2018.07.26</title></head><body><h1>교보악사</h1></body></html>".encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_wrong,
        claimed_ticker="035420",
        claimed_issuer="NAVER",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-10-12",
        claimed_window_start="2018-01-02",
        claimed_window_end="2018-12-28",
        source_id="DART_OFFICIAL_DISCLOSURE",
        record_id="DART_RCP_20180726000405",
    )
    assert parsed["blocked_page_detected"] is False
    assert parsed["issuer_match"] is False
    assert parsed["document_valid"] is False
    assert parsed["authority_valid"] is False
    assert "WRONG_DOCUMENT_ISSUER_MISMATCH" in parsed["validation_reason"]


def test_wrong_event_type_rejected():
    raw_other_event = "<html><head><title>현대제철/감사보고서/2015.04.08</title></head><body><h1>현대제철</h1></body></html>".encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_other_event,
        claimed_ticker="004020",
        claimed_issuer="현대제철",
        claimed_event_type="MERGER",
        claimed_anchor_type="MERGER_EFFECTIVE_DATE",
        claimed_anchor_date="2015-07-01",
        claimed_window_start="2015-01-02",
        claimed_window_end="2015-12-30",
        source_id="DART_OFFICIAL_DISCLOSURE",
        record_id="DART_RCP_20150408000450",
    )
    assert parsed["blocked_page_detected"] is False
    assert parsed["issuer_match"] is True
    assert parsed["event_type_match"] is False
    assert parsed["document_valid"] is False
    assert parsed["authority_valid"] is False
    assert "EVENT_TYPE_MISMATCH" in parsed["validation_reason"]


def test_valid_json_record_accepted():
    valid_json = json.dumps({
        "ticker": "005930",
        "event": "Samsung Electronics 50:1 split",
        "dates": ["2018-04-27", "2018-05-04"],
    }).encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=valid_json,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        claimed_window_start="2018-01-02",
        claimed_window_end="2018-12-28",
        source_id="DART_OFFICIAL_DISCLOSURE",
        record_id="DART_RCP_20180323001340",
    )
    assert parsed["authority_valid"] is True
    assert parsed["issuer_match"] is True
    assert parsed["event_type_match"] is True
    assert parsed["document_valid"] is True


def test_raw_content_beats_filename(tmp_path):
    fake_file = tmp_path / "035420_STOCK_SPLIT_fake.html"
    fake_file.write_text("<html><head><title>교보악사자산운용/보고서/2018.07.26</title></head></html>", encoding="utf-8")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=fake_file.read_bytes(),
        claimed_ticker="035420",
        claimed_issuer="NAVER",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-10-12",
        claimed_window_start="2018-01-02",
        claimed_window_end="2018-12-28",
        source_id="DART_OFFICIAL_DISCLOSURE",
        record_id="DART_RCP_20180726000405",
    )
    assert parsed["authority_valid"] is False


def test_gate_06_fails_when_authority_valid_controls_lt_8():
    dec_p = DEFAULT_CORP_EVIDENCE_DIR_FIX01 / "adjusted_price_source_authority_corporate_action_evidence_v01_fix01.json"
    assert dec_p.exists()

    data = json.loads(dec_p.read_text(encoding="utf-8"))
    assert data["final_authority_valid_controls"] == 1
    assert data["gate_06_result"] is False
    assert data["review_decision"] == "CONDITIONAL_REVIEW_REQUIRED"
    assert data["production_integration_authorized"] is False
    assert data["active_production_authority_changed"] is False
    assert data["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX01"


def test_event_sensitive_metrics_derived_from_actual_rows():
    parity_p = DEFAULT_CORP_EVIDENCE_DIR_FIX01 / "corporate_action_event_sensitive_parity_v01_fix01.csv"
    assert parity_p.exists()

    df = pd.read_csv(parity_p, dtype={"ticker": str})
    assert len(df) == 8

    # Check that events at different dates have different pre/post rows (no static 100/overlap-100!)
    row_005930 = df[df["ticker"] == "005930"].iloc[0]
    row_035420 = df[df["ticker"] == "035420"].iloc[0]

    # 005930 split is in May 2018; 035420 split is in Oct 2018
    # Within the same 2018 year window, NAVER must have substantially more pre-event rows than Samsung!
    assert int(row_035420["pre_event_candidate_rows"]) > int(row_005930["pre_event_candidate_rows"])


def test_fix01_manifest_integrity():
    manifest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX01 / "artifact_manifest.json"
    assert manifest_p.exists()

    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 10

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Artifact {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"SHA mismatch for {fname}"
