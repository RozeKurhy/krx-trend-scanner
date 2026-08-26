"""Offline historical-universe authority reconciliation preflight."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trend_scanner.universe.historical_authority_reconciliation import (
    BLOCKED_RECONCILIATION_INPUT_AUTHORITY,
    DEFAULT_ACQUISITION_CHECKPOINT_PATH,
    DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH,
    DEFAULT_HARNESS_OUTPUT_DIR,
    DEFAULT_RAW_ROOT,
    DEFAULT_TARGET_IDENTITY_PATH,
    ReconciliationContractError,
    derive_target_identities_from_repository,
    run_reconciliation_preflight,
    write_target_identity_artifact,
)

# Section 32: BLOCKED states are never reported as CLI exit 0.
EXIT_OK = 0
EXIT_BLOCKED_RECONCILIATION_INPUT_AUTHORITY = 2
EXIT_TARGET_CONTRACT_FAILURE = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the network-free historical-universe reconciliation preflight")
    parser.add_argument("--basic-info-root", type=Path, default=DEFAULT_RAW_ROOT)
    parser.add_argument("--target-identities", type=Path, default=DEFAULT_TARGET_IDENTITY_PATH)
    parser.add_argument("--acquisition-checkpoint", type=Path, default=DEFAULT_ACQUISITION_CHECKPOINT_PATH)
    parser.add_argument("--acquisition-final-summary", type=Path, default=DEFAULT_ACQUISITION_FINAL_SUMMARY_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_HARNESS_OUTPUT_DIR)
    parser.add_argument(
        "--write-target-artifact",
        action="store_true",
        help="derive the compact target identity reference from local parquet data",
    )
    args = parser.parse_args()

    try:
        if args.write_target_artifact:
            payload = derive_target_identities_from_repository(Path.cwd())
            write_target_identity_artifact(payload, args.target_identities)

        result = run_reconciliation_preflight(
            target_identities_path=args.target_identities,
            basic_info_root=args.basic_info_root,
            acquisition_checkpoint_path=args.acquisition_checkpoint,
            acquisition_final_summary_path=args.acquisition_final_summary,
        )
    except ReconciliationContractError as exc:
        print(json.dumps({"status": exc.status, "reason": str(exc)}, ensure_ascii=False, indent=2))
        return EXIT_TARGET_CONTRACT_FAILURE

    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = args.output_dir / "preflight_summary.json"
    summary_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    print(json.dumps({
        "status": result["status"],
        "reconciliation_input_status": result["reconciliation_input_status"],
        "target": result["target"],
        "classification_executed": result["classification_executed"],
        "actual_denominator_frozen": result["actual_denominator_frozen"],
        "network_requests": result["network_requests"],
        "summary_path": str(summary_path),
    }, ensure_ascii=False, indent=2))
    if result["status"] == BLOCKED_RECONCILIATION_INPUT_AUTHORITY:
        return EXIT_BLOCKED_RECONCILIATION_INPUT_AUTHORITY
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
