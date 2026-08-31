"""Read-only composition layer for adjusted prices and raw KRX facts."""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.adjusted_price_provider import (
    ADJUSTED_OHLC_COLUMNS,
    normalize_ticker,
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

NON_TRADING_PLACEHOLDER_PREDICATE_NAME = "NON_TRADING_PLACEHOLDER_V01"
NON_TRADING_PLACEHOLDER_PREDICATE_BASIS = "ADJUSTED_PRICE_PROVIDER_PHANTOM_COMPATIBILITY"
NON_TRADING_PLACEHOLDER_FIELDS = (
    "open == 0",
    "high == 0",
    "low == 0",
    "close > 0",
    "volume == 0",
    "trading_value == 0",
)


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


def _validate_source_history_ohlc(frame: pd.DataFrame) -> None:
    """Validate source-history adjusted OHLC without rewriting source relations.

    The adjusted store deliberately preserves source-native observations even
    when a candle violates the analytic high/low relation.  Repository V2's
    composed daily view is therefore a source-history view; analytic callers
    must opt into ``AdjustedPriceStore.load_daily_analytic`` separately.
    """

    _validate_numeric(frame, ADJUSTED_OHLC_COLUMNS)
    if (frame.loc[:, list(ADJUSTED_OHLC_COLUMNS)] <= 0).any().any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")


def _validate_raw_ohlc_columns(frame: pd.DataFrame) -> None:
    """Apply the frozen raw authority relation only to all-positive rows."""

    columns = ("open", "high", "low", "close")
    values = frame.loc[:, list(columns)].apply(pd.to_numeric, errors="coerce")
    if values.isna().any().any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    if not np.isfinite(values.to_numpy(dtype="float64")).all():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    positive_mask = (values > 0).all(axis=1)
    if not positive_mask.any():
        return
    positive = values.loc[positive_mask]
    relation_violations = (
        (positive["high"] < positive["low"])
        | (positive["high"] < positive["open"])
        | (positive["high"] < positive["close"])
        | (positive["low"] > positive["open"])
        | (positive["low"] > positive["close"])
    )
    if relation_violations.any():
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")


def validate_repository_v2_daily(
    frame: pd.DataFrame,
    *,
    source_history: bool = False,
) -> None:
    """Validate the exact composed daily schema without changing source values.

    ``source_history=True`` is the explicit V2 composition contract: adjusted
    OHLC is preserved from the authoritative source-history store and is not
    subjected to an analytic relation filter.
    """

    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != DAILY_COLUMNS:
        raise MarketDataError("INVALID_REPOSITORY_V2_OUTPUT")
    _validate_index(frame)
    if frame.empty:
        return
    if source_history:
        _validate_source_history_ohlc(frame.loc[:, list(ADJUSTED_OHLC_COLUMNS)])
    else:
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
    _validate_raw_ohlc_columns(frame)
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


def _is_non_trading_placeholder(row: pd.Series) -> bool:
    """Return true only for the exact, deliberately narrow placeholder shape."""

    return bool(
        row["open"] == 0
        and row["high"] == 0
        and row["low"] == 0
        and row["close"] > 0
        and row["volume"] == 0
        and row["trading_value"] == 0
    )


def _placeholder_predicate_fields(row: pd.Series) -> dict[str, bool]:
    return {
        "open_zero": bool(row["open"] == 0),
        "high_zero": bool(row["high"] == 0),
        "low_zero": bool(row["low"] == 0),
        "close_positive": bool(row["close"] > 0),
        "volume_zero": bool(row["volume"] == 0),
        "trading_value_zero": bool(row["trading_value"] == 0),
    }


def _json_scalar(value: Any) -> Any:
    return value.item() if hasattr(value, "item") else value


def _session_projection_evidence(
    adjusted: pd.DataFrame,
    raw: pd.DataFrame,
) -> dict[str, Any]:
    """Describe and explicitly apply the raw-only session projection.

    The returned ``projected_raw`` is a copy.  The caller's physical raw frame is
    never mutated, and this helper is intentionally limited to the composed
    ``get_daily`` view.
    """

    adjusted_dates = sorted(pd.Timestamp(value).normalize() for value in adjusted.index)
    raw_dates = sorted(pd.Timestamp(value).normalize() for value in raw.index)
    adjusted_date_set = set(adjusted_dates)
    raw_date_set = set(raw_dates)
    adjusted_only_dates = sorted(adjusted_date_set - raw_date_set)
    raw_only_dates = sorted(raw_date_set - adjusted_date_set)

    raw_only_row_details: list[dict[str, Any]] = []
    accepted_placeholder_dates: list[pd.Timestamp] = []
    rejected_raw_only_dates: list[pd.Timestamp] = []
    for date in raw_only_dates:
        row = raw.loc[date]
        predicate_fields = _placeholder_predicate_fields(row)
        accepted = _is_non_trading_placeholder(row)
        if accepted:
            accepted_placeholder_dates.append(date)
            classification = "NON_TRADING_PLACEHOLDER"
            classification_reason = (
                "all six NON_TRADING_PLACEHOLDER_V01 fields match"
            )
        else:
            rejected_raw_only_dates.append(date)
            mismatched_fields = [
                field for field, matches in predicate_fields.items() if not matches
            ]
            classification = "UNCLASSIFIED_RAW_ONLY"
            classification_reason = "predicate fields failed: " + ", ".join(mismatched_fields)
        raw_only_row_details.append(
            {
                "date": date.date().isoformat(),
                "open": _json_scalar(row["open"]),
                "high": _json_scalar(row["high"]),
                "low": _json_scalar(row["low"]),
                "close": _json_scalar(row["close"]),
                "volume": _json_scalar(row["volume"]),
                "trading_value": _json_scalar(row["trading_value"]),
                "market_cap": _json_scalar(row["market_cap"]),
                "listed_shares": _json_scalar(row["listed_shares"]),
                "adjusted_present": False,
                "raw_present": True,
                "placeholder_predicate_name": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
                "placeholder_predicate_fields": predicate_fields,
                "classification": classification,
                "classification_reason": classification_reason,
            }
        )

    shared_dates = sorted(adjusted_date_set & raw_date_set)
    shared_placeholder_conflict_dates: list[pd.Timestamp] = []
    shared_placeholder_conflict_row_details: list[dict[str, Any]] = []
    for date in shared_dates:
        row = raw.loc[date]
        if not _is_non_trading_placeholder(row):
            continue
        shared_placeholder_conflict_dates.append(date)
        shared_placeholder_conflict_row_details.append(
            {
                "date": date.date().isoformat(),
                "open": _json_scalar(row["open"]),
                "high": _json_scalar(row["high"]),
                "low": _json_scalar(row["low"]),
                "close": _json_scalar(row["close"]),
                "volume": _json_scalar(row["volume"]),
                "trading_value": _json_scalar(row["trading_value"]),
                "market_cap": _json_scalar(row["market_cap"]),
                "listed_shares": _json_scalar(row["listed_shares"]),
                "adjusted_present": True,
                "raw_present": True,
                "placeholder_predicate_name": NON_TRADING_PLACEHOLDER_PREDICATE_NAME,
                "placeholder_predicate_fields": _placeholder_predicate_fields(row),
                "classification": "SHARED_DATE_PLACEHOLDER_CONFLICT",
                "classification_reason": (
                    "shared adjusted/raw date has NON_TRADING_PLACEHOLDER_V01 raw semantics"
                ),
            }
        )

    projected_raw = raw.copy()
    if accepted_placeholder_dates:
        projected_raw = projected_raw.drop(index=accepted_placeholder_dates)
    projected_raw = projected_raw.sort_index()
    projected_date_set = set(projected_raw.index)
    projected_date_set_exact_match = projected_date_set == adjusted_date_set
    return {
        "adjusted_dates": [date.date().isoformat() for date in adjusted_dates],
        "raw_dates": [date.date().isoformat() for date in raw_dates],
        "adjusted_only_dates": [date.date().isoformat() for date in adjusted_only_dates],
        "raw_only_dates": [date.date().isoformat() for date in raw_only_dates],
        "raw_only_row_details": raw_only_row_details,
        "shared_dates": [date.date().isoformat() for date in shared_dates],
        "shared_placeholder_conflict_dates": [
            date.date().isoformat() for date in shared_placeholder_conflict_dates
        ],
        "shared_placeholder_conflict_count": len(shared_placeholder_conflict_dates),
        "shared_placeholder_conflict_row_details": shared_placeholder_conflict_row_details,
        "accepted_placeholder_dates": [
            date.date().isoformat() for date in accepted_placeholder_dates
        ],
        "rejected_raw_only_dates": [
            date.date().isoformat() for date in rejected_raw_only_dates
        ],
        "projected_raw": projected_raw,
        "projected_raw_rows": len(projected_raw),
        "projected_date_set_exact_match": projected_date_set_exact_match,
        "explicit_placeholder_projection_count": len(accepted_placeholder_dates),
        "silent_inner_drop_count": 0,
    }


def _project_raw_trading_sessions(adjusted: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    evidence = _session_projection_evidence(adjusted, raw)
    if (
        evidence["adjusted_only_dates"]
        or evidence["rejected_raw_only_dates"]
        or evidence["shared_placeholder_conflict_dates"]
        or not evidence["projected_date_set_exact_match"]
    ):
        if evidence["shared_placeholder_conflict_dates"]:
            raise MarketDataError("REPOSITORY_V2_SESSION_SEMANTIC_CONFLICT")
        raise MarketDataError("REPOSITORY_V2_TRADING_SESSION_MISMATCH")
    return evidence["projected_raw"]


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
            frame = self._adjusted_price_store.load_daily_source(
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
            _validate_source_history_ohlc(result)
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

        adjusted = adjusted.sort_index()
        raw = _project_raw_trading_sessions(adjusted, raw)
        result = pd.concat(
            [
                adjusted.loc[:, list(ADJUSTED_OHLC_COLUMNS)],
                raw.loc[:, ["volume", "trading_value"]],
            ],
            axis=1,
        )
        result = result.loc[:, list(DAILY_COLUMNS)]
        validate_repository_v2_daily(result, source_history=True)
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
