#!/usr/bin/env python3
"""Run a bounded, secret-safe OpenDART API access validation.

This is an access and raw-schema smoke test only.  It deliberately does not
implement a Fundamentals provider, PIT resolver, normalization contract,
scoring, or Stock Report integration.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/access_v01"
WORK_ID = "OPENDART_API_ACCESS_VALIDATION_V01"
TICKERS = ("005930", "237690", "086790")
TICKER_NAMES = {
    "005930": "삼성전자",
    "237690": "에스티팜",
    "086790": "하나금융지주",
}

CORP_CODE_ENDPOINT = "https://opendart.fss.or.kr/api/corpCode.xml"
COMPANY_ENDPOINT = "https://opendart.fss.or.kr/api/company.json"
DISCLOSURE_ENDPOINT = "https://opendart.fss.or.kr/api/list.json"
FINANCIAL_ENDPOINT = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"

EXPECTED_COMPANY_FIELDS = (
    "corp_code", "corp_name", "corp_name_eng", "stock_name", "stock_code",
    "ceo_nm", "corp_cls", "jurir_no", "bizr_no", "adres", "hm_url", "ir_url",
    "phn_no", "fax_no", "induty_code", "est_dt", "acc_mt",
)
EXPECTED_FINANCIAL_FIELDS = (
    "rcept_no", "reprt_code", "bsns_year", "corp_code", "sj_div", "sj_nm",
    "account_id", "account_nm", "account_detail", "thstrm_nm", "thstrm_amount",
    "thstrm_add_amount", "frmtrm_nm", "frmtrm_amount", "frmtrm_q_nm",
    "frmtrm_q_amount", "frmtrm_add_amount", "ord", "currency",
)
# OpenDART may omit these prior-quarter fields for an annual report while
# retaining the surrounding comparative-period fields.  Keep them visible in
# ``missing_expected_fields`` but do not turn a parseable annual response into
# a schema failure solely because of this report-type variation.
ANNUAL_OPTIONAL_FINANCIAL_FIELDS = frozenset({
    "frmtrm_q_nm", "frmtrm_q_amount", "frmtrm_add_amount",
})
DIAGNOSTIC_ACCOUNT_TERMS = (
    "매출", "영업이익", "당기순이익", "자산총계", "부채총계", "자본총계", "영업활동",
)
DISCLOSURE_FIELDS = (
    "corp_cls", "corp_name", "corp_code", "stock_code", "report_nm", "rcept_no",
    "flr_nm", "rcept_dt", "rm",
)


def redact_url(url: str) -> str:
    """Redact a credential from a URL before it can reach logs or artifacts."""

    parts = urlsplit(url)
    redacted_query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        redacted_query.append((key, "<REDACTED>" if key == "crtfc_key" else value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(redacted_query), parts.fragment))


def build_request_url(endpoint: str, params: dict[str, str]) -> str:
    """Build a URL for a request; callers must use the unredacted value only for transport."""

    return f"{endpoint}?{urlencode(params)}"


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _normalise_corp_name(value: Any) -> str:
    """Compare corp names without legal-form suffix/punctuation noise."""

    normalised = re.sub(r"\s+", "", str(value or ""))
    normalised = normalised.replace("㈜", "").replace("(주)", "")
    normalised = normalised.replace("(주식회사)", "")
    return normalised


def parse_corp_code_zip(raw: bytes) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """Parse the XML contained in the official corpCode ZIP response."""

    with zipfile.ZipFile(BytesIO(raw)) as archive:
        xml_names = [name for name in archive.namelist() if name.lower().endswith(".xml")]
        if not xml_names:
            raise ValueError("corpCode ZIP contains no XML member")
        xml_raw = archive.read(xml_names[0])

    root = ElementTree.fromstring(xml_raw)
    records: list[dict[str, str]] = []
    for element in root.iter():
        if _local_name(element.tag) != "list":
            continue
        values = {
            _local_name(child.tag): (child.text or "").strip()
            for child in list(element)
        }
        if values.get("corp_code"):
            records.append({
                "corp_code": values.get("corp_code", ""),
                "corp_name": values.get("corp_name", ""),
                "stock_code": values.get("stock_code", ""),
                "modify_date": values.get("modify_date", ""),
            })
    return records, {
        "xml_member": xml_names[0],
        "xml_byte_length": len(xml_raw),
        "record_count": len(records),
    }


def map_tickers(records: list[dict[str, str]], tickers: tuple[str, ...] = TICKERS) -> tuple[dict[str, dict[str, str]], list[str]]:
    """Exact-match stock codes to one and only one eight-digit corp code."""

    mapping: dict[str, dict[str, str]] = {}
    errors: list[str] = []
    for ticker in tickers:
        matches = [row for row in records if row.get("stock_code") == ticker]
        if len(matches) != 1:
            errors.append(f"{ticker}: expected one mapping, found {len(matches)}")
            continue
        row = matches[0]
        if not re.fullmatch(r"\d{8}", row.get("corp_code", "")):
            errors.append(f"{ticker}: corp_code is not eight digits")
            continue
        mapping[ticker] = row
    return mapping, errors


def classify_status(status: str | None) -> str:
    """Classify OpenDART's documented status codes without treating 013 as an outage."""

    if status == "000":
        return "PASS"
    if status == "013":
        return "DATA_NOT_FOUND"
    if status in {"010", "011", "012"}:
        return "API_ACCESS_BLOCKED"
    if status in {"020", "021"}:
        return "REQUEST_LIMIT_BLOCKED"
    if status in {"800", "900", "901"}:
        return "EXTERNAL_SERVICE_ERROR"
    if status in {"014", "100", "101"}:
        return "API_REQUEST_ERROR"
    return "UNKNOWN_STATUS"


