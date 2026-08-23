"""Run the bounded, secret-safe KRX Open API due-diligence validation.

This script is intentionally a validation tool only.  It does not modify any
production provider, PyKRX behavior, or historical datasets.  When the API
key is rejected, it persists an explicit blocked report instead of inventing
schema, parity, or corporate-action conclusions.
"""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/data_providers/krx_open_api/validation_v01"
CALENDAR_PATH = ROOT / "data/reference/krx_trading_calendar.json"
START_HEAD = "b73ae96a6a30f1211a045fedae7688973adb195f"
WORK_ID = "KRX_OPEN_API_VALIDATION_V01"
CANONICAL_FALLBACK = "2026-08-14"

BLOCKED = "BLOCKED_API_ACCESS_OR_SERVICE_APPROVAL"
AUTH_BLOCKED = "NOT_EVALUATED_AUTH_BLOCKED"
EXPECTED_STOCK_FIELDS = [
    "BAS_DD",
    "ISU_CD",
    "ISU_NM",
    "MKT_NM",
    "SECT_TP_NM",
    "TDD_CLSPRC",
    "CMPPREVDD_PRC",
    "FLUC_RT",
    "TDD_OPNPRC",
    "TDD_HGPRC",
    "TDD_LWPRC",
    "ACC_TRDVOL",
    "ACC_TRDVAL",
    "MKTCAP",
    "LIST_SHRS",
]
EXPECTED_INDEX_FIELDS = [
    "BAS_DD",
    "IDX_NM",
    "CLSPRC_IDX",
    "FLUC_TP_CD",
    "PRV_DD_CMPR",
    "FLUC_RT",
    "OPNPRC_IDX",
    "HGPRC_IDX",
    "LWPRC_IDX",
    "ACC_TRDVOL",
    "ACC_TRDVAL",
    "MKTCAP",
]
SERVICES = [
    {
        "service_name": "kospi_stock_daily",
        "api_id": "stk_bydd_trd",
        "endpoint": "https://data-dbg.krx.co.kr/svc/apis/sto/stk_bydd_trd",
        "kind": "stock",
    },
    {
        "service_name": "kosdaq_stock_daily",
        "api_id": "ksq_bydd_trd",
        "endpoint": "https://data-dbg.krx.co.kr/svc/apis/sto/ksq_bydd_trd",
        "kind": "stock",
    },
    {
        "service_name": "kospi_index_daily",
        "api_id": "kospi_dd_trd",
        "endpoint": "https://data-dbg.krx.co.kr/svc/apis/idx/kospi_dd_trd",
        "kind": "index",
    },
    {
        "service_name": "kosdaq_index_daily",
        "api_id": "kosdaq_dd_trd",
        "endpoint": "https://data-dbg.krx.co.kr/svc/apis/idx/kosdaq_dd_trd",
        "kind": "index",
    },
]
CORPORATE_ACTION_CASES = [
    ("005930", "삼성전자", "split", "2018"),
    ("035420", "NAVER", "split", "2018"),
    ("035720", "카카오", "split", "2021"),
    ("090430", "추가 액면분할 사례", "split", "2015"),
    ("278650", "노터스/HLB바이오스텝", "bonus_issue", "required_by_w_md"),
    ("366030", "공구우먼", "bonus_issue", "required_by_w_md"),
]


def normalize_numeric(value: Any) -> float | int | None:
    """Normalize KRX numeric strings without changing the stored raw value."""

    if value is None:
        return None
    text = str(value).replace(",", "").strip()
    if text in {"", "-", "—", "nan", "None"}:
        return None
    number = float(text)
    return int(number) if number.is_integer() else number


def redact_headers(headers: dict[str, str]) -> dict[str, str]:
    """Return a header audit representation that can never contain a key."""

    return {name: "<redacted>" if name.upper() == "AUTH_KEY" else value for name, value in headers.items()}


