#!/usr/bin/env python3
"""Run the resumable production KRX ETF raw whole-market snapshot backfill.

Independent of any adjusted-price update -- decoupled from
``backfill_krx_etf_repository_v2_v01.py``'s bundled 17-ticker acceptance
scope so ETF raw ingestion can roll forward on its own schedule (directive
``ROLLING_MARKET_DATA_REFRESH_PATH_V01`` section 18). Session-date
determination reuses the COMMON raw store's already-established KOSPI
manifest (COMPLETE/NO_DATA) as the trading-session authority, the same
convention the bundled script already follows -- run the COMMON raw backfill
(``backfill_krx_raw_stock_v01.py``) for the same range first.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore
from trend_scanner.data.krx_etf_raw_provider import KrxRawEtfSnapshotProvider
from trend_scanner.data.rolling_market_data_refresh import RollingRawEtfUpdater


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
    parser = argparse.ArgumentParser(description="Backfill immutable KRX ETF raw whole-market daily snapshots")
    parser.add_argument("--current-boundary", required=True, help="last already-certified COMPLETE date, inclusive; fetch starts the day after")
    parser.add_argument("--target-as-of", required=True, help="inclusive YYYY-MM-DD to roll forward to")
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--max-requests", type=int, required=True, help="logical ETF snapshot task budget")
    parser.add_argument("--request-interval-ms", type=int, default=100)
    parser.add_argument("--root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--quota-db", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    auth_key = load_auth_key()
    if not auth_key:
        print(json.dumps({"status": "BLOCKED_KRX_AUTH", "blockers": ["BLOCKED_KRX_AUTH"]}, ensure_ascii=False))
        return 2
    quota = LocalKrxOpenApiQuota(args.quota_db)
    client = KrxOpenApiClient(auth_key, max_requests=args.max_requests, max_transient_retries=0, quota=quota)
    provider = KrxRawEtfSnapshotProvider(client)
    store_root = args.root if args.root.is_absolute() else ROOT / args.root
    store = KrxRawStockStore(store_root)
    updater = RollingRawEtfUpdater(provider, store, request_interval_ms=args.request_interval_ms)
    result = updater.refresh(args.current_boundary, args.target_as_of, resume=args.resume)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if not result["failures"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
