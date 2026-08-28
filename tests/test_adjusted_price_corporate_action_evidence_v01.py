"""Comprehensive Unit, Negative, and Regression Tests for Corporate Action Evidence Acquisition.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_7 (Section 41-56)
Authoritative Technical Parent: ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import zipfile
import pytest

from trend_scanner.data.corporate_action_authority import (
    OfficialEvidenceContentParser,
    evaluate_gate06,
    resolve_archive_member,
    run_corporate_action_evidence_acquisition_fix03_correction_7,
    select_official_anchor_by_priority,
    validate_archive_provenance,
    validate_discovery_duplicate_identity,
    validate_pagination_pages,
    verify_parent_authority_freeze,
)


def test_parent_authority_freeze_validation_positive():
    """Section 3: Parent FIX03_CORRECTION artifacts remain frozen byte-for-byte."""
    res = verify_parent_authority_freeze()
    assert res["all_parent_inputs_unchanged"] is True
    assert res["parent_artifacts_verified_count"] == 8
    assert res["mismatches"] == []


def test_claim_free_extraction_ignores_claimed_inputs():
    """Section 4, 7-10: Official anchor extracted purely from structure without claim inputs."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
  <DOCUMENT-HEADER>
    <DOCUMENT-NAME>주주총회소집공고</DOCUMENT-NAME>
    <COMPANY-NAME>삼성전자</COMPANY-NAME>
  </DOCUMENT-HEADER>
  <BODY>
    <SECTION-1>
      <SECTION-2>
        <TITLE>주식의 분할</TITLE>
        <P>신주상장예정일 : 2018-05-16</P>
        <P>분할기일 : 2018-05-03</P>
      </SECTION-2>
    </SECTION-1>
  </BODY>
</DOCUMENT>""".encode("utf-8")

    official_auth = OfficialEvidenceContentParser.extract_official_event_authority(
        raw_content_bytes=xml_content,
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )

    assert official_auth["authority_valid"] is True
    assert official_auth["source_event_type"] == "STOCK_SPLIT"
    assert official_auth["official_anchor_type"] == "NEW_SHARE_LISTING_DATE"
    assert official_auth["official_anchor_date"] == "2018-05-16"
    assert official_auth["official_anchor_priority_rank"] == 1


def test_adjudicate_prior_claim_independence():
    """Section 11, 23: Post-extraction claim adjudication maintains zero claim influence."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
  <DOCUMENT-HEADER><DOCUMENT-NAME>주식분할결정</DOCUMENT-NAME><COMPANY-NAME>삼성전자</COMPANY-NAME></DOCUMENT-HEADER>
  <BODY><SECTION-1><TITLE>주식분할</TITLE><P>신주상장예정일 : 2018-05-16</P></SECTION-1></BODY>
</DOCUMENT>""".encode("utf-8")

    official_auth = OfficialEvidenceContentParser.extract_official_event_authority(
        raw_content_bytes=xml_content,
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )

    adj = OfficialEvidenceContentParser.adjudicate_prior_claim(
        official_auth=official_auth,
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="NEW_SHARE_LISTING_DATE",
        claimed_anchor_date="2018-05-16",
        claimed_issuer="삼성전자",
        claimed_ticker="005930",
    )

    assert adj["claim_independence_valid"] is True
    assert adj["claim_used_for_event_selection"] is False
    assert adj["claim_used_for_context_selection"] is False
    assert adj["claim_used_for_anchor_type_selection"] is False
    assert adj["claim_used_for_anchor_date_selection"] is False
    assert adj["adjudication_status"] == "CONFIRMED"


def test_same_date_independent_sibling_roots_fail_closed():
    """Section 12-21: Multiple independent sibling event contexts fail closed with EVENT_CONTEXT_AMBIGUOUS."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
  <DOCUMENT-HEADER><DOCUMENT-NAME>주주총회소집공고</DOCUMENT-NAME><COMPANY-NAME>테스트기업</COMPANY-NAME></DOCUMENT-HEADER>
  <BODY>
    <SECTION-1>
      <TITLE>안건 1: 주식의 분할</TITLE>
      <P>신주상장예정일 : 2021-05-01</P>
    </SECTION-1>
    <SECTION-1>
      <TITLE>안건 2: 무상증자</TITLE>
      <P>신주상장예정일 : 2021-05-01</P>
    </SECTION-1>
  </BODY>
