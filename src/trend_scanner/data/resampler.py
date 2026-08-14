"""일봉 OHLCV DataFrame을 주봉/월봉으로 변환한다."""

from __future__ import annotations

import pandas as pd

_OHLCV_AGG = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    # trading_value는 개별 거래일 NaN(비수정 API 응답과 join 특성)이 있을 수 있는데,
    # pandas의 sum은 기본적으로 NaN을 0으로 취급해서 건너뛴다. 즉 한 달 전체가 NaN이면
    # 월봉 trading_value는 NaN이 아니라 0이 된다 — resample 특성상 자연히 생기는
    # 동작이라 여기서 별도로 보정하지 않는다.
    "trading_value": "sum",
}


def _resample(daily: pd.DataFrame, rule) -> pd.DataFrame:
    return daily.resample(rule).agg(_OHLCV_AGG).dropna(how="all")


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 DataFrame을 주봉으로 리샘플링한다.

    KRX 거래주 기준(금요일 마감)에 맞춰 "W-FRI"를 사용한다.
    daily는 DatetimeIndex와 open/high/low/close/volume/trading_value 컬럼을
    가져야 한다.
    """
    return _resample(daily, "W-FRI")


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """일봉 DataFrame을 월봉으로 리샘플링한다.

    문자열 alias("M"/"ME")는 pandas 버전에 따라 지원 여부가 달라서
    (2.0/2.1은 "M"만, 2.2+는 "ME"도, 3.0+는 "ME"만 지원) 버전에 안전한
    pd.offsets.MonthEnd()를 명시적으로 사용한다.
    daily는 DatetimeIndex와 open/high/low/close/volume/trading_value 컬럼을
    가져야 한다.
    """
    return _resample(daily, pd.offsets.MonthEnd())
