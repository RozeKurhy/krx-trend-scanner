"""Focused offline contracts for Daily Update Foundation FIX02."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.corporate_action_detector import CorporateActionSnapshot
from trend_scanner.data.corporate_action_refresh import CorporateActionRefreshService
from trend_scanner.data.corporate_action_state_store import CorporateActionStateStore
from trend_scanner.data.daily_update_foundation import DailyUpdateFoundation, DailyUpdateFoundationError
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore
from trend_scanner.data.adjusted_price_pilot import ExpectedCoverageResolution
from trend_scanner.data.rolling_market_data_refresh import (
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    RollingAdjustedPriceUpdater,
    RollingAuthorityManifest,
    migrate_rolling_authority_manifest,
    write_merged_pit_extension,
    write_rolling_authority,
)
from trend_scanner.data.rolling_market_data_refresh import PitExtensionResult


def _adjusted_frame(days: list[str], base: float = 10.0) -> pd.DataFrame:
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


def _write_adjusted_authority(tmp_path: Path, intervals: list[dict[str, str]]) -> tuple[Path, Path]:
    pit = tmp_path / "pit.json"
    calendar = tmp_path / "calendar.json"
    pit.write_text(json.dumps({"intervals": intervals}), encoding="utf-8")
    calendar.write_text(
        json.dumps({"trading_dates": ["2026-08-01", "2026-08-02", "2026-08-03"]}),
        encoding="utf-8",
    )
    return pit, calendar


def test_common_adjusted_authority_failure_is_blocked_and_boundary_is_unchanged(tmp_path):
    pit, calendar = _write_adjusted_authority(
        tmp_path,
        [
            {
                "ticker": "000001",
                "isu_cd": "KR7000000001",
                "market": "KOSPI",
                "state": "COMMON",
                "effective_from": "2026-08-01",
                "effective_to": "2026-08-03",
            },
            {
                "ticker": "000001",
                "isu_cd": "KR7000000002",
                "market": "KOSPI",
                "state": "COMMON",
                "effective_from": "2026-08-01",
                "effective_to": "2026-08-03",
            },
        ],
    )
    store = AdjustedPriceStore(tmp_path / "adjusted")

    class Provider:
        def load_daily(self, *_args):
            raise AssertionError("unresolved identity must not call the provider")

    result = RollingAdjustedPriceUpdater(
        Provider(), store, pit_path=pit, historical_calendar_path=calendar
    ).refresh(["000001"], "2026-08-01", "2026-08-03")
    assert result["blocked"][0]["reason"] == "IDENTITY_AMBIGUOUS"
    assert result["skipped"] == []
    assert result["failures"] == []
    assert result["new_boundary"] == "2026-08-01"


@pytest.mark.parametrize("authority_status", ["ERROR", "INSUFFICIENT_AUTHORITY"])
def test_common_adjusted_non_valid_coverage_is_blocked(monkeypatch, tmp_path, authority_status):
    pit, calendar = _write_adjusted_authority(
        tmp_path,
        [
            {
                "ticker": "000001",
                "isu_cd": "KR7000000001",
                "market": "KOSPI",
                "state": "COMMON",
                "effective_from": "2026-08-01",
                "effective_to": "2026-08-03",
            }
        ],
    )
    monkeypatch.setattr(
        "trend_scanner.data.rolling_market_data_refresh.resolve_expected_coverage",
        lambda *_args, **_kwargs: ExpectedCoverageResolution(
            ticker="000001",
            query_start="2026-08-01",
            query_end="2026-08-03",
            authority_status=authority_status,
            authority_source="TEST",
            authority_quality="TEST",
            raw_observed_count=0,
            excluded_nontradable_count=0,
            expected_tradable_count=0,
            expected_tradable_dates=(),
            nontradable_dates=(),
            source_path="TEST",
        ),
    )
    result = RollingAdjustedPriceUpdater(
        object(), AdjustedPriceStore(tmp_path / "adjusted"), pit_path=pit, historical_calendar_path=calendar
    ).refresh(["000001"], "2026-08-01", "2026-08-03", requested_start="2026-08-01")
    assert result["blocked"][0]["reason"] == authority_status
    assert result["new_boundary"] == "2026-08-01"


def test_foundation_does_not_pass_when_common_adjusted_is_blocked(tmp_path):
    authority = tmp_path / "authority"
    extension = PitExtensionResult(
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
    write_merged_pit_extension(extension, authority, built_against_certified_through="2026-08-21", target_as_of="2026-08-21")
    write_rolling_authority(
        RollingAuthorityManifest(
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
        ),
        authority,
    )
    migrate_rolling_authority_manifest(authority, apply=True)

    class RawLeg:
        def plan(self, *_args, **_kwargs):
            return {"missing_dates": ["2026-08-21"]}

        def refresh(self, *_args, **_kwargs):
            return {"updated_dates": [], "new_boundary": "2026-08-21"}

    class AdjustedLeg:
        def plan(self, *_args, **_kwargs):
            return {"missing_dates": ["2026-08-21"]}

        def refresh(self, *_args, **_kwargs):
            return {
                "blocked": [{"ticker": "000001", "reason": "INSUFFICIENT_AUTHORITY"}],
                "failures": [],
                "updated": [],
                "new_boundary": "2026-08-21",
            }

    raw = KrxRawStockStore(tmp_path / "raw")
    foundation = DailyUpdateFoundation(
        authority_dir=authority,
        raw_store=raw,
        adjusted_store=AdjustedPriceStore(tmp_path / "adjusted"),
        common_adjusted_tickers=["000001"],
        common_raw_updater=RawLeg(),
        etf_raw_updater=RawLeg(),
        common_adjusted_updater=AdjustedLeg(),
        etf_adjusted_updater=AdjustedLeg(),
        market_index_plan=lambda _target: {"missing_dates": ["2026-08-21"]},
        repository_validator=lambda *_args: {"status": "PASS"},
    )
    result = foundation.execute("2026-08-21", dry_run=False)
    assert result["final_status"] == "BLOCKED"
    assert result["authority_promotion"] == 0
    assert result["reason"] == "BLOCKED_COMMON_ADJUSTED_AUTHORITY"


def _raw_frame(day: str, ticker: str, listed_shares: int) -> pd.DataFrame:
    return pd.DataFrame(
        [[day, ticker, 10, 11, 9, 10, 100, 1000, 1_000_000, listed_shares]],
        columns=list(RAW_COLUMNS),
    )


def _ca_foundation(tmp_path: Path, raw: KrxRawStockStore, state: CorporateActionStateStore, provider):
    adjusted = AdjustedPriceStore(tmp_path / "adjusted")
    adjusted.save_full(
        "000001",
        _adjusted_frame(["2026-08-21"], base=10),
        {"requested_start": "2026-08-21", "requested_end": "2026-08-21"},
    )
    return DailyUpdateFoundation(
        authority_dir=tmp_path / "authority",
        raw_store=raw,
        adjusted_store=adjusted,
        common_adjusted_tickers=["000001"],
        common_raw_updater=None,
        etf_raw_updater=None,
        common_adjusted_updater=None,
        etf_adjusted_updater=None,
        corporate_action_state_store=state,
        corporate_action_refresh_service=CorporateActionRefreshService(state, provider, adjusted),
    )


def test_corporate_action_baselines_old_raw_before_new_observation_and_refreshes_change(tmp_path):
    raw = KrxRawStockStore(tmp_path / "raw")
    raw.save_snapshot("KOSPI", "2026-08-21", _raw_frame("2026-08-21", "000001", 100), "/sto/stk")
    raw.save_snapshot("KOSPI", "2026-08-24", _raw_frame("2026-08-24", "000001", 200), "/sto/stk")
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")

    class Provider:
        calls = []

        def load_daily(self, ticker, start, end):
            self.calls.append((ticker, start, end))
            return _adjusted_frame(["2026-08-21", "2026-08-24"], base=20)

    provider = Provider()
    foundation = _ca_foundation(tmp_path, raw, state, provider)
    result = foundation._run_corporate_action_phase(
        "2026-08-24",
        ["2026-08-24"],
        managed_universe={"000001"},
        baseline_boundary="2026-08-21",
    )
    assert result["status"] == "PASS"
    assert result["baseline_count"] == 1
    assert provider.calls == [("000001", "2026-08-21", "2026-08-24")]
    assert state.get("000001").status == "CLEAN"


def test_corporate_action_same_value_and_new_listing_are_clean_without_refresh(tmp_path):
    raw = KrxRawStockStore(tmp_path / "raw")
    raw.save_snapshot("KOSPI", "2026-08-21", _raw_frame("2026-08-21", "000001", 100), "/sto/stk")
    raw.save_snapshot("KOSPI", "2026-08-24", _raw_frame("2026-08-24", "000001", 100), "/sto/stk")
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")

    class Provider:
        def load_daily(self, *_args):
            raise AssertionError("unchanged listed shares must not refresh")

    foundation = _ca_foundation(tmp_path, raw, state, Provider())
    result = foundation._run_corporate_action_phase(
        "2026-08-24", ["2026-08-24"], managed_universe={"000001"}, baseline_boundary="2026-08-21"
    )
    assert result["status"] == "PASS"
    assert result["refreshes"] == []

    new_raw = KrxRawStockStore(tmp_path / "new_raw")
    new_raw.save_snapshot("KOSPI", "2026-08-24", _raw_frame("2026-08-24", "000002", 200), "/sto/stk")
    new_state = CorporateActionStateStore(tmp_path / "new_state.sqlite3")
    new_foundation = _ca_foundation(tmp_path / "new", new_raw, new_state, Provider())
    new_result = new_foundation._run_corporate_action_phase(
        "2026-08-24", ["2026-08-24"], managed_universe={"000002"}, baseline_boundary="2026-08-21"
    )
    assert new_result["status"] == "PASS"
    assert new_result["baseline_count"] == 0
    assert new_state.get("000002").status == "CLEAN"


def test_corporate_action_managed_universe_filters_out_of_scope_dirty_and_snapshots(tmp_path):
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")
    state.evaluate_and_record(CorporateActionSnapshot("000999", "2026-08-20", 100))
    state.evaluate_and_record(CorporateActionSnapshot("000999", "2026-08-21", 200))
    accepted_etf = ETF_VALIDATED_ACCEPTANCE_TICKERS[0]
    foundation = DailyUpdateFoundation(
        authority_dir=tmp_path,
        raw_store=None,
        adjusted_store=AdjustedPriceStore(tmp_path / "adjusted"),
        common_adjusted_tickers=["000001"],
        common_raw_updater=None,
        etf_raw_updater=None,
        common_adjusted_updater=None,
        etf_adjusted_updater=None,
        corporate_action_state_store=state,
        corporate_action_refresh_service=None,
        corporate_action_snapshot_loader=lambda _day: [
            CorporateActionSnapshot("000001", "2026-08-24", 100),
            CorporateActionSnapshot(accepted_etf, "2026-08-24", 100),
            CorporateActionSnapshot("000999", "2026-08-24", 300),
        ],
    )
    snapshots = foundation._corporate_action_snapshots(
        ["2026-08-24"], {"000001", accepted_etf}
    )
    assert {snapshot.ticker for snapshot in snapshots} == {"000001", accepted_etf}

    class Service:
        state_store = state

        def refresh_dirty(self, *_args):
            raise AssertionError("out-of-scope DIRTY state must not be refreshed")

    foundation.corporate_action_refresh_service = Service()
    result = foundation._run_corporate_action_phase(
        "2026-08-24", [], managed_universe={"000001", accepted_etf}
    )
    assert result["status"] == "PASS"
    assert result["dirty_tickers"] == []
