"""표준 OHLCV DataFrame 검증.

잘못된 raw 데이터를 조용히 보정하지 않고 MarketDataError로 명확히 실패시킨다.
"""

from __future__ import annotations

import pandas as pd

from trend_scanner.data.errors import MarketDataError

REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume", "trading_value")

# NaN을 허용하지 않는 컬럼. trading_value는 여기서 제외한다: PyKrxDataProvider가
# 수정주가(open/high/low/close/volume)와 거래대금을 서로 다른 두 API 호출로 가져와
# 날짜 기준으로 합치기 때문에, 두 응답의 거래일이 완전히 일치하지 않으면
# trading_value에 NaN이 생길 수 있다. OHLC와 volume은 항상 단일 조회 결과이므로
# NaN을 허용하지 않는다. trading_value는 개별 NaN은 허용하되(아래), 전부 NaN이거나
# 음수인 경우는 별도로 거른다.
REQUIRED_NON_NULL_COLUMNS = ("open", "high", "low", "close", "volume")


def validate_ohlcv(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise MarketDataError(f"필수 컬럼이 없습니다: {missing}")

    if not isinstance(df.index, pd.DatetimeIndex):
        raise MarketDataError(f"index가 DatetimeIndex가 아닙니다: {type(df.index)}")

    if df.empty:
        return

    if not df.index.is_monotonic_increasing:
        raise MarketDataError("index가 오름차순으로 정렬되어 있지 않습니다.")

    duplicated = df.index[df.index.duplicated()]
    if len(duplicated) > 0:
        raise MarketDataError(f"중복된 거래일이 있습니다: {list(duplicated)}")

    null_rows = df[list(REQUIRED_NON_NULL_COLUMNS)].isna().any(axis=1)
    if null_rows.any():
        raise MarketDataError(f"OHLC/volume에 NaN이 있습니다: {list(df.index[null_rows])}")

    price_columns = ["open", "high", "low", "close"]
    negative_price_rows = (df[price_columns] < 0).any(axis=1)
    if negative_price_rows.any():
        raise MarketDataError(f"음수 가격이 있습니다: {list(df.index[negative_price_rows])}")

    if (df["volume"] < 0).any():
        bad = df.index[df["volume"] < 0]
        raise MarketDataError(f"음수 거래량이 있습니다: {list(bad)}")

    if df["trading_value"].isna().all():
        raise MarketDataError("trading_value가 전부 NaN입니다(정상적인 조회 결과로 보기 어렵습니다).")

    negative_trading_value = df["trading_value"].dropna() < 0
    if negative_trading_value.any():
        bad = negative_trading_value.index[negative_trading_value]
        raise MarketDataError(f"음수 거래대금이 있습니다: {list(bad)}")

    relation_violations = (
        (df["high"] < df["low"])
        | (df["high"] < df["open"])
        | (df["high"] < df["close"])
        | (df["low"] > df["open"])
        | (df["low"] > df["close"])
    )
    if relation_violations.any():
        bad = df.index[relation_violations]
        raise MarketDataError(f"OHLC 가격 관계가 깨진 거래일이 있습니다: {list(bad)}")
