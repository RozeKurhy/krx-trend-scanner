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

확인됨(Feature Validation v0.1, 삼성전자 2018-05-04 50:1 액면분할 실측): adjusted=True
경로의 거래량(volume)은 분할 조정되지 않은 원본 값이다. 가격만 조정되고 거래량은
그대로라, 분할 경계를 넘는 장기 거래량 비교는 인위적 불연속이 생긴다. 거래대금은
그날 실제 체결 기준이라 이 문제가 없다.

휴장일 phantom row: 두 백엔드 모두 일부 휴장일을 응답에서 제외하지 않고
open=high=low=volume=0, close=직전 거래일 값인 행을 포함시킨다. 이런 행은
_to_standard_schema에서 필터링한다(아래).

1원 반올림 보정(adjusted=True 전용): 액면분할 등으로 수정주가를 소급 계산할 때
OHLC 각 필드를 독립적으로 반올림하면서 high가 open/close보다 1원 낮거나 low가
open/close보다 1원 높은 사소한 관계 위반이 생기는 경우가 있다(NAVER 15건,
삼성전자 1건 실측). validator는 느슨하게 만들지 않고, adjusted=True 경로에서만
_correct_minor_rounding_violations로 1원 이내 위반만 정상값으로 보정한다. 2원
이상 벌어진 위반이나 adjusted=False(원본) 데이터는 보정하지 않고 그대로
validate_ohlcv가 실패시키게 둔다.

인증: adjusted=False(KRX 원천) 경로는 KRX_ID/KRX_PW 환경 변수가 설정되어
있으면 PyKRX가 내부적으로 로그인 세션을 사용한다(없어도 익명 요청으로
자동 폴백하지만, 최근 KRX 쪽 정책상 익명 요청이 막힐 수 있다). 이 모듈을
import하는 시점에 .env 파일이 있으면 자동으로 읽어 환경 변수로 등록한다.
KRX_ID/KRX_PW 값 자체는 이 프로젝트 코드 어디에도 하드코딩하지 않는다.
"""

from __future__ import annotations

import pandas as pd
from dotenv import load_dotenv

from trend_scanner.data.errors import MarketDataError

_STANDARD_COLUMNS = ("open", "high", "low", "close", "volume", "trading_value")

_KOREAN_TO_STANDARD = {
    "시가": "open",
    "고가": "high",
    "저가": "low",
    "종가": "close",
    "거래량": "volume",
}


def _is_phantom_holiday_row(df: pd.DataFrame) -> pd.Series:
    """휴장일인데 open/high/low/volume=0, close만 직전 거래일 값을 들고 있는 행."""
    return (
        (df["open"] == 0)
        & (df["high"] == 0)
        & (df["low"] == 0)
        & (df["volume"] == 0)
        & (df["close"] > 0)
    )


def _correct_minor_rounding_violations(df: pd.DataFrame) -> pd.DataFrame:
    """수정주가 소급 계산의 1원 이내 반올림 오차만 보정한다.

    high가 open/close보다 낮거나 low가 open/close보다 높은 위반 중,
    정상값(max/min(open, close))과의 차이가 1원 이하인 경우에만 보정한다.
    2원 이상 벌어진 위반은 손대지 않고 validate_ohlcv가 그대로 실패시키게 둔다.
    """
    df = df.copy()

    normal_high = df[["open", "close"]].max(axis=1)
    high_diff = normal_high - df["high"]
    correctable_high = (high_diff > 0) & (high_diff <= 1)
    df.loc[correctable_high, "high"] = normal_high[correctable_high]

    normal_low = df[["open", "close"]].min(axis=1)
    low_diff = df["low"] - normal_low
    correctable_low = (low_diff > 0) & (low_diff <= 1)
    df.loc[correctable_low, "low"] = normal_low[correctable_low]

    return df


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
            load_dotenv()
            from pykrx import stock

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

        missing = [k for k in _KOREAN_TO_STANDARD if k not in price_df.columns]
        if missing:
            raise MarketDataError(f"PyKRX 응답 schema 오류: missing={missing}")

        index = pd.DatetimeIndex(price_df.index).rename(None)
        df = pd.DataFrame(index=index)

        try:
            for korean, standard in _KOREAN_TO_STANDARD.items():
                series = price_df[korean]
                if series.isna().any():
                    # NaN -> int64 캐스팅은 예외 없이 조용히 쓰레기 값을 만들어낼 수
                    # 있어(예: NaN -> INT64_MIN) 캐스팅 전에 명시적으로 막는다.
                    raise MarketDataError(f"PyKRX 응답 정규화 실패: {korean} 컬럼에 NaN이 있습니다.")
                dtype = "int64" if standard == "volume" else "float64"
                df[standard] = series.to_numpy(dtype=dtype)

            if trading_value is not None:
                df = df.join(trading_value.rename("trading_value"))
            else:
                df["trading_value"] = float("nan")
            df["trading_value"] = df["trading_value"].astype("float64")
        except (ValueError, TypeError) as exc:
            raise MarketDataError(f"PyKRX 응답 정규화 실패: {exc}") from exc

        result = df[list(_STANDARD_COLUMNS)].sort_index()
        phantom_mask = _is_phantom_holiday_row(result)
        if phantom_mask.any():
            result = result.loc[~phantom_mask]
        if self._adjusted:
            result = _correct_minor_rounding_violations(result)
        return result
