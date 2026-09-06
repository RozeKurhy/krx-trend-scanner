#!/usr/bin/env python3
"""Official rolling market-data refresh entrypoint.

Wraps :class:`RollingRefreshCoordinator`. ``--dry-run`` (the default) only
computes and prints the plan against the current rolling authority manifest
-- it never touches any canonical store. Live execution requires
``--execute-live`` explicitly, and today the COMMON adjusted-price leg will
still fail closed with ``InsufficientPitFrontierError`` (see
``rolling_market_data_refresh.py``'s module docstring) until a rolling-safe
PIT/survivorship-denominator extension exists -- that is a designed
boundary, not a bug.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.krx_etf_raw_provider import KrxRawEtfSnapshotProvider
from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_provider import KrxRawStockSnapshotProvider
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    RollingAdjustedPriceUpdater,
    RollingEtfAdjustedUpdater,
    RollingRawEtfUpdater,
    RollingRawMarketUpdater,
    RollingRefreshCoordinator,
    load_rolling_authority,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADJUSTED_ROOT = Path("data/market/adjusted/stocks")


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
    parser = argparse.ArgumentParser(description="Roll Repository V2 production market data forward to --target-as-of")
    parser.add_argument("--target-as-of", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--execute-live", action="store_true", help="perform the actual refresh; overrides --dry-run")
    parser.add_argument("--pit-path", type=Path, default=None, help="required for a live run: a PIT artifact whose frontier already covers --target-as-of")
    parser.add_argument("--historical-calendar-path", type=Path, default=None)
    parser.add_argument("--raw-root", type=Path, default=DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--adjusted-root", type=Path, default=DEFAULT_ADJUSTED_ROOT)
    parser.add_argument("--authority-dir", type=Path, default=DEFAULT_ROLLING_AUTHORITY_DIR)
    parser.add_argument("--max-attempts", type=int, default=200)
    parser.add_argument("--quota-db", type=Path, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    dry_run = not args.execute_live

    if dry_run:
        # A dry-run plan requires no credentials and performs no network calls or writes.
        try:
            manifest = load_rolling_authority(args.authority_dir)
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"status": "ERROR", "error": str(exc)}, ensure_ascii=False))
            return 2
        raw_store = KrxRawStockStore(args.raw_root)
        plan = {
            "status": "DRY_RUN",
            "current_certified_through": manifest.certified_through,
            "target_as_of": args.target_as_of,
            "leg_boundaries": manifest.leg_boundaries,
            "common_raw": RollingRawMarketUpdater.plan(manifest.leg_boundaries["common_raw"], args.target_as_of),
            "etf_raw": RollingRawEtfUpdater(None, raw_store).plan(manifest.leg_boundaries["etf_raw"], args.target_as_of),
            "production_write_performed": False,
        }
        print(json.dumps(plan, ensure_ascii=False, sort_keys=True, indent=2))
        return 0

    auth_key = load_auth_key()
    if not auth_key:
        print(json.dumps({"status": "BLOCKED_KRX_AUTH"}, ensure_ascii=False))
        return 2
    if args.pit_path is None or args.historical_calendar_path is None:
        print(json.dumps({"status": "BLOCKED_MISSING_PIT_AUTHORITY", "reason": "a live run requires --pit-path/--historical-calendar-path covering --target-as-of"}, ensure_ascii=False))
        return 2

    quota = LocalKrxOpenApiQuota(args.quota_db)
    client = KrxOpenApiClient(auth_key, max_requests=args.max_attempts, max_transient_retries=0, quota=quota)
    raw_store = KrxRawStockStore(args.raw_root)
    adjusted_store = AdjustedPriceStore(args.adjusted_root)
    coordinator = RollingRefreshCoordinator(
        raw_updater=RollingRawMarketUpdater(
            KrxHistoricalBackfillRunner(KrxRawStockSnapshotProvider(client), raw_store, quota), raw_store
        ),
        raw_etf_updater=RollingRawEtfUpdater(KrxRawEtfSnapshotProvider(client), raw_store),
        etf_adjusted_updater=RollingEtfAdjustedUpdater(NaverDirectAdjustedPriceDataProvider(), adjusted_store),
        common_adjusted_updater=RollingAdjustedPriceUpdater(
            NaverDirectAdjustedPriceDataProvider(), adjusted_store, pit_path=args.pit_path, historical_calendar_path=args.historical_calendar_path
        ),
        common_adjusted_tickers=[
            p.name.removesuffix(".meta.json")
            for p in Path(args.adjusted_root).glob("*.meta.json")
            if p.name.removesuffix(".meta.json") not in ETF_VALIDATED_ACCEPTANCE_TICKERS
        ],
        authority_dir=args.authority_dir,
        raw_store=raw_store,
        adjusted_store=adjusted_store,
    )
    result = coordinator.execute(args.target_as_of, dry_run=False)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, default=str))
    return 0 if result["status"] == "PROMOTED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
