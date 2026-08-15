#!/usr/bin/env python
"""CLI Script to prepare Pattern A Candidate Chart Review Datasets.

Usage:
    uv run python scripts/prepare_pattern_a_candidate_review.py \
        --scanner-csv artifacts/scanner/pattern_a_universe_scan_20260814.csv \
        --output-dir artifacts/chart_review \
        --as-of 2026-08-14
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import sys

import pandas as pd

from trend_scanner.review.candidate_review import (
    CandidateReviewIntegrityError,
    extract_and_prepare_candidate_review,
    save_candidate_review_artifacts,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("prepare_pattern_a_candidate_review")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract Pattern A Candidate stocks and prepare chart review dataset."
    )
    parser.add_argument(
        "--scanner-csv",
        type=str,
        default="artifacts/scanner/pattern_a_universe_scan_20260814.csv",
        help="Path to Pattern A universe scan CSV artifact",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="artifacts/chart_review",
        help="Directory to save candidate review artifacts",
    )
    parser.add_argument(
        "--as-of",
        type=str,
        default="2026-08-14",
        help="As-of date string (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--overwrite-manual",
        action="store_true",
        default=False,
        help="Force overwrite existing manual review CSV (default: False)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scanner_path = Path(args.scanner_csv)

    if not scanner_path.exists():
        logger.error("Scanner CSV artifact not found at: %s", scanner_path)
        sys.exit(1)

    logger.info("==================================================")
    logger.info("Starting Pattern A Candidate Chart Review Dataset Preparation")
    logger.info("  Scanner CSV: %s", scanner_path)
    logger.info("  Output Dir:  %s", args.output_dir)
    logger.info("  As-Of:       %s", args.as_of)
    logger.info("==================================================")

    # 1. Scanner 결과 로드 (문자열 ticker 보존)
    scanner_df = pd.read_csv(scanner_path, dtype={"ticker": str})
    logger.info("Loaded scanner matrix: %d rows", len(scanner_df))

    # 2. Candidate 추출 및 검증
    try:
        as_of_tag = args.as_of.replace("-", "")
        source_df, manual_df, summary = extract_and_prepare_candidate_review(
            scanner_df=scanner_df,
            as_of=args.as_of,
            source_artifact_name=scanner_path.name,
        )
    except CandidateReviewIntegrityError as exc:
        logger.error("Integrity check failed: %s", exc)
        sys.exit(1)

    # 3. 아티팩트 저장
    source_csv, manual_csv, summary_json = save_candidate_review_artifacts(
        source_df=source_df,
        manual_review_df=manual_df,
        summary=summary,
        output_dir=args.output_dir,
        as_of_tag=as_of_tag,
        overwrite_manual=args.overwrite_manual,
    )

    logger.info("==================================================")
    logger.info("Pattern A Candidate Chart Review Datasets Ready!")
    logger.info("  Total Candidates Extracted: %d", summary.total_candidates)
    logger.info("    - TRANSITION:             %d", summary.transition_total)
    logger.info("    - EARLY_TREND:            %d", summary.early_trend_total)
    logger.info("  Reviewed:                   %d", summary.reviewed_count)
    logger.info("  Unreviewed:                 %d", summary.unreviewed_count)
    logger.info("--------------------------------------------------")
    logger.info("Artifacts:")
    logger.info("  Source CSV:        %s (%d rows)", source_csv, len(source_df))
    logger.info("  Manual Review CSV: %s (%d rows)", manual_csv, len(manual_df))
    logger.info("  Summary JSON:      %s", summary_json)
    logger.info("==================================================")


if __name__ == "__main__":
    main()