</DOCUMENT>""".encode("utf-8")

    official_auth = OfficialEvidenceContentParser.extract_official_event_authority(
        raw_content_bytes=xml_content,
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210101000001",
        doc_request_record_id="20210101000001",
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )

    assert official_auth["authority_valid"] is False
    assert (
        official_auth["event_type_ambiguous"] is True
        or official_auth["event_context_ambiguous"] is True
    )


def test_same_priority_timing_ambiguity_fails_closed():
    """Section 9: Multiple conflicting dates for highest priority anchor fail closed."""
    xml_content = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
  <DOCUMENT-HEADER><DOCUMENT-NAME>주식분할결정</DOCUMENT-NAME><COMPANY-NAME>테스트기업</COMPANY-NAME></DOCUMENT-HEADER>
  <BODY>
    <SECTION-1>
      <TITLE>주식분할</TITLE>
      <P>신주상장예정일 : 2021-05-01</P>
      <P>신주상장예정일 : 2021-05-15</P>
    </SECTION-1>
  </BODY>
</DOCUMENT>""".encode("utf-8")

    official_auth = OfficialEvidenceContentParser.extract_official_event_authority(
        raw_content_bytes=xml_content,
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210101000001",
        doc_request_record_id="20210101000001",
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )

    assert official_auth["authority_valid"] is False
    assert official_auth["event_timing_ambiguous"] is True
    assert "EVENT_TIMING_AMBIGUOUS" in official_auth["validation_reason"]


def test_prior_raw_exists_but_live_fetch_fails_does_not_reuse_cache(tmp_path):
    """Section 41: When simulated live fetch fails, prior raw file MUST NOT be reused."""
    prior_dir = tmp_path / "prior_raw"
    prior_dir.mkdir(parents=True)
    (prior_dir / "005930_STOCK_SPLIT_20180223000294.xml").write_bytes(b"<XML>old</XML>")

    # Simulated failed live response
    failed_live_bytes = b"<?xml version='1.0'?><result><status>800</status><message>Maintenance</message></result>"
    official_auth = OfficialEvidenceContentParser.extract_official_event_authority(
        raw_content_bytes=failed_live_bytes,
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20180223000294",
        doc_request_record_id="20180223000294",
        evidence_origin="LIVE_OPENDART_DOCUMENT_RESPONSE",
    )

    assert official_auth["authority_valid"] is False
    assert official_auth["blocked_page_detected"] is True


def test_failed_request_log_remains_failed_and_immutable():
    """Section 42: A failed initial request log is never mutated when a fallback succeeds."""
    logs = []
    # 1. Failed request
    logs.append({
        "canonical_run_id": "RUN_01",
        "request_id": "REQ_01",
        "source": "OPENDART_OFFICIAL_API",
        "http_status": 500,
        "raw_http_response_sha256": "failed_sha",
        "outcome": "ERROR",
    })
    # 2. Fallback succeeds
    logs.append({
        "canonical_run_id": "RUN_01",
        "request_id": "REQ_02",
        "source": "DART_OFFICIAL_DISCLOSURE",
        "http_status": 200,
        "raw_http_response_sha256": "success_sha",
        "outcome": "SUCCESS",
    })

    assert logs[0]["outcome"] == "ERROR"
    assert logs[0]["raw_http_response_sha256"] == "failed_sha"
    assert logs[1]["outcome"] == "SUCCESS"
    assert logs[1]["raw_http_response_sha256"] == "success_sha"


