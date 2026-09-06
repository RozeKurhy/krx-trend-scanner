"""Build the instrument-only 4,095-date calendar from local migration evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from trend_scanner.data.krx_historical_instrument_acquisition import (
    HISTORICAL_CALENDAR_PATH,
    build_historical_calendar_payload,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--staging", type=Path, default=Path(".cache/krx_openapi/market_index_migration/v01/market_index_staging.parquet"))
    parser.add_argument("--output", type=Path, default=HISTORICAL_CALENDAR_PATH)
    args = parser.parse_args()
    frame = pd.read_parquet(args.staging)
    if "date" not in frame.columns:
        raise SystemExit("staging parquet has no date column")
    dates = sorted({pd.Timestamp(value).strftime("%Y-%m-%d") for value in frame["date"]})
    payload = build_historical_calendar_payload(dates)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output), "trading_date_count": payload["trading_date_count"], "trading_dates_sha256": payload["trading_dates_sha256"], "generated_from_network": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
