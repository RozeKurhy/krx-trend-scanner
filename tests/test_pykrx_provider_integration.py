"""실제 PyKRX API를 호출하는 통합 테스트.

기본 `pytest` 실행에서는 제외된다(pyproject.toml의 addopts). 명시적으로
`pytest -m integration`으로만 실행한다. 네트워크가 필요하다.

KRX_ID/KRX_PW 환경 변수(.env 또는 실제 환경 변수)가 없으면 skip 처리한다.
credential 값 자체는 이 파일 어디에도 출력하지 않는다.
"""

import os

import pandas as pd
import pytest
from dotenv import load_dotenv

from trend_scanner.data.pykrx_provider import PyKrxDataProvider
from trend_scanner.data.validator import validate_ohlcv

load_dotenv()

pytestmark = pytest.mark.integration

_HAS_KRX_CREDENTIALS = bool(os.getenv("KRX_ID")) and bool(os.getenv("KRX_PW"))


@pytest.mark.skipif(
    not _HAS_KRX_CREDENTIALS,
    reason="KRX_ID/KRX_PW 환경 변수가 없어 integration test를 skip합니다.",
)
def test_load_daily_returns_valid_standard_ohlcv():
    provider = PyKrxDataProvider(adjusted=True)

    result = provider.load_daily("005930", "2024-01-02", "2024-01-10")

    assert isinstance(result.index, pd.DatetimeIndex)
    assert list(result.columns) == ["open", "high", "low", "close", "volume", "trading_value"]
    validate_ohlcv(result)
