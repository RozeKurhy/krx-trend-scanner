"""Dedicated PyKRX adjusted-OHLC provider.

This provider deliberately performs exactly one ``adjusted=True`` request per
logical fetch.  It never loads credentials, calls the KRX Open API, or asks
PyKRX for the unadjusted response used by the legacy composite provider.
"""

from __future__ import annotations

import pandas as pd

from trend_scanner.data.errors import MarketDataError


ADJUSTED_OHLC_COLUMNS = ("open", "high", "low", "close")
_PYKRX_COLUMNS = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
_FORBIDDEN_OUTPUT_COLUMNS = {"volume", "trading_value", "market_cap", "listed_shares"}


import re

_TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")


def normalize_ticker(ticker: str | int) -> str:
    """Normalize the equity ticker to the six-digit project representation."""

    value = str(ticker).strip()
    if not value or len(value) > 6:
        raise MarketDataError(f"유효하지 않은 6자리 종목코드입니다: {ticker!r}")
    zfilled = value.zfill(6)
    if not _TICKER_RE.match(zfilled):
        raise MarketDataError(f"유효하지 않은 6자리 종목코드입니다: {ticker!r}")
    return zfilled


def _empty_adjusted_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            column: pd.Series(dtype="float64")
            for column in ADJUSTED_OHLC_COLUMNS
        },
        index=pd.DatetimeIndex([]),
    )


def _normalise_index(index: pd.Index) -> pd.DatetimeIndex:
    try:
        result = pd.DatetimeIndex(pd.to_datetime(index, errors="raise"))
    except (TypeError, ValueError) as exc:
        raise MarketDataError(f"거래일 index 변환에 실패했습니다: {exc}") from exc
    if result.tz is not None:
        result = result.tz_localize(None)
    return result.rename(None)


def _correct_minor_rounding_violations(frame: pd.DataFrame) -> pd.DataFrame:
    """Correct only the known one-won adjusted-price rounding discrepancy."""

    result = frame.copy()
    normal_high = result[["open", "close"]].max(axis=1)
    high_diff = normal_high - result["high"]
    high_mask = (high_diff > 0) & (high_diff <= 1)
    result.loc[high_mask, "high"] = normal_high[high_mask]

    normal_low = result[["open", "close"]].min(axis=1)
    low_diff = result["low"] - normal_low
    low_mask = (low_diff > 0) & (low_diff <= 1)
    result.loc[low_mask, "low"] = normal_low[low_mask]
    return result


def validate_adjusted_ohlc(frame: pd.DataFrame) -> None:
    """Fail-closed validation for the adjusted OHLC-only frame."""

    if tuple(frame.columns) != ADJUSTED_OHLC_COLUMNS:
        raise MarketDataError(
            f"수정주가 frame schema가 정확히 OHLC가 아닙니다: {list(frame.columns)}"
        )
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise MarketDataError(f"index가 DatetimeIndex가 아닙니다: {type(frame.index)}")
    if frame.empty:
        return
    if not frame.index.is_monotonic_increasing:
        raise MarketDataError("수정주가 거래일 index가 오름차순이 아닙니다.")
    if not frame.index.is_unique:
        raise MarketDataError("수정주가 거래일 index에 중복이 있습니다.")
    if frame[list(ADJUSTED_OHLC_COLUMNS)].isna().any().any():
        raise MarketDataError("수정주가 OHLC에 NaN이 있습니다.")
    if (frame[list(ADJUSTED_OHLC_COLUMNS)] <= 0).any().any():
        raise MarketDataError("수정주가 OHLC에 0 이하의 가격이 있습니다.")
    relation_violations = (
        (frame["high"] < frame["low"])
        | (frame["high"] < frame["open"])
        | (frame["high"] < frame["close"])
        | (frame["low"] > frame["open"])
        | (frame["low"] > frame["close"])
    )
    if relation_violations.any():
        bad_dates = list(frame.index[relation_violations])
        raise MarketDataError(f"수정주가 OHLC 관계가 깨졌습니다: {bad_dates}")


import signal


class _TimeoutContext:
    def __init__(self, seconds: int = 8) -> None:
        self.seconds = seconds

    def _handler(self, signum: Any, frame: Any) -> None:
        raise TimeoutError(f"PyKRX 요청이 {self.seconds}초 내에 응답하지 않아 타임아웃되었습니다.")

    def __enter__(self) -> _TimeoutContext:
        self.old_handler = signal.signal(signal.SIGALRM, self._handler)
        signal.alarm(self.seconds)
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self.old_handler)


class AdjustedPriceDataProvider:
    """Fetch adjusted OHLC only from PyKRX."""

    def __init__(self) -> None:
        self._logical_fetch_count = 0
        self._adjusted_true_call_count = 0
        self._adjusted_false_call_count = 0

    @property
    def logical_fetch_count(self) -> int:
        return self._logical_fetch_count

    @property
    def adjusted_true_call_count(self) -> int:
        return self._adjusted_true_call_count

    @property
    def adjusted_false_call_count(self) -> int:
        return self._adjusted_false_call_count

    def call_audit(self) -> dict[str, int]:
        return {
            "logical_fetch_count": self.logical_fetch_count,
            "adjusted_true_call_count": self.adjusted_true_call_count,
            "adjusted_false_call_count": self.adjusted_false_call_count,
        }

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        normalized_ticker = normalize_ticker(ticker)
        self._logical_fetch_count += 1
        self._adjusted_true_call_count += 1
        try:
            from pykrx import stock

            with _TimeoutContext(seconds=8):
                raw = stock.get_market_ohlcv_by_date(
                    start,
                    end,
                    normalized_ticker,
                    adjusted=True,
                )
        except Exception as exc:
            raise MarketDataError(
                f"PyKRX adjusted=True 조회 실패 (ticker={normalized_ticker}, start={start}, end={end}): {exc}"
            ) from exc
        return self._normalise_response(raw)

    def _normalise_response(self, raw: pd.DataFrame) -> pd.DataFrame:
        if raw is None or raw.empty:
            return _empty_adjusted_frame()
        missing = [column for column in _PYKRX_COLUMNS if column not in raw.columns]
        if missing:
            raise MarketDataError(f"PyKRX adjusted=True 응답 schema 오류: missing={missing}")

        index = _normalise_index(raw.index)
        frame = pd.DataFrame(index=index)
        try:
            for korean, standard in _PYKRX_COLUMNS.items():
                numeric = pd.to_numeric(raw[korean], errors="coerce")
                if numeric.isna().any():
                    raise MarketDataError(f"PyKRX adjusted=True {korean} 컬럼에 NaN이 있습니다.")
                frame[standard] = numeric.astype("float64").to_numpy()
        except (TypeError, ValueError) as exc:
            raise MarketDataError(f"PyKRX adjusted=True 응답 정규화 실패: {exc}") from exc

        phantom = (
            (frame["open"] == 0)
            & (frame["high"] == 0)
            & (frame["low"] == 0)
            & (frame["close"] > 0)
        )
        frame = frame.loc[~phantom].sort_index()
        frame = _correct_minor_rounding_violations(frame)
        output = frame[list(ADJUSTED_OHLC_COLUMNS)]
        if _FORBIDDEN_OUTPUT_COLUMNS.intersection(output.columns):
            raise MarketDataError("AdjustedPriceDataProvider가 ancillary column을 반환했습니다.")
        validate_adjusted_ohlc(output)
        return output.astype("float64")


__all__ = [
    "ADJUSTED_OHLC_COLUMNS",
    "AdjustedPriceDataProvider",
    "normalize_ticker",
    "validate_adjusted_ohlc",
]
