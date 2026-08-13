"""일봉 OHLCV DataFrame을 주봉/월봉으로 변환한다."""

from __future__ import annotations

import pandas as pd

_OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
}


def _resample(daily: pd.DataFrame, rule: str) -> pd.DataFrame:
    return daily.resample(rule).agg(_OHLCV_AGG).dropna(how="all")


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 DataFrame을 주봉으로 리샘플링한다.

    daily는 DatetimeIndex와 open/high/low/close/volume 컬럼을 가져야 한다.
    """
    return _resample(daily, "W")


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 DataFrame을 월봉으로 리샘플링한다.

    daily는 DatetimeIndex와 open/high/low/close/volume 컬럼을 가져야 한다.
    """
    return _resample(daily, "ME")