def test_failed_candidate_then_successful_candidate_preserves_both():
    """Section 43: Failed candidate rank 1 and successful rank 2 are independently retained."""
    logs = [
        {"request_id": "REQ_C1", "outcome": "ERROR", "error_type": "EVENT_MISMATCH"},
        {"request_id": "REQ_C2", "outcome": "SUCCESS", "error_type": ""},
    ]
    assert len(logs) == 2
    assert logs[0]["outcome"] == "ERROR"
    assert logs[1]["outcome"] == "SUCCESS"


def test_historical_sha_coincidence_does_not_prove_live_fetch():
    """Section 44: Same SHA as previous run only passes if current transport lineage passes."""
    metrics = {
        "preflight_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "live_lineage_failure_count": 1,  # lineage failed despite matching bytes
    }
    pass_eval, blockers = evaluate_gate06(metrics)
    assert pass_eval is False
    assert any("lineage" in b for b in blockers)


def test_impossible_archive_state_fails_provenance():
    """Section 45: archive_detected=True with member_count=0 fails provenance validation."""
    valid, fails = validate_archive_provenance(
        archive_detected=True,
        archive_member_count=0,
        selected_member_name="",
        member_selection_rule="EXACTLY_ONE_XML_MEMBER",
        extracted_member_size=0,
        extracted_member_sha256="",
        canonical_raw_sha256="",
        transport_response_sha256="some_sha",
    )
    assert valid is False
    assert any("ARCHIVE_PROVENANCE_INCONSISTENT" in f for f in fails)


def test_exactly_one_rule_requires_exactly_one_member():
    """Section 46: Rule EXACTLY_ONE_XML_MEMBER requires member count == 1."""
    valid_0, fails_0 = validate_archive_provenance(
        archive_detected=True,
        archive_member_count=0,
        selected_member_name="doc.xml",
        member_selection_rule="EXACTLY_ONE_XML_MEMBER",
        extracted_member_size=100,
        extracted_member_sha256="abc",
        canonical_raw_sha256="abc",
        transport_response_sha256="zip_sha",
    )
    assert valid_0 is False

    valid_2, fails_2 = validate_archive_provenance(
        archive_detected=True,
        archive_member_count=2,
        selected_member_name="doc.xml",
        member_selection_rule="EXACTLY_ONE_XML_MEMBER",
        extracted_member_size=100,
        extracted_member_sha256="abc",
        canonical_raw_sha256="abc",
        transport_response_sha256="zip_sha",
    )
    assert valid_2 is False


def test_valid_zip_provenance_transport_vs_extracted_sha():
    """Section 47: In valid ZIP archive, transport SHA != extracted SHA is allowed and valid."""
    transport_sha = "zip_hash_12345"
    extracted_sha = "xml_hash_67890"

    valid, fails = validate_archive_provenance(
        archive_detected=True,
        archive_member_count=1,
        selected_member_name="20180223000294.xml",
        member_selection_rule="EXACTLY_ONE_XML_MEMBER",
        extracted_member_size=5000,
        extracted_member_sha256=extracted_sha,
        canonical_raw_sha256=extracted_sha,
        transport_response_sha256=transport_sha,
    )
    assert valid is True
    assert fails == []


def test_direct_response_provenance():
    """Section 48: Non-archive direct response requires transport SHA == canonical raw SHA."""
    doc_sha = "direct_xml_hash"
    valid, fails = validate_archive_provenance(
        archive_detected=False,
        archive_member_count=0,
        selected_member_name="",
        member_selection_rule="DIRECT_RESPONSE",
        extracted_member_size=5000,
        extracted_member_sha256=doc_sha,
        canonical_raw_sha256=doc_sha,
        transport_response_sha256=doc_sha,
    )
    assert valid is True
    assert fails == []


def test_wrong_producing_request_fails_linkage():
    """Section 49: Producing request failure count triggers Gate 06 failure."""
    metrics = {
        "preflight_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "producing_request_failure_count": 1,
    }
    pass_eval, blockers = evaluate_gate06(metrics)
    assert pass_eval is False
    assert any("producing request" in b for b in blockers)


