"""CLI Runner for Pattern A Full Universe Scanner Integration v0.1.

Usage:
    uv run python scripts/run_pattern_a_universe_scanner.py --as-of 2026-08-14
    uv run python scripts/run_pattern_a_universe_scanner.py --as-of 2026-08-14 --market KOSPI
    uv run python scripts/run_pattern_a_universe_scanner.py --as-of 2026-08-14 --limit 10
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

import pandas as pd

from trend_scanner.data.market_calendar import load_rolling_production_market_calendar
from trend_scanner.data.repository_v2_loader import build_production_repository_v2
from trend_scanner.data.sector_membership import (
    load_sector_mapping_exact_snapshot,
    resolve_sector_membership_snapshot_for_target,
)
from trend_scanner.scanner import scan_pattern_a_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_pattern_a_universe_scanner")

ROOT = Path(__file__).resolve().parents[1]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Pattern A Full Universe Scanner on Official COMMON Stocks."
    )
    parser.add_argument(
        "--as-of",
        type=str,
        required=True,
        help="Required target as-of date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        default="data/raw/stocks",
        help="Path to Parquet cache directory (default: data/raw/stocks)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/patterns/pattern_a/production/scanner",
        help="Path to artifacts output directory (default: artifacts/patterns/pattern_a/production/scanner)",
    )
    parser.add_argument(
        "--market",
        type=str,
        choices=["KOSPI", "KOSDAQ"],
        default=None,
        help="Filter by specific market (default: all KOSPI/KOSDAQ)",
    )
    parser.add_argument(
        "--tickers",
        type=str,
        nargs="+",
        default=None,
        help="Filter by specific ticker list",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of stocks to scan (for testing)",
    )
    parser.add_argument(
        "--enrich-market-rs-cross-section",
        action="store_true",
        help="Compute Market RS ranks/percentiles over the complete COMMON scan population",
    )
    return parser.parse_args(argv)


def resolve_reference_market_date(target_as_of: str, calendar: object | None) -> str:
    """Return the certified market trading date at or before ``target_as_of``.

    The requested analysis date is not rewritten on weekends or holidays.  A
    missing or unusable rolling production calendar is an explicit failure,
    never a latest-date or system-date fallback.
    """

    if calendar is None:
        raise RuntimeError("ROLLING_PRODUCTION_CALENDAR_UNAVAILABLE")

    try:
        target = pd.Timestamp(target_as_of).normalize()
        trading_dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    except (AttributeError, TypeError, ValueError) as exc:
        raise RuntimeError("ROLLING_PRODUCTION_CALENDAR_INVALID") from exc

    eligible = trading_dates[trading_dates <= target]
    if len(eligible) == 0:
        raise RuntimeError(f"ROLLING_PRODUCTION_CALENDAR_NO_DATE_AT_OR_BEFORE:{target_as_of}")
    return eligible.max().strftime("%Y-%m-%d")


def validate_full_common_scan(summary: object, *, is_full_common_scan: bool) -> None:
    """Fail the production CLI when an unfiltered COMMON scan is incomplete."""

    if not is_full_common_scan:
        return

    if summary.scan_target_count != summary.official_common_total:
        raise RuntimeError(
            "FULL_COMMON_SCAN_TARGET_COUNT_MISMATCH:"
            f"{summary.scan_target_count}!={summary.official_common_total}"
        )
    if summary.rows_emitted != summary.official_common_total:
        raise RuntimeError(
            "FULL_COMMON_SCAN_ROW_COUNT_MISMATCH:"
            f"{summary.rows_emitted}!={summary.official_common_total}"
        )
    if summary.scanner_error_count > 0:
        raise RuntimeError(f"FULL_COMMON_SCAN_SCANNER_ERRORS:{summary.scanner_error_count}")


def run_phase4a(
    target_as_of: str,
    *,
    root: Path = ROOT,
    cache_dir: str | Path = "data/raw/stocks",
    output_dir: str | Path = "artifacts/patterns/pattern_a/production/scanner",
    market: str | None = None,
    tickers: list[str] | None = None,
    limit: int | None = None,
    enrich_market_rs_cross_section: bool = False,
) -> dict[str, object]:
    """Run the existing full-universe scanner and return a small structured result.

    This is an adapter for Phase 4E; scanner calculations and artifact contracts remain
    owned by :func:`scan_pattern_a_universe` and the existing CLI.
    """

    root = Path(root)
    markets = [market] if market else None
    resolved_cache_dir = Path(cache_dir)
    if not resolved_cache_dir.is_absolute():
        resolved_cache_dir = root / resolved_cache_dir
    resolved_output_dir = Path(output_dir)
    if not resolved_output_dir.is_absolute():
        resolved_output_dir = root / resolved_output_dir

    repository = build_production_repository_v2(root, end=target_as_of)
    production_calendar = load_rolling_production_market_calendar(root)
    reference_market_date = resolve_reference_market_date(target_as_of, production_calendar)

    _, membership_effective_date, membership_path, _ = (
        resolve_sector_membership_snapshot_for_target(target_as_of, repo_root=root)
    )
    sector_mapping = load_sector_mapping_exact_snapshot(
        membership_effective_date,
        path=membership_path,
        repo_root=root,
    )

    result = scan_pattern_a_universe(
        cache=resolved_cache_dir,
        as_of=target_as_of,
        reference_market_date=reference_market_date,
        target_markets=markets,
        target_tickers=tickers,
        limit=limit,
        repository=repository,
        sector_mapping=sector_mapping,
        sector_mapping_snapshot_date=membership_effective_date,
        enrich_market_rs_cross_section=enrich_market_rs_cross_section,
    )
    summary = result.summary
    validate_full_common_scan(
        summary,
        is_full_common_scan=(market is None and tickers is None and limit is None),
    )
    csv_path, json_path = result.save_artifacts(output_dir=resolved_output_dir)
    return {
        "status": "PASS",
        "requested_as_of": target_as_of,
        "target_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "csv_path": str(csv_path),
        "summary_path": str(json_path),
        "summary": summary,
    }


def main() -> None:
    args = parse_args()

    logger.info("==================================================")
    logger.info("Starting Pattern A Full Universe Scanner v0.1")
    logger.info("  As-Of Date: %s", args.as_of)
    logger.info("  Cache Dir:  %s", args.cache_dir)
    logger.info("  Market:     %s", args.market or "ALL (KOSPI + KOSDAQ)")
    logger.info("  Limit:      %s", args.limit or "None (Full COMMON)")
    logger.info("  Market RS Cross-Section: %s", args.enrich_market_rs_cross_section)
    logger.info("==================================================")

    # PRODUCTION_ROLLING_MODE: --as-of is caller-supplied and can be a live date, so the rolling
    # certified boundary must be enforced unconditionally (directive
    # ROLLING_MARKET_DATA_AUTHORITY_FINALIZATION_V01 section 7).
    run_result = run_phase4a(
        args.as_of,
        root=ROOT,
        cache_dir=args.cache_dir,
        output_dir=args.output_dir,
        market=args.market,
        tickers=args.tickers,
        limit=args.limit,
        enrich_market_rs_cross_section=args.enrich_market_rs_cross_section,
    )
    reference_market_date = str(run_result["reference_market_date"])
    summary = run_result["summary"]
    logger.info("  Reference Market Date: %s", reference_market_date)

    logger.info("==================================================")
    logger.info("Pattern A Universe Scan Completed!")
    logger.info("  Official COMMON Total:  %d", summary.official_common_total)
    logger.info("  Scan Target Count:      %d", summary.scan_target_count)
    logger.info("  Rows Emitted:           %d", summary.rows_emitted)
    logger.info("  Cache Present:          %d", summary.cache_present_count)
    logger.info("  Cache Missing:          %d", summary.cache_missing_count)
    logger.info("  Raw Data Ready:         %d", summary.raw_ready_count)
    logger.info("  Score Ready:            %d", summary.score_ready_count)
    logger.info("  Stage Ready:            %d", summary.stage_ready_count)
    logger.info("  Evaluator Ready:        %d", summary.evaluator_ready_count)
    logger.info("  Momentum Current Ready: %d", summary.momentum_current_ready_count)
    logger.info("  Momentum 1M Ready:      %d", summary.momentum_1m_ready_count)
    logger.info("  Momentum 3M Ready:      %d", summary.momentum_3m_ready_count)
    logger.info("  Momentum 6M Ready:      %d", summary.momentum_6m_ready_count)
    logger.info("  Scanner Errors:         %d", summary.scanner_error_count)
    logger.info("--------------------------------------------------")
    logger.info("  Stage Distribution:")
    for k, v in summary.stage_distribution.items():
        logger.info("    - %-12s: %d", k, v)
    logger.info("--------------------------------------------------")
    logger.info("  Candidate State Distribution:")
    for k, v in summary.candidate_state_distribution.items():
        logger.info("    - %-18s: %d", k, v)
    logger.info("--------------------------------------------------")
    logger.info("  Score Statistics (N=%d):", summary.score_distribution["count"])
    logger.info(
        "    mean=%.2f, median=%.2f, min=%.2f, max=%.2f, q25=%.2f, q75=%.2f",
        summary.score_distribution["mean"] or 0,
        summary.score_distribution["median"] or 0,
        summary.score_distribution["min"] or 0,
        summary.score_distribution["max"] or 0,
        summary.score_distribution["q25"] or 0,
        summary.score_distribution["q75"] or 0,
    )
    logger.info("==================================================")

    logger.info("Artifacts saved:")
    logger.info("  CSV:  %s", run_result["csv_path"])
    logger.info("  JSON: %s", run_result["summary_path"])


if __name__ == "__main__":
    main()
