"""Repository V2 backed input adapter for Market Relative Strength.

The RS calculator intentionally remains data-source agnostic.  This module is
the single production boundary that turns the frozen Repository V2 analytic
daily view into the ``stock_df`` shape consumed by that calculator.  It never
falls back to the legacy ``ParquetCache`` when Repository V2 cannot provide a
series.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2


@dataclass(frozen=True)
class MarketRSRepositoryInput:
    """One fail-closed Repository V2 input resolution."""

    stock_df: pd.DataFrame | None
    reason: str | None
    requested_start: str | None
    requested_end: str


def benchmark_anchor_start(
    market_index_df: pd.DataFrame,
    *,
    market_code: str,
    as_of: str,
) -> str | None:
    """Resolve the oldest exact benchmark anchor required by Market RS.

    Anchors are selected from the benchmark session sequence, never from a
    calendar offset or a stock sequence.  Returning ``None`` is intentional
    fail-closed behaviour when the benchmark itself cannot support all three
    frozen horizons.
    """

    if not isinstance(market_index_df, pd.DataFrame) or market_index_df.empty:
        return None
    required = market_index_df.loc[
        market_index_df["index_code"].astype(str) == str(market_code),
        ["date", "close"],
    ].copy()
    if required.empty:
        return None
    required["date"] = pd.to_datetime(required["date"], errors="coerce")
    required = required.dropna(subset=["date"])
    required = required[required["date"] <= pd.Timestamp(as_of)]
    required = required.sort_values("date", kind="mergesort").drop_duplicates("date")
    # The calculator uses index[-1 - sessions_back].  The oldest required
    # element is therefore index[-253] for the 252-session horizon.
    if len(required) <= 252:
        return None
    return required.iloc[-253]["date"].strftime("%Y-%m-%d")


def resolve_market_rs_repository_input(
    repository: MarketDataRepositoryV2 | None,
    *,
    ticker: str,
    as_of: str,
    market_code: str | None,
    market_index_df: pd.DataFrame,
) -> MarketRSRepositoryInput:
    """Load one stock series from the shared Repository V2 instance.

    Any Repository V2 error becomes a DATA_UNAVAILABLE input.  In particular,
    no legacy cache or adjusted/raw source is consulted here.
    """

    if repository is None:
        return MarketRSRepositoryInput(None, "REPOSITORY_V2_UNAVAILABLE", None, str(as_of))
    if market_code is None:
        return MarketRSRepositoryInput(None, "UNSUPPORTED_MARKET", None, str(as_of))
    start = benchmark_anchor_start(market_index_df, market_code=market_code, as_of=as_of)
    if start is None:
        return MarketRSRepositoryInput(None, "BENCHMARK_ANCHOR_UNAVAILABLE", None, str(as_of))
    try:
        daily = repository.get_daily(str(ticker).zfill(6), start, as_of)
    except Exception as exc:
        return MarketRSRepositoryInput(None, str(exc), start, str(as_of))
    if not isinstance(daily, pd.DataFrame) or daily.empty:
        return MarketRSRepositoryInput(None, "REPOSITORY_V2_EMPTY", start, str(as_of))
    if "close" not in daily.columns:
        return MarketRSRepositoryInput(None, "REPOSITORY_V2_CLOSE_MISSING", start, str(as_of))
    # The calculator expects a DatetimeIndex and a close column.  Keep all V2
    # columns intact for diagnostics; this is a view copy and never mutates the
    # canonical store.
    result = daily.copy()
    result.index = pd.DatetimeIndex(result.index).normalize()
    result.attrs["market_rs_input_authority"] = "MarketDataRepositoryV2"
    result.attrs["market_rs_requested_start"] = start
    result.attrs["market_rs_requested_end"] = str(as_of)
    return MarketRSRepositoryInput(result, None, start, str(as_of))


__all__ = [
    "MarketRSRepositoryInput",
    "benchmark_anchor_start",
    "resolve_market_rs_repository_input",
]
