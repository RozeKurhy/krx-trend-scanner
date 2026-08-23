#!/usr/bin/env python3
"""Validate the OpenDART Fundamentals V01 architecture boundary.

The script performs a bounded live probe for filing-specific XBRL and two
half-year schema samples.  It never persists raw XBRL/JSON and never prints an
API key.  Contract behavior is implemented in
``trend_scanner.fundamentals.opendart_contract`` and is exercised separately
by unit tests.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

from trend_scanner.fundamentals.opendart_contract import (
    PIT_GRANULARITY,
    FilingRecord,
    classify_company_family,
    map_statement_family,
    redact_url,
    resolve_core_account,
    select_pit_filing,
)


ROOT = Path(__file__).resolve().parents[1]
ACCESS_DIR = ROOT / "artifacts/fundamentals/opendart/validation/access_v01"
ARTIFACT_DIR = ROOT / "artifacts/fundamentals/opendart/validation/architecture_v01"
WORK_ID = "OPENDART_FUNDAMENTALS_V01_ARCHITECTURE"
ACCESS_VALIDATION_SHA = "7b235817607f7b58d46e49a2346bc14b0b28936c"
TICKERS = ("005930", "237690", "086790")
TICKER_NAMES = {"005930": "삼성전자", "237690": "에스티팜", "086790": "하나금융지주"}
NON_FINANCIAL_TICKERS = ("005930", "237690")
FINANCIAL_TICKERS = ("086790",)

LIST_ENDPOINT = "https://opendart.fss.or.kr/api/list.json"
XBRL_ENDPOINT = "https://opendart.fss.or.kr/api/fnlttXbrl.xml"
FINANCIAL_ENDPOINT = "https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json"


def _build_url(endpoint: str, params: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return f"{endpoint}?{urlencode(params)}"


def _status_from_payload(payload: dict[str, Any]) -> str | None:
    value = payload.get("status")
    return str(value) if value is not None else None


def _rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("list")
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _error_classification(status: str | None) -> str | None:
    return {
        "010": "API_ACCESS_BLOCKED",
        "011": "API_ACCESS_BLOCKED",
        "012": "API_ACCESS_BLOCKED",
        "013": "DATA_NOT_FOUND",
        "014": "API_REQUEST_ERROR",
        "020": "REQUEST_LIMIT_BLOCKED",
        "021": "REQUEST_LIMIT_BLOCKED",
        "100": "API_REQUEST_ERROR",
        "101": "API_REQUEST_ERROR",
        "800": "EXTERNAL_SERVICE_ERROR",
        "900": "EXTERNAL_SERVICE_ERROR",
        "901": "EXTERNAL_SERVICE_ERROR",
    }.get(status)


def _decode_error_status(raw: bytes) -> tuple[str | None, str | None]:
    """Inspect a non-ZIP body for a documented JSON/XML status only."""

    if not raw:
        return None, None
    try:
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict):
            status = _status_from_payload(payload)
            return status, _error_classification(status)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    text = raw[:4096].decode("utf-8", errors="ignore")
    match = re.search(r"<status>\s*([^<]+)\s*</status>", text)
    if match:
        status = match.group(1).strip()
        return status, _error_classification(status)
    return None, None


def _request_json(
    endpoint: str,
    params: dict[str, str],
    auth_key: str,
    audit: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    transport = {**params, "crtfc_key": auth_key}
    request_url = _build_url(endpoint, transport)
    entry: dict[str, Any] = {
        "label": label,
        "endpoint": endpoint,
        "redacted_request": redact_url(request_url),
        "parameters": {key: "<REDACTED>" if key == "crtfc_key" else value for key, value in transport.items()},
        "http_status": None,
        "content_type": None,
        "response_byte_length": 0,
        "status": None,
        "classification": None,
        "record_count": 0,
        "error_type": None,
    }
    raw = b""
    try:
        request = Request(request_url, headers={"Accept": "application/json"}, method="GET")
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            entry["http_status"] = int(response.status)
            entry["content_type"] = response.headers.get("Content-Type")
    except HTTPError as exc:
        raw = exc.read()
        entry["http_status"] = int(exc.code)
        entry["content_type"] = exc.headers.get("Content-Type") if exc.headers else None
        entry["error_type"] = "HTTPError"
    except (URLError, TimeoutError, OSError) as exc:
        entry["error_type"] = type(exc).__name__
    entry["response_byte_length"] = len(raw)
    try:
        payload = json.loads(raw.decode("utf-8")) if raw else {}
        payload = payload if isinstance(payload, dict) else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = {}
        entry["error_type"] = entry["error_type"] or "InvalidJSON"
    status = _status_from_payload(payload)
    entry["status"] = status
    entry["classification"] = "PASS" if status == "000" else _error_classification(status)
    entry["record_count"] = len(_rows(payload))
    audit.append(entry)
    return payload


def _request_xbrl(
    rcept_no: str,
    reprt_code: str,
    auth_key: str,
    audit: list[dict[str, Any]],
    label: str,
) -> dict[str, Any]:
    transport = {"rcept_no": rcept_no, "reprt_code": reprt_code, "crtfc_key": auth_key}
    request_url = _build_url(XBRL_ENDPOINT, transport)
    entry: dict[str, Any] = {
        "label": label,
        "endpoint": XBRL_ENDPOINT,
        "redacted_request": redact_url(request_url),
        "parameters": {key: "<REDACTED>" if key == "crtfc_key" else value for key, value in transport.items()},
        "http_status": None,
        "content_type": None,
        "response_byte_length": 0,
        "status": None,
        "classification": None,
        "zip_parse": "NOT_RUN",
        "member_count": 0,
        "member_names": [],
        "sha256": None,
        "error_type": None,
    }
    raw = b""
    try:
        request = Request(request_url, headers={"Accept": "application/zip, application/octet-stream"}, method="GET")
        with urlopen(request, timeout=30) as response:
            raw = response.read()
            entry["http_status"] = int(response.status)
            entry["content_type"] = response.headers.get("Content-Type")
    except HTTPError as exc:
        raw = exc.read()
        entry["http_status"] = int(exc.code)
        entry["content_type"] = exc.headers.get("Content-Type") if exc.headers else None
        entry["error_type"] = "HTTPError"
    except (URLError, TimeoutError, OSError) as exc:
        entry["error_type"] = type(exc).__name__
    entry["response_byte_length"] = len(raw)

    if raw:
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                names = archive.namelist()
                entry["zip_parse"] = "PASS"
                entry["member_count"] = len(names)
                entry["member_names"] = names[:10]
                entry["sha256"] = hashlib.sha256(raw).hexdigest()
                entry["classification"] = "PASS" if entry["http_status"] == 200 else "HTTP_ERROR_WITH_ZIP_BODY"
        except zipfile.BadZipFile:
            status, classification = _decode_error_status(raw)
            entry["zip_parse"] = "FAIL_NOT_ZIP"
            entry["status"] = status
            entry["classification"] = classification or "NON_ZIP_RESPONSE"
            entry["error_type"] = entry["error_type"] or "BadZipFile"
    elif not entry["error_type"]:
        entry["error_type"] = "EmptyResponse"
        entry["classification"] = "EMPTY_RESPONSE"
    audit.append(entry)
    return entry


def _infer_report_code(report_nm: str) -> str | None:
    name = str(report_nm or "")
    if "사업보고서" in name:
        return "11011"
    if "반기보고서" in name:
        return "11012"
    if "분기보고서" in name and ("3분기" in name or "09" in name):
        return "11014"
    if "분기보고서" in name:
        return "11013"
    return None


def _infer_year(report_nm: str, rcept_dt: str) -> str:
    match = re.search(r"(20\d{2})\.\s*(?:12|06|03|09)", str(report_nm or ""))
    if match:
        return match.group(1)
    return str(rcept_dt or "")[:4]


def _filing_records(ticker: str, rows: Iterable[dict[str, Any]]) -> list[FilingRecord]:
    records: list[FilingRecord] = []
    for row in rows:
        report_nm = str(row.get("report_nm") or "")
        rcept_dt = str(row.get("rcept_dt") or "")
        reprt_code = _infer_report_code(report_nm)
        if not reprt_code or not row.get("rcept_no"):
            continue
        records.append(FilingRecord(
            ticker=ticker,
            corp_code=str(row.get("corp_code") or ""),
            bsns_year=_infer_year(report_nm, rcept_dt),
            reprt_code=reprt_code,
            report_nm=report_nm,
            rcept_no=str(row.get("rcept_no")),
            rcept_dt=rcept_dt,
        ))
    return records


def _is_correction(report_nm: str) -> bool:
    return bool(re.search(r"\[(?:기재정정|첨부정정|첨부추가|정정|자진공시)\]|\((?:기재정정|첨부정정|첨부추가|정정)\)", report_nm or ""))


def _correction_pair(records: Iterable[FilingRecord], bsns_year: str, reprt_code: str) -> tuple[FilingRecord, FilingRecord] | None:
    groups: dict[str, list[FilingRecord]] = {}
    for record in records:
        if record.bsns_year != bsns_year or record.reprt_code != reprt_code:
            continue
        key = record.derived_chain_key
        if key:
            groups.setdefault(key, []).append(record)
    for group in groups.values():
        originals = [item for item in group if not _is_correction(item.report_nm)]
        corrections = [item for item in group if _is_correction(item.report_nm)]
        if originals and corrections:
            original = min(originals, key=lambda item: (item.parsed_date or date.max, item.rcept_no))
            correction = min(corrections, key=lambda item: (item.parsed_date or date.max, item.rcept_no))
            return original, correction
    return None


def _compact_row(row: dict[str, Any]) -> dict[str, Any]:
    fields = ("corp_code", "stock_code", "corp_name", "report_nm", "rcept_no", "rcept_dt", "flr_nm", "rm")
    return {key: row.get(key) for key in fields if key in row}


def _half_year_semantics(payload: dict[str, Any], ticker: str) -> dict[str, Any]:
    rows = _rows(payload)
    fields = sorted({key for row in rows for key in row})
    field_presence = {
        field: {
            "present_row_count": sum(field in row for row in rows),
            "non_blank_row_count": sum(bool(str(row.get(field) or "").strip()) for row in rows),
        }
        for field in (
            "thstrm_nm", "thstrm_amount", "thstrm_add_amount", "frmtrm_nm",
            "frmtrm_amount", "frmtrm_q_nm", "frmtrm_q_amount", "frmtrm_add_amount",
        )
    }
    samples = []
    for row in rows:
        if any(term in str(row.get("account_nm") or "") for term in ("매출", "영업이익", "당기순이익")):
            samples.append({
                key: row.get(key)
                for key in ("account_id", "account_nm", "sj_div", "thstrm_nm", "thstrm_amount", "thstrm_add_amount", "frmtrm_nm", "frmtrm_amount")
            })
        if len(samples) >= 12:
            break
    return {
        "ticker": ticker,
        "status": _status_from_payload(payload),
        "classification": "PASS" if _status_from_payload(payload) == "000" else _error_classification(_status_from_payload(payload)),
        "row_count": len(rows),
        "observed_fields": fields,
        "field_presence": field_presence,
        "diagnostic_rows": samples,
    }


def _load_access_summary() -> dict[str, Any]:
    return json.loads((ACCESS_DIR / "opendart_api_access_summary.json").read_text(encoding="utf-8"))


def _mapping_diagnostics(access: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    diagnostics: dict[str, Any] = {}
    family_results: dict[str, Any] = {}
    for ticker in TICKERS:
        company = access.get("company_api", {}).get(ticker, {})
        annual = access.get("financial_statement_2025_annual", {}).get(ticker, {})
        company_fields = company.get("selected_fields", {})
        rows = [
            {**row, "statement_family": map_statement_family(row.get("sj_div"))}
            for row in annual.get("diagnostic_account_rows", [])
        ]
        family = classify_company_family(company_fields, rows)
        family_results[ticker] = family
        metrics = ("assets", "liabilities", "equity", "revenue", "operating_income", "net_income", "operating_cash_flow")
        diagnostics[ticker] = {
            "ticker": ticker,
            "name": TICKER_NAMES[ticker],
            "company_family": family["company_family"],
            "family_evidence": family["evidence"],
            "metrics": [resolve_core_account(rows, metric, family["company_family"]) for metric in metrics],
            "duplicate_account_cases": _duplicate_cases(rows),
        }
    return diagnostics, family_results


def _duplicate_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        account_id = str(row.get("account_id") or "")
        if account_id:
            by_id.setdefault(account_id, []).append(row)
    cases = []
    for account_id, items in sorted(by_id.items()):
        if len(items) > 1:
            cases.append({
                "account_id": account_id,
                "match_count": len(items),
                "raw_sj_div_values": sorted({str(item.get("sj_div") or "") for item in items}),
                "statement_families": sorted({str(item.get("statement_family") or "") for item in items}),
            })
    return cases


def _statement_contract(family_results: dict[str, Any]) -> dict[str, Any]:
    return {
        "work_id": WORK_ID,
        "raw_sj_div_to_statement_family": {
            "BS": "BALANCE_SHEET",
            "IS": "INCOME_STATEMENT",
            "CIS": "INCOME_STATEMENT",
            "CF": "CASH_FLOW",
            "SCE": "EQUITY_CHANGES",
        },
        "raw_sj_div_preserved": True,
        "statement_family_selection": "Metric candidates are filtered by canonical statement family; SCE is never used for BS/IS metrics.",
        "fs_div_contract": {
            "preferred": "CFS",
            "fallback": "OFS only when CFS status is 013 and OFS status is 000 with usable rows",
            "api_error_rule": "CFS API errors fail closed; no silent OFS fallback",
            "basis_atomicity": "One report-level fs_div basis; account-level CFS/OFS mixing prohibited",
        },
        "company_family_contract": {
            "enum": ["NON_FINANCIAL", "FINANCIAL", "UNKNOWN"],
            "fixture_results": family_results,
            "classification_scope": "Evidence-based representative fixture only; not a full KRX industry engine",
        },
        "duplicate_account_contract": {
            "required_context": ["statement_family", "raw_sj_div", "account_id", "account_nm", "account_detail", "period_context", "ord"],
            "first_match_forbidden": True,
            "tie_behavior": "AMBIGUOUS / fail closed",
        },
        "report_codes": {"11013": "Q1", "11012": "HALF_YEAR", "11014": "Q3", "11011": "ANNUAL"},
        "canonical_metric_candidates": {
            "NON_FINANCIAL": ["assets", "liabilities", "equity", "revenue", "operating_income", "net_income", "operating_cash_flow"],
            "FINANCIAL": ["assets", "liabilities", "equity", "net_income", "operating_cash_flow"],
        },
        "score_or_valuation_implemented": False,
    }


def _final_status(
    api_key_present: bool,
    xbrl_primary: dict[str, Any] | None,
    xbrl_repeat: dict[str, Any] | None,
    diagnostics: dict[str, Any],
    secret_leak_count: int,
    request_count: int,
) -> str:
    if not api_key_present:
        return "BLOCKED_OPENDART_API_KEY"
    if not xbrl_primary or xbrl_primary.get("zip_parse") != "PASS":
        return "OPENDART_XBRL_VALIDATION_FIX_REQUIRED"
    if not xbrl_repeat or xbrl_repeat.get("zip_parse") != "PASS":
        return "OPENDART_XBRL_VALIDATION_FIX_REQUIRED"
    if xbrl_primary.get("sha256") != xbrl_repeat.get("sha256"):
        return "OPENDART_XBRL_VALIDATION_FIX_REQUIRED"
    if secret_leak_count or request_count > 15:
        return "OPENDART_FUNDAMENTALS_ARCHITECTURE_FIX_REQUIRED"
    st = diagnostics.get("237690", {}).get("metrics", [])
    required = {item.get("metric") for item in st if item.get("resolution_status") == "RESOLVED"}
    if not {"revenue", "operating_income", "net_income"}.issubset(required):
        return "OPENDART_FUNDAMENTALS_ARCHITECTURE_FIX_REQUIRED"
    return "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ARCHITECTURE_REVIEW"


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    load_dotenv(ROOT / ".env", override=False)
    auth_key = os.getenv("OPENDART_API_KEY", "").strip()
    run_date = date.today().isoformat()
    request_audit: list[dict[str, Any]] = []
    access = _load_access_summary()
    corp_mapping = access.get("corp_code_mapping", {})
    list_results: dict[str, Any] = {}
    filing_selections: dict[str, Any] = {}
    correction_results: dict[str, Any] = {}
    records_by_ticker: dict[str, list[FilingRecord]] = {}
    xbrl_results: dict[str, Any] = {}
    half_year_results: dict[str, Any] = {}
    xbrl_primary: dict[str, Any] | None = None
    xbrl_repeat: dict[str, Any] | None = None

    if auth_key:
        for ticker in TICKERS:
            corp_code = str(corp_mapping.get(ticker, {}).get("corp_code") or "")
            payload = _request_json(
                LIST_ENDPOINT,
                {"corp_code": corp_code, "bgn_de": "20250101", "end_de": run_date.replace("-", ""), "page_no": "1", "page_count": "100"},
                auth_key,
                request_audit,
                f"list_{ticker}",
            )
            rows = _rows(payload)
            records = _filing_records(ticker, rows)
            # Samsung has a high disclosure volume; its 2025 annual filing can
            # fall outside the first 100 rows of the broad bounded window.
            # A single narrow filing-window probe keeps the request budget
            # bounded while making the representative annual fixture explicit.
            targeted_payload: dict[str, Any] | None = None
            if ticker == "005930" and not any(
                item.bsns_year == "2025" and item.reprt_code == "11011" for item in records
            ):
                targeted_payload = _request_json(
                    LIST_ENDPOINT,
                    {"corp_code": corp_code, "bgn_de": "20260301", "end_de": "20260430", "page_no": "1", "page_count": "100"},
                    auth_key,
                    request_audit,
                    "list_005930_2025_annual_window",
                )
                rows.extend(_rows(targeted_payload))
                deduped: dict[str, FilingRecord] = {}
                for item in _filing_records(ticker, rows):
                    deduped[item.rcept_no] = item
                records = list(deduped.values())
            records_by_ticker[ticker] = records
            selection = select_pit_filing(records, run_date, "2025", "11011")
            list_results[ticker] = {
                "status": _status_from_payload(payload),
                "classification": "PASS" if _status_from_payload(payload) == "000" else _error_classification(_status_from_payload(payload)),
                "row_count": len(rows),
                "filing_record_count": len(records),
                "sample_filings": [_compact_row(row) for row in rows[:8]],
                "targeted_annual_window": (
                    {
                        "status": _status_from_payload(targeted_payload),
                        "row_count": len(_rows(targeted_payload)),
                    }
                    if targeted_payload is not None
                    else None
                ),
            }
            filing_selections[ticker] = {
                "status": selection.status,
                "availability": selection.availability,
                "reason": selection.reason,
                "selected": selection.selected.__dict__ if selection.selected else None,
                "eligible_count": len(selection.eligible),
                "future_count": len(selection.future),
            }
            pair = _correction_pair(records, "2025", "11011")
            correction_results[ticker] = {
                "found": bool(pair),
                "original": pair[0].__dict__ if pair else None,
                "correction": pair[1].__dict__ if pair else None,
            }

        probe: FilingRecord | None = None
        samsung_candidates = [
            item for item in records_by_ticker.get("005930", [])
            if item.reprt_code == "11011" and item.bsns_year == "2025" and not _is_correction(item.report_nm)
        ]
        if samsung_candidates:
            probe = max(samsung_candidates, key=lambda item: (item.parsed_date or date.min, item.rcept_no))
        else:
            # If the high-volume Samsung window still misses the annual row,
            # use a bounded correction-pair original as the representative
            # filing-specific probe.  The pair itself remains diagnostic.
            for ticker in TICKERS:
                pair = correction_results.get(ticker)
                if pair and pair.get("found"):
                    probe = FilingRecord.from_mapping(pair["original"])
                    break
        if probe is not None:
            xbrl_primary = _request_xbrl(probe.rcept_no, probe.reprt_code, auth_key, request_audit, "xbrl_primary")
            xbrl_repeat = _request_xbrl(probe.rcept_no, probe.reprt_code, auth_key, request_audit, "xbrl_primary_repeat")
            xbrl_results["primary_filing"] = {
                "ticker": probe.ticker,
                "corp_code": probe.corp_code,
                "report_nm": probe.report_nm,
                "rcept_no": probe.rcept_no,
                "rcept_dt": probe.rcept_dt,
                "reprt_code": probe.reprt_code,
            }

        for ticker in ("005930", "237690"):
            corp_code = str(corp_mapping.get(ticker, {}).get("corp_code") or "")
            payload = _request_json(
                FINANCIAL_ENDPOINT,
                {"corp_code": corp_code, "bsns_year": "2026", "reprt_code": "11012", "fs_div": "CFS"},
                auth_key,
                request_audit,
                f"financial_2026_half_year_{ticker}",
            )
            half_year_results[ticker] = _half_year_semantics(payload, ticker)

        correction_pair = next((value for value in correction_results.values() if value.get("found")), None)
        if correction_pair:
            for label, filing in (("correction_original", correction_pair["original"]), ("correction_filing", correction_pair["correction"])):
                xbrl_results[label] = _request_xbrl(
                    filing["rcept_no"], filing["reprt_code"], auth_key, request_audit, f"xbrl_{label}"
                )

    diagnostics, family_results = _mapping_diagnostics(access)
    primary_filing = xbrl_results.get("primary_filing", {})
    pit_artifact: dict[str, Any] = {
        "work_id": WORK_ID,
        "run_date": run_date,
        "access_validation_authority_sha": ACCESS_VALIDATION_SHA,
        "pit_granularity": PIT_GRANULARITY,
        "current_latest_source": "fnlttSinglAcntAll.json (convenience/latest diagnostic only)",
        "historical_strict_pit_candidate": "Filing Registry (list.json) + filing-specific fnlttXbrl.xml",
        "fnlttSinglAcntAll_strict_historical_ssot": False,
        "strict_pit_supported": bool(xbrl_primary and xbrl_repeat and xbrl_primary.get("zip_parse") == "PASS" and xbrl_primary.get("sha256") == xbrl_repeat.get("sha256")),
        "strict_pit_support_scope": "Filing-specific source feasibility proven; full correction-chain resolver remains a later implementation boundary",
        "filing_specific_retrieval_proven": bool(xbrl_primary and xbrl_primary.get("zip_parse") == "PASS"),
        "same_day_policy": "rcept_dt == as_of is AVAILABLE_AT_EOD; DAILY_EOD_KST information set",
        "revision_policy": "Eligible filings are rcept_dt <= as_of; latest eligible filing within an identified chain; unknown chain identity fails closed",
        "future_filing_policy": "rcept_dt > as_of is FUTURE_FORBIDDEN",
        "filing_registry": list_results,
        "pit_selection": filing_selections,
        "filing_specific_xbrl_probe": {
            "primary_filing": primary_filing,
            "first_request": xbrl_primary,
            "repeat_request": xbrl_repeat,
            "deterministic_sha_match": bool(xbrl_primary and xbrl_repeat and xbrl_primary.get("sha256") == xbrl_repeat.get("sha256")),
            "correction_pair": correction_results,
            "correction_xbrl": {key: value for key, value in xbrl_results.items() if key.startswith("correction_")},
        },
        "half_year_2026_field_semantics": half_year_results,
        "request_audit": request_audit,
        "total_http_requests": len(request_audit),
        "request_budget_max": 15,
        "request_budget_pass": len(request_audit) <= 15,
        "api_key_present": bool(auth_key),
        "secret_leak_count": 0,
    }
    statement_artifact = _statement_contract(family_results)
    mapping_artifact = {
        "work_id": WORK_ID,
        "source": "access_v01 annual 2025 CFS diagnostic rows",
        "diagnostics": diagnostics,
        "duplicate_account_cases_found": {
            ticker: value.get("duplicate_account_cases", []) for ticker, value in diagnostics.items()
        },
        "first_match_account_selection_used": False,
        "resolution_policy": "statement family + raw sj_div + account_id + account_nm + account_detail + ord; tied candidates fail closed",
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    paths = {
        "opendart_pit_source_validation.json": pit_artifact,
        "opendart_statement_contract.json": statement_artifact,
        "opendart_account_mapping_diagnostic.json": mapping_artifact,
    }
    for name, value in paths.items():
        _write_json(ARTIFACT_DIR / name, value)

    serialized_paths = [ARTIFACT_DIR / name for name in paths]
    leak_count = sum(path.read_text(encoding="utf-8").count(auth_key) for path in serialized_paths) if auth_key else 0
    pit_artifact["secret_leak_count"] = leak_count
    pit_artifact["final_status"] = _final_status(
        bool(auth_key), xbrl_primary, xbrl_repeat, diagnostics, leak_count, len(request_audit)
    )
    _write_json(ARTIFACT_DIR / "opendart_pit_source_validation.json", pit_artifact)

    manifest = {
        "work_id": WORK_ID,
        "artifact_directory": str(ARTIFACT_DIR.relative_to(ROOT)),
        "access_validation_authority_sha": ACCESS_VALIDATION_SHA,
        "files": {name: _sha256(ARTIFACT_DIR / name) for name in sorted(paths)},
        "raw_response_policy": "No raw XBRL ZIP/XML or full JSON persisted; metadata, samples, and hashes only",
        "secret_policy": "API key environment-only; request audit redacted",
        "total_http_requests": len(request_audit),
    }
    _write_json(ARTIFACT_DIR / "opendart_architecture_manifest.json", manifest)

    print(f"OPENDART_API_KEY_PRESENT={bool(auth_key)}")
    print(f"TOTAL_HTTP_REQUESTS={len(request_audit)}")
    print(f"XBRL_ZIP_PARSE={xbrl_primary.get('zip_parse') if xbrl_primary else 'NOT_RUN'}")
    print(f"FINAL_STATUS={pit_artifact['final_status']}")
    print(f"ARTIFACT_DIR={ARTIFACT_DIR.relative_to(ROOT)}")
    return 0 if pit_artifact["final_status"] == "READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ARCHITECTURE_REVIEW" else 1


if __name__ == "__main__":
    raise SystemExit(main())
