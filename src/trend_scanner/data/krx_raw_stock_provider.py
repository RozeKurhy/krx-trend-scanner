"""Raw KRX whole-market daily snapshot provider.

The KRX daily trading endpoints are consumed as an authority-preserving
market/date snapshot.  This module performs only strict transport/schema
validation and source-field mapping; it never adjusts or classifies rows.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Mapping

import numpy as np
import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient


RAW_COLUMNS = (
    "date",
    "ticker",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "trading_value",
    "market_cap",
    "listed_shares",
)
RAW_NUMERIC_COLUMNS = RAW_COLUMNS[2:]
MARKETS = ("KOSPI", "KOSDAQ")
MARKET_ENDPOINTS = {
    "KOSPI": "/sto/stk_bydd_trd",
    "KOSDAQ": "/sto/ksq_bydd_trd",
}
SOURCE_FIELDS = {
    "date": "BAS_DD",
    "ticker": "ISU_CD",
    "open": "TDD_OPNPRC",
    "high": "TDD_HGPRC",
    "low": "TDD_LWPRC",
    "close": "TDD_CLSPRC",
    "volume": "ACC_TRDVOL",
    "trading_value": "ACC_TRDVAL",
    "market_cap": "MKTCAP",
    "listed_shares": "LIST_SHRS",
}
SCHEMA_VERSION = "KRX_RAW_STOCK_V01"
AUTHORITY = "KRX Open API Stock Daily"
_INT64_MAX = int(np.iinfo("int64").max)
_DATE_PATTERN = re.compile(r"^\d{8}$")


class KrxRawStockSnapshotError(MarketDataError):
    """Raised when a raw KRX snapshot violates its fail-closed contract."""

    def __init__(self, error_code: str, message: str = "", *, diagnostic: Mapping[str, Any] | None = None) -> None:
        self.error_code = str(error_code)
        self.diagnostic = dict(diagnostic or {})
        detail = f": {message}" if message else ""
        super().__init__(f"{self.error_code}{detail}")


def _snapshot_error(error_code: str, message: str = "", **diagnostic: Any) -> KrxRawStockSnapshotError:
    return KrxRawStockSnapshotError(error_code, message, diagnostic=diagnostic)


def normalize_market(market: str) -> str:
    value = str(market).strip().upper()
    if value not in MARKETS:
        raise _snapshot_error("RAW_SNAPSHOT_INVALID_MARKET", repr(market))
    return value


def normalize_bas_dd(value: Any) -> str:
    if isinstance(value, datetime):
        result = value.date().isoformat()
    elif isinstance(value, date):
        result = value.isoformat()
    else:
        text = str(value).strip()
        digits = re.sub(r"[^0-9]", "", text)
        if len(digits) != 8:
            raise _snapshot_error("RAW_SNAPSHOT_INVALID_DATE", repr(value))
        result = f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    try:
        parsed = pd.Timestamp(result)
    except (TypeError, ValueError, OverflowError) as exc:
        raise _snapshot_error("RAW_SNAPSHOT_INVALID_DATE", repr(value)) from exc
    if pd.isna(parsed):
        raise _snapshot_error("RAW_SNAPSHOT_INVALID_DATE", repr(value))
    return parsed.date().isoformat()


def _source_date(value: Any) -> str:
    digits = re.sub(r"[^0-9]", "", str(value or "").strip())
    return digits if _DATE_PATTERN.fullmatch(digits) else ""


def _parse_int(value: Any, field: str, *, strictly_positive: bool = False) -> int:
    if isinstance(value, bool) or value is None:
        raise _snapshot_error("RAW_SNAPSHOT_NUMERIC_PARSE_ERROR", field, numeric_field=field)
    text = str(value).replace(",", "").strip()
    if not text or text in {"-", "—", "nan", "NaN", "None", "null"}:
        raise _snapshot_error("RAW_SNAPSHOT_NUMERIC_PARSE_ERROR", field, numeric_field=field)
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise _snapshot_error("RAW_SNAPSHOT_NUMERIC_PARSE_ERROR", field, numeric_field=field) from exc
    if not number.is_finite() or number != number.to_integral_value():
        raise _snapshot_error("RAW_SNAPSHOT_NUMERIC_PARSE_ERROR", field, numeric_field=field)
    parsed = int(number)
    if parsed < (1 if strictly_positive else 0) or parsed > _INT64_MAX:
        raise _snapshot_error("RAW_SNAPSHOT_NUMERIC_RANGE_ERROR", field, numeric_field=field)
    return parsed


def _typed_empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series([], dtype="datetime64[ns]"),
            "ticker": pd.Series([], dtype="string"),
            **{field: pd.Series([], dtype="int64") for field in RAW_NUMERIC_COLUMNS},
        },
        columns=list(RAW_COLUMNS),
    )


def _validate_ohlc_relation(row: Mapping[str, int]) -> None:
    values = [row[field] for field in ("open", "high", "low", "close")]
    if all(value > 0 for value in values):
        if not (
            row["high"] >= row["open"]
            and row["high"] >= row["close"]
            and row["high"] >= row["low"]
            and row["low"] <= row["open"]
            and row["low"] <= row["close"]
        ):
            raise KrxRawStockSnapshotError("RAW_SNAPSHOT_OHLC_RELATION_ERROR")


def validate_raw_snapshot_frame(frame: pd.DataFrame, expected_date: Any) -> pd.DataFrame:
    """Validate and normalize a raw snapshot without changing source values."""

    if not isinstance(frame, pd.DataFrame) or tuple(frame.columns) != RAW_COLUMNS:
        raise KrxRawStockSnapshotError("RAW_SNAPSHOT_SCHEMA_ERROR")
    requested = normalize_bas_dd(expected_date)
    result = frame.copy()
    try:
        dates = pd.to_datetime(result["date"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise KrxRawStockSnapshotError("RAW_SNAPSHOT_DATE_MISMATCH") from exc
    if any(pd.Timestamp(value).date().isoformat() != requested for value in dates):
        raise KrxRawStockSnapshotError("RAW_SNAPSHOT_DATE_MISMATCH")
    result["date"] = pd.Series(pd.DatetimeIndex(dates).normalize(), index=result.index, dtype="datetime64[ns]")
    tickers = result["ticker"].astype("string")
    if tickers.isna().any() or not tickers.str.fullmatch(r"\d{6}").all():
        raise KrxRawStockSnapshotError("RAW_SNAPSHOT_TICKER_FORMAT_ERROR")
    if tickers.duplicated().any():
        raise KrxRawStockSnapshotError("RAW_SNAPSHOT_DUPLICATE_TICKER")
    result["ticker"] = tickers
    for field in RAW_NUMERIC_COLUMNS:
        if result[field].isna().any():
            raise KrxRawStockSnapshotError(f"RAW_SNAPSHOT_NUMERIC_PARSE_ERROR: {field}")
        parsed = []
        for value in result[field].tolist():
            parsed.append(_parse_int(value, field, strictly_positive=field == "listed_shares"))
        result[field] = pd.Series(parsed, index=result.index, dtype="int64")
    for row in result.to_dict("records"):
        _validate_ohlc_relation(row)
    return result.loc[:, list(RAW_COLUMNS)].reset_index(drop=True)


class KrxRawStockSnapshotProvider:
    """Map one KRX market/date response into the frozen raw stock schema."""

    def __init__(self, client: KrxOpenApiClient) -> None:
        self.client = client

    def fetch_market_snapshot(self, market: str, bas_dd: Any) -> pd.DataFrame:
        normalized_market = normalize_market(market)
        requested_date = normalize_bas_dd(bas_dd)
        response = self.client.fetch(
            MARKET_ENDPOINTS[normalized_market],
            requested_date,
            quota_endpoint_key=MARKET_ENDPOINTS[normalized_market].strip("/"),
        )
        response_diagnostic = {
            "http_status": getattr(response, "http_status", None),
            "transport_error_type": getattr(response, "error_type", None),
            "records_key": getattr(response, "records_key", None),
            "record_count": len(getattr(response, "records", ()) or ()),
            "top_level_keys": list(getattr(response, "top_level_keys", ()) or ()),
            "record_keys": sorted({str(key) for row in (getattr(response, "records", ()) or ()) for key in row.keys()})[:64],
        }
        if response.http_status != 200:
            raise _snapshot_error("RAW_SNAPSHOT_HTTP_STATUS", str(response.http_status), **response_diagnostic)
        if response.records_key != "OutBlock_1":
            raise _snapshot_error("RAW_SNAPSHOT_RECORDS_KEY", **response_diagnostic)
        if not getattr(response, "records", ()):
            return _typed_empty_snapshot()
        rows: list[dict[str, Any]] = []
        for source_row in response.records:
            missing = [source for source in SOURCE_FIELDS.values() if source not in source_row]
            if missing:
                raise _snapshot_error(
                    "RAW_SNAPSHOT_REQUIRED_FIELD_MISSING",
                    str(missing),
                    **response_diagnostic,
                    required_missing_fields=missing,
                )
            source_date = _source_date(source_row[SOURCE_FIELDS["date"]])
            if source_date != requested_date.replace("-", ""):
                raise _snapshot_error(
                    "RAW_SNAPSHOT_DATE_MISMATCH",
                    **response_diagnostic,
                    source_date_sample_shape="8-digit" if source_date else "invalid",
                )
            ticker = str(source_row[SOURCE_FIELDS["ticker"]]).strip()
            if not re.fullmatch(r"\d{6}", ticker):
                raise _snapshot_error(
                    "RAW_SNAPSHOT_TICKER_FORMAT_ERROR",
                    **response_diagnostic,
                    ticker_sample_shape=f"length={len(ticker)}" if ticker else "empty",
                )
            row: dict[str, Any] = {"date": pd.Timestamp(requested_date), "ticker": ticker}
            for field in RAW_NUMERIC_COLUMNS:
                try:
                    row[field] = _parse_int(
                        source_row[SOURCE_FIELDS[field]],
                        field,
                        strictly_positive=field == "listed_shares",
                    )
                except KrxRawStockSnapshotError as exc:
                    raise KrxRawStockSnapshotError(
                        exc.error_code,
                        str(exc).split(": ", 1)[-1],
                        diagnostic={**response_diagnostic, **exc.diagnostic, "numeric_field_failure": field},
                    ) from exc
            _validate_ohlc_relation(row)
            rows.append(row)
        frame = pd.DataFrame(rows, columns=list(RAW_COLUMNS))
        try:
            return validate_raw_snapshot_frame(frame, requested_date)
        except KrxRawStockSnapshotError as exc:
            raise KrxRawStockSnapshotError(
                exc.error_code,
                str(exc).split(": ", 1)[-1],
                diagnostic={**response_diagnostic, **exc.diagnostic},
            ) from exc


__all__ = [
    "AUTHORITY",
    "MARKETS",
    "MARKET_ENDPOINTS",
    "RAW_COLUMNS",
    "RAW_NUMERIC_COLUMNS",
    "SCHEMA_VERSION",
    "SOURCE_FIELDS",
    "KrxRawStockSnapshotError",
    "KrxRawStockSnapshotProvider",
    "normalize_bas_dd",
    "normalize_market",
    "validate_raw_snapshot_frame",
]
