"""데이터 공급자 인터페이스.

Pattern 로직(patterns/pattern_a.py 등)은 이 모듈이 반환하는 표준 OHLCV
DataFrame에만 의존하고, PyKRX 등 구체적인 데이터 소스를 직접 호출하지 않는다.

표준 OHLCV DataFrame 형식:
    - index: DatetimeIndex (거래일 오름차순)
    - columns: open, high, low, close, volume
"""

from __future__ import annotations

import pandas as pd


def load_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """종목의 표준 OHLCV DataFrame을 반환한다.

    실제 데이터 공급자(PyKRX 등) 연동은 아직 구현되지 않았다.
    """
    raise NotImplementedError(
        "데이터 공급자 연동은 아직 구현되지 않았습니다. "
        "Pattern 로직 검증이 끝난 뒤 별도로 구현합니다."
    )
