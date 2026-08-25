#!/usr/bin/env python3
"""FIX08-only resumable historical backfill runner.

This runner never re-runs the accepted FIX07 pilot, Samsung evidence, or
2019-04-26 KOSDAQ repair.  It only resumes non-terminal logical partitions.
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

from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner, candidate_dates  # noqa: E402
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient  # noqa: E402
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota  # noqa: E402
from trend_scanner.data.krx_raw_stock_provider import KrxRawStockSnapshotProvider  # noqa: E402
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore  # noqa: E402


FIX_VERSION = "FIX08"
START_HEAD = "901af3ecaece64f918e983a5fa67ab07a7cc81f5"
PRODUCTION_RUNTIME_HEAD = "e508005c16e5fa3fa19c03b6568ba56ab9ac9294"
TARGET_START = "2010-01-04"
TARGET_END = "2026-08-21"
MARKETS = ("KOSPI", "KOSDAQ")
OUTPUT = ROOT / "artifacts/data/krx_historical_backfill/v01"
RUNNER_PATHS = (
    "scripts/run_krx_historical_backfill_v01_fix08.py",
    "scripts/validate_krx_historical_backfill_v01_fix08.py",
    "tests/test_krx_historical_backfill_v01_fix08.py",
)


def git_head() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def implementation_head() -> str:
    """Resolve the committed FIX08 implementation independently of artifacts."""
    return subprocess.check_output(
        ["git", "log", "-1", "--format=%H", "--", *RUNNER_PATHS],
        cwd=ROOT,
        text=True,
    ).strip()


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


def _manifest_counts(store: KrxRawStockStore, dates: set[str]) -> dict[str, int]:
    rows = [row for row in store.list_manifest() if row.get("date") in dates and row.get("market") in MARKETS]
    return {
        "complete": sum(row.get("status") == "COMPLETE" for row in rows),
        "no_data": sum(row.get("status") == "NO_DATA" for row in rows),
        "failed": sum(row.get("status") == "FAILED" for row in rows),
        "terminal": sum(row.get("status") in {"COMPLETE", "NO_DATA"} for row in rows),
    }


def run_resume(raw_root: Path, quota_db: Path | None = None) -> dict[str, Any]:
    auth = load_auth_key()
    if not auth:
        raise RuntimeError("BLOCKED_KRX_AUTH")
    execution_head = git_head()
    validation_head = implementation_head()
    quota = LocalKrxOpenApiQuota(quota_db)
    quota_before = _quota_payload(quota)
    store = KrxRawStockStore(raw_root)
    dates = set(candidate_dates(TARGET_START, TARGET_END))
    before = _manifest_counts(store, dates)
    expected_partitions = len(dates) * len(MARKETS)
    pending = expected_partitions - before["terminal"]
    request_budget = max(1, pending)
    started = monotonic()
    client = KrxOpenApiClient(auth, max_requests=request_budget, max_transient_retries=0, quota=quota)
    provider = KrxRawStockSnapshotProvider(client)
    runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=100)
    result = runner.run(
        TARGET_START,
        TARGET_END,
        resume=True,
        retry_failures=False,
        max_task_attempts=request_budget,
    )
    after = _manifest_counts(store, dates)
    final_missing = expected_partitions - after["terminal"]
    status_counts = dict(client.status_counts)
    aggregate = result.get("aggregate", {})
    status = "PASS" if (
        not result.get("blockers")
        and client.retry_count == 0
        and all(int(status_counts.get(key, 0)) == 0 for key in ("401", "403", "429", "5xx", "transport_error"))
        and after["failed"] == 0
        and final_missing == 0
        and aggregate.get("partial_date_count", 0) == 0
    ) else (result.get("blockers") or ["BLOCKED_COVERAGE"])[0]
    payload = {
        "validation_generation": FIX_VERSION,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": validation_head,
        "execution_head": execution_head,
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "target_start": TARGET_START,
        "target_end": TARGET_END,
        "resume": True,
        "retry_failures": False,
        "max_transient_retries": 0,
        "pre_resume_terminal_partition_count": before["terminal"],
        "pre_resume_missing_partition_count": pending,
        "pre_resume_failed_partition_count": before["failed"],
        "request_budget": request_budget,
        "request_count": int(client.request_count),
        "retry_count": int(client.retry_count),
        "status_counts": status_counts,
        "existing_complete_skip_count": before["complete"],
        "existing_no_data_skip_count": before["no_data"],
        "new_complete_partition_count": max(0, after["complete"] - before["complete"]),
        "new_no_data_partition_count": max(0, after["no_data"] - before["no_data"]),
        "failed_partition_count": after["failed"],
        "final_missing_partition_count": final_missing,
        "final_terminal_partition_count": after["terminal"],
        "result": result,
        "quota_before": quota_before,
        "quota_after": _quota_payload(quota),
        "elapsed_seconds": round(monotonic() - started, 3),
        "status": status,
    }
    _write(OUTPUT / "FIX08_backfill_resume_summary.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--quota-db", type=Path, default=None)
    args = parser.parse_args()
    raw_root = args.raw_root if args.raw_root.is_absolute() else ROOT / args.raw_root
    result = run_resume(raw_root, args.quota_db)
    print(json.dumps({
        "mode": "fix08-resume",
        "status": result.get("status"),
        "request_count": result.get("request_count", 0),
        "retry_count": result.get("retry_count", 0),
    }, ensure_ascii=False, sort_keys=True))
    return 0 if result.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
