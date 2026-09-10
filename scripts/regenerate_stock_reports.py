#!/usr/bin/env python
"""Batch regenerator for Stock Reports using the canonical KRX Market Calendar."""

import glob
import logging
from pathlib import Path
import re
from concurrent.futures import ProcessPoolExecutor
from trend_scanner.reporting.stock_report import generate_stock_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
_DATE_DIR_PATTERN = re.compile(r"^(\d{8})$")


def _resolve_report_directory() -> tuple[Path, str]:
    candidates = []
    root = ROOT / "artifacts/reporting/stock_reports"
    for path in root.iterdir():
        if not path.is_dir() or _DATE_DIR_PATTERN.fullmatch(path.name) is None:
            continue
        json_dir = path / "json"
        if json_dir.is_dir() and any(json_dir.glob("*.json")):
            candidates.append((path.name, path))
    if not candidates:
        raise FileNotFoundError("no dated Stock Report JSON authority found")
    date_key, directory = max(candidates)
    return directory, f"{date_key[:4]}-{date_key[4:6]}-{date_key[6:]}"


REPORTS_DIR, REPORT_AS_OF = _resolve_report_directory()


def _regen_worker(ticker: str) -> tuple[str, str, str]:
    try:
        report, jp, mp = generate_stock_report(
            ticker=ticker, as_of=REPORT_AS_OF, save_artifacts=True, output_dir=REPORTS_DIR
        )
        return (ticker, str(report.name), "OK")
    except Exception as exc:
        return (ticker, "ERROR", str(exc))


def main() -> None:
    json_files = sorted(glob.glob(str(REPORTS_DIR / "json" / "*.json")))
    tickers = [Path(f).stem.split("_")[0] for f in json_files]
    logger.info("Regenerating %d stock reports for %s...", len(tickers), REPORT_AS_OF)

    with ProcessPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_regen_worker, tickers))

    errors = [r for r in results if r[2] != "OK"]
    logger.info("Regeneration finished: %d succeeded, %d failed.", len(results) - len(errors), len(errors))
    if errors:
        for e in errors:
            logger.error("Error for ticker %s: %s", e[0], e[2])


if __name__ == "__main__":
    main()
