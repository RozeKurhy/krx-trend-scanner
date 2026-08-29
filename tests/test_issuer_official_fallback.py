"""Candidate-bound issuer-official fallback contract tests."""

from __future__ import annotations

from pathlib import Path
import hashlib

import pytest

from trend_scanner.data.corporate_action_authority import (
    classify_candidate_resolution,
    evaluate_candidate_resolution_population,
)
from trend_scanner.data.issuer_official_fallback import (
    CANDIDATE_BOUND_FALLBACK_MODE,
    TIER_A1_OPENDART,
    TIER_B_ISSUER_OFFICIAL,
    parse_issuer_official_document,
    validate_candidate_bound_tier_b_fallback,
)


RAW_PATH = Path("/private/tmp/krx_c13_resume3_evidence/unresolved_higher_priority_candidate_resolution_v01_fix01/issuer_official_raw/samsung_public_disclosure_71206.html")
RAW_SHA = "940b0ab6bfdfc3c179dc7f2d5c01e088af436b8c479ad4f4c0c7739dbca9a116"
URL = "https://www.samsung.com/global/ir/reports-disclosures/public-disclosure-view.71206/"


@pytest.fixture()
def raw() -> bytes:
    return RAW_PATH.read_bytes()


def _candidate(**updates: object) -> dict[str, object]:
    value: dict[str, object] = {
        "ticker": "005930",
        "issuer_name": "삼성전자",
        "rcept_no": "20180316800856",
        "identity_record_id": "20180316800856",
        "identity_authority_tier": TIER_A1_OPENDART,
        "identity_candidate_rank": 2,
        "candidate_rank": 2,
        "candidate_rank_deterministic": True,
        "event_match_score": 80,
        "rcept_dt": "20180316",
        "event_family": "STOCK_SPLIT",
        "report_nm": "[기재정정]주식분할결정",
        "a1_body_usable": False,
        "a1_failure_persisted": True,
        "a1_transport_response_sha256": "03f4385d883fd756de28e791dde6f153baad5771898af36fcd2f07b479a84a8f",
        "a2_candidate_specific_attempted": True,
        "a2_usable": False,
    }
    value.update(updates)
    return value


def _validate(raw: bytes, **updates: object) -> dict[str, object]:
    return validate_candidate_bound_tier_b_fallback(
        _candidate(**updates),
        raw_bytes=raw,
        source_url=URL,
        expected_sha256=RAW_SHA,
        raw_path=RAW_PATH,
        retrieval_lineage={"request_id": "REQ_ISSUER_OFFICIAL_SAMSUNG_005930_20180316800856_FIX01_R1", "retrieved_at": "2026-08-29T22:40:11Z", "raw_path": str(RAW_PATH)},
    )


def test_parser_independently_extracts_update_and_superseded_anchor(raw: bytes):
    parsed = parse_issuer_official_document(raw)
    assert parsed["event_family"] == "STOCK_SPLIT"
    assert parsed["update_semantics"] == "UPDATE"
    assert parsed["publication_date"] == "2018-03-16"
    assert parsed["official_anchor_type"] == "NEW_SHARE_LISTING_DATE"
    assert parsed["official_anchor_date"] == "2018-05-04"
    assert parsed["superseded_anchor_date"] == "2018-05-16"
    assert parsed["chronology_valid"] is True


@pytest.mark.parametrize(
    "url",
    [
        "http://www.samsung.com/global/ir/reports-disclosures/public-disclosure-view.71206/",
        "https://samsung.com/global/ir/reports-disclosures/public-disclosure-view.71206/",
        "https://www.samsung.com.evil.example/global/ir/reports-disclosures/public-disclosure-view.71206/",
        "https://ir.samsung.com/global/ir/reports-disclosures/public-disclosure-view.71206/",
        "https://www.samsung.com/global/other/public-disclosure-view.71206/",
    ],
)
def test_trust_registry_fails_closed_for_non_exact_urls(raw: bytes, url: str):
    result = validate_candidate_bound_tier_b_fallback(_candidate(), raw_bytes=raw, source_url=url, expected_sha256=RAW_SHA, raw_path=RAW_PATH, retrieval_lineage={"request_id": "R", "retrieved_at": "T", "raw_path": str(RAW_PATH)})
    assert result["valid"] is False
    assert result["reason_codes"]


@pytest.mark.parametrize(
    "updates,reason",
    [
        ({"ticker": "999999"}, "TICKER_NOT_REGISTERED"),
        ({"issuer_name": "Other Corp"}, "CANDIDATE_ISSUER_NOT_REGISTERED_ALIAS"),
        ({"rcept_dt": "20180317"}, "DISCLOSURE_DATE_MISMATCH"),
        ({"event_family": "MERGER"}, "EVENT_FAMILY_MISMATCH"),
        ({"report_nm": "주식분할결정"}, "UPDATE_SEMANTICS_MISMATCH"),
        ({"a2_candidate_specific_attempted": False}, "A2_CANDIDATE_ATTEMPT_MISSING"),
        ({"a1_failure_persisted": False}, "A1_FAILURE_NOT_PERSISTED"),
        ({"candidate_rank_deterministic": False}, "CANDIDATE_RANK_NOT_DETERMINISTIC"),
    ],
)
def test_candidate_linkage_and_preconditions_fail_closed(raw: bytes, updates: dict[str, object], reason: str):
    result = _validate(raw, **updates)
    assert result["valid"] is False
    assert reason in result["reason_codes"]


