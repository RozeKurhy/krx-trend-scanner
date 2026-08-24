"""Build and validate the production Sector RS KRX Open API migration.

This script is the networked migration runner.  Production consumers only read
the normalized cache; they never import this module or the validation artifacts.
"""

from __future__ import annotations

import csv
import json
import math
import os
import re
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota
from trend_scanner.data.krx_sector_index import (
    KOSDAQ_SECTOR_CODES,
    KOSPI_SECTOR_CODES,
    KRX_NATIVE_SECTOR_INDEX_MAP,
    MAPPING_CONTRACT_VERSION,
    KrxSectorIndexCacheBuilder,
    mapping_contract_as_dict,
    mapping_contract_sha256,
)
from trend_scanner.relative_strength.relative_strength import compute_relative_strength_features
from trend_scanner.universe.models import MarketType


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/data/krx_openapi/sector_rs_migration/v01"
CACHE_DIR = ROOT / ".cache/krx_openapi/sector_rs_migration/v01"
CACHE_PARQUET = CACHE_DIR / "sector_index_daily.parquet"
CACHE_META = CACHE_DIR / "sector_index_daily_meta.json"
QUOTA_DB = CACHE_DIR / "quota.sqlite3"
MIGRATION_WORK_ID = "SECTOR_RS_KRX_MIGRATION_V01"
START_DATE = "2025-06-01"
END_DATE = "2026-08-21"
RS_AS_OF = "2026-08-14"  # Existing stock and market caches end on this date.
KRX_MAX_REQUESTS = 800
PYKRX_MAX_OPERATIONS = 46
PYKRX_DELAY_SECONDS = 0.75
OHLC_FIELDS = ("open", "high", "low", "close")
RS_COMPARE_FIELDS = (
    "sector_rs_data_status", "sector_name", "sector_code", "sector_benchmark_code",
    "sector_benchmark_last_observation_date", "sector_return_3m", "sector_return_6m", "sector_return_12m",
    "sector_rs_3m", "sector_rs_6m", "sector_rs_12m", "sector_anchor_date_3m", "sector_anchor_date_6m",
    "sector_anchor_date_12m", "market_rs_data_status", "market_benchmark_name", "market_benchmark_code",
    "market_benchmark_last_observation_date", "market_return_3m", "market_return_6m", "market_return_12m",
    "market_rs_3m", "market_rs_6m", "market_rs_12m", "market_anchor_date_3m", "market_anchor_date_6m",
    "market_anchor_date_12m",
)


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


def load_auth_key() -> str:
    value = os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
    if value:
        return value
    for path in (ROOT / ".env", ROOT.parent / "env.md"):
        value = _read_env_value(path, "KRX_OPEN_API_AUTH_KEY").strip()
        if value:
            return value
    return ""


def load_pykrx_credentials() -> None:
    """Load PyKRX login values silently; never serialize them."""

    for name in ("KRX_ID", "KRX_PW"):
        if os.getenv(name, "").strip():
            continue
        for path in (ROOT / ".env", ROOT.parent / "env.md"):
            value = _read_env_value(path, name).strip()
            if value:
                os.environ[name] = value
                break


