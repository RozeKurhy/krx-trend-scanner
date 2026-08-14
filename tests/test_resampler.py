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
