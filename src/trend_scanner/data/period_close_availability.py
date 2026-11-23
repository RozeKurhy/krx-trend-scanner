"""Price availability at certified exchange week and month ends."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import pandas as pd

from trend_scanner.data.market_calendar import MarketCalendarAuthority

PERIOD_CLOSE_AVAILABILITY = "period_close_availability"


@dataclass(frozen=True)
class UnavailableClose:
    label: pd.Timestamp
    session: pd.Timestamp
    reason: str
    raw_activity: str

    def __str__(self) -> str:
        return f"{self.label.date()} ({self.session.date()}: {self.reason}, {self.raw_activity})"


@dataclass(frozen=True)
class PeriodCloseAvailability:
    """Sparse gaps, scoped to the repository read's PIT identity and dates."""

    certified_months: frozenset[pd.Period]
    monthly: tuple[UnavailableClose, ...]
    weekly: tuple[UnavailableClose, ...]
    calendar_available: bool = True

    def __deepcopy__(self, memo):
        # Shared certificate and immutable gaps; pandas may copy attrs per column.
        return self

    @classmethod
    def stitch(cls, segments: list[PeriodCloseAvailability]) -> PeriodCloseAvailability:
        months = segments[0].certified_months
        if any(segment.certified_months != months for segment in segments):
            raise ValueError("PERIOD_CLOSE_CALENDAR_MISMATCH")
        return cls(
            months,
            tuple(gap for segment in segments for gap in segment.monthly),
            tuple(gap for segment in segments for gap in segment.weekly),
            all(segment.calendar_available for segment in segments),
        )


@dataclass(frozen=True)
class PeriodCloseCalendar:
    """Actual last market sessions, indexed by period label for one calendar."""

    monthly: pd.Series
    weekly: pd.Series
    certified_months: frozenset[pd.Period]
    calendar_available: bool

    @classmethod
    def from_market_calendar(cls, calendar: MarketCalendarAuthority) -> PeriodCloseCalendar:
        sessions = calendar.trading_dates
        month_ends = pd.DatetimeIndex(calendar.get_month_ends())
        months = month_ends.to_period("M")
        week_labels = sessions.to_period("W-FRI").to_timestamp(how="end").normalize()
        weeks = sessions.to_series(index=week_labels).groupby(level=0).last()
        certified_through = calendar.metadata.get("certified_through") or calendar.max_observed_trading_date
        return cls(
            month_ends.to_series(index=months.to_timestamp(how="end").normalize()),
            weeks.loc[:pd.Timestamp(certified_through)] if certified_through is not None else weeks.iloc[:0],
            frozenset(months),
            not sessions.empty,
        )

    def availability(
        self,
        start: pd.Timestamp,
        end: pd.Timestamp,
        raw: pd.DataFrame,
        adjusted_dates: pd.DatetimeIndex,
        exclusions: Mapping[str, list[str]],
        outside_lifecycle: list[str],
    ) -> PeriodCloseAvailability:
        exclusion_reasons = {
            session: reason for reason, dates in exclusions.items() for session in dates
        }

        def find_gaps(periods: pd.Series) -> tuple[UnavailableClose, ...]:
            relevant = periods.loc[periods.between(start, end) & ~periods.isin(pd.to_datetime(outside_lifecycle))]
            session_dates = pd.DatetimeIndex(relevant)
            activity = raw[["volume", "trading_value"]].reindex(session_dates)
            traded = activity.gt(0).all(axis=1)
            nontrading = activity.eq(0).all(axis=1)
            priced = session_dates.isin(adjusted_dates)
            gaps = []
            for label, session in relevant.loc[~((traded & priced) | nontrading).to_numpy()].items():
                if session not in raw.index:
                    reason, raw_activity = "RAW_SESSION_MISSING", "UNKNOWN"
                elif not traded.loc[session]:
                    reason, raw_activity = "RAW_ACTIVITY_UNCONFIRMED", "UNKNOWN"
                else:
                    reason = exclusion_reasons.get(session.date().isoformat(), "ADJUSTED_CLOSE_MISSING")
                    raw_activity = "TRADED"
                gaps.append(UnavailableClose(label, session, reason, raw_activity))
            return tuple(gaps)

        return PeriodCloseAvailability(
            self.certified_months, find_gaps(self.monthly), find_gaps(self.weekly), self.calendar_available,
        )


def mask_unavailable_closes(
    bars: pd.DataFrame,
    gaps: tuple[UnavailableClose, ...],
    as_of: pd.Timestamp,
    *,
    completed_labels_only: bool = False,
) -> pd.DataFrame:
    """Keep each unavailable period's slot with missing OHLCV, even if no rows survived."""
    labels = pd.DatetimeIndex([
        gap.label for gap in gaps
        if gap.session <= as_of and (not completed_labels_only or gap.label <= as_of)
    ])
    if labels.empty:
        return bars
    result = bars.reindex(bars.index.union(labels))
    result.loc[labels] = float("nan")
    return result


def gaps_in_window(
    bars: pd.DataFrame,
    gaps: tuple[UnavailableClose, ...],
    as_of: pd.Timestamp,
    window: int,
) -> tuple[UnavailableClose, ...]:
    labels = bars.index[-window:]
    return tuple(gap for gap in gaps if gap.session <= as_of and gap.label in labels)
