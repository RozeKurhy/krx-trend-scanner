#!/usr/bin/env python3
"""KRX Official Common Stock Cache Population CLI.

Usage:
    uv run python scripts/populate_krx_common_cache.py [--dry-run] [--limit N] [--tickers 005930,000660] [--market KOSPI] [--delay 0.1]
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
import sys

from dotenv import load_dotenv

load_dotenv()

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.universe.asset_classifier import classify_asset_type
from trend_scanner.universe.cache_population import (
    CachePopulationRecord,
    CachePopulationStatus,
    CachePopulationSummary,
    populate_common_stock_cache,
)
from trend_scanner.universe.krx_universe import (
    get_latest_market_trading_date,
    load_krx_equity_universe,
)
from trend_scanner.universe.models import AssetType, MarketType
from trend_scanner.universe.quality_auditor import audit_universe_quality


def _save_records_csv(records: tuple[CachePopulationRecord, ...], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ticker",
            "name",
            "market",
            "asset_type",
            "reference_market_date",
            "status",
            "cache_existed_before",
            "cache_first_date_before",
            "cache_last_date_before",
            "fetch_start_date",
            "fetch_end_date",
            "fetched_row_count",
            "cache_first_date_after",
            "cache_last_date_after",
            "total_row_count_after",
            "completed_month_count_after",
            "retry_count",
            "error_type",
            "error_message",
        ])
        for r in records:
            writer.writerow([
                r.ticker,
                r.name,
                r.market.value,
                r.asset_type.value,
                r.reference_market_date,
                r.status.value,
                r.cache_existed_before,
                r.cache_first_date_before or "",
                r.cache_last_date_before or "",
                r.fetch_start_date or "",
                r.fetch_end_date or "",
                r.fetched_row_count,
                r.cache_first_date_after or "",
                r.cache_last_date_after or "",
                r.total_row_count_after,
                r.completed_month_count_after,
                r.retry_count,
                r.error_type or "",
                r.error_message or "",
            ])


def main() -> int:
    parser = argparse.ArgumentParser(description="KRX Official Common Stock Cache Population v0.1")
    parser.add_argument("--dry-run", action="store_true", help="계획만 출력하고 실제 다운로드/저장하지 않음")
    parser.add_argument("--limit", type=int, default=None, help="처리할 최대 종목 수")
    parser.add_argument("--tickers", type=str, default=None, help="콤마로 구분된 특정 종목코드 목록 (예: 005930,000660)")
    parser.add_argument("--market", type=str, choices=["KOSPI", "KOSDAQ"], default=None, help="시장 필터")
    parser.add_argument("--delay", type=float, default=0.05, help="종목 간 요청 딜레이(초)")
    parser.add_argument("--audit", action="store_true", default=True, help="완료 후 Universe Quality Audit 실행")
    parser.add_argument("--output", type=str, default=None, help="결과 CSV 저장 경로")

    args = parser.parse_args()

    print("=" * 80)
    print("KRX Official Common Stock Cache Population v0.1")
    print("=" * 80)

    cache = ParquetCache()
    provider = PyKrxDataProvider(adjusted=True)

    ref_date = get_latest_market_trading_date()
    print(f"Official Reference Market Date: {ref_date}")

    market_filter = MarketType(args.market) if args.market else None
    tickers_filter = [t.strip() for t in args.tickers.split(",")] if args.tickers else None

    # Universe 사전 확인
    universe = load_krx_equity_universe(as_of=ref_date)
    common_targets = [s for s in universe if classify_asset_type(s.ticker, s.name) == AssetType.COMMON]
    print(f"Official Total Universe: {len(universe):,} 종목")
    print(f"Official COMMON Target: {len(common_targets):,} 종목")
    if args.limit:
        print(f"Limit: {args.limit} 종목")
    if market_filter:
        print(f"Market Filter: {market_filter.value}")
    if tickers_filter:
        print(f"Tickers Filter: {tickers_filter}")
    if args.dry_run:
        print("[DRY-RUN MODE 활성화: 실제 다운로드 및 저장을 수행하지 않습니다]")

    print("-" * 80)

    start_time = datetime.now()

    def _progress(rec: CachePopulationRecord, current: int, total: int):
        pct = (current / total) * 100
        status_sym = "✓" if rec.status in (CachePopulationStatus.CREATED, CachePopulationStatus.UPDATED, CachePopulationStatus.SKIPPED_FRESH) else "✗"
        print(f"[{current:4d}/{total:4d} ({pct:5.1f}%)] {status_sym} {rec.ticker} {rec.name[:10]:10s} -> {rec.status.value:15s} (rows={rec.total_row_count_after:4d}, months={rec.completed_month_count_after:2d})")

    summary = populate_common_stock_cache(
        cache=cache,
        provider=provider,
        reference_market_date=ref_date,
        universe_securities=universe,
        limit=args.limit,
        tickers=tickers_filter,
        market=market_filter,
        delay_seconds=args.delay,
        dry_run=args.dry_run,
        progress_callback=_progress,
    )

    elapsed = datetime.now() - start_time
    print("-" * 80)
    print("Population Execution Summary:")
    print(f"  Target Count:         {summary.population_target_count:,}")
    print(f"  Created (New):        {summary.created_count:,}")
    print(f"  Updated (Existing):   {summary.updated_count:,}")
    print(f"  Skipped (Fresh):      {summary.skipped_fresh_count:,}")
    print(f"  Failed:               {summary.failed_count:,}")
    print(f"  Cache Present After:  {summary.cache_present_after:,}")
    print(f"  Fresh After:          {summary.fresh_after:,}")
    print(f"  Stale After:          {summary.stale_after:,}")
    print(f"  42M History Ready:    {summary.history_42m_ready_after:,}")
    print(f"  48M History Ready:    {summary.history_48m_ready_after:,}")
    print(f"  Elapsed Time:         {elapsed}")

    if summary.failed_records:
        print("\nFailed Tickers:")
        for fr in summary.failed_records[:20]:
            print(f"  - {fr.ticker} {fr.name}: {fr.error_type} - {fr.error_message}")
        if len(summary.failed_records) > 20:
            print(f"  ... 외 {len(summary.failed_records) - 20}건")

    # CSV 저장
    out_path = Path(args.output) if args.output else Path(f"artifacts/cache_population/population_{ref_date.replace('-', '')}.csv")
    _save_records_csv(summary.records, out_path)
    print(f"\nSaved CSV Report to: {out_path}")

    # Post Quality Audit
    if args.audit and not args.dry_run:
        print("\n" + "=" * 80)
        print("Running Post-Population Universe Quality Audit...")
        print("=" * 80)
        _, audit_res = audit_universe_quality(
            ticker_metadata=universe,
            cache_dir=cache.base_dir,
            reference_market_date=ref_date,
        )
        print(f"Official Total:       {audit_res.official_universe_count:,}")
        print(f"Common Total:         {audit_res.common_stock_count:,}")
        print(f"Cache Coverage:       {audit_res.cache_coverage_pct:.2f}% ({audit_res.cache_present_count}/{audit_res.official_universe_count})")
        print(f"Fresh:                {audit_res.fresh_count:,}")
        print(f"Stale:                {audit_res.stale_count:,}")
        print(f"Very Stale:           {audit_res.very_stale_count:,}")
        print(f"Evaluator Ready:      {audit_res.evaluator_ready_count:,}")
        print(f"Score Ready:          {audit_res.score_ready_count:,}")
        print(f"Stage Ready:          {audit_res.stage_ready_count:,}")
        print(f"Raw Data Ready:       {audit_res.raw_data_ready_count:,}")
        print(f"Future Violations:    {audit_res.future_date_count}")
        print(f"Duplicate Violations: {audit_res.duplicate_date_count}")
        print(f"Unsorted Violations:  {audit_res.unsorted_date_count}")
        print(f"Quality Exceptions:   {audit_res.exception_count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
