import math

import pytest

from trend_scanner.features.resistance import distance_to_resistance, range_position


def test_distance_to_resistance_near_zero_at_resistance():
    assert distance_to_resistance(close=95, resistance=100) == pytest.approx(0.05)


def test_distance_to_resistance_large_when_far_below():
    assert distance_to_resistance(close=50, resistance=100) == pytest.approx(0.5)


def test_range_position_bounds():
    assert range_position(close=50, low=0, high=100) == pytest.approx(0.5)
    assert range_position(close=0, low=0, high=100) == pytest.approx(0.0)
    assert range_position(close=100, low=0, high=100) == pytest.approx(1.0)


def test_range_position_nan_when_flat_range():
    assert math.isnan(range_position(close=100, low=100, high=100))
