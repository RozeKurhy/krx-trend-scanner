#!/usr/bin/env python3
"""Generate official ETF 36 Stock Report v0.6 artifacts from local data only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import warnings

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
warnings.filterwarnings("ignore", category=FutureWarning)

from trend_scanner.reporting.julia_v1_report import generate_official_etf36_reports
LEGACY_TARGET_AS_OF = "2026-09-25"
LEGACY_REFERENCE_MARKET_DATE = "2026-09-23"
SAMPLE_TICKERS = ("069500", "133690", "411060")


def _code_commit() -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", action="store_true", help="Run only the frozen three-ETF preflight sample in a temporary directory.")
    parser.add_argument(
        "--target-as-of",
        default=LEGACY_TARGET_AS_OF,
        help="Explicit report target date (defaults to the certified 2026-09-25 CLI regression).",
    )
    parser.add_argument(
        "--reference-market-date",
        default=LEGACY_REFERENCE_MARKET_DATE,
        help="Explicit certified market reference date (defaults to the 2026-09-25 CLI regression).",
    )
    args = parser.parse_args()
    if args.sample:
        with tempfile.TemporaryDirectory(prefix="etf_stock_report_v06_sample_") as temp_dir:
            summary = generate_official_etf36_reports(
                repo_root=ROOT,
                target_as_of=args.target_as_of,
                reference_market_date=args.reference_market_date,
                output_dir=Path(temp_dir),
                tickers=SAMPLE_TICKERS,
            )
        summary["code_commit"] = _code_commit()
        passed = (
            summary["expected_count"] == 3
            and summary["generated_count"] == 3
            and summary["failed_tickers_and_reasons"] == []
            and summary["strategy_id_counts"].get("JULIA_ETF_STRATEGY_V01") == 3
            and summary["julia_evaluator_error_tickers"] == []
        )
        print(json.dumps({"verdict": "SAMPLE_PASS" if passed else "SAMPLE_FAIL", **summary}, ensure_ascii=False, indent=2))
        return 0 if passed else 2

    output_dir = ROOT / "artifacts/reporting/etf_stock_reports" / args.target_as_of.replace("-", "")
    summary = generate_official_etf36_reports(
        repo_root=ROOT,
        target_as_of=args.target_as_of,
        reference_market_date=args.reference_market_date,
        output_dir=output_dir,
    )
    summary["code_commit"] = _code_commit()
    if summary.get("status") != "NOOP_ALREADY_COMPLETE":
        (output_dir / "generation_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    expected = set()
    from trend_scanner.reporting.julia_v1_report import load_official_etf36
    universe, _ = load_official_etf36(ROOT)
    expected = {row.ticker for row in universe}
    passed = (
        summary.get("status") in {"PASS", "NOOP_ALREADY_COMPLETE"}
        and summary["expected_count"] == 36
        and summary["generated_count"] == 36
        and set(summary["generated_tickers"]) == expected
        and summary["strategy_id_counts"].get("JULIA_ETF_STRATEGY_V01") == 36
        and summary["network_requests"] == 0
        and summary["post_asof_data_references"] == 0
        and summary["failed_tickers_and_reasons"] == []
        and summary["julia_evaluator_error_tickers"] == []
    )
    summary["verdict"] = "OFFICIAL_ETF36_STOCK_REPORT_JULIA_V1_INTEGRATION_PASS" if passed else "CHECK_REQUIRED"
    if summary.get("status") != "NOOP_ALREADY_COMPLETE":
        (output_dir / "generation_summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "status": summary.get("status"),
        "verdict": summary["verdict"],
        "expected_count": summary["expected_count"],
        "generated_count": summary["generated_count"],
        "readiness_status_counts": summary["readiness_status_counts"],
        "strategy_id_counts": summary["strategy_id_counts"],
        "eligibility_pass_fail_counts": summary["eligibility_pass_fail_counts"],
        "failed_tickers_and_reasons": summary["failed_tickers_and_reasons"],
        "code_commit": summary["code_commit"],
    }, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
