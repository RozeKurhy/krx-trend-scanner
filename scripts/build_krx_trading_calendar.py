#!/usr/bin/env python
"""Canonical Derived KRX Exchange Trading Calendar Generator.

Constructs the canonical derived KRX market trading calendar artifact from the
union of all traded KRX common stocks in data/raw/stocks/*.parquet.

Explicitly accepts:
  - cutoff_date: the maximum observation date (e.g. 2026-08-14)
  - last_completed_market_month_end: the definitive actual market trading day of the last completed month (e.g. 2026-07-31)

Zero reliance on naive calendar MonthEnd (e.g. MonthEnd(0)) inferences to ensure
accurate handling of months where actual market month end precedes calendar month end (e.g. 2025-08-29 vs 2025-08-31).
"""

from __future__ import annotations

import glob
import json
import logging
from pathlib import Path
from typing import Any, Sequence

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = ROOT / "data/raw/stocks"
OUTPUT_DIR = ROOT / "data/reference"
OUTPUT_PARQUET = OUTPUT_DIR / "krx_trading_calendar.parquet"
OUTPUT_JSON = OUTPUT_DIR / "krx_trading_calendar.json"

DEFAULT_CUTOFF = pd.Timestamp("2026-08-21")
DEFAULT_LAST_COMPLETED_MONTH_END = pd.Timestamp("2026-07-31")


