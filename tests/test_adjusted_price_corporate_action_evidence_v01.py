"""Unit and regression tests for Corporate Action Authority Live Evidence Acquisition FIX03.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03 (Section 68-80)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.corporate_action_authority import (
    DEFAULT_CORP_EVIDENCE_DIR_FIX03,
    PARENT_FIX03_CORRECTION_DIR,
    START_HEAD_CORP_EVIDENCE_FIX03,
    AuthoritySourceTier,
    ClaimAdjudicationStatus,
    CorporateActionNetworkAccounting,
    OfficialEvidenceContentParser,
    get_prior_claim_search_hints,
    run_corporate_action_evidence_acquisition_fix03,
    verify_parent_authority_freeze,
)


def test_parent_authority_freeze_validation():
    res = verify_parent_authority_freeze()
    assert res["all_parent_inputs_unchanged"] is True
    assert res["parent_artifacts_verified_count"] == 8
    assert len(res["mismatches"]) == 0


def test_synthetic_official_document_prohibited():
    raw_doc = "<html><head><title>삼성전자/주요사항보고서/2018.01.31</title></head><body><h1>삼성전자</h1><p>분할기일: 2018-05-04</p></body></html>".encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        claimed_window_start="2018-01-02",
        claimed_window_end="2018-12-28",
        source_id="DART_OFFICIAL_DISCLOSURE",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="DART_RCP_20180131000186",
        expected_record_id="DART_RCP_20180131000186",
        evidence_origin="GENERATED",
    )
    assert parsed["official_source_valid"] is False
    assert parsed["authority_valid"] is False
    assert "SYNTHETIC_OR_FORBIDDEN_EVIDENCE_ORIGIN" in parsed["validation_reason"]


def test_canonical_module_has_no_synthetic_generator():
    import trend_scanner.data.corporate_action_authority as ca_mod
    assert not hasattr(ca_mod, "generate_official_raw_disclosure_document")


def test_event_timing_extracted_independently_from_content():
    raw_doc = "<html><head><title>삼성전자/주요사항보고서(주식분할결정)/2018.01.31</title></head><body><h1>삼성전자</h1><p>접수번호: 20180131000186</p><p>분할기일: 2018-05-03</p></body></html>".encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",  # Claimed was May 4
        claimed_window_start="2018-01-02",
        claimed_window_end="2018-12-28",
        source_id="DART_OFFICIAL_DISCLOSURE",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="DART_RCP_20180131000186",
        expected_record_id="DART_RCP_20180131000186",
        evidence_origin="LIVE_DART_HTTP_RESPONSE",
    )
    assert parsed["parsed_anchor_date"] == "2018-05-03"  # Must extract actual May 3 from document
    assert parsed["authority_valid"] is True


def test_record_id_independence():
    raw_doc = "<html><head><title>삼성전자/주요사항보고서/2018.01.31</title></head><body><h1>삼성전자</h1><p>접수번호: 20180131000186</p><p>분할기일: 2018-05-04</p></body></html>".encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        claimed_window_start="2018-01-02",
        claimed_window_end="2018-12-28",
        source_id="DART_OFFICIAL_DISCLOSURE",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="DART_RCP_OTHER_999999",
        expected_record_id="DART_RCP_20180131000186",
        evidence_origin="LIVE_DART_HTTP_RESPONSE",
    )
    assert parsed["record_identity_valid"] is False
    assert parsed["authority_valid"] is False


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
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="DART_RCP_20210225000572",
        expected_record_id="DART_RCP_20210225000572",
        evidence_origin="LIVE_DART_HTTP_RESPONSE",
    )
    assert parsed["blocked_page_detected"] is True
    assert parsed["authority_valid"] is False


def test_fix03_conditional_decision_when_evidence_deficit():
    dec_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03 / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03.json"
    assert dec_p.exists()

    data = json.loads(dec_p.read_text(encoding="utf-8"))
    assert data["review_decision"] == "CONDITIONAL_REVIEW_REQUIRED"
    assert data["production_integration_authorized"] is False
    assert data["active_production_authority_changed"] is False
    assert data["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03"


def test_fix03_live_attestation_artifact():
    attest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03 / "canonical_live_evidence_attestation_v01_fix03.json"
    assert attest_p.exists()

    data = json.loads(attest_p.read_text(encoding="utf-8"))
    assert data["execution_mode"] == "LIVE_EVIDENCE_ACQUISITION"
    assert data["synthetic_official_documents_used"] is False
    assert data["synthetic_price_rows_used"] is False
    assert data["all_official_records_request_linked"] is True


def test_fix03_manifest_integrity():
    manifest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03 / "artifact_manifest.json"
    assert manifest_p.exists()

    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 12

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Artifact {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"SHA mismatch for {fname}"
