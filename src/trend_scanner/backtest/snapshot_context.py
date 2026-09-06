"""Precomputed Ticker Snapshot Context -- performance-only module
(BACKTEST_PERFORMANCE_ENGINEERING_V01 Phase 4 / Phase 4.1 Major Fix 1).

This code originally lived inside
``trend_scanner.validation.historical_snapshot``, but that module's file
SHA256 is a frozen production identity under
``trend_scanner.validation.pattern_a_final_closure.EXPECTED_FROZEN_HASHES``
(Pattern A Final Production Closure Gate 7). Backtest performance
optimization is not a production semantics change, so rather than update
the frozen hash to accommodate it, this module was split out: nothing in
``historical_snapshot.py`` was touched, and its SHA256 is restored to the
exact byte-for-byte content it had before Phase 4
(``793014cbf434acadafcc59b1ae9fc50b59980178c1aeba71bc39d6d9f8a3d250``).

Everything below reuses the legacy module's ``HistoricalSnapshot``,
``build_feature_row``, ``_drop_incomplete_current_month``,
``_drop_incomplete_weekly`` verbatim -- no feature formula, Pattern A logic,
FAST contract logic, or weekly/monthly completion semantics is
reimplemented here. See ``build_historical_snapshot_from_context``'s
docstring for the reuse-vs-recompute correctness argument (unchanged from
Phase 4): a resample bucket's label is always its calendar upper boundary,
so label <= effective_as_of proves every day that could ever fall in that
bucket has already occurred at or before effective_as_of -- reuse cannot
leak a future day, regardless of calendar-label vs actual-last-trading-day
divergence. Proven parity-identical to the legacy path via
tests/test_backtest_performance_engine_v01_snapshot_context.py
(SNAPSHOT_PARITY_MISMATCH = 0).
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from typing import Callable

import pandas as pd

from trend_scanner.data.market_calendar import MarketCalendarAuthority, is_completed_market_month
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.validation.feature_report import build_feature_row
from trend_scanner.validation.historical_snapshot import (
    HistoricalSnapshot,
    _drop_incomplete_current_month,
    _drop_incomplete_weekly,
    _last_or_none,
)


@dataclass
class PrecomputedTickerContext:
    """One-per-ticker precomputed context that lets
    ``build_historical_snapshot_from_context`` avoid re-running
    ``to_weekly()``/``to_monthly()`` over the full history on every
    snapshot call.

    Deliberately NOT "resample once, slice by label" (forbidden -- see
    module docstring): ``full_weekly``/``full_monthly`` are resampled once,
    but only buckets whose LABEL is <= the snapshot's ``effective_as_of``
    are reused as-is. The bucket whose label is > effective_as_of (the
    still-in-progress "current" bucket, at most one such bucket per
    snapshot) is instead recomputed fresh from just the daily rows that
    belong to it, exactly reproducing what
    ``to_weekly(sliced)``/``to_monthly(sliced)`` would have computed for
    that same bucket.
    """

    ticker: str
    name: str
    daily: pd.DataFrame
    daily_dates: list[pd.Timestamp]
    full_weekly: pd.DataFrame
    full_monthly: pd.DataFrame
    weekly_labels: list[pd.Timestamp]
    monthly_labels: list[pd.Timestamp]

    def slice_daily_up_to(self, requested: pd.Timestamp) -> pd.DataFrame:
        """searchsorted-based equivalent of ``daily[daily.index <= requested]``
        (used by both snapshot construction and any other per-snapshot daily
        slicing, e.g. ``compute_daily_timing_features`` inputs, so callers
        never need to re-run the O(N) boolean-mask scan this context exists
        to avoid)."""
        _, pos = _effective_as_of_position(self, pd.Timestamp(requested))
        return self.daily.iloc[: pos + 1] if pos >= 0 else self.daily.iloc[0:0]

    # -- Cutoff-safe strategy views (w.md Phase 4.1 Section 8) --------------
    # These let a strategy entry point (simulate_ticker_strategy_2022) reuse
    # this ticker's ALREADY-precomputed sort/resample across all 4
    # Baseline/Julia x Primary/Sensitivity passes, instead of each pass
    # independently repeating `daily.sort_index()` / `to_weekly(daily)` /
    # `to_monthly(daily)`. Each view reuses the exact same tail-bucket-safe
    # reconstruction as `build_historical_snapshot_from_context` (the
    # underlying math doesn't care whether the boundary date is a per-week
    # snapshot `as_of` or a strategy `cutoff_date` -- both are "give me the
    # weekly/monthly frame as it would look with daily truncated to this
    # date", so reusing `_reconstruct_period_frame` here has already been
    # proven parity-safe by the snapshot parity tests), so a naive label
    # slice can never silently leak a not-yet-complete bucket past cutoff.

    def daily_up_to(self, cutoff_date: pd.Timestamp) -> pd.DataFrame:
        """Equivalent to ``daily.sort_index()[daily.index <= cutoff_date]``."""
        return self.slice_daily_up_to(cutoff_date)

    def weekly_up_to(self, cutoff_date: pd.Timestamp) -> pd.DataFrame:
        """Equivalent to ``to_weekly(daily[daily.index <= cutoff_date])``."""
        effective_as_of, _ = _effective_as_of_position(self, pd.Timestamp(cutoff_date))
        if effective_as_of is None:
            return self.full_weekly.iloc[0:0]
        return _reconstruct_period_frame(self.full_weekly, self.weekly_labels, self.daily, effective_as_of, to_weekly)

    def monthly_up_to(self, cutoff_date: pd.Timestamp) -> pd.DataFrame:
        """Equivalent to ``to_monthly(daily[daily.index <= cutoff_date])``."""
        effective_as_of, _ = _effective_as_of_position(self, pd.Timestamp(cutoff_date))
        if effective_as_of is None:
            return self.full_monthly.iloc[0:0]
        return _reconstruct_period_frame(self.full_monthly, self.monthly_labels, self.daily, effective_as_of, to_monthly)

    def valid_weeks_up_to(self, cutoff_date: pd.Timestamp, weekly_frame: pd.DataFrame | None = None) -> list[pd.Timestamp]:
        """Equivalent to the ``[w for w in to_weekly(daily_cutoff).index if
        w in set(daily_cutoff.index)]`` valid-week computation in
        ``simulate_ticker_strategy_2022`` (see that module's Phase 4
        VALID_WEEK_SET_MISMATCH=0 comment for why this set-membership form
        is equivalent to the legacy per-week boolean-mask-and-max check).

        ``weekly_frame`` (optional, w.md Phase 4.2 Section 13): pass the
        already-computed ``weekly_up_to(cutoff_date)`` result here to avoid
        reconstructing the same cutoff weekly frame twice when the caller
        already has it (as ``simulate_ticker_strategy_2022`` does). Omitted:
        reconstructs it internally, unchanged from before."""
        weekly = weekly_frame if weekly_frame is not None else self.weekly_up_to(cutoff_date)
        daily_cutoff_dates = set(self.daily_up_to(cutoff_date).index)
        return [w for w in weekly.index if w in daily_cutoff_dates]


def build_precomputed_ticker_context(ticker: str, name: str, daily: pd.DataFrame) -> PrecomputedTickerContext:
    """Builds the one-time-per-ticker precomputed context. Cheap to call
    repeatedly with the SAME daily frame (idempotent), but callers should
    build this once per ticker per process and reuse it across all
    snapshot dates for that ticker."""
    daily_sorted = daily.sort_index()
    full_weekly = to_weekly(daily_sorted)
    full_monthly = to_monthly(daily_sorted)
    return PrecomputedTickerContext(
        ticker=ticker,
        name=name,
        daily=daily_sorted,
        daily_dates=list(daily_sorted.index),
        full_weekly=full_weekly,
        full_monthly=full_monthly,
        weekly_labels=list(full_weekly.index),
        monthly_labels=list(full_monthly.index),
    )


def _effective_as_of_position(context: PrecomputedTickerContext, requested: pd.Timestamp) -> tuple[pd.Timestamp | None, int]:
    """Returns (effective_as_of, position) for the last daily date <=
    requested via bisect (searchsorted) over the precomputed sorted date
    list, or (None, -1) if no such date exists."""
    pos = bisect.bisect_right(context.daily_dates, requested) - 1
    if pos < 0:
        return None, -1
    return context.daily_dates[pos], pos


def _reconstruct_period_frame(
    full_frame: pd.DataFrame,
    labels: list[pd.Timestamp],
    daily: pd.DataFrame,
    effective_as_of: pd.Timestamp,
    resample_fn: Callable[[pd.DataFrame], pd.DataFrame],
    skip_incomplete_tail: bool = False,
) -> pd.DataFrame:
    """Reconstructs the weekly/monthly frame equivalent to
    ``resample_fn(daily[daily.index <= effective_as_of])`` by reusing
    precomputed buckets whose label <= effective_as_of and recomputing only
    the (at most one) tail bucket whose label is > effective_as_of."""
    safe_upto = bisect.bisect_right(labels, effective_as_of)
    safe_part = full_frame.iloc[:safe_upto]

    if safe_upto >= len(labels):
        return safe_part

    # When the caller will immediately drop an incomplete tail bucket, do not
    # resample that bucket just to throw it away.  This is exact for the
    # weekly path (the label is necessarily after ``effective_as_of``), and
    # callers must only set it for the monthly path after applying the same
    # calendar/request-date condition as ``_drop_incomplete_current_month``.
    if skip_incomplete_tail:
        return safe_part

    prev_boundary = labels[safe_upto - 1] if safe_upto > 0 else None
    if prev_boundary is None:
        tail_window = daily[daily.index <= effective_as_of]
    else:
        tail_window = daily[(daily.index > prev_boundary) & (daily.index <= effective_as_of)]

    if tail_window.empty:
        return safe_part

    tail_frame = resample_fn(tail_window)
    if tail_frame.empty:
        return safe_part
    return pd.concat([safe_part, tail_frame])


def build_historical_snapshot_from_context(
    context: PrecomputedTickerContext,
    snapshot_date: str | pd.Timestamp,
    include_incomplete_periods: bool = True,
    market_calendar: MarketCalendarAuthority | None = None,
) -> HistoricalSnapshot:
    """Optimized fast-path counterpart to
    ``trend_scanner.validation.historical_snapshot.build_historical_snapshot``.
    Reuses ``build_feature_row``, ``_drop_incomplete_current_month``,
    ``_drop_incomplete_weekly`` verbatim -- no feature formula, Pattern A
    logic, FAST contract logic, or weekly/monthly completion semantics is
    reimplemented here. Must remain provably parity-identical to
    ``build_historical_snapshot`` for the same
    (ticker, daily, snapshot_date, include_incomplete_periods)."""
    requested = pd.Timestamp(snapshot_date)
    effective_as_of, pos = _effective_as_of_position(context, requested)

    if effective_as_of is None:
        weekly = context.full_weekly.iloc[0:0]
        monthly = context.full_monthly.iloc[0:0]
    else:
        # ``_drop_incomplete_weekly`` always removes the one tail bucket whose
        # calendar label is after the last observed daily date.  Avoid its
        # resample entirely; completed buckets remain byte-for-byte identical.
        weekly = _reconstruct_period_frame(
            context.full_weekly,
            context.weekly_labels,
            context.daily,
            effective_as_of,
            to_weekly,
            skip_incomplete_tail=not include_incomplete_periods,
        )

        # Monthly completion is market-calendar based.  A ticker can be
        # halted before month-end while the market month is already complete;
        # in that case the tail must be reconstructed and retained.  Skip
        # only when the exact legacy drop helper would remove the tail.
        monthly_safe_upto = bisect.bisect_right(context.monthly_labels, effective_as_of)
        monthly_tail_label = (
            context.monthly_labels[monthly_safe_upto]
            if monthly_safe_upto < len(context.monthly_labels)
            else None
        )
        monthly_tail_is_incomplete = bool(
            not include_incomplete_periods
            and monthly_tail_label is not None
            and monthly_tail_label.year == requested.year
            and monthly_tail_label.month == requested.month
            and not is_completed_market_month(requested, calendar=market_calendar)
        )
        monthly = _reconstruct_period_frame(
            context.full_monthly,
            context.monthly_labels,
            context.daily,
            effective_as_of,
            to_monthly,
            skip_incomplete_tail=monthly_tail_is_incomplete,
        )

    if not include_incomplete_periods:
        monthly = _drop_incomplete_current_month(monthly, requested, market_calendar=market_calendar)
        weekly = _drop_incomplete_weekly(weekly, effective_as_of)

    sliced_daily = context.daily.iloc[: pos + 1] if pos >= 0 else context.daily.iloc[0:0]
    features = build_feature_row(context.ticker, context.name, sliced_daily, weekly, monthly)

    return HistoricalSnapshot(
        requested_snapshot_date=requested,
        effective_as_of=effective_as_of,
        include_incomplete_periods=include_incomplete_periods,
        monthly_as_of=_last_or_none(monthly),
        weekly_as_of=_last_or_none(weekly),
        features=features,
        monthly=monthly,
        weekly=weekly,
    )
