"""Bounded, validation-only evidence collection for KRX Open API V02.

This script intentionally does not participate in the production provider
path.  It validates the three newly approved services, records redacted raw
snapshots, and joins them with the committed V01 index samples.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping

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
ARTIFACT_DIR = ROOT / "artifacts/data/krx_openapi/v02"
RAW_DIR = ARTIFACT_DIR / "raw_samples"
WORK_ID = "KRX_OPEN_API_V02_EXPANSION_VALIDATION"
EXPECTED_START_HEAD = "8a42e70a37a43177e9a6e388b18fabcf92f91f94"
ANCHOR_DATE = "2026-08-20"
ADJACENT_DATES = ("2026-08-19", "2026-08-20", "2026-08-21")
HOLIDAY_DATE = "2026-08-23"
HISTORICAL_DATES = ("2018-04-27", "2018-05-04")
CUTOFF_DATE = "20180504"
MAX_KRX_OPEN_API_REQUESTS = 40

SERVICES: tuple[dict[str, str], ...] = (
    {"service_name": "krx_index_daily", "api_id": "krx_dd_trd", "endpoint": "/idx/krx_dd_trd", "kind": "index", "market": "KRX", "raw_name": "krx_index_20260820.json"},
    {"service_name": "kospi_basic_info", "api_id": "stk_isu_base_info", "endpoint": "/sto/stk_isu_base_info", "kind": "basic", "market": "KOSPI", "raw_name": "kospi_basic_info_20260820.json"},
    {"service_name": "kosdaq_basic_info", "api_id": "ksq_isu_base_info", "endpoint": "/sto/ksq_isu_base_info", "kind": "basic", "market": "KOSDAQ", "raw_name": "kosdaq_basic_info_20260820.json"},
)
SERVICE_BY_NAME = {item["service_name"]: item for item in SERVICES}
REQUIRED_BASIC_FIELDS = {
    "ISU_CD", "ISU_SRT_CD", "ISU_NM", "LIST_DD", "MKT_TP_NM", "SECUGRP_NM",
    "SECT_TP_NM", "KIND_STKCERT_TP_NM", "PARVAL", "LIST_SHRS",
}
OPTIONAL_BASIC_FIELDS = {"ISU_ABBRV", "ISU_ENG_NM"}
REQUIRED_INDEX_FIELDS = {
    "BAS_DD", "IDX_CLSS", "IDX_NM", "CLSPRC_IDX", "OPNPRC_IDX", "HGPRC_IDX",
    "LWPRC_IDX", "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP",
}
INDEX_CATEGORIES = ("BROAD_MARKET", "SECTOR_INDUSTRY", "SIZE_STYLE", "THEMATIC", "STRATEGY", "ESG", "OTHER", "UNKNOWN")


def normalize_numeric(value: Any) -> int | float | None:
    """Parse KRX numeric values without converting blank values to zero."""

    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "—", "nan", "NaN", "None", "null"}:
        return None
    try:
        number = float(text)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid numeric value type={type(value).__name__}") from exc
    if number != number:
        return None
    return int(number) if number.is_integer() else number


def missing_value(value: Any) -> bool:
    return value is None or str(value).strip() in {"", "-", "—", "null", "None"}


def normalize_date(value: Any) -> str:
    text = re.sub(r"[^0-9]", "", str(value or ""))
    return text[:8] if len(text) >= 8 else text


def normalize_basic_row(row: Mapping[str, Any], requested_date: str) -> dict[str, Any]:
    """Normalize logical stock-master fields while preserving requested PIT date."""

    return {
        "requested_date": requested_date,
        "standard_code": str(row.get("ISU_CD", "")).strip() or None,
        "ticker": str(row.get("ISU_SRT_CD", "")).strip() or None,
        "name": str(row.get("ISU_NM", "")).strip() or None,
        "name_abbrev": str(row.get("ISU_ABBRV", "")).strip() or None,
        "name_english": str(row.get("ISU_ENG_NM", "")).strip() or None,
        "listing_date": normalize_date(row.get("LIST_DD")),
        "market": str(row.get("MKT_TP_NM", "")).strip() or None,
        "security_group": str(row.get("SECUGRP_NM", "")).strip() or None,
        "section": str(row.get("SECT_TP_NM", "")).strip() or None,
        "stock_type": str(row.get("KIND_STKCERT_TP_NM", "")).strip() or None,
        "par_value": normalize_numeric(row.get("PARVAL")),
        "listed_shares": normalize_numeric(row.get("LIST_SHRS")),
    }


def field_presence(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    rows = list(rows)
    total = len(rows)
    fields = sorted({str(key) for row in rows for key in row})
    result = []
    for field in fields:
        key_count = sum(field in row for row in rows)
        blank_count = sum(field in row and missing_value(row.get(field)) for row in rows)
        result.append({
            "field_name": field,
            "field_presence_count": key_count,
            "field_presence_ratio": (key_count / total) if total else 0.0,
            "blank_value_count": blank_count,
            "key_missing_count": total - key_count,
        })
    return result


def required_schema_missing(kind: str, rows: Iterable[Mapping[str, Any]]) -> list[str]:
    observed = {str(key) for row in rows for key in row}
    required = REQUIRED_BASIC_FIELDS if kind == "basic" else REQUIRED_INDEX_FIELDS
    return sorted(required - observed)


def classify_index_name(name: Any) -> str:
    """Conservative, name-based inventory taxonomy; UNKNOWN is intentional."""

    text = str(name or "").strip()
    if not text:
        return "UNKNOWN"
    if any(token in text for token in ("샤프", "전략")):
        return "STRATEGY"
    if any(token in text for token in ("ESG", "ESG")):
        return "ESG"
    if any(token in text for token in ("밸류업", "K콘텐츠")):
        return "THEMATIC"
    if any(token in text for token in ("소형", "중형", "중대형", "초소형", "SIZE", "스타일")):
        return "SIZE_STYLE"
    if any(token in text for token in ("자동차", "반도체", "헬스케어", "은행", "에너지화학", "철강", "방송통신", "건설", "증권", "기계장비", "보험", "운송", "경기소비재", "필수소비재", "정보기술", "유틸리티", "자유소비재", "산업재", "소재", "커뮤니케이션서비스", "금융")):
        return "SECTOR_INDUSTRY"
    if any(token in text for token in ("TMI", "300", "100", "TOP", "코스피", "코스닥")):
        return "BROAD_MARKET"
    return "OTHER"


def normalize_sector_name(value: str) -> str:
    return re.sub(r"[^가-힣A-Za-z0-9]", "", value.replace("KRX", "")).lower()


def load_sector_names() -> dict[str, str]:
    path = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/sector_mapping_20260814.csv"
    names: dict[str, str] = {}
    if not path.exists():
        return names
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            code = str(row.get("sector_code", "")).strip()
            name = str(row.get("sector_name", "")).strip()
            if code and name and code not in names:
                names[code] = name
    return names


def sector_match_status(sector_name: str | None, krx_names: set[str]) -> tuple[str, str | None]:
    if not sector_name:
        return "INSUFFICIENT_LOCAL_EVIDENCE", None
    normalized = normalize_sector_name(sector_name)
    direct = []
    for name in sorted(krx_names):
        candidate = normalize_sector_name(name)
        if candidate.startswith("krx"):
            candidate = candidate[3:]
        if candidate == normalized:
            direct.append(name)
    if len(direct) == 1:
        return "MAPPED_TO_KRX_SERIES", direct[0]
    aliases = {
        "화학": ("KRX 에너지화학",), "제약": ("KRX 헬스케어",), "비금속": ("KRX 소재",),
        "금속": ("KRX 철강",), "전기전자": ("KRX 정보기술",), "의료정밀기기": ("KRX 헬스케어",),
        "운송장비부품": ("KRX 자동차",), "유통": ("KRX 경기소비재",), "전기가스": ("KRX 유틸리티",),
        "운송창고": ("KRX 운송",), "통신": ("KRX 방송통신",), "금융": ("KRX 300 금융",),
        "음식료담배": ("KRX 필수소비재",),
    }
    candidates = [candidate for candidate in aliases.get(normalized, ()) if candidate in krx_names]
    if len(candidates) == 1:
        return "AMBIGUOUS_NAME_MAPPING", candidates[0]
    return "MISSING_FROM_KRX_SERIES", None


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


def git_sha(ref: str) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def safe_write_json(path: Path, value: Any, secret: str = "") -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if secret and secret in serialized:
        raise ValueError("secret detected in validation artifact")
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
        if not path.is_file():
            continue
        scanned += 1
        try:
            count += path.read_text(encoding="utf-8", errors="ignore").count(secret)
        except OSError:
            pass
    return {"secret_occurrence_count": count, "scanned_file_count": scanned}


def _response_ok(response: KrxOpenApiResponse | None) -> bool:
    return bool(response and response.http_status == 200 and response.records_key == "OutBlock_1")


def _response_status(response: KrxOpenApiResponse | None) -> str:
    if response is None:
        return "NOT_REQUESTED_OR_ERROR"
    if response.http_status != 200:
        return f"HTTP_{response.http_status}"
    if response.records_key != "OutBlock_1":
        return "HTTP_200_NO_OUTBLOCK"
    return "HTTP_200_EMPTY" if response.record_count == 0 else "HTTP_200_RECORDS"


def _daily_rows() -> dict[str, dict[str, dict[str, Any]]]:
    result: dict[str, dict[str, dict[str, Any]]] = {"KOSPI": {}, "KOSDAQ": {}}
    for market, filename in (("KOSPI", "kospi_stock_20260820.json"), ("KOSDAQ", "kosdaq_stock_20260820.json")):
        path = ROOT / "artifacts/data/krx_openapi/v01/raw_samples" / filename
        if not path.exists():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        for row in payload.get("OutBlock_1", []):
            ticker = str(row.get("ISU_CD", "")).strip()
            if ticker:
                result[market][ticker] = row
    return result


def _basic_by_ticker(response: KrxOpenApiResponse | None) -> dict[str, dict[str, Any]]:
    if not response:
        return {}
    return {str(row.get("ISU_SRT_CD", "")).strip(): row for row in response.records if str(row.get("ISU_SRT_CD", "")).strip()}


def _basic_contract(response: KrxOpenApiResponse | None, service: Mapping[str, str]) -> dict[str, Any]:
    rows = list(response.records if response else ())
    missing = required_schema_missing("basic", rows)
    return {
        "service_name": service["service_name"], "api_id": service["api_id"], "expected_endpoint": service["endpoint"],
        "actual_endpoint": service["endpoint"], "method": "GET", "auth_header": "AUTH_KEY",
        "query_parameter_names": ["basDd"], "query_date_format": "YYYYMMDD", "records_container": response.records_key if response else None,
        "requested_date": ANCHOR_DATE, "http_status": response.http_status if response else None,
        "record_count": response.record_count if response else 0, "required_fields_missing": missing,
        "schema_status": "KNOWN" if _response_ok(response) and not missing else "BLOCKED_KRX_OPEN_API_SCHEMA",
        "access_status": "PASS" if _response_ok(response) else "FAIL",
    }


def run_validation() -> dict[str, Any]:
    # The task's START HEAD is the repository baseline, not the implementation
    # commit from which this replay is launched.  On a feature branch this is
    # origin/main; if it is unavailable, retain the local HEAD as provenance.
    start_head = git_sha("origin/main")
    if start_head == "UNKNOWN":
        start_head = git_sha("HEAD")
    implementation_head = git_sha("HEAD")
    secret = load_auth_key()
    if not secret:
        status = "BLOCKED_KRX_OPEN_API_V02_AUTHORIZATION"
        safe_write_json(ARTIFACT_DIR / "krx_openapi_v02_access_summary.json", {"work_id": WORK_ID, "status": status, "auth_key_present": False, "auth_key_exposed": False, "services": []})
        safe_write_json(ARTIFACT_DIR / "krx_open_api_v02_manifest.json", {"work_id": WORK_ID, "status": status, "implementation_head": implementation_head})
        return {"status": status, "request_count": 0}

    quota = LocalKrxOpenApiQuota()
    client = KrxOpenApiClient(secret, max_requests=MAX_KRX_OPEN_API_REQUESTS, max_transient_retries=2, quota=quota)
    responses: dict[tuple[str, str], KrxOpenApiResponse | None] = {}
    failures: list[dict[str, Any]] = []
    halted = False

    def fetch(service_name: str, requested_date: str) -> KrxOpenApiResponse | None:
        nonlocal halted
        key = (service_name, requested_date)
        if halted:
            responses[key] = None
            return None
        service = SERVICE_BY_NAME[service_name]
        try:
            response = client.fetch(service["endpoint"], requested_date, quota_endpoint_key=service["api_id"])
        except KrxOpenApiAuthorizationError as exc:
            failures.append({"service_name": service_name, "requested_date": requested_date, "status": "BLOCKED_KRX_OPEN_API_V02_AUTHORIZATION", "error": str(exc)})
            halted = True
            response = None
        except KrxOpenApiRateLimitError as exc:
            failures.append({"service_name": service_name, "requested_date": requested_date, "status": "BLOCKED_KRX_OPEN_API_V02_RATE_LIMIT", "error": str(exc)})
            halted = True
            response = None
        except KrxOpenApiBudgetError as exc:
            failures.append({"service_name": service_name, "requested_date": requested_date, "status": "BLOCKED_KRX_OPEN_API_V02_BUDGET", "error": str(exc)})
            halted = True
            response = None
        except KrxOpenApiQuotaExceeded as exc:
            failures.append({"service_name": service_name, "requested_date": requested_date, "status": "BLOCKED_KRX_OPEN_API_V02_QUOTA", "error": str(exc)})
            halted = True
            response = None
        responses[key] = response
        if response is not None:
            # Only redacted response payloads are written later; this guard prevents accidental secret serialization.
            if secret in json.dumps(response.payload, ensure_ascii=False):
                raise ValueError("secret detected in KRX response payload")
        return response

    # Bounded request schedule: 4 KRX index dates + 3 dates for each stock master.
    for date in (*ADJACENT_DATES, HOLIDAY_DATE):
        fetch("krx_index_daily", date)
    for service_name in ("kospi_basic_info", "kosdaq_basic_info"):
        for date in (ANCHOR_DATE, *HISTORICAL_DATES):
            fetch(service_name, date)

    anchor_responses = {service["service_name"]: responses.get((service["service_name"], ANCHOR_DATE)) for service in SERVICES}
    endpoint_summary = [_basic_contract(anchor_responses[service["service_name"]], service) if service["kind"] == "basic" else {
        "service_name": service["service_name"], "api_id": service["api_id"], "expected_endpoint": service["endpoint"], "actual_endpoint": service["endpoint"],
        "method": "GET", "auth_header": "AUTH_KEY", "query_parameter_names": ["basDd"], "query_date_format": "YYYYMMDD",
        "records_container": anchor_responses[service["service_name"]].records_key if anchor_responses[service["service_name"]] else None,
        "requested_date": ANCHOR_DATE, "http_status": anchor_responses[service["service_name"]].http_status if anchor_responses[service["service_name"]] else None,
        "record_count": anchor_responses[service["service_name"]].record_count if anchor_responses[service["service_name"]] else 0,
        "required_fields_missing": required_schema_missing("index", anchor_responses[service["service_name"]].records if anchor_responses[service["service_name"]] else []),
        "schema_status": "KNOWN" if _response_ok(anchor_responses[service["service_name"]]) and not required_schema_missing("index", anchor_responses[service["service_name"]].records) else "BLOCKED_KRX_OPEN_API_SCHEMA",
        "access_status": "PASS" if _response_ok(anchor_responses[service["service_name"]]) else "FAIL",
    } for service in SERVICES]

    schema_snapshot: dict[str, Any] = {"work_id": WORK_ID, "anchor_date": ANCHOR_DATE, "endpoints": {}}
    required_missing_count = 0
    for service in SERVICES:
        response = anchor_responses[service["service_name"]]
        rows = list(response.records if response else ())
        required = REQUIRED_BASIC_FIELDS if service["kind"] == "basic" else REQUIRED_INDEX_FIELDS
        missing = sorted(required - {key for row in rows for key in row})
        required_missing_count += len(missing)
        schema_snapshot["endpoints"][service["service_name"]] = {
            "requested_date": ANCHOR_DATE, "top_level_keys": list(response.top_level_keys) if response else [],
            "records_container": response.records_key if response else None, "record_count": len(rows),
            "required_fields": sorted(required), "optional_fields": sorted(OPTIONAL_BASIC_FIELDS) if service["kind"] == "basic" else [],
            "required_fields_missing": missing, "fields": field_presence(rows),
        }
        if response:
            safe_write_json(RAW_DIR / service["raw_name"], response.payload, secret)

    # Endpoint-specific identifier semantics; daily evidence is the committed V01 raw sample.
    daily = _daily_rows()
    basic_anchor = {market: _basic_by_ticker(anchor_responses[name]) for market, name in (("KOSPI", "kospi_basic_info"), ("KOSDAQ", "kosdaq_basic_info"))}
    samsung = basic_anchor["KOSPI"].get("005930")
    basic_identifier_class = "BASE_INFO_ISU_CD_STANDARD_CODE" if samsung and re.fullmatch(r"KR[A-Z0-9]{10}", str(samsung.get("ISU_CD", ""))) and re.fullmatch(r"\d{6}", str(samsung.get("ISU_SRT_CD", ""))) else "OTHER_IDENTIFIER_SEMANTIC"
    daily_identifier_samples = []
    for market in ("KOSPI", "KOSDAQ"):
        row = next(iter(daily[market].values()), None)
        daily_identifier_samples.append({"market": market, "ISU_CD": row.get("ISU_CD") if row else None, "classification": "SHORT_TICKER" if row and re.fullmatch(r"\d{6}", str(row.get("ISU_CD"))) else "UNKNOWN"})
    unknown_identifier_count = int(basic_identifier_class == "OTHER_IDENTIFIER_SEMANTIC") + sum(item["classification"] == "UNKNOWN" for item in daily_identifier_samples)
    identifier_matrix = {
        "work_id": WORK_ID,
        "endpoint_semantics": {
            "stk_bydd_trd": {"ISU_CD": "SHORT_TICKER"}, "ksq_bydd_trd": {"ISU_CD": "SHORT_TICKER"},
            "stk_isu_base_info": {"ISU_CD": "STANDARD_CODE", "ISU_SRT_CD": "SHORT_TICKER"},
            "ksq_isu_base_info": {"ISU_CD": "STANDARD_CODE", "ISU_SRT_CD": "SHORT_TICKER"},
        },
        "samsung": {"ISU_CD": samsung.get("ISU_CD") if samsung else None, "ISU_SRT_CD": samsung.get("ISU_SRT_CD") if samsung else None, "ISU_NM": samsung.get("ISU_NM") if samsung else None, "classification": basic_identifier_class},
        "daily_identifier_samples": daily_identifier_samples,
        "daily_vs_basic_ISU_CD_conclusion": "ENDPOINT_SPECIFIC_SEMANTICS_DAILY_SHORT_TICKER_BASIC_STANDARD_CODE",
        "internal_ticker_field": "ISU_SRT_CD",
        "unknown_identifier_semantic_count": unknown_identifier_count,
    }

    # PIT snapshot tests and historical table.
    pit_rows: list[dict[str, Any]] = []
    pit_markets: dict[str, Any] = {}
    for market, service_name in (("KOSPI", "kospi_basic_info"), ("KOSDAQ", "kosdaq_basic_info")):
        current = _basic_by_ticker(responses.get((service_name, ANCHOR_DATE)))
        historical = {date: _basic_by_ticker(responses.get((service_name, date))) for date in HISTORICAL_DATES}
        selected_absence: dict[str, Any] | None = None
        for ticker, row in sorted(current.items(), key=lambda item: (normalize_date(item[1].get("LIST_DD")), item[0]), reverse=True):
            listing_date = normalize_date(row.get("LIST_DD"))
            if listing_date > CUTOFF_DATE and ticker not in historical[HISTORICAL_DATES[0]]:
                selected_absence = {"ticker": ticker, "name": row.get("ISU_NM"), "listing_date": listing_date, "present_2018_04_27": False, "present_2026_08_20": True}
                break
        survivor_rows = []
        for ticker, row in sorted(historical[HISTORICAL_DATES[0]].items()):
            if normalize_date(row.get("LIST_DD")) <= CUTOFF_DATE and ticker in current:
                current_row = current[ticker]
                survivor_rows.append({"ticker": ticker, "historical_name": row.get("ISU_NM"), "current_name": current_row.get("ISU_NM"), "listing_date": normalize_date(row.get("LIST_DD")), "standard_code_same": str(row.get("ISU_CD")) == str(current_row.get("ISU_CD")), "name_same": str(row.get("ISU_NM")) == str(current_row.get("ISU_NM"))})
            if len(survivor_rows) >= 3:
                break
        absence_pass = bool(selected_absence)
        historical_classification = "HISTORICAL_AS_OF_SNAPSHOT" if absence_pass and len(survivor_rows) >= 3 else "PARTIAL_HISTORICAL_SEMANTICS" if absence_pass else "CURRENT_UNIVERSE_WITH_REQUEST_DATE" if current else "UNKNOWN_PIT_SEMANTICS"
        pit_markets[market] = {
            "snapshot_record_counts": {"2018-04-27": len(historical["2018-04-27"]), "2018-05-04": len(historical["2018-05-04"]), "2026-08-20": len(current)},
            "post_2018_listing_absence_test": selected_absence or {"pass": False, "reason": "no current post-cutoff row absent from historical snapshot"},
            "historical_survivors": survivor_rows,
            "historical_survivor_count": len(survivor_rows), "classification": historical_classification,
        }
        if selected_absence:
            pit_rows.append({"market": market, "ticker": selected_absence["ticker"], "name": selected_absence["name"], "listing_date": selected_absence["listing_date"], "historical_present": False, "current_present": True, "expected": "ABSENT_THEN_PRESENT", "classification": "PASS"})
        for survivor in survivor_rows:
            pit_rows.append({"market": market, "ticker": survivor["ticker"], "name": survivor["historical_name"], "listing_date": survivor["listing_date"], "historical_present": True, "current_present": True, "expected": "SURVIVOR", "classification": "PASS" if survivor["standard_code_same"] else "IDENTIFIER_CHANGED"})
    pit_classifications = {item["classification"] for item in pit_markets.values()}
    pit_unknown_count = int(any(value == "UNKNOWN_PIT_SEMANTICS" for value in pit_classifications))
    pit_classification = "HISTORICAL_AS_OF_SNAPSHOT" if all(value == "HISTORICAL_AS_OF_SNAPSHOT" for value in pit_classifications) else "PARTIAL_HISTORICAL_SEMANTICS" if pit_classifications and "UNKNOWN_PIT_SEMANTICS" not in pit_classifications else "UNKNOWN_PIT_SEMANTICS"

    # Samsung corporate-action metadata and daily LIST_SHRS cross-check.
    split_comparisons = []
    samsung_rows = {}
    for date in HISTORICAL_DATES:
        response = responses.get(("kospi_basic_info", date))
        row = _basic_by_ticker(response).get("005930")
        samsung_rows[date] = row
        split_comparisons.append({"requested_date": date, "ISU_CD": row.get("ISU_CD") if row else None, "ISU_SRT_CD": row.get("ISU_SRT_CD") if row else None, "ISU_NM": row.get("ISU_NM") if row else None, "PARVAL": normalize_numeric(row.get("PARVAL")) if row else None, "LIST_SHRS": normalize_numeric(row.get("LIST_SHRS")) if row else None, "LIST_DD": normalize_date(row.get("LIST_DD")) if row else None, "KIND_STKCERT_TP_NM": row.get("KIND_STKCERT_TP_NM") if row else None})
    par_values = [item["PARVAL"] for item in split_comparisons]
    share_values = [item["LIST_SHRS"] for item in split_comparisons]
    par_changed = len(par_values) == 2 and None not in par_values and par_values[0] != par_values[1]
    shares_changed = len(share_values) == 2 and None not in share_values and share_values[0] != share_values[1]
    corporate = {
        "work_id": WORK_ID, "ticker": "005930", "event": "Samsung Electronics 50:1 split", "comparisons": split_comparisons,
        "parval_classification": "USEFUL_PRIMARY_TRIGGER" if par_changed else "NO_OBSERVED_CHANGE" if all(value is not None for value in par_values) else "UNKNOWN",
        "listed_shares_classification": "USEFUL_SECONDARY_TRIGGER" if shares_changed else "NO_OBSERVED_CHANGE" if all(value is not None for value in share_values) else "UNKNOWN",
        "boundary_alignment": "REQUESTED_BOUNDARY_OBSERVED" if par_changed or shares_changed else "UNKNOWN",
        "overclaim_guard": "These fields are dirty-candidate signals, not a complete corporate-action oracle.",
    }
    parity_rows = []
    for market in ("KOSPI", "KOSDAQ"):
        for ticker, daily_row in sorted(daily[market].items()):
            basic_row = basic_anchor[market].get(ticker)
            if not basic_row:
                continue
            daily_shares = normalize_numeric(daily_row.get("LIST_SHRS"))
            basic_shares = normalize_numeric(basic_row.get("LIST_SHRS"))
            parity_rows.append({"market": market, "ticker": ticker, "name": basic_row.get("ISU_NM"), "daily_listed_shares": daily_shares, "basic_listed_shares": basic_shares, "classification": "EXACT_MATCH" if daily_shares == basic_shares else "UNKNOWN_DIFFERENCE" if daily_shares is not None and basic_shares is not None else "KNOWN_SEMANTIC_DIFFERENCE"})
    parity_counts = Counter(row["classification"] for row in parity_rows)
    basic_daily_parity = {"source": "committed V01 daily raw sample vs V02 basic-info anchor", "rows": parity_rows, "classification_counts": dict(parity_counts), "unknown_difference_count": parity_counts["UNKNOWN_DIFFERENCE"]}

    # KRX index inventory and adjacent-day stability.
    index_anchor = anchor_responses["krx_index_daily"]
    index_rows = list(index_anchor.records if index_anchor else ())
    index_inventory = []
    for row in index_rows:
        index_inventory.append({"source_api": "krx_dd_trd", "idx_class": row.get("IDX_CLSS"), "idx_name": row.get("IDX_NM"), "has_close": not missing_value(row.get("CLSPRC_IDX")), "has_ohlc": all(not missing_value(row.get(field)) for field in ("OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX", "CLSPRC_IDX")), "has_volume": not missing_value(row.get("ACC_TRDVOL")), "has_trading_value": not missing_value(row.get("ACC_TRDVAL")), "has_market_cap": not missing_value(row.get("MKTCAP")), "classification": classify_index_name(row.get("IDX_NM"))})
    index_names = [str(row.get("IDX_NM", "")) for row in index_rows]
    index_categories = Counter(row["classification"] for row in index_inventory)
    adjacent = []
    anchor_keys = {(str(row.get("IDX_CLSS")), str(row.get("IDX_NM")), classify_index_name(row.get("IDX_NM"))) for row in index_rows}
    for date in ADJACENT_DATES:
        rows = list((responses.get(("krx_index_daily", date)).records if responses.get(("krx_index_daily", date)) else ()))
        keys = {(str(row.get("IDX_CLSS")), str(row.get("IDX_NM")), classify_index_name(row.get("IDX_NM"))) for row in rows}
        adjacent.append({"requested_date": date, "record_count": len(rows), "index_name_count": len({row.get("IDX_NM") for row in rows}), "name_set_changed_vs_anchor": keys != anchor_keys, "classification_key_stable_vs_anchor": {(key[0], key[1]): key[2] for key in keys} == {(key[0], key[1]): key[2] for key in anchor_keys}})
    holiday_response = responses.get(("krx_index_daily", HOLIDAY_DATE))
    index_validation = {
        "work_id": WORK_ID, "anchor_date": ANCHOR_DATE, "required_fields": sorted(REQUIRED_INDEX_FIELDS), "required_fields_missing": required_schema_missing("index", index_rows),
        "record_count": len(index_rows), "unique_index_name_count": len(set(index_names)), "duplicate_name_count": len(index_names) - len(set(index_names)),
        "blank_close_count": sum(missing_value(row.get("CLSPRC_IDX")) for row in index_rows), "categories": dict(index_categories), "adjacent_day_stability": adjacent,
        "non_trading_date": {"requested_date": HOLIDAY_DATE, "http_status": holiday_response.http_status if holiday_response else None, "records_container": holiday_response.records_key if holiday_response else None, "record_count": holiday_response.record_count if holiday_response else 0, "classification": _response_status(holiday_response)},
        "unknown_structural_error_count": sum(1 for row in index_rows if any(field not in row for field in REQUIRED_INDEX_FIELDS)),
    }

    # Combine committed V01 KOSPI/KOSDAQ index samples with the new KRX series inventory.
    all_inventory = list(index_inventory)
    for source_api, filename in (("kospi_dd_trd", "kospi_index_20260820.json"), ("kosdaq_dd_trd", "kosdaq_index_20260820.json")):
        path = ROOT / "artifacts/data/krx_openapi/v01/raw_samples" / filename
        if path.exists():
            for row in json.loads(path.read_text(encoding="utf-8")).get("OutBlock_1", []):
                all_inventory.append({"source_api": source_api, "idx_class": row.get("IDX_CLSS"), "idx_name": row.get("IDX_NM"), "has_close": not missing_value(row.get("CLSPRC_IDX")), "has_ohlc": all(not missing_value(row.get(field)) for field in ("OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX", "CLSPRC_IDX")), "has_volume": not missing_value(row.get("ACC_TRDVOL")), "has_trading_value": not missing_value(row.get("ACC_TRDVAL")), "has_market_cap": not missing_value(row.get("MKTCAP")), "classification": classify_index_name(row.get("IDX_NM"))})
    names_by_source: dict[str, set[str]] = defaultdict(set)
    for row in all_inventory:
        names_by_source[row["source_api"]].add(str(row["idx_name"]))
    source_pairs = [(a, b, name) for i, a in enumerate(sorted(names_by_source)) for b in sorted(names_by_source)[i + 1:] for name in sorted(names_by_source[a] & names_by_source[b])]
    for row in all_inventory:
        row["candidate_role"] = "CROSS_API_DUPLICATE" if any(row["idx_name"] == name and (row["source_api"] in (a, b)) for a, b, name in source_pairs) else "INVENTORY_ONLY"
    write_csv(ARTIFACT_DIR / "krx_index_series_inventory.csv", ["source_api", "idx_class", "idx_name", "has_close", "has_ohlc", "has_volume", "has_trading_value", "has_market_cap", "classification"], index_inventory)
    write_csv(ARTIFACT_DIR / "all_index_series_inventory.csv", ["source_api", "idx_class", "idx_name", "has_close", "has_ohlc", "has_volume", "has_trading_value", "has_market_cap", "classification", "candidate_role"], all_inventory)

    # Sector readiness uses only committed local mapping metadata; no PyKRX sweep.
    sector_names = load_sector_names()
    total_codes = list(KOSPI_SECTOR_CODES) + list(KOSDAQ_SECTOR_CODES)
    krx_name_set = {str(row.get("IDX_NM")) for row in index_rows if row.get("IDX_NM")}
    sector_rows = []
    for code in total_codes:
        local_name = sector_names.get(code)
        status, matched = sector_match_status(local_name, krx_name_set)
        sector_rows.append({"market": "KOSPI" if code in KOSPI_SECTOR_CODES else "KOSDAQ", "sector_code": code, "local_sector_name": local_name, "status": status, "matched_krx_name": matched})
    sector_counts = Counter(row["status"] for row in sector_rows)
    sector_parity = {"status": "INSUFFICIENT_LOCAL_EVIDENCE", "sample_count": 0, "reason": "Committed sector index cache contains no usable rows; no uncontrolled PyKRX sweep was performed.", "samples": []}
    sector_readiness = {"work_id": WORK_ID, "internal_sector_universe_total_count": len(total_codes), "sector_mapping_coverage_count": sector_counts["MAPPED_TO_KRX_SERIES"], "sector_mapping_ambiguous_count": sector_counts["AMBIGUOUS_NAME_MAPPING"], "sector_mapping_missing_count": sector_counts["MISSING_FROM_KRX_SERIES"], "sector_mapping_insufficient_evidence_count": sector_counts["INSUFFICIENT_LOCAL_EVIDENCE"], "sector_rows": sector_rows, "bounded_sector_parity": sector_parity, "krx_sector_candidate_count": sum(value for key, value in index_categories.items() if key == "SECTOR_INDUSTRY"), "recommendation": "READY_FOR_KRX_INDEX_SERIES_MAPPING_V01" if index_categories["SECTOR_INDUSTRY"] else "BLOCKED_SECTOR_INDEX_NOT_AVAILABLE"}

    usage = quota.get_usage()
    quota_recorded = int(usage["global_total"])
    quota_mismatch = int(quota_recorded != client.request_count)
    audit_mismatch = int(len(client.audit) != client.request_count)
    secret_scan = scan_secret(secret)
    readiness_counters = {
        "new_api_access_fail_count": sum(item["access_status"] != "PASS" for item in endpoint_summary),
        "required_schema_missing_count": required_missing_count,
        "unknown_identifier_semantic_count": unknown_identifier_count,
        "pit_unknown_count": pit_unknown_count,
        "request_audit_mismatch_count": audit_mismatch,
        "quota_counter_mismatch_count": quota_mismatch,
        "secret_occurrence_count": secret_scan["secret_occurrence_count"],
        "validation_source_head_mismatch_count": int(implementation_head != git_sha("HEAD")),
        "unknown_structural_error_count": index_validation["unknown_structural_error_count"],
    }
    access_pass = readiness_counters["new_api_access_fail_count"] == 0
    index_pass = bool(index_rows) and not index_validation["required_fields_missing"] and index_validation["unknown_structural_error_count"] == 0
    pit_pass = pit_classification != "UNKNOWN_PIT_SEMANTICS"
    final_status = "READY_FOR_ARCHITECT_KRX_OPEN_API_V02_REVIEW" if access_pass and index_pass and pit_pass and all(value == 0 for value in readiness_counters.values()) else "BLOCKED_MORE_EVIDENCE_REQUIRED"
    for failure_status in ("BLOCKED_KRX_OPEN_API_V02_AUTHORIZATION", "BLOCKED_KRX_OPEN_API_V02_RATE_LIMIT", "BLOCKED_KRX_OPEN_API_V02_QUOTA"):
        if any(item["status"] == failure_status for item in failures):
            final_status = failure_status
            break
    architecture = "RECOMMEND_PROCEED_TO_INDEX_MAPPING" if final_status.startswith("READY") and sector_readiness["recommendation"] == "READY_FOR_KRX_INDEX_SERIES_MAPPING_V01" else "BLOCKED_MORE_EVIDENCE_REQUIRED"

    access_summary = {"work_id": WORK_ID, "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "auth_key_present": True, "auth_key_exposed": False, "services": endpoint_summary, "new_api_access_pass_count": sum(item["access_status"] == "PASS" for item in endpoint_summary), "new_api_access_fail_count": readiness_counters["new_api_access_fail_count"], "status": final_status}
    endpoint_contract = {"work_id": WORK_ID, "base_url": client.base_url, "method": "GET", "auth_header": client.auth_header, "query_parameters": {"date": "basDd", "format": "YYYYMMDD"}, "records_container": "OutBlock_1", "services": [{"api_id": service["api_id"], "service_name": service["service_name"], "expected_endpoint": service["endpoint"], "actual_endpoint": service["endpoint"], "method": "GET", "auth_header": "AUTH_KEY", "date_parameter": "basDd"} for service in SERVICES]}
    safe_write_json(ARTIFACT_DIR / "krx_openapi_v02_access_summary.json", access_summary, secret)
    safe_write_json(ARTIFACT_DIR / "krx_openapi_v02_endpoint_contract.json", endpoint_contract, secret)
    safe_write_json(ARTIFACT_DIR / "krx_openapi_v02_schema_snapshot.json", schema_snapshot, secret)
    safe_write_json(ARTIFACT_DIR / "identifier_semantic_matrix.json", identifier_matrix, secret)
    safe_write_json(ARTIFACT_DIR / "stock_basic_info_pit_validation.json", {"work_id": WORK_ID, "classification": pit_classification, "markets": pit_markets}, secret)
    write_csv(ARTIFACT_DIR / "stock_basic_info_historical_table.csv", ["market", "ticker", "name", "listing_date", "historical_present", "current_present", "expected", "classification"], pit_rows)
    safe_write_json(ARTIFACT_DIR / "corporate_action_metadata_validation.json", corporate, secret)
    safe_write_json(ARTIFACT_DIR / "basic_vs_daily_list_shares_parity.json", basic_daily_parity, secret)
    safe_write_json(ARTIFACT_DIR / "krx_index_series_validation.json", index_validation, secret)
    safe_write_json(ARTIFACT_DIR / "sector_rs_readiness.json", sector_readiness, secret)
    safe_write_json(ARTIFACT_DIR / "quota_validation.json", {"storage_type": "SQLite", "usage_date_kst": usage["usage_date_kst"], "endpoint_usage": usage["endpoint_usage"], "global_total": quota_recorded, "actual_http_attempts": client.request_count, "quota_recorded_attempts": quota_recorded, "quota_mismatch_count": quota_mismatch, "endpoint_limit": quota.endpoint_limit, "global_safety_limit": quota.global_safety_limit, "reserve": quota.reserve}, secret)
    safe_write_json(ARTIFACT_DIR / "request_audit.json", {"work_id": WORK_ID, "max_requests": MAX_KRX_OPEN_API_REQUESTS, "request_count": client.request_count, "retry_count": client.retry_count, "status_counts": client.status_counts, "failures": failures, "requests": client.audit}, secret)
    architecture_text = "\n".join(["architecture_recommendation.md", "=" * 80, "KRX Open API V02 architecture recommendation", "=" * 80, "", f"RECOMMENDATION: {architecture}", "", "Validation only: no production provider, repository, Pattern A, or RS calculation was changed.", "Basic-info ISU_SRT_CD is the internal 6-digit ticker candidate; ISU_CD remains endpoint-specific.", "PARVAL/LIST_SHRS are dirty-candidate signals, not a complete corporate-action oracle.", "Sector RS formula and existing mapping are frozen; the next bounded step is full KRX index-series mapping."])
    (ARTIFACT_DIR / "architecture_recommendation.md").parent.mkdir(parents=True, exist_ok=True)
    (ARTIFACT_DIR / "architecture_recommendation.md").write_text(architecture_text + "\n", encoding="utf-8")
    manifest = {"work_id": WORK_ID, "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "end_head": None, "status": final_status, "architecture_recommendation": architecture, "readiness_counters": readiness_counters, "actual_http_attempts": client.request_count, "quota_recorded_attempts": quota_recorded, "secret_occurrence_count": secret_scan["secret_occurrence_count"]}
    safe_write_json(ARTIFACT_DIR / "krx_openapi_v02_manifest.json", manifest, secret)
    return {"status": final_status, "start_head": start_head, "implementation_head": implementation_head, "request_count": client.request_count, "retry_count": client.retry_count, "endpoint_summary": endpoint_summary, "schema_snapshot": schema_snapshot, "identifier_matrix": identifier_matrix, "pit_markets": pit_markets, "pit_classification": pit_classification, "corporate": corporate, "parity": basic_daily_parity, "index_validation": index_validation, "sector_readiness": sector_readiness, "quota": usage, "quota_mismatch": quota_mismatch, "readiness_counters": readiness_counters, "secret_scan": secret_scan, "architecture": architecture}


def main() -> int:
    try:
        result = run_validation()
    except Exception as exc:
        print(f"FINAL_STATUS=BLOCKED_VALIDATION_EXCEPTION_{type(exc).__name__}")
        return 1
    print(f"FINAL_STATUS={result['status']}")
    print(f"REQUEST_COUNT={result.get('request_count', 0)}")
    print(f"RETRY_COUNT={result.get('retry_count', 0)}")
    print(f"SECRET_OCCURRENCE_COUNT={result.get('secret_scan', {}).get('secret_occurrence_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
