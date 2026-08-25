"""Read-only composition layer for adjusted prices and raw KRX facts."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    normalize_ticker,
    validate_adjusted_ohlc,
)
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS, is_valid_krx_short_code
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


DAILY_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
)
RAW_DAILY_COLUMNS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
    "market_cap",
    "listed_shares",
)
ANCILLARY_COLUMNS = ("volume", "trading_value", "market_cap", "listed_shares")


def _empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(
        {column: pd.Series(dtype="float64") for column in columns},
        index=pd.DatetimeIndex([], name=None),
    )


def _date_range(start: Any, end: Any) -> tuple[pd.Timestamp, pd.Timestamp]:
    try:
        start_ts = pd.Timestamp(start)
        end_ts = pd.Timestamp(end)
    except (TypeError, ValueError, OverflowError) as exc:
        raise MarketDataError("REPOSITORY_V2_INVALID_RANGE") from exc
    if pd.isna(start_ts) or pd.isna(end_ts):
        raise MarketDataError("REPOSITORY_V2_INVALID_RANGE")
    if start_ts.tzinfo is not None:
        start_ts = start_ts.tz_localize(None)
    if end_ts.tzinfo is not None:
        end_ts = end_ts.tz_localize(None)
    start_ts = start_ts.normalize()
    end_ts = end_ts.normalize()
    if start_ts > end_ts:
        raise MarketDataError("REPOSITORY_V2_INVALID_RANGE")
    return start_ts, end_ts


def _validate_index(frame: pd.DataFrame) -> None:
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    if frame.index.tz is not None:
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")


def _validate_numeric(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    values = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    if not np.isfinite(values.to_numpy(dtype="float64")).all():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")


def _validate_ohlc_columns(frame: pd.DataFrame, columns: tuple[str, ...]) -> None:
    relation_violations = (
        (frame["high"] < frame["low"])
        | (frame["high"] < frame["open"])
        | (frame["high"] < frame["close"])
        | (frame["low"] > frame["open"])
        | (frame["low"] > frame["close"])
    )
    if relation_violations.any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    _validate_numeric(frame, columns)


def validate_repository_v2_daily(frame: pd.DataFrame) -> None:
    """Validate the exact composed daily schema without changing source values."""

    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != DAILY_COLUMNS:
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    _validate_index(frame)
    if frame.empty:
        return
    _validate_ohlc_columns(frame, ADJUSTED_OHLC_COLUMNS)
    _validate_numeric(frame, ("volume", "trading_value"))
    if (frame["volume"] < 0).any() or (frame["trading_value"] < 0).any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")


def _validate_raw_daily(frame: pd.DataFrame) -> None:
    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != RAW_DAILY_COLUMNS:
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    _validate_index(frame)
    if frame.empty:
        return
    _validate_ohlc_columns(frame, ("open", "high", "low", "close"))
    _validate_numeric(frame, RAW_DAILY_COLUMNS)
    if (frame.loc[:, list(ANCILLARY_COLUMNS)] < 0).any().any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")


def _validate_ancillary(frame: pd.DataFrame) -> None:
    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != ANCILLARY_COLUMNS:
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    _validate_index(frame)
    if frame.empty:
        return
    _validate_numeric(frame, ANCILLARY_COLUMNS)
    if (frame < 0).any().any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")


class MarketDataRepositoryV2:
    """Compose adjusted OHLC with raw KRX daily facts without owning I/O."""

    def __init__(
        self,
        adjusted_price_store: AdjustedPriceStore,
        raw_stock_store: KrxRawStockStore,
    ) -> None:
        self._adjusted_price_store = adjusted_price_store
        self._raw_stock_store = raw_stock_store

    @staticmethod
    def _adjusted_ticker(ticker: str) -> str:
        try:
            return normalize_ticker(ticker)
        except MarketDataError as exc:
            raise MarketDataError("UNSUPPORTED_ADJUSTED_TICKER") from exc

    @staticmethod
    def _raw_ticker(ticker: str) -> str:
        if not is_valid_krx_short_code(ticker):
            raise MarketDataError("RAW_TICKER_FORMAT_ERROR")
        return ticker

    def _load_adjusted(self, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        try:
            frame = self._adjusted_price_store.load_daily(
                ticker,
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
            )
        except FileNotFoundError as exc:
            raise MarketDataError("DATA_UNAVAILABLE: ADJUSTED_MISSING") from exc
        if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != ADJUSTED_OHLC_COLUMNS:
            raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
        result = frame.copy()
        try:
            index = pd.DatetimeIndex(pd.to_datetime(result.index, errors="raise"))
        except (TypeError, ValueError) as exc:
            raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT") from exc
        if index.tz is not None:
            index = index.tz_localize(None)
        result.index = index.normalize().rename(None)
        try:
            validate_adjusted_ohlc(result)
        except MarketDataError as exc:
            raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT") from exc
        return result.loc[:, list(ADJUSTED_OHLC_COLUMNS)]

    def _load_raw(self, ticker: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        try:
            frame = self._raw_stock_store.load_ticker(
                ticker,
                start.strftime("%Y-%m-%d"),
                end.strftime("%Y-%m-%d"),
            )
        except FileNotFoundError as exc:
            raise MarketDataError("DATA_UNAVAILABLE: RAW_MISSING") from exc
        if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != RAW_COLUMNS:
            raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
        if frame.empty:
            return _empty_frame(RAW_DAILY_COLUMNS)
        result = frame.loc[:, list(RAW_COLUMNS)].copy()
        try:
            index = pd.DatetimeIndex(pd.to_datetime(result.pop("date"), errors="raise"))
        except (TypeError, ValueError) as exc:
            raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT") from exc
        if index.tz is not None:
            index = index.tz_localize(None)
        result = result.drop(columns=["ticker"])
        result.index = index.normalize().rename(None)
        result = result.loc[:, list(RAW_DAILY_COLUMNS)]
        _validate_raw_daily(result)
        return result

    @staticmethod
    def _session_mismatch(adjusted: pd.DataFrame, raw: pd.DataFrame) -> bool:
        return set(adjusted.index) != set(raw.index)

    def get_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        start_ts, end_ts = _date_range(start, end)
        adjusted_ticker = self._adjusted_ticker(ticker)
        adjusted = self._load_adjusted(adjusted_ticker, start_ts, end_ts)
        raw = self._load_raw(self._raw_ticker(ticker), start_ts, end_ts)

        if adjusted.empty and raw.empty:
            return _empty_frame(DAILY_COLUMNS)
        if adjusted.empty:
            raise MarketDataError("DATA_UNAVAILABLE: ADJUSTED_MISSING")
        if raw.empty:
            raise MarketDataError("DATA_UNAVAILABLE: RAW_MISSING")
        if self._session_mismatch(adjusted, raw):
            raise MarketDataError("REPOSITORY_V2_TRADING_SESSION_MISMATCH")

        adjusted = adjusted.sort_index()
        raw = raw.sort_index()
        result = pd.concat(
            [
                adjusted.loc[:, list(ADJUSTED_OHLC_COLUMNS)],
                raw.loc[:, ["volume", "trading_value"]],
            ],
            axis=1,
        )
        result = result.loc[:, list(DAILY_COLUMNS)]
        validate_repository_v2_daily(result)
        return result

    def get_raw_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        start_ts, end_ts = _date_range(start, end)
        return self._load_raw(self._raw_ticker(ticker), start_ts, end_ts)

    def get_daily_ancillary(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        raw = self.get_raw_daily(ticker, start, end)
        result = raw.loc[:, list(ANCILLARY_COLUMNS)].copy()
        _validate_ancillary(result)
        return result

    def get_stock_snapshot(self, ticker: str, date: str) -> pd.DataFrame:
        start_ts, end_ts = _date_range(date, date)
        raw = self.get_raw_daily(ticker, date, date)
        if raw.empty:
            raise MarketDataError("DATA_UNAVAILABLE: RAW_MISSING")
        if len(raw) != 1:
            raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
        result = raw.loc[:, list(RAW_DAILY_COLUMNS)].copy()
        result.index = pd.DatetimeIndex([start_ts])
        return result


__all__ = [
    "ANCILLARY_COLUMNS",
    "DAILY_COLUMNS",
    "MarketDataRepositoryV2",
    "RAW_DAILY_COLUMNS",
    "validate_repository_v2_daily",
]
