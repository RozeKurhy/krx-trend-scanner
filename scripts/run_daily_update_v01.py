#!/usr/bin/env python3
"""Official one-target Daily Update foundation entrypoint.

The default is a network-free plan.  Production stores and official providers are constructed
only when ``--execute-live`` is explicitly supplied.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from refresh_market_data_v01 import load_auth_key
from refresh_market_index_v01 import derive_incremental_trading_dates, inspect_production_index, refresh_market_index
from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.corporate_action_refresh import CorporateActionRefreshService
from trend_scanner.data.corporate_action_state_store import DEFAULT_CORPORATE_ACTION_STATE_PATH, CorporateActionStateStore
from trend_scanner.data.daily_update_foundation import DailyUpdateFoundation
from trend_scanner.data.index_store import DEFAULT_INDEX_STORE_ROOT, IndexStore
from trend_scanner.data.krx_etf_raw_provider import KrxRawEtfSnapshotProvider
from trend_scanner.data.krx_historical_backfill import KrxHistoricalBackfillRunner
from trend_scanner.data.krx_historical_instrument_acquisition import HistoricalInstrumentAcquisitionRunner
from trend_scanner.data.krx_market_index import KrxMarketIndexBuilder
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.krx_raw_stock_provider import KrxRawStockSnapshotProvider
from trend_scanner.data.krx_raw_stock_store import DEFAULT_RAW_STOCK_ROOT, KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    DEFAULT_BASIC_INFO_RAW_ROOT,
    DEFAULT_FULL_POPULATION_CLOSURE_RESULTS_PATH,
    DEFAULT_MERGED_CALENDAR_PATH,
    DEFAULT_MERGED_PIT_PATH,
    DEFAULT_ROLLING_AUTHORITY_DIR,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    DEFAULT_SUSPENSION_ERRATA_PATH,
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    RollingAdjustedPriceUpdater,
    RollingEtfAdjustedUpdater,
    RollingRawEtfUpdater,
    RollingRawMarketUpdater,
    load_effective_common_adjusted_population,
    migrate_rolling_authority_manifest,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ADJUSTED_ROOT = ROOT / "data/market/adjusted/stocks"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the one-target KRX Daily Update foundation")
    parser.add_argument("--target-as-of", required=True, help="inclusive YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="plan only; this is the default")
    parser.add_argument("--execute-live", action="store_true", help="enable official network/store mutation")
    parser.add_argument(
        "--migrate-authority",
        action="store_true",
        help="explicitly bind an existing legacy manifest to already-coherent merged authority files",
    )
    parser.add_argument("--authority-dir", type=Path, default=ROOT / DEFAULT_ROLLING_AUTHORITY_DIR)
    parser.add_argument("--raw-root", type=Path, default=ROOT / DEFAULT_RAW_STOCK_ROOT)
    parser.add_argument("--adjusted-root", type=Path, default=DEFAULT_ADJUSTED_ROOT)
    parser.add_argument("--index-root", type=Path, default=ROOT / DEFAULT_INDEX_STORE_ROOT)
    parser.add_argument("--pit-path", type=Path, default=None)
    parser.add_argument("--historical-calendar-path", type=Path, default=None)
    parser.add_argument("--quota-db", type=Path, default=None)
    parser.add_argument("--max-requests", type=int, default=200)
    return parser


def _load_common_tickers(pit_path: Path) -> list[str]:
    return load_effective_common_adjusted_population(
        pit_path,
        etf_acceptance_tickers=ETF_VALIDATED_ACCEPTANCE_TICKERS,
    )


def build_foundation(args: argparse.Namespace, *, execute_live: bool) -> DailyUpdateFoundation:
    raw_store = KrxRawStockStore(args.raw_root)
    adjusted_store = AdjustedPriceStore(args.adjusted_root)
    pit_path = args.pit_path or (args.authority_dir / DEFAULT_MERGED_PIT_PATH.name)
    historical_calendar_path = args.historical_calendar_path or (args.authority_dir / DEFAULT_MERGED_CALENDAR_PATH.name)
    if not execute_live:
        # These are never called in dry-run mode; keeping the object graph explicit makes the
        # single entrypoint's plan use the same existing components without credentials.
        from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater

        common_raw = RollingRawMarketUpdater(None, raw_store)
        etf_raw = RollingRawEtfUpdater(None, raw_store)
        common_adjusted = RollingAdjustedPriceUpdater(
            None, adjusted_store, pit_path=pit_path, historical_calendar_path=historical_calendar_path
        )
        etf_adjusted = RollingEtfAdjustedUpdater(None, adjusted_store, raw_store=raw_store)
        common_tickers = _load_common_tickers(pit_path) if pit_path.exists() else []
        index_store = IndexStore(args.index_root)

        def plan_index(target: str):
            pre_run = inspect_production_index(index_store)
            boundary = next(iter(pre_run["per_code_last"].values()))
            plan = derive_incremental_trading_dates(raw_store, boundary, target, existing_frame=pre_run["frame"])
            return {
                "status": "PLAN",
                "missing_dates": list(plan["missing_dates"]),
                "missing_date_count": int(plan["missing_date_count"]),
                "request_count": 0,
                "plan": plan,
            }
        return DailyUpdateFoundation(
            authority_dir=args.authority_dir,
            raw_store=raw_store,
            adjusted_store=adjusted_store,
            common_adjusted_tickers=common_tickers,
            common_raw_updater=common_raw,
            etf_raw_updater=etf_raw,
            common_adjusted_updater=common_adjusted,
            etf_adjusted_updater=etf_adjusted,
            market_index_plan=plan_index,
        )

    auth_key = load_auth_key()
    if not auth_key:
        raise RuntimeError("BLOCKED_KRX_AUTH")
    # Basic Info rolling acquisition has a fixed 500-attempt safety reserve.  The
    # same quota object is shared with the other KRX legs so their requests remain
    # visible to one local accounting boundary.
    quota = LocalKrxOpenApiQuota(args.quota_db, reserve=500)
    client = KrxOpenApiClient(auth_key, max_requests=args.max_requests, max_transient_retries=0, quota=quota)
    common_provider = KrxRawStockSnapshotProvider(client)
    common_raw = RollingRawMarketUpdater(
        KrxHistoricalBackfillRunner(common_provider, raw_store, quota), raw_store
    )
    etf_raw = RollingRawEtfUpdater(KrxRawEtfSnapshotProvider(client), raw_store)
    adjusted_provider = NaverDirectAdjustedPriceDataProvider()
    common_adjusted = RollingAdjustedPriceUpdater(
        adjusted_provider,
        adjusted_store,
        pit_path=pit_path,
        historical_calendar_path=historical_calendar_path,
    )
    etf_adjusted = RollingEtfAdjustedUpdater(
        adjusted_provider,
        adjusted_store,
        raw_store=raw_store,
    )
    index_store = IndexStore(args.index_root)

    def plan_index(target: str):
        pre_run = inspect_production_index(index_store)
        boundaries = pre_run["per_code_last"]
        boundary = next(iter(boundaries.values()))
        plan = derive_incremental_trading_dates(
            raw_store,
            boundary,
            target,
            existing_frame=pre_run["frame"],
        )
        return {
            "status": "PLAN",
            "missing_dates": list(plan["missing_dates"]),
            "missing_date_count": int(plan["missing_date_count"]),
            "request_count": 0,
            "plan": plan,
        }

    def refresh_index(target: str):
        return refresh_market_index(
            target_as_of=target,
            raw_store=raw_store,
            index_store=index_store,
            builder=KrxMarketIndexBuilder(client=client),
        )

    basic_info_runner = HistoricalInstrumentAcquisitionRunner(
        client,
        quota,
        raw_root=ROOT / DEFAULT_BASIC_INFO_RAW_ROOT,
        checkpoint_path=ROOT / DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    )
    corporate_action_state_store = CorporateActionStateStore(ROOT / DEFAULT_CORPORATE_ACTION_STATE_PATH)
    corporate_action_refresh_service = CorporateActionRefreshService(
        corporate_action_state_store,
        adjusted_provider,
        adjusted_store,
    )
    return DailyUpdateFoundation(
        authority_dir=args.authority_dir,
        raw_store=raw_store,
        adjusted_store=adjusted_store,
        common_adjusted_tickers=_load_common_tickers(pit_path),
        common_raw_updater=common_raw,
        etf_raw_updater=etf_raw,
        common_adjusted_updater=common_adjusted,
        etf_adjusted_updater=etf_adjusted,
        market_index_refresh=refresh_index,
        market_index_plan=plan_index,
        basic_info_runner=basic_info_runner,
        corporate_action_state_store=corporate_action_state_store,
        corporate_action_refresh_service=corporate_action_refresh_service,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        migration = migrate_rolling_authority_manifest(
            args.authority_dir,
            apply=bool(args.migrate_authority),
        )
        foundation = build_foundation(args, execute_live=args.execute_live)
        result = foundation.execute(args.target_as_of, dry_run=not args.execute_live)
        result["authority_migration"] = migration
    except Exception as exc:  # noqa: BLE001 - redaction-safe top-level result
        from trend_scanner.data.daily_update_foundation import DailyUpdateFoundationError
        from trend_scanner.data.rolling_market_data_refresh import RollingAuthorityError

        expected = isinstance(exc, (DailyUpdateFoundationError, RollingAuthorityError))
        result = {
            "target_as_of": args.target_as_of,
            "final_status": "BLOCKED" if expected else "FAILED",
            "status": "BLOCKED" if expected else "FAILED",
            "reason": str(exc),
            "network_request_count": 0,
            "production_write_count": 0,
            "production_write_performed": False,
            "authority_promotion": 0,
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0 if result.get("final_status") in {"PASS", "NOOP"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
