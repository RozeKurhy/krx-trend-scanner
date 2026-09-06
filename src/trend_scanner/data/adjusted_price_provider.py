"""Dedicated PyKRX adjusted-OHLC provider.

This provider deliberately performs exactly one ``adjusted=True`` request per
logical fetch.  It never loads credentials, calls the KRX Open API, or asks
PyKRX for the unadjusted response used by the legacy composite provider.
"""

from __future__ import annotations

from datetime import date, datetime
import math
import re
import xml.etree.ElementTree as ET
from typing import Any

import pandas as pd
import requests

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.adjusted_price_semantics import (
    ClosureState,
    analytic_candle_is_valid,
    classify_source_row,
    is_zero_ohlc_phantom,
    validate_source_integrity,
)
from trend_scanner.data.adjusted_price_source_authority import (
    AdjustedPriceSourceDescriptor,
    CURRENT_SOURCE_DESCRIPTOR,
    assert_current_descriptor,
    load_adjusted_price_source_authority,
)


ADJUSTED_OHLC_COLUMNS = ("open", "high", "low", "close")
_PYKRX_COLUMNS = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}
_FORBIDDEN_OUTPUT_COLUMNS = {"volume", "trading_value", "market_cap", "listed_shares"}


_TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")
_NAVER_DATE_RE = re.compile(r"^\d{8}$")


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
            & (frame["volume"] == 0)
        )
        frame = frame.loc[~phantom].sort_index()
        output = frame[list(ADJUSTED_OHLC_COLUMNS)]
        if _FORBIDDEN_OUTPUT_COLUMNS.intersection(output.columns):
            raise MarketDataError("AdjustedPriceDataProvider가 ancillary column을 반환했습니다.")
        validate_adjusted_ohlc(output)
        return output.astype("float64")


