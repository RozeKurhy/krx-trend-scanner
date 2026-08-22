"""Ticker-level in-memory data cache (BACKTEST_PERFORMANCE_ENGINEERING_V01, Priority 1).

``ParquetCache.load(ticker)`` performs a full disk read on every call with no
memory layer. Several call sites (the 2022+ backtest simulation loop, the
proxy market-cap registry's internal price lookups, and the proxy validation
loop) each independently call ``.load(ticker)`` for the same ticker multiple
times within a single script run.

``TickerDataCache`` is a drop-in replacement for ``ParquetCache`` (same
``.load(ticker) -> DataFrame | None`` contract, same returned content) that
adds a memory layer: first request per ticker reads from disk, every
subsequent request for the same ticker returns the identical in-memory
DataFrame.

This module deliberately does NOT cache ``to_weekly``/``to_monthly``
full-history resamples. ``simulate_ticker_strategy_2022`` resamples
``daily[daily.index <= cutoff_date]`` (a cutoff-bounded slice, not the raw
full-history frame), and ``build_historical_snapshot`` resamples
``daily[daily.index <= m]`` per reference date with
``_drop_incomplete_current_month``/``_drop_incomplete_weekly`` boundary
logic applied afterward. A full-history resample sliced by label
(``full_monthly[full_monthly.index <= m]``) is NOT guaranteed equal to
resampling only the cutoff/reference-date-bounded slice, because monthly
labels are calendar month-ends while trading data ends on the last trading
day of the month -- when those differ (most months), label-based slicing
and completed-period trimming can disagree on which bucket is "complete".
Wiring in a full-history resample cache here would risk silently diverging
from the existing per-call resample it would replace. See
``docs/architecture/backtest_performance_engine_v01.md`` Section 12 (Known
Limitations) for the deferred Phase 4 candidate this represents.

No strategy semantics, filter logic, or PIT rule is implemented here --
this module only removes repeated disk IO of an otherwise-identical input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from trend_scanner.data.cache import ParquetCache


@dataclass
class TickerDataCache:
    """In-memory memoizing wrapper around ``ParquetCache``.

    Duck-type compatible with ``ParquetCache`` for ``.load(ticker)`` so it
    can be passed anywhere a ``ParquetCache`` is currently accepted (e.g.
    ``ProxyHistoricalMarketCapRegistry(cache=...)``) without changing any
    call-site logic.
    """

    base_dir: Path | str = Path("data/raw/stocks")
    _cache: ParquetCache = field(init=False, repr=False)
    _daily: dict[str, pd.DataFrame | None] = field(default_factory=dict, repr=False)

    disk_read_count: int = field(default=0, repr=False)
    memory_hit_count: int = field(default=0, repr=False)
    memory_miss_count: int = field(default=0, repr=False)

    def __post_init__(self) -> None:
        self._cache = ParquetCache(base_dir=self.base_dir)

    def load(self, ticker: str) -> pd.DataFrame | None:
        if ticker in self._daily:
            self.memory_hit_count += 1
            return self._daily[ticker]
        self.memory_miss_count += 1
        self.disk_read_count += 1
        df = self._cache.load(ticker)
        self._daily[ticker] = df
        return df

    def diagnostics(self) -> dict[str, int]:
        return {
            "unique_tickers_loaded": len(self._daily),
            "disk_read_count": self.disk_read_count,
            "memory_hit_count": self.memory_hit_count,
            "memory_miss_count": self.memory_miss_count,
        }