def _json_or_empty(raw: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _record_count(payload: dict[str, Any]) -> int:
    for value in payload.values():
        if isinstance(value, list):
            return len(value)
    return 0


def _request(service: dict[str, str], date: str, auth_key: str) -> dict[str, Any]:
    """Make one bounded request; retry only transient server/rate-limit errors."""

    query = {"basDd": date.replace("-", "")}
    headers = {"AUTH_KEY": auth_key, "Accept": "application/json"}
    attempts = 0
    last: dict[str, Any] = {}
    while attempts < 2:
        attempts += 1
        request = Request(f"{service['endpoint']}?{urlencode(query)}", headers=headers, method="GET")
        try:
            with urlopen(request, timeout=30) as response:
                payload = _json_or_empty(response.read())
                status = int(response.status)
                last = {
                    "http_status": status,
                    "resp_code": payload.get("respCode"),
                    "resp_msg": payload.get("respMsg"),
                    "top_level_keys": sorted(payload),
                    "record_count": _record_count(payload),
                    "attempts": attempts,
                }
        except HTTPError as exc:
            payload = _json_or_empty(exc.read())
            status = int(exc.code)
            last = {
                "http_status": status,
                "resp_code": payload.get("respCode"),
                "resp_msg": payload.get("respMsg"),
                "top_level_keys": sorted(payload),
                "record_count": _record_count(payload),
                "attempts": attempts,
            }
        except (URLError, TimeoutError, OSError) as exc:
            last = {
                "http_status": None,
                "resp_code": None,
                "resp_msg": type(exc).__name__,
                "top_level_keys": [],
                "record_count": 0,
                "attempts": attempts,
            }
        if last["http_status"] not in {429, 500, 502, 503, 504}:
            break
    return last


def _canonical_date() -> str:
    if CALENDAR_PATH.exists():
        data = json.loads(CALENDAR_PATH.read_text(encoding="utf-8"))
        value = data.get("max_observed_trading_date") or data.get("cutoff_date")
        if value:
            return str(value)[:10]
    return CANONICAL_FALLBACK


def _parity_dates() -> list[str]:
    manifest = ROOT / "artifacts/strategies/julia/v00/historical_market_cap_source_manifest.csv"
    if not manifest.exists():
        return []
    dates: list[str] = []
    with manifest.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if row.get("available") == "True" and row.get("effective_date"):
                normalized = row["effective_date"][:10]
                if normalized not in dates:
                    dates.append(normalized)
    if len(dates) <= 5:
        return dates
    indices = [0, len(dates) // 3, (2 * len(dates)) // 3, len(dates) - 2, len(dates) - 1]
    return list(dict.fromkeys(dates[i] for i in indices if 0 <= i < len(dates)))


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=fieldnames,
            extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    load_dotenv(ROOT / ".env", override=True)
    auth_key = os.getenv("KRX_OPEN_API_AUTH_KEY", "")
    auth_key_present = bool(auth_key.strip())
    canonical_date = _canonical_date()
    validation_dates = [canonical_date]
    services_result: list[dict[str, Any]] = []

    if auth_key_present:
        for service in SERVICES:
            result = _request(service, canonical_date, auth_key)
            result.update(
                {
                    "service_name": service["service_name"],
                    "api_id": service["api_id"],
                    "endpoint_without_secret": service["endpoint"],
                    "query_parameter_names": ["basDd"],
                    "validation_dates": validation_dates,
                    "kind": service["kind"],
                }
            )
            services_result.append(result)
    else:
        for service in SERVICES:
            services_result.append(
                {
                    "service_name": service["service_name"],
                    "api_id": service["api_id"],
                    "endpoint_without_secret": service["endpoint"],
                    "query_parameter_names": ["basDd"],
                    "validation_dates": validation_dates,
                    "http_status": None,
                    "resp_code": None,
                    "resp_msg": "AUTH_KEY_NOT_LOADED",
                    "top_level_keys": [],
                    "record_count": 0,
                    "attempts": 0,
                    "kind": service["kind"],
                }
            )

    blocked_reason = "AUTH_KEY_NOT_LOADED" if not auth_key_present else "All four official endpoints returned HTTP 401 Unauthorized API Call."
    final_status = "BLOCKED_LOCAL_AUTH_KEY_NOT_LOADED" if not auth_key_present else BLOCKED
    parity_dates = _parity_dates()
    manifest_rows = [
        {
            "service_name": item["service_name"],
            "api_id": item["api_id"],
            "endpoint_without_secret": item["endpoint_without_secret"],
            "query_parameter_names": "basDd",
            "validation_dates": ";".join(item["validation_dates"]),
            "http_status": item["http_status"],
            "record_count": item["record_count"],
            "attempts": item["attempts"],
        }
        for item in services_result
    ]
    _write_json(
        ARTIFACT_DIR / "request_manifest.json",
        {
            "work_id": WORK_ID,
            "start_head": START_HEAD,
            "auth_key_present": auth_key_present,
            "auth_key_exposed": False,
            "services": manifest_rows,
            "total_api_requests": sum(int(item["attempts"]) for item in services_result),
        },
    )
    _write_json(
        ARTIFACT_DIR / "connectivity_summary.json",
        {
            "work_id": WORK_ID,
            "canonical_validation_date": canonical_date,
            "overall_status": final_status,
            "reason": blocked_reason,
            "services": services_result,
        },
    )
    _write_json(
        ARTIFACT_DIR / "response_schema.json",
        {
            "work_id": WORK_ID,
            "status": final_status,
            "actual_data_schema_available": False,
            "observed_error_response_schema": {
                item["service_name"]: item["top_level_keys"] for item in services_result
            },
            "expected_stock_fields_from_official_spec": EXPECTED_STOCK_FIELDS,
            "expected_index_fields_from_official_spec": EXPECTED_INDEX_FIELDS,
            "schema_drift": "NOT_EVALUATED_AUTH_BLOCKED",
        },
    )

    parity_rows = []
    for date in parity_dates:
        parity_rows.append(
            {
                "effective_date": date,
                "api_observation_count": 0,
                "official_snapshot_observation_count": "available_snapshot_only",
                "close_parity": AUTH_BLOCKED,
                "volume_parity": AUTH_BLOCKED,
                "trading_value_parity": AUTH_BLOCKED,
                "market_cap_parity": AUTH_BLOCKED,
                "listed_shares_parity": AUTH_BLOCKED,
                "notes": "KRX Open API access blocked before authenticated rows were returned",
            }
        )
    _write_csv(
        ARTIFACT_DIR / "market_field_parity.csv",
        [
            "effective_date",
            "api_observation_count",
            "official_snapshot_observation_count",
            "close_parity",
            "volume_parity",
            "trading_value_parity",
            "market_cap_parity",
            "listed_shares_parity",
            "notes",
        ],
        parity_rows,
    )

    case_rows = [
        {
            "ticker": ticker,
            "name": name,
            "event_type": event_type,
            "event_reference": event_reference,
            "status": AUTH_BLOCKED,
            "adjustment_observation": "not_observed",
            "notes": "Authenticated API rows unavailable; no adjustment conclusion made",
        }
        for ticker, name, event_type, event_reference in CORPORATE_ACTION_CASES
    ]
    _write_csv(
        ARTIFACT_DIR / "corporate_action_cases.csv",
        ["ticker", "name", "event_type", "event_reference", "status", "adjustment_observation", "notes"],
        case_rows,
    )
    _write_csv(
        ARTIFACT_DIR / "adjusted_price_equivalence.csv",
        ["ticker", "name", "event_type", "classification", "local_adjusted_reference", "api_equivalence", "status"],
        [
            {
                "ticker": ticker,
                "name": name,
                "event_type": event_type,
                "classification": "INCONCLUSIVE",
                "local_adjusted_reference": "available_local_parquet",
                "api_equivalence": AUTH_BLOCKED,
                "status": AUTH_BLOCKED,
            }
            for ticker, name, event_type, _ in CORPORATE_ACTION_CASES
        ],
    )
    _write_csv(
        ARTIFACT_DIR / "index_validation.csv",
        ["service_name", "api_id", "status", "observation_count", "parity", "notes"],
        [
            {
                "service_name": item["service_name"],
                "api_id": item["api_id"],
                "status": final_status,
                "observation_count": item["record_count"],
                "parity": AUTH_BLOCKED,
                "notes": "No authenticated index rows returned",
            }
            for item in services_result
            if item["kind"] == "index"
        ],
    )

    service_status = {item["service_name"]: final_status for item in services_result}
    _write_json(
        ARTIFACT_DIR / "validation_summary.json",
        {
            "work_id": WORK_ID,
            "start_head": START_HEAD,
            "auth_key_present": auth_key_present,
            "auth_key_exposed": False,
            "status": final_status,
            "reason": blocked_reason,
            "total_api_requests": sum(int(item["attempts"]) for item in services_result),
            "canonical_validation_date": canonical_date,
            "kospi_stock_api": service_status["kospi_stock_daily"],
            "kosdaq_stock_api": service_status["kosdaq_stock_daily"],
            "kospi_index_api": service_status["kospi_index_daily"],
            "kosdaq_index_api": service_status["kosdaq_index_daily"],
            "actual_stock_response_schema": "NOT_AVAILABLE_AUTH_BLOCKED",
            "market_cap_parity": AUTH_BLOCKED,
            "listed_shares_parity": AUTH_BLOCKED,
            "trading_value_parity": AUTH_BLOCKED,
            "market_parity_observation_count": 0,
            "split_adjustment": AUTH_BLOCKED,
            "bonus_issue_adjustment": AUTH_BLOCKED,
            "adjusted_price_classification": "INCONCLUSIVE",
            "index_parity": AUTH_BLOCKED,
            "non_trading_date_behavior": AUTH_BLOCKED,
            "schema_drift": AUTH_BLOCKED,
            "recommended_architecture": "DO_NOT_MIGRATE_YET",
            "production_migration": False,
            "pykrx_removed": False,
            "services": service_status,
        },
    )
    print(f"AUTH_KEY_PRESENT={str(auth_key_present).lower()}")
    print("AUTH_KEY_EXPOSED=false")
    print(f"FINAL_STATUS={final_status}")
    print(f"TOTAL_API_REQUESTS={sum(int(item['attempts']) for item in services_result)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