def _payload_status(payload: dict[str, Any]) -> str | None:
    value = payload.get("status")
    return str(value) if value is not None else None


def _payload_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("list")
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _status_result(payload: dict[str, Any]) -> dict[str, Any]:
    status = _payload_status(payload)
    return {
        "status": status,
        "message": payload.get("message"),
        "classification": classify_status(status),
    }


def _request_json(
    endpoint: str,
    params: dict[str, str],
    auth_key: str,
    request_audit: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    """Perform exactly one bounded JSON request without exposing the key."""

    transport_params = {**params, "crtfc_key": auth_key}
    request_url = build_request_url(endpoint, transport_params)
    safe_params = {key: "<REDACTED>" if key == "crtfc_key" else value for key, value in transport_params.items()}
    audit: dict[str, Any] = {
        "label": label,
        "endpoint": endpoint,
        "redacted_request": redact_url(request_url),
        "parameters": safe_params,
        "http_status": None,
        "content_type": None,
        "response_byte_length": 0,
        "status": None,
        "message": None,
        "record_count": 0,
        "error_type": None,
    }
    try:
        request = Request(request_url, headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            audit["http_status"] = int(response.status)
            audit["content_type"] = response.headers.get("Content-Type")
            audit["response_byte_length"] = len(raw)
    except HTTPError as exc:
        raw = exc.read()
        audit["http_status"] = int(exc.code)
        audit["content_type"] = exc.headers.get("Content-Type") if exc.headers else None
        audit["response_byte_length"] = len(raw)
        audit["error_type"] = "HTTPError"
    except (URLError, TimeoutError, OSError) as exc:
        raw = b""
        audit["error_type"] = type(exc).__name__

    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        payload = payload if isinstance(payload, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
        audit["error_type"] = audit["error_type"] or "InvalidJSON"

    audit.update({
        "status": _payload_status(payload),
        "message": payload.get("message"),
        "record_count": len(_payload_rows(payload)),
    })
    request_audit.append(audit)
    return payload


def _request_binary(
    endpoint: str,
    auth_key: str,
    request_audit: list[dict[str, Any]],
) -> tuple[bytes, dict[str, Any]]:
    """Perform exactly one corpCode binary request."""

    transport_params = {"crtfc_key": auth_key}
    request_url = build_request_url(endpoint, transport_params)
    audit: dict[str, Any] = {
        "label": "corp_code_download",
        "endpoint": endpoint,
        "redacted_request": redact_url(request_url),
        "parameters": {"crtfc_key": "<REDACTED>"},
        "http_status": None,
        "content_type": None,
        "response_byte_length": 0,
        "status": None,
        "message": None,
        "record_count": 0,
        "error_type": None,
    }
    try:
        request = Request(request_url, headers={"Accept": "application/zip"}, method="GET")
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            audit["http_status"] = int(response.status)
            audit["content_type"] = response.headers.get("Content-Type")
            audit["response_byte_length"] = len(raw)
    except HTTPError as exc:
        raw = exc.read()
        audit["http_status"] = int(exc.code)
        audit["content_type"] = exc.headers.get("Content-Type") if exc.headers else None
        audit["response_byte_length"] = len(raw)
        audit["error_type"] = "HTTPError"
    except (URLError, TimeoutError, OSError) as exc:
        raw = b""
        audit["error_type"] = type(exc).__name__
    request_audit.append(audit)
    return raw, audit


def _company_summary(payload: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    fields = sorted(payload)
    missing = sorted(set(EXPECTED_COMPANY_FIELDS) - set(fields))
    identity = {
        "corp_code": payload.get("corp_code"),
        "corp_name": payload.get("corp_name"),
        "stock_name": payload.get("stock_name"),
        "stock_code": payload.get("stock_code"),
    }
    corp_name_match = _normalise_corp_name(identity["corp_name"]) == _normalise_corp_name(expected["corp_name"])
    identity_consistency = (
        identity["corp_code"] == expected["corp_code"]
        and identity["stock_code"] == expected["stock_code"]
        and corp_name_match
    )
    return {
        **_status_result(payload),
        "observed_fields": fields,
        "missing_expected_fields": missing,
        "identity": identity,
        "expected_identity": expected,
        "corp_name_match_after_legal_suffix_normalization": corp_name_match,
        "identity_consistency": identity_consistency,
        "selected_fields": {key: payload.get(key) for key in EXPECTED_COMPANY_FIELDS if key in payload},
    }


def _disclosure_summary(payload: dict[str, Any], corp_code: str) -> dict[str, Any]:
    rows = _payload_rows(payload)
    fields = sorted({key for row in rows for key in row})
    samples = [{key: row.get(key) for key in DISCLOSURE_FIELDS if key in row} for row in rows[:3]]
    return {
        **_status_result(payload),
        "row_count": len(rows),
        "observed_fields": fields,
        "corp_code_consistency": all(str(row.get("corp_code", "")) == corp_code for row in rows),
        "sample_rows": samples,
    }


def _financial_summary(payload: dict[str, Any], expected: dict[str, str]) -> dict[str, Any]:
    rows = _payload_rows(payload)
    fields = sorted({key for row in rows for key in row})
    missing = sorted(set(EXPECTED_FINANCIAL_FIELDS) - set(fields)) if rows else []
    diagnostics: list[dict[str, Any]] = []
    for row in rows:
        account_name = str(row.get("account_nm") or "")
        if any(term in account_name for term in DIAGNOSTIC_ACCOUNT_TERMS):
            diagnostics.append({
                key: row.get(key)
                for key in ("account_id", "account_nm", "sj_div", "thstrm_amount")
            })
    schema_required_missing = sorted(set(missing) - ANNUAL_OPTIONAL_FINANCIAL_FIELDS)
    schema_status = (
        "PASS"
        if rows and not schema_required_missing
        else ("DATA_NOT_FOUND" if _payload_status(payload) == "013" else "NOT_EVALUATED_NO_ROWS")
    )
    return {
        **_status_result(payload),
        "row_count": len(rows),
        "observed_fields": fields,
        "missing_expected_fields": missing,
        "schema_required_missing_fields": schema_required_missing,
        "schema_optional_missing_fields": sorted(set(missing) & ANNUAL_OPTIONAL_FINANCIAL_FIELDS),
        "schema_status": schema_status,
        "unique_sj_div": sorted({str(row.get("sj_div")) for row in rows if row.get("sj_div")}),
        "unique_sj_nm": sorted({str(row.get("sj_nm")) for row in rows if row.get("sj_nm")}),
        "corp_code_consistency": all(str(row.get("corp_code", "")) == expected["corp_code"] for row in rows),
        "diagnostic_account_rows": diagnostics[:30],
    }


def _half_year_classification(payload: dict[str, Any]) -> str:
    status = _payload_status(payload)
    if status == "000":
        return "AVAILABLE"
    if status == "013":
        return "NOT_AVAILABLE"
    return classify_status(status)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_artifacts(
    summary: dict[str, Any],
    company_samples: dict[str, Any],
    financial_schema: dict[str, Any],
    auth_key: str,
) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    outputs = {
        "opendart_api_access_summary.json": summary,
        "opendart_api_company_samples.json": company_samples,
        "opendart_api_financial_schema_summary.json": financial_schema,
    }
    serialized = [json.dumps(value, ensure_ascii=False) for value in outputs.values()]
    leak_count = sum(text.count(auth_key) for text in serialized) if auth_key else 0
    summary["secret_leak_count"] = leak_count
    outputs["opendart_api_access_summary.json"] = summary
    for name, value in outputs.items():
        (ARTIFACT_DIR / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    manifest = {
        "work_id": WORK_ID,
        "artifact_directory": str(ARTIFACT_DIR.relative_to(ROOT)),
        "files": {},
        "raw_response_policy": "No raw corpCode ZIP/XML or full financial JSON persisted",
        "secret_policy": "API key is environment-only and redacted from request audit",
    }
    manifest["files"] = {name: _sha256(ARTIFACT_DIR / name) for name in sorted(outputs)}
    (ARTIFACT_DIR / "opendart_api_access_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _refresh_manifest() -> None:
    """Keep manifest hashes aligned after the summary receives final_status."""

    manifest_path = ARTIFACT_DIR / "opendart_api_access_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    names = (
        "opendart_api_access_summary.json",
        "opendart_api_company_samples.json",
        "opendart_api_financial_schema_summary.json",
    )
    manifest["files"] = {name: _sha256(ARTIFACT_DIR / name) for name in names}
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _final_status(summary: dict[str, Any]) -> str:
    if not summary["api_key_present"]:
        return "BLOCKED_OPENDART_API_KEY"
    audit = summary["request_audit"]
    statuses = {entry.get("status") for entry in audit if entry.get("status")}
    if statuses & {"010", "011", "012"}:
        return "BLOCKED_OPENDART_API_ACCESS"
    if any(entry.get("error_type") for entry in audit) or statuses & {"800", "900", "901"}:
        return "BLOCKED_EXTERNAL_OPENDART_SERVICE"
    annual = summary["financial_statement_2025_annual"]
    required_annual = all(annual[ticker]["classification"] == "PASS" for ticker in ("005930", "237690"))
    company_pass = all(summary["company_api"][ticker]["classification"] == "PASS" for ticker in TICKERS)
    list_success = any(item["classification"] == "PASS" for item in summary["disclosure_search_api"].values())
    schema_pass = all(annual[ticker]["schema_status"] == "PASS" for ticker in ("005930", "237690"))
    primary = (
        summary["corp_code_download"] == "PASS"
        and summary["corp_code_zip_parse"] == "PASS"
        and summary["corp_code_mapping_status"] == "PASS"
        and company_pass
        and list_success
        and required_annual
        and schema_pass
        and summary["secret_leak_count"] == 0
        and summary["request_budget_pass"]
    )
    if primary:
        return "READY_FOR_ARCHITECT_OPENDART_API_ACCESS_REVIEW"
    if summary["corp_code_download"] == "PASS" and summary["corp_code_zip_parse"] == "PASS":
        return "OPENDART_FINANCIAL_API_VALIDATION_FIX_REQUIRED"
    return "OPENDART_ACCESS_VALIDATION_FIX_REQUIRED"


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    auth_key = os.getenv("OPENDART_API_KEY", "").strip()
    request_audit: list[dict[str, Any]] = []
    run_date = date.today().isoformat()

    summary: dict[str, Any] = {
        "work_id": WORK_ID,
        "run_date": run_date,
        "api_key_present": bool(auth_key),
        "corp_code_download": "NOT_RUN",
        "corp_code_content_type": None,
        "corp_code_zip_parse": "NOT_RUN",
        "corp_code_record_count": 0,
        "corp_code_mapping_status": "NOT_RUN",
        "corp_code_mapping": {},
        "company_api": {},
        "disclosure_search_api": {},
        "financial_statement_2025_annual": {},
        "half_year_2026_probe": {},
        "request_audit": request_audit,
        "total_http_requests": 0,
        "request_budget_max": 13,
        "request_budget_pass": True,
        "status_codes_encountered": [],
        "http_network_errors": [],
        "secret_leak_count": 0,
    }

    if auth_key:
        corp_raw, corp_audit = _request_binary(CORP_CODE_ENDPOINT, auth_key, request_audit)
        summary["corp_code_content_type"] = corp_audit.get("content_type")
        summary["corp_code_download"] = "PASS" if corp_audit.get("http_status") == 200 and corp_raw else "FAIL"
        mapping: dict[str, dict[str, str]] = {}
        company_samples: dict[str, Any] = {"corp_code_records": {}, "company": {}, "disclosure": {}}
        financial_schema: dict[str, Any] = {"annual_2025_cfs": {}, "half_year_2026_cfs": {}}
        if summary["corp_code_download"] == "PASS":
            try:
                records, zip_info = parse_corp_code_zip(corp_raw)
                summary["corp_code_zip_parse"] = "PASS"
                summary["corp_code_record_count"] = zip_info["record_count"]
                mapping, mapping_errors = map_tickers(records)
                summary["corp_code_mapping_status"] = "PASS" if not mapping_errors else "FAIL"
                summary["corp_code_mapping_errors"] = mapping_errors
                summary["corp_code_mapping"] = {
                    ticker: mapping[ticker] for ticker in sorted(mapping)
                }
                company_samples["corp_code_records"] = summary["corp_code_mapping"]
            except (ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
                summary["corp_code_zip_parse"] = "FAIL"
                summary["corp_code_parse_error_type"] = type(exc).__name__
        else:
            summary["corp_code_mapping_status"] = "NOT_EVALUATED"
            company_samples = {"corp_code_records": {}, "company": {}, "disclosure": {}}
            financial_schema = {"annual_2025_cfs": {}, "half_year_2026_cfs": {}}

        for ticker in TICKERS:
            expected = mapping.get(ticker)
            if expected is None:
                summary["company_api"][ticker] = {"classification": "NOT_EVALUATED"}
                summary["disclosure_search_api"][ticker] = {"classification": "NOT_EVALUATED"}
                summary["financial_statement_2025_annual"][ticker] = {"classification": "NOT_EVALUATED"}
                summary["half_year_2026_probe"][ticker] = {"classification": "NOT_EVALUATED"}
                continue
            company_payload = _request_json(
                COMPANY_ENDPOINT, {"corp_code": expected["corp_code"]}, auth_key, request_audit, f"company_{ticker}"
            )
            company_result = _company_summary(company_payload, expected)
            summary["company_api"][ticker] = company_result
            company_samples["company"][ticker] = company_result

            disclosure_payload = _request_json(
                DISCLOSURE_ENDPOINT,
                {
                    "corp_code": expected["corp_code"],
                    # OpenDART's list API expects compact YYYYMMDD values.
                    "bgn_de": "20250101",
                    "end_de": run_date.replace("-", ""),
                    "page_no": "1",
                    "page_count": "5",
                },
                auth_key,
                request_audit,
                f"disclosure_{ticker}",
            )
            disclosure_result = _disclosure_summary(disclosure_payload, expected["corp_code"])
            summary["disclosure_search_api"][ticker] = disclosure_result
            company_samples["disclosure"][ticker] = disclosure_result

            annual_payload = _request_json(
                FINANCIAL_ENDPOINT,
                {
                    "corp_code": expected["corp_code"],
                    "bsns_year": "2025",
                    "reprt_code": "11011",
                    "fs_div": "CFS",
                },
                auth_key,
                request_audit,
                f"financial_2025_annual_{ticker}",
            )
            annual_result = _financial_summary(annual_payload, expected)
            summary["financial_statement_2025_annual"][ticker] = annual_result
            financial_schema["annual_2025_cfs"][ticker] = annual_result

            half_payload = _request_json(
                FINANCIAL_ENDPOINT,
                {
                    "corp_code": expected["corp_code"],
                    "bsns_year": "2026",
                    "reprt_code": "11012",
                    "fs_div": "CFS",
                },
                auth_key,
                request_audit,
                f"financial_2026_half_year_{ticker}",
            )
            half_result = _status_result(half_payload)
            half_result["availability"] = _half_year_classification(half_payload)
            half_result["row_count"] = len(_payload_rows(half_payload))
            summary["half_year_2026_probe"][ticker] = half_result
            financial_schema["half_year_2026_cfs"][ticker] = half_result

        summary["total_http_requests"] = len(request_audit)
        summary["request_budget_pass"] = len(request_audit) <= summary["request_budget_max"]
        summary["status_codes_encountered"] = sorted({entry["status"] for entry in request_audit if entry.get("status")})
        summary["http_network_errors"] = [
            {"label": entry["label"], "error_type": entry["error_type"]}
            for entry in request_audit
            if entry.get("error_type")
        ]
        summary["secret_leak_count"] = 0
        summary["final_status"] = "PENDING"
        _write_artifacts(summary, company_samples, financial_schema, auth_key)
        # The artifact writer computes the leak count before manifest creation;
        # re-read the summary so final status uses the persisted value.
        summary = json.loads((ARTIFACT_DIR / "opendart_api_access_summary.json").read_text(encoding="utf-8"))
        summary["final_status"] = _final_status(summary)
        (ARTIFACT_DIR / "opendart_api_access_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        _refresh_manifest()
    else:
        summary["failure_code"] = "FAIL_ENV_MISSING"
        summary["final_status"] = "BLOCKED_OPENDART_API_KEY"
        _write_artifacts(summary, {"corp_code_records": {}, "company": {}, "disclosure": {}}, {"annual_2025_cfs": {}, "half_year_2026_cfs": {}}, auth_key)

    print(f"OPENDART_API_KEY_PRESENT={summary['api_key_present']}")
    print(f"TOTAL_HTTP_REQUESTS={summary['total_http_requests']}")
    print(f"FINAL_STATUS={summary['final_status']}")
    print(f"ARTIFACT_DIR={ARTIFACT_DIR.relative_to(ROOT)}")
    return 0 if summary["final_status"] == "READY_FOR_ARCHITECT_OPENDART_API_ACCESS_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
