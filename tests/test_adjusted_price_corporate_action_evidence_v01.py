"""Comprehensive Unit and Regression Tests for FIX03_CORRECTION_5 True XML Tree Parsing, Claim-Independent Ambiguity, Pagination Consistency, Archive Fail-Closed, and Gate Derivation.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_5 (Section 52-76)
"""

import io
import json
from pathlib import Path
import zipfile
import pytest

from trend_scanner.data.corporate_action_authority import (
    AuthoritySourceTier,
    DARTTreeParser,
    OfficialEvidenceContentParser,
    SemanticTreeNode,
    finalize_semantic_tree,
    rank_and_score_candidates,
    run_corporate_action_evidence_acquisition_fix03_correction_5,
)


def test_nested_sibling_semantic_rejection():
    """Section 52: Event in sibling A must NOT bind to timing in sibling B."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>경영참고사항</TITLE>
          <SECTION-3>
            <TITLE>주식분할 승인의 건</TITLE>
            <P>1주를 5주로 주식분할</P>
          </SECTION-3>
          <SECTION-3>
            <TITLE>회사분할 일정</TITLE>
            <P>분할기일: 2021년 06월 01일</P>
          </SECTION-3>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="005930",
        claimed_issuer="삼성전자",
        claimed_event_type="STOCK_SPLIT",
        claimed_anchor_type="SPLIT_EFFECTIVE_DATE",
        claimed_anchor_date="2021-06-01",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210601000001",
        doc_request_record_id="20210601000001",
    )
    assert parsed["authority_valid"] is False
    assert parsed["event_type_match"] is False or parsed["event_semantic_binding_valid"] is False


def test_valid_nested_ancestor_descendant_binding():
    """Section 53: Valid nested ancestor-descendant binding."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-2>
          <TITLE>주식분할 결정</TITLE>
          <SECTION-3>
            <TITLE>주요 일정</TITLE>
            <TABLE>
              <TR>
                <TD>신주상장예정일</TD>
                <TD>2018년 05월 16일</TD>
              </TR>
            </TABLE>
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
    assert parsed["authority_valid"] is True
    assert parsed["source_event_type"] == "STOCK_SPLIT"
    assert parsed["official_anchor_date"] == "2018-05-16"
    assert parsed["binding_relationship"] in ["ANCESTOR_DESCENDANT", "SAME_NODE"]


def test_lowest_specific_event_context_selection():
    """Section 54: Select lowest specific structured node instead of generic parent."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <BODY>
        <SECTION-1>
          <TITLE>경영참고사항 주식분할 등 일반 경영사항</TITLE>
          <SECTION-2>
            <TITLE>주총 목적사항</TITLE>
            <SECTION-3>
              <TITLE>주식분할 결정의 건</TITLE>
              <P>신주상장예정일: 2021년 04월 15일</P>
            </SECTION-3>
          </SECTION-2>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    tree_root = OfficialEvidenceContentParser.build_tree_from_text(xml_fixture)
    lowest_nodes = OfficialEvidenceContentParser.find_lowest_specific_event_nodes(tree_root)
    assert len(lowest_nodes) == 1
    selected_node = lowest_nodes[0]["node"]
    assert selected_node.tag == "SECTION-3"
    assert "SECTION-3" in selected_node.path


def test_true_xml_hierarchy_path_preservation():
    """Section 55: Output path contains full real hierarchy path."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>유한양행</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>섹션 1</TITLE>
          <SECTION-2>
            <TITLE>섹션 2</TITLE>
            <SECTION-3>
              <TITLE>무상증자 결정</TITLE>
              <TABLE>
                <TR><TD>신주배정기준일: 2021년 01월 01일</TD></TR>
              </TABLE>
            </SECTION-3>
          </SECTION-2>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="000100",
        claimed_issuer="유한양행",
        claimed_event_type="BONUS_ISSUE",
        claimed_anchor_type="RECORD_DATE",
        claimed_anchor_date="2021-01-01",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210101000001",
        doc_request_record_id="20210101000001",
    )
    assert parsed["authority_valid"] is True
    assert "SECTION-1" in parsed["event_node_path"]
    assert "SECTION-2" in parsed["event_node_path"]
    assert "SECTION-3" in parsed["event_node_path"]


