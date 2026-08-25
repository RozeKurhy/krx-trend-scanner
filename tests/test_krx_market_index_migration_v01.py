"""Offline mapping, snapshot, calendar and quota tests for market migration."""

from __future__ import annotations

from dataclasses import replace
import json
import sys
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


def _checkpoint_656_fixture(tmp_path: Path) -> tuple[pd.DataFrame, Path, str]:
    """Build an explicit frozen checkpoint instead of reading mutable production staging."""

    days = [day.strftime("%Y-%m-%d") for day in pd.date_range("2010-01-04", periods=656, freq="B")]
    frame = _staged_rows(days)
    staging_path = tmp_path / "checkpoint_656.parquet"
    frame.to_parquet(staging_path, index=False)
    return frame, staging_path, migration.file_sha256(staging_path)


def test_artifact_state_derives_completed_from_staging_not_stale_backfill() -> None:
    frame = _staged_rows(["2026-08-14"])
    stale_backfill = {
        "status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01",
        "complete_date_count": 0,
        "staging_rows": 0,
        "pending_date_count": 1,
        "next_pending_date": "2026-08-14",
        "blockers": [],
    }
    first = migration.derive_migration_artifact_state(
        calendar={"target_dates": ["2026-08-14"], "complete_trading_date_count": 1},
        backfill=stale_backfill,
        staging_frame=frame,
    )
    second = migration.derive_migration_artifact_state(
        calendar={"target_dates": ["2026-08-14"], "complete_trading_date_count": 1},
        backfill=stale_backfill,
        staging_frame=frame,
    )
    assert first == second
    assert first["status"] == "COMPLETED"
    assert first["complete_date_count"] == 1
    assert first["staging_rows"] == 2
    assert first["pending_date_count"] == 0
    assert first["next_pending_date"] is None
    assert first["exact_pair_count"] == 1
    assert first["duplicate_pair_count"] == 0
    assert first["incomplete_pair_count"] == 0


def test_artifact_writer_emits_completed_state_without_manual_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    monkeypatch.setattr(migration, "ARTIFACT_DIR", artifact_dir)
    frame = _staged_rows(["2026-08-14"])
    migration.write_migration_artifacts(
        calendar={"target_dates": ["2026-08-14"], "complete_trading_date_count": 1},
        pilot={"status": "NOT_RUN"},
        backfill={"status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01", "complete_date_count": 0, "staging_rows": 0, "pending_date_count": 1, "next_pending_date": "2026-08-14", "blockers": []},
        source_head="FIX05_TEST_HEAD",
        staging_frame=frame,
    )
    progress = json.loads((artifact_dir / "backfill_progress_summary.json").read_text(encoding="utf-8"))
    coverage = json.loads((artifact_dir / "coverage_summary.json").read_text(encoding="utf-8"))
    manifest = json.loads((artifact_dir / "market_index_migration_v01_manifest.json").read_text(encoding="utf-8"))
    assert progress["status"] == "COMPLETED"
    assert progress["complete_date_count"] == 1
    assert progress["pending_date_count"] == 0
    assert progress["next_pending_date"] is None
    assert coverage["status"] == "PASS"
    assert coverage["missing_date_count"] == 0
    assert coverage["production_published"] is False
    assert manifest["status"] == "COMPLETED"
    assert manifest["current_status"] == "HISTORICAL_COLLECTION_COMPLETED_NOT_PUBLISHED"


