"""PyKRX 기반 MarketDataProvider 구현.

PyKRX 의존성은 이 모듈 안에만 존재한다. Pattern/Feature/Resampler 계층은
이 모듈을 알지 못하고 provider.MarketDataProvider Protocol만 사용한다.

수정주가 정책: adjusted=True(기본값)일 때 PyKRX는 내부적으로 Naver 시세를
사용하는데, 이 경로는 거래대금(trading_value) 컬럼을 제공하지 않는다. 반면
adjusted=False(KRX 원천) 경로는 거래대금을 포함한다. 거래대금은 그날 실제
체결가 기준의 값이라 과거로 소급 조정될 이유가 없으므로, 수정주가
OHLC는 adjusted 경로에서, 거래대금은 필요하면 unadjusted 경로에서 받아
날짜 기준으로 합친다.

알려진 한계: PyKRX 내부 두 백엔드(Naver/KRX) 모두 응답 파싱 실패를
예외로 올리지 않고 빈 DataFrame으로 삼켜버린다. 따라서 "거래일이 없는
정상적인 빈 응답"과 "API 응답 형식이 깨진 실패"를 이 계층에서 구분할 수
없다. 빈 DataFrame은 유효한 것으로 취급한다.

미확인 사항: adjusted=True 경로의 거래량(volume)이 실제로 분할/액면 조정된
값인지는 PyKRX 소스 코드만으로는 확인되지 않는다. 만약 조정되지 않은
원본 거래량이라면 액면분할 시점에 거래량 기반 Feature(ATR 등 거래대금
연동 지표는 아니지만 거래량 압축 판단)에 불연속이 생길 수 있다. 실제
종목(예: 2018년 삼성전자 액면분할) 데이터로 Validation 단계에서 확인한다.
"""

from __future__ import annotations

import pandas as pd
from pykrx import stock

from trend_scanner.data.errors import MarketDataError

_STANDARD_COLUMNS = ("open", "high", "low", "close", "volume", "trading_value")

_KOREAN_TO_STANDARD = {
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
}


class PyKrxDataProvider:
    def __init__(self, adjusted: bool = True):
        self._adjusted = adjusted

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        price_df = self._call_pykrx(ticker, start, end, adjusted=self._adjusted)

        if self._adjusted:
            raw_df = self._call_pykrx(ticker, start, end, adjusted=False)
        else:
            raw_df = price_df

        trading_value = raw_df["거래대금"] if "거래대금" in raw_df.columns else None
        return self._to_standard_schema(price_df, trading_value)

    def _call_pykrx(self, ticker: str, start: str, end: str, adjusted: bool) -> pd.DataFrame:
        try:
            return stock.get_market_ohlcv_by_date(start, end, ticker, adjusted=adjusted)
        except Exception as exc:
            raise MarketDataError(
                f"PyKRX 조회 실패 (ticker={ticker}, start={start}, end={end}, "
                f"adjusted={adjusted}): {exc}"
            ) from exc

    def _to_standard_schema(
        self, price_df: pd.DataFrame, trading_value: pd.Series | None
    ) -> pd.DataFrame:
        if price_df.empty:
            return pd.DataFrame(columns=list(_STANDARD_COLUMNS), index=pd.DatetimeIndex([]))

        index = pd.DatetimeIndex(price_df.index).rename(None)
        df = pd.DataFrame(index=index)

        for korean, standard in _KOREAN_TO_STANDARD.items():
            dtype = "int64" if standard == "volume" else "float64"
            df[standard] = price_df[korean].to_numpy(dtype=dtype)

        if trading_value is not None:
            df = df.join(trading_value.rename("trading_value"))
        else:
            df["trading_value"] = float("nan")
        df["trading_value"] = df["trading_value"].astype("float64")

        return df[list(_STANDARD_COLUMNS)].sort_index()
