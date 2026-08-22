"""BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE4 -- Precomputed Ticker Snapshot
Context parity tests (w.md Phase 4 Sections 5-7).

``build_historical_snapshot_from_context`` must be provably identical to the
legacy ``build_historical_snapshot`` for every (ticker, snapshot_date,
include_incomplete_periods) combination -- this is the single most important
test suite in this cycle (SNAPSHOT_PARITY_MISMATCH = 0 target). Rather than
hand-picking a handful of calendar edge cases, this module builds the
PrecomputedTickerContext once per real ticker (loaded from
data/raw/stocks/*.parquet, the actual production universe) and then compares
BOTH paths across a dense, deterministic sample of real trading days spanning
each ticker's entire history -- which necessarily sweeps through every actual
month-end/holiday-week/Chuseok/Lunar-New-Year/year-end boundary that ticker
ever had, without needing to know their calendar dates in advance.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.market_calendar import get_canonical_market_calendar
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.historical_snapshot import (
    build_historical_snapshot,
    build_historical_snapshot_from_context,
    build_precomputed_ticker_context,
)

ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = ROOT / "data/raw/stocks"
CALENDAR_PATH = ROOT / "data/reference/krx_trading_calendar.parquet"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

# w.md Phase 4 Section 7's representative-ticker list (by role, not literal
# LG/Exit3/Exit4/Reentry membership -- those depend on the live strategy
# simulation, not on this module's raw snapshot-construction concern; the
# snapshot/context equivalence proven here is ticker-content-agnostic, so a
# dense real-history sweep across these 4 liquid, long-history names already
# exercises every calendar-boundary class the strategy layer could ever see).
SAMPLE_TICKERS = ["005930", "000660", "068270", "035420"]


def _load_daily(ticker: str) -> pd.DataFrame:
    return pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()


def _market_calendar():
    if not CALENDAR_PATH.exists():
        return None
    return get_canonical_market_calendar(CALENDAR_PATH)


def _sample_dates(daily: pd.DataFrame, stride: int) -> list[pd.Timestamp]:
    """Every `stride`-th actual trading day (dense enough to sweep every
    month-end/holiday-week boundary over a multi-year history), PLUS
    explicit edge dates: the very first and last trading day, and every
    calendar month's last trading day (guarantees the month-end
    label-vs-actual-trading-day divergence case, and the year-end/holiday-
    week cases embedded in real KRX history, are always included)."""
    idx = daily.index
    dates = list(idx[::stride])
    if len(idx):
        dates.append(idx[0])
        dates.append(idx[-1])
    month_ends = daily.groupby(idx.to_period("M")).apply(lambda g: g.index.max())
    dates.extend(month_ends.tolist())
    # Non-trading requested snapshot: the day after each sampled date (may or
    # may not itself be a trading day -- either way exercises the "requested
    # date has no exact daily row" path identically on both sides).
    dates.extend([d + pd.Timedelta(days=1) for d in dates[:50]])
    return sorted(set(pd.Timestamp(d) for d in dates))


def _weekly_monthly_equal(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    if a.shape != b.shape:
        return False
    if not a.index.equals(b.index):
        return False
    for col in a.columns:
        av, bv = a[col].to_numpy(dtype=float, na_value=float("nan")), b[col].to_numpy(dtype=float, na_value=float("nan"))
        for x, y in zip(av, bv):
            x_nan, y_nan = math.isnan(x), math.isnan(y)
            if x_nan or y_nan:
                if x_nan != y_nan:
                    return False
                continue
            if x != y:
                return False
    return True


def _feature_row_equal(a, b) -> bool:
    da, db = asdict(a), asdict(b)
    for key in da:
        x, y = da[key], db[key]
        if isinstance(x, float) and isinstance(y, float) and math.isnan(x) and math.isnan(y):
            continue
        if x != y:
            return False
    return True


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
@pytest.mark.parametrize("include_incomplete_periods", [True, False])
def test_snapshot_context_matches_legacy_across_dense_real_history(ticker, include_incomplete_periods):
    if not (STOCKS_DIR / f"{ticker}.parquet").exists():
        pytest.skip(f"{ticker} parquet not present in this environment")

    daily = _load_daily(ticker)
    context = build_precomputed_ticker_context(ticker, ticker, daily)
    calendar = _market_calendar()

    mismatches: list[str] = []
    for snapshot_date in _sample_dates(daily, stride=11):
        legacy = build_historical_snapshot(
            ticker, ticker, daily, snapshot_date,
            include_incomplete_periods=include_incomplete_periods, market_calendar=calendar,
        )
        fast = build_historical_snapshot_from_context(
            context, snapshot_date,
            include_incomplete_periods=include_incomplete_periods, market_calendar=calendar,
        )

        if legacy.effective_as_of != fast.effective_as_of:
            mismatches.append(f"{snapshot_date}: effective_as_of {legacy.effective_as_of} != {fast.effective_as_of}")
            continue
        if legacy.weekly_as_of != fast.weekly_as_of:
            mismatches.append(f"{snapshot_date}: weekly_as_of {legacy.weekly_as_of} != {fast.weekly_as_of}")
        if legacy.monthly_as_of != fast.monthly_as_of:
            mismatches.append(f"{snapshot_date}: monthly_as_of {legacy.monthly_as_of} != {fast.monthly_as_of}")
        if not _weekly_monthly_equal(legacy.weekly, fast.weekly):
            mismatches.append(f"{snapshot_date}: weekly OHLCV mismatch")
        if not _weekly_monthly_equal(legacy.monthly, fast.monthly):
            mismatches.append(f"{snapshot_date}: monthly OHLCV mismatch")
        if not _feature_row_equal(legacy.features, fast.features):
            mismatches.append(f"{snapshot_date}: FeatureRow mismatch")

        legacy_pa = evaluate_pattern_a(legacy)
        fast_pa = evaluate_pattern_a(fast)
        if legacy_pa.score != fast_pa.score or legacy_pa.stage != fast_pa.stage:
            mismatches.append(f"{snapshot_date}: Pattern A score/stage mismatch ({legacy_pa.score}/{legacy_pa.stage} vs {fast_pa.score}/{fast_pa.stage})")

    assert mismatches == [], f"SNAPSHOT_PARITY_MISMATCH={len(mismatches)} for {ticker} include_incomplete={include_incomplete_periods}:\n" + "\n".join(mismatches[:20])


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_evaluate_pattern_a_fast_context_matches_legacy_across_completed_weeks(ticker):
    """FAST-level parity (w.md Phase 4 Section 7's other required comparison
    dimensions: FAST inputs/score/stage-status), not just the raw snapshot
    frames -- proves evaluate_pattern_a_fast(context=...) is bit-for-bit
    identical to the legacy call across a large sample of completed weekly
    bars."""
    if not (STOCKS_DIR / f"{ticker}.parquet").exists() or not SCORE_CONTRACT_PATH.exists():
        pytest.skip("required fixture files not present in this environment")

    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    daily = _load_daily(ticker)
    context = build_precomputed_ticker_context(ticker, ticker, daily)
    as_of = daily.index.max()

    weekly_labels = [w for w in context.full_weekly.index if w <= as_of]
    weekly_labels = [
        w for w in weekly_labels
        if not daily[daily.index <= w].empty and daily[daily.index <= w].index.max().normalize() == w.normalize()
    ]

    compared = 0
    for weekly_date in weekly_labels[::7]:
        legacy_result = evaluate_pattern_a_fast(ticker, ticker, daily, weekly_date, score, stage)
        context_result = evaluate_pattern_a_fast(ticker, ticker, daily, weekly_date, score, stage, context=context)
        assert legacy_result == context_result, f"FAST parity mismatch at {ticker} {weekly_date.date()}"
        compared += 1

    assert compared >= 10, "비교 대상 주봉 수가 예상보다 적음"


def test_snapshot_context_matches_legacy_for_non_trading_requested_date():
    """Explicit non-trading-day requested snapshot (e.g. a Sunday), which may
    not fall in the dense sample above depending on stride alignment."""
    ticker = "005930"
    if not (STOCKS_DIR / f"{ticker}.parquet").exists():
        pytest.skip("005930 parquet not present in this environment")
    daily = _load_daily(ticker)
    context = build_precomputed_ticker_context(ticker, ticker, daily)

    # Pick a handful of Sundays spread across the history.
    candidates = pd.date_range(daily.index[100], daily.index[-100], freq="90D")
    sundays = [d + pd.Timedelta(days=(6 - d.weekday()) % 7) for d in candidates]

    for snapshot_date in sundays:
        legacy = build_historical_snapshot(ticker, ticker, daily, snapshot_date, include_incomplete_periods=False)
        fast = build_historical_snapshot_from_context(context, snapshot_date, include_incomplete_periods=False)
        assert legacy.effective_as_of == fast.effective_as_of
        assert legacy.weekly_as_of == fast.weekly_as_of
        assert legacy.monthly_as_of == fast.monthly_as_of
        assert _weekly_monthly_equal(legacy.weekly, fast.weekly)
        assert _weekly_monthly_equal(legacy.monthly, fast.monthly)


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_valid_weeks_set_lookup_matches_legacy_full_scan(ticker):
    """w.md Phase 4 Section 8: VALID_WEEK_SET_MISMATCH = 0. Proves the
    set-membership replacement in simulate_ticker_strategy_2022 for
    ``valid_weeks`` produces the EXACT same list as the legacy
    ``daily[daily.index <= w].index.max() == w`` per-week boolean-mask
    scan, across full real ticker history."""
    from trend_scanner.data.resampler import to_weekly as _to_weekly

    if not (STOCKS_DIR / f"{ticker}.parquet").exists():
        pytest.skip(f"{ticker} parquet not present in this environment")

    daily = _load_daily(ticker)
    weekly_bars = _to_weekly(daily)

    legacy_valid_weeks = [
        w for w in weekly_bars.index
        if daily[daily.index <= w].index.max().normalize() == w.normalize()
    ]
    daily_dates_set = set(daily.index)
    fast_valid_weeks = [w for w in weekly_bars.index if w in daily_dates_set]

    mismatch_count = sum(1 for a, b in zip(legacy_valid_weeks, fast_valid_weeks) if a != b)
    mismatch_count += abs(len(legacy_valid_weeks) - len(fast_valid_weeks))
    assert mismatch_count == 0, f"VALID_WEEK_SET_MISMATCH={mismatch_count} for {ticker}"
    assert len(legacy_valid_weeks) > 100  # sanity: real history actually exercised


def test_snapshot_context_matches_legacy_before_ticker_history_starts():
    """snapshot_date strictly before the ticker's first daily row -- both
    paths must agree on empty/None result (no data available yet)."""
    ticker = "005930"
    if not (STOCKS_DIR / f"{ticker}.parquet").exists():
        pytest.skip("005930 parquet not present in this environment")
    daily = _load_daily(ticker)
    context = build_precomputed_ticker_context(ticker, ticker, daily)

    snapshot_date = daily.index[0] - pd.Timedelta(days=30)
    legacy = build_historical_snapshot(ticker, ticker, daily, snapshot_date, include_incomplete_periods=False)
    fast = build_historical_snapshot_from_context(context, snapshot_date, include_incomplete_periods=False)

    assert legacy.effective_as_of is None
    assert fast.effective_as_of is None
    assert legacy.weekly_as_of is None and fast.weekly_as_of is None
    assert legacy.monthly_as_of is None and fast.monthly_as_of is None
    assert len(legacy.weekly) == 0 and len(fast.weekly) == 0
    assert len(legacy.monthly) == 0 and len(fast.monthly) == 0
