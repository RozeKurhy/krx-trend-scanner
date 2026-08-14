"""데이터 공급자 인터페이스.

Pattern/Feature/Resampler 계층은 이 Protocol에만 의존하고, PyKRX 등
구체적인 데이터 소스를 직접 알지 못한다.
"""

from __future__ import annotations

from typing import Protocol

import pandas as pd


class MarketDataProvider(Protocol):
    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        """종목의 표준 OHLCV DataFrame을 반환한다.

        반환값은 DatetimeIndex(오름차순)와 open/high/low/close/volume/
        trading_value 컬럼을 가져야 한다.
        """
        ...
