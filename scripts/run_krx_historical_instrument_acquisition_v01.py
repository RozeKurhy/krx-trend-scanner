"""Plan the historical instrument-master acquisition; live mode is explicit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trend_scanner.data.krx_acquisition_closure import (
    DEFAULT_CLOSURE_PATH,
    build_acquisition_closure_summary,
    write_acquisition_closure_summary,
)
from trend_scanner.data.krx_historical_instrument_acquisition import (
    HISTORICAL_CALENDAR_PATH,
    EXPECTED_TRADING_DATES,
    HistoricalInstrumentAcquisitionRunner,
)
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, default=HISTORICAL_CALENDAR_PATH)
    parser.add_argument("--quota-db", type=Path, default=Path(".cache/krx_openapi/quota.sqlite3"))
    parser.add_argument("--closure-summary", type=Path, default=DEFAULT_CLOSURE_PATH)
    parser.add_argument("--execute-live", action="store_true", help="required for any HTTP request; not used by default")
    args = parser.parse_args()
    quota = LocalKrxOpenApiQuota(args.quota_db, reserve=500)
    try:
        if args.execute_live:
            auth_key = os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
            if not auth_key:
                raise SystemExit("KRX_OPEN_API_AUTH_KEY is required only with --execute-live")
            client = KrxOpenApiClient(auth_key, max_requests=16380, max_transient_retries=1, quota=quota)
        else:
            client = None
        runner = HistoricalInstrumentAcquisitionRunner(client, quota)
        summary = runner.run_full_historical(args.calendar, execute_live=args.execute_live)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED_ACQUISITION_EXECUTION_READINESS", "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 2

    closure_status = None
    if args.execute_live:
        # Section 21: a dry run (no --execute-live) must never touch the
        # production closure file at all — not even to write a non-ready
        # summary. Every live run, regardless of outcome, overwrites it
        # (Section 11 policy B), so a stale READY summary can never survive
        # a later failed/partial/paused run (Section 39).
        closure_payload = build_acquisition_closure_summary(
            summary, checkpoint_path=runner.checkpoint_path, raw_root=runner.raw_root, calendar_path=args.calendar,
        )
        write_acquisition_closure_summary(closure_payload, args.closure_summary)
        closure_status = closure_payload["status"]

    print(json.dumps({**summary, "closure_status": closure_status, "closure_summary_path": str(args.closure_summary) if args.execute_live else None}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
