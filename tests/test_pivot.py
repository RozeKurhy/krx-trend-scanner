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