def build_krx_trading_calendar_from_dates(
    trading_dates: Sequence[pd.Timestamp | str],
    cutoff_date: pd.Timestamp | str,
    last_completed_market_month_end: pd.Timestamp | str,
    output_dir: Path | None = None,
    source_name: str = "CANONICAL_DERIVED_KRX_CALENDAR",
    provenance_description: str = "Derived canonical KRX Exchange Trading Calendar constructed from the union of all traded common stocks.",
    allow_downgrade: bool = False,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Trading dates 시계열과 명시적 completion boundary로부터 캘린더 아티팩트를 생성하고 검증한다."""
    cutoff_dt = pd.Timestamp(cutoff_date).normalize()
    last_cme_dt = pd.Timestamp(last_completed_market_month_end).normalize()

    # Stale Downgrade Guard
    if output_dir is not None and not allow_downgrade:
        json_path = output_dir / "krx_trading_calendar.json"
        if json_path.exists():
            try:
                with open(json_path, encoding="utf-8") as f:
                    existing_meta = json.load(f)
                existing_cutoff = pd.Timestamp(existing_meta.get("cutoff_date")).normalize()
                if cutoff_dt < existing_cutoff:
                    raise ValueError(
                        f"Refusing stale calendar downgrade: attempted cutoff {cutoff_dt.strftime('%Y-%m-%d')} "
                        f"is older than existing canonical cutoff {existing_cutoff.strftime('%Y-%m-%d')}"
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    # Slicing and normalization
    all_dt_series = pd.DatetimeIndex(pd.to_datetime(list(trading_dates)).normalize()).sort_values().unique()
    sliced_dates = all_dt_series[all_dt_series <= cutoff_dt]

    if len(sliced_dates) == 0:
        raise ValueError(f"No trading dates available on or before cutoff {cutoff_dt.strftime('%Y-%m-%d')}")

    min_date = sliced_dates[0]
    max_observed_date = sliced_dates[-1]

    # --- Strict Input Validation on last_completed_market_month_end ---
    if last_cme_dt > cutoff_dt:
        raise ValueError(
            f"last_completed_market_month_end ({last_cme_dt.strftime('%Y-%m-%d')}) cannot be in the future "
            f"beyond cutoff_date ({cutoff_dt.strftime('%Y-%m-%d')})"
        )

    if last_cme_dt < min_date:
        raise ValueError(
            f"last_completed_market_month_end ({last_cme_dt.strftime('%Y-%m-%d')}) cannot precede "
            f"min trading date ({min_date.strftime('%Y-%m-%d')})"
        )

    dates_set = set(sliced_dates)
    if last_cme_dt not in dates_set:
        raise ValueError(
            f"last_completed_market_month_end ({last_cme_dt.strftime('%Y-%m-%d')}) is not a valid trading day in the calendar."
        )

    # Group by (year, month) and calculate observed month end for each month
    df_dates = pd.DataFrame({"trading_date": sliced_dates}, index=sliced_dates)
    monthly_groups = df_dates.groupby([df_dates.index.year, df_dates.index.month])

    # Validate that last_cme_dt is indeed the max trading date for its year/month
    cme_ym = (last_cme_dt.year, last_cme_dt.month)
    if cme_ym not in monthly_groups.groups:
        raise ValueError(f"Year-month {cme_ym} not found in trading dates.")
    
    expected_max_for_cme_month = monthly_groups.get_group(cme_ym).index.max().normalize()
    if last_cme_dt != expected_max_for_cme_month:
        raise ValueError(
            f"last_completed_market_month_end ({last_cme_dt.strftime('%Y-%m-%d')}) must match the "
            f"actual last trading date of that month ({expected_max_for_cme_month.strftime('%Y-%m-%d')})."
        )

    # Build completed_month_ends using explicit boundary comparison (month_end <= last_cme_dt)
    completed_month_ends: list[str] = []
    last_completed_ym: tuple[int, int] | None = None

    for (year, month), group in monthly_groups:
        actual_month_end_date = group.index.max().normalize()
        if actual_month_end_date <= last_cme_dt:
            completed_month_ends.append(actual_month_end_date.strftime("%Y-%m-%d"))
            last_completed_ym = (year, month)

    last_completed_str = f"{last_completed_ym[0]:04d}-{last_completed_ym[1]:02d}" if last_completed_ym else None
    last_completed_me_str = completed_month_ends[-1] if completed_month_ends else None

    # Determine terminal partial month if max_observed_date > last_cme_dt
    terminal_partial_month = (
        f"{max_observed_date.year:04d}-{max_observed_date.month:02d}"
        if max_observed_date > last_cme_dt
        else None
    )

    completed_set = set(completed_month_ends)
    cal_df = pd.DataFrame({
        "trading_date": sliced_dates,
        "is_completed_month_end": [d.strftime("%Y-%m-%d") in completed_set for d in sliced_dates],
    })

    metadata: dict[str, Any] = {
        "calendar_source": source_name,
        "provenance_description": provenance_description,
        "source_version": "v2.0",
        "generated_at": pd.Timestamp.now(tz="Asia/Seoul").isoformat(),
        "cutoff_date": cutoff_dt.strftime("%Y-%m-%d"),
        "min_date": min_date.strftime("%Y-%m-%d"),
        "max_observed_trading_date": max_observed_date.strftime("%Y-%m-%d"),
        "row_count": len(cal_df),
        "last_completed_market_month": last_completed_str,
        "last_completed_market_month_end_date": last_completed_me_str,
        "completed_month_ends_count": len(completed_month_ends),
        "completed_month_ends": completed_month_ends,
        "terminal_partial_month": terminal_partial_month,
    }

    if output_dir is not None:
        out_p = Path(output_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        cal_df.to_parquet(out_p / "krx_trading_calendar.parquet", index=False)
        (out_p / "krx_trading_calendar.json").write_text(
            json.dumps(metadata, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    return cal_df, metadata


def build_krx_trading_calendar(
    stocks_dir: Path = STOCKS_DIR,
    cutoff_date: pd.Timestamp = DEFAULT_CUTOFF,
    last_completed_market_month_end: pd.Timestamp = DEFAULT_LAST_COMPLETED_MONTH_END,
    output_dir: Path = OUTPUT_DIR,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """2506개 KRX 보통주 Parquet 파일들로부터 Canonical Trading Calendar를 빌드한다."""
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

    cal_df, metadata = build_krx_trading_calendar_from_dates(
        trading_dates=sorted(all_dates),
        cutoff_date=cutoff_date,
        last_completed_market_month_end=last_completed_market_month_end,
        output_dir=output_dir,
    )

    logger.info(
        "Saved canonical KRX trading calendar: %d trading dates, %d completed month ends. "
        "Max observed: %s, Last completed month: %s (End: %s, Terminal Partial: %s)",
        len(cal_df),
        metadata["completed_month_ends_count"],
        metadata["max_observed_trading_date"],
        metadata["last_completed_market_month"],
        metadata["last_completed_market_month_end_date"],
        metadata["terminal_partial_month"],
    )

    return cal_df, metadata


if __name__ == "__main__":
    build_krx_trading_calendar()