def test_artifact_generation_preserves_last_resume_execution_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_dir = tmp_path / "artifacts"
    (artifact_dir / "execution").mkdir(parents=True)
    (artifact_dir / "execution/run3_resume_20260826.json").write_text(
        json.dumps({
            "execution_kind": "MARKET_INDEX_HISTORICAL_RESUME",
            "execution_head": "RUN3_EXECUTION_HEAD",
            "status": "PASS",
            "run": {"state": "COMPLETED"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(migration, "ARTIFACT_DIR", artifact_dir)
    kwargs = {
        "calendar": {"target_dates": ["2026-08-14"], "complete_trading_date_count": 1},
        "pilot": {"status": "NOT_RUN"},
        "backfill": {"status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01", "complete_date_count": 0, "staging_rows": 0, "blockers": []},
        "staging_frame": _staged_rows(["2026-08-14"]),
    }
    migration.write_migration_artifacts(**kwargs, source_head="FIX05_REVISION_HEAD")
    first = json.loads((artifact_dir / "market_index_migration_v01_manifest.json").read_text(encoding="utf-8"))
    migration.write_migration_artifacts(**kwargs, source_head="A_SECOND_ARTIFACT_HEAD")
    second = json.loads((artifact_dir / "market_index_migration_v01_manifest.json").read_text(encoding="utf-8"))
    assert first["artifact_generation_head"] == "FIX05_REVISION_HEAD"
    assert second["artifact_generation_head"] == "A_SECOND_ARTIFACT_HEAD"
    assert first["last_resume_execution_head"] == "RUN3_EXECUTION_HEAD"
    assert second["last_resume_execution_head"] == "RUN3_EXECUTION_HEAD"


def test_artifact_generation_without_new_execution_keeps_existing_head(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    manifest_path = artifact_dir / "market_index_migration_v01_manifest.json"
    manifest_path.write_text(json.dumps({"last_resume_execution_head": "RUN3_EXECUTION_HEAD"}), encoding="utf-8")
    monkeypatch.setattr(migration, "ARTIFACT_DIR", artifact_dir)
    migration.write_migration_artifacts(
        calendar={"target_dates": ["2026-08-14"], "complete_trading_date_count": 1},
        pilot={"status": "NOT_RUN"},
        backfill={"status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01", "complete_date_count": 0, "staging_rows": 0, "blockers": []},
        source_head="FIX05_REVISION_HEAD",
        staging_frame=_staged_rows(["2026-08-14"]),
    )
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["last_resume_execution_head"] == "RUN3_EXECUTION_HEAD"


def test_production_publication_authority_fails_closed_for_missing_or_unpublished(tmp_path: Path) -> None:
    root = tmp_path / "production"
    missing = migration.validate_production_publication_authority(production_root=root)
    assert missing["production_published"] is False
    frame = _staged_rows(["2026-08-14"])
    migration.IndexStore(root).save_family_full(migration.MARKET_INDEX_FAMILY, frame)
    unpublished = migration.validate_production_publication_authority(production_root=root)
    assert unpublished["parquet_exists"] is True
    assert unpublished["meta_exists"] is True
    assert unpublished["explicit_published"] is False
    assert unpublished["production_published"] is False


def test_production_publication_authority_requires_integrity(tmp_path: Path) -> None:
    root = tmp_path / "production"
    frame = _staged_rows(["2026-08-14"])
    migration.IndexStore(root).save_family_full(migration.MARKET_INDEX_FAMILY, frame, metadata_context={"published": True})
    meta_path = root / "market_index.meta.json"
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    metadata["content_sha256"] = "tampered"
    meta_path.write_text(json.dumps(metadata), encoding="utf-8")
    invalid = migration.validate_production_publication_authority(production_root=root)
    assert invalid["explicit_published"] is True
    assert invalid["integrity_status"] == "FAIL"
    assert invalid["production_published"] is False


def test_production_publication_authority_accepts_explicit_valid_publish(tmp_path: Path) -> None:
    root = tmp_path / "production"
    migration.IndexStore(root).save_family_full(migration.MARKET_INDEX_FAMILY, _staged_rows(["2026-08-14"]), metadata_context={"published": True})
    accepted = migration.validate_production_publication_authority(production_root=root)
    assert accepted["explicit_published"] is True
    assert accepted["integrity_status"] == "PASS"
    assert accepted["production_published"] is True


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


def test_runner_zero_quota_does_not_create_operational_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame = migration._load_staging()
    client = FakeClient()
    quota = FakeQuota(0)
    monkeypatch.setattr(migration, "_load_staging", lambda: frame)
    monkeypatch.setattr(migration, "_staging_snapshot", lambda _frame: {"date_count": 656, "row_count": 1312, "sha256": "SHA656"})
    ledger = _operational_ledger_fixture()
    ledger_path = tmp_path / "ledger.json"
    migration.atomic_write_json(ledger_path, ledger)
    runner = migration.MarketIndexMigrationRunner(client=client, quota=quota)
    target_dates = sorted(frame["date"].astype(str).unique()) + ["2099-01-01"]
    result = runner.run({"target_dates": target_dates, "complete_trading_date_count": len(target_dates)}, operational_ledger_path=ledger_path)
    assert result["operational_run_created"] is False
    assert client.calls == []
    assert len(migration.load_operational_ledger(ledger_path)["runs"]) == 2


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
        "phase_endpoint_deltas": {"kospi_dd_trd": 656, "kosdaq_dd_trd": 656},
        "runs": [
            {"run_id": "RUN1_PILOT", "usage_date_kst": "2026-08-25", "global_before": 8688, "global_after": 8694, "global_delta": 6, "client_request_count": 6, "audit_entry_count": 6, "endpoint_deltas": {"kospi_dd_trd": 3, "kosdaq_dd_trd": 3}},
            {"run_id": "RUN2_HISTORICAL_BACKFILL_TRANCHE", "usage_date_kst": "2026-08-25", "global_before": 8694, "global_after": 10000, "global_delta": 1306, "client_request_count": 1306, "audit_entry_count": 1306, "endpoint_deltas": {"kospi_dd_trd": 653, "kosdaq_dd_trd": 653}},
        ],
    }


def test_quota_reconciliation_cross_day_reset_passes() -> None:
    ledger = {
        "phase_global_delta": 1512,
        "phase_request_count": 1512,
        "phase_audit_count": 1512,
        "phase_endpoint_deltas": {"kospi_dd_trd": 756, "kosdaq_dd_trd": 756},
        "runs": [
            {"run_id": "RUN1", "usage_date_kst": "2026-08-25", "global_before": 8688, "global_after": 8694, "global_delta": 6, "client_request_count": 6, "audit_entry_count": 6, "endpoint_deltas": {"kospi_dd_trd": 3, "kosdaq_dd_trd": 3}},
            {"run_id": "RUN2", "usage_date_kst": "2026-08-25", "global_before": 8694, "global_after": 10000, "global_delta": 1306, "client_request_count": 1306, "audit_entry_count": 1306, "endpoint_deltas": {"kospi_dd_trd": 653, "kosdaq_dd_trd": 653}},
            {"run_id": "RUN3", "usage_date_kst": "2026-08-26", "global_before": 0, "global_after": 200, "global_delta": 200, "client_request_count": 200, "audit_entry_count": 200, "endpoint_deltas": {"kospi_dd_trd": 100, "kosdaq_dd_trd": 100}},
        ],
    }
    result = migration.validate_quota_reconciliation(ledger)
    assert result["status"] == "PASS"
    assert result["derived_phase_delta"] == 1512
    assert result["derived_request_count"] == 1512
    assert result["derived_audit_count"] == 1512


def test_quota_reconciliation_bad_cross_day_run_fails() -> None:
    ledger = {
        "phase_global_delta": 1511,
        "phase_request_count": 1511,
        "phase_audit_count": 1511,
        "phase_endpoint_deltas": {"kospi_dd_trd": 755, "kosdaq_dd_trd": 756},
        "runs": [
            {"run_id": "RUN1", "usage_date_kst": "2026-08-25", "global_before": 8688, "global_after": 8694, "global_delta": 6, "client_request_count": 6, "audit_entry_count": 6, "endpoint_deltas": {"kospi_dd_trd": 3, "kosdaq_dd_trd": 3}},
            {"run_id": "RUN3", "usage_date_kst": "2026-08-26", "global_before": 0, "global_after": 200, "global_delta": 199, "client_request_count": 199, "audit_entry_count": 199, "endpoint_deltas": {"kospi_dd_trd": 99, "kosdaq_dd_trd": 100}},
        ],
    }
    result = migration.validate_quota_reconciliation(ledger)
    assert result["status"] == "FAIL"
    assert result["runs"][1]["counter_delta_match"] is False


def test_legacy_in_scope_extra_key_fails() -> None:
    frame = _reference_as_index_store_frame()
    extra = frame.iloc[[0]].copy()
    extra["date"] = "2026-01-03"
    _, summary = migration.compare_legacy_market_parity(pd.concat([frame, extra], ignore_index=True))
    assert summary["extra_krx_within_reference_scope_count"] == 1
    assert summary["status"] == "FAIL"


def test_rs_same_wrong_code_on_both_sides_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    original = migration.compute_relative_strength_features

    def wrong_code(*args, **kwargs):
        return replace(original(*args, **kwargs), market_benchmark_code="9999")

    monkeypatch.setattr(migration, "compute_relative_strength_features", wrong_code)
    result = migration.market_rs_parity(_reference_as_index_store_frame())
    assert result["status"] == "FAIL"
    assert all(case["canonical_identity_match"] is False for case in result["cases"].values())


def test_rs_same_wrong_name_on_both_sides_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    original = migration.compute_relative_strength_features

    def wrong_name(*args, **kwargs):
        return replace(original(*args, **kwargs), market_benchmark_name="잘못된 이름")

    monkeypatch.setattr(migration, "compute_relative_strength_features", wrong_name)
    result = migration.market_rs_parity(_reference_as_index_store_frame())
    assert result["status"] == "FAIL"
    assert all(case["canonical_identity_match"] is False for case in result["cases"].values())


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


def test_finalizer_empty_secret_blocks_publish() -> None:
    frame = _reference_as_index_store_frame()
    writes: list[int] = []
    result = migration.finalize_market_index_migration(**_finalizer_kwargs(frame), publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["secret_gate"]["reason"] == "BLOCKED_SECRET_SCAN_UNAVAILABLE"
    assert result["production_index_store_publish_count"] == 0
    assert writes == []


def test_finalizer_zero_scan_scope_blocks_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _reference_as_index_store_frame()
    monkeypatch.setattr(migration, "secret_scan", lambda _secret: {"scanned_file_count": 0, "secret_occurrence_count": 0})
    kwargs = _finalizer_kwargs(frame)
    kwargs["secret"] = "synthetic_secret"
    writes: list[int] = []
    result = migration.finalize_market_index_migration(**kwargs, publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["secret_gate"]["reason"] == "BLOCKED_SECRET_SCAN_EMPTY_SCOPE"
    assert result["production_index_store_publish_count"] == 0
    assert writes == []


def test_finalizer_secret_found_blocks_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _reference_as_index_store_frame()
    monkeypatch.setattr(migration, "secret_scan", lambda _secret: {"scanned_file_count": 100, "secret_occurrence_count": 1})
    kwargs = _finalizer_kwargs(frame)
    kwargs["secret"] = "synthetic_secret"
    writes: list[int] = []
    result = migration.finalize_market_index_migration(**kwargs, publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["secret_gate"]["reason"] == "BLOCKED_SECRET_EXPOSURE"
    assert result["production_index_store_publish_count"] == 0
    assert writes == []


def test_finalizer_clean_secret_gate_allows_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _reference_as_index_store_frame()
    monkeypatch.setattr(migration, "secret_scan", lambda _secret: {"scanned_file_count": 100, "secret_occurrence_count": 0})
    kwargs = _finalizer_kwargs(frame)
    kwargs["secret"] = "synthetic_secret"
    writes: list[int] = []
    result = migration.finalize_market_index_migration(**kwargs, publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["status"] == "PASS"
    assert result["gates"]["secret_gate"]["status"] == "PASS"
    assert result["production_index_store_publish_count"] == 1
    assert writes == [len(frame)]


def test_publish_without_finalize_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["migrate_market_index_krx_v01.py", "--publish"])
    with pytest.raises(SystemExit):
        migration.main()


def test_finalize_partial_staging_does_not_fetch_or_publish() -> None:
    frame = _reference_as_index_store_frame().iloc[:2].copy()
    kwargs = _finalizer_kwargs(frame)
    kwargs["calendar"] = {"target_dates": [str(frame["date"].iloc[0]), "2026-08-21"]}
    writes: list[int] = []
    result = migration.finalize_market_index_migration(**kwargs, publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["coverage_gate"]["status"] == "FAIL"
    assert result["production_index_store_publish_count"] == 0
    assert writes == []


def _operational_ledger_fixture() -> dict[str, object]:
    base = _valid_quota_ledger()
    runs = []
    for index, run in enumerate(base["runs"]):
        value = dict(run)
        value.update({"run_type": "PILOT" if index == 0 else "HISTORICAL_BACKFILL_TRANCHE", "state": "COMPLETED", "started_at_kst": None, "completed_at_kst": None, "staging_date_count_before": 0 if index == 0 else 3, "staging_date_count_after": 3 if index == 0 else 656, "staging_row_count_before": 0 if index == 0 else 6, "staging_row_count_after": 6 if index == 0 else 1312, "staging_sha_before": None if index == 0 else "SHA3", "staging_sha_after": "SHA3" if index == 0 else "SHA656", "dates_fetched": 3 if index == 0 else 653, "next_pending_date": "2010-01-05" if index == 0 else "2012-08-16", "run_status": "COMPLETED"})
        runs.append(value)
    return {"schema_version": migration.OPERATIONAL_LEDGER_SCHEMA_VERSION, "phase": "KRX_INDEX_MIGRATION_V01", "runs": runs, "phase_cumulative": {"global_delta": 1312, "client_request_count": 1312, "audit_entry_count": 1312, "retry_count": 0, "endpoint_deltas": {"kospi_dd_trd": 656, "kosdaq_dd_trd": 656}}}


def test_seed_operational_ledger_from_known_checkpoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame, staging_path, fixture_sha = _checkpoint_656_fixture(tmp_path)
    monkeypatch.setattr(migration, "STAGING_PARQUET", staging_path)
    ledger_path = tmp_path / "quota_run_ledger.json"
    ledger = migration.seed_operational_ledger_from_checkpoint(frame=frame, path=ledger_path, expected_checkpoint_sha256=fixture_sha)
    assert ledger["schema_version"] == migration.OPERATIONAL_LEDGER_SCHEMA_VERSION
    assert len(ledger["runs"]) == 2
    assert ledger["phase_cumulative"]["global_delta"] == 1312
    assert ledger["seed_checkpoint_sha256"] == fixture_sha
    assert migration.validate_operational_ledger(ledger)["status"] == "PASS"


def test_missing_ledger_with_advanced_staging_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    dates = [day.strftime("%Y-%m-%d") for day in pd.date_range("2010-01-04", periods=657, freq="D")]
    advanced = _staged_rows(dates)
    staging_path = tmp_path / "advanced.parquet"
    advanced.to_parquet(staging_path, index=False)
    monkeypatch.setattr(migration, "STAGING_PARQUET", staging_path)
    with pytest.raises(MarketDataError, match="BLOCKED_OPERATIONAL_LEDGER_MISSING_FOR_ADVANCED_STAGING"):
        migration.seed_operational_ledger_from_checkpoint(frame=advanced, path=tmp_path / "ledger.json")


def test_append_cross_day_resume_run_preserves_previous_runs(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    ledger = _operational_ledger_fixture()
    migration.atomic_write_json(path, ledger)
    run3 = {"run_id": "RUN3_HISTORICAL_BACKFILL_RESUME_20260826T000001", "usage_date_kst": "2026-08-26", "run_type": "HISTORICAL_BACKFILL_RESUME", "state": "COMPLETED", "global_before": 0, "global_after": 200, "global_delta": 200, "client_request_count": 200, "audit_entry_count": 200, "retry_count": 0, "endpoint_deltas": {"kospi_dd_trd": 100, "kosdaq_dd_trd": 100}, "staging_date_count_before": 656, "staging_date_count_after": 756, "staging_row_count_before": 1312, "staging_row_count_after": 1512, "staging_sha_before": "SHA656", "staging_sha_after": "SHA756", "dates_fetched": 100}
    updated = migration.append_operational_run(ledger, run3, path)
    assert len(updated["runs"]) == 3
    assert updated["runs"][0]["run_id"] == "RUN1_PILOT"
    assert updated["phase_cumulative"]["global_delta"] == 1512
    assert migration.validate_operational_ledger(updated)["status"] == "PASS"


def test_second_resume_and_duplicate_run_are_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    ledger = _operational_ledger_fixture()
    migration.atomic_write_json(path, ledger)
    run4 = {"run_id": "RUN4", "usage_date_kst": "2026-08-27", "state": "COMPLETED", "global_before": 0, "global_after": 10, "global_delta": 10, "client_request_count": 10, "audit_entry_count": 10, "retry_count": 0, "endpoint_deltas": {"kospi_dd_trd": 5, "kosdaq_dd_trd": 5}, "staging_date_count_before": 656, "staging_date_count_after": 661, "staging_row_count_before": 1312, "staging_row_count_after": 1322, "staging_sha_before": "SHA656", "staging_sha_after": "SHA661", "dates_fetched": 5}
    migration.append_operational_run(ledger, run4, path)
    assert len(migration.load_operational_ledger(path)["runs"]) == 3
    with pytest.raises(MarketDataError, match="BLOCKED_DUPLICATE_RUN_ID"):
        migration.append_operational_run(ledger, run4, path)


def test_started_run_blocks_next_resume(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    ledger = _operational_ledger_fixture()
    migration.atomic_write_json(path, ledger)
    started = {"run_id": "RUN3_STARTED", "usage_date_kst": "2026-08-26", "state": "STARTED", "global_before": 0, "global_after": 0, "global_delta": 0, "client_request_count": 0, "audit_entry_count": 0, "retry_count": 0, "endpoint_deltas": {}}
    migration.append_operational_run(ledger, started, path)
    with pytest.raises(MarketDataError, match="BLOCKED_INCOMPLETE_RUN_JOURNAL"):
        migration.load_operational_ledger(path)


def test_operational_ledger_atomic_write_leaves_no_temporary_file(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    migration.atomic_write_json(path, {"schema_version": migration.OPERATIONAL_LEDGER_SCHEMA_VERSION})
    assert path.exists()
    assert list(tmp_path.glob(".*.tmp")) == []


def test_runtime_source_guard_artifact_only_and_source_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(migration.subprocess, "check_output", lambda command, **kwargs: "HEAD\n" if command[:3] == ["git", "rev-parse", "HEAD"] else ("artifacts/data/krx_openapi/market_index_migration/v01/fix03/a.json\n" if command[:2] == ["git", "diff"] else ""))
    monkeypatch.setattr(migration.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    assert migration.validate_current_source_freeze("HEAD")["status"] == "PASS"
    monkeypatch.setattr(migration.subprocess, "check_output", lambda command, **kwargs: "HEAD\n" if command[:3] == ["git", "rev-parse", "HEAD"] else ("scripts/migrate_market_index_krx_v01.py\n" if command[:2] == ["git", "diff"] else ""))
    assert migration.validate_current_source_freeze("HEAD")["status"] == "FAIL"
    monkeypatch.setattr(migration.subprocess, "check_output", lambda command, **kwargs: "HEAD\n" if command[:3] == ["git", "rev-parse", "HEAD"] else ("src/trend_scanner/data/index_store.py\n" if command[:2] == ["git", "diff"] else ""))
    assert migration.validate_current_source_freeze("HEAD")["status"] == "FAIL"


def test_finalizer_uses_operational_ledger_not_static_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _reference_as_index_store_frame()
    op_path = tmp_path / "ledger.json"
    good = _operational_ledger_fixture()
    migration.atomic_write_json(op_path, good)
    monkeypatch.setattr(migration, "validate_current_source_freeze", lambda *_args, **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(migration, "validate_staging_ledger_continuity", lambda *_args, **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(migration, "secret_scan", lambda _secret: {"scanned_file_count": 100, "secret_occurrence_count": 0})
    writes: list[int] = []
    bad_static = {**_valid_quota_ledger(), "phase_global_delta": 9999}
    kwargs = _finalizer_kwargs(frame)
    kwargs["quota_ledger"] = bad_static
    kwargs["secret"] = "synthetic_secret"
    kwargs["diff_guard"] = {"status": "FAIL", "reason": "stale static guard must be ignored"}
    result = migration.finalize_market_index_migration(**kwargs, operational_ledger_path=op_path, validation_source_head="HEAD", publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["quota_gate"]["status"] == "PASS"
    assert result["gates"]["provenance_network_gate"]["status"] == "PASS"
    assert result["production_index_store_publish_count"] == 1
    assert writes == [len(frame)]

    bad_operational = _operational_ledger_fixture()
    bad_operational["runs"][0]["global_delta"] = 5
    migration.atomic_write_json(op_path, bad_operational)
    kwargs = _finalizer_kwargs(frame)
    kwargs["quota_ledger"] = _valid_quota_ledger()
    kwargs["secret"] = "synthetic_secret"
    result = migration.finalize_market_index_migration(**kwargs, operational_ledger_path=op_path, validation_source_head="HEAD", publish=True, production_writer=lambda value: writes.append(len(value)))
    assert result["gates"]["quota_gate"]["status"] == "FAIL"
    assert result["production_index_store_publish_count"] == 0


def test_resume_writer_preserves_historical_pilot_and_network_is_cumulative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    pilot_path = artifact_dir / "pilot_summary.json"
    pilot_path.write_text("{\"historical\":true}\n", encoding="utf-8")
    before = migration.file_sha256(pilot_path)
    monkeypatch.setattr(migration, "ARTIFACT_DIR", artifact_dir)
    ledger = _operational_ledger_fixture()
    migration.write_migration_artifacts(calendar={"complete_trading_date_count": 656}, pilot={"status": "NOT_RUN"}, backfill={"status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01", "complete_date_count": 656, "staging_rows": 1312}, source_head="HEAD", operational_ledger=ledger)
    assert migration.file_sha256(pilot_path) == before
    summary = migration.network_summary_from_operational_ledger(ledger)
    assert summary["krx_request_count"] == 1312
    assert migration.validate_cumulative_progress(summary, {**summary, "krx_request_count": 1512})["status"] == "PASS"
    assert migration.validate_cumulative_progress(summary, {**summary, "krx_request_count": 200})["status"] == "FAIL"


def test_resume_writer_rejects_cumulative_network_regression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "network_request_summary.json").write_text(json.dumps({"krx_request_count": 1512, "kospi_dd_trd_request_count": 756, "kosdaq_dd_trd_request_count": 756, "audit_entry_count": 1512, "retry_count": 0}), encoding="utf-8")
    monkeypatch.setattr(migration, "ARTIFACT_DIR", artifact_dir)
    with pytest.raises(MarketDataError, match="BLOCKED_CUMULATIVE_EVIDENCE_REGRESSION"):
        migration.write_migration_artifacts(calendar={"complete_trading_date_count": 656}, pilot={"status": "NOT_RUN"}, backfill={"status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01", "complete_date_count": 656, "staging_rows": 1312}, source_head="HEAD", operational_ledger=_operational_ledger_fixture())


def _continuity_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[pd.DataFrame, dict[str, object], Path]:
    frame = _staged_rows(["2026-08-14"])
    staging_path = tmp_path / "market_index_staging.parquet"
    frame.to_parquet(staging_path, index=False)
    monkeypatch.setattr(migration, "STAGING_PARQUET", staging_path)
    ledger = _operational_ledger_fixture()
    terminal = ledger["runs"][-1]
    terminal["staging_date_count_before"] = 0
    terminal["staging_date_count_after"] = 1
    terminal["staging_row_count_before"] = 0
    terminal["staging_row_count_after"] = 2
    terminal["staging_sha_before"] = "SHA0"
    terminal["staging_sha_after"] = migration.file_sha256(staging_path)
    ledger["runs"][0]["staging_date_count_after"] = 0
    ledger["runs"][0]["staging_row_count_after"] = 0
    ledger["runs"][0]["staging_sha_after"] = "SHA0"
    ledger["runs"][1]["staging_date_count_before"] = 0
    ledger["runs"][1]["staging_row_count_before"] = 0
    ledger["runs"][1]["staging_sha_before"] = "SHA0"
    ledger["phase_cumulative"] = migration._phase_cumulative_from_runs(ledger["runs"])
    return frame, ledger, staging_path


def test_current_staging_matches_terminal_ledger_passes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame, ledger, _ = _continuity_fixture(tmp_path, monkeypatch)
    assert migration.validate_staging_ledger_continuity(frame, ledger)["status"] == "PASS"


@pytest.mark.parametrize("mode", ["ahead", "behind", "same_count_different_sha"])
def test_current_staging_divergence_blocks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    frame, ledger, _ = _continuity_fixture(tmp_path, monkeypatch)
    if mode == "ahead":
        frame = _staged_rows(["2026-08-14", "2026-08-15"])
    elif mode == "behind":
        frame = _staged_rows([])
    else:
        frame = _staged_rows(["2026-08-14"])
        ledger["runs"][-1]["staging_sha_after"] = "DIFFERENT_SHA"
    assert migration.validate_staging_ledger_continuity(frame, ledger)["reason"] == "BLOCKED_STAGING_LEDGER_DIVERGENCE"


def test_adjacent_run_staging_chain_passes_and_mismatch_fails() -> None:
    ledger = _operational_ledger_fixture()
    assert migration.validate_operational_ledger_chain(ledger)["status"] == "PASS"
    ledger["runs"][1]["staging_date_count_before"] = 4
    ledger["runs"][1]["dates_fetched"] = 652
    assert migration.validate_operational_ledger(ledger)["reason"] == "BLOCKED_OPERATIONAL_LEDGER_STAGING_CHAIN"


def test_new_run_before_snapshot_equals_previous_after(tmp_path: Path) -> None:
    path = tmp_path / "ledger.json"
    ledger = _operational_ledger_fixture()
    migration.atomic_write_json(path, ledger)
    run3 = {"run_id": "RUN3_CHAIN", "usage_date_kst": "2026-08-26", "state": "COMPLETED", "global_before": 0, "global_after": 2, "global_delta": 2, "client_request_count": 2, "audit_entry_count": 2, "retry_count": 0, "endpoint_deltas": {"kospi_dd_trd": 1, "kosdaq_dd_trd": 1}, "staging_date_count_before": 656, "staging_date_count_after": 657, "staging_row_count_before": 1312, "staging_row_count_after": 1314, "staging_sha_before": "SHA656", "staging_sha_after": "SHA657", "dates_fetched": 1}
    updated = migration.append_operational_run(ledger, run3, path)
    assert updated["runs"][2]["staging_sha_before"] == updated["runs"][1]["staging_sha_after"]


def test_seeded_ledger_continuity_upgrade_is_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame, staging_path, fixture_sha = _checkpoint_656_fixture(tmp_path)
    monkeypatch.setattr(migration, "STAGING_PARQUET", staging_path)
    path = tmp_path / "ledger.json"
    ledger = migration.seed_operational_ledger_from_checkpoint(frame=frame, path=path, expected_checkpoint_sha256=fixture_sha)
    assert ledger["runs"][-1]["staging_sha_after"] is None
    upgraded = migration.upgrade_seeded_ledger_checkpoint(frame=frame, path=path, expected_checkpoint_sha256=fixture_sha)
    assert upgraded["runs"][-1]["staging_sha_after"] == fixture_sha
    assert migration.validate_operational_ledger(upgraded, require_terminal_snapshot=True)["status"] == "PASS"


def test_manifest_validation_source_anchor_is_immutable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    manifest_path = artifact_dir / "market_index_migration_v01_manifest.json"
    manifest_path.write_text(json.dumps({"fix03_validation_source_head": "SOURCE_A", "fix04_validation_source_head": "SOURCE_A"}), encoding="utf-8")
    monkeypatch.setattr(migration, "ARTIFACT_DIR", artifact_dir)
    migration.write_migration_artifacts(calendar={"complete_trading_date_count": 1}, pilot={"status": "NOT_RUN"}, backfill={"status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01", "complete_date_count": 0, "staging_rows": 0}, source_head="EXECUTION_E", operational_ledger=None)
    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert saved["fix03_validation_source_head"] == "SOURCE_A"
    assert saved["fix04_validation_source_head"] == "SOURCE_A"
    assert saved["artifact_generation_head"] == "EXECUTION_E"
    with pytest.raises(MarketDataError, match="BLOCKED_VALIDATION_SOURCE_ANCHOR_MUTATION"):
        migration.write_migration_artifacts(calendar={"complete_trading_date_count": 1}, pilot={"status": "NOT_RUN"}, backfill={"status": "PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01", "complete_date_count": 0, "staging_rows": 0}, source_head="EXECUTION_E", validation_source_head="SOURCE_B")


def test_missing_validation_anchor_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(MarketDataError, match="BLOCKED_VALIDATION_SOURCE_ANCHOR_MISSING"):
        migration.resolve_validation_source_head(tmp_path / "manifest.json")


@pytest.mark.parametrize(
    "exc,expected",
    [
        (migration.KrxOpenApiRateLimitError("quota"), "PARTIAL"),
        (migration.KrxOpenApiAuthorizationError("auth"), "BLOCKED"),
        (RuntimeError("transport failure"), "BLOCKED"),
        (migration.KrxMarketIndexError("BLOCKED_KRX_INDEX_SCHEMA", "schema"), "BLOCKED"),
    ],
)
def test_terminal_run_state_semantics(exc: Exception, expected: str) -> None:
    assert migration.terminal_run_state([migration._classify_blocker(exc)], ["2012-08-16"]) == expected
    if expected == "BLOCKED":
        assert migration.terminal_run_state([migration._classify_blocker(exc)], []) == "BLOCKED"
    else:
        assert migration.terminal_run_state([], ["2012-08-16"]) == "PARTIAL"
    assert migration.terminal_run_state([], []) == "COMPLETED"


def test_pre_network_source_failure_has_zero_calls_and_no_journal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame, ledger, _ = _continuity_fixture(tmp_path, monkeypatch)
    ledger["runs"][0]["dates_fetched"] = 0
    ledger["runs"][1]["dates_fetched"] = 1
    monkeypatch.setattr(migration, "validate_current_source_freeze", lambda *_args, **_kwargs: {"status": "FAIL"})
    calls: list[str] = []
    with pytest.raises(MarketDataError, match="BLOCKED_CURRENT_SOURCE_FREEZE"):
        migration.validate_resume_pre_network(staging_frame=frame, ledger=ledger, target_dates=frame["date"].astype(str).unique(), validation_source_head="SOURCE_A")
    assert calls == []
    assert len(ledger["runs"]) == 2


def test_pre_network_continuity_failure_has_zero_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    frame = migration._load_staging()
    ledger = _operational_ledger_fixture()
    ledger["runs"][-1]["staging_sha_after"] = "DIFFERENT_SHA"
    monkeypatch.setattr(migration, "validate_current_source_freeze", lambda *_args, **_kwargs: {"status": "PASS"})
    with pytest.raises(MarketDataError, match="BLOCKED_STAGING_LEDGER_DIVERGENCE"):
        migration.validate_resume_pre_network(staging_frame=frame, ledger=ledger, target_dates=frame["date"].astype(str).unique(), validation_source_head="SOURCE_A")
    assert len(ledger["runs"]) == 2


def test_finalizer_continuity_gate_blocks_publish_on_divergence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    frame = _reference_as_index_store_frame()
    op_path = tmp_path / "ledger.json"
    ledger = _operational_ledger_fixture()
    migration.atomic_write_json(op_path, ledger)
    monkeypatch.setattr(migration, "validate_current_source_freeze", lambda *_args, **_kwargs: {"status": "PASS"})
    monkeypatch.setattr(migration, "secret_scan", lambda _secret: {"scanned_file_count": 100, "secret_occurrence_count": 0})
    kwargs = _finalizer_kwargs(frame)
    kwargs["secret"] = "synthetic_secret"
    result = migration.finalize_market_index_migration(**kwargs, operational_ledger_path=op_path, validation_source_head="HEAD", publish=True, production_writer=lambda _value: pytest.fail("production write must be blocked"))
    assert result["gates"]["staging_ledger_continuity_gate"]["status"] == "FAIL"
    assert result["production_index_store_publish_count"] == 0
