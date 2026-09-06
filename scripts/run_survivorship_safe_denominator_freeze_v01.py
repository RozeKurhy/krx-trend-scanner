"""Offline survivorship-safe historical denominator freeze (zero network)."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from trend_scanner.universe.historical_authority_reconciliation import (
    DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
    DEFAULT_CALENDAR_PATH,
    DEFAULT_RAW_ROOT,
    DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR,
    DEFAULT_TARGET_IDENTITY_PATH,
)
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_CLOSURE_ARTIFACT_PATH,
    DEFAULT_PIT_ARTIFACT_PATH,
    DEFAULT_POPULATION_ARTIFACT_PATH,
    FREEZE_STATUS_CLOSED_AND_FROZEN,
    run_survivorship_safe_denominator_freeze,
)

EXIT_OK = 0
EXIT_BLOCKED = 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze the survivorship-safe Population Universe + PIT common denominator")
    parser.add_argument("--basic-info-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--target-identities", type=Path, default=DEFAULT_TARGET_IDENTITY_PATH)
    parser.add_argument("--acquisition-checkpoint", type=Path, default=DEFAULT_ACQUISITION_CHECKPOINT_PATH)
    parser.add_argument("--acquisition-final-summary", type=Path, default=DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH)
    parser.add_argument("--supplemental-authority-dir", type=Path, default=DEFAULT_SUPPLEMENTAL_AUTHORITY_DIR)
    parser.add_argument("--calendar", type=Path, default=DEFAULT_CALENDAR_PATH)
    parser.add_argument("--population-artifact", type=Path, default=DEFAULT_POPULATION_ARTIFACT_PATH)
    parser.add_argument("--pit-artifact", type=Path, default=DEFAULT_PIT_ARTIFACT_PATH)
    parser.add_argument("--closure-artifact", type=Path, default=DEFAULT_CLOSURE_ARTIFACT_PATH)
    parser.add_argument("--created-from-head", type=str, default=None)
    args = parser.parse_args()

    created_from_head = args.created_from_head
    if created_from_head is None:
        try:
            created_from_head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).resolve().parents[1],
                capture_output=True,
                check=True,
                text=True,
            ).stdout.strip()
        except (OSError, subprocess.CalledProcessError):
            created_from_head = None

    result = run_survivorship_safe_denominator_freeze(
        target_identities_path=args.target_identities,
        basic_info_root=args.basic_info_root,
        acquisition_checkpoint_path=args.acquisition_checkpoint,
        acquisition_final_summary_path=args.acquisition_final_summary,
        supplemental_authority_dir=args.supplemental_authority_dir,
        calendar_path=args.calendar,
        population_artifact_path=args.population_artifact,
        pit_artifact_path=args.pit_artifact,
        closure_artifact_path=args.closure_artifact,
        created_from_head=created_from_head,
    )

    print(json.dumps({
        "status": result["status"],
        "network_requests": result.get("network_requests"),
        "population_artifact_path": str(args.population_artifact),
        "pit_artifact_path": str(args.pit_artifact),
        "closure_artifact_path": str(args.closure_artifact),
    }, ensure_ascii=False, indent=2))

    return EXIT_OK if result["status"] == FREEZE_STATUS_CLOSED_AND_FROZEN else EXIT_BLOCKED


if __name__ == "__main__":
    raise SystemExit(main())
