import pandas as pd
import pytest

from trend_scanner.data import pykrx_provider as pykrx_provider_module
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.pykrx_provider import PyKrxDataProvider


def _adjusted_korean_df() -> pd.DataFrame:
    # adjusted=True 경로(Naver)는 거래대금 컬럼이 없다.
    index = pd.date_range("2024-01-02", periods=2, freq="D")
    return pd.DataFrame(
        {
            "시가": [100, 101],
            "고가": [105, 106],
            "저가": [95, 96],
            "종가": [102, 103],
            "거래량": [1000, 1100],
            "등락률": [0.0, 0.98],
        },
        index=index,
    )


def _unadjusted_korean_df() -> pd.DataFrame:
    # adjusted=False 경로(KRX)는 거래대금 컬럼을 포함한다.
    index = pd.date_range("2024-01-02", periods=2, freq="D")
    return pd.DataFrame(
        {
            "시가": [99, 100],
            "고가": [104, 105],
            "저가": [94, 95],
            "종가": [101, 102],
            "거래량": [999, 1099],
            "거래대금": [123_456_789, 234_567_890],
            "등락률": [0.0, 0.99],
        },
        index=index,
    )


def test_load_daily_merges_adjusted_price_with_unadjusted_trading_value(monkeypatch):
    calls = []

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        calls.append(adjusted)
        return _adjusted_korean_df() if adjusted else _unadjusted_korean_df()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-03")

    assert calls == [True, False]
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    assert isinstance(result.index, pd.DatetimeIndex)
    assert result.index.is_monotonic_increasing

    # OHLC/volume은 adjusted(Naver) 경로에서, trading_value는 unadjusted(KRX) 경로에서 온다.
    assert result["open"].tolist() == [100.0, 101.0]
    assert result["volume"].tolist() == [1000, 1100]
    assert result["trading_value"].tolist() == [123_456_789.0, 234_567_890.0]

    assert result["open"].dtype == "float64"
    assert result["volume"].dtype == "int64"
    assert result["trading_value"].dtype == "float64"


def test_unadjusted_mode_calls_pykrx_only_once(monkeypatch):
    calls = []

    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        calls.append(adjusted)
        return _unadjusted_korean_df()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=False)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-03")

    assert calls == [False]
    assert result["trading_value"].tolist() == [123_456_789.0, 234_567_890.0]


def test_load_daily_wraps_underlying_exception():
    def raising_get_market_ohlcv_by_date(*args, **kwargs):
        raise RuntimeError("network down")

    provider = PyKrxDataProvider(adjusted=True)
    original = pykrx_provider_module.stock.get_market_ohlcv_by_date
    pykrx_provider_module.stock.get_market_ohlcv_by_date = raising_get_market_ohlcv_by_date
    try:
        with pytest.raises(MarketDataError):
            provider.load_daily("005930", "2024-01-02", "2024-01-03")
    finally:
        pykrx_provider_module.stock.get_market_ohlcv_by_date = original


def test_load_daily_empty_response_returns_empty_standard_frame(monkeypatch):
    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        return pd.DataFrame()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    result = provider.load_daily("005930", "2024-01-02", "2024-01-03")

    assert result.empty
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    assert isinstance(result.index, pd.DatetimeIndex)


def test_missing_source_column_raises_market_data_error(monkeypatch):
    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        broken = _adjusted_korean_df().drop(columns=["거래량"])
        return broken if adjusted else _unadjusted_korean_df()

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    with pytest.raises(MarketDataError):
        provider.load_daily("005930", "2024-01-02", "2024-01-03")


@pytest.mark.parametrize(
    "column,bad_value",
    [
        ("시가", "abc"),  # 문자열 -> float64 변환 실패
        ("거래량", float("nan")),  # NaN -> int64 변환 실패
    ],
)
def test_dtype_conversion_failure_raises_market_data_error(monkeypatch, column, bad_value):
    def fake_get_market_ohlcv_by_date(fromdate, todate, ticker, adjusted=True):
        if not adjusted:
            return _unadjusted_korean_df()
        broken = _adjusted_korean_df()
        broken.loc[broken.index[0], column] = bad_value
        return broken

    monkeypatch.setattr(
        pykrx_provider_module.stock, "get_market_ohlcv_by_date", fake_get_market_ohlcv_by_date
    )

    provider = PyKrxDataProvider(adjusted=True)
    with pytest.raises(MarketDataError):
        provider.load_daily("005930", "2024-01-02", "2024-01-03")
