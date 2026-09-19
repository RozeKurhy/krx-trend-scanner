#!/usr/bin/env python3
"""Update exact-date KRX sector membership snapshot for Daily Update V01."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from trend_scanner.data.sector_membership_exact_update import (
    BLOCKED,
    FAILED,
    update_sector_membership_exact,
)


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Update exact-date KRX sector membership snapshot."
    )
    parser.add_argument(
        "--as-of",
        required=True,
        help="Explicit target date (YYYY-MM-DD); no default or fallback is permitted.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=ROOT,
        help="Repository root directory (defaults to repo root).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    result = update_sector_membership_exact(
        args.as_of,
        repo_root=args.repo_root.resolve(),
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result.status in {BLOCKED, FAILED} else 0


if __name__ == "__main__":
    raise SystemExit(main())
