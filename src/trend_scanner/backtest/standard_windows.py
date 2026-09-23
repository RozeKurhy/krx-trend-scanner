"""Canonical date definitions and fail-closed resolution for standard backtest windows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from trend_scanner.data.market_calendar import MarketCalendarAuthority


@dataclass(frozen=True)
class StandardBacktestWindow:
    window_id: str
    name: str
    calendar_start: pd.Timestamp
    calendar_end: pd.Timestamp


@dataclass(frozen=True)
class ResolvedBacktestWindow:
    window: StandardBacktestWindow
    effective_start: pd.Timestamp
    effective_end: pd.Timestamp
    execution_support: pd.Timestamp


STANDARD_BACKTEST_WINDOWS: Mapping[str, StandardBacktestWindow] = {
    "P1": StandardBacktestWindow("P1", "Long History", pd.Timestamp("2014-01-01"), pd.Timestamp("2026-08-31")),
    "P2-1": StandardBacktestWindow("P2-1", "2021 Fixed", pd.Timestamp("2021-01-01"), pd.Timestamp("2025-05-31")),
    "P2-2": StandardBacktestWindow("P2-2", "2021 Full", pd.Timestamp("2021-01-01"), pd.Timestamp("2026-08-31")),
    "P3-1": StandardBacktestWindow("P3-1", "2022 Fixed", pd.Timestamp("2022-01-01"), pd.Timestamp("2025-05-31")),
    "P3-2": StandardBacktestWindow("P3-2", "2022 Full", pd.Timestamp("2022-01-01"), pd.Timestamp("2026-08-31")),
}


class StandardWindowResolutionError(RuntimeError):
    """A standard period cannot be resolved from the supplied calendar authority."""


def resolve_standard_backtest_window(
    window_id: str,
    calendar: MarketCalendarAuthority | None,
) -> ResolvedBacktestWindow:
    """Resolve calendar boundaries and the next session without extrapolation."""
    try:
        window = STANDARD_BACKTEST_WINDOWS[window_id]
    except KeyError as exc:
        raise StandardWindowResolutionError(f"UNKNOWN_STANDARD_WINDOW: {window_id}") from exc
    if calendar is None or len(calendar.trading_dates) == 0:
        raise StandardWindowResolutionError("ROLLING_MARKET_CALENDAR_UNAVAILABLE")

    dates = pd.DatetimeIndex(calendar.trading_dates).normalize()
    if dates.has_duplicates or not dates.is_monotonic_increasing:
        raise StandardWindowResolutionError("ROLLING_MARKET_CALENDAR_INVALID_ORDER")
    if calendar.min_date is None or calendar.min_date > window.calendar_start:
        raise StandardWindowResolutionError(
            f"CALENDAR_AUTHORITY_SHORT_OF_WINDOW_START: {window.window_id}: "
            f"required={window.calendar_start.date()} "
            f"available={calendar.min_date.date() if calendar.min_date is not None else None}"
        )

    certified_through = calendar.metadata.get("certified_through")
    coverage_end = calendar.max_observed_trading_date
    if coverage_end is None or coverage_end < window.calendar_end:
        raise StandardWindowResolutionError(
            f"CALENDAR_AUTHORITY_SHORT_OF_WINDOW_END: {window.window_id}: "
            f"required={window.calendar_end.date()} available={coverage_end.date() if coverage_end is not None else None}"
        )
    if certified_through is not None and pd.Timestamp(certified_through).normalize() < window.calendar_end:
        raise StandardWindowResolutionError(
            f"CALENDAR_CERTIFICATION_SHORT_OF_WINDOW_END: {window.window_id}: "
            f"required={window.calendar_end.date()} certified={pd.Timestamp(certified_through).date()}"
        )

    eligible_start = dates[dates >= window.calendar_start]
    eligible_end = dates[dates <= window.calendar_end]
    if len(eligible_start) == 0 or len(eligible_end) == 0:
        raise StandardWindowResolutionError(f"CALENDAR_BOUNDARY_UNRESOLVED: {window.window_id}")
    effective_start = eligible_start[0]
    effective_end = eligible_end[-1]
    end_index = int(dates.get_loc(effective_end))
    if end_index + 1 >= len(dates):
        raise StandardWindowResolutionError(f"NEXT_SESSION_UNAVAILABLE: {window.window_id}")
    execution_support = dates[end_index + 1]
    if certified_through is not None and execution_support > pd.Timestamp(certified_through).normalize():
        raise StandardWindowResolutionError(
            f"CALENDAR_CERTIFICATION_SHORT_OF_EXECUTION_SUPPORT: {window.window_id}: "
            f"required={execution_support.date()} certified={pd.Timestamp(certified_through).date()}"
        )
    return ResolvedBacktestWindow(window, effective_start, effective_end, execution_support)
