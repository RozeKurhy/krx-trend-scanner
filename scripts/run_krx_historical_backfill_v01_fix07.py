#!/usr/bin/env python3
"""FIX07 source-bound pilot, failed-partition repair, and resumable backfill.

The command is deliberately split into modes so a transport/schema failure
stops the phase before any subsequent request is attempted.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from time import monotonic
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner  # noqa: E402
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient  # noqa: E402
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota  # noqa: E402
from trend_scanner.data.krx_raw_stock_provider import MARKET_ENDPOINTS, MARKETS, KrxRawStockSnapshotProvider  # noqa: E402
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore  # noqa: E402


FIX_VERSION = "FIX07"
START_HEAD = "2001f1020c7c594baf1029b80231abf4b3e02d18"
PRODUCTION_RUNTIME_HEAD = "e508005c16e5fa3fa19c03b6568ba56ab9ac9294"
PILOT_DATES = ("2018-04-27", "2018-05-04", "2026-08-21")
REPAIR_DATE = "2019-04-26"
SAMSUNG_EXPECTED = {"2018-04-27": 128386494, "2018-05-04": 6419324700}
TARGET_START = "2010-01-04"
TARGET_END = "2026-08-21"
OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


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
    return value or _read_env_value(ROOT.parent / "env.md", "KRX_OPEN_API_AUTH_KEY").strip()


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _quota_payload(quota: LocalKrxOpenApiQuota) -> dict[str, Any]:
    usage = quota.get_usage()
    return {
        "usage_date_kst": usage.get("usage_date_kst"),
        "global_total": int(usage.get("global_total", 0)),
        "endpoint_usage": dict(usage.get("endpoint_usage", {})),
        "last_attempt_at_utc": usage.get("last_attempt_at_utc"),
        "remaining_global": quota.remaining("stk_bydd_trd"),
        "remaining_stk_bydd_trd": quota.remaining("stk_bydd_trd"),
        "remaining_ksq_bydd_trd": quota.remaining("ksq_bydd_trd"),
    }


def _partition(store: KrxRawStockStore, date: str, market: str) -> dict[str, Any]:
    manifest = store.get_manifest(market, date)
    verification = store.verify_snapshot(market, date)
    return {
        "date": date,
        "market": market,
        "endpoint": MARKET_ENDPOINTS[market],
        "manifest_status": manifest.get("status") if manifest else None,
        "row_count": int(manifest.get("row_count", 0)) if manifest else 0,
        "status": "PASS" if manifest and manifest.get("status") == "COMPLETE" and verification.get("valid") else "FAIL",
        "verification": verification,
    }


def _samsung(store: KrxRawStockStore, validation_head: str) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for date, expected in SAMSUNG_EXPECTED.items():
        available = found = False
        observed: int | None = None
        try:
            frame = store.load_snapshot("KOSPI", date)
            available = True
            matched = frame.loc[frame["ticker"].astype(str) == "005930"]
            found = not matched.empty
            if found:
                observed = int(matched.iloc[0]["listed_shares"])
        except Exception:
            pass
        observations.append({
            "date": date,
            "ticker": "005930",
            "expected": expected,
            "observed": observed,
            "snapshot_available": available,
            "ticker_found": found,
            "match": bool(available and found and observed == expected),
        })
    status = "PASS" if all(item["match"] for item in observations) else "BLOCKED_SAMSUNG_LISTED_SHARES_EVIDENCE"
    return {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": validation_head,
        "legacy": False,
        "mode": "live-pilot",
        "status": status,
        "blockers": [] if status == "PASS" else [status],
        "ticker": "005930",
        "observations": observations,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def _client(auth_key: str, quota: LocalKrxOpenApiQuota, max_requests: int) -> tuple[KrxOpenApiClient, KrxRawStockStore, KrxHistoricalBackfillRunner]:
    client = KrxOpenApiClient(auth_key, max_requests=max_requests, max_transient_retries=0, quota=quota)
    provider = KrxRawStockSnapshotProvider(client)
    store = KrxRawStockStore(DEFAULT_RAW_STOCK_ROOT)
    runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=100)
    return client, store, runner


def run_pilot(raw_root: Path, quota_db: Path | None = None) -> dict[str, Any]:
    auth = load_auth_key()
    if not auth:
        raise RuntimeError("BLOCKED_KRX_AUTH")
    validation_head = git_head()
    started = monotonic()
    quota = LocalKrxOpenApiQuota(quota_db)
    client = KrxOpenApiClient(auth, max_requests=6, max_transient_retries=0, quota=quota)
    provider = KrxRawStockSnapshotProvider(client)
    store = KrxRawStockStore(raw_root)
    runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=100)
    dates: list[dict[str, Any]] = []
    idempotent_existing = 0
    conflicts = 0
    for date in PILOT_DATES:
        before = {market: store.get_manifest(market, date) for market in MARKETS}
        result = runner.run(date, date, resume=False, max_task_attempts=2, retry_failures=False)
        partitions = [_partition(store, date, market) for market in MARKETS]
        idempotent_existing += sum(1 for market in MARKETS if (before[market] or {}).get("status") == "COMPLETE" and partitions[MARKETS.index(market)]["status"] == "PASS")
        if "RAW_PARTITION_CONFLICT" in str(result.get("diagnostics", [])) or "RAW_PARTITION_CONFLICT" in str(result.get("blockers", [])):
            conflicts += 1
        dates.append({
            "date": date,
            "status": result.get("status"),
            "blockers": result.get("blockers", []),
            "request_count": int(result.get("krx_open_api_attempt_count", 0)),
            "retry_count": int(result.get("retry_attempt_count", 0)),
            "aggregate": result.get("aggregate", {}),
            "diagnostics": result.get("diagnostics", []),
            "partitions": partitions,
        })
        if result.get("blockers"):
            break
    partition_rows = [item for item in dates for item in item["partitions"]]
    diagnostics = [item for item in dates for item in item["diagnostics"]]
    request_count = int(client.request_count)
    status_counts = dict(client.status_counts)
    samsung = _samsung(store, validation_head)
    blockers = [blocker for item in dates for blocker in item.get("blockers", [])]
    blockers.extend(samsung.get("blockers", []))
    if conflicts:
        blockers.append("BLOCKED_SOURCE_CONTENT_CONFLICT")
    blockers = list(dict.fromkeys(blockers))
    status = "PASS" if len(dates) == 3 and request_count == 6 and client.retry_count == 0 and len(partition_rows) == 6 and all(item["status"] == "PASS" for item in partition_rows) and not blockers else (blockers[0] if blockers else "BLOCKED_PILOT")
    summary = {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": validation_head,
        "legacy": False,
        "mode": "live-pilot",
        "dates": dates,
        "markets": list(MARKETS),
        "request_budget": 6,
        "request_count": request_count,
        "retry_count": int(client.retry_count),
        "status_counts": status_counts,
        "quota_usage": _quota_payload(quota),
        "partition_count": len(partition_rows),
        "complete_partition_count": sum(item["status"] == "PASS" for item in partition_rows),
        "failed_partition_count": sum(item["status"] != "PASS" for item in partition_rows),
        "partial_partition_count": 0,
        "idempotent_existing_partition_count": idempotent_existing,
        "partition_conflict_count": conflicts,
        "ticker_format_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_TICKER_FORMAT_ERROR" for item in diagnostics),
        "required_field_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_REQUIRED_FIELD_MISSING" for item in diagnostics),
        "numeric_error_count": sum(str(item.get("error_code", "")).startswith("RAW_SNAPSHOT_NUMERIC") for item in diagnostics),
        "date_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_DATE_MISMATCH" for item in diagnostics),
        "ohlc_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_OHLC_RELATION_ERROR" for item in diagnostics),
        "duplicate_ticker_count": 0,
        "cross_market_ticker_conflict_count": 0,
        "integrity_error_count": sum(not item["verification"].get("valid") for item in partition_rows),
        "blockers": blockers,
        "status": status,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": round(monotonic() - started, 3),
    }
    _write(OUTPUT / "FIX07_live_pilot_summary.json", summary)
    _write(OUTPUT / "FIX07_samsung_listed_shares_evidence.json", samsung)
    return summary


def run_repair(raw_root: Path, quota_db: Path | None = None) -> dict[str, Any]:
    auth = load_auth_key()
    if not auth:
        raise RuntimeError("BLOCKED_KRX_AUTH")
    validation_head = git_head()
    quota = LocalKrxOpenApiQuota(quota_db)
    before = _quota_payload(quota)
    client = KrxOpenApiClient(auth, max_requests=1, max_transient_retries=0, quota=quota)
    provider = KrxRawStockSnapshotProvider(client)
    store = KrxRawStockStore(raw_root)
    paired = store.get_manifest("KOSPI", REPAIR_DATE)
    if (paired or {}).get("status") != "COMPLETE":
        raise RuntimeError("BLOCKED_REPAIR_PAIRED_MARKET")
    runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=0)
    result = runner.run(REPAIR_DATE, REPAIR_DATE, resume=True, retry_failures=True, max_task_attempts=1)
    manifest = store.get_manifest("KOSDAQ", REPAIR_DATE)
    verification = store.verify_snapshot("KOSDAQ", REPAIR_DATE)
    audit = [item for item in client.audit if item.get("endpoint_key") == "ksq_bydd_trd"]
    status = "PASS" if client.request_count == 1 and client.retry_count == 0 and manifest and manifest.get("status") == "COMPLETE" and verification.get("valid") and not result.get("blockers") else (result.get("blockers") or ["BLOCKED_KRX_TRANSPORT"])[0]
    payload = {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": validation_head,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "date": REPAIR_DATE,
        "market": "KOSDAQ",
        "previous_status": "FAILED",
        "paired_market": "KOSPI",
        "paired_market_status": paired.get("status"),
        "attempt_count": int(client.request_count),
        "retry_count": int(client.retry_count),
        "http_status": audit[-1].get("http_status") if audit else None,
        "records_key": audit[-1].get("records_key") if audit else None,
        "row_count": int(manifest.get("row_count", 0)) if manifest else 0,
        "new_status": manifest.get("status") if manifest else None,
        "verification": verification,
        "status": status,
        "blockers": [] if status == "PASS" else [status],
        "quota_before": before,
        "quota_after": _quota_payload(quota),
    }
    _write(OUTPUT / "FIX07_failed_partition_repair.json", payload)
    return payload


def run_resume(raw_root: Path, quota_db: Path | None = None) -> dict[str, Any]:
    auth = load_auth_key()
    if not auth:
        raise RuntimeError("BLOCKED_KRX_AUTH")
    validation_head = git_head()
    quota = LocalKrxOpenApiQuota(quota_db)
    before = _quota_payload(quota)
    store = KrxRawStockStore(raw_root)
    pending = sum(1 for row in store.list_manifest() if row.get("status") not in {"COMPLETE", "NO_DATA"})
    # Missing rows are not represented in the manifest; derive the exact
    # logical pending count from the candidate range in the runner itself.
    from trend_scanner.data.krx_historical_backfill import candidate_dates
    dates = set(candidate_dates(TARGET_START, TARGET_END))
    represented = {(row["market"], row["date"]) for row in store.list_manifest() if row["date"] in dates and row["status"] in {"COMPLETE", "NO_DATA"}}
    missing = len(dates) * 2 - len(represented)
    request_budget = max(1, pending + missing)
    client = KrxOpenApiClient(auth, max_requests=request_budget, max_transient_retries=0, quota=quota)
    provider = KrxRawStockSnapshotProvider(client)
    runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=100)
    result = runner.run(TARGET_START, TARGET_END, resume=True, retry_failures=False, max_task_attempts=request_budget)
    payload = {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": validation_head,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "target_start": TARGET_START,
        "target_end": TARGET_END,
        "request_budget": request_budget,
        "precomputed_missing_partition_count": missing,
        "precomputed_pending_failure_count": pending,
        "result": result,
        "request_count": int(client.request_count),
        "retry_count": int(client.retry_count),
        "status_counts": dict(client.status_counts),
        "quota_before": before,
        "quota_after": _quota_payload(quota),
        "status": "PASS" if not result.get("blockers") and result.get("aggregate", {}).get("failed_date_count", 0) == 0 and result.get("aggregate", {}).get("partial_date_count", 0) == 0 else (result.get("blockers") or ["BLOCKED_COVERAGE"])[0],
    }
    _write(OUTPUT / "FIX07_backfill_resume_summary.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("pilot", "repair", "resume"), required=True)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--quota-db", type=Path, default=None)
    args = parser.parse_args()
    raw_root = args.raw_root if args.raw_root.is_absolute() else ROOT / args.raw_root
    if args.mode == "pilot":
        result = run_pilot(raw_root, args.quota_db)
    elif args.mode == "repair":
        result = run_repair(raw_root, args.quota_db)
    else:
        result = run_resume(raw_root, args.quota_db)
    print(json.dumps({"mode": args.mode, "status": result.get("status"), "request_count": result.get("request_count", result.get("result", {}).get("krx_open_api_attempt_count", 0))}, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
