#!/usr/bin/env python3
"""Phase 4B production runner: exact-target A FAST Core V2 + Stock Report v0.5.

Consumes only the 4A Scanner's exact-target artifacts
(``artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_{TARGET}.csv``
and its ``_summary.json``) and Phase 3B production Fundamentals artifacts
(``artifacts/fundamentals/production/{TARGET}/tickers/{ticker}.json``). It never
re-runs the Scanner, redefines the strategy, or hydrates Fundamentals -- it only
wires already-computed inputs into the existing ``generate_stock_report()`` /
A FAST Core V2 implementation for the Scanner's official ``candidate`` set.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from trend_scanner.data.repository_v2_loader import build_production_repository_v2
from trend_scanner.patterns.pattern_a_evaluator import PatternACandidateState
from trend_scanner.reporting.fundamentals_report import (
    FundamentalsArtifactUnavailable,
    load_fundamentals_section_from_production_artifact,
)
from trend_scanner.reporting.stock_report import generate_stock_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("run_daily_update_phase4b_v01")

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_STRATEGY_ID = "PATTERN_A_FAST_FINAL_STRATEGY_V02"
EXPECTED_REPORT_VERSION = "0.5"


class Phase4BError(RuntimeError):
    """Phase 4B fail-closed error (Scanner input validation, corpus validation)."""


def _scanner_paths(root: Path, target_as_of: str) -> tuple[Path, Path]:
    dt_clean = target_as_of.replace("-", "")
    base = root / "artifacts/patterns/pattern_a/production/scanner"
    return (
        base / f"pattern_a_universe_scan_{dt_clean}.csv",
        base / f"pattern_a_universe_scan_{dt_clean}_summary.json",
    )


def load_and_validate_scanner_input(root: Path, target_as_of: str) -> tuple[list[dict[str, str]], dict[str, Any]]:
    """4A exact-target Scanner CSV/summary만 로드하고 최소 계약을 검증한다 (fail-closed)."""
    csv_path, summary_path = _scanner_paths(root, target_as_of)
    if not csv_path.exists():
        raise Phase4BError(f"PHASE4B_SCANNER_CSV_MISSING: {csv_path}")
    if not summary_path.exists():
        raise Phase4BError(f"PHASE4B_SCANNER_SUMMARY_MISSING: {summary_path}")

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("requested_as_of") != target_as_of:
        raise Phase4BError(
            f"PHASE4B_SCANNER_REQUESTED_AS_OF_MISMATCH: expected {target_as_of}, "
            f"got {summary.get('requested_as_of')!r}"
        )
    reference_market_date = summary.get("reference_market_date")
    if not reference_market_date:
        raise Phase4BError("PHASE4B_SCANNER_REFERENCE_MARKET_DATE_MISSING")
    if str(reference_market_date) > target_as_of:
        raise Phase4BError(
            f"PHASE4B_SCANNER_REFERENCE_MARKET_DATE_AFTER_TARGET: "
            f"{reference_market_date} > {target_as_of}"
        )

    with csv_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    tickers = [r["ticker"] for r in rows]
    if len(tickers) != len(set(tickers)):
        raise Phase4BError("PHASE4B_SCANNER_DUPLICATE_TICKERS")

    rows_emitted = summary.get("rows_emitted")
    if rows_emitted != len(rows):
        raise Phase4BError(
            f"PHASE4B_SCANNER_ROW_COUNT_MISMATCH: csv rows={len(rows)}, "
            f"summary.rows_emitted={rows_emitted}"
        )

    return rows, summary


def select_candidate_tickers(rows: list[dict[str, str]]) -> list[str]:
    """Scanner 공식 candidate_state == CANDIDATE만, 실제 직렬화 값 기준으로 선택한다."""
    candidate_value = PatternACandidateState.CANDIDATE.value
    tickers = sorted(r["ticker"] for r in rows if r.get("candidate_state") == candidate_value)
    return tickers


@dataclass
class GenerationOutcome:
    ticker: str
    status: str  # "OK" or "ERROR"
    error: str | None = None


def generate_candidate_reports(
    candidate_tickers: list[str],
    *,
    target_as_of: str,
    reference_market_date: str,
    repository: Any,
    root: Path,
    staging_dir: Path,
) -> list[GenerationOutcome]:
    """staging_dir에 후보별 Stock Report v0.5를 생성한다. 개별 실패는 수집해 계속 진행하고
    (전체 생성 -> 전체 검증 -> promote 흐름을 위해), 최종 승격 여부는 호출자가 판단한다."""
    outcomes: list[GenerationOutcome] = []
    total = len(candidate_tickers)
    for i, ticker in enumerate(candidate_tickers, start=1):
        try:
            fundamentals_section = load_fundamentals_section_from_production_artifact(
                ticker, target_as_of, root,
            )
            generate_stock_report(
                ticker=ticker,
                as_of=target_as_of,
                repo_root=root,
                repository=repository,
                fundamentals_section=fundamentals_section,
                reference_market_date=reference_market_date,
                output_dir=staging_dir,
                save_artifacts=True,
            )
            outcomes.append(GenerationOutcome(ticker=ticker, status="OK"))
        except FundamentalsArtifactUnavailable as exc:
            outcomes.append(GenerationOutcome(ticker=ticker, status="ERROR", error=f"FUNDAMENTALS_FAIL_CLOSED: {exc}"))
        except Exception as exc:  # noqa: BLE001 -- collected for full-batch visibility, not swallowed
            outcomes.append(GenerationOutcome(ticker=ticker, status="ERROR", error=str(exc)))

        if i % 25 == 0 or i == total:
            logger.info("Generated %d/%d candidate reports", i, total)

    return outcomes


def validate_corpus(
    staging_dir: Path,
    candidate_tickers: set[str],
    target_as_of: str,
    reference_market_date: str,
) -> dict[str, Any]:
    """staging_dir에 실제로 쓰여진 JSON/Markdown을 대상으로 전체 결과를 검증한다."""
    json_paths = sorted((staging_dir / "json").glob("*.json"))
    md_paths = sorted(staging_dir.glob("*.md"))
    json_tickers = {p.stem.split("_")[0] for p in json_paths}
    md_tickers = {p.stem.split("_")[0] for p in md_paths}

    report_version_mismatches: list[str] = []
    strategy_id_mismatches: list[str] = []
    date_mismatches: list[str] = []

    for p in json_paths:
        payload = json.loads(p.read_text(encoding="utf-8"))
        ticker = p.stem.split("_")[0]
        if payload.get("report_version") != EXPECTED_REPORT_VERSION:
            report_version_mismatches.append(ticker)
        if payload.get("requested_as_of") != target_as_of or payload.get("reference_market_date") != reference_market_date:
            date_mismatches.append(ticker)
        strategy_id = (payload.get("a_fast_core") or {}).get("strategy_id")
        if strategy_id != EXPECTED_STRATEGY_ID:
            strategy_id_mismatches.append(ticker)

    return {
        "json_count": len(json_paths),
        "markdown_count": len(md_paths),
        "json_ticker_duplicate_count": len(json_paths) - len(json_tickers),
        "markdown_ticker_duplicate_count": len(md_paths) - len(md_tickers),
        "missing_tickers": sorted(candidate_tickers - json_tickers),
        "extra_tickers": sorted(json_tickers - candidate_tickers),
        "markdown_missing_tickers": sorted(candidate_tickers - md_tickers),
        "markdown_extra_tickers": sorted(md_tickers - candidate_tickers),
        "report_version_mismatch_count": len(report_version_mismatches),
        "strategy_id_mismatch_count": len(strategy_id_mismatches),
        "date_mismatch_count": len(date_mismatches),
    }


def promote_staging(staging_dir: Path, canonical_dir: Path) -> None:
    """staging_dir을 canonical_dir로 원자적으로 승격한다. 기존 partial canonical_dir이
    있어도 merge하지 않고 완전히 교체한다."""
    parent = canonical_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    new_dir = Path(tempfile.mkdtemp(prefix=".phase4b-new-", dir=str(parent)))
    shutil.rmtree(new_dir)
    shutil.copytree(staging_dir, new_dir)
    if canonical_dir.exists():
        old_dir = parent / f".phase4b-old-{uuid4().hex}"
        canonical_dir.rename(old_dir)
        try:
            new_dir.rename(canonical_dir)
        except Exception:
            old_dir.rename(canonical_dir)
            raise
        shutil.rmtree(old_dir)
    else:
        new_dir.rename(canonical_dir)


def run_phase4b(target_as_of: str, root: Path = ROOT) -> dict[str, Any]:
    rows, summary = load_and_validate_scanner_input(root, target_as_of)
    reference_market_date = str(summary["reference_market_date"])
    candidate_tickers = select_candidate_tickers(rows)
    candidate_ticker_set = set(candidate_tickers)

    logger.info(
        "Phase 4B target=%s: scanner rows=%d, candidate count=%d",
        target_as_of, len(rows), len(candidate_tickers),
    )

    repository = build_production_repository_v2(root, end=target_as_of)

    canonical_dir = root / "artifacts/reporting/stock_reports" / target_as_of.replace("-", "")
    staging_parent = canonical_dir.parent
    staging_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=".phase4b-staging-", dir=str(staging_parent)) as temp_name:
        staging_dir = Path(temp_name) / canonical_dir.name
        staging_dir.mkdir(parents=True, exist_ok=True)

        outcomes = generate_candidate_reports(
            candidate_tickers,
            target_as_of=target_as_of,
            reference_market_date=reference_market_date,
            repository=repository,
            root=root,
            staging_dir=staging_dir,
        )
        errors = [o for o in outcomes if o.status == "ERROR"]

        corpus = validate_corpus(staging_dir, candidate_ticker_set, target_as_of, reference_market_date)

        promoted = False
        success = (
            not errors
            and corpus["json_count"] == len(candidate_tickers)
            and corpus["markdown_count"] == len(candidate_tickers)
            and not corpus["missing_tickers"]
            and not corpus["extra_tickers"]
            and not corpus["markdown_missing_tickers"]
            and not corpus["markdown_extra_tickers"]
            and corpus["json_ticker_duplicate_count"] == 0
            and corpus["markdown_ticker_duplicate_count"] == 0
            and corpus["report_version_mismatch_count"] == 0
            and corpus["strategy_id_mismatch_count"] == 0
            and corpus["date_mismatch_count"] == 0
        )
        if success:
            promote_staging(staging_dir, canonical_dir)
            promoted = True
        else:
            logger.error("Phase 4B validation failed; canonical directory NOT promoted (staging discarded).")

    result = {
        "target_as_of": target_as_of,
        "requested_as_of": target_as_of,
        "reference_market_date": reference_market_date,
        "scanner_rows": len(rows),
        "scanner_candidate_count": len(candidate_tickers),
        "report_target_count": len(candidate_tickers),
        "generation_error_count": len(errors),
        "generation_errors": [{"ticker": o.ticker, "error": o.error} for o in errors],
        **corpus,
        "promoted": promoted,
        "canonical_dir": str(canonical_dir) if promoted else None,
    }
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="explicit YYYY-MM-DD target (no default)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = run_phase4b(args.target_as_of)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, default=str))
    return 0 if result["promoted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
