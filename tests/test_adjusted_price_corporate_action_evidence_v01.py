"""Comprehensive Unit, Negative, Provenance, Semantic-Binding, and Determinism Tests for FIX03_CORRECTION_3.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_3 (Section 83-101)
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import random
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
    DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2,
    DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3,
    PARENT_FIX03_CORRECTION_DIR,
    START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_3,
    AuthoritySourceTier,
    ClaimAdjudicationStatus,
    CorporateActionNetworkAccounting,
    OfficialEvidenceContentParser,
    get_official_discovery_search_targets,
    rank_and_score_candidates,
    run_corporate_action_evidence_acquisition_fix03_correction_3,
    verify_parent_authority_freeze,
)


# ==============================================================================
# 1. Environment & Credential Resolution Tests
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
# 2. OpenDART Preflight Tests (Section 6, 7)
# ==============================================================================

def test_preflight_success_000_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "mock_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "000", "message": "정상"}

    with patch("requests.Session.get", return_value=mock_resp):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["credential_present"] is True
        assert res["network_reachable"] is True
        assert res["authentication_valid"] is True
        assert res["probe_response_status"] == "AUTHENTICATED_WITH_DATA"
        assert res["response_identity_status"] == "VALID"
        assert res["verdict"] == "READY"


def test_preflight_success_013_mock(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "mock_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "013", "message": "조회된 데이터가 없습니다."}

    with patch("requests.Session.get", return_value=mock_resp):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["credential_present"] is True
        assert res["network_reachable"] is True
        assert res["authentication_valid"] is True
        assert res["probe_response_status"] == "AUTHENTICATED_NO_DATA"
        assert res["response_identity_status"] == "NOT_APPLICABLE"
        assert res["verdict"] == "READY"


def test_preflight_missing_key_verdict_fail(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with patch("trend_scanner.data.opendart_preflight.load_dotenv"):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["credential_present"] is False
        assert res["verdict"] == "FAIL"
        assert res["error_reason"] == "OPENDART_CREDENTIAL_MISSING"


def test_preflight_hard_gate_blocks_acquisition(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with patch("trend_scanner.data.opendart_preflight.load_dotenv"):
        with pytest.raises(RuntimeError) as exc_info:
            run_corporate_action_evidence_acquisition_fix03_correction_3(output_dir=tmp_path)
        assert "OpenDART Preflight Hard Gate FAIL" in str(exc_info.value)


# ==============================================================================
# 3. Event Locality & Semantic Binding Tests (Section 83, 84, 85, 86, 87)
# ==============================================================================

def test_event_locality_cross_section_false_positive_fails(tmp_path):
    # Section A has stock split, Section B has unrelated division date without split keyword
    raw_doc = (
        "<HTML><HEAD><TITLE>주주총회소집공고</TITLE></HEAD><BODY><h1>(주)카카오</h1>"
        "<SECTION id='sec1'><h2>안건 1: 주식분할 승인의 건</h2><p>1주를 5주로 분할합니다.</p></SECTION>"
        "<SECTION id='sec2'><h2>안건 2: 회사분할 합병 승인의 건</h2><p>본건 단순 물적분할에 따른 분할기일은 2021년 06월 01일입니다.</p></SECTION>"
        "</BODY></HTML>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="035720",
        claimed_issuer="카카오",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2021-04-15",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20210312001048",
        doc_request_record_id="20210312001048",
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )
    # Since sec1 has no timing field, and sec2 has no stock split keywords, semantic binding must fail
    assert parsed["event_semantic_binding_valid"] is False
    assert parsed["authority_valid"] is False


def test_same_section_valid_split_passes():
    raw_doc = (
        "<HTML><HEAD><TITLE>주주총회소집공고</TITLE></HEAD><BODY><h1>(주)삼성전자</h1>"
        "<TABLE><TR><TD>안건: 주식분할(액면분할)</TD></TR>"
        "<TR><TD>분할기일</TD><TD>2018년 05월 03일</TD></TR></TABLE>"
        "</BODY></HTML>"
    ).encode("euc-kr")

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
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )
    assert parsed["event_semantic_binding_valid"] is True
    assert parsed["official_anchor_date"] == "2018-05-03"
    assert parsed["official_anchor_source_field"] == "분할기일"
    assert parsed["claim_anchor_match"] is False
    assert parsed["authority_valid"] is True


def test_wrong_event_timing_field_fails():
    # Target is RIGHTS_OFFERING, but table contains only MERGER fields
    raw_doc = (
        "<HTML><HEAD><TITLE>주요사항보고서</TITLE></HEAD><BODY><h1>포스코퓨처엠</h1>"
        "<TABLE><TR><TD>유상증자 결정</TD></TR>"
        "<TR><TD>합병기일</TD><TD>2021년 01월 15일</TD></TR></TABLE>"
        "</BODY></HTML>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_doc,
        claimed_ticker="003670",
        claimed_issuer="포스코퓨처엠",
        claimed_event_type="RIGHTS_OFFERING",
        claimed_anchor_type="EX_DATE",
        claimed_anchor_date="2021-01-13",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20210121800246",
        doc_request_record_id="20210121800246",
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )
    # Mergers fields are not allowed for RIGHTS_OFFERING
    assert parsed["event_timing_valid"] is False
    assert parsed["authority_valid"] is False


def test_multiple_event_blocks_ambiguous_fails():
    raw_doc = (
        "<HTML><HEAD><TITLE>주식분할결정</TITLE></HEAD><BODY><h1>(주)삼성전자</h1>"
        "<TABLE id='t1'><TR><TD>주식분할</TD></TR><TR><TD>분할기일</TD><TD>2018년 05월 03일</TD></TR></TABLE>"
        "<TABLE id='t2'><TR><TD>주식분할</TD></TR><TR><TD>분할기일</TD><TD>2018년 05월 10일</TD></TR></TABLE>"
        "</BODY></HTML>"
    ).encode("euc-kr")

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
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )
    assert parsed["authority_valid"] is False
    assert "EVENT_CONTEXT_AMBIGUOUS" in parsed["validation_reason"]


# ==============================================================================
# 4. Candidate Scoring, Ranking & Order Invariance Tests (Section 89, 90)
# ==============================================================================

def test_candidate_scoring_and_order_invariance():
    target = {
        "keywords": ["주주총회소집공고", "주식분할"],
    }
    raw_items = [
        {"rcept_no": "20180101000100", "report_nm": "기타경영사항", "rcept_dt": "20180101"},
        {"rcept_no": "20180223000294", "report_nm": "주주총회소집공고(주식분할)", "rcept_dt": "20180223"},
        {"rcept_no": "20180223000490", "report_nm": "[기재정정]주주총회소집공고(주식분할)", "rcept_dt": "20180223"},
        {"rcept_no": "20180115000050", "report_nm": "주식분할결정", "rcept_dt": "20180115"},
    ]

    base_ranked = rank_and_score_candidates(raw_items, target)
    base_order = [c["rcept_no"] for c in base_ranked]

    # Test reverse order input
    rev_ranked = rank_and_score_candidates(list(reversed(raw_items)), target)
    assert [c["rcept_no"] for c in rev_ranked] == base_order

    # Test shuffled order inputs
    for s_idx in range(5):
        shuf = list(raw_items)
        random.Random(100 + s_idx).shuffle(shuf)
        shuf_ranked = rank_and_score_candidates(shuf, target)
        assert [c["rcept_no"] for c in shuf_ranked] == base_order


def test_fix03_correction_3_determinism_validation_artifact():
    det_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3 / "corporate_action_discovery_determinism_validation_v01_fix03_correction_3.json"
    assert det_p.exists()

    data = json.loads(det_p.read_text(encoding="utf-8"))
    assert data["all_controls_order_invariant"] is True
    assert len(data["validation_by_ticker"]) == 8


# ==============================================================================
# 5. Document Probe Audit & Network Accounting Invariant (Section 91, 92, 93)
# ==============================================================================

def test_fix03_correction_3_document_probe_audit():
    probe_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3 / "corporate_action_document_probe_audit_v01_fix03_correction_3.csv"
    assert probe_p.exists()

    df = pd.read_csv(probe_p)
    assert len(df) >= 8
    assert "probe_request_id" in df.columns
    assert "response_sha256" in df.columns
    assert "semantic_binding_valid" in df.columns


def test_fix03_correction_3_network_accounting_cross_invariant():
    net_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3 / "corporate_action_evidence_network_accounting_v01_fix03_correction_3.json"
    assert net_p.exists()

    data = json.loads(net_p.read_text(encoding="utf-8"))
    req_logs = data.get("request_logs", [])

    phys_in_logs = sum(1 for r in req_logs if r.get("physical_attempt") == 1)
    assert data["total_physical_external_calls"] == phys_in_logs
    assert data["accounting_cross_invariant_pass"] is True


# ==============================================================================
# 6. Evidence Linkage, Manifest Integrity & Final Adjudication (Section 94-101)
# ==============================================================================

def test_fix03_correction_3_evidence_linkage_valid():
    link_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3 / "live_evidence_linkage_validation_v01_fix03_correction_3.json"
    assert link_p.exists()

    data = json.loads(link_p.read_text(encoding="utf-8"))
    assert data["all_linkage_valid"] is True
    assert data["total_linkage_failures"] == 0
    assert data["discovery_document_identity_failures"] == 0
    assert data["raw_orphan_file_count"] == 0
    assert data["accounting_cross_invariant_pass"] is True


def test_fix03_correction_3_manifest_integrity():
    manifest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3 / "artifact_manifest.json"
    assert manifest_p.exists()

    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 22

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Artifact {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"SHA mismatch for {fname}"


def test_fix03_correction_3_decision_and_gates():
    dec_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3 / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_3.json"
    assert dec_p.exists()

    data = json.loads(dec_p.read_text(encoding="utf-8"))
    assert data["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert data["production_integration_authorized"] is True
    assert data["authority_valid_control_count"] == 8
    assert data["gate_06_result"] is True
    assert data["gate_15_result"] is True
    assert data["all_gates_passed"] is True
    assert data["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
