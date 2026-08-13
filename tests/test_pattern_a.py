import dataclasses

import pandas as pd
import pytest

from trend_scanner.patterns.pattern_a import (
    PATTERN_A_MAX_SCORE,
    PATTERN_A_WEIGHTS,
    PatternAResult,
    evaluate_pattern_a,
)


def test_weights_sum_to_max_score():
    assert sum(PATTERN_A_WEIGHTS.values()) == PATTERN_A_MAX_SCORE


def test_pattern_a_result_has_documented_fields():
    field_names = {f.name for f in dataclasses.fields(PatternAResult)}
    expected = {
        "ticker",
        "name",
        "pattern_a_score",
        "base_score",
        "low_score",
        "ma_score",
        "volatility_score",
        "breakout_score",
        "ma6_slope",
        "ma12_slope",
        "ma24_slope",
        "ma24_slope_acceleration",
        "ma_spread",
        "ma_spread_12m_ago",
        "ma_spread_ratio",
        "low_regression_slope",
        "atr_pct",
        "atr_ratio",
        "distance_to_resistance",
        "range_position",
    }
    assert expected <= field_names


def test_evaluate_pattern_a_not_implemented_yet():
    daily = pd.DataFrame(
        {"open": [], "high": [], "low": [], "close": [], "volume": []},
        index=pd.DatetimeIndex([]),
    )
    with pytest.raises(NotImplementedError):
        evaluate_pattern_a(daily)
