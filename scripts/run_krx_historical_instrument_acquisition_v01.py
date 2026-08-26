"""Plan the historical instrument-master acquisition; live mode is explicit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

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
        summary = HistoricalInstrumentAcquisitionRunner(client, quota).run_full_historical(args.calendar, execute_live=args.execute_live)
    except SystemExit:
        raise
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED_ACQUISITION_EXECUTION_READINESS", "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
