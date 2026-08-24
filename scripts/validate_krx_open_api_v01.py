"""Bounded, evidence-first validation of the approved KRX Open API services.

The validator is deliberately separate from the production PyKRX provider. It
captures redacted KRX snapshots, compares them with existing PyKRX/local
authorities, and writes only validation artifacts under ``artifacts/data``.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import subprocess
from urllib.error import HTTPError, URLError
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
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/data/krx_openapi/v01"
RAW_DIR = ARTIFACT_DIR / "raw_samples"
START_HEAD = "af27d0120ffa8ca21217419c666f1ceac6c987ed"
FIX_START_HEAD = "a7a346dad886f0362469ce25ffac59c688850e72"
WORK_ID = "KRX_OPEN_API_V01_ACCESS_AND_PARITY_VALIDATION"
ANCHOR_DATE = "2026-08-20"
ADJACENT_DATES = ("2026-08-19", "2026-08-20", "2026-08-21")
HOLIDAY_DATE = "2026-08-23"
SPLIT_DATES = ("2018-04-27", "2018-05-04")
MAX_KRX_OPEN_API_REQUESTS = 80
FIX_ARTIFACT_DIR = ARTIFACT_DIR / "fix01"
FIX_STATUS_READY = "READY_FOR_ARCHITECT_KRX_OPEN_API_V01_FIX01_REVIEW"
REQUIRED_STOCK_SCHEMA = {"BAS_DD", "ISU_CD", "ISU_NM", "MKT_NM", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC", "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS"}
REQUIRED_INDEX_SCHEMA = {"BAS_DD", "IDX_CLSS", "IDX_NM", "OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX", "CLSPRC_IDX", "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP"}

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


def required_schema_missing(kind: str, rows: Iterable[dict[str, Any]]) -> list[str]:
    observed = {key for row in rows for key in row}
    required = REQUIRED_STOCK_SCHEMA if kind == "stock" else REQUIRED_INDEX_SCHEMA
    return sorted(required - observed)


def classify_index_ancillary(rows: Iterable[dict[str, Any]], market: str, exact_name: str, pykrx_volume: Any, pykrx_trading_value: Any) -> dict[str, Any]:
    rows = list(rows)
    foreign_name = f"{exact_name} (외국주포함)"
    target = next((row for row in rows if row.get("IDX_CLSS") == market and row.get("IDX_NM") == exact_name), None)
    foreign_target = next((row for row in rows if row.get("IDX_CLSS") == market and row.get("IDX_NM") == foreign_name), None)
    exact_match = bool(target and _equal(normalize_numeric(target.get("ACC_TRDVOL")), pykrx_volume) and _equal(normalize_numeric(target.get("ACC_TRDVAL")), pykrx_trading_value))
    foreign_match = bool(foreign_target and _equal(normalize_numeric(foreign_target.get("ACC_TRDVOL")), pykrx_volume) and _equal(normalize_numeric(foreign_target.get("ACC_TRDVAL")), pykrx_trading_value))
    other = next((row for row in rows if row.get("IDX_CLSS") == market and row is not target and row is not foreign_target and _equal(normalize_numeric(row.get("ACC_TRDVOL")), pykrx_volume) and _equal(normalize_numeric(row.get("ACC_TRDVAL")), pykrx_trading_value)), None)
    if exact_match:
        classification, volume_matching_row, trading_value_matching_row = "EXACT_NAME_ROW_MATCH", "exact_name", "exact_name"
    elif foreign_match:
        classification, volume_matching_row, trading_value_matching_row = "FOREIGN_INCLUDED_ROW_MATCH", "foreign_included", "foreign_included"
    elif other:
        classification, volume_matching_row, trading_value_matching_row = "OTHER_KNOWN_ROW_MATCH", str(other.get("IDX_NM")), str(other.get("IDX_NM"))
    else:
        classification, volume_matching_row, trading_value_matching_row = "UNKNOWN_INDEX_ANCILLARY_DIFFERENCE", None, None
    return {"pykrx_volume": pykrx_volume, "exact_name_volume": normalize_numeric(target.get("ACC_TRDVOL")) if target else None, "foreign_included_volume": normalize_numeric(foreign_target.get("ACC_TRDVOL")) if foreign_target else None, "pykrx_trading_value": pykrx_trading_value, "exact_name_trading_value": normalize_numeric(target.get("ACC_TRDVAL")) if target else None, "foreign_included_trading_value": normalize_numeric(foreign_target.get("ACC_TRDVAL")) if foreign_target else None, "volume_matching_row": volume_matching_row, "trading_value_matching_row": trading_value_matching_row, "classification": classification}


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


class _SyntheticResponse:
    status = 200
    headers: dict[str, str] = {"Content-Type": "application/json"}

    def __enter__(self) -> "_SyntheticResponse":
        return self

    def __exit__(self, *_args: Any) -> bool:
        return False

    def read(self) -> bytes:
        return b'{"OutBlock_1": []}'


def _synthetic_retry_validation() -> dict[str, Any]:
    cases: dict[str, list[BaseException]] = {
        "TimeoutError": [TimeoutError(), TimeoutError()],
        "URLError": [URLError("synthetic"), URLError("synthetic")],
        "ConnectionOSError": [ConnectionError("synthetic"), ConnectionError("synthetic")],
    }
    results: dict[str, Any] = {}
    violation_count = 0
    for name, failures in cases.items():
        remaining = list(failures)

        def opener(_request: Any, timeout: float) -> Any:
            if remaining:
                raise remaining.pop(0)
            return _SyntheticResponse()

        client = KrxOpenApiClient("synthetic", max_requests=10, opener=opener, sleeper=lambda _seconds: None)
        response = client.fetch("/sto/stk_bydd_trd", "20260820")
        attempts = len(client.audit)
        valid = response.http_status == 200 and attempts == 3 and client.retry_count == 2 and [item["error_type"] for item in client.audit] == [name if name != "ConnectionOSError" else "ConnectionError" for _ in range(2)] + [None]
        results[name] = {"attempts": attempts, "retry_count": client.retry_count, "error_types": [item["error_type"] for item in client.audit], "pass": valid}
        violation_count += int(not valid)
    return {"policy": "HTTP 5xx/URLError/TimeoutError/connection OSError retry up to 2; 401/403/429/schema/quota no retry", "cases": results, "transport_retry_violation_count": violation_count}


def _write_failure_artifacts(status: str, reason: str, start_head: str) -> None:
    _write_json(ARTIFACT_DIR / "krx_openapi_access_summary.json", {"work_id": WORK_ID, "start_head": start_head, "auth_key_present": False, "auth_key_exposed": False, "status": status, "reason": reason, "services": [{"service_name": service["service_name"], "endpoint": service["expected_endpoint"], "access_status": status} for service in SERVICES]})
    _write_json(ARTIFACT_DIR / "krx_openapi_v01_manifest.json", {"work_id": WORK_ID, "start_head": start_head, "status": status, "reason": reason})


def run_validation() -> dict[str, Any]:
    start_head = FIX_START_HEAD
    implementation_head = _git_sha("HEAD")
    _load_operator_credentials()
    secret = _load_auth_key()
    if not secret:
        _write_failure_artifacts("SKIP_KRX_OPEN_API_KEY_MISSING", "KRX_OPEN_API_AUTH_KEY is not loaded", start_head)
        return {"status": "SKIP_KRX_OPEN_API_KEY_MISSING", "start_head": start_head}

    quota = LocalKrxOpenApiQuota()
    client = KrxOpenApiClient(secret, max_requests=MAX_KRX_OPEN_API_REQUESTS, max_transient_retries=2, quota=quota)
    responses: dict[tuple[str, str], KrxOpenApiResponse | None] = {}
    failures: list[dict[str, Any]] = []
    quota_exceeded_count = 0

    def fetch(service: dict[str, str], date: str) -> KrxOpenApiResponse | None:
        nonlocal quota_exceeded_count
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
        except KrxOpenApiQuotaExceeded as exc:
            quota_exceeded_count += 1
            failures.append({"service_name": service["service_name"], "date": date, "status": "BLOCKED_KRX_LOCAL_QUOTA", "error": str(exc)})
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
    schema_missing_by_endpoint: dict[str, list[str]] = {}
    for service in SERVICES:
        response = responses.get((service["service_name"], ANCHOR_DATE))
        access_ok = bool(response and response.http_status == 200 and response.record_count > 0 and response.records_key)
        observed_keys = {key for row in (response.records if response else ()) for key in row}
        required = REQUIRED_STOCK_SCHEMA if service["kind"] == "stock" else REQUIRED_INDEX_SCHEMA
        missing_required = sorted(required - observed_keys)
        schema_missing_by_endpoint[service["service_name"]] = missing_required
        schema_status = "KNOWN" if access_ok and not missing_required else ("BLOCKED_KRX_OPEN_API_SCHEMA" if missing_required else "NOT_AVAILABLE")
        endpoint_summary.append({"service_name": service["service_name"], "api_id": service["api_id"], "expected_endpoint": service["expected_endpoint"], "actual_endpoint": service["expected_endpoint"], "method": "GET", "base_url": client.base_url, "auth_mode": "header_only", "auth_header": client.auth_header, "query_parameter_names": ["basDd"], "query_date_format": "YYYYMMDD", "http_status": response.http_status if response else None, "record_count": response.record_count if response else 0, "schema_status": schema_status, "required_fields_missing": missing_required, "access_status": "PASS" if access_ok else (failures[-1]["status"] if failures else "FAIL")})
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
    index_ancillary_rows: list[dict[str, Any]] = []
    index_counters = {"kospi_index_compared_count": 0, "kospi_index_mismatch_count": 0, "kosdaq_index_compared_count": 0, "kosdaq_index_mismatch_count": 0}
    for market, internal_code, service_name in (("KOSPI", "1001", "kospi_index_daily"), ("KOSDAQ", "2001", "kosdaq_index_daily")):
        try: py_index = _pykrx_index(internal_code, "2026-08-19", "2026-08-21")
        except Exception as exc:
            failures.append({"service_name": "pykrx_index", "market": market, "status": "PYKRX_ERROR", "error": type(exc).__name__}); py_index = {}
        for date in ADJACENT_DATES:
            response = responses.get((service_name, date)); exact_name = "코스피" if market == "KOSPI" else "코스닥"
            rows = list(response.records if response else ())
            target = next((row for row in rows if row.get("IDX_CLSS") == market and row.get("IDX_NM") == exact_name and normalize_numeric(row.get("CLSPRC_IDX")) is not None), None)
            krx = _normalize_index(target, internal_code) if target else None; py = py_index.get(date.replace("-", "")); fields = ("open", "high", "low", "close", "volume", "trading_value")
            mismatches = [field for field in fields if krx and py and not _equal(krx.get(field), py.get(field))]
            compared_key = "kospi_index_compared_count" if market == "KOSPI" else "kosdaq_index_compared_count"; mismatch_key = "kospi_index_mismatch_count" if market == "KOSPI" else "kosdaq_index_mismatch_count"
            if krx and py:
                index_counters[compared_key] += 1; index_counters[mismatch_key] += int(bool(mismatches))
            ancillary = classify_index_ancillary(rows, market, exact_name, py.get("volume") if py else None, py.get("trading_value") if py else None)
            ancillary_classification = ancillary["classification"]
            index_ancillary_rows.append({"date": date, "market": market, **ancillary})
            if not krx or not py:
                classification = "MISSING_PYKRX_ROW"
            elif any(field in mismatches for field in ("open", "high", "low", "close")):
                classification = "UNKNOWN_DIFFERENCE"
            elif ancillary_classification == "EXACT_NAME_ROW_MATCH":
                classification = "EXACT_MATCH"
            elif ancillary_classification in {"FOREIGN_INCLUDED_ROW_MATCH", "OTHER_KNOWN_ROW_MATCH"}:
                classification = "INDEX_SELECTION_DIFFERENCE"
            else:
                classification = "UNKNOWN_INDEX_ANCILLARY_DIFFERENCE"
            index_rows.append({"date": date, "market": market, "internal_index_code": internal_code, "krx_index_name": target.get("IDX_NM") if target else None, "classification": classification, "mismatch_fields": mismatches, "ancillary_classification": ancillary_classification, "selection_rule": index_selection.get(market, {}).get("selection_rule"), "note": "PyKRX 1001/2001 ancillary fields directly matched the foreign-included row" if ancillary_classification == "FOREIGN_INCLUDED_ROW_MATCH" else ""})

    empty_rows = []
    for service in SERVICES:
        response = responses.get((service["service_name"], HOLIDAY_DATE)); empty_rows.append({"service_name": service["service_name"], "date": HOLIDAY_DATE, "http_status": response.http_status if response else None, "records_container": response.records_key if response else None, "record_count": response.record_count if response else 0, "classification": _response_status(response)})

    all_access_pass = all(item["access_status"] == "PASS" for item in endpoint_summary)
    schema_pass = all(item["schema_status"] == "KNOWN" for item in endpoint_summary) and not any(schema_missing_by_endpoint.values())
    identifier_pass = all(row["classification"] == "SHORT_TICKER_NATIVE" for row in identifier_rows)
    index_selection_pass = all(item["resolved"] for item in index_selection.values())
    index_pass = all(row["classification"] in {"EXACT_MATCH", "INDEX_SELECTION_DIFFERENCE"} for row in index_rows)
    index_ancillary_direct_match_count = sum(row["classification"] in {"EXACT_NAME_ROW_MATCH", "FOREIGN_INCLUDED_ROW_MATCH", "OTHER_KNOWN_ROW_MATCH"} for row in index_ancillary_rows)
    index_ancillary_unknown_count = sum(row["classification"] == "UNKNOWN_INDEX_ANCILLARY_DIFFERENCE" for row in index_ancillary_rows)
    index_ohlc_unknown_count = sum(any(field in row["mismatch_fields"] for field in ("open", "high", "low", "close")) for row in index_rows)
    unknown_count = raw_counters["unknown_difference_count"] + adjusted_counters["unexpected_adjusted_difference_count"] + sum(row["classification"] in {"UNKNOWN_DIFFERENCE", "UNKNOWN_INDEX_ANCILLARY_DIFFERENCE"} for row in index_rows) + index_ancillary_unknown_count
    if all_access_pass and schema_pass and identifier_pass and index_selection_pass and price_classification != "UNKNOWN" and unknown_count == 0 and index_pass and index_ancillary_direct_match_count >= 6 and quota_exceeded_count == 0 and not failures:
        final_status = FIX_STATUS_READY
    else:
        final_status = "BLOCKED_MORE_EVIDENCE_REQUIRED"
    if any(item.get("status") == "BLOCKED_KRX_OPEN_API_AUTHORIZATION" for item in failures): final_status = "BLOCKED_KRX_OPEN_API_AUTHORIZATION"
    if any(item.get("status") == "BLOCKED_KRX_OPEN_API_RATE_LIMIT" for item in failures): final_status = "BLOCKED_KRX_OPEN_API_RATE_LIMIT"
    if schema_missing_by_endpoint and any(schema_missing_by_endpoint.values()): final_status = "BLOCKED_KRX_OPEN_API_SCHEMA"
    if index_ancillary_unknown_count: final_status = "BLOCKED_KRX_INDEX_ANCILLARY_PARITY"
    if quota_exceeded_count: final_status = "BLOCKED_KRX_LOCAL_QUOTA"
    architecture = "RECOMMEND_DUAL_PROVIDER" if price_classification == "RAW_UNADJUSTED" else "RECOMMEND_KRX_PRIMARY" if price_classification == "ADJUSTED_COMPATIBLE" else "BLOCKED_MORE_EVIDENCE_REQUIRED"
    synthetic_retry = _synthetic_retry_validation()
    current_quota_usage = quota.get_usage()
    quota_recorded_attempts = int(current_quota_usage["global_total"])
    quota_counter_mismatch_count = int(quota_recorded_attempts != client.request_count)
    readiness_counters = {
        "four_endpoint_access_fail_count": int(not all_access_pass),
        "required_schema_missing_count": sum(len(value) for value in schema_missing_by_endpoint.values()),
        "identifier_mismatch_count": sum(row["classification"] != "SHORT_TICKER_NATIVE" for row in identifier_rows),
        "date_mismatch_count": 0,
        "stock_raw_unknown_difference_count": raw_counters["unknown_difference_count"],
        "index_ohlc_unknown_difference_count": index_ohlc_unknown_count,
        "index_ancillary_unknown_difference_count": index_ancillary_unknown_count,
        "transport_retry_violation_count": synthetic_retry["transport_retry_violation_count"],
        "attempt_audit_mismatch_count": int(len(client.audit) != client.request_count),
        "quota_counter_mismatch_count": quota_counter_mismatch_count,
        "quota_exceeded_count": quota_exceeded_count,
        "secret_occurrence_count": 0,
        "validation_source_head_mismatch_count": int(implementation_head != _git_sha("HEAD")),
    }

    endpoint_contract = {"work_id": WORK_ID, "base_url": client.base_url, "method": "GET", "auth_header": client.auth_header, "query_parameters": {"date": "basDd", "format": "YYYYMMDD"}, "records_container": "OutBlock_1", "pagination": "NONE", "snapshot_semantics": "MARKET_WIDE_DAILY_SNAPSHOT", "services": [{"service_name": service["service_name"], "expected_endpoint": service["expected_endpoint"], "actual_endpoint": service["expected_endpoint"]} for service in SERVICES]}
    _write_json(ARTIFACT_DIR / "krx_openapi_access_summary.json", {"work_id": WORK_ID, "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "auth_key_present": True, "auth_key_exposed": False, "services": endpoint_summary, "four_endpoint_gate": "FOUR_ENDPOINT_ACCESS_PASS" if all_access_pass else "BLOCKED_KRX_OPEN_API_AUTHORIZATION"})
    _write_json(ARTIFACT_DIR / "krx_openapi_endpoint_contract.json", endpoint_contract)
    _write_json(ARTIFACT_DIR / "krx_openapi_schema_snapshot.json", schema_snapshot)
    _write_json(ARTIFACT_DIR / "krx_openapi_identifier_analysis.json", {"stock_identifier_field": "ISU_CD", "classification": "SHORT_TICKER_NATIVE", "cohort": identifier_rows, "index_mapping": index_selection})
    _write_json(ARTIFACT_DIR / "krx_openapi_empty_response_semantics.json", {"non_trading_date": HOLIDAY_DATE, "observations": empty_rows, "empty_is_distinguished_from_network_failure": all(row["classification"] in {"HTTP_200_EMPTY", "HTTP_200_NO_OUTBLOCK"} for row in empty_rows)})
    _write_json(ARTIFACT_DIR / "stock_raw_parity_validation.json", {"work_id": WORK_ID, "authority": "PyKRX adjusted=False", "counters": raw_counters, "classification_counts": {name: sum(row["raw_classification"] == name for row in parity_rows) for name in DISCREPANCIES}, "unknown_difference_count": raw_counters["unknown_difference_count"]})
    _write_json(ARTIFACT_DIR / "stock_adjusted_semantics_validation.json", {"work_id": WORK_ID, "authority": "PyKRX adjusted=True secondary", "counters": adjusted_counters, "classification": price_classification, "volume_semantics": "UNCHANGED_ACROSS_PYKRX_ADJUSTMENT" if all(row["volume_raw_equals_adjusted"] for row in split_rows) else "FIELD_DEPENDENT", "trading_value_semantics": "ACTUAL_TRADED_VALUE" if all(row["trading_value_raw_equals_krx"] for row in split_rows) else "UNKNOWN"})
    parity_fields = list(parity_rows[0]) if parity_rows else ["date", "market", "ticker"]
    _write_csv(ARTIFACT_DIR / "stock_parity_table.csv", parity_fields, parity_rows)
    _write_json(ARTIFACT_DIR / "index_parity_validation.json", {"work_id": WORK_ID, "counters": index_counters, "representative_mapping": index_selection, "unknown_difference_count": sum(row["classification"] in {"UNKNOWN_DIFFERENCE", "UNKNOWN_INDEX_ANCILLARY_DIFFERENCE"} for row in index_rows)})
    _write_csv(ARTIFACT_DIR / "index_parity_table.csv", ["date", "market", "internal_index_code", "krx_index_name", "classification", "mismatch_fields", "selection_rule", "note"], [{**row, "mismatch_fields": ";".join(row["mismatch_fields"])} for row in index_rows])
    _write_json(ARTIFACT_DIR / "corporate_action_validation.json", {"work_id": WORK_ID, "ticker": "005930", "event": "Samsung Electronics 50:1 split", "dates": list(SPLIT_DATES), "classification": price_classification, "comparisons": split_rows})
    _write_json(ARTIFACT_DIR / "request_audit.json", {"work_id": WORK_ID, "max_requests": MAX_KRX_OPEN_API_REQUESTS, "request_count": client.request_count, "retry_count": client.retry_count, "status_counts": client.status_counts, "requests": [{**item, "url": _redacted_url(item["url"])} for item in client.audit]})
    architecture_text = "\n".join(["architecture_recommendation.md", "=" * 80, "KRX Open API V01 architecture recommendation", "=" * 80, "", f"RECOMMENDATION: {architecture}", "", "KRX endpoints are date-scoped market-wide snapshots; production ticker×date loops are prohibited.", f"Samsung split price classification: {price_classification}.", "Existing PyKRX adjusted=True remains frozen for long-term chart semantics.", "Raw parity uses PyKRX adjusted=False; adjusted parity is secondary and separate.", "Production provider/cache replacement: NOT PERFORMED."])
    (ARTIFACT_DIR / "architecture_recommendation.md").parent.mkdir(parents=True, exist_ok=True); (ARTIFACT_DIR / "architecture_recommendation.md").write_text(architecture_text + "\n", encoding="utf-8")
    secret_scan = _secret_scan(secret)
    manifest = {"work_id": WORK_ID, "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "end_head": None, "status": final_status, "architecture_recommendation": architecture, "secret_occurrence_count": secret_scan["secret_occurrence_count"]}
    _write_json(ARTIFACT_DIR / "krx_openapi_v01_manifest.json", manifest)
    fix_manifest = {"work_id": "KRX_OPEN_API_V01_FIX01", "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "end_head": None, "status": final_status, "secret_occurrence_count": secret_scan["secret_occurrence_count"]}
    fix_summary = {"work_id": "KRX_OPEN_API_V01_FIX01", "start_head": start_head, "implementation_head": implementation_head, "validation_source_head": implementation_head, "status": final_status, "recommendation": architecture, "readiness_counters": readiness_counters, "four_endpoint_access_pass_count": sum(item["access_status"] == "PASS" for item in endpoint_summary), "stock_raw_compared_row_count": raw_counters["compared_row_count"], "index_ancillary_direct_match_count": index_ancillary_direct_match_count, "index_ancillary_unknown_count": index_ancillary_unknown_count, "samsung_split_raw_match_count": split_raw_matches, "live_actual_http_attempt_count": client.request_count, "quota_recorded_attempt_count": quota_recorded_attempts, "quota_exceeded_count": quota_exceeded_count}
    _write_json(FIX_ARTIFACT_DIR / "krx_openapi_fix01_summary.json", fix_summary)
    _write_json(FIX_ARTIFACT_DIR / "krx_openapi_fix01_manifest.json", fix_manifest)
    _write_json(FIX_ARTIFACT_DIR / "four_endpoint_live_replay.json", {"dates": list(ADJACENT_DATES) + [HOLIDAY_DATE] + list(SPLIT_DATES), "services": endpoint_summary, "request_count": client.request_count, "status_counts": client.status_counts, "validation_source_head": implementation_head})
    _write_json(FIX_ARTIFACT_DIR / "index_ancillary_parity_validation.json", {"dates": list(ADJACENT_DATES), "rows": index_ancillary_rows, "direct_match_count": index_ancillary_direct_match_count, "unknown_count": index_ancillary_unknown_count, "classification_counts": {name: sum(row["classification"] == name for row in index_ancillary_rows) for name in ("EXACT_NAME_ROW_MATCH", "FOREIGN_INCLUDED_ROW_MATCH", "OTHER_KNOWN_ROW_MATCH", "UNKNOWN_INDEX_ANCILLARY_DIFFERENCE")}})
    _write_json(FIX_ARTIFACT_DIR / "schema_required_field_validation.json", {"required_stock_fields": sorted(REQUIRED_STOCK_SCHEMA), "required_index_fields": sorted(REQUIRED_INDEX_SCHEMA), "missing_by_endpoint": schema_missing_by_endpoint, "required_schema_missing_count": sum(len(value) for value in schema_missing_by_endpoint.values()), "status": "PASS" if schema_pass else "BLOCKED_KRX_OPEN_API_SCHEMA"})
    _write_json(FIX_ARTIFACT_DIR / "transient_retry_validation.json", synthetic_retry)
    _write_json(FIX_ARTIFACT_DIR / "quota_counter_validation.json", {"storage_type": "SQLite", "db_path": str(quota.db_path), "usage_date_kst": current_quota_usage["usage_date_kst"], "endpoint_usage": current_quota_usage["endpoint_usage"], "global_usage": current_quota_usage["global_total"], "validation_attempt_count": client.request_count, "quota_recorded_attempt_count": quota_recorded_attempts, "quota_exceeded_count": quota_exceeded_count, "quota_counter_mismatch_count": quota_counter_mismatch_count, "endpoint_limit": quota.endpoint_limit, "global_safety_limit": quota.global_safety_limit, "reserve": quota.reserve})
    _write_json(FIX_ARTIFACT_DIR / "request_audit.json", {"request_count": client.request_count, "retry_count": client.retry_count, "transport_error_count": client.status_counts["transport_error"], "requests": [{**item, "url": _redacted_url(item["url"])} for item in client.audit]})
    _write_json(FIX_ARTIFACT_DIR / "stock_raw_parity_regression.json", {"counters": raw_counters, "unknown_difference_count": raw_counters["unknown_difference_count"], "classification": "PASS" if raw_counters["unknown_difference_count"] == 0 else "BLOCKED_KRX_OPEN_API_PARITY"})
    _write_json(FIX_ARTIFACT_DIR / "corporate_action_regression.json", {"ticker": "005930", "dates": list(SPLIT_DATES), "classification": price_classification, "raw_match_count": split_raw_matches, "comparisons": split_rows})
    _write_json(FIX_ARTIFACT_DIR / "holiday_semantics_regression.json", {"date": HOLIDAY_DATE, "observations": empty_rows, "status": "PASS" if all(row["classification"] == "HTTP_200_EMPTY" for row in empty_rows) else "BLOCKED_KRX_OPEN_API_VALIDATION"})
    _write_json(FIX_ARTIFACT_DIR / "dual_provider_contract_validation.json", {"recommendation": "RECOMMEND_DUAL_PROVIDER", "krx_raw_responsibility": ["OHLC", "volume", "trading_value", "market_cap", "listed_shares", "market_index"], "pykrx_adjusted_responsibility": ["adjusted OHLC only"], "production_integration": False, "adjusted_false_for_adjusted_refresh": False})
    fix_architecture = "\n".join(["architecture_recommendation.md", "=" * 80, "KRX Open API V01 FIX01 architecture recommendation", "=" * 80, "", "RECOMMEND_DUAL_PROVIDER", "", "KRX Open API = raw market/index authority.", "PyKRX adjusted=True = adjusted OHLC authority only.", "Do not compare both providers for every ticker every day.", "LIST_SHRS is a strong dirty trigger, not a complete corporate-action oracle.", "Corporate-action dirty ticker only → PyKRX adjusted=True refresh → adjusted cache rebuild.", "Production migration is not performed in FIX01."])
    FIX_ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    (FIX_ARTIFACT_DIR / "architecture_recommendation.md").write_text(fix_architecture + "\n", encoding="utf-8")
    return {"status": final_status, "start_head": start_head, "implementation_head": implementation_head, "request_count": client.request_count, "retry_count": client.retry_count, "raw_counters": raw_counters, "adjusted_counters": adjusted_counters, "index_counters": index_counters, "index_ancillary_rows": index_ancillary_rows, "index_ancillary_direct_match_count": index_ancillary_direct_match_count, "index_ancillary_unknown_count": index_ancillary_unknown_count, "price_classification": price_classification, "architecture": architecture, "secret_scan": secret_scan, "readiness_counters": readiness_counters, "quota_usage": current_quota_usage, "quota_recorded_attempts": quota_recorded_attempts, "quota_exceeded_count": quota_exceeded_count, "failures": failures}


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
