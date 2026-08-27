#!/usr/bin/env python3
"""Run Adjusted Price Store Bounded Live Pilot v01."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trend_scanner.data.adjusted_price_pilot import (
    EXPECTED_POPULATION_SHA256,
    build_pilot_sample_manifest,
    run_bounded_live_pilot,
)
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
)

DEFAULT_OUTPUT_DIR = Path(
    "artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_bounded_live_pilot/v01"
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run bounded live pilot for AdjustedPriceStore")
    parser.add_argument(
        "--population-path",
        type=Path,
        default=Path(DEFAULT_POPULATION_ARTIFACT_PATH),
        help="Path to frozen historical common population artifact",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write pilot artifacts",
    )
    args = parser.parse_args()

    print("======================================================================")
    print("ADJUSTED PRICE STORE BOUNDED LIVE PILOT V01")
    print("======================================================================")
    print(f"Population Path: {args.population_path}")
    print(f"Output Directory: {args.output_dir}")

    manifest = build_pilot_sample_manifest(args.population_path)
    print(f"Constructed stratified sample manifest: {len(manifest)} samples")

    print("\nExecuting bounded live pilot queries...")
    output = run_bounded_live_pilot(
        samples=manifest,
        population_path=args.population_path,
        output_dir=args.output_dir,
    )

    summary = output["summary"]
    print("\n======================================================================")
    print(f"PILOT EXECUTION RESULT: {summary['final_verdict']}")
    print("======================================================================")
    print(json.dumps(summary, indent=2, ensure_ascii=False))

    return 0 if summary["final_verdict"] in ("ACCEPT", "CONDITIONAL") else 1


if __name__ == "__main__":
    raise SystemExit(main())
