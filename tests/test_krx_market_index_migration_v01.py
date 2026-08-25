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


def _staged_rows(days: list[str]) -> pd.DataFrame:
    rows = []
    for day in days:
        for code, name, source_class in (("1001", "코스피", "KOSPI"), ("2001", "코스닥", "KOSDAQ")):
            rows.append({
                "date": day, "family": "MARKET_INDEX", "source_index_class": source_class,
                "index_code": code, "index_name": name, "open": 99.0, "high": 101.0,
                "low": 98.0, "close": 100.0, "volume": 1, "trading_value": 2.0,
            })
    return pd.DataFrame(rows, columns=list(migration.INDEX_STORE_COLUMNS))


class FakeQuota:
    def __init__(self, remaining_slots: int):
        self.remaining_slots = remaining_slots

    def remaining(self, _endpoint: str) -> dict[str, int]:
        return {"global": self.remaining_slots, "endpoint": self.remaining_slots}

    def get_usage(self) -> dict[str, object]:
        return {"global_total": 0, "endpoint_usage": {}}


def test_existing_pair_validation_accepts_exact_pair_and_rejects_partial() -> None:
    complete = _staged_rows(["2026-08-14"])
    assert migration.validate_complete_staged_date(complete, "2026-08-14")["status"] == "COMPLETE"
    partial = complete[complete["index_code"] == "1001"]
    assert migration.validate_complete_staged_date(partial, "2026-08-14")["status"] == "BLOCKED_STAGING_PAIR_INCOMPLETE"
    extra = pd.concat([complete, complete.iloc[[0]].assign(index_code="9999")], ignore_index=True)
    assert migration.validate_complete_staged_date(extra, "2026-08-14")["status"] == "FAIL_STAGING_PAIR_INVALID"


def test_runner_blocks_corrupted_staging_without_network(monkeypatch: pytest.MonkeyPatch) -> None:
    partial = _staged_rows(["2026-08-14"]).query("index_code == '1001'")
    client = FakeClient()
    monkeypatch.setattr(migration, "_load_staging", lambda: partial)
    runner = migration.MarketIndexMigrationRunner(client=client, quota=FakeQuota(10))
    with pytest.raises(MarketDataError, match="BLOCKED_STAGING_PAIR_INCOMPLETE"):
        runner.run({"target_dates": ["2026-08-14"], "complete_trading_date_count": 1}, resume=True)
    assert client.calls == []


def test_runner_skips_valid_existing_date_without_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _staged_rows(["2026-08-14"])
    client = FakeClient()
    monkeypatch.setattr(migration, "_load_staging", lambda: frame)
    runner = migration.MarketIndexMigrationRunner(client=client, quota=FakeQuota(10))
    result = runner.run({"target_dates": ["2026-08-14"], "complete_trading_date_count": 1}, resume=True)
    assert result["dates_resumed_or_skipped"] == ["2026-08-14"]
    assert client.calls == []


