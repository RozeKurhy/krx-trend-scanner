import math

import pandas as pd

from trend_scanner.data.resampler import to_monthly, to_weekly


def _daily_frame() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=40, freq="D")
    return pd.DataFrame(
        {
            "open": range(40),
            "high": [v + 1 for v in range(40)],
            "low": [v - 1 for v in range(40)],
            "close": [v + 0.5 for v in range(40)],
            "volume": [100] * 40,
            "trading_value": [100.0 * v for v in range(40)],
        },
        index=index,
    )


def test_to_weekly_aggregates_ohlcv():
    daily = _daily_frame()
    weekly = to_weekly(daily)

    # KRX 거래주 기준(W-FRI): 2024-01-01(Mon)은 첫 주(2024-01-05 금요일 마감)에 속한다.
    first_week = weekly.loc["2024-01-05"]
    first_week_daily = daily.loc["2024-01-01":"2024-01-05"]

    assert first_week["open"] == first_week_daily["open"].iloc[0]
    assert first_week["close"] == first_week_daily["close"].iloc[-1]
    assert first_week["high"] == first_week_daily["high"].max()
    assert first_week["low"] == first_week_daily["low"].min()
    assert first_week["volume"] == first_week_daily["volume"].sum()
    assert first_week["trading_value"] == first_week_daily["trading_value"].sum()


def test_to_monthly_aggregates_ohlcv():
    daily = _daily_frame()
    monthly = to_monthly(daily)

    jan = monthly.loc["2024-01-31"]
    jan_daily = daily.loc["2024-01-01":"2024-01-31"]

    assert jan["open"] == jan_daily["open"].iloc[0]
    assert jan["close"] == jan_daily["close"].iloc[-1]
    assert jan["high"] == jan_daily["high"].max()
    assert jan["low"] == jan_daily["low"].min()
    assert jan["volume"] == jan_daily["volume"].sum()
    assert jan["trading_value"] == jan_daily["trading_value"].sum()


def test_trading_value_all_nan_window_stays_nan_not_zero():
    daily = _daily_frame()
    # 2월(2024-02-01 이후, 이 frame에서는 2024-02-09까지) trading_value를 전부 NaN으로.
    daily.loc["2024-02-01":, "trading_value"] = float("nan")

    monthly = to_monthly(daily)

    feb = monthly.loc["2024-02-29"]
    assert math.isnan(feb["trading_value"])

    # 회귀 방지: 1월은 여전히 정상적으로 합산돼야 한다.
    jan = monthly.loc["2024-01-31"]
    jan_daily = daily.loc["2024-01-01":"2024-01-31"]
    assert jan["trading_value"] == jan_daily["trading_value"].sum()


def test_trading_value_partial_nan_window_sums_non_nan_values():
    index = pd.date_range("2024-03-01", periods=5, freq="D")
    daily = pd.DataFrame(
        {
            "open": [1, 2, 3, 4, 5],
            "high": [1, 2, 3, 4, 5],
            "low": [1, 2, 3, 4, 5],
            "close": [1, 2, 3, 4, 5],
            "volume": [10, 10, 10, 10, 10],
            "trading_value": [100.0, float("nan"), 300.0, float("nan"), 500.0],
        },
        index=index,
    )

    monthly = to_monthly(daily)

    march = monthly.loc["2024-03-31"]
    assert march["trading_value"] == 900.0  # NaN은 건너뛰고 100+300+500만 합산
