"""Validation-only mapping of native sector codes to official KRX index rows.

The script deliberately does not replace the production sector provider.  It
uses a bounded, sequential PyKRX probe as a reference and compares its OHLC
fingerprints with cached KRX Open API market snapshots.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import time
from collections import Counter, defaultdict
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError

from trend_scanner.data.index_price_provider import KOSDAQ_SECTOR_CODES, KOSPI_SECTOR_CODES
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiClient,
    KrxOpenApiRateLimitError,
    KrxOpenApiResponse,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/data/krx_openapi/index_mapping/v01"
RAW_DIR = ARTIFACT_DIR / "raw_samples"
WORK_ID = "KRX_INDEX_SERIES_MAPPING_V01"
EXPECTED_START_HEAD = "de82de0d4cb42e7b83e51792c94f94b87d8a8c94"
PRIMARY_DATES = ("2026-07-24", "2026-07-31", "2026-08-07", "2026-08-14", "2026-08-20", "2026-08-21")
PYKRX_START = "2026-06-01"
PYKRX_END = "2026-08-21"
MAX_KRX_ATTEMPTS = 30
PYKRX_DELAY_SECONDS = 0.75
PYKRX_MAX_OPERATIONS = 60
MIN_COMMON_DATES = 3
OHLC_FIELDS = ("open", "high", "low", "close")

KRX_SERVICES: tuple[dict[str, str], ...] = (
    {"service_name": "kospi_index_daily", "api_id": "kospi_dd_trd", "endpoint": "/idx/kospi_dd_trd", "idx_class": "KOSPI"},
    {"service_name": "kosdaq_index_daily", "api_id": "kosdaq_dd_trd", "endpoint": "/idx/kosdaq_dd_trd", "idx_class": "KOSDAQ"},
    {"service_name": "krx_index_daily", "api_id": "krx_dd_trd", "endpoint": "/idx/krx_dd_trd", "idx_class": "KRX"},
)
SERVICE_BY_NAME = {item["service_name"]: item for item in KRX_SERVICES}
MAPPING_STATUSES = (
    "EXACT_MARKET_SERIES_MATCH", "ROUNDING_ONLY_MARKET_SERIES_MATCH", "INACTIVE_OR_LEGACY_CODE",
    "PYKRX_REFERENCE_UNAVAILABLE", "AMBIGUOUS_PRICE_SIGNATURE", "NO_MARKET_SERIES_MATCH",
    "INSUFFICIENT_COMMON_DATES",
)
DUPLICATE_STATUSES = (
    "EXACT_CROSS_API_DUPLICATE", "SAME_NAME_DIFFERENT_SERIES", "PARTIAL_CROSS_API_EVIDENCE", "UNKNOWN_CROSS_API_RELATION",
)


def normalize_decimal(value: Any) -> Decimal | None:
    """Canonical decimal normalization; no arbitrary tolerance is applied."""

    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "—", "nan", "NaN", "None", "null"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def decimal_text(value: Decimal | None) -> str:
    value = normalize_decimal(value)
    if value is None:
        return ""
    return format(value, "f")


def date_key(value: Any) -> str:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    return text[:8] if len(text) >= 8 else text


def build_signature(row: Mapping[str, Any], *, source: str = "") -> dict[str, Decimal | None | str]:
    """Build the comparable OHLC signature for either provider."""

    return {
        "source": source,
        "open": normalize_decimal(row.get("open", row.get("OPNPRC_IDX", row.get("시가")))),
        "high": normalize_decimal(row.get("high", row.get("HGPRC_IDX", row.get("고가")))),
        "low": normalize_decimal(row.get("low", row.get("LWPRC_IDX", row.get("저가")))),
        "close": normalize_decimal(row.get("close", row.get("CLSPRC_IDX", row.get("종가")))),
    }


def signature_values(signature: Mapping[str, Any]) -> dict[str, str]:
    """Convert a canonical signature to JSON/CSV-safe decimal strings."""

    return {field: decimal_text(signature.get(field)) for field in OHLC_FIELDS}


def compare_signatures(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    matches = {field: normalize_decimal(left.get(field)) == normalize_decimal(right.get(field)) and normalize_decimal(left.get(field)) is not None for field in OHLC_FIELDS}
    differences = {field: (normalize_decimal(left.get(field)), normalize_decimal(right.get(field))) for field in OHLC_FIELDS if not matches[field]}
    rounding_fields = {field for field, (lhs, rhs) in differences.items() if lhs is not None and rhs is not None and abs(lhs - rhs) == Decimal("0.01")}
    return {"matches": matches, "exact_field_match_count": sum(matches.values()), "difference_fields": sorted(differences), "rounding_difference_count": len(rounding_fields), "rounding_only": bool(differences) and rounding_fields == set(differences)}


def classify_candidate(common_date_count: int, compared_field_count: int, exact_field_match_count: int, rounding_difference_count: int, candidate_count: int) -> str:
    if common_date_count < MIN_COMMON_DATES:
        return "INSUFFICIENT_COMMON_DATES"
    if candidate_count > 1 and exact_field_match_count == common_date_count * len(OHLC_FIELDS):
        return "AMBIGUOUS_PRICE_SIGNATURE"
    if exact_field_match_count == common_date_count * len(OHLC_FIELDS):
        return "EXACT_MARKET_SERIES_MATCH"
    if compared_field_count == common_date_count * len(OHLC_FIELDS) and rounding_difference_count > 0 and exact_field_match_count + rounding_difference_count == compared_field_count:
        return "ROUNDING_ONLY_MARKET_SERIES_MATCH"
    return "NO_MARKET_SERIES_MATCH"


def classify_duplicate(common_date_count: int, compared_field_count: int, exact_field_match_count: int) -> str:
    if common_date_count == 0:
        return "UNKNOWN_CROSS_API_RELATION"
    if common_date_count < len(PRIMARY_DATES) or compared_field_count < common_date_count * len(OHLC_FIELDS):
        return "PARTIAL_CROSS_API_EVIDENCE"
    if exact_field_match_count == compared_field_count:
        return "EXACT_CROSS_API_DUPLICATE"
    return "SAME_NAME_DIFFERENT_SERIES"


def readiness_gate(counters: Mapping[str, int]) -> bool:
    required_zero = (
        "active_ambiguous_count", "active_no_match_count", "active_reference_unavailable_count",
        "active_insufficient_common_dates_count", "krx_access_fail_count", "quota_counter_mismatch_count",
        "request_audit_mismatch_count", "secret_occurrence_count", "validation_source_head_mismatch_count",
    )
    return counters.get("sector_code_total_count") == 46 and all(int(counters.get(key, 0)) == 0 for key in required_zero)


def internal_sector_names() -> dict[str, str]:
    path = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/sector_mapping_20260814.csv"
    result: dict[str, str] = {}
    if not path.exists():
        return result
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("sector_code", "")).strip()
            name = str(row.get("sector_name", "")).strip()
            if code and name and code not in result:
                result[code] = name
    return result


def read_env_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""


def load_auth_key() -> str:
    value = os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
    if value:
        return value
    for path in (ROOT / ".env", ROOT.parent / "env.md"):
        value = read_env_value(path, "KRX_OPEN_API_AUTH_KEY").strip()
        if value:
            return value
    return ""


def load_krx_operator_credentials() -> None:
    """Load PyKRX credentials silently; never serialize the values."""

    for name in ("KRX_ID", "KRX_PW"):
        if os.getenv(name, "").strip():
            continue
        for path in (ROOT / ".env", ROOT.parent / "env.md"):
            value = read_env_value(path, name).strip()
            if value:
                os.environ[name] = value
                break


def git_sha(ref: str) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def safe_write_json(path: Path, value: Any, secret: str = "") -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if secret and secret in serialized:
        raise ValueError("secret detected in mapping artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def scan_secret(secret: str) -> dict[str, int]:
    if not secret:
        return {"secret_occurrence_count": 0, "scanned_file_count": 0}
    try:
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    except (OSError, subprocess.CalledProcessError):
        paths = []
    paths.extend(str(path.relative_to(ROOT)) for path in ARTIFACT_DIR.rglob("*") if path.is_file())
    count = scanned = 0
    for raw_path in sorted(set(paths)):
        if not raw_path or raw_path == ".env" or raw_path.endswith("/.env"):
            continue
        path = ROOT / raw_path
        if path.is_file():
            scanned += 1
            try:
                count += path.read_text(encoding="utf-8", errors="ignore").count(secret)
            except OSError:
                pass
    return {"secret_occurrence_count": count, "scanned_file_count": scanned}


def _response_status(response: KrxOpenApiResponse | None) -> str:
    if response is None:
        return "NOT_REQUESTED_OR_ERROR"
    if response.http_status != 200:
        return f"HTTP_{response.http_status}"
    if response.records_key != "OutBlock_1":
        return "HTTP_200_NO_OUTBLOCK"
    return "HTTP_200_EMPTY" if response.record_count == 0 else "HTTP_200_RECORDS"


def _krx_row_signature(row: Mapping[str, Any]) -> dict[str, Any]:
    return build_signature(row, source="KRX_OPEN_API")


def _fetch_pykrx_series(code: str, *, start: str, end: str, delay_seconds: float, state: dict[str, Any]) -> dict[str, Any]:
    """One bounded range call per code with at most one retry."""

    attempts = 0
    last_error: str | None = None
    for attempt in range(2):
        if state.get("halted"):
            return {"code": code, "status": "PYKRX_REFERENCE_UNAVAILABLE", "rows": {}, "attempts": attempts, "error": "probe halted after suspected block"}
        if delay_seconds > 0:
            time.sleep(delay_seconds)
        attempts += 1
        state["network_operations"] = int(state.get("network_operations", 0)) + 1
        capture = StringIO()
        try:
            with redirect_stdout(capture), redirect_stderr(capture):
                from pykrx import stock
                frame = stock.get_index_ohlcv_by_date(start.replace("-", ""), end.replace("-", ""), code)
            if frame is None or getattr(frame, "empty", True):
                last_error = "EMPTY_DATAFRAME"
                state["consecutive_empty"] = int(state.get("consecutive_empty", 0)) + 1
                if state["consecutive_empty"] >= 3:
                    state["halted"] = True
                    state["suspected_block_events"] = int(state.get("suspected_block_events", 0)) + 1
                    return {"code": code, "status": "PYKRX_SUSPECTED_THROTTLE_OR_BLOCK", "rows": {}, "attempts": attempts, "error": last_error}
                continue
            state["consecutive_empty"] = 0
            result: dict[str, dict[str, Any]] = {}
            for index, row in frame.iterrows():
                try:
                    date = index.strftime("%Y%m%d")
                except AttributeError:
                    date = date_key(index)
                result[date] = {field: normalize_decimal(row.get(column)) for field, column in (("open", "시가"), ("high", "고가"), ("low", "저가"), ("close", "종가"))}
            state["consecutive_errors"] = 0
            return {"code": code, "status": "PASS", "rows": result, "attempts": attempts, "error": None}
        except Exception as exc:  # PyKRX backend/parser errors are evidence, not silent empty data.
            last_error = type(exc).__name__
            state["consecutive_errors"] = int(state.get("consecutive_errors", 0)) + 1
            if state["consecutive_errors"] >= 3:
                state["halted"] = True
                state["suspected_block_events"] = int(state.get("suspected_block_events", 0)) + 1
                return {"code": code, "status": "PYKRX_SUSPECTED_THROTTLE_OR_BLOCK", "rows": {}, "attempts": attempts, "error": last_error}
    return {"code": code, "status": "PYKRX_REFERENCE_UNAVAILABLE", "rows": {}, "attempts": attempts, "error": last_error}


def _snapshot_rows(responses: Mapping[tuple[str, str], KrxOpenApiResponse | None], service_name: str, date: str) -> list[dict[str, Any]]:
    response = responses.get((service_name, date))
    return list(response.records if response else ())


def _candidate_map(rows: Iterable[Mapping[str, Any]], idx_class: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        if str(row.get("IDX_CLSS", "")) != idx_class:
            continue
        name = str(row.get("IDX_NM", "")).strip()
        if not name:
            continue
        result[name] = row
    return result


def _duplicate_snapshot_rows(responses: Mapping[tuple[str, str], KrxOpenApiResponse | None]) -> int:
    """Count duplicate (source, date, class, name) rows before mapping."""

    duplicates = 0
    for service in KRX_SERVICES:
        for date in PRIMARY_DATES:
            seen: set[tuple[str, str, str, str]] = set()
            for row in _snapshot_rows(responses, service["service_name"], date):
                key = (service["api_id"], date, str(row.get("IDX_CLSS", "")), str(row.get("IDX_NM", "")))
                if key in seen:
                    duplicates += 1
                seen.add(key)
    return duplicates


def _mapping_evidence(code: str, market: str, py_rows: Mapping[str, Mapping[str, Any]], candidates_by_date: Mapping[str, Mapping[str, Mapping[str, Any]]], internal_name: str | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    candidate_names = sorted({name for rows in candidates_by_date.values() for name in rows})
    candidate_details = []
    for name in candidate_names:
        comparisons = []
        for date in PRIMARY_DATES:
            py = py_rows.get(date.replace("-", ""))
            krx = candidates_by_date.get(date, {}).get(name)
            if not py or not krx:
                continue
            comparison = compare_signatures(py, _krx_row_signature(krx))
            comparisons.append({"date": date, "pykrx": signature_values(py), "krx": signature_values(_krx_row_signature(krx)), **comparison})
        common = len(comparisons)
        compared = sum(len(item["matches"]) for item in comparisons)
        exact = sum(int(item["exact_field_match_count"]) for item in comparisons)
        rounding = sum(int(item["rounding_difference_count"]) for item in comparisons)
        status = classify_candidate(common, compared, exact, rounding, 1)
        candidate_details.append({"official_idx_name": name, "source_api": "kospi_dd_trd" if market == "KOSPI" else "kosdaq_dd_trd", "official_idx_class": market, "common_date_count": common, "compared_field_count": compared, "exact_field_match_count": exact, "rounding_difference_count": rounding, "candidate_count": len(candidate_names), "status": status, "comparisons": comparisons})
    exact_candidates = [item for item in candidate_details if item["status"] == "EXACT_MARKET_SERIES_MATCH"]
    rounding_candidates = [item for item in candidate_details if item["status"] == "ROUNDING_ONLY_MARKET_SERIES_MATCH"]
    common_max = max((item["common_date_count"] for item in candidate_details), default=0)
    active = any(date.replace("-", "") in py_rows for date in PRIMARY_DATES[-3:])
    if not py_rows:
        status = "PYKRX_REFERENCE_UNAVAILABLE"
        chosen = None
    elif len(exact_candidates) > 1:
        status = "AMBIGUOUS_PRICE_SIGNATURE"
        chosen = None
    elif len(exact_candidates) == 1:
        status = "EXACT_MARKET_SERIES_MATCH"
        chosen = exact_candidates[0]
    elif len(rounding_candidates) == 1:
        status = "ROUNDING_ONLY_MARKET_SERIES_MATCH"
        chosen = rounding_candidates[0]
    elif active and common_max < MIN_COMMON_DATES:
        status = "INSUFFICIENT_COMMON_DATES"
        chosen = None
    elif not active and py_rows:
        status = "INACTIVE_OR_LEGACY_CODE"
        chosen = None
    else:
        status = "NO_MARKET_SERIES_MATCH"
        chosen = None
    official_name = chosen.get("official_idx_name") if chosen else None
    name_warning = bool(chosen and internal_name and re.sub(r"[^가-힣A-Za-z0-9]", "", internal_name) not in re.sub(r"[^가-힣A-Za-z0-9]", "", official_name or "") and re.sub(r"[^가-힣A-Za-z0-9]", "", official_name or "") not in re.sub(r"[^가-힣A-Za-z0-9]", "", internal_name))
    summary = {"market": market, "sector_code": code, "internal_sector_name": internal_name, "official_idx_name": official_name, "source_api": chosen.get("source_api") if chosen else ("kospi_dd_trd" if market == "KOSPI" else "kosdaq_dd_trd"), "official_idx_class": market if chosen else None, "common_date_count": chosen.get("common_date_count", common_max) if chosen else common_max, "ohlc_compared_field_count": chosen.get("compared_field_count", 0) if chosen else 0, "exact_field_match_count": chosen.get("exact_field_match_count", 0) if chosen else 0, "rounding_difference_count": chosen.get("rounding_difference_count", 0) if chosen else 0, "candidate_count": len(candidate_names), "mapping_status": status, "evidence_dates": [item["date"] for item in chosen.get("comparisons", [])] if chosen else [], "active_reference_code": active, "name_semantic_warning": name_warning}
    detail = {"summary": summary, "candidate_evidence": candidate_details}
    parity_rows = []
    if chosen:
        common_count = len(chosen.get("comparisons", []))
        for item in chosen.get("comparisons", []):
            parity_rows.append({"market": market, "sector_code": code, "internal_sector_name": internal_name, "official_idx_name": official_name, "source_api": summary["source_api"], "mapping_status": status, "common_date_count": common_count, "date": item["date"], "pykrx_open": decimal_text(item["pykrx"].get("open")), "pykrx_high": decimal_text(item["pykrx"].get("high")), "pykrx_low": decimal_text(item["pykrx"].get("low")), "pykrx_close": decimal_text(item["pykrx"].get("close")), "krx_open": decimal_text(item["krx"].get("open")), "krx_high": decimal_text(item["krx"].get("high")), "krx_low": decimal_text(item["krx"].get("low")), "krx_close": decimal_text(item["krx"].get("close")), "open_match": item["matches"]["open"], "high_match": item["matches"]["high"], "low_match": item["matches"]["low"], "close_match": item["matches"]["close"]})
    return detail, parity_rows


def _duplicate_evidence(responses: Mapping[tuple[str, str], KrxOpenApiResponse | None]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_rows: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    for service in KRX_SERVICES:
        for date in PRIMARY_DATES:
            rows = _snapshot_rows(responses, service["service_name"], date)
            all_rows[(service["service_name"], date)] = {str(row.get("IDX_NM", "")): row for row in rows if row.get("IDX_NM")}
    names_by_service: dict[str, set[str]] = defaultdict(set)
    for (service_name, _date), rows in all_rows.items():
        names_by_service[service_name].update(rows)
    names = sorted({name for values in names_by_service.values() for name in values})
    pairs = []
    detail_rows = []
    for name in names:
        services = sorted(service for service, values in names_by_service.items() if name in values)
        for left_index, left_service in enumerate(services):
            for right_service in services[left_index + 1:]:
                comparisons = []
                for date in PRIMARY_DATES:
                    left = all_rows[(left_service, date)].get(name)
                    right = all_rows[(right_service, date)].get(name)
                    if not left or not right:
                        continue
                    comparison = compare_signatures(_krx_row_signature(left), _krx_row_signature(right))
                    comparisons.append({"date": date, "left": signature_values(_krx_row_signature(left)), "right": signature_values(_krx_row_signature(right)), **comparison})
                common = len(comparisons)
                compared = sum(len(item["matches"]) for item in comparisons)
                exact = sum(int(item["exact_field_match_count"]) for item in comparisons)
                status = classify_duplicate(common, compared, exact)
                pair = {"idx_name": name, "left_source_api": SERVICE_BY_NAME[left_service]["api_id"], "right_source_api": SERVICE_BY_NAME[right_service]["api_id"], "common_date_count": common, "compared_field_count": compared, "exact_field_match_count": exact, "classification": status, "evidence_dates": [item["date"] for item in comparisons], "canonical_authority_candidate": SERVICE_BY_NAME[left_service]["api_id"] if status == "EXACT_CROSS_API_DUPLICATE" and left_service != "krx_index_daily" else SERVICE_BY_NAME[right_service]["api_id"] if status == "EXACT_CROSS_API_DUPLICATE" else "SOURCE_QUALIFIED_IDENTITY_REQUIRED"}
                pairs.append(pair)
                for item in comparisons:
                    detail_rows.append({"idx_name": name, "left_source_api": pair["left_source_api"], "right_source_api": pair["right_source_api"], "date": item["date"], "classification": status, "left_open": decimal_text(item["left"].get("open")), "left_high": decimal_text(item["left"].get("high")), "left_low": decimal_text(item["left"].get("low")), "left_close": decimal_text(item["left"].get("close")), "right_open": decimal_text(item["right"].get("open")), "right_high": decimal_text(item["right"].get("high")), "right_low": decimal_text(item["right"].get("low")), "right_close": decimal_text(item["right"].get("close")), "open_match": item["matches"]["open"], "high_match": item["matches"]["high"], "low_match": item["matches"]["low"], "close_match": item["matches"]["close"]})
    return pairs, detail_rows


def run_validation() -> dict[str, Any]:
    start_head = git_sha("origin/main")
    if start_head == "UNKNOWN":
        start_head = git_sha("HEAD")
    implementation_head = git_sha("HEAD")
    secret = load_auth_key()
    if not secret:
        status = "BLOCKED_KRX_INDEX_ACCESS"
        safe_write_json(ARTIFACT_DIR / "index_mapping_v01_manifest.json", {"work_id": WORK_ID, "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "status": status, "secret_occurrence_count": 0})
        return {"status": status, "request_count": 0, "pykrx_operations": 0}

    quota = LocalKrxOpenApiQuota()
    client = KrxOpenApiClient(secret, max_requests=MAX_KRX_ATTEMPTS, max_transient_retries=2, quota=quota)
    responses: dict[tuple[str, str], KrxOpenApiResponse | None] = {}
    failures: list[dict[str, Any]] = []
    halted = False

    def fetch(service: Mapping[str, str], date: str) -> KrxOpenApiResponse | None:
        nonlocal halted
        key = (service["service_name"], date)
        if halted:
            responses[key] = None
            return None
        try:
            response = client.fetch(service["endpoint"], date, quota_endpoint_key=service["api_id"])
        except KrxOpenApiAuthorizationError as exc:
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_INDEX_ACCESS", "error": str(exc)})
            halted = True
            response = None
        except KrxOpenApiRateLimitError as exc:
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_RATE_LIMIT", "error": str(exc)})
            halted = True
            response = None
        except KrxOpenApiBudgetError as exc:
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_REQUEST_BUDGET", "error": str(exc)})
            halted = True
            response = None
        except KrxOpenApiQuotaExceeded as exc:
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_QUOTA", "error": str(exc)})
            halted = True
            response = None
        responses[key] = response
        if response and secret in json.dumps(response.payload, ensure_ascii=False):
            raise ValueError("secret detected in KRX response")
        return response

    for date in PRIMARY_DATES:
        for service in KRX_SERVICES:
            fetch(service, date)

    py_state: dict[str, Any] = {"network_operations": 0, "consecutive_empty": 0, "consecutive_errors": 0, "halted": False, "suspected_block_events": 0}
    load_krx_operator_credentials()
    names = internal_sector_names()
    code_specs = [("KOSPI", code) for code in KOSPI_SECTOR_CODES] + [("KOSDAQ", code) for code in KOSDAQ_SECTOR_CODES]
    py_results: dict[str, dict[str, Any]] = {}
    for market, code in code_specs:
        py_results[code] = _fetch_pykrx_series(code, start=PYKRX_START, end=PYKRX_END, delay_seconds=PYKRX_DELAY_SECONDS, state=py_state)
        if py_state["network_operations"] > PYKRX_MAX_OPERATIONS:
            py_state["halted"] = True
            py_state["suspected_block_events"] += 1
            break
    for market, code in code_specs:
        if code not in py_results:
            py_results[code] = {"code": code, "status": "PYKRX_REFERENCE_UNAVAILABLE", "rows": {}, "attempts": 0, "error": "probe halted before this code"}

    mapping_details: list[dict[str, Any]] = []
    parity_rows: list[dict[str, Any]] = []
    for market, code in code_specs:
        py = py_results[code]
        candidates_by_date = {}
        service_name = "kospi_index_daily" if market == "KOSPI" else "kosdaq_index_daily"
        for date in PRIMARY_DATES:
            candidates_by_date[date] = _candidate_map(_snapshot_rows(responses, service_name, date), market)
        detail, rows = _mapping_evidence(code, market, py.get("rows", {}), candidates_by_date, names.get(code))
        detail["pykrx_status"] = py.get("status")
        detail["pykrx_attempts"] = py.get("attempts", 0)
        detail["pykrx_error"] = py.get("error")
        mapping_details.append(detail)
        parity_rows.extend(rows)

    duplicate_pairs, duplicate_detail_rows = _duplicate_evidence(responses)
    duplicate_snapshot_row_count = _duplicate_snapshot_rows(responses)
    krx_sector_rows = []
    for date in PRIMARY_DATES:
        for row in _snapshot_rows(responses, "krx_index_daily", date):
            if str(row.get("IDX_CLSS", "")) == "KRX" and str(row.get("IDX_NM", "")).strip() and any(token in str(row.get("IDX_NM")) for token in ("자동차", "반도체", "헬스케어", "은행", "에너지화학", "철강", "방송통신", "건설", "증권", "기계장비", "보험", "운송", "경기소비재", "필수소비재", "정보기술", "유틸리티", "자유소비재", "산업재", "소재", "커뮤니케이션서비스", "금융")):
                krx_sector_rows.append(row)
    unique_taxonomy: dict[str, dict[str, Any]] = {}
    for row in krx_sector_rows:
        unique_taxonomy[str(row.get("IDX_NM"))] = row
    taxonomy_rows = [{"official_idx_name": name, "source_api": "krx_dd_trd", "official_idx_class": "KRX", "classification": "SECTOR_INDUSTRY", "has_close": normalize_decimal(row.get("CLSPRC_IDX")) is not None} for name, row in sorted(unique_taxonomy.items())]
    exact_taxonomy_count = sum(1 for row in taxonomy_rows if row["classification"] == "EXACT_CROSS_TAXONOMY_EQUIVALENT")
    relation_rows = [{"official_idx_name": row["official_idx_name"], "native_match_names": [], "relation": "DISTINCT_KRX_TAXONOMY", "reason": "KRX-branded sector series is source-qualified and not substituted by name similarity."} for row in taxonomy_rows]

    mapping_status_counts = Counter(item["summary"]["mapping_status"] for item in mapping_details)
    active_items = [item["summary"] for item in mapping_details if item["summary"]["active_reference_code"]]
    counters = {
        "sector_code_total_count": len(code_specs), "active_sector_code_count": len(active_items), "exact_mapping_count": mapping_status_counts["EXACT_MARKET_SERIES_MATCH"], "rounding_only_mapping_count": mapping_status_counts["ROUNDING_ONLY_MARKET_SERIES_MATCH"], "inactive_legacy_count": mapping_status_counts["INACTIVE_OR_LEGACY_CODE"], "active_ambiguous_count": sum(item["mapping_status"] == "AMBIGUOUS_PRICE_SIGNATURE" for item in active_items), "active_no_match_count": sum(item["mapping_status"] == "NO_MARKET_SERIES_MATCH" for item in active_items), "active_reference_unavailable_count": sum(item["mapping_status"] == "PYKRX_REFERENCE_UNAVAILABLE" for item in active_items), "active_insufficient_common_dates_count": sum(item["mapping_status"] == "INSUFFICIENT_COMMON_DATES" for item in active_items), "cross_api_duplicate_pair_count": len(duplicate_pairs), "cross_api_exact_duplicate_count": sum(item["classification"] == "EXACT_CROSS_API_DUPLICATE" for item in duplicate_pairs), "cross_api_same_name_different_count": sum(item["classification"] == "SAME_NAME_DIFFERENT_SERIES" for item in duplicate_pairs), "cross_api_partial_count": sum(item["classification"] == "PARTIAL_CROSS_API_EVIDENCE" for item in duplicate_pairs), "cross_api_unknown_count": sum(item["classification"] == "UNKNOWN_CROSS_API_RELATION" for item in duplicate_pairs), "krx_access_fail_count": sum(not (responses.get((service["service_name"], date)) and responses[(service["service_name"], date)].http_status == 200) for date in PRIMARY_DATES for service in KRX_SERVICES), "quota_counter_mismatch_count": int(quota.get_usage()["global_total"] != client.request_count), "request_audit_mismatch_count": int(len(client.audit) != client.request_count), "secret_occurrence_count": 0, "validation_source_head_mismatch_count": int(implementation_head != git_sha("HEAD")), "duplicate_snapshot_row_count": duplicate_snapshot_row_count}
    secret_scan = scan_secret(secret)
    counters["secret_occurrence_count"] = secret_scan["secret_occurrence_count"]
    final_status = "READY_FOR_ARCHITECT_KRX_INDEX_SERIES_MAPPING_V01_REVIEW" if readiness_gate(counters) and duplicate_snapshot_row_count == 0 and not py_state.get("halted") and py_state.get("suspected_block_events", 0) == 0 else "BLOCKED_MORE_EVIDENCE_REQUIRED"
    if py_state.get("halted") or py_state.get("suspected_block_events", 0):
        final_status = "BLOCKED_PYKRX_REFERENCE_ACCESS"
    if failures and any(item["status"] == "BLOCKED_KRX_INDEX_ACCESS" for item in failures):
        final_status = "BLOCKED_KRX_INDEX_ACCESS"
    recommendation = "RECOMMEND_SECTOR_RS_KRX_MIGRATION" if final_status.startswith("READY") else "BLOCKED_ACTIVE_SECTOR_MAPPING" if counters["active_ambiguous_count"] or counters["active_no_match_count"] or counters["active_insufficient_common_dates_count"] else "BLOCKED_MORE_EVIDENCE_REQUIRED"
    usage = quota.get_usage()
    endpoint_contract = {"work_id": WORK_ID, "method": "GET", "auth_header": "AUTH_KEY", "date_parameter": "basDd", "date_format": "YYYYMMDD", "records_container": "OutBlock_1", "services": [{**service, "actual_endpoint": service["endpoint"]} for service in KRX_SERVICES]}
    pykrx_started_calls = sum(1 for item in py_results.values() if int(item.get("attempts", 0)) > 0)
    network_summary = {"work_id": WORK_ID, "fingerprint_dates": [{"requested_date": date, "actual_date": date, "status": {service["service_name"]: _response_status(responses.get((service["service_name"], date))) for service in KRX_SERVICES}} for date in PRIMARY_DATES], "krx_kospi_snapshot_requests": len(PRIMARY_DATES), "krx_kosdaq_snapshot_requests": len(PRIMARY_DATES), "krx_series_snapshot_requests": len(PRIMARY_DATES), "actual_http_attempts": client.request_count, "quota_recorded_attempts": usage["global_total"], "pykrx_primary_calls": pykrx_started_calls, "pykrx_retries": max(0, py_state["network_operations"] - pykrx_started_calls), "pykrx_total_network_operations": py_state["network_operations"], "pykrx_throttle_seconds": PYKRX_DELAY_SECONDS, "suspected_block_events": py_state.get("suspected_block_events", 0), "duplicate_snapshot_row_count": duplicate_snapshot_row_count, "failures": failures}
    safe_write_json(ARTIFACT_DIR / "index_mapping_v01_summary.json", {"work_id": WORK_ID, "status": final_status, "recommendation": recommendation, "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "counters": counters, "krx_sector_taxonomy_count": len(taxonomy_rows), "krx_sector_exact_equivalence_count": exact_taxonomy_count, "krx_distinct_taxonomy_count": len(taxonomy_rows) - exact_taxonomy_count, "pykrx_state": py_state, "fingerprint_dates": list(PRIMARY_DATES)}, secret)
    safe_write_json(ARTIFACT_DIR / "index_mapping_v01_manifest.json", {"work_id": WORK_ID, "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "end_head": None, "status": final_status, "recommendation": recommendation, "counters": counters, "secret_occurrence_count": secret_scan["secret_occurrence_count"]}, secret)
    write_csv(ARTIFACT_DIR / "sector_code_mapping.csv", ["market", "sector_code", "internal_sector_name", "official_idx_name", "source_api", "official_idx_class", "common_date_count", "ohlc_compared_field_count", "exact_field_match_count", "rounding_difference_count", "candidate_count", "mapping_status", "evidence_dates", "active_reference_code", "name_semantic_warning"], [{**item["summary"], "evidence_dates": ";".join(item["summary"]["evidence_dates"])} for item in mapping_details])
    safe_write_json(ARTIFACT_DIR / "sector_code_mapping_detail.json", {"work_id": WORK_ID, "mapping_statuses": list(MAPPING_STATUSES), "items": mapping_details}, secret)
    write_csv(ARTIFACT_DIR / "sector_price_parity.csv", ["market", "sector_code", "internal_sector_name", "official_idx_name", "source_api", "mapping_status", "common_date_count", "date", "pykrx_open", "pykrx_high", "pykrx_low", "pykrx_close", "krx_open", "krx_high", "krx_low", "krx_close", "open_match", "high_match", "low_match", "close_match"], parity_rows)
    safe_write_json(ARTIFACT_DIR / "sector_mapping_failures.json", {"work_id": WORK_ID, "items": [{"market": item["summary"]["market"], "sector_code": item["summary"]["sector_code"], "status": item["summary"]["mapping_status"], "pykrx_status": item.get("pykrx_status"), "pykrx_error": item.get("pykrx_error"), "candidate_evidence": item.get("candidate_evidence", [])} for item in mapping_details if item["summary"]["mapping_status"] not in {"EXACT_MARKET_SERIES_MATCH", "ROUNDING_ONLY_MARKET_SERIES_MATCH", "INACTIVE_OR_LEGACY_CODE"}]}, secret)
    write_csv(ARTIFACT_DIR / "cross_api_duplicate_parity.csv", ["idx_name", "left_source_api", "right_source_api", "date", "classification", "left_open", "left_high", "left_low", "left_close", "right_open", "right_high", "right_low", "right_close", "open_match", "high_match", "low_match", "close_match"], duplicate_detail_rows)
    safe_write_json(ARTIFACT_DIR / "cross_api_duplicate_contract.json", {"work_id": WORK_ID, "duplicate_name_count": len(duplicate_pairs), "pair_classifications": list(DUPLICATE_STATUSES), "pairs": duplicate_pairs, "authority_rule": {"EXACT_CROSS_API_DUPLICATE": "native KOSPI→kospi_dd_trd; native KOSDAQ→kosdaq_dd_trd; KRX-branded→krx_dd_trd", "SAME_NAME_DIFFERENT_SERIES": "retain source-qualified identity (source_api, IDX_CLSS, IDX_NM)", "PARTIAL_CROSS_API_EVIDENCE": "do not deduplicate until complete evidence", "UNKNOWN_CROSS_API_RELATION": "block authority decision"}, "unknown_count": counters["cross_api_unknown_count"]}, secret)
    write_csv(ARTIFACT_DIR / "krx_sector_taxonomy.csv", ["official_idx_name", "source_api", "official_idx_class", "classification", "has_close"], taxonomy_rows)
    safe_write_json(ARTIFACT_DIR / "krx_sector_taxonomy_relation.json", {"work_id": WORK_ID, "taxonomy_count": len(taxonomy_rows), "exact_equivalence_count": exact_taxonomy_count, "distinct_taxonomy_count": len(taxonomy_rows) - exact_taxonomy_count, "relations": relation_rows, "substitution_policy": "KRX taxonomy is not a drop-in replacement for native 46-code sector RS."}, secret)
    safe_write_json(ARTIFACT_DIR / "network_request_summary.json", network_summary, secret)
    safe_write_json(ARTIFACT_DIR / "quota_validation.json", {"storage_type": "SQLite", "usage_date_kst": usage["usage_date_kst"], "endpoint_usage": usage["endpoint_usage"], "global_total": usage["global_total"], "actual_http_attempts": client.request_count, "quota_recorded_attempts": usage["global_total"], "quota_counter_mismatch_count": counters["quota_counter_mismatch_count"], "endpoint_limit": quota.endpoint_limit, "global_safety_limit": quota.global_safety_limit, "reserve": quota.reserve}, secret)
    safe_write_json(ARTIFACT_DIR / "request_audit.json", {"work_id": WORK_ID, "max_requests": MAX_KRX_ATTEMPTS, "request_count": client.request_count, "retry_count": client.retry_count, "status_counts": client.status_counts, "failures": failures, "requests": client.audit}, secret)
    safe_write_json(ARTIFACT_DIR / "endpoint_contract.json", endpoint_contract, secret)
    for date in PRIMARY_DATES:
        for service in KRX_SERVICES:
            response = responses.get((service["service_name"], date))
            if response:
                safe_write_json(RAW_DIR / f"{service['api_id']}_{date.replace('-', '')}.json", response.payload, secret)
    architecture_text = "\n".join(["architecture_recommendation.md", "=" * 80, "KRX Index Series Mapping V01 recommendation", "=" * 80, "", f"RECOMMENDATION: {recommendation}", "", "Native KOSPI/KOSDAQ sector codes are mapped only by multi-date OHLC price identity.", "KRX-branded sector taxonomy remains a separate source-qualified axis.", "PyKRX is validation reference only; production provider and RS formula were not changed.", "Index price-history PIT is separate from ticker-to-sector membership PIT."])
    (ARTIFACT_DIR / "architecture_recommendation.md").parent.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "architecture_recommendation.md").write_text(architecture_text + "\n", encoding="utf-8")
    return {"status": final_status, "recommendation": recommendation, "start_head": start_head, "implementation_head": implementation_head, "request_count": client.request_count, "pykrx_operations": py_state["network_operations"], "pykrx_state": py_state, "counters": counters, "mapping_details": mapping_details, "duplicate_pairs": duplicate_pairs, "taxonomy_rows": taxonomy_rows, "secret_scan": secret_scan, "quota": usage}


def main() -> int:
    try:
        result = run_validation()
    except Exception as exc:
        print(f"FINAL_STATUS=BLOCKED_VALIDATION_EXCEPTION_{type(exc).__name__}")
        return 1
    print(f"FINAL_STATUS={result['status']}")
    print(f"RECOMMENDATION={result.get('recommendation', '')}")
    print(f"KRX_REQUEST_COUNT={result.get('request_count', 0)}")
    print(f"PYKRX_NETWORK_OPERATIONS={result.get('pykrx_operations', 0)}")
    print(f"SECRET_OCCURRENCE_COUNT={result.get('secret_scan', {}).get('secret_occurrence_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
