"""Focused offline tests for the MARKET_INDEX rolling refresh path."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.index_store import INDEX_STORE_COLUMNS, IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.krx_market_index import KRX_MARKET_INDEX_MAP, KrxMarketIndexBuilder
from scripts.refresh_market_index_v01 import (
    MarketIndexRollingRefreshError,
    append_market_index_rows,
    derive_incremental_trading_dates,
    refresh_market_index,
    validate_market_index_frame,
)


def _manifest(*rows: tuple[str, str, str]) -> list[dict[str, str]]:
    return [{"market": market, "date": day, "status": status} for market, day, status in rows]


class FakeRawStore:
    def __init__(self, rows: list[dict[str, str]]) -> None:
        self.rows = rows

    def list_manifest(self) -> list[dict[str, str]]:
        return list(self.rows)


class FakeResponse:
    def __init__(self, records: list[dict[str, str]]) -> None:
        self.records = tuple(records)
        self.records_key = "OutBlock_1"
        self.http_status = 200


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.request_count = 0
        self.retry_count = 0
        self.audit: list[dict[str, object]] = []

    def fetch(self, endpoint_path: str, date: str, *, quota_endpoint_key: str | None = None) -> FakeResponse:
        self.calls.append((endpoint_path, date))
        self.request_count += 1
        code = "1001" if endpoint_path.endswith("kospi_dd_trd") else "2001"
        contract = KRX_MARKET_INDEX_MAP[code]
        return FakeResponse([{
            "BAS_DD": date.replace("-", ""),
            "IDX_CLSS": contract["source_index_class"],
            "IDX_NM": contract["source_index_name"],
            "OPNPRC_IDX": "99.0",
            "HGPRC_IDX": "101.0",
            "LWPRC_IDX": "98.0",
            "CLSPRC_IDX": "100.0",
            "ACC_TRDVOL": "1000",
            "ACC_TRDVAL": "2000",
        }])


def _index_rows(days: list[str]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for day in days:
        for code, contract in KRX_MARKET_INDEX_MAP.items():
            rows.append({
                "date": day,
                "family": MARKET_INDEX_FAMILY,
                "source_index_class": contract["source_index_class"],
                "index_code": code,
                "index_name": contract["source_index_name"],
                "open": 99.0,
                "high": 101.0,
                "low": 98.0,
                "close": 100.0,
                "volume": 1000,
                "trading_value": 2000.0,
            })
    return pd.DataFrame(rows, columns=list(INDEX_STORE_COLUMNS))


def test_paired_complete_raw_manifest_derivation() -> None:
    raw = FakeRawStore(_manifest(
        ("KOSPI", "2026-09-07", "COMPLETE"),
        ("KOSDAQ", "2026-09-07", "COMPLETE"),
        ("KOSPI", "2026-09-08", "COMPLETE"),
        ("KOSDAQ", "2026-09-08", "COMPLETE"),
    ))
    result = derive_incremental_trading_dates(raw, "2026-09-04", "2026-09-11")
    assert result["missing_dates"] == ["2026-09-07", "2026-09-08"]


def test_only_dates_after_boundary_are_fetched(tmp_path: Path) -> None:
    raw = FakeRawStore(_manifest(
        ("KOSPI", "2026-09-04", "COMPLETE"),
        ("KOSDAQ", "2026-09-04", "COMPLETE"),
        ("KOSPI", "2026-09-07", "COMPLETE"),
        ("KOSDAQ", "2026-09-07", "COMPLETE"),
    ))
    client = FakeClient()
    # Seed the pre-run production family at the observed boundary.
    store = IndexStore(tmp_path / "market-index-rolling-test-store")
    store.save_family_full(MARKET_INDEX_FAMILY, _index_rows(["2026-09-04"]))
    result = refresh_market_index(
        target_as_of="2026-09-07",
        raw_store=raw,
        index_store=store,
        builder=KrxMarketIndexBuilder(client=client),
    )
    assert result["fetched_dates"] == ["2026-09-07"]
    assert {date for _, date in client.calls} == {"2026-09-07"}


def test_both_codes_required_per_date() -> None:
    frame = _index_rows(["2026-09-07"]).query("index_code == '1001'")
    with pytest.raises(MarketIndexRollingRefreshError, match="INCOMPLETE_PAIR"):
        validate_market_index_frame(frame)


def test_incomplete_raw_pair_fails_closed() -> None:
    raw = FakeRawStore(_manifest(("KOSPI", "2026-09-07", "COMPLETE")))
    with pytest.raises(MarketIndexRollingRefreshError, match="INCOMPLETE_PAIR"):
        derive_incremental_trading_dates(raw, "2026-09-04", "2026-09-11")


def test_duplicate_pair_fails_closed() -> None:
    frame = pd.concat([_index_rows(["2026-09-07"]), _index_rows(["2026-09-07"]).iloc[[0]]], ignore_index=True)
    with pytest.raises(MarketIndexRollingRefreshError):
        validate_market_index_frame(frame)


def test_already_complete_target_is_idempotent_without_duplicate() -> None:
    raw = FakeRawStore(_manifest(
        ("KOSPI", "2026-09-07", "COMPLETE"),
        ("KOSDAQ", "2026-09-07", "COMPLETE"),
    ))
    result = derive_incremental_trading_dates(raw, "2026-09-04", "2026-09-07", existing_frame=_index_rows(["2026-09-07"]))
    assert result["missing_dates"] == []
    assert result["already_present_dates"] == ["2026-09-07"]


def test_historical_rows_unchanged_when_increment_is_appended() -> None:
    current = _index_rows(["2026-09-04"])
    increment = _index_rows(["2026-09-07"])
    merged = append_market_index_rows(current, increment, expected_dates=["2026-09-07"])
    pd.testing.assert_frame_equal(
        current.sort_values(list(INDEX_STORE_COLUMNS)).reset_index(drop=True),
        merged.loc[merged["date"] <= "2026-09-04"].sort_values(list(INDEX_STORE_COLUMNS)).reset_index(drop=True),
        check_dtype=False,
    )


def test_mapping_contract_equals_exact_two_codes() -> None:
    assert set(KRX_MARKET_INDEX_MAP) == {"1001", "2001"}