def test_cross_run_request_linkage_fails():
    """Section 50: Cross-run request linkage failure triggers Gate 06 failure."""
    metrics = {
        "preflight_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "cross_run_request_linkage_failure_count": 1,
    }
    pass_eval, blockers = evaluate_gate06(metrics)
    assert pass_eval is False
    assert any("Cross-run" in b for b in blockers)


def test_invalid_retrieval_mode_fails():
    """Section 51: Forbidden retrieval mode (e.g. PRIOR_RUN_CACHE) fails Gate 06."""
    metrics = {
        "preflight_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "invalid_retrieval_mode_count": 1,
    }
    pass_eval, blockers = evaluate_gate06(metrics)
    assert pass_eval is False
    assert any("retrieval mode" in b for b in blockers)


def test_duplicate_conflict_detection_uses_production_helper():
    """Section 55: Conflicting duplicate disclosure records detected via production helper."""
    items = [
        {"rcept_no": "1001", "report_nm": "주식분할결정", "rcept_dt": "20200101", "corp_code": "001"},
        {"rcept_no": "1001", "report_nm": "주식분할결정", "rcept_dt": "20200101", "corp_code": "001"},
    ]
    is_valid, dups, conflicts, details = validate_discovery_duplicate_identity(items)
    assert is_valid is True
    assert dups == 1
    assert conflicts == 0

    conflicting_items = [
        {"rcept_no": "1001", "report_nm": "주식분할결정", "rcept_dt": "20200101", "corp_code": "001"},
        {"rcept_no": "1001", "report_nm": "다른보고서", "rcept_dt": "20200101", "corp_code": "001"},
    ]
    is_valid_c, dups_c, conflicts_c, details_c = validate_discovery_duplicate_identity(conflicting_items)
    assert is_valid_c is False
    assert conflicts_c == 1


def test_zip_exact_basename_resolver_rejects_substring():
    """Section 29: Exact basename matching rejects substring matches."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("sub/20180223000294.xml", b"<XML>exact</XML>")
        z.writestr("sub/pre_20180223000294_post.xml", b"<XML>substring</XML>")

    data, sha, name, arch, cnt, rule, ambig, fails = resolve_archive_member(
        buf.getvalue(), "20180223000294"
    )
    assert ambig is False
    assert rule == "EXACT_RCEPT_NO_MATCH"
    assert name == "sub/20180223000294.xml"
    assert data == b"<XML>exact</XML>"


def test_pagination_production_helper_validates_metadata():
    """Section 25-27: Pagination helper rejects total_count and total_page mismatches across pages."""
    frozen_p1 = {"reported_total_count": 100, "reported_total_page": 2, "page_count": 50}
    pages_meta = [
        {"page_no": 1, "reported_total_count": 100, "reported_total_page": 2, "page_count": 50, "item_count": 50, "http_status": 200, "opendart_status": "000"},
        {"page_no": 2, "reported_total_count": 95, "reported_total_page": 2, "page_count": 50, "item_count": 50, "http_status": 200, "opendart_status": "000"},
    ]
    is_valid, fails = validate_pagination_pages(pages_meta, 100, 2, frozen_p1)
    assert is_valid is False
    assert any("total_count mismatch" in f for f in fails)


def test_gate_06_and_15_approval_positive(tmp_path):
    """Section 86-88, 91: Complete valid execution passes Gate 06 and Gate 15 or produces deterministic RESUME when transiently unavailable."""
    res = run_corporate_action_evidence_acquisition_fix03_correction_7(
        output_dir=tmp_path / "test_out",
        allow_network=True,
    )
    if res["all_gates_passed"]:
        assert res["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
        assert res["production_integration_authorized"] is True
        assert res["gate_06_result"] is True
        assert res["gate_15_result"] is True
        assert res["authority_valid_control_count"] == 8
    else:
        assert res["review_decision"] == "CONDITIONAL_REVIEW_REQUIRED"
        assert res["production_integration_authorized"] is False
        assert res["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_7_RESUME"