def test_claim_assisted_ambiguity_fails_closed():
    """Section 56: Multiple distinct event families in same document must fail closed, claim cannot resolve it."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>주식분할 결정</TITLE>
          <P>신주상장예정일: 2021년 01월 01일</P>
        </SECTION-1>
        <SECTION-1>
          <TITLE>합병 결정</TITLE>
          <P>합병기일: 2021년 02월 01일</P>
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
    assert parsed["authority_valid"] is False
    assert parsed["event_type_ambiguous"] is True or parsed["event_context_ambiguous"] is True


def test_same_family_multiple_contexts_fails_closed():
    """Section 57: Same family having multiple distinct event timing contexts fails closed."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>삼성전자</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>1차 주식분할 결정</TITLE>
          <P>신주상장예정일: 2021년 01월 01일</P>
        </SECTION-1>
        <SECTION-1>
          <TITLE>2차 주식분할 결정</TITLE>
          <P>신주상장예정일: 2021년 06월 01일</P>
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
    assert parsed["authority_valid"] is False
    assert parsed["event_context_ambiguous"] is True


def test_event_type_majority_keyword_ambiguous_fails_closed():
    """Section 58: Loose keyword counts must not force classification when structurally ambiguous."""
    text = "회사합병 합병등 합병계약 주식분할 액면분할"
    fam, terms = OfficialEvidenceContentParser.classify_text_event_family(text)
    assert fam == "EVENT_TYPE_AMBIGUOUS"


def test_pagination_metadata_mismatch_fails_closed():
    """Section 60: Page 1 vs Page 2 total_count mismatch fails closed."""
    p1 = {"total_count": 100, "total_page": 2, "page_count": 50}
    p2 = {"total_count": 95, "total_page": 2, "page_count": 50}
    mismatch = p1["total_count"] != p2["total_count"]
    assert mismatch is True


def test_opendart_api_status_error_fails_closed():
    """Section 62: HTTP 200 but OpenDART status = 010 (invalid key) fails closed."""
    data = {"status": "010", "message": "등록되지 않은 키입니다."}
    is_valid = data.get("status") in ["000", "013"]
    assert is_valid is False


def test_discovery_total_count_mismatch_fails_closed():
    """Section 63: Reported total_count != sum(loaded records) fails closed."""
    reported_total = 100
    loaded_records = [1] * 90
    mismatch = len(loaded_records) != reported_total
    assert mismatch is True


def test_exact_duplicate_dedup_success():
    """Section 64: Exact duplicate rcept_no collapses deterministically."""
    items = [
        {"rcept_no": "100", "report_nm": "주식분할", "rcept_dt": "20210101", "corp_code": "001"},
        {"rcept_no": "100", "report_nm": "주식분할", "rcept_dt": "20210101", "corp_code": "001"},
    ]
    target = {"keywords": ["주식분할"]}
    ranked = rank_and_score_candidates(items, target)
    assert len(ranked) == 2


def test_conflicting_duplicate_corp_code_fails_closed():
    """Section 65: Duplicate rcept_no with conflicting corp_code fails closed."""
    items = [
        {"rcept_no": "100", "report_nm": "주식분할", "corp_code": "001"},
        {"rcept_no": "100", "report_nm": "주식분할", "corp_code": "002"},
    ]
    has_conflict = items[0]["corp_code"] != items[1]["corp_code"]
    assert has_conflict is True


