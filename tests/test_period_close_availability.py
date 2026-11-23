import pandas as pd
import pytest

from trend_scanner.backtest.snapshot_context import (
    build_historical_snapshot_from_context,
    build_precomputed_ticker_context,
)
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.data.period_close_availability import (
    PERIOD_CLOSE_AVAILABILITY, PeriodCloseCalendar, mask_unavailable_closes,
)
from trend_scanner.data.period_derivation import BLOCKED, derive_periods
from trend_scanner.data.repository_v2 import MarketDataRepositoryV2
from trend_scanner.data.repository_v2_loader import RepositoryV2DailyLoader
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_b_evaluator import evaluate_pattern_b
from trend_scanner.patterns.pattern_b_features_v01 import completed_bars
from trend_scanner.patterns.pattern_b_operational import HistorySegment, stitch_frames
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import monthly_alignment_decision
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (
    LifecyclePeriodCloseUnavailableError, _simulate_causal_lifecycle,
)


@pytest.fixture
def period_source(monkeypatch):
    dates = pd.bdate_range("2019-01-01", "2024-11-08")
    closes = pd.Series(range(100, 100 + len(dates)), index=dates, dtype=float)
    adjusted = pd.DataFrame({
        "open": closes - 1, "high": closes + 2, "low": closes - 2, "close": closes,
    })
    raw = adjusted.assign(volume=10, trading_value=closes * 10, market_cap=closes * 100, listed_shares=100)
    month_ends = dates.to_series().groupby(dates.to_period("M")).last().iloc[:-1]
    calendar = MarketCalendarAuthority(dates, list(month_ends))
    repository = MarketDataRepositoryV2(object(), object())
    monkeypatch.setattr(repository, "_load_adjusted", lambda ticker, start, end: adjusted.loc[start:end].copy())
    monkeypatch.setattr(repository, "_load_raw", lambda ticker, start, end: raw.loc[start:end].copy())
    monkeypatch.setattr(repository, "_period_calendar", PeriodCloseCalendar.from_market_calendar(calendar))
    return repository, adjusted, raw, calendar


@pytest.mark.parametrize("column, offset", [("high", -1), ("high", -100), ("low", 1)])
def test_active_excluded_month_end_cannot_supply_alignment_or_pattern_b(period_source, column, offset):
    repository, adjusted, _, _ = period_source
    day = pd.Timestamp("2024-10-31")
    adjusted.loc[day, column] = adjusted.loc[day, "close" if column == "high" else "open"] + offset
    dates = RepositoryV2DailyLoader(repository, start="2019-01-01", end="2024-11-08").load("000001")
    assert day not in dates.index
    assert monthly_alignment_decision(dates, "2024-11-08").reason_code == "REJECT_MA_UNAVAILABLE"
    assert evaluate_pattern_b("000001", dates, "2024-11-08").evaluation_status.value == "UNAVAILABLE"


def test_active_excluded_week_end_cannot_supply_pattern_b(period_source):
    repository, adjusted, _, _ = period_source
    day = pd.Timestamp("2024-10-25")
    adjusted.loc[day, "high"] = adjusted.loc[day, "close"] - 1
    dates = RepositoryV2DailyLoader(repository, start="2019-01-01", end="2024-11-08").load("000001")
    result = evaluate_pattern_b("000001", dates, "2024-11-08")
    assert result.evaluation_status.value == "UNAVAILABLE"
    assert result.range_52w is None


def test_unavailable_month_is_retained_in_both_window_consumers(period_source):
    repository, adjusted, raw, calendar = period_source
    month = pd.Timestamp("2024-10-31")
    missing = adjusted.index[(adjusted.index.month == 10) & (adjusted.index.year == 2024) & (adjusted.index < month)]
    adjusted.drop(missing, inplace=True)
    raw.drop(missing, inplace=True)
    adjusted.loc[month, "high"] = adjusted.loc[month, "close"] - 1
    daily = RepositoryV2DailyLoader(repository, start="2019-01-01", end="2024-11-08").load("000001")
    context = build_precomputed_ticker_context("000001", "Fixture", daily)
    as_of = pd.Timestamp("2024-11-08")
    snapshot = build_historical_snapshot_from_context(context, as_of, False, market_calendar=calendar)
    assert month in snapshot.monthly.index
    assert snapshot.monthly.loc[month].isna().all()
    assert evaluate_pattern_a(snapshot).score is None
    assert evaluate_pattern_a(snapshot).stage is None
    result = mask_unavailable_closes(
        completed_bars(daily, pd.offsets.MonthEnd(), as_of), context.period_closes.monthly, as_of,
    )
    assert result.index[-1] == month
    assert result.loc[month].isna().all()


@pytest.mark.parametrize("nontrading", [False, True])
def test_normal_month_end_and_confirmed_suspension_keep_valid_observations(period_source, nontrading):
    repository, adjusted, raw, calendar = period_source
    month = pd.Timestamp("2024-10-31")
    if nontrading:
        raw.loc[month, ["open", "high", "low", "volume", "trading_value"]] = 0
    daily = RepositoryV2DailyLoader(repository, start="2019-01-01", end="2024-11-08").load("000001")
    availability = daily.attrs[PERIOD_CLOSE_AVAILABILITY]
    assert availability.monthly == ()
    context = build_precomputed_ticker_context("000001", "Fixture", daily)
    actual = adjusted.index[adjusted.index < month][-1] if nontrading else month
    assert context.monthly_up_to(pd.Timestamp("2024-11-08")).loc[month, "close"] == adjusted.loc[actual, "close"]
    assert monthly_alignment_decision(daily, "2024-11-08").allowed
    assert evaluate_pattern_b("000001", daily, "2024-11-08").evaluation_status.value == "READY"


