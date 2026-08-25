#!/usr/bin/env python3
"""Run the resumable production KRX raw stock historical backfill."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_provider import KrxRawStockSnapshotProvider
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore


ROOT = Path(__file__).resolve().parents[1]


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill immutable KRX raw stock daily snapshots")
    parser.add_argument("--start", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--resume", action="store_true", help="skip integrity-valid COMPLETE/NO_DATA dates")
    parser.add_argument("--max-attempts", type=int, required=True, help="logical market snapshot task budget")
    parser.add_argument("--request-interval-ms", type=int, default=100)
    parser.add_argument("--retry-failures", action="store_true")
    parser.add_argument("--markets", nargs="+", choices=("KOSPI", "KOSDAQ"), default=["KOSPI", "KOSDAQ"])
    parser.add_argument("--root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--quota-db", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    auth_key = load_auth_key()
    if not auth_key:
        print(json.dumps({"status": "BLOCKED_KRX_AUTH", "recommendation": "BLOCKED_KRX_AUTH", "blockers": ["BLOCKED_KRX_AUTH"]}, ensure_ascii=False))
        return 2
    quota = LocalKrxOpenApiQuota(args.quota_db)
    client = KrxOpenApiClient(
        auth_key,
        max_requests=args.max_attempts,
        max_transient_retries=1 if args.retry_failures else 0,
        quota=quota,
    )
    provider = KrxRawStockSnapshotProvider(client)
    store_root = args.root if args.root.is_absolute() else ROOT / args.root
    store = KrxRawStockStore(store_root)
    runner = KrxHistoricalBackfillRunner(provider, store, quota, request_interval_ms=args.request_interval_ms)
    result = runner.run(
        args.start,
        args.end,
        resume=args.resume,
        max_task_attempts=args.max_attempts,
        retry_failures=args.retry_failures,
        markets=args.markets,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"].startswith("READY_") or result["status"] == "BACKFILL_IN_PROGRESS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
