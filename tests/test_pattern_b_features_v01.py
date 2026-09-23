"""Pattern B Feature Contract V01 — synthetic fixtures only (no real ticker data)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from trend_scanner.patterns import pattern_b_features_v01 as pb


def _frame(dates, close, high=None, low=None) -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    high = close * 1.01 if high is None else np.asarray(high, dtype=float)
    low = close * 0.99 if low is None else np.asarray(low, dtype=float)
    return pd.DataFrame(
        {"open": close, "high": high, "low": low, "close": close},
        index=pd.DatetimeIndex(dates),
    )


def _monthly_rows(n: int, close, high=None, low=None, start="2015-01-01") -> pd.DataFrame:
    """One session per month on the 15th, so each completed month equals that row."""
    return _frame(pd.date_range(start, periods=n, freq="MS") + pd.Timedelta(days=14), close, high, low)


def _weekly_rows(n: int, close, high=None, low=None, start="2020-01-01") -> pd.DataFrame:
    """One session per week on Wednesday, so each completed W-FRI week equals that row."""
    return _frame(pd.date_range(start, periods=n, freq="W-WED"), close, high, low)


def _daily(start="2012-01-02", end="2025-12-31", seed=7) -> pd.DataFrame:
    dates = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, len(dates))))
    return _frame(dates, close)


def _values(result: pb.PatternBFeaturesV01) -> dict:
    return {name: (fv.value, fv.status) for name, fv in result.features.items()}


# --- PIT ---------------------------------------------------------------------

def test_future_rows_do_not_change_result():
    as_of = "2024-10-15"
    base = pb.compute_pattern_b_features_v01(_daily(end=as_of), as_of)
    extended = _daily(end="2025-12-31")
    extended.loc["2025-06-02":, "close"] = np.nan  # invalid future rows must be ignored
    later = pb.compute_pattern_b_features_v01(extended, as_of)
    assert _values(base) == _values(later)
    assert all(fv.status == pb.STATUS_OK for fv in base.features.values())


def test_in_progress_month_and_week_are_excluded():
    result = pb.compute_pattern_b_features_v01(_daily(), "2024-10-15")  # Tuesday, mid-month
    assert result.monthly_last_bar == pd.Timestamp("2024-09-30")
    assert result.weekly_last_bar == pd.Timestamp("2024-10-11")


def test_period_ending_on_as_of_is_completed():
    result = pb.compute_pattern_b_features_v01(_daily(), "2023-06-30")  # Friday, month end
    assert result.monthly_last_bar == pd.Timestamp("2023-06-30")
    assert result.weekly_last_bar == pd.Timestamp("2023-06-30")


def test_percentile_reference_excludes_current_observation():
    # Accelerating growth: every 12M return exceeds all earlier ones.
    n = 60
    close = 100 * np.exp(0.001 * np.arange(n) ** 2)
    result = pb.compute_pattern_b_features_v01(_monthly_rows(n, close), "2019-12-31")
    fv = result.features[pb.RETURN_12M_PERCENTILE]
    assert fv.status == pb.STATUS_OK
    assert fv.value == 100.0  # would be below 100 if the current return were in the reference


# --- Formula -----------------------------------------------------------------

def test_monthly_formulas():
    n = 40
    close = np.linspace(100, 139, n)
    high = close + 5
    low = close - 5
    high[10] = 300  # inside the last 36 bars (index 4..39)
    low[3] = 1  # outside the last 36 bars
    result = pb.compute_pattern_b_features_v01(_monthly_rows(n, close, high, low), "2018-04-30")
    assert result.monthly_bar_count == n
    c = close[-1]
    l36, h36 = low[-36:].min(), high[-36:].max()
    assert result.features[pb.RANGE_POSITION_36M].value == pytest.approx((c - l36) / (h36 - l36))
    assert result.features[pb.MONTHLY_MA24_DISTANCE].value == pytest.approx(c / close[-24:].mean() - 1)
    assert result.features[pb.HIGH_DRAWDOWN_36M].value == pytest.approx(c / 300 - 1)


def test_weekly_formulas():
    n = 60
    close = np.linspace(50, 109, n)
    high = close + 1
    low = close - 1
    low[20] = 10  # inside the last 52 bars (index 8..59)
    result = pb.compute_pattern_b_features_v01(_weekly_rows(n, close, high, low), "2021-02-19")
    assert result.weekly_bar_count == n
    c = close[-1]
    l52, h52 = low[-52:].min(), high[-52:].max()
    assert result.features[pb.RANGE_POSITION_52W].value == pytest.approx((c - l52) / (h52 - l52))
    assert result.features[pb.WEEKLY_MA40_DISTANCE].value == pytest.approx(c / close[-40:].mean() - 1)


def test_monthly_percentile_matches_manual_computation():
    rng = np.random.default_rng(3)
    n = 50
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.05, n)))
    result = pb.compute_pattern_b_features_v01(_monthly_rows(n, close), "2019-02-28")
    returns = close[12:] / close[:-12] - 1
    reference, current = returns[:-1], returns[-1]
    expected = 100 * ((reference < current).sum() + 0.5 * (reference == current).sum()) / len(reference)
    assert result.features[pb.RETURN_12M_PERCENTILE].value == pytest.approx(expected)


def test_weekly_percentile_matches_manual_computation():
    rng = np.random.default_rng(5)
    n = 100
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.03, n)))
    result = pb.compute_pattern_b_features_v01(_weekly_rows(n, close), "2021-11-26")
    assert result.weekly_bar_count == n
    returns = close[26:] / close[:-26] - 1
    reference, current = returns[:-1], returns[-1]
    expected = 100 * ((reference < current).sum() + 0.5 * (reference == current).sum()) / len(reference)
    assert result.features[pb.RETURN_26W_PERCENTILE].value == pytest.approx(expected)


def test_mid_rank_percentile_ties():
    reference = np.array([1.0, 2.0, 2.0, 3.0])
    assert pb.mid_rank_percentile(reference, 2.0) == 50.0
    assert pb.mid_rank_percentile(reference, 3.0) == 87.5
    assert pb.mid_rank_percentile(reference, 0.5) == 0.0
    assert pb.mid_rank_percentile(reference, 9.0) == 100.0


def test_halted_week_is_skipped_and_windows_count_bars():
    n = 60
    close = np.linspace(50, 109, n)
    frame = _weekly_rows(n, close)
    halted = frame.index[30]
    frame = frame.drop(index=halted)
    result = pb.compute_pattern_b_features_v01(frame, "2021-02-19")
    assert result.weekly_bar_count == n - 1
    kept = close[np.arange(n) != 30]
    assert result.features[pb.WEEKLY_MA40_DISTANCE].value == pytest.approx(kept[-1] / kept[-40:].mean() - 1)


# --- Boundary ----------------------------------------------------------------

def test_insufficient_bars_is_unavailable():
    result = pb.compute_pattern_b_features_v01(_monthly_rows(35, np.linspace(100, 134, 35)), "2017-11-30")
    for name in (pb.RANGE_POSITION_36M, pb.HIGH_DRAWDOWN_36M):
        assert result.features[name].value is None
        assert result.features[name].status == pb.STATUS_INSUFFICIENT_BARS
    assert result.features[pb.MONTHLY_MA24_DISTANCE].status == pb.STATUS_OK


def test_insufficient_percentile_reference():
    close36 = np.linspace(100, 135, 36)
    short = pb.compute_pattern_b_features_v01(_monthly_rows(36, close36), "2017-12-31")
    fv = short.features[pb.RETURN_12M_PERCENTILE]
    assert fv.value is None and fv.status == pb.STATUS_INSUFFICIENT_REFERENCE  # 23 references
    close37 = np.linspace(100, 136, 37)
    enough = pb.compute_pattern_b_features_v01(_monthly_rows(37, close37), "2018-01-31")
    assert enough.features[pb.RETURN_12M_PERCENTILE].status == pb.STATUS_OK  # 24 references

    weekly = pb.compute_pattern_b_features_v01(_weekly_rows(78, np.linspace(50, 127, 78)), "2021-06-30")
    assert weekly.features[pb.RETURN_26W_PERCENTILE].status == pb.STATUS_INSUFFICIENT_REFERENCE


def test_flat_range_is_unavailable():
    flat = np.full(40, 100.0)
    result = pb.compute_pattern_b_features_v01(_monthly_rows(40, flat, flat, flat), "2018-04-30")
    fv = result.features[pb.RANGE_POSITION_36M]
    assert fv.value is None and fv.status == pb.STATUS_FLAT_RANGE


@pytest.mark.parametrize(
    "mutate",
    [
        lambda f: f.drop(columns=["high"]),
        lambda f: f.assign(close=f["close"].where(f.index != f.index[5], np.nan)),
        lambda f: f.assign(low=f["low"].where(f.index != f.index[5], f["high"] * 2)),
        lambda f: f.assign(close=f["close"].where(f.index != f.index[5], 0.0)),
    ],
    ids=["missing_high", "nan_close", "low_above_high", "non_positive"],
)
def test_invalid_adjusted_ohlc_raises(mutate):
    frame = mutate(_monthly_rows(40, np.linspace(100, 139, 40)))
    with pytest.raises(pb.PatternBFeatureInputError):
        pb.compute_pattern_b_features_v01(frame, "2018-04-30")
