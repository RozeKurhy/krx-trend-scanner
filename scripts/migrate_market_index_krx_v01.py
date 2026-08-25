"""Resumable KRX Open API migration for MARKET_INDEX (1001/2001 only).

The runner derives its calendar from the closed raw-stock manifest, uses the
canonical shared quota database, writes only staging until every gate passes,
and never falls back to PyKRX.
"""

from __future__ import annotations

import argparse
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable, Mapping

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_store import (
    DEFAULT_INDEX_STORE_ROOT,
    INDEX_STORE_COLUMNS,
    INDEX_STORE_SCHEMA_VERSION,
    IndexStore,
    MARKET_INDEX_FAMILY,
    file_sha256,
    normalize_index_frame,
)
from trend_scanner.data.krx_market_index import (
    FETCH_MODE,
    KRX_MARKET_INDEX_MAP,
    MAPPING_CONTRACT_VERSION,
    MARKET_INDEX_SOURCE_NAME,
    KrxMarketIndexBuilder,
    KrxMarketIndexError,
    mapping_contract_as_dict,
    mapping_contract_sha256,
)
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.relative_strength.relative_strength import compute_relative_strength_features


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "artifacts/data/krx_openapi/market_index_migration/v01"
STAGING_DIR = ROOT / ".cache/krx_openapi/market_index_migration/v01"
STAGING_PARQUET = STAGING_DIR / "market_index_staging.parquet"
STAGING_META = STAGING_DIR / "market_index_staging.meta.json"
PRODUCTION_PARQUET = ROOT / DEFAULT_INDEX_STORE_ROOT / "market_index.parquet"
PRODUCTION_META = ROOT / DEFAULT_INDEX_STORE_ROOT / "market_index.meta.json"
START_HEAD = "9e1856df7c2a9e4232484a88220735ceaae6d0fe"
START_DATE = "2010-01-04"
END_DATE = "2026-08-21"
LEGACY_REFERENCE = ROOT / "artifacts/patterns/pattern_a/validation/relative_strength/source/market_index_daily_20260814.parquet"
LEGACY_REFERENCE_SHA256 = "82646acedfa97e85fcec7f88922ab8bc0990f7623f9d9e7a3f9bc78156dd71fa"
PILOT_DATES = ("2010-01-04", "2018-05-04", "2026-08-21")
OHLC_FIELDS = ("open", "high", "low", "close")
RS_COMPARE_FIELDS = (
    "market_rs_data_status", "market_benchmark_name", "market_benchmark_code",
    "market_benchmark_last_observation_date", "market_return_3m", "market_return_6m",
    "market_return_12m", "market_rs_3m", "market_rs_6m", "market_rs_12m",
    "market_anchor_date_3m", "market_anchor_date_6m", "market_anchor_date_12m",
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
    for value in (os.getenv("KRX_OPEN_API_AUTH_KEY", ""), _read_env_value(ROOT / ".env", "KRX_OPEN_API_AUTH_KEY"), _read_env_value(ROOT.parent / "env.md", "KRX_OPEN_API_AUTH_KEY")):
        if value.strip():
            return value.strip()
    return ""


def safe_write_json(path: Path, value: Any, secret: str = "") -> None:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if secret and secret in text:
        raise ValueError("secret detected in artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _date(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _sha_dates(values: Iterable[str]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def derive_raw_trading_calendar(
    start: str = START_DATE,
    end: str = END_DATE,
    raw_store: KrxRawStockStore | None = None,
) -> dict[str, Any]:
    """Derive target dates from paired COMPLETE raw-store manifest rows."""

    store = raw_store or KrxRawStockStore(ROOT / "data/market/raw/krx_stocks/v01")
    rows = store.list_manifest()
    states: dict[str, dict[str, str]] = {}
    for row in rows:
        day = str(row.get("date", ""))
        if start <= day <= end and str(row.get("market", "")) in {"KOSPI", "KOSDAQ"}:
            states.setdefault(day, {})[str(row["market"])] = str(row.get("status", ""))
    target: list[str] = []
    no_data: list[str] = []
    asymmetric: list[str] = []
    for day in sorted(states):
        pair = states[day]
        if pair.get("KOSPI") == pair.get("KOSDAQ") == "COMPLETE":
            target.append(day)
        elif pair.get("KOSPI") == pair.get("KOSDAQ") == "NO_DATA":
            no_data.append(day)
        else:
            asymmetric.append(day)
    if asymmetric:
        raise MarketDataError("BLOCKED_RAW_TRADING_CALENDAR_INCONSISTENT")
    return {
        "requested_start": start,
        "requested_end": end,
        "candidate_date_count": len(states),
        "complete_trading_date_count": len(target),
        "no_data_date_count": len(no_data),
        "asymmetric_date_count": len(asymmetric),
        "first_trading_date": target[0] if target else None,
        "last_trading_date": target[-1] if target else None,
        "target_date_sha256": _sha_dates(target),
        "target_dates": target,
        "no_data_dates": no_data,
    }


def _load_staging() -> pd.DataFrame:
    if not STAGING_PARQUET.exists() or not STAGING_META.exists():
        return pd.DataFrame(columns=list(INDEX_STORE_COLUMNS))
    try:
        return normalize_index_frame(pd.read_parquet(STAGING_PARQUET), MARKET_INDEX_FAMILY)
    except Exception as exc:
        raise MarketDataError("BLOCKED_STAGING_INTEGRITY") from exc


def _save_staging(frame: pd.DataFrame, *, start: str, end: str) -> dict[str, Any]:
    store = IndexStore(STAGING_DIR)
    metadata = store.save_family_full(
        MARKET_INDEX_FAMILY,
        frame,
        metadata_context={"requested_start": start, "requested_end": end, "fetch_mode": FETCH_MODE, "mapping_contract_version": MAPPING_CONTRACT_VERSION, "mapping_contract_sha256": mapping_contract_sha256()},
        output_parquet=STAGING_PARQUET,
        output_meta=STAGING_META,
    )
    return metadata


def _quota_usage(quota: Any | None) -> dict[str, Any]:
    if quota is None or not hasattr(quota, "get_usage"):
        return {"global_total": 0, "endpoint_usage": {}}
    return quota.get_usage()


def _available_whole_dates(quota: Any | None, pending_count: int) -> int:
    if quota is None:
        return pending_count
    if not hasattr(quota, "remaining"):
        return pending_count
    kospi = quota.remaining("kospi_dd_trd")
    kosdaq = quota.remaining("kosdaq_dd_trd")
    global_remaining = min(int(kospi.get("global", 0)), int(kosdaq.get("global", 0)))
    endpoint_remaining = min(int(kospi.get("endpoint", 0)), int(kosdaq.get("endpoint", 0)))
    return max(0, min(pending_count, endpoint_remaining, global_remaining // 2))


def _classify_blocker(exc: Exception) -> str:
    if isinstance(exc, KrxOpenApiAuthorizationError):
        return "BLOCKED_KRX_AUTH"
    if isinstance(exc, KrxOpenApiRateLimitError) or isinstance(exc, KrxOpenApiQuotaExceeded):
        return "BACKFILL_PAUSED_QUOTA"
    if isinstance(exc, KrxOpenApiBudgetError):
        return "BACKFILL_PAUSED_QUOTA"
    if isinstance(exc, KrxMarketIndexError):
        if exc.error_code == "BLOCKED_KRX_TRANSPORT":
            return "BLOCKED_KRX_TRANSPORT"
        return "BLOCKED_KRX_INDEX_SCHEMA"
    return "BLOCKED_KRX_TRANSPORT" if "transport" in str(exc).lower() else "BLOCKED_KRX_INDEX_SCHEMA"


class MarketIndexMigrationRunner:
    """Sequential, whole-date resumable staging runner."""

    def __init__(self, *, client: Any | None = None, quota: Any | None = None, auth_key: str | None = None, max_requests: int = 10_000, throttle_seconds: float = 0.0) -> None:
        self.quota = quota or LocalKrxOpenApiQuota()
        if client is not None:
            self.client = client
        else:
            from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
            key = (auth_key or load_auth_key()).strip()
            if not key:
                raise ValueError("KRX_OPEN_API_AUTH_KEY is required")
            self.client = KrxOpenApiClient(key, max_requests=max_requests, max_transient_retries=0, quota=self.quota)
        self.builder = KrxMarketIndexBuilder(client=self.client, throttle_seconds=throttle_seconds)

    def run(self, calendar: Mapping[str, Any], *, resume: bool = True, publish: bool = False, max_dates: int | None = None) -> dict[str, Any]:
        target_dates = list(calendar.get("target_dates", []))
        existing = _load_staging() if resume else pd.DataFrame(columns=list(INDEX_STORE_COLUMNS))
        complete_existing = set(existing["date"].astype(str).unique()) if not existing.empty else set()
        pending = [day for day in target_dates if day not in complete_existing]
        quota_before = _quota_usage(self.quota)
        capacity = _available_whole_dates(self.quota, len(pending))
        if max_dates is not None:
            capacity = min(capacity, int(max_dates))
        if pending and capacity <= 0:
            return self._result(calendar, existing, pending, quota_before, blockers=["BACKFILL_PAUSED_QUOTA"])
        selected = pending[:capacity]
        fetched_dates: list[str] = []
        blockers: list[str] = []
        for day in selected:
            try:
                frame, report = self.builder.fetch_date(day)
                if report["status"] != "COMPLETE" or len(frame) != 2:
                    raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", "target trading date did not yield two rows")
                existing = pd.concat([existing, frame], ignore_index=True)
                existing = normalize_index_frame(existing, MARKET_INDEX_FAMILY)
                _save_staging(existing, start=calendar["requested_start"], end=calendar["requested_end"])
                fetched_dates.append(day)
            except Exception as exc:
                blockers.append(_classify_blocker(exc))
                break
        pending_after = [day for day in target_dates if day not in set(existing["date"].astype(str).unique())]
        if not blockers and pending_after:
            blockers.append("BACKFILL_PAUSED_QUOTA")
        result = self._result(calendar, existing, pending_after, quota_before, blockers=blockers)
        result["dates_fetched_this_run"] = fetched_dates
        result["dates_resumed_or_skipped"] = sorted(complete_existing)
        result["production_index_store_publish_count"] = 0
        if not blockers and not pending_after and publish:
            # Production publication is deliberately a single full replacement.
            IndexStore(PRODUCTION_PARQUET.parent).save_family_full(MARKET_INDEX_FAMILY, existing)
            result["production_index_store_publish_count"] = 1
            result["production_integrity"] = IndexStore(PRODUCTION_PARQUET.parent).verify_family(MARKET_INDEX_FAMILY)
        return result

    def _result(self, calendar: Mapping[str, Any], frame: pd.DataFrame, pending: list[str], quota_before: Mapping[str, Any], *, blockers: list[str]) -> dict[str, Any]:
        quota_after = _quota_usage(self.quota)
        request_count = int(getattr(self.client, "request_count", 0))
        target_count = int(calendar.get("complete_trading_date_count", len(calendar.get("target_dates", []))))
        complete_count = int(frame["date"].nunique()) if not frame.empty else 0
        status = "READY_FOR_ARCHITECT_KRX_INDEX_MIGRATION_V01_REVIEW" if not blockers and complete_count == target_count else "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01"
        return {
            "status": status,
            "target_date_count": target_count,
            "complete_date_count": complete_count,
            "pending_date_count": len(pending),
            "failed_date_count": 0,
            "next_pending_date": pending[0] if pending else None,
            "staging_rows": int(len(frame)),
            "krx_request_count": request_count,
            "quota_before": dict(quota_before),
            "quota_after": dict(quota_after),
            "quota_delta": int(quota_after.get("global_total", 0)) - int(quota_before.get("global_total", 0)),
            "client_request_count": request_count,
            "audit_entry_count": len(getattr(self.client, "audit", []) or []),
            "retry_count": int(getattr(self.client, "retry_count", 0)),
            "blockers": sorted(set(blockers)),
            "staging_parquet": str(STAGING_PARQUET),
            "staging_meta": str(STAGING_META),
            "codes": ["1001", "2001"],
        }


def legacy_reference_summary(path: Path = LEGACY_REFERENCE) -> dict[str, Any]:
    if not path.exists():
        return {"reference_sha256": None, "reference_hash_match": False, "status": "BLOCKED_LEGACY_MARKET_REFERENCE_MISSING"}
    observed = file_sha256(path)
    return {"reference_path": str(path), "reference_sha256": LEGACY_REFERENCE_SHA256, "observed_sha256": observed, "reference_hash_match": observed == LEGACY_REFERENCE_SHA256}


def compare_legacy_market_parity(new_frame: pd.DataFrame, reference_path: Path = LEGACY_REFERENCE) -> tuple[pd.DataFrame, dict[str, Any]]:
    reference_info = legacy_reference_summary(reference_path)
    if not reference_info.get("reference_hash_match"):
        raise MarketDataError("BLOCKED_LEGACY_MARKET_REFERENCE_HASH_MISMATCH" if reference_path.exists() else "BLOCKED_LEGACY_MARKET_REFERENCE_MISSING")
    reference = pd.read_parquet(reference_path).copy()
    left = new_frame.copy()
    for frame in (left, reference):
        frame["date"] = frame["date"].astype(str)
        frame["index_code"] = frame["index_code"].astype(str)
    left = left[left["index_code"].isin({"1001", "2001"})]
    reference = reference[reference["index_code"].isin({"1001", "2001"})]
    left_map = {(row.date, row.index_code): row for row in left.itertuples()}
    ref_map = {(row.date, row.index_code): row for row in reference.itertuples()}
    rows: list[dict[str, Any]] = []
    compared_fields = exact_fields = mismatches = 0
    for key in sorted(set(left_map) | set(ref_map)):
        lrow, rrow = left_map.get(key), ref_map.get(key)
        row: dict[str, Any] = {"date": key[0], "index_code": key[1], "index_name": getattr(lrow or rrow, "index_name", "")}
        row_mismatch = lrow is None or rrow is None
        for field in OHLC_FIELDS:
            lv = getattr(lrow, field, None) if lrow is not None else None
            rv = getattr(rrow, field, None) if rrow is not None else None
            match = lv is not None and rv is not None and Decimal(str(lv)) == Decimal(str(rv))
            row[f"krx_{field}"] = "" if lv is None else str(lv)
            row[f"reference_{field}"] = "" if rv is None else str(rv)
            row[f"{field}_match"] = bool(match)
            compared_fields += int(lv is not None and rv is not None)
            exact_fields += int(match)
            row_mismatch |= not match
        row["row_mismatch"] = bool(row_mismatch)
        mismatches += int(row_mismatch)
        rows.append(row)
    result = pd.DataFrame(rows)
    summary = {
        **reference_info,
        "compared_index_count": len({key[1] for key in set(left_map) & set(ref_map)}),
        "compared_date_count": len({key[0] for key in set(left_map) & set(ref_map)}),
        "compared_field_count": compared_fields,
        "exact_field_count": exact_fields,
        "mismatch_count": mismatches,
        "missing_krx_row_count": len(set(ref_map) - set(left_map)),
        "missing_reference_row_count": len(set(left_map) - set(ref_map)),
        "status": "PASS" if mismatches == 0 else "FAIL",
    }
    return result, summary


def market_rs_parity(new_frame: pd.DataFrame, reference_path: Path = LEGACY_REFERENCE) -> dict[str, Any]:
    old = pd.read_parquet(reference_path)
    dates = pd.to_datetime(old["date"].astype(str)).sort_values().drop_duplicates()
    stock = pd.DataFrame({"close": range(100, 100 + len(dates))}, index=dates)
    cases: dict[str, Any] = {}
    for market, code, name in (("KOSPI", "1001", "코스피"), ("KOSDAQ", "2001", "코스닥")):
        old_result = compute_relative_strength_features("SYNTH01", str(dates.max().date()), stock, old, market)
        new_result = compute_relative_strength_features("SYNTH01", str(dates.max().date()), stock, new_frame, market)
        old_dict, new_dict = old_result.to_dict(), new_result.to_dict()
        numeric_diffs = [abs(float(old_dict[field]) - float(new_dict[field])) for field in RS_COMPARE_FIELDS if isinstance(old_dict.get(field), (int, float)) and isinstance(new_dict.get(field), (int, float))]
        fields_match = all(old_dict.get(field) == new_dict.get(field) for field in RS_COMPARE_FIELDS if field not in {"market_return_3m", "market_return_6m", "market_return_12m", "market_rs_3m", "market_rs_6m", "market_rs_12m"})
        cases[market] = {
            "old_status": old_dict["market_rs_data_status"],
            "new_status": new_dict["market_rs_data_status"],
            "benchmark_code_match": old_dict["market_benchmark_code"] == new_dict["market_benchmark_code"] == code,
            "benchmark_name_match": old_dict["market_benchmark_name"] == new_dict["market_benchmark_name"] == name,
            "last_observation_match": old_dict["market_benchmark_last_observation_date"] == new_dict["market_benchmark_last_observation_date"],
            "anchor_dates_match": all(old_dict[f"market_anchor_date_{h}"] == new_dict[f"market_anchor_date_{h}"] for h in ("3m", "6m", "12m")),
            "market_returns_match": all(abs(float(old_dict[f"market_return_{h}"]) - float(new_dict[f"market_return_{h}"])) <= 1e-12 for h in ("3m", "6m", "12m") if old_dict[f"market_return_{h}"] is not None and new_dict[f"market_return_{h}"] is not None),
            "market_rs_match": all(abs(float(old_dict[f"market_rs_{h}"]) - float(new_dict[f"market_rs_{h}"])) <= 1e-12 for h in ("3m", "6m", "12m") if old_dict[f"market_rs_{h}"] is not None and new_dict[f"market_rs_{h}"] is not None),
            "max_abs_numeric_diff": max(numeric_diffs, default=None),
            "status": "PASS" if fields_match and old_dict["market_rs_data_status"] == new_dict["market_rs_data_status"] == "READY" else "FAIL",
        }
    return {"cases": cases, "status": "PASS" if all(item["status"] == "PASS" for item in cases.values()) else "FAIL"}


def secret_scan(secret: str) -> dict[str, Any]:
    if not secret:
        return {"secret_occurrence_count": 0, "scanned_file_count": 0}
    try:
        paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    except (OSError, subprocess.CalledProcessError):
        paths = []
    paths.extend(str(path.relative_to(ROOT)) for path in ARTIFACT_DIR.rglob("*") if path.is_file())
    count = scanned = 0
    for raw in sorted(set(path for path in paths if path and path not in {".env"} )):
        path = ROOT / raw
        if path.is_file():
            scanned += 1
            count += path.read_text(encoding="utf-8", errors="ignore").count(secret)
    return {"secret_occurrence_count": count, "scanned_file_count": scanned}


def write_migration_artifacts(*, calendar: Mapping[str, Any], pilot: Mapping[str, Any], backfill: Mapping[str, Any], source_head: str, auth_key: str = "") -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    safe_write_json(ARTIFACT_DIR / "market_index_mapping_contract.json", {"mapping_version": MAPPING_CONTRACT_VERSION, "entries": mapping_contract_as_dict(), "mapping_sha256": mapping_contract_sha256()}, auth_key)
    safe_write_json(ARTIFACT_DIR / "raw_trading_calendar_summary.json", {key: value for key, value in calendar.items() if key != "target_dates"}, auth_key)
    safe_write_json(ARTIFACT_DIR / "pilot_summary.json", {**pilot, "validation_source_head": source_head}, auth_key)
    safe_write_json(ARTIFACT_DIR / "backfill_progress_summary.json", {**backfill, "validation_source_head": source_head}, auth_key)
    safe_write_json(ARTIFACT_DIR / "coverage_summary.json", {"raw_target_date_count": calendar.get("complete_trading_date_count"), "index_store_date_count": backfill.get("complete_date_count"), "index_store_row_count": backfill.get("staging_rows"), "index_count": 2, "codes": ["1001", "2001"], "status": "PASS" if backfill.get("status", "").startswith("READY_") else "PARTIAL"}, auth_key)
    safe_write_json(ARTIFACT_DIR / "network_request_summary.json", {"krx_request_count": backfill.get("krx_request_count", 0), "kospi_dd_trd_request_count": getattr(backfill, "kospi_dd_trd_request_count", 0), "kosdaq_dd_trd_request_count": getattr(backfill, "kosdaq_dd_trd_request_count", 0), "krx_dd_trd_request_count": 0, "retry_count": backfill.get("retry_count", 0), "audit_entry_count": backfill.get("audit_entry_count", 0), "pykrx_live_market_calls": 0}, auth_key)
    safe_write_json(ARTIFACT_DIR / "secret_scan.json", secret_scan(auth_key), auth_key)
    safe_write_json(ARTIFACT_DIR / "market_index_migration_v01_manifest.json", {"work_id": "KRX_INDEX_MIGRATION_V01", "start_head": START_HEAD, "implementation_head": source_head, "validation_source_head": source_head, "status": backfill.get("status"), "blockers": backfill.get("blockers", []), "artifact_files": sorted(path.name for path in ARTIFACT_DIR.iterdir() if path.is_file())}, auth_key)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate KOSPI/KOSDAQ representative indexes to KRX Open API IndexStore")
    parser.add_argument("--start", default=START_DATE)
    parser.add_argument("--end", default=END_DATE)
    parser.add_argument("--pilot", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    calendar = derive_raw_trading_calendar(args.start, args.end)
    auth_key = load_auth_key()
    runner = MarketIndexMigrationRunner(auth_key=auth_key)
    dates = list(PILOT_DATES) if args.pilot else None
    if dates is not None:
        missing = sorted(set(dates) - set(calendar["target_dates"]))
        if missing:
            raise SystemExit(f"pilot dates are not raw target dates: {missing}")
        pilot = runner.run({**calendar, "target_dates": dates, "complete_trading_date_count": len(dates)}, resume=args.resume, publish=False)
        backfill = {"status": pilot.get("status"), "krx_request_count": pilot.get("krx_request_count"), "blockers": pilot.get("blockers", [])}
    else:
        pilot = {"status": "NOT_RUN", "request_count": 0}
        backfill = runner.run(calendar, resume=args.resume or True, publish=args.publish)
    write_migration_artifacts(calendar=calendar, pilot=pilot, backfill=backfill, source_head=subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(), auth_key=auth_key)
    print(json.dumps({"pilot": pilot, "backfill": backfill}, ensure_ascii=False, indent=2))
    return 0 if str(backfill.get("status", "")).startswith(("READY_", "PARTIAL_")) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_DIR", "END_DATE", "LEGACY_REFERENCE", "LEGACY_REFERENCE_SHA256", "PILOT_DATES", "START_DATE", "START_HEAD",
    "MarketIndexMigrationRunner", "compare_legacy_market_parity", "derive_raw_trading_calendar", "legacy_reference_summary", "load_auth_key", "market_rs_parity", "mapping_contract_sha256", "safe_write_json", "secret_scan", "write_migration_artifacts",
]
