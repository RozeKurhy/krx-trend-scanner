#!/usr/bin/env python3
"""Persist B Select Core V1 historical PIT fundamental statuses for one status date.

Reads the B Select production status for ``--as-of``, evaluates every status key
(trade entry signal dates, open-position entry dates, the requested date for
items without a signal) with the shared cache-only PIT path, and merges the
results into the ledger.  Fixed entries are never rewritten; entries that are
``미상`` only because of a local cache gap stay retryable.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.strategies.b_select_core_fundamental_status import (  # noqa: E402
    resolve_statuses,
    status_keys,
    write_ledger,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", required=True, help="B Select status requested_as_of (YYYY-MM-DD)")
    args = parser.parse_args()
    status_path = ROOT / "artifacts/strategies/b_select_core_v1/production" / args.as_of.replace("-", "") / "status.json"
    status = json.loads(status_path.read_text(encoding="utf-8"))
    if status.get("requested_as_of") != args.as_of:
        raise SystemExit(f"status requested_as_of mismatch: {status.get('requested_as_of')}")
    keys = status_keys(status["items"], args.as_of)
    resolved = resolve_statuses(keys, ROOT)
    path = write_ledger(ROOT, resolved)
    print(json.dumps({
        "as_of": args.as_of,
        "keys": len(keys),
        "basis": dict(Counter(keys.values())),
        "status": dict(Counter(row["fundamental_status"] for row in resolved.values())),
        "retryable": sum(row["retryable"] == "true" for row in resolved.values()),
        "ledger": str(path.relative_to(ROOT)),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
