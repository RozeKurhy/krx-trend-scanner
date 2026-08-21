#!/usr/bin/env python
"""KRX Historical Market Cap Backfill Manager for Julia Strategy V00 Required Signal Dates.

Direct KRX Data Marketplace collection is DEPRECATED and disabled due to KDM usage restriction.
Future resumption requires approved KRX Open API provider.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
import pandas as pd

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

HISTORY_DIR = ROOT / "artifacts/patterns/pattern_a/validation/investability_history"
SOURCE_DIR = HISTORY_DIR / "source"
NORMALIZED_DIR = HISTORY_DIR / "normalized"
JULIA_V00_DIR = ROOT / "artifacts/strategies/julia/v00"

REQUIRED_DATES_CSV = JULIA_V00_DIR / "historical_market_cap_required_dates.csv"
MANIFEST_CSV = JULIA_V00_DIR / "historical_market_cap_source_manifest.csv"
MISSING_DATES_CSV = JULIA_V00_DIR / "historical_market_cap_missing_dates.csv"


class HistoricalMarketCapSourceProvider:
    """Abstract interface for historical market cap source providers."""

    def fetch_market_snapshot(self, date_compact: str) -> list[dict[str, Any]]:
        raise NotImplementedError


class DirectKRXClient(HistoricalMarketCapSourceProvider):
    """Deprecated direct KDM client. Execution is guarded and disabled."""

    def __init__(self):
        raise RuntimeError(
            "Direct KRX Data Marketplace collection is disabled. "
            "Resume requires approved KRX OPEN API provider."
        )

    def fetch_market_snapshot(self, date_compact: str) -> list[dict[str, Any]]:
        raise RuntimeError("DirectKRXClient is disabled.")


def main() -> None:
    logger.info("Direct backfill script is currently disabled (checkpoint state).")
    logger.info("Refer to %s for pending dates to be backfilled via KRX Open API.", MISSING_DATES_CSV)


if __name__ == "__main__":
    main()
