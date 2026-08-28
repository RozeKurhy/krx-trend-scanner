"""Unit and regression tests for Corporate Action Authority Evidence Acquisition FIX02.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX02 (Section 61-71)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.corporate_action_authority import (
    DEFAULT_CORP_EVIDENCE_DIR_FIX02,
    PARENT_FIX03_CORRECTION_DIR,
    START_HEAD_CORP_EVIDENCE_FIX02,
    AuthoritySourceTier,
    ClaimAdjudicationStatus,
    CorporateActionNetworkAccounting,
    OfficialEvidenceContentParser,
    get_official_discovery_targets,
    run_corporate_action_evidence_acquisition_fix02,
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
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="DART_RCP_20210225000572",
        expected_record_id="DART_RCP_20210225000572",
    )
    assert parsed["blocked_page_detected"] is True
    assert parsed["authority_valid"] is False
    assert parsed["validation_reason"] == "BLOCKED_OR_EMPTY_DOCUMENT_DETECTED"


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
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="DART_RCP_20180726000282",
        expected_record_id="DART_RCP_20180726000282",
    )
    assert parsed["issuer_identity_valid"] is False
    assert parsed["authority_valid"] is False
    assert "WRONG_DOCUMENT_ISSUER_MISMATCH" in parsed["validation_reason"]


def test_wrong_event_type_rejected():
    raw_other_event = "<html><head><title>현대제철/감사보고서/2015.04.08</title></head><body><h1>현대제철</h1><p>감사보고서 본문</p></body></html>".encode("utf-8")
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
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="DART_RCP_20150408000450",
        expected_record_id="DART_RCP_20150408000450",
    )
    assert parsed["issuer_identity_valid"] is True
    assert parsed["event_type_valid"] is False
    assert parsed["authority_valid"] is False
    assert "EVENT_TYPE_MISMATCH" in parsed["validation_reason"]


def test_internal_artifact_cannot_be_official_evidence():
    raw_internal = json.dumps({"ticker": "005930", "event": "Samsung split"}).encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_internal,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        claimed_window_start="2018-01-02",
        claimed_window_end="2018-12-28",
        source_id="INTERNAL_VALIDATION",
        source_tier=AuthoritySourceTier.INTERNAL_VALIDATION.value,
        discovered_record_id="artifacts/data/krx_openapi/v01/corporate_action_validation.json",
        expected_record_id="artifacts/data/krx_openapi/v01/corporate_action_validation.json",
    )
    assert parsed["official_source_valid"] is False
    assert parsed["authority_valid"] is False
    assert "INTERNAL_VALIDATION_ARTIFACT" in parsed["validation_reason"]


def test_record_identity_valid_requires_matching_id():
    raw_doc = "<html><head><title>삼성전자/주요사항보고서(주식분할결정)/2018.01.31</title></head><body><h1>삼성전자</h1><p>접수번호: 20180131000186</p><p>분할기일: 2018-05-04</p></body></html>".encode("utf-8")
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
        discovered_record_id="DART_RCP_WRONG_ID_999999",
        expected_record_id="DART_RCP_20180131000186",
    )
    assert parsed["record_identity_valid"] is False
    assert parsed["authority_valid"] is False


def test_event_timing_valid_requires_actual_event_date():
    raw_no_date = "<html><head><title>삼성전자/주요사항보고서(주식분할결정)/2018.01.31</title></head><body><h1>삼성전자</h1><p>접수번호: 20180131000186</p></body></html>".encode("utf-8")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_no_date,
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
    )
    assert parsed["event_timing_valid"] is False
    assert parsed["authority_valid"] is False


def test_fix02_full_execution_approves_all_15_gates():
    dec_p = DEFAULT_CORP_EVIDENCE_DIR_FIX02 / "adjusted_price_source_authority_corporate_action_evidence_v01_fix02.json"
    assert dec_p.exists()

    data = json.loads(dec_p.read_text(encoding="utf-8"))
    assert data["final_authority_valid_controls"] == 8
    assert data["gate_06_result"] is True
    assert data["all_gates_passed"] is True
    assert data["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert data["production_integration_authorized"] is True
    assert data["active_production_authority_changed"] is False
    assert data["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"


def test_fix02_manifest_integrity():
    manifest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX02 / "artifact_manifest.json"
    assert manifest_p.exists()

    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 12

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Artifact {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"SHA mismatch for {fname}"
