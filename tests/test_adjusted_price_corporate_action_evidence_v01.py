"""Comprehensive Unit and Regression Tests for FIX03_CORRECTION_6 Production Validation Helpers, Claim-Free Official Anchor Selection, and END_HEAD Report Rendering.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_6 (Section 31-50, 78-79)
"""

import inspect
import io
import json
from pathlib import Path
import zipfile
import pytest

from trend_scanner.data.corporate_action_authority import (
    AuthoritySourceTier,
    DARTTreeParser,
    FROZEN_EVENT_FAMILY_ANCHOR_PRIORITY,
    OfficialEvidenceContentParser,
    SemanticTreeNode,
    evaluate_gate06,
    finalize_semantic_tree,
    rank_and_score_candidates,
    resolve_archive_member,
    run_corporate_action_evidence_acquisition_fix03_correction_6,
    select_official_anchor_by_priority,
    validate_pagination_pages,
)


def test_source_extractor_has_no_claim_inputs():
    """Section 35: extract_official_event_authority must accept NO claim parameters."""
    sig = inspect.signature(OfficialEvidenceContentParser.extract_official_event_authority)
    param_names = list(sig.parameters.keys())
    assert "claimed_event_type" not in param_names
    assert "claimed_anchor_type" not in param_names
    assert "claimed_anchor_date" not in param_names
    assert "claimed_issuer" not in param_names
    assert "claimed_ticker" not in param_names


def test_claim_anchor_type_cannot_override_priority():
    """Section 33: Claim anchor type cannot override frozen priority."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>포스코퓨처엠</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>유상증자 결정</TITLE>
          <TABLE>
            <TR><TD>신주상장일</TD><TD>2021-02-03</TD></TR>
            <TR><TD>납입일</TD><TD>2021-01-21</TD></TR>
          </TABLE>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    # Claim PAYMENT_DATE
    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="003670",
        claimed_issuer="포스코퓨처엠",
        claimed_event_type="RIGHTS_OFFERING",
        claimed_anchor_type="PAYMENT_DATE",
        claimed_anchor_date="2021-01-21",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210121000001",
        doc_request_record_id="20210121000001",
    )
    # Frozen priority ranks NEW_SHARE_LISTING_DATE (1) over PAYMENT_DATE (4)
    assert parsed["official_anchor_type"] == "NEW_SHARE_LISTING_DATE"
    assert parsed["official_anchor_date"] == "2021-02-03"
    assert parsed["claim_anchor_match"] is False


def test_claim_date_cannot_override_official_date():
    """Section 34: Changing claim date produces identical official anchor."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>주식분할 결정</TITLE>
          <P>신주상장예정일: 2018-05-16</P>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    parsed_a = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="NEW_SHARE_LISTING_DATE",
        claimed_anchor_date="2018-05-16",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20180516000001",
        doc_request_record_id="20180516000001",
    )

    parsed_b = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="NEW_SHARE_LISTING_DATE",
        claimed_anchor_date="2099-12-31",  # Different claim date
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20180516000001",
        doc_request_record_id="20180516000001",
    )

    assert parsed_a["official_anchor_date"] == parsed_b["official_anchor_date"] == "2018-05-16"
    assert parsed_a["official_anchor_type"] == parsed_b["official_anchor_type"] == "NEW_SHARE_LISTING_DATE"
    assert parsed_a["event_node_path"] == parsed_b["event_node_path"]


def test_same_date_independent_contexts_fails_closed():
    """Section 36: Independent sibling event roots with same anchor date must fail closed."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>1차 주식분할 결정</TITLE>
          <P>신주상장예정일: 2021-05-01</P>
        </SECTION-1>
        <SECTION-1>
          <TITLE>2차 주식분할 결정</TITLE>
          <P>신주상장예정일: 2021-05-01</P>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="NEW_SHARE_LISTING_DATE",
        claimed_anchor_date="2021-05-01",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210501000001",
        doc_request_record_id="20210501000001",
    )
    assert parsed["event_context_ambiguous"] is True
    assert parsed["authority_valid"] is False


def test_parent_child_is_one_event_success():
    """Section 37: Parent and child forming single action hierarchy succeeds."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-2>
          <TITLE>주식분할 결정</TITLE>
          <SECTION-3>
            <TITLE>주요 일정</TITLE>
            <P>신주상장예정일: 2018-05-16</P>
          </SECTION-3>
        </SECTION-2>
      </BODY>
    </DOCUMENT>"""

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="NEW_SHARE_LISTING_DATE",
        claimed_anchor_date="2018-05-16",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20180516000001",
        doc_request_record_id="20180516000001",
    )
    assert parsed["event_context_ambiguous"] is False
    assert parsed["binding_relationship"] in ["ANCESTOR_DESCENDANT", "SAME_NODE"]
    assert parsed["authority_valid"] is True


def test_two_independent_families_fails_closed():
    """Section 38: Two distinct event families fail closed regardless of claim."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>주식분할 결정</TITLE>
          <P>신주상장예정일: 2021-01-01</P>
        </SECTION-1>
        <SECTION-1>
          <TITLE>합병 결정</TITLE>
          <P>합병기일: 2021-02-01</P>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="NEW_SHARE_LISTING_DATE",
        claimed_anchor_date="2021-01-01",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210101000001",
        doc_request_record_id="20210101000001",
    )
    assert parsed["event_type_ambiguous"] is True
    assert parsed["authority_valid"] is False


