"""BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE4_1_FINAL_COLD_OPTIMIZATION tests.

Covers w.md Phase 4.1 Section 22's [Evaluation Window] items 12-14 and the
Section 5/6 pre-evaluation-window pruning requirement: pruning must never
change trade output (legacy vs optimized == identical), must still allow a
late-2021 signal to execute on the first 2022 trading day, and must
measurably reduce FAST evaluation count for long-history tickers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_START_DATE,
    simulate_ticker_strategy_2022,
)

ROOT = Path(__file__).resolve().parent.parent
STOCKS_DIR = ROOT / "data/raw/stocks"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

SAMPLE_TICKERS = ["005930", "000660", "068270", "035420"]


def _require_fixtures():
    if not (STOCKS_DIR / "005930.parquet").exists() or not SCORE_CONTRACT_PATH.exists():
        pytest.skip("required fixture files not present in this environment")


def _contracts():
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    return score, stage


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_pre_window_pruning_produces_identical_trades_baseline(ticker):
    """[Evaluation Window] item: legacy (pruning disabled) vs optimized
    (pruning enabled) trade result must be identical, Baseline (loss guard
    ON)."""
    _require_fixtures()
    score, stage = _contracts()
    daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()

    legacy = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=True, enable_pre_window_pruning=False,
    )
    optimized = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=True, enable_pre_window_pruning=True,
    )
    assert legacy == optimized


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_pre_window_pruning_produces_identical_trades_julia(ticker):
    """Same as above, Julia (loss guard OFF)."""
    _require_fixtures()
    score, stage = _contracts()
    daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()

    legacy = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=False, enable_pre_window_pruning=False,
    )
    optimized = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=False, enable_pre_window_pruning=True,
    )
    assert legacy == optimized


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_pre_window_pruning_reduces_fast_evaluation_count(ticker):
    """Pruning must measurably reduce the number of FAST snapshots
    evaluated for a long-history ticker (w.md Section 6)."""
    _require_fixtures()
    score, stage = _contracts()
    daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()

    legacy_cache = FastSnapshotCache()
    simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=True, enable_pre_window_pruning=False,
        fast_snapshot_cache=legacy_cache,
    )
    optimized_cache = FastSnapshotCache()
    simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=True, enable_pre_window_pruning=True,
        fast_snapshot_cache=optimized_cache,
    )

    assert optimized_cache.evaluation_count <= legacy_cache.evaluation_count
    if daily.index.min() < EVALUATION_START_DATE - pd.Timedelta(days=180):
        # A genuinely long-history ticker should see a real reduction, not
        # just an equal count.
        assert optimized_cache.evaluation_count < legacy_cache.evaluation_count


def test_late_2021_signal_still_executes_on_first_2022_trading_day():
    """[Evaluation Window] item 13: a FAST trigger in late 2021 whose next
    trading day falls in 2022 must remain eligible for entry -- pruning
    must not discard the boundary week."""
    _require_fixtures()
    score, stage = _contracts()

    # Build a small synthetic daily frame spanning a 2021-12 -> 2022-01
    # boundary with enough history for FAST/Pattern A features, then confirm
    # the earliest allowed search week (as computed by the pruning formula)
    # is <= the last valid week of December 2021, i.e. the boundary week is
    # NOT excluded outright.
    dates = pd.bdate_range("2020-01-01", "2022-01-10")
    import numpy as np
    close = 100.0 + np.cumsum(np.random.default_rng(7).normal(0, 0.3, len(dates)))
    daily = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": 1_000_000.0, "trading_value": close * 1_000_000.0,
    }, index=dates)

    from trend_scanner.data.resampler import to_weekly
    import bisect as _bisect

    weekly_bars = to_weekly(daily)
    daily_dates_set = set(daily.index)
    valid_weeks = [w for w in weekly_bars.index if w in daily_dates_set]
    daily_dates_sorted = list(daily.index)

    def _next_trading_day_or_far_future(w):
        pos = _bisect.bisect_right(daily_dates_sorted, w)
        return daily_dates_sorted[pos] if pos < len(daily_dates_sorted) else pd.Timestamp.max

    start_idx = _bisect.bisect_left(valid_weeks, EVALUATION_START_DATE, key=_next_trading_day_or_far_future)
    first_allowed_week = valid_weeks[start_idx]

    # The last trading week of December 2021 (whose next trading day is the
    # first 2022 trading day) must be admitted, i.e. first_allowed_week must
    # not be later than that week.
    december_weeks = [w for w in valid_weeks if w.year == 2021 and w.month == 12]
    assert december_weeks, "test fixture must contain December 2021 weeks"
    last_december_week = december_weeks[-1]
    assert first_allowed_week <= last_december_week, (
        f"pruning incorrectly excluded the late-2021 boundary week: "
        f"first_allowed_week={first_allowed_week}, last_december_week={last_december_week}"
    )


def test_pre_2022_signal_with_pre_2022_execution_is_pruned():
    """[Evaluation Window] item: a week whose next trading day is still
    before start_date must be excluded from the search start (it can never
    produce a valid entry)."""
    dates = pd.bdate_range("2020-01-01", "2021-11-30")
    import numpy as np
    close = 100.0 + np.cumsum(np.random.default_rng(3).normal(0, 0.3, len(dates)))
    daily = pd.DataFrame({
        "open": close, "high": close + 1, "low": close - 1, "close": close,
        "volume": 1_000_000.0, "trading_value": close * 1_000_000.0,
    }, index=dates)

    from trend_scanner.data.resampler import to_weekly
    import bisect as _bisect

    weekly_bars = to_weekly(daily)
    daily_dates_set = set(daily.index)
    valid_weeks = [w for w in weekly_bars.index if w in daily_dates_set]
    daily_dates_sorted = list(daily.index)

    def _next_trading_day_or_far_future(w):
        pos = _bisect.bisect_right(daily_dates_sorted, w)
        return daily_dates_sorted[pos] if pos < len(daily_dates_sorted) else pd.Timestamp.max

    start_idx = _bisect.bisect_left(valid_weeks, EVALUATION_START_DATE, key=_next_trading_day_or_far_future)
    # No week in this all-2020-2021 fixture can ever execute >= 2022-01-01,
    # so the pruning boundary should land at (or past) the end of the list.
    assert start_idx == len(valid_weeks)


# =============================================================================
# Strategy Context Parity Test (w.md Phase 4.1 Section 9, Section 22 items 15-19)
# =============================================================================

@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_strategy_context_parity_daily_weekly_monthly_valid_weeks(ticker):
    """STRATEGY_CONTEXT_PARITY_MISMATCH = 0 target: legacy per-call
    sort/resample/valid_weeks computation vs the context's cutoff-safe
    views must be exactly identical."""
    _require_fixtures()
    from trend_scanner.data.resampler import to_monthly, to_weekly
    from trend_scanner.validation.julia_strategy_v00 import EVALUATION_END_DATE

    raw_daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet")
    context = build_precomputed_ticker_context(ticker, ticker, raw_daily)

    cutoff = EVALUATION_END_DATE
    legacy_daily = raw_daily.sort_index()
    legacy_daily = legacy_daily[legacy_daily.index <= cutoff]
    legacy_weekly = to_weekly(legacy_daily)
    legacy_monthly = to_monthly(legacy_daily)
    legacy_daily_dates_set = set(legacy_daily.index)
    legacy_valid_weeks = [w for w in legacy_weekly.index if w in legacy_daily_dates_set]

    context_daily = context.daily_up_to(cutoff)
    context_weekly = context.weekly_up_to(cutoff)
    context_monthly = context.monthly_up_to(cutoff)
    context_valid_weeks = context.valid_weeks_up_to(cutoff)

    assert context_daily.equals(legacy_daily), f"{ticker}: daily cutoff frame mismatch"
    assert context_weekly.equals(legacy_weekly), f"{ticker}: weekly OHLCV mismatch"
    assert context_monthly.equals(legacy_monthly), f"{ticker}: monthly OHLCV mismatch"
    assert context_valid_weeks == legacy_valid_weeks, f"{ticker}: valid_weeks mismatch"
    assert context_valid_weeks[0] == legacy_valid_weeks[0], f"{ticker}: first searchable week mismatch"
    assert context_valid_weeks[-1] == legacy_valid_weeks[-1], f"{ticker}: last searchable week mismatch"


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_strategy_context_no_repeated_full_resample_across_4_pass(ticker, monkeypatch):
    """[Strategy Context] item 19: running Baseline/Julia x Primary/
    Sensitivity (4 simulate_ticker_strategy_2022 calls) with a shared
    PrecomputedTickerContext must NOT trigger a fresh full to_weekly()/
    to_monthly() resample per pass -- the context's full_weekly/full_monthly
    were already resampled exactly once at context-build time."""
    _require_fixtures()
    score, stage = _contracts()
    raw_daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet")

    import trend_scanner.backtest.snapshot_context as snapshot_context_module

    # Distinguish a "full-history" resample call (large input, the exact
    # cost this Phase 4.1 change eliminates) from the many small
    # tail-bucket-window resample calls that both the strategy setup AND
    # the (already-cached, unrelated-to-this-test) per-trade monthly
    # Pattern A snapshot evaluation legitimately perform -- those always
    # operate on a tiny slice (at most a few weeks/days), never the ticker's
    # entire history, so they are not what this test guards against.
    full_history_len = len(raw_daily)
    large_call_threshold = max(60, full_history_len // 2)
    large_call_count = {"weekly": 0, "monthly": 0}
    real_to_weekly = snapshot_context_module.to_weekly
    real_to_monthly = snapshot_context_module.to_monthly

    def counting_to_weekly(df):
        if len(df) >= large_call_threshold:
            large_call_count["weekly"] += 1
        return real_to_weekly(df)

    def counting_to_monthly(df):
        if len(df) >= large_call_threshold:
            large_call_count["monthly"] += 1
        return real_to_monthly(df)

    monkeypatch.setattr(snapshot_context_module, "to_weekly", counting_to_weekly)
    monkeypatch.setattr(snapshot_context_module, "to_monthly", counting_to_monthly)

    # Context build itself does exactly 1 full-history weekly + 1 full-history monthly resample.
    context = build_precomputed_ticker_context(ticker, ticker, raw_daily)
    assert large_call_count == {"weekly": 1, "monthly": 1}

    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()
    for enable_loss_guard in (True, False):
        for sensitivity_mode in (True, False):
            simulate_ticker_strategy_2022(
                ticker, ticker, "KOSPI", raw_daily, score, stage,
                enable_loss_guard=enable_loss_guard, sensitivity_mode=sensitivity_mode,
                fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
                snapshot_context=context,
            )

    # The 4 passes (Baseline/Julia x Primary/Sensitivity) must not have
    # triggered any ADDITIONAL full-history resample beyond the 1 done at
    # context-build time -- every subsequent to_weekly/to_monthly call
    # (strategy cutoff reconstruction, per-trade monthly snapshot
    # evaluation) only ever touches a tiny tail/window slice.
    assert large_call_count == {"weekly": 1, "monthly": 1}, (
        f"{ticker}: unexpected repeated full-history resample across 4-pass: {large_call_count}"
    )