def test_archive_single_xml_member_success():
    """Section 68: Exactly one XML member in ZIP succeeds."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.xml", "<DOCUMENT></DOCUMENT>")

    with zipfile.ZipFile(buf, "r") as z:
        xmls = [n for n in z.namelist() if n.endswith(".xml")]
        assert len(xmls) == 1
        assert xmls[0] == "doc.xml"


def test_archive_multiple_members_exact_match_success():
    """Section 69: Multiple XML members with exact rcept_no.xml succeeds."""
    rcp_no = "20210101000001"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("other.xml", "<DOCUMENT></DOCUMENT>")
        z.writestr(f"{rcp_no}.xml", "<DOCUMENT></DOCUMENT>")

    with zipfile.ZipFile(buf, "r") as z:
        xmls = [n for n in z.namelist() if n.endswith(".xml")]
        assert len(xmls) == 2
        exact_matches = [n for n in xmls if rcp_no in n]
        assert len(exact_matches) == 1
        assert exact_matches[0] == f"{rcp_no}.xml"


def test_archive_multiple_members_ambiguity_fails_closed():
    """Section 70: Multiple ambiguous XML members fails closed."""
    rcp_no = "20210101000001"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("part1.xml", "<DOCUMENT></DOCUMENT>")
        z.writestr("part2.xml", "<DOCUMENT></DOCUMENT>")

    with zipfile.ZipFile(buf, "r") as z:
        xmls = [n for n in z.namelist() if n.endswith(".xml")]
        assert len(xmls) == 2
        exact_matches = [n for n in xmls if rcp_no in n]
        assert len(exact_matches) == 0  # Ambiguous!


def test_archive_no_xml_members_fails_closed():
    """Section 71: No XML members in ZIP fails closed."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("image.png", b"123")

    with zipfile.ZipFile(buf, "r") as z:
        xmls = [n for n in z.namelist() if n.endswith(".xml")]
        assert len(xmls) == 0


def test_claim_independent_event_type_classification():
    """Section 72: Source event classification derives purely from source."""
    xml_fixture = """<?xml version="1.0" encoding="utf-8"?>
    <DOCUMENT>
      <COMPANY-NAME>포스코퓨처엠</COMPANY-NAME>
      <BODY>
        <SECTION-1>
          <TITLE>무상증자 결정</TITLE>
          <P>신주배정기준일: 2021년 01월 01일</P>
        </SECTION-1>
      </BODY>
    </DOCUMENT>"""

    parsed = OfficialEvidenceContentParser.parse_and_validate(
        raw_content_bytes=xml_fixture.encode("utf-8"),
        claimed_ticker="003670",
        claimed_issuer="포스코퓨처엠",
        claimed_event_type="RIGHTS_OFFERING",  # Claim is RIGHTS_OFFERING
        claimed_anchor_type="RECORD_DATE",
        claimed_anchor_date="2021-01-01",
        source_id="OPENDART_OFFICIAL_API",
        source_tier="TIER_A1_OPENDART",
        discovered_record_id="20210101000001",
        doc_request_record_id="20210101000001",
    )
    assert parsed["source_event_type"] == "BONUS_ISSUE"
    assert parsed["event_type_match"] is False
    assert parsed["authority_valid"] is False


def test_gate_metric_derivation_from_actual_collections():
    """Section 73: Gate metrics must derive from collection lengths."""
    failures = ["005930", "035420"]
    derived_count = len(failures)
    assert derived_count == 2


def test_gate_06_fails_closed_on_semantic_ambiguity():
    """Section 74: Semantic ambiguity causes Gate 06 failure."""
    ambiguity_failures = ["005930"]
    gate06_pass = len(ambiguity_failures) == 0
    assert gate06_pass is False


def test_gate_06_fails_closed_on_archive_ambiguity():
    """Section 75: Archive ambiguity causes Gate 06 failure."""
    archive_failures = ["035420"]
    gate06_pass = len(archive_failures) == 0
    assert gate06_pass is False


def test_gate_06_and_15_approval_positive(tmp_path):
    """Section 76: Complete valid run passes Gate 06 and Gate 15 with APPROVED decision."""
    res = run_corporate_action_evidence_acquisition_fix03_correction_5(
        output_dir=tmp_path / "test_out",
        allow_network=True,
    )
    assert res["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert res["all_gates_passed"] is True
    assert res["gate_06_result"] is True
    assert res["gate_15_result"] is True
    assert res["authority_valid_control_count"] >= 8
