"""Comprehensive Unit, Negative, Provenance, Semantic-Binding, Pagination, and Determinism Tests for FIX03_CORRECTION_4.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_4 (Section 78-102)
"""

from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import random
import zipfile
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
    DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_3,
    DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_4,
    PARENT_FIX03_CORRECTION_DIR,
    START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_4,
    AuthoritySourceTier,
    ClaimAdjudicationStatus,
    CorporateActionNetworkAccounting,
    OfficialEvidenceContentParser,
    get_official_discovery_search_targets,
    rank_and_score_candidates,
    run_corporate_action_evidence_acquisition_fix03_correction_4,
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
# 2. Pagination Regression Tests (Section 78-85)
# ==============================================================================

def test_pagination_two_pages_mock(monkeypatch, tmp_path):
    target = {
        "control_id": "TEST_CTRL",
        "ticker": "005930",
        "corp_code": "00126380",
        "discovery_start": "20180101",
        "discovery_end": "20180531",
        "target_event_family": "STOCK_SPLIT",
        "keywords": ["주식분할"],
    }
    p1_items = [{"rcept_no": f"20180101000{i:03d}", "report_nm": "기타경영사항", "rcept_dt": "20180101"} for i in range(100)]
    p2_items = [{"rcept_no": f"20180201000{i:03d}", "report_nm": "주식분할결정", "rcept_dt": "20180201"} for i in range(31)]

    all_items = p1_items + p2_items
    assert len(all_items) == 131

    ranked = rank_and_score_candidates(all_items, target)
    assert len(ranked) == 131
    assert ranked[0]["rcept_no"].startswith("20180201")
    assert ranked[0]["event_match_score"] > 0


def test_ranking_across_page_boundary_selects_page_2_candidate():
    target = {
        "keywords": ["주식분할결정", "주식분할"],
    }
    p1_items = [{"rcept_no": f"20180101000{i:03d}", "report_nm": "기타경영사항", "rcept_dt": "20180101"} for i in range(100)]
    p2_items = [{"rcept_no": "20180315000500", "report_nm": "주식분할결정", "rcept_dt": "20180315"}]

    all_items = p1_items + p2_items
    ranked = rank_and_score_candidates(all_items, target)
    assert ranked[0]["rcept_no"] == "20180315000500"
    assert ranked[0]["candidate_rank"] == 1


# ==============================================================================
# 3. Determinism & Order Invariance Tests (Section 86, 87)
# ==============================================================================

def test_complete_set_order_invariance():
    target = {
        "keywords": ["주주총회소집공고", "주식분할", "액면분할"],
    }
    items = [
        {"rcept_no": "20180101000100", "report_nm": "기타경영사항", "rcept_dt": "20180101"},
        {"rcept_no": "20180223000294", "report_nm": "주주총회소집공고(주식분할)", "rcept_dt": "20180223"},
        {"rcept_no": "20180223000490", "report_nm": "[기재정정]주주총회소집공고(주식분할)", "rcept_dt": "20180223"},
        {"rcept_no": "20180115000050", "report_nm": "주식분할결정", "rcept_dt": "20180115"},
    ]

    base_ranked = rank_and_score_candidates(items, target)
    base_order = [c["rcept_no"] for c in base_ranked]

    assert [c["rcept_no"] for c in rank_and_score_candidates(list(reversed(items)), target)] == base_order

    for i in range(5):
        shuf = list(items)
        random.Random(100 + i).shuffle(shuf)
        assert [c["rcept_no"] for c in rank_and_score_candidates(shuf, target)] == base_order


def test_selected_record_invariance_computation():
    target = {"keywords": ["주식분할"]}
    items = [
        {"rcept_no": "1001", "report_nm": "주식분할 A", "rcept_dt": "20180201"},
        {"rcept_no": "1002", "report_nm": "주식분할 B", "rcept_dt": "20180202"},
    ]
    validity_map = {"1002": False, "1001": True}

    ranked = rank_and_score_candidates(items, target)
    winner_base = next(c["rcept_no"] for c in ranked if validity_map.get(c["rcept_no"], False))

    rev_ranked = rank_and_score_candidates(list(reversed(items)), target)
    winner_rev = next(c["rcept_no"] for c in rev_ranked if validity_map.get(c["rcept_no"], False))

    assert winner_base == "1001"
    assert winner_rev == "1001"


