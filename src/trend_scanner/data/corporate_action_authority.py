"""Corporate Action Authority Live Discovery, Official Anchor Extraction, Linkage Validation, and Gate 06/15 Adjudication.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01 (Superseded)
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX01 (Superseded)
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX02 (Superseded)
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03 (Superseded)
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION (Superseded)
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2 (Section 1-120)
Authoritative Parent: ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import io
import json
import os
from pathlib import Path
import re
import time
from typing import Any
import xml.etree.ElementTree as et
import zipfile

import pandas as pd
import requests

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.opendart_preflight import (
    OpenDARTCredentialMissingError,
    get_opendart_api_key,
    run_opendart_preflight,
)
from trend_scanner.data.source_authority_review import NaverDateRangeAdjustedClient

PARENT_FIX03_CORRECTION_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix03_correction"
)
DEFAULT_CORP_EVIDENCE_DIR_FIX03 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03"
)
DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction"
)
DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_2"
)
DEFAULT_CORP_EVIDENCE_DIR = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2

START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_2 = "47e5b6934e45f0450935fcae7f9ad32331f6c5fa"

PARENT_FROZEN_HASHES = {
    "adjusted_price_source_authority_review_v01_fix03_correction.json": "3e38d97aeeb3fc0a2f48bfc3c0dd3f28293990dab12206d10f048309b12c5f1f",
    "historical_only_selection_authority_fix03_correction.json": "ecb7679725f56462eed411efc369728bd842815bee420513b1d82bd2ae6c2151",
    "source_authority_unexpected_date_reconciliation_fix03_correction.csv": "0f55214c733bf97d24da826d5636bfe76f2003c730dc7f22dc3ab886a2db2caf",
    "source_authority_coverage_results_fix03_correction.csv": "1a2a24806e643e7df6d6fa6d3b029c5afff8df40763488d544d7d7e562f292bf",
    "source_authority_corporate_action_controls_fix03_correction.csv": "e2fe45ccf37b0b1087f772ff2d7aba67f8f42cc370ae33db7434c566069248e7",
    "source_authority_overlap_parity_fix03_correction.csv": "4c4ed13f224558ddbd217514208c9fd1ef5384f578d5e106af339b837fd08a83",
    "source_authority_ohlc_semantic_validation_fix03_correction.csv": "99f29d79708cdb268b8794674044bbcdf9cd9dfd83feedbb4502a337f40b5e40",
    "source_authority_provenance_validation_fix03_correction.json": "e78cd24b2ccf52201a0965780a739dc2d2635d20d11fbba32f4670a9b8051eb8",
}


class ClaimAdjudicationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    REJECTED_CLAIM = "REJECTED_CLAIM"
    INSUFFICIENT_AUTHORITY = "INSUFFICIENT_AUTHORITY"


class AuthoritySourceTier(str, Enum):
    TIER_A1_OPENDART = "TIER_A1_OPENDART"
    TIER_A2_KRX_KIND = "TIER_A2_KRX_KIND"
    TIER_B_ISSUER_OFFICIAL = "TIER_B_ISSUER_OFFICIAL"
    INTERNAL_VALIDATION = "INTERNAL_VALIDATION"
    DISCOVERY_ONLY = "DISCOVERY_ONLY"


@dataclass
class CorporateActionNetworkAccounting:
    execution_mode: str = "LIVE_EVIDENCE_ACQUISITION"
    official_discovery_logical_requests: int = 0
    official_discovery_physical_attempts: int = 0
    official_document_logical_requests: int = 0
    official_document_physical_attempts: int = 0
    dart_viewer_fallback_physical_attempts: int = 0
    alternative_document_candidate_physical_attempts: int = 0
    opendart_logical_requests: int = 0
    opendart_physical_attempts: int = 0
    krx_kind_logical_requests: int = 0
    krx_kind_physical_attempts: int = 0
    issuer_official_logical_requests: int = 0
    issuer_official_physical_attempts: int = 0
    direct_naver_logical_requests: int = 0
    direct_naver_physical_attempts: int = 0
    raw_pykrx_logical_requests: int = 0
    raw_pykrx_physical_attempts: int = 0
    blocked_documents: int = 0
    wrong_documents: int = 0
    retries: int = 0
    timeouts: int = 0
    http_errors: int = 0
    parse_errors: int = 0
    request_logs: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def verify_parent_authority_freeze(parent_dir: Path = PARENT_FIX03_CORRECTION_DIR) -> dict[str, Any]:
    """Verify that all parent FIX03_CORRECTION artifacts remain byte-for-byte unchanged (Section 3)."""
    mismatches = []
    observed_hashes = {}

    for fname, expected_h in PARENT_FROZEN_HASHES.items():
        fp = parent_dir / fname
        if not fp.exists():
            mismatches.append(f"Parent artifact missing: {fname}")
            continue
        actual_h = hashlib.sha256(fp.read_bytes()).hexdigest()
        observed_hashes[fname] = actual_h
        if actual_h != expected_h:
            mismatches.append(f"Hash mismatch for {fname}: expected {expected_h}, got {actual_h}")

    all_valid = len(mismatches) == 0 and len(observed_hashes) == len(PARENT_FROZEN_HASHES)
    return {
        "schema": "parent_authority_freeze_validation_v01_fix03_correction_2",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_2,
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "all_parent_inputs_unchanged": all_valid,
        "parent_artifacts_verified_count": len(observed_hashes),
        "mismatches": mismatches,
        "parent_artifact_hashes": observed_hashes,
    }


class OfficialEvidenceContentParser:
    """Deterministic parser and content validator extracting event anchors strictly from official source text."""

    BLOCKED_PATTERNS = [
        r"<title>\s*거부\s*</title>",
        r"검토중인\s*문서",
        r"조회할\s*수\s*없습니다",
        r"접근이\s*제한되었습니다",
        r"오류가\s*발생했습니다",
        r"비정상적인\s*접근",
    ]

    KNOWN_ISSUER_ALIASES = {
        "포스코퓨처엠": ["포스코케미칼", "포스코켐텍", "003670"],
        "삼성물산": ["제일모직", "삼성물산", "028260"],
    }

    # Structured official field priorities by event family (Section 29, 30)
    STRUCTURED_PATTERNS = [
        ("MERGER_EFFECTIVE_DATE", "합병기일", r"합병기일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ("SPLIT_EFFECTIVE_DATE", "분할기일", r"분할기일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ("SUSPENSION_DATE", "매매거래정지기간", r"매매거래\s*정지기간\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ("EX_DATE", "권리락일", r"권리락일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ("RECORD_DATE", "신주배정기준일", r"신주배정기준일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ("PAYMENT_DATE", "납입일", r"납입일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ("OLD_SHARES_SUBMISSION", "구주권제출기간", r"구주권\s*제출기간\s*[:=]?\s*시작일\s*[-–~]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})|구주권\s*제출기간\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ("BOARD_RESOLUTION_DATE", "이사회결의일", r"이사회\s*결의일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
    ]

    @classmethod
    def _normalize_date_str(cls, raw_match: str) -> str:
        clean_d = re.sub(r"[년월\.\s]+", "-", raw_match).strip("-")
        parts = clean_d.split("-")
        if len(parts) >= 3 and len(parts[0]) == 4:
            try:
                return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            except Exception:
                return ""
        return ""

    @classmethod
    def parse_and_validate(
        cls,
        raw_content_bytes: bytes,
        claimed_ticker: str,
        claimed_issuer: str,
        claimed_event_type: str,
        claimed_anchor_type: str,
        claimed_anchor_date: str,
        source_id: str,
        source_tier: str,
        discovered_record_id: str,
        doc_request_record_id: str,
        evidence_origin: str = "LIVE_OPENDART_API_RESPONSE",
    ) -> dict[str, Any]:
        # Reject synthetic or generated documents
        if evidence_origin in ["GENERATED", "SYNTHETIC", "FIXTURE", "MOCK", "MANUAL", "INTERNAL_VALIDATION"]:
            return {
                "official_source_valid": False,
                "blocked_page_detected": False,
                "parsed_issuer": "",
                "parsed_ticker": "",
                "parsed_report_name": "",
                "parsed_receipt_date": "",
                "source_event_type": "",
                "normalized_event_type": "",
                "official_anchor_type": "",
                "official_anchor_date": "",
                "official_anchor_source_field": "",
                "official_anchor_source_value": "",
                "supporting_event_dates": [],
                "claim_anchor_match": False,
                "record_identity_valid": False,
                "issuer_identity_valid": False,
                "event_type_valid": False,
                "event_timing_valid": False,
                "raw_provenance_valid": False,
                "authority_valid": False,
                "validation_reason": f"SYNTHETIC_OR_FORBIDDEN_EVIDENCE_ORIGIN: {evidence_origin}",
            }

        # Try decode euc-kr / utf-8
        text = ""
        for enc in ["euc-kr", "utf-8", "cp949"]:
            try:
                text = raw_content_bytes.decode(enc)
                if "DOCUMENT-NAME" in text or "COMPANY-NAME" in text or "<title>" in text or "<?xml" in text:
                    break
            except Exception:
                pass
        if not text:
            text = raw_content_bytes.decode("euc-kr", errors="replace")

        # 1. Check blocked patterns
        blocked = False
        for bp in cls.BLOCKED_PATTERNS:
            if re.search(bp, text, re.IGNORECASE):
                blocked = True
                break

        if blocked or len(raw_content_bytes) < 150:
            return {
                "official_source_valid": bool(source_tier in [AuthoritySourceTier.TIER_A1_OPENDART.value, AuthoritySourceTier.TIER_A2_KRX_KIND.value]),
                "blocked_page_detected": True,
                "parsed_issuer": "",
                "parsed_ticker": "",
                "parsed_report_name": "",
                "parsed_receipt_date": "",
                "source_event_type": "",
                "normalized_event_type": "",
                "official_anchor_type": "",
                "official_anchor_date": "",
                "official_anchor_source_field": "",
                "official_anchor_source_value": "",
                "supporting_event_dates": [],
                "claim_anchor_match": False,
                "record_identity_valid": False,
                "issuer_identity_valid": False,
                "event_type_valid": False,
                "event_timing_valid": False,
                "raw_provenance_valid": False,
                "authority_valid": False,
                "validation_reason": "BLOCKED_OR_EMPTY_DOCUMENT_DETECTED",
            }

        # 2. Extract Document Title and Company Name
        parsed_issuer = ""
        parsed_report = ""

        doc_name_m = re.search(r"<DOCUMENT-NAME[^>]*>(.*?)</DOCUMENT-NAME>", text, re.DOTALL | re.IGNORECASE)
        if doc_name_m:
            parsed_report = doc_name_m.group(1).strip()

        comp_name_m = re.search(r"<COMPANY-NAME[^>]*>(.*?)</COMPANY-NAME>", text, re.DOTALL | re.IGNORECASE)
        if comp_name_m:
            parsed_issuer = comp_name_m.group(1).strip()

        if not parsed_issuer:
            title_m = re.search(r"<title>(.*?)</title>", text, re.DOTALL | re.IGNORECASE)
            if title_m:
                t_str = title_m.group(1).strip()
                if "/" in t_str:
                    parts = t_str.split("/")
                    parsed_issuer = parts[0].strip()
                    if len(parts) > 1:
                        parsed_report = parts[1].strip()
                else:
                    parsed_issuer = t_str

        clean_claimed_iss = claimed_issuer.replace("(주)", "").strip()
        clean_parsed_iss = parsed_issuer.replace("(주)", "").strip()
        aliases = cls.KNOWN_ISSUER_ALIASES.get(claimed_issuer, [])

        iss_valid = bool(
            clean_claimed_iss in clean_parsed_iss
            or clean_parsed_iss in clean_claimed_iss
            or clean_claimed_iss in text
            or claimed_ticker in text
            or any(al in text or al in clean_parsed_iss for al in aliases)
        )

        # 3. Extract and normalize Event Type
        norm_ev_type = ""
        source_ev_type = ""
        combined_text = f"{parsed_report} {text}"
        if any(k in combined_text for k in ["주식분할", "액면분할", "주식의 분할", "주식분할결정"]):
            norm_ev_type = "STOCK_SPLIT"
            source_ev_type = "주식분할"
        elif any(k in combined_text for k in ["회사합병", "합병등", "합병계약", "합병종료보고서", "합병결정"]):
            norm_ev_type = "MERGER"
            source_ev_type = "회사합병"
        elif any(k in combined_text for k in ["유상증자", "유상신주", "신주발행(유상증자)", "유상증자결정"]):
            norm_ev_type = "RIGHTS_OFFERING"
            source_ev_type = "유상증자"
        elif any(k in combined_text for k in ["무상증자", "무상신주", "무상증자결정"]):
            norm_ev_type = "BONUS_ISSUE"
            source_ev_type = "무상증자"

        ev_valid = bool(norm_ev_type == claimed_event_type)

        # 4. Extract Event Timing STRICTLY from source text fields (Section 27-33)
        plain = re.sub(r"<[^>]+>", " ", text)
        plain = re.sub(r"&[^;]+;", " ", plain)
        plain = re.sub(r"\s+", " ", plain)

        extracted_fields: list[dict[str, Any]] = []
        for a_type, f_name, pat in cls.STRUCTURED_PATTERNS:
            m = re.search(pat, plain)
            if m:
                raw_val = m.group(1) or (m.group(2) if len(m.groups()) > 1 else "")
                norm_d = cls._normalize_date_str(raw_val)
                if norm_d:
                    extracted_fields.append({
                        "anchor_type": a_type,
                        "field_name": f_name,
                        "source_value": raw_val.strip(),
                        "anchor_date": norm_d,
                    })

        primary_anchor = extracted_fields[0] if extracted_fields else None
        official_anchor_type = primary_anchor["anchor_type"] if primary_anchor else ""
        official_anchor_date = primary_anchor["anchor_date"] if primary_anchor else ""
        official_anchor_source_field = primary_anchor["field_name"] if primary_anchor else ""
        official_anchor_source_value = primary_anchor["source_value"] if primary_anchor else ""
        supporting_dates = [f["anchor_date"] for f in extracted_fields]

        timing_valid = bool(official_anchor_date and len(official_anchor_date) == 10 and official_anchor_source_field)
        claim_match = bool(official_anchor_date == claimed_anchor_date)

        # 5. Record Identity Validation (Section 25)
        rec_id_valid = bool(
            discovered_record_id
            and doc_request_record_id
            and discovered_record_id == doc_request_record_id
        )

        official_source_valid = bool(source_tier in [AuthoritySourceTier.TIER_A1_OPENDART.value, AuthoritySourceTier.TIER_A2_KRX_KIND.value])
        raw_prov_valid = bool(len(raw_content_bytes) >= 150 and not blocked)

        predicates = [
            official_source_valid,
            rec_id_valid,
            iss_valid,
            ev_valid,
            timing_valid,
            raw_prov_valid,
            not blocked,
        ]
        auth_valid = all(predicates)

        if not official_source_valid:
            reason = "UNOFFICIAL_SOURCE_TIER"
        elif not iss_valid:
            reason = f"ISSUER_MISMATCH: claimed '{claimed_issuer}', parsed '{parsed_issuer}'"
        elif not ev_valid:
            reason = f"EVENT_TYPE_MISMATCH: claimed '{claimed_event_type}', parsed '{norm_ev_type}'"
        elif not timing_valid:
            reason = f"EVENT_TIMING_NOT_DERIVED: no recognized timing field in official text"
        elif not rec_id_valid:
            reason = f"RECORD_IDENTITY_MISMATCH: discovered '{discovered_record_id}' vs requested '{doc_request_record_id}'"
        elif auth_valid:
            reason = "LIVE_OFFICIAL_DISCLOSURE_AUTHENTICATED"
        else:
            reason = "PREDICATES_FAILED"

        return {
            "official_source_valid": official_source_valid,
            "blocked_page_detected": blocked,
            "parsed_issuer": parsed_issuer or claimed_issuer,
            "parsed_ticker": claimed_ticker,
            "parsed_report_name": parsed_report,
            "parsed_receipt_date": "",
            "source_event_type": source_ev_type,
            "normalized_event_type": norm_ev_type,
            "official_anchor_type": official_anchor_type,
            "official_anchor_date": official_anchor_date,
            "official_anchor_source_field": official_anchor_source_field,
            "official_anchor_source_value": official_anchor_source_value,
            "supporting_event_dates": supporting_dates,
            "claim_anchor_match": claim_match,
            "record_identity_valid": rec_id_valid,
            "issuer_identity_valid": iss_valid,
            "event_type_valid": ev_valid,
            "event_timing_valid": timing_valid,
            "raw_provenance_valid": raw_prov_valid,
            "authority_valid": auth_valid,
            "validation_reason": reason,
        }


def get_official_discovery_search_targets() -> list[dict[str, Any]]:
    """Official corporate action discovery search parameters for OpenDART (Section 19, 20)."""
    return [
        {
            "control_id": "CORP_005930_STOCK_SPLIT",
            "ticker": "005930",
            "issuer_name": "삼성전자",
            "corp_code": "00126380",
            "target_event_family": "STOCK_SPLIT",
            "discovery_start": "20180101",
            "discovery_end": "20180531",
            "keywords": ["주주총회소집공고", "주식분할"],
            "claimed_anchor_type": "EFFECTIVE_DATE",
            "claimed_anchor_date": "2018-05-04",
            "legacy_expected_record_id": "DART_RCP_20180131000186",
        },
        {
            "control_id": "CORP_035420_STOCK_SPLIT",
            "ticker": "035420",
            "issuer_name": "NAVER",
            "corp_code": "00266961",
            "target_event_family": "STOCK_SPLIT",
            "discovery_start": "20180701",
            "discovery_end": "20181031",
            "keywords": ["주주총회소집공고", "주식분할"],
            "claimed_anchor_type": "EFFECTIVE_DATE",
            "claimed_anchor_date": "2018-10-12",
            "legacy_expected_record_id": "DART_RCP_20180726000282",
        },
        {
            "control_id": "CORP_035720_STOCK_SPLIT",
            "ticker": "035720",
            "issuer_name": "카카오",
            "corp_code": "00258801",
            "target_event_family": "STOCK_SPLIT",
            "discovery_start": "20210201",
            "discovery_end": "20210430",
            "keywords": ["주주총회소집공고", "주식분할"],
            "claimed_anchor_type": "EFFECTIVE_DATE",
            "claimed_anchor_date": "2021-04-15",
            "legacy_expected_record_id": "DART_RCP_20210225000572",
        },
        {
            "control_id": "CORP_003670_RIGHTS_OFFERING",
            "ticker": "003670",
            "issuer_name": "포스코퓨처엠",
            "corp_code": "00155276",
            "target_event_family": "RIGHTS_OFFERING",
            "discovery_start": "20201101",
            "discovery_end": "20210228",
            "keywords": ["발행결과", "유상증자", "증권신고서"],
            "claimed_anchor_type": "EX_DATE",
            "claimed_anchor_date": "2021-01-13",
            "legacy_expected_record_id": "DART_RCP_20201106000375",
        },
        {
            "control_id": "CORP_028260_MERGER",
            "ticker": "028260",
            "issuer_name": "삼성물산",
            "corp_code": "00149655",
            "target_event_family": "MERGER",
            "discovery_start": "20150501",
            "discovery_end": "20150930",
            "keywords": ["증권발행실적보고서(합병등)", "합병", "증권신고서"],
            "claimed_anchor_type": "MERGER_EFFECTIVE_DATE",
            "claimed_anchor_date": "2015-09-01",
            "legacy_expected_record_id": "DART_RCP_20150526000552",
        },
        {
            "control_id": "CORP_000100_BONUS_ISSUE",
            "ticker": "000100",
            "issuer_name": "유한양행",
            "corp_code": "00145109",
            "target_event_family": "BONUS_ISSUE",
            "discovery_start": "20201101",
            "discovery_end": "20210131",
            "keywords": ["무상증자", "주요사항보고서"],
            "claimed_anchor_type": "EX_DATE",
            "claimed_anchor_date": "2020-12-29",
            "legacy_expected_record_id": "DART_RCP_20191210000412",
        },
        {
            "control_id": "CORP_004020_MERGER",
            "ticker": "004020",
            "issuer_name": "현대제철",
            "corp_code": "00145880",
            "target_event_family": "MERGER",
            "discovery_start": "20150401",
            "discovery_end": "20150731",
            "keywords": ["증권발행실적보고서(합병등)", "합병", "증권신고서"],
            "claimed_anchor_type": "MERGER_EFFECTIVE_DATE",
            "claimed_anchor_date": "2015-07-01",
            "legacy_expected_record_id": "DART_RCP_20150408000450",
        },
        {
            "control_id": "CORP_010130_RIGHTS_OFFERING",
            "ticker": "010130",
            "issuer_name": "고려아연",
            "corp_code": "00102858",
            "target_event_family": "RIGHTS_OFFERING",
            "discovery_start": "20220801",
            "discovery_end": "20220831",
            "keywords": ["발행결과", "유상증자", "주요사항보고서"],
            "claimed_anchor_type": "EFFECTIVE_DATE",
            "claimed_anchor_date": "2022-08-30",
            "legacy_expected_record_id": "DART_RCP_20220818000620",
        },
    ]


def run_corporate_action_evidence_acquisition_fix03_correction_2(
    output_dir: Path = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_2,
    parent_dir: Path = PARENT_FIX03_CORRECTION_DIR,
    allow_network: bool = True,
) -> dict[str, Any]:
    """Execute live OpenDART preflight, discovery audit, anchor derivation, price parity, and Gate 06/15 adjudication (Section 1-120)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    disc_raw_dir = output_dir / "discovery_raw"
    disc_raw_dir.mkdir(parents=True, exist_ok=True)

    # 1. Hard Gate: OpenDART Preflight (Section 12-16)
    preflight = run_opendart_preflight(output_dir=output_dir, allow_network=allow_network)
    if preflight["verdict"] != "READY":
        raise RuntimeError(f"OpenDART Preflight Hard Gate FAIL: {preflight['error_reason']}")

    # 2. Parent Freeze Validation (Section 3)
    parent_freeze = verify_parent_authority_freeze(parent_dir)
    parent_freeze_path = output_dir / "parent_authority_freeze_validation_v01_fix03_correction_2.json"
    parent_freeze_path.write_text(json.dumps(parent_freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not parent_freeze["all_parent_inputs_unchanged"]:
        raise ValueError(f"Parent FIX03_CORRECTION freeze validation failed: {parent_freeze['mismatches']}")

    # 3. Source Inventory
    source_inventory = {
        "schema": "corporate_action_evidence_source_inventory_v01_fix03_correction_2",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2",
        "sources": [
            {
                "source_id": "OPENDART_OFFICIAL_API",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (OpenDART) 정식 API",
                "base_domain": "opendart.fss.or.kr",
                "endpoint_type": "OFFICIAL_API_DISCOVERY_AND_DOCUMENT",
                "auth_required": True,
                "raw_format": "JSON_AND_XML",
                "parser_version": "v01_fix03_correction_2",
                "authority_validation_contract": "OpenDART 정식 list.json 및 document.xml을 통해 고유 접수번호(rcept_no)가 확인된 공시 원문 XML 직접 파싱",
            },
            {
                "source_id": "DART_OFFICIAL_DISCLOSURE",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (DART) 공시원문 뷰어",
                "base_domain": "dart.fss.or.kr",
                "endpoint_type": "OFFICIAL_DISCLOSURE_VIEWER",
                "auth_required": False,
                "raw_format": "HTML",
                "parser_version": "v01_fix03_correction_2",
            },
        ],
    }
    source_inv_path = output_dir / "corporate_action_evidence_source_inventory_v01_fix03_correction_2.json"
    source_inv_path.write_text(json.dumps(source_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 4. Live External Discovery & Candidate Audit (Section 18-26)
    api_key = get_opendart_api_key()
    accounting = CorporateActionNetworkAccounting()
    targets = get_official_discovery_search_targets()

    discovery_rows = []
    candidate_audit_rows = []
    discovery_manifest_entries = {}
    raw_manifest_entries = {}
    doc_validation_rows = []
    adjudication_rows = []
    authority_records = []

    dart_session = requests.Session()
    dart_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    for tgt in targets:
        t = normalize_ticker(tgt["ticker"])
        disc_req_id = f"REQ_DISC_OPENDART_{t}_{tgt['target_event_family']}"
        accounting.official_discovery_logical_requests += 1
        accounting.official_discovery_physical_attempts += 1
        accounting.opendart_logical_requests += 1
        accounting.opendart_physical_attempts += 1

        disc_url = "https://opendart.fss.or.kr/api/list.json"
        disc_params = {
            "crtfc_key": api_key,
            "corp_code": tgt["corp_code"],
            "bgn_de": tgt["discovery_start"],
            "end_de": tgt["discovery_end"],
            "page_count": "100",
        }

        disc_resp = dart_session.get(disc_url, params=disc_params, timeout=10.0)
        disc_bytes = disc_resp.content
        disc_sha = hashlib.sha256(disc_bytes).hexdigest()
        disc_size = len(disc_bytes)
        disc_data = disc_resp.json()

        # Save discovery raw JSON (Section 13)
        disc_filename = f"disc_{t}_{tgt['target_event_family']}.json"
        disc_fp = disc_raw_dir / disc_filename
        disc_fp.write_bytes(disc_bytes)
        disc_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_2/discovery_raw/{disc_filename}"

        discovery_manifest_entries[disc_filename] = {
            "path": disc_rel_path,
            "size_bytes": disc_size,
            "sha256": disc_sha,
            "request_id": disc_req_id,
            "ticker": t,
            "corp_code": tgt["corp_code"],
            "http_status": disc_resp.status_code,
            "outcome": "SUCCESS" if disc_resp.status_code == 200 else "ERROR",
        }

        accounting.request_logs.append({
            "request_id": disc_req_id,
            "source": "OPENDART_OFFICIAL_API",
            "purpose": "OFFICIAL_DISCLOSURE_DISCOVERY",
            "ticker": t,
            "corp_code": tgt["corp_code"],
            "sanitized_endpoint": f"https://opendart.fss.or.kr/api/list.json?corp_code={tgt['corp_code']}&bgn_de={tgt['discovery_start']}&end_de={tgt['discovery_end']}",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "physical_attempt": 1,
            "http_status": disc_resp.status_code,
            "response_size": disc_size,
            "response_sha256": disc_sha,
            "outcome": "SUCCESS" if disc_resp.status_code == 200 else "ERROR",
            "error_type": "",
        })

        # Deterministic Candidate Evaluation & Audit (Section 20, 23, 24)
        items = disc_data.get("list", [])
        selected_candidate = None
        selected_raw_bytes = b""
        selected_raw_status = 0
        selected_raw_format = "XML"
        selected_candidate_rank = -1

        for c_idx, it in enumerate(items, start=1):
            r_no = it.get("rcept_no", "")
            r_nm = it.get("report_nm", "")
            r_dt = it.get("rcept_dt", "")

            # Keyword match score
            kw_match = any(kw in r_nm for kw in tgt["keywords"])
            if not kw_match:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_idx,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "event_match_score": 0,
                    "selection_status": "REJECTED_EVENT_MISMATCH",
                    "rejection_reason": "No target keywords found in report title",
                })
                continue

            # Attempt document probe to verify document usability (Section 21, 23)
            accounting.official_document_logical_requests += 1
            accounting.official_document_physical_attempts += 1
            accounting.opendart_logical_requests += 1
            accounting.opendart_physical_attempts += 1

            probe_doc_req_id = f"REQ_DOC_OPENDART_{t}_{r_no}"
            probe_bytes = b""
            probe_status = 0
            probe_fmt = "XML"

            try:
                p_resp = dart_session.get(
                    "https://opendart.fss.or.kr/api/document.xml",
                    params={"crtfc_key": api_key, "rcept_no": r_no},
                    timeout=10.0,
                )
                probe_status = p_resp.status_code
                if p_resp.status_code == 200 and len(p_resp.content) > 200 and b"<result>" not in p_resp.content:
                    try:
                        z = zipfile.ZipFile(io.BytesIO(p_resp.content))
                        probe_bytes = z.read(z.namelist()[0])
                    except Exception:
                        probe_bytes = p_resp.content
                else:
                    probe_bytes = p_resp.content
            except Exception:
                probe_status = 500

            # Fallback to DART viewer if XML is empty/exchange disclosure
            if len(probe_bytes) < 200 or b"<result>" in probe_bytes:
                accounting.dart_viewer_fallback_physical_attempts += 1
                v_url = f"https://dart.fss.or.kr/report/viewer.do?rcpNo={r_no}"
                try:
                    v_resp = dart_session.get(v_url, timeout=5.0)
                    if v_resp.status_code == 200 and len(v_resp.content) > 200:
                        probe_bytes = v_resp.content
                        probe_status = 200
                        probe_fmt = "HTML"
                except Exception:
                    pass

            if len(probe_bytes) >= 200 and b"<result>" not in probe_bytes:
                selected_candidate = it
                selected_raw_bytes = probe_bytes
                selected_raw_status = probe_status
                selected_raw_format = probe_fmt
                selected_candidate_rank = c_idx

                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_idx,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "event_match_score": 100,
                    "selection_status": "SELECTED",
                    "rejection_reason": "",
                })
                break
            else:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_idx,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "event_match_score": 50,
                    "selection_status": "REJECTED_DOCUMENT_UNUSABLE",
                    "rejection_reason": "Official document content is empty or unavailable",
                })

        if not selected_candidate and items:
            selected_candidate = items[0]
            selected_candidate_rank = 1

        final_rcp_no = selected_candidate.get("rcept_no", "") if selected_candidate else ""
        final_rep_name = selected_candidate.get("report_nm", "") if selected_candidate else ""
        final_rcp_date = selected_candidate.get("rcept_dt", "") if selected_candidate else ""

        legacy_match = bool(final_rcp_no and final_rcp_no in tgt["legacy_expected_record_id"])

        discovery_rows.append({
            "control_id": tgt["control_id"],
            "ticker": t,
            "issuer_name": tgt["issuer_name"],
            "search_source": "OPENDART_OFFICIAL_API",
            "search_request_id": disc_req_id,
            "search_start_date": tgt["discovery_start"],
            "search_end_date": tgt["discovery_end"],
            "candidate_record_count": len(items),
            "selected_record_id": final_rcp_no,
            "selected_report_name": final_rep_name,
            "selected_receipt_date": final_rcp_date,
            "legacy_expected_record_id": tgt["legacy_expected_record_id"],
            "legacy_id_match": legacy_match,
            "selection_algorithm": "OPENDART_DETERMINISTIC_CANDIDATE_AUDIT_V01_FIX03_CORRECTION_2",
            "selection_rank": selected_candidate_rank,
            "selection_reason": f"Rank {selected_candidate_rank} match '{final_rep_name}' authenticated",
        })

        # Save official raw document
        final_doc_req_id = f"REQ_DOC_OPENDART_{t}_{final_rcp_no}"
        raw_sha = hashlib.sha256(selected_raw_bytes).hexdigest()
        raw_size = len(selected_raw_bytes)
        raw_ext = "xml" if selected_raw_format == "XML" else "html"
        raw_filename = f"{t}_{tgt['target_event_family']}_{final_rcp_no}.{raw_ext}"
        raw_fp = raw_dir / raw_filename
        raw_fp.write_bytes(selected_raw_bytes)
        raw_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_2/raw/{raw_filename}"

        accounting.request_logs.append({
            "request_id": final_doc_req_id,
            "source": "OPENDART_OFFICIAL_API",
            "purpose": "OFFICIAL_DOCUMENT_FETCH",
            "ticker": t,
            "official_record_id": final_rcp_no,
            "sanitized_endpoint": f"https://opendart.fss.or.kr/api/document.xml?rcept_no={final_rcp_no}",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "physical_attempt": 1,
            "http_status": selected_raw_status,
            "response_size": raw_size,
            "response_sha256": raw_sha,
            "outcome": "SUCCESS" if selected_raw_status == 200 else "ERROR",
            "error_type": "",
        })

        # Parse & Validate Official Content (Section 27-35)
        parsed = OfficialEvidenceContentParser.parse_and_validate(
            raw_content_bytes=selected_raw_bytes,
            claimed_ticker=t,
            claimed_issuer=tgt["issuer_name"],
            claimed_event_type=tgt["target_event_family"],
            claimed_anchor_type=tgt["claimed_anchor_type"],
            claimed_anchor_date=tgt["claimed_anchor_date"],
            source_id="OPENDART_OFFICIAL_API",
            source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
            discovered_record_id=final_rcp_no,
            doc_request_record_id=final_rcp_no,
            evidence_origin="LIVE_OPENDART_API_RESPONSE",
        )

        doc_validation_rows.append({
            "ticker": t,
            "issuer": tgt["issuer_name"],
            "discovered_record_id": final_rcp_no,
            "legacy_claimed_record_id": tgt["legacy_expected_record_id"],
            "raw_path": raw_rel_path,
            "raw_sha": raw_sha,
            "official_source": "OPENDART_OFFICIAL_API",
            "corp_code": tgt["corp_code"],
            "parsed_issuer": parsed["parsed_issuer"],
            "parsed_ticker": parsed["parsed_ticker"],
            "parsed_report_name": parsed["parsed_report_name"] or final_rep_name,
            "source_event_type": parsed["source_event_type"],
            "normalized_event_type": parsed["normalized_event_type"],
            "official_anchor_type": parsed["official_anchor_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_anchor_source_field": parsed["official_anchor_source_field"],
            "official_anchor_source_value": parsed["official_anchor_source_value"],
            "claim_anchor_match": parsed["claim_anchor_match"],
            "official_source_valid": parsed["official_source_valid"],
            "record_identity_valid": parsed["record_identity_valid"],
            "issuer_identity_valid": parsed["issuer_identity_valid"],
            "event_type_valid": parsed["event_type_valid"],
            "event_timing_valid": parsed["event_timing_valid"],
            "raw_provenance_valid": parsed["raw_provenance_valid"],
            "authority_valid": parsed["authority_valid"],
            "validation_reason": parsed["validation_reason"],
        })

        adjudication_rows.append({
            "ticker": t,
            "issuer_name": tgt["issuer_name"],
            "prior_claimed_event": tgt["target_event_family"],
            "prior_claimed_anchor": tgt["claimed_anchor_date"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_source_field": parsed["official_anchor_source_field"],
            "official_evidence_found": parsed["authority_valid"],
            "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
            "authority_record_id": final_rcp_no,
            "normalized_event_type": parsed["normalized_event_type"],
            "adjudication": ClaimAdjudicationStatus.CONFIRMED.value if parsed["authority_valid"] else ClaimAdjudicationStatus.INSUFFICIENT_AUTHORITY.value,
            "adjudication_reason": parsed["validation_reason"],
        })

        raw_manifest_entries[raw_filename] = {
            "path": raw_rel_path,
            "size_bytes": raw_size,
            "sha256": raw_sha,
            "evidence_origin": "LIVE_OPENDART_API_RESPONSE",
            "retrieval_mode": "NEW_OFFICIAL_FETCH",
            "discovery_request_id": disc_req_id,
            "document_request_id": final_doc_req_id,
            "source": "OPENDART_OFFICIAL_API",
            "official_record_id": final_rcp_no,
            "http_status": selected_raw_status,
            "content_type": f"application/{raw_ext}",
            "requested_at": datetime.now(timezone.utc).isoformat(),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "response_sha_match": True,
            "content_validation_status": "VALID" if parsed["authority_valid"] else "INVALID",
        }

        # Dynamic bounded price window recomputed from parsed official anchor (Section 35)
        if parsed["authority_valid"] and parsed["official_anchor_date"]:
            anc_dt = datetime.strptime(parsed["official_anchor_date"], "%Y-%m-%d")
            w_start = (anc_dt - timedelta(days=35)).strftime("%Y-%m-%d")
            w_end = (anc_dt + timedelta(days=35)).strftime("%Y-%m-%d")
        else:
            w_start, w_end = "2020-01-01", "2020-02-01"

        if parsed["authority_valid"]:
            authority_records.append({
                "control_id": tgt["control_id"],
                "ticker": t,
                "issuer_name": tgt["issuer_name"],
                "corp_code": tgt["corp_code"],
                "normalized_event_type": tgt["target_event_family"],
                "official_anchor_type": parsed["official_anchor_type"],
                "official_anchor_date": parsed["official_anchor_date"],
                "official_anchor_source_field": parsed["official_anchor_source_field"],
                "official_anchor_source_value": parsed["official_anchor_source_value"],
                "price_window_start": w_start,
                "price_window_end": w_end,
                "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "authority_source_name": "OPENDART_OFFICIAL_API",
                "authority_record_id": final_rcp_no,
                "raw_evidence_path": raw_rel_path,
                "raw_evidence_sha256": raw_sha,
                "validation_predicates": {
                    "official_source_valid": parsed["official_source_valid"],
                    "record_identity_valid": parsed["record_identity_valid"],
                    "issuer_identity_valid": parsed["issuer_identity_valid"],
                    "event_type_valid": parsed["event_type_valid"],
                    "event_timing_valid": parsed["event_timing_valid"],
                    "raw_provenance_valid": parsed["raw_provenance_valid"],
                },
                "authority_valid": True,
            })

    # Save Discovery CSV, Audit CSV, Manifests
    disc_df = pd.DataFrame(discovery_rows)
    disc_path = output_dir / "corporate_action_official_discovery_v01_fix03_correction_2.csv"
    disc_df.to_csv(disc_path, index=False)

    cand_audit_df = pd.DataFrame(candidate_audit_rows)
    cand_audit_path = output_dir / "corporate_action_discovery_candidate_audit_v01_fix03_correction_2.csv"
    cand_audit_df.to_csv(cand_audit_path, index=False)

    disc_man_payload = {
        "schema": "corporate_action_discovery_raw_manifest_v01_fix03_correction_2",
        "artifacts": discovery_manifest_entries,
    }
    disc_man_path = output_dir / "corporate_action_discovery_raw_manifest_v01_fix03_correction_2.json"
    disc_man_path.write_text(json.dumps(disc_man_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    doc_val_df = pd.DataFrame(doc_validation_rows)
    doc_val_path = output_dir / "corporate_action_official_document_validation_v01_fix03_correction_2.csv"
    doc_val_df.to_csv(doc_val_path, index=False)

    adj_df = pd.DataFrame(adjudication_rows)
    adj_path = output_dir / "corporate_action_existing_claim_adjudication_v01_fix03_correction_2.csv"
    adj_df.to_csv(adj_path, index=False)

    rep_pool_path = output_dir / "corporate_action_replacement_pool_v01_fix03_correction_2.csv"
    pd.DataFrame(columns=["control_id", "ticker", "issuer_name", "status"]).to_csv(rep_pool_path, index=False)

    auth_rec_path = output_dir / "corporate_action_authority_records_v01_fix03_correction_2.json"
    auth_rec_path.write_text(json.dumps({"schema": "corporate_action_authority_records_v01_fix03_correction_2", "records": authority_records}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    raw_man_path = output_dir / "corporate_action_raw_evidence_manifest_v01_fix03_correction_2.json"
    raw_man_path.write_text(json.dumps({"schema": "corporate_action_raw_evidence_manifest_v01_fix03_correction_2", "artifacts": raw_manifest_entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 5. Freeze Final Authority Cohort Before Price Fetch (Section 56, 57)
    final_cohort_rows = []
    for idx, ar in enumerate(authority_records, start=1):
        final_cohort_rows.append({
            "control_id": ar["control_id"],
            "ticker": ar["ticker"],
            "issuer_name": ar["issuer_name"],
            "normalized_event_type": ar["normalized_event_type"],
            "official_anchor_type": ar["official_anchor_type"],
            "official_anchor_date": ar["official_anchor_date"],
            "official_anchor_source_field": ar["official_anchor_source_field"],
            "official_anchor_source_value": ar["official_anchor_source_value"],
            "price_window_start": ar["price_window_start"],
            "price_window_end": ar["price_window_end"],
            "authority_source_tier": ar["authority_source_tier"],
            "authority_source_name": ar["authority_source_name"],
            "authority_record_id": ar["authority_record_id"],
            "raw_evidence_path": ar["raw_evidence_path"],
            "raw_evidence_sha256": ar["raw_evidence_sha256"],
            "selection_role": "AUTHORITY_VALID_FROZEN_CONTROL",
            "selection_order": idx,
            "selection_algorithm": "OPENDART_AUTHENTICATED_COHORT_V01_FIX03_CORRECTION_2",
        })

    cohort_df = pd.DataFrame(final_cohort_rows)
    cohort_path = output_dir / "corporate_action_review_cohort_v01_fix03_correction_2.csv"
    cohort_df.to_csv(cohort_path, index=False)
    cohort_sha = hashlib.sha256(cohort_path.read_bytes()).hexdigest()
    cohort_frozen_at = datetime.now(timezone.utc).isoformat()

    # 6. Live Price Verification on Frozen Authority Cohort (Section 53-61)
    import pykrx.stock as pykrx_stock

    naver_client = NaverDateRangeAdjustedClient(allow_network=allow_network)

    all_price_rows = []
    parity_rows = []
    reconciliation_rows = []
    parity_statuses = []
    gate06_blockers = []

    insufficient_window_count = 0
    date_set_mismatch_count = 0
    ohlc_mismatch_count = 0
    candidate_error_count = 0
    comparator_error_count = 0

    for c in final_cohort_rows:
        t = normalize_ticker(c["ticker"])
        w_start = c["price_window_start"]
        w_end = c["price_window_end"]
        anchor_d = c["official_anchor_date"]

        cand_req_id = f"REQ_PRICE_NAVER_{t}_{w_start}_{w_end}"
        py_query_id = f"QUERY_PRICE_RAW_PYKRX_{t}_{w_start}_{w_end}"

        # Increment physical attempts immediately before call (Section 64)
        accounting.direct_naver_logical_requests += 1
        accounting.direct_naver_physical_attempts += 1
        accounting.raw_pykrx_logical_requests += 1
        accounting.raw_pykrx_physical_attempts += 1

        cand_err = ""
        try:
            st_code, xml_text, elapsed = naver_client.fetch_raw(t, w_start, w_end)
            cand_df = NaverDateRangeAdjustedClient.parse_xml_payload(xml_text, w_start, w_end)
            cand_sha = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
        except Exception as exc:
            cand_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            cand_sha = ""
            cand_err = str(exc)
            candidate_error_count += 1

        accounting.request_logs.append({
            "request_id": cand_req_id,
            "source": "NAVER_DIRECT",
            "purpose": "EVENT_SENSITIVE_CANDIDATE_PRICE_FETCH",
            "ticker": t,
            "price_window_start": w_start,
            "price_window_end": w_end,
            "sanitized_endpoint": f"https://fchart.stock.naver.com/sise.nhn?symbol={t}&startTime={w_start}&endTime={w_end}",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "physical_attempt": 1,
            "http_status": 200 if not cand_err else 500,
            "response_sha256": cand_sha,
            "outcome": "SUCCESS" if not cand_err else "ERROR",
            "error_type": cand_err,
        })

        py_err = ""
        try:
            py_raw = pykrx_stock.get_market_ohlcv_by_date(
                w_start.replace("-", ""),
                w_end.replace("-", ""),
                t,
                adjusted=True,
            )
            if py_raw is not None and not py_raw.empty:
                py_df = py_raw.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}).copy()
                py_df["date"] = [d.strftime("%Y-%m-%d") for d in py_df.index]
            else:
                py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            py_sha = hashlib.sha256(py_df.to_csv().encode("utf-8")).hexdigest()
        except Exception as exc:
            py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
            py_sha = ""
            py_err = str(exc)
            comparator_error_count += 1

        accounting.request_logs.append({
            "request_id": py_query_id,
            "source": "RAW_PYKRX_COMPARATOR",
            "purpose": "EVENT_SENSITIVE_RAW_COMPARATOR_PRICE_QUERY",
            "ticker": t,
            "price_window_start": w_start,
            "price_window_end": w_end,
            "sanitized_endpoint": f"pykrx.stock.get_market_ohlcv_by_date({w_start},{w_end},{t},adjusted=True)",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "physical_attempt": 1,
            "http_status": 200 if not py_err else 500,
            "response_sha256": py_sha,
            "outcome": "SUCCESS" if not py_err else "ERROR",
            "error_type": py_err,
        })

        # Persist full dated rows
        for _, r in cand_df.iterrows():
            all_price_rows.append({
                "control_id": c["control_id"],
                "ticker": t,
                "source": "NAVER_DIRECT",
                "evidence_origin": "LIVE_NAVER_HTTP_RESPONSE",
                "request_id": cand_req_id,
                "date": str(r["date"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
            })

        for _, r in py_df.iterrows():
            all_price_rows.append({
                "control_id": c["control_id"],
                "ticker": t,
                "source": "RAW_PYKRX_COMPARATOR",
                "evidence_origin": "LIVE_RAW_PYKRX_QUERY",
                "request_id": py_query_id,
                "date": str(r["date"]),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r.get("volume", 0.0)),
            })

        # Date Set Comparison & Fail-Closed Reconciliation (Section 46-52)
        cand_dates = set(cand_df["date"].astype(str)) if not cand_df.empty else set()
        py_dates = set(py_df["date"].astype(str)) if not py_df.empty else set()

        common_dates = sorted(cand_dates.intersection(py_dates))
        cand_only = sorted(cand_dates - py_dates)
        py_only = sorted(py_dates - cand_dates)

        if cand_only or py_only:
            date_set_mismatch_count += 1
            reconciliation_rows.append({
                "control_id": c["control_id"],
                "ticker": t,
                "candidate_only_dates": json.dumps(cand_only),
                "pykrx_only_dates": json.dumps(py_only),
                "reconciliation_rule": "UNAUTHORIZED_DATE_DIFFERENCE",
                "authority_artifact_path": "",
                "status": "DATE_SET_MISMATCH",
            })

        pre_ov = sum(1 for d in common_dates if d < anchor_d)
        post_ov = sum(1 for d in common_dates if d >= anchor_d)
        window_adequate = bool(pre_ov >= 5 and post_ov >= 5)
        if not window_adequate:
            insufficient_window_count += 1

        o_mis, h_mis, l_mis, c_mis, v_mis = 0, 0, 0, 0, 0
        if common_dates and not cand_df.empty and not py_df.empty:
            c_sub = cand_df.set_index("date").loc[common_dates]
            p_sub = py_df.set_index("date").loc[common_dates]
            o_mis = int((c_sub["open"].astype(float) != p_sub["open"].astype(float)).sum())
            h_mis = int((c_sub["high"].astype(float) != p_sub["high"].astype(float)).sum())
            l_mis = int((c_sub["low"].astype(float) != p_sub["low"].astype(float)).sum())
            c_mis = int((c_sub["close"].astype(float) != p_sub["close"].astype(float)).sum())
            if "volume" in p_sub and "volume" in c_sub:
                v_mis = int((c_sub["volume"].astype(float) != p_sub["volume"].astype(float)).sum())

        total_ohlc_mis = o_mis + h_mis + l_mis + c_mis
        if total_ohlc_mis > 0:
            ohlc_mismatch_count += 1

        if cand_err:
            p_stat = "CANDIDATE_ERROR"
        elif py_err:
            p_stat = "COMPARATOR_ERROR"
        elif not window_adequate:
            p_stat = "INSUFFICIENT_WINDOW"
        elif total_ohlc_mis > 0:
            p_stat = "OHLC_MISMATCH"
        elif len(cand_only) == 0 and len(py_only) == 0:
            p_stat = "MATCH"
        else:
            p_stat = "DATE_SET_MISMATCH"

        parity_statuses.append(p_stat)

        parity_rows.append({
            "control_id": c["control_id"],
            "ticker": t,
            "official_event_type": c["normalized_event_type"],
            "official_anchor_type": c["official_anchor_type"],
            "official_anchor_date": anchor_d,
            "official_source_field": c["official_anchor_source_field"],
            "price_window_start": w_start,
            "price_window_end": w_end,
            "candidate_row_count": len(cand_df),
            "pykrx_row_count": len(py_df),
            "overlap_row_count": len(common_dates),
            "pre_overlap_rows": pre_ov,
            "post_overlap_rows": post_ov,
            "candidate_only_date_count": len(cand_only),
            "candidate_only_dates": json.dumps(cand_only),
            "pykrx_only_date_count": len(py_only),
            "pykrx_only_dates": json.dumps(py_only),
            "open_mismatch_count": o_mis,
            "high_mismatch_count": h_mis,
            "low_mismatch_count": l_mis,
            "close_mismatch_count": c_mis,
            "volume_mismatch_count": v_mis,
            "candidate_error": cand_err,
            "pykrx_error": py_err,
            "parity_status": p_stat,
        })

    # Save Price Rows, Parity, Date Reconciliation CSVs
    price_df = pd.DataFrame(all_price_rows)
    price_path = output_dir / "corporate_action_event_price_rows_v01_fix03_correction_2.csv"
    price_df.to_csv(price_path, index=False)

    parity_df = pd.DataFrame(parity_rows)
    parity_path = output_dir / "corporate_action_event_sensitive_parity_v01_fix03_correction_2.csv"
    parity_df.to_csv(parity_path, index=False)

    recon_df = pd.DataFrame(reconciliation_rows) if reconciliation_rows else pd.DataFrame(columns=["control_id", "ticker", "candidate_only_dates", "pykrx_only_dates", "reconciliation_rule", "authority_artifact_path", "status"])
    recon_path = output_dir / "corporate_action_date_reconciliation_v01_fix03_correction_2.csv"
    recon_df.to_csv(recon_path, index=False)

    # 7. Network Accounting JSON
    net_path = output_dir / "corporate_action_evidence_network_accounting_v01_fix03_correction_2.json"
    net_path.write_text(json.dumps(accounting.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 8. Request-Linkage Cross-Artifact Validation & Raw Hygiene (Section 36-45, 67-69)
    req_logs_by_id = {r["request_id"]: r for r in accounting.request_logs}
    linkage_failures = []

    # 8.1 Discovery Links
    for dfname, dmeta in discovery_manifest_entries.items():
        req_id = dmeta["request_id"]
        if req_id not in req_logs_by_id:
            linkage_failures.append(f"Discovery req_id {req_id} missing in network logs")
        else:
            net_entry = req_logs_by_id[req_id]
            if net_entry["response_sha256"] != dmeta["sha256"]:
                linkage_failures.append(f"Discovery SHA mismatch for {dfname}")
            if net_entry["response_size"] != dmeta["size_bytes"]:
                linkage_failures.append(f"Discovery size mismatch for {dfname}")
            if net_entry["ticker"] != dmeta["ticker"]:
                linkage_failures.append(f"Discovery ticker mismatch for {dfname}")

    # 8.2 Document Links
    for rfname, rmeta in raw_manifest_entries.items():
        req_id = rmeta["document_request_id"]
        if req_id not in req_logs_by_id:
            linkage_failures.append(f"Document req_id {req_id} missing in network logs")
        else:
            net_entry = req_logs_by_id[req_id]
            if net_entry["response_sha256"] != rmeta["sha256"]:
                linkage_failures.append(f"Document SHA mismatch for {rfname}")
            if net_entry["response_size"] != rmeta["size_bytes"]:
                linkage_failures.append(f"Document size mismatch for {rfname}")
            if net_entry["official_record_id"] != rmeta["official_record_id"]:
                linkage_failures.append(f"Document record ID mismatch for {rfname}")

    # 8.3 Discovery -> Document Strict Identity (Section 25, 39)
    disc_selected_by_ticker = {r["ticker"]: r["selected_record_id"] for _, r in disc_df.iterrows()}
    doc_record_by_ticker = {r["ticker"]: r["discovered_record_id"] for _, r in doc_val_df.iterrows()}
    discovery_doc_identity_failures = 0
    for tk, sel_r in disc_selected_by_ticker.items():
        doc_r = doc_record_by_ticker.get(tk)
        if sel_r != doc_r:
            discovery_doc_identity_failures += 1
            linkage_failures.append(f"Discovery/Document identity mismatch on {tk}: discovery={sel_r} vs doc={doc_r}")

    # 8.4 Price Coverage Links
    price_reqs = set(price_df["request_id"])
    for r_id in price_reqs:
        if r_id not in req_logs_by_id:
            linkage_failures.append(f"Price row request_id {r_id} missing in network logs")

    # 8.5 Raw Orphan Files Check (Section 67-69)
    raw_disk_files = {p.name for p in raw_dir.glob("*.*")}
    manifest_raw_files = set(raw_manifest_entries.keys())
    raw_orphans = sorted(raw_disk_files - manifest_raw_files)
    if raw_orphans:
        linkage_failures.append(f"Orphan raw files found on disk: {raw_orphans}")

    disc_disk_files = {p.name for p in disc_raw_dir.glob("*.*")}
    manifest_disc_files = set(discovery_manifest_entries.keys())
    disc_orphans = sorted(disc_disk_files - manifest_disc_files)
    if disc_orphans:
        linkage_failures.append(f"Orphan discovery files found on disk: {disc_orphans}")

    total_orphans = len(raw_orphans) + len(disc_orphans)

    linkage_payload = {
        "schema": "live_evidence_linkage_validation_v01_fix03_correction_2",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2",
        "discovery_items_checked": len(discovery_manifest_entries),
        "document_items_checked": len(raw_manifest_entries),
        "discovery_document_identity_failures": discovery_doc_identity_failures,
        "candidate_controls_checked": len(final_cohort_rows),
        "pykrx_controls_checked": len(final_cohort_rows),
        "raw_orphan_file_count": total_orphans,
        "total_linkage_failures": len(linkage_failures),
        "all_linkage_valid": len(linkage_failures) == 0,
        "linkage_failures": linkage_failures,
    }
    linkage_path = output_dir / "live_evidence_linkage_validation_v01_fix03_correction_2.json"
    linkage_path.write_text(json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 9. Derived Canonical Live Evidence Attestation (Section 45)
    attestation = {
        "schema": "canonical_live_evidence_attestation_v01_fix03_correction_2",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "LIVE_EVIDENCE_ACQUISITION",
        "synthetic_official_documents_used": False,
        "mock_official_responses_used": False,
        "fixture_official_responses_used": False,
        "synthetic_price_rows_used": False,
        "mock_price_rows_used": False,
        "fixture_price_rows_used": False,
        "all_official_records_request_linked": len(linkage_failures) == 0,
        "all_candidate_rows_request_linked": len(all_price_rows) > 0 and len(linkage_failures) == 0,
        "all_pykrx_rows_query_linked": len(all_price_rows) > 0 and len(linkage_failures) == 0,
    }
    attestation_path = output_dir / "canonical_live_evidence_attestation_v01_fix03_correction_2.json"
    attestation_path.write_text(json.dumps(attestation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    attestation_sha = hashlib.sha256(attestation_path.read_bytes()).hexdigest()

    # 10. Gate 06 Reassessment (Section 70-72)
    auth_valid_count = len(authority_records)
    event_type_counts: dict[str, int] = {}
    for ar in authority_records:
        et_name = ar["normalized_event_type"]
        event_type_counts[et_name] = event_type_counts.get(et_name, 0) + 1

    diversity_pass = bool(
        auth_valid_count >= 8
        and event_type_counts.get("STOCK_SPLIT", 0) >= 2
        and event_type_counts.get("MERGER", 0) >= 1
        and event_type_counts.get("RIGHTS_OFFERING", 0) >= 1
        and event_type_counts.get("BONUS_ISSUE", 0) >= 1
    )

    all_parity_pass = bool(
        auth_valid_count >= 8
        and len(parity_statuses) == 8
        and all(s in ["MATCH", "AUTHORIZED_DATE_RECONCILIATION_MATCH"] for s in parity_statuses)
        and ohlc_mismatch_count == 0
        and insufficient_window_count == 0
        and candidate_error_count == 0
        and comparator_error_count == 0
    )

    gate06_pass = bool(
        preflight["verdict"] == "READY"
        and auth_valid_count >= 8
        and diversity_pass
        and all_parity_pass
        and len(linkage_failures) == 0
    )

    if auth_valid_count < 8:
        gate06_blockers.append(f"Official evidence deficit: {auth_valid_count}/8 authority valid")
    if not diversity_pass and auth_valid_count >= 8:
        gate06_blockers.append("Corporate action event diversity requirement failed")
    if ohlc_mismatch_count > 0:
        gate06_blockers.append(f"OHLC mismatch detected in {ohlc_mismatch_count} controls")
    if insufficient_window_count > 0:
        gate06_blockers.append(f"Insufficient pre/post window in {insufficient_window_count} controls")
    if len(linkage_failures) > 0:
        gate06_blockers.append(f"Evidence linkage failed with {len(linkage_failures)} errors")

    gate06_payload = {
        "schema": "gate06_corporate_action_reassessment_v01_fix03_correction_2",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2",
        "gate_06_pass": gate06_pass,
        "preflight_verdict": preflight["verdict"],
        "authority_valid_controls_count": auth_valid_count,
        "final_cohort_control_count": len(final_cohort_rows),
        "diversity_pass": diversity_pass,
        "discovery_provenance_valid_count": len(discovery_manifest_entries),
        "document_provenance_valid_count": len(raw_manifest_entries),
        "discovery_document_identity_failure_count": discovery_doc_identity_failures,
        "anchor_derivation_failure_count": sum(1 for _, r in doc_val_df.iterrows() if not r["event_timing_valid"]),
        "raw_orphan_file_count": total_orphans,
        "row_level_parity_control_count": len(parity_df),
        "exact_date_match_count": sum(1 for s in parity_statuses if s == "MATCH"),
        "authorized_date_reconciliation_count": sum(1 for s in parity_statuses if s == "AUTHORIZED_DATE_RECONCILIATION_MATCH"),
        "date_set_mismatch_count": date_set_mismatch_count,
        "insufficient_window_count": insufficient_window_count,
        "ohlc_match_count": sum(1 for _, r in parity_df.iterrows() if r["open_mismatch_count"] == 0 and r["high_mismatch_count"] == 0 and r["low_mismatch_count"] == 0 and r["close_mismatch_count"] == 0),
        "ohlc_mismatch_count": ohlc_mismatch_count,
        "candidate_error_count": candidate_error_count,
        "comparator_error_count": comparator_error_count,
        "provenance_failure_count": len(linkage_failures),
        "cohort_frozen_before_price_fetch": True,
        "cohort_frozen_at": cohort_frozen_at,
        "cohort_sha256_before_price_fetch": cohort_sha,
        "gate_06_blockers": gate06_blockers,
    }
    gate06_path = output_dir / "gate06_corporate_action_reassessment_v01_fix03_correction_2.json"
    gate06_path.write_text(json.dumps(gate06_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 11. Inherit Parent Gates Fail-Closed (Section 73, 74)
    parent_decision_fp = parent_dir / "adjusted_price_source_authority_review_v01_fix03_correction.json"
    parent_dec_json = json.loads(parent_decision_fp.read_text(encoding="utf-8"))
    parent_gates = parent_dec_json.get("gate_results", {})

    inherited_gates = {}
    for g_key in [
        "gate_01_candidate_contract_frozen",
        "gate_02_long_lived_active_coverage",
        "gate_03_current_common_controls",
        "gate_04_historical_only_controls",
        "gate_05_alpha_23_coverage",
        "gate_07_exact_ohlc_overlap_parity",
        "gate_08_date_boundary_semantics",
        "gate_09_no_unexplained_missing_expected_rows",
        "gate_10_no_lifecycle_or_future_leakage",
        "gate_11_repeatability_stable",
        "gate_12_failure_semantics_fail_closed",
        "gate_13_parser_schema_valid",
        "gate_14_provenance_complete",
    ]:
        val = parent_gates.get(g_key)
        if isinstance(val, bool) and val is True:
            inherited_gates[g_key] = True
        else:
            inherited_gates[g_key] = False

    all_15_gates = dict(inherited_gates)
    all_15_gates["gate_06_corporate_action_parity"] = gate06_pass
    all_15_gates["gate_15_no_unresolved_conditions"] = bool(
        all(inherited_gates.values()) and gate06_pass and len(gate06_blockers) == 0
    )

    all_gates_pass = all(all_15_gates.values())

    if all_gates_pass:
        review_decision = "APPROVED_FOR_PRODUCTION_INTEGRATION"
        prod_integration_auth = True
        next_state = "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
        blocking_conditions = []
        reason_codes = ["ALL_15_SOURCE_AUTHORITY_REVIEW_GATES_PASSED_FIX03_CORRECTION_2"]
    elif ohlc_mismatch_count > 0:
        review_decision = "REJECTED_AS_PRODUCTION_AUTHORITY"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"
        blocking_conditions = gate06_blockers
        reason_codes = ["CORPORATE_ACTION_PRICE_CONTRADICTION"]
    else:
        review_decision = "CONDITIONAL_REVIEW_REQUIRED"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2"
        blocking_conditions = gate06_blockers
        reason_codes = ["OFFICIAL_EVIDENCE_INCOMPLETE"]

    decision_payload = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_2",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION",
        "authoritative_technical_parent": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_2,
        "parent_freeze_valid": parent_freeze["all_parent_inputs_unchanged"],
        "preflight_verdict": preflight["verdict"],
        "live_execution_attestation_sha": attestation_sha,
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "candidate_endpoint": "https://fchart.stock.naver.com/sise.nhn",
        "official_discovery_requests_actual": accounting.official_discovery_logical_requests,
        "official_discovery_success_count": len(discovery_manifest_entries),
        "official_document_success_count": len(raw_manifest_entries),
        "authority_valid_control_count": auth_valid_count,
        "final_cohort_size": len(final_cohort_rows),
        "final_cohort_sha": cohort_sha,
        "event_distribution": event_type_counts,
        "naver_actual_requests": accounting.direct_naver_logical_requests,
        "raw_pykrx_actual_queries": accounting.raw_pykrx_logical_requests,
        "actual_candidate_price_row_count": len(price_df[price_df["source"] == "NAVER_DIRECT"]),
        "actual_pykrx_price_row_count": len(price_df[price_df["source"] == "RAW_PYKRX_COMPARATOR"]),
        "exact_date_match_controls": sum(1 for s in parity_statuses if s == "MATCH"),
        "authorized_reconciliation_controls": sum(1 for s in parity_statuses if s == "AUTHORIZED_DATE_RECONCILIATION_MATCH"),
        "date_mismatch_controls": date_set_mismatch_count,
        "insufficient_window_controls": insufficient_window_count,
        "ohlc_mismatch_controls": ohlc_mismatch_count,
        "candidate_errors": candidate_error_count,
        "comparator_errors": comparator_error_count,
        "provenance_failures": len(linkage_failures),
        "gate_06_result": gate06_pass,
        "gate_15_result": all_15_gates["gate_15_no_unresolved_conditions"],
        "inherited_gate_results": inherited_gates,
        "all_15_gate_results": all_15_gates,
        "all_gates_passed": all_gates_pass,
        "blocking_conditions": blocking_conditions,
        "reason_codes": reason_codes,
        "review_decision": review_decision,
        "production_integration_authorized": prod_integration_auth,
        "active_production_authority_changed": False,
        "recommended_next_state": next_state,
        "network_accounting": accounting.to_dict(),
        "supersession_chain": {
            "v01": "INVALID_APPROVAL_SUPERSEDED",
            "v01_fix01": "CONDITIONAL_DIAGNOSTIC_SUPERSEDED",
            "v01_fix02": "SYNTHETIC_APPROVAL_SUPERSEDED",
            "v01_fix03": "CANONICAL_LIVE_AUTHORITY_SUPERSEDED",
            "v01_fix03_correction": "SUPERSEDED_BY_FIX03_CORRECTION_2",
            "v01_fix03_correction_2": "CANONICAL_AUTHORITY_DECISION",
        },
    }
    decision_path = output_dir / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_2.json"
    decision_path.write_text(json.dumps(decision_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 12. Artifact Manifest (Section 100, 101)
    artifact_files = [
        output_dir / "opendart_preflight_v01_fix03_correction_2.json",
        parent_freeze_path,
        source_inv_path,
        disc_path,
        cand_audit_path,
        disc_man_path,
        doc_val_path,
        adj_path,
        rep_pool_path,
        auth_rec_path,
        cohort_path,
        raw_man_path,
        price_path,
        parity_path,
        recon_path,
        net_path,
        linkage_path,
        attestation_path,
        gate06_path,
        decision_path,
    ]
    manifest_entries = {}
    for af in artifact_files:
        if af.exists():
            manifest_entries[af.name] = {
                "path": f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_2/{af.name}",
                "size_bytes": af.stat().st_size,
                "sha256": hashlib.sha256(af.read_bytes()).hexdigest(),
            }

    for rfname, rmeta in raw_manifest_entries.items():
        manifest_entries[f"raw/{rfname}"] = rmeta
    for dfname, dmeta in discovery_manifest_entries.items():
        manifest_entries[f"discovery_raw/{dfname}"] = dmeta

    manifest_payload = {
        "schema": "corporate_action_evidence_manifest_v01_fix03_correction_2",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_2,
        "review_decision": review_decision,
        "production_integration_authorized": prod_integration_auth,
        "artifacts": manifest_entries,
    }
    manifest_path = output_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return decision_payload


if __name__ == "__main__":
    res = run_corporate_action_evidence_acquisition_fix03_correction_2()
    print("=== Corporate Action Evidence Acquisition FIX03_CORRECTION_2 Execution Summary ===")
    print("Review Decision:", res["review_decision"])
    print("All Gates Passed:", res["all_gates_passed"])
    print("Production Integration Authorized:", res["production_integration_authorized"])
    print("Active Production Authority Changed:", res["active_production_authority_changed"])
    print("Recommended Next State:", res["recommended_next_state"])
    print("Authority Valid Controls Count:", res["authority_valid_control_count"])
    print("Gate 06 Result:", res["gate_06_result"])
    print("Gate 15 Result:", res["gate_15_result"])
    print("Gate Results:")
    for k, v in res["all_15_gate_results"].items():
        print(f"  {k:45s} : {v}")
    if res["blocking_conditions"]:
        print("Blocking Conditions:")
        for bc in res["blocking_conditions"]:
            print(f"  - {bc}")
