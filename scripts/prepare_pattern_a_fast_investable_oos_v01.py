#!/usr/bin/env python
"""Phase 13J-1 strict-PIT investability feasibility audit.

This phase must stop before sampling when a reference-date market-cap history
is not locally available.  It deliberately has no market-data client and does
not create a sample manifest, charts, human labels, or OOS evaluation results.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


BASE_SHA = "0f460fa0132956296b3e6b003053a05acf019538"
# These are calendar-quarter W-FRI candidates.  The exact completed-week label
# must be derived from cached data; it cannot be verified for 2020 because the
# local raw cache begins in 2021-08.
REFERENCE_GRID_CANDIDATES = [
    "2020-03-27", "2020-06-26", "2020-09-25", "2020-12-25",
    "2021-03-26", "2021-06-25", "2021-09-24", "2021-12-31",
    "2022-03-25", "2022-06-24", "2022-09-30", "2022-12-30",
    "2023-03-31", "2023-06-30", "2023-09-22", "2023-12-29",
    "2024-03-29", "2024-06-28", "2024-09-27", "2024-12-27",
    "2025-03-28", "2025-06-27",
]
ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = ROOT / "artifacts/investability/source"
RAW_STOCK_DIR = ROOT / "data/raw/stocks"
OUT = ROOT / "artifacts/pattern_a_fast/investable_oos/pattern_a_fast_investable_oos_historical_investability_pit_audit_v01.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit() -> dict:
    """Report whether all required inputs exist at each common reference date."""
    source_files = sorted(SOURCE_DIR.glob("krx_market_cap_*.csv"))
    sources = []
    for path in source_files:
        frame = pd.read_csv(path, nrows=1)
        sources.append({
            "file_path": str(path.relative_to(ROOT)),
            "sha256": sha256(path),
            "effective_date": str(frame["effective_date"].iloc[0]) if "effective_date" in frame else None,
            "columns": frame.columns.tolist(),
        })

    raw_columns: list[str] = []
    raw_min_date = None
    raw_max_date = None
    sample_file = next(iter(sorted(RAW_STOCK_DIR.glob("*.parquet"))), None)
    if sample_file is not None:
        raw = pd.read_parquet(sample_file)
        raw_columns = raw.columns.tolist()
        raw_min_date = pd.Timestamp(raw.index.min()).strftime("%Y-%m-%d")
        raw_max_date = pd.Timestamp(raw.index.max()).strftime("%Y-%m-%d")

    available_mcap_dates = {item["effective_date"] for item in sources if item["effective_date"]}
    missing_mcap_calendar_candidates = [date for date in REFERENCE_GRID_CANDIDATES if date not in available_mcap_dates]
    return {
        "version": "PATTERN_A_FAST_INVESTABLE_OOS_B_PIT_AUDIT_V01",
        "phase": "13J-1",
        "base_sha": BASE_SHA,
        "status": "HISTORICAL_INVESTABILITY_PIT_BLOCKED",
        "historical_investability_pit_status": "BLOCKED",
        "calendar_quarter_reference_candidates": REFERENCE_GRID_CANDIDATES,
        "calendar_quarter_reference_candidate_count": len(REFERENCE_GRID_CANDIDATES),
        "exact_completed_week_grid_status": "NOT_DERIVABLE_FOR_FULL_PERIOD_FROM_LOCAL_CACHE",
        "required_inputs": {
            "market_cap_at_reference": "MISSING_FOR_ALL_REFERENCE_GRID_DATES",
            "shares_outstanding_at_reference": "MISSING_FOR_ALL_REFERENCE_GRID_DATES",
            "avg_trading_value_20d_at_reference": "AVAILABLE_FROM_LOCAL_RAW_OHLCV_WHERE_DAILY_HISTORY_EXISTS",
            "ticker_market_identity_at_reference": "NOT_FROZEN_AS_HISTORICAL_REFERENCE_DATASET",
        },
        "local_market_cap_sources": sources,
        "available_market_cap_effective_dates": sorted(available_mcap_dates),
        "missing_market_cap_calendar_candidates": missing_mcap_calendar_candidates,
        "raw_ohlcv_cache": {
            "sample_file": str(sample_file.relative_to(ROOT)) if sample_file else None,
            "columns": raw_columns,
            "min_date": raw_min_date,
            "max_date": raw_max_date,
            "contains_market_cap": "market_cap" in raw_columns,
            "contains_shares_outstanding": "shares_outstanding" in raw_columns,
        },
        "prohibited_substitutions_not_used": [
            "current_market_cap",
            "current_listing_status",
            "future_shares_outstanding",
            "close_times_future_shares_outstanding",
            "proxy_market_cap",
        ],
        "additional_data_required": [
            "KRX historical market-cap snapshot for every common reference-grid date",
            "reference-date shares outstanding or a canonical historical market-cap field",
            "reference-date ticker and market identity history",
        ],
        "sample_generated_count": 0,
        "human_stage_review_started": False,
        "human_outcome_review_started": False,
        "oos_evaluation_executed": False,
        "network_market_request_count": 0,
    }


def main() -> None:
    report = audit()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{report['status']}: {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
