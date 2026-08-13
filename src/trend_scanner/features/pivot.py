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


def pivot_low_regression_slope(pivot_lows: list[tuple], lookback: int = 4) -> float:
    """최근 `lookback`개 Pivot Low의 선형회귀 기울기를 저점 평균값으로 정규화한 값.

    Pivot Low가 2개 미만이면 계산할 수 없어 NaN을 반환한다.
    """
    recent = pivot_lows[-lookback:]

    if len(recent) < 2:
        return float("nan")

    values = np.array([p[1] for p in recent], dtype=float)
    x = np.arange(len(values))

    slope = np.polyfit(x, values, 1)[0]
    return slope / values.mean()
