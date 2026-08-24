from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from trend_scanner.data.krx_raw_stock_provider import (
    MARKET_ENDPOINTS,
    RAW_COLUMNS,
    KrxRawStockSnapshotError,
    KrxRawStockSnapshotProvider,
)


@dataclass
class _Response:
    http_status: int = 200
    records_key: str | None = "OutBlock_1"
    records: tuple[dict, ...] = ()


class _Client:
    def __init__(self, response: _Response):
        self.response = response
        self.calls: list[tuple[str, str, str]] = []

    def fetch(self, endpoint, date, *, quota_endpoint_key):
        self.calls.append((endpoint, date, quota_endpoint_key))
        return self.response


def _row(**overrides):
    row = {
        "BAS_DD": "20260821",
        "ISU_CD": "005930",
        "TDD_OPNPRC": "100",
        "TDD_HGPRC": "110",
        "TDD_LWPRC": "90",
        "TDD_CLSPRC": "105",
        "ACC_TRDVOL": "1,000",
        "ACC_TRDVAL": "2,000",
        "MKTCAP": "3,000",
        "LIST_SHRS": "4,000",
    }
    row.update(overrides)
    return row


@pytest.mark.parametrize("market,endpoint", [("KOSPI", "/sto/stk_bydd_trd"), ("KOSDAQ", "/sto/ksq_bydd_trd")])
def test_exact_endpoint_mapping_and_source_field_mapping(market, endpoint):
    client = _Client(_Response(records=(_row(),)))
    result = KrxRawStockSnapshotProvider(client).fetch_market_snapshot(market, "2026-08-21")
    assert client.calls == [(endpoint, "2026-08-21", endpoint.strip("/"))]
    assert tuple(result.columns) == RAW_COLUMNS
    assert result.iloc[0].to_dict() == {
        "date": pd.Timestamp("2026-08-21"),
        "ticker": "005930",
        "open": 100,
        "high": 110,
        "low": 90,
        "close": 105,
        "volume": 1000,
        "trading_value": 2000,
        "market_cap": 3000,
        "listed_shares": 4000,
    }


def test_outblock_1_is_required():
    client = _Client(_Response(records_key="Other", records=(_row(),)))
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_RECORDS_KEY"):
        KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")


def test_http_status_is_fail_closed():
    client = _Client(_Response(http_status=500))
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_HTTP_STATUS"):
        KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")


def test_source_date_mismatch_is_rejected():
    client = _Client(_Response(records=(_row(BAS_DD="20260820"),)))
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_DATE_MISMATCH"):
        KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")


def test_duplicate_ticker_is_rejected():
    client = _Client(_Response(records=(_row(), _row(TDD_CLSPRC="106"))))
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_DUPLICATE_TICKER"):
        KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")


@pytest.mark.parametrize("ticker", ["5930", "KR7005930003", "ABC930"])
def test_ticker_must_be_six_digits(ticker):
    client = _Client(_Response(records=(_row(ISU_CD=ticker),)))
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_TICKER_FORMAT_ERROR"):
        KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")


def test_numeric_parse_failure_is_rejected():
    client = _Client(_Response(records=(_row(ACC_TRDVOL="not-a-number"),)))
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_NUMERIC_PARSE_ERROR"):
        KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")


def test_empty_response_is_typed_and_preserved():
    client = _Client(_Response(records=()))
    result = KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")
    assert result.empty
    assert tuple(result.columns) == RAW_COLUMNS
    assert str(result["date"].dtype) == "datetime64[ns]"
    assert str(result["volume"].dtype) == "int64"


def test_zero_volume_and_zero_ohlc_are_not_filtered_or_corrected():
    client = _Client(_Response(records=(_row(TDD_OPNPRC="0", TDD_HGPRC="0", TDD_LWPRC="0", TDD_CLSPRC="0", ACC_TRDVOL="0"),)))
    result = KrxRawStockSnapshotProvider(client).fetch_market_snapshot("KOSPI", "20260821")
    assert result.loc[0, "volume"] == 0
    assert result.loc[0, "close"] == 0
    assert result.loc[0, "open"] == 0


def test_missing_field_and_negative_values_fail_closed():
    missing = _row()
    del missing["LIST_SHRS"]
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_REQUIRED_FIELD_MISSING"):
        KrxRawStockSnapshotProvider(_Client(_Response(records=(missing,)))).fetch_market_snapshot("KOSPI", "20260821")
    with pytest.raises(KrxRawStockSnapshotError, match="RAW_SNAPSHOT_NUMERIC_RANGE_ERROR"):
        KrxRawStockSnapshotProvider(_Client(_Response(records=(_row(ACC_TRDVAL="-1"),)))).fetch_market_snapshot("KOSPI", "20260821")


def test_no_one_won_correction_or_adjusted_calculation():
    result = KrxRawStockSnapshotProvider(_Client(_Response(records=(_row(TDD_OPNPRC="100", TDD_HGPRC="110", TDD_LWPRC="90", TDD_CLSPRC="105"),)))).fetch_market_snapshot("KOSPI", "20260821")
    assert result.loc[0, ["open", "high", "low", "close"]].tolist() == [100, 110, 90, 105]