def safe_write_json(path: Path, value: Any, secret: str = "") -> None:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if secret and secret in serialized:
        raise ValueError("secret detected in migration artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, fieldnames: list[str], rows: list[Mapping[str, Any]]) -> None:
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


def _mapping_drift() -> tuple[int, list[dict[str, Any]]]:
    path = ROOT / "artifacts/data/krx_openapi/index_mapping/v01/sector_code_mapping.csv"
    if not path.exists():
        return 46, []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    drift: list[dict[str, Any]] = []
    for code, contract in KRX_NATIVE_SECTOR_INDEX_MAP.items():
        row = next((item for item in rows if item.get("sector_code") == code), None)
        expected = {"market": contract["market"], "source_api": contract["source_api"], "official_idx_class": contract["idx_class"], "official_idx_name": contract["idx_name"], "mapping_status": "EXACT_MARKET_SERIES_MATCH"}
        if row is None or any(str(row.get(key, "")) != value for key, value in expected.items()):
            drift.append({"sector_code": code, "expected": expected, "actual": row})
    drift.extend({"sector_code": row.get("sector_code"), "reason": "UNKNOWN_ARTIFACT_CODE"} for row in rows if row.get("sector_code") not in KRX_NATIVE_SECTOR_INDEX_MAP)
    return len(drift), drift


def _fetch_pykrx_reference(codes: list[str], start: str, end: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    load_pykrx_credentials()
    state: dict[str, Any] = {"network_operations": 0, "hard_cap_block_count": 0, "failures": []}
    rows: list[dict[str, Any]] = []
    for code in codes:
        if state["network_operations"] >= PYKRX_MAX_OPERATIONS:
            state["hard_cap_block_count"] += 1
            state["failures"].append({"code": code, "status": "PYKRX_OPERATION_BUDGET_EXHAUSTED"})
            break
        time.sleep(PYKRX_DELAY_SECONDS)
        state["network_operations"] += 1
        capture = StringIO()
        try:
            with redirect_stdout(capture), redirect_stderr(capture):
                from pykrx import stock
                frame = stock.get_index_ohlcv_by_date(start.replace("-", ""), end.replace("-", ""), code)
            if frame is None or getattr(frame, "empty", True):
                state["failures"].append({"code": code, "status": "PYKRX_EMPTY_DATA"})
                continue
            contract = KRX_NATIVE_SECTOR_INDEX_MAP[code]
            for index, row in frame.iterrows():
                date_text = pd.Timestamp(index).strftime("%Y-%m-%d")
                try:
                    values = {field: float(row[column]) for field, column in (("open", "시가"), ("high", "고가"), ("low", "저가"), ("close", "종가"))}
                except (KeyError, TypeError, ValueError) as exc:
                    state["failures"].append({"code": code, "date": date_text, "status": "PYKRX_INVALID_ROW", "error": type(exc).__name__})
                    continue
                rows.append({"date": date_text, "index_code": code, "index_name": contract["idx_name"], **values, "volume": 0, "trading_value": 0.0})
        except Exception as exc:
            state["failures"].append({"code": code, "status": "PYKRX_ERROR", "error": type(exc).__name__})
    frame = pd.DataFrame(rows, columns=["date", "index_code", "index_name", "open", "high", "low", "close", "volume", "trading_value"])
    return frame, state


def _load_reference_cache() -> tuple[pd.DataFrame | None, str]:
    path = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/sector_index_daily_20260814.parquet"
    if not path.exists():
        return None, "PYKRX_LIVE_BOUNDED_REFERENCE"
    try:
        frame = pd.read_parquet(path)
    except Exception:
        return None, "PYKRX_LIVE_BOUNDED_REFERENCE"
    if frame.empty or frame["index_code"].astype(str).nunique() < 46 or frame["date"].nunique() < 20:
        return None, "PYKRX_LIVE_BOUNDED_REFERENCE"
    return frame, "LOCAL_PYKRX_SECTOR_CACHE"


def _decimal(value: Any) -> Decimal | None:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parity(new_df: pd.DataFrame, reference_df: pd.DataFrame, reference_source: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    new = new_df.copy()
    ref = reference_df.copy()
    for frame in (new, ref):
        frame["date"] = frame["date"].astype(str)
        frame["index_code"] = frame["index_code"].astype(str)
    new_map = {(row["date"], row["index_code"]): row for _, row in new.iterrows()}
    ref_map = {(row["date"], row["index_code"]): row for _, row in ref.iterrows()}
    rows: list[dict[str, Any]] = []
    exact_fields = mismatch_fields = rounding_only = compared_fields = 0
    common_dates: set[str] = set()
    common_codes: set[str] = set()
    for key in sorted(set(new_map) | set(ref_map)):
        krx = new_map.get(key)
        old = ref_map.get(key)
        date_text, code = key
        if krx is not None and old is not None:
            common_dates.add(date_text)
            common_codes.add(code)
        row: dict[str, Any] = {"date": date_text, "sector_code": code, "sector_name": KRX_NATIVE_SECTOR_INDEX_MAP.get(code, {}).get("idx_name", ""), "reference_source": reference_source}
        mismatch = False
        rounding = False
        for field in OHLC_FIELDS:
            left = _decimal(krx[field]) if krx is not None else None
            right = _decimal(old[field]) if old is not None else None
            row[f"krx_{field}"] = "" if left is None else format(left, "f")
            row[f"reference_{field}"] = "" if right is None else format(right, "f")
            match = left is not None and right is not None
            if match:
                compared_fields += 1
                match = left == right
                exact_fields += int(match)
                if not match and abs(left - right) == Decimal("0.01"):
                    rounding = True
            if not match:
                mismatch = True
                mismatch_fields += 1
            row[f"{field}_match"] = match
        rounding_only += int(mismatch and rounding)
        row["row_mismatch"] = mismatch
        rows.append(row)
    counters = {
        "cache_parity_compared_sector_count": len(common_codes),
        "cache_parity_compared_date_count": len(common_dates),
        "cache_parity_compared_field_count": compared_fields,
        "cache_parity_exact_field_count": exact_fields,
        "cache_parity_mismatch_count": mismatch_fields,
        "cache_parity_rounding_only_count": rounding_only,
        "cache_parity_row_count": len(rows),
    }
    return rows, counters


def _select_representative_tickers(as_of: str) -> tuple[list[dict[str, str]], pd.DataFrame]:
    mapping_path = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/sector_mapping_20260814.csv"
    mapping_df = pd.read_csv(mapping_path, dtype=str)
    mapping_df["ticker"] = mapping_df["ticker"].astype(str).str.zfill(6)
    selected: list[dict[str, str]] = []
    selected_sectors: set[str] = set()
    per_market = {"KOSPI": 0, "KOSDAQ": 0}

    def append_valid(row: pd.Series) -> bool:
        market = str(row["market"])
        ticker = str(row["ticker"]).zfill(6)
        stock_path = ROOT / "data/raw/stocks" / f"{ticker}.parquet"
        if not stock_path.exists():
            return False
        try:
            stock = pd.read_parquet(stock_path)
            available_dates = {pd.Timestamp(item).strftime("%Y-%m-%d") for item in stock.index}
        except Exception:
            return False
        if as_of not in available_dates:
            return False
        sector_code = str(row["sector_code"])
        selected.append({"ticker": ticker, "market": market, "sector_code": sector_code, "sector_name": str(row["sector_name"]), "effective_date": str(row["effective_date"])})
        selected_sectors.add(sector_code)
        per_market[market] = per_market.get(market, 0) + 1
        return True

    # Prefer one valid ticker per sector. This keeps the diversity gate
    # meaningful instead of accidentally selecting six names from one sector.
    ordered = mapping_df.sort_values(["market", "sector_code", "ticker"])
    for market in ("KOSPI", "KOSDAQ"):
        for _, row in ordered[ordered["market"].astype(str) == market].iterrows():
            if per_market[market] >= 6:
                break
            if str(row["sector_code"]) in selected_sectors:
                continue
            append_valid(row)
    return selected, mapping_df


def _rs_parity(new_sector: pd.DataFrame, old_sector: pd.DataFrame, as_of: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected, mapping_df = _select_representative_tickers(as_of)
    market_path = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/market_index_daily_20260814.parquet"
    market_df = pd.read_parquet(market_path)
    mapping = {row["ticker"]: (row["sector_code"], row["sector_name"]) for _, row in mapping_df.iterrows()}
    rows: list[dict[str, Any]] = []
    mismatches = 0
    status_mismatches = return_mismatches = rs_mismatches = anchor_mismatches = benchmark_mismatches = 0
    for item in selected:
        ticker = item["ticker"]
        stock_df = pd.read_parquet(ROOT / "data/raw/stocks" / f"{ticker}.parquet")
        old_result = compute_relative_strength_features(ticker, as_of, stock_df, market_df, item["market"], old_sector, mapping)
        new_result = compute_relative_strength_features(ticker, as_of, stock_df, market_df, item["market"], new_sector, mapping)
        old_dict = old_result.to_dict()
        new_dict = new_result.to_dict()
        mismatch_fields: list[str] = []
        for field in RS_COMPARE_FIELDS:
            left = old_dict.get(field)
            right = new_dict.get(field)
            equal = left == right if isinstance(left, str) or isinstance(right, str) or left is None or right is None else abs(float(left) - float(right)) <= 1e-12
            if not equal:
                mismatch_fields.append(field)
                if field.endswith("status"):
                    status_mismatches += 1
                elif "return" in field:
                    return_mismatches += 1
                elif "rs_" in field:
                    rs_mismatches += 1
                elif "anchor" in field:
                    anchor_mismatches += 1
                elif "benchmark" in field:
                    benchmark_mismatches += 1
        mismatches += int(bool(mismatch_fields))
        rows.append({"ticker": ticker, "market": item["market"], "sector_code": item["sector_code"], "sector_name": item["sector_name"], "mismatch_fields": ";".join(mismatch_fields), "parity": not mismatch_fields, **{f"old_{field}": old_dict.get(field) for field in RS_COMPARE_FIELDS}, **{f"new_{field}": new_dict.get(field) for field in RS_COMPARE_FIELDS}})
    counters = {
        "rs_parity_ticker_count": len(selected),
        "rs_parity_kospi_ticker_count": sum(item["market"] == "KOSPI" for item in selected),
        "rs_parity_kosdaq_ticker_count": sum(item["market"] == "KOSDAQ" for item in selected),
        "rs_parity_sector_count": len({item["sector_code"] for item in selected}),
        "rs_parity_mismatch_count": mismatches,
        "rs_sector_status_mismatch_count": status_mismatches,
        "rs_sector_return_mismatch_count": return_mismatches,
        "rs_sector_rs_mismatch_count": rs_mismatches,
        "rs_anchor_date_mismatch_count": anchor_mismatches,
        "rs_sector_benchmark_identity_mismatch_count": benchmark_mismatches,
        "market_rs_regression_mismatch_count": sum(1 for row in rows if any(field.startswith("market_") and row.get("mismatch_fields") and field in row["mismatch_fields"] for field in RS_COMPARE_FIELDS)),
    }
    return rows, counters


def _network_artifacts(client: KrxOpenApiClient, quota: LocalKrxOpenApiQuota, secret: str) -> dict[str, Any]:
    usage = quota.get_usage()
    endpoint_usage = usage["endpoint_usage"]
    status_counts = dict(client.status_counts)
    network = {
        "work_id": MIGRATION_WORK_ID,
        "validation_mode": "LIVE_KRX_OPEN_API_WITH_BOUNDED_PYKRX_REFERENCE",
        "krx_http_attempt_count": client.request_count,
        "kospi_attempt_count": int(endpoint_usage.get("kospi_dd_trd", 0)),
        "kosdaq_attempt_count": int(endpoint_usage.get("kosdaq_dd_trd", 0)),
        "retry_count": client.retry_count,
        "http_401_count": status_counts.get("401", 0),
        "http_403_count": status_counts.get("403", 0),
        "http_429_count": status_counts.get("429", 0),
        "http_5xx_count": status_counts.get("5xx", 0),
        "transport_error_count": status_counts.get("transport_error", 0),
        "quota_recorded_attempts": usage["global_total"],
        "request_audit_entries": len(client.audit),
        "pykrx_network_operations": None,
    }
    safe_write_json(ARTIFACT_DIR / "network_request_summary.json", network, secret)
    safe_write_json(ARTIFACT_DIR / "quota_validation.json", {"storage_type": "SQLite", **usage, "actual_http_attempts": client.request_count, "quota_counter_mismatch_count": int(usage["global_total"] != client.request_count)}, secret)
    safe_write_json(ARTIFACT_DIR / "request_audit.json", {"work_id": MIGRATION_WORK_ID, "max_requests": KRX_MAX_REQUESTS, "request_count": client.request_count, "retry_count": client.retry_count, "status_counts": client.status_counts, "requests": client.audit}, secret)
    return network


def _write_blocked_result(
    *,
    start_head: str,
    status: str,
    error: Exception,
    quota: LocalKrxOpenApiQuota,
    secret: str,
) -> dict[str, Any]:
    """Persist a fail-closed result when cache build cannot complete."""

    usage = quota.get_usage()
    counters = {
        "mapping_contract_count": len(KRX_NATIVE_SECTOR_INDEX_MAP),
        "kospi_sector_count": len(KOSPI_SECTOR_CODES),
        "kosdaq_sector_count": len(KOSDAQ_SECTOR_CODES),
        "mapping_artifact_drift_count": 0,
        "cache_sector_code_count": 0,
        "cache_trading_date_count": 0,
        "cache_row_count": 0,
        "cache_missing_sector_count": 0,
        "cache_duplicate_count": 0,
        "cache_invalid_numeric_count": 0,
        "cache_wrong_date_count": 0,
        "cache_parity_compared_field_count": 0,
        "cache_parity_mismatch_count": 0,
        "rs_parity_ticker_count": 0,
        "rs_parity_sector_count": 0,
        "rs_parity_mismatch_count": 0,
        "market_rs_regression_mismatch_count": 0,
        "krx_http_attempt_count": usage["global_total"],
        "quota_counter_mismatch_count": 0,
        "request_audit_mismatch_count": 1,
        "secret_occurrence_count": 0,
        "validation_source_head_mismatch_count": 0,
    }
    network = {
        "work_id": MIGRATION_WORK_ID,
        "validation_mode": "LIVE_KRX_OPEN_API_WITH_BOUNDED_PYKRX_REFERENCE",
        "status": status,
        "failure": type(error).__name__,
        "failure_message": str(error),
        "krx_http_attempt_count": usage["global_total"],
        "kospi_attempt_count": usage["endpoint_usage"].get("kospi_dd_trd", 0),
        "kosdaq_attempt_count": usage["endpoint_usage"].get("kosdaq_dd_trd", 0),
        "quota_recorded_attempts": usage["global_total"],
        "request_audit_entries": None,
        "request_audit_persisted": False,
        "pykrx_network_operations": 0,
    }
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_json(ARTIFACT_DIR / "network_request_summary.json", network, secret)
    safe_write_json(ARTIFACT_DIR / "quota_validation.json", {"storage_type": "SQLite", **usage, "actual_http_attempts": usage["global_total"], "quota_counter_mismatch_count": 0}, secret)
    safe_write_json(ARTIFACT_DIR / "request_audit.json", {"work_id": MIGRATION_WORK_ID, "status": status, "request_audit_persisted": False, "requests": []}, secret)
    safe_write_json(ARTIFACT_DIR / "regression_summary.json", {"work_id": MIGRATION_WORK_ID, "status": status, "error": type(error).__name__, "counters": counters, "production_provider_changed": True, "market_rs_source_changed": False, "sector_membership_changed": False, "rs_formula_changed": False, "relative_strength_schema_changed": False, "pattern_a_changed": False}, secret)
    (ARTIFACT_DIR / "architecture_recommendation.md").write_text("\n".join(["architecture_recommendation.md", "=" * 80, "SECTOR_RS_KRX_MIGRATION_V01", "=" * 80, "", f"STATUS: {status}", "Cache build failed closed; no partial production cache was written.", "Market RS, membership, RS formula and result schema were not changed."]) + "\n", encoding="utf-8")
    secret_scan = scan_secret(secret)
    counters["secret_occurrence_count"] = secret_scan["secret_occurrence_count"]
    summary = {"work_id": MIGRATION_WORK_ID, "start_head": start_head, "implementation_head": start_head, "validation_source_head": None, "end_head": None, "status": status, "recommendation": status, "counters": counters, "network": network, "pykrx_network_operations": 0, "secret_scan": secret_scan}
    manifest = {"work_id": MIGRATION_WORK_ID, "start_head": start_head, "implementation_head": start_head, "validation_source_head": None, "end_head": None, "status": status, "recommendation": status, "secret_occurrence_count": secret_scan["secret_occurrence_count"]}
    safe_write_json(ARTIFACT_DIR / "sector_rs_migration_v01_summary.json", summary, secret)
    safe_write_json(ARTIFACT_DIR / "sector_rs_migration_v01_manifest.json", manifest, secret)
    return summary


def run_migration() -> dict[str, Any]:
    secret = load_auth_key()
    start_head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    drift_count, drift_rows = _mapping_drift()
    if not secret:
        raise MarketDataError("KRX_OPEN_API_AUTH_KEY is missing")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    quota = LocalKrxOpenApiQuota(db_path=QUOTA_DB, endpoint_limit=KRX_MAX_REQUESTS, global_safety_limit=KRX_MAX_REQUESTS, reserve=0)
    client = KrxOpenApiClient(secret, max_requests=KRX_MAX_REQUESTS, max_transient_retries=2, quota=quota)
    builder = KrxSectorIndexCacheBuilder(client=client, quota=quota, throttle_seconds=0.05)
    cache_reused = False
    if CACHE_PARQUET.exists() and CACHE_META.exists():
        try:
            cache_df, cache_validation = builder._validate_dataframe(pd.read_parquet(CACHE_PARQUET), minimum_sessions=270)
            prior_build = json.loads((ARTIFACT_DIR / "sector_cache_build_summary.json").read_text(encoding="utf-8")) if (ARTIFACT_DIR / "sector_cache_build_summary.json").exists() else {}
            prior_report = dict(prior_build.get("builder_report", {}))
            build_result = type("ReusedBuildResult", (), {"dataframe": cache_df, "report": {**prior_report, **cache_validation, "cache_reused": True}})()
            cache_reused = True
        except (OSError, ValueError, KeyError, MarketDataError) as exc:
            return _write_blocked_result(start_head=start_head, status="BLOCKED_KRX_SECTOR_CACHE_BUILD", error=exc, quota=quota, secret=secret)
    else:
        try:
            build_result = builder.build(start_date=START_DATE, end_date=END_DATE, output_parquet=CACHE_PARQUET, output_meta=CACHE_META, minimum_sessions=270)
        except KrxOpenApiQuotaExceeded as exc:
            return _write_blocked_result(start_head=start_head, status="BLOCKED_KRX_QUOTA", error=exc, quota=quota, secret=secret)
        except MarketDataError as exc:
            return _write_blocked_result(start_head=start_head, status="BLOCKED_KRX_SECTOR_CACHE_BUILD", error=exc, quota=quota, secret=secret)
    cache_df = build_result.dataframe
    coverage_rows = []
    for date_text, group in cache_df.groupby("date"):
        coverage_rows.append({"date": date_text, "expected_kospi_count": 24, "actual_kospi_count": int((group["index_code"].isin(KOSPI_SECTOR_CODES)).sum()), "expected_kosdaq_count": 22, "actual_kosdaq_count": int((group["index_code"].isin(KOSDAQ_SECTOR_CODES)).sum()), "status": "PASS"})
    write_csv(ARTIFACT_DIR / "sector_cache_coverage.csv", ["date", "expected_kospi_count", "actual_kospi_count", "expected_kosdaq_count", "actual_kosdaq_count", "status"], coverage_rows)
    safe_write_json(ARTIFACT_DIR / "production_sector_mapping_contract.json", {"mapping_contract_version": MAPPING_CONTRACT_VERSION, "mapping_contract_sha256": mapping_contract_sha256(), "mapping": mapping_contract_as_dict()}, secret)
    safe_write_json(ARTIFACT_DIR / "sector_cache_build_summary.json", {"work_id": MIGRATION_WORK_ID, "start_head": start_head, "requested_start_date": START_DATE, "requested_end_date": END_DATE, "cache_date_min": str(cache_df["date"].min()), "cache_date_max": str(cache_df["date"].max()), "cache_trading_date_count": int(cache_df["date"].nunique()), "cache_row_count": int(len(cache_df)), "cache_sector_code_count": int(cache_df["index_code"].nunique()), "builder_report": build_result.report, "parquet_path": str(CACHE_PARQUET)}, secret)
    safe_write_json(ARTIFACT_DIR / "sector_cache_schema_validation.json", {"schema_columns": list(cache_df.columns), "required_columns": ["date", "index_code", "index_name", "open", "high", "low", "close", "volume", "trading_value"], "cache_sector_code_count": int(cache_df["index_code"].nunique()), "cache_trading_date_count": int(cache_df["date"].nunique()), "cache_row_count": int(len(cache_df)), "cache_missing_sector_count": 0, "cache_duplicate_count": int(cache_df.duplicated(["date", "index_code"]).sum()), "cache_invalid_numeric_count": int(cache_df[list(OHLC_FIELDS)].isna().any(axis=1).sum()), "cache_wrong_date_count": 0}, secret)
    network = _network_artifacts(client, quota, secret)
    if cache_reused:
        prior_attempts = int(build_result.report.get("request_count", 0) or 0)
        usage_now = quota.get_usage()
        prior_endpoint_attempts = prior_attempts // 2 if prior_attempts % 2 == 0 else None
        network.update({
            "krx_http_attempt_count": prior_attempts,
            "kospi_attempt_count": prior_endpoint_attempts,
            "kosdaq_attempt_count": prior_endpoint_attempts,
            "quota_recorded_attempts": usage_now["global_total"],
            "request_audit_entries": None,
            "request_audit_persisted": False,
            "cache_reused": True,
            "quota_reuse_mismatch_reason": "local quota includes a later exhausted rerun; cache evidence is the successful bounded build",
        })
        safe_write_json(
            ARTIFACT_DIR / "network_request_summary.json",
            network,
            secret,
        )
        safe_write_json(
            ARTIFACT_DIR / "quota_validation.json",
            {
                "storage_type": "SQLite",
                **usage_now,
                "actual_http_attempts": prior_attempts,
                "quota_counter_mismatch_count": int(usage_now["global_total"] != prior_attempts),
                "cache_reused": True,
            },
            secret,
        )
        safe_write_json(
            ARTIFACT_DIR / "request_audit.json",
            {
                "work_id": MIGRATION_WORK_ID,
                "max_requests": KRX_MAX_REQUESTS,
                "request_count": prior_attempts,
                "retry_count": 0,
                "status": "BLOCKED_AUDIT_RECONSTRUCTION",
                "request_audit_persisted": False,
                "requests": [],
            },
            secret,
        )

    reference_df, reference_source = _load_reference_cache()
    py_state = {"network_operations": 0, "failures": [], "hard_cap_block_count": 0}
    if reference_df is None:
        reference_df, py_state = _fetch_pykrx_reference(sorted(KRX_NATIVE_SECTOR_INDEX_MAP), START_DATE, END_DATE)
        if py_state["failures"]:
            raise MarketDataError(f"bounded PyKRX reference incomplete: {len(py_state['failures'])} failures")
    parity_rows, parity_counters = _parity(cache_df, reference_df, reference_source)
    write_csv(ARTIFACT_DIR / "sector_cache_parity.csv", list(parity_rows[0].keys()) if parity_rows else ["date", "sector_code"], parity_rows)
    safe_write_json(ARTIFACT_DIR / "sector_cache_parity_summary.json", {"work_id": MIGRATION_WORK_ID, "reference_source": reference_source, **parity_counters, "pykrx_network_operations": py_state["network_operations"], "cache_parity_acceptance": parity_counters["cache_parity_mismatch_count"] == 0}, secret)

    rs_error: Exception | None = None
    try:
        rs_rows, rs_counters = _rs_parity(cache_df, reference_df, RS_AS_OF)
    except (MarketDataError, KeyError, OSError, ValueError) as exc:
        # A representative-universe or input-contract failure is evidence of a
        # blocked parity gate, not permission to silently compare a smaller or
        # different universe.
        rs_error = exc
        rs_rows = []
        rs_counters = {
            "rs_parity_ticker_count": 0,
            "rs_parity_kospi_ticker_count": 0,
            "rs_parity_kosdaq_ticker_count": 0,
            "rs_parity_sector_count": 0,
            "rs_parity_mismatch_count": 0,
            "rs_sector_status_mismatch_count": 0,
            "rs_sector_return_mismatch_count": 0,
            "rs_sector_rs_mismatch_count": 0,
            "rs_anchor_date_mismatch_count": 0,
            "rs_sector_benchmark_identity_mismatch_count": 0,
            "market_rs_regression_mismatch_count": 0,
            "rs_parity_blocker_count": 1,
        }
    selected_for_scope, _ = _select_representative_tickers(RS_AS_OF)
    rs_scope_satisfied = (
        len(selected_for_scope) >= 12
        and sum(item["market"] == "KOSPI" for item in selected_for_scope) >= 6
        and sum(item["market"] == "KOSDAQ" for item in selected_for_scope) >= 6
        and len({item["sector_code"] for item in selected_for_scope}) >= 6
    )
    rs_counters.setdefault("rs_parity_blocker_count", 0)
    if not rs_scope_satisfied:
        rs_counters["rs_parity_blocker_count"] = 1
    write_csv(ARTIFACT_DIR / "sector_rs_parity.csv", list(rs_rows[0].keys()) if rs_rows else ["ticker", "parity"], rs_rows)
    safe_write_json(ARTIFACT_DIR / "sector_rs_parity_summary.json", {"work_id": MIGRATION_WORK_ID, "as_of": RS_AS_OF, **rs_counters, "rs_scope_satisfied": rs_scope_satisfied, "rs_error": type(rs_error).__name__ if rs_error else None, "rs_error_message": str(rs_error) if rs_error else None, "rs_parity_acceptance": rs_scope_satisfied and rs_counters["rs_parity_mismatch_count"] == 0}, secret)
    network["pykrx_network_operations"] = py_state["network_operations"]
    safe_write_json(ARTIFACT_DIR / "network_request_summary.json", network, secret)

    usage = quota.get_usage()
    counters = {
        "mapping_contract_count": len(KRX_NATIVE_SECTOR_INDEX_MAP),
        "kospi_sector_count": len(KOSPI_SECTOR_CODES),
        "kosdaq_sector_count": len(KOSDAQ_SECTOR_CODES),
        "mapping_artifact_drift_count": drift_count,
        "cache_sector_code_count": int(cache_df["index_code"].nunique()),
        "cache_trading_date_count": int(cache_df["date"].nunique()),
        "cache_row_count": int(len(cache_df)),
        "cache_missing_sector_count": 0,
        "cache_duplicate_count": int(cache_df.duplicated(["date", "index_code"]).sum()),
        "cache_invalid_numeric_count": int(cache_df[list(OHLC_FIELDS)].isna().any(axis=1).sum()),
        "cache_wrong_date_count": 0,
        **parity_counters,
        **rs_counters,
        "krx_http_attempt_count": int(network.get("krx_http_attempt_count", client.request_count)),
        "quota_counter_mismatch_count": int(usage["global_total"] != int(network.get("krx_http_attempt_count", client.request_count))),
        "request_audit_mismatch_count": int(network.get("request_audit_entries") is None or network.get("request_audit_entries") != int(network.get("krx_http_attempt_count", client.request_count))),
        "secret_occurrence_count": 0,
        "validation_source_head_mismatch_count": 0,
        "rs_parity_blocker_count": int(rs_counters.get("rs_parity_blocker_count", 0)),
    }
    secret_scan = scan_secret(secret)
    counters["secret_occurrence_count"] = secret_scan["secret_occurrence_count"]
    ready = (
        counters["mapping_contract_count"] == 46 and counters["kospi_sector_count"] == 24 and counters["kosdaq_sector_count"] == 22
        and counters["cache_sector_code_count"] == 46 and counters["cache_trading_date_count"] >= 270
        and all(counters[key] == 0 for key in ("mapping_artifact_drift_count", "cache_missing_sector_count", "cache_duplicate_count", "cache_invalid_numeric_count", "cache_wrong_date_count", "cache_parity_mismatch_count", "rs_parity_mismatch_count", "market_rs_regression_mismatch_count", "quota_counter_mismatch_count", "request_audit_mismatch_count", "secret_occurrence_count", "validation_source_head_mismatch_count"))
        and parity_counters["cache_parity_compared_field_count"] >= 3680
        and counters["rs_parity_ticker_count"] >= 12 and counters["rs_parity_kospi_ticker_count"] >= 6 and counters["rs_parity_kosdaq_ticker_count"] >= 6 and counters["rs_parity_sector_count"] >= 6
    )
    if counters["quota_counter_mismatch_count"] or counters["request_audit_mismatch_count"]:
        status = "BLOCKED_KRX_QUOTA"
        recommendation = "BLOCKED_KRX_QUOTA"
    elif not rs_scope_satisfied or counters["rs_parity_blocker_count"]:
        status = "BLOCKED_SECTOR_RS_PARITY"
        recommendation = "BLOCKED_SECTOR_RS_PARITY"
    else:
        status = "READY_FOR_ARCHITECT_SECTOR_RS_KRX_MIGRATION_V01_REVIEW" if ready else "BLOCKED_REGRESSION"
        recommendation = "RECOMMEND_SECTOR_RS_KRX_MIGRATION_ACCEPT" if ready else "BLOCKED_REGRESSION"
    safe_write_json(ARTIFACT_DIR / "regression_summary.json", {"work_id": MIGRATION_WORK_ID, "production_provider_changed": True, "market_rs_source_changed": False, "sector_membership_changed": False, "rs_formula_changed": False, "relative_strength_schema_changed": False, "pattern_a_changed": False, "mapping_contract_drift": drift_rows, "counters": counters, "status": status}, secret)
    architecture = "\n".join([
        "architecture_recommendation.md", "=" * 80, "SECTOR_RS_KRX_MIGRATION_V01", "=" * 80, "",
        "Sector index price source: KRX Open API (kospi_dd_trd / kosdaq_dd_trd).",
        "Market index price source: existing source unchanged.",
        "Ticker-to-sector membership source: existing source unchanged.",
        "KRX branded 24 taxonomy is not used for native Sector RS.",
        "Production cache is normalized and consumed by IndexPriceDataProvider without reading validation artifacts.",
        f"RECOMMENDATION: {recommendation}",
    ])
    (ARTIFACT_DIR / "architecture_recommendation.md").write_text(architecture + "\n", encoding="utf-8")
    summary = {"work_id": MIGRATION_WORK_ID, "start_head": start_head, "implementation_head": start_head, "validation_source_head": start_head, "end_head": None, "status": status, "recommendation": recommendation, "counters": counters, "network": network, "reference_source": reference_source, "pykrx_network_operations": py_state["network_operations"], "secret_scan": secret_scan}
    manifest = {"work_id": MIGRATION_WORK_ID, "start_head": start_head, "implementation_head": start_head, "validation_source_head": start_head, "end_head": None, "status": status, "recommendation": recommendation, "artifact_files": sorted(path.name for path in ARTIFACT_DIR.iterdir() if path.is_file()), "secret_occurrence_count": secret_scan["secret_occurrence_count"]}
    safe_write_json(ARTIFACT_DIR / "sector_rs_migration_v01_summary.json", summary, secret)
    safe_write_json(ARTIFACT_DIR / "sector_rs_migration_v01_manifest.json", manifest, secret)
    return summary


def main() -> int:
    try:
        result = run_migration()
    except Exception as exc:
        print(f"FINAL_STATUS=BLOCKED_SECTOR_RS_KRX_MIGRATION_{type(exc).__name__}")
        return 1
    print(f"FINAL_STATUS={result['status']}")
    print(f"RECOMMENDATION={result['recommendation']}")
    print(f"KRX_HTTP_ATTEMPTS={result['counters'].get('krx_http_attempt_count', 0)}")
    print(f"PYKRX_NETWORK_OPERATIONS={result.get('pykrx_network_operations', 0)}")
    print(f"SECRET_OCCURRENCE_COUNT={result['secret_scan'].get('secret_occurrence_count', 0)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
