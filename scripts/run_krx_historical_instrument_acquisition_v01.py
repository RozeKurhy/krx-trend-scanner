"""Plan the historical instrument-master acquisition; live mode is explicit."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from trend_scanner.data.krx_historical_instrument_acquisition import (
    EXPECTED_TRADING_DATES,
    HistoricalInstrumentAcquisitionRunner,
)
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota
from trend_scanner.data.market_calendar import MarketCalendarAuthority


def _dates(path: Path) -> list[str]:
    calendar = MarketCalendarAuthority.from_parquet(path)
    values = [value.strftime("%Y-%m-%d") for value in calendar.trading_dates]
    if len(values) != EXPECTED_TRADING_DATES:
        raise ValueError(f"validated calendar has {len(values)} dates; expected {EXPECTED_TRADING_DATES}")
    return values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--calendar", type=Path, default=Path("data/reference/krx_trading_calendar.parquet"))
    parser.add_argument("--quota-db", type=Path, default=Path(".cache/krx_openapi/quota.sqlite3"))
    parser.add_argument("--execute-live", action="store_true", help="required for any HTTP request; not used by default")
    args = parser.parse_args()
    try:
        dates = _dates(args.calendar)
    except Exception as exc:
        print(json.dumps({"status": "BLOCKED_ACQUISITION_EXECUTION_READINESS", "reason": str(exc)}, ensure_ascii=False, indent=2))
        return 2
    quota = LocalKrxOpenApiQuota(args.quota_db, reserve=500)
    if args.execute_live:
        auth_key = os.getenv("KRX_OPEN_API_AUTH_KEY", "").strip()
        if not auth_key:
            raise SystemExit("KRX_OPEN_API_AUTH_KEY is required only with --execute-live")
        client = KrxOpenApiClient(auth_key, max_requests=16380, max_transient_retries=1, quota=quota)
        summary = HistoricalInstrumentAcquisitionRunner(client, quota).run(dates, execute_live=True)
    else:
        summary = HistoricalInstrumentAcquisitionRunner(None, quota).run(dates, execute_live=False)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