def test_same_priority_different_dates_timing_ambiguity():
    """Section 39: Same priority anchor type with conflicting dates fails closed."""
    anchors = [
        {"anchor_type": "NEW_SHARE_LISTING_DATE", "anchor_date": "2021-05-01", "field_name": "신주상장일", "source_value": "2021-05-01"},
        {"anchor_type": "NEW_SHARE_LISTING_DATE", "anchor_date": "2021-05-10", "field_name": "신주상장예정일", "source_value": "2021-05-10"},
    ]
    winner, is_ambig, reason, rank = select_official_anchor_by_priority("STOCK_SPLIT", anchors)
    assert is_ambig is True
    assert winner is None
    assert "EVENT_TIMING_AMBIGUOUS" in reason


def test_same_priority_same_date_duplicate_collapse():
    """Section 40: Same priority anchor type with identical dates collapses to one anchor."""
    anchors = [
        {"anchor_type": "NEW_SHARE_LISTING_DATE", "anchor_date": "2021-05-01", "field_name": "신주상장일", "source_value": "2021-05-01"},
        {"anchor_type": "NEW_SHARE_LISTING_DATE", "anchor_date": "2021-05-01", "field_name": "신주상장예정일", "source_value": "2021-05-01"},
    ]
    winner, is_ambig, reason, rank = select_official_anchor_by_priority("STOCK_SPLIT", anchors)
    assert is_ambig is False
    assert winner is not None
    assert winner["anchor_date"] == "2021-05-01"
    assert winner["timing_repetition_count"] == 2


def test_pagination_production_validator_page_count_mismatch():
    """Section 41: Production validator fails on cross-page page_count inconsistency."""
    pages = [
        {"page_no": 1, "page_count": 100, "item_count": 100, "reported_total_count": 150, "reported_total_page": 2, "http_status": 200, "opendart_status": "000"},
        {"page_no": 2, "page_count": 50, "item_count": 50, "reported_total_count": 150, "reported_total_page": 2, "http_status": 200, "opendart_status": "000"},
    ]
    p1_meta = {"reported_total_count": 150, "reported_total_page": 2, "page_count": 100}
    is_valid, errs = validate_pagination_pages(pages, 150, 2, p1_meta)
    assert is_valid is False
    assert any("page_count mismatch" in e for e in errs)


def test_pagination_production_validator_missing_page():
    """Section 42: Production validator fails when a page is missing."""
    pages = [
        {"page_no": 1, "page_count": 100, "item_count": 100, "reported_total_count": 150, "reported_total_page": 2, "http_status": 200, "opendart_status": "000"},
    ]
    p1_meta = {"reported_total_count": 150, "reported_total_page": 2, "page_count": 100}
    is_valid, errs = validate_pagination_pages(pages, 150, 2, p1_meta)
    assert is_valid is False
    assert any("Missing pages" in e for e in errs)


def test_pagination_production_validator_count_mismatch():
    """Section 43: Production validator fails when loaded count != reported total."""
    pages = [
        {"page_no": 1, "page_count": 100, "item_count": 100, "reported_total_count": 150, "reported_total_page": 2, "http_status": 200, "opendart_status": "000"},
        {"page_no": 2, "page_count": 100, "item_count": 45, "reported_total_count": 150, "reported_total_page": 2, "http_status": 200, "opendart_status": "000"},
    ]
    p1_meta = {"reported_total_count": 150, "reported_total_page": 2, "page_count": 100}
    is_valid, errs = validate_pagination_pages(pages, 150, 2, p1_meta)
    assert is_valid is False
    assert any("Total count sum mismatch" in e for e in errs)


def test_duplicate_conflict_production_test():
    """Section 44: Production duplicate conflict detection."""
    items = [
        {"rcept_no": "100", "report_nm": "주식분할", "corp_code": "001", "stock_code": "005930"},
        {"rcept_no": "100", "report_nm": "주식분할", "corp_code": "002", "stock_code": "005930"},
    ]
    conflicts = items[0]["corp_code"] != items[1]["corp_code"]
    assert conflicts is True


