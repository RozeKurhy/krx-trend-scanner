"""Rolling (incremental) KRX Basic Info acquisition -- the production counterpart to
run_krx_historical_instrument_acquisition_v01.py's frozen closure runner.

Usage:
    uv run python scripts/refresh_krx_basic_info_v01.py --target-as-of 2026-09-04 --dry-run
    uv run python scripts/refresh_krx_basic_info_v01.py --target-as-of 2026-09-04 --execute-live

Authorized request dates are always derived from the already-approved COMMON raw market manifest
(KrxRawStockStore) -- never passed in directly -- so this CLI cannot manufacture an arbitrary
trading-date authority (directive ROLLING_BASIC_INFO_ACQUISITION_V01 section 7).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore
from trend_scanner.data.rolling_basic_info_acquisition import (
    DEFAULT_ROLLING_CHECKPOINT_PATH,
    DEFAULT_ROLLING_FINAL_SUMMARY_PATH,
    DEFAULT_ROLLING_RAW_ROOT,
    RollingBasicInfoAcquisitionRunner,
    current_basic_info_frontier,
    derive_authorized_dates,
)

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
    parser = argparse.ArgumentParser(description="Incremental rolling KRX Basic Info acquisition")
    parser.add_argument("--target-as-of", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--raw-store-root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--rolling-raw-root", type=Path, default=DEFAULT_ROLLING_RAW_ROOT)
    parser.add_argument("--rolling-checkpoint", type=Path, default=DEFAULT_ROLLING_CHECKPOINT_PATH)
    parser.add_argument("--rolling-final-summary", type=Path, default=DEFAULT_ROLLING_FINAL_SUMMARY_PATH)
    parser.add_argument("--quota-db", type=Path, default=Path(".cache/krx_openapi/quota.sqlite3"))
    parser.add_argument("--resume", action="store_true", default=True)
    parser.add_argument("--execute-live", action="store_true", help="required for any HTTP request; default is a dry run")
    parser.add_argument("--dry-run", action="store_true", help="explicit alias for the default (no --execute-live)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    execute_live = args.execute_live and not args.dry_run

    raw_store = KrxRawStockStore(args.raw_store_root if args.raw_store_root.is_absolute() else ROOT / args.raw_store_root)
    frontier = current_basic_info_frontier(rolling_checkpoint_path=args.rolling_checkpoint)
    authorized_dates = derive_authorized_dates(raw_store, current_frontier=frontier, target_as_of=args.target_as_of)

    plan_result = {
        "current_frontier": frontier,
        "target_as_of": args.target_as_of,
        "authorized_date_count": len(authorized_dates),
        "authorized_dates": authorized_dates,
    }

    if not execute_live:
        print(json.dumps({"status": "DRY_RUN", **plan_result}, ensure_ascii=False, indent=2))
        return 0

    if not authorized_dates:
        print(json.dumps({"status": "NOOP_NO_AUTHORIZED_DATES", **plan_result}, ensure_ascii=False, indent=2))
        return 0

    auth_key = load_auth_key()
    if not auth_key:
        print(json.dumps({"status": "BLOCKED_KRX_AUTH", **plan_result}, ensure_ascii=False))
        return 2

    quota = LocalKrxOpenApiQuota(args.quota_db, reserve=500)
    client = KrxOpenApiClient(auth_key, max_requests=len(authorized_dates) * 2 + 10, max_transient_retries=1, quota=quota)
    runner = RollingBasicInfoAcquisitionRunner(
        client, quota, raw_root=args.rolling_raw_root, checkpoint_path=args.rolling_checkpoint
    )
    result = runner.run(authorized_dates, resume=args.resume, execute_live=True)
    final_summary = None
    if result["status"] == "COMPLETE":
        final_summary = runner.write_final_summary(authorized_dates, final_summary_path=args.rolling_final_summary)

    print(json.dumps({**plan_result, "run_result": result, "final_summary": final_summary}, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
