from __future__ import annotations

import pandas as pd
import pytest
import pykrx.stock as pykrx_stock

from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    AdjustedPriceDataProvider,
    validate_adjusted_ohlc,
)
from trend_scanner.data.errors import MarketDataError


def _response(*, phantom: bool = False) -> pd.DataFrame:
    index = pd.date_range("2024-01-02", periods=3 if phantom else 2, freq="D")
    values = {
        "시가": [100, 0, 102] if phantom else [100, 101],
        "고가": [105, 0, 107] if phantom else [105, 106],
        "저가": [95, 0, 97] if phantom else [95, 96],
        "종가": [102, 102, 104] if phantom else [102, 103],
        "거래량": [1000, 0, 1200] if phantom else [1000, 1100],
    }
    return pd.DataFrame(values, index=index)


def test_adjusted_provider_calls_pykrx_adjusted_true_only(monkeypatch):
    calls = []

    def fake(start, end, ticker, adjusted=True):
        calls.append((start, end, ticker, adjusted))
        return _response()

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", fake)
    provider = AdjustedPriceDataProvider()
    result = provider.load_daily("5930", "2024-01-02", "2024-01-03")
    assert calls == [("2024-01-02", "2024-01-03", "005930", True)]
    assert provider.call_audit() == {
        "logical_fetch_count": 1,
        "adjusted_true_call_count": 1,
        "adjusted_false_call_count": 0,
    }
    assert not result.empty


def test_adjusted_provider_never_calls_adjusted_false(monkeypatch):
    def fake(start, end, ticker, adjusted=True):
        assert adjusted is True
        return _response()

    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", fake)
    provider = AdjustedPriceDataProvider()
    provider.load_daily("005930", "2024-01-02", "2024-01-03")
    assert provider.adjusted_false_call_count == 0


def test_provider_returns_ohlc_only(monkeypatch):
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: _response())
    result = AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-03")
    assert tuple(result.columns) == ADJUSTED_OHLC_COLUMNS
    assert isinstance(result.index, pd.DatetimeIndex)
    assert all(dtype == "float64" for dtype in result.dtypes)
    assert "volume" not in result.columns


def test_provider_drops_volume_after_phantom_check(monkeypatch):
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: _response(phantom=True))
    result = AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-04")
    assert len(result) == 2
    assert list(result.index) == list(pd.date_range("2024-01-02", "2024-01-04", freq="D").take([0, 2]))
    assert tuple(result.columns) == ADJUSTED_OHLC_COLUMNS


def test_provider_filters_phantom_holiday_rows(monkeypatch):
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: _response(phantom=True))
    result = AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-04")
    assert (result[["open", "high", "low"]] == 0).sum().sum() == 0


def test_provider_applies_only_one_won_high_correction(monkeypatch):
    frame = _response().copy()
    frame.loc[frame.index[0], "고가"] = 101
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: frame)
    result = AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-03")
    assert result.loc[frame.index[0], "high"] == 102


def test_provider_applies_only_one_won_low_correction(monkeypatch):
    frame = _response().copy()
    frame.loc[frame.index[0], "저가"] = 101
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: frame)
    result = AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-03")
    assert result.loc[frame.index[0], "low"] == 100


def test_provider_rejects_two_won_relation_violation(monkeypatch):
    frame = _response().copy()
    frame.loc[frame.index[0], "고가"] = 100
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: frame)
    with pytest.raises(MarketDataError):
        AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-03")


def test_provider_rejects_missing_ohlc_column(monkeypatch):
    frame = _response().drop(columns=["저가"])
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: frame)
    with pytest.raises(MarketDataError):
        AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-03")


def test_provider_rejects_nan_price(monkeypatch):
    frame = _response().copy()
    frame.loc[frame.index[0], "종가"] = float("nan")
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: frame)
    with pytest.raises(MarketDataError):
        AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-03")


def test_provider_returns_typed_empty_frame(monkeypatch):
    monkeypatch.setattr(pykrx_stock, "get_market_ohlcv_by_date", lambda *args, **kwargs: pd.DataFrame())
    result = AdjustedPriceDataProvider().load_daily("005930", "2024-01-02", "2024-01-03")
    assert result.empty
    assert tuple(result.columns) == ADJUSTED_OHLC_COLUMNS
    assert isinstance(result.index, pd.DatetimeIndex)


def test_validate_adjusted_ohlc_rejects_ancillary_columns():
    frame = _response().rename(columns={"시가": "open"})
    with pytest.raises(MarketDataError):
        validate_adjusted_ohlc(frame)
