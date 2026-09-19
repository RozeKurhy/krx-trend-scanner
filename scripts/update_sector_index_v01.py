#!/usr/bin/env python3
"""Roll the existing native KRX sector-index cache to an explicit as-of date."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from dotenv import load_dotenv

from trend_scanner.data.sector_index_rolling import (
    BLOCKED,
    FAILED,
    update_sector_index_rolling,
)


ROOT = Path(__file__).resolve().parents[1]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--as-of",
        required=True,
        help="Explicit target date (YYYY-MM-DD); no system-date fallback is used.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    load_dotenv(ROOT / ".env", override=False)
    result = update_sector_index_rolling(args.as_of, repo_root=ROOT)
    print(json.dumps(result.to_dict(), ensure_ascii=False, sort_keys=True, indent=2))
    return 1 if result.status in {BLOCKED, FAILED} else 0


if __name__ == "__main__":
    raise SystemExit(main())
