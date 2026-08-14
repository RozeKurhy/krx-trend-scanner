"""실제 PyKRX API를 호출하는 통합 테스트.

기본 `pytest` 실행에서는 제외된다(pyproject.toml의 addopts). 명시적으로
`pytest -m integration`으로만 실행한다. 네트워크가 필요하다.
"""

import pandas as pd
import pytest

from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.data.validator import validate_ohlcv


@pytest.mark.integration
def test_load_daily_returns_valid_standard_ohlcv():
    provider = PyKrxDataProvider(adjusted=True)

    result = provider.load_daily("005930", "2024-01-02", "2024-01-10")

    assert isinstance(result.index, pd.DatetimeIndex)
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    validate_ohlcv(result)
