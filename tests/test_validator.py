import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.validator import validate_ohlcv


def _valid_df() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "open": [100.0, 101.0, 102.0],
            "high": [105.0, 106.0, 107.0],
            "low": [95.0, 96.0, 97.0],
            "close": [102.0, 103.0, 104.0],
            "volume": [1000, 1100, 1200],
            "trading_value": [1.0e8, 1.1e8, 1.2e8],
        },
        index=index,
    )


def test_valid_df_passes():
    validate_ohlcv(_valid_df())  # raises nothing


def test_empty_df_with_correct_columns_passes():
    df = pd.DataFrame(
        columns=["open", "high", "low", "close", "volume", "trading_value"],
        index=pd.DatetimeIndex([]),
    )
    validate_ohlcv(df)


def test_missing_column_raises():
    df = _valid_df().drop(columns=["volume"])
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)


def test_non_datetime_index_raises():
    df = _valid_df().reset_index(drop=True)
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)


def test_unsorted_index_raises():
    df = _valid_df().iloc[::-1]
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)


def test_duplicate_index_raises():
    df = _valid_df()
    dup = pd.concat([df, df.iloc[[0]]]).sort_index()
    with pytest.raises(MarketDataError):
        validate_ohlcv(dup)


def test_nan_in_ohlc_raises():
    df = _valid_df()
    df.loc[df.index[0], "close"] = float("nan")
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)


def test_nan_in_trading_value_is_tolerated():
    df = _valid_df()
    df.loc[df.index[0], "trading_value"] = float("nan")
    validate_ohlcv(df)  # raises nothing


def test_negative_price_raises():
    df = _valid_df()
    df.loc[df.index[0], "open"] = -1.0
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)


def test_negative_volume_raises():
    df = _valid_df()
    df.loc[df.index[0], "volume"] = -1
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)


@pytest.mark.parametrize(
    "column,value",
    [
        ("high", 90.0),  # high < low
        ("open", 200.0),  # high < open
        ("close", 200.0),  # high < close
    ],
)
def test_high_relation_violations_raise(column, value):
    df = _valid_df()
    df.loc[df.index[0], column] = value
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)


@pytest.mark.parametrize(
    "column,value",
    [
        ("open", 1.0),  # low > open
        ("close", 1.0),  # low > close
    ],
)
def test_low_relation_violations_raise(column, value):
    df = _valid_df()
    df.loc[df.index[0], column] = value
    with pytest.raises(MarketDataError):
        validate_ohlcv(df)