def test_runner_remaining_one_never_fetches_half_date(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(migration, "_load_staging", lambda: pd.DataFrame(columns=list(migration.INDEX_STORE_COLUMNS)))
    runner = migration.MarketIndexMigrationRunner(client=client, quota=FakeQuota(1))
    result = runner.run({"target_dates": ["2026-08-14"], "complete_trading_date_count": 1}, resume=True)
    assert result["blockers"] == ["BACKFILL_PAUSED_QUOTA"]
    assert client.calls == []


def test_runner_remaining_two_fetches_one_whole_date(monkeypatch: pytest.MonkeyPatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(migration, "_load_staging", lambda: pd.DataFrame(columns=list(migration.INDEX_STORE_COLUMNS)))
    monkeypatch.setattr(migration, "_save_staging", lambda *_args, **_kwargs: {})
    runner = migration.MarketIndexMigrationRunner(client=client, quota=FakeQuota(2))
    result = runner.run({"requested_start": "2026-08-14", "requested_end": "2026-08-14", "target_dates": ["2026-08-14"], "complete_trading_date_count": 1}, resume=True)
    assert result["dates_fetched_this_run"] == ["2026-08-14"]
    assert len(client.calls) == 2


def test_runner_publish_flag_fails_closed_without_production_write(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migration, "_load_staging", lambda: _staged_rows(["2026-08-14"]))
    client = FakeClient()
    runner = migration.MarketIndexMigrationRunner(client=client, quota=FakeQuota(10))
    with pytest.raises(MarketDataError, match="PRODUCTION_PUBLISH_REQUIRES_FINALIZATION"):
        runner.run({"target_dates": ["2026-08-14"], "complete_trading_date_count": 1}, publish=True)
    assert client.calls == []


def _reference_as_index_store_frame() -> pd.DataFrame:
    ref = pd.read_parquet(migration.LEGACY_REFERENCE).copy()
    ref["family"] = "MARKET_INDEX"
    ref["source_index_class"] = ref["index_code"].map({"1001": "KOSPI", "2001": "KOSDAQ"})
    return ref[list(migration.INDEX_STORE_COLUMNS)]


def _valid_quota_ledger() -> dict[str, object]:
    return {
        "phase_global_before": 8688, "phase_global_after": 10000, "phase_global_delta": 1312,
        "pilot_delta": 6, "backfill_global_before": 8694, "backfill_global_after": 10000,
        "backfill_delta": 1306, "client_request_count_phase": 1312, "audit_entry_count_phase": 1312,
        "runs": [
            {"global_delta": 6, "client_request_count": 6, "audit_entry_count": 6, "endpoint_deltas": {"kospi_dd_trd": 3, "kosdaq_dd_trd": 3}},
            {"global_delta": 1306, "client_request_count": 1306, "audit_entry_count": 1306, "endpoint_deltas": {"kospi_dd_trd": 653, "kosdaq_dd_trd": 653}},
        ],
    }


def _finalizer_kwargs(frame: pd.DataFrame) -> dict[str, object]:
    return {
        "calendar": {"target_dates": sorted(frame["date"].astype(str).unique())},
        "staging_frame": frame,
        "quota_ledger": _valid_quota_ledger(),
        "provenance_audit": {"status": "PASS", "network_request_count": 0},
        "diff_guard": {"status": "PASS", "git_diff_check": "PASS", "forbidden_changes": []},
        "secret": "",
    }


def test_legacy_parity_uses_reference_scope_and_ignores_new_history() -> None:
    frame = _reference_as_index_store_frame()
    extra = frame.iloc[[0]].copy()
    extra["date"] = "2010-01-04"
    compared, summary = migration.compare_legacy_market_parity(pd.concat([frame, extra], ignore_index=True))
    assert summary["status"] == "PASS"
    assert summary["ignored_krx_outside_reference_scope_count"] == 1
    assert summary["extra_krx_within_reference_scope_count"] == 0
    assert len(compared) == summary["reference_key_count"]


def test_legacy_parity_missing_reference_key_fails() -> None:
    frame = _reference_as_index_store_frame().iloc[1:].copy()
    _, summary = migration.compare_legacy_market_parity(frame)
    assert summary["missing_krx_row_count"] == 1
    assert summary["status"] == "FAIL"


def test_rs_numeric_perturbation_fails() -> None:
    frame = _reference_as_index_store_frame()
    perturbed = frame.copy()
    latest_kospi = perturbed.index[perturbed["index_code"] == "1001"][-1]
    perturbed.loc[latest_kospi, "close"] = float(perturbed.loc[latest_kospi, "close"]) + 1.0
    result = migration.market_rs_parity(perturbed)
    assert result["status"] == "FAIL"
    assert any(case["market_returns_match"] is False or case["market_rs_match"] is False for case in result["cases"].values())


def test_finalizer_failure_paths_never_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _reference_as_index_store_frame()
    writes: list[int] = []
    bad = frame.copy()
    bad.loc[bad.index[0], "close"] = float(bad.loc[bad.index[0], "close"]) + 1.0
    result = migration.finalize_market_index_migration(**_finalizer_kwargs(bad), publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["legacy_ohlc_parity_gate"]["status"] == "FAIL"
    assert result["production_index_store_publish_count"] == 0
    assert writes == []

    quota_bad = _finalizer_kwargs(frame)
    quota_bad["quota_ledger"] = {**_valid_quota_ledger(), "audit_entry_count_phase": 1311}
    result = migration.finalize_market_index_migration(**quota_bad, publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["quota_gate"]["status"] == "FAIL"
    assert result["production_index_store_publish_count"] == 0


def test_finalizer_rs_failure_blocks_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _reference_as_index_store_frame()
    monkeypatch.setattr(migration, "market_rs_parity", lambda *_args, **_kwargs: {"status": "FAIL", "cases": {}})
    writes: list[int] = []
    result = migration.finalize_market_index_migration(**_finalizer_kwargs(frame), publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["market_rs_parity_gate"]["status"] == "FAIL"
    assert result["production_index_store_publish_count"] == 0
    assert writes == []


def test_finalizer_synthetic_all_pass_publishes_once() -> None:
    frame = _reference_as_index_store_frame()
    writes: list[int] = []
    result = migration.finalize_market_index_migration(**_finalizer_kwargs(frame), publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["status"] == "PASS"
    assert result["production_index_store_publish_count"] == 1
    assert writes == [len(frame)]
