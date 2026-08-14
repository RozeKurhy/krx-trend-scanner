"""Pivot Low 탐색 및 저점 구조 Feature 계산 함수."""

from __future__ import annotations

import numpy as np
import pandas as pd


def find_pivot_lows(low: pd.Series, window: int = 2) -> list[tuple]:
    """좌우 `window` 구간보다 낮은 저점(Pivot Low)을 찾는다.

    반환값은 (index, value) 튜플의 리스트이며 시간 순으로 정렬돼 있다.
    """
    pivots = []

    for i in range(window, len(low) - window):
        current = low.iloc[i]

        left = low.iloc[i - window:i]
        right = low.iloc[i + 1:i + window + 1]

        if current < left.min() and current < right.min():
            pivots.append((low.index[i], current))

    return pivots


def _elapsed_days(start, end) -> float:
    """두 index 값 사이의 간격을 일(day) 단위로 환산한다.

    DatetimeIndex라면 실제 경과일을, 정수/실수 index라면 그 차이를 그대로 쓴다.
    """
    diff = end - start
    if isinstance(diff, pd.Timedelta):
        return diff.total_seconds() / 86400
    return float(diff)


def pivot_low_regression_slope(pivot_lows: list[tuple], lookback: int = 4) -> float:
    """최근 `lookback`개 Pivot Low의 선형회귀 기울기를 저점 평균값으로 정규화한 값.

    x축은 Pivot 순번이 아니라 실제 경과 시간(day)이다. Pivot 사이 간격이
    일정하지 않으면(예: 저점이 짧은 기간에 몰려 빠르게 올라오는 경우와
    긴 기간에 걸쳐 천천히 올라오는 경우) 같은 가격 변화라도 다른 기울기가
    나와야 하기 때문이다.

    Pivot Low가 2개 미만이거나 경과 시간이 전부 동일하면 계산할 수 없어
    NaN을 반환한다.
    """
    recent = pivot_lows[-lookback:]

    if len(recent) < 2:
        return float("nan")

    start = recent[0][0]
    x = np.array([_elapsed_days(start, idx) for idx, _ in recent], dtype=float)
    values = np.array([value for _, value in recent], dtype=float)

    if x.max() == x.min():
        return float("nan")

    slope = np.polyfit(x, values, 1)[0]
    return slope / values.mean()
