"""Offline mapping, snapshot, calendar and quota tests for market migration."""

from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_price_provider import IndexPriceDataProvider
from trend_scanner.data.krx_market_index import (
    INDEX_COLUMNS,
    KRX_MARKET_INDEX_MAP,
    KrxMarketIndexBuilder,
    mapping_contract_sha256,
)
from scripts import migrate_market_index_krx_v01 as migration


class FakeResponse:
    def __init__(self, records, status: int = 200):
        self.records = tuple(records)
        self.http_status = status
        self.records_key = "OutBlock_1"


def _row(api: str, date: str, name: str, *, close: str = "100.00") -> dict[str, str]:
    cls = "KOSPI" if api == "kospi_dd_trd" else "KOSDAQ"
    return {"BAS_DD": date.replace("-", ""), "IDX_CLSS": cls, "IDX_NM": name, "OPNPRC_IDX": "99.00", "HGPRC_IDX": "101.00", "LWPRC_IDX": "98.00", "CLSPRC_IDX": close, "ACC_TRDVOL": "1,000", "ACC_TRDVAL": "2,000", "MKTCAP": "999"}


class FakeClient:
    def __init__(self, *, duplicate: bool = False, missing: bool = False):
        self.calls = []
        self.request_count = 0
        self.retry_count = 0
        self.audit = []
        self.status_counts = {"401": 0, "403": 0, "429": 0, "5xx": 0, "transport_error": 0}
        self.duplicate = duplicate
        self.missing = missing

    def fetch(self, endpoint_path: str, date: str, *, quota_endpoint_key: str | None = None):
        api = endpoint_path.rsplit("/", 1)[-1]
        self.calls.append((api, date))
        self.request_count += 1
        contract = next(item for item in KRX_MARKET_INDEX_MAP.values() if item["source_api"] == api)
        rows = [_row(api, date, contract["source_index_name"]), _row(api, date, f'{contract["source_index_name"]} (외국주포함)', close="")]
        if self.missing:
            rows = rows[1:]
        if self.duplicate:
            rows.append(dict(rows[0]))
        return FakeResponse(rows)


def test_market_index_map_is_immutable() -> None:
    assert len(KRX_MARKET_INDEX_MAP) == 2
    with pytest.raises(TypeError):
        KRX_MARKET_INDEX_MAP["1001"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        KRX_MARKET_INDEX_MAP["1001"]["source_index_name"] = "wrong"  # type: ignore[index]


def test_market_index_map_has_exact_two_entries() -> None:
    assert set(KRX_MARKET_INDEX_MAP) == {"1001", "2001"}
    assert mapping_contract_sha256()


@pytest.mark.parametrize("api,code,name", [("kospi_dd_trd", "1001", "코스피"), ("kosdaq_dd_trd", "2001", "코스닥")])
def test_exact_representative_selected_and_foreign_included_ignored(api: str, code: str, name: str) -> None:
    client = FakeClient()
    frame, report = KrxMarketIndexBuilder(client=client).fetch_date("2026-08-14")
    assert report["status"] == "COMPLETE"
    assert set(frame["index_code"]) == {"1001", "2001"}
    assert all("외국" not in value for value in frame["index_name"])
    assert code in set(frame["index_code"])


@pytest.mark.parametrize("kwargs", [{"duplicate": True}, {"missing": True}])
def test_duplicate_or_missing_representative_fails(kwargs: dict[str, bool]) -> None:
    with pytest.raises(MarketDataError):
        KrxMarketIndexBuilder(client=FakeClient(**kwargs)).fetch_date("2026-08-14")


def test_endpoint_isolation_and_snapshot_contract() -> None:
    client = FakeClient()
    frame, _ = KrxMarketIndexBuilder(client=client).fetch_date("2026-08-14")
    assert list(frame.columns) == list(INDEX_COLUMNS)
    assert len(client.calls) == 2
    assert all("krx_dd_trd" not in endpoint for endpoint, _ in client.calls)


def test_provider_market_build_does_not_call_pykrx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    provider = IndexPriceDataProvider()
    monkeypatch.setattr(provider, "fetch_index_series", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PyKRX market fetch must not run")))
    frame = provider.build_market_index_cache("2026-08-14", "2026-08-14", tmp_path / "market.parquet", tmp_path / "market.meta.json", client=client)
    assert set(frame["index_code"]) == {"1001", "2001"}
    assert len(client.calls) == 2


def test_calendar_uses_paired_manifest_without_business_day_inference() -> None:
    class FakeStore:
        def list_manifest(self):
            return [
                {"market": "KOSPI", "date": "2026-08-14", "status": "COMPLETE"},
                {"market": "KOSDAQ", "date": "2026-08-14", "status": "COMPLETE"},
                {"market": "KOSPI", "date": "2026-08-15", "status": "NO_DATA"},
                {"market": "KOSDAQ", "date": "2026-08-15", "status": "NO_DATA"},
            ]
    summary = migration.derive_raw_trading_calendar("2026-08-14", "2026-08-15", FakeStore())
    assert summary["target_dates"] == ["2026-08-14"]
    assert summary["no_data_dates"] == ["2026-08-15"]


def test_calendar_asymmetry_fails_closed() -> None:
    class FakeStore:
        def list_manifest(self):
            return [{"market": "KOSPI", "date": "2026-08-14", "status": "COMPLETE"}, {"market": "KOSDAQ", "date": "2026-08-14", "status": "NO_DATA"}]
    with pytest.raises(MarketDataError, match="INCONSISTENT"):
        migration.derive_raw_trading_calendar("2026-08-14", "2026-08-14", FakeStore())
