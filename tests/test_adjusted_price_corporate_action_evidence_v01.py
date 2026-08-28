"""Comprehensive Unit, Negative, Provenance, and Regression Tests for FIX03_CORRECTION_2.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2 (Section 79-96)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.opendart_preflight import (
    OpenDARTCredentialMissingError,
    get_opendart_api_key,
    run_opendart_preflight,
)
from trend_scanner.data.corporate_action_authority import (
    DEFAULT_CORP_EVIDENCE_DIR_FIX03,
    DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION,
    DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2,
    PARENT_FIX03_CORRECTION_DIR,
    START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_2,
    AuthoritySourceTier,
    ClaimAdjudicationStatus,
    CorporateActionNetworkAccounting,
    OfficialEvidenceContentParser,
    get_official_discovery_search_targets,
    run_corporate_action_evidence_acquisition_fix03_correction_2,
    verify_parent_authority_freeze,
)


# ==============================================================================
# 1. Environment & Credential Resolution Tests (Section 79)
# ==============================================================================

def test_environment_key_resolution_success(monkeypatch):
    monkeypatch.setenv("OPENDART_API_KEY", "test_mock_api_key_12345")
    key = get_opendart_api_key()
    assert key == "test_mock_api_key_12345"


def test_missing_environment_key_raises_explicit_error(monkeypatch):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with patch("trend_scanner.data.opendart_preflight.load_dotenv"):
        with pytest.raises(OpenDARTCredentialMissingError) as exc_info:
            get_opendart_api_key()
        assert "OPENDART_CREDENTIAL_MISSING" in str(exc_info.value)


def test_personal_absolute_secret_path_absent():
    import inspect
    import trend_scanner.data.corporate_action_authority as ca_mod
    import trend_scanner.data.opendart_preflight as pf_mod

    ca_src = inspect.getsource(ca_mod)
    pf_src = inspect.getsource(pf_mod)

    assert "/Users/june/Documents/projects/env.md" not in ca_src
    assert "/Users/june/Documents/projects/env.md" not in pf_src
    assert "/Users/" not in ca_src
    assert "env.md" not in ca_src


# ==============================================================================
# 2. OpenDART Preflight Tests (Section 80, 81)
# ==============================================================================

def test_preflight_success_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "mock_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "000", "message": "정상"}

    with patch("requests.Session.get", return_value=mock_resp):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["credential_present"] is True
        assert res["network_reachable"] is True
        assert res["authenticated_request_success"] is True
        assert res["opendart_status"] == "000"
        assert res["verdict"] == "READY"


def test_preflight_missing_key_verdict_fail(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with patch("trend_scanner.data.opendart_preflight.load_dotenv"):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["credential_present"] is False
        assert res["verdict"] == "FAIL"
        assert res["error_reason"] == "OPENDART_CREDENTIAL_MISSING"


def test_preflight_auth_failed_status_010(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "invalid_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "010", "message": "등록되지 않은 인증키입니다."}

    with patch("requests.Session.get", return_value=mock_resp):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["verdict"] == "FAIL"
        assert "OPENDART_AUTH_FAILED" in res["error_reason"]


def test_preflight_hard_gate_blocks_acquisition(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with patch("trend_scanner.data.opendart_preflight.load_dotenv"):
        with pytest.raises(RuntimeError) as exc_info:
            run_corporate_action_evidence_acquisition_fix03_correction_2(output_dir=tmp_path)
        assert "OpenDART Preflight Hard Gate FAIL" in str(exc_info.value)


# ==============================================================================
# 3. Official Anchor Independence & Timing Tests (Section 82, 83, 84)
# ==============================================================================

def test_official_anchor_independent_from_prior_claim():
    # Long valid document containing explicit split date: 2018-05-03, while claim says 2018-05-04
    raw_doc = ("<html><head><title>주주총회소집공고</title></head><body><h1>(주)삼성전자</h1>"
               "<DOCUMENT-NAME>주주총회소집공고(주식분할)</DOCUMENT-NAME><COMPANY-NAME>삼성전자</COMPANY-NAME>"
               "<p>주식분할의 건에 관하여 결의합니다. 분할기일: 2018년 05월 03일입니다.</p>"
               "<div>상세 공시 본문 내용이 충분히 긴 공식 공시 문서 텍스트 패딩입니다.</div></body></html>").encode("euc-kr")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",  # Prior claim was May 4
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
        evidence_origin="LIVE_OPENDART_API_RESPONSE",
    )
    assert parsed["official_anchor_date"] == "2018-05-03"  # Extracted strictly from source text
    assert parsed["official_anchor_source_field"] == "분할기일"
    assert parsed["claim_anchor_match"] is False  # Acknowledges mismatch with prior claim
    assert parsed["event_timing_valid"] is True
    assert parsed["authority_valid"] is True


def test_missing_event_timing_field_fails_closed():
    # Document has company name and report name, but no recognized corporate event field
    raw_doc = ("<html><head><title>주식분할결정</title></head><body><h1>(주)삼성전자</h1>"
               "<DOCUMENT-NAME>주식분할결정</DOCUMENT-NAME><COMPANY-NAME>삼성전자</COMPANY-NAME>"
               "<p>정기공시 본문 내용만 있고 세부 분할기일이나 효력발생일 등의 timing field가 전혀 없는 문서입니다. "
               "충분한 길이의 패딩 텍스트를 포함하고 있습니다.</p></body></html>").encode("euc-kr")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
        evidence_origin="LIVE_OPENDART_API_RESPONSE",
    )
    assert parsed["event_timing_valid"] is False
    assert parsed["authority_valid"] is False
    assert "EVENT_TIMING_NOT_DERIVED" in parsed["validation_reason"]


# ==============================================================================
# 4. Strict Discovery / Document Identity & No Hardcoded Logic (Section 85, 86, 87)
# ==============================================================================

def test_discovery_document_identity_mismatch_fails():
    raw_doc = ("<html><head><title>주주총회소집공고</title></head><body><h1>(주)삼성전자</h1>"
               "<DOCUMENT-NAME>주주총회소집공고(주식분할)</DOCUMENT-NAME><COMPANY-NAME>삼성전자</COMPANY-NAME>"
               "<p>주식분할 분할기일: 2018년 05월 04일. 충분한 길이의 패딩 텍스트를 포함합니다.</p></body></html>").encode("euc-kr")
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000490",  # Mismatched record ID
        evidence_origin="LIVE_OPENDART_API_RESPONSE",
    )
    assert parsed["record_identity_valid"] is False
    assert parsed["authority_valid"] is False
    assert "RECORD_IDENTITY_MISMATCH" in parsed["validation_reason"]


def test_no_hardcoded_ticker_specific_fallback():
    import inspect
    import trend_scanner.data.corporate_action_authority as ca_mod
    src = inspect.getsource(ca_mod)
    assert "if t == \"005930\"" not in src
    assert "if ticker == \"005930\"" not in src
    assert "sel_rcp_no = \"20180223000294\"" not in src


# ==============================================================================
# 5. Evidence Linkage & Provenance Validation (Section 88, 89, 90, 91, 94)
# ==============================================================================

def test_fix03_correction_2_evidence_linkage_valid():
    link_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2 / "live_evidence_linkage_validation_v01_fix03_correction_2.json"
    assert link_p.exists()

    data = json.loads(link_p.read_text(encoding="utf-8"))
    assert data["all_linkage_valid"] is True
    assert data["total_linkage_failures"] == 0
    assert data["discovery_document_identity_failures"] == 0
    assert data["raw_orphan_file_count"] == 0


def test_fix03_correction_2_attestation_derived():
    attest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2 / "canonical_live_evidence_attestation_v01_fix03_correction_2.json"
    assert attest_p.exists()

    data = json.loads(attest_p.read_text(encoding="utf-8"))
    assert data["execution_mode"] == "LIVE_EVIDENCE_ACQUISITION"
    assert data["synthetic_official_documents_used"] is False
    assert data["all_official_records_request_linked"] is True
    assert data["all_candidate_rows_request_linked"] is True
    assert data["all_pykrx_rows_query_linked"] is True


def test_fix03_correction_2_manifest_integrity():
    manifest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2 / "artifact_manifest.json"
    assert manifest_p.exists()

    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 21

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Artifact {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"SHA mismatch for {fname}"


# ==============================================================================
# 6. Price Parity, Windows & Gate 06/15 Final Adjudication (Section 92, 96)
# ==============================================================================

def test_fix03_correction_2_price_parity_exact():
    parity_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2 / "corporate_action_event_sensitive_parity_v01_fix03_correction_2.csv"
    assert parity_p.exists()

    df = pd.read_csv(parity_p)
    assert len(df) == 8
    assert (df["open_mismatch_count"] == 0).all()
    assert (df["high_mismatch_count"] == 0).all()
    assert (df["low_mismatch_count"] == 0).all()
    assert (df["close_mismatch_count"] == 0).all()
    assert (df["candidate_only_date_count"] == 0).all()
    assert (df["pykrx_only_date_count"] == 0).all()
    assert (df["pre_overlap_rows"] >= 5).all()
    assert (df["post_overlap_rows"] >= 5).all()
    assert (df["parity_status"] == "MATCH").all()


def test_fix03_correction_2_decision_and_gates():
    dec_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2 / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_2.json"
    assert dec_p.exists()

    data = json.loads(dec_p.read_text(encoding="utf-8"))
    assert data["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert data["production_integration_authorized"] is True
    assert data["authority_valid_control_count"] == 8
    assert data["gate_06_result"] is True
    assert data["gate_15_result"] is True
    assert data["all_gates_passed"] is True
    assert data["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