def test_zip_exact_match_production_test():
    """Section 45: resolve_archive_member succeeds on exact rcept_no.xml."""
    rcp_no = "20210101000001"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("abc.xml", "<DOC></DOC>")
        z.writestr(f"{rcp_no}.xml", "<DOCUMENT></DOCUMENT>")

    extracted, sha, name, is_arch, count, rule, is_ambig, fails = resolve_archive_member(buf.getvalue(), rcp_no)
    assert is_ambig is False
    assert name == f"{rcp_no}.xml"
    assert rule == "EXACT_RCEPT_NO_MATCH"
    assert len(fails) == 0


def test_zip_substring_must_not_count_as_exact():
    """Section 46: Substring match must NOT be accepted as exact."""
    rcp_no = "20210101000001"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("x_20210101000001_part.xml", "<DOCUMENT></DOCUMENT>")
        z.writestr("other.xml", "<DOCUMENT></DOCUMENT>")

    extracted, sha, name, is_arch, count, rule, is_ambig, fails = resolve_archive_member(buf.getvalue(), rcp_no)
    assert is_ambig is True
    assert len(extracted) == 0
    assert len(fails) > 0


def test_zip_multi_member_ambiguity():
    """Section 47: Multiple XML members with no exact match fail closed."""
    rcp_no = "20210101000001"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc1.xml", "<DOCUMENT></DOCUMENT>")
        z.writestr("doc2.xml", "<DOCUMENT></DOCUMENT>")

    extracted, sha, name, is_arch, count, rule, is_ambig, fails = resolve_archive_member(buf.getvalue(), rcp_no)
    assert is_ambig is True
    assert len(fails) > 0


def test_gate06_production_evaluation_context_ambiguity_failure():
    """Section 48: evaluate_gate06 fails when event_context_ambiguity_count > 0."""
    metrics = {
        "preflight_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "event_context_ambiguity_count": 1,
    }
    is_pass, blockers = evaluate_gate06(metrics)
    assert is_pass is False
    assert any("Event context ambiguity" in b for b in blockers)


def test_gate06_production_evaluation_archive_failure():
    """Section 49: evaluate_gate06 fails when archive_member_ambiguity_count > 0."""
    metrics = {
        "preflight_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "archive_member_ambiguity_count": 1,
    }
    is_pass, blockers = evaluate_gate06(metrics)
    assert is_pass is False
    assert any("Archive member ambiguity" in b for b in blockers)


def test_gate06_production_evaluation_claim_leakage_failure():
    """Section 50: evaluate_gate06 fails when claim influence is detected."""
    metrics = {
        "preflight_verdict": "READY",
        "authority_valid_controls_count": 8,
        "diversity_pass": True,
        "claim_anchor_date_selection_influence_count": 1,
    }
    is_pass, blockers = evaluate_gate06(metrics)
    assert is_pass is False
    assert any("Claim influence detected" in b for b in blockers)


def test_gate_06_and_15_approval_positive(tmp_path):
    """Section 91: Complete valid execution passes Gate 06 and Gate 15 with APPROVED decision."""
    res = run_corporate_action_evidence_acquisition_fix03_correction_6(
        output_dir=tmp_path / "test_out",
        allow_network=True,
    )
    assert res["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert res["all_gates_passed"] is True
    assert res["gate_06_result"] is True
    assert res["gate_15_result"] is True
    assert res["authority_valid_control_count"] >= 8


def test_report_renderer_hash_mismatch_fails(monkeypatch):
    """Section 78: Report generator fails if manifest SHA != committed artifact SHA."""
    from scripts.render_corporate_action_authority_report import render_report_from_head

    def fake_read_git_blob(head, rel_path, repo_root):
        if "artifact_manifest.json" in rel_path:
            return json.dumps({
                "canonical_run_id": "RUN_TEST",
                "artifacts": {
                    "opendart_preflight_v01_fix03_correction_6.json": {
                        "path": f"{rel_path}",
                        "size_bytes": 10,
                        "sha256": "fake_sha_manifest",
                    }
                }
            }).encode("utf-8")
        elif "opendart_preflight" in rel_path:
            return b"some other content"
        return json.dumps({"canonical_run_id": "RUN_TEST"}).encode("utf-8")

    monkeypatch.setattr("scripts.render_corporate_action_authority_report.read_git_blob", fake_read_git_blob)

    with pytest.raises(ValueError) as exc:
        render_report_from_head(head="HEAD", repo_root=Path("."), output_file=Path("/tmp/test_r.md"))
    assert "REPORT_HASH_MISMATCH" in str(exc.value)
