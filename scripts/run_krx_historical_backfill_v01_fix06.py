#!/usr/bin/env python3
"""Run the FIX06 three-date pilot against the production raw store."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
from time import monotonic
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner  # noqa: E402
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient  # noqa: E402
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota  # noqa: E402
from trend_scanner.data.krx_raw_stock_provider import MARKET_ENDPOINTS, MARKETS, KrxRawStockSnapshotError, KrxRawStockSnapshotProvider  # noqa: E402
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore  # noqa: E402


FIX_VERSION = "FIX06"
START_HEAD = "0a1bf2a8cc239386c48a514db43b4193e8599623"
DATES = ("2018-04-27", "2018-05-04", "2026-08-21")
SAMSUNG_EXPECTED = {"2018-04-27": 128386494, "2018-05-04": 6419324700}
OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"


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
    return _read_env_value(ROOT.parent / "env.md", "KRX_OPEN_API_AUTH_KEY").strip()


def _write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _partition_evidence(store: KrxRawStockStore, date: str, market: str) -> dict[str, Any]:
    manifest = store.get_manifest(market, date)
    verification = store.verify_snapshot(market, date)
    return {
        "date": date,
        "market": market,
        "endpoint": MARKET_ENDPOINTS[market],
        "manifest_status": manifest.get("status") if manifest else None,
        "row_count": int(manifest.get("row_count", 0)) if manifest else 0,
        "status": "PASS" if verification.get("valid") and manifest and manifest.get("status") == "COMPLETE" else "FAIL",
        "verification": verification,
    }


def _cross_market(store: KrxRawStockStore, dates: tuple[str, ...]) -> tuple[int, list[dict[str, Any]]]:
    conflicts: list[dict[str, Any]] = []
    for date in dates:
        frames = {}
        for market in MARKETS:
            try:
                frames[market] = store.load_snapshot(market, date)
            except Exception:
                continue
        if len(frames) != 2:
            continue
        left = set(frames["KOSPI"]["ticker"].astype(str))
        right = set(frames["KOSDAQ"]["ticker"].astype(str))
        conflicts.extend({"date": date, "ticker": ticker, "markets": ["KOSPI", "KOSDAQ"]} for ticker in sorted(left & right))
    return len(conflicts), conflicts[:50]


def _samsung(store: KrxRawStockStore) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for date, expected in SAMSUNG_EXPECTED.items():
        snapshot_available = False
        ticker_found = False
        observed = None
        try:
            frame = store.load_snapshot("KOSPI", date)
            snapshot_available = True
            match = frame.loc[frame["ticker"].astype(str) == "005930"]
            ticker_found = not match.empty
            if ticker_found:
                observed = int(match.iloc[0]["listed_shares"])
        except Exception:
            pass
        observations.append({
            "date": date,
            "ticker": "005930",
            "expected": expected,
            "observed": observed,
            "snapshot_available": snapshot_available,
            "ticker_found": ticker_found,
            "match": bool(snapshot_available and ticker_found and observed == expected),
        })
    status = "PASS" if all(item["match"] for item in observations) else "BLOCKED_SAMSUNG_LISTED_SHARES_EVIDENCE"
    return {
        "validation_generation": FIX_VERSION,
        "source_head": _git_head(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "legacy": False,
        "mode": "live-pilot",
        "status": status,
        "blockers": [] if status == "PASS" else [status],
        "ticker": "005930",
        "observations": observations,
    }


def _git_head() -> str:
    import subprocess
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def run_pilot(raw_root: Path, quota_db: Path | None = None) -> dict[str, Any]:
    auth_key = load_auth_key()
    if not auth_key:
        raise RuntimeError("BLOCKED_KRX_AUTH")
    started = monotonic()
    quota = LocalKrxOpenApiQuota(quota_db)
    client = KrxOpenApiClient(auth_key, max_requests=6, max_transient_retries=0, quota=quota)
    provider = KrxRawStockSnapshotProvider(client)
    store = KrxRawStockStore(raw_root)
    runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=100)
    date_results: list[dict[str, Any]] = []
    for date in DATES:
        result = runner.run(date, date, resume=True, max_task_attempts=2, retry_failures=False)
        partitions = [_partition_evidence(store, date, market) for market in MARKETS]
        print(json.dumps({"date": date, "status": result["status"], "requests": result["krx_open_api_attempt_count"], "partitions": [(item["market"], item["status"], item["row_count"]) for item in partitions]}, ensure_ascii=False), flush=True)
        date_results.append({
            "date": date,
            "status": result["status"],
            "blockers": result["blockers"],
            "aggregate": result["aggregate"],
            "diagnostics": result.get("diagnostics", []),
            "failure_observations": result.get("failure_observations", []),
            "partitions": partitions,
        })
        if result["blockers"]:
            break
    cross_count, cross_samples = _cross_market(store, DATES)
    samsung = _samsung(store)
    partition_rows = [item for result in date_results for item in result["partitions"]]
    complete = sum(item["status"] == "PASS" for item in partition_rows)
    failed = len(partition_rows) - complete
    diagnostics = [item for result in date_results for item in result["diagnostics"]]
    blockers = []
    blockers.extend(item for result in date_results for item in result["blockers"])
    blockers.extend(samsung["blockers"])
    if cross_count:
        blockers.append("BLOCKED_CROSS_MARKET_TICKER_CONFLICT")
    blockers = list(dict.fromkeys(blockers))
    status = "PASS" if len(date_results) == 3 and complete == 6 and failed == 0 and not blockers and cross_count == 0 else (blockers[0] if blockers else "BLOCKED_COVERAGE")
    summary = {
        "validation_generation": FIX_VERSION,
        "source_head": _git_head(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "legacy": False,
        "mode": "live-pilot",
        "dates": date_results,
        "markets": list(MARKETS),
        "request_budget": 6,
        "request_count": client.request_count,
        "retry_count": client.retry_count,
        "status_counts": client.status_counts,
        "quota_usage": quota.get_usage(),
        "partition_count": len(partition_rows),
        "complete_partition_count": complete,
        "failed_partition_count": failed,
        "partial_partition_count": 0,
        "ticker_format_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_TICKER_FORMAT_ERROR" for item in diagnostics),
        "required_field_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_REQUIRED_FIELD_MISSING" for item in diagnostics),
        "numeric_error_count": sum(str(item.get("error_code", "")).startswith("RAW_SNAPSHOT_NUMERIC") for item in diagnostics),
        "date_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_DATE_MISMATCH" for item in diagnostics),
        "ohlc_error_count": sum(item.get("error_code") == "RAW_SNAPSHOT_OHLC_RELATION_ERROR" for item in diagnostics),
        "duplicate_ticker_count": 0,
        "cross_market_ticker_conflict_count": cross_count,
        "cross_market_conflict_samples": cross_samples,
        "integrity_error_count": sum(not item["verification"].get("valid") for item in partition_rows),
        "blockers": blockers,
        "status": status,
        "elapsed_seconds": round(monotonic() - started, 3),
    }
    _write(OUTPUT / "FIX06_live_pilot_summary.json", summary)
    _write(OUTPUT / "FIX06_samsung_listed_shares_evidence.json", samsung)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--quota-db", type=Path, default=None)
    args = parser.parse_args()
    raw_root = args.raw_root if args.raw_root.is_absolute() else ROOT / args.raw_root
    summary = run_pilot(raw_root, args.quota_db)
    print(json.dumps({"status": summary["status"], "request_count": summary["request_count"], "complete_partition_count": summary["complete_partition_count"], "samsung": summary["status"]}, ensure_ascii=False))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
