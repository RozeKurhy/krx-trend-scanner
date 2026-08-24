"""Deterministic tests for the production KRX native sector cache contract."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.index_price_provider import IndexPriceDataProvider
from trend_scanner.data.krx_sector_index import (
    KOSDAQ_SECTOR_CODES,
    KOSPI_SECTOR_CODES,
    KRX_NATIVE_SECTOR_INDEX_MAP,
    KrxSectorIndexCacheBuilder,
    MAPPING_CONTRACT_VERSION,
    mapping_contract_sha256,
)


class FakeResponse:
    def __init__(self, records, status: int = 200):
        self.records = tuple(records)
        self.http_status = status


class FakeSnapshotClient:
    def __init__(self, *, empty_dates: set[tuple[str, str]] | None = None, fail: set[tuple[str, str]] | None = None):
        self.empty_dates = empty_dates or set()
        self.fail = fail or set()
        self.calls: list[tuple[str, str]] = []
        self.request_count = 0
        self.retry_count = 0
        self.audit: list[dict] = []
        self.status_counts = {"401": 0, "403": 0, "429": 0, "5xx": 0, "transport_error": 0}

    def fetch(self, endpoint_path: str, date: str, *, quota_endpoint_key: str | None = None):
        api = endpoint_path.rsplit("/", 1)[-1]
        key = (api, date)
        self.calls.append(key)
        self.request_count += 1
        if key in self.fail:
            raise RuntimeError("synthetic endpoint failure")
        if key in self.empty_dates:
            return FakeResponse([])
        rows = []
        for contract in KRX_NATIVE_SECTOR_INDEX_MAP.values():
            if contract["source_api"] != api:
                continue
            value = "100.00"
            rows.append({
                "BAS_DD": date.replace("-", ""),
                "IDX_CLSS": contract["idx_class"],
                "IDX_NM": contract["idx_name"],
                "OPNPRC_IDX": value,
                "HGPRC_IDX": value,
                "LWPRC_IDX": value,
                "CLSPRC_IDX": value,
                "ACC_TRDVOL": "1,000",
                "ACC_TRDVAL": "2,000",
            })
        return FakeResponse(rows)


def _build(tmp_path: Path, client: FakeSnapshotClient, *, start: str = "2026-08-20", end: str = "2026-08-21", minimum: int = 1):
    return KrxSectorIndexCacheBuilder(client=client).build(
        start_date=start,
        end_date=end,
        output_parquet=tmp_path / "sector.parquet",
        output_meta=tmp_path / "sector.meta.json",
        minimum_sessions=minimum,
    )


def test_contract_is_immutable_and_has_46_native_entries() -> None:
    assert len(KRX_NATIVE_SECTOR_INDEX_MAP) == 46
    assert len(KOSPI_SECTOR_CODES) == 24
    assert len(KOSDAQ_SECTOR_CODES) == 22
    with pytest.raises(TypeError):
        KRX_NATIVE_SECTOR_INDEX_MAP["1005"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        KRX_NATIVE_SECTOR_INDEX_MAP["1005"]["idx_name"] = "wrong"  # type: ignore[index]


def test_contract_matches_committed_mapping_artifact_one_to_one() -> None:
    artifact = Path(__file__).parents[1] / "artifacts/data/krx_openapi/index_mapping/v01/sector_code_mapping.csv"
    with artifact.open(encoding="utf-8", newline="") as handle:
        rows = {row["sector_code"]: row for row in csv.DictReader(handle)}
    assert set(rows) == set(KRX_NATIVE_SECTOR_INDEX_MAP)
    for code, contract in KRX_NATIVE_SECTOR_INDEX_MAP.items():
        row = rows[code]
        assert row["market"] == contract["market"]
        assert row["source_api"] == contract["source_api"]
        assert row["official_idx_class"] == contract["idx_class"]
        assert row["official_idx_name"] == contract["idx_name"]
        assert row["mapping_status"] == "EXACT_MARKET_SERIES_MATCH"


def test_snapshot_builder_normalizes_46_rows_with_two_market_calls_per_date(tmp_path: Path) -> None:
    client = FakeSnapshotClient()
    result = _build(tmp_path, client, start="2026-08-20", end="2026-08-21", minimum=2)
    assert len(result.dataframe) == 92
    assert result.dataframe["index_code"].nunique() == 46
    assert result.dataframe["date"].nunique() == 2
    assert len(client.calls) == 4
    assert result.report["cache_missing_sector_count"] == 0
    metadata = json.loads((tmp_path / "sector.meta.json").read_text(encoding="utf-8"))
    assert metadata["source_name"] == "KRX_OPEN_API_SECTOR_INDEX"
    assert metadata["fetch_mode"] == "DAILY_MARKET_SNAPSHOT_KRX_OPEN_API"
    assert metadata["mapping_contract_version"] == MAPPING_CONTRACT_VERSION
    assert metadata["mapping_contract_sha256"] == mapping_contract_sha256()


def test_non_trading_empty_snapshot_is_not_an_error(tmp_path: Path) -> None:
    client = FakeSnapshotClient(empty_dates={("kospi_dd_trd", "2026-08-20"), ("kosdaq_dd_trd", "2026-08-20")})
    result = _build(tmp_path, client, minimum=1)
    assert result.trading_dates == ("2026-08-21",)
    assert result.report["non_trading_date_count"] == 1


@pytest.mark.parametrize("kind", ["missing", "duplicate", "wrong_date"])
def test_snapshot_identity_and_date_invariants_fail_closed(tmp_path: Path, kind: str) -> None:
    client = FakeSnapshotClient()
    original_fetch = client.fetch

    def broken_fetch(endpoint_path: str, date: str, *, quota_endpoint_key: str | None = None):
        response = original_fetch(endpoint_path, date, quota_endpoint_key=quota_endpoint_key)
        if endpoint_path.endswith("kospi_dd_trd") and date == "2026-08-20":
            rows = list(response.records)
            if kind == "missing":
                rows = rows[:-1]
            elif kind == "duplicate":
                rows.append(dict(rows[0]))
            else:
                rows[0] = {**rows[0], "BAS_DD": "20260819"}
            return FakeResponse(rows)
        return response

    client.fetch = broken_fetch  # type: ignore[method-assign]
    with pytest.raises(MarketDataError):
        _build(tmp_path, client)


def test_incremental_update_is_idempotent_and_replaces_same_date(tmp_path: Path) -> None:
    client = FakeSnapshotClient()
    result = _build(tmp_path, client, start="2026-08-20", end="2026-08-20")
    updated = KrxSectorIndexCacheBuilder(client=client).update(
        target_date="2026-08-20", output_parquet=tmp_path / "sector.parquet", output_meta=tmp_path / "sector.meta.json",
    )
    assert len(updated.dataframe) == len(result.dataframe) == 46
    assert updated.dataframe.duplicated(["date", "index_code"]).sum() == 0
    second = KrxSectorIndexCacheBuilder(client=client).update(
        target_date="2026-08-20", output_parquet=tmp_path / "sector.parquet", output_meta=tmp_path / "sector.meta.json",
    )
    assert len(second.dataframe) == 46
    assert second.dataframe.duplicated(["date", "index_code"]).sum() == 0
    assert (tmp_path / "sector.parquet").exists()


def test_partial_api_failure_does_not_replace_existing_cache(tmp_path: Path) -> None:
    good = FakeSnapshotClient()
    _build(tmp_path, good, start="2026-08-20", end="2026-08-20")
    original = (tmp_path / "sector.parquet").read_bytes()
    failing = FakeSnapshotClient(fail={("kosdaq_dd_trd", "2026-08-21")})
    with pytest.raises(RuntimeError):
        KrxSectorIndexCacheBuilder(client=failing).update(
            target_date="2026-08-21", output_parquet=tmp_path / "sector.parquet", output_meta=tmp_path / "sector.meta.json",
        )
    assert (tmp_path / "sector.parquet").read_bytes() == original


def test_provider_sector_build_does_not_use_pykrx_fetch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeSnapshotClient()
    provider = IndexPriceDataProvider()
    monkeypatch.setattr(provider, "fetch_index_series", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("PyKRX sector fetch must not run")))
    result = provider.build_sector_index_cache(
        list(KRX_NATIVE_SECTOR_INDEX_MAP), "2026-08-20", "2026-08-20", tmp_path / "sector.parquet", tmp_path / "sector.meta.json",
        client=client, minimum_sessions=1,
    )
    assert len(result) == 46
    assert len(client.calls) == 2
