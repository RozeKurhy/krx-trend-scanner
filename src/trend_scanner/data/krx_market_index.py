"""KRX Open API normalizer for the two representative market indexes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
import time
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol

import pandas as pd

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota


MARKET_INDEX_FAMILY = "MARKET_INDEX"
MAPPING_CONTRACT_VERSION = "KRX_MARKET_INDEX_MAP_V01"
MARKET_INDEX_SOURCE_NAME = "KRX_OPEN_API_MARKET_INDEX"
FETCH_MODE = "DAILY_MARKET_SNAPSHOT_KRX_OPEN_API"
INDEX_COLUMNS = (
    "date", "family", "source_index_class", "index_code", "index_name",
    "open", "high", "low", "close", "volume", "trading_value",
)
_RAW_FIELDS = {
    "open": "OPNPRC_IDX",
    "high": "HGPRC_IDX",
    "low": "LWPRC_IDX",
    "close": "CLSPRC_IDX",
    "volume": "ACC_TRDVOL",
    "trading_value": "ACC_TRDVAL",
}


def _immutable_mapping(entries: Mapping[str, Mapping[str, str]]) -> Mapping[str, Mapping[str, str]]:
    return MappingProxyType({code: MappingProxyType(dict(values)) for code, values in entries.items()})


KRX_MARKET_INDEX_MAP = _immutable_mapping(
    {
        "1001": {
            "index_code": "1001",
            "family": MARKET_INDEX_FAMILY,
            "market": "KOSPI",
            "source_api": "kospi_dd_trd",
            "endpoint": "/idx/kospi_dd_trd",
            "source_index_class": "KOSPI",
            "source_index_name": "코스피",
        },
        "2001": {
            "index_code": "2001",
            "family": MARKET_INDEX_FAMILY,
            "market": "KOSDAQ",
            "source_api": "kosdaq_dd_trd",
            "endpoint": "/idx/kosdaq_dd_trd",
            "source_index_class": "KOSDAQ",
            "source_index_name": "코스닥",
        },
    }
)


class KrxMarketIndexError(MarketDataError):
    """Fail-closed error with a stable migration diagnostic code."""

    def __init__(self, error_code: str, message: str = "", *, diagnostic: Mapping[str, Any] | None = None) -> None:
        self.error_code = str(error_code)
        self.diagnostic = dict(diagnostic or {})
        detail = f": {message}" if message else ""
        super().__init__(f"{self.error_code}{detail}")


class SnapshotClient(Protocol):
    request_count: int
    retry_count: int
    audit: list[dict[str, Any]]
    status_counts: dict[str, int]

    def fetch(self, endpoint_path: str, date: str, *, quota_endpoint_key: str | None = None) -> Any:
        ...


def mapping_contract_as_dict() -> dict[str, dict[str, str]]:
    return {code: dict(values) for code, values in KRX_MARKET_INDEX_MAP.items()}


def mapping_contract_sha256() -> str:
    payload = json.dumps(mapping_contract_as_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _date_text(value: str | date) -> str:
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OverflowError) as exc:
        raise KrxMarketIndexError("KRX_INDEX_INVALID_DATE", repr(value)) from exc


def _records(response: Any) -> list[Mapping[str, Any]]:
    records_key = getattr(response, "records_key", None)
    if records_key not in (None, "OutBlock_1"):
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", "records key must be OutBlock_1", diagnostic={"records_key": records_key})
    return [row for row in (getattr(response, "records", ()) or ()) if isinstance(row, Mapping)]


def _number(value: Any, *, field: str, date_text: str, integer: bool = False, positive: bool = False) -> float | int:
    if value is None or (isinstance(value, str) and not value.strip()):
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", f"missing {field}", diagnostic={"date": date_text, "field": field})
    try:
        number = Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", f"invalid {field}", diagnostic={"date": date_text, "field": field}) from exc
    if not number.is_finite() or (integer and number != number.to_integral_value()):
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", f"non-finite/non-integer {field}", diagnostic={"date": date_text, "field": field})
    if positive and number <= 0:
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", f"non-positive {field}", diagnostic={"date": date_text, "field": field})
    if not positive and number < 0:
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", f"negative {field}", diagnostic={"date": date_text, "field": field})
    return int(number) if integer else float(number)


def _canonical_row(rows: Iterable[Mapping[str, Any]], contract: Mapping[str, str], date_text: str) -> dict[str, Any]:
    expected_date = date_text.replace("-", "")
    matches = [
        row for row in rows
        if str(row.get("IDX_CLSS", "")).strip() == contract["source_index_class"]
        and str(row.get("IDX_NM", "")).strip() == contract["source_index_name"]
    ]
    if not matches:
        raise KrxMarketIndexError(
            "BLOCKED_KRX_INDEX_SCHEMA",
            "canonical representative row missing",
            diagnostic={"index_code": contract["index_code"], "source_index_name": contract["source_index_name"]},
        )
    if len(matches) != 1:
        raise KrxMarketIndexError(
            "BLOCKED_KRX_INDEX_SCHEMA",
            "canonical representative row is not unique",
            diagnostic={"index_code": contract["index_code"], "match_count": len(matches)},
        )
    raw = matches[0]
    bas_dd = "".join(ch for ch in str(raw.get("BAS_DD", "")) if ch.isdigit())
    if bas_dd != expected_date:
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", "BAS_DD mismatch", diagnostic={"expected": expected_date, "actual": bas_dd})
    values: dict[str, Any] = {
        field: _number(raw.get(source_field), field=field, date_text=date_text, integer=field == "volume", positive=field in {"open", "high", "low", "close"})
        for field, source_field in _RAW_FIELDS.items()
    }
    if not (
        values["high"] >= values["open"]
        and values["high"] >= values["low"]
        and values["high"] >= values["close"]
        and values["low"] <= values["open"]
        and values["low"] <= values["close"]
    ):
        raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", "OHLC relation invalid", diagnostic={"date": date_text, "index_code": contract["index_code"]})
    return {
        "date": date_text,
        "family": MARKET_INDEX_FAMILY,
        "source_index_class": contract["source_index_class"],
        "index_code": contract["index_code"],
        "index_name": contract["source_index_name"],
        **values,
    }


def normalize_market_index_response(response: Any, contract: Mapping[str, str], date_text: str) -> dict[str, Any] | None:
    """Select one exact representative row; return None only for empty response."""

    status = getattr(response, "http_status", 200)
    if status != 200:
        raise KrxMarketIndexError("BLOCKED_KRX_TRANSPORT", f"HTTP {status}", diagnostic={"http_status": status})
    rows = _records(response)
    if not rows:
        return None
    return _canonical_row(rows, contract, date_text)


def normalize_snapshot(response: Any, contract: Mapping[str, str], date_text: str) -> dict[str, Any] | None:
    """Compatibility alias for callers that use the shorter selector name."""

    return normalize_market_index_response(response, contract, date_text)


class KrxMarketIndexBuilder:
    """Fetch and normalize KOSPI/KOSDAQ representative daily snapshots."""

    def __init__(
        self,
        *,
        client: SnapshotClient | None = None,
        auth_key: str | None = None,
        quota: LocalKrxOpenApiQuota | None = None,
        max_requests: int = 80,
        throttle_seconds: float = 0.0,
        sleeper: Any = time.sleep,
    ) -> None:
        self._throttle_seconds = max(0.0, float(throttle_seconds))
        self._sleeper = sleeper
        if client is not None:
            self.client = client
        else:
            key = (auth_key or os.getenv("KRX_OPEN_API_AUTH_KEY", "")).strip()
            if not key:
                raise ValueError("KRX_OPEN_API_AUTH_KEY is required for market index build")
            self.client = KrxOpenApiClient(key, max_requests=max_requests, max_transient_retries=0, quota=quota or LocalKrxOpenApiQuota())

    def _fetch(self, code: str, date_text: str) -> Any:
        contract = KRX_MARKET_INDEX_MAP[code]
        if self._throttle_seconds:
            self._sleeper(self._throttle_seconds)
        return self.client.fetch(contract["endpoint"], date_text, quota_endpoint_key=contract["source_api"])

    def fetch_date(self, date_value: str | date) -> tuple[pd.DataFrame, dict[str, Any]]:
        date_text = _date_text(date_value)
        responses = {code: self._fetch(code, date_text) for code in ("1001", "2001")}
        normalized = {code: normalize_market_index_response(responses[code], KRX_MARKET_INDEX_MAP[code], date_text) for code in ("1001", "2001")}
        if normalized["1001"] is None and normalized["2001"] is None:
            return pd.DataFrame(columns=list(INDEX_COLUMNS)), {"date": date_text, "status": "NO_DATA", "row_count": 0}
        if normalized["1001"] is None or normalized["2001"] is None:
            raise KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", "asymmetric empty market snapshot", diagnostic={"date": date_text})
        frame = pd.DataFrame([normalized["1001"], normalized["2001"]], columns=list(INDEX_COLUMNS))
        return frame, {"date": date_text, "status": "COMPLETE", "row_count": 2}

    def build(self, trading_dates: Iterable[str | date]) -> tuple[pd.DataFrame, dict[str, Any]]:
        requested_dates = tuple(trading_dates)
        rows: list[pd.DataFrame] = []
        no_data_dates: list[str] = []
        for value in requested_dates:
            frame, report = self.fetch_date(value)
            if report["status"] == "NO_DATA":
                no_data_dates.append(report["date"])
            else:
                rows.append(frame)
        combined = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame(columns=list(INDEX_COLUMNS))
        if not combined.empty:
            combined = combined.sort_values(["date", "index_code"], kind="mergesort").reset_index(drop=True)
        return combined, {
            "requested_date_count": len(requested_dates),
            "complete_date_count": int(combined["date"].nunique()) if not combined.empty else 0,
            "no_data_date_count": len(no_data_dates),
            "no_data_dates": no_data_dates,
            "request_count": int(getattr(self.client, "request_count", 0)),
            "retry_count": int(getattr(self.client, "retry_count", 0)),
        }


__all__ = [
    "FETCH_MODE",
    "INDEX_COLUMNS",
    "KRX_MARKET_INDEX_MAP",
    "MARKET_INDEX_FAMILY",
    "MARKET_INDEX_SOURCE_NAME",
    "MAPPING_CONTRACT_VERSION",
    "KrxMarketIndexBuilder",
    "KrxMarketIndexError",
    "mapping_contract_as_dict",
    "mapping_contract_sha256",
    "normalize_market_index_response",
    "normalize_snapshot",
]
