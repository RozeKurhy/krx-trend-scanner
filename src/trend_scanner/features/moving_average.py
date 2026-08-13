"""이동평균 관련 Feature 계산 함수."""

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
import pandas as pd


def moving_average(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def ma_slope(series: pd.Series, periods: int = 3) -> float:
    """`periods` 구간 동안의 이동평균 변화율. 상승 시 양수."""
    current = series.iloc[-1]
    past = series.iloc[-1 - periods]
    return current / past - 1


def ma_slope_series(series: pd.Series, periods: int = 3) -> pd.Series:
    return series.pct_change(periods)


def ma_slope_acceleration(series: pd.Series, periods: int = 3, lag: int = 3) -> float:
    """직전 slope 대비 현재 slope의 변화량. 하락 둔화/상승 전환 시 양수."""
    slope = ma_slope_series(series, periods)
    current_slope = slope.iloc[-1]
    previous_slope = slope.iloc[-1 - lag]
    return current_slope - previous_slope


def ma_spread(ma_values: Iterable[float], close: float) -> float:
    """여러 이동평균선 간의 간격을 종가 대비 비율로 정규화한다."""
    values = np.array(list(ma_values), dtype=float)
    return (values.max() - values.min()) / close


def ma_spread_ratio(current_spread: float, past_spread: float) -> float:
    """과거 대비 현재 MA Spread 비율. 작을수록 수렴이 진행된 것."""
    if past_spread == 0:
        return float("nan")
    return current_spread / past_spread