def test_holiday_and_weekend_labels_record_the_actual_trading_date(period_source, monkeypatch):
    repository, adjusted, raw, calendar = period_source
    holiday = pd.Timestamp("2024-08-30")
    actual = pd.Timestamp("2024-08-29")
    adjusted.drop(holiday, inplace=True)
    raw.drop(holiday, inplace=True)
    adjusted.loc[actual, "high"] = adjusted.loc[actual, "close"] - 1
    dates = calendar.trading_dates.drop(holiday)
    month_ends = [actual if end == holiday else end for end in calendar.get_month_ends()]
    closed_calendar = MarketCalendarAuthority(dates, month_ends)
    monkeypatch.setattr(repository, "_period_calendar", PeriodCloseCalendar.from_market_calendar(closed_calendar))
    daily = RepositoryV2DailyLoader(repository, start="2019-01-01", end="2024-08-29").load("000001")
    gaps = daily.attrs[PERIOD_CLOSE_AVAILABILITY]
    assert [(g.label, g.session) for g in gaps.monthly] == [(pd.Timestamp("2024-08-31"), actual)]
    assert [(g.label, g.session) for g in gaps.weekly] == [(holiday, actual)]
    derived = derive_periods(daily, actual, closed_calendar)
    assert derived.final_status == BLOCKED
    assert derived.monthly.loc[pd.Timestamp("2024-08-31")].isna().all()
    assert derived.weekly.loc[holiday].isna().all()


def test_missing_raw_and_adjusted_on_a_certified_pit_session_is_unknown(period_source):
    repository, adjusted, raw, _ = period_source
    missing = pd.Timestamp("2024-10-31")
    adjusted.drop(missing, inplace=True)
    raw.drop(missing, inplace=True)
    daily = RepositoryV2DailyLoader(repository, start="2019-01-01", end="2024-11-08").load("000001")
    gap, = daily.attrs[PERIOD_CLOSE_AVAILABILITY].monthly
    assert (gap.session, gap.reason, gap.raw_activity) == (missing, "RAW_SESSION_MISSING", "UNKNOWN")
    assert monthly_alignment_decision(daily, "2024-11-08").reason_code == "REJECT_MA_UNAVAILABLE"
    narrowed = RepositoryV2DailyLoader(repository, start="2024-11-01", end="2024-11-08").load("000001")
    assert narrowed.attrs[PERIOD_CLOSE_AVAILABILITY].monthly == ()


def test_future_exclusion_does_not_affect_an_earlier_evaluation(period_source):
    repository, adjusted, _, calendar = period_source
    future = pd.Timestamp("2024-11-08")
    adjusted.loc[future, "high"] = adjusted.loc[future, "close"] - 1
    before = pd.Timestamp("2024-11-01")
    narrow = RepositoryV2DailyLoader(repository, start="2019-01-01", end=before).load("000001")
    broad = RepositoryV2DailyLoader(repository, start="2019-01-01", end=future).load("000001")
    assert narrow.attrs[PERIOD_CLOSE_AVAILABILITY].weekly == ()
    assert broad.attrs[PERIOD_CLOSE_AVAILABILITY].weekly[-1].session == future
    assert monthly_alignment_decision(narrow, before) == monthly_alignment_decision(broad, before)
    assert evaluate_pattern_b("000001", narrow, before) == evaluate_pattern_b("000001", broad, before)
    assert monthly_alignment_decision(broad, future).details["cause"] == "SIGNAL_DATE_CLOSE_MISSING_OR_DUPLICATED"
    context = build_precomputed_ticker_context("000001", "Fixture", broad)
    snapshot = build_historical_snapshot_from_context(context, before, False, market_calendar=calendar)
    assert snapshot.weekly.index.max() == before


def test_pit_stitch_keeps_the_earlier_components_gap(period_source):
    repository, adjusted, _, _ = period_source
    day = pd.Timestamp("2024-10-31")
    adjusted.loc[day, "high"] = adjusted.loc[day, "close"] - 1
    first = RepositoryV2DailyLoader(repository, start="2019-01-01", end=day).load("000001")
    second = RepositoryV2DailyLoader(repository, start="2024-11-01", end="2024-11-08").load("000001")
    isu_cd = "KR7000001000"
    joined = stitch_frames([
        (HistorySegment("KOSDAQ", isu_cd, "2019-01-01", "2024-10-31"), first),
        (HistorySegment("KOSPI", isu_cd, "2024-11-01", "2024-11-08"), second),
    ], "2024-11-08")
    result = evaluate_pattern_b("000001", joined, "2024-11-08")
    assert result.evaluation_status.value == "UNAVAILABLE"
    assert result.monthly_last_bar == "2024-10-31"
    assert any("2024-10-31" in reason and "ADJUSTED_OHLC_INVALID" in reason for reason in result.reason_details)


def test_open_position_cannot_skip_an_unavailable_stage_into_an_exit():
    observed = [
        {"date": "2024-09-30", "stage": "PROGRESSED", "score": 60},
        {"date": "2024-10-31", "stage": "UNAVAILABLE",
         "period_close_unavailable": ("2024-10-31 ADJUSTED_OHLC_INVALID",)},
        {"date": "2024-11-30", "stage": "WEAK", "score": 30},
    ]
    with pytest.raises(LifecyclePeriodCloseUnavailableError, match="2024-10-31"):
        _simulate_causal_lifecycle(observed, "EARLY_TREND")
    result = _simulate_causal_lifecycle(observed, "EARLY_TREND", stop_date=pd.Timestamp("2024-10-30"))
    assert result["exit_signal_date"] is None
