"""변동성 관련 Feature 계산 함수."""

from __future__ import annotations

import pandas as pd


def true_range(df: pd.DataFrame) -> pd.Series:
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)

    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).rolling(window=period).mean()


def atr_pct(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """ATR을 종가 대비 비율로 정규화한 값. 값이 작을수록 변동성이 낮다."""
    return atr(df, period) / df["close"]
