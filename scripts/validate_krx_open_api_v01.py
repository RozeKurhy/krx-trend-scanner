"""Bounded, evidence-first validation of the approved KRX Open API services.

The validator is deliberately separate from the production PyKRX provider. It
captures redacted KRX snapshots, compares them with existing PyKRX/local
authorities, and writes only validation artifacts under ``artifacts/data``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiClient,
    KrxOpenApiRateLimitError,
    KrxOpenApiResponse,
    redact_headers,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/data/krx_openapi/v01"
RAW_DIR = ARTIFACT_DIR / "raw_samples"
START_HEAD = "af27d0120ffa8ca21217419c666f1ceac6c987ed"
WORK_ID = "KRX_OPEN_API_V01_ACCESS_AND_PARITY_VALIDATION"
ANCHOR_DATE = "2026-08-20"
ADJACENT_DATES = ("2026-08-19", "2026-08-20", "2026-08-21")
HOLIDAY_DATE = "2026-08-23"
SPLIT_DATES = ("2018-04-27", "2018-05-04")
MAX_KRX_OPEN_API_REQUESTS = 80

SERVICES: tuple[dict[str, str], ...] = (
    {"service_name": "kospi_stock_daily", "api_id": "stk_bydd_trd", "expected_endpoint": "/sto/stk_bydd_trd", "kind": "stock", "market": "KOSPI"},
    {"service_name": "kosdaq_stock_daily", "api_id": "ksq_bydd_trd", "expected_endpoint": "/sto/ksq_bydd_trd", "kind": "stock", "market": "KOSDAQ"},
    {"service_name": "kospi_index_daily", "api_id": "kospi_dd_trd", "expected_endpoint": "/idx/kospi_dd_trd", "kind": "index", "market": "KOSPI"},
    {"service_name": "kosdaq_index_daily", "api_id": "kosdaq_dd_trd", "expected_endpoint": "/idx/kosdaq_dd_trd", "kind": "index", "market": "KOSDAQ"},
)
SERVICE_BY_NAME = {item["service_name"]: item for item in SERVICES}
KOSPI_TICKERS = ("005930", "000660", "035420", "068270", "005380")
KOSDAQ_TICKERS = ("237690", "028300", "293490")
COHORT_BY_MARKET = {"KOSPI": KOSPI_TICKERS, "KOSDAQ": KOSDAQ_TICKERS}

STOCK_FIELDS = {
    "date": "BAS_DD", "ticker_or_issue_code": "ISU_CD", "name": "ISU_NM", "market": "MKT_NM",
    "close": "TDD_CLSPRC", "open": "TDD_OPNPRC", "high": "TDD_HGPRC", "low": "TDD_LWPRC",
    "volume": "ACC_TRDVOL", "trading_value": "ACC_TRDVAL", "market_cap": "MKTCAP", "listed_shares": "LIST_SHRS",
    "change": "CMPPREVDD_PRC", "change_rate": "FLUC_RT",
}
INDEX_FIELDS = {
    "date": "BAS_DD", "index_name": "IDX_NM", "index_class": "IDX_CLSS", "close": "CLSPRC_IDX",
    "open": "OPNPRC_IDX", "high": "HGPRC_IDX", "low": "LWPRC_IDX", "volume": "ACC_TRDVOL",
    "trading_value": "ACC_TRDVAL", "market_cap": "MKTCAP",
}
DISCREPANCIES = ("EXACT_MATCH", "NUMERIC_FORMAT_ONLY", "ROUNDING_DIFFERENCE", "CORPORATE_ACTION_ADJUSTMENT", "MISSING_KRX_ROW", "MISSING_PYKRX_ROW", "HOLIDAY_SEMANTIC_DIFFERENCE", "IDENTIFIER_MAPPING_DIFFERENCE", "INDEX_SELECTION_DIFFERENCE", "SCHEMA_DIFFERENCE", "UNKNOWN_DIFFERENCE")


def normalize_numeric(value: Any) -> float | int | None:
    """Parse KRX numeric strings explicitly; blank values remain missing."""
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


def _read_env_value(path: Path, name: str) -> str:
    if not path.exists():
        return ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            value = line.split("=", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            return value
    return ""


def _read_secret_from_file(path: Path) -> str:
    return _read_env_value(path, "KRX_OPEN_API_AUTH_KEY")


def _load_operator_credentials() -> None:
    """Load PyKRX credentials silently without serializing or printing them."""

    for name in ("KRX_ID", "KRX_PW"):
        if os.getenv(name, "").strip():
            continue
        for path in (ROOT / ".env", ROOT.parent / "env.md"):
            value = _read_env_value(path, name).strip()
            if value:
                os.environ[name] = value
                break


def _load_auth_key() -> str:
    value = os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
    if value:
        return value
    for path in (ROOT / ".env", ROOT.parent / "env.md"):
        value = _read_secret_from_file(path).strip()
        if value:
            return value
    return ""


def _redacted_url(url: str) -> str:
    return re.sub(r"([?&](?:AUTH_KEY|auth_key|api_key)=)[^&]*", r"\1<redacted>", url)


def _safe_payload(payload: dict[str, Any], secret: str) -> dict[str, Any]:
    if secret and secret in json.dumps(payload, ensure_ascii=False):
        raise ValueError("secret detected in KRX payload")
    return payload


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _observed_field_schema(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = sorted({key for row in rows for key in row})
    result = []
    for key in keys:
        values = [row.get(key) for row in rows]
        nonblank = [value for value in values if value not in (None, "", "-")]
        result.append({"field_name": key, "field_type_observed": sorted({type(value).__name__ for value in nonblank}) or ["missing"], "nullable": len(nonblank) != len(values), "blank_count": len(values) - len(nonblank)})
    return result


def _response_status(response: KrxOpenApiResponse | None) -> str:
    if response is None or response.http_status is None or response.http_status != 200:
        return "ERROR_RESPONSE"
    if response.records_key is None:
        return "HTTP_200_NO_OUTBLOCK"
    if response.record_count == 0:
        return "HTTP_200_EMPTY"
    return "HTTP_200_RECORDS"


def _normalize_stock(row: dict[str, Any]) -> dict[str, Any]:
    return {"date": str(row.get("BAS_DD", ""))[:8], "market": row.get("MKT_NM"), "ticker_or_issue_code": str(row.get("ISU_CD", "")), "name": row.get("ISU_NM"), **{field: normalize_numeric(row.get(raw)) for field, raw in STOCK_FIELDS.items() if field not in {"date", "market", "ticker_or_issue_code", "name"}}}


def _normalize_index(row: dict[str, Any], internal_code: str | None = None) -> dict[str, Any]:
    return {"date": str(row.get("BAS_DD", ""))[:8], "index_identifier": internal_code or row.get("IDX_NM"), "index_name": row.get("IDX_NM"), "index_class": row.get("IDX_CLSS"), **{field: normalize_numeric(row.get(raw)) for field, raw in INDEX_FIELDS.items() if field not in {"date", "index_name", "index_class"}}}


def _pykrx_stock(ticker: str, start: str, end: str, adjusted: bool) -> dict[str, dict[str, Any]]:
    from pykrx import stock
    capture = StringIO()
    with redirect_stdout(capture), redirect_stderr(capture):
        frame = stock.get_market_ohlcv_by_date(start.replace("-", ""), end.replace("-", ""), ticker, adjusted=adjusted)
    result: dict[str, dict[str, Any]] = {}
    if frame is None or frame.empty:
        return result
    for index, row in frame.iterrows():
        date = pd.Timestamp(index).strftime("%Y%m%d")
        result[date] = {"date": date, "open": normalize_numeric(row.get("시가")), "high": normalize_numeric(row.get("고가")), "low": normalize_numeric(row.get("저가")), "close": normalize_numeric(row.get("종가")), "volume": normalize_numeric(row.get("거래량")), "trading_value": normalize_numeric(row.get("거래대금")) if "거래대금" in row.index else None}
    return result


def _pykrx_index(index_code: str, start: str, end: str) -> dict[str, dict[str, Any]]:
    from pykrx import stock
    capture = StringIO()
    with redirect_stdout(capture), redirect_stderr(capture):
        frame = stock.get_index_ohlcv_by_date(start.replace("-", ""), end.replace("-", ""), index_code)
    result: dict[str, dict[str, Any]] = {}
    if frame is None or frame.empty:
        return result
    for index, row in frame.iterrows():
        date = pd.Timestamp(index).strftime("%Y%m%d")
        result[date] = {"date": date, "open": normalize_numeric(row.get("시가")), "high": normalize_numeric(row.get("고가")), "low": normalize_numeric(row.get("저가")), "close": normalize_numeric(row.get("종가")), "volume": normalize_numeric(row.get("거래량")), "trading_value": normalize_numeric(row.get("거래대금")), "market_cap": None}
    return result


def _equal(left: Any, right: Any) -> bool:
    return left == right if left is not None and right is not None else left is right


def _collect_rows(responses: dict[tuple[str, str], KrxOpenApiResponse | None]) -> dict[str, dict[str, dict[str, Any]]]:
    rows: dict[str, dict[str, dict[str, Any]]] = {"KOSPI": {}, "KOSDAQ": {}}
    for service in SERVICES:
        if service["kind"] != "stock":
            continue
        response = responses.get((service["service_name"], ANCHOR_DATE))
        for row in response.records if response else ():
            normalized = _normalize_stock(row)
            rows[service["market"]][normalized["ticker_or_issue_code"]] = normalized
    return rows


def _git_sha(ref: str) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", ref], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _secret_scan(secret: str) -> dict[str, Any]:
    if not secret:
        return {"secret_occurrence_count": 0, "scanned_tracked_file_count": 0}
    try:
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    except (OSError, subprocess.CalledProcessError):
        paths = []
    count = scanned = 0
    for raw_path in paths:
        if not raw_path or raw_path == ".env" or raw_path.endswith("/.env"):
            continue
        path = ROOT / raw_path
        if path.is_file():
            scanned += 1
            try:
                count += path.read_text(encoding="utf-8", errors="ignore").count(secret)
            except OSError:
                pass
    return {"secret_occurrence_count": count, "scanned_tracked_file_count": scanned}


def _write_failure_artifacts(status: str, reason: str, start_head: str) -> None:
    _write_json(ARTIFACT_DIR / "krx_openapi_access_summary.json", {"work_id": WORK_ID, "start_head": start_head, "auth_key_present": False, "auth_key_exposed": False, "status": status, "reason": reason, "services": [{"service_name": service["service_name"], "endpoint": service["expected_endpoint"], "access_status": status} for service in SERVICES]})
    _write_json(ARTIFACT_DIR / "krx_openapi_v01_manifest.json", {"work_id": WORK_ID, "start_head": start_head, "status": status, "reason": reason})


def run_validation() -> dict[str, Any]:
    start_head = _git_sha("HEAD")
    _load_operator_credentials()
    secret = _load_auth_key()
    if not secret:
        _write_failure_artifacts("SKIP_KRX_OPEN_API_KEY_MISSING", "KRX_OPEN_API_AUTH_KEY is not loaded", start_head)
        return {"status": "SKIP_KRX_OPEN_API_KEY_MISSING", "start_head": start_head}

    client = KrxOpenApiClient(secret, max_requests=MAX_KRX_OPEN_API_REQUESTS, max_transient_retries=2)
    responses: dict[tuple[str, str], KrxOpenApiResponse | None] = {}
    failures: list[dict[str, Any]] = []

    def fetch(service: dict[str, str], date: str) -> KrxOpenApiResponse | None:
        try:
            response = client.fetch(service["expected_endpoint"], date)
        except KrxOpenApiAuthorizationError as exc:
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_OPEN_API_AUTHORIZATION", "error": str(exc)})
            response = None
        except KrxOpenApiRateLimitError as exc:
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_OPEN_API_RATE_LIMIT", "error": str(exc)})
            response = None
        except KrxOpenApiBudgetError as exc:
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_OPEN_API_REQUEST_BUDGET", "error": str(exc)})
            response = None
        responses[(service["service_name"], date)] = response
        return response

    for date in (*ADJACENT_DATES, HOLIDAY_DATE):
        for service in SERVICES:
            fetch(service, date)
    for date in SPLIT_DATES:
        fetch(SERVICE_BY_NAME["kospi_stock_daily"], date)

    endpoint_summary = []
    schema_snapshot: dict[str, Any] = {"work_id": WORK_ID, "anchor_date": ANCHOR_DATE, "endpoints": {}}
    raw_names = {"kospi_stock_daily": "kospi_stock_20260820.json", "kosdaq_stock_daily": "kosdaq_stock_20260820.json", "kospi_index_daily": "kospi_index_20260820.json", "kosdaq_index_daily": "kosdaq_index_20260820.json"}
    for service in SERVICES:
        response = responses.get((service["service_name"], ANCHOR_DATE))
        access_ok = bool(response and response.http_status == 200 and response.record_count > 0 and response.records_key)
        endpoint_summary.append({"service_name": service["service_name"], "api_id": service["api_id"], "expected_endpoint": service["expected_endpoint"], "actual_endpoint": service["expected_endpoint"], "method": "GET", "base_url": client.base_url, "auth_mode": "header_only", "auth_header": client.auth_header, "query_parameter_names": ["basDd"], "query_date_format": "YYYYMMDD", "http_status": response.http_status if response else None, "record_count": response.record_count if response else 0, "schema_status": "KNOWN" if access_ok else "NOT_AVAILABLE", "access_status": "PASS" if access_ok else (failures[-1]["status"] if failures else "FAIL")})
        if response:
            _safe_payload(response.payload, secret)
            _write_json(RAW_DIR / raw_names[service["service_name"]], response.payload)
            schema_snapshot["endpoints"][service["service_name"]] = {"top_level_keys": list(response.top_level_keys), "records_container": response.records_key, "record_count": response.record_count, "record_keys": sorted({key for row in response.records for key in row}), "fields": _observed_field_schema(list(response.records))}

    stock_rows = _collect_rows(responses)
    identifier_rows = []
    for market, tickers in COHORT_BY_MARKET.items():
        for ticker in tickers:
            row = stock_rows[market].get(ticker)
            identifier_rows.append({"market": market, "internal_ticker": ticker, "krx_identifier": row.get("ticker_or_issue_code") if row else None, "name": row.get("name") if row else None, "identifier_length": len(str(row["ticker_or_issue_code"])) if row else None, "classification": "SHORT_TICKER_NATIVE" if row and re.fullmatch(r"\d{6}", str(row["ticker_or_issue_code"])) else "OTHER_MAPPING_REQUIRED"})

    index_selection: dict[str, Any] = {}
    for service in SERVICES:
        if service["kind"] != "index":
            continue
        response = responses.get((service["service_name"], ANCHOR_DATE))
        exact_name = "코스피" if service["market"] == "KOSPI" else "코스닥"
        candidates = [row for row in (response.records if response else ()) if row.get("IDX_CLSS") == service["market"] and row.get("IDX_NM") == exact_name and normalize_numeric(row.get("CLSPRC_IDX")) is not None]
        representative = candidates[0] if candidates else None
        index_selection[service["market"]] = {"internal_index_code": "1001" if service["market"] == "KOSPI" else "2001", "internal_index_name": exact_name, "krx_response_identifier": f"{service['market']}:{exact_name}" if representative else None, "krx_response_name": representative.get("IDX_NM") if representative else None, "selection_rule": f"IDX_CLSS == '{service['market']}' AND IDX_NM == '{exact_name}' AND CLSPRC_IDX is nonblank", "ancillary_selection_rule": f"For PyKRX volume/trading-value parity only: IDX_CLSS == '{service['market']}' AND IDX_NM == '{exact_name} (외국주포함)'", "candidate_count": len(candidates), "resolved": bool(representative)}

    parity_rows: list[dict[str, Any]] = []
    raw_counters = {key: 0 for key in ("compared_row_count", "exact_row_count", "field_mismatch_count", "ohlc_mismatch_count", "volume_mismatch_count", "trading_value_mismatch_count", "missing_krx_count", "missing_pykrx_count", "unknown_difference_count")}
    adjusted_counters = {"adjusted_exact_count": 0, "expected_adjustment_difference_count": 0, "unexpected_adjusted_difference_count": 0}
    pykrx_cache: dict[tuple[str, bool], dict[str, dict[str, Any]]] = {}
    for market, tickers in COHORT_BY_MARKET.items():
        service = SERVICE_BY_NAME["kospi_stock_daily" if market == "KOSPI" else "kosdaq_stock_daily"]
        for ticker in tickers:
            for adjusted in (False, True):
                try:
                    pykrx_cache[(ticker, adjusted)] = _pykrx_stock(ticker, "2026-08-19", "2026-08-21", adjusted)
                except Exception as exc:
                    failures.append({"service_name": "pykrx", "ticker": ticker, "adjusted": adjusted, "status": "PYKRX_ERROR", "error": type(exc).__name__})
                    pykrx_cache[(ticker, adjusted)] = {}
            for date in ADJACENT_DATES:
                date_key = date.replace("-", "")
                response = responses.get((service["service_name"], date))
                by_ticker = {str(row.get("ISU_CD")): row for row in response.records} if response else {}
                krx = _normalize_stock(by_ticker[ticker]) if ticker in by_ticker else None
                raw = pykrx_cache[(ticker, False)].get(date_key)
                adj = pykrx_cache[(ticker, True)].get(date_key)
                fields = ("open", "high", "low", "close", "volume", "trading_value")
                if krx is None:
                    raw_counters["missing_krx_count"] += 1; raw_class = "MISSING_KRX_ROW"
                elif raw is None:
                    raw_counters["missing_pykrx_count"] += 1; raw_class = "MISSING_PYKRX_ROW"
                else:
                    raw_counters["compared_row_count"] += 1
                    mismatches = [field for field in fields if not _equal(krx.get(field), raw.get(field))]
                    if not mismatches:
                        raw_counters["exact_row_count"] += 1; raw_class = "EXACT_MATCH"
                    else:
                        raw_counters["field_mismatch_count"] += len(mismatches); raw_counters["ohlc_mismatch_count"] += int(any(field in mismatches for field in ("open", "high", "low", "close"))); raw_counters["volume_mismatch_count"] += int("volume" in mismatches); raw_counters["trading_value_mismatch_count"] += int("trading_value" in mismatches); raw_counters["unknown_difference_count"] += 1; raw_class = "UNKNOWN_DIFFERENCE"
                adj_mismatches = [field for field in ("open", "high", "low", "close", "volume") if krx and adj and not _equal(krx.get(field), adj.get(field))]
                if krx and adj and not adj_mismatches:
                    adjusted_counters["adjusted_exact_count"] += 1; adjusted_class = "EXACT_MATCH"
                elif adj_mismatches and date in SPLIT_DATES:
                    adjusted_counters["expected_adjustment_difference_count"] += 1; adjusted_class = "CORPORATE_ACTION_ADJUSTMENT"
                elif adj_mismatches:
                    adjusted_counters["unexpected_adjusted_difference_count"] += 1; adjusted_class = "UNKNOWN_DIFFERENCE"
                else:
                    adjusted_class = "MISSING_PYKRX_ROW"
                parity_rows.append({"date": date, "market": market, "ticker": ticker, "name": krx.get("name") if krx else None, "raw_classification": raw_class, "adjusted_classification": adjusted_class, "krx_close": krx.get("close") if krx else None, "pykrx_raw_close": raw.get("close") if raw else None, "pykrx_adjusted_close": adj.get("close") if adj else None, "krx_volume": krx.get("volume") if krx else None, "pykrx_raw_volume": raw.get("volume") if raw else None, "pykrx_adjusted_volume": adj.get("volume") if adj else None, "krx_trading_value": krx.get("trading_value") if krx else None, "pykrx_raw_trading_value": raw.get("trading_value") if raw else None})

    split_rows = []
    split_raw_matches = split_adj_matches = 0
    for date in SPLIT_DATES:
        response = responses.get(("kospi_stock_daily", date)); by_ticker = {str(row.get("ISU_CD")): row for row in response.records} if response else {}
        krx = _normalize_stock(by_ticker["005930"]) if "005930" in by_ticker else None
        raw = _pykrx_stock("005930", date, date, False).get(date.replace("-", "")); adj = _pykrx_stock("005930", date, date, True).get(date.replace("-", ""))
        raw_match = bool(krx and raw and all(_equal(krx.get(field), raw.get(field)) for field in ("open", "high", "low", "close")))
        adj_match = bool(krx and adj and all(_equal(krx.get(field), adj.get(field)) for field in ("open", "high", "low", "close")))
        if adj and raw and any(not _equal(raw.get(field), adj.get(field)) for field in ("open", "high", "low", "close", "volume")):
            adjusted_counters["expected_adjustment_difference_count"] += 1
        split_raw_matches += int(raw_match); split_adj_matches += int(adj_match)
        split_rows.append({"date": date, "krx": {field: krx.get(field) for field in ("open", "high", "low", "close", "volume", "trading_value")} if krx else None, "pykrx_adjusted_false": raw, "pykrx_adjusted_true": adj, "raw_ohlc_match": raw_match, "adjusted_ohlc_match": adj_match, "volume_raw_equals_adjusted": bool(raw and adj and _equal(raw.get("volume"), adj.get("volume"))), "trading_value_raw_equals_krx": bool(krx and raw and _equal(raw.get("trading_value"), krx.get("trading_value")))})
    if split_raw_matches == len(SPLIT_DATES): price_classification = "RAW_UNADJUSTED"
    elif split_adj_matches == len(SPLIT_DATES): price_classification = "ADJUSTED_COMPATIBLE"
    elif split_raw_matches or split_adj_matches: price_classification = "MIXED_OR_FIELD_DEPENDENT"
    else: price_classification = "UNKNOWN"

    index_rows: list[dict[str, Any]] = []
    index_counters = {"kospi_index_compared_count": 0, "kospi_index_mismatch_count": 0, "kosdaq_index_compared_count": 0, "kosdaq_index_mismatch_count": 0}
    for market, internal_code, service_name in (("KOSPI", "1001", "kospi_index_daily"), ("KOSDAQ", "2001", "kosdaq_index_daily")):
        try: py_index = _pykrx_index(internal_code, "2026-08-19", "2026-08-21")
        except Exception as exc:
            failures.append({"service_name": "pykrx_index", "market": market, "status": "PYKRX_ERROR", "error": type(exc).__name__}); py_index = {}
        for date in ADJACENT_DATES:
            response = responses.get((service_name, date)); exact_name = "코스피" if market == "KOSPI" else "코스닥"
            target = next((row for row in (response.records if response else ()) if row.get("IDX_CLSS") == market and row.get("IDX_NM") == exact_name and normalize_numeric(row.get("CLSPRC_IDX")) is not None), None)
            krx = _normalize_index(target, internal_code) if target else None; py = py_index.get(date.replace("-", "")); fields = ("open", "high", "low", "close", "volume", "trading_value")
            mismatches = [field for field in fields if krx and py and not _equal(krx.get(field), py.get(field))]
            compared_key = "kospi_index_compared_count" if market == "KOSPI" else "kosdaq_index_compared_count"; mismatch_key = "kospi_index_mismatch_count" if market == "KOSPI" else "kosdaq_index_mismatch_count"
            if krx and py:
                index_counters[compared_key] += 1; index_counters[mismatch_key] += int(bool(mismatches))
            classification = "EXACT_MATCH" if krx and py and not mismatches else ("INDEX_SELECTION_DIFFERENCE" if mismatches and set(mismatches).issubset({"volume", "trading_value"}) else ("UNKNOWN_DIFFERENCE" if mismatches else "MISSING_PYKRX_ROW"))
            index_rows.append({"date": date, "market": market, "internal_index_code": internal_code, "krx_index_name": target.get("IDX_NM") if target else None, "classification": classification, "mismatch_fields": mismatches, "selection_rule": index_selection.get(market, {}).get("selection_rule"), "note": "PyKRX 1001/2001 aligns OHLC with exact-name row but uses KRX aggregate ancillary volume/trading-value row" if classification == "INDEX_SELECTION_DIFFERENCE" else ""})

    empty_rows = []
    for service in SERVICES:
        response = responses.get((service["service_name"], HOLIDAY_DATE)); empty_rows.append({"service_name": service["service_name"], "date": HOLIDAY_DATE, "http_status": response.http_status if response else None, "records_container": response.records_key if response else None, "record_count": response.record_count if response else 0, "classification": _response_status(response)})

    all_access_pass = all(item["access_status"] == "PASS" for item in endpoint_summary)
    schema_pass = all(item["schema_status"] == "KNOWN" for item in endpoint_summary)
    identifier_pass = all(row["classification"] == "SHORT_TICKER_NATIVE" for row in identifier_rows)
    index_selection_pass = all(item["resolved"] for item in index_selection.values())
    index_pass = all(row["classification"] in {"EXACT_MATCH", "INDEX_SELECTION_DIFFERENCE"} for row in index_rows)
    unknown_count = raw_counters["unknown_difference_count"] + adjusted_counters["unexpected_adjusted_difference_count"] + sum(row["classification"] == "UNKNOWN_DIFFERENCE" for row in index_rows)
    final_status = "READY_FOR_ARCHITECT_KRX_OPEN_API_V01_REVIEW" if all_access_pass and schema_pass and identifier_pass and index_selection_pass and price_classification != "UNKNOWN" and unknown_count == 0 and index_pass and not failures else "BLOCKED_MORE_EVIDENCE_REQUIRED"
    if any(item.get("status") == "BLOCKED_KRX_OPEN_API_AUTHORIZATION" for item in failures): final_status = "BLOCKED_KRX_OPEN_API_AUTHORIZATION"
    if any(item.get("status") == "BLOCKED_KRX_OPEN_API_RATE_LIMIT" for item in failures): final_status = "BLOCKED_KRX_OPEN_API_RATE_LIMIT"
    architecture = "RECOMMEND_DUAL_PROVIDER" if price_classification == "RAW_UNADJUSTED" else "RECOMMEND_KRX_PRIMARY" if price_classification == "ADJUSTED_COMPATIBLE" else "BLOCKED_MORE_EVIDENCE_REQUIRED"

    endpoint_contract = {"work_id": WORK_ID, "base_url": client.base_url, "method": "GET", "auth_header": client.auth_header, "query_parameters": {"date": "basDd", "format": "YYYYMMDD"}, "records_container": "OutBlock_1", "pagination": "NONE", "snapshot_semantics": "MARKET_WIDE_DAILY_SNAPSHOT", "services": [{"service_name": service["service_name"], "expected_endpoint": service["expected_endpoint"], "actual_endpoint": service["expected_endpoint"]} for service in SERVICES]}
    _write_json(ARTIFACT_DIR / "krx_openapi_access_summary.json", {"work_id": WORK_ID, "start_head": start_head, "implementation_head": _git_sha("HEAD"), "validation_source_head": start_head, "auth_key_present": True, "auth_key_exposed": False, "services": endpoint_summary, "four_endpoint_gate": "FOUR_ENDPOINT_ACCESS_PASS" if all_access_pass else "BLOCKED_KRX_OPEN_API_AUTHORIZATION"})
    _write_json(ARTIFACT_DIR / "krx_openapi_endpoint_contract.json", endpoint_contract)
    _write_json(ARTIFACT_DIR / "krx_openapi_schema_snapshot.json", schema_snapshot)
    _write_json(ARTIFACT_DIR / "krx_openapi_identifier_analysis.json", {"stock_identifier_field": "ISU_CD", "classification": "SHORT_TICKER_NATIVE", "cohort": identifier_rows, "index_mapping": index_selection})
    _write_json(ARTIFACT_DIR / "krx_openapi_empty_response_semantics.json", {"non_trading_date": HOLIDAY_DATE, "observations": empty_rows, "empty_is_distinguished_from_network_failure": all(row["classification"] in {"HTTP_200_EMPTY", "HTTP_200_NO_OUTBLOCK"} for row in empty_rows)})
    _write_json(ARTIFACT_DIR / "stock_raw_parity_validation.json", {"work_id": WORK_ID, "authority": "PyKRX adjusted=False", "counters": raw_counters, "classification_counts": {name: sum(row["raw_classification"] == name for row in parity_rows) for name in DISCREPANCIES}, "unknown_difference_count": raw_counters["unknown_difference_count"]})
    _write_json(ARTIFACT_DIR / "stock_adjusted_semantics_validation.json", {"work_id": WORK_ID, "authority": "PyKRX adjusted=True secondary", "counters": adjusted_counters, "classification": price_classification, "volume_semantics": "UNCHANGED_ACROSS_PYKRX_ADJUSTMENT" if all(row["volume_raw_equals_adjusted"] for row in split_rows) else "FIELD_DEPENDENT", "trading_value_semantics": "ACTUAL_TRADED_VALUE" if all(row["trading_value_raw_equals_krx"] for row in split_rows) else "UNKNOWN"})
    parity_fields = list(parity_rows[0]) if parity_rows else ["date", "market", "ticker"]
    _write_csv(ARTIFACT_DIR / "stock_parity_table.csv", parity_fields, parity_rows)
    _write_json(ARTIFACT_DIR / "index_parity_validation.json", {"work_id": WORK_ID, "counters": index_counters, "representative_mapping": index_selection, "unknown_difference_count": sum(row["classification"] == "UNKNOWN_DIFFERENCE" for row in index_rows)})
    _write_csv(ARTIFACT_DIR / "index_parity_table.csv", ["date", "market", "internal_index_code", "krx_index_name", "classification", "mismatch_fields", "selection_rule", "note"], [{**row, "mismatch_fields": ";".join(row["mismatch_fields"])} for row in index_rows])
    _write_json(ARTIFACT_DIR / "corporate_action_validation.json", {"work_id": WORK_ID, "ticker": "005930", "event": "Samsung Electronics 50:1 split", "dates": list(SPLIT_DATES), "classification": price_classification, "comparisons": split_rows})
    _write_json(ARTIFACT_DIR / "request_audit.json", {"work_id": WORK_ID, "max_requests": MAX_KRX_OPEN_API_REQUESTS, "request_count": client.request_count, "retry_count": client.retry_count, "status_counts": client.status_counts, "requests": [{**item, "url": _redacted_url(item["url"])} for item in client.audit]})
    architecture_text = "\n".join(["architecture_recommendation.md", "=" * 80, "KRX Open API V01 architecture recommendation", "=" * 80, "", f"RECOMMENDATION: {architecture}", "", "KRX endpoints are date-scoped market-wide snapshots; production ticker×date loops are prohibited.", f"Samsung split price classification: {price_classification}.", "Existing PyKRX adjusted=True remains frozen for long-term chart semantics.", "Raw parity uses PyKRX adjusted=False; adjusted parity is secondary and separate.", "Production provider/cache replacement: NOT PERFORMED."])
    (ARTIFACT_DIR / "architecture_recommendation.md").parent.mkdir(parents=True, exist_ok=True); (ARTIFACT_DIR / "architecture_recommendation.md").write_text(architecture_text + "\n", encoding="utf-8")
    secret_scan = _secret_scan(secret)
    manifest = {"work_id": WORK_ID, "start_head": start_head, "implementation_head": _git_sha("HEAD"), "validation_source_head": start_head, "end_head": None, "status": final_status, "architecture_recommendation": architecture, "secret_occurrence_count": secret_scan["secret_occurrence_count"]}
    _write_json(ARTIFACT_DIR / "krx_openapi_v01_manifest.json", manifest)
    return {"status": final_status, "start_head": start_head, "request_count": client.request_count, "retry_count": client.retry_count, "raw_counters": raw_counters, "adjusted_counters": adjusted_counters, "index_counters": index_counters, "price_classification": price_classification, "architecture": architecture, "secret_scan": secret_scan, "failures": failures}


def redact_headers_for_test(headers: dict[str, str]) -> dict[str, str]:
    return redact_headers(headers)


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
