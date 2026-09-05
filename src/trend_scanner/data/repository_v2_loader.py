"""Production consumer loader backed by the canonical Repository V2.

The loader is deliberately small: Repository V2 owns all adjusted/raw
composition and validation; this class only supplies the DataFrame shape that
the frozen consumers already accept.  It never falls back to ParquetCache or
performs network I/O.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2


EXPECTED_DATA_UNAVAILABLE = frozenset(
    {
        "DATA_UNAVAILABLE: ADJUSTED_MISSING",
        "DATA_UNAVAILABLE: RAW_MISSING",
        "REPOSITORY_V2_EMPTY",
        # A raw/adjusted session mismatch is an explicit authority gap.  The
        # composed repository must remain fail-closed; consumers represent it
        # as DATA_UNAVAILABLE rather than converting it into an ERROR row or
        # consulting a legacy price source.
        "REPOSITORY_V2_TRADING_SESSION_MISMATCH",
    }
)


class RepositoryV2DailyLoader:
    """DataFrame loader for consumer paths; missing authority is fail-closed."""

    def __init__(
        self,
        repository: MarketDataRepositoryV2,
        *,
        start: str = "1900-01-01",
        end: str | pd.Timestamp = "2026-08-14",
    ) -> None:
        self.repository = repository
        self.start = str(start)[:10]
        self.end = pd.Timestamp(end).strftime("%Y-%m-%d")
        self.load_count = 0

    def load(self, ticker: str) -> pd.DataFrame | None:
        self.load_count += 1
        try:
            frame = self.repository.get_daily(str(ticker).zfill(6), self.start, self.end)
        except MarketDataError as exc:
            if str(exc) in EXPECTED_DATA_UNAVAILABLE:
                return None
            raise
        if frame is None or frame.empty:
            return None
        # Repository V2 exposes a deliberately detailed session audit on the
        # composed frame.  Pandas propagates/deep-copies ``DataFrame.attrs``
        # during every resample aggregation; carrying the full audit through
        # Pattern A/strategy feature calculation turns a linear scan into an
        # effectively quadratic metadata-copy workload.  Consumers only need
        # provenance and aggregate counts, so retain a compact immutable
        # summary and never pass the row-level evidence through feature code.
        audit = frame.attrs.get("session_projection_audit", {})
        result = frame.copy()
        result.attrs = {
            "data_authority": "MarketDataRepositoryV2",
            "session_projection_summary": {
                "adjusted_only_count": len(audit.get("adjusted_only_dates", ())),
                "raw_only_count": len(audit.get("raw_only_dates", ())),
                "explicit_exclusion_count": sum(
                    int(audit.get(key, 0) or 0)
                    for key in (
                        "explicit_placeholder_projection_count",
                        "explicit_known_gap_exclusion_count",
                        "explicit_outside_identity_lifecycle_exclusion_count",
                        "explicit_adjusted_source_nonusable_exclusion_count",
                        "explicit_analytic_invalid_exclusion_count",
                    )
                ),
                "silent_inner_drop_count": int(audit.get("silent_inner_drop_count", 0) or 0),
            },
        }
        result.attrs["requested_start"] = self.start
        result.attrs["requested_end"] = self.end
        result.attrs["effective_as_of"] = result.index.max().strftime("%Y-%m-%d")
        return result

    def load_ancillary(self, ticker: str) -> pd.DataFrame | None:
        """Return raw ancillary fields through the same V2 authority."""
        self.load_count += 1
        try:
            frame = self.repository.get_daily_ancillary(str(ticker).zfill(6), self.start, self.end)
        except MarketDataError as exc:
            if str(exc) in EXPECTED_DATA_UNAVAILABLE:
                return None
            raise
        if frame is None or frame.empty:
            return None
        result = frame.copy()
        result.attrs["data_authority"] = "MarketDataRepositoryV2"
        result.attrs["requested_start"] = self.start
        result.attrs["requested_end"] = self.end
        return result


def build_repository_v2(repo_root: Path | str, *, end: str | pd.Timestamp = "2026-08-14") -> MarketDataRepositoryV2:
    """Build one run-scoped Repository V2 instance from canonical stores."""
    root = Path(repo_root)
    return MarketDataRepositoryV2(
        AdjustedPriceStore(root / "data/market/adjusted/stocks"),
        KrxRawStockStore(root / "data/market/raw/krx_stocks/v01"),
    )


def repository_v2_provenance(frame: pd.DataFrame | None) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"authority": "MarketDataRepositoryV2", "available": False}
    return {
        "authority": "MarketDataRepositoryV2",
        "available": True,
        "requested_start": frame.attrs.get("requested_start"),
        "requested_end": frame.attrs.get("requested_end"),
        "effective_as_of": frame.attrs.get("effective_as_of"),
    }


__all__ = ["RepositoryV2DailyLoader", "build_repository_v2", "repository_v2_provenance"]