class NaverDirectAdjustedPriceDataProvider:
    """Authoritative adjusted-OHLC provider backed by Naver's XML endpoint.

    The provider deliberately performs one physical request for each logical
    fetch. Retry policy belongs to the caller (the full-population runner).
    """

    endpoint = CURRENT_SOURCE_DESCRIPTOR.source_endpoint

    def __init__(
        self,
        session: requests.Session | None = None,
        timeout_seconds: float = 10.0,
        authority_descriptor: AdjustedPriceSourceDescriptor | None = None,
    ) -> None:
        self.session = session if session is not None else requests.Session()
        self.timeout_seconds = float(timeout_seconds)
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        # Validate the durable decision before the provider can make a call.
        self.source_descriptor = authority_descriptor or load_adjusted_price_source_authority()
        assert_current_descriptor(self.source_descriptor)
        self._logical_fetch_count = 0
        self._naver_http_call_count = 0
        self._successful_fetch_count = 0
        self._empty_fetch_count = 0
        self._error_fetch_count = 0
        self._pykrx_fallback_call_count = 0
        self._phantom_row_count = 0
        self._source_nonusable_row_count = 0
        self._phantom_dates: list[str] = []
        self._source_nonusable_dates: list[str] = []

    @staticmethod
    def _request_date(value: Any, field: str) -> tuple[str, pd.Timestamp]:
        if isinstance(value, datetime):
            timestamp = pd.Timestamp(value).tz_localize(None) if pd.Timestamp(value).tzinfo else pd.Timestamp(value)
        elif isinstance(value, date):
            timestamp = pd.Timestamp(value)
        else:
            try:
                timestamp = pd.Timestamp(value)
            except (TypeError, ValueError, OverflowError) as exc:
                raise MarketDataError(f"{field}가 유효한 date-like 값이 아닙니다: {value!r}") from exc
        if pd.isna(timestamp):
            raise MarketDataError(f"{field}가 유효한 date-like 값이 아닙니다: {value!r}")
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_localize(None)
        return timestamp.strftime("%Y%m%d"), timestamp.normalize()

    @property
    def logical_fetch_count(self) -> int:
        return self._logical_fetch_count

    @property
    def naver_http_call_count(self) -> int:
        return self._naver_http_call_count

    @property
    def successful_fetch_count(self) -> int:
        return self._successful_fetch_count

    @property
    def empty_fetch_count(self) -> int:
        return self._empty_fetch_count

    @property
    def error_fetch_count(self) -> int:
        return self._error_fetch_count

    @property
    def pykrx_fallback_call_count(self) -> int:
        return self._pykrx_fallback_call_count

    @property
    def phantom_row_count(self) -> int:
        """Number of exact suspension placeholder rows removed so far."""

        return self._phantom_row_count

    @property
    def source_nonusable_row_count(self) -> int:
        return self._source_nonusable_row_count

    @property
    def phantom_dates(self) -> tuple[str, ...]:
        return tuple(self._phantom_dates)

    @property
    def source_nonusable_dates(self) -> tuple[str, ...]:
        return tuple(self._source_nonusable_dates)

    def call_audit(self) -> dict[str, int]:
        return {
            "logical_fetch_count": self.logical_fetch_count,
            "naver_http_call_count": self.naver_http_call_count,
            "successful_fetch_count": self.successful_fetch_count,
            "empty_fetch_count": self.empty_fetch_count,
            "error_fetch_count": self.error_fetch_count,
            "pykrx_fallback_call_count": self.pykrx_fallback_call_count,
            "phantom_row_count": self.phantom_row_count,
        }

    @staticmethod
    def _empty() -> pd.DataFrame:
        return _empty_adjusted_frame()

    def _parse_response(self, payload: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        if not payload or not payload.strip():
            raise MarketDataError("Naver XML payload가 비어 있습니다.")
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as exc:
            raise MarketDataError(f"Naver XML parse failure: {exc}") from exc
        if root.tag != "protocol":
            raise MarketDataError(f"Naver XML root가 protocol이 아닙니다: {root.tag!r}")
        children = list(root)
        if len(children) != 1 or children[0].tag != "chartdata":
            raise MarketDataError("Naver XML protocol에 direct chartdata child가 정확히 하나 필요합니다.")
        chartdata = children[0]
        items = list(chartdata)
        if any(item.tag != "item" for item in items):
            raise MarketDataError("Naver XML chartdata에는 item child만 허용됩니다.")
        rows: list[tuple[pd.Timestamp, float, float, float, float]] = []
        phantom_dates: list[str] = []
        source_nonusable_dates: list[str] = []
        source_row_audit: list[dict[str, Any]] = []
        seen_dates: set[pd.Timestamp] = set()
        for item in items:
            data = item.attrib.get("data")
            if data is None:
                raise MarketDataError("Naver item에 data attribute가 없습니다.")
            fields = data.split("|")
            if len(fields) != 6:
                raise MarketDataError(f"Naver item field count가 6이 아닙니다: {len(fields)}")
            if not _NAVER_DATE_RE.fullmatch(fields[0]):
                raise MarketDataError(f"Naver item date schema 오류: {fields[0]!r}")
            try:
                day = pd.Timestamp(datetime.strptime(fields[0], "%Y%m%d"))
                values = [float(fields[i]) for i in range(1, 5)]
                volume = float(fields[5])  # volume is validated but never emitted
            except (TypeError, ValueError, OverflowError) as exc:
                raise MarketDataError(f"Naver item numeric/date parse failure: {data!r}") from exc
            if not all(math.isfinite(value) for value in (*values, volume)):
                raise MarketDataError(f"Naver item numeric value가 finite하지 않습니다: {data!r}")
            if day < start or day > end:
                raise MarketDataError(f"Naver response date is outside requested window: {fields[0]}")
            if day in seen_dates:
                raise MarketDataError("Naver response contains duplicate dates")
            seen_dates.add(day)
            open_, high, low, close = values
            date_str = day.strftime("%Y-%m-%d")
            if is_zero_ohlc_phantom(open_, high, low, close) and volume == 0.0:
                self._phantom_row_count += 1
                phantom_dates.append(date_str)
                source_row_audit.append(
                    {
                        "date": date_str,
                        "classification": "NAVER_SOURCE_PLACEHOLDER_CANDIDATE",
                        "reason": "exact zero-OHL positive-close shape with zero Naver volume; independent authority required",
                        "source_authority": self.source_descriptor.source_authority_id,
                        "source_row_present": True,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    }
                )
                continue
            state = classify_source_row(open_, high, low, close, volume, volume)
            if state == ClosureState.ADJUDICATED_SOURCE_NONUSABLE:
                self._source_nonusable_row_count += 1
                source_nonusable_dates.append(date_str)
                source_row_audit.append(
                    {
                        "date": date_str,
                        "classification": "NAVER_SOURCE_NONUSABLE",
                        "reason": "source row has non-positive OHLC or activity-positive zero-OHL shape",
                        "source_authority": self.source_descriptor.source_authority_id,
                        "source_row_present": True,
                        "open": open_,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume,
                    }
                )
                continue
            rows.append((day, open_, high, low, close))
        frame = pd.DataFrame(
            [(day, open_, high, low, close) for day, open_, high, low, close in rows],
            columns=["date", *ADJUSTED_OHLC_COLUMNS],
        ).set_index("date")
        if frame.index.has_duplicates:
            raise MarketDataError("Naver response contains duplicate dates")
        frame = frame.sort_index()
        frame.index = pd.DatetimeIndex(frame.index).rename(None)
        frame = frame[list(ADJUSTED_OHLC_COLUMNS)].astype("float64")
        validate_source_integrity(frame)
        frame.attrs["source_native_adjusted"] = True
        frame.attrs["raw_source_row_count"] = len(items)
        frame.attrs["phantom_row_count"] = len(phantom_dates)
        frame.attrs["phantom_dates"] = tuple(phantom_dates)
        frame.attrs["source_nonusable_row_count"] = len(source_nonusable_dates)
        frame.attrs["source_nonusable_dates"] = tuple(source_nonusable_dates)
        frame.attrs["source_row_audit"] = tuple(source_row_audit)
        self._phantom_dates.extend(phantom_dates)
        self._source_nonusable_dates.extend(source_nonusable_dates)
        valid = analytic_candle_is_valid(frame)
        frame.attrs["analytic_invalid_ohlc_count"] = int((~valid).sum())
        return frame

    def load_daily(self, ticker: str, start: Any, end: Any) -> pd.DataFrame:
        normalized_ticker = normalize_ticker(ticker)
        start_param, start_ts = self._request_date(start, "start")
        end_param, end_ts = self._request_date(end, "end")
        if start_ts > end_ts:
            raise MarketDataError("start가 end보다 늦습니다.")
        self._logical_fetch_count += 1
        params = {
            "symbol": normalized_ticker,
            "timeframe": "day",
            "count": self.source_descriptor.count,
            "requestType": 1,
            "startTime": start_param,
            "endTime": end_param,
        }
        self._naver_http_call_count += 1
        try:
            response = self.session.get(self.endpoint, params=params, timeout=self.timeout_seconds)
            if getattr(response, "status_code", 200) >= 400:
                raise MarketDataError(f"Naver HTTP failure: {response.status_code}")
            frame = self._parse_response(getattr(response, "text", ""), start_ts, end_ts)
            frame.attrs["source_row_audit"] = tuple(
                {**entry, "ticker": normalized_ticker}
                for entry in frame.attrs.get("source_row_audit", ())
            )
        except MarketDataError:
            self._error_fetch_count += 1
            raise
        except Exception as exc:
            self._error_fetch_count += 1
            raise MarketDataError(f"Naver adjusted-price request failed: {exc}") from exc
        if frame.empty:
            self._empty_fetch_count += 1
        else:
            self._successful_fetch_count += 1
        return frame


__all__ = [
    "ADJUSTED_OHLC_COLUMNS",
    "AdjustedPriceDataProvider",
    "NaverDirectAdjustedPriceDataProvider",
    "normalize_ticker",
    "validate_adjusted_ohlc",
    "validate_source_integrity",
]
