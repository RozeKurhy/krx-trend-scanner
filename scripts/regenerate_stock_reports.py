#!/usr/bin/env python
"""Batch regenerator for Stock Reports using the canonical KRX Market Calendar."""

import glob
import logging
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from trend_scanner.reporting.stock_report import generate_stock_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "artifacts/stock_reports/20260814"


def _regen_worker(ticker: str) -> tuple[str, str, str]:
    try:
        report, jp, mp = generate_stock_report(
            ticker=ticker, as_of="2026-08-14", save_artifacts=True, output_dir=REPORTS_DIR
        )
        return (ticker, str(report.name), "OK")
    except Exception as exc:
        return (ticker, "ERROR", str(exc))


def main() -> None:
    json_files = sorted(glob.glob(str(REPORTS_DIR / "*.json")))
    tickers = [Path(f).stem.split("_")[0] for f in json_files]
    logger.info("Regenerating %d stock reports for 2026-08-14...", len(tickers))

    with ProcessPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_regen_worker, tickers))

    errors = [r for r in results if r[2] != "OK"]
    logger.info("Regeneration finished: %d succeeded, %d failed.", len(results) - len(errors), len(errors))
    if errors:
        for e in errors:
            logger.error("Error for ticker %s: %s", e[0], e[2])


if __name__ == "__main__":
    main()