def test_tier_b_cannot_create_candidate_without_a1_or_a2_identity(raw: bytes):
    result = validate_candidate_bound_tier_b_fallback(_candidate(identity_authority_tier=TIER_B_ISSUER_OFFICIAL), raw_bytes=raw, source_url=URL, expected_sha256=RAW_SHA, raw_path=RAW_PATH, retrieval_lineage={"request_id": "R", "retrieved_at": "T", "raw_path": str(RAW_PATH)})
    assert result["valid"] is False
    assert "A1_A2_IDENTITY_REQUIRED" in result["reason_codes"]


def test_integrity_and_lineage_fail_closed(raw: bytes):
    assert "TIER_B_RAW_SHA256_MISMATCH" in _validate(raw + b"x")["reason_codes"]
    assert "RETRIEVAL_LINEAGE_MISSING" in validate_candidate_bound_tier_b_fallback(_candidate(), raw_bytes=raw, source_url=URL, expected_sha256=RAW_SHA, raw_path=RAW_PATH, retrieval_lineage=None)["reason_codes"]
    assert "TIER_B_RAW_EMPTY" in validate_candidate_bound_tier_b_fallback(_candidate(), raw_bytes=b"", source_url=URL, expected_sha256=hashlib.sha256(b"").hexdigest(), raw_path=RAW_PATH, retrieval_lineage={"request_id": "R", "retrieved_at": "T", "raw_path": str(RAW_PATH)})["reason_codes"]


def test_blocked_page_and_caller_assertion_fail_closed(raw: bytes):
    blocked = raw.replace(b"Decision on Stock Split", b"Access Denied", 1)
    result = validate_candidate_bound_tier_b_fallback(_candidate(), raw_bytes=blocked, source_url=URL, expected_sha256=hashlib.sha256(blocked).hexdigest(), raw_path=RAW_PATH, retrieval_lineage={"request_id": "R", "retrieved_at": "T", "raw_path": str(RAW_PATH)})
    assert result["valid"] is False
    assert "TIER_B_BLOCKED_PAGE" in result["reason_codes"]
    asserted = validate_candidate_bound_tier_b_fallback(_candidate(official=True), raw_bytes=raw, source_url=URL, expected_sha256=RAW_SHA, raw_path=RAW_PATH, retrieval_lineage={"request_id": "R", "retrieved_at": "T", "raw_path": str(RAW_PATH)})
    assert "CALLER_ASSERTED_OFFICIAL_TRUST_FORBIDDEN" in asserted["reason_codes"]


def test_valid_fallback_emits_dual_tier_provenance_and_population_selection(raw: bytes):
    result = _validate(raw)
    assert result["valid"] is True
    provenance = result["provenance"]
    assert provenance["identity_authority_tier"] == TIER_A1_OPENDART
    assert provenance["content_authority_tier"] == TIER_B_ISSUER_OFFICIAL
    assert provenance["authority_resolution_mode"] == CANDIDATE_BOUND_FALLBACK_MODE
    population = evaluate_candidate_resolution_population([
        {**_candidate(), "fallback_validation": result, "content_authority_tier": TIER_B_ISSUER_OFFICIAL},
        {"candidate_rank": 3, "event_match_score": 50, "official_evidence_obtained": True, "official_content_usable": True, "semantic_valid": True},
    ])
    assert population["selected_candidate"]["candidate_rank"] == 2
    assert [item["status"] for item in population["candidate_statuses"]] == ["SELECTED", "REJECTED_LOWER_PRIORITY"]
    assert population["unresolved_higher_priority_candidate_count"] == 0


def test_invalid_fallback_stays_unresolved_and_direct_a1_contract_is_unchanged(raw: bytes):
    invalid = _validate(raw, a1_failure_persisted=False)
    population = evaluate_candidate_resolution_population([
        {**_candidate(), "content_authority_tier": TIER_B_ISSUER_OFFICIAL, "fallback_validation": invalid},
        {"candidate_rank": 3, "event_match_score": 50, "official_evidence_obtained": True, "official_content_usable": True, "semantic_valid": True},
    ])
    assert population["candidate_statuses"][0]["status"] == "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE"
    assert population["unresolved_higher_priority_candidate_count"] == 1
    assert classify_candidate_resolution(
        {"candidate_rank": 1}, official_evidence_obtained=True, semantic_valid=True, official_content_usable=True
    ) == "AUTHORITY_VALID"