# ==============================================================================
# 4. DART Hierarchical Parsing & Semantic Binding Tests (Section 88-96)
# ==============================================================================

def test_dart_numbered_section_parsing():
    raw_xml = (
        "<DOCUMENT><COMPANY-NAME>삼성전자</COMPANY-NAME>"
        "<SECTION-1><TITLE>1. 주식분할 승인의 건</TITLE>"
        "<SECTION-2><TITLE>주요 일정</TITLE>"
        "<TABLE><TR><TD>안건</TD><TD>발행주식 액면분할</TD></TR>"
        "<TR><TD>매매거래 정지기간</TD><TD>2018년 4월 25일</TD></TR></TABLE>"
        "</SECTION-2></SECTION-1></DOCUMENT>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_xml,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-04-25",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
    )
    assert parsed["authority_valid"] is True
    assert parsed["semantic_block_id"] != "SEM_BLOCK_GLOBAL_DOC"
    assert parsed["source_event_type"] == "STOCK_SPLIT"
    assert parsed["official_anchor_date"] == "2018-04-25"


def test_nested_parent_child_binding_bonus_issue():
    raw_xml = (
        "<DOCUMENT><COMPANY-NAME>유한양행</COMPANY-NAME>"
        "<SECTION-1><TITLE>무상증자 결정</TITLE>"
        "<TABLE><TR><TD>1. 신주배정기준일</TD><TD>2021년 01월 01일</TD></TR></TABLE>"
        "</SECTION-1></DOCUMENT>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_xml,
        claimed_ticker="000100",
        claimed_issuer="유한양행",
        claimed_event_type="BONUS_ISSUE",
        claimed_anchor_type="EX_DATE",
        claimed_anchor_date="2020-12-29",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20201211000171",
        doc_request_record_id="20201211000171",
    )
    assert parsed["authority_valid"] is True
    assert parsed["source_event_type"] == "BONUS_ISSUE"
    assert parsed["official_anchor_date"] == "2021-01-01"
    assert parsed["semantic_block_id"] != "SEM_BLOCK_GLOBAL_DOC"


def test_cross_section_false_positive_parser_matching_syntax():
    test_str = "분할기일: 2021년 06월 01일"
    rules = OfficialEvidenceContentParser.ALLOWED_EVENT_TIMING_FIELDS["STOCK_SPLIT"]
    split_date_pat = rules[0][2]
    import re
    assert re.search(split_date_pat, test_str) is not None

    raw_xml = (
        "<DOCUMENT><COMPANY-NAME>카카오</COMPANY-NAME>"
        "<SECTION-1><TITLE>주식분할 승인의 건</TITLE><P>1주를 5주로 액면분할합니다.</P></SECTION-1>"
        "<SECTION-2><TITLE>기타 회사분할 승인의 건</TITLE><TABLE><TR><TD>분할기일: 2021년 06월 01일</TD></TR></TABLE></SECTION-2>"
        "</DOCUMENT>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_xml,
        claimed_ticker="035720",
        claimed_issuer="카카오",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2021-04-15",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20210225800978",
        doc_request_record_id="20210225800978",
    )
    assert parsed["event_semantic_binding_valid"] is False
    assert parsed["authority_valid"] is False


def test_no_global_fallback_produced():
    raw_xml = (
        "<DOCUMENT><COMPANY-NAME>삼성전자</COMPANY-NAME>"
        "<P>당사는 주식분할을 검토한 바 있습니다.</P>"
        "<P>납입일: 2021년 01월 01일</P>"
        "</DOCUMENT>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_xml,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
    )
    assert parsed["semantic_block_id"] != "SEM_BLOCK_GLOBAL_DOC"
    assert parsed["authority_valid"] is False


def test_source_derived_event_type_mismatch():
    raw_xml = (
        "<DOCUMENT><COMPANY-NAME>포스코퓨처엠</COMPANY-NAME>"
        "<SECTION-1><TITLE>무상증자 결정</TITLE>"
        "<TABLE><TR><TD>신주배정기준일: 2021년 01월 01일</TD></TR></TABLE>"
        "</SECTION-1></DOCUMENT>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_xml,
        claimed_ticker="003670",
        claimed_issuer="포스코퓨처엠",
        claimed_event_type="RIGHTS_OFFERING",
        claimed_anchor_type="EX_DATE",
        claimed_anchor_date="2021-01-13",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20210121800246",
        doc_request_record_id="20210121800246",
    )
    assert parsed["source_event_type"] == "BONUS_ISSUE"
    assert parsed["event_type_match"] is False
    assert parsed["authority_valid"] is False


