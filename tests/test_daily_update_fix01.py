"""Focused offline contracts for Daily Update Foundation FIX01."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.corporate_action_detector import CorporateActionSnapshot
from trend_scanner.data.corporate_action_refresh import CorporateActionRefreshService
from trend_scanner.data.corporate_action_state_store import CorporateActionStateStore
from trend_scanner.data.daily_update_foundation import DailyUpdateFoundation, DailyUpdateFoundationError
from trend_scanner.data.krx_historical_instrument_acquisition import (
    load_bounded_basic_info_snapshots,
)
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.rolling_market_data_refresh import (
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    PitExtensionResult,
    RollingAdjustedPriceUpdater,
    RollingAuthorityManifest,
    RollingRawMarketUpdater,
    build_rolling_pit_extension,
    load_effective_common_adjusted_population,
    migrate_rolling_authority_manifest,
    write_merged_pit_extension,
    write_rolling_authority,
)


def _frame(days: list[str], base: float = 10.0) -> pd.DataFrame:
    values = [base + index for index in range(len(days))]
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 1 for value in values],
            "low": [value - 1 for value in values],
            "close": [value + 0.5 for value in values],
        },
        index=pd.DatetimeIndex(days),
    )


def _extension() -> PitExtensionResult:
    return PitExtensionResult(
        merged_intervals=(
            {
                "ticker": "000001",
                "isu_cd": "KR7000000001",
                "market": "KOSPI",
                "state": "COMMON",
                "effective_from": "2026-08-21",
                "effective_to": "2026-08-21",
            },
        ),
        merged_calendar_dates=("2026-08-21",),
        extension_start="2026-08-21",
        extension_end="2026-08-21",
        frozen_interval_count=1,
        merged_interval_count=1,
        new_ticker_count=0,
    )


def _legacy_authority(tmp_path: Path) -> Path:
    authority = tmp_path / "authority"
    refs = write_merged_pit_extension(
        _extension(),
        authority,
        built_against_certified_through="2026-08-21",
        target_as_of="2026-08-21",
    )
    manifest = RollingAuthorityManifest(
        authority_version="ROLLING_MARKET_DATA_V01",
        certified_through="2026-08-21",
        leg_boundaries={
            "common_raw": "2026-08-21",
            "common_adjusted": "2026-08-21",
            "etf_raw": "2026-08-21",
            "etf_adjusted": "2026-08-21",
        },
        previous_boundary=None,
        raw_store_version="KRX_RAW_STOCK_V01",
        adjusted_store_version="ADJUSTED_PRICE_STORE_V02",
        instrument_contract_version="REPOSITORY_V2_INSTRUMENT_CONTRACT_V01",
        bootstrap_source=None,
        generated_at="2026-09-18T00:00:00+00:00",
    )
    assert refs.merged_pit_frontier == "2026-08-21"
    write_rolling_authority(manifest, authority)
    return authority


def _basic_info_payload(day: str, market: str) -> dict[str, list[dict[str, str]]]:
    market_name = market
    return {
        "OutBlock_1": [
            {
                "ISU_CD": "KR7000000001",
                "ISU_SRT_CD": "000001",
                "MKT_TP_NM": market_name,
                "LIST_DD": day.replace("-", ""),
                "SECUGRP_NM": "주권",
                "KIND_STKCERT_TP_NM": "보통주",
                "SECT_TP_NM": "제조업",
            }
        ]
    }


def _write_bounded_basic_info(root: Path, checkpoint_path: Path, day: str) -> None:
    entries: dict[str, dict[str, object]] = {}
    for market, endpoint in (("KOSPI", "stk_isu_base_info"), ("KOSDAQ", "ksq_isu_base_info")):
        payload = _basic_info_payload(day, market)
        content = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        path = root / day[:4] / day.replace("-", "") / f"{market}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        entries[f"{day.replace('-', '')}|{market}|{endpoint}"] = {
            "status": "COMPLETE",
            "schema_validation": "PASS",
            "identity_validation": "PASS",
            "row_count": 1,
            "raw_content_sha256": hashlib.sha256(content).hexdigest(),
            "raw_path": str(path),
        }
    checkpoint_path.write_text(json.dumps({"entries": entries}), encoding="utf-8")


def test_bounded_basic_info_ignores_frozen_extras_and_blocks_hash_mismatch(tmp_path):
    root = tmp_path / "basic_info"
    checkpoint = tmp_path / "checkpoint.json"
    _write_bounded_basic_info(root, checkpoint, "2026-08-24")
    extra = root / "2025" / "20250102" / "KOSPI.json"
    extra.parent.mkdir(parents=True)
    extra.write_text("{}", encoding="utf-8")

    ready = load_bounded_basic_info_snapshots(root, ["2026-08-24"], checkpoint_path=checkpoint)
    assert ready.ready
    assert ready.expected_files == 2
    assert ready.current_files == 2

    (root / "2026" / "20260824" / "KOSPI.json").write_text("tampered", encoding="utf-8")
    blocked = load_bounded_basic_info_snapshots(root, ["2026-08-24"], checkpoint_path=checkpoint)
    assert not blocked.ready
    assert any("raw hash mismatch" in error for error in blocked.errors)


def test_rolling_pit_extension_uses_bounded_authority(monkeypatch, tmp_path):
    root = tmp_path / "basic_info"
    checkpoint = tmp_path / "checkpoint.json"
    _write_bounded_basic_info(root, checkpoint, "2026-08-24")
    frozen_pit = tmp_path / "frozen_pit.json"
    frozen_calendar = tmp_path / "frozen_calendar.json"
    frozen_pit.write_text(json.dumps({"intervals": list(_extension().merged_intervals)}), encoding="utf-8")
    frozen_calendar.write_text(json.dumps({"trading_dates": ["2026-08-21"]}), encoding="utf-8")

    def classify(_snapshots, *, expected_dates):
        assert expected_dates == ["2026-08-24"]
        return {
            "000002": [
                {
                    "classification": "COMMON",
                    "ISU_CD": "KR7000000002",
                    "market": "KOSPI",
                    "effective_from": "2026-08-24",
                    "effective_to": "2026-08-24",
                }
            ]
        }

    supplemental_authority = {
        ("000002", "KR7000000002"): {
            "decision": "COMMON",
            "decision_reason_code": "TEST_EXACT_IDENTITY_SUPPLEMENT",
        }
    }
    seen_supplemental: dict[str, object] = {}

    def classify_with_supplemental(_snapshots, *, expected_dates, supplemental_authority=None):
        seen_supplemental["value"] = supplemental_authority
        return classify(_snapshots, expected_dates=expected_dates)

    monkeypatch.setattr(
        "trend_scanner.data.rolling_market_data_refresh.classify_full_universe",
        classify_with_supplemental,
    )
    result = build_rolling_pit_extension(
        extension_calendar_dates=["2026-08-24"],
        frozen_pit_path=frozen_pit,
        historical_calendar_path=frozen_calendar,
        basic_info_raw_root=root,
        acquisition_checkpoint_path=checkpoint,
        supplemental_authority=supplemental_authority,
    )
    assert result.new_ticker_count == 1
    assert {interval["ticker"] for interval in result.merged_intervals} == {"000001", "000002"}
    assert seen_supplemental["value"] == supplemental_authority


def test_legacy_authority_migration_is_explicit_idempotent_and_boundary_safe(tmp_path):
    authority = _legacy_authority(tmp_path)
    before = json.loads((authority / "manifest.json").read_text(encoding="utf-8"))
    pending = migrate_rolling_authority_manifest(authority, apply=False)
    assert pending["status"] == "MIGRATION_REQUIRED"
    assert json.loads((authority / "manifest.json").read_text(encoding="utf-8")) == before

    applied = migrate_rolling_authority_manifest(authority, apply=True)
    assert applied["status"] == "MIGRATED"
    assert applied["boundary_unchanged"] is True
    noop = migrate_rolling_authority_manifest(authority, apply=False)
    assert noop["status"] == "NOOP"
    assert json.loads((authority / "manifest.json").read_text(encoding="utf-8"))["certified_through"] == before["certified_through"]


def test_common_adjusted_partial_response_preserves_store_and_boundary(tmp_path):
    pit = tmp_path / "pit.json"
    calendar = tmp_path / "calendar.json"
    pit.write_text(
        json.dumps(
            {
                "intervals": [
                    {
                        "ticker": "000001",
                        "isu_cd": "KR7000000001",
                        "market": "KOSPI",
                        "state": "COMMON",
                        "effective_from": "2026-08-01",
                        "effective_to": "2026-08-03",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    calendar.write_text(json.dumps({"trading_dates": ["2026-08-01", "2026-08-02", "2026-08-03"]}), encoding="utf-8")
    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame(["2026-08-01"]), {"requested_start": "2026-08-01", "requested_end": "2026-08-01"})
    before = (store.base_dir / "000001.parquet").read_bytes()

    class PartialProvider:
        def load_daily(self, _ticker, _start, _end):
            return _frame(["2026-08-02"])

    result = RollingAdjustedPriceUpdater(
        PartialProvider(),
        store,
        pit_path=pit,
        historical_calendar_path=calendar,
    ).refresh(["000001"], "2026-08-01", "2026-08-03")
    assert result["new_boundary"] == "2026-08-01"
    assert result["updated"] == []
    assert result["failures"][0]["error_type"] == "RuntimeError"
    assert (store.base_dir / "000001.parquet").read_bytes() == before


def _empty_raw_frame() -> pd.DataFrame:
    return pd.DataFrame({column: pd.Series(dtype="object") for column in RAW_COLUMNS}, columns=list(RAW_COLUMNS))


def test_paired_no_data_is_terminal_and_second_common_raw_run_is_noop(tmp_path):
    raw = KrxRawStockStore(tmp_path / "raw")
    day = "2026-08-24"
    for market in ("KOSPI", "KOSDAQ"):
        raw.save_snapshot(market, day, _empty_raw_frame(), f"/sto/{market.lower()}")

    class Runner:
        calls = 0

        def run(self, *_args, **_kwargs):
            self.calls += 1
            raise AssertionError("a finalized paired NO_DATA date must not be fetched")

    updater = RollingRawMarketUpdater(Runner(), raw)
    result = updater.refresh("2026-08-21", day, required_dates=[day])
    assert result["updated_date_count"] == 0
    assert result["physical_write_count"] == 0
    assert result["runner_result"]["status"] == "IDEMPOTENT_NOOP"


def test_weekday_paired_no_data_does_not_extend_operating_calendar(tmp_path):
    authority = _legacy_authority(tmp_path)
    migrate_rolling_authority_manifest(authority, apply=True)
    raw = KrxRawStockStore(tmp_path / "raw")
    for day in ("2026-08-21", "2026-08-24"):
        for market in ("KOSPI", "KOSDAQ"):
            raw.save_snapshot(market, day, _empty_raw_frame(), f"/sto/{market.lower()}")

    class NoopPlan:
        def plan(self, *_args, **_kwargs):
            return {"missing_dates": []}

    foundation = DailyUpdateFoundation(
        authority_dir=authority,
        raw_store=raw,
        adjusted_store=AdjustedPriceStore(tmp_path / "adjusted"),
        common_adjusted_tickers=[],
        common_raw_updater=NoopPlan(),
        etf_raw_updater=NoopPlan(),
        common_adjusted_updater=NoopPlan(),
        etf_adjusted_updater=NoopPlan(),
        market_index_plan=lambda _target: {"missing_dates": []},
    )
    plan = foundation.plan("2026-08-24")
    assert plan["authority_extension_candidates"] == []
    assert plan["required_candidate_dates"] == ["2026-08-21"]
    assert plan["common_raw"]["missing_dates"] == []


def test_staged_pit_population_includes_new_common_and_excludes_etf_scope(tmp_path):
    pit = tmp_path / "staged_pit.json"
    pit.write_text(
        json.dumps(
            {
                "intervals": [
                    {"ticker": "000001", "isu_cd": "KR7000000001", "market": "KOSPI", "state": "COMMON", "effective_from": "2026-08-21", "effective_to": "2026-08-24"},
                    {"ticker": "000002", "isu_cd": "KR7000000002", "market": "KOSPI", "state": "COMMON", "effective_from": "2026-08-24", "effective_to": "2026-08-24"},
                    {"ticker": ETF_VALIDATED_ACCEPTANCE_TICKERS[0], "isu_cd": "ETF00000001", "market": "ETF", "state": "COMMON", "effective_from": "2026-08-21", "effective_to": "2026-08-24"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_effective_common_adjusted_population(
        pit,
        etf_acceptance_tickers=ETF_VALIDATED_ACCEPTANCE_TICKERS,
        removed_identity_audit_path=None,
        zero_store_contract_path=None,
        effective_population_path=None,
        identity_as_of="2026-08-24",
    ) == ["000001", "000002"]


def test_daily_foundation_corporate_action_phase_refreshes_only_dirty_ticker(tmp_path):
    adjusted = AdjustedPriceStore(tmp_path / "adjusted")
    old = _frame(["2024-01-02", "2024-01-03", "2024-01-04"])
    adjusted.save_full("005930", old, {"requested_start": "2024-01-02", "requested_end": "2024-01-04"})
    state = CorporateActionStateStore(tmp_path / "corporate_action.sqlite3")
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-01", 100, 5000))
    state.evaluate_and_record(CorporateActionSnapshot("005930", "2024-01-02", 100, 5000))

    class Provider:
        calls: list[tuple[str, str, str]] = []

        def load_daily(self, ticker, start, end):
            self.calls.append((ticker, start, end))
            return _frame(["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"], base=20)

    provider = Provider()
    foundation = DailyUpdateFoundation(
        authority_dir=tmp_path,
        raw_store=None,
        adjusted_store=adjusted,
        common_adjusted_tickers=[],
        common_raw_updater=None,
        etf_raw_updater=None,
        common_adjusted_updater=None,
        etf_adjusted_updater=None,
        corporate_action_state_store=state,
        corporate_action_refresh_service=CorporateActionRefreshService(state, provider, adjusted),
        corporate_action_snapshot_loader=lambda _day: [CorporateActionSnapshot("005930", "2024-01-03", 100, 5000)],
    )
    clean = foundation._run_corporate_action_phase("2024-01-05", ["2024-01-03"])
    assert clean["status"] == "PASS"
    assert provider.calls == []

    foundation.corporate_action_snapshot_loader = lambda _day: [CorporateActionSnapshot("005930", "2024-01-04", 200, 5000)]
    dirty_refresh = foundation._run_corporate_action_phase("2024-01-05", ["2024-01-04"])
    assert dirty_refresh["status"] == "PASS"
    assert provider.calls == [("005930", "2024-01-02", "2024-01-05")]
    assert state.get("005930").status == "CLEAN"

    foundation.corporate_action_snapshot_loader = lambda _day: [CorporateActionSnapshot("005930", "2024-01-05", 300, 5000)]
    provider.load_daily = lambda *_args: _frame(["2024-01-02"])
    with pytest.raises(DailyUpdateFoundationError, match="DIRTY_REMAINS"):
        foundation._run_corporate_action_phase("2024-01-05", ["2024-01-05"])
    assert state.get("005930").status == "FAILED"


def test_physical_write_telemetry_counts_raw_partition_transitions(tmp_path):
    raw = KrxRawStockStore(tmp_path / "raw")
    day = "2026-08-24"

    class Runner:
        def run(self, *_args, **_kwargs):
            raw.save_snapshot("KOSPI", day, _empty_raw_frame(), "/sto/kospi")
            raw.save_snapshot("KOSDAQ", day, _empty_raw_frame(), "/sto/kosdaq")
            return {"status": "COMPLETE", "network_attempts": 0}

    result = RollingRawMarketUpdater(Runner(), raw).refresh("2026-08-21", day, required_dates=[day])
    assert result["updated_dates"] == [day]
    assert result["physical_write_count"] == 2
    assert result["production_write_performed"] is True
