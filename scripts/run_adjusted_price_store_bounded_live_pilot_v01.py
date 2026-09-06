#!/usr/bin/env python3
"""CLI runner for Adjusted Price Store Bounded Live Pilot (FIX05)."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

from trend_scanner.data.adjusted_price_pilot import (
    DEFAULT_ARTIFACT_DIR,
    DEFAULT_REUSE_DIR,
    run_bounded_live_pilot,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Adjusted Price Store Bounded Live Pilot FIX05")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Directory to save artifacts (default: canonical dir for live, reuse_verification for reuse)",
    )
    parser.add_argument(
        "--mode",
        type=str,
        default="reuse",
        choices=["live", "reuse"],
        help="Execution mode: 'live' (execute live provider queries) or 'reuse' (source-faithful offline cached verification)",
    )
    args = parser.parse_args()

    print(f"Starting Adjusted Price Store Bounded Live Pilot (FIX05)...")
    print(f"Mode: {args.mode}")

    pilot_data = run_bounded_live_pilot(output_dir=args.output_dir, mode=args.mode)
    summary = pilot_data["summary"]

    print("\n--- Pilot Execution Completed ---")
    print(f"Execution ID: {summary['execution_id']}")
    print(f"Execution Mode: {summary['execution_provenance']['execution_mode']}")
    print(f"Final Verdict: {summary['final_verdict']}")
    print(f"Next State: {summary['next_state']}")
    print(f"New Live Requests: {summary['execution_provenance']['new_live_request_count']}")
    print(f"Reused Samples: {summary['execution_provenance']['reused_sample_count']}")

    return 0 if summary["final_verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    sys.exit(main())
