"""Pivot Low 탐색 및 저점 구조 Feature 계산 함수."""

from __future__ import annotations

import warnings

import numpy as np
import pandas as pd


def find_pivot_lows(low: pd.Series, window: int = 2) -> list[tuple]:
    """좌우 `window` 구간보다 낮은 저점(Pivot Low)을 찾는다.

    반환값은 (index, value) 튜플의 리스트이며 시간 순으로 정렬돼 있다.

    PHASE4B_STOCK_REPORT_PERFORMANCE_V01: 원래 구현은 인덱스마다
    ``low.iloc[...]`` 세 번(현재/좌측 구간/우측 구간)씩 호출하는 파이썬
    반복문이었다. pandas ``.iloc[]``는 호출당 오버헤드가 커서, 이 함수가
    (A FAST Core 재진입 시뮬레이션의 매 주간/월간 스냅샷마다) 수백~수천 번
    반복 호출되면 그 오버헤드가 누적되어 리포트 생성 시간의 상당 부분을
    차지했다(1850개 리포트 production 실행에서 실측 확인). 아래는 numpy
    슬라이딩 윈도우로 완전히 벡터화한 동일 알고리즘이다: 각 위치의
    좌/우 구간 최솟값을 ``np.nanmin``으로 계산해 기존 ``Series.min()``의
    NaN skip(=skipna=True) 동작과 동일하게 맞추고, 비교 로직
    (``current < left_min and current < right_min``, NaN 비교는 항상
    False)도 그대로 유지한다 — 산식/의미는 바뀌지 않고 구현만 벡터화했다.
    """
    n = len(low)
    if n <= 2 * window:
        return []

    values = low.to_numpy(dtype=float, copy=False)
    index = low.index

    # sliding_window_view(values, window)[k] == values[k : k + window]
    windows = np.lib.stride_tricks.sliding_window_view(values, window)
    with np.errstate(invalid="ignore"), warnings.catch_warnings():
        # all-NaN 구간은 pandas Series.min()도 조용히 NaN을 반환한다(skipna=True) --
        # np.nanmin의 "All-NaN slice encountered" 경고를 억제해 동일하게 조용히 처리한다.
        warnings.filterwarnings("ignore", message="All-NaN slice encountered")
        window_min = np.nanmin(windows, axis=1)

    idx_range = np.arange(window, n - window)
    current = values[idx_range]
    left_min = window_min[idx_range - window]      # values[i-window:i].min()
    right_min = window_min[idx_range + 1]           # values[i+1:i+window+1].min()

    mask = (current < left_min) & (current < right_min)
    selected = idx_range[mask]

    return [(index[i], values[i]) for i in selected]


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
