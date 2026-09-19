#!/usr/bin/env python3
"""Offline-by-default Phase 3A foreign-flow rolling update entrypoint."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from trend_scanner.data.foreign_flow_rolling import update_foreign_flow_snapshot


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Update one exact-date foreign-flow snapshot")
    parser.add_argument(
        "--target-as-of",
        required=True,
        help="inclusive YYYY-MM-DD target; there is no system-date default",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    result = update_foreign_flow_snapshot(args.target_as_of, repo_root=ROOT)
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result.status in {"PASS", "NOOP_ALREADY_COMPLETE"} else 1


if __name__ == "__main__":
    raise SystemExit(main())

