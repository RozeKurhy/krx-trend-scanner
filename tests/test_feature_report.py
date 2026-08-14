import math

import pandas as pd
import pytest

from trend_scanner.features.moving_average import ma_slope, ma_spread, moving_average
from trend_scanner.features.pivot import find_pivot_lows, pivot_low_regression_slope
from trend_scanner.features.volatility import atr_pct
from trend_scanner.validation.feature_report import (
    FeatureRow,
    build_feature_row,
    to_csv_row,
)


def _monthly_frame(
    n: int,
    close: list[float] | None = None,
    high: list[float] | None = None,
    low: list[float] | None = None,
    volume: list[float] | None = None,
    trading_value: list[float] | None = None,
    start: str = "2015-01-31",
) -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="ME")
    close = close if close is not None else [100.0 + i for i in range(n)]
    high = high if high is not None else [c + 5 for c in close]
    low = low if low is not None else [c - 5 for c in close]
    volume = volume if volume is not None else [1000.0 + i for i in range(n)]
    trading_value = trading_value if trading_value is not None else [v * 100 for v in volume]
    return pd.DataFrame(
        {
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "trading_value": trading_value,
        },
        index=index,
    )


def _weekly_frame(n: int, start: str = "2015-01-02") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="W-FRI")
    close = [100.0 + i for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 2 for c in close],
            "low": [c - 2 for c in close],
            "close": close,
            "volume": [500.0 + i for i in range(n)],
            "trading_value": [v * 100 for v in [500.0 + i for i in range(n)]],
        },
        index=index,
    )


def _daily_frame(n: int, start: str = "2015-01-01") -> pd.DataFrame:
    index = pd.date_range(start, periods=n, freq="D")
    close = [100.0 + i * 0.1 for i in range(n)]
    return pd.DataFrame(
        {
            "open": close,
            "high": [c + 1 for c in close],
            "low": [c - 1 for c in close],
            "close": close,
            "volume": [1000.0] * n,
            "trading_value": [1.0e8] * n,
        },
        index=index,
    )


def _empty_ohlcv() -> pd.DataFrame:
    return pd.DataFrame(
        columns=["open", "high", "low", "close", "volume", "trading_value"],
        index=pd.DatetimeIndex([]),
    )


# --- 가격 구조: range / compression / position / distance -----------------


def test_range_windows_and_compression_ratio():
    # 앞 12개월(포지션 0~11): 넓은 range(high=200, low=0), 뒤 24개월: 좁은 range(high=110, low=90)
    n = 36
    high = [200.0] * 12 + [110.0] * 24
    low = [0.0] * 12 + [90.0] * 24
    close = [100.0] * n

    monthly = _monthly_frame(n, close=close, high=high, low=low)
    weekly = _weekly_frame(60)
    daily = _daily_frame(400)

    row = build_feature_row("TEST", "테스트", daily, weekly, monthly)

    assert row.range_36m == pytest.approx((200.0 - 0.0) / 100.0)
    assert row.range_24m == pytest.approx((110.0 - 90.0) / 100.0)
    assert row.range_12m == pytest.approx((110.0 - 90.0) / 100.0)
    assert row.compression_ratio == pytest.approx(row.range_12m / row.range_36m)


def test_range_position_and_distance_to_resistance():
    n = 36
    close = [100.0] * n
    high = [200.0] * n
    low = [0.0] * n
    monthly = _monthly_frame(n, close=close, high=high, low=low)
    weekly = _weekly_frame(60)
    daily = _daily_frame(400)

    row = build_feature_row("TEST", "테스트", daily, weekly, monthly)

    # close=100, low_36m=0, high_36m=200 -> range_position = (100-0)/(200-0) = 0.5
    assert row.range_position == pytest.approx(0.5)
    # distance_to_resistance = (200-100)/200 = 0.5
    assert row.distance_to_resistance == pytest.approx(0.5)


# --- Pivot Low 연결 ---------------------------------------------------------


def test_pivot_low_connection_matches_underlying_function():
    n = 20
    low_values = [10, 9, 8, 9, 10, 9, 7, 9, 10, 9, 6, 9, 10, 9, 5, 9, 10, 9, 8, 9]
    close = [v + 5 for v in low_values]
    high = [v + 10 for v in low_values]
    monthly = _monthly_frame(n, close=[float(c) for c in close], high=[float(h) for h in high], low=[float(v) for v in low_values])
    weekly = _weekly_frame(60)
    daily = _daily_frame(400)

    row = build_feature_row("TEST", "테스트", daily, weekly, monthly)

    expected_pivots = find_pivot_lows(monthly["low"], window=2)
    expected_slope = pivot_low_regression_slope(expected_pivots, lookback=4)

    assert row.pivot_low_count == len(expected_pivots)
    if math.isnan(expected_slope):
        assert math.isnan(row.pivot_low_slope)
    else:
        assert row.pivot_low_slope == pytest.approx(expected_slope)

    expected_recent = expected_pivots[-3:]
    expected_prices = [float(v) for _, v in expected_recent]
    assert row.pivot_low_1 == pytest.approx(expected_prices[0])


