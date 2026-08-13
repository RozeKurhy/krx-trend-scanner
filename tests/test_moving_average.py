import math

import pandas as pd
import pytest

from trend_scanner.features.moving_average import (
    ma_slope,
    ma_slope_acceleration,
    ma_spread,
    ma_spread_ratio,
)


def test_ma_slope_rising_series_is_positive():
    series = pd.Series([100.0, 102.0, 104.0, 108.0])
    assert ma_slope(series, periods=3) == pytest.approx(108.0 / 100.0 - 1)


def test_ma_slope_falling_series_is_negative():
    series = pd.Series([100.0, 98.0, 95.0, 90.0])
    assert ma_slope(series, periods=3) < 0


def test_ma_slope_acceleration_detects_deceleration():
    # slope가 약 -0.05 -> -0.03으로 개선되는(하락 둔화) 시나리오
    series = pd.Series([100, 96, 92, 90, 91, 92, 93, 88.2])
    result = ma_slope_acceleration(series, periods=3, lag=3)
    assert result > 0


def test_ma_spread_normalizes_by_close():
    spread = ma_spread([98, 100, 105], close=100)
    assert spread == pytest.approx(0.07)


def test_ma_spread_ratio():
    assert ma_spread_ratio(current_spread=0.07, past_spread=0.20) == pytest.approx(0.35)


def test_ma_spread_ratio_zero_past_is_nan():
    assert math.isnan(ma_spread_ratio(current_spread=0.05, past_spread=0.0))
