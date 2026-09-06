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

from trend_scanner.data.repository_v2_loader import build_production_repository_v2
from trend_scanner.scanner import scan_pattern_a_universe

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run_pattern_a_universe_scanner")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Pattern A Full Universe Scanner on Official COMMON Stocks."
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default="2026-08-14",
        help="Evaluation as-of date (YYYY-MM-DD, default: 2026-08-14)",
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
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    markets = [args.market] if args.market else None

    logger.info("==================================================")
    logger.info("Starting Pattern A Full Universe Scanner v0.1")
    logger.info("  As-Of Date: %s", args.as_of)
    logger.info("  Cache Dir:  %s", args.cache_dir)
    logger.info("  Market:     %s", args.market or "ALL (KOSPI + KOSDAQ)")
    logger.info("  Limit:      %s", args.limit or "None (Full COMMON)")
    logger.info("==================================================")

    # PRODUCTION_ROLLING_MODE: --as-of is caller-supplied and can be a live date, so the rolling
    # certified boundary must be enforced unconditionally (directive
    # ROLLING_MARKET_DATA_AUTHORITY_FINALIZATION_V01 section 7).
    repository = build_production_repository_v2(Path(__file__).resolve().parents[1], end=args.as_of)

    result = scan_pattern_a_universe(
        cache=Path(args.cache_dir),
        as_of=args.as_of,
        reference_market_date=args.as_of,
        target_markets=markets,
        target_tickers=args.tickers,
        limit=args.limit,
        repository=repository,
    )

    summary = result.summary

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

    csv_path, json_path = result.save_artifacts(output_dir=args.output_dir)
    logger.info("Artifacts saved:")
    logger.info("  CSV:  %s", csv_path)
    logger.info("  JSON: %s", json_path)


if __name__ == "__main__":
    main()
