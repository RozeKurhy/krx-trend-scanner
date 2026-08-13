import pytest

from trend_scanner.data.loader import load_ohlcv


def test_load_ohlcv_not_implemented_yet():
    with pytest.raises(NotImplementedError):
        load_ohlcv("005930", start="2020-01-01", end="2024-01-01")
