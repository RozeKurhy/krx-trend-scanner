import math

import pandas as pd

from trend_scanner.features.pivot import find_pivot_lows, pivot_low_regression_slope


def test_find_pivot_lows_detects_local_minima():
    low = pd.Series([10, 9, 8, 9, 10, 9, 7, 9, 10])
    pivots = find_pivot_lows(low, window=2)

    values = [v for _, v in pivots]
    assert 8 in values
    assert 7 in values


def test_find_pivot_lows_empty_when_monotonic():
    low = pd.Series([10, 9, 8, 7, 6, 5])
    assert find_pivot_lows(low, window=2) == []


def test_pivot_low_regression_slope_positive_for_rising_lows():
    pivot_lows = [
        (0, 100.0),
        (1, 102.0),
        (2, 105.0),
        (3, 109.0),
    ]
    slope = pivot_low_regression_slope(pivot_lows, lookback=4)
    assert slope > 0


def test_pivot_low_regression_slope_negative_for_falling_lows():
    pivot_lows = [
        (0, 109.0),
        (1, 105.0),
        (2, 102.0),
        (3, 100.0),
    ]
    slope = pivot_low_regression_slope(pivot_lows, lookback=4)
    assert slope < 0


def test_pivot_low_regression_slope_nan_with_insufficient_data():
    assert math.isnan(pivot_low_regression_slope([(0, 100.0)], lookback=4))


def test_pivot_low_regression_slope_weighs_actual_time_gap():
    # 같은 가격 상승폭(100 -> 115)이라도 짧은 기간에 걸쳐 있으면 기울기가 더 커야 한다.
    fast_pivots = [
        (pd.Timestamp("2024-01-31"), 100.0),
        (pd.Timestamp("2024-02-29"), 105.0),
        (pd.Timestamp("2024-03-31"), 110.0),
        (pd.Timestamp("2024-04-30"), 115.0),
    ]
    slow_pivots = [
        (pd.Timestamp("2024-01-31"), 100.0),
        (pd.Timestamp("2025-01-31"), 105.0),
        (pd.Timestamp("2025-12-31"), 110.0),
        (pd.Timestamp("2026-12-31"), 115.0),
    ]

    fast_slope = pivot_low_regression_slope(fast_pivots, lookback=4)
    slow_slope = pivot_low_regression_slope(slow_pivots, lookback=4)

    assert fast_slope > slow_slope > 0


def test_pivot_low_regression_slope_nan_when_no_time_spread():
    same_timestamp = pd.Timestamp("2024-01-31")
    pivot_lows = [(same_timestamp, 100.0), (same_timestamp, 105.0)]
    assert math.isnan(pivot_low_regression_slope(pivot_lows, lookback=4))
