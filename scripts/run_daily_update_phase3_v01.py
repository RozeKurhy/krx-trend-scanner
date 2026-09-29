#!/usr/bin/env python3
"""Run the official Phase 3G coordinator for one explicit target date."""

from __future__ import annotations

import argparse
from contextlib import redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path

from trend_scanner.data.daily_update_phase3 import build_official_phase3_coordinator
from trend_scanner.data.krx_credentials import load_phase3_krx_credentials


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target-as-of", required=True, help="inclusive YYYY-MM-DD target")
    parser.add_argument(
        "--fundamentals-run-date",
        help="explicit OpenDART quota-accounting date; required when fundamentals must run",
    )
    parser.add_argument("--fundamentals-env-file", type=Path, default=ROOT.parent / "env.md")
    parser.add_argument(
        "--execute-live",
        action="store_true",
        help="allow existing production 3A--3F entrypoints to run",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.execute_live:
        parser.error("--execute-live is required; 3G has no implicit live execution")
    load_phase3_krx_credentials(ROOT)
    coordinator = build_official_phase3_coordinator(
        repo_root=ROOT,
        fundamentals_env_file=args.fundamentals_env_file,
        fundamentals_run_date=args.fundamentals_run_date,
    )
    # Existing PyKRX dependencies may print login diagnostics. Keep those
    # process-local and publish only the structured, secret-checked result.
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        result = coordinator.execute(args.target_as_of)
    serialized = json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2, default=str)
    credentials = (
        os.getenv("KRX_ID", "").strip(),
        os.getenv("KRX_PW", "").strip(),
        os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip(),
    )
    if any(value and value in serialized for value in credentials):
        print(json.dumps({"overall_status": "FAILED", "reason": "CREDENTIAL_VALUE_DETECTED"}))
        return 1
    print(serialized)
    return 0 if result.overall_status in {"PASS", "NOOP_ALREADY_COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
