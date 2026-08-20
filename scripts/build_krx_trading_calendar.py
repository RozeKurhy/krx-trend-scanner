#!/usr/bin/env python
"""Canonical KRX Exchange Trading Calendar Generator.

Constructs the canonical derived KRX market trading calendar artifact from the
union of all traded KRX common stocks in data/raw/stocks/*.parquet.

Explicitly distinguishes between:
  1. max_observed_trading_date (e.g. 2026-08-14)
  2. last_completed_market_month (e.g. 2026-07)
  3. completed_month_ends (list of confirmed actual market month-end trading days)

Ensures terminal partial months (e.g. August 2026 when cutoff is 2026-08-14)
are strictly excluded from completed_month_ends to prevent Point-In-Time leakage.
"""

from __future__ import annotations

import glob
import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = ROOT / "data/raw/stocks"
OUTPUT_DIR = ROOT / "data/reference"
OUTPUT_PARQUET = OUTPUT_DIR / "krx_trading_calendar.parquet"
OUTPUT_JSON = OUTPUT_DIR / "krx_trading_calendar.json"

DEFAULT_CUTOFF = pd.Timestamp("2026-08-14")


def build_krx_trading_calendar(
    stocks_dir: Path = STOCKS_DIR,
    cutoff_date: pd.Timestamp = DEFAULT_CUTOFF,
    output_dir: Path = OUTPUT_DIR,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=True)

    stock_files = sorted(glob.glob(str(stocks_dir / "*.parquet")))
    if not stock_files:
        raise RuntimeError(f"No stock parquet files found in {stocks_dir}")

    logger.info("Collecting trading dates from %d stock files...", len(stock_files))

    all_dates: set[pd.Timestamp] = set()
    for f in stock_files:
        try:
            df = pd.read_parquet(f, columns=["close"])
            if not df.empty:
                sliced = df[df.index <= cutoff_date]
                all_dates.update(sliced.index.normalize())
        except Exception as exc:
            logger.warning("Error reading %s: %s", f, exc)

    if not all_dates:
        raise RuntimeError("No trading dates collected from stock files.")

    sorted_dates = sorted(all_dates)
    min_date = sorted_dates[0]
    max_observed_date = sorted_dates[-1]

    # Group dates by (year, month) to identify month-end trading days
    df_dates = pd.DataFrame({"trading_date": sorted_dates}, index=sorted_dates)
    monthly_groups = df_dates.groupby([df_dates.index.year, df_dates.index.month])

    # Determine completion for each month
    # A month is completed if:
    # 1. The month is strictly before cutoff's month (i.e. year < cutoff.year or (year == cutoff.year and month < cutoff.month)), OR
    # 2. For cutoff's month, cutoff >= calendar month end (cutoff reached the end of the month)
    cutoff_month_end = (cutoff_date + pd.offsets.MonthEnd(0)).normalize()
    cutoff_is_full_month = cutoff_date.normalize() >= cutoff_month_end

    completed_month_ends: list[str] = []
    last_completed_ym: tuple[int, int] | None = None

    for (year, month), group in monthly_groups:
        last_day_in_month = group.index.max().normalize()
        is_prior_month = (year < cutoff_date.year) or (year == cutoff_date.year and month < cutoff_date.month)
        is_cutoff_month = (year == cutoff_date.year and month == cutoff_date.month)

        if is_prior_month or (is_cutoff_month and cutoff_is_full_month):
            completed_month_ends.append(last_day_in_month.strftime("%Y-%m-%d"))
            last_completed_ym = (year, month)

    last_completed_str = f"{last_completed_ym[0]:04d}-{last_completed_ym[1]:02d}" if last_completed_ym else None
    last_completed_me_str = completed_month_ends[-1] if completed_month_ends else None

    # Parquet artifact
    cal_df = pd.DataFrame({
        "trading_date": sorted_dates,
        "is_completed_month_end": [d.strftime("%Y-%m-%d") in set(completed_month_ends) for d in sorted_dates],
    })
    cal_df.to_parquet(output_dir / "krx_trading_calendar.parquet", index=False)

    metadata: dict[str, Any] = {
        "calendar_source": "CANONICAL_DERIVED_KRX_CALENDAR",
        "provenance_description": "Derived canonical KRX Exchange Trading Calendar constructed from the union of all traded common stocks.",
        "source_version": "v2.0",
        "generated_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
        "cutoff_date": cutoff_date.strftime("%Y-%m-%d"),
        "min_date": min_date.strftime("%Y-%m-%d"),
        "max_observed_trading_date": max_observed_date.strftime("%Y-%m-%d"),
        "row_count": len(cal_df),
        "last_completed_market_month": last_completed_str,
        "last_completed_market_month_end_date": last_completed_me_str,
        "completed_month_ends_count": len(completed_month_ends),
        "completed_month_ends": completed_month_ends,
        "terminal_partial_month": None if cutoff_is_full_month else f"{cutoff_date.year:04d}-{cutoff_date.month:02d}",
    }

    (output_dir / "krx_trading_calendar.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    logger.info(
        "Saved canonical KRX trading calendar: %d trading dates, %d completed month ends. "
        "Max observed: %s, Last completed month: %s (End: %s)",
        len(cal_df),
        len(completed_month_ends),
        max_observed_date.strftime("%Y-%m-%d"),
        last_completed_str,
        last_completed_me_str,
    )

    return cal_df, metadata


if __name__ == "__main__":
    build_krx_trading_calendar()
