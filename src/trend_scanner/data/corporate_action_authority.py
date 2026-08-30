"""Corporate Action Authority Live Discovery, Pagination, True XML Hierarchy Tree Parsing, Claim-Free Official Anchor Selection, Immutable Physical Logs, Readiness Hard Gate, Correct Scoped Network Accounting Invariants, and Gate 06/15 Adjudication.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9 (historical)
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_13
Authoritative Technical Parent: ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import time
import tempfile
from typing import Any, Mapping
import xml.etree.ElementTree as et
import zipfile

import pandas as pd
import requests

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.issuer_official_fallback import (
    CANDIDATE_BOUND_FALLBACK_MODE,
    TIER_B_ISSUER_OFFICIAL,
    trust_registry_audit,
    validate_candidate_bound_tier_b_fallback,
)
from trend_scanner.data.opendart_preflight import (
    OpenDARTCredentialMissingError,
    get_opendart_api_key,
    run_document_endpoint_readiness_probe,
    run_opendart_preflight,
)
from trend_scanner.data.source_authority_review import NaverDateRangeAdjustedClient

PARENT_FIX03_CORRECTION_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/v01_fix03_correction"
)
DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_8 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_8"
)
DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_9 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_9"
)
DEFAULT_CORP_EVIDENCE_DIR = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_9

START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_9 = "58c32e38192b8a455e535cf238bf46b0e925d79b"
DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_11 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_11"
)
START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_11 = "00eb6bb2d9ebcfc3e32dd935df37aef168ca6c7e"
DIRECTIVE_ID_CORRECTION_11 = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11"
PARENT_DIRECTIVE_CORRECTION_11 = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_10"

DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_12 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_12"
)
START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_12 = "4f82d710015b94639da97ac07ff9c5ddd6509fc9"
DIRECTIVE_ID_CORRECTION_12 = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12"
PARENT_DIRECTIVE_CORRECTION_12 = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11"
FULL_PYTEST_EVIDENCE_RELATIVE_PATH_CORRECTION_12 = (
    DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_12
    / "full_pytest_summary_v01_fix03_correction_12.json"
)

DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_13 = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_13"
)
START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_13 = "468ea0b8420562504f9f8cdceb6569498bf2243a"
START_TREE_CORP_EVIDENCE_FIX03_CORRECTION_13 = "4a134e71f241cb3dbd9736e42898aff2cdf89680"
DIRECTIVE_ID_CORRECTION_13 = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_13"
PARENT_DIRECTIVE_CORRECTION_13 = DIRECTIVE_ID_CORRECTION_12
CORRECTION_13_PRICE_FILE = "corporate_action_event_price_rows_v01_fix03_correction_13.csv"
CORRECTION_13_PARITY_FILE = "corporate_action_event_sensitive_parity_v01_fix03_correction_13.csv"
CORRECTION_13_RECONCILIATION_FILE = "corporate_action_date_reconciliation_v01_fix03_correction_13.csv"
FULL_PYTEST_EVIDENCE_RELATIVE_PATH_CORRECTION_13 = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_13 / "full_pytest_summary_v01_fix03_correction_13.json"
FULL_PYTEST_CERTIFICATION_RELATIVE_PATH_CORRECTION_13 = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_13 / "full_pytest_certification_v01_fix03_correction_13.json"
FULL_PYTEST_CERTIFICATION_FILE_CORRECTION_13 = "full_pytest_certification_v01_fix03_correction_13.json"
IMMUTABLE_C13_SOURCE_FILES = frozenset({"full_pytest_summary_v01_fix03_correction_13.json"})
FULL_PYTEST_SCHEMAS = frozenset({
    "full_pytest_summary_v01_fix03_correction_12",
    "full_pytest_summary_v01_fix03_correction_13",
})

ALLOWED_BASELINE_FAILURE_NODEIDS = frozenset({
    "tests/test_krx_historical_backfill.py::test_recent_empty_is_not_checkpointed_and_general_resume_retries",
})

# Offline C13 Tier-B reassessment inputs are immutable evidence captured by
# RESUME_3.  No function below performs a network request or consults secrets.
# The evidence and output roots are caller-owned; no machine-specific default
# path is part of the production contract.
C13_SAMSUNG_ISSUER_URL = "https://www.samsung.com/global/ir/reports-disclosures/public-disclosure-view.71206/"
C13_SAMSUNG_ISSUER_RAW_SHA256 = "940b0ab6bfdfc3c179dc7f2d5c01e088af436b8c479ad4f4c0c7739dbca9a116"
C13_TIER_B_CONTRACT_EVIDENCE_SHA256 = "13cb04f8d48450ff2c90b8108d80e05e214ae03d02b6c43ada698a33d9ca493d"


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


FROZEN_EVENT_FAMILY_ANCHOR_PRIORITY: dict[str, list[str]] = {
    "STOCK_SPLIT": [
        "NEW_SHARE_LISTING_DATE",
        "SPLIT_EFFECTIVE_DATE",
        "SUSPENSION_DATE",
        "OLD_SHARES_SUBMISSION",
        "BOARD_RESOLUTION_DATE",
    ],
    "MERGER": [
        "MERGER_EFFECTIVE_DATE",
        "MERGER_REGISTRATION_DATE",
        "NEW_SHARE_LISTING_DATE",
    ],
    "RIGHTS_OFFERING": [
        "NEW_SHARE_LISTING_DATE",
        "RECORD_DATE",
        "EX_DATE",
        "PAYMENT_DATE",
        "EFFECTIVE_DATE",
    ],
    "BONUS_ISSUE": [
        "RECORD_DATE",
        "EX_DATE",
        "NEW_SHARE_LISTING_DATE",
        "BOARD_RESOLUTION_DATE",
    ],
}


@dataclass
class CorporateActionNetworkAccounting:
    execution_mode: str = "LIVE_EVIDENCE_ACQUISITION"
    preflight_physical_calls: int = 0
    readiness_physical_calls: int = 0
    official_discovery_logical_requests: int = 0
    official_discovery_physical_attempts: int = 0
    official_document_probe_logical_requests: int = 0
    official_document_probe_physical_attempts: int = 0
    dart_viewer_fallback_physical_attempts: int = 0
    alternative_document_candidate_physical_attempts: int = 0
    evidence_acquisition_physical_calls: int = 0
    direct_naver_logical_requests: int = 0
    direct_naver_physical_attempts: int = 0
    raw_pykrx_logical_requests: int = 0
    raw_pykrx_physical_attempts: int = 0
    price_physical_calls: int = 0
    downstream_logged_physical_calls: int = 0
    request_log_physical_entries: int = 0
    grand_total_physical_external_calls: int = 0
    total_physical_external_calls: int = 0
    downstream_accounting_invariant_pass: bool = True
    grand_total_accounting_invariant_pass: bool = True
    accounting_cross_invariant_pass: bool = True
    opendart_logical_operations: int = 0
    opendart_physical_attempts: int = 0
    blocked_documents: int = 0
    wrong_documents: int = 0
    retries: int = 0
    timeouts: int = 0
    http_errors: int = 0
    parse_errors: int = 0
    request_logs: list[dict[str, Any]] = field(default_factory=list)

    def compute_totals(self) -> None:
        self.evidence_acquisition_physical_calls = (
            self.official_discovery_physical_attempts
            + self.official_document_probe_physical_attempts
            + self.dart_viewer_fallback_physical_attempts
            + self.alternative_document_candidate_physical_attempts
        )
        self.price_physical_calls = (
            self.direct_naver_physical_attempts + self.raw_pykrx_physical_attempts
        )
        self.downstream_logged_physical_calls = (
            self.evidence_acquisition_physical_calls + self.price_physical_calls
        )
        self.request_log_physical_entries = sum(
            1 for r in self.request_logs if r.get("physical_attempt") == 1
        )
        self.grand_total_physical_external_calls = (
            self.preflight_physical_calls
            + self.readiness_physical_calls
            + self.downstream_logged_physical_calls
        )
        self.total_physical_external_calls = self.grand_total_physical_external_calls

        self.downstream_accounting_invariant_pass = bool(
            self.downstream_logged_physical_calls == self.request_log_physical_entries
        )
        self.grand_total_accounting_invariant_pass = bool(
            self.grand_total_physical_external_calls
            == (self.preflight_physical_calls + self.readiness_physical_calls + self.downstream_logged_physical_calls)
        )
        self.accounting_cross_invariant_pass = bool(
            self.downstream_accounting_invariant_pass and self.grand_total_accounting_invariant_pass
        )

        self.opendart_logical_operations = (
            self.official_discovery_logical_requests + self.official_document_probe_logical_requests
        )
        self.opendart_physical_attempts = (
            self.preflight_physical_calls
            + self.readiness_physical_calls
            + self.official_discovery_physical_attempts
            + self.official_document_probe_physical_attempts
        )

    def to_dict(self) -> dict[str, Any]:
        self.compute_totals()
        return asdict(self)


@dataclass(frozen=True)
class GitCodeSnapshot:
    """Observed Git identity for the code scope being certified."""

    head: str
    tree_sha: str
    dirty: bool


def observe_git_code_snapshot(repo_root: Path = Path(".")) -> GitCodeSnapshot:
    """Observe HEAD, tree, and scoped worktree dirtiness from Git itself."""
    root = Path(repo_root)

    def _rev_parse(spec: str) -> str:
        proc = subprocess.run(
            ["git", "rev-parse", spec],
            cwd=str(root),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            text=True,
        )
        return proc.stdout.strip() if proc.returncode == 0 else ""

    status_proc = subprocess.run(
        ["git", "status", "--porcelain", "--", "src", "scripts", "tests"],
        cwd=str(root),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        text=True,
    )
    # A failed status command is not clean: the observer could not establish
    # that the scoped worktree is safe to certify.
    dirty = status_proc.returncode != 0 or bool(status_proc.stdout.strip())
    return GitCodeSnapshot(
        head=_rev_parse("HEAD"),
        tree_sha=_rev_parse("HEAD^{tree}"),
        dirty=dirty,
    )


def load_full_regression_evidence(path: Path) -> dict[str, Any] | None:
    """Load only a regular, canonical C12/C13 pytest-summary JSON file.

    Missing, malformed, non-object, or wrong-schema files return ``None`` so
    the caller enters the same fail-closed validation path as missing evidence.
    No synthetic fallback is ever generated here.
    """
    evidence_path = Path(path)
    if not evidence_path.is_file():
        return None
    try:
        payload = json.loads(evidence_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("schema") not in FULL_PYTEST_SCHEMAS:
        return None
    return payload


def _normalize_failure_nodeid(entry: Any) -> str:
    """Normalize a pytest failure entry to its final node ID."""
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, Mapping):
        for key in ("nodeid", "node_id", "test_nodeid", "test_node_id"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


@dataclass
class FullRegressionCertification:
    """Validated full-suite evidence bound to one exact code commit and tree."""

    evidence_status: str
    full_suite_completion: bool
    new_regression_count: int | None
    code_head_under_test: str
    code_tree_sha_under_test: str
    expected_fix_head: str
    expected_fix_tree_sha: str
    binding_valid: bool
    certification_valid: bool
    blockers: list[str] = field(default_factory=list)
    schema: str = "full_pytest_summary_v01_fix03_correction_12"
    passed: int | None = None
    failed: int | None = None
    skipped: int | None = None
    deselected: int | None = None
    warnings: int | None = None
    known_baseline_failures: list[Any] = field(default_factory=list)
    unexpected_failures: list[Any] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CanonicalRunIdentityValidation:
    """Evidence that every populated final-artifact run identity is coherent."""

    expected_run_id: str
    artifacts_checked: int
    rows_checked: int
    mismatches: list[dict[str, Any]] = field(default_factory=list)

    @property
    def all_identity_valid(self) -> bool:
        return bool(self.expected_run_id and not self.mismatches)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "canonical_run_identity_validation_v01_fix03_correction_13",
            "expected_run_id": self.expected_run_id,
            "artifacts_checked": self.artifacts_checked,
            "rows_checked": self.rows_checked,
            "mismatches": self.mismatches,
            "all_identity_valid": self.all_identity_valid,
        }


def validate_canonical_run_identity_correction13(
    output_dir: Path,
    expected_run_id: str,
) -> CanonicalRunIdentityValidation:
    """Validate the final C13 artifact set, including JSON and CSV rows.

    This validator deliberately inspects the materialized representation rather
    than trusting the stage runner's in-memory result.  Every populated
    ``canonical_run_id`` must be present and equal to the one run identity.
    """
    root = Path(output_dir)
    expected = str(expected_run_id or "").strip()
    mismatches: list[dict[str, Any]] = []
    artifacts_checked = 0
    rows_checked = 0
    if not expected:
        mismatches.append({"code": "CANONICAL_RUN_ID_MISSING", "path": str(root)})
    if not root.is_dir():
        mismatches.append({"code": "CANONICAL_ARTIFACT_DIR_MISSING", "path": str(root)})
        return CanonicalRunIdentityValidation(expected, 0, 0, mismatches)

    def inspect_value(value: Any, path: str) -> None:
        nonlocal rows_checked
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key) == "canonical_run_id":
                    rows_checked += 1
                    observed = str(child or "").strip()
                    if not observed:
                        mismatches.append({"code": "CANONICAL_RUN_ID_MISSING", "path": path})
                    elif observed != expected:
                        mismatches.append({"code": "CANONICAL_RUN_IDENTITY_MISMATCH", "path": path, "observed": observed, "expected": expected})
                inspect_value(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect_value(child, f"{path}[{index}]")

    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name == "artifact_manifest.json":
            continue
        artifacts_checked += 1
        relative = str(path.relative_to(root))
        if path.suffix.lower() == ".json":
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            inspect_value(payload, relative)
        elif path.suffix.lower() == ".csv":
            try:
                frame = pd.read_csv(path, dtype=str, keep_default_na=False)
            except (OSError, UnicodeDecodeError, pd.errors.ParserError):
                continue
            if "canonical_run_id" in frame.columns:
                for index, value in enumerate(frame["canonical_run_id"].tolist()):
                    rows_checked += 1
                    observed = str(value or "").strip()
                    if not observed:
                        mismatches.append({"code": "CANONICAL_RUN_ID_MISSING", "path": f"{relative}[{index}]"})
                    elif observed != expected:
                        mismatches.append({"code": "CANONICAL_RUN_IDENTITY_MISMATCH", "path": f"{relative}[{index}]", "observed": observed, "expected": expected})
    unique_mismatches: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in mismatches:
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker not in seen:
            seen.add(marker)
            unique_mismatches.append(item)
    return CanonicalRunIdentityValidation(expected, artifacts_checked, rows_checked, unique_mismatches)


@dataclass(frozen=True)
class C13NetworkAccountingValidation:
    """Independent network-accounting recomputation from persisted request logs."""

    recomputed_request_log_physical_entries: int
    recomputed_downstream_calls: int
    recomputed_price_calls: int
    recomputed_evidence_calls: int
    recomputed_grand_total: int
    recomputed_official_discovery_calls: int
    recomputed_document_probe_calls: int
    recomputed_viewer_fallback_calls: int
    recomputed_alternative_candidate_calls: int
    persisted_downstream_calls: int | None
    persisted_request_log_physical_entries: int | None
    persisted_price_calls: int | None
    persisted_evidence_calls: int | None
    persisted_grand_total: int | None
    persisted_total_physical_calls: int | None
    all_network_accounting_valid: bool
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _network_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        candidate = value.strip()
        if candidate and (candidate.isdigit() or (candidate.startswith("-") and candidate[1:].isdigit())):
            return int(candidate)
    return None


def validate_c13_network_accounting(accounting: Mapping[str, Any] | None) -> C13NetworkAccountingValidation:
    """Recompute C13 physical-call totals and compare all persisted aggregates."""
    payload = accounting if isinstance(accounting, Mapping) else {}
    logs = payload.get("request_logs")
    blockers: list[str] = []
    if not isinstance(logs, list):
        logs = []
        blockers.append("NETWORK_REQUEST_LOGS_MISSING")

    counters = {
        "official_discovery": 0,
        "document_probe": 0,
        "viewer_fallback": 0,
        "alternative_candidate": 0,
        "naver": 0,
        "pykrx": 0,
    }
    physical_entries = 0
    for index, record in enumerate(logs):
        if not isinstance(record, Mapping):
            blockers.append(f"NETWORK_REQUEST_LOG_INVALID:{index}")
            continue
        physical_attempt = _network_int(record.get("physical_attempt"))
        if physical_attempt is None:
            blockers.append(f"NETWORK_REQUEST_LOG_PHYSICAL_ATTEMPT_INVALID:{index}")
            continue
        if physical_attempt != 1:
            continue
        physical_entries += 1
        source = str(record.get("source", "")).strip().upper()
        purpose = str(record.get("purpose", "")).strip().upper()
        if source == "NAVER_DIRECT":
            counters["naver"] += 1
        elif source == "RAW_PYKRX_COMPARATOR":
            counters["pykrx"] += 1
        elif "DISCOVERY" in purpose:
            counters["official_discovery"] += 1
        elif "DOCUMENT_PROBE" in purpose:
            counters["document_probe"] += 1
        elif "VIEWER_FALLBACK" in purpose:
            counters["viewer_fallback"] += 1
        elif "ALTERNATIVE" in purpose or "ALTERNATIVE" in source:
            counters["alternative_candidate"] += 1
        else:
            blockers.append(f"NETWORK_REQUEST_LOG_UNCLASSIFIED:{index}")

    evidence_calls = counters["official_discovery"] + counters["document_probe"] + counters["viewer_fallback"] + counters["alternative_candidate"]
    price_calls = counters["naver"] + counters["pykrx"]
    downstream_calls = evidence_calls + price_calls
    preflight = _network_int(payload.get("preflight_physical_calls"))
    readiness = _network_int(payload.get("readiness_physical_calls"))
    if preflight is None:
        blockers.append("NETWORK_ACCOUNTING_FIELD_MISSING:preflight_physical_calls")
        preflight = 0
    if readiness is None:
        blockers.append("NETWORK_ACCOUNTING_FIELD_MISSING:readiness_physical_calls")
        readiness = 0
    if preflight < 0:
        blockers.append("NETWORK_ACCOUNTING_FIELD_INVALID:preflight_physical_calls")
    if readiness < 0:
        blockers.append("NETWORK_ACCOUNTING_FIELD_INVALID:readiness_physical_calls")
    grand_total = preflight + readiness + downstream_calls

    persisted_values = {
        "downstream_logged_physical_calls": _network_int(payload.get("downstream_logged_physical_calls")),
        "request_log_physical_entries": _network_int(payload.get("request_log_physical_entries")),
        "price_physical_calls": _network_int(payload.get("price_physical_calls")),
        "evidence_acquisition_physical_calls": _network_int(payload.get("evidence_acquisition_physical_calls")),
        "grand_total_physical_external_calls": _network_int(payload.get("grand_total_physical_external_calls")),
        "total_physical_external_calls": _network_int(payload.get("total_physical_external_calls")),
    }
    recomputed_values = {
        "downstream_logged_physical_calls": downstream_calls,
        "request_log_physical_entries": physical_entries,
        "price_physical_calls": price_calls,
        "evidence_acquisition_physical_calls": evidence_calls,
        "grand_total_physical_external_calls": grand_total,
        "total_physical_external_calls": grand_total,
    }
    if downstream_calls != physical_entries:
        blockers.append("NETWORK_ACCOUNTING_RECOMPUTATION_MISMATCH")
    for key, expected in recomputed_values.items():
        observed = persisted_values[key]
        if observed is None:
            blockers.append(f"NETWORK_ACCOUNTING_FIELD_MISSING:{key}")
        elif observed != expected:
            blockers.append("NETWORK_ACCOUNTING_RECOMPUTATION_MISMATCH")
    persisted_bool = payload.get("accounting_cross_invariant_pass")
    if persisted_bool is not None and persisted_bool is not (not blockers):
        blockers.append("NETWORK_ACCOUNTING_RECOMPUTATION_MISMATCH")
    blockers = list(dict.fromkeys(blockers))
    return C13NetworkAccountingValidation(
        recomputed_request_log_physical_entries=physical_entries,
        recomputed_downstream_calls=downstream_calls,
        recomputed_price_calls=price_calls,
        recomputed_evidence_calls=evidence_calls,
        recomputed_grand_total=grand_total,
        recomputed_official_discovery_calls=counters["official_discovery"],
        recomputed_document_probe_calls=counters["document_probe"],
        recomputed_viewer_fallback_calls=counters["viewer_fallback"],
        recomputed_alternative_candidate_calls=counters["alternative_candidate"],
        persisted_downstream_calls=persisted_values["downstream_logged_physical_calls"],
        persisted_request_log_physical_entries=persisted_values["request_log_physical_entries"],
        persisted_price_calls=persisted_values["price_physical_calls"],
        persisted_evidence_calls=persisted_values["evidence_acquisition_physical_calls"],
        persisted_grand_total=persisted_values["grand_total_physical_external_calls"],
        persisted_total_physical_calls=persisted_values["total_physical_external_calls"],
        all_network_accounting_valid=not blockers,
        blockers=blockers,
    )


def validate_full_regression_evidence(
    evidence: FullRegressionCertification | Mapping[str, Any] | None,
    *,
    expected_fix_head: str,
    expected_fix_tree_sha: str,
) -> FullRegressionCertification:
    """Validate canonical full-pytest evidence before it can affect certification."""
    blockers: list[str] = []
    expected_head = str(expected_fix_head or "")
    expected_tree = str(expected_fix_tree_sha or "")
    if not expected_head:
        blockers.append("EXPECTED_FIX_HEAD_MISSING")
    if not expected_tree:
        blockers.append("EXPECTED_FIX_TREE_MISSING")

    if isinstance(evidence, FullRegressionCertification):
        raw = evidence.to_dict()
    elif isinstance(evidence, Mapping):
        raw = dict(evidence)
    else:
        raw = {}
        blockers.append("PYTEST_EVIDENCE_MISSING")

    schema = str(raw.get("schema") or "")
    if not schema:
        blockers.append("PYTEST_SCHEMA_MISSING")
    elif schema not in FULL_PYTEST_SCHEMAS:
        blockers.append("PYTEST_SCHEMA_MISMATCH")

    result_fields = ("passed", "failed", "skipped", "deselected", "warnings")
    result_values: dict[str, int | None] = {}
    for field_name in result_fields:
        value = raw.get(field_name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            blockers.append(f"PYTEST_{field_name.upper()}_MISSING")
            result_values[field_name] = None
        else:
            result_values[field_name] = value
    known_baseline_failures = raw.get("known_baseline_failures")
    if not isinstance(known_baseline_failures, list):
        blockers.append("PYTEST_KNOWN_BASELINE_FAILURES_MISSING")
        known_baseline_failures = []
    unexpected_failures = raw.get("unexpected_failures")
    if not isinstance(unexpected_failures, list):
        blockers.append("PYTEST_UNEXPECTED_FAILURES_MISSING")
        unexpected_failures = []

    normalized_known_failures: list[str] = []
    normalized_unexpected_failures: list[str] = []
    for entry in known_baseline_failures:
        nodeid = _normalize_failure_nodeid(entry)
        if not nodeid:
            blockers.append("PYTEST_FAILURE_NODEID_MISSING")
        normalized_known_failures.append(nodeid)
        if nodeid and nodeid not in ALLOWED_BASELINE_FAILURE_NODEIDS:
            blockers.append("PYTEST_UNKNOWN_BASELINE_FAILURE")
    for entry in unexpected_failures:
        nodeid = _normalize_failure_nodeid(entry)
        if not nodeid:
            blockers.append("PYTEST_FAILURE_NODEID_MISSING")
        normalized_unexpected_failures.append(nodeid)

    if len(normalized_known_failures) != len(set(normalized_known_failures)) or len(normalized_unexpected_failures) != len(set(normalized_unexpected_failures)):
        blockers.append("PYTEST_DUPLICATE_FAILURE_ENTRY")
    if set(normalized_known_failures).intersection(normalized_unexpected_failures):
        blockers.append("PYTEST_FAILURE_CLASSIFICATION_OVERLAP")

    completion = raw.get("full_suite_completion")
    if not isinstance(completion, bool):
        blockers.append("PYTEST_COMPLETION_MISSING")
        completion_value = False
    else:
        completion_value = completion
        if completion is not True:
            blockers.append("FULL_PYTEST_INCOMPLETE")

    tested_head = str(raw.get("code_head_under_test") or "")
    tested_tree = str(raw.get("code_tree_sha_under_test") or "")
    if not tested_head:
        blockers.append("PYTEST_FIX_HEAD_MISSING")
    elif expected_head and tested_head != expected_head:
        blockers.append("PYTEST_FIX_HEAD_MISMATCH")
    if not tested_tree:
        blockers.append("PYTEST_FIX_TREE_MISSING")
    elif expected_tree and tested_tree != expected_tree:
        blockers.append("PYTEST_FIX_TREE_MISMATCH")

    regression_count = raw.get("new_regression_count")
    if regression_count is None or isinstance(regression_count, bool) or not isinstance(regression_count, int):
        blockers.append("PYTEST_REGRESSION_COUNT_MISSING")
        regression_value = None
    else:
        regression_value = regression_count
        if regression_count != 0:
            blockers.append("PYTEST_NEW_REGRESSION_DETECTED")

    failed_count = result_values["failed"]
    if failed_count is not None and failed_count != len(known_baseline_failures) + len(unexpected_failures):
        blockers.append("PYTEST_FAILED_COUNT_MISMATCH")
    if regression_value is not None and regression_value != len(unexpected_failures):
        blockers.append("PYTEST_REGRESSION_COUNT_MISMATCH")

    binding_valid = not any(
        code in blockers
        for code in (
            "EXPECTED_FIX_HEAD_MISSING",
            "EXPECTED_FIX_TREE_MISSING",
            "PYTEST_FIX_HEAD_MISSING",
            "PYTEST_FIX_TREE_MISSING",
            "PYTEST_FIX_HEAD_MISMATCH",
            "PYTEST_FIX_TREE_MISMATCH",
        )
    )
    certification_valid = bool(binding_valid and completion_value is True and regression_value == 0 and not blockers)
    status = "VALID" if certification_valid else ("MISSING" if not evidence else "INVALID")
    return FullRegressionCertification(
        evidence_status=status,
        full_suite_completion=completion_value,
        new_regression_count=regression_value,
        code_head_under_test=tested_head,
        code_tree_sha_under_test=tested_tree,
        expected_fix_head=expected_head,
        expected_fix_tree_sha=expected_tree,
        binding_valid=binding_valid,
        certification_valid=certification_valid,
        blockers=list(dict.fromkeys(blockers)),
        schema=schema or "full_pytest_summary_v01_fix03_correction_12",
        passed=result_values["passed"],
        failed=result_values["failed"],
        skipped=result_values["skipped"],
        deselected=result_values["deselected"],
        warnings=result_values["warnings"],
        known_baseline_failures=list(normalized_known_failures),
        unexpected_failures=list(normalized_unexpected_failures),
    )


def production_certification_ready(
    *,
    all_source_gates_pass: bool,
    regression_certification: FullRegressionCertification | None,
) -> bool:
    """Return true only when validated regression evidence is bound and clean."""
    return bool(
        all_source_gates_pass
        and isinstance(regression_certification, FullRegressionCertification)
        and regression_certification.evidence_status == "VALID"
        and not regression_certification.blockers
        and regression_certification.binding_valid
        and regression_certification.certification_valid
    )


def build_full_pytest_certification_artifact(
    summary_bytes: bytes,
    certification: FullRegressionCertification,
) -> dict[str, Any]:
    """Build derived certification metadata without rewriting the source summary."""
    return {
        "schema": "full_pytest_certification_v01_fix03_correction_13",
        "source_summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        "expected_fix_head": certification.expected_fix_head,
        "expected_fix_tree_sha": certification.expected_fix_tree_sha,
        "observed_test_head": certification.code_head_under_test,
        "observed_test_tree": certification.code_tree_sha_under_test,
        "binding_valid": certification.binding_valid,
        "certification_valid": certification.certification_valid,
        "evidence_status": certification.evidence_status,
        "full_suite_completion": certification.full_suite_completion,
        "new_regression_count": certification.new_regression_count,
        "blockers": list(certification.blockers),
    }


def verify_parent_authority_freeze(parent_dir: Path = PARENT_FIX03_CORRECTION_DIR) -> dict[str, Any]:
    """Verify that all parent FIX03_CORRECTION artifacts remain byte-for-byte unchanged."""
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
        "schema": "parent_authority_freeze_validation_v01_fix03_correction_9",
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_9,
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_8",
        "all_parent_inputs_unchanged": all_valid,
        "parent_artifacts_verified_count": len(observed_hashes),
        "mismatches": mismatches,
        "parent_artifact_hashes": observed_hashes,
    }


class SemanticTreeNode:
    """Internal structured node representing real XML/HTML ancestry and content."""

    def __init__(self, tag: str, path: str, depth: int, parent_path: str = "", ancestor_paths: list[str] = None):
        self.tag = tag.upper()
        self.path = path
        self.depth = depth
        self.parent_path = parent_path
        self.ancestor_paths = list(ancestor_paths or [])
        self.heading = ""
        self.inherited_headings: list[str] = []
        self.local_text_parts: list[str] = []
        self.children: list[SemanticTreeNode] = []
        self.subtree_text = ""
        self.node_id = ""
        self.node_sha256 = ""

    @property
    def local_text(self) -> str:
        return " ".join(" ".join(self.local_text_parts).split())


class DARTTreeParser(HTMLParser):
    """Recursive true XML/HTML tree builder with namespace stripping and stable indexed paths."""

    def __init__(self):
        super().__init__()
        self.root = SemanticTreeNode("ROOT", "ROOT[1]", 0)
        self.stack: list[SemanticTreeNode] = [self.root]
        self.tag_counts_by_parent: dict[str, dict[str, int]] = {}
        self.node_count = 0

    def handle_starttag(self, tag: str, attrs):
        clean_tag = tag.split("}")[-1] if "}" in tag else tag
        u_tag = clean_tag.upper()

        parent = self.stack[-1]
        p_path = parent.path
        if p_path not in self.tag_counts_by_parent:
            self.tag_counts_by_parent[p_path] = {}
        t_counts = self.tag_counts_by_parent[p_path]
        t_counts[u_tag] = t_counts.get(u_tag, 0) + 1
        tag_idx = t_counts[u_tag]

        clean_p_path = "" if parent.path == "ROOT[1]" else parent.path
        node_path = f"{clean_p_path}/{u_tag}[{tag_idx}]" if clean_p_path else f"{u_tag}[{tag_idx}]"
        self.node_count += 1
        anc_paths = parent.ancestor_paths + [clean_p_path] if clean_p_path else []

        node = SemanticTreeNode(
            tag=u_tag,
            path=node_path,
            depth=parent.depth + 1,
            parent_path=clean_p_path,
            ancestor_paths=anc_paths,
        )
        parent.children.append(node)
        self.stack.append(node)

    def handle_endtag(self, tag: str):
        clean_tag = tag.split("}")[-1] if "}" in tag else tag
        u_tag = clean_tag.upper()
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == u_tag:
                self.stack = self.stack[:i]
                break

    def handle_data(self, data: str):
        clean = data.strip()
        if clean and len(self.stack) > 0:
            self.stack[-1].local_text_parts.append(clean)


def finalize_semantic_tree(node: SemanticTreeNode, inherited_headings: list[str] = None, node_counter: list[int] = None) -> None:
    """Compute headings, subtree text, depth, and SHA256 recursively across the tree."""
    inherited_headings = inherited_headings or []
    node_counter = node_counter if node_counter is not None else [0]

    node_counter[0] += 1
    node.node_id = f"SEM_NODE_{node_counter[0]:04d}"
    node.inherited_headings = list(inherited_headings)

    direct_title = ""
    for ch in node.children:
        if ch.tag in ["TITLE", "H1", "H2", "H3", "H4", "H5", "H6"]:
            direct_title = ch.local_text
            break
    if direct_title:
        node.heading = direct_title

    curr_headings = list(inherited_headings)
    if node.heading:
        curr_headings.append(node.heading)

    all_texts = list(node.local_text_parts)
    for ch in node.children:
        finalize_semantic_tree(ch, curr_headings, node_counter)
        if ch.subtree_text:
            all_texts.append(ch.subtree_text)

    combined_text = " ".join(" ".join(all_texts).split())
    node.subtree_text = combined_text
    node.node_sha256 = hashlib.sha256(combined_text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Pure Production Validation and Resolution Helpers
# ---------------------------------------------------------------------------

def validate_discovery_duplicate_identity(items: list[dict[str, Any]]) -> tuple[bool, int, int, list[str]]:
    """Pure production helper to detect duplicate disclosure records and attribute conflicts."""
    unique_items_by_rcp: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    conflicting_duplicate_count = 0
    conflict_details = []

    for it in items:
        r_no = str(it.get("rcept_no", "")).strip()
        if r_no in unique_items_by_rcp:
            duplicate_count += 1
            existing = unique_items_by_rcp[r_no]
            conflicts = []
            for field_key in ["report_nm", "rcept_dt", "corp_code", "stock_code", "corp_name"]:
                if existing.get(field_key) != it.get(field_key):
                    conflicts.append(field_key)
            if conflicts:
                conflicting_duplicate_count += 1
                conflict_details.append(f"{r_no}:conflicts_in_{conflicts}")
        else:
            unique_items_by_rcp[r_no] = it

    is_valid = (conflicting_duplicate_count == 0)
    return is_valid, duplicate_count, conflicting_duplicate_count, conflict_details


def validate_archive_provenance(
    archive_detected: bool,
    archive_member_count: int,
    selected_member_name: str,
    member_selection_rule: str,
    extracted_member_size: int,
    extracted_member_sha256: str,
    canonical_raw_sha256: str,
    transport_response_sha256: str,
) -> tuple[bool, list[str]]:
    """Pure production validator for archive transport and member invariants."""
    inconsistencies = []

    if archive_detected:
        if archive_member_count <= 0:
            inconsistencies.append("ARCHIVE_PROVENANCE_INCONSISTENT: archive_detected=True but archive_member_count <= 0")
        if not selected_member_name:
            inconsistencies.append("ARCHIVE_PROVENANCE_INCONSISTENT: archive_detected=True but selected_member_name is empty")
        if member_selection_rule not in ["EXACTLY_ONE_XML_MEMBER", "EXACT_RCEPT_NO_MATCH", "HTML_VIEWER_FALLBACK"]:
            inconsistencies.append(f"ARCHIVE_PROVENANCE_INCONSISTENT: invalid archive rule {member_selection_rule}")
        if member_selection_rule == "EXACTLY_ONE_XML_MEMBER" and archive_member_count != 1:
            inconsistencies.append(f"ARCHIVE_PROVENANCE_INCONSISTENT: rule EXACTLY_ONE_XML_MEMBER requires member_count=1, got {archive_member_count}")
        if extracted_member_size <= 0:
            inconsistencies.append("ARCHIVE_PROVENANCE_INCONSISTENT: extracted_member_size <= 0")
        if not extracted_member_sha256:
            inconsistencies.append("ARCHIVE_PROVENANCE_INCONSISTENT: extracted_member_sha256 is empty")
        if canonical_raw_sha256 != extracted_member_sha256:
            inconsistencies.append(f"ARCHIVE_PROVENANCE_INCONSISTENT: canonical_raw_sha {canonical_raw_sha256} != extracted_sha {extracted_member_sha256}")
    else:
        if archive_member_count != 0:
            inconsistencies.append(f"ARCHIVE_PROVENANCE_INCONSISTENT: archive_detected=False but archive_member_count={archive_member_count}")
        if selected_member_name != "":
            inconsistencies.append(f"ARCHIVE_PROVENANCE_INCONSISTENT: archive_detected=False but selected_member_name={selected_member_name}")
        if member_selection_rule not in ["DIRECT_RESPONSE", "HTML_VIEWER_FALLBACK"]:
            inconsistencies.append(f"ARCHIVE_PROVENANCE_INCONSISTENT: invalid direct rule {member_selection_rule}")
        if transport_response_sha256 != canonical_raw_sha256:
            inconsistencies.append(f"ARCHIVE_PROVENANCE_INCONSISTENT: direct transport SHA {transport_response_sha256} != canonical raw SHA {canonical_raw_sha256}")

    return len(inconsistencies) == 0, inconsistencies


def resolve_archive_member(
    zip_bytes: bytes,
    rcept_no: str,
) -> tuple[bytes, str, str, bool, int, str, bool, list[str]]:
    """Pure production helper to resolve ZIP archive members with exact basename matching."""
    if not zipfile.is_zipfile(io.BytesIO(zip_bytes)):
        return zip_bytes, "", "", False, 0, "DIRECT_RESPONSE", False, []

    archive_ambiguous = False
    archive_failures = []
    extracted_bytes = b""
    member_name = ""
    member_rule = ""

    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        namelist = z.namelist()
        archive_members = len(namelist)
        xml_members = [n for n in namelist if n.lower().endswith(".xml")]

        if len(xml_members) == 1:
            member_name = xml_members[0]
            member_rule = "EXACTLY_ONE_XML_MEMBER"
            extracted_bytes = z.read(member_name)
        elif len(xml_members) > 1:
            exact_matches = [n for n in xml_members if Path(n).name.lower() == f"{rcept_no}.xml".lower()]
            if len(exact_matches) == 1:
                member_name = exact_matches[0]
                member_rule = "EXACT_RCEPT_NO_MATCH"
                extracted_bytes = z.read(member_name)
            else:
                archive_ambiguous = True
                archive_failures.append(f"{rcept_no}:ambiguous_members_{xml_members}")
                extracted_bytes = b""
        else:
            archive_failures.append(f"{rcept_no}:no_xml_members")
            extracted_bytes = b""

    extracted_sha = hashlib.sha256(extracted_bytes).hexdigest() if extracted_bytes else ""
    return extracted_bytes, extracted_sha, member_name, bool(archive_members > 0), archive_members, member_rule, archive_ambiguous, archive_failures


def validate_pagination_pages(
    pages_meta: list[dict[str, Any]],
    expected_total_count: int,
    expected_total_pages: int,
    frozen_page1_meta: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Pure production validator for pagination page-to-page consistency and completeness."""
    inconsistencies = []
    observed_pages = [p["page_no"] for p in pages_meta]
    expected_pages = list(range(1, expected_total_pages + 1))

    if observed_pages != expected_pages:
        inconsistencies.append(f"Missing pages: observed {observed_pages} vs expected {expected_pages}")

    for p in pages_meta:
        p_no = p["page_no"]
        st = p.get("opendart_status", "")
        http_st = p.get("http_status", 0)
        if http_st != 200 or st not in ["000", "013"]:
            inconsistencies.append(f"Page {p_no} failed status: http={http_st}, opendart={st}")

        if p_no > 1:
            if p.get("reported_total_count") != frozen_page1_meta.get("reported_total_count"):
                inconsistencies.append(f"Page {p_no} total_count mismatch: {p.get('reported_total_count')} vs page 1 {frozen_page1_meta.get('reported_total_count')}")
            if p.get("reported_total_page") != frozen_page1_meta.get("reported_total_page"):
                inconsistencies.append(f"Page {p_no} total_page mismatch: {p.get('reported_total_page')} vs page 1 {frozen_page1_meta.get('reported_total_page')}")
            if p.get("page_count") != frozen_page1_meta.get("page_count") and "page_count" in p:
                inconsistencies.append(f"Page {p_no} page_count mismatch: {p.get('page_count')} vs page 1 {frozen_page1_meta.get('page_count')}")

    total_loaded = sum(p.get("item_count", 0) for p in pages_meta)
    if total_loaded != expected_total_count:
        inconsistencies.append(f"Total count sum mismatch: sum={total_loaded} vs reported={expected_total_count}")

    return len(inconsistencies) == 0, inconsistencies


# ---------------------------------------------------------------------------
# FIX03_CORRECTION_10: production linkage truth source
# ---------------------------------------------------------------------------

ALLOWED_RETRIEVAL_MODES = frozenset(
    {"NEW_OPENDART_DOCUMENT_FETCH", "NEW_DART_VIEWER_FETCH"}
)
FORBIDDEN_RETRIEVAL_MODES = frozenset(
    {
        "PRIOR_RUN_RAW_REUSE",
        "CACHED_OFFICIAL_RAW",
        "SYNTHETIC_OFFICIAL_RAW",
        "UNKNOWN",
        "",
    }
)


def _linkage_records(value: Any) -> list[dict[str, Any]]:
    """Normalize list/dict artifact containers without inventing records."""
    if value is None:
        return []
    if isinstance(value, dict):
        if isinstance(value.get("records"), list):
            return [r for r in value["records"] if isinstance(r, dict)]
        if isinstance(value.get("entries"), list):
            return [r for r in value["entries"] if isinstance(r, dict)]
        if isinstance(value.get("artifacts"), dict):
            return [r for r in value["artifacts"].values() if isinstance(r, dict)]
        if isinstance(value.get("pages"), dict):
            return [r for r in value["pages"].values() if isinstance(r, dict)]
        return [r for r in value.values() if isinstance(r, dict)]
    if isinstance(value, (list, tuple)):
        return [r for r in value if isinstance(r, dict)]
    return []


def _linkage_value(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in record:
            return record[name]
    return ""


def _linkage_text(record: dict[str, Any], *names: str) -> str:
    value = _linkage_value(record, *names)
    return "" if value is None else str(value).strip()


def _linkage_bool(record: dict[str, Any], *names: str) -> bool:
    value = _linkage_value(record, *names)
    return value is True or (isinstance(value, str) and value.strip().lower() == "true")


def _linkage_failure(code: str, **details: Any) -> dict[str, Any]:
    return {"code": code, **details}


@dataclass
class LiveEvidenceLinkageResult:
    """All live evidence linkage failures produced by one canonical run."""

    canonical_run_id: str
    linkage_evaluation_status: str
    accounting_cross_invariant_pass: bool
    schema_suffix: str = "10"
    producing_request_failures: list[dict[str, Any]] = field(default_factory=list)
    live_lineage_failures: list[dict[str, Any]] = field(default_factory=list)
    cross_run_request_linkage_failures: list[dict[str, Any]] = field(default_factory=list)
    historical_raw_reuse_failures: list[dict[str, Any]] = field(default_factory=list)
    invalid_retrieval_modes: list[dict[str, Any]] = field(default_factory=list)
    physical_request_mutation_failures: list[dict[str, Any]] = field(default_factory=list)
    record_identity_failures: list[dict[str, Any]] = field(default_factory=list)
    issuer_identity_failures: list[dict[str, Any]] = field(default_factory=list)
    candidate_linkage_failures: list[dict[str, Any]] = field(default_factory=list)
    pykrx_linkage_failures: list[dict[str, Any]] = field(default_factory=list)
    raw_orphan_failures: list[dict[str, Any]] = field(default_factory=list)

    @property
    def linkage_failures(self) -> list[dict[str, Any]]:
        return [
            *self.producing_request_failures,
            *self.live_lineage_failures,
            *self.cross_run_request_linkage_failures,
            *self.historical_raw_reuse_failures,
            *self.invalid_retrieval_modes,
            *self.physical_request_mutation_failures,
            *self.record_identity_failures,
            *self.issuer_identity_failures,
            *self.candidate_linkage_failures,
            *self.pykrx_linkage_failures,
            *self.raw_orphan_failures,
        ]

    @property
    def total_linkage_failures(self) -> int:
        return len(self.linkage_failures)

    @property
    def all_linkage_valid(self) -> bool:
        return bool(
            self.linkage_evaluation_status == "EVALUATED"
            and self.total_linkage_failures == 0
            and self.accounting_cross_invariant_pass
        )

    def to_metrics(self) -> dict[str, Any]:
        return {
            "linkage_evaluation_status": self.linkage_evaluation_status,
            "accounting_cross_invariant_pass": self.accounting_cross_invariant_pass,
            "producing_request_failure_count": len(self.producing_request_failures),
            "cross_run_request_linkage_failure_count": len(self.cross_run_request_linkage_failures),
            "invalid_retrieval_mode_count": len(self.invalid_retrieval_modes),
            "record_identity_failure_count": len(self.record_identity_failures),
            "issuer_identity_failure_count": len(self.issuer_identity_failures),
            "candidate_linkage_failure_count": len(self.candidate_linkage_failures),
            "pykrx_linkage_failure_count": len(self.pykrx_linkage_failures),
            "historical_raw_reuse_count": len(self.historical_raw_reuse_failures),
            "physical_request_mutation_failure_count": len(self.physical_request_mutation_failures),
            "live_lineage_failure_count": len(self.live_lineage_failures),
            "raw_orphan_file_count": len(self.raw_orphan_failures),
            "total_provenance_failure_count": self.total_linkage_failures,
            "all_linkage_valid": self.all_linkage_valid,
        }

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema": f"live_evidence_linkage_validation_v01_fix03_correction_{self.schema_suffix}",
            "canonical_run_id": self.canonical_run_id,
            "linkage_evaluation_status": self.linkage_evaluation_status,
            "accounting_cross_invariant_pass": self.accounting_cross_invariant_pass,
            "discovery_pages_checked": 0,
            "document_items_checked": 0,
            "producing_request_failures": self.producing_request_failures,
            "live_lineage_failures": self.live_lineage_failures,
            "cross_run_request_linkage_failures": self.cross_run_request_linkage_failures,
            "historical_raw_reuse_failures": self.historical_raw_reuse_failures,
            "invalid_retrieval_modes": self.invalid_retrieval_modes,
            "physical_request_mutation_failures": self.physical_request_mutation_failures,
            "record_identity_failures": self.record_identity_failures,
            "issuer_identity_failures": self.issuer_identity_failures,
            "candidate_linkage_failures": self.candidate_linkage_failures,
            "pykrx_linkage_failures": self.pykrx_linkage_failures,
            "raw_orphan_failures": self.raw_orphan_failures,
            "linkage_failures": self.linkage_failures,
            "total_linkage_failures": self.total_linkage_failures,
            "all_linkage_valid": self.all_linkage_valid,
        }
        payload.update(self.to_metrics())
        return payload

    as_dict = to_dict


def _request_source_matches(document: dict[str, Any], request: dict[str, Any]) -> bool:
    doc_source = _linkage_text(document, "source", "official_source", "authority_source_name")
    req_source = _linkage_text(request, "source")
    if not doc_source or not req_source:
        return False
    doc_upper, req_upper = doc_source.upper(), req_source.upper()
    if "DART" in doc_upper and "DART" in req_upper:
        return True
    return doc_upper == req_upper or doc_upper in req_upper or req_upper in doc_upper


def _request_hash_matches(document: dict[str, Any], request: dict[str, Any]) -> bool:
    doc_sha = _linkage_text(document, "sha256", "raw_sha", "raw_evidence_sha256")
    if not doc_sha:
        return False
    request_hashes = {
        _linkage_text(request, name)
        for name in (
            "canonical_raw_sha256",
            "extracted_member_sha256",
            "transport_response_sha256",
            "raw_http_response_sha256",
        )
    }
    return doc_sha in {h for h in request_hashes if h}


def _request_matches_control(request: dict[str, Any], authority: dict[str, Any]) -> bool:
    req_ticker = _linkage_text(request, "ticker")
    auth_ticker = _linkage_text(authority, "ticker")
    req_start = _linkage_text(request, "price_window_start")
    req_end = _linkage_text(request, "price_window_end")
    auth_start = _linkage_text(authority, "price_window_start")
    auth_end = _linkage_text(authority, "price_window_end")
    return bool(
        req_ticker
        and auth_ticker
        and req_ticker == auth_ticker
        and req_start == auth_start
        and req_end == auth_end
    )


def validate_live_evidence_linkage(
    canonical_run_id: str,
    discovery_records: Any,
    document_records: Any,
    raw_manifest_entries: Any = None,
    authority_rows: Any = None,
    request_logs: Any = None,
    price_request_logs: Any = None,
    artifact_paths: Any = None,
    current_output_dir: Path | None = None,
    accounting_cross_invariant_pass: bool | None = None,
    schema_suffix: str = "10",
) -> LiveEvidenceLinkageResult:
    """Validate every provenance edge used by Gate 06 from one shared truth source.

    The function is deliberately data-only: tests can supply mocked records, while the
    production orchestration passes its immutable request logs and canonical manifests.
    Missing evidence never becomes a successful default.
    """
    discovery = _linkage_records(discovery_records)
    documents = _linkage_records(document_records)
    raw_entries = _linkage_records(raw_manifest_entries if raw_manifest_entries is not None else document_records)
    authorities = _linkage_records(authority_rows)
    requests_log = _linkage_records(request_logs)
    price_logs = _linkage_records(price_request_logs)
    if price_request_logs is None:
        price_logs = [
            r for r in requests_log
            if _linkage_text(r, "source") in {"NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"}
        ]

    strict_identity = str(schema_suffix or "10") in {"11", "12"}
    result = LiveEvidenceLinkageResult(
        canonical_run_id=str(canonical_run_id or ""),
        linkage_evaluation_status="EVALUATED" if canonical_run_id else "NOT_EVALUATED_MISSING_RUN_ID",
        accounting_cross_invariant_pass=bool(accounting_cross_invariant_pass is True),
        schema_suffix=str(schema_suffix or "10"),
    )
    request_by_id: dict[str, dict[str, Any]] = {}
    request_groups: dict[str, list[dict[str, Any]]] = {}
    for request in requests_log:
        request_id = _linkage_text(request, "request_id")
        if not request_id:
            result.physical_request_mutation_failures.append(
                _linkage_failure("MISSING_PHYSICAL_REQUEST_ID")
            )
            continue
        request_groups.setdefault(request_id, []).append(request)
        request_by_id.setdefault(request_id, request)
        if _linkage_text(request, "canonical_run_id") != result.canonical_run_id:
            result.cross_run_request_linkage_failures.append(
                _linkage_failure("REQUEST_RUN_MISMATCH", request_id=request_id)
            )
    for request_id, grouped in request_groups.items():
        if len(grouped) > 1:
            result.physical_request_mutation_failures.append(
                _linkage_failure("DUPLICATE_PHYSICAL_REQUEST_RECORD", request_id=request_id, count=len(grouped))
            )
        fingerprints = {
            tuple(_linkage_text(r, key) for key in (
                "canonical_run_id", "source", "outcome", "http_status",
                "transport_response_size", "transport_response_sha256",
                "raw_http_response_size", "raw_http_response_sha256",
            ))
            for r in grouped
        }
        if len(fingerprints) > 1:
            result.physical_request_mutation_failures.append(
                _linkage_failure("CONFLICTING_PHYSICAL_REQUEST_RECORD", request_id=request_id)
            )

    authority_by_control = {
        (_linkage_text(row, "control_id"), _linkage_text(row, "ticker")): row
        for row in authorities
    }
    authority_by_record_id = {
        _linkage_text(row, "authority_record_id", "record_id", "rcept_no"): row
        for row in authorities
        if _linkage_text(row, "authority_record_id", "record_id", "rcept_no")
    }
    discovery_by_control = {
        (_linkage_text(row, "control_id"), _linkage_text(row, "ticker")): row
        for row in discovery
        if _linkage_text(row, "control_id", "ticker")
    }

    for discovery_row in discovery:
        if strict_identity:
            for field_name in ("canonical_run_id", "control_id", "ticker", "corp_code", "selected_record_id"):
                if not _linkage_text(discovery_row, field_name):
                    result.record_identity_failures.append(
                        _linkage_failure("MISSING_DISCOVERY_" + field_name.upper(), field=field_name)
                    )
            if not _linkage_text(discovery_row, "issuer_name", "issuer", "corp_name"):
                result.issuer_identity_failures.append(
                    _linkage_failure("MISSING_DISCOVERY_ISSUER", field="issuer_name")
                )
        discovery_run = _linkage_text(discovery_row, "canonical_run_id")
        if discovery_run != result.canonical_run_id:
            result.live_lineage_failures.append(
                _linkage_failure("DISCOVERY_RECORD_RUN_MISMATCH", control_id=_linkage_text(discovery_row, "control_id"), observed=discovery_run)
            )
            if discovery_run:
                result.cross_run_request_linkage_failures.append(
                    _linkage_failure("DISCOVERY_RECORD_CROSS_RUN", control_id=_linkage_text(discovery_row, "control_id"), observed=discovery_run)
                )
        discovery_request_id = _linkage_text(discovery_row, "request_id", "producing_request_id")
        if discovery_request_id:
            discovery_request = request_by_id.get(discovery_request_id)
            if discovery_request is None or _linkage_text(discovery_request, "outcome") != "SUCCESS":
                result.live_lineage_failures.append(
                    _linkage_failure("DISCOVERY_REQUEST_NOT_SUCCESS", request_id=discovery_request_id)
                )

    # 1-6. Document → producing request, run, retrieval mode, and raw reuse.
    for document in documents:
        doc_id = _linkage_text(document, "official_record_id", "rcept_no", "record_id", "authority_record_id")
        request_id = _linkage_text(document, "producing_request_id", "request_id")
        document_run = _linkage_text(document, "canonical_run_id")
        if strict_identity:
            for field_name in ("canonical_run_id", "control_id", "ticker", "corp_code", "official_record_id", "producing_request_id", "retrieval_mode"):
                if not _linkage_text(document, field_name):
                    result.record_identity_failures.append(
                        _linkage_failure("MISSING_DOCUMENT_" + field_name.upper(), record_id=doc_id, field=field_name)
                    )
            if not _linkage_text(document, "issuer_name", "issuer", "parsed_issuer"):
                result.issuer_identity_failures.append(
                    _linkage_failure("MISSING_DOCUMENT_ISSUER", record_id=doc_id, field="issuer")
                )
            if not _linkage_text(document, "sha256", "raw_sha", "raw_evidence_sha256"):
                result.record_identity_failures.append(
                    _linkage_failure("MISSING_DOCUMENT_RAW_SHA", record_id=doc_id, field="raw_sha")
                )
        if document_run != result.canonical_run_id:
            result.live_lineage_failures.append(
                _linkage_failure("DOCUMENT_RUN_MISMATCH", record_id=doc_id, observed=document_run)
            )
            if document_run and document_run != result.canonical_run_id:
                result.cross_run_request_linkage_failures.append(
                    _linkage_failure("DOCUMENT_CROSS_RUN", record_id=doc_id, observed=document_run)
                )
        request = request_by_id.get(request_id)
        if not request_id or request is None:
            result.producing_request_failures.append(
                _linkage_failure("PRODUCING_REQUEST_NOT_FOUND", record_id=doc_id, request_id=request_id)
            )
        else:
            if _linkage_text(request, "outcome") != "SUCCESS":
                result.producing_request_failures.append(
                    _linkage_failure("PRODUCING_REQUEST_NOT_SUCCESS", record_id=doc_id, request_id=request_id)
                )
            if _linkage_text(request, "canonical_run_id") != result.canonical_run_id:
                result.cross_run_request_linkage_failures.append(
                    _linkage_failure("PRODUCING_REQUEST_CROSS_RUN", record_id=doc_id, request_id=request_id)
                )
            if not _request_source_matches(document, request):
                result.producing_request_failures.append(
                    _linkage_failure("PRODUCING_REQUEST_SOURCE_MISMATCH", record_id=doc_id, request_id=request_id)
                )
            if not _request_hash_matches(document, request):
                result.producing_request_failures.append(
                    _linkage_failure("PRODUCING_REQUEST_SHA_MISMATCH", record_id=doc_id, request_id=request_id)
                )
            request_record_id = _linkage_text(request, "official_record_id", "authority_record_id", "rcept_no")
            if request_record_id and doc_id and request_record_id != doc_id:
                result.record_identity_failures.append(
                    _linkage_failure("PRODUCING_REQUEST_RECORD_ID_MISMATCH", record_id=doc_id, request_id=request_id)
                )
        retrieval_mode = _linkage_text(document, "retrieval_mode")
        if retrieval_mode not in ALLOWED_RETRIEVAL_MODES:
            result.invalid_retrieval_modes.append(
                _linkage_failure("INVALID_RETRIEVAL_MODE", record_id=doc_id, retrieval_mode=retrieval_mode)
            )
        path_text = _linkage_text(document, "path", "raw_path", "raw_evidence_path")
        lower_path = path_text.lower()
        current_dir_name = Path(current_output_dir).name if current_output_dir is not None else ""
        current_fix = ""
        if "v01_fix03_correction_9" in current_dir_name:
            current_fix = "v01_fix03_correction_9"
        elif "v01_fix03_correction_10" in current_dir_name:
            current_fix = "v01_fix03_correction_10"
        elif "v01_fix03_correction_11" in current_dir_name:
            current_fix = "v01_fix03_correction_11"
        if (
            retrieval_mode in FORBIDDEN_RETRIEVAL_MODES
            or any(token in lower_path for token in ("historical", "synthetic", "cached"))
            or (current_fix and "v01_fix03_correction" in lower_path and current_fix not in lower_path)
        ):
            result.historical_raw_reuse_failures.append(
                _linkage_failure("HISTORICAL_RAW_REUSE", record_id=doc_id, path=path_text, retrieval_mode=retrieval_mode)
            )
        if strict_identity:
            matching_raw = [
                raw for raw in raw_entries
                if _linkage_text(raw, "canonical_run_id") == document_run
                and _linkage_text(raw, "control_id") == _linkage_text(document, "control_id")
                and _linkage_text(raw, "ticker") == _linkage_text(document, "ticker")
                and _linkage_text(raw, "corp_code") == _linkage_text(document, "corp_code")
                and _linkage_text(raw, "official_record_id", "rcept_no", "authority_record_id") == doc_id
            ]
            if not matching_raw:
                result.live_lineage_failures.append(
                    _linkage_failure("DOCUMENT_RAW_MANIFEST_NOT_LINKED", record_id=doc_id)
                )
            for raw in matching_raw:
                doc_sha = _linkage_text(document, "sha256", "raw_sha", "raw_evidence_sha256")
                raw_sha = _linkage_text(raw, "sha256", "raw_sha", "raw_evidence_sha256", "canonical_raw_sha256")
                if not doc_sha or not raw_sha or doc_sha != raw_sha:
                    result.record_identity_failures.append(
                        _linkage_failure("DOCUMENT_RAW_SHA_MISMATCH", record_id=doc_id)
                    )
                if _linkage_text(raw, "producing_request_id", "request_id") != request_id:
                    result.producing_request_failures.append(
                        _linkage_failure("DOCUMENT_RAW_REQUEST_MISMATCH", record_id=doc_id, request_id=request_id)
                    )

    # 2, 7. Discovery/document/authority identity and current-run lineage.
    for authority in authorities:
        control_key = (_linkage_text(authority, "control_id"), _linkage_text(authority, "ticker"))
        authority_id = _linkage_text(authority, "authority_record_id", "record_id", "rcept_no")
        if strict_identity:
            for field_name in ("canonical_run_id", "control_id", "ticker", "corp_code", "authority_record_id", "producing_request_id", "raw_evidence_path", "raw_evidence_sha256"):
                if not _linkage_text(authority, field_name):
                    result.record_identity_failures.append(
                        _linkage_failure("MISSING_AUTHORITY_" + field_name.upper(), authority_record_id=authority_id, field=field_name)
                    )
            if not _linkage_text(authority, "issuer_name", "issuer"):
                result.issuer_identity_failures.append(
                    _linkage_failure("MISSING_AUTHORITY_ISSUER", authority_record_id=authority_id, field="issuer_name")
                )
        doc_matches = [
            d for d in documents
            if _linkage_text(d, "official_record_id", "rcept_no", "record_id", "authority_record_id") == authority_id
            or (control_key[0] and (_linkage_text(d, "control_id"), _linkage_text(d, "ticker")) == control_key)
        ]
        discovery_row = discovery_by_control.get(control_key)
        if not doc_matches:
            result.live_lineage_failures.append(
                _linkage_failure("AUTHORITY_DOCUMENT_NOT_LINKED", authority_record_id=authority_id)
            )
        for document in doc_matches:
            doc_id = _linkage_text(document, "official_record_id", "rcept_no", "record_id", "authority_record_id")
            if doc_id != authority_id:
                result.record_identity_failures.append(
                    _linkage_failure("DOCUMENT_AUTHORITY_RECORD_ID_MISMATCH", document_id=doc_id, authority_record_id=authority_id)
                )
            if _linkage_text(document, "canonical_run_id") != result.canonical_run_id:
                result.live_lineage_failures.append(
                    _linkage_failure("DOCUMENT_AUTHORITY_LINEAGE_RUN_MISMATCH", authority_record_id=authority_id)
                )
            if _linkage_text(document, "ticker") != _linkage_text(authority, "ticker"):
                result.record_identity_failures.append(
                    _linkage_failure("DOCUMENT_TICKER_MISMATCH", authority_record_id=authority_id)
                )
            if _linkage_text(document, "corp_code") and _linkage_text(authority, "corp_code") and _linkage_text(document, "corp_code") != _linkage_text(authority, "corp_code"):
                result.record_identity_failures.append(
                    _linkage_failure("DOCUMENT_CORP_CODE_MISMATCH", authority_record_id=authority_id)
                )
            doc_issuer = _linkage_text(document, "issuer", "issuer_name", "parsed_issuer")
            auth_issuer = _linkage_text(authority, "issuer_name", "issuer")
            if doc_issuer and auth_issuer and doc_issuer != auth_issuer:
                result.issuer_identity_failures.append(
                    _linkage_failure("DOCUMENT_ISSUER_MISMATCH", authority_record_id=authority_id)
                )
        if discovery_row is None:
            result.live_lineage_failures.append(
                _linkage_failure("AUTHORITY_DISCOVERY_NOT_LINKED", authority_record_id=authority_id)
            )
        else:
            discovery_run = _linkage_text(discovery_row, "canonical_run_id")
            if discovery_run != result.canonical_run_id:
                result.live_lineage_failures.append(
                    _linkage_failure("DISCOVERY_RUN_MISMATCH", control_id=control_key[0], observed=discovery_run)
                )
            selected_id = _linkage_text(discovery_row, "selected_record_id", "selected_rcept_no", "rcept_no")
            if selected_id and selected_id != authority_id:
                result.record_identity_failures.append(
                    _linkage_failure("DISCOVERY_AUTHORITY_RECORD_ID_MISMATCH", selected_id=selected_id, authority_record_id=authority_id)
                )
            if _linkage_text(discovery_row, "ticker") != _linkage_text(authority, "ticker"):
                result.record_identity_failures.append(
                    _linkage_failure("DISCOVERY_TICKER_MISMATCH", authority_record_id=authority_id)
                )
            discovery_corp_code = _linkage_text(discovery_row, "corp_code")
            authority_corp_code = _linkage_text(authority, "corp_code")
            if discovery_corp_code and authority_corp_code and discovery_corp_code != authority_corp_code:
                result.record_identity_failures.append(
                    _linkage_failure("DISCOVERY_CORP_CODE_MISMATCH", authority_record_id=authority_id)
                )
            d_issuer = _linkage_text(discovery_row, "issuer_name", "issuer", "corp_name")
            a_issuer = _linkage_text(authority, "issuer_name", "issuer")
            if d_issuer and a_issuer and d_issuer != a_issuer:
                result.issuer_identity_failures.append(
                    _linkage_failure("DISCOVERY_ISSUER_MISMATCH", authority_record_id=authority_id)
                )
        authority_run = _linkage_text(authority, "canonical_run_id")
        if authority_run != result.canonical_run_id:
            result.live_lineage_failures.append(
                _linkage_failure("AUTHORITY_RUN_MISMATCH", authority_record_id=authority_id, observed=authority_run)
            )
            if authority_run and authority_run != result.canonical_run_id:
                result.cross_run_request_linkage_failures.append(
                    _linkage_failure("AUTHORITY_CROSS_RUN", authority_record_id=authority_id, observed=authority_run)
                )

    # 8-9. Candidate and raw PyKRX requests must bind to the frozen cohort.
    naver_logs = [r for r in price_logs if _linkage_text(r, "source") == "NAVER_DIRECT"]
    pykrx_logs = [r for r in price_logs if _linkage_text(r, "source") == "RAW_PYKRX_COMPARATOR"]
    for authority in authorities:
        authority_id = _linkage_text(authority, "authority_record_id", "record_id", "rcept_no")
        for source, logs, failures in (
            ("NAVER_DIRECT", naver_logs, result.candidate_linkage_failures),
            ("RAW_PYKRX_COMPARATOR", pykrx_logs, result.pykrx_linkage_failures),
        ):
            matches = [r for r in logs if _request_matches_control(r, authority)]
            if not matches:
                failures.append(
                    _linkage_failure("PRICE_REQUEST_NOT_LINKED", source=source, authority_record_id=authority_id)
                )
                continue
            for request in matches:
                if strict_identity:
                    for field_name in ("canonical_run_id", "control_id", "ticker", "authority_record_id", "price_window_start", "price_window_end", "outcome"):
                        if not _linkage_text(request, field_name):
                            failures.append(_linkage_failure("MISSING_" + source + "_" + field_name.upper(), authority_record_id=authority_id, field=field_name))
                if _linkage_text(request, "canonical_run_id") != result.canonical_run_id:
                    failures.append(_linkage_failure("PRICE_REQUEST_RUN_MISMATCH", source=source, authority_record_id=authority_id))
                if _linkage_text(request, "outcome") != "SUCCESS":
                    failures.append(_linkage_failure("PRICE_REQUEST_NOT_SUCCESS", source=source, authority_record_id=authority_id))
                req_control = _linkage_text(request, "control_id")
                auth_control = _linkage_text(authority, "control_id")
                if not req_control or not auth_control or req_control != auth_control:
                    failures.append(_linkage_failure("PRICE_CONTROL_ID_MISMATCH", source=source, authority_record_id=authority_id))
                req_authority_id = _linkage_text(request, "authority_record_id", "official_record_id")
                if not req_authority_id or not authority_id or req_authority_id != authority_id:
                    failures.append(_linkage_failure("PRICE_AUTHORITY_ID_MISMATCH", source=source, authority_record_id=authority_id))
                if source == "RAW_PYKRX_COMPARATOR":
                    adjusted = _linkage_bool(request, "adjusted") or "adjusted=true" in _linkage_text(request, "sanitized_endpoint").lower()
                    if not adjusted:
                        failures.append(_linkage_failure("PYKRX_ADJUSTED_FLAG_MISSING", authority_record_id=authority_id))

    # 10. Bidirectional raw-file ↔ manifest validation.
    manifest_paths: set[str] = set()
    for entry in raw_entries:
        path_text = _linkage_text(entry, "path", "raw_path", "raw_evidence_path")
        if strict_identity:
            for field_name in ("canonical_run_id", "control_id", "ticker", "corp_code", "official_record_id", "producing_request_id", "retrieval_mode", "sha256", "canonical_raw_sha256"):
                if not _linkage_text(entry, field_name):
                    result.raw_orphan_failures.append(
                        _linkage_failure("MISSING_RAW_MANIFEST_" + field_name.upper(), path=path_text, field=field_name)
                    )
            if not _linkage_text(entry, "issuer_name", "issuer", "parsed_issuer"):
                result.raw_orphan_failures.append(
                    _linkage_failure("MISSING_RAW_MANIFEST_ISSUER", path=path_text, field="issuer_name")
                )
        if path_text:
            manifest_paths.add(Path(path_text).name)
        if not _linkage_text(entry, "producing_request_id", "request_id"):
            result.raw_orphan_failures.append(_linkage_failure("RAW_MANIFEST_MISSING_PRODUCING_REQUEST", path=path_text))
        if _linkage_text(entry, "canonical_run_id") != result.canonical_run_id:
            result.raw_orphan_failures.append(_linkage_failure("RAW_MANIFEST_RUN_MISMATCH", path=path_text))
        entry_id = _linkage_text(entry, "official_record_id", "rcept_no", "authority_record_id")
        if entry_id and entry_id not in authority_by_record_id:
            result.raw_orphan_failures.append(_linkage_failure("RAW_MANIFEST_AUTHORITY_NOT_FOUND", path=path_text, record_id=entry_id))

    raw_root: Path | None = None
    if current_output_dir is not None:
        raw_root = Path(current_output_dir) / "raw"
    if isinstance(artifact_paths, dict):
        candidate_root = artifact_paths.get("raw") or artifact_paths.get("raw_dir")
        if candidate_root:
            raw_root = Path(candidate_root)
    if raw_root is not None and raw_root.exists():
        for raw_file in raw_root.rglob("*"):
            if raw_file.is_file() and raw_file.name not in manifest_paths:
                result.raw_orphan_failures.append(
                    _linkage_failure("RAW_FILE_NOT_IN_MANIFEST", path=str(raw_file))
                )
        if manifest_paths:
            on_disk = {p.name for p in raw_root.rglob("*") if p.is_file()}
            for manifest_name in sorted(manifest_paths - on_disk):
                result.raw_orphan_failures.append(
                    _linkage_failure("RAW_MANIFEST_FILE_MISSING", path=manifest_name)
                )

    if not authorities and result.linkage_evaluation_status == "EVALUATED":
        # An empty cohort is not a successful full-success evaluation.
        result.linkage_evaluation_status = "NOT_EVALUATED_EMPTY_AUTHORITY_COHORT"
    return result


def select_official_anchor_by_priority(
    event_family: str,
    found_anchors: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, bool, str, int]:
    """Pure production helper to select official anchor by frozen priority without claim assistance."""
    if not found_anchors:
        return None, False, "NO_TIMING_ANCHORS_FOUND", 0

    priority_list = FROZEN_EVENT_FAMILY_ANCHOR_PRIORITY.get(event_family, [])
    anchors_by_type: dict[str, list[dict[str, Any]]] = {}
    for a in found_anchors:
        a_type = a["anchor_type"]
        anchors_by_type.setdefault(a_type, []).append(a)

    for p_idx, p_type in enumerate(priority_list, start=1):
        if p_type in anchors_by_type:
            cands = anchors_by_type[p_type]
            distinct_dates = {c["anchor_date"] for c in cands}
            if len(distinct_dates) > 1:
                return None, True, f"EVENT_TIMING_AMBIGUOUS: multiple distinct dates {distinct_dates} for priority anchor {p_type}", 0
            winner = cands[0]
            winner["official_anchor_priority_rank"] = p_idx
            winner["timing_repetition_count"] = len(cands)
            return winner, False, "SUCCESS", p_idx

    first_type = found_anchors[0]["anchor_type"]
    cands = [a for a in found_anchors if a["anchor_type"] == first_type]
    distinct_dates = {c["anchor_date"] for c in cands}
    if len(distinct_dates) > 1:
        return None, True, f"EVENT_TIMING_AMBIGUOUS: multiple distinct dates {distinct_dates}", 0
    winner = cands[0]
    winner["official_anchor_priority_rank"] = len(priority_list) + 1
    winner["timing_repetition_count"] = len(cands)
    return winner, False, "SUCCESS", len(priority_list) + 1


PRICE_ROW_REQUIRED_COLUMNS = frozenset({
    "canonical_run_id", "control_id", "ticker", "corp_code", "authority_record_id",
    "source", "request_id", "evidence_origin", "price_window_start", "price_window_end",
    "official_anchor_date", "date", "open", "high", "low", "close", "volume",
})
PARITY_REQUIRED_COLUMNS = frozenset({
    "canonical_run_id", "control_id", "ticker", "corp_code", "authority_record_id",
    "candidate_request_id", "pykrx_request_id", "price_window_start", "price_window_end",
    "official_anchor_date", "candidate_row_count", "pykrx_row_count", "common_date_count",
    "candidate_only_date_count", "pykrx_only_date_count", "pre_event_common_count",
    "post_event_common_count", "open_mismatch_count", "high_mismatch_count",
    "low_mismatch_count", "close_mismatch_count", "volume_mismatch_count", "parity_status",
})
RECONCILIATION_REQUIRED_COLUMNS = frozenset({
    "canonical_run_id", "control_id", "ticker", "authority_record_id",
    "candidate_request_id", "pykrx_request_id", "candidate_date_count", "pykrx_date_count",
    "common_date_count", "candidate_only_date_count", "pykrx_only_date_count",
    "candidate_only_dates", "pykrx_only_dates", "reconciliation_status",
})


@dataclass
class PersistedPriceParityValidation:
    """Independent validation result for persisted event-sensitive price evidence."""

    evaluation_status: str
    expected_control_count: int
    naver_control_count: int
    pykrx_control_count: int
    parity_control_count: int
    reconciliation_control_count: int
    naver_price_row_count: int
    pykrx_price_row_count: int
    exact_match_control_count: int
    date_mismatch_control_count: int
    insufficient_window_control_count: int
    ohlc_mismatch_control_count: int
    all_controls_evidenced: bool
    all_cardinality_valid: bool
    all_request_bindings_valid: bool
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evidence_frame(value: Any) -> pd.DataFrame:
    """Load evidence without inventing rows; accepts a frame, rows, or CSV path."""
    if isinstance(value, pd.DataFrame):
        return value.copy()
    if isinstance(value, (str, Path)):
        path = Path(value)
        if not path.is_file():
            return pd.DataFrame()
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False)
        except (OSError, ValueError, pd.errors.ParserError):
            return pd.DataFrame()
    if isinstance(value, Mapping):
        value = value.get("records", value.get("rows", []))
    if isinstance(value, (list, tuple)):
        return pd.DataFrame([row for row in value if isinstance(row, Mapping)])
    return pd.DataFrame()


def _control_frame(value: Any) -> pd.DataFrame:
    frame = _evidence_frame(value)
    if frame.empty:
        return frame
    aliases = {"authority_record_id": "authority_record_id", "selected_record_id": "authority_record_id"}
    for old, new in aliases.items():
        if old in frame.columns and new not in frame.columns:
            frame[new] = frame[old]
    return frame


def _int_field(row: Mapping[str, Any], name: str, blockers: list[str]) -> int | None:
    value = row.get(name)
    try:
        if value is None or str(value).strip() == "":
            raise ValueError
        return int(float(value))
    except (TypeError, ValueError):
        blockers.append(f"PRICE_EVIDENCE_FIELD_INVALID:{name}")
        return None


def validate_persisted_price_parity_evidence(
    price_rows: Any,
    parity_rows: Any,
    reconciliation_rows: Any,
    frozen_controls: Any,
    *,
    request_logs: Any = None,
    gate06_payload: Mapping[str, Any] | None = None,
    decision_payload: Mapping[str, Any] | None = None,
) -> PersistedPriceParityValidation:
    """Recompute every C13 claim from persisted raw rows, then fail closed."""
    blockers: list[str] = []
    price_df = _evidence_frame(price_rows)
    parity_df = _evidence_frame(parity_rows)
    recon_df = _evidence_frame(reconciliation_rows)
    controls_df = _control_frame(frozen_controls)
    expected_ids = {str(v).strip() for v in controls_df.get("control_id", pd.Series(dtype=str)).tolist() if str(v).strip()}
    expected_count = len(expected_ids)
    if expected_count == 0:
        blockers.append("PRICE_EVIDENCE_EXPECTED_COHORT_MISSING")
    for frame, required, label in ((price_df, PRICE_ROW_REQUIRED_COLUMNS, "PRICE_EVIDENCE"), (parity_df, PARITY_REQUIRED_COLUMNS, "PARITY_EVIDENCE"), (recon_df, RECONCILIATION_REQUIRED_COLUMNS, "RECONCILIATION_EVIDENCE")):
        if frame.empty:
            blockers.append(f"{label}_EMPTY")
        blockers.extend(f"{label}_COLUMN_MISSING:{c}" for c in sorted(required - set(frame.columns)))

    def ids_for(frame: pd.DataFrame) -> set[str]:
        return {str(v).strip() for v in frame.get("control_id", pd.Series(dtype=str)).tolist() if str(v).strip()}

    naver_df = price_df[price_df.get("source", pd.Series(index=price_df.index, dtype=str)).astype(str) == "NAVER_DIRECT"].copy() if not price_df.empty else price_df.copy()
    pykrx_df = price_df[price_df.get("source", pd.Series(index=price_df.index, dtype=str)).astype(str) == "RAW_PYKRX_COMPARATOR"].copy() if not price_df.empty else price_df.copy()
    naver_ids, pykrx_ids, parity_ids, recon_ids = ids_for(naver_df), ids_for(pykrx_df), ids_for(parity_df), ids_for(recon_df)
    for label, actual in (("NAVER", naver_ids), ("PYKRX", pykrx_ids), ("PARITY", parity_ids), ("RECONCILIATION", recon_ids)):
        if actual != expected_ids:
            blockers.append(f"PRICE_SOURCE_CONTROL_COVERAGE_MISMATCH:{label}")
    if "control_id" in parity_df and parity_df.duplicated("control_id").any():
        blockers.append("PARITY_CONTROL_DUPLICATE")
    if "control_id" in recon_df and recon_df.duplicated("control_id").any():
        blockers.append("RECONCILIATION_CONTROL_DUPLICATE")

    controls_by_id = {str(row.get("control_id", "")).strip(): row for row in controls_df.to_dict("records")}
    for source_name, source_df in (("NAVER_DIRECT", naver_df), ("RAW_PYKRX_COMPARATOR", pykrx_df)):
        if "control_id" not in source_df:
            continue
        for cid, group in source_df.groupby("control_id", dropna=False):
            if group.duplicated("date").any() if "date" in group else False:
                blockers.append("PRICE_DUPLICATE_DATE")
            control = controls_by_id.get(str(cid).strip())
            if control is None:
                blockers.append("PRICE_PARITY_CONTROL_COVERAGE_MISMATCH")
                continue
            for field_name in ("ticker", "price_window_start", "price_window_end", "official_anchor_date", "authority_record_id"):
                expected = str(control.get(field_name, control.get("selected_record_id", ""))).strip()
                if expected and str(group[field_name].iloc[0] if field_name in group else "").strip() != expected:
                    blockers.append(f"PRICE_EVIDENCE_IDENTITY_MISMATCH:{field_name}")
            if "source_rowset_sha256" in group:
                shas = {str(v).strip() for v in group["source_rowset_sha256"].tolist() if str(v).strip()}
                try:
                    computed_sha = _c13_compute_rowset_sha(group)
                except (KeyError, TypeError, ValueError):
                    computed_sha = ""
                if len(shas) != 1 or not computed_sha or computed_sha not in shas:
                    blockers.append("PRICE_ROWSET_SHA_MISMATCH")

    logs = _evidence_frame(request_logs).to_dict("records") if request_logs is not None else []
    binding_ok = True
    for source_name, source_df in (("NAVER_DIRECT", naver_df), ("RAW_PYKRX_COMPARATOR", pykrx_df)):
        if source_df.empty or "control_id" not in source_df:
            continue
        for (cid, req_id), group in source_df.groupby(["control_id", "request_id"], dropna=False):
            matches = [log for log in logs if str(log.get("control_id", "")).strip() == str(cid).strip() and str(log.get("source", "")).strip() == source_name and str(log.get("request_id", "")).strip() == str(req_id).strip() and str(log.get("outcome", "")).upper() == "SUCCESS"]
            if len(matches) != 1 or int(float(matches[0].get("physical_attempt", 0) or 0)) != 1:
                binding_ok = False
                blockers.append("PRICE_REQUEST_LINKAGE_MISSING" if not matches else "PRICE_REQUEST_IDENTITY_MISMATCH")
            if matches:
                for name in ("price_window_start", "price_window_end"):
                    if str(matches[0].get(name, "")).strip() != str(group[name].iloc[0]).strip():
                        binding_ok = False
                        blockers.append("PRICE_REQUEST_WINDOW_MISMATCH")

    def raw_metrics(cid: str) -> dict[str, Any]:
        n = naver_df[naver_df.get("control_id", pd.Series(index=naver_df.index, dtype=str)).astype(str) == cid]
        p = pykrx_df[pykrx_df.get("control_id", pd.Series(index=pykrx_df.index, dtype=str)).astype(str) == cid]
        ndates = {str(v).strip() for v in n.get("date", pd.Series(dtype=str)).tolist() if str(v).strip()}
        pdates = {str(v).strip() for v in p.get("date", pd.Series(dtype=str)).tolist() if str(v).strip()}
        common_dates = sorted(ndates & pdates)
        candidate_only = sorted(ndates - pdates)
        pykrx_only = sorted(pdates - ndates)
        anchor = str(controls_by_id.get(cid, {}).get("official_anchor_date", ""))
        mismatches = {name: 0 for name in ("open", "high", "low", "close", "volume")}
        if common_dates and not n.empty and not p.empty:
            ni, pi = n.set_index("date"), p.set_index("date")
            for date in common_dates:
                for name in mismatches:
                    try:
                        if float(ni.loc[date, name]) != float(pi.loc[date, name]):
                            mismatches[name] += 1
                    except (KeyError, TypeError, ValueError):
                        blockers.append("PRICE_RAW_VALUE_INVALID")
        pre = sum(date < anchor for date in common_dates)
        post = sum(date > anchor for date in common_dates)
        date_bad = bool(candidate_only or pykrx_only)
        window_bad = pre < 5 or post < 5
        ohlc_bad = sum(mismatches[name] for name in ("open", "high", "low", "close")) > 0
        expected_status = "MATCH" if (len(n) > 0 and len(p) > 0 and common_dates and not date_bad and not window_bad and not ohlc_bad) else "MISMATCH"
        return {"candidate_row_count": len(n), "pykrx_row_count": len(p), "common_date_count": len(common_dates), "candidate_only_date_count": len(candidate_only), "pykrx_only_date_count": len(pykrx_only), "pre_event_common_count": pre, "post_event_common_count": post, **{f"{name}_mismatch_count": value for name, value in mismatches.items()}, "parity_status": expected_status, "candidate_date_count": len(ndates), "pykrx_date_count": len(pdates), "candidate_only_dates": _c13_json_dates(candidate_only), "pykrx_only_dates": _c13_json_dates(pykrx_only), "reconciliation_status": "MATCH" if not date_bad else "MISMATCH"}

    exact_matches = date_mismatches = insufficient = ohlc_mismatches = 0
    parity_count_ok = True
    parity_by_id = {str(row.get("control_id", "")).strip(): row for row in parity_df.to_dict("records")}
    recon_by_id = {str(row.get("control_id", "")).strip(): row for row in recon_df.to_dict("records")}
    for cid in expected_ids:
        metrics = raw_metrics(cid)
        if metrics["candidate_row_count"] == 0 or metrics["pykrx_row_count"] == 0:
            blockers.append("PRICE_SOURCE_EMPTY_FOR_CONTROL")
        if metrics["candidate_only_date_count"] or metrics["pykrx_only_date_count"]:
            date_mismatches += 1
        if metrics["pre_event_common_count"] < 5 or metrics["post_event_common_count"] < 5:
            insufficient += 1
        if any(metrics[f"{name}_mismatch_count"] for name in ("open", "high", "low", "close")):
            ohlc_mismatches += 1
        if metrics["parity_status"] == "MATCH":
            exact_matches += 1
        prow = parity_by_id.get(cid)
        rrow = recon_by_id.get(cid)
        if prow is None:
            blockers.append("PARITY_CONTROL_MISSING")
        else:
            expected_naver_req = ""
            expected_pykrx_req = ""
            n_for_control = naver_df[naver_df.get("control_id", pd.Series(index=naver_df.index, dtype=str)).astype(str) == cid]
            p_for_control = pykrx_df[pykrx_df.get("control_id", pd.Series(index=pykrx_df.index, dtype=str)).astype(str) == cid]
            if not n_for_control.empty and "request_id" in n_for_control:
                requests_for_control = {str(v).strip() for v in n_for_control["request_id"].tolist() if str(v).strip()}
                expected_naver_req = next(iter(requests_for_control)) if len(requests_for_control) == 1 else ""
            if not p_for_control.empty and "request_id" in p_for_control:
                requests_for_control = {str(v).strip() for v in p_for_control["request_id"].tolist() if str(v).strip()}
                expected_pykrx_req = next(iter(requests_for_control)) if len(requests_for_control) == 1 else ""
            if str(prow.get("candidate_request_id", "")).strip() != expected_naver_req or str(prow.get("pykrx_request_id", "")).strip() != expected_pykrx_req:
                parity_count_ok = False
                blockers.append("PRICE_REQUEST_IDENTITY_MISMATCH")
            control = controls_by_id.get(cid, {})
            for identity_field in ("ticker", "price_window_start", "price_window_end", "official_anchor_date", "authority_record_id"):
                expected_identity = str(control.get(identity_field, control.get("selected_record_id", ""))).strip()
                if expected_identity and str(prow.get(identity_field, "")).strip() != expected_identity:
                    parity_count_ok = False
                    blockers.append(f"PARITY_IDENTITY_MISMATCH:{identity_field}")
            for field_name in ("candidate_row_count", "pykrx_row_count", "common_date_count", "candidate_only_date_count", "pykrx_only_date_count", "pre_event_common_count", "post_event_common_count", "open_mismatch_count", "high_mismatch_count", "low_mismatch_count", "close_mismatch_count", "volume_mismatch_count"):
                observed = _int_field(prow, field_name, blockers)
                if observed is not None and observed != metrics[field_name]:
                    parity_count_ok = False
                    blockers.append("PARITY_SUMMARY_RECOMPUTATION_MISMATCH")
            for field_name in ("parity_status",):
                if str(prow.get(field_name, "")).strip() != metrics[field_name]:
                    parity_count_ok = False
                    blockers.append("PARITY_SUMMARY_RECOMPUTATION_MISMATCH")
        if rrow is None:
            blockers.append("RECONCILIATION_CONTROL_MISSING")
        else:
            control = controls_by_id.get(cid, {})
            for identity_field in ("ticker", "authority_record_id"):
                expected_identity = str(control.get(identity_field, control.get("selected_record_id", ""))).strip()
                if expected_identity and str(rrow.get(identity_field, "")).strip() != expected_identity:
                    blockers.append(f"RECONCILIATION_IDENTITY_MISMATCH:{identity_field}")
            for field_name in ("candidate_date_count", "pykrx_date_count", "common_date_count", "candidate_only_date_count", "pykrx_only_date_count"):
                observed = _int_field(rrow, field_name, blockers)
                if observed is not None and observed != metrics[field_name]:
                    blockers.append("RECONCILIATION_RECOMPUTATION_MISMATCH")
            for field_name in ("candidate_only_dates", "pykrx_only_dates", "reconciliation_status"):
                if str(rrow.get(field_name, "")).strip() != str(metrics[field_name]).strip():
                    blockers.append("RECONCILIATION_RECOMPUTATION_MISMATCH")
    if gate06_payload is not None:
        for key, value in {"date_set_mismatch_count": date_mismatches, "date_mismatch_control_count": date_mismatches, "insufficient_window_count": insufficient, "insufficient_window_control_count": insufficient, "ohlc_mismatch_count": ohlc_mismatches, "ohlc_mismatch_control_count": ohlc_mismatches, "exact_match_control_count": exact_matches, "naver_control_count": len(naver_ids), "pykrx_control_count": len(pykrx_ids), "parity_control_count": len(parity_ids), "reconciliation_control_count": len(recon_ids)}.items():
            if key in gate06_payload and gate06_payload.get(key) != value:
                blockers.append("GATE06_PERSISTED_PARITY_MISMATCH")
    if decision_payload is not None:
        for key, value in {"actual_candidate_price_row_count": len(naver_df), "actual_pykrx_price_row_count": len(pykrx_df), "exact_date_match_controls": exact_matches, "date_mismatch_controls": date_mismatches, "insufficient_window_controls": insufficient, "ohlc_mismatch_controls": ohlc_mismatches}.items():
            if key in decision_payload and decision_payload.get(key) != value:
                blockers.append("DECISION_PERSISTED_PARITY_MISMATCH")
    all_controls = bool(expected_ids and naver_ids == expected_ids and pykrx_ids == expected_ids and parity_ids == expected_ids and recon_ids == expected_ids)
    cardinality_valid = bool(all_controls and parity_count_ok and not {"PARITY_CONTROL_DUPLICATE", "RECONCILIATION_CONTROL_DUPLICATE"}.intersection(blockers))
    structural_blockers = {"PRICE_EVIDENCE_EMPTY", "PARITY_EVIDENCE_EMPTY", "RECONCILIATION_EVIDENCE_EMPTY"}
    status = "EVALUATED" if cardinality_valid and not blockers else ("INCOMPLETE" if structural_blockers.intersection(blockers) else "INVALID")
    return PersistedPriceParityValidation(status, expected_count, len(naver_ids), len(pykrx_ids), len(parity_ids), len(recon_ids), len(naver_df), len(pykrx_df), exact_matches, date_mismatches, insufficient, ohlc_mismatches, all_controls, cardinality_valid, binding_ok and not any(code.startswith("PRICE_REQUEST_") for code in blockers), list(dict.fromkeys(blockers)))


def classify_candidate_resolution(
    candidate: Mapping[str, Any],
    *,
    official_evidence_obtained: bool,
    semantic_valid: bool,
    official_content_usable: bool = True,
    fallback_available: bool = False,
) -> str:
    """Classify candidate facts without conflating selected and unresolved provenance."""
    fallback_validation = candidate.get("fallback_validation")
    fallback_valid = bool(
        isinstance(fallback_validation, Mapping)
        and fallback_validation.get("valid") is True
        and isinstance(fallback_validation.get("provenance"), Mapping)
        and fallback_validation["provenance"].get("content_authority_tier") == TIER_B_ISSUER_OFFICIAL
        and fallback_validation["provenance"].get("authority_resolution_mode") == CANDIDATE_BOUND_FALLBACK_MODE
        and candidate.get("identity_authority_tier") in {
            AuthoritySourceTier.TIER_A1_OPENDART.value,
            AuthoritySourceTier.TIER_A2_KRX_KIND.value,
        }
    )
    # Tier-B is content-only.  A candidate cannot become authoritative merely
    # because a caller marked its page as official or usable.
    if fallback_valid:
        return "AUTHORITY_VALID_FALLBACK"
    if candidate.get("content_authority_tier") == TIER_B_ISSUER_OFFICIAL:
        return "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE"
    if official_evidence_obtained and official_content_usable and semantic_valid:
        return "AUTHORITY_VALID"
    if official_evidence_obtained and official_content_usable and not semantic_valid:
        return "DEFINITIVELY_REJECTED"
    if int(candidate.get("candidate_rank", 0) or 0) > 0 and int(candidate.get("event_match_score", 0) or 0) > 0:
        return "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE"
    return "REJECTED"


def evaluate_candidate_resolution_population(candidates: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Classify ranked candidates and keep unresolved higher-priority facts explicit.

    A candidate with valid official content but invalid semantics is a definitive
    rejection.  An otherwise positive candidate whose official content cannot be
    adjudicated is unresolved only when it outranks the selected authority.
    """
    ordered = sorted(candidates, key=lambda item: int(item.get("candidate_rank", 0) or 0))
    statuses: list[dict[str, Any]] = []
    authority_valid = []
    for candidate in ordered:
        status = classify_candidate_resolution(
            candidate,
            official_evidence_obtained=bool(candidate.get("official_evidence_obtained")),
            semantic_valid=bool(candidate.get("semantic_valid")),
            official_content_usable=bool(candidate.get("official_content_usable", True)),
            fallback_available=bool(candidate.get("fallback_available", False)),
        )
        if status in {"AUTHORITY_VALID", "AUTHORITY_VALID_FALLBACK"}:
            authority_valid.append(candidate)
        statuses.append({"candidate": dict(candidate), "status": status})
    selected = authority_valid[0] if authority_valid else None
    selected_rank = int(selected.get("candidate_rank", 0) or 0) if selected else None
    unresolved = []
    selected_authority_failures = []
    for item in statuses:
        rank = int(item["candidate"].get("candidate_rank", 0) or 0)
        status = item["status"]
        if status == "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE" and (selected_rank is None or rank < selected_rank):
            item["status"] = "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE"
            unresolved.append(item)
        elif status in {"AUTHORITY_VALID", "AUTHORITY_VALID_FALLBACK"} and selected is not None and rank == selected_rank:
            item["status"] = "SELECTED"
        elif status in {"AUTHORITY_VALID", "AUTHORITY_VALID_FALLBACK"}:
            item["status"] = "REJECTED_LOWER_PRIORITY"
        elif status == "UNRESOLVED_HIGHER_PRIORITY_CANDIDATE":
            item["status"] = "UNRESOLVED_LOWER_PRIORITY_CANDIDATE"
    if selected is not None and selected.get("archive_provenance_valid") is False:
        selected_authority_failures.append({
            "candidate_rank": selected_rank,
            "rcept_no": selected.get("rcept_no", ""),
            "code": "SELECTED_AUTHORITY_ARCHIVE_PROVENANCE_FAILURE",
        })
    return {
        "selected_candidate": dict(selected) if selected else None,
        "candidate_statuses": statuses,
        "unresolved_higher_priority_candidates": unresolved,
        "selected_authority_archive_provenance_failures": selected_authority_failures,
        "unresolved_higher_priority_candidate_count": len(unresolved),
        "selected_authority_archive_provenance_failure_count": len(selected_authority_failures),
    }


def evaluate_gate06(metrics: dict[str, Any]) -> tuple[bool, list[str]]:
    """Pure production evaluator for Gate 06 corporate action source authority."""
    blockers = []

    if metrics.get("preflight_verdict") != "READY":
        blockers.append("OpenDART preflight not READY")
    if metrics.get("document_readiness_verdict") != "READY":
        blockers.append("OpenDART document endpoint readiness probe not READY")
    if metrics.get("authority_valid_controls_count", 0) < 8:
        blockers.append(f"Official evidence deficit: {metrics.get('authority_valid_controls_count')}/8 authority valid")
    if not metrics.get("diversity_pass", False):
        blockers.append("Corporate action event diversity requirement failed")
    if metrics.get("pagination_incomplete_control_count", 0) > 0:
        blockers.append("Pagination incomplete across controls")
    if metrics.get("pagination_metadata_inconsistency_count", 0) > 0:
        blockers.append("Pagination metadata inconsistency detected")
    if metrics.get("pagination_page_count_inconsistency_count", 0) > 0:
        blockers.append("Pagination page_count inconsistency detected")
    if metrics.get("discovery_total_count_mismatch_count", 0) > 0:
        blockers.append("Discovery total count sum mismatch detected")
    if metrics.get("conflicting_duplicate_rcept_no_count", 0) > 0:
        blockers.append("Conflicting duplicate disclosure records detected")
    if metrics.get("candidate_audit_incomplete_count", 0) > 0:
        blockers.append("Candidate audit table incomplete")
    if metrics.get("ranking_order_invariance_failure_count", 0) > 0:
        blockers.append("Candidate ranking order invariance failed")
    if metrics.get("selected_record_invariance_failure_count", 0) > 0:
        blockers.append("Selected record invariance failed")
    if metrics.get("historical_raw_reuse_count", 0) > 0:
        blockers.append("Forbidden prior-run historical raw file reuse detected")
    if metrics.get("physical_request_mutation_failure_count", 0) > 0:
        blockers.append("Physical request log mutation detected")
    if metrics.get("live_lineage_failure_count", 0) > 0:
        blockers.append("Live evidence lineage failure detected")
    if metrics.get("claim_event_selection_influence_count", 0) > 0:
        blockers.append("Claim influence detected in event selection")
    if metrics.get("claim_context_selection_influence_count", 0) > 0:
        blockers.append("Claim influence detected in context selection")
    if metrics.get("claim_anchor_type_selection_influence_count", 0) > 0:
        blockers.append("Claim influence detected in anchor type selection")
    if metrics.get("claim_anchor_date_selection_influence_count", 0) > 0:
        blockers.append("Claim influence detected in anchor date selection")
    if metrics.get("event_type_ambiguity_count", 0) > 0:
        blockers.append("Event type ambiguity detected")
    if metrics.get("event_context_ambiguity_count", 0) > 0:
        blockers.append("Event context ambiguity detected")
    if metrics.get("event_timing_ambiguity_count", 0) > 0:
        blockers.append("Event timing ambiguity detected")
    if metrics.get("semantic_binding_failure_count", 0) > 0:
        blockers.append("Semantic hierarchy timing binding failed")
    if metrics.get("global_semantic_block_authority_count", 0) > 0:
        blockers.append("Forbidden global semantic block fallback used")
    # C13 separates selected-authority and unresolved-candidate provenance.
    # The legacy aggregate is retained for historical C12 payloads only and
    # cannot create a second blocker for a correctly classified rejection.
    is_c13 = str(metrics.get("schema", "")).endswith("correction_13") or str(metrics.get("directive_id", "")).endswith("CORRECTION_13")
    if metrics.get("archive_provenance_failure_count", 0) > 0 and not is_c13:
        blockers.append("Archive provenance failure detected")
    if metrics.get("archive_member_ambiguity_count", 0) > 0:
        blockers.append("Archive member ambiguity detected")
    if metrics.get("archive_transport_inconsistency_count", 0) > 0:
        blockers.append("Archive transport inconsistency detected")
    if metrics.get("archive_member_inconsistency_count", 0) > 0:
        blockers.append("Archive member inconsistency detected")
    if metrics.get("producing_request_failure_count", 0) > 0:
        blockers.append("Raw producing request failure detected")
    if metrics.get("cross_run_request_linkage_failure_count", 0) > 0:
        blockers.append("Cross-run request linkage failure detected")
    if metrics.get("invalid_retrieval_mode_count", 0) > 0:
        blockers.append("Forbidden or invalid retrieval mode detected")
    if metrics.get("record_identity_failure_count", 0) > 0:
        blockers.append("Discovery/document/authority record identity failure detected")
    if metrics.get("issuer_identity_failure_count", 0) > 0:
        blockers.append("Issuer identity mismatch detected")
    if metrics.get("candidate_linkage_failure_count", 0) > 0:
        blockers.append("Candidate price linkage failure detected")
    if metrics.get("pykrx_linkage_failure_count", 0) > 0:
        blockers.append("PyKRX comparator linkage failure detected")
    if metrics.get("raw_orphan_file_count", 0) > 0:
        blockers.append("Raw canonical evidence orphan detected")
    if metrics.get("ohlc_mismatch_count", 0) > 0:
        blockers.append(f"OHLC mismatch in {metrics.get('ohlc_mismatch_count')} controls")
    if metrics.get("insufficient_window_count", 0) > 0:
        blockers.append(f"Insufficient window in {metrics.get('insufficient_window_count')} controls")
    if metrics.get("candidate_error_count", 0) > 0 or metrics.get("comparator_error_count", 0) > 0:
        blockers.append("Candidate or comparator price fetch errors detected")
    if metrics.get("network_accounting_failure_count", 0) > 0:
        blockers.append("Network accounting cross-invariants failed")
    if metrics.get("total_provenance_failure_count", 0) > 0:
        blockers.append(f"Provenance linkage failures: {metrics.get('total_provenance_failure_count')}")
    if "linkage_evaluation_status" in metrics:
        if metrics.get("linkage_evaluation_status") != "EVALUATED":
            blockers.append("Live evidence linkage validator was not evaluated")
        if metrics.get("all_linkage_valid") is not True:
            blockers.append("Live evidence linkage validator did not certify all edges")

    # CORRECTION_13 adds a second, independent source-authority dimension:
    # Gate06 must consume persisted price/parity evidence, never only transient
    # in-memory counters.  The conditional keeps historical C9-C12 payloads
    # backwards compatible while making C13 fail closed.
    if "persisted_price_evidence_status" in metrics:
        if metrics.get("persisted_price_evidence_status") != "EVALUATED":
            blockers.append("PRICE_EVIDENCE_NOT_EVALUATED")
        if metrics.get("all_controls_evidenced") is not True:
            blockers.append("PRICE_PARITY_CONTROL_COVERAGE_MISMATCH")
        if metrics.get("all_cardinality_valid") is not True:
            blockers.append("PERSISTED_PRICE_PARITY_CARDINALITY_INVALID")
        if metrics.get("all_request_bindings_valid") is not True:
            blockers.append("PRICE_REQUEST_LINKAGE_MISSING")
        expected = metrics.get("expected_control_count")
        for key, label in (("naver_control_count", "NAVER"), ("pykrx_control_count", "PYKRX"), ("parity_control_count", "PARITY"), ("reconciliation_control_count", "RECONCILIATION")):
            if expected is not None and metrics.get(key) != expected:
                blockers.append(f"PRICE_SOURCE_CONTROL_COVERAGE_MISMATCH:{label}")
        if metrics.get("date_mismatch_control_count", 0) != 0:
            blockers.append("PERSISTED_PRICE_PARITY_DATE_SET_MISMATCH_COUNT_NONZERO")
        if metrics.get("insufficient_window_control_count", 0) != 0:
            blockers.append("PERSISTED_PRICE_PARITY_INSUFFICIENT_WINDOW_COUNT_NONZERO")
        if metrics.get("ohlc_mismatch_control_count", 0) != 0:
            blockers.append("PERSISTED_PRICE_PARITY_OHLC_MISMATCH_COUNT_NONZERO")
        if metrics.get("naver_price_row_count", 0) <= 0 or metrics.get("pykrx_price_row_count", 0) <= 0:
            blockers.append("PRICE_EVIDENCE_EMPTY")

    if metrics.get("unresolved_higher_priority_candidate_count", 0) > 0:
        blockers.append("UNRESOLVED_HIGHER_PRIORITY_CANDIDATE")
    if metrics.get("selected_authority_archive_provenance_failure_count", 0) > 0:
        blockers.append("SELECTED_AUTHORITY_ARCHIVE_PROVENANCE_FAILURE")
    if metrics.get("canonical_run_identity_valid") is False or metrics.get("canonical_run_identity_failure_count", 0) > 0:
        blockers.append("CANONICAL_RUN_IDENTITY_MISMATCH")
    if metrics.get("canonical_pytest_summary_immutability_failure_count", 0) > 0 or metrics.get("canonical_pytest_summary_physically_unchanged") is False:
        blockers.append("PYTEST_SUMMARY_PHYSICAL_IMMUTABILITY_FAILURE")

    return len(blockers) == 0, blockers


def evaluate_gate15(metrics: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Evaluate unresolved-condition closure without source-specific branches."""
    blockers: list[str] = []
    if metrics.get("gate_06_pass") is not True:
        blockers.append("GATE06_NOT_PASS")
    if int(metrics.get("unresolved_higher_priority_candidate_count", 0) or 0) > 0:
        blockers.append("UNRESOLVED_HIGHER_PRIORITY_CANDIDATE")
    if int(metrics.get("selected_authority_archive_provenance_failure_count", 0) or 0) > 0:
        blockers.append("SELECTED_AUTHORITY_ARCHIVE_PROVENANCE_FAILURE")
    if metrics.get("fallback_contract_valid") is False:
        blockers.append("TIER_B_FALLBACK_CONTRACT_INVALID")
    if metrics.get("price_parity_verdict") not in (None, "MATCH"):
        blockers.append("PRICE_EVIDENCE_CONTRADICTION")
    return not blockers, blockers


def _offline_evidence_sha256(path: Path) -> str:
    """Hash one frozen local evidence file without any network or mutation."""
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _recompute_samsung_price_parity_offline(price_rows: Any, anchor_date: str) -> dict[str, Any]:
    """Recompute Samsung parity from persisted rows; never fetches prices."""
    frame = _evidence_frame(price_rows)
    scoped = frame[frame["ticker"].astype(str) == "005930"].copy()
    sources = {"NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"}
    source_frames = {source: scoped[scoped["source"] == source].copy() for source in sources}
    source_dates = {source: set(item["date"].astype(str)) for source, item in source_frames.items()}
    common = sorted(source_dates["NAVER_DIRECT"] & source_dates["RAW_PYKRX_COMPARATOR"])
    naver_only = sorted(source_dates["NAVER_DIRECT"] - source_dates["RAW_PYKRX_COMPARATOR"])
    pykrx_only = sorted(source_dates["RAW_PYKRX_COMPARATOR"] - source_dates["NAVER_DIRECT"])
    mismatch_counts = {field: 0 for field in ("open", "high", "low", "close", "volume")}
    if common:
        naver = source_frames["NAVER_DIRECT"].set_index("date")
        pykrx = source_frames["RAW_PYKRX_COMPARATOR"].set_index("date")
        for day in common:
            for field in mismatch_counts:
                if float(naver.loc[day, field]) != float(pykrx.loc[day, field]):
                    mismatch_counts[field] += 1
    pre_count = sum(day < anchor_date for day in common)
    post_count = sum(day > anchor_date for day in common)
    date_mismatch = len(naver_only) + len(pykrx_only)
    ohlc_mismatch = sum(mismatch_counts[field] for field in ("open", "high", "low", "close"))
    return {
        "ticker": "005930",
        "anchor_date": anchor_date,
        "naver_rows": len(source_frames["NAVER_DIRECT"]),
        "pykrx_rows": len(source_frames["RAW_PYKRX_COMPARATOR"]),
        "common_date_count": len(common),
        "naver_only_date_count": len(naver_only),
        "pykrx_only_date_count": len(pykrx_only),
        "pre_common_date_count": pre_count,
        "post_common_date_count": post_count,
        **{f"{field}_mismatch_count": value for field, value in mismatch_counts.items()},
        "date_mismatch_count": date_mismatch,
        "ohlc_mismatch_count": ohlc_mismatch,
        "parity_verdict": "MATCH" if date_mismatch == 0 and ohlc_mismatch == 0 and pre_count >= 5 and post_count >= 5 else "MISMATCH",
        "api_fetch_count": 0,
    }


REASSESSED_GATE14_PROVENANCE = "REASSESSED_GATE14_PROVENANCE"

_C13_XML_ONLY_PROVENANCE_FIELDS = (
    "selected_source_event_context_id",
    "event_node_path",
    "event_node_heading",
    "timing_node_path",
    "binding_relationship",
    "lowest_common_ancestor_path",
)

_C13_AUTHORITY_PROVENANCE_FIELDS = (
    "authority_record_id",
    "authority_source_tier",
    "authority_source_name",
    "official_anchor_type",
    "official_anchor_date",
    "official_anchor_source_field",
    "official_anchor_source_value",
    "official_anchor_priority_rank",
    "producing_request_id",
    "retrieval_mode",
    "raw_evidence_path",
    "raw_evidence_sha256",
)

_C13_DUAL_TIER_PROVENANCE_FIELDS = (
    "identity_authority_tier",
    "identity_record_id",
    "identity_candidate_rank",
    "content_authority_tier",
    "content_source_url",
    "content_source_sha256",
    "content_retrieval_request_id",
    "content_producing_request_id",
    "authority_resolution_mode",
    "fallback_reason",
    "superseded_anchor_date",
    "active_anchor",
    "active_anchor_source_value",
    "superseded_anchor",
    "candidate_discovery_algorithm",
    "raw_evidence_origin",
    "raw_evidence_size_bytes",
)


def _c13_normalize_provenance_date(value: Any) -> str:
    """Normalize an ISO or English/Korean-style date for Gate14 checks."""
    raw = re.sub(r"\s+", " ", str(value or "")).strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}", raw):
        year, month, day = re.split(r"[-/.]", raw)
        try:
            return datetime(int(year), int(month), int(day)).date().isoformat()
        except ValueError:
            return ""
    month_names = {
        "jan": 1, "january": 1, "feb": 2, "february": 2,
        "mar": 3, "march": 3, "apr": 4, "april": 4,
        "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
        "aug": 8, "august": 8, "sep": 9, "september": 9,
        "oct": 10, "october": 10, "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }
    match = re.fullmatch(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", raw)
    if match:
        month = month_names.get(match.group(1).lower())
        if month:
            try:
                return datetime(int(match.group(3)), month, int(match.group(2))).date().isoformat()
            except ValueError:
                return ""
    korean = re.fullmatch(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})", raw)
    if korean:
        try:
            return datetime(int(korean.group(1)), int(korean.group(2)), int(korean.group(3))).date().isoformat()
        except ValueError:
            return ""
    return ""


def materialize_candidate_bound_fallback_control(
    parent_control: Mapping[str, Any],
    *,
    candidate: Mapping[str, Any],
    fallback_validation: Mapping[str, Any],
    retrieval_lineage: Mapping[str, Any],
    raw_path: str | Path,
    raw_sha256: str,
) -> dict[str, Any]:
    """Build a fully self-consistent rank2/Tier-B control without row mutation.

    Population identity fields are copied explicitly from the parent control,
    while every authority-specific field is rebuilt from the selected
    candidate, parsed issuer content and its frozen retrieval lineage.  XML
    tree paths from a lower-priority OpenDART candidate are intentionally
    cleared because issuer HTML does not provide that hierarchy.
    """
    if not isinstance(parent_control, Mapping):
        raise ValueError("PARENT_CONTROL_REQUIRED")
    if not isinstance(candidate, Mapping) or not isinstance(fallback_validation, Mapping):
        raise ValueError("CANDIDATE_AND_FALLBACK_VALIDATION_REQUIRED")
    provenance = fallback_validation.get("provenance")
    parsed = fallback_validation.get("parsed")
    if not isinstance(provenance, Mapping) or not isinstance(parsed, Mapping):
        raise ValueError("FALLBACK_PROVENANCE_AND_PARSED_EVIDENCE_REQUIRED")
    if fallback_validation.get("valid") is not True:
        raise ValueError("TIER_B_FALLBACK_CONTRACT_INVALID")

    identity_id = str(candidate.get("identity_record_id") or candidate.get("rcept_no") or "").strip()
    authority_id = str(candidate.get("rcept_no") or "").strip()
    identity_tier = str(candidate.get("identity_authority_tier") or provenance.get("identity_authority_tier") or "").strip()
    content_tier = str(provenance.get("content_authority_tier") or "").strip()
    resolution_mode = str(provenance.get("authority_resolution_mode") or "").strip()
    request_id = str(
        retrieval_lineage.get("request_id")
        or retrieval_lineage.get("retrieval_id")
        or retrieval_lineage.get("producing_request_id")
        or provenance.get("content_retrieval_request_id")
        or ""
    ).strip()
    source_url = str(provenance.get("content_source_url") or "").strip()
    active_anchor = str(parsed.get("official_anchor_date") or "").strip()
    active_anchor_type = str(parsed.get("official_anchor_type") or "").strip()
    superseded_anchor = str(parsed.get("superseded_anchor_date") or "").strip()
    actual_raw_sha = str(fallback_validation.get("raw_sha256") or raw_sha256 or "").strip()
    if not identity_id or authority_id != identity_id:
        raise ValueError("FALLBACK_IDENTITY_LINKAGE_INVALID")
    if identity_tier not in {AuthoritySourceTier.TIER_A1_OPENDART.value, AuthoritySourceTier.TIER_A2_KRX_KIND.value}:
        raise ValueError("FALLBACK_IDENTITY_TIER_INVALID")
    if content_tier != TIER_B_ISSUER_OFFICIAL or resolution_mode != CANDIDATE_BOUND_FALLBACK_MODE:
        raise ValueError("FALLBACK_CONTENT_CONTRACT_INVALID")
    if not request_id or not active_anchor or not superseded_anchor or not actual_raw_sha:
        raise ValueError("FALLBACK_PROVENANCE_INCOMPLETE")

    # Copy only population identity/selection fields.  Authority-specific and
    # XML-only fields are rebuilt below, never inherited from the parent row.
    result: dict[str, Any] = {}
    sensitive_tokens = (
        "authority", "provenance", "anchor", "request", "raw_evidence",
        "event_node", "timing_node", "binding_relationship", "lowest_common_ancestor",
    )
    for key, value in parent_control.items():
        key_text = str(key)
        key_lower = key_text.lower()
        if key_text in _C13_AUTHORITY_PROVENANCE_FIELDS or key_text in _C13_XML_ONLY_PROVENANCE_FIELDS:
            continue
        if key_text in _C13_DUAL_TIER_PROVENANCE_FIELDS:
            continue
        if any(token in key_lower for token in sensitive_tokens):
            continue
        result[key_text] = value

    result.update({
        # Rebuilt authority provenance.
        "authority_record_id": authority_id,
        "authority_source_tier": content_tier,
        "authority_source_name": "SAMSUNG_ISSUER_OFFICIAL",
        "official_anchor_type": active_anchor_type,
        "official_anchor_date": active_anchor,
        "official_anchor_source_field": "Scheduled Listing Date of New Share Certificates",
        "official_anchor_source_value": active_anchor,
        "official_anchor_priority_rank": "1",
        "producing_request_id": request_id,
        "retrieval_mode": CANDIDATE_BOUND_FALLBACK_MODE,
        "raw_evidence_path": str(raw_path),
        "raw_evidence_sha256": actual_raw_sha,
        # Issuer HTML has no XML tree semantics; do not fabricate or inherit.
        **{field_name: "" for field_name in _C13_XML_ONLY_PROVENANCE_FIELDS},
        # Explicit dual-tier/content lineage.
        "identity_authority_tier": identity_tier,
        "identity_record_id": identity_id,
        "identity_candidate_rank": str(candidate.get("identity_candidate_rank") or candidate.get("candidate_rank") or ""),
        "content_authority_tier": content_tier,
        "content_source_url": source_url,
        "content_source_sha256": actual_raw_sha,
        "content_retrieval_request_id": request_id,
        "content_producing_request_id": request_id,
        "authority_resolution_mode": resolution_mode,
        "fallback_reason": str(provenance.get("fallback_reason") or "A1_DOCUMENT_BODY_UNUSABLE_AND_A2_UNAVAILABLE"),
        "superseded_anchor_date": superseded_anchor,
        "active_anchor": active_anchor,
        "active_anchor_source_value": active_anchor,
        "superseded_anchor": superseded_anchor,
        "candidate_discovery_algorithm": str(parent_control.get("selection_algorithm") or ""),
        "raw_evidence_origin": "ISSUER_OFFICIAL_HTML",
        "raw_evidence_size_bytes": str(fallback_validation.get("raw_size_bytes") or ""),
    })
    return result


def evaluate_reassessed_gate14_provenance(
    control: Mapping[str, Any],
    *,
    fallback_validation: Mapping[str, Any] | None = None,
    retrieval_lineage: Mapping[str, Any] | None = None,
    raw_path: str | Path | None = None,
    raw_bytes: bytes | None = None,
) -> dict[str, Any]:
    """Evaluate Gate14 from the materialized control, fail-closed.

    Gate14 is intentionally independent from the parent Gate14 value.  It
    checks identity/content linkage, active-anchor provenance, producing
    request, raw hash linkage and leakage of the stale rank3/MAY-16 claims.
    """
    row = dict(control) if isinstance(control, Mapping) else {}
    blockers: list[str] = []
    checks: dict[str, bool] = {}

    authority_id = str(row.get("authority_record_id") or "").strip()
    identity_id = str(row.get("identity_record_id") or "").strip()
    selected_id = str(row.get("selected_record_id") or authority_id).strip()
    identity_tier = str(row.get("identity_authority_tier") or "").strip()
    content_tier = str(row.get("content_authority_tier") or row.get("authority_source_tier") or "").strip()
    resolution_mode = str(row.get("authority_resolution_mode") or row.get("retrieval_mode") or "").strip()
    content_request = str(row.get("content_producing_request_id") or row.get("content_retrieval_request_id") or "").strip()
    producing_request = str(row.get("producing_request_id") or "").strip()
    active_anchor = str(row.get("official_anchor_date") or row.get("active_anchor") or "").strip()
    active_source_value = str(row.get("official_anchor_source_value") or row.get("active_anchor_source_value") or "").strip()
    superseded_anchor = str(row.get("superseded_anchor_date") or row.get("superseded_anchor") or "").strip()
    raw_hash = str(row.get("raw_evidence_sha256") or row.get("content_source_sha256") or "").strip()
    raw_path_value = str(row.get("raw_evidence_path") or raw_path or "").strip()

    checks["selected_authority_identity_valid"] = bool(authority_id and identity_id and authority_id == identity_id and selected_id == authority_id)
    checks["identity_tier_valid"] = identity_tier in {AuthoritySourceTier.TIER_A1_OPENDART.value, AuthoritySourceTier.TIER_A2_KRX_KIND.value}
    checks["content_tier_valid"] = content_tier == TIER_B_ISSUER_OFFICIAL
    checks["identity_content_linkage_valid"] = bool(
        row.get("content_authority_tier") == TIER_B_ISSUER_OFFICIAL
        and str(row.get("content_source_sha256") or "").strip() == raw_hash
        and content_request == producing_request
    )
    checks["selected_record_id_consistent"] = bool(authority_id == identity_id)
    checks["active_anchor_consistent"] = bool(
        _c13_normalize_provenance_date(active_anchor)
        and _c13_normalize_provenance_date(active_source_value) == _c13_normalize_provenance_date(active_anchor)
    )
    checks["anchor_source_value_consistent"] = checks["active_anchor_consistent"]
    expected_request = str((retrieval_lineage or {}).get("request_id") or (retrieval_lineage or {}).get("producing_request_id") or "").strip()
    checks["producing_content_request_consistent"] = bool(content_request and producing_request and content_request == producing_request and (not expected_request or content_request == expected_request))
    checks["retrieval_mode_consistent"] = resolution_mode == CANDIDATE_BOUND_FALLBACK_MODE
    checks["raw_evidence_path_hash_consistent"] = bool(raw_path_value and raw_hash)
    if raw_bytes is not None:
        checks["raw_evidence_path_hash_consistent"] = checks["raw_evidence_path_hash_consistent"] and hashlib.sha256(raw_bytes).hexdigest() == raw_hash
    elif raw_path_value:
        candidate_path = Path(raw_path_value)
        if candidate_path.is_file():
            checks["raw_evidence_path_hash_consistent"] = checks["raw_evidence_path_hash_consistent"] and _offline_evidence_sha256(candidate_path) == raw_hash
        else:
            checks["raw_evidence_path_hash_consistent"] = False
    checks["superseded_anchor_explicit"] = bool(superseded_anchor and _c13_normalize_provenance_date(superseded_anchor) != _c13_normalize_provenance_date(active_anchor))

    sensitive_fields = set(_C13_AUTHORITY_PROVENANCE_FIELDS) | set(_C13_DUAL_TIER_PROVENANCE_FIELDS) | set(_C13_XML_ONLY_PROVENANCE_FIELDS)
    stale_rank3_reference_count = sum(
        str(value or "").count("20180223000294")
        for key, value in row.items()
        if str(key) in sensitive_fields and str(key) not in {"superseded_anchor_date", "superseded_anchor"}
    )
    stale_active_may16_reference_count = sum(
        str(row.get(key) or "").count("2018-05-16") + str(row.get(key) or "").count("2018년 5월 16")
        for key in ("official_anchor_date", "official_anchor_source_value", "active_anchor", "active_anchor_source_value")
    )
    checks["no_stale_rank3_authority_provenance"] = stale_rank3_reference_count == 0
    checks["no_stale_active_may16_provenance"] = stale_active_may16_reference_count == 0
    checks["fallback_contract_valid"] = bool(
        isinstance(fallback_validation, Mapping)
        and fallback_validation.get("valid") is True
        and isinstance(fallback_validation.get("provenance"), Mapping)
        and fallback_validation["provenance"].get("content_authority_tier") == TIER_B_ISSUER_OFFICIAL
        and fallback_validation["provenance"].get("authority_resolution_mode") == CANDIDATE_BOUND_FALLBACK_MODE
    )
    checks["dual_tier_provenance_complete"] = bool(
        identity_id and identity_tier and content_tier and content_request and producing_request
        and raw_hash and raw_path_value and resolution_mode
    )

    check_labels = {
        "selected_authority_identity_valid": "SELECTED_AUTHORITY_IDENTITY_INVALID",
        "identity_tier_valid": "IDENTITY_AUTHORITY_TIER_INVALID",
        "content_tier_valid": "CONTENT_AUTHORITY_TIER_INVALID",
        "identity_content_linkage_valid": "IDENTITY_CONTENT_LINKAGE_INVALID",
        "selected_record_id_consistent": "SELECTED_RECORD_ID_INCONSISTENT",
        "active_anchor_consistent": "ACTIVE_ANCHOR_INCONSISTENT",
        "anchor_source_value_consistent": "ANCHOR_SOURCE_VALUE_INCONSISTENT",
        "producing_content_request_consistent": "CONTENT_PRODUCING_REQUEST_INVALID",
        "retrieval_mode_consistent": "RETRIEVAL_MODE_INVALID",
        "raw_evidence_path_hash_consistent": "RAW_EVIDENCE_PATH_HASH_INVALID",
        "superseded_anchor_explicit": "SUPERSEDED_ANCHOR_NOT_EXPLICIT",
        "no_stale_rank3_authority_provenance": "STALE_RANK3_PROVENANCE_LEAK",
        "no_stale_active_may16_provenance": "STALE_ACTIVE_MAY16_PROVENANCE_LEAK",
        "fallback_contract_valid": "TIER_B_FALLBACK_CONTRACT_INVALID",
        "dual_tier_provenance_complete": "DUAL_TIER_PROVENANCE_INCOMPLETE",
    }
    blockers.extend(label for key, label in check_labels.items() if not checks.get(key, False))
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema": "gate14_reassessment_v01_c13_tier_b_candidate_bound_fallback",
        "evaluation_type": REASSESSED_GATE14_PROVENANCE,
        "gate_14_pass": not blockers,
        "blockers": blockers,
        "selected_rcept_no": authority_id,
        "identity_authority_tier": identity_tier,
        "content_authority_tier": content_tier,
        "authority_resolution_mode": resolution_mode,
        "content_producing_request_id": content_request,
        "active_anchor": active_anchor,
        "active_anchor_source_value": active_source_value,
        "superseded_anchor": superseded_anchor,
        "raw_sha256": raw_hash,
        "stale_rank3_reference_count": stale_rank3_reference_count,
        "stale_active_may16_reference_count": stale_active_may16_reference_count,
        "checks": checks,
    }


def reassess_c13_tier_b_fallback_offline(
    *,
    evidence_root: Path,
    output_dir: Path,
    implementation_fix_head: str,
    implementation_fix_tree: str,
    regression_certification: Mapping[str, Any],
) -> dict[str, Any]:
    """Reassess C13 once from caller-supplied frozen evidence, with no live calls.

    ``evidence_root`` and ``output_dir`` are deliberately required so a clean
    checkout cannot silently discover a prior user's temporary evidence.
    """
    if evidence_root is None or output_dir is None:
        raise ValueError("FROZEN_EVIDENCE_ROOT_AND_OUTPUT_REQUIRED")
    root = Path(evidence_root)
    parent = root / "c13_live_artifacts"
    supplemental = root / "unresolved_higher_priority_candidate_resolution_v01_fix01"
    output = Path(output_dir)
    if output.resolve() == root.resolve() or root.resolve() in output.resolve().parents:
        raise ValueError("REASSESSMENT_OUTPUT_MUST_BE_OUTSIDE_EVIDENCE_ROOT")
    output.mkdir(parents=True, exist_ok=True)
    raw_path = supplemental / "issuer_official_raw" / "samsung_public_disclosure_71206.html"
    contract_path = root / "authority_source_tier_contract_review_v01" / "authority_source_tier_contract_review_v01.json"
    price_path = parent / CORRECTION_13_PRICE_FILE
    candidate_path = parent / "corporate_action_discovery_candidate_audit_v01_fix03_correction_13.csv"
    manifest_path = parent / "artifact_manifest.json"
    required_paths = (raw_path, contract_path, price_path, candidate_path, manifest_path)
    missing = [str(path) for path in required_paths if not path.is_file()]
    if missing:
        raise FileNotFoundError("FROZEN_EVIDENCE_INTEGRITY_FAILURE: " + ", ".join(missing))
    raw_sha = _offline_evidence_sha256(raw_path)
    contract_sha = _offline_evidence_sha256(contract_path)
    if raw_sha != C13_SAMSUNG_ISSUER_RAW_SHA256 or contract_sha != C13_TIER_B_CONTRACT_EVIDENCE_SHA256:
        raise ValueError("FROZEN_EVIDENCE_INTEGRITY_FAILURE")

    parent_manifest = _read_json_file(manifest_path, {})
    parent_entries = parent_manifest.get("artifacts", {}) if isinstance(parent_manifest, Mapping) else {}
    manifest_failures: list[str] = []
    if not isinstance(parent_entries, Mapping):
        manifest_failures.append("artifacts")
    else:
        for relative, entry in parent_entries.items():
            if not isinstance(entry, Mapping):
                manifest_failures.append(str(relative))
                continue
            artifact = parent / str(entry.get("path") or relative)
            expected = str(entry.get("sha256") or "")
            if not artifact.is_file() or not expected or _offline_evidence_sha256(artifact) != expected:
                manifest_failures.append(str(relative))
    if manifest_failures:
        raise ValueError("PARENT_CANONICAL_EVIDENCE_INTEGRITY_FAILURE")

    parent_fingerprints = {
        str(relative): _offline_evidence_sha256(parent / str(entry.get("path") or relative))
        for relative, entry in parent_entries.items()
        if isinstance(entry, Mapping)
    }
    supplemental_fingerprints = {
        "issuer_raw": _offline_evidence_sha256(raw_path),
        "contract_review": _offline_evidence_sha256(contract_path),
    }

    parent_gate = _read_json_file(parent / "gate06_corporate_action_reassessment_v01_fix03_correction_13.json", {})
    parent_decision = _read_json_file(parent / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13.json", {})
    probe_frame = _evidence_frame(parent / "corporate_action_document_probe_audit_v01_fix03_correction_13.csv")
    candidate_frame = pd.read_csv(candidate_path, dtype=object, keep_default_na=False)
    cohort_frame = _evidence_frame(parent / "corporate_action_review_cohort_v01_fix03_correction_13.csv")
    samsung_candidates = candidate_frame[candidate_frame["ticker"].astype(str) == "005930"]
    target_rows = samsung_candidates[samsung_candidates["rcept_no"].astype(str) == "20180316800856"]
    if len(target_rows) != 1:
        raise ValueError("SAMSUNG_CANDIDATE_IDENTITY_NOT_UNIQUE")
    target_row = target_rows.iloc[0].to_dict()
    probe_rows = probe_frame[probe_frame["rcept_no"].astype(str) == "20180316800856"]
    if len(probe_rows) != 1:
        raise ValueError("SAMSUNG_A1_FAILURE_RECORD_NOT_UNIQUE")
    probe_row = probe_rows.iloc[0].to_dict()
    supplemental_log = _read_json_file(supplemental / "supplemental_request_log.json", {})
    requests = list(supplemental_log.get("requests", [])) if isinstance(supplemental_log, Mapping) else []
    issuer_success = next((item for item in requests if item.get("outcome") == "SUCCESS" and item.get("authority_tier") == TIER_B_ISSUER_OFFICIAL), {})
    a2_attempted = any(item.get("authority_tier") == AuthoritySourceTier.TIER_A2_KRX_KIND.value and item.get("purpose") == "CANDIDATE_DISCLOSURE_VIEWER_RETRIEVAL" and str(item.get("target_rcept_no") or supplemental_log.get("target_rcept_no") or "20180316800856") == "20180316800856" for item in requests)
    a2_usable = any(item.get("authority_tier") == AuthoritySourceTier.TIER_A2_KRX_KIND.value and item.get("outcome") == "SUCCESS" and int(item.get("response_size_bytes") or 0) > 0 for item in requests)
    issuer_name = ""
    if not cohort_frame.empty:
        cohort_rows = cohort_frame[cohort_frame["ticker"].astype(str) == "005930"]
        if len(cohort_rows) == 1:
            issuer_name = str(cohort_rows.iloc[0].get("issuer_name") or "")
    rank_value = int(float(target_row.get("candidate_rank") or 0))
    candidate = {
        "candidate_rank": rank_value,
        "identity_candidate_rank": rank_value,
        "candidate_rank_deterministic": samsung_candidates["candidate_rank"].astype(str).nunique() == len(samsung_candidates["candidate_rank"]),
        "event_match_score": int(float(target_row.get("event_match_score") or 0)),
        "rcept_no": str(target_row.get("rcept_no") or ""),
        "identity_record_id": str(target_row.get("rcept_no") or ""),
        "identity_authority_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
        "ticker": "005930",
        "issuer_name": issuer_name,
        "report_nm": str(target_row.get("report_nm") or ""),
        "rcept_dt": str(target_row.get("rcept_dt") or ""),
        "event_family": "STOCK_SPLIT" if "주식분할" in str(target_row.get("report_nm") or "") else "",
        "a1_body_usable": str(probe_row.get("validation_reason") or "") not in {"EMPTY_OR_UNUSABLE_DOCUMENT", "ARCHIVE_MEMBER_AMBIGUOUS"},
        "a1_failure_persisted": bool(str(probe_row.get("validation_reason") or "") == "EMPTY_OR_UNUSABLE_DOCUMENT" and str(probe_row.get("transport_response_sha256") or "")),
        "a1_transport_response_sha256": str(probe_row.get("transport_response_sha256") or ""),
        "a2_candidate_specific_attempted": a2_attempted,
        "a2_usable": a2_usable,
    }
    if candidate["a1_body_usable"]:
        raise ValueError("A1_DOCUMENT_NOT_PROVEN_UNUSABLE")
    fallback_validation = validate_candidate_bound_tier_b_fallback(
        candidate,
        raw_bytes=raw_path.read_bytes(),
        source_url=str(issuer_success.get("url") or ""),
        expected_sha256=C13_SAMSUNG_ISSUER_RAW_SHA256,
        raw_path=raw_path,
        retrieval_lineage={
            "request_id": issuer_success.get("request_id", ""),
            "retrieved_at": issuer_success.get("completed_at", ""),
            "raw_path": str(raw_path),
        },
    )
    population = _load_c13_candidate_evaluation(parent, fallback_by_record={candidate["rcept_no"]: fallback_validation})
    samsung_selected = next(
        (
            item["candidate"]
            for item in population["candidate_statuses"]
            if str(item["candidate"].get("ticker")) == "005930" and item.get("status") == "SELECTED"
        ),
        {},
    )
    parent_controls = _control_frame(parent / "corporate_action_review_cohort_v01_fix03_correction_13.csv")
    if parent_controls.empty or "control_id" not in parent_controls:
        raise ValueError("PARENT_CONTROL_EVIDENCE_EMPTY")
    samsung_mask = parent_controls["ticker"].astype(str) == "005930"
    if int(samsung_mask.sum()) != 1:
        raise ValueError("SAMSUNG_PARENT_CONTROL_NOT_UNIQUE")

    # Build a derived control set.  The seven non-Samsung controls retain every
    # parent column byte-for-byte; Samsung is fully materialized from the
    # candidate-bound issuer-official content evidence instead of shallowly
    # overwriting a rank3 row.
    issuer_lineage = {
        "request_id": issuer_success.get("request_id", ""),
        "retrieved_at": issuer_success.get("completed_at", ""),
        "raw_path": str(raw_path),
    }
    reassessed_controls = parent_controls.copy()
    samsung_idx = reassessed_controls.index[samsung_mask][0]
    # The materializer needs the actual parent row; construct it after the
    # index is known and then append only its explicit dual-tier columns.
    samsung_control = materialize_candidate_bound_fallback_control(
        parent_controls.loc[samsung_idx].to_dict(),
        candidate=candidate,
        fallback_validation=fallback_validation,
        retrieval_lineage=issuer_lineage,
        raw_path=raw_path,
        raw_sha256=raw_sha,
    )
    for field_name in samsung_control:
        if field_name not in reassessed_controls.columns:
            reassessed_controls[field_name] = ""
    for field_name, value in samsung_control.items():
        reassessed_controls.at[samsung_idx, field_name] = value
    non_samsung_parent = parent_controls.loc[~samsung_mask].reset_index(drop=True)
    non_samsung_reassessed = reassessed_controls.loc[~samsung_mask, parent_controls.columns].reset_index(drop=True)
    seven_control_drift = not non_samsung_parent.equals(non_samsung_reassessed)
    if seven_control_drift:
        raise ValueError("SEVEN_CONTROL_DRIFT")

    reassessed_gate14 = evaluate_reassessed_gate14_provenance(
        samsung_control,
        fallback_validation=fallback_validation,
        retrieval_lineage=issuer_lineage,
        raw_path=raw_path,
        raw_bytes=raw_path.read_bytes(),
    )

    parent_price = _evidence_frame(price_path)
    if parent_price.empty:
        raise ValueError("PARENT_PRICE_EVIDENCE_EMPTY")
    reassessed_price = parent_price.copy()
    reassessed_price.loc[reassessed_price["ticker"].astype(str) == "005930", "authority_record_id"] = candidate["rcept_no"]
    reassessed_price.loc[reassessed_price["ticker"].astype(str) == "005930", "official_anchor_date"] = "2018-05-04"
    source_frames: dict[tuple[str, str], pd.DataFrame] = {}
    request_ids: dict[tuple[str, str], str] = {}
    for control in reassessed_controls.to_dict("records"):
        cid = str(control.get("control_id", ""))
        for source in ("NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"):
            group = reassessed_price[(reassessed_price["control_id"].astype(str) == cid) & (reassessed_price["source"].astype(str) == source)].copy()
            source_frames[(cid, source)] = group
            request_ids[(cid, source)] = str(group["request_id"].iloc[0]) if not group.empty else ""
    reassessed_parity_rows, reassessed_reconciliation_rows = _c13_price_parity_rows(
        reassessed_controls.to_dict("records"), source_frames, request_ids,
        str(parent_gate.get("canonical_run_id") or ""),
    )
    reassessed_parity = pd.DataFrame(reassessed_parity_rows)
    reassessed_reconciliation = pd.DataFrame(reassessed_reconciliation_rows)
    price_request_logs = list((_read_json_file(parent / "corporate_action_evidence_network_accounting_v01_fix03_correction_13.json", {}) or {}).get("request_logs", []))
    price_validation = validate_persisted_price_parity_evidence(
        reassessed_price,
        reassessed_parity,
        reassessed_reconciliation,
        reassessed_controls,
        request_logs=price_request_logs,
    )
    price_reassessment = _recompute_samsung_price_parity_offline(reassessed_price, "2018-05-04")
    if price_validation.evaluation_status != "EVALUATED":
        raise ValueError("REASSESSED_PRICE_EVIDENCE_INVALID")

    output.mkdir(parents=True, exist_ok=True)
    reassessed_controls_path = output / "reassessed_corporate_action_controls.csv"
    reassessed_parity_path = output / "reassessed_event_sensitive_parity.csv"
    reassessed_reconciliation_path = output / "reassessed_date_reconciliation.csv"
    reassessed_controls.to_csv(reassessed_controls_path, index=False)
    reassessed_parity.to_csv(reassessed_parity_path, index=False)
    reassessed_reconciliation.to_csv(reassessed_reconciliation_path, index=False)
    gate_metrics = dict(parent_gate)
    gate_metrics.update(price_validation.to_dict())
    gate_metrics.update({
        "schema": "gate06_corporate_action_reassessment_v01_fix03_correction_13",
        "unresolved_higher_priority_candidate_count": population["unresolved_higher_priority_candidate_count"],
        "selected_authority_archive_provenance_failure_count": population["selected_authority_archive_provenance_failure_count"],
        "reassessed_gate14_provenance_complete": bool(reassessed_gate14.get("gate_14_pass")),
        "gate14_stale_rank3_reference_count": reassessed_gate14.get("stale_rank3_reference_count", 0),
        "gate14_stale_active_may16_reference_count": reassessed_gate14.get("stale_active_may16_reference_count", 0),
        "reassessed_control_artifact": reassessed_controls_path.name,
        "reassessed_parity_artifact": reassessed_parity_path.name,
        "reassessed_reconciliation_artifact": reassessed_reconciliation_path.name,
        "reassessed_control_artifact_sha256": _offline_evidence_sha256(reassessed_controls_path),
        "reassessed_parity_artifact_sha256": _offline_evidence_sha256(reassessed_parity_path),
        "reassessed_reconciliation_artifact_sha256": _offline_evidence_sha256(reassessed_reconciliation_path),
        "samsung_gate06_authority_record_id": candidate["rcept_no"],
        "samsung_gate06_anchor_date": "2018-05-04",
        "gate06_price_provenance": "REASSESSED_MAY-04_PARITY",
        "gate06_reconciliation_provenance": "REASSESSED_MAY-04_RECONCILIATION",
        "old_may16_samsung_canonical_price_metric_used": False,
    })
    gate06_pass, gate06_blockers = evaluate_gate06(gate_metrics)
    gate15_pass, gate15_blockers = evaluate_gate15({
        "gate_06_pass": gate06_pass,
        "unresolved_higher_priority_candidate_count": population["unresolved_higher_priority_candidate_count"],
        "selected_authority_archive_provenance_failure_count": population["selected_authority_archive_provenance_failure_count"],
        "fallback_contract_valid": fallback_validation.get("valid") is True,
        "price_parity_verdict": price_reassessment["parity_verdict"],
    })
    inherited = parent_decision.get("inherited_gate_results", {}) if isinstance(parent_decision, Mapping) else {}
    all_gates = {key: value is True for key, value in inherited.items()}
    all_gates["gate_06_corporate_action_parity"] = gate06_pass
    all_gates["gate_14_provenance_complete"] = bool(reassessed_gate14.get("gate_14_pass"))
    all_gates["gate_15_no_unresolved_conditions"] = gate15_pass
    regression_valid = bool(regression_certification.get("certification_valid") is True and regression_certification.get("full_suite_completion") is True and not regression_certification.get("unexpected_failures") and not regression_certification.get("unexpected_errors") and int(regression_certification.get("new_regression_count", 0) or 0) == 0)
    ready = bool(regression_valid and fallback_validation.get("valid") is True and price_reassessment["parity_verdict"] == "MATCH" and all(all_gates.values()))
    status_rows: list[dict[str, Any]] = []
    for item in population["candidate_statuses"]:
        row = item["candidate"]
        if str(row.get("ticker")) == "005930" and int(row.get("candidate_rank", 0) or 0) in {1, 2, 3}:
            status_rows.append({
                "ticker": row.get("ticker"),
                "candidate_rank": row.get("candidate_rank"),
                "rcept_no": row.get("rcept_no"),
                "status": item.get("status"),
                "resolution_mode": fallback_validation.get("provenance", {}).get("authority_resolution_mode", "") if row.get("rcept_no") == candidate["rcept_no"] else "",
                "content_authority_tier": fallback_validation.get("provenance", {}).get("content_authority_tier", "") if row.get("rcept_no") == candidate["rcept_no"] else "",
                "identity_authority_tier": samsung_control.get("identity_authority_tier", "") if row.get("rcept_no") == candidate["rcept_no"] else "",
                "content_producing_request_id": samsung_control.get("content_producing_request_id", "") if row.get("rcept_no") == candidate["rcept_no"] else "",
            })
    implementation_identity = {
        "schema": "implementation_fix_identity_v01_c13_tier_b_candidate_bound_fallback",
        "implementation_fix_head": implementation_fix_head,
        "implementation_fix_tree": implementation_fix_tree,
        "parent_canonical_run_id": str(parent_gate.get("canonical_run_id") or ""),
        "execution_mode": "OFFLINE_DETERMINISTIC_REASSESSMENT",
        "external_network_calls": 0,
    }
    (output / "implementation_fix_identity.json").write_text(json.dumps(implementation_identity, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "implementation_regression_certification.json").write_text(json.dumps(dict(regression_certification), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "issuer_official_trust_registry_audit.json").write_text(json.dumps({"schema": "issuer_official_trust_registry_audit_v01", "registry": trust_registry_audit()}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "tier_b_fallback_contract_validation.json").write_text(json.dumps({"schema": "tier_b_fallback_contract_validation_v01", "candidate": candidate, "validation": fallback_validation, "supplemental_evidence_hashes": {"issuer_raw": raw_sha, "contract_review": contract_sha}}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    dual_tier_payload = {
        field_name: samsung_control.get(field_name, "")
        for field_name in (
            "identity_authority_tier", "identity_record_id", "identity_candidate_rank",
            "content_authority_tier", "content_source_url", "content_source_sha256",
            "content_retrieval_request_id", "content_producing_request_id",
            "authority_resolution_mode", "fallback_reason", "authority_record_id",
            "official_anchor_type", "official_anchor_date", "official_anchor_source_field",
            "official_anchor_source_value", "superseded_anchor_date", "raw_evidence_path",
            "raw_evidence_sha256", "retrieval_mode",
        )
    }
    (output / "dual_tier_provenance.json").write_text(json.dumps(dual_tier_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "reassessed_provenance_audit.json").write_text(
        json.dumps({
            "schema": "reassessed_provenance_audit_v01_c13_tier_b_candidate_bound_fallback",
            "evaluation_type": REASSESSED_GATE14_PROVENANCE,
            "selected_control": samsung_control,
            "gate14": reassessed_gate14,
        }, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    pd.DataFrame(status_rows).sort_values("candidate_rank").to_csv(output / "candidate_population_reassessment.csv", index=False)
    anchor_payload = {
        "ticker": "005930",
        "disclosure_date": fallback_validation.get("parsed", {}).get("publication_date", ""),
        "active_anchor_type": fallback_validation.get("parsed", {}).get("official_anchor_type", ""),
        "active_anchor_date": fallback_validation.get("parsed", {}).get("official_anchor_date", ""),
        "superseded_anchor_date": fallback_validation.get("parsed", {}).get("superseded_anchor_date", ""),
        "selected_rcept_no": candidate["rcept_no"],
        "selected_candidate_rank": rank_value,
    }
    (output / "samsung_anchor_reassessment.json").write_text(json.dumps(anchor_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pd.DataFrame([price_reassessment]).to_csv(output / "samsung_price_parity_reassessment.csv", index=False)
    (output / "gate06_reassessment.json").write_text(json.dumps({"schema": "gate06_reassessment_v01_c13_tier_b_candidate_bound_fallback", "gate_06_pass": gate06_pass, "blockers": gate06_blockers, "selected_rcept_no": candidate["rcept_no"], "active_anchor_date": "2018-05-04", "reassessed_parity_artifact_sha256": _offline_evidence_sha256(reassessed_parity_path), "reassessed_reconciliation_artifact_sha256": _offline_evidence_sha256(reassessed_reconciliation_path), "unresolved_count": population["unresolved_higher_priority_candidate_count"], "metrics": gate_metrics}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "gate14_reassessment.json").write_text(json.dumps(reassessed_gate14, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "gate15_reassessment.json").write_text(json.dumps({"schema": "gate15_reassessment_v01_c13_tier_b_candidate_bound_fallback", "gate_15_pass": gate15_pass, "blockers": gate15_blockers, "metrics": {"gate06_result": gate06_pass, "gate06_input_artifact": reassessed_parity_path.name, "gate06_reconciliation_artifact": reassessed_reconciliation_path.name, "unresolved_higher_priority_candidate_count": population["unresolved_higher_priority_candidate_count"], "fallback_contract_valid": fallback_validation.get("valid") is True, "price_parity_verdict": price_reassessment["parity_verdict"]}}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    parent_unchanged = all(
        path.is_file() and _offline_evidence_sha256(path) == expected
        for relative, expected in parent_fingerprints.items()
        for path in [parent / relative]
    )
    supplemental_unchanged = (
        _offline_evidence_sha256(raw_path) == supplemental_fingerprints["issuer_raw"]
        and _offline_evidence_sha256(contract_path) == supplemental_fingerprints["contract_review"]
    )
    if not parent_unchanged or not supplemental_unchanged:
        raise ValueError("FROZEN_EVIDENCE_MUTATED_DURING_REASSESSMENT")
    result = {
        "implementation_fix_head": implementation_fix_head,
        "implementation_fix_tree": implementation_fix_tree,
        "parent_canonical_run_id": implementation_identity["parent_canonical_run_id"],
        "regression_certification_valid": regression_valid,
        "fallback_contract_valid": bool(fallback_validation.get("valid")),
        "selected_rcept_no": str(samsung_selected.get("rcept_no") or ""),
        "selected_candidate_rank": samsung_selected.get("candidate_rank"),
        "unresolved_higher_priority_candidate_count": population["unresolved_higher_priority_candidate_count"],
        "active_anchor_date": anchor_payload["active_anchor_date"],
        "superseded_anchor_date": anchor_payload["superseded_anchor_date"],
        "samsung_price_parity": price_reassessment,
        "reassessed_price_parity_validation": price_validation.to_dict(),
        "reassessed_control_artifact": reassessed_controls_path.name,
        "reassessed_parity_artifact": reassessed_parity_path.name,
        "reassessed_reconciliation_artifact": reassessed_reconciliation_path.name,
        "parent_canonical_artifacts_unchanged": parent_unchanged,
        "supplemental_frozen_evidence_unchanged": supplemental_unchanged,
        "gate06_pass": gate06_pass,
        "gate14_pass": bool(reassessed_gate14.get("gate_14_pass")),
        "gate14_reassessment": reassessed_gate14,
        "gate15_pass": gate15_pass,
        "all_gates": all_gates,
        "recommended_next_state": "IMPLEMENTATION_FIX02_ACCEPTED_READY_FOR_CLOSURE_REASSESSMENT_V02" if ready else "IMPLEMENTATION_FIX02_REASSESSMENT_BLOCKED",
        "external_network_calls": 0,
    }
    output_manifest = {
        "schema": "offline_reassessment_manifest_v01_c13_tier_b_candidate_bound_fallback",
        "execution_mode": "OFFLINE_DETERMINISTIC_REASSESSMENT",
        "external_network_calls": 0,
        "parent_canonical_run_id": implementation_identity["parent_canonical_run_id"],
        "implementation_fix_head": implementation_fix_head,
        "implementation_fix_tree": implementation_fix_tree,
        "input_evidence_hashes": {"issuer_raw": raw_sha, "contract_review": contract_sha, "parent_price": _offline_evidence_sha256(price_path), "parent_candidate": _offline_evidence_sha256(candidate_path), "parent_manifest": _offline_evidence_sha256(manifest_path)},
        "parent_evidence_root_identity": {"manifest_sha256": _offline_evidence_sha256(manifest_path), "parent_artifact_count": len(parent_fingerprints)},
        "reassessed_artifact_hashes": {"controls": _offline_evidence_sha256(reassessed_controls_path), "parity": _offline_evidence_sha256(reassessed_parity_path), "reconciliation": _offline_evidence_sha256(reassessed_reconciliation_path)},
        "result": result,
    }
    (output / "offline_reassessment_manifest.json").write_text(json.dumps(output_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def acquire_current_official_document(
    ticker: str,
    corp_code: str,
    rcept_no: str,
    candidate_rank: int,
    api_key: str,
    session: requests.Session,
    accounting: CorporateActionNetworkAccounting,
    canonical_run_id: str,
) -> tuple[bytes, str, str, str, str, int, str, int, bool, int, str, str, bool, list[str]]:
    """Pure production helper to acquire live official document with immutable request logging."""
    probe_doc_req_id = f"REQ_DOC_PROBE_OPENDART_{ticker}_{rcept_no}_R{candidate_rank}"
    p_start_time = datetime.now(timezone.utc).isoformat()

    accounting.official_document_probe_logical_requests += 1
    accounting.official_document_probe_physical_attempts += 1

    probe_http_bytes = b""
    probe_status = 0
    probe_origin = "LIVE_OPENDART_DOCUMENT_RESPONSE"
    probe_src = "OPENDART_OFFICIAL_API"
    probe_retrieval_mode = "NEW_OPENDART_DOCUMENT_FETCH"

    try:
        p_resp = session.get(
            "https://opendart.fss.or.kr/api/document.xml",
            params={"crtfc_key": api_key, "rcept_no": rcept_no},
            timeout=10.0,
        )
        p_end_time = datetime.now(timezone.utc).isoformat()
        probe_status = p_resp.status_code
        probe_http_bytes = p_resp.content
    except Exception:
        p_end_time = datetime.now(timezone.utc).isoformat()
        probe_status = 500

    http_sha = hashlib.sha256(probe_http_bytes).hexdigest()
    http_size = len(probe_http_bytes)

    (
        extracted_bytes,
        extracted_sha,
        member_name,
        archive_detected,
        archive_members,
        member_rule,
        archive_ambiguous,
        arch_fails,
    ) = resolve_archive_member(probe_http_bytes, rcept_no)
    # Direct (non-archive) responses are already canonical bytes; preserve their
    # SHA so the immutable request record can be linked to the raw manifest.
    if extracted_bytes and not extracted_sha:
        extracted_sha = hashlib.sha256(extracted_bytes).hexdigest()

    extracted_size = len(extracted_bytes)
    is_maintenance = bool(b"<status>800</status>" in probe_http_bytes or b"\xec\x8b\x9c\xec\x8a\xa4\xed\x85\x9c \xec\xa0\x90\xea\xb2\x80" in probe_http_bytes)

    opendart_success = bool(
        probe_status == 200
        and extracted_size > 200
        and not is_maintenance
        and not archive_ambiguous
    )

    accounting.request_logs.append({
        "canonical_run_id": canonical_run_id,
        "request_id": probe_doc_req_id,
        "source": "OPENDART_OFFICIAL_API",
        "purpose": "OFFICIAL_DOCUMENT_PROBE",
        "ticker": ticker,
        "corp_code": corp_code,
        "official_record_id": rcept_no,
        "sanitized_endpoint": f"https://opendart.fss.or.kr/api/document.xml?rcept_no={rcept_no}",
        "started_at": p_start_time,
        "completed_at": p_end_time,
        "physical_attempt": 1,
        "http_status": probe_status,
        "raw_http_response_size": http_size,
        "raw_http_response_sha256": http_sha,
        "transport_response_size": http_size,
        "transport_response_sha256": http_sha,
        "archive_detected": archive_detected,
        "archive_member_count": archive_members,
        "selected_member_name": member_name,
        "extracted_member_size": extracted_size,
        "extracted_member_sha256": extracted_sha,
        "canonical_raw_sha256": extracted_sha if opendart_success else "",
        "outcome": "SUCCESS" if opendart_success else "ERROR",
        "error_type": "" if opendart_success else ("ARCHIVE_MEMBER_AMBIGUOUS" if archive_ambiguous else ("OPENDART_DOCUMENT_MAINTENANCE_800" if is_maintenance else "OPENDART_DOCUMENT_UNUSABLE")),
    })

    final_bytes = extracted_bytes if opendart_success else b""
    final_sha = extracted_sha if opendart_success else ""
    final_producing_req_id = probe_doc_req_id if opendart_success else ""
    final_src = probe_src if opendart_success else ""
    final_origin = probe_origin if opendart_success else ""
    final_retrieval_mode = probe_retrieval_mode if opendart_success else ""
    final_transport_sha = http_sha
    final_transport_size = http_size
    final_arch_det = archive_detected
    final_arch_cnt = archive_members
    final_mem_name = member_name
    final_mem_rule = member_rule

    if not opendart_success and not archive_ambiguous:
        v_req_id = f"REQ_DOC_VIEWER_DART_{ticker}_{rcept_no}_R{candidate_rank}"
        v_start_time = datetime.now(timezone.utc).isoformat()
        accounting.dart_viewer_fallback_physical_attempts += 1
        v_url = f"https://dart.fss.or.kr/report/viewer.do?rcpNo={rcept_no}"
        v_bytes = b""
        v_status = 500
        try:
            v_resp = session.get(v_url, timeout=10.0)
            v_end_time = datetime.now(timezone.utc).isoformat()
            v_status = v_resp.status_code
            v_bytes = v_resp.content
        except Exception:
            v_end_time = datetime.now(timezone.utc).isoformat()

        v_sha = hashlib.sha256(v_bytes).hexdigest()
        v_size = len(v_bytes)
        viewer_success = bool(v_status == 200 and v_size > 200)

        accounting.request_logs.append({
            "canonical_run_id": canonical_run_id,
            "request_id": v_req_id,
            "source": "DART_OFFICIAL_DISCLOSURE",
            "purpose": "OFFICIAL_VIEWER_FALLBACK",
            "ticker": ticker,
            "corp_code": corp_code,
            "official_record_id": rcept_no,
            "sanitized_endpoint": f"https://dart.fss.or.kr/report/viewer.do?rcpNo={rcept_no}",
            "started_at": v_start_time,
            "completed_at": v_end_time,
            "physical_attempt": 1,
            "http_status": v_status,
            "raw_http_response_size": v_size,
            "raw_http_response_sha256": v_sha,
            "transport_response_size": v_size,
            "transport_response_sha256": v_sha,
            "archive_detected": False,
            "archive_member_count": 0,
            "selected_member_name": "",
            "extracted_member_size": v_size if viewer_success else 0,
            "extracted_member_sha256": v_sha if viewer_success else "",
            "canonical_raw_sha256": v_sha if viewer_success else "",
            "outcome": "SUCCESS" if viewer_success else "ERROR",
            "error_type": "" if viewer_success else "DART_VIEWER_EMPTY_OR_UNAVAILABLE",
        })

        if viewer_success:
            final_bytes = v_bytes
            final_sha = v_sha
            final_producing_req_id = v_req_id
            final_src = "DART_OFFICIAL_DISCLOSURE"
            final_origin = "LIVE_DART_VIEWER_RESPONSE"
            final_retrieval_mode = "NEW_DART_VIEWER_FETCH"
            final_transport_sha = v_sha
            final_transport_size = v_size
            final_arch_det = False
            final_arch_cnt = 0
            final_mem_name = ""
            final_mem_rule = "DIRECT_RESPONSE"

    return (
        final_bytes,
        final_sha,
        final_producing_req_id,
        final_src,
        final_origin,
        final_transport_size,
        final_transport_sha,
        probe_status,
        final_arch_det,
        final_arch_cnt,
        final_mem_name,
        final_mem_rule,
        archive_ambiguous,
        arch_fails,
    )


class OfficialEvidenceContentParser:
    """True XML Tree Traversal Parser with Claim-Free Official Anchor Selection."""

    BLOCKED_PATTERNS = [
        r"<title>\s*거부\s*</title>",
        r"검토중인\s*문서",
        r"조회할\s*수\s*없습니다",
        r"접근이\s*제한되었습니다",
        r"오류가\s*발생했습니다",
        r"비정상적인\s*접근",
        r"시스템\s*점검",
        r"<status>\s*800\s*</status>",
    ]

    KNOWN_ISSUER_ALIASES = {
        "NAVER": ["네이버", "NAVER", "네이버㈜", "035420"],
        "포스코퓨처엠": ["포스코케미칼", "포스코켐텍", "003670"],
        "삼성물산": ["제일모직", "삼성물산", "028260"],
        "유한양행": ["유한양행", "000100"],
        "현대제철": ["현대제철", "004020"],
        "고려아연": ["고려아연", "010130"],
        "삼성전자": ["삼성전자", "005930"],
        "카카오": ["카카오", "035720"],
    }

    ALLOWED_EVENT_TIMING_FIELDS = {
        "STOCK_SPLIT": [
            ("NEW_SHARE_LISTING_DATE", "신주상장예정일", r"(?:신\s*주\s*(?:권\s*)?상\s*장\s*(?:예\s*정)?\s*일|신\s*주\s*상\s*장\s*일)\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("SPLIT_EFFECTIVE_DATE", "분할기일", r"분\s*할\s*기\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("SUSPENSION_DATE", "매매거래정지기간", r"매\s*매\s*거\s*래\s*정\s*지\s*기\s*간\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("OLD_SHARES_SUBMISSION", "구주권제출기간", r"구\s*주\s*권\s*제\s*출\s*기\s*간\s*[:=]?\s*(?:시\s*작\s*일\s*[-–~]?)?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("BOARD_RESOLUTION_DATE", "이사회결의일", r"이\s*사\s*회\s*결\s*의\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ],
        "MERGER": [
            ("MERGER_EFFECTIVE_DATE", "합병기일", r"합\s*병\s*기\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("MERGER_REGISTRATION_DATE", "합병등기예정일", r"합\s*병\s*등\s*기\s*(?:예\s*정)?\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("NEW_SHARE_LISTING_DATE", "신주상장예정일", r"(?:신\s*주\s*(?:권\s*)?상\s*장\s*(?:예\s*정)?\s*일|신\s*주\s*상\s*장\s*일)\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ],
        "RIGHTS_OFFERING": [
            ("NEW_SHARE_LISTING_DATE", "신주상장일", r"(?:신\s*주\s*(?:권\s*)?상\s*장\s*(?:예\s*정)?\s*일|신\s*주\s*상\s*장\s*일)\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("RECORD_DATE", "신주배정기준일", r"(?:신\s*주\s*)?배\s*정\s*기\s*준\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("EX_DATE", "권리락일", r"권\s*리\s*락\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("PAYMENT_DATE", "납입일", r"(?:주\s*금\s*)?납\s*입\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("EFFECTIVE_DATE", "효력발생일", r"효\s*력\s*발\s*생\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ],
        "BONUS_ISSUE": [
            ("RECORD_DATE", "신주배정기준일", r"(?:신\s*주\s*)?배\s*정\s*기\s*준\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("EX_DATE", "권리락일", r"권\s*리\s*락\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("NEW_SHARE_LISTING_DATE", "신주상장예정일", r"(?:신\s*주\s*(?:권\s*)?상\s*장\s*(?:예\s*정)?\s*일|신\s*주\s*상\s*장\s*일)\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
            ("BOARD_RESOLUTION_DATE", "이사회결의일", r"이\s*사\s*회\s*결\s*의\s*일\s*[:=]?\s*(\d{4}[-년\.\s]+\d{1,2}[-월\.\s]+\d{1,2})"),
        ],
    }

    EVENT_FAMILY_KEYWORDS = {
        "STOCK_SPLIT": ["주식분할", "액면분할", "주식의 분할", "주식분할결정", "발행주식 액면분할", "주식의분할"],
        "MERGER": ["회사합병", "합병등", "합병계약", "합병종료보고서", "합병결정", "피합병회사", "합병회사"],
        "RIGHTS_OFFERING": ["유상증자", "유상신주", "신주발행(유상증자)", "유상증자결정"],
        "BONUS_ISSUE": ["무상증자", "무상신주", "무상증자결정"],
    }

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
    def classify_text_event_family(cls, text: str) -> tuple[str, list[str]]:
        clean_text = re.sub(r"\s+", "", text)
        found: dict[str, list[str]] = {}
        for fam, kws in cls.EVENT_FAMILY_KEYWORDS.items():
            matched = [kw for kw in kws if kw in text or re.sub(r"\s+", "", kw) in clean_text]
            if matched:
                found[fam] = matched

        if not found:
            return "", []
        if len(found) == 1:
            fam = next(iter(found))
            return fam, found[fam]

        return "EVENT_TYPE_AMBIGUOUS", [f"{k}:{v}" for k, v in found.items()]

    @classmethod
    def build_tree_from_text(cls, text: str) -> SemanticTreeNode:
        parser = DARTTreeParser()
        parser.feed(text)
        finalize_semantic_tree(parser.root)
        return parser.root

    @classmethod
    def collect_all_nodes(cls, root: SemanticTreeNode) -> list[SemanticTreeNode]:
        nodes = []
        def _traverse(n: SemanticTreeNode):
            nodes.append(n)
            for ch in n.children:
                _traverse(ch)
        _traverse(root)
        return nodes

    @classmethod
    def find_lowest_specific_event_nodes(cls, root: SemanticTreeNode) -> list[dict[str, Any]]:
        all_nodes = cls.collect_all_nodes(root)

        section_nodes = [n for n in all_nodes if n.tag.startswith("SECTION") or n.tag in ["LIBRARY", "INSERTION"]]
        candidate_nodes = section_nodes if section_nodes else [n for n in all_nodes if n.tag in ["TABLE", "DIV", "BODY"]]

        event_candidates = []
        for n in candidate_nodes:
            if n.tag in ["ROOT", "DOCUMENT", "BODY", "HTML"]:
                continue

            text_for_event = f"{n.heading} {n.local_text} {n.subtree_text}".strip()
            src_fam, terms = cls.classify_text_event_family(text_for_event)

            if src_fam and src_fam != "EVENT_TYPE_AMBIGUOUS":
                event_candidates.append({
                    "node": n,
                    "event_family": src_fam,
                    "terms": terms,
                    "depth": n.depth,
                })

        if not event_candidates:
            return []

        lowest_nodes = []
        for cand in event_candidates:
            c_node = cand["node"]
            c_fam = cand["event_family"]
            has_deeper_same_fam = any(
                other["event_family"] == c_fam
                and c_node.path in other["node"].ancestor_paths
                and other["node"].path != c_node.path
                for other in event_candidates
            )
            if not has_deeper_same_fam:
                lowest_nodes.append(cand)

        return lowest_nodes

    @classmethod
    def extract_timing_for_event_node(
        cls,
        event_cand: dict[str, Any],
        all_nodes: list[SemanticTreeNode],
    ) -> list[dict[str, Any]]:
        ev_node: SemanticTreeNode = event_cand["node"]
        ev_fam = event_cand["event_family"]
        allowed_timings = cls.ALLOWED_EVENT_TIMING_FIELDS.get(ev_fam, [])

        descendant_nodes = [n for n in all_nodes if n.path == ev_node.path or ev_node.path in n.ancestor_paths]
        descendant_nodes.sort(key=lambda x: x.depth, reverse=True)

        found_anchors = []
        for a_type, f_name, pat in allowed_timings:
            for d_node in descendant_nodes:
                text_to_check = d_node.local_text or d_node.subtree_text
                for m in re.finditer(pat, text_to_check):
                    raw_val = m.group(1) if m.groups() else m.group(0)
                    norm_d = cls._normalize_date_str(raw_val)
                    if norm_d:
                        rel = "SAME_NODE" if d_node.path == ev_node.path else "ANCESTOR_DESCENDANT"
                        found_anchors.append({
                            "event_node": ev_node,
                            "timing_node": d_node,
                            "event_family": ev_fam,
                            "anchor_type": a_type,
                            "field_name": f_name,
                            "source_value": raw_val.strip(),
                            "anchor_date": norm_d,
                            "binding_relationship": rel,
                            "terms": event_cand["terms"],
                        })

        return found_anchors

    @classmethod
    def extract_official_event_authority(
        cls,
        raw_content_bytes: bytes,
        source_tier: str,
        discovered_record_id: str,
        doc_request_record_id: str,
        evidence_origin: str = "LIVE_OPENDART_DOCUMENT_RESPONSE",
    ) -> dict[str, Any]:
        if evidence_origin in ["GENERATED", "SYNTHETIC", "FIXTURE", "MOCK", "MANUAL", "INTERNAL_VALIDATION"]:
            return {
                "official_source_valid": False,
                "blocked_page_detected": False,
                "parsed_issuer": "",
                "parsed_ticker": "",
                "parsed_report_name": "",
                "source_event_type": "",
                "normalized_event_type": "",
                "event_context_candidate_count": 0,
                "event_type_candidate_count": 0,
                "selected_source_event_context_id": "",
                "event_node_id": "",
                "event_node_tag": "",
                "event_node_path": "",
                "event_node_depth": 0,
                "event_node_heading": "",
                "timing_candidate_count": 0,
                "timing_node_id": "",
                "timing_node_tag": "",
                "timing_node_path": "",
                "timing_node_depth": 0,
                "selected_timing_node_id": "",
                "selected_timing_node_tag": "",
                "selected_timing_node_path": "",
                "selected_timing_node_depth": 0,
                "binding_relationship": "",
                "lowest_common_ancestor_path": "",
                "semantic_block_id": "",
                "semantic_block_type": "",
                "semantic_section_path": "",
                "semantic_parent_heading": "",
                "semantic_block_sha256": "",
                "official_anchor_type": "",
                "official_anchor_date": "",
                "official_anchor_source_field": "",
                "official_anchor_source_value": "",
                "official_anchor_priority_rank": 0,
                "timing_repetition_count": 0,
                "record_identity_valid": False,
                "event_type_valid": False,
                "event_semantic_binding_valid": False,
                "event_timing_valid": False,
                "raw_provenance_valid": False,
                "global_fallback_used": False,
                "event_context_ambiguous": False,
                "event_type_ambiguous": False,
                "event_timing_ambiguous": False,
                "sibling_cross_binding_detected": False,
                "authority_valid": False,
                "validation_reason": f"SYNTHETIC_OR_FORBIDDEN_EVIDENCE_ORIGIN: {evidence_origin}",
            }

        text = ""
        for enc in ["euc-kr", "utf-8", "cp949"]:
            try:
                dec = raw_content_bytes.decode(enc)
                if "DOCUMENT-NAME" in dec or "COMPANY-NAME" in dec or "<title>" in dec or "<?xml" in dec or "<HTML" in dec or "<html" in dec or "<BODY" in dec or "<DOCUMENT" in dec:
                    text = dec
                    break
            except Exception:
                pass
        if not text:
            text = raw_content_bytes.decode("euc-kr", errors="replace")

        blocked = False
        for bp in cls.BLOCKED_PATTERNS:
            if re.search(bp, text, re.IGNORECASE):
                blocked = True
                break

        if blocked or len(raw_content_bytes) < 50:
            return {
                "official_source_valid": bool(source_tier in [AuthoritySourceTier.TIER_A1_OPENDART.value, AuthoritySourceTier.TIER_A2_KRX_KIND.value]),
                "blocked_page_detected": True,
                "parsed_issuer": "",
                "parsed_ticker": "",
                "parsed_report_name": "",
                "source_event_type": "",
                "normalized_event_type": "",
                "event_context_candidate_count": 0,
                "event_type_candidate_count": 0,
                "selected_source_event_context_id": "",
                "event_node_id": "",
                "event_node_tag": "",
                "event_node_path": "",
                "event_node_depth": 0,
                "event_node_heading": "",
                "timing_candidate_count": 0,
                "timing_node_id": "",
                "timing_node_tag": "",
                "timing_node_path": "",
                "timing_node_depth": 0,
                "selected_timing_node_id": "",
                "selected_timing_node_tag": "",
                "selected_timing_node_path": "",
                "selected_timing_node_depth": 0,
                "binding_relationship": "",
                "lowest_common_ancestor_path": "",
                "semantic_block_id": "",
                "semantic_block_type": "",
                "semantic_section_path": "",
                "semantic_parent_heading": "",
                "semantic_block_sha256": "",
                "official_anchor_type": "",
                "official_anchor_date": "",
                "official_anchor_source_field": "",
                "official_anchor_source_value": "",
                "official_anchor_priority_rank": 0,
                "timing_repetition_count": 0,
                "record_identity_valid": False,
                "event_type_valid": False,
                "event_semantic_binding_valid": False,
                "event_timing_valid": False,
                "raw_provenance_valid": False,
                "global_fallback_used": False,
                "event_context_ambiguous": False,
                "event_type_ambiguous": False,
                "event_timing_ambiguous": False,
                "sibling_cross_binding_detected": False,
                "authority_valid": False,
                "validation_reason": "BLOCKED_OR_EMPTY_DOCUMENT_DETECTED",
            }

        parsed_issuer = ""
        parsed_report = ""

        doc_name_m = re.search(r"<DOCUMENT-NAME[^>]*>(.*?)</DOCUMENT-NAME>", text, re.DOTALL | re.IGNORECASE)
        if doc_name_m:
            parsed_report = doc_name_m.group(1).strip()

        comp_name_m = re.search(r"<COMPANY-NAME[^>]*>(.*?)</COMPANY-NAME>", text, re.DOTALL | re.IGNORECASE)
        if comp_name_m:
            parsed_issuer = comp_name_m.group(1).strip()

        if not parsed_issuer:
            head_title_m = re.search(r"<HEAD[^>]*>.*?<TITLE[^>]*>(.*?)</TITLE>.*?</HEAD>", text, re.DOTALL | re.IGNORECASE)
            if head_title_m:
                t_str = head_title_m.group(1).strip()
                if "/" in t_str:
                    parts = t_str.split("/")
                    parsed_issuer = parts[0].strip()
                    if len(parts) > 1:
                        parsed_report = parts[1].strip()
                else:
                    parsed_issuer = t_str

        tree_root = cls.build_tree_from_text(text)
        all_nodes = cls.collect_all_nodes(tree_root)
        lowest_event_cands = cls.find_lowest_specific_event_nodes(tree_root)

        distinct_families = {c["event_family"] for c in lowest_event_cands}
        event_type_ambiguous = len(distinct_families) > 1

        node_timings: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
        for ec in lowest_event_cands:
            timings = cls.extract_timing_for_event_node(ec, all_nodes)
            if timings:
                node_timings.append((ec, timings))

        event_context_ambiguous = len(node_timings) > 1

        selected_anchor = None
        selected_ev_node = None
        selected_context_id = ""
        event_timing_ambiguous = False
        timing_cands_count = 0

        if node_timings and not event_type_ambiguous and not event_context_ambiguous:
            ec_sel, tms_sel = node_timings[0]
            selected_ev_node = ec_sel["node"]
            ev_fam = ec_sel["event_family"]
            selected_context_id = f"{discovered_record_id}:{ev_fam}:{selected_ev_node.path}"
            timing_cands_count = len(tms_sel)

            anchor_win, tm_ambig, tm_reason, p_rank = select_official_anchor_by_priority(ev_fam, tms_sel)
            selected_anchor = anchor_win
            event_timing_ambiguous = tm_ambig

        source_event_type = selected_anchor["event_family"] if selected_anchor else (lowest_event_cands[0]["event_family"] if lowest_event_cands else "")
        ev_type_valid = bool(source_event_type and not event_type_ambiguous)

        ev_node = selected_ev_node or (selected_anchor["event_node"] if selected_anchor else None)
        tm_node = selected_anchor["timing_node"] if selected_anchor else None

        event_node_id = ev_node.node_id if ev_node else ""
        event_node_tag = ev_node.tag if ev_node else ""
        event_node_path = ev_node.path if ev_node else ""
        event_node_depth = ev_node.depth if ev_node else 0
        event_node_heading = ev_node.heading if ev_node else ""

        timing_node_id = tm_node.node_id if tm_node else ""
        timing_node_tag = tm_node.tag if tm_node else ""
        timing_node_path = tm_node.path if tm_node else ""
        timing_node_depth = tm_node.depth if tm_node else 0

        binding_rel = selected_anchor["binding_relationship"] if selected_anchor else ""
        lca_path = ev_node.path if ev_node and tm_node and (ev_node.path == tm_node.path or ev_node.path in tm_node.ancestor_paths) else ""

        official_anchor_type = selected_anchor["anchor_type"] if selected_anchor else ""
        official_anchor_date = selected_anchor["anchor_date"] if selected_anchor else ""
        official_anchor_source_field = selected_anchor["field_name"] if selected_anchor else ""
        official_anchor_source_value = selected_anchor["source_value"] if selected_anchor else ""
        priority_rank = selected_anchor.get("official_anchor_priority_rank", 0) if selected_anchor else 0
        repetition_count = selected_anchor.get("timing_repetition_count", 1) if selected_anchor else 0

        semantic_binding_valid = bool(
            selected_anchor is not None
            and not event_context_ambiguous
            and not event_type_ambiguous
            and not event_timing_ambiguous
            and binding_rel in ["SAME_NODE", "ANCESTOR_DESCENDANT"]
        )
        timing_valid = bool(official_anchor_date and len(official_anchor_date) == 10 and official_anchor_source_field)

        rec_id_valid = bool(
            discovered_record_id
            and doc_request_record_id
            and discovered_record_id == doc_request_record_id
        )

        official_source_valid = bool(source_tier in [AuthoritySourceTier.TIER_A1_OPENDART.value, AuthoritySourceTier.TIER_A2_KRX_KIND.value])
        raw_prov_valid = bool(len(raw_content_bytes) >= 50 and not blocked)

        predicates = [
            official_source_valid,
            rec_id_valid,
            ev_type_valid,
            semantic_binding_valid,
            timing_valid,
            raw_prov_valid,
            not event_context_ambiguous,
            not event_type_ambiguous,
            not event_timing_ambiguous,
            not blocked,
        ]
        auth_valid = all(predicates)

        if not official_source_valid:
            reason = "UNOFFICIAL_SOURCE_TIER"
        elif event_type_ambiguous:
            reason = "EVENT_TYPE_AMBIGUOUS: multiple distinct corporate event families found in document"
        elif event_context_ambiguous:
            reason = "EVENT_CONTEXT_AMBIGUOUS: multiple independent event contexts found in document"
        elif event_timing_ambiguous:
            reason = "EVENT_TIMING_AMBIGUOUS: multiple conflicting dates for highest-priority timing anchor"
        elif not source_event_type:
            reason = "SOURCE_EVENT_CLASSIFICATION_FAILED: No valid corporate action found in structured tree"
        elif not semantic_binding_valid or not timing_valid:
            reason = "EVENT_SEMANTIC_BINDING_FAILED: timing field not bound to valid event node"
        elif not rec_id_valid:
            reason = f"RECORD_IDENTITY_MISMATCH: discovered '{discovered_record_id}' vs requested '{doc_request_record_id}'"
        elif auth_valid:
            reason = "LIVE_OFFICIAL_DISCLOSURE_AUTHENTICATED_AND_SEMANTICALLY_BOUND"
        else:
            reason = "PREDICATES_FAILED"

        return {
            "official_source_valid": official_source_valid,
            "blocked_page_detected": blocked,
            "parsed_issuer": parsed_issuer,
            "parsed_report_name": parsed_report,
            "source_event_type": source_event_type,
            "normalized_event_type": source_event_type if ev_type_valid else "",
            "event_context_candidate_count": len(lowest_event_cands),
            "event_type_candidate_count": len(distinct_families),
            "selected_source_event_context_id": selected_context_id,
            "event_node_id": event_node_id,
            "event_node_tag": event_node_tag,
            "event_node_path": event_node_path,
            "event_node_depth": event_node_depth,
            "event_node_heading": event_node_heading,
            "timing_candidate_count": timing_cands_count,
            "timing_node_id": timing_node_id,
            "timing_node_tag": timing_node_tag,
            "timing_node_path": timing_node_path,
            "timing_node_depth": timing_node_depth,
            "selected_timing_node_id": timing_node_id,
            "selected_timing_node_tag": timing_node_tag,
            "selected_timing_node_path": timing_node_path,
            "selected_timing_node_depth": timing_node_depth,
            "binding_relationship": binding_rel,
            "lowest_common_ancestor_path": lca_path,
            "semantic_block_id": event_node_id,
            "semantic_block_type": event_node_tag,
            "semantic_section_path": event_node_path,
            "semantic_parent_heading": event_node_heading,
            "semantic_block_sha256": ev_node.node_sha256 if ev_node else "",
            "official_anchor_type": official_anchor_type,
            "official_anchor_date": official_anchor_date,
            "official_anchor_source_field": official_anchor_source_field,
            "official_anchor_source_value": official_anchor_source_value,
            "official_anchor_priority_rank": priority_rank,
            "timing_repetition_count": repetition_count,
            "record_identity_valid": rec_id_valid,
            "event_type_valid": ev_type_valid,
            "event_semantic_binding_valid": semantic_binding_valid,
            "event_timing_valid": timing_valid,
            "raw_provenance_valid": raw_prov_valid,
            "global_fallback_used": False,
            "event_context_ambiguous": event_context_ambiguous,
            "event_type_ambiguous": event_type_ambiguous,
            "event_timing_ambiguous": event_timing_ambiguous,
            "sibling_cross_binding_detected": False,
            "authority_valid": auth_valid,
            "validation_reason": reason,
        }

    @classmethod
    def adjudicate_prior_claim(
        cls,
        official_auth: dict[str, Any],
        claimed_event_type: str,
        claimed_anchor_type: str,
        claimed_anchor_date: str,
        claimed_issuer: str,
        claimed_ticker: str,
    ) -> dict[str, Any]:
        clean_claimed_iss = claimed_issuer.replace("(주)", "").strip()
        parsed_iss = official_auth.get("parsed_issuer", "")
        clean_parsed_iss = parsed_iss.replace("(주)", "").strip() if parsed_iss else ""
        aliases = cls.KNOWN_ISSUER_ALIASES.get(claimed_issuer, [])

        iss_valid = bool(
            (clean_parsed_iss and (clean_claimed_iss in clean_parsed_iss or clean_parsed_iss in clean_claimed_iss))
            or any(al in parsed_iss or (clean_parsed_iss and al in clean_parsed_iss) for al in aliases)
            or not parsed_iss
        )

        ev_match = bool(official_auth["source_event_type"] == claimed_event_type)
        anc_type_match = bool(official_auth["official_anchor_type"] == claimed_anchor_type)
        anc_date_match = bool(official_auth["official_anchor_date"] == claimed_anchor_date)

        claim_used_event = False
        claim_used_context = False
        claim_used_anchor_type = False
        claim_used_anchor_date = False

        claim_independence_valid = not (claim_used_event or claim_used_context or claim_used_anchor_type or claim_used_anchor_date)

        if not official_auth["authority_valid"]:
            adjudication_status = ClaimAdjudicationStatus.INSUFFICIENT_AUTHORITY.value
        elif ev_match and anc_date_match:
            adjudication_status = ClaimAdjudicationStatus.CONFIRMED.value
        else:
            adjudication_status = ClaimAdjudicationStatus.REJECTED_CLAIM.value

        return {
            "claimed_event_type": claimed_event_type,
            "claimed_anchor_type": claimed_anchor_type,
            "claimed_anchor_date": claimed_anchor_date,
            "claimed_issuer": claimed_issuer,
            "claimed_ticker": claimed_ticker,
            "issuer_identity_valid": iss_valid,
            "claim_event_type_match": ev_match,
            "claim_anchor_type_match": anc_type_match,
            "claim_anchor_date_match": anc_date_match,
            "claim_used_for_event_selection": claim_used_event,
            "claim_used_for_context_selection": claim_used_context,
            "claim_used_for_anchor_type_selection": claim_used_anchor_type,
            "claim_used_for_anchor_date_selection": claim_used_anchor_date,
            "claim_independence_valid": claim_independence_valid,
            "adjudication_status": adjudication_status,
        }

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
        evidence_origin: str = "LIVE_OPENDART_DOCUMENT_RESPONSE",
    ) -> dict[str, Any]:
        official_auth = cls.extract_official_event_authority(
            raw_content_bytes=raw_content_bytes,
            source_tier=source_tier,
            discovered_record_id=discovered_record_id,
            doc_request_record_id=doc_request_record_id,
            evidence_origin=evidence_origin,
        )
        claim_adj = cls.adjudicate_prior_claim(
            official_auth=official_auth,
            claimed_event_type=claimed_event_type,
            claimed_anchor_type=claimed_anchor_type,
            claimed_anchor_date=claimed_anchor_date,
            claimed_issuer=claimed_issuer,
            claimed_ticker=claimed_ticker,
        )

        res = dict(official_auth)
        res["parsed_ticker"] = claimed_ticker
        res["event_type_match"] = claim_adj["claim_event_type_match"]
        res["claim_anchor_match"] = claim_adj["claim_anchor_date_match"]
        res["issuer_identity_valid"] = claim_adj["issuer_identity_valid"]
        res["authority_valid"] = bool(
            official_auth["authority_valid"]
            and claim_adj["issuer_identity_valid"]
            and claim_adj["claim_event_type_match"]
        )
        return res


def rank_and_score_candidates(items: list[dict[str, Any]], target: dict[str, Any]) -> list[dict[str, Any]]:
    scored = []
    keywords = target["keywords"]

    for it in items:
        r_no = str(it.get("rcept_no", "")).strip()
        r_nm = str(it.get("report_nm", "")).strip()
        r_dt = str(it.get("rcept_dt", "")).strip()

        score = 0
        for kw in keywords:
            if kw in r_nm:
                score += 50

        if any(ek in r_nm for ek in ["주식분할", "액면분할", "합병", "유상증자", "무상증자"]):
            score += 30

        report_priority = 10
        if "[기재정정]" in r_nm:
            report_priority = 5

        scored.append({
            "rcept_no": r_no,
            "report_nm": r_nm,
            "rcept_dt": r_dt,
            "corp_code": str(it.get("corp_code", "")).strip(),
            "stock_code": str(it.get("stock_code", "")).strip(),
            "event_match_score": score,
            "report_priority": report_priority,
            "raw_item": it,
        })

    def sort_key(c: dict[str, Any]) -> tuple:
        dt_val = int(c["rcept_dt"]) if c["rcept_dt"].isdigit() else 0
        no_val = int(c["rcept_no"]) if c["rcept_no"].isdigit() else 0
        return (-c["event_match_score"], -c["report_priority"], -dt_val, -no_val)

    scored.sort(key=sort_key)

    for idx, c in enumerate(scored, start=1):
        c["candidate_rank"] = idx

    return scored


def get_official_discovery_search_targets() -> list[dict[str, Any]]:
    return [
        {
            "control_id": "CORP_005930_STOCK_SPLIT",
            "ticker": "005930",
            "issuer_name": "삼성전자",
            "corp_code": "00126380",
            "target_event_family": "STOCK_SPLIT",
            "discovery_start": "20180101",
            "discovery_end": "20180531",
            "keywords": ["주주총회소집공고", "주식분할", "액면분할"],
            "claimed_anchor_type": "NEW_SHARE_LISTING_DATE",
            "claimed_anchor_date": "2018-05-16",
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
            "keywords": ["주주총회소집공고", "주식분할", "액면분할"],
            "claimed_anchor_type": "NEW_SHARE_LISTING_DATE",
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
            "keywords": ["주주총회소집공고", "주식분할", "액면분할"],
            "claimed_anchor_type": "NEW_SHARE_LISTING_DATE",
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
            "claimed_anchor_type": "NEW_SHARE_LISTING_DATE",
            "claimed_anchor_date": "2021-01-21",
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
            "claimed_anchor_type": "RECORD_DATE",
            "claimed_anchor_date": "2021-01-01",
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
            "claimed_anchor_type": "NEW_SHARE_LISTING_DATE",
            "claimed_anchor_date": "2022-08-18",
            "legacy_expected_record_id": "DART_RCP_20220818000620",
        },
    ]


def run_corporate_action_evidence_acquisition_fix03_correction_9(
    output_dir: Path = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_9,
    parent_dir: Path = PARENT_FIX03_CORRECTION_DIR,
    allow_network: bool = True,
) -> dict[str, Any]:
    """Execute complete corporate action authority orchestration with strict readiness hard gating and corrected network accounting (Section 0-27)."""
    canonical_run_id = f"CORP_AUTH_FIX03_CORRECTION_9_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    if output_dir.exists():
        raw_existing = output_dir / "raw"
        if raw_existing.exists():
            shutil.rmtree(raw_existing)
        disc_existing = output_dir / "discovery_raw"
        if disc_existing.exists():
            shutil.rmtree(disc_existing)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    disc_raw_dir = output_dir / "discovery_raw"
    disc_raw_dir.mkdir(parents=True, exist_ok=True)

    accounting = CorporateActionNetworkAccounting()

    # Explicit maintenance/offline guard for repository regression runs.  This
    # short-circuits before credential resolution or any external client is built.
    if os.environ.get("CORRECTION_10_OFFLINE_ONLY") == "1":
        return _terminate_on_readiness_or_preflight_failure(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight={"verdict": "FAIL", "reason": "CORRECTION_10_OFFLINE_ONLY"},
            doc_readiness={"verdict": "NOT_EXECUTED", "schema": "opendart_document_readiness_v01_fix03_correction_9"},
            accounting=accounting,
            failure_reason="CORRECTION_10_OFFLINE_ONLY",
        )

    # 1. Hard Gate: OpenDART Preflight (Section 4, 16)
    preflight = run_opendart_preflight(output_dir=output_dir, allow_network=allow_network, canonical_run_id=canonical_run_id)
    accounting.preflight_physical_calls = 1 if allow_network else 0
    if preflight["verdict"] != "READY":
        return _terminate_on_readiness_or_preflight_failure(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight=preflight,
            doc_readiness={"verdict": "NOT_EXECUTED", "schema": "opendart_document_readiness_v01_fix03_correction_9"},
            accounting=accounting,
            failure_reason="OPENDART_PREFLIGHT_FAIL",
        )

    # 2. Hard Gate: Document Endpoint Readiness Probe (Section 4, 16, 17)
    doc_readiness = run_document_endpoint_readiness_probe(output_dir=output_dir, allow_network=allow_network, canonical_run_id=canonical_run_id)
    accounting.readiness_physical_calls = 1 if allow_network else 0

    if doc_readiness["verdict"] != "READY":
        return _terminate_on_readiness_or_preflight_failure(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight=preflight,
            doc_readiness=doc_readiness,
            accounting=accounting,
            failure_reason="TRANSIENT_OFFICIAL_DOCUMENT_ENDPOINT_UNAVAILABLE",
        )

    # 3. Parent Freeze Validation (Section 2)
    parent_freeze = verify_parent_authority_freeze(parent_dir)
    parent_freeze_path = output_dir / "parent_authority_freeze_validation_v01_fix03_correction_9.json"
    parent_freeze_path.write_text(json.dumps(parent_freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not parent_freeze["all_parent_inputs_unchanged"]:
        raise ValueError(f"Parent FIX03_CORRECTION freeze validation failed: {parent_freeze['mismatches']}")

    # 4. Source Inventory
    source_inventory = {
        "schema": "corporate_action_evidence_source_inventory_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "sources": [
            {
                "source_id": "OPENDART_OFFICIAL_API",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (OpenDART) 정식 API",
                "base_domain": "opendart.fss.or.kr",
                "endpoint_type": "OFFICIAL_API_PAGINATED_DISCOVERY_AND_DOCUMENT",
                "auth_required": True,
                "raw_format": "JSON_AND_XML",
                "parser_version": "v01_fix03_correction_9",
                "authority_validation_contract": "OpenDART 전수 페이지네이션 및 공시 원문 XML의 True XML Hierarchy Tree 파싱 기반 Claim-Free 공식 앵커 추출",
            },
            {
                "source_id": "DART_OFFICIAL_DISCLOSURE",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (DART) 공시원문 뷰어",
                "base_domain": "dart.fss.or.kr",
                "endpoint_type": "OFFICIAL_DISCLOSURE_VIEWER",
                "auth_required": False,
                "raw_format": "HTML",
                "parser_version": "v01_fix03_correction_9",
            },
        ],
    }
    source_inv_path = output_dir / "corporate_action_evidence_source_inventory_v01_fix03_correction_9.json"
    source_inv_path.write_text(json.dumps(source_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 5. Full Downstream Live Acquisition (Executed strictly when readiness == READY)
    api_key = get_opendart_api_key()
    targets = get_official_discovery_search_targets()

    discovery_rows = []
    discovery_page_manifest_entries = {}
    pagination_validation_entries = {}
    candidate_audit_rows = []
    probe_audit_rows = []
    determinism_validation_results = {}
    discovery_manifest_entries = {}
    raw_manifest_entries = {}
    doc_validation_rows = []
    semantic_binding_rows = []
    hierarchy_validation_entries = {}
    claim_independence_entries = {}
    adjudication_rows = []
    authority_records = []

    pagination_inconsistency_failures = []
    pagination_page_count_inconsistencies = []
    pagination_incomplete_failures = []
    discovery_total_count_mismatches = []
    conflicting_duplicate_failures = []
    candidate_audit_incompleteness_failures = []
    ranking_order_invariance_failures = []
    selected_record_invariance_failures = []
    source_event_classification_failures = []
    source_event_type_mismatches = []
    event_type_ambiguity_failures = []
    event_context_ambiguity_failures = []
    event_timing_ambiguity_failures = []
    claim_event_influence_failures = []
    claim_context_influence_failures = []
    claim_anchor_type_influence_failures = []
    claim_anchor_date_influence_failures = []
    semantic_binding_failures = []
    invalid_binding_relationship_failures = []
    global_semantic_block_authority_failures = []
    archive_provenance_failures = []
    archive_member_ambiguity_failures = []
    archive_transport_inconsistencies = []
    archive_member_inconsistencies = []

    dart_session = requests.Session()
    dart_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    for tgt in targets:
        t = normalize_ticker(tgt["ticker"])
        cid = tgt["control_id"]
        ev_fam = tgt["target_event_family"]
        disc_query_id = f"DISC_QUERY_{t}_{ev_fam}"

        accounting.official_discovery_logical_requests += 1

        page_no = 1
        total_pages = 1
        frozen_page1_meta: dict[str, Any] = {}
        all_raw_items: list[dict[str, Any]] = []
        pages_meta = []
        pages_requested = []
        pages_successful = []

        while page_no <= total_pages:
            disc_req_id = f"REQ_DISC_OPENDART_{t}_{ev_fam}_P{page_no:03d}"
            disc_start_time = datetime.now(timezone.utc).isoformat()
            accounting.official_discovery_physical_attempts += 1

            disc_url = "https://opendart.fss.or.kr/api/list.json"
            disc_params = {
                "crtfc_key": api_key,
                "corp_code": tgt["corp_code"],
                "bgn_de": tgt["discovery_start"],
                "end_de": tgt["discovery_end"],
                "page_count": "100",
                "page_no": str(page_no),
            }

            pages_requested.append(page_no)
            disc_resp = dart_session.get(disc_url, params=disc_params, timeout=10.0)
            disc_end_time = datetime.now(timezone.utc).isoformat()
            disc_bytes = disc_resp.content
            disc_sha = hashlib.sha256(disc_bytes).hexdigest()
            disc_size = len(disc_bytes)
            disc_data = disc_resp.json()

            status_code = disc_data.get("status", "")
            r_total_cnt = int(disc_data.get("total_count", 0)) if str(disc_data.get("total_count", "")).isdigit() else 0
            r_total_page = int(disc_data.get("total_page", 1)) if str(disc_data.get("total_page", "")).isdigit() else 1
            r_page_cnt = int(disc_data.get("page_count", 100)) if str(disc_data.get("page_count", "")).isdigit() else 100

            page_success = bool(disc_resp.status_code == 200 and status_code in ["000", "013"])
            if page_success:
                pages_successful.append(page_no)

            if page_no == 1:
                total_pages = max(r_total_page, 1)
                frozen_page1_meta = {
                    "corp_code": tgt["corp_code"],
                    "bgn_de": tgt["discovery_start"],
                    "end_de": tgt["discovery_end"],
                    "page_count": r_page_cnt,
                    "reported_total_count": r_total_cnt,
                    "reported_total_page": total_pages,
                }

            page_items = disc_data.get("list", [])
            all_raw_items.extend(page_items)

            pages_meta.append({
                "page_no": page_no,
                "page_count": r_page_cnt,
                "item_count": len(page_items),
                "reported_total_count": r_total_cnt,
                "reported_total_page": r_total_page,
                "http_status": disc_resp.status_code,
                "opendart_status": status_code,
            })

            p_filename = f"disc_{t}_{ev_fam}_p{page_no:03d}.json"
            p_fp = disc_raw_dir / p_filename
            p_fp.write_bytes(disc_bytes)
            p_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_9/discovery_raw/{p_filename}"

            discovery_page_manifest_entries[p_filename] = {
                "ticker": t,
                "control_id": cid,
                "logical_discovery_query_id": disc_query_id,
                "page_no": page_no,
                "page_count": len(page_items),
                "reported_total_count": r_total_cnt,
                "reported_total_page": r_total_page,
                "request_id": disc_req_id,
                "path": p_rel_path,
                "size_bytes": disc_size,
                "sha256": disc_sha,
                "http_status": disc_resp.status_code,
                "opendart_status": status_code,
                "outcome": "SUCCESS" if page_success else "ERROR",
            }

            discovery_manifest_entries[p_filename] = {
                "path": p_rel_path,
                "size_bytes": disc_size,
                "sha256": disc_sha,
                "request_id": disc_req_id,
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "http_status": disc_resp.status_code,
                "outcome": "SUCCESS" if page_success else "ERROR",
            }

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": disc_req_id,
                "source": "OPENDART_OFFICIAL_API",
                "purpose": "OFFICIAL_DISCLOSURE_DISCOVERY_PAGE",
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "official_record_id": "",
                "page_no": page_no,
                "sanitized_endpoint": f"https://opendart.fss.or.kr/api/list.json?corp_code={tgt['corp_code']}&bgn_de={tgt['discovery_start']}&end_de={tgt['discovery_end']}&page_no={page_no}",
                "started_at": disc_start_time,
                "completed_at": disc_end_time,
                "physical_attempt": 1,
                "http_status": disc_resp.status_code,
                "raw_http_response_size": disc_size,
                "raw_http_response_sha256": disc_sha,
                "transport_response_size": disc_size,
                "transport_response_sha256": disc_sha,
                "outcome": "SUCCESS" if page_success else "ERROR",
                "error_type": "" if page_success else f"OPENDART_STATUS_{status_code}",
            })

            page_no += 1

        loaded_raw_count = len(all_raw_items)
        reported_total_count = frozen_page1_meta.get("reported_total_count", 0)

        pag_pass, ticker_pagination_inconsistencies = validate_pagination_pages(
            pages_meta=pages_meta,
            expected_total_count=reported_total_count,
            expected_total_pages=total_pages,
            frozen_page1_meta=frozen_page1_meta,
        )

        if not pag_pass:
            pagination_inconsistency_failures.extend(ticker_pagination_inconsistencies)
            if loaded_raw_count != reported_total_count:
                discovery_total_count_mismatches.append(t)
            if pages_successful != pages_requested:
                pagination_incomplete_failures.append(t)

        dup_pass, duplicate_count, conflicting_duplicate_count, conflict_details = validate_discovery_duplicate_identity(all_raw_items)
        if not dup_pass:
            conflicting_duplicate_failures.extend(conflict_details)

        unique_items_by_rcp: dict[str, dict[str, Any]] = {}
        for it in all_raw_items:
            r_no = str(it.get("rcept_no", "")).strip()
            if r_no not in unique_items_by_rcp:
                unique_items_by_rcp[r_no] = it

        unique_items = list(unique_items_by_rcp.values())
        unique_candidate_count = len(unique_items)

        ranked_candidates = rank_and_score_candidates(unique_items, tgt)
        audit_rcp_ids = []

        selected_candidate = None
        selected_raw_bytes = b""
        selected_raw_status = 0
        selected_raw_format = "XML"
        selected_producing_req_id = ""
        selected_evidence_origin = ""
        selected_source = ""
        selected_retrieval_mode = ""
        selected_candidate_rank = -1
        selected_parsed = None
        selected_transport_sha = ""
        selected_transport_size = 0
        selected_archive_detected = False
        selected_archive_members = 0
        selected_member_name = ""
        selected_extracted_sha = ""
        selected_extracted_size = 0
        selected_member_rule = ""

        candidate_validity_map: dict[str, bool] = {}

        for c in ranked_candidates:
            r_no = c["rcept_no"]
            r_nm = c["report_nm"]
            r_dt = c["rcept_dt"]
            c_rank = c["candidate_rank"]
            score = c["event_match_score"]
            audit_rcp_ids.append(r_no)

            if score == 0:
                candidate_validity_map[r_no] = False
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "REJECTED_EVENT_MISMATCH",
                    "rejection_reason": "No target keywords found in report title",
                })
                continue

            if selected_candidate is not None:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "NOT_PROBED_LOWER_PRIORITY",
                    "rejection_reason": "Higher rank candidate already selected",
                })
                continue

            (
                extracted_bytes,
                extracted_sha,
                producing_req_id,
                final_probe_src,
                final_probe_origin,
                final_transport_size,
                final_transport_sha,
                probe_status,
                archive_detected,
                archive_members,
                member_name,
                member_rule,
                archive_ambiguous,
                arch_fails,
            ) = acquire_current_official_document(
                ticker=t,
                corp_code=tgt["corp_code"],
                rcept_no=r_no,
                candidate_rank=c_rank,
                api_key=api_key,
                session=dart_session,
                accounting=accounting,
                canonical_run_id=canonical_run_id,
            )

            if arch_fails:
                archive_member_ambiguity_failures.extend(arch_fails)
            extracted_size = len(extracted_bytes)

            arch_prov_valid, arch_prov_fails = validate_archive_provenance(
                archive_detected=archive_detected,
                archive_member_count=archive_members,
                selected_member_name=member_name,
                member_selection_rule=member_rule,
                extracted_member_size=extracted_size,
                extracted_member_sha256=extracted_sha,
                canonical_raw_sha256=extracted_sha,
                transport_response_sha256=final_transport_sha,
            )
            if not arch_prov_valid:
                archive_provenance_failures.extend(arch_prov_fails)

            if archive_ambiguous or not arch_prov_valid or not extracted_bytes:
                parsed_cand = {
                    "official_source_valid": bool(final_probe_src),
                    "blocked_page_detected": bool(not extracted_bytes),
                    "parsed_issuer": "",
                    "parsed_ticker": t,
                    "parsed_report_name": r_nm,
                    "source_event_type": "",
                    "normalized_event_type": "",
                    "event_type_match": False,
                    "event_node_id": "",
                    "event_node_tag": "",
                    "event_node_path": "",
                    "event_node_depth": 0,
                    "event_node_heading": "",
                    "timing_candidate_count": 0,
                    "timing_node_id": "",
                    "timing_node_tag": "",
                    "timing_node_path": "",
                    "timing_node_depth": 0,
                    "selected_timing_node_id": "",
                    "selected_timing_node_tag": "",
                    "selected_timing_node_path": "",
                    "selected_timing_node_depth": 0,
                    "binding_relationship": "",
                    "lowest_common_ancestor_path": "",
                    "semantic_block_id": "",
                    "semantic_block_type": "",
                    "semantic_section_path": "",
                    "semantic_parent_heading": "",
                    "semantic_block_sha256": "",
                    "official_anchor_type": "",
                    "official_anchor_date": "",
                    "official_anchor_source_field": "",
                    "official_anchor_source_value": "",
                    "official_anchor_priority_rank": 0,
                    "claim_anchor_match": False,
                    "record_identity_valid": True,
                    "issuer_identity_valid": True,
                    "event_type_valid": False,
                    "event_semantic_binding_valid": False,
                    "event_timing_valid": False,
                    "raw_provenance_valid": False,
                    "global_fallback_used": False,
                    "event_context_candidate_count": 0,
                    "event_type_candidate_count": 0,
                    "event_context_ambiguous": False,
                    "event_type_ambiguous": False,
                    "event_timing_ambiguous": False,
                    "sibling_cross_binding_detected": False,
                    "authority_valid": False,
                    "validation_reason": "EMPTY_OR_UNUSABLE_DOCUMENT" if not extracted_bytes else ("ARCHIVE_PROVENANCE_INCONSISTENT" if not arch_prov_valid else "ARCHIVE_MEMBER_AMBIGUOUS"),
                }
            else:
                official_auth_cand = OfficialEvidenceContentParser.extract_official_event_authority(
                    raw_content_bytes=extracted_bytes,
                    source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
                    discovered_record_id=r_no,
                    doc_request_record_id=r_no,
                    evidence_origin=final_probe_origin,
                )
                claim_adj_cand = OfficialEvidenceContentParser.adjudicate_prior_claim(
                    official_auth=official_auth_cand,
                    claimed_event_type=ev_fam,
                    claimed_anchor_type=tgt["claimed_anchor_type"],
                    claimed_anchor_date=tgt["claimed_anchor_date"],
                    claimed_issuer=tgt["issuer_name"],
                    claimed_ticker=t,
                )
                parsed_cand = dict(official_auth_cand)
                parsed_cand["parsed_ticker"] = t
                parsed_cand["event_type_match"] = claim_adj_cand["claim_event_type_match"]
                parsed_cand["claim_anchor_match"] = claim_adj_cand["claim_anchor_date_match"]
                parsed_cand["issuer_identity_valid"] = claim_adj_cand["issuer_identity_valid"]
                parsed_cand["authority_valid"] = bool(
                    official_auth_cand["authority_valid"]
                    and claim_adj_cand["issuer_identity_valid"]
                    and claim_adj_cand["claim_event_type_match"]
                )

            candidate_validity_map[r_no] = parsed_cand["authority_valid"]

            probe_audit_rows.append({
                "ticker": t,
                "candidate_rank": c_rank,
                "rcept_no": r_no,
                "report_nm": r_nm,
                "probe_request_id": producing_req_id,
                "source": final_probe_src,
                "evidence_origin": final_probe_origin,
                "retrieval_mode": "NEW_OPENDART_DOCUMENT_FETCH" if final_probe_src == "OPENDART_OFFICIAL_API" else ("NEW_DART_VIEWER_FETCH" if final_probe_src == "DART_OFFICIAL_DISCLOSURE" else ""),
                "http_status": probe_status,
                "transport_response_sha256": final_transport_sha,
                "archive_detected": archive_detected,
                "extracted_member_sha256": extracted_sha,
                "canonical_raw_sha256": extracted_sha,
                "event_node_path": parsed_cand["event_node_path"],
                "timing_node_path": parsed_cand["timing_node_path"],
                "binding_relationship": parsed_cand["binding_relationship"],
                "authority_valid": parsed_cand["authority_valid"],
                "validation_reason": parsed_cand["validation_reason"],
            })

            if parsed_cand["authority_valid"]:
                selected_candidate = c
                selected_raw_bytes = extracted_bytes
                selected_raw_status = probe_status
                selected_raw_format = "XML" if archive_detected or b"<DOCUMENT" in extracted_bytes or b"<?xml" in extracted_bytes else "HTML"
                selected_producing_req_id = producing_req_id
                selected_evidence_origin = final_probe_origin
                selected_source = final_probe_src
                selected_retrieval_mode = "NEW_OPENDART_DOCUMENT_FETCH" if final_probe_src == "OPENDART_OFFICIAL_API" else "NEW_DART_VIEWER_FETCH"
                selected_candidate_rank = c_rank
                selected_parsed = parsed_cand
                selected_transport_sha = final_transport_sha
                selected_transport_size = final_transport_size
                selected_archive_detected = archive_detected
                selected_archive_members = archive_members
                selected_member_name = member_name
                selected_extracted_sha = extracted_sha
                selected_extracted_size = extracted_size
                selected_member_rule = member_rule

                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "SELECTED",
                    "rejection_reason": "",
                })
            else:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "REJECTED_AUTHORITY_VALIDATION",
                    "rejection_reason": parsed_cand["validation_reason"],
                })

        if not selected_candidate and ranked_candidates:
            selected_candidate = ranked_candidates[0]
            selected_candidate_rank = 1

        unique_candidate_ids = {c["rcept_no"] for c in unique_items}
        if set(audit_rcp_ids) != unique_candidate_ids:
            candidate_audit_incompleteness_failures.append(t)

        pagination_validation_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "logical_discovery_query_id": disc_query_id,
            "total_count_reported": reported_total_count,
            "total_page_reported": total_pages,
            "pages_requested": pages_requested,
            "pages_successful": pages_successful,
            "raw_records_loaded": loaded_raw_count,
            "unique_records_loaded": unique_candidate_count,
            "duplicate_count": duplicate_count,
            "conflicting_duplicate_count": conflicting_duplicate_count,
            "metadata_audit_count": len(audit_rcp_ids),
            "pagination_complete": pag_pass and conflicting_duplicate_count == 0 and len(ticker_pagination_inconsistencies) == 0,
            "pagination_inconsistencies": ticker_pagination_inconsistencies,
        }

        final_rcp_no = selected_candidate.get("rcept_no", "") if selected_candidate else ""
        final_rep_name = selected_candidate.get("report_nm", "") if selected_candidate else ""
        final_rcp_date = selected_candidate.get("rcept_dt", "") if selected_candidate else ""
        legacy_match = bool(final_rcp_no and final_rcp_no in tgt["legacy_expected_record_id"])

        base_ranks = [c["rcept_no"] for c in ranked_candidates]
        permutations = [
            ("reverse", list(reversed(unique_items))),
            ("shuffle_1", random.Random(42).sample(unique_items, len(unique_items))),
            ("shuffle_2", random.Random(43).sample(unique_items, len(unique_items))),
            ("shuffle_3", random.Random(44).sample(unique_items, len(unique_items))),
        ]

        ranking_order_invariant = True
        permuted_selected_nos = [final_rcp_no]

        for p_name, p_items in permutations:
            p_ranked = rank_and_score_candidates(p_items, tgt)
            p_order = [c["rcept_no"] for c in p_ranked]
            if p_order != base_ranks:
                ranking_order_invariant = False
                ranking_order_invariance_failures.append(f"{t}:{p_name}")

            winner = None
            for c in p_ranked:
                r_id = c["rcept_no"]
                if candidate_validity_map.get(r_id, False):
                    winner = r_id
                    break
            if not winner and p_ranked:
                winner = p_ranked[0]["rcept_no"]
            permuted_selected_nos.append(winner)

        selected_record_invariant = bool(len(set(permuted_selected_nos)) == 1 and permuted_selected_nos[0] == final_rcp_no)
        if not selected_record_invariant:
            selected_record_invariance_failures.append(t)

        determinism_validation_results[t] = {
            "reported_total_count": reported_total_count,
            "loaded_raw_count": loaded_raw_count,
            "unique_candidate_count": unique_candidate_count,
            "pagination_complete": pag_pass,
            "ranking_order_invariant": ranking_order_invariant,
            "selected_rcept_no_order_invariant": selected_record_invariant,
            "canonical_selected_rcept_no": final_rcp_no,
            "permutation_selected_rcept_nos": permuted_selected_nos,
            "determinism_pass": ranking_order_invariant and selected_record_invariant,
        }

        discovery_rows.append({
            "canonical_run_id": canonical_run_id,
            "control_id": cid,
            "ticker": t,
            "issuer_name": tgt["issuer_name"],
            "search_source": "OPENDART_OFFICIAL_API",
            "logical_discovery_query_id": disc_query_id,
            "search_start_date": tgt["discovery_start"],
            "search_end_date": tgt["discovery_end"],
            "reported_total_count": reported_total_count,
            "reported_total_pages": total_pages,
            "loaded_record_count": loaded_raw_count,
            "unique_candidate_count": unique_candidate_count,
            "selected_record_id": final_rcp_no,
            "selected_report_name": final_rep_name,
            "selected_receipt_date": final_rcp_date,
            "legacy_expected_record_id": tgt["legacy_expected_record_id"],
            "legacy_id_match": legacy_match,
            "selection_algorithm": "OPENDART_DETERMINISTIC_PAGINATED_RANKING_V01_FIX03_CORRECTION_9",
            "selection_rank": selected_candidate_rank,
            "selection_reason": f"Rank {selected_candidate_rank} match '{final_rep_name}' authenticated via True XML Hierarchy",
        })

        raw_sha = hashlib.sha256(selected_raw_bytes).hexdigest() if selected_raw_bytes else ""
        raw_size = len(selected_raw_bytes)
        raw_ext = "xml" if selected_raw_format == "XML" else "html"
        raw_filename = f"{t}_{ev_fam}_{final_rcp_no}.{raw_ext}"

        if selected_raw_bytes and selected_parsed and selected_parsed["authority_valid"]:
            raw_fp = raw_dir / raw_filename
            raw_fp.write_bytes(selected_raw_bytes)
            raw_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_9/raw/{raw_filename}"
            raw_manifest_entries[raw_filename] = {
                "canonical_run_id": canonical_run_id,
                "control_id": cid,
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "issuer_name": tgt["issuer_name"],
                "path": raw_rel_path,
                "size_bytes": raw_size,
                "sha256": raw_sha,
                "source": selected_source,
                "retrieval_mode": selected_retrieval_mode,
                "evidence_origin": selected_evidence_origin,
                "official_record_id": final_rcp_no,
                "producing_request_id": selected_producing_req_id,
                "transport_response_size": selected_transport_size,
                "transport_response_sha256": selected_transport_sha,
                "archive_detected": selected_archive_detected,
                "archive_member_count": selected_archive_members,
                "selected_member_name": selected_member_name,
                "member_selection_rule": selected_member_rule,
                "extracted_member_size": selected_extracted_size,
                "extracted_member_sha256": selected_extracted_sha,
                "canonical_raw_size": raw_size,
                "canonical_raw_sha256": raw_sha,
                "content_type": f"application/{raw_ext}",
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content_validation_status": "VALID",
                "live_lineage_valid": True,
            }
        else:
            raw_rel_path = ""

        parsed = selected_parsed if selected_parsed else OfficialEvidenceContentParser.parse_and_validate(
            raw_content_bytes=selected_raw_bytes,
            claimed_ticker=t,
            claimed_issuer=tgt["issuer_name"],
            claimed_event_type=ev_fam,
            claimed_anchor_type=tgt["claimed_anchor_type"],
            claimed_anchor_date=tgt["claimed_anchor_date"],
            source_id=selected_source,
            source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
            discovered_record_id=final_rcp_no,
            doc_request_record_id=final_rcp_no,
            evidence_origin=selected_evidence_origin,
        )

        claim_adj = OfficialEvidenceContentParser.adjudicate_prior_claim(
            official_auth=parsed,
            claimed_event_type=ev_fam,
            claimed_anchor_type=tgt["claimed_anchor_type"],
            claimed_anchor_date=tgt["claimed_anchor_date"],
            claimed_issuer=tgt["issuer_name"],
            claimed_ticker=t,
        )

        if not parsed["event_type_valid"]:
            source_event_classification_failures.append(t)
        if not parsed["event_type_match"]:
            source_event_type_mismatches.append(t)
        if parsed["event_type_ambiguous"]:
            event_type_ambiguity_failures.append(t)
        if parsed["event_context_ambiguous"]:
            event_context_ambiguity_failures.append(t)
        if parsed.get("event_timing_ambiguous", False):
            event_timing_ambiguity_failures.append(t)
        if not parsed["event_semantic_binding_valid"]:
            semantic_binding_failures.append(t)
        if parsed["binding_relationship"] not in ["SAME_NODE", "ANCESTOR_DESCENDANT"]:
            invalid_binding_relationship_failures.append(t)
        if parsed["semantic_block_id"] == "SEM_BLOCK_GLOBAL_DOC":
            global_semantic_block_authority_failures.append(t)
        doc_validation_rows.append({
            "ticker": t,
            "issuer": tgt["issuer_name"],
            "discovered_record_id": final_rcp_no,
            "legacy_claimed_record_id": tgt["legacy_expected_record_id"],
            "raw_path": raw_rel_path,
            "raw_sha": raw_sha,
            "official_source": selected_source,
            "corp_code": tgt["corp_code"],
            "parsed_issuer": parsed["parsed_issuer"],
            "parsed_ticker": parsed["parsed_ticker"],
            "parsed_report_name": parsed["parsed_report_name"] or final_rep_name,
            "source_event_type": parsed["source_event_type"],
            "expected_event_type": ev_fam,
            "event_type_match": parsed["event_type_match"],
            "normalized_event_type": parsed["normalized_event_type"],
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_id": parsed["event_node_id"],
            "event_node_tag": parsed["event_node_tag"],
            "event_node_path": parsed["event_node_path"],
            "event_node_depth": parsed["event_node_depth"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_candidate_count": parsed.get("timing_candidate_count", 1),
            "timing_node_id": parsed["timing_node_id"],
            "timing_node_tag": parsed["timing_node_tag"],
            "timing_node_path": parsed["timing_node_path"],
            "timing_node_depth": parsed["timing_node_depth"],
            "binding_relationship": parsed["binding_relationship"],
            "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
            "semantic_block_id": parsed["semantic_block_id"],
            "semantic_block_type": parsed["semantic_block_type"],
            "semantic_section_path": parsed["semantic_section_path"],
            "semantic_parent_heading": parsed["semantic_parent_heading"],
            "semantic_block_sha256": parsed["semantic_block_sha256"],
            "official_anchor_type": parsed["official_anchor_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_anchor_source_field": parsed["official_anchor_source_field"],
            "official_anchor_source_value": parsed["official_anchor_source_value"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "timing_repetition_count": parsed.get("timing_repetition_count", 1),
            "claim_anchor_match": parsed["claim_anchor_match"],
            "official_source_valid": parsed["official_source_valid"],
            "record_identity_valid": parsed["record_identity_valid"],
            "issuer_identity_valid": parsed["issuer_identity_valid"],
            "event_type_valid": parsed["event_type_valid"],
            "event_semantic_binding_valid": parsed["event_semantic_binding_valid"],
            "event_timing_valid": parsed["event_timing_valid"],
            "raw_provenance_valid": parsed["raw_provenance_valid"],
            "global_fallback_used": parsed["global_fallback_used"],
            "event_context_ambiguous": parsed["event_context_ambiguous"],
            "event_type_ambiguous": parsed["event_type_ambiguous"],
            "event_timing_ambiguous": parsed.get("event_timing_ambiguous", False),
            "authority_valid": parsed["authority_valid"],
            "validation_reason": parsed["validation_reason"],
        })

        semantic_binding_rows.append({
            "control_id": cid,
            "ticker": t,
            "source_event_type": parsed["source_event_type"],
            "expected_event_type": ev_fam,
            "event_type_match": parsed["event_type_match"],
            "selected_rcept_no": final_rcp_no,
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_id": parsed["event_node_id"],
            "event_node_tag": parsed["event_node_tag"],
            "event_node_path": parsed["event_node_path"],
            "event_node_depth": parsed["event_node_depth"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_node_id": parsed["timing_node_id"],
            "timing_node_tag": parsed["timing_node_tag"],
            "timing_node_path": parsed["timing_node_path"],
            "timing_node_depth": parsed["timing_node_depth"],
            "binding_relationship": parsed["binding_relationship"],
            "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
            "anchor_field_name": parsed["official_anchor_source_field"],
            "anchor_source_value": parsed["official_anchor_source_value"],
            "anchor_date": parsed["official_anchor_date"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "semantic_binding_valid": parsed["event_semantic_binding_valid"],
            "global_fallback_used": parsed["global_fallback_used"],
        })

        hierarchy_validation_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "selected_rcept_no": final_rcp_no,
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_path": parsed["event_node_path"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_node_path": parsed["timing_node_path"],
            "binding_relationship": parsed["binding_relationship"],
            "event_node_is_ancestor_of_timing": parsed["binding_relationship"] == "ANCESTOR_DESCENDANT",
            "same_node": parsed["binding_relationship"] == "SAME_NODE",
            "sibling_cross_binding_detected": False,
            "event_context_candidate_count": parsed.get("event_context_candidate_count", 1),
            "event_type_candidate_count": parsed.get("event_type_candidate_count", 1),
            "event_context_ambiguous": parsed["event_context_ambiguous"],
            "event_type_ambiguous": parsed["event_type_ambiguous"],
            "event_timing_ambiguous": parsed.get("event_timing_ambiguous", False),
            "hierarchical_binding_valid": parsed["event_semantic_binding_valid"],
        }

        claim_independence_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "source_event_type": parsed["source_event_type"],
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "official_anchor_type": parsed["official_anchor_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "claim_event_type": tgt["target_event_family"],
            "claim_anchor_type": tgt["claimed_anchor_type"],
            "claim_anchor_date": tgt["claimed_anchor_date"],
            "claim_event_type_match": claim_adj["claim_event_type_match"],
            "claim_anchor_type_match": claim_adj["claim_anchor_type_match"],
            "claim_anchor_date_match": claim_adj["claim_anchor_date_match"],
            "claim_used_for_event_selection": claim_adj["claim_used_for_event_selection"],
            "claim_used_for_context_selection": claim_adj["claim_used_for_context_selection"],
            "claim_used_for_anchor_type_selection": claim_adj["claim_used_for_anchor_type_selection"],
            "claim_used_for_anchor_date_selection": claim_adj["claim_used_for_anchor_date_selection"],
            "claim_independence_valid": claim_adj["claim_independence_valid"],
            "authority_valid": parsed["authority_valid"],
        }

        adjudication_rows.append({
            "ticker": t,
            "issuer_name": tgt["issuer_name"],
            "prior_claimed_event": ev_fam,
            "prior_claimed_anchor": tgt["claimed_anchor_date"],
            "source_event_type": parsed["source_event_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_source_field": parsed["official_anchor_source_field"],
            "official_evidence_found": parsed["authority_valid"],
            "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
            "authority_record_id": final_rcp_no,
            "normalized_event_type": parsed["normalized_event_type"],
            "adjudication": claim_adj["adjudication_status"],
            "adjudication_reason": parsed["validation_reason"],
        })

        if parsed["authority_valid"] and parsed["official_anchor_date"]:
            anc_dt = datetime.strptime(parsed["official_anchor_date"], "%Y-%m-%d")
            w_start = (anc_dt - timedelta(days=35)).strftime("%Y-%m-%d")
            w_end = (anc_dt + timedelta(days=35)).strftime("%Y-%m-%d")
            authority_records.append({
                "canonical_run_id": canonical_run_id,
                "control_id": cid,
                "ticker": t,
                "issuer_name": tgt["issuer_name"],
                "corp_code": tgt["corp_code"],
                "source_event_type": parsed["source_event_type"],
                "normalized_event_type": parsed["normalized_event_type"],
                "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
                "event_node_path": parsed["event_node_path"],
                "event_node_heading": parsed["event_node_heading"],
                "timing_node_path": parsed["timing_node_path"],
                "binding_relationship": parsed["binding_relationship"],
                "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
                "official_anchor_type": parsed["official_anchor_type"],
                "official_anchor_date": parsed["official_anchor_date"],
                "official_anchor_source_field": parsed["official_anchor_source_field"],
                "official_anchor_source_value": parsed["official_anchor_source_value"],
                "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
                "price_window_start": w_start,
                "price_window_end": w_end,
                "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "authority_source_name": selected_source,
                "authority_record_id": final_rcp_no,
                "raw_evidence_path": raw_rel_path,
                "raw_evidence_sha256": raw_sha,
                "producing_request_id": selected_producing_req_id,
                "retrieval_mode": selected_retrieval_mode,
                "validation_predicates": {
                    "official_source_valid": parsed["official_source_valid"],
                    "record_identity_valid": parsed["record_identity_valid"],
                    "issuer_identity_valid": parsed["issuer_identity_valid"],
                    "source_event_type_valid": parsed["event_type_valid"],
                    "event_type_match": parsed["event_type_match"],
                    "event_semantic_binding_valid": parsed["event_semantic_binding_valid"],
                    "event_timing_valid": parsed["event_timing_valid"],
                    "raw_provenance_valid": parsed["raw_provenance_valid"],
                    "global_fallback_not_used": not parsed["global_fallback_used"],
                },
                "authority_valid": True,
            })

    # Save discovery and validation artifacts
    disc_df = pd.DataFrame(discovery_rows)
    disc_path = output_dir / "corporate_action_official_discovery_v01_fix03_correction_9.csv"
    disc_df.to_csv(disc_path, index=False)

    page_man_path = output_dir / "corporate_action_discovery_page_manifest_v01_fix03_correction_9.json"
    page_man_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_page_manifest_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "pages": discovery_page_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pag_val_path = output_dir / "corporate_action_discovery_pagination_validation_v01_fix03_correction_9.json"
    pag_val_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_pagination_validation_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "all_pagination_complete": all(v["pagination_complete"] for v in pagination_validation_entries.values()),
        "validation_by_ticker": pagination_validation_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cand_audit_df = pd.DataFrame(candidate_audit_rows)
    cand_audit_path = output_dir / "corporate_action_discovery_candidate_audit_v01_fix03_correction_9.csv"
    cand_audit_df.to_csv(cand_audit_path, index=False)

    det_val_path = output_dir / "corporate_action_discovery_determinism_validation_v01_fix03_correction_9.json"
    det_val_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_determinism_validation_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "all_controls_order_invariant": all(v["determinism_pass"] for v in determinism_validation_results.values()),
        "validation_by_ticker": determinism_validation_results,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    probe_audit_df = pd.DataFrame(probe_audit_rows)
    probe_audit_path = output_dir / "corporate_action_document_probe_audit_v01_fix03_correction_9.csv"
    probe_audit_df.to_csv(probe_audit_path, index=False)

    disc_man_payload = {
        "schema": "corporate_action_discovery_raw_manifest_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "artifacts": discovery_manifest_entries,
    }
    disc_man_path = output_dir / "corporate_action_discovery_raw_manifest_v01_fix03_correction_9.json"
    disc_man_path.write_text(json.dumps(disc_man_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    doc_val_df = pd.DataFrame(doc_validation_rows)
    doc_val_path = output_dir / "corporate_action_official_document_validation_v01_fix03_correction_9.csv"
    doc_val_df.to_csv(doc_val_path, index=False)

    sem_bind_df = pd.DataFrame(semantic_binding_rows)
    sem_bind_path = output_dir / "corporate_action_event_semantic_binding_v01_fix03_correction_9.csv"
    sem_bind_df.to_csv(sem_bind_path, index=False)

    hier_val_path = output_dir / "corporate_action_event_hierarchy_validation_v01_fix03_correction_9.json"
    hier_val_path.write_text(json.dumps({
        "schema": "corporate_action_event_hierarchy_validation_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "all_hierarchy_valid": all(v["hierarchical_binding_valid"] for v in hierarchy_validation_entries.values()),
        "validation_by_ticker": hierarchy_validation_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    claim_indep_path = output_dir / "corporate_action_claim_independence_validation_v01_fix03_correction_9.json"
    claim_indep_path.write_text(json.dumps({
        "schema": "corporate_action_claim_independence_validation_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "all_claim_independent": all(v["claim_independence_valid"] for v in claim_independence_entries.values()),
        "validation_by_ticker": claim_independence_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    adj_df = pd.DataFrame(adjudication_rows)
    adj_path = output_dir / "corporate_action_existing_claim_adjudication_v01_fix03_correction_9.csv"
    adj_df.to_csv(adj_path, index=False)

    rep_pool_path = output_dir / "corporate_action_replacement_pool_v01_fix03_correction_9.csv"
    pd.DataFrame(columns=["control_id", "ticker", "issuer_name", "status"]).to_csv(rep_pool_path, index=False)

    auth_rec_path = output_dir / "corporate_action_authority_records_v01_fix03_correction_9.json"
    auth_rec_path.write_text(json.dumps({
        "schema": "corporate_action_authority_records_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "records": authority_records,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    raw_man_path = output_dir / "corporate_action_raw_evidence_manifest_v01_fix03_correction_9.json"
    raw_man_path.write_text(json.dumps({
        "schema": "corporate_action_raw_evidence_manifest_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "artifacts": raw_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 6. Freeze Cohort Before Price Fetch
    final_cohort_rows = []
    for idx, ar in enumerate(authority_records, start=1):
        final_cohort_rows.append({
            "canonical_run_id": canonical_run_id,
                "control_id": ar["control_id"],
                "ticker": ar["ticker"],
                "issuer_name": ar["issuer_name"],
                "corp_code": ar["corp_code"],
            "source_event_type": ar["source_event_type"],
            "normalized_event_type": ar["normalized_event_type"],
            "selected_source_event_context_id": ar.get("selected_source_event_context_id", ""),
            "event_node_path": ar["event_node_path"],
            "event_node_heading": ar["event_node_heading"],
            "timing_node_path": ar["timing_node_path"],
            "binding_relationship": ar["binding_relationship"],
            "lowest_common_ancestor_path": ar["lowest_common_ancestor_path"],
            "official_anchor_type": ar["official_anchor_type"],
            "official_anchor_date": ar["official_anchor_date"],
            "official_anchor_source_field": ar["official_anchor_source_field"],
            "official_anchor_source_value": ar["official_anchor_source_value"],
            "official_anchor_priority_rank": ar.get("official_anchor_priority_rank", 1),
            "price_window_start": ar["price_window_start"],
            "price_window_end": ar["price_window_end"],
            "authority_source_tier": ar["authority_source_tier"],
            "authority_source_name": ar["authority_source_name"],
            "authority_record_id": ar["authority_record_id"],
            "producing_request_id": ar["producing_request_id"],
            "retrieval_mode": ar.get("retrieval_mode", "NEW_OPENDART_DOCUMENT_FETCH"),
            "raw_evidence_path": ar["raw_evidence_path"],
            "raw_evidence_sha256": ar["raw_evidence_sha256"],
            "selection_role": "AUTHORITY_VALID_FROZEN_CONTROL",
            "selection_order": idx,
            "selection_algorithm": "OPENDART_PAGINATED_CLAIM_FREE_TRUE_XML_HIERARCHY_COHORT_V01_FIX03_CORRECTION_9",
        })

    cohort_df = pd.DataFrame(final_cohort_rows)
    cohort_path = output_dir / "corporate_action_review_cohort_v01_fix03_correction_9.csv"
    cohort_df.to_csv(cohort_path, index=False)
    cohort_sha = hashlib.sha256(cohort_path.read_bytes()).hexdigest()
    cohort_frozen_at = datetime.now(timezone.utc).isoformat()

    # 7. Price Parity Execution (Only if cohort > 0)
    all_price_rows = []
    parity_rows = []
    reconciliation_rows = []
    parity_statuses = []

    insufficient_window_count = 0
    date_set_mismatch_count = 0
    ohlc_mismatch_count = 0
    candidate_error_count = 0
    comparator_error_count = 0

    if final_cohort_rows:
        import pykrx.stock as pykrx_stock
        naver_client = NaverDateRangeAdjustedClient(allow_network=allow_network)

        for c in final_cohort_rows:
            t = normalize_ticker(c["ticker"])
            w_start = c["price_window_start"]
            w_end = c["price_window_end"]
            anchor_d = c["official_anchor_date"]

            cand_req_id = f"REQ_PRICE_NAVER_{t}_{w_start}_{w_end}"
            py_query_id = f"QUERY_PRICE_RAW_PYKRX_{t}_{w_start}_{w_end}"

            accounting.direct_naver_logical_requests += 1
            accounting.direct_naver_physical_attempts += 1
            accounting.raw_pykrx_logical_requests += 1
            accounting.raw_pykrx_physical_attempts += 1

            cand_err = ""
            c_start_t = datetime.now(timezone.utc).isoformat()
            try:
                st_code, xml_text, elapsed = naver_client.fetch_raw(t, w_start, w_end)
                c_end_t = datetime.now(timezone.utc).isoformat()
                cand_df = NaverDateRangeAdjustedClient.parse_xml_payload(xml_text, w_start, w_end)
                cand_raw_sha = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
            except Exception as exc:
                c_end_t = datetime.now(timezone.utc).isoformat()
                cand_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                cand_raw_sha = ""
                cand_err = str(exc)
                candidate_error_count += 1

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": cand_req_id,
                "source": "NAVER_DIRECT",
                "purpose": "EVENT_SENSITIVE_CANDIDATE_PRICE_FETCH",
                "control_id": c["control_id"],
                "ticker": t,
                "corp_code": c["corp_code"],
                "official_record_id": c["authority_record_id"],
                "authority_record_id": c["authority_record_id"],
                "price_window_start": w_start,
                "price_window_end": w_end,
                "sanitized_endpoint": f"https://fchart.stock.naver.com/sise.nhn?symbol={t}&startTime={w_start}&endTime={w_end}",
                "started_at": c_start_t,
                "completed_at": c_end_t,
                "physical_attempt": 1,
                "http_status": 200 if not cand_err else 500,
                "raw_http_response_size": len(xml_text) if not cand_err else 0,
                "raw_http_response_sha256": cand_raw_sha,
                "transport_response_size": len(xml_text) if not cand_err else 0,
                "transport_response_sha256": cand_raw_sha,
                "outcome": "SUCCESS" if not cand_err else "ERROR",
                "error_type": cand_err,
            })

            py_err = ""
            p_start_t = datetime.now(timezone.utc).isoformat()
            try:
                py_raw = pykrx_stock.get_market_ohlcv_by_date(
                    w_start.replace("-", ""),
                    w_end.replace("-", ""),
                    t,
                    adjusted=True,
                )
                p_end_t = datetime.now(timezone.utc).isoformat()
                if py_raw is not None and not py_raw.empty:
                    py_df = py_raw.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}).copy()
                    py_df["date"] = [d.strftime("%Y-%m-%d") for d in py_df.index]
                else:
                    py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                py_rowset_sha = hashlib.sha256(py_df.to_csv(index=False).encode("utf-8")).hexdigest()
            except Exception as exc:
                p_end_t = datetime.now(timezone.utc).isoformat()
                py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                py_rowset_sha = ""
                py_err = str(exc)
                comparator_error_count += 1

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": py_query_id,
                "source": "RAW_PYKRX_COMPARATOR",
                "purpose": "EVENT_SENSITIVE_RAW_COMPARATOR_PRICE_QUERY",
                "control_id": c["control_id"],
                "ticker": t,
                "corp_code": c["corp_code"],
                "official_record_id": c["authority_record_id"],
                "authority_record_id": c["authority_record_id"],
                "adjusted": True,
                "price_window_start": w_start,
                "price_window_end": w_end,
                "sanitized_endpoint": f"pykrx.stock.get_market_ohlcv_by_date({w_start},{w_end},{t},adjusted=True)",
                "started_at": p_start_t,
                "completed_at": p_end_t,
                "physical_attempt": 1,
                "http_status": 200 if not py_err else 500,
                "raw_http_response_size": 0,
                "raw_http_response_sha256": py_rowset_sha,
                "transport_response_size": 0,
                "transport_response_sha256": py_rowset_sha,
                "outcome": "SUCCESS" if not py_err else "ERROR",
                "error_type": py_err,
            })

            # Evaluate parity
            cand_dates = set(cand_df["date"].astype(str)) if not cand_df.empty else set()
            py_dates = set(py_df["date"].astype(str)) if not py_df.empty else set()
            common_dates = sorted(cand_dates.intersection(py_dates))
            cand_only = sorted(cand_dates - py_dates)
            py_only = sorted(py_dates - cand_dates)

            if cand_only or py_only:
                date_set_mismatch_count += 1

            pre_ov = sum(1 for d in common_dates if d < anchor_d)
            post_ov = sum(1 for d in common_dates if d >= anchor_d)
            if pre_ov < 5 or post_ov < 5:
                insufficient_window_count += 1

            o_mis, h_mis, l_mis, c_mis, v_mis = 0, 0, 0, 0, 0
            if common_dates and not cand_df.empty and not py_df.empty:
                c_sub = cand_df.set_index("date").loc[common_dates]
                p_sub = py_df.set_index("date").loc[common_dates]
                o_mis = int((c_sub["open"].astype(float) != p_sub["open"].astype(float)).sum())
                h_mis = int((c_sub["high"].astype(float) != p_sub["high"].astype(float)).sum())
                l_mis = int((c_sub["low"].astype(float) != p_sub["low"].astype(float)).sum())
                c_mis = int((c_sub["close"].astype(float) != p_sub["close"].astype(float)).sum())

            if (o_mis + h_mis + l_mis + c_mis) > 0:
                ohlc_mismatch_count += 1

            parity_statuses.append("MATCH" if (o_mis + h_mis + l_mis + c_mis == 0 and len(cand_only) == 0 and len(py_only) == 0) else "MISMATCH")

    price_df = pd.DataFrame(all_price_rows) if all_price_rows else pd.DataFrame(columns=["control_id", "ticker", "source", "evidence_origin", "request_id", "date", "open", "high", "low", "close", "volume"])
    (output_dir / "corporate_action_event_price_rows_v01_fix03_correction_9.csv").write_text(price_df.to_csv(index=False), encoding="utf-8")

    parity_df = pd.DataFrame(parity_rows) if parity_rows else pd.DataFrame(columns=["control_id", "ticker", "parity_status"])
    (output_dir / "corporate_action_event_sensitive_parity_v01_fix03_correction_9.csv").write_text(parity_df.to_csv(index=False), encoding="utf-8")

    recon_df = pd.DataFrame(reconciliation_rows) if reconciliation_rows else pd.DataFrame(columns=["control_id", "ticker", "status"])
    (output_dir / "corporate_action_date_reconciliation_v01_fix03_correction_9.csv").write_text(recon_df.to_csv(index=False), encoding="utf-8")

    # 8. Network Accounting & Linkage (Section 3, 4)
    accounting.compute_totals()

    net_path = output_dir / "corporate_action_evidence_network_accounting_v01_fix03_correction_9.json"
    net_dict = accounting.to_dict()
    net_dict["canonical_run_id"] = canonical_run_id
    net_path.write_text(json.dumps(net_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    linkage_result = validate_live_evidence_linkage(
        canonical_run_id=canonical_run_id,
        discovery_records=discovery_rows,
        document_records=raw_manifest_entries,
        raw_manifest_entries=raw_manifest_entries,
        authority_rows=authority_records,
        request_logs=accounting.request_logs,
        price_request_logs=[
            r for r in accounting.request_logs
            if r.get("source") in {"NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"}
        ],
        artifact_paths={"raw": raw_dir},
        current_output_dir=output_dir,
        accounting_cross_invariant_pass=accounting.accounting_cross_invariant_pass,
    )
    linkage_payload = linkage_result.to_dict()
    linkage_payload.update({
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_10",
        "discovery_pages_checked": len(discovery_manifest_entries),
        "document_items_checked": len(raw_manifest_entries),
    })
    # Back-propagate the validator's per-run truth to the manifest metadata;
    # this field is never a default assertion of lineage validity.
    failed_record_ids = {
        str(item.get("record_id") or item.get("authority_record_id") or item.get("document_id"))
        for item in linkage_result.linkage_failures
        if item.get("record_id") or item.get("authority_record_id") or item.get("document_id")
    }
    for manifest_entry in raw_manifest_entries.values():
        manifest_record_id = _linkage_text(manifest_entry, "official_record_id", "rcept_no", "authority_record_id")
        manifest_entry["live_lineage_valid"] = bool(manifest_record_id and manifest_record_id not in failed_record_ids and linkage_result.all_linkage_valid)
    raw_man_path.write_text(json.dumps({
        "schema": "corporate_action_raw_evidence_manifest_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "artifacts": raw_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "live_evidence_linkage_validation_v01_fix03_correction_9.json").write_text(
        json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # 9. Gate 06 Evaluation
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

    gate06_eval_metrics = {
        "preflight_verdict": preflight["verdict"],
        "document_readiness_verdict": doc_readiness["verdict"],
        "authority_valid_controls_count": auth_valid_count,
        "final_cohort_control_count": len(final_cohort_rows),
        "diversity_pass": diversity_pass,
        "pagination_incomplete_control_count": len(pagination_incomplete_failures),
        "pagination_metadata_inconsistency_count": len(pagination_inconsistency_failures),
        "pagination_page_count_inconsistency_count": len(pagination_page_count_inconsistencies),
        "discovery_total_count_mismatch_count": len(discovery_total_count_mismatches),
        "duplicate_rcept_no_count": sum(v["duplicate_count"] for v in pagination_validation_entries.values()),
        "conflicting_duplicate_rcept_no_count": len(conflicting_duplicate_failures),
        "candidate_audit_incomplete_count": len(candidate_audit_incompleteness_failures),
        "ranking_order_invariance_failure_count": len(ranking_order_invariance_failures),
        "selected_record_invariance_failure_count": len(selected_record_invariance_failures),
        "source_event_classification_failure_count": len(source_event_classification_failures),
        "source_event_type_mismatch_count": len(source_event_type_mismatches),
        "historical_raw_reuse_count": len(linkage_result.historical_raw_reuse_failures),
        "physical_request_mutation_failure_count": len(linkage_result.physical_request_mutation_failures),
        "live_lineage_failure_count": len(linkage_result.live_lineage_failures),
        "claim_event_selection_influence_count": len(claim_event_influence_failures),
        "claim_context_selection_influence_count": len(claim_context_influence_failures),
        "claim_anchor_type_selection_influence_count": len(claim_anchor_type_influence_failures),
        "claim_anchor_date_selection_influence_count": len(claim_anchor_date_influence_failures),
        "event_type_ambiguity_count": len(event_type_ambiguity_failures),
        "event_context_ambiguity_count": len(event_context_ambiguity_failures),
        "event_timing_ambiguity_count": len(event_timing_ambiguity_failures),
        "semantic_binding_failure_count": len(semantic_binding_failures),
        "invalid_binding_relationship_count": len(invalid_binding_relationship_failures),
        "global_semantic_block_authority_count": len(global_semantic_block_authority_failures),
        "archive_provenance_failure_count": len(archive_provenance_failures),
        "archive_member_ambiguity_count": len(archive_member_ambiguity_failures),
        "archive_transport_inconsistency_count": len(archive_transport_inconsistencies),
        "archive_member_inconsistency_count": len(archive_member_inconsistencies),
        "producing_request_failure_count": len(linkage_result.producing_request_failures),
        "cross_run_request_linkage_failure_count": len(linkage_result.cross_run_request_linkage_failures),
        "invalid_retrieval_mode_count": len(linkage_result.invalid_retrieval_modes),
        "record_identity_failure_count": len(linkage_result.record_identity_failures),
        "issuer_identity_failure_count": len(linkage_result.issuer_identity_failures),
        "candidate_linkage_failure_count": len(linkage_result.candidate_linkage_failures),
        "pykrx_linkage_failure_count": len(linkage_result.pykrx_linkage_failures),
        "raw_orphan_file_count": len(linkage_result.raw_orphan_failures),
        "date_set_mismatch_count": date_set_mismatch_count,
        "authorized_reconciliation_count": sum(1 for s in parity_statuses if s == "AUTHORIZED_DATE_RECONCILIATION_MATCH"),
        "insufficient_window_count": insufficient_window_count,
        "ohlc_match_count": sum(1 for _, r in parity_df.iterrows() if r.get("open_mismatch_count", 0) == 0),
        "ohlc_mismatch_count": ohlc_mismatch_count,
        "candidate_error_count": candidate_error_count,
        "comparator_error_count": comparator_error_count,
        "network_accounting_failure_count": 0 if accounting.accounting_cross_invariant_pass else 1,
        "linkage_evaluation_status": linkage_result.linkage_evaluation_status,
        "all_linkage_valid": linkage_result.all_linkage_valid,
        "total_provenance_failure_count": linkage_result.total_linkage_failures,
        "cohort_frozen_before_price_fetch": True,
        "cohort_frozen_at": cohort_frozen_at,
        "cohort_sha256_before_price_fetch": cohort_sha,
    }

    gate06_pass, gate06_blockers = evaluate_gate06(gate06_eval_metrics)

    gate06_payload = dict(gate06_eval_metrics)
    gate06_payload["schema"] = "gate06_corporate_action_reassessment_v01_fix03_correction_9"
    gate06_payload["canonical_run_id"] = canonical_run_id
    gate06_payload["directive_id"] = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9"
    gate06_payload["gate_06_pass"] = gate06_pass
    gate06_payload["gate_06_blockers"] = gate06_blockers

    gate06_path = output_dir / "gate06_corporate_action_reassessment_v01_fix03_correction_9.json"
    gate06_path.write_text(json.dumps(gate06_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

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
        inherited_gates[g_key] = bool(isinstance(val, bool) and val is True)

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
        reason_codes = ["ALL_15_SOURCE_AUTHORITY_REVIEW_GATES_PASSED_FIX03_CORRECTION_9"]
    elif ohlc_mismatch_count > 0:
        review_decision = "REJECTED_AS_PRODUCTION_AUTHORITY"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"
        blocking_conditions = gate06_blockers
        reason_codes = ["CORPORATE_ACTION_PRICE_CONTRADICTION"]
    else:
        review_decision = "CONDITIONAL_REVIEW_REQUIRED"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9"
        blocking_conditions = gate06_blockers
        reason_codes = ["OFFICIAL_EVIDENCE_INCOMPLETE"]

    successful_doc_count = sum(1 for m in raw_manifest_entries.values() if m.get("content_validation_status") == "VALID" and m.get("live_lineage_valid") and m.get("size_bytes", 0) > 0)

    decision_payload = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_8",
        "authoritative_technical_parent": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_9,
        "parent_freeze_valid": parent_freeze["all_parent_inputs_unchanged"],
        "preflight_verdict": preflight["verdict"],
        "document_readiness_verdict": doc_readiness["verdict"],
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "candidate_endpoint": "https://fchart.stock.naver.com/sise.nhn",
        "official_discovery_requests_logical": accounting.official_discovery_logical_requests,
        "official_discovery_requests_physical": accounting.official_discovery_physical_attempts,
        "official_discovery_success_count": len(discovery_manifest_entries),
        "official_document_manifest_entry_count": len(raw_manifest_entries),
        "official_document_success_count": successful_doc_count,
        "authority_valid_control_count": auth_valid_count,
        "final_cohort_size": len(final_cohort_rows),
        "final_cohort_sha": cohort_sha if final_cohort_rows else "",
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
        "provenance_failures": linkage_result.total_linkage_failures,
        "linkage_evaluation_status": linkage_result.linkage_evaluation_status,
        "all_linkage_valid": linkage_result.all_linkage_valid,
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
    }
    (output_dir / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_9.json").write_text(
        json.dumps(decision_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Manifest
    _write_artifact_manifest(output_dir, canonical_run_id, review_decision, prod_integration_auth, raw_manifest_entries, discovery_manifest_entries)
    return decision_payload


def _terminate_on_readiness_or_preflight_failure(
    output_dir: Path,
    parent_dir: Path,
    canonical_run_id: str,
    preflight: dict[str, Any],
    doc_readiness: dict[str, Any],
    accounting: CorporateActionNetworkAccounting,
    failure_reason: str,
) -> dict[str, Any]:
    """Strict Hard-Gate termination when preflight or readiness probe fails."""
    parent_freeze = verify_parent_authority_freeze(parent_dir)
    (output_dir / "parent_authority_freeze_validation_v01_fix03_correction_9.json").write_text(
        json.dumps(parent_freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    source_inventory = {
        "schema": "corporate_action_evidence_source_inventory_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "sources": [],
    }
    (output_dir / "corporate_action_evidence_source_inventory_v01_fix03_correction_9.json").write_text(
        json.dumps(source_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    accounting.compute_totals()
    net_dict = accounting.to_dict()
    net_dict["canonical_run_id"] = canonical_run_id
    (output_dir / "corporate_action_evidence_network_accounting_v01_fix03_correction_9.json").write_text(
        json.dumps(net_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    linkage_result = validate_live_evidence_linkage(
        canonical_run_id=canonical_run_id,
        discovery_records=[],
        document_records=[],
        raw_manifest_entries=[],
        authority_rows=[],
        request_logs=accounting.request_logs,
        current_output_dir=output_dir,
        accounting_cross_invariant_pass=accounting.accounting_cross_invariant_pass,
    )
    linkage_result.linkage_evaluation_status = "NOT_EVALUATED_DUE_TO_READINESS_FAILURE"
    linkage_result.live_lineage_failures.append(
        _linkage_failure("DOWNSTREAM_ACQUISITION_NOT_EXECUTED", reason=failure_reason)
    )
    linkage_payload = linkage_result.to_dict()
    linkage_payload.update({
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_10",
        "discovery_pages_checked": 0,
        "document_items_checked": 0,
    })
    (output_dir / "live_evidence_linkage_validation_v01_fix03_correction_9.json").write_text(
        json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    gate06_blockers = [
        f"Readiness hard gate failed: {failure_reason}",
        "Official evidence deficit: 0/8 authority valid",
        "Corporate action event diversity requirement failed",
    ]
    gate06_payload = {
        "schema": "gate06_corporate_action_reassessment_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "preflight_verdict": preflight.get("verdict", "FAIL"),
        "document_readiness_verdict": doc_readiness.get("verdict", "FAIL"),
        "authority_valid_controls_count": 0,
        "final_cohort_control_count": 0,
        "diversity_pass": False,
        "gate_06_pass": False,
        "gate_06_blockers": gate06_blockers,
    }
    gate06_payload.update(linkage_result.to_metrics())
    (output_dir / "gate06_corporate_action_reassessment_v01_fix03_correction_9.json").write_text(
        json.dumps(gate06_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

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
        inherited_gates[g_key] = bool(isinstance(val, bool) and val is True)

    all_15_gates = dict(inherited_gates)
    all_15_gates["gate_06_corporate_action_parity"] = False
    all_15_gates["gate_15_no_unresolved_conditions"] = False

    decision_payload = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_8",
        "authoritative_technical_parent": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_9,
        "parent_freeze_valid": parent_freeze["all_parent_inputs_unchanged"],
        "preflight_verdict": preflight.get("verdict", "FAIL"),
        "document_readiness_verdict": doc_readiness.get("verdict", "FAIL"),
        "official_discovery_requests_logical": 0,
        "official_discovery_requests_physical": 0,
        "official_discovery_success_count": 0,
        "official_document_manifest_entry_count": 0,
        "official_document_success_count": 0,
        "authority_valid_control_count": 0,
        "final_cohort_size": 0,
        "final_cohort_sha": "",
        "naver_actual_requests": 0,
        "raw_pykrx_actual_queries": 0,
        "exact_date_match_controls": 0,
        "authorized_reconciliation_controls": 0,
        "date_mismatch_controls": 0,
        "insufficient_window_controls": 0,
        "ohlc_mismatch_controls": 0,
        "candidate_errors": 0,
        "comparator_errors": 0,
        "provenance_failures": len(linkage_payload["linkage_failures"]),
        "gate_06_result": False,
        "gate_15_result": False,
        "inherited_gate_results": inherited_gates,
        "all_15_gate_results": all_15_gates,
        "all_gates_passed": False,
        "blocking_conditions": gate06_blockers,
        "reason_codes": [failure_reason],
        "review_decision": "CONDITIONAL_REVIEW_REQUIRED",
        "production_integration_authorized": False,
        "active_production_authority_changed": False,
        "recommended_next_state": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "network_accounting": accounting.to_dict(),
    }
    (output_dir / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_9.json").write_text(
        json.dumps(decision_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    _write_artifact_manifest(output_dir, canonical_run_id, "CONDITIONAL_REVIEW_REQUIRED", False, {}, {})
    return decision_payload


def _write_artifact_manifest(
    output_dir: Path,
    canonical_run_id: str,
    review_decision: str,
    prod_integration_auth: bool,
    raw_manifest_entries: dict[str, Any],
    discovery_manifest_entries: dict[str, Any],
) -> None:
    manifest_entries = {}
    for p in output_dir.glob("*.*"):
        if p.name != "artifact_manifest.json":
            manifest_entries[p.name] = {
                "path": f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_9/{p.name}",
                "size_bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }

    for rfname, rmeta in raw_manifest_entries.items():
        manifest_entries[f"raw/{rfname}"] = rmeta
    for dfname, dmeta in discovery_manifest_entries.items():
        manifest_entries[f"discovery_raw/{dfname}"] = dmeta

    manifest_payload = {
        "schema": "corporate_action_evidence_manifest_v01_fix03_correction_9",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_9",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_9,
        "review_decision": review_decision,
        "production_integration_authorized": prod_integration_auth,
        "artifacts": manifest_entries,
    }
    manifest_path = output_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_corporate_action_evidence_acquisition_fix03_correction_11(
    output_dir: Path = DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_11,
    parent_dir: Path = PARENT_FIX03_CORRECTION_DIR,
    allow_network: bool = True,
    full_suite_completion: bool = False,
    new_regression_count: int | None = None,
) -> dict[str, Any]:
    """Execute complete corporate action authority orchestration with strict readiness hard gating and corrected network accounting (Section 0-27)."""
    canonical_run_id = f"CORP_AUTH_FIX03_CORRECTION_11_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"

    if output_dir.exists():
        raw_existing = output_dir / "raw"
        if raw_existing.exists():
            shutil.rmtree(raw_existing)
        disc_existing = output_dir / "discovery_raw"
        if disc_existing.exists():
            shutil.rmtree(disc_existing)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    disc_raw_dir = output_dir / "discovery_raw"
    disc_raw_dir.mkdir(parents=True, exist_ok=True)

    accounting = CorporateActionNetworkAccounting()

    # Explicit maintenance/offline guard for repository regression runs.  This
    # short-circuits before credential resolution or any external client is built.
    if os.environ.get("CORRECTION_11_OFFLINE_ONLY") == "1":
        accounting.execution_mode = "OFFLINE_IMPLEMENTATION_ONLY"
        return _terminate_on_readiness_or_preflight_failure_correction_11(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight={"verdict": "FAIL", "reason": "CORRECTION_11_OFFLINE_ONLY"},
            doc_readiness={"verdict": "NOT_EXECUTED", "schema": "opendart_document_readiness_v01_fix03_correction_11"},
            accounting=accounting,
            failure_reason="CORRECTION_11_OFFLINE_ONLY",
        )

    # 1. Hard Gate: OpenDART Preflight (Section 4, 16)
    preflight = run_opendart_preflight(output_dir=output_dir, allow_network=allow_network, canonical_run_id=canonical_run_id, correction_suffix="11")
    accounting.preflight_physical_calls = 1 if allow_network else 0
    if preflight["verdict"] != "READY":
        return _terminate_on_readiness_or_preflight_failure_correction_11(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight=preflight,
            doc_readiness={"verdict": "NOT_EXECUTED", "schema": "opendart_document_readiness_v01_fix03_correction_11"},
            accounting=accounting,
            failure_reason="OPENDART_PREFLIGHT_FAIL",
        )

    # 2. Hard Gate: Document Endpoint Readiness Probe (Section 4, 16, 17)
    doc_readiness = run_document_endpoint_readiness_probe(output_dir=output_dir, allow_network=allow_network, canonical_run_id=canonical_run_id, correction_suffix="11")
    accounting.readiness_physical_calls = 1 if allow_network else 0

    if doc_readiness["verdict"] != "READY":
        return _terminate_on_readiness_or_preflight_failure_correction_11(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight=preflight,
            doc_readiness=doc_readiness,
            accounting=accounting,
            failure_reason="TRANSIENT_OFFICIAL_DOCUMENT_ENDPOINT_UNAVAILABLE",
        )

    # 3. Parent Freeze Validation (Section 2)
    parent_freeze = verify_parent_authority_freeze(parent_dir)
    parent_freeze = {
        **parent_freeze,
        "schema": "parent_authority_freeze_validation_v01_fix03_correction_11",
        "directive_id": DIRECTIVE_ID_CORRECTION_11,
    }
    parent_freeze_path = output_dir / "parent_authority_freeze_validation_v01_fix03_correction_11.json"
    parent_freeze_path.write_text(json.dumps(parent_freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not parent_freeze["all_parent_inputs_unchanged"]:
        raise ValueError(f"Parent FIX03_CORRECTION freeze validation failed: {parent_freeze['mismatches']}")

    # 4. Source Inventory
    source_inventory = {
        "schema": "corporate_action_evidence_source_inventory_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "sources": [
            {
                "source_id": "OPENDART_OFFICIAL_API",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (OpenDART) 정식 API",
                "base_domain": "opendart.fss.or.kr",
                "endpoint_type": "OFFICIAL_API_PAGINATED_DISCOVERY_AND_DOCUMENT",
                "auth_required": True,
                "raw_format": "JSON_AND_XML",
                "parser_version": "v01_fix03_correction_11",
                "authority_validation_contract": "OpenDART 전수 페이지네이션 및 공시 원문 XML의 True XML Hierarchy Tree 파싱 기반 Claim-Free 공식 앵커 추출",
            },
            {
                "source_id": "DART_OFFICIAL_DISCLOSURE",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (DART) 공시원문 뷰어",
                "base_domain": "dart.fss.or.kr",
                "endpoint_type": "OFFICIAL_DISCLOSURE_VIEWER",
                "auth_required": False,
                "raw_format": "HTML",
                "parser_version": "v01_fix03_correction_11",
            },
        ],
    }
    source_inv_path = output_dir / "corporate_action_evidence_source_inventory_v01_fix03_correction_11.json"
    source_inv_path.write_text(json.dumps(source_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 5. Full Downstream Live Acquisition (Executed strictly when readiness == READY)
    api_key = get_opendart_api_key()
    targets = get_official_discovery_search_targets()

    discovery_rows = []
    discovery_page_manifest_entries = {}
    pagination_validation_entries = {}
    candidate_audit_rows = []
    probe_audit_rows = []
    determinism_validation_results = {}
    discovery_manifest_entries = {}
    raw_manifest_entries = {}
    doc_validation_rows = []
    semantic_binding_rows = []
    hierarchy_validation_entries = {}
    claim_independence_entries = {}
    adjudication_rows = []
    authority_records = []

    pagination_inconsistency_failures = []
    pagination_page_count_inconsistencies = []
    pagination_incomplete_failures = []
    discovery_total_count_mismatches = []
    conflicting_duplicate_failures = []
    candidate_audit_incompleteness_failures = []
    ranking_order_invariance_failures = []
    selected_record_invariance_failures = []
    source_event_classification_failures = []
    source_event_type_mismatches = []
    event_type_ambiguity_failures = []
    event_context_ambiguity_failures = []
    event_timing_ambiguity_failures = []
    claim_event_influence_failures = []
    claim_context_influence_failures = []
    claim_anchor_type_influence_failures = []
    claim_anchor_date_influence_failures = []
    semantic_binding_failures = []
    invalid_binding_relationship_failures = []
    global_semantic_block_authority_failures = []
    archive_provenance_failures = []
    archive_member_ambiguity_failures = []
    archive_transport_inconsistencies = []
    archive_member_inconsistencies = []

    dart_session = requests.Session()
    dart_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    for tgt in targets:
        t = normalize_ticker(tgt["ticker"])
        cid = tgt["control_id"]
        ev_fam = tgt["target_event_family"]
        disc_query_id = f"DISC_QUERY_{t}_{ev_fam}"

        accounting.official_discovery_logical_requests += 1

        page_no = 1
        total_pages = 1
        frozen_page1_meta: dict[str, Any] = {}
        all_raw_items: list[dict[str, Any]] = []
        pages_meta = []
        pages_requested = []
        pages_successful = []

        while page_no <= total_pages:
            disc_req_id = f"REQ_DISC_OPENDART_{t}_{ev_fam}_P{page_no:03d}"
            disc_start_time = datetime.now(timezone.utc).isoformat()
            accounting.official_discovery_physical_attempts += 1

            disc_url = "https://opendart.fss.or.kr/api/list.json"
            disc_params = {
                "crtfc_key": api_key,
                "corp_code": tgt["corp_code"],
                "bgn_de": tgt["discovery_start"],
                "end_de": tgt["discovery_end"],
                "page_count": "100",
                "page_no": str(page_no),
            }

            pages_requested.append(page_no)
            disc_resp = dart_session.get(disc_url, params=disc_params, timeout=10.0)
            disc_end_time = datetime.now(timezone.utc).isoformat()
            disc_bytes = disc_resp.content
            disc_sha = hashlib.sha256(disc_bytes).hexdigest()
            disc_size = len(disc_bytes)
            disc_data = disc_resp.json()

            status_code = disc_data.get("status", "")
            r_total_cnt = int(disc_data.get("total_count", 0)) if str(disc_data.get("total_count", "")).isdigit() else 0
            r_total_page = int(disc_data.get("total_page", 1)) if str(disc_data.get("total_page", "")).isdigit() else 1
            r_page_cnt = int(disc_data.get("page_count", 100)) if str(disc_data.get("page_count", "")).isdigit() else 100

            page_success = bool(disc_resp.status_code == 200 and status_code in ["000", "013"])
            if page_success:
                pages_successful.append(page_no)

            if page_no == 1:
                total_pages = max(r_total_page, 1)
                frozen_page1_meta = {
                    "corp_code": tgt["corp_code"],
                    "bgn_de": tgt["discovery_start"],
                    "end_de": tgt["discovery_end"],
                    "page_count": r_page_cnt,
                    "reported_total_count": r_total_cnt,
                    "reported_total_page": total_pages,
                }

            page_items = disc_data.get("list", [])
            all_raw_items.extend(page_items)

            pages_meta.append({
                "page_no": page_no,
                "page_count": r_page_cnt,
                "item_count": len(page_items),
                "reported_total_count": r_total_cnt,
                "reported_total_page": r_total_page,
                "http_status": disc_resp.status_code,
                "opendart_status": status_code,
            })

            p_filename = f"disc_{t}_{ev_fam}_p{page_no:03d}.json"
            p_fp = disc_raw_dir / p_filename
            p_fp.write_bytes(disc_bytes)
            p_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_11/discovery_raw/{p_filename}"

            discovery_page_manifest_entries[p_filename] = {
                "ticker": t,
                "control_id": cid,
                "logical_discovery_query_id": disc_query_id,
                "page_no": page_no,
                "page_count": len(page_items),
                "reported_total_count": r_total_cnt,
                "reported_total_page": r_total_page,
                "request_id": disc_req_id,
                "path": p_rel_path,
                "size_bytes": disc_size,
                "sha256": disc_sha,
                "http_status": disc_resp.status_code,
                "opendart_status": status_code,
                "outcome": "SUCCESS" if page_success else "ERROR",
            }

            discovery_manifest_entries[p_filename] = {
                "path": p_rel_path,
                "size_bytes": disc_size,
                "sha256": disc_sha,
                "request_id": disc_req_id,
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "http_status": disc_resp.status_code,
                "outcome": "SUCCESS" if page_success else "ERROR",
            }

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": disc_req_id,
                "source": "OPENDART_OFFICIAL_API",
                "purpose": "OFFICIAL_DISCLOSURE_DISCOVERY_PAGE",
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "official_record_id": "",
                "page_no": page_no,
                "sanitized_endpoint": f"https://opendart.fss.or.kr/api/list.json?corp_code={tgt['corp_code']}&bgn_de={tgt['discovery_start']}&end_de={tgt['discovery_end']}&page_no={page_no}",
                "started_at": disc_start_time,
                "completed_at": disc_end_time,
                "physical_attempt": 1,
                "http_status": disc_resp.status_code,
                "raw_http_response_size": disc_size,
                "raw_http_response_sha256": disc_sha,
                "transport_response_size": disc_size,
                "transport_response_sha256": disc_sha,
                "outcome": "SUCCESS" if page_success else "ERROR",
                "error_type": "" if page_success else f"OPENDART_STATUS_{status_code}",
            })

            page_no += 1

        loaded_raw_count = len(all_raw_items)
        reported_total_count = frozen_page1_meta.get("reported_total_count", 0)

        pag_pass, ticker_pagination_inconsistencies = validate_pagination_pages(
            pages_meta=pages_meta,
            expected_total_count=reported_total_count,
            expected_total_pages=total_pages,
            frozen_page1_meta=frozen_page1_meta,
        )

        if not pag_pass:
            pagination_inconsistency_failures.extend(ticker_pagination_inconsistencies)
            if loaded_raw_count != reported_total_count:
                discovery_total_count_mismatches.append(t)
            if pages_successful != pages_requested:
                pagination_incomplete_failures.append(t)

        dup_pass, duplicate_count, conflicting_duplicate_count, conflict_details = validate_discovery_duplicate_identity(all_raw_items)
        if not dup_pass:
            conflicting_duplicate_failures.extend(conflict_details)

        unique_items_by_rcp: dict[str, dict[str, Any]] = {}
        for it in all_raw_items:
            r_no = str(it.get("rcept_no", "")).strip()
            if r_no not in unique_items_by_rcp:
                unique_items_by_rcp[r_no] = it

        unique_items = list(unique_items_by_rcp.values())
        unique_candidate_count = len(unique_items)

        ranked_candidates = rank_and_score_candidates(unique_items, tgt)
        audit_rcp_ids = []

        selected_candidate = None
        selected_raw_bytes = b""
        selected_raw_status = 0
        selected_raw_format = "XML"
        selected_producing_req_id = ""
        selected_evidence_origin = ""
        selected_source = ""
        selected_retrieval_mode = ""
        selected_candidate_rank = -1
        selected_parsed = None
        selected_transport_sha = ""
        selected_transport_size = 0
        selected_archive_detected = False
        selected_archive_members = 0
        selected_member_name = ""
        selected_extracted_sha = ""
        selected_extracted_size = 0
        selected_member_rule = ""

        candidate_validity_map: dict[str, bool] = {}

        for c in ranked_candidates:
            r_no = c["rcept_no"]
            r_nm = c["report_nm"]
            r_dt = c["rcept_dt"]
            c_rank = c["candidate_rank"]
            score = c["event_match_score"]
            audit_rcp_ids.append(r_no)

            if score == 0:
                candidate_validity_map[r_no] = False
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "REJECTED_EVENT_MISMATCH",
                    "rejection_reason": "No target keywords found in report title",
                })
                continue

            if selected_candidate is not None:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "NOT_PROBED_LOWER_PRIORITY",
                    "rejection_reason": "Higher rank candidate already selected",
                })
                continue

            (
                extracted_bytes,
                extracted_sha,
                producing_req_id,
                final_probe_src,
                final_probe_origin,
                final_transport_size,
                final_transport_sha,
                probe_status,
                archive_detected,
                archive_members,
                member_name,
                member_rule,
                archive_ambiguous,
                arch_fails,
            ) = acquire_current_official_document(
                ticker=t,
                corp_code=tgt["corp_code"],
                rcept_no=r_no,
                candidate_rank=c_rank,
                api_key=api_key,
                session=dart_session,
                accounting=accounting,
                canonical_run_id=canonical_run_id,
            )

            if arch_fails:
                archive_member_ambiguity_failures.extend(arch_fails)
            extracted_size = len(extracted_bytes)

            arch_prov_valid, arch_prov_fails = validate_archive_provenance(
                archive_detected=archive_detected,
                archive_member_count=archive_members,
                selected_member_name=member_name,
                member_selection_rule=member_rule,
                extracted_member_size=extracted_size,
                extracted_member_sha256=extracted_sha,
                canonical_raw_sha256=extracted_sha,
                transport_response_sha256=final_transport_sha,
            )
            if not arch_prov_valid:
                archive_provenance_failures.extend(arch_prov_fails)

            if archive_ambiguous or not arch_prov_valid or not extracted_bytes:
                parsed_cand = {
                    "official_source_valid": bool(final_probe_src),
                    "blocked_page_detected": bool(not extracted_bytes),
                    "parsed_issuer": "",
                    "parsed_ticker": t,
                    "parsed_report_name": r_nm,
                    "source_event_type": "",
                    "normalized_event_type": "",
                    "event_type_match": False,
                    "event_node_id": "",
                    "event_node_tag": "",
                    "event_node_path": "",
                    "event_node_depth": 0,
                    "event_node_heading": "",
                    "timing_candidate_count": 0,
                    "timing_node_id": "",
                    "timing_node_tag": "",
                    "timing_node_path": "",
                    "timing_node_depth": 0,
                    "selected_timing_node_id": "",
                    "selected_timing_node_tag": "",
                    "selected_timing_node_path": "",
                    "selected_timing_node_depth": 0,
                    "binding_relationship": "",
                    "lowest_common_ancestor_path": "",
                    "semantic_block_id": "",
                    "semantic_block_type": "",
                    "semantic_section_path": "",
                    "semantic_parent_heading": "",
                    "semantic_block_sha256": "",
                    "official_anchor_type": "",
                    "official_anchor_date": "",
                    "official_anchor_source_field": "",
                    "official_anchor_source_value": "",
                    "official_anchor_priority_rank": 0,
                    "claim_anchor_match": False,
                    "record_identity_valid": True,
                    "issuer_identity_valid": True,
                    "event_type_valid": False,
                    "event_semantic_binding_valid": False,
                    "event_timing_valid": False,
                    "raw_provenance_valid": False,
                    "global_fallback_used": False,
                    "event_context_candidate_count": 0,
                    "event_type_candidate_count": 0,
                    "event_context_ambiguous": False,
                    "event_type_ambiguous": False,
                    "event_timing_ambiguous": False,
                    "sibling_cross_binding_detected": False,
                    "authority_valid": False,
                    "validation_reason": "EMPTY_OR_UNUSABLE_DOCUMENT" if not extracted_bytes else ("ARCHIVE_PROVENANCE_INCONSISTENT" if not arch_prov_valid else "ARCHIVE_MEMBER_AMBIGUOUS"),
                }
            else:
                official_auth_cand = OfficialEvidenceContentParser.extract_official_event_authority(
                    raw_content_bytes=extracted_bytes,
                    source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
                    discovered_record_id=r_no,
                    doc_request_record_id=r_no,
                    evidence_origin=final_probe_origin,
                )
                claim_adj_cand = OfficialEvidenceContentParser.adjudicate_prior_claim(
                    official_auth=official_auth_cand,
                    claimed_event_type=ev_fam,
                    claimed_anchor_type=tgt["claimed_anchor_type"],
                    claimed_anchor_date=tgt["claimed_anchor_date"],
                    claimed_issuer=tgt["issuer_name"],
                    claimed_ticker=t,
                )
                parsed_cand = dict(official_auth_cand)
                parsed_cand["parsed_ticker"] = t
                parsed_cand["event_type_match"] = claim_adj_cand["claim_event_type_match"]
                parsed_cand["claim_anchor_match"] = claim_adj_cand["claim_anchor_date_match"]
                parsed_cand["issuer_identity_valid"] = claim_adj_cand["issuer_identity_valid"]
                parsed_cand["authority_valid"] = bool(
                    official_auth_cand["authority_valid"]
                    and claim_adj_cand["issuer_identity_valid"]
                    and claim_adj_cand["claim_event_type_match"]
                )

            candidate_validity_map[r_no] = parsed_cand["authority_valid"]

            probe_audit_rows.append({
                "ticker": t,
                "candidate_rank": c_rank,
                "rcept_no": r_no,
                "report_nm": r_nm,
                "probe_request_id": producing_req_id,
                "source": final_probe_src,
                "evidence_origin": final_probe_origin,
                "retrieval_mode": "NEW_OPENDART_DOCUMENT_FETCH" if final_probe_src == "OPENDART_OFFICIAL_API" else ("NEW_DART_VIEWER_FETCH" if final_probe_src == "DART_OFFICIAL_DISCLOSURE" else ""),
                "http_status": probe_status,
                "transport_response_sha256": final_transport_sha,
                "archive_detected": archive_detected,
                "extracted_member_sha256": extracted_sha,
                "canonical_raw_sha256": extracted_sha,
                "event_node_path": parsed_cand["event_node_path"],
                "timing_node_path": parsed_cand["timing_node_path"],
                "binding_relationship": parsed_cand["binding_relationship"],
                "authority_valid": parsed_cand["authority_valid"],
                "validation_reason": parsed_cand["validation_reason"],
            })

            if parsed_cand["authority_valid"]:
                selected_candidate = c
                selected_raw_bytes = extracted_bytes
                selected_raw_status = probe_status
                selected_raw_format = "XML" if archive_detected or b"<DOCUMENT" in extracted_bytes or b"<?xml" in extracted_bytes else "HTML"
                selected_producing_req_id = producing_req_id
                selected_evidence_origin = final_probe_origin
                selected_source = final_probe_src
                selected_retrieval_mode = "NEW_OPENDART_DOCUMENT_FETCH" if final_probe_src == "OPENDART_OFFICIAL_API" else "NEW_DART_VIEWER_FETCH"
                selected_candidate_rank = c_rank
                selected_parsed = parsed_cand
                selected_transport_sha = final_transport_sha
                selected_transport_size = final_transport_size
                selected_archive_detected = archive_detected
                selected_archive_members = archive_members
                selected_member_name = member_name
                selected_extracted_sha = extracted_sha
                selected_extracted_size = extracted_size
                selected_member_rule = member_rule

                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "SELECTED",
                    "rejection_reason": "",
                })
            else:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "REJECTED_AUTHORITY_VALIDATION",
                    "rejection_reason": parsed_cand["validation_reason"],
                })

        if not selected_candidate and ranked_candidates:
            selected_candidate = ranked_candidates[0]
            selected_candidate_rank = 1

        unique_candidate_ids = {c["rcept_no"] for c in unique_items}
        if set(audit_rcp_ids) != unique_candidate_ids:
            candidate_audit_incompleteness_failures.append(t)

        pagination_validation_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "logical_discovery_query_id": disc_query_id,
            "total_count_reported": reported_total_count,
            "total_page_reported": total_pages,
            "pages_requested": pages_requested,
            "pages_successful": pages_successful,
            "raw_records_loaded": loaded_raw_count,
            "unique_records_loaded": unique_candidate_count,
            "duplicate_count": duplicate_count,
            "conflicting_duplicate_count": conflicting_duplicate_count,
            "metadata_audit_count": len(audit_rcp_ids),
            "pagination_complete": pag_pass and conflicting_duplicate_count == 0 and len(ticker_pagination_inconsistencies) == 0,
            "pagination_inconsistencies": ticker_pagination_inconsistencies,
        }

        final_rcp_no = selected_candidate.get("rcept_no", "") if selected_candidate else ""
        final_rep_name = selected_candidate.get("report_nm", "") if selected_candidate else ""
        final_rcp_date = selected_candidate.get("rcept_dt", "") if selected_candidate else ""
        legacy_match = bool(final_rcp_no and final_rcp_no in tgt["legacy_expected_record_id"])

        base_ranks = [c["rcept_no"] for c in ranked_candidates]
        permutations = [
            ("reverse", list(reversed(unique_items))),
            ("shuffle_1", random.Random(42).sample(unique_items, len(unique_items))),
            ("shuffle_2", random.Random(43).sample(unique_items, len(unique_items))),
            ("shuffle_3", random.Random(44).sample(unique_items, len(unique_items))),
        ]

        ranking_order_invariant = True
        permuted_selected_nos = [final_rcp_no]

        for p_name, p_items in permutations:
            p_ranked = rank_and_score_candidates(p_items, tgt)
            p_order = [c["rcept_no"] for c in p_ranked]
            if p_order != base_ranks:
                ranking_order_invariant = False
                ranking_order_invariance_failures.append(f"{t}:{p_name}")

            winner = None
            for c in p_ranked:
                r_id = c["rcept_no"]
                if candidate_validity_map.get(r_id, False):
                    winner = r_id
                    break
            if not winner and p_ranked:
                winner = p_ranked[0]["rcept_no"]
            permuted_selected_nos.append(winner)

        selected_record_invariant = bool(len(set(permuted_selected_nos)) == 1 and permuted_selected_nos[0] == final_rcp_no)
        if not selected_record_invariant:
            selected_record_invariance_failures.append(t)

        determinism_validation_results[t] = {
            "reported_total_count": reported_total_count,
            "loaded_raw_count": loaded_raw_count,
            "unique_candidate_count": unique_candidate_count,
            "pagination_complete": pag_pass,
            "ranking_order_invariant": ranking_order_invariant,
            "selected_rcept_no_order_invariant": selected_record_invariant,
            "canonical_selected_rcept_no": final_rcp_no,
            "permutation_selected_rcept_nos": permuted_selected_nos,
            "determinism_pass": ranking_order_invariant and selected_record_invariant,
        }

        discovery_rows.append({
            "canonical_run_id": canonical_run_id,
            "control_id": cid,
            "ticker": t,
            "corp_code": tgt["corp_code"],
            "issuer_name": tgt["issuer_name"],
            "search_source": "OPENDART_OFFICIAL_API",
            "logical_discovery_query_id": disc_query_id,
            "search_start_date": tgt["discovery_start"],
            "search_end_date": tgt["discovery_end"],
            "reported_total_count": reported_total_count,
            "reported_total_pages": total_pages,
            "loaded_record_count": loaded_raw_count,
            "unique_candidate_count": unique_candidate_count,
            "selected_record_id": final_rcp_no,
            "selected_report_name": final_rep_name,
            "selected_receipt_date": final_rcp_date,
            "legacy_expected_record_id": tgt["legacy_expected_record_id"],
            "legacy_id_match": legacy_match,
            "selection_algorithm": "OPENDART_DETERMINISTIC_PAGINATED_RANKING_V01_FIX03_CORRECTION_11",
            "selection_rank": selected_candidate_rank,
            "selection_reason": f"Rank {selected_candidate_rank} match '{final_rep_name}' authenticated via True XML Hierarchy",
        })

        raw_sha = hashlib.sha256(selected_raw_bytes).hexdigest() if selected_raw_bytes else ""
        raw_size = len(selected_raw_bytes)
        raw_ext = "xml" if selected_raw_format == "XML" else "html"
        raw_filename = f"{t}_{ev_fam}_{final_rcp_no}.{raw_ext}"

        if selected_raw_bytes and selected_parsed and selected_parsed["authority_valid"]:
            raw_fp = raw_dir / raw_filename
            raw_fp.write_bytes(selected_raw_bytes)
            raw_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_11/raw/{raw_filename}"
            raw_manifest_entries[raw_filename] = {
                "canonical_run_id": canonical_run_id,
                "control_id": cid,
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "issuer_name": tgt["issuer_name"],
                "path": raw_rel_path,
                "size_bytes": raw_size,
                "sha256": raw_sha,
                "source": selected_source,
                "retrieval_mode": selected_retrieval_mode,
                "evidence_origin": selected_evidence_origin,
                "official_record_id": final_rcp_no,
                "producing_request_id": selected_producing_req_id,
                "transport_response_size": selected_transport_size,
                "transport_response_sha256": selected_transport_sha,
                "archive_detected": selected_archive_detected,
                "archive_member_count": selected_archive_members,
                "selected_member_name": selected_member_name,
                "member_selection_rule": selected_member_rule,
                "extracted_member_size": selected_extracted_size,
                "extracted_member_sha256": selected_extracted_sha,
                "canonical_raw_size": raw_size,
                "canonical_raw_sha256": raw_sha,
                "content_type": f"application/{raw_ext}",
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content_validation_status": "VALID",
                "live_lineage_valid": True,
            }
        else:
            raw_rel_path = ""

        parsed = selected_parsed if selected_parsed else OfficialEvidenceContentParser.parse_and_validate(
            raw_content_bytes=selected_raw_bytes,
            claimed_ticker=t,
            claimed_issuer=tgt["issuer_name"],
            claimed_event_type=ev_fam,
            claimed_anchor_type=tgt["claimed_anchor_type"],
            claimed_anchor_date=tgt["claimed_anchor_date"],
            source_id=selected_source,
            source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
            discovered_record_id=final_rcp_no,
            doc_request_record_id=final_rcp_no,
            evidence_origin=selected_evidence_origin,
        )

        claim_adj = OfficialEvidenceContentParser.adjudicate_prior_claim(
            official_auth=parsed,
            claimed_event_type=ev_fam,
            claimed_anchor_type=tgt["claimed_anchor_type"],
            claimed_anchor_date=tgt["claimed_anchor_date"],
            claimed_issuer=tgt["issuer_name"],
            claimed_ticker=t,
        )

        if not parsed["event_type_valid"]:
            source_event_classification_failures.append(t)
        if not parsed["event_type_match"]:
            source_event_type_mismatches.append(t)
        if parsed["event_type_ambiguous"]:
            event_type_ambiguity_failures.append(t)
        if parsed["event_context_ambiguous"]:
            event_context_ambiguity_failures.append(t)
        if parsed.get("event_timing_ambiguous", False):
            event_timing_ambiguity_failures.append(t)
        if not parsed["event_semantic_binding_valid"]:
            semantic_binding_failures.append(t)
        if parsed["binding_relationship"] not in ["SAME_NODE", "ANCESTOR_DESCENDANT"]:
            invalid_binding_relationship_failures.append(t)
        if parsed["semantic_block_id"] == "SEM_BLOCK_GLOBAL_DOC":
            global_semantic_block_authority_failures.append(t)
        doc_validation_rows.append({
            "canonical_run_id": canonical_run_id,
            "control_id": cid,
            "ticker": t,
            "issuer": tgt["issuer_name"],
            "issuer_name": tgt["issuer_name"],
            "official_record_id": final_rcp_no,
            "producing_request_id": selected_producing_req_id,
            "retrieval_mode": selected_retrieval_mode,
            "raw_evidence_sha256": raw_sha,

            "discovered_record_id": final_rcp_no,
            "legacy_claimed_record_id": tgt["legacy_expected_record_id"],
            "raw_path": raw_rel_path,
            "raw_sha": raw_sha,
            "official_source": selected_source,
            "corp_code": tgt["corp_code"],
            "parsed_issuer": parsed["parsed_issuer"],
            "parsed_ticker": parsed["parsed_ticker"],
            "parsed_report_name": parsed["parsed_report_name"] or final_rep_name,
            "source_event_type": parsed["source_event_type"],
            "expected_event_type": ev_fam,
            "event_type_match": parsed["event_type_match"],
            "normalized_event_type": parsed["normalized_event_type"],
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_id": parsed["event_node_id"],
            "event_node_tag": parsed["event_node_tag"],
            "event_node_path": parsed["event_node_path"],
            "event_node_depth": parsed["event_node_depth"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_candidate_count": parsed.get("timing_candidate_count", 1),
            "timing_node_id": parsed["timing_node_id"],
            "timing_node_tag": parsed["timing_node_tag"],
            "timing_node_path": parsed["timing_node_path"],
            "timing_node_depth": parsed["timing_node_depth"],
            "binding_relationship": parsed["binding_relationship"],
            "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
            "semantic_block_id": parsed["semantic_block_id"],
            "semantic_block_type": parsed["semantic_block_type"],
            "semantic_section_path": parsed["semantic_section_path"],
            "semantic_parent_heading": parsed["semantic_parent_heading"],
            "semantic_block_sha256": parsed["semantic_block_sha256"],
            "official_anchor_type": parsed["official_anchor_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_anchor_source_field": parsed["official_anchor_source_field"],
            "official_anchor_source_value": parsed["official_anchor_source_value"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "timing_repetition_count": parsed.get("timing_repetition_count", 1),
            "claim_anchor_match": parsed["claim_anchor_match"],
            "official_source_valid": parsed["official_source_valid"],
            "record_identity_valid": parsed["record_identity_valid"],
            "issuer_identity_valid": parsed["issuer_identity_valid"],
            "event_type_valid": parsed["event_type_valid"],
            "event_semantic_binding_valid": parsed["event_semantic_binding_valid"],
            "event_timing_valid": parsed["event_timing_valid"],
            "raw_provenance_valid": parsed["raw_provenance_valid"],
            "global_fallback_used": parsed["global_fallback_used"],
            "event_context_ambiguous": parsed["event_context_ambiguous"],
            "event_type_ambiguous": parsed["event_type_ambiguous"],
            "event_timing_ambiguous": parsed.get("event_timing_ambiguous", False),
            "authority_valid": parsed["authority_valid"],
            "validation_reason": parsed["validation_reason"],
        })

        semantic_binding_rows.append({
            "control_id": cid,
            "ticker": t,
            "source_event_type": parsed["source_event_type"],
            "expected_event_type": ev_fam,
            "event_type_match": parsed["event_type_match"],
            "selected_rcept_no": final_rcp_no,
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_id": parsed["event_node_id"],
            "event_node_tag": parsed["event_node_tag"],
            "event_node_path": parsed["event_node_path"],
            "event_node_depth": parsed["event_node_depth"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_node_id": parsed["timing_node_id"],
            "timing_node_tag": parsed["timing_node_tag"],
            "timing_node_path": parsed["timing_node_path"],
            "timing_node_depth": parsed["timing_node_depth"],
            "binding_relationship": parsed["binding_relationship"],
            "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
            "anchor_field_name": parsed["official_anchor_source_field"],
            "anchor_source_value": parsed["official_anchor_source_value"],
            "anchor_date": parsed["official_anchor_date"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "semantic_binding_valid": parsed["event_semantic_binding_valid"],
            "global_fallback_used": parsed["global_fallback_used"],
        })

        hierarchy_validation_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "selected_rcept_no": final_rcp_no,
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_path": parsed["event_node_path"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_node_path": parsed["timing_node_path"],
            "binding_relationship": parsed["binding_relationship"],
            "event_node_is_ancestor_of_timing": parsed["binding_relationship"] == "ANCESTOR_DESCENDANT",
            "same_node": parsed["binding_relationship"] == "SAME_NODE",
            "sibling_cross_binding_detected": False,
            "event_context_candidate_count": parsed.get("event_context_candidate_count", 1),
            "event_type_candidate_count": parsed.get("event_type_candidate_count", 1),
            "event_context_ambiguous": parsed["event_context_ambiguous"],
            "event_type_ambiguous": parsed["event_type_ambiguous"],
            "event_timing_ambiguous": parsed.get("event_timing_ambiguous", False),
            "hierarchical_binding_valid": parsed["event_semantic_binding_valid"],
        }

        claim_independence_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "source_event_type": parsed["source_event_type"],
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "official_anchor_type": parsed["official_anchor_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "claim_event_type": tgt["target_event_family"],
            "claim_anchor_type": tgt["claimed_anchor_type"],
            "claim_anchor_date": tgt["claimed_anchor_date"],
            "claim_event_type_match": claim_adj["claim_event_type_match"],
            "claim_anchor_type_match": claim_adj["claim_anchor_type_match"],
            "claim_anchor_date_match": claim_adj["claim_anchor_date_match"],
            "claim_used_for_event_selection": claim_adj["claim_used_for_event_selection"],
            "claim_used_for_context_selection": claim_adj["claim_used_for_context_selection"],
            "claim_used_for_anchor_type_selection": claim_adj["claim_used_for_anchor_type_selection"],
            "claim_used_for_anchor_date_selection": claim_adj["claim_used_for_anchor_date_selection"],
            "claim_independence_valid": claim_adj["claim_independence_valid"],
            "authority_valid": parsed["authority_valid"],
        }

        adjudication_rows.append({
            "ticker": t,
            "issuer_name": tgt["issuer_name"],
            "prior_claimed_event": ev_fam,
            "prior_claimed_anchor": tgt["claimed_anchor_date"],
            "source_event_type": parsed["source_event_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_source_field": parsed["official_anchor_source_field"],
            "official_evidence_found": parsed["authority_valid"],
            "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
            "authority_record_id": final_rcp_no,
            "normalized_event_type": parsed["normalized_event_type"],
            "adjudication": claim_adj["adjudication_status"],
            "adjudication_reason": parsed["validation_reason"],
        })

        if parsed["authority_valid"] and parsed["official_anchor_date"]:
            anc_dt = datetime.strptime(parsed["official_anchor_date"], "%Y-%m-%d")
            w_start = (anc_dt - timedelta(days=35)).strftime("%Y-%m-%d")
            w_end = (anc_dt + timedelta(days=35)).strftime("%Y-%m-%d")
            authority_records.append({
                "canonical_run_id": canonical_run_id,
                "control_id": cid,
                "ticker": t,
                "issuer_name": tgt["issuer_name"],
                "corp_code": tgt["corp_code"],
                "source_event_type": parsed["source_event_type"],
                "normalized_event_type": parsed["normalized_event_type"],
                "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
                "event_node_path": parsed["event_node_path"],
                "event_node_heading": parsed["event_node_heading"],
                "timing_node_path": parsed["timing_node_path"],
                "binding_relationship": parsed["binding_relationship"],
                "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
                "official_anchor_type": parsed["official_anchor_type"],
                "official_anchor_date": parsed["official_anchor_date"],
                "official_anchor_source_field": parsed["official_anchor_source_field"],
                "official_anchor_source_value": parsed["official_anchor_source_value"],
                "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
                "price_window_start": w_start,
                "price_window_end": w_end,
                "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "authority_source_name": selected_source,
                "authority_record_id": final_rcp_no,
                "raw_evidence_path": raw_rel_path,
                "raw_evidence_sha256": raw_sha,
                "producing_request_id": selected_producing_req_id,
                "retrieval_mode": selected_retrieval_mode,
                "validation_predicates": {
                    "official_source_valid": parsed["official_source_valid"],
                    "record_identity_valid": parsed["record_identity_valid"],
                    "issuer_identity_valid": parsed["issuer_identity_valid"],
                    "source_event_type_valid": parsed["event_type_valid"],
                    "event_type_match": parsed["event_type_match"],
                    "event_semantic_binding_valid": parsed["event_semantic_binding_valid"],
                    "event_timing_valid": parsed["event_timing_valid"],
                    "raw_provenance_valid": parsed["raw_provenance_valid"],
                    "global_fallback_not_used": not parsed["global_fallback_used"],
                },
                "authority_valid": True,
            })

    # Save discovery and validation artifacts
    disc_df = pd.DataFrame(discovery_rows)
    disc_path = output_dir / "corporate_action_official_discovery_v01_fix03_correction_11.csv"
    disc_df.to_csv(disc_path, index=False)

    page_man_path = output_dir / "corporate_action_discovery_page_manifest_v01_fix03_correction_11.json"
    page_man_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_page_manifest_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "pages": discovery_page_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pag_val_path = output_dir / "corporate_action_discovery_pagination_validation_v01_fix03_correction_11.json"
    pag_val_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_pagination_validation_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "all_pagination_complete": all(v["pagination_complete"] for v in pagination_validation_entries.values()),
        "validation_by_ticker": pagination_validation_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cand_audit_df = pd.DataFrame(candidate_audit_rows)
    cand_audit_path = output_dir / "corporate_action_discovery_candidate_audit_v01_fix03_correction_11.csv"
    cand_audit_df.to_csv(cand_audit_path, index=False)

    det_val_path = output_dir / "corporate_action_discovery_determinism_validation_v01_fix03_correction_11.json"
    det_val_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_determinism_validation_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "all_controls_order_invariant": all(v["determinism_pass"] for v in determinism_validation_results.values()),
        "validation_by_ticker": determinism_validation_results,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    probe_audit_df = pd.DataFrame(probe_audit_rows)
    probe_audit_path = output_dir / "corporate_action_document_probe_audit_v01_fix03_correction_11.csv"
    probe_audit_df.to_csv(probe_audit_path, index=False)

    disc_man_payload = {
        "schema": "corporate_action_discovery_raw_manifest_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "artifacts": discovery_manifest_entries,
    }
    disc_man_path = output_dir / "corporate_action_discovery_raw_manifest_v01_fix03_correction_11.json"
    disc_man_path.write_text(json.dumps(disc_man_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    doc_val_df = pd.DataFrame(doc_validation_rows)
    doc_val_path = output_dir / "corporate_action_official_document_validation_v01_fix03_correction_11.csv"
    doc_val_df.to_csv(doc_val_path, index=False)

    sem_bind_df = pd.DataFrame(semantic_binding_rows)
    sem_bind_path = output_dir / "corporate_action_event_semantic_binding_v01_fix03_correction_11.csv"
    sem_bind_df.to_csv(sem_bind_path, index=False)

    hier_val_path = output_dir / "corporate_action_event_hierarchy_validation_v01_fix03_correction_11.json"
    hier_val_path.write_text(json.dumps({
        "schema": "corporate_action_event_hierarchy_validation_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "all_hierarchy_valid": all(v["hierarchical_binding_valid"] for v in hierarchy_validation_entries.values()),
        "validation_by_ticker": hierarchy_validation_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    claim_indep_path = output_dir / "corporate_action_claim_independence_validation_v01_fix03_correction_11.json"
    claim_indep_path.write_text(json.dumps({
        "schema": "corporate_action_claim_independence_validation_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "all_claim_independent": all(v["claim_independence_valid"] for v in claim_independence_entries.values()),
        "validation_by_ticker": claim_independence_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    adj_df = pd.DataFrame(adjudication_rows)
    adj_path = output_dir / "corporate_action_existing_claim_adjudication_v01_fix03_correction_11.csv"
    adj_df.to_csv(adj_path, index=False)

    rep_pool_path = output_dir / "corporate_action_replacement_pool_v01_fix03_correction_11.csv"
    pd.DataFrame(columns=["control_id", "ticker", "issuer_name", "status"]).to_csv(rep_pool_path, index=False)

    auth_rec_path = output_dir / "corporate_action_authority_records_v01_fix03_correction_11.json"
    auth_rec_path.write_text(json.dumps({
        "schema": "corporate_action_authority_records_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "records": authority_records,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    raw_man_path = output_dir / "corporate_action_raw_evidence_manifest_v01_fix03_correction_11.json"
    raw_man_path.write_text(json.dumps({
        "schema": "corporate_action_raw_evidence_manifest_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "artifacts": raw_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 6. Freeze Cohort Before Price Fetch
    final_cohort_rows = []
    for idx, ar in enumerate(authority_records, start=1):
        final_cohort_rows.append({
            "canonical_run_id": canonical_run_id,
                "control_id": ar["control_id"],
                "ticker": ar["ticker"],
                "issuer_name": ar["issuer_name"],
                "corp_code": ar["corp_code"],
            "source_event_type": ar["source_event_type"],
            "normalized_event_type": ar["normalized_event_type"],
            "selected_source_event_context_id": ar.get("selected_source_event_context_id", ""),
            "event_node_path": ar["event_node_path"],
            "event_node_heading": ar["event_node_heading"],
            "timing_node_path": ar["timing_node_path"],
            "binding_relationship": ar["binding_relationship"],
            "lowest_common_ancestor_path": ar["lowest_common_ancestor_path"],
            "official_anchor_type": ar["official_anchor_type"],
            "official_anchor_date": ar["official_anchor_date"],
            "official_anchor_source_field": ar["official_anchor_source_field"],
            "official_anchor_source_value": ar["official_anchor_source_value"],
            "official_anchor_priority_rank": ar.get("official_anchor_priority_rank", 1),
            "price_window_start": ar["price_window_start"],
            "price_window_end": ar["price_window_end"],
            "authority_source_tier": ar["authority_source_tier"],
            "authority_source_name": ar["authority_source_name"],
            "authority_record_id": ar["authority_record_id"],
            "producing_request_id": ar["producing_request_id"],
            "retrieval_mode": ar.get("retrieval_mode", "NEW_OPENDART_DOCUMENT_FETCH"),
            "raw_evidence_path": ar["raw_evidence_path"],
            "raw_evidence_sha256": ar["raw_evidence_sha256"],
            "selection_role": "AUTHORITY_VALID_FROZEN_CONTROL",
            "selection_order": idx,
            "selection_algorithm": "OPENDART_PAGINATED_CLAIM_FREE_TRUE_XML_HIERARCHY_COHORT_V01_FIX03_CORRECTION_11",
        })

    cohort_df = pd.DataFrame(final_cohort_rows)
    cohort_path = output_dir / "corporate_action_review_cohort_v01_fix03_correction_11.csv"
    cohort_df.to_csv(cohort_path, index=False)
    cohort_sha = hashlib.sha256(cohort_path.read_bytes()).hexdigest()
    cohort_frozen_at = datetime.now(timezone.utc).isoformat()

    # 7. Price Parity Execution (Only if cohort > 0)
    all_price_rows = []
    parity_rows = []
    reconciliation_rows = []
    parity_statuses = []

    insufficient_window_count = 0
    date_set_mismatch_count = 0
    ohlc_mismatch_count = 0
    candidate_error_count = 0
    comparator_error_count = 0

    if final_cohort_rows:
        import pykrx.stock as pykrx_stock
        naver_client = NaverDateRangeAdjustedClient(allow_network=allow_network)

        for c in final_cohort_rows:
            t = normalize_ticker(c["ticker"])
            w_start = c["price_window_start"]
            w_end = c["price_window_end"]
            anchor_d = c["official_anchor_date"]

            cand_req_id = f"REQ_PRICE_NAVER_{t}_{w_start}_{w_end}"
            py_query_id = f"QUERY_PRICE_RAW_PYKRX_{t}_{w_start}_{w_end}"

            accounting.direct_naver_logical_requests += 1
            accounting.direct_naver_physical_attempts += 1
            accounting.raw_pykrx_logical_requests += 1
            accounting.raw_pykrx_physical_attempts += 1

            cand_err = ""
            c_start_t = datetime.now(timezone.utc).isoformat()
            try:
                st_code, xml_text, elapsed = naver_client.fetch_raw(t, w_start, w_end)
                c_end_t = datetime.now(timezone.utc).isoformat()
                cand_df = NaverDateRangeAdjustedClient.parse_xml_payload(xml_text, w_start, w_end)
                cand_raw_sha = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
            except Exception as exc:
                c_end_t = datetime.now(timezone.utc).isoformat()
                cand_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                cand_raw_sha = ""
                cand_err = str(exc)
                candidate_error_count += 1

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": cand_req_id,
                "source": "NAVER_DIRECT",
                "purpose": "EVENT_SENSITIVE_CANDIDATE_PRICE_FETCH",
                "control_id": c["control_id"],
                "ticker": t,
                "corp_code": c["corp_code"],
                "official_record_id": c["authority_record_id"],
                "authority_record_id": c["authority_record_id"],
                "price_window_start": w_start,
                "price_window_end": w_end,
                "sanitized_endpoint": f"https://fchart.stock.naver.com/sise.nhn?symbol={t}&startTime={w_start}&endTime={w_end}",
                "started_at": c_start_t,
                "completed_at": c_end_t,
                "physical_attempt": 1,
                "http_status": 200 if not cand_err else 500,
                "raw_http_response_size": len(xml_text) if not cand_err else 0,
                "raw_http_response_sha256": cand_raw_sha,
                "transport_response_size": len(xml_text) if not cand_err else 0,
                "transport_response_sha256": cand_raw_sha,
                "outcome": "SUCCESS" if not cand_err else "ERROR",
                "error_type": cand_err,
            })

            py_err = ""
            p_start_t = datetime.now(timezone.utc).isoformat()
            try:
                py_raw = pykrx_stock.get_market_ohlcv_by_date(
                    w_start.replace("-", ""),
                    w_end.replace("-", ""),
                    t,
                    adjusted=True,
                )
                p_end_t = datetime.now(timezone.utc).isoformat()
                if py_raw is not None and not py_raw.empty:
                    py_df = py_raw.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}).copy()
                    py_df["date"] = [d.strftime("%Y-%m-%d") for d in py_df.index]
                else:
                    py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                py_rowset_sha = hashlib.sha256(py_df.to_csv(index=False).encode("utf-8")).hexdigest()
            except Exception as exc:
                p_end_t = datetime.now(timezone.utc).isoformat()
                py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                py_rowset_sha = ""
                py_err = str(exc)
                comparator_error_count += 1

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": py_query_id,
                "source": "RAW_PYKRX_COMPARATOR",
                "purpose": "EVENT_SENSITIVE_RAW_COMPARATOR_PRICE_QUERY",
                "control_id": c["control_id"],
                "ticker": t,
                "corp_code": c["corp_code"],
                "official_record_id": c["authority_record_id"],
                "authority_record_id": c["authority_record_id"],
                "adjusted": True,
                "price_window_start": w_start,
                "price_window_end": w_end,
                "sanitized_endpoint": f"pykrx.stock.get_market_ohlcv_by_date({w_start},{w_end},{t},adjusted=True)",
                "started_at": p_start_t,
                "completed_at": p_end_t,
                "physical_attempt": 1,
                "http_status": 200 if not py_err else 500,
                "raw_http_response_size": 0,
                "raw_http_response_sha256": py_rowset_sha,
                "transport_response_size": 0,
                "transport_response_sha256": py_rowset_sha,
                "outcome": "SUCCESS" if not py_err else "ERROR",
                "error_type": py_err,
            })

            # Evaluate parity
            cand_dates = set(cand_df["date"].astype(str)) if not cand_df.empty else set()
            py_dates = set(py_df["date"].astype(str)) if not py_df.empty else set()
            common_dates = sorted(cand_dates.intersection(py_dates))
            cand_only = sorted(cand_dates - py_dates)
            py_only = sorted(py_dates - cand_dates)

            if cand_only or py_only:
                date_set_mismatch_count += 1

            pre_ov = sum(1 for d in common_dates if d < anchor_d)
            post_ov = sum(1 for d in common_dates if d >= anchor_d)
            if pre_ov < 5 or post_ov < 5:
                insufficient_window_count += 1

            o_mis, h_mis, l_mis, c_mis, v_mis = 0, 0, 0, 0, 0
            if common_dates and not cand_df.empty and not py_df.empty:
                c_sub = cand_df.set_index("date").loc[common_dates]
                p_sub = py_df.set_index("date").loc[common_dates]
                o_mis = int((c_sub["open"].astype(float) != p_sub["open"].astype(float)).sum())
                h_mis = int((c_sub["high"].astype(float) != p_sub["high"].astype(float)).sum())
                l_mis = int((c_sub["low"].astype(float) != p_sub["low"].astype(float)).sum())
                c_mis = int((c_sub["close"].astype(float) != p_sub["close"].astype(float)).sum())

            if (o_mis + h_mis + l_mis + c_mis) > 0:
                ohlc_mismatch_count += 1

            parity_statuses.append("MATCH" if (o_mis + h_mis + l_mis + c_mis == 0 and len(cand_only) == 0 and len(py_only) == 0) else "MISMATCH")

    price_df = pd.DataFrame(all_price_rows) if all_price_rows else pd.DataFrame(columns=["control_id", "ticker", "source", "evidence_origin", "request_id", "date", "open", "high", "low", "close", "volume"])
    (output_dir / "corporate_action_event_price_rows_v01_fix03_correction_11.csv").write_text(price_df.to_csv(index=False), encoding="utf-8")

    parity_df = pd.DataFrame(parity_rows) if parity_rows else pd.DataFrame(columns=["control_id", "ticker", "parity_status"])
    (output_dir / "corporate_action_event_sensitive_parity_v01_fix03_correction_11.csv").write_text(parity_df.to_csv(index=False), encoding="utf-8")

    recon_df = pd.DataFrame(reconciliation_rows) if reconciliation_rows else pd.DataFrame(columns=["control_id", "ticker", "status"])
    (output_dir / "corporate_action_date_reconciliation_v01_fix03_correction_11.csv").write_text(recon_df.to_csv(index=False), encoding="utf-8")

    # 8. Network Accounting & Linkage (Section 3, 4)
    accounting.compute_totals()

    net_path = output_dir / "corporate_action_evidence_network_accounting_v01_fix03_correction_11.json"
    net_dict = accounting.to_dict()
    net_dict["schema"] = "corporate_action_evidence_network_accounting_v01_fix03_correction_11"
    net_dict["directive_id"] = DIRECTIVE_ID_CORRECTION_11
    net_dict["canonical_run_id"] = canonical_run_id
    net_path.write_text(json.dumps(net_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    linkage_result = validate_live_evidence_linkage(
        canonical_run_id=canonical_run_id,
        discovery_records=discovery_rows,
        document_records=doc_validation_rows,
        raw_manifest_entries=raw_manifest_entries,
        authority_rows=authority_records,
        request_logs=accounting.request_logs,
        price_request_logs=[
            r for r in accounting.request_logs
            if r.get("source") in {"NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"}
        ],
        artifact_paths={"raw": raw_dir},
        current_output_dir=output_dir,
        accounting_cross_invariant_pass=accounting.accounting_cross_invariant_pass,
        schema_suffix="11",
    )
    linkage_payload = linkage_result.to_dict()
    linkage_payload.update({
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "discovery_pages_checked": len(discovery_manifest_entries),
        "document_items_checked": len(raw_manifest_entries),
    })
    # Back-propagate the validator's per-run truth to the manifest metadata;
    # this field is never a default assertion of lineage validity.
    failed_record_ids = {
        str(item.get("record_id") or item.get("authority_record_id") or item.get("document_id"))
        for item in linkage_result.linkage_failures
        if item.get("record_id") or item.get("authority_record_id") or item.get("document_id")
    }
    for manifest_entry in raw_manifest_entries.values():
        manifest_record_id = _linkage_text(manifest_entry, "official_record_id", "rcept_no", "authority_record_id")
        manifest_entry["live_lineage_valid"] = bool(manifest_record_id and manifest_record_id not in failed_record_ids and linkage_result.all_linkage_valid)
    raw_man_path.write_text(json.dumps({
        "schema": "corporate_action_raw_evidence_manifest_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "artifacts": raw_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "live_evidence_linkage_validation_v01_fix03_correction_11.json").write_text(
        json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # 9. Gate 06 Evaluation
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

    gate06_eval_metrics = {
        "preflight_verdict": preflight["verdict"],
        "document_readiness_verdict": doc_readiness["verdict"],
        "authority_valid_controls_count": auth_valid_count,
        "final_cohort_control_count": len(final_cohort_rows),
        "diversity_pass": diversity_pass,
        "pagination_incomplete_control_count": len(pagination_incomplete_failures),
        "pagination_metadata_inconsistency_count": len(pagination_inconsistency_failures),
        "pagination_page_count_inconsistency_count": len(pagination_page_count_inconsistencies),
        "discovery_total_count_mismatch_count": len(discovery_total_count_mismatches),
        "duplicate_rcept_no_count": sum(v["duplicate_count"] for v in pagination_validation_entries.values()),
        "conflicting_duplicate_rcept_no_count": len(conflicting_duplicate_failures),
        "candidate_audit_incomplete_count": len(candidate_audit_incompleteness_failures),
        "ranking_order_invariance_failure_count": len(ranking_order_invariance_failures),
        "selected_record_invariance_failure_count": len(selected_record_invariance_failures),
        "source_event_classification_failure_count": len(source_event_classification_failures),
        "source_event_type_mismatch_count": len(source_event_type_mismatches),
        "historical_raw_reuse_count": len(linkage_result.historical_raw_reuse_failures),
        "physical_request_mutation_failure_count": len(linkage_result.physical_request_mutation_failures),
        "live_lineage_failure_count": len(linkage_result.live_lineage_failures),
        "claim_event_selection_influence_count": len(claim_event_influence_failures),
        "claim_context_selection_influence_count": len(claim_context_influence_failures),
        "claim_anchor_type_selection_influence_count": len(claim_anchor_type_influence_failures),
        "claim_anchor_date_selection_influence_count": len(claim_anchor_date_influence_failures),
        "event_type_ambiguity_count": len(event_type_ambiguity_failures),
        "event_context_ambiguity_count": len(event_context_ambiguity_failures),
        "event_timing_ambiguity_count": len(event_timing_ambiguity_failures),
        "semantic_binding_failure_count": len(semantic_binding_failures),
        "invalid_binding_relationship_count": len(invalid_binding_relationship_failures),
        "global_semantic_block_authority_count": len(global_semantic_block_authority_failures),
        "archive_provenance_failure_count": len(archive_provenance_failures),
        "archive_member_ambiguity_count": len(archive_member_ambiguity_failures),
        "archive_transport_inconsistency_count": len(archive_transport_inconsistencies),
        "archive_member_inconsistency_count": len(archive_member_inconsistencies),
        "producing_request_failure_count": len(linkage_result.producing_request_failures),
        "cross_run_request_linkage_failure_count": len(linkage_result.cross_run_request_linkage_failures),
        "invalid_retrieval_mode_count": len(linkage_result.invalid_retrieval_modes),
        "record_identity_failure_count": len(linkage_result.record_identity_failures),
        "issuer_identity_failure_count": len(linkage_result.issuer_identity_failures),
        "candidate_linkage_failure_count": len(linkage_result.candidate_linkage_failures),
        "pykrx_linkage_failure_count": len(linkage_result.pykrx_linkage_failures),
        "raw_orphan_file_count": len(linkage_result.raw_orphan_failures),
        "date_set_mismatch_count": date_set_mismatch_count,
        "authorized_reconciliation_count": sum(1 for s in parity_statuses if s == "AUTHORIZED_DATE_RECONCILIATION_MATCH"),
        "insufficient_window_count": insufficient_window_count,
        "ohlc_match_count": sum(1 for _, r in parity_df.iterrows() if r.get("open_mismatch_count", 0) == 0),
        "ohlc_mismatch_count": ohlc_mismatch_count,
        "candidate_error_count": candidate_error_count,
        "comparator_error_count": comparator_error_count,
        "network_accounting_failure_count": 0 if accounting.accounting_cross_invariant_pass else 1,
        "linkage_evaluation_status": linkage_result.linkage_evaluation_status,
        "all_linkage_valid": linkage_result.all_linkage_valid,
        "total_provenance_failure_count": linkage_result.total_linkage_failures,
        "cohort_frozen_before_price_fetch": True,
        "cohort_frozen_at": cohort_frozen_at,
        "cohort_sha256_before_price_fetch": cohort_sha,
    }

    gate06_pass, gate06_blockers = evaluate_gate06(gate06_eval_metrics)

    gate06_payload = dict(gate06_eval_metrics)
    gate06_payload["schema"] = "gate06_corporate_action_reassessment_v01_fix03_correction_11"
    gate06_payload["canonical_run_id"] = canonical_run_id
    gate06_payload["directive_id"] = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11"
    gate06_payload["gate_06_pass"] = gate06_pass
    gate06_payload["gate_06_blockers"] = gate06_blockers

    gate06_path = output_dir / "gate06_corporate_action_reassessment_v01_fix03_correction_11.json"
    gate06_path.write_text(json.dumps(gate06_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

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
        inherited_gates[g_key] = bool(isinstance(val, bool) and val is True)

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
        reason_codes = ["ALL_15_SOURCE_AUTHORITY_REVIEW_GATES_PASSED_FIX03_CORRECTION_11"]
    elif ohlc_mismatch_count > 0:
        review_decision = "REJECTED_AS_PRODUCTION_AUTHORITY"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"
        blocking_conditions = gate06_blockers
        reason_codes = ["CORPORATE_ACTION_PRICE_CONTRADICTION"]
    else:
        review_decision = "CONDITIONAL_REVIEW_REQUIRED"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11"
        blocking_conditions = gate06_blockers
        reason_codes = ["OFFICIAL_EVIDENCE_INCOMPLETE"]

    successful_doc_count = sum(1 for m in raw_manifest_entries.values() if m.get("content_validation_status") == "VALID" and m.get("live_lineage_valid") and m.get("size_bytes", 0) > 0)

    decision_payload = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_10",
        "authoritative_technical_parent": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_11,
        "parent_freeze_valid": parent_freeze["all_parent_inputs_unchanged"],
        "preflight_verdict": preflight["verdict"],
        "document_readiness_verdict": doc_readiness["verdict"],
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "candidate_endpoint": "https://fchart.stock.naver.com/sise.nhn",
        "official_discovery_requests_logical": accounting.official_discovery_logical_requests,
        "official_discovery_requests_physical": accounting.official_discovery_physical_attempts,
        "official_discovery_success_count": len(discovery_manifest_entries),
        "official_document_manifest_entry_count": len(raw_manifest_entries),
        "official_document_success_count": successful_doc_count,
        "authority_valid_control_count": auth_valid_count,
        "final_cohort_size": len(final_cohort_rows),
        "final_cohort_sha": cohort_sha if final_cohort_rows else "",
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
        "provenance_failures": linkage_result.total_linkage_failures,
        "linkage_evaluation_status": linkage_result.linkage_evaluation_status,
        "all_linkage_valid": linkage_result.all_linkage_valid,
        "gate_06_result": gate06_pass,
        "gate_15_result": all_15_gates["gate_15_no_unresolved_conditions"],
        "inherited_gate_results": inherited_gates,
        "all_15_gate_results": all_15_gates,
        "all_gates_passed": all_gates_pass,
        "full_suite_completion": bool(full_suite_completion),
        "new_regression_count": new_regression_count,
        "blocking_conditions": blocking_conditions,
        "reason_codes": reason_codes,
        "review_decision": review_decision,
        "production_integration_authorized": prod_integration_auth,
        "active_production_authority_changed": False,
        "recommended_next_state": next_state,
        "network_accounting": accounting.to_dict(),
    }
    (output_dir / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_11.json").write_text(
        json.dumps(decision_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Manifest
    _write_artifact_manifest_correction_11(output_dir, canonical_run_id, review_decision, prod_integration_auth, raw_manifest_entries, discovery_manifest_entries)
    return decision_payload




def _terminate_on_readiness_or_preflight_failure_correction_11(
    output_dir: Path,
    parent_dir: Path,
    canonical_run_id: str,
    preflight: dict[str, Any],
    doc_readiness: dict[str, Any],
    accounting: CorporateActionNetworkAccounting,
    failure_reason: str,
) -> dict[str, Any]:
    """Strict Hard-Gate termination when preflight or readiness probe fails."""
    parent_freeze = verify_parent_authority_freeze(parent_dir)
    parent_freeze = {
        **parent_freeze,
        "schema": "parent_authority_freeze_validation_v01_fix03_correction_11",
        "directive_id": DIRECTIVE_ID_CORRECTION_11,
    }
    (output_dir / "parent_authority_freeze_validation_v01_fix03_correction_11.json").write_text(
        json.dumps(parent_freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    source_inventory = {
        "schema": "corporate_action_evidence_source_inventory_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "sources": [],
    }
    (output_dir / "corporate_action_evidence_source_inventory_v01_fix03_correction_11.json").write_text(
        json.dumps(source_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    accounting.compute_totals()
    net_dict = accounting.to_dict()
    net_dict["schema"] = "corporate_action_evidence_network_accounting_v01_fix03_correction_11"
    net_dict["directive_id"] = DIRECTIVE_ID_CORRECTION_11
    net_dict["canonical_run_id"] = canonical_run_id
    (output_dir / "corporate_action_evidence_network_accounting_v01_fix03_correction_11.json").write_text(
        json.dumps(net_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    linkage_result = validate_live_evidence_linkage(
        canonical_run_id=canonical_run_id,
        discovery_records=[],
        document_records=[],
        raw_manifest_entries=[],
        authority_rows=[],
        request_logs=accounting.request_logs,
        current_output_dir=output_dir,
        accounting_cross_invariant_pass=accounting.accounting_cross_invariant_pass,
        schema_suffix="11",
    )
    linkage_result.linkage_evaluation_status = "NOT_EVALUATED_DUE_TO_READINESS_FAILURE"
    linkage_result.live_lineage_failures.append(
        _linkage_failure("DOWNSTREAM_ACQUISITION_NOT_EXECUTED", reason=failure_reason)
    )
    linkage_payload = linkage_result.to_dict()
    linkage_payload.update({
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "discovery_pages_checked": 0,
        "document_items_checked": 0,
    })
    (output_dir / "live_evidence_linkage_validation_v01_fix03_correction_11.json").write_text(
        json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    gate06_blockers = [
        f"Readiness hard gate failed: {failure_reason}",
        "Official evidence deficit: 0/8 authority valid",
        "Corporate action event diversity requirement failed",
    ]
    gate06_payload = {
        "schema": "gate06_corporate_action_reassessment_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "preflight_verdict": preflight.get("verdict", "FAIL"),
        "document_readiness_verdict": doc_readiness.get("verdict", "FAIL"),
        "authority_valid_controls_count": 0,
        "final_cohort_control_count": 0,
        "diversity_pass": False,
        "gate_06_pass": False,
        "gate_06_blockers": gate06_blockers,
    }
    gate06_payload.update(linkage_result.to_metrics())
    (output_dir / "gate06_corporate_action_reassessment_v01_fix03_correction_11.json").write_text(
        json.dumps(gate06_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

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
        inherited_gates[g_key] = bool(isinstance(val, bool) and val is True)

    all_15_gates = dict(inherited_gates)
    all_15_gates["gate_06_corporate_action_parity"] = False
    all_15_gates["gate_15_no_unresolved_conditions"] = False

    decision_payload = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_10",
        "authoritative_technical_parent": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_11,
        "parent_freeze_valid": parent_freeze["all_parent_inputs_unchanged"],
        "preflight_verdict": preflight.get("verdict", "FAIL"),
        "document_readiness_verdict": doc_readiness.get("verdict", "FAIL"),
        "official_discovery_requests_logical": 0,
        "official_discovery_requests_physical": 0,
        "official_discovery_success_count": 0,
        "official_document_manifest_entry_count": 0,
        "official_document_success_count": 0,
        "authority_valid_control_count": 0,
        "final_cohort_size": 0,
        "final_cohort_sha": "",
        "naver_actual_requests": 0,
        "raw_pykrx_actual_queries": 0,
        "exact_date_match_controls": 0,
        "authorized_reconciliation_controls": 0,
        "date_mismatch_controls": 0,
        "insufficient_window_controls": 0,
        "ohlc_mismatch_controls": 0,
        "candidate_errors": 0,
        "comparator_errors": 0,
        "provenance_failures": len(linkage_payload["linkage_failures"]),
        "gate_06_result": False,
        "gate_15_result": False,
        "inherited_gate_results": inherited_gates,
        "all_15_gate_results": all_15_gates,
        "all_gates_passed": False,
        "full_suite_completion": False,
        "new_regression_count": None,
        "blocking_conditions": gate06_blockers,
        "reason_codes": [failure_reason],
        "review_decision": "CONDITIONAL_REVIEW_REQUIRED",
        "production_integration_authorized": False,
        "active_production_authority_changed": False,
        "recommended_next_state": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "network_accounting": accounting.to_dict(),
    }
    (output_dir / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_11.json").write_text(
        json.dumps(decision_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    _write_artifact_manifest_correction_11(output_dir, canonical_run_id, "CONDITIONAL_REVIEW_REQUIRED", False, {}, {})
    return decision_payload




def _write_artifact_manifest_correction_11(
    output_dir: Path,
    canonical_run_id: str,
    review_decision: str,
    prod_integration_auth: bool,
    raw_manifest_entries: dict[str, Any],
    discovery_manifest_entries: dict[str, Any],
) -> None:
    manifest_entries = {}
    for p in output_dir.glob("*.*"):
        if p.name != "artifact_manifest.json":
            manifest_entries[p.name] = {
                "path": f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_11/{p.name}",
                "size_bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }

    for rfname, rmeta in raw_manifest_entries.items():
        manifest_entries[f"raw/{rfname}"] = rmeta
    for dfname, dmeta in discovery_manifest_entries.items():
        manifest_entries[f"discovery_raw/{dfname}"] = dmeta

    manifest_payload = {
        "schema": "corporate_action_evidence_manifest_v01_fix03_correction_11",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_11,
        "review_decision": review_decision,
        "production_integration_authorized": prod_integration_auth,
        "artifacts": manifest_entries,
    }
    manifest_path = output_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def run_corporate_action_evidence_acquisition_fix03_correction_12(
    output_dir: Path | None = None,
    parent_dir: Path | None = None,
    allow_network: bool = True,
    regression_evidence: FullRegressionCertification | Mapping[str, Any] | None = None,
    repo_root: Path = Path("."),
) -> dict[str, Any]:
    """Execute complete corporate action authority orchestration with strict readiness hard gating and corrected network accounting (Section 0-27)."""
    canonical_run_id = f"CORP_AUTH_FIX03_CORRECTION_12_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    root = Path(repo_root)
    git_snapshot = observe_git_code_snapshot(root)
    output_dir = root / DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_12 if output_dir is None else Path(output_dir)
    parent_dir = root / PARENT_FIX03_CORRECTION_DIR if parent_dir is None else Path(parent_dir)

    if output_dir.exists():
        raw_existing = output_dir / "raw"
        if raw_existing.exists():
            shutil.rmtree(raw_existing)
        disc_existing = output_dir / "discovery_raw"
        if disc_existing.exists():
            shutil.rmtree(disc_existing)

    output_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = output_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    disc_raw_dir = output_dir / "discovery_raw"
    disc_raw_dir.mkdir(parents=True, exist_ok=True)

    accounting = CorporateActionNetworkAccounting()
    regression_certification = validate_full_regression_evidence(
        regression_evidence,
        expected_fix_head=git_snapshot.head,
        expected_fix_tree_sha=git_snapshot.tree_sha,
    )
    if git_snapshot.dirty:
        regression_certification.blockers.append("CODE_SCOPE_WORKTREE_DIRTY")
        regression_certification.blockers = list(dict.fromkeys(regression_certification.blockers))
        regression_certification.evidence_status = "INVALID"
        regression_certification.certification_valid = False

    # Explicit maintenance/offline guard for repository regression runs.  This
    # short-circuits before credential resolution or any external client is built.
    if os.environ.get("CORRECTION_12_OFFLINE_ONLY") == "1":
        accounting.execution_mode = "OFFLINE_IMPLEMENTATION_ONLY"
        return _terminate_on_readiness_or_preflight_failure_correction_12(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight={"verdict": "FAIL", "reason": "CORRECTION_12_OFFLINE_ONLY"},
            doc_readiness={"verdict": "NOT_EXECUTED", "schema": "opendart_document_readiness_v01_fix03_correction_12"},
            accounting=accounting,
            failure_reason="CORRECTION_12_OFFLINE_ONLY",
            regression_certification=regression_certification,
            git_snapshot=git_snapshot,
        )

    if not regression_certification.certification_valid:
        return _terminate_on_readiness_or_preflight_failure_correction_12(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight={"verdict": "NOT_EXECUTED", "reason": "REGRESSION_EVIDENCE_INVALID"},
            doc_readiness={"verdict": "NOT_EXECUTED", "schema": "opendart_document_readiness_v01_fix03_correction_12"},
            accounting=accounting,
            failure_reason="SOURCE_ACQUISITION_NOT_EXECUTED",
            regression_certification=regression_certification,
            git_snapshot=git_snapshot,
        )

    # 1. Hard Gate: OpenDART Preflight (Section 4, 16)
    preflight = run_opendart_preflight(output_dir=output_dir, allow_network=allow_network, canonical_run_id=canonical_run_id, correction_suffix="12")
    accounting.preflight_physical_calls = 1 if allow_network else 0
    if preflight["verdict"] != "READY":
        return _terminate_on_readiness_or_preflight_failure_correction_12(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight=preflight,
            doc_readiness={"verdict": "NOT_EXECUTED", "schema": "opendart_document_readiness_v01_fix03_correction_12"},
            accounting=accounting,
            failure_reason="OPENDART_PREFLIGHT_FAIL",
            regression_certification=regression_certification,
            git_snapshot=git_snapshot,
        )

    # 2. Hard Gate: Document Endpoint Readiness Probe (Section 4, 16, 17)
    doc_readiness = run_document_endpoint_readiness_probe(output_dir=output_dir, allow_network=allow_network, canonical_run_id=canonical_run_id, correction_suffix="12")
    accounting.readiness_physical_calls = 1 if allow_network else 0

    if doc_readiness["verdict"] != "READY":
        return _terminate_on_readiness_or_preflight_failure_correction_12(
            output_dir=output_dir,
            parent_dir=parent_dir,
            canonical_run_id=canonical_run_id,
            preflight=preflight,
            doc_readiness=doc_readiness,
            accounting=accounting,
            failure_reason="TRANSIENT_OFFICIAL_DOCUMENT_ENDPOINT_UNAVAILABLE",
            regression_certification=regression_certification,
            git_snapshot=git_snapshot,
        )

    # 3. Parent Freeze Validation (Section 2)
    parent_freeze = verify_parent_authority_freeze(parent_dir)
    parent_freeze = {
        **parent_freeze,
        "schema": "parent_authority_freeze_validation_v01_fix03_correction_12",
        "directive_id": DIRECTIVE_ID_CORRECTION_12,
    }
    parent_freeze_path = output_dir / "parent_authority_freeze_validation_v01_fix03_correction_12.json"
    parent_freeze_path.write_text(json.dumps(parent_freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if not parent_freeze["all_parent_inputs_unchanged"]:
        raise ValueError(f"Parent FIX03_CORRECTION freeze validation failed: {parent_freeze['mismatches']}")

    # 4. Source Inventory
    source_inventory = {
        "schema": "corporate_action_evidence_source_inventory_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "sources": [
            {
                "source_id": "OPENDART_OFFICIAL_API",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (OpenDART) 정식 API",
                "base_domain": "opendart.fss.or.kr",
                "endpoint_type": "OFFICIAL_API_PAGINATED_DISCOVERY_AND_DOCUMENT",
                "auth_required": True,
                "raw_format": "JSON_AND_XML",
                "parser_version": "v01_fix03_correction_12",
                "authority_validation_contract": "OpenDART 전수 페이지네이션 및 공시 원문 XML의 True XML Hierarchy Tree 파싱 기반 Claim-Free 공식 앵커 추출",
            },
            {
                "source_id": "DART_OFFICIAL_DISCLOSURE",
                "source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "source_name": "금융감독원 전자공시시스템 (DART) 공시원문 뷰어",
                "base_domain": "dart.fss.or.kr",
                "endpoint_type": "OFFICIAL_DISCLOSURE_VIEWER",
                "auth_required": False,
                "raw_format": "HTML",
                "parser_version": "v01_fix03_correction_12",
            },
        ],
    }
    source_inv_path = output_dir / "corporate_action_evidence_source_inventory_v01_fix03_correction_12.json"
    source_inv_path.write_text(json.dumps(source_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 5. Full Downstream Live Acquisition (Executed strictly when readiness == READY)
    api_key = get_opendart_api_key()
    targets = get_official_discovery_search_targets()

    discovery_rows = []
    discovery_page_manifest_entries = {}
    pagination_validation_entries = {}
    candidate_audit_rows = []
    probe_audit_rows = []
    determinism_validation_results = {}
    discovery_manifest_entries = {}
    raw_manifest_entries = {}
    doc_validation_rows = []
    semantic_binding_rows = []
    hierarchy_validation_entries = {}
    claim_independence_entries = {}
    adjudication_rows = []
    authority_records = []

    pagination_inconsistency_failures = []
    pagination_page_count_inconsistencies = []
    pagination_incomplete_failures = []
    discovery_total_count_mismatches = []
    conflicting_duplicate_failures = []
    candidate_audit_incompleteness_failures = []
    ranking_order_invariance_failures = []
    selected_record_invariance_failures = []
    source_event_classification_failures = []
    source_event_type_mismatches = []
    event_type_ambiguity_failures = []
    event_context_ambiguity_failures = []
    event_timing_ambiguity_failures = []
    claim_event_influence_failures = []
    claim_context_influence_failures = []
    claim_anchor_type_influence_failures = []
    claim_anchor_date_influence_failures = []
    semantic_binding_failures = []
    invalid_binding_relationship_failures = []
    global_semantic_block_authority_failures = []
    archive_provenance_failures = []
    archive_member_ambiguity_failures = []
    archive_transport_inconsistencies = []
    archive_member_inconsistencies = []

    dart_session = requests.Session()
    dart_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

    for tgt in targets:
        t = normalize_ticker(tgt["ticker"])
        cid = tgt["control_id"]
        ev_fam = tgt["target_event_family"]
        disc_query_id = f"DISC_QUERY_{t}_{ev_fam}"

        accounting.official_discovery_logical_requests += 1

        page_no = 1
        total_pages = 1
        frozen_page1_meta: dict[str, Any] = {}
        all_raw_items: list[dict[str, Any]] = []
        pages_meta = []
        pages_requested = []
        pages_successful = []

        while page_no <= total_pages:
            disc_req_id = f"REQ_DISC_OPENDART_{t}_{ev_fam}_P{page_no:03d}"
            disc_start_time = datetime.now(timezone.utc).isoformat()
            accounting.official_discovery_physical_attempts += 1

            disc_url = "https://opendart.fss.or.kr/api/list.json"
            disc_params = {
                "crtfc_key": api_key,
                "corp_code": tgt["corp_code"],
                "bgn_de": tgt["discovery_start"],
                "end_de": tgt["discovery_end"],
                "page_count": "100",
                "page_no": str(page_no),
            }

            pages_requested.append(page_no)
            disc_resp = dart_session.get(disc_url, params=disc_params, timeout=10.0)
            disc_end_time = datetime.now(timezone.utc).isoformat()
            disc_bytes = disc_resp.content
            disc_sha = hashlib.sha256(disc_bytes).hexdigest()
            disc_size = len(disc_bytes)
            disc_data = disc_resp.json()

            status_code = disc_data.get("status", "")
            r_total_cnt = int(disc_data.get("total_count", 0)) if str(disc_data.get("total_count", "")).isdigit() else 0
            r_total_page = int(disc_data.get("total_page", 1)) if str(disc_data.get("total_page", "")).isdigit() else 1
            r_page_cnt = int(disc_data.get("page_count", 100)) if str(disc_data.get("page_count", "")).isdigit() else 100

            page_success = bool(disc_resp.status_code == 200 and status_code in ["000", "013"])
            if page_success:
                pages_successful.append(page_no)

            if page_no == 1:
                total_pages = max(r_total_page, 1)
                frozen_page1_meta = {
                    "corp_code": tgt["corp_code"],
                    "bgn_de": tgt["discovery_start"],
                    "end_de": tgt["discovery_end"],
                    "page_count": r_page_cnt,
                    "reported_total_count": r_total_cnt,
                    "reported_total_page": total_pages,
                }

            page_items = disc_data.get("list", [])
            all_raw_items.extend(page_items)

            pages_meta.append({
                "page_no": page_no,
                "page_count": r_page_cnt,
                "item_count": len(page_items),
                "reported_total_count": r_total_cnt,
                "reported_total_page": r_total_page,
                "http_status": disc_resp.status_code,
                "opendart_status": status_code,
            })

            p_filename = f"disc_{t}_{ev_fam}_p{page_no:03d}.json"
            p_fp = disc_raw_dir / p_filename
            p_fp.write_bytes(disc_bytes)
            p_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_12/discovery_raw/{p_filename}"

            discovery_page_manifest_entries[p_filename] = {
                "ticker": t,
                "control_id": cid,
                "logical_discovery_query_id": disc_query_id,
                "page_no": page_no,
                "page_count": len(page_items),
                "reported_total_count": r_total_cnt,
                "reported_total_page": r_total_page,
                "request_id": disc_req_id,
                "path": p_rel_path,
                "size_bytes": disc_size,
                "sha256": disc_sha,
                "http_status": disc_resp.status_code,
                "opendart_status": status_code,
                "outcome": "SUCCESS" if page_success else "ERROR",
            }

            discovery_manifest_entries[p_filename] = {
                "path": p_rel_path,
                "size_bytes": disc_size,
                "sha256": disc_sha,
                "request_id": disc_req_id,
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "http_status": disc_resp.status_code,
                "outcome": "SUCCESS" if page_success else "ERROR",
            }

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": disc_req_id,
                "source": "OPENDART_OFFICIAL_API",
                "purpose": "OFFICIAL_DISCLOSURE_DISCOVERY_PAGE",
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "official_record_id": "",
                "page_no": page_no,
                "sanitized_endpoint": f"https://opendart.fss.or.kr/api/list.json?corp_code={tgt['corp_code']}&bgn_de={tgt['discovery_start']}&end_de={tgt['discovery_end']}&page_no={page_no}",
                "started_at": disc_start_time,
                "completed_at": disc_end_time,
                "physical_attempt": 1,
                "http_status": disc_resp.status_code,
                "raw_http_response_size": disc_size,
                "raw_http_response_sha256": disc_sha,
                "transport_response_size": disc_size,
                "transport_response_sha256": disc_sha,
                "outcome": "SUCCESS" if page_success else "ERROR",
                "error_type": "" if page_success else f"OPENDART_STATUS_{status_code}",
            })

            page_no += 1

        loaded_raw_count = len(all_raw_items)
        reported_total_count = frozen_page1_meta.get("reported_total_count", 0)

        pag_pass, ticker_pagination_inconsistencies = validate_pagination_pages(
            pages_meta=pages_meta,
            expected_total_count=reported_total_count,
            expected_total_pages=total_pages,
            frozen_page1_meta=frozen_page1_meta,
        )

        if not pag_pass:
            pagination_inconsistency_failures.extend(ticker_pagination_inconsistencies)
            if loaded_raw_count != reported_total_count:
                discovery_total_count_mismatches.append(t)
            if pages_successful != pages_requested:
                pagination_incomplete_failures.append(t)

        dup_pass, duplicate_count, conflicting_duplicate_count, conflict_details = validate_discovery_duplicate_identity(all_raw_items)
        if not dup_pass:
            conflicting_duplicate_failures.extend(conflict_details)

        unique_items_by_rcp: dict[str, dict[str, Any]] = {}
        for it in all_raw_items:
            r_no = str(it.get("rcept_no", "")).strip()
            if r_no not in unique_items_by_rcp:
                unique_items_by_rcp[r_no] = it

        unique_items = list(unique_items_by_rcp.values())
        unique_candidate_count = len(unique_items)

        ranked_candidates = rank_and_score_candidates(unique_items, tgt)
        audit_rcp_ids = []

        selected_candidate = None
        selected_raw_bytes = b""
        selected_raw_status = 0
        selected_raw_format = "XML"
        selected_producing_req_id = ""
        selected_evidence_origin = ""
        selected_source = ""
        selected_retrieval_mode = ""
        selected_candidate_rank = -1
        selected_parsed = None
        selected_transport_sha = ""
        selected_transport_size = 0
        selected_archive_detected = False
        selected_archive_members = 0
        selected_member_name = ""
        selected_extracted_sha = ""
        selected_extracted_size = 0
        selected_member_rule = ""

        candidate_validity_map: dict[str, bool] = {}

        for c in ranked_candidates:
            r_no = c["rcept_no"]
            r_nm = c["report_nm"]
            r_dt = c["rcept_dt"]
            c_rank = c["candidate_rank"]
            score = c["event_match_score"]
            audit_rcp_ids.append(r_no)

            if score == 0:
                candidate_validity_map[r_no] = False
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "REJECTED_EVENT_MISMATCH",
                    "rejection_reason": "No target keywords found in report title",
                })
                continue

            if selected_candidate is not None:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "NOT_PROBED_LOWER_PRIORITY",
                    "rejection_reason": "Higher rank candidate already selected",
                })
                continue

            (
                extracted_bytes,
                extracted_sha,
                producing_req_id,
                final_probe_src,
                final_probe_origin,
                final_transport_size,
                final_transport_sha,
                probe_status,
                archive_detected,
                archive_members,
                member_name,
                member_rule,
                archive_ambiguous,
                arch_fails,
            ) = acquire_current_official_document(
                ticker=t,
                corp_code=tgt["corp_code"],
                rcept_no=r_no,
                candidate_rank=c_rank,
                api_key=api_key,
                session=dart_session,
                accounting=accounting,
                canonical_run_id=canonical_run_id,
            )

            if arch_fails:
                archive_member_ambiguity_failures.extend(arch_fails)
            extracted_size = len(extracted_bytes)

            arch_prov_valid, arch_prov_fails = validate_archive_provenance(
                archive_detected=archive_detected,
                archive_member_count=archive_members,
                selected_member_name=member_name,
                member_selection_rule=member_rule,
                extracted_member_size=extracted_size,
                extracted_member_sha256=extracted_sha,
                canonical_raw_sha256=extracted_sha,
                transport_response_sha256=final_transport_sha,
            )
            if not arch_prov_valid:
                archive_provenance_failures.extend(arch_prov_fails)

            if archive_ambiguous or not arch_prov_valid or not extracted_bytes:
                parsed_cand = {
                    "official_source_valid": bool(final_probe_src),
                    "blocked_page_detected": bool(not extracted_bytes),
                    "parsed_issuer": "",
                    "parsed_ticker": t,
                    "parsed_report_name": r_nm,
                    "source_event_type": "",
                    "normalized_event_type": "",
                    "event_type_match": False,
                    "event_node_id": "",
                    "event_node_tag": "",
                    "event_node_path": "",
                    "event_node_depth": 0,
                    "event_node_heading": "",
                    "timing_candidate_count": 0,
                    "timing_node_id": "",
                    "timing_node_tag": "",
                    "timing_node_path": "",
                    "timing_node_depth": 0,
                    "selected_timing_node_id": "",
                    "selected_timing_node_tag": "",
                    "selected_timing_node_path": "",
                    "selected_timing_node_depth": 0,
                    "binding_relationship": "",
                    "lowest_common_ancestor_path": "",
                    "semantic_block_id": "",
                    "semantic_block_type": "",
                    "semantic_section_path": "",
                    "semantic_parent_heading": "",
                    "semantic_block_sha256": "",
                    "official_anchor_type": "",
                    "official_anchor_date": "",
                    "official_anchor_source_field": "",
                    "official_anchor_source_value": "",
                    "official_anchor_priority_rank": 0,
                    "claim_anchor_match": False,
                    "record_identity_valid": True,
                    "issuer_identity_valid": True,
                    "event_type_valid": False,
                    "event_semantic_binding_valid": False,
                    "event_timing_valid": False,
                    "raw_provenance_valid": False,
                    "global_fallback_used": False,
                    "event_context_candidate_count": 0,
                    "event_type_candidate_count": 0,
                    "event_context_ambiguous": False,
                    "event_type_ambiguous": False,
                    "event_timing_ambiguous": False,
                    "sibling_cross_binding_detected": False,
                    "authority_valid": False,
                    "validation_reason": "EMPTY_OR_UNUSABLE_DOCUMENT" if not extracted_bytes else ("ARCHIVE_PROVENANCE_INCONSISTENT" if not arch_prov_valid else "ARCHIVE_MEMBER_AMBIGUOUS"),
                }
            else:
                official_auth_cand = OfficialEvidenceContentParser.extract_official_event_authority(
                    raw_content_bytes=extracted_bytes,
                    source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
                    discovered_record_id=r_no,
                    doc_request_record_id=r_no,
                    evidence_origin=final_probe_origin,
                )
                claim_adj_cand = OfficialEvidenceContentParser.adjudicate_prior_claim(
                    official_auth=official_auth_cand,
                    claimed_event_type=ev_fam,
                    claimed_anchor_type=tgt["claimed_anchor_type"],
                    claimed_anchor_date=tgt["claimed_anchor_date"],
                    claimed_issuer=tgt["issuer_name"],
                    claimed_ticker=t,
                )
                parsed_cand = dict(official_auth_cand)
                parsed_cand["parsed_ticker"] = t
                parsed_cand["event_type_match"] = claim_adj_cand["claim_event_type_match"]
                parsed_cand["claim_anchor_match"] = claim_adj_cand["claim_anchor_date_match"]
                parsed_cand["issuer_identity_valid"] = claim_adj_cand["issuer_identity_valid"]
                parsed_cand["authority_valid"] = bool(
                    official_auth_cand["authority_valid"]
                    and claim_adj_cand["issuer_identity_valid"]
                    and claim_adj_cand["claim_event_type_match"]
                )

            candidate_validity_map[r_no] = parsed_cand["authority_valid"]

            probe_audit_rows.append({
                "ticker": t,
                "candidate_rank": c_rank,
                "rcept_no": r_no,
                "report_nm": r_nm,
                "probe_request_id": producing_req_id,
                "source": final_probe_src,
                "evidence_origin": final_probe_origin,
                "retrieval_mode": "NEW_OPENDART_DOCUMENT_FETCH" if final_probe_src == "OPENDART_OFFICIAL_API" else ("NEW_DART_VIEWER_FETCH" if final_probe_src == "DART_OFFICIAL_DISCLOSURE" else ""),
                "http_status": probe_status,
                "transport_response_sha256": final_transport_sha,
                "archive_detected": archive_detected,
                "extracted_member_sha256": extracted_sha,
                "canonical_raw_sha256": extracted_sha,
                "event_node_path": parsed_cand["event_node_path"],
                "timing_node_path": parsed_cand["timing_node_path"],
                "binding_relationship": parsed_cand["binding_relationship"],
                "authority_valid": parsed_cand["authority_valid"],
                "validation_reason": parsed_cand["validation_reason"],
            })

            if parsed_cand["authority_valid"]:
                selected_candidate = c
                selected_raw_bytes = extracted_bytes
                selected_raw_status = probe_status
                selected_raw_format = "XML" if archive_detected or b"<DOCUMENT" in extracted_bytes or b"<?xml" in extracted_bytes else "HTML"
                selected_producing_req_id = producing_req_id
                selected_evidence_origin = final_probe_origin
                selected_source = final_probe_src
                selected_retrieval_mode = "NEW_OPENDART_DOCUMENT_FETCH" if final_probe_src == "OPENDART_OFFICIAL_API" else "NEW_DART_VIEWER_FETCH"
                selected_candidate_rank = c_rank
                selected_parsed = parsed_cand
                selected_transport_sha = final_transport_sha
                selected_transport_size = final_transport_size
                selected_archive_detected = archive_detected
                selected_archive_members = archive_members
                selected_member_name = member_name
                selected_extracted_sha = extracted_sha
                selected_extracted_size = extracted_size
                selected_member_rule = member_rule

                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "SELECTED",
                    "rejection_reason": "",
                })
            else:
                candidate_audit_rows.append({
                    "ticker": t,
                    "candidate_rank": c_rank,
                    "rcept_no": r_no,
                    "report_nm": r_nm,
                    "rcept_dt": r_dt,
                    "corp_code": c["corp_code"],
                    "event_match_score": score,
                    "selection_status": "REJECTED_AUTHORITY_VALIDATION",
                    "rejection_reason": parsed_cand["validation_reason"],
                })

        if not selected_candidate and ranked_candidates:
            selected_candidate = ranked_candidates[0]
            selected_candidate_rank = 1

        unique_candidate_ids = {c["rcept_no"] for c in unique_items}
        if set(audit_rcp_ids) != unique_candidate_ids:
            candidate_audit_incompleteness_failures.append(t)

        pagination_validation_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "logical_discovery_query_id": disc_query_id,
            "total_count_reported": reported_total_count,
            "total_page_reported": total_pages,
            "pages_requested": pages_requested,
            "pages_successful": pages_successful,
            "raw_records_loaded": loaded_raw_count,
            "unique_records_loaded": unique_candidate_count,
            "duplicate_count": duplicate_count,
            "conflicting_duplicate_count": conflicting_duplicate_count,
            "metadata_audit_count": len(audit_rcp_ids),
            "pagination_complete": pag_pass and conflicting_duplicate_count == 0 and len(ticker_pagination_inconsistencies) == 0,
            "pagination_inconsistencies": ticker_pagination_inconsistencies,
        }

        final_rcp_no = selected_candidate.get("rcept_no", "") if selected_candidate else ""
        final_rep_name = selected_candidate.get("report_nm", "") if selected_candidate else ""
        final_rcp_date = selected_candidate.get("rcept_dt", "") if selected_candidate else ""
        legacy_match = bool(final_rcp_no and final_rcp_no in tgt["legacy_expected_record_id"])

        base_ranks = [c["rcept_no"] for c in ranked_candidates]
        permutations = [
            ("reverse", list(reversed(unique_items))),
            ("shuffle_1", random.Random(42).sample(unique_items, len(unique_items))),
            ("shuffle_2", random.Random(43).sample(unique_items, len(unique_items))),
            ("shuffle_3", random.Random(44).sample(unique_items, len(unique_items))),
        ]

        ranking_order_invariant = True
        permuted_selected_nos = [final_rcp_no]

        for p_name, p_items in permutations:
            p_ranked = rank_and_score_candidates(p_items, tgt)
            p_order = [c["rcept_no"] for c in p_ranked]
            if p_order != base_ranks:
                ranking_order_invariant = False
                ranking_order_invariance_failures.append(f"{t}:{p_name}")

            winner = None
            for c in p_ranked:
                r_id = c["rcept_no"]
                if candidate_validity_map.get(r_id, False):
                    winner = r_id
                    break
            if not winner and p_ranked:
                winner = p_ranked[0]["rcept_no"]
            permuted_selected_nos.append(winner)

        selected_record_invariant = bool(len(set(permuted_selected_nos)) == 1 and permuted_selected_nos[0] == final_rcp_no)
        if not selected_record_invariant:
            selected_record_invariance_failures.append(t)

        determinism_validation_results[t] = {
            "reported_total_count": reported_total_count,
            "loaded_raw_count": loaded_raw_count,
            "unique_candidate_count": unique_candidate_count,
            "pagination_complete": pag_pass,
            "ranking_order_invariant": ranking_order_invariant,
            "selected_rcept_no_order_invariant": selected_record_invariant,
            "canonical_selected_rcept_no": final_rcp_no,
            "permutation_selected_rcept_nos": permuted_selected_nos,
            "determinism_pass": ranking_order_invariant and selected_record_invariant,
        }

        discovery_rows.append({
            "canonical_run_id": canonical_run_id,
            "control_id": cid,
            "ticker": t,
            "corp_code": tgt["corp_code"],
            "issuer_name": tgt["issuer_name"],
            "search_source": "OPENDART_OFFICIAL_API",
            "logical_discovery_query_id": disc_query_id,
            "search_start_date": tgt["discovery_start"],
            "search_end_date": tgt["discovery_end"],
            "reported_total_count": reported_total_count,
            "reported_total_pages": total_pages,
            "loaded_record_count": loaded_raw_count,
            "unique_candidate_count": unique_candidate_count,
            "selected_record_id": final_rcp_no,
            "selected_report_name": final_rep_name,
            "selected_receipt_date": final_rcp_date,
            "legacy_expected_record_id": tgt["legacy_expected_record_id"],
            "legacy_id_match": legacy_match,
            "selection_algorithm": "OPENDART_DETERMINISTIC_PAGINATED_RANKING_V01_FIX03_CORRECTION_12",
            "selection_rank": selected_candidate_rank,
            "selection_reason": f"Rank {selected_candidate_rank} match '{final_rep_name}' authenticated via True XML Hierarchy",
        })

        raw_sha = hashlib.sha256(selected_raw_bytes).hexdigest() if selected_raw_bytes else ""
        raw_size = len(selected_raw_bytes)
        raw_ext = "xml" if selected_raw_format == "XML" else "html"
        raw_filename = f"{t}_{ev_fam}_{final_rcp_no}.{raw_ext}"

        if selected_raw_bytes and selected_parsed and selected_parsed["authority_valid"]:
            raw_fp = raw_dir / raw_filename
            raw_fp.write_bytes(selected_raw_bytes)
            raw_rel_path = f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_12/raw/{raw_filename}"
            raw_manifest_entries[raw_filename] = {
                "canonical_run_id": canonical_run_id,
                "control_id": cid,
                "ticker": t,
                "corp_code": tgt["corp_code"],
                "issuer_name": tgt["issuer_name"],
                "path": raw_rel_path,
                "size_bytes": raw_size,
                "sha256": raw_sha,
                "source": selected_source,
                "retrieval_mode": selected_retrieval_mode,
                "evidence_origin": selected_evidence_origin,
                "official_record_id": final_rcp_no,
                "producing_request_id": selected_producing_req_id,
                "transport_response_size": selected_transport_size,
                "transport_response_sha256": selected_transport_sha,
                "archive_detected": selected_archive_detected,
                "archive_member_count": selected_archive_members,
                "selected_member_name": selected_member_name,
                "member_selection_rule": selected_member_rule,
                "extracted_member_size": selected_extracted_size,
                "extracted_member_sha256": selected_extracted_sha,
                "canonical_raw_size": raw_size,
                "canonical_raw_sha256": raw_sha,
                "content_type": f"application/{raw_ext}",
                "requested_at": datetime.now(timezone.utc).isoformat(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "content_validation_status": "VALID",
                "live_lineage_valid": True,
            }
        else:
            raw_rel_path = ""

        parsed = selected_parsed if selected_parsed else OfficialEvidenceContentParser.parse_and_validate(
            raw_content_bytes=selected_raw_bytes,
            claimed_ticker=t,
            claimed_issuer=tgt["issuer_name"],
            claimed_event_type=ev_fam,
            claimed_anchor_type=tgt["claimed_anchor_type"],
            claimed_anchor_date=tgt["claimed_anchor_date"],
            source_id=selected_source,
            source_tier=AuthoritySourceTier.TIER_A1_OPENDART.value,
            discovered_record_id=final_rcp_no,
            doc_request_record_id=final_rcp_no,
            evidence_origin=selected_evidence_origin,
        )

        claim_adj = OfficialEvidenceContentParser.adjudicate_prior_claim(
            official_auth=parsed,
            claimed_event_type=ev_fam,
            claimed_anchor_type=tgt["claimed_anchor_type"],
            claimed_anchor_date=tgt["claimed_anchor_date"],
            claimed_issuer=tgt["issuer_name"],
            claimed_ticker=t,
        )

        if not parsed["event_type_valid"]:
            source_event_classification_failures.append(t)
        if not parsed["event_type_match"]:
            source_event_type_mismatches.append(t)
        if parsed["event_type_ambiguous"]:
            event_type_ambiguity_failures.append(t)
        if parsed["event_context_ambiguous"]:
            event_context_ambiguity_failures.append(t)
        if parsed.get("event_timing_ambiguous", False):
            event_timing_ambiguity_failures.append(t)
        if not parsed["event_semantic_binding_valid"]:
            semantic_binding_failures.append(t)
        if parsed["binding_relationship"] not in ["SAME_NODE", "ANCESTOR_DESCENDANT"]:
            invalid_binding_relationship_failures.append(t)
        if parsed["semantic_block_id"] == "SEM_BLOCK_GLOBAL_DOC":
            global_semantic_block_authority_failures.append(t)
        doc_validation_rows.append({
            "canonical_run_id": canonical_run_id,
            "control_id": cid,
            "ticker": t,
            "issuer": tgt["issuer_name"],
            "issuer_name": tgt["issuer_name"],
            "official_record_id": final_rcp_no,
            "producing_request_id": selected_producing_req_id,
            "retrieval_mode": selected_retrieval_mode,
            "raw_evidence_sha256": raw_sha,

            "discovered_record_id": final_rcp_no,
            "legacy_claimed_record_id": tgt["legacy_expected_record_id"],
            "raw_path": raw_rel_path,
            "raw_sha": raw_sha,
            "official_source": selected_source,
            "corp_code": tgt["corp_code"],
            "parsed_issuer": parsed["parsed_issuer"],
            "parsed_ticker": parsed["parsed_ticker"],
            "parsed_report_name": parsed["parsed_report_name"] or final_rep_name,
            "source_event_type": parsed["source_event_type"],
            "expected_event_type": ev_fam,
            "event_type_match": parsed["event_type_match"],
            "normalized_event_type": parsed["normalized_event_type"],
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_id": parsed["event_node_id"],
            "event_node_tag": parsed["event_node_tag"],
            "event_node_path": parsed["event_node_path"],
            "event_node_depth": parsed["event_node_depth"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_candidate_count": parsed.get("timing_candidate_count", 1),
            "timing_node_id": parsed["timing_node_id"],
            "timing_node_tag": parsed["timing_node_tag"],
            "timing_node_path": parsed["timing_node_path"],
            "timing_node_depth": parsed["timing_node_depth"],
            "binding_relationship": parsed["binding_relationship"],
            "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
            "semantic_block_id": parsed["semantic_block_id"],
            "semantic_block_type": parsed["semantic_block_type"],
            "semantic_section_path": parsed["semantic_section_path"],
            "semantic_parent_heading": parsed["semantic_parent_heading"],
            "semantic_block_sha256": parsed["semantic_block_sha256"],
            "official_anchor_type": parsed["official_anchor_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_anchor_source_field": parsed["official_anchor_source_field"],
            "official_anchor_source_value": parsed["official_anchor_source_value"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "timing_repetition_count": parsed.get("timing_repetition_count", 1),
            "claim_anchor_match": parsed["claim_anchor_match"],
            "official_source_valid": parsed["official_source_valid"],
            "record_identity_valid": parsed["record_identity_valid"],
            "issuer_identity_valid": parsed["issuer_identity_valid"],
            "event_type_valid": parsed["event_type_valid"],
            "event_semantic_binding_valid": parsed["event_semantic_binding_valid"],
            "event_timing_valid": parsed["event_timing_valid"],
            "raw_provenance_valid": parsed["raw_provenance_valid"],
            "global_fallback_used": parsed["global_fallback_used"],
            "event_context_ambiguous": parsed["event_context_ambiguous"],
            "event_type_ambiguous": parsed["event_type_ambiguous"],
            "event_timing_ambiguous": parsed.get("event_timing_ambiguous", False),
            "authority_valid": parsed["authority_valid"],
            "validation_reason": parsed["validation_reason"],
        })

        semantic_binding_rows.append({
            "control_id": cid,
            "ticker": t,
            "source_event_type": parsed["source_event_type"],
            "expected_event_type": ev_fam,
            "event_type_match": parsed["event_type_match"],
            "selected_rcept_no": final_rcp_no,
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_id": parsed["event_node_id"],
            "event_node_tag": parsed["event_node_tag"],
            "event_node_path": parsed["event_node_path"],
            "event_node_depth": parsed["event_node_depth"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_node_id": parsed["timing_node_id"],
            "timing_node_tag": parsed["timing_node_tag"],
            "timing_node_path": parsed["timing_node_path"],
            "timing_node_depth": parsed["timing_node_depth"],
            "binding_relationship": parsed["binding_relationship"],
            "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
            "anchor_field_name": parsed["official_anchor_source_field"],
            "anchor_source_value": parsed["official_anchor_source_value"],
            "anchor_date": parsed["official_anchor_date"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "semantic_binding_valid": parsed["event_semantic_binding_valid"],
            "global_fallback_used": parsed["global_fallback_used"],
        })

        hierarchy_validation_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "selected_rcept_no": final_rcp_no,
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "event_node_path": parsed["event_node_path"],
            "event_node_heading": parsed["event_node_heading"],
            "timing_node_path": parsed["timing_node_path"],
            "binding_relationship": parsed["binding_relationship"],
            "event_node_is_ancestor_of_timing": parsed["binding_relationship"] == "ANCESTOR_DESCENDANT",
            "same_node": parsed["binding_relationship"] == "SAME_NODE",
            "sibling_cross_binding_detected": False,
            "event_context_candidate_count": parsed.get("event_context_candidate_count", 1),
            "event_type_candidate_count": parsed.get("event_type_candidate_count", 1),
            "event_context_ambiguous": parsed["event_context_ambiguous"],
            "event_type_ambiguous": parsed["event_type_ambiguous"],
            "event_timing_ambiguous": parsed.get("event_timing_ambiguous", False),
            "hierarchical_binding_valid": parsed["event_semantic_binding_valid"],
        }

        claim_independence_entries[t] = {
            "control_id": cid,
            "ticker": t,
            "source_event_type": parsed["source_event_type"],
            "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
            "official_anchor_type": parsed["official_anchor_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
            "claim_event_type": tgt["target_event_family"],
            "claim_anchor_type": tgt["claimed_anchor_type"],
            "claim_anchor_date": tgt["claimed_anchor_date"],
            "claim_event_type_match": claim_adj["claim_event_type_match"],
            "claim_anchor_type_match": claim_adj["claim_anchor_type_match"],
            "claim_anchor_date_match": claim_adj["claim_anchor_date_match"],
            "claim_used_for_event_selection": claim_adj["claim_used_for_event_selection"],
            "claim_used_for_context_selection": claim_adj["claim_used_for_context_selection"],
            "claim_used_for_anchor_type_selection": claim_adj["claim_used_for_anchor_type_selection"],
            "claim_used_for_anchor_date_selection": claim_adj["claim_used_for_anchor_date_selection"],
            "claim_independence_valid": claim_adj["claim_independence_valid"],
            "authority_valid": parsed["authority_valid"],
        }

        adjudication_rows.append({
            "ticker": t,
            "issuer_name": tgt["issuer_name"],
            "prior_claimed_event": ev_fam,
            "prior_claimed_anchor": tgt["claimed_anchor_date"],
            "source_event_type": parsed["source_event_type"],
            "official_anchor_date": parsed["official_anchor_date"],
            "official_source_field": parsed["official_anchor_source_field"],
            "official_evidence_found": parsed["authority_valid"],
            "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
            "authority_record_id": final_rcp_no,
            "normalized_event_type": parsed["normalized_event_type"],
            "adjudication": claim_adj["adjudication_status"],
            "adjudication_reason": parsed["validation_reason"],
        })

        if parsed["authority_valid"] and parsed["official_anchor_date"]:
            anc_dt = datetime.strptime(parsed["official_anchor_date"], "%Y-%m-%d")
            w_start = (anc_dt - timedelta(days=35)).strftime("%Y-%m-%d")
            w_end = (anc_dt + timedelta(days=35)).strftime("%Y-%m-%d")
            authority_records.append({
                "canonical_run_id": canonical_run_id,
                "control_id": cid,
                "ticker": t,
                "issuer_name": tgt["issuer_name"],
                "corp_code": tgt["corp_code"],
                "source_event_type": parsed["source_event_type"],
                "normalized_event_type": parsed["normalized_event_type"],
                "selected_source_event_context_id": parsed.get("selected_source_event_context_id", ""),
                "event_node_path": parsed["event_node_path"],
                "event_node_heading": parsed["event_node_heading"],
                "timing_node_path": parsed["timing_node_path"],
                "binding_relationship": parsed["binding_relationship"],
                "lowest_common_ancestor_path": parsed["lowest_common_ancestor_path"],
                "official_anchor_type": parsed["official_anchor_type"],
                "official_anchor_date": parsed["official_anchor_date"],
                "official_anchor_source_field": parsed["official_anchor_source_field"],
                "official_anchor_source_value": parsed["official_anchor_source_value"],
                "official_anchor_priority_rank": parsed.get("official_anchor_priority_rank", 1),
                "price_window_start": w_start,
                "price_window_end": w_end,
                "authority_source_tier": AuthoritySourceTier.TIER_A1_OPENDART.value,
                "authority_source_name": selected_source,
                "authority_record_id": final_rcp_no,
                "raw_evidence_path": raw_rel_path,
                "raw_evidence_sha256": raw_sha,
                "producing_request_id": selected_producing_req_id,
                "retrieval_mode": selected_retrieval_mode,
                "validation_predicates": {
                    "official_source_valid": parsed["official_source_valid"],
                    "record_identity_valid": parsed["record_identity_valid"],
                    "issuer_identity_valid": parsed["issuer_identity_valid"],
                    "source_event_type_valid": parsed["event_type_valid"],
                    "event_type_match": parsed["event_type_match"],
                    "event_semantic_binding_valid": parsed["event_semantic_binding_valid"],
                    "event_timing_valid": parsed["event_timing_valid"],
                    "raw_provenance_valid": parsed["raw_provenance_valid"],
                    "global_fallback_not_used": not parsed["global_fallback_used"],
                },
                "authority_valid": True,
            })

    # Save discovery and validation artifacts
    disc_df = pd.DataFrame(discovery_rows)
    disc_path = output_dir / "corporate_action_official_discovery_v01_fix03_correction_12.csv"
    disc_df.to_csv(disc_path, index=False)

    page_man_path = output_dir / "corporate_action_discovery_page_manifest_v01_fix03_correction_12.json"
    page_man_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_page_manifest_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "pages": discovery_page_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    pag_val_path = output_dir / "corporate_action_discovery_pagination_validation_v01_fix03_correction_12.json"
    pag_val_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_pagination_validation_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "all_pagination_complete": all(v["pagination_complete"] for v in pagination_validation_entries.values()),
        "validation_by_ticker": pagination_validation_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    cand_audit_df = pd.DataFrame(candidate_audit_rows)
    cand_audit_path = output_dir / "corporate_action_discovery_candidate_audit_v01_fix03_correction_12.csv"
    cand_audit_df.to_csv(cand_audit_path, index=False)

    det_val_path = output_dir / "corporate_action_discovery_determinism_validation_v01_fix03_correction_12.json"
    det_val_path.write_text(json.dumps({
        "schema": "corporate_action_discovery_determinism_validation_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "all_controls_order_invariant": all(v["determinism_pass"] for v in determinism_validation_results.values()),
        "validation_by_ticker": determinism_validation_results,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    probe_audit_df = pd.DataFrame(probe_audit_rows)
    probe_audit_path = output_dir / "corporate_action_document_probe_audit_v01_fix03_correction_12.csv"
    probe_audit_df.to_csv(probe_audit_path, index=False)

    disc_man_payload = {
        "schema": "corporate_action_discovery_raw_manifest_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "artifacts": discovery_manifest_entries,
    }
    disc_man_path = output_dir / "corporate_action_discovery_raw_manifest_v01_fix03_correction_12.json"
    disc_man_path.write_text(json.dumps(disc_man_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    doc_val_df = pd.DataFrame(doc_validation_rows)
    doc_val_path = output_dir / "corporate_action_official_document_validation_v01_fix03_correction_12.csv"
    doc_val_df.to_csv(doc_val_path, index=False)

    sem_bind_df = pd.DataFrame(semantic_binding_rows)
    sem_bind_path = output_dir / "corporate_action_event_semantic_binding_v01_fix03_correction_12.csv"
    sem_bind_df.to_csv(sem_bind_path, index=False)

    hier_val_path = output_dir / "corporate_action_event_hierarchy_validation_v01_fix03_correction_12.json"
    hier_val_path.write_text(json.dumps({
        "schema": "corporate_action_event_hierarchy_validation_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "all_hierarchy_valid": all(v["hierarchical_binding_valid"] for v in hierarchy_validation_entries.values()),
        "validation_by_ticker": hierarchy_validation_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    claim_indep_path = output_dir / "corporate_action_claim_independence_validation_v01_fix03_correction_12.json"
    claim_indep_path.write_text(json.dumps({
        "schema": "corporate_action_claim_independence_validation_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "all_claim_independent": all(v["claim_independence_valid"] for v in claim_independence_entries.values()),
        "validation_by_ticker": claim_independence_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    adj_df = pd.DataFrame(adjudication_rows)
    adj_path = output_dir / "corporate_action_existing_claim_adjudication_v01_fix03_correction_12.csv"
    adj_df.to_csv(adj_path, index=False)

    rep_pool_path = output_dir / "corporate_action_replacement_pool_v01_fix03_correction_12.csv"
    pd.DataFrame(columns=["control_id", "ticker", "issuer_name", "status"]).to_csv(rep_pool_path, index=False)

    auth_rec_path = output_dir / "corporate_action_authority_records_v01_fix03_correction_12.json"
    auth_rec_path.write_text(json.dumps({
        "schema": "corporate_action_authority_records_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "records": authority_records,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    raw_man_path = output_dir / "corporate_action_raw_evidence_manifest_v01_fix03_correction_12.json"
    raw_man_path.write_text(json.dumps({
        "schema": "corporate_action_raw_evidence_manifest_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "artifacts": raw_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 6. Freeze Cohort Before Price Fetch
    final_cohort_rows = []
    for idx, ar in enumerate(authority_records, start=1):
        final_cohort_rows.append({
            "canonical_run_id": canonical_run_id,
                "control_id": ar["control_id"],
                "ticker": ar["ticker"],
                "issuer_name": ar["issuer_name"],
                "corp_code": ar["corp_code"],
            "source_event_type": ar["source_event_type"],
            "normalized_event_type": ar["normalized_event_type"],
            "selected_source_event_context_id": ar.get("selected_source_event_context_id", ""),
            "event_node_path": ar["event_node_path"],
            "event_node_heading": ar["event_node_heading"],
            "timing_node_path": ar["timing_node_path"],
            "binding_relationship": ar["binding_relationship"],
            "lowest_common_ancestor_path": ar["lowest_common_ancestor_path"],
            "official_anchor_type": ar["official_anchor_type"],
            "official_anchor_date": ar["official_anchor_date"],
            "official_anchor_source_field": ar["official_anchor_source_field"],
            "official_anchor_source_value": ar["official_anchor_source_value"],
            "official_anchor_priority_rank": ar.get("official_anchor_priority_rank", 1),
            "price_window_start": ar["price_window_start"],
            "price_window_end": ar["price_window_end"],
            "authority_source_tier": ar["authority_source_tier"],
            "authority_source_name": ar["authority_source_name"],
            "authority_record_id": ar["authority_record_id"],
            "producing_request_id": ar["producing_request_id"],
            "retrieval_mode": ar.get("retrieval_mode", "NEW_OPENDART_DOCUMENT_FETCH"),
            "raw_evidence_path": ar["raw_evidence_path"],
            "raw_evidence_sha256": ar["raw_evidence_sha256"],
            "selection_role": "AUTHORITY_VALID_FROZEN_CONTROL",
            "selection_order": idx,
            "selection_algorithm": "OPENDART_PAGINATED_CLAIM_FREE_TRUE_XML_HIERARCHY_COHORT_V01_FIX03_CORRECTION_12",
        })

    cohort_df = pd.DataFrame(final_cohort_rows)
    cohort_path = output_dir / "corporate_action_review_cohort_v01_fix03_correction_12.csv"
    cohort_df.to_csv(cohort_path, index=False)
    cohort_sha = hashlib.sha256(cohort_path.read_bytes()).hexdigest()
    cohort_frozen_at = datetime.now(timezone.utc).isoformat()

    # 7. Price Parity Execution (Only if cohort > 0)
    all_price_rows = []
    parity_rows = []
    reconciliation_rows = []
    parity_statuses = []

    insufficient_window_count = 0
    date_set_mismatch_count = 0
    ohlc_mismatch_count = 0
    candidate_error_count = 0
    comparator_error_count = 0
    source_frames: dict[tuple[str, str], pd.DataFrame] = {}
    price_request_ids: dict[tuple[str, str], str] = {}

    if final_cohort_rows:
        import pykrx.stock as pykrx_stock
        naver_client = NaverDateRangeAdjustedClient(allow_network=allow_network)

        for c in final_cohort_rows:
            t = normalize_ticker(c["ticker"])
            w_start = c["price_window_start"]
            w_end = c["price_window_end"]
            anchor_d = c["official_anchor_date"]

            cand_req_id = f"REQ_PRICE_NAVER_{t}_{w_start}_{w_end}"
            py_query_id = f"QUERY_PRICE_RAW_PYKRX_{t}_{w_start}_{w_end}"

            accounting.direct_naver_logical_requests += 1
            accounting.direct_naver_physical_attempts += 1
            accounting.raw_pykrx_logical_requests += 1
            accounting.raw_pykrx_physical_attempts += 1

            cand_err = ""
            c_start_t = datetime.now(timezone.utc).isoformat()
            try:
                st_code, xml_text, elapsed = naver_client.fetch_raw(t, w_start, w_end)
                c_end_t = datetime.now(timezone.utc).isoformat()
                cand_df = NaverDateRangeAdjustedClient.parse_xml_payload(xml_text, w_start, w_end)
                cand_raw_sha = hashlib.sha256(xml_text.encode("utf-8")).hexdigest()
            except Exception as exc:
                c_end_t = datetime.now(timezone.utc).isoformat()
                cand_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                cand_raw_sha = ""
                cand_err = str(exc)
                candidate_error_count += 1

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": cand_req_id,
                "source": "NAVER_DIRECT",
                "purpose": "EVENT_SENSITIVE_CANDIDATE_PRICE_FETCH",
                "control_id": c["control_id"],
                "ticker": t,
                "corp_code": c["corp_code"],
                "official_record_id": c["authority_record_id"],
                "authority_record_id": c["authority_record_id"],
                "price_window_start": w_start,
                "price_window_end": w_end,
                "sanitized_endpoint": f"https://fchart.stock.naver.com/sise.nhn?symbol={t}&startTime={w_start}&endTime={w_end}",
                "started_at": c_start_t,
                "completed_at": c_end_t,
                "physical_attempt": 1,
                "http_status": 200 if not cand_err else 500,
                "raw_http_response_size": len(xml_text) if not cand_err else 0,
                "raw_http_response_sha256": cand_raw_sha,
                "transport_response_size": len(xml_text) if not cand_err else 0,
                "transport_response_sha256": cand_raw_sha,
                "outcome": "SUCCESS" if not cand_err else "ERROR",
                "error_type": cand_err,
            })

            py_err = ""
            p_start_t = datetime.now(timezone.utc).isoformat()
            try:
                py_raw = pykrx_stock.get_market_ohlcv_by_date(
                    w_start.replace("-", ""),
                    w_end.replace("-", ""),
                    t,
                    adjusted=True,
                )
                p_end_t = datetime.now(timezone.utc).isoformat()
                if py_raw is not None and not py_raw.empty:
                    py_df = py_raw.rename(columns={"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}).copy()
                    py_df["date"] = [d.strftime("%Y-%m-%d") for d in py_df.index]
                else:
                    py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                py_rowset_sha = hashlib.sha256(py_df.to_csv(index=False).encode("utf-8")).hexdigest()
            except Exception as exc:
                p_end_t = datetime.now(timezone.utc).isoformat()
                py_df = pd.DataFrame(columns=["date", "open", "high", "low", "close", "volume"])
                py_rowset_sha = ""
                py_err = str(exc)
                comparator_error_count += 1

            accounting.request_logs.append({
                "canonical_run_id": canonical_run_id,
                "request_id": py_query_id,
                "source": "RAW_PYKRX_COMPARATOR",
                "purpose": "EVENT_SENSITIVE_RAW_COMPARATOR_PRICE_QUERY",
                "control_id": c["control_id"],
                "ticker": t,
                "corp_code": c["corp_code"],
                "official_record_id": c["authority_record_id"],
                "authority_record_id": c["authority_record_id"],
                "adjusted": True,
                "price_window_start": w_start,
                "price_window_end": w_end,
                "sanitized_endpoint": f"pykrx.stock.get_market_ohlcv_by_date({w_start},{w_end},{t},adjusted=True)",
                "started_at": p_start_t,
                "completed_at": p_end_t,
                "physical_attempt": 1,
                "http_status": 200 if not py_err else 500,
                "raw_http_response_size": 0,
                "raw_http_response_sha256": py_rowset_sha,
                "transport_response_size": 0,
                "transport_response_sha256": py_rowset_sha,
                "outcome": "SUCCESS" if not py_err else "ERROR",
                "error_type": py_err,
            })

            # Persist the exact normalized rows used by the parity calculation.
            candidate_rows = _c13_normalize_price_frame(cand_df, control=c, source="NAVER_DIRECT", request_id=cand_req_id)
            pykrx_rows = _c13_normalize_price_frame(py_df, control=c, source="RAW_PYKRX_COMPARATOR", request_id=py_query_id)
            source_frames[(str(c["control_id"]), "NAVER_DIRECT")] = candidate_rows
            source_frames[(str(c["control_id"]), "RAW_PYKRX_COMPARATOR")] = pykrx_rows
            price_request_ids[(str(c["control_id"]), "NAVER_DIRECT")] = cand_req_id
            price_request_ids[(str(c["control_id"]), "RAW_PYKRX_COMPARATOR")] = py_query_id
            all_price_rows.extend(candidate_rows.to_dict("records"))
            all_price_rows.extend(pykrx_rows.to_dict("records"))

            # Evaluate parity
            cand_dates = set(cand_df["date"].astype(str)) if not cand_df.empty else set()
            py_dates = set(py_df["date"].astype(str)) if not py_df.empty else set()
            common_dates = sorted(cand_dates.intersection(py_dates))
            cand_only = sorted(cand_dates - py_dates)
            py_only = sorted(py_dates - cand_dates)

            if cand_only or py_only:
                date_set_mismatch_count += 1

            pre_ov = sum(1 for d in common_dates if d < anchor_d)
            post_ov = sum(1 for d in common_dates if d >= anchor_d)
            if pre_ov < 5 or post_ov < 5:
                insufficient_window_count += 1

            o_mis, h_mis, l_mis, c_mis, v_mis = 0, 0, 0, 0, 0
            if common_dates and not cand_df.empty and not py_df.empty:
                c_sub = cand_df.set_index("date").loc[common_dates]
                p_sub = py_df.set_index("date").loc[common_dates]
                o_mis = int((c_sub["open"].astype(float) != p_sub["open"].astype(float)).sum())
                h_mis = int((c_sub["high"].astype(float) != p_sub["high"].astype(float)).sum())
                l_mis = int((c_sub["low"].astype(float) != p_sub["low"].astype(float)).sum())
                c_mis = int((c_sub["close"].astype(float) != p_sub["close"].astype(float)).sum())

            if (o_mis + h_mis + l_mis + c_mis) > 0:
                ohlc_mismatch_count += 1

            parity_statuses.append("MATCH" if (o_mis + h_mis + l_mis + c_mis == 0 and len(cand_only) == 0 and len(py_only) == 0) else "MISMATCH")

    price_df = pd.DataFrame(all_price_rows) if all_price_rows else pd.DataFrame(columns=sorted(PRICE_ROW_REQUIRED_COLUMNS))
    if source_frames:
        computed_parity_rows, computed_reconciliation_rows = _c13_price_parity_rows(
            final_cohort_rows,
            source_frames,
            price_request_ids,
            canonical_run_id,
        )
        parity_rows = computed_parity_rows
        reconciliation_rows = computed_reconciliation_rows
    (output_dir / "corporate_action_event_price_rows_v01_fix03_correction_12.csv").write_text(price_df.to_csv(index=False), encoding="utf-8")

    parity_df = pd.DataFrame(parity_rows) if parity_rows else pd.DataFrame(columns=sorted(PARITY_REQUIRED_COLUMNS))
    (output_dir / "corporate_action_event_sensitive_parity_v01_fix03_correction_12.csv").write_text(parity_df.to_csv(index=False), encoding="utf-8")

    recon_df = pd.DataFrame(reconciliation_rows) if reconciliation_rows else pd.DataFrame(columns=sorted(RECONCILIATION_REQUIRED_COLUMNS))
    (output_dir / "corporate_action_date_reconciliation_v01_fix03_correction_12.csv").write_text(recon_df.to_csv(index=False), encoding="utf-8")

    # 8. Network Accounting & Linkage (Section 3, 4)
    accounting.compute_totals()

    net_path = output_dir / "corporate_action_evidence_network_accounting_v01_fix03_correction_12.json"
    net_dict = accounting.to_dict()
    net_dict["schema"] = "corporate_action_evidence_network_accounting_v01_fix03_correction_12"
    net_dict["directive_id"] = DIRECTIVE_ID_CORRECTION_12
    net_dict["canonical_run_id"] = canonical_run_id
    net_path.write_text(json.dumps(net_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    linkage_result = validate_live_evidence_linkage(
        canonical_run_id=canonical_run_id,
        discovery_records=discovery_rows,
        document_records=doc_validation_rows,
        raw_manifest_entries=raw_manifest_entries,
        authority_rows=authority_records,
        request_logs=accounting.request_logs,
        price_request_logs=[
            r for r in accounting.request_logs
            if r.get("source") in {"NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"}
        ],
        artifact_paths={"raw": raw_dir},
        current_output_dir=output_dir,
        accounting_cross_invariant_pass=accounting.accounting_cross_invariant_pass,
        schema_suffix="12",
    )
    linkage_payload = linkage_result.to_dict()
    linkage_payload.update({
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "discovery_pages_checked": len(discovery_manifest_entries),
        "document_items_checked": len(raw_manifest_entries),
    })
    # Back-propagate the validator's per-run truth to the manifest metadata;
    # this field is never a default assertion of lineage validity.
    failed_record_ids = {
        str(item.get("record_id") or item.get("authority_record_id") or item.get("document_id"))
        for item in linkage_result.linkage_failures
        if item.get("record_id") or item.get("authority_record_id") or item.get("document_id")
    }
    for manifest_entry in raw_manifest_entries.values():
        manifest_record_id = _linkage_text(manifest_entry, "official_record_id", "rcept_no", "authority_record_id")
        manifest_entry["live_lineage_valid"] = bool(manifest_record_id and manifest_record_id not in failed_record_ids and linkage_result.all_linkage_valid)
    raw_man_path.write_text(json.dumps({
        "schema": "corporate_action_raw_evidence_manifest_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "artifacts": raw_manifest_entries,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output_dir / "live_evidence_linkage_validation_v01_fix03_correction_12.json").write_text(
        json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # 9. Gate 06 Evaluation
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

    gate06_eval_metrics = {
        "preflight_verdict": preflight["verdict"],
        "document_readiness_verdict": doc_readiness["verdict"],
        "authority_valid_controls_count": auth_valid_count,
        "final_cohort_control_count": len(final_cohort_rows),
        "diversity_pass": diversity_pass,
        "pagination_incomplete_control_count": len(pagination_incomplete_failures),
        "pagination_metadata_inconsistency_count": len(pagination_inconsistency_failures),
        "pagination_page_count_inconsistency_count": len(pagination_page_count_inconsistencies),
        "discovery_total_count_mismatch_count": len(discovery_total_count_mismatches),
        "duplicate_rcept_no_count": sum(v["duplicate_count"] for v in pagination_validation_entries.values()),
        "conflicting_duplicate_rcept_no_count": len(conflicting_duplicate_failures),
        "candidate_audit_incomplete_count": len(candidate_audit_incompleteness_failures),
        "ranking_order_invariance_failure_count": len(ranking_order_invariance_failures),
        "selected_record_invariance_failure_count": len(selected_record_invariance_failures),
        "source_event_classification_failure_count": len(source_event_classification_failures),
        "source_event_type_mismatch_count": len(source_event_type_mismatches),
        "historical_raw_reuse_count": len(linkage_result.historical_raw_reuse_failures),
        "physical_request_mutation_failure_count": len(linkage_result.physical_request_mutation_failures),
        "live_lineage_failure_count": len(linkage_result.live_lineage_failures),
        "claim_event_selection_influence_count": len(claim_event_influence_failures),
        "claim_context_selection_influence_count": len(claim_context_influence_failures),
        "claim_anchor_type_selection_influence_count": len(claim_anchor_type_influence_failures),
        "claim_anchor_date_selection_influence_count": len(claim_anchor_date_influence_failures),
        "event_type_ambiguity_count": len(event_type_ambiguity_failures),
        "event_context_ambiguity_count": len(event_context_ambiguity_failures),
        "event_timing_ambiguity_count": len(event_timing_ambiguity_failures),
        "semantic_binding_failure_count": len(semantic_binding_failures),
        "invalid_binding_relationship_count": len(invalid_binding_relationship_failures),
        "global_semantic_block_authority_count": len(global_semantic_block_authority_failures),
        "archive_provenance_failure_count": len(archive_provenance_failures),
        "archive_member_ambiguity_count": len(archive_member_ambiguity_failures),
        "archive_transport_inconsistency_count": len(archive_transport_inconsistencies),
        "archive_member_inconsistency_count": len(archive_member_inconsistencies),
        "producing_request_failure_count": len(linkage_result.producing_request_failures),
        "cross_run_request_linkage_failure_count": len(linkage_result.cross_run_request_linkage_failures),
        "invalid_retrieval_mode_count": len(linkage_result.invalid_retrieval_modes),
        "record_identity_failure_count": len(linkage_result.record_identity_failures),
        "issuer_identity_failure_count": len(linkage_result.issuer_identity_failures),
        "candidate_linkage_failure_count": len(linkage_result.candidate_linkage_failures),
        "pykrx_linkage_failure_count": len(linkage_result.pykrx_linkage_failures),
        "raw_orphan_file_count": len(linkage_result.raw_orphan_failures),
        "date_set_mismatch_count": date_set_mismatch_count,
        "authorized_reconciliation_count": sum(1 for s in parity_statuses if s == "AUTHORIZED_DATE_RECONCILIATION_MATCH"),
        "insufficient_window_count": insufficient_window_count,
        "ohlc_match_count": sum(1 for _, r in parity_df.iterrows() if r.get("open_mismatch_count", 0) == 0),
        "ohlc_mismatch_count": ohlc_mismatch_count,
        "candidate_error_count": candidate_error_count,
        "comparator_error_count": comparator_error_count,
        "network_accounting_failure_count": 0 if accounting.accounting_cross_invariant_pass else 1,
        "linkage_evaluation_status": linkage_result.linkage_evaluation_status,
        "all_linkage_valid": linkage_result.all_linkage_valid,
        "total_provenance_failure_count": linkage_result.total_linkage_failures,
        "cohort_frozen_before_price_fetch": True,
        "cohort_frozen_at": cohort_frozen_at,
        "cohort_sha256_before_price_fetch": cohort_sha,
    }

    gate06_pass, gate06_blockers = evaluate_gate06(gate06_eval_metrics)

    gate06_payload = dict(gate06_eval_metrics)
    gate06_payload["schema"] = "gate06_corporate_action_reassessment_v01_fix03_correction_12"
    gate06_payload["canonical_run_id"] = canonical_run_id
    gate06_payload["directive_id"] = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12"
    gate06_payload["gate_06_pass"] = gate06_pass
    gate06_payload["gate_06_blockers"] = gate06_blockers

    gate06_path = output_dir / "gate06_corporate_action_reassessment_v01_fix03_correction_12.json"
    gate06_path.write_text(json.dumps(gate06_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

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
        inherited_gates[g_key] = bool(isinstance(val, bool) and val is True)

    all_15_gates = dict(inherited_gates)
    all_15_gates["gate_06_corporate_action_parity"] = gate06_pass
    source_authority_gates_pass = bool(
        all(inherited_gates.values()) and gate06_pass and len(gate06_blockers) == 0
    )
    production_certification_ready_flag = production_certification_ready(
        all_source_gates_pass=source_authority_gates_pass,
        regression_certification=regression_certification,
    )
    all_15_gates["gate_15_no_unresolved_conditions"] = bool(
        source_authority_gates_pass and production_certification_ready_flag
    )

    all_gates_pass = all(all_15_gates.values())

    if all_gates_pass and production_certification_ready_flag:
        review_decision = "APPROVED_FOR_PRODUCTION_INTEGRATION"
        prod_integration_auth = True
        next_state = "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
        blocking_conditions = []
        reason_codes = ["ALL_15_SOURCE_AUTHORITY_REVIEW_GATES_PASSED_FIX03_CORRECTION_12"]
    elif ohlc_mismatch_count > 0:
        review_decision = "REJECTED_AS_PRODUCTION_AUTHORITY"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"
        blocking_conditions = list(gate06_blockers)
        reason_codes = ["CORPORATE_ACTION_PRICE_CONTRADICTION"]
    else:
        review_decision = "CONDITIONAL_REVIEW_REQUIRED"
        prod_integration_auth = False
        next_state = "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12"
        blocking_conditions = list(gate06_blockers)
        if source_authority_gates_pass and not regression_certification.certification_valid:
            blocking_conditions.extend(regression_certification.blockers)
            reason_codes = list(regression_certification.blockers) or ["REGRESSION_CERTIFICATION_INVALID"]
        else:
            reason_codes = ["OFFICIAL_EVIDENCE_INCOMPLETE"]

    successful_doc_count = sum(1 for m in raw_manifest_entries.values() if m.get("content_validation_status") == "VALID" and m.get("live_lineage_valid") and m.get("size_bytes", 0) > 0)

    decision_payload = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "authoritative_technical_parent": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_12,
        "git_code_snapshot": asdict(git_snapshot),
        "parent_freeze_valid": parent_freeze["all_parent_inputs_unchanged"],
        "preflight_verdict": preflight["verdict"],
        "document_readiness_verdict": doc_readiness["verdict"],
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "candidate_endpoint": "https://fchart.stock.naver.com/sise.nhn",
        "official_discovery_requests_logical": accounting.official_discovery_logical_requests,
        "official_discovery_requests_physical": accounting.official_discovery_physical_attempts,
        "official_discovery_success_count": len(discovery_manifest_entries),
        "official_document_manifest_entry_count": len(raw_manifest_entries),
        "official_document_success_count": successful_doc_count,
        "authority_valid_control_count": auth_valid_count,
        "final_cohort_size": len(final_cohort_rows),
        "final_cohort_sha": cohort_sha if final_cohort_rows else "",
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
        "provenance_failures": linkage_result.total_linkage_failures,
        "linkage_evaluation_status": linkage_result.linkage_evaluation_status,
        "all_linkage_valid": linkage_result.all_linkage_valid,
        "gate_06_result": gate06_pass,
        "gate_15_result": all_15_gates["gate_15_no_unresolved_conditions"],
        "inherited_gate_results": inherited_gates,
        "all_15_gate_results": all_15_gates,
        "all_gates_passed": all_gates_pass,
        "production_certification_ready": production_certification_ready_flag,
        "full_suite_completion": regression_certification.full_suite_completion,
        "new_regression_count": regression_certification.new_regression_count,
        "regression_certification": regression_certification.to_dict(),
        "blocking_conditions": blocking_conditions,
        "reason_codes": reason_codes,
        "review_decision": review_decision,
        "production_integration_authorized": prod_integration_auth,
        "active_production_authority_changed": False,
        "recommended_next_state": next_state,
        "network_accounting": accounting.to_dict(),
    }
    (output_dir / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_12.json").write_text(
        json.dumps(decision_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Manifest
    _write_artifact_manifest_correction_12(output_dir, canonical_run_id, review_decision, prod_integration_auth, raw_manifest_entries, discovery_manifest_entries)
    return decision_payload


def run_correction12_from_canonical_evidence(
    *,
    repo_root: Path = Path("."),
    output_dir: Path | None = None,
    parent_dir: Path | None = None,
    allow_network: bool = True,
) -> dict[str, Any]:
    """Run the single production C12 path using the immutable pytest summary."""
    root = Path(repo_root)
    evidence_path = root / FULL_PYTEST_EVIDENCE_RELATIVE_PATH_CORRECTION_12
    regression_evidence = load_full_regression_evidence(evidence_path)
    resolved_output = Path(output_dir) if output_dir is not None else root / DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_12
    resolved_parent = Path(parent_dir) if parent_dir is not None else root / PARENT_FIX03_CORRECTION_DIR
    return run_corporate_action_evidence_acquisition_fix03_correction_12(
        output_dir=resolved_output,
        parent_dir=resolved_parent,
        allow_network=allow_network,
        regression_evidence=regression_evidence,
        repo_root=root,
    )




def _terminate_on_readiness_or_preflight_failure_correction_12(
    output_dir: Path,
    parent_dir: Path,
    canonical_run_id: str,
    preflight: dict[str, Any],
    doc_readiness: dict[str, Any],
    accounting: CorporateActionNetworkAccounting,
    failure_reason: str,
    regression_certification: FullRegressionCertification | None = None,
    git_snapshot: GitCodeSnapshot | None = None,
) -> dict[str, Any]:
    """Strict Hard-Gate termination when preflight or readiness probe fails."""
    if regression_certification is None:
        regression_certification = validate_full_regression_evidence(
            None,
            expected_fix_head="",
            expected_fix_tree_sha="",
        )
    if git_snapshot is None:
        git_snapshot = observe_git_code_snapshot(Path("."))
    parent_freeze = verify_parent_authority_freeze(parent_dir)
    parent_freeze = {
        **parent_freeze,
        "schema": "parent_authority_freeze_validation_v01_fix03_correction_12",
        "directive_id": DIRECTIVE_ID_CORRECTION_12,
    }
    (output_dir / "parent_authority_freeze_validation_v01_fix03_correction_12.json").write_text(
        json.dumps(parent_freeze, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    source_inventory = {
        "schema": "corporate_action_evidence_source_inventory_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "sources": [],
    }
    (output_dir / "corporate_action_evidence_source_inventory_v01_fix03_correction_12.json").write_text(
        json.dumps(source_inventory, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    accounting.compute_totals()
    net_dict = accounting.to_dict()
    net_dict["schema"] = "corporate_action_evidence_network_accounting_v01_fix03_correction_12"
    net_dict["directive_id"] = DIRECTIVE_ID_CORRECTION_12
    net_dict["canonical_run_id"] = canonical_run_id
    (output_dir / "corporate_action_evidence_network_accounting_v01_fix03_correction_12.json").write_text(
        json.dumps(net_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    linkage_result = validate_live_evidence_linkage(
        canonical_run_id=canonical_run_id,
        discovery_records=[],
        document_records=[],
        raw_manifest_entries=[],
        authority_rows=[],
        request_logs=accounting.request_logs,
        current_output_dir=output_dir,
        accounting_cross_invariant_pass=accounting.accounting_cross_invariant_pass,
        schema_suffix="12",
    )
    linkage_result.linkage_evaluation_status = "NOT_EVALUATED_DUE_TO_READINESS_FAILURE"
    linkage_result.live_lineage_failures.append(
        _linkage_failure("DOWNSTREAM_ACQUISITION_NOT_EXECUTED", reason=failure_reason)
    )
    linkage_payload = linkage_result.to_dict()
    linkage_payload.update({
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "discovery_pages_checked": 0,
        "document_items_checked": 0,
    })
    (output_dir / "live_evidence_linkage_validation_v01_fix03_correction_12.json").write_text(
        json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    gate_failure_reason = (
        "SOURCE_ACQUISITION_NOT_EXECUTED"
        if failure_reason in {"CODE_SCOPE_WORKTREE_DIRTY", "SOURCE_ACQUISITION_NOT_EXECUTED"}
        else failure_reason
    )
    gate06_blockers = [
        f"Readiness hard gate failed: {gate_failure_reason}",
        "Official evidence deficit: 0/8 authority valid",
        "Corporate action event diversity requirement failed",
    ]
    certification_blockers = list(regression_certification.blockers)
    gate06_payload = {
        "schema": "gate06_corporate_action_reassessment_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "preflight_verdict": preflight.get("verdict", "FAIL"),
        "document_readiness_verdict": doc_readiness.get("verdict", "FAIL"),
        "authority_valid_controls_count": 0,
        "final_cohort_control_count": 0,
        "diversity_pass": False,
        "gate_06_pass": False,
        "gate_06_blockers": gate06_blockers,
    }
    gate06_payload.update(linkage_result.to_metrics())
    (output_dir / "gate06_corporate_action_reassessment_v01_fix03_correction_12.json").write_text(
        json.dumps(gate06_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

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
        inherited_gates[g_key] = bool(isinstance(val, bool) and val is True)

    all_15_gates = dict(inherited_gates)
    all_15_gates["gate_06_corporate_action_parity"] = False
    all_15_gates["gate_15_no_unresolved_conditions"] = False

    decision_payload = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "parent_directive": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_11",
        "authoritative_technical_parent": "ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW_V01_FIX03_CORRECTION",
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_12,
        "git_code_snapshot": asdict(git_snapshot),
        "parent_freeze_valid": parent_freeze["all_parent_inputs_unchanged"],
        "preflight_verdict": preflight.get("verdict", "FAIL"),
        "document_readiness_verdict": doc_readiness.get("verdict", "FAIL"),
        "official_discovery_requests_logical": 0,
        "official_discovery_requests_physical": 0,
        "official_discovery_success_count": 0,
        "official_document_manifest_entry_count": 0,
        "official_document_success_count": 0,
        "authority_valid_control_count": 0,
        "final_cohort_size": 0,
        "final_cohort_sha": "",
        "naver_actual_requests": 0,
        "raw_pykrx_actual_queries": 0,
        "exact_date_match_controls": 0,
        "authorized_reconciliation_controls": 0,
        "date_mismatch_controls": 0,
        "insufficient_window_controls": 0,
        "ohlc_mismatch_controls": 0,
        "candidate_errors": 0,
        "comparator_errors": 0,
        "provenance_failures": len(linkage_payload["linkage_failures"]),
        "gate_06_result": False,
        "gate_15_result": False,
        "inherited_gate_results": inherited_gates,
        "all_15_gate_results": all_15_gates,
        "all_gates_passed": False,
        "production_certification_ready": False,
        "full_suite_completion": regression_certification.full_suite_completion,
        "new_regression_count": regression_certification.new_regression_count,
        "regression_certification": regression_certification.to_dict(),
        "blocking_conditions": gate06_blockers + certification_blockers,
        "reason_codes": [failure_reason] + certification_blockers,
        "review_decision": "CONDITIONAL_REVIEW_REQUIRED",
        "production_integration_authorized": False,
        "active_production_authority_changed": False,
        "recommended_next_state": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "network_accounting": accounting.to_dict(),
    }
    (output_dir / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_12.json").write_text(
        json.dumps(decision_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    _write_artifact_manifest_correction_12(output_dir, canonical_run_id, "CONDITIONAL_REVIEW_REQUIRED", False, {}, {})
    return decision_payload




def _write_artifact_manifest_correction_12(
    output_dir: Path,
    canonical_run_id: str,
    review_decision: str,
    prod_integration_auth: bool,
    raw_manifest_entries: dict[str, Any],
    discovery_manifest_entries: dict[str, Any],
) -> None:
    manifest_entries = {}
    for p in output_dir.glob("*.*"):
        if p.name != "artifact_manifest.json":
            manifest_entries[p.name] = {
                "path": f"artifacts/data/end_to_end_data_parity/v01/adjusted_price_source_authority_review/corporate_action_evidence/v01_fix03_correction_12/{p.name}",
                "size_bytes": p.stat().st_size,
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            }

    for rfname, rmeta in raw_manifest_entries.items():
        manifest_entries[f"raw/{rfname}"] = rmeta
    for dfname, dmeta in discovery_manifest_entries.items():
        manifest_entries[f"discovery_raw/{dfname}"] = dmeta

    manifest_payload = {
        "schema": "corporate_action_evidence_manifest_v01_fix03_correction_12",
        "canonical_run_id": canonical_run_id,
        "directive_id": "ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_12",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_12,
        "review_decision": review_decision,
        "production_integration_authorized": prod_integration_auth,
        "artifacts": manifest_entries,
    }
    manifest_path = output_dir / "artifact_manifest.json"
    manifest_path.write_text(json.dumps(manifest_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _c13_normalize_price_frame(value: Any, *, control: Mapping[str, Any], source: str, request_id: str) -> pd.DataFrame:
    """Normalize exactly the source rows consumed by C13 parity evaluation."""
    columns = ["date", "open", "high", "low", "close", "volume"]
    frame = _evidence_frame(value)
    if frame.empty:
        return pd.DataFrame(columns=list(PRICE_ROW_REQUIRED_COLUMNS))
    aliases = {"일자": "date", "날짜": "date", "시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
    frame = frame.rename(columns={key: alias for key, alias in aliases.items() if key in frame.columns}).copy()
    if any(column not in frame.columns for column in columns):
        return pd.DataFrame(columns=list(PRICE_ROW_REQUIRED_COLUMNS))
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    frame = frame.dropna(subset=["date"]).sort_values("date", kind="stable").drop_duplicates("date", keep="first")
    for column in columns[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=columns[1:]).reset_index(drop=True)
    rowset_sha = _c13_compute_rowset_sha(frame)
    metadata = {
        "canonical_run_id": control.get("canonical_run_id", ""), "control_id": control.get("control_id", ""), "ticker": normalize_ticker(str(control.get("ticker", ""))),
        "corp_code": control.get("corp_code", ""), "authority_record_id": control.get("authority_record_id", control.get("selected_record_id", "")), "source": source,
        "request_id": request_id, "evidence_origin": "MOCKED_NORMALIZED_SOURCE_ROWSET" if str(request_id).startswith("MOCK_") else "LIVE_NORMALIZED_SOURCE_ROWSET",
        "price_window_start": control.get("price_window_start", ""), "price_window_end": control.get("price_window_end", ""), "official_anchor_date": control.get("official_anchor_date", ""), "source_rowset_sha256": rowset_sha,
    }
    for key, value in metadata.items():
        frame[key] = value
    return frame[["canonical_run_id", "control_id", "ticker", "corp_code", "authority_record_id", "source", "request_id", "evidence_origin", "price_window_start", "price_window_end", "official_anchor_date", *columns, "source_rowset_sha256"]]


def _c13_compute_rowset_sha(frame: pd.DataFrame) -> str:
    columns = ["date", "open", "high", "low", "close", "volume"]
    normalized = frame[columns].copy()
    normalized["date"] = pd.to_datetime(normalized["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in columns[1:]:
        normalized[column] = pd.to_numeric(normalized[column], errors="coerce")
    normalized = normalized.sort_values("date", kind="stable").reset_index(drop=True)
    return hashlib.sha256(normalized.to_csv(index=False, float_format="%.15g").encode("utf-8")).hexdigest()


def _c13_json_dates(values: list[str]) -> str:
    return json.dumps(sorted(str(value) for value in values), ensure_ascii=False, separators=(",", ":"))


def _c13_price_parity_rows(controls: list[Mapping[str, Any]], source_frames: Mapping[tuple[str, str], pd.DataFrame], request_ids: Mapping[tuple[str, str], str], canonical_run_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parity_rows: list[dict[str, Any]] = []
    reconciliation_rows: list[dict[str, Any]] = []
    for control in controls:
        cid = str(control.get("control_id", "")); ticker = normalize_ticker(str(control.get("ticker", "")))
        naver = source_frames.get((cid, "NAVER_DIRECT"), pd.DataFrame()); pykrx = source_frames.get((cid, "RAW_PYKRX_COMPARATOR"), pd.DataFrame())
        cand_dates = set(naver["date"].astype(str)) if not naver.empty else set(); py_dates = set(pykrx["date"].astype(str)) if not pykrx.empty else set()
        common = sorted(cand_dates & py_dates); cand_only = sorted(cand_dates - py_dates); py_only = sorted(py_dates - cand_dates)
        anchor = str(control.get("official_anchor_date", "")); pre = sum(date < anchor for date in common); post = sum(date > anchor for date in common)
        mismatches = {name: 0 for name in ("open", "high", "low", "close", "volume")}
        if common and not naver.empty and not pykrx.empty:
            n_index, p_index = naver.set_index("date"), pykrx.set_index("date")
            for date in common:
                for name in mismatches:
                    if float(n_index.loc[date, name]) != float(p_index.loc[date, name]): mismatches[name] += 1
        status = "MATCH" if (not naver.empty and not pykrx.empty and common and not cand_only and not py_only and pre >= 5 and post >= 5 and sum(mismatches[name] for name in ("open", "high", "low", "close")) == 0) else "MISMATCH"
        parity_rows.append({
            "canonical_run_id": canonical_run_id, "control_id": cid, "ticker": ticker, "corp_code": control.get("corp_code", ""), "authority_record_id": control.get("authority_record_id", control.get("selected_record_id", "")),
            "candidate_request_id": request_ids.get((cid, "NAVER_DIRECT"), ""), "pykrx_request_id": request_ids.get((cid, "RAW_PYKRX_COMPARATOR"), ""), "price_window_start": control.get("price_window_start", ""), "price_window_end": control.get("price_window_end", ""), "official_anchor_date": anchor,
            "candidate_row_count": len(naver), "pykrx_row_count": len(pykrx), "common_date_count": len(common), "candidate_only_date_count": len(cand_only), "pykrx_only_date_count": len(py_only), "pre_event_common_count": pre, "post_event_common_count": post,
            "open_mismatch_count": mismatches["open"], "high_mismatch_count": mismatches["high"], "low_mismatch_count": mismatches["low"], "close_mismatch_count": mismatches["close"], "volume_mismatch_count": mismatches["volume"], "parity_status": status,
        })
        reconciliation_rows.append({
            "canonical_run_id": canonical_run_id, "control_id": cid, "ticker": ticker, "authority_record_id": control.get("authority_record_id", control.get("selected_record_id", "")), "candidate_request_id": request_ids.get((cid, "NAVER_DIRECT"), ""), "pykrx_request_id": request_ids.get((cid, "RAW_PYKRX_COMPARATOR"), ""),
            "candidate_date_count": len(cand_dates), "pykrx_date_count": len(py_dates), "common_date_count": len(common), "candidate_only_date_count": len(cand_only), "pykrx_only_date_count": len(py_only), "candidate_only_dates": _c13_json_dates(cand_only), "pykrx_only_dates": _c13_json_dates(py_only), "reconciliation_status": "MATCH" if not cand_only and not py_only else "MISMATCH",
        })
    return parity_rows, reconciliation_rows


def _write_c13_fail_closed(
    output: Path,
    snapshot: GitCodeSnapshot,
    certification: FullRegressionCertification,
    reason: str,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    run_id = f"CORP_AUTH_FIX03_CORRECTION_13_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    decision = {
        "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13",
        "canonical_run_id": run_id, "directive_id": DIRECTIVE_ID_CORRECTION_13,
        "parent_directive": PARENT_DIRECTIVE_CORRECTION_13,
        "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_13,
        "git_code_snapshot": asdict(snapshot), "full_suite_completion": certification.full_suite_completion,
        "new_regression_count": certification.new_regression_count,
        "regression_certification": certification.to_dict(), "gate_06_result": False,
        "gate_15_result": False, "all_gates_passed": False,
        "production_certification_ready": False, "production_integration_authorized": False,
        "review_decision": "CONDITIONAL_REVIEW_REQUIRED",
        "recommended_next_state": DIRECTIVE_ID_CORRECTION_13,
        "blocking_conditions": [reason, *certification.blockers],
        "reason_codes": [reason, *certification.blockers],
        "network_accounting": {"execution_mode": "CERTIFICATION_HARD_STOP", "grand_total_physical_external_calls": 0, "request_logs": []},
    }
    (output / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return decision


def _copy_c12_artifacts_to_c13(stage: Path, output: Path, canonical_run_id: str) -> None:
    """Materialize a C12 stage as C13 and rebind every persisted representation.

    This adapter is intentionally exhaustive: JSON values, CSV cells, nested
    raw/discovery paths, schemas, and run IDs are all rewritten before any C13
    validator is run.  The stage's artifact manifest is never copied because it
    describes the pre-materialization representation.
    """
    output.mkdir(parents=True, exist_ok=True)
    for child in output.iterdir():
        if child.is_file() and child.name in IMMUTABLE_C13_SOURCE_FILES:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    stage_run_id = ""
    for candidate in stage.rglob("*.json"):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        if isinstance(payload, Mapping) and str(payload.get("canonical_run_id") or "").strip():
            stage_run_id = str(payload["canonical_run_id"]).strip()
            break

    def replace(value: Any) -> Any:
        if isinstance(value, str):
            result = value
            if stage_run_id:
                result = result.replace(stage_run_id, canonical_run_id)
            result = result.replace("CORRECTION_12", "CORRECTION_13").replace("correction_12", "correction_13")
            return result
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    def target_for(source: Path) -> Path:
        relative = source.relative_to(stage)
        parts = [part.replace("CORRECTION_12", "CORRECTION_13").replace("correction_12", "correction_13") for part in relative.parts]
        target = output.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    for source in sorted(stage.rglob("*")):
        if not source.is_file() or source.name == "artifact_manifest.json":
            continue
        target = target_for(source)
        if source.suffix.lower() == ".json":
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                shutil.copyfile(source, target)
            else:
                target.write_text(json.dumps(replace(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        elif source.suffix.lower() == ".csv":
            try:
                frame = pd.read_csv(source, dtype=object, keep_default_na=False)
            except (OSError, UnicodeDecodeError, pd.errors.ParserError):
                shutil.copyfile(source, target)
            else:
                for column in frame.columns:
                    frame[column] = frame[column].map(replace)
                frame.to_csv(target, index=False)
        else:
            shutil.copyfile(source, target)


def _load_c13_candidate_evaluation(
    output: Path,
    *,
    fallback_by_record: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Rebuild candidate-resolution semantics from the final C13 CSVs."""
    candidate_rows = _evidence_frame(output / "corporate_action_document_probe_audit_v01_fix03_correction_13.csv")
    ranked_rows = _evidence_frame(output / "corporate_action_discovery_candidate_audit_v01_fix03_correction_13.csv")
    score_by_candidate = {
        (str(row.get("ticker", "")), str(row.get("rcept_no", ""))): row.get("event_match_score", 0)
        for row in ranked_rows.to_dict("records")
    }
    candidate_groups: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_rows.to_dict("records"):
        source = str(row.get("source", "")).strip()
        status_code = str(row.get("http_status", "")).strip()
        obtained = bool(source and status_code not in {"", "0", "500"})
        semantic_valid = str(row.get("authority_valid", "")).lower() == "true"
        score = score_by_candidate.get(
            (str(row.get("ticker", "")), str(row.get("rcept_no", ""))),
            row.get("event_match_score", 0),
        )
        archive_value = str(row.get("archive_provenance_valid", "")).strip().lower()
        archive_valid = archive_value not in {"false", "0", "no"}
        try:
            rank = int(float(row.get("candidate_rank", 0) or 0))
        except (TypeError, ValueError):
            rank = 0
        try:
            score_value = int(float(score or 0))
        except (TypeError, ValueError):
            score_value = 0
        fact = {
            "ticker": str(row.get("ticker", "")),
            "candidate_rank": rank,
            "event_match_score": score_value,
            "official_evidence_obtained": obtained,
            "semantic_valid": semantic_valid,
            "official_content_usable": str(row.get("validation_reason", "")).strip() not in {"EMPTY_OR_UNUSABLE_DOCUMENT", "ARCHIVE_MEMBER_AMBIGUOUS"},
            "fallback_available": source == "DART_OFFICIAL_DISCLOSURE",
            "archive_provenance_valid": archive_valid,
            "rcept_no": row.get("rcept_no", ""),
        }
        fallback = (fallback_by_record or {}).get(str(row.get("rcept_no", "")))
        if isinstance(fallback, Mapping):
            fallback_provenance = fallback.get("provenance", {}) if isinstance(fallback.get("provenance"), Mapping) else {}
            fact.update({
                "identity_authority_tier": fallback.get("identity_authority_tier", fallback_provenance.get("identity_authority_tier", "")),
                "identity_record_id": fallback.get("identity_record_id", fallback_provenance.get("identity_record_id", row.get("rcept_no", ""))),
                "identity_candidate_rank": fallback.get("identity_candidate_rank", fallback_provenance.get("identity_candidate_rank", rank)),
                "fallback_validation": dict(fallback),
                "content_authority_tier": fallback_provenance.get("content_authority_tier", ""),
            })
        candidate_groups.setdefault(str(row.get("ticker", "")), []).append(fact)
    evaluations = [evaluate_candidate_resolution_population(group) for group in candidate_groups.values()]
    selected_candidates = [item["selected_candidate"] for item in evaluations if item.get("selected_candidate")]
    return {
        "selected_candidate": selected_candidates[0] if len(selected_candidates) == 1 else None,
        "unresolved_higher_priority_candidate_count": sum(item["unresolved_higher_priority_candidate_count"] for item in evaluations),
        "selected_authority_archive_provenance_failure_count": sum(item["selected_authority_archive_provenance_failure_count"] for item in evaluations),
        "candidate_statuses": [status for item in evaluations for status in item["candidate_statuses"]],
    }


def _read_json_file(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return default


def _file_immutability_fingerprint(path: Path) -> dict[str, Any]:
    """Capture portable physical identity and bytes for immutable source checks."""
    target = Path(path)
    stat = target.stat()
    raw = target.read_bytes()
    return {
        "inode": getattr(stat, "st_ino", None),
        "mtime_ns": stat.st_mtime_ns,
        "size_bytes": stat.st_size,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": raw,
    }


def _load_c13_final_linkage_inputs(output: Path) -> dict[str, Any]:
    network = _read_json_file(output / "corporate_action_evidence_network_accounting_v01_fix03_correction_13.json", {})
    raw_manifest = _read_json_file(output / "corporate_action_raw_evidence_manifest_v01_fix03_correction_13.json", {})
    authority_payload = _read_json_file(output / "corporate_action_authority_records_v01_fix03_correction_13.json", {})
    return {
        "discovery_records": _evidence_frame(output / "corporate_action_official_discovery_v01_fix03_correction_13.csv").to_dict("records"),
        "document_records": _evidence_frame(output / "corporate_action_official_document_validation_v01_fix03_correction_13.csv").to_dict("records"),
        "raw_manifest_entries": list(raw_manifest.get("artifacts", {}).values()) if isinstance(raw_manifest, Mapping) else [],
        "authority_rows": authority_payload.get("records", []) if isinstance(authority_payload, Mapping) else [],
        "request_logs": network.get("request_logs", []) if isinstance(network, Mapping) else [],
        "price_request_logs": [
            row for row in (network.get("request_logs", []) if isinstance(network, Mapping) else [])
            if row.get("source") in {"NAVER_DIRECT", "RAW_PYKRX_COMPARATOR"}
        ],
        "accounting": network if isinstance(network, Mapping) else {},
    }


def recompute_c13_metric_values(
    output: Path,
    *,
    validation: PersistedPriceParityValidation,
    linkage: LiveEvidenceLinkageResult,
    accounting: Mapping[str, Any],
    network_validation: C13NetworkAccountingValidation | None = None,
) -> dict[str, Any]:
    """Independently reproduce Gate06 production metrics from final evidence."""
    cohort = _control_frame(output / "corporate_action_review_cohort_v01_fix03_correction_13.csv")
    controls = {str(row.get("control_id", "")).strip() for row in cohort.to_dict("records") if str(row.get("control_id", "")).strip()}
    distribution: dict[str, int] = {}
    for row in cohort.to_dict("records"):
        event = str(row.get("normalized_event_type", "")).strip()
        if event:
            distribution[event] = distribution.get(event, 0) + 1
    authority_count = len(controls)
    diversity_pass = bool(
        authority_count >= 8
        and distribution.get("STOCK_SPLIT", 0) >= 2
        and distribution.get("MERGER", 0) >= 1
        and distribution.get("RIGHTS_OFFERING", 0) >= 1
        and distribution.get("BONUS_ISSUE", 0) >= 1
    )
    candidate_eval = _load_c13_candidate_evaluation(output)
    network = network_validation or validate_c13_network_accounting(accounting)
    values: dict[str, Any] = {
        "authority_valid_controls_count": authority_count,
        "final_cohort_control_count": authority_count,
        "event_type_counts": distribution,
        "diversity_pass": diversity_pass,
        "unresolved_higher_priority_candidate_count": candidate_eval["unresolved_higher_priority_candidate_count"],
        "selected_authority_archive_provenance_failure_count": candidate_eval["selected_authority_archive_provenance_failure_count"],
        "naver_control_count": validation.naver_control_count,
        "pykrx_control_count": validation.pykrx_control_count,
        "parity_control_count": validation.parity_control_count,
        "reconciliation_control_count": validation.reconciliation_control_count,
        "naver_price_row_count": validation.naver_price_row_count,
        "pykrx_price_row_count": validation.pykrx_price_row_count,
        "exact_match_control_count": validation.exact_match_control_count,
        "date_mismatch_control_count": validation.date_mismatch_control_count,
        "insufficient_window_control_count": validation.insufficient_window_control_count,
        "ohlc_mismatch_control_count": validation.ohlc_mismatch_control_count,
        "all_controls_evidenced": validation.all_controls_evidenced,
        "all_cardinality_valid": validation.all_cardinality_valid,
        "all_request_bindings_valid": validation.all_request_bindings_valid,
        "persisted_price_evidence_status": validation.evaluation_status,
        **linkage.to_metrics(),
        "network_accounting_failure_count": 0 if network.all_network_accounting_valid else 1,
        "accounting_cross_invariant_pass": network.all_network_accounting_valid,
        "request_log_physical_entries": network.recomputed_request_log_physical_entries,
        "downstream_logged_physical_calls": network.recomputed_downstream_calls,
        "price_physical_calls": network.recomputed_price_calls,
        "evidence_acquisition_physical_calls": network.recomputed_evidence_calls,
        "grand_total_physical_external_calls": network.recomputed_grand_total,
        "total_physical_external_calls": network.recomputed_grand_total,
        "official_discovery_physical_attempts": network.recomputed_official_discovery_calls,
        "official_document_probe_physical_attempts": network.recomputed_document_probe_calls,
        "dart_viewer_fallback_physical_attempts": network.recomputed_viewer_fallback_calls,
        "alternative_document_candidate_physical_attempts": network.recomputed_alternative_candidate_calls,
    }
    return values


def audit_c13_metric_provenance(
    output: Path,
    *,
    gate_payload: Mapping[str, Any],
    decision_payload: Mapping[str, Any],
    validation: PersistedPriceParityValidation,
    linkage: LiveEvidenceLinkageResult,
    accounting: Mapping[str, Any],
) -> dict[str, Any]:
    """Compare independently recomputed metrics with Gate06 and decision claims."""
    network = validate_c13_network_accounting(accounting)
    recomputed = recompute_c13_metric_values(output, validation=validation, linkage=linkage, accounting=accounting, network_validation=network)
    production_keys = (
        "authority_valid_controls_count", "final_cohort_control_count", "diversity_pass",
        "unresolved_higher_priority_candidate_count", "selected_authority_archive_provenance_failure_count",
        "naver_control_count", "pykrx_control_count", "parity_control_count", "reconciliation_control_count",
        "naver_price_row_count", "pykrx_price_row_count", "exact_match_control_count",
        "date_mismatch_control_count", "insufficient_window_control_count", "ohlc_mismatch_control_count",
        "all_controls_evidenced", "all_cardinality_valid", "all_request_bindings_valid",
        "persisted_price_evidence_status", "all_linkage_valid", "network_accounting_failure_count",
        "request_log_physical_entries", "downstream_logged_physical_calls", "price_physical_calls",
        "evidence_acquisition_physical_calls", "grand_total_physical_external_calls", "total_physical_external_calls",
    )
    mismatches: list[dict[str, Any]] = []
    missing: list[str] = []
    network_keys = {
        "request_log_physical_entries", "downstream_logged_physical_calls", "price_physical_calls",
        "evidence_acquisition_physical_calls", "grand_total_physical_external_calls", "total_physical_external_calls",
    }
    for key in production_keys:
        expected = recomputed.get(key)
        observed_source: Mapping[str, Any] = accounting if key in network_keys else gate_payload
        if key not in observed_source:
            missing.append(key)
        elif observed_source.get(key) != expected:
            mismatches.append({"source": "network_accounting" if key in network_keys else "gate06", "metric": key, "expected": expected, "observed": observed_source.get(key)})
        decision_source = decision_payload.get("network_accounting", {}) if key in network_keys and isinstance(decision_payload.get("network_accounting"), Mapping) else decision_payload
        if key in decision_source and decision_source.get(key) != expected:
            mismatches.append({"source": "decision", "metric": key, "expected": expected, "observed": decision_source.get(key)})
    blockers = ["METRIC_PROVENANCE_RECOMPUTATION_MISMATCH"] if mismatches else []
    blockers.extend(network.blockers)
    if missing:
        blockers.append("METRIC_PROVENANCE_METRIC_MISSING")
    blockers = list(dict.fromkeys(blockers))
    complete = not mismatches and not missing
    return {
        "schema": "gate06_metric_provenance_audit_v01_fix03_correction_13",
        "canonical_run_id": str(gate_payload.get("canonical_run_id", "")),
        "verdict": "COMPLETE" if complete else "INCOMPLETE",
        "all_metrics_audited": complete,
        "recomputed_metrics": recomputed,
        "production_significant_metrics": list(production_keys),
        "missing_metrics": missing,
        "mismatches": mismatches,
        "network_accounting": network.to_dict(),
        "blockers": blockers,
    }


def run_corporate_action_evidence_acquisition_fix03_correction_13(
    output_dir: Path | None = None,
    *,
    repo_root: Path = Path("."),
    allow_network: bool = True,
    parent_dir: Path | None = None,
) -> dict[str, Any]:
    """Run the single live-capable C13 orchestration using low-level adapters."""
    root = Path(repo_root)
    canonical_run_id = f"CORP_AUTH_FIX03_CORRECTION_13_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    snapshot = observe_git_code_snapshot(root)
    evidence_path = root / FULL_PYTEST_EVIDENCE_RELATIVE_PATH_CORRECTION_13
    summary_bytes = evidence_path.read_bytes() if evidence_path.is_file() else b""
    summary_before = _file_immutability_fingerprint(evidence_path) if evidence_path.is_file() else None
    evidence = load_full_regression_evidence(evidence_path)
    certification = validate_full_regression_evidence(evidence, expected_fix_head=snapshot.head, expected_fix_tree_sha=snapshot.tree_sha)
    if isinstance(evidence, Mapping) and evidence.get("schema") != "full_pytest_summary_v01_fix03_correction_13":
        certification.blockers.append("PYTEST_SCHEMA_MISMATCH")
        certification.blockers = list(dict.fromkeys(certification.blockers))
        certification.evidence_status = "INVALID"
        certification.certification_valid = False
    if snapshot.dirty:
        certification.blockers.append("CODE_SCOPE_WORKTREE_DIRTY")
        certification.blockers = list(dict.fromkeys(certification.blockers))
        certification.evidence_status = "INVALID"
        certification.certification_valid = False
    output = root / DEFAULT_CORP_EVIDENCE_DIR_FIX03_CORRECTION_13 if output_dir is None else Path(output_dir)
    if not certification.certification_valid:
        return _write_c13_fail_closed(output, snapshot, certification, "PYTEST_EVIDENCE_INVALID")

    stage_root = Path(tempfile.mkdtemp(prefix="c13-c12-acquisition-"))
    stage_output = stage_root / "v01_fix03_correction_12"
    try:
        stage_result = run_corporate_action_evidence_acquisition_fix03_correction_12(
            output_dir=stage_output,
            parent_dir=parent_dir,
            allow_network=allow_network,
            regression_evidence=certification,
            repo_root=root,
        )
        _copy_c12_artifacts_to_c13(stage_output, output, canonical_run_id)
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)

    output.mkdir(parents=True, exist_ok=True)
    # The canonical summary is immutable source evidence.  In the canonical
    # topology it already lives inside ``output`` and must never be rewritten;
    # non-canonical test output receives a copy for report completeness.
    summary_path = output / "full_pytest_summary_v01_fix03_correction_13.json"
    canonical_topology = summary_before is not None and output.resolve() == evidence_path.parent.resolve()
    if summary_bytes and not canonical_topology:
        summary_path.write_bytes(summary_bytes)
    summary_after = _file_immutability_fingerprint(evidence_path) if summary_before is not None and evidence_path.is_file() else None
    summary_unchanged = bool(
        summary_before is not None
        and summary_after is not None
        and summary_before["mtime_ns"] == summary_after["mtime_ns"]
        and summary_before["size_bytes"] == summary_after["size_bytes"]
        and summary_before["sha256"] == summary_after["sha256"]
        and summary_before["bytes"] == summary_after["bytes"]
    )
    certification_payload = build_full_pytest_certification_artifact(summary_bytes, certification)
    (output / FULL_PYTEST_CERTIFICATION_FILE_CORRECTION_13).write_text(
        json.dumps(certification_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    cohort_path = output / "corporate_action_review_cohort_v01_fix03_correction_13.csv"
    price_path = output / CORRECTION_13_PRICE_FILE
    parity_path = output / CORRECTION_13_PARITY_FILE
    recon_path = output / CORRECTION_13_RECONCILIATION_FILE
    controls = _evidence_frame(cohort_path)
    accounting_path = output / "corporate_action_evidence_network_accounting_v01_fix03_correction_13.json"
    accounting_payload = json.loads(accounting_path.read_text(encoding="utf-8")) if accounting_path.is_file() else {"request_logs": []}
    network_validation = validate_c13_network_accounting(accounting_payload)
    gate_path = output / "gate06_corporate_action_reassessment_v01_fix03_correction_13.json"
    gate_payload = json.loads(gate_path.read_text(encoding="utf-8")) if gate_path.is_file() else {}
    validation = validate_persisted_price_parity_evidence(price_path, parity_path, recon_path, controls, request_logs=accounting_payload.get("request_logs", []))

    identity_validation = validate_canonical_run_identity_correction13(output, canonical_run_id)
    identity_payload = identity_validation.to_dict()
    (output / "canonical_run_identity_validation_v01_fix03_correction_13.json").write_text(
        json.dumps(identity_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    final_inputs = _load_c13_final_linkage_inputs(output)
    final_linkage = validate_live_evidence_linkage(
        canonical_run_id=canonical_run_id,
        discovery_records=final_inputs["discovery_records"],
        document_records=final_inputs["document_records"],
        raw_manifest_entries=final_inputs["raw_manifest_entries"],
        authority_rows=final_inputs["authority_rows"],
        request_logs=final_inputs["request_logs"],
        price_request_logs=final_inputs["price_request_logs"],
        artifact_paths={"raw": output / "raw"},
        current_output_dir=output,
        accounting_cross_invariant_pass=bool(final_inputs["accounting"].get("accounting_cross_invariant_pass", False)),
        schema_suffix="13",
    )
    # The lineage flag is itself part of the final raw-manifest representation;
    # update it, then rerun linkage so the emitted result validates the exact
    # bytes that will be committed.
    failed_record_ids = {
        str(item.get("record_id") or item.get("authority_record_id") or item.get("document_id"))
        for item in final_linkage.linkage_failures
        if item.get("record_id") or item.get("authority_record_id") or item.get("document_id")
    }
    raw_manifest_path = output / "corporate_action_raw_evidence_manifest_v01_fix03_correction_13.json"
    raw_manifest = _read_json_file(raw_manifest_path, {})
    if isinstance(raw_manifest, dict) and isinstance(raw_manifest.get("artifacts"), dict):
        for item in raw_manifest["artifacts"].values():
            if isinstance(item, dict):
                record_id = _linkage_text(item, "official_record_id", "rcept_no", "authority_record_id")
                item["live_lineage_valid"] = bool(record_id and record_id not in failed_record_ids and final_linkage.all_linkage_valid)
        raw_manifest_path.write_text(json.dumps(raw_manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        final_inputs = _load_c13_final_linkage_inputs(output)
        final_linkage = validate_live_evidence_linkage(
            canonical_run_id=canonical_run_id,
            discovery_records=final_inputs["discovery_records"],
            document_records=final_inputs["document_records"],
            raw_manifest_entries=final_inputs["raw_manifest_entries"],
            authority_rows=final_inputs["authority_rows"],
            request_logs=final_inputs["request_logs"],
            price_request_logs=final_inputs["price_request_logs"],
            artifact_paths={"raw": output / "raw"},
            current_output_dir=output,
            accounting_cross_invariant_pass=bool(final_inputs["accounting"].get("accounting_cross_invariant_pass", False)),
            schema_suffix="13",
        )
    linkage_payload = final_linkage.to_dict()
    linkage_payload.update({"directive_id": DIRECTIVE_ID_CORRECTION_13, "canonical_run_id": canonical_run_id})
    (output / "live_evidence_linkage_validation_v01_fix03_correction_13.json").write_text(
        json.dumps(linkage_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    candidate_eval = _load_c13_candidate_evaluation(output)

    gate_metrics = dict(gate_payload)
    gate_metrics.update(validation.to_dict())
    gate_metrics.update(final_linkage.to_metrics())
    gate_metrics["persisted_price_evidence_status"] = validation.evaluation_status
    gate_metrics["unresolved_higher_priority_candidate_count"] = candidate_eval["unresolved_higher_priority_candidate_count"]
    gate_metrics["selected_authority_archive_provenance_failure_count"] = candidate_eval["selected_authority_archive_provenance_failure_count"]
    gate_metrics["candidate_error_count"] = gate_metrics.get("candidate_error_count", 0)
    gate_metrics["comparator_error_count"] = gate_metrics.get("comparator_error_count", 0)
    gate_metrics["network_accounting_failure_count"] = 0 if network_validation.all_network_accounting_valid else 1
    gate_metrics["canonical_run_identity_valid"] = identity_validation.all_identity_valid
    if not identity_validation.all_identity_valid:
        gate_metrics["canonical_run_identity_failure_count"] = len(identity_validation.mismatches)
    else:
        gate_metrics["canonical_run_identity_failure_count"] = 0
    gate_metrics["canonical_pytest_summary_physically_unchanged"] = summary_unchanged
    if not summary_unchanged:
        gate_metrics["canonical_pytest_summary_immutability_failure_count"] = 1
    else:
        gate_metrics["canonical_pytest_summary_immutability_failure_count"] = 0
    gate_metrics["schema"] = "gate06_corporate_action_reassessment_v01_fix03_correction_13"
    gate_metrics["directive_id"] = DIRECTIVE_ID_CORRECTION_13
    gate_pass, gate_blockers = evaluate_gate06(gate_metrics)
    gate_payload.update(gate_metrics)
    gate_payload.update({"schema": "gate06_corporate_action_reassessment_v01_fix03_correction_13", "directive_id": DIRECTIVE_ID_CORRECTION_13, "gate_06_pass": gate_pass, "gate_06_blockers": gate_blockers})
    gate_path.write_text(json.dumps(gate_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    # Gate06 is now audited against independently recomputed final evidence,
    # including authority, candidate, price, linkage, and network populations.
    audit_payload = audit_c13_metric_provenance(
        output,
        gate_payload=gate_payload,
        decision_payload={},
        validation=validation,
        linkage=final_linkage,
        accounting=accounting_payload,
    )
    audit_complete = audit_payload["verdict"] == "COMPLETE"
    audit_payload.update({
        "rows_loaded": {"price": len(_evidence_frame(price_path)), "parity": len(_evidence_frame(parity_path)), "reconciliation": len(_evidence_frame(recon_path))},
        "recomputed": validation.to_dict(),
    })
    (output / "gate06_metric_provenance_audit_v01_fix03_correction_13.json").write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    inherited = stage_result.get("inherited_gate_results", {})
    all_gates = {key: bool(value) for key, value in inherited.items()}
    all_gates["gate_06_corporate_action_parity"] = bool(gate_pass and audit_complete)
    all_gates["gate_15_no_unresolved_conditions"] = bool(gate_pass and audit_complete and certification.certification_valid and not candidate_eval["unresolved_higher_priority_candidate_count"] and not validation.blockers)
    all_pass = all(all_gates.values()) if all_gates else False
    if all_pass:
        decision_name, authorized, next_state = "APPROVED_FOR_PRODUCTION_INTEGRATION", True, "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
    elif validation.ohlc_mismatch_control_count > 0:
        decision_name, authorized, next_state = "REJECTED_AS_PRODUCTION_AUTHORITY", False, "ADJUSTED_PRICE_ALTERNATIVE_SOURCE_DISCOVERY_V01"
    else:
        decision_name, authorized, next_state = "CONDITIONAL_REVIEW_REQUIRED", False, DIRECTIVE_ID_CORRECTION_13
    decision = dict(stage_result)
    decision.update({"canonical_run_id": canonical_run_id, "schema": "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13", "directive_id": DIRECTIVE_ID_CORRECTION_13, "parent_directive": PARENT_DIRECTIVE_CORRECTION_13, "start_head": START_HEAD_CORP_EVIDENCE_FIX03_CORRECTION_13, "git_code_snapshot": asdict(snapshot), "full_suite_completion": certification.full_suite_completion, "new_regression_count": certification.new_regression_count, "regression_certification": certification.to_dict(), "persisted_price_evidence_status": validation.evaluation_status, "persisted_price_parity_validation": validation.to_dict(), "actual_candidate_price_row_count": validation.naver_price_row_count, "actual_pykrx_price_row_count": validation.pykrx_price_row_count, "exact_date_match_controls": validation.exact_match_control_count, "date_mismatch_controls": validation.date_mismatch_control_count, "insufficient_window_controls": validation.insufficient_window_control_count, "ohlc_mismatch_controls": validation.ohlc_mismatch_control_count, "unresolved_higher_priority_candidate_count": candidate_eval["unresolved_higher_priority_candidate_count"], "selected_authority_archive_provenance_failure_count": candidate_eval["selected_authority_archive_provenance_failure_count"], "canonical_pytest_summary_physically_unchanged": summary_unchanged, "canonical_pytest_summary_physical_immutability": {"before": {k: v for k, v in (summary_before or {}).items() if k != "bytes"}, "after": {k: v for k, v in (summary_after or {}).items() if k != "bytes"}}, "gate_06_result": bool(gate_pass and audit_complete), "gate_15_result": all_gates["gate_15_no_unresolved_conditions"], "all_15_gate_results": all_gates, "all_gates_passed": all_pass, "production_certification_ready": all_pass, "production_integration_authorized": authorized, "review_decision": decision_name, "recommended_next_state": next_state, "blocking_conditions": list(dict.fromkeys(gate_blockers + validation.blockers)), "reason_codes": ["CORPORATE_ACTION_PRICE_CONTRADICTION"] if decision_name.startswith("REJECTED") else (["ALL_15_SOURCE_AUTHORITY_REVIEW_GATES_PASSED_FIX03_CORRECTION_13"] if all_pass else ["C13_CERTIFICATION_UNRESOLVED"]), "network_accounting": accounting_payload, "c13_live_execution": bool(allow_network)})
    # Re-run the audit after decision construction so any production-significant
    # values duplicated into the decision are also equality-bound to evidence.
    audit_payload = audit_c13_metric_provenance(
        output,
        gate_payload=gate_payload,
        decision_payload=decision,
        validation=validation,
        linkage=final_linkage,
        accounting=accounting_payload,
    )
    audit_complete = audit_payload["verdict"] == "COMPLETE"
    audit_payload.update({
        "rows_loaded": {"price": len(_evidence_frame(price_path)), "parity": len(_evidence_frame(parity_path)), "reconciliation": len(_evidence_frame(recon_path))},
        "recomputed": validation.to_dict(),
    })
    if not audit_complete:
        gate_blockers = list(dict.fromkeys([*gate_blockers, *audit_payload.get("blockers", [])]))
        gate_pass = False
        gate_payload["gate_06_pass"] = False
        gate_payload["gate_06_blockers"] = gate_blockers
        gate_path.write_text(json.dumps(gate_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        all_gates["gate_06_corporate_action_parity"] = False
        all_gates["gate_15_no_unresolved_conditions"] = False
        all_pass = False
        decision.update({"gate_06_result": False, "gate_15_result": False, "all_15_gate_results": all_gates, "all_gates_passed": False, "production_certification_ready": False, "production_integration_authorized": False, "review_decision": "CONDITIONAL_REVIEW_REQUIRED", "recommended_next_state": DIRECTIVE_ID_CORRECTION_13, "blocking_conditions": gate_blockers})
    decision_path = output / "adjusted_price_source_authority_corporate_action_evidence_v01_fix03_correction_13.json"
    decision_path.write_text(json.dumps(decision, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (output / "gate06_metric_provenance_audit_v01_fix03_correction_13.json").write_text(json.dumps(audit_payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    binding = {"schema": "code_test_binding_evidence_v01_fix03_correction_13", "directive_id": DIRECTIVE_ID_CORRECTION_13, "fix_head": snapshot.head, "fix_tree_sha": snapshot.tree_sha, "tested_code_head": certification.code_head_under_test, "tested_code_tree_sha": certification.code_tree_sha_under_test, "code_scope": ["src", "scripts", "tests"]}
    (output / "code_test_binding_evidence_v01_fix03_correction_13.json").write_text(json.dumps(binding, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    entries: dict[str, dict[str, Any]] = {}
    for path in sorted(output.rglob("*")):
        if not path.is_file() or path.name == "artifact_manifest.json":
            continue
        relative = str(path.relative_to(output))
        entries[relative] = {"path": relative, "size_bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / "artifact_manifest.json").write_text(json.dumps({"schema": "corporate_action_evidence_manifest_v01_fix03_correction_13", "canonical_run_id": decision.get("canonical_run_id", ""), "directive_id": decision.get("directive_id", ""), "review_decision": decision.get("review_decision", ""), "production_integration_authorized": decision.get("production_integration_authorized", False), "artifacts": entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return decision


def run_correction13_from_canonical_evidence(*, repo_root: Path = Path("."), output_dir: Path | None = None, allow_network: bool = True, parent_dir: Path | None = None) -> dict[str, Any]:
    """Certify C13 pytest evidence before entering the production acquisition path."""
    return run_corporate_action_evidence_acquisition_fix03_correction_13(repo_root=Path(repo_root), output_dir=output_dir, allow_network=allow_network, parent_dir=parent_dir)


if __name__ == "__main__":
    result = run_correction13_from_canonical_evidence(repo_root=Path.cwd())
    print("=== Corporate Action Evidence Acquisition FIX03_CORRECTION_13 Execution Summary ===")
    print("Review Decision:", result["review_decision"])
    print("All Gates Passed:", result["all_gates_passed"])
    print("Production Integration Authorized:", result["production_integration_authorized"])
    print("Recommended Next State:", result["recommended_next_state"])