# --- MA 연결 ----------------------------------------------------------------


def test_ma_feature_connection_matches_underlying_functions():
    n = 40
    close = [100.0 + i for i in range(n)]
    monthly = _monthly_frame(n, close=close)
    weekly = _weekly_frame(60)
    daily = _daily_frame(800)

    row = build_feature_row("TEST", "테스트", daily, weekly, monthly)

    close_series = monthly["close"]
    ma6_series = moving_average(close_series, 6)
    ma12_series = moving_average(close_series, 12)
    ma24_series = moving_average(close_series, 24)

    assert row.ma6 == pytest.approx(ma6_series.iloc[-1])
    assert row.ma12 == pytest.approx(ma12_series.iloc[-1])
    assert row.ma24 == pytest.approx(ma24_series.iloc[-1])
    assert row.ma6_slope == pytest.approx(ma_slope(ma6_series, periods=3))
    assert row.ma24_slope == pytest.approx(ma_slope(ma24_series, periods=3))

    expected_spread = ma_spread(
        [ma6_series.iloc[-1], ma12_series.iloc[-1], ma24_series.iloc[-1]], close_series.iloc[-1]
    )
    assert row.ma_spread == pytest.approx(expected_spread)


# --- ATR 연결 ----------------------------------------------------------------


def test_atr_feature_connection_matches_underlying_function():
    n = 40
    close = [100.0 + (i % 5) for i in range(n)]
    high = [c + 3 for c in close]
    low = [c - 3 for c in close]
    monthly = _monthly_frame(n, close=close, high=high, low=low)
    weekly = _weekly_frame(60)
    daily = _daily_frame(800)

    row = build_feature_row("TEST", "테스트", daily, weekly, monthly)

    expected_atr_series = atr_pct(monthly)
    assert row.atr_pct == pytest.approx(expected_atr_series.iloc[-1])
    expected_ago = expected_atr_series.iloc[-13]
    assert row.atr_pct_12m_ago == pytest.approx(expected_ago)
    assert row.atr_ratio == pytest.approx(row.atr_pct / expected_ago)


# --- lookback 부족 -> NaN ----------------------------------------------------


def test_insufficient_lookback_returns_nan_not_crash():
    n = 10  # 12개월 미만: range_12m/24m/36m, MA12/MA24 전부 NaN이어야 함
    monthly = _monthly_frame(n)
    weekly = _weekly_frame(20)
    daily = _daily_frame(200)

    row = build_feature_row("TEST", "테스트", daily, weekly, monthly)

    assert math.isnan(row.range_12m)
    assert math.isnan(row.range_24m)
    assert math.isnan(row.range_36m)
    assert math.isnan(row.ma12)
    assert math.isnan(row.ma24)
    # MA6는 6개월 창이 10개월 데이터 안에서 채워지므로 값이 있어야 한다.
    assert not math.isnan(row.ma6)


def test_build_feature_row_on_fully_empty_frames_does_not_crash():
    daily = _empty_ohlcv()
    weekly = _empty_ohlcv()
    monthly = _empty_ohlcv()

    row = build_feature_row("TEST", "테스트", daily, weekly, monthly)

    assert row.daily_rows == 0
    assert row.weekly_rows == 0
    assert row.monthly_rows == 0
    assert row.as_of is None
    assert math.isnan(row.close)
    assert math.isnan(row.range_36m)
    assert row.pivot_low_count == 0
    assert math.isnan(row.ma24)


# --- CSV row 생성 -------------------------------------------------------------


def test_to_csv_row_contains_all_dataclass_fields():
    n = 40
    monthly = _monthly_frame(n)
    weekly = _weekly_frame(60)
    daily = _daily_frame(800)

    row = build_feature_row("005930", "삼성전자", daily, weekly, monthly)
    csv_row = to_csv_row(row)

    assert csv_row["ticker"] == "005930"
    assert csv_row["name"] == "삼성전자"
    assert set(csv_row.keys()) == {f.name for f in FeatureRow.__dataclass_fields__.values()}