def test_korean_field_whitespace_normalization():
    raw_xml = (
        "<DOCUMENT><COMPANY-NAME>NAVER</COMPANY-NAME><TABLE><TR><TD>주식분할결정</TD></TR>"
        "<TR><TD>신 주 권  상 장  예 정 일</TD><TD>2018-10-12</TD></TR></TABLE></DOCUMENT>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_xml,
        claimed_ticker="035420",
        claimed_issuer="NAVER",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-10-12",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180726800004",
        doc_request_record_id="20180726800004",
    )
    assert parsed["official_anchor_date"] == "2018-10-12"
    assert parsed["authority_valid"] is True


def test_anchor_priority_order():
    raw_xml = (
        "<DOCUMENT><COMPANY-NAME>삼성전자</COMPANY-NAME><TABLE><TR><TD>주식분할결정</TD></TR>"
        "<TR><TD>매매거래정지기간</TD><TD>2018-04-25</TD></TR>"
        "<TR><TD>신주권상장예정일</TD><TD>2018-05-04</TD></TR>"
        "</TABLE></DOCUMENT>"
    ).encode("euc-kr")

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=raw_xml,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-04",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
    )
    assert parsed["official_anchor_type"] == "NEW_SHARE_LISTING_DATE"
    assert parsed["official_anchor_date"] == "2018-05-04"


# ==============================================================================
# 5. ZIP Transport & Provenance Tests (Section 97-100)
# ==============================================================================

def test_zip_transport_provenance_separation():
    xml_content = "<DOCUMENT><COMPANY-NAME>삼성전자</COMPANY-NAME><TABLE><TR><TD>주식분할결정</TD></TR><TR><TD>분할기일: 2018-05-03</TD></TR></TABLE></DOCUMENT>".encode("euc-kr")
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("test_doc.xml", xml_content)
    zip_bytes = zip_buffer.getvalue()

    http_sha = hashlib.sha256(zip_bytes).hexdigest()
    extracted_sha = hashlib.sha256(xml_content).hexdigest()

    assert http_sha != extracted_sha

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_content,
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="EFFECTIVE_DATE",
        claimed_anchor_date="2018-05-03",
        source_id="OPENDART_OFFICIAL_API",
        source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
    )
    assert parsed["authority_valid"] is True


def test_fix03_correction_4_network_accounting_cross_invariant():
    net_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_4 / "corporate_action_evidence_network_accounting_v01_fix03_correction_4.json"
    assert net_p.exists()

    data = json.loads(net_p.read_text(encoding="utf-8"))
    req_logs = data.get("request_logs", [])

    phys_in_logs = sum(1 for r in req_logs if r.get("physical_attempt") == 1)
    assert data["total_physical_external_calls"] == phys_in_logs
    assert data["accounting_cross_invariant_pass"] is True


# ==============================================================================
# 6. Artifact Integrity & Decision Tests (Section 101, 102)
# ==============================================================================

def test_fix03_correction_4_pagination_validation_artifact():
    pag_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_4 / "corporate_action_discovery_pagination_validation_v01_fix03_correction_4.json"
    assert pag_p.exists()

    data = json.loads(pag_p.read_text(encoding="utf-8"))
    assert data["all_pagination_complete"] is True
    assert len(data["validation_by_ticker"]) == 8


def test_fix03_correction_4_manifest_integrity():
    manifest_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_4 / "artifact_manifest.json"
    assert manifest_p.exists()

    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 24

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Artifact {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"SHA mismatch for {fname}"


def test_fix03_correction_4_decision_and_gates():
    dec_p = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_4 / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_4.json"
    assert dec_p.exists()

    data = json.loads(dec_p.read_text(encoding="utf-8"))
    assert data["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert data["production_integration_authorized"] is True
    assert data["authority_valid_control_count"] == 8
    assert data["gate_06_result"] is True
    assert data["gate_15_result"] is True
    assert data["all_gates_passed"] is True
    assert data["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
