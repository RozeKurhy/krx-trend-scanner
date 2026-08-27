#!/usr/bin/env python3
"""CLI runner for Adjusted Price Store Bounded Live Pilot (FIX01)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from trend_scanner.data.adjusted_price_pilot import run_bounded_live_pilot

DEFAULT_OUTPUT_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_bounded_live_pilot/v01"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Adjusted Price Store Bounded Live Pilot FIX01")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to save canonical pilot artifacts",
    )
    args = parser.parse_args()

    print(f"Starting Adjusted Price Store Bounded Live Pilot (FIX01)...")
    print(f"Output directory: {args.output_dir}")

    pilot_data = run_bounded_live_pilot(output_dir=args.output_dir)
    summary = pilot_data["summary"]

    print("\n--- Pilot Execution Completed ---")
    print(f"Final Verdict: {summary['final_verdict']}")
    print(f"Next State: {summary['next_state']}")
    print(f"Total Samples: {summary['sample_counts']['total_samples']}")
    print(f"Eligible Full: {summary['outcome_counts']['eligible_full']}")
    print(f"Alpha 23 Supported: {summary['group_summaries']['alpha_23_census']['supported']}/23")
    print(f"Data Quality: duplicates={summary['data_quality']['total_duplicate_rows']}, "
          f"invalid_ohlc={summary['data_quality']['total_invalid_ohlc_rows']}, "
          f"future_rows={summary['data_quality']['total_future_rows']}")

    return 0 if summary["final_verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    sys.exit(main())
