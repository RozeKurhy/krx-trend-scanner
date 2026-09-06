"""Strict raw ETF daily snapshot provider for the official KRX Open API.

ETF rows use the same lossless raw partition schema as common stocks.  The
provider has its own endpoint contract and never falls back to PyKRX, HTML,
Naver, legacy parquet, or reconstructed values.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from trend_scanner.data.krx_openapi_client import KrxOpenApiClient
from trend_scanner.data.krx_raw_stock_provider import (
    RAW_COLUMNS,
    RAW_NUMERIC_COLUMNS,
    KrxRawStockSnapshotError,
    _parse_int,
    _snapshot_error,
    _source_date,
    is_valid_krx_short_code,
    normalize_bas_dd,
    validate_raw_snapshot_frame,
)


ETF_ENDPOINT = "/etp/etf_bydd_trd"
ETF_SOURCE_FIELDS = {
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
ETF_AUTHORITY = "KRX Open API ETF Daily Trading Information"


def _typed_empty_snapshot() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.Series([], dtype="datetime64[ns]"),
            "ticker": pd.Series([], dtype="string"),
            **{field: pd.Series([], dtype="int64") for field in RAW_NUMERIC_COLUMNS},
        },
        columns=list(RAW_COLUMNS),
    )


class KrxRawEtfSnapshotProvider:
    """Map one official KRX ETF date response into the raw stock schema."""

    endpoint = ETF_ENDPOINT
    authority = ETF_AUTHORITY

    def __init__(self, client: KrxOpenApiClient) -> None:
        self.client = client

    def fetch_snapshot(self, bas_dd: Any) -> pd.DataFrame:
        requested_date = normalize_bas_dd(bas_dd)
        response = self.client.fetch(
            ETF_ENDPOINT,
            requested_date,
            quota_endpoint_key=ETF_ENDPOINT.strip("/"),
        )
        response_diagnostic = {
            "http_status": getattr(response, "http_status", None),
            "transport_error_type": getattr(response, "error_type", None),
            "records_key": getattr(response, "records_key", None),
            "record_count": len(getattr(response, "records", ()) or ()),
            "top_level_keys": list(getattr(response, "top_level_keys", ()) or ()),
            "record_keys": sorted(
                {str(key) for row in (getattr(response, "records", ()) or ()) for key in row.keys()}
            )[:64],
        }
        if response.http_status != 200:
            raise _snapshot_error("RAW_ETF_SNAPSHOT_HTTP_STATUS", str(response.http_status), **response_diagnostic)
        if response.records_key != "OutBlock_1":
            raise _snapshot_error("RAW_ETF_SNAPSHOT_RECORDS_KEY", **response_diagnostic)
        if not getattr(response, "records", ()):
            return _typed_empty_snapshot()

        rows: list[dict[str, Any]] = []
        for source_row in response.records:
            missing = [source for source in ETF_SOURCE_FIELDS.values() if source not in source_row]
            if missing:
                raise _snapshot_error(
                    "RAW_ETF_SNAPSHOT_REQUIRED_FIELD_MISSING",
                    str(missing),
                    **response_diagnostic,
                    required_missing_fields=missing,
                )
            source_date = _source_date(source_row[ETF_SOURCE_FIELDS["date"]])
            if source_date != requested_date.replace("-", ""):
                raise _snapshot_error(
                    "RAW_ETF_SNAPSHOT_DATE_MISMATCH",
                    **response_diagnostic,
                    source_date_sample_shape="8-digit" if source_date else "invalid",
                )
            ticker = str(source_row[ETF_SOURCE_FIELDS["ticker"]])
            if not is_valid_krx_short_code(ticker):
                raise _snapshot_error(
                    "RAW_ETF_SNAPSHOT_TICKER_FORMAT_ERROR",
                    **response_diagnostic,
                    ticker_sample_shape=f"length={len(ticker)}" if ticker else "empty",
                )
            row: dict[str, Any] = {"date": pd.Timestamp(requested_date), "ticker": ticker}
            for field in RAW_NUMERIC_COLUMNS:
                try:
                    row[field] = _parse_int(
                        source_row[ETF_SOURCE_FIELDS[field]],
                        field,
                        strictly_positive=field == "listed_shares",
                    )
                except KrxRawStockSnapshotError as exc:
                    raise KrxRawStockSnapshotError(
                        exc.error_code,
                        str(exc).split(": ", 1)[-1],
                        diagnostic={**response_diagnostic, **exc.diagnostic, "numeric_field_failure": field},
                    ) from exc
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


__all__ = ["ETF_AUTHORITY", "ETF_ENDPOINT", "ETF_SOURCE_FIELDS", "KrxRawEtfSnapshotProvider"]
