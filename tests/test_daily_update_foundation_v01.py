"""Offline contract tests for the one-target Daily Update foundation."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.refresh_market_index_v01 import derive_incremental_trading_dates
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.daily_update_foundation import (
    DailyUpdateFoundation,
    DailyUpdateFoundationError,
    normalize_target_as_of,
)
from trend_scanner.data.index_store import INDEX_STORE_COLUMNS, IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.krx_market_index import KRX_MARKET_INDEX_MAP
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.rolling_market_data_refresh import (
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    PitExtensionResult,
    RollingEtfAdjustedUpdater,
    RollingRawEtfUpdater,
    _missing_session_dates,
    _merge_adjusted_frames,
    _normalise_session_dates,
    write_merged_pit_extension,
    write_rolling_authority,
    RollingAuthorityManifest,
)


def _frame(days: list[str], base: float = 10.0) -> pd.DataFrame:
    values = [base + i for i in range(len(days))]
    return pd.DataFrame(
        {
            "open": values,
            "high": [v + 2 for v in values],
            "low": [v - 1 for v in values],
            "close": [v + 1 for v in values],
        },
        index=pd.DatetimeIndex(days),
    )


class FakeRawStore:
    def __init__(self, *, calendar: list[str], complete: list[str], etf_complete: list[str] | None = None) -> None:
        self.rows: dict[str, dict[str, dict[str, str]]] = {"KOSPI": {}, "KOSDAQ": {}, "ETF": {}}
        for day in calendar:
            for market in ("KOSPI", "KOSDAQ"):
                self.rows[market][day] = {"market": market, "date": day, "status": "NO_DATA"}
        for day in complete:
            for market in ("KOSPI", "KOSDAQ"):
                self.rows[market][day] = {"market": market, "date": day, "status": "COMPLETE"}
        for day in etf_complete or []:
            self.rows["ETF"][day] = {"market": "ETF", "date": day, "status": "COMPLETE"}

    def list_manifest(self, market: str | None = None) -> list[dict[str, str]]:
        markets = (market,) if market else tuple(self.rows)
        return [dict(row) for key in markets for row in self.rows[key].values()]

    def get_manifest(self, market: str, day: str) -> dict[str, str] | None:
        row = self.rows.get(market, {}).get(day)
        return None if row is None else dict(row)

    def mark_complete(self, day: str, market: str = "ETF") -> None:
        self.rows[market][day] = {"market": market, "date": day, "status": "COMPLETE"}


def _authority(tmp_path: Path, calendar: list[str], *, certified: str | None = None) -> Path:
    authority = tmp_path / "authority"
    authority.mkdir()
    intervals = [
        {
            "ticker": "000001",
            "isu_cd": "KR7000000001",
            "market": "KOSPI",
            "state": "COMMON",
            "effective_from": calendar[0],
            "effective_to": calendar[-1],
        }
    ]
    extension = PitExtensionResult(
        merged_intervals=tuple(intervals),
        merged_calendar_dates=tuple(calendar),
        extension_start=calendar[0],
        extension_end=calendar[-1],
        frozen_interval_count=len(intervals),
        merged_interval_count=len(intervals),
        new_ticker_count=0,
    )
    refs = write_merged_pit_extension(
        extension,
        authority,
        built_against_certified_through=certified or calendar[-1],
        target_as_of=calendar[-1],
    )
    boundary = certified or calendar[-1]
    manifest = RollingAuthorityManifest(
        authority_version="ROLLING_MARKET_DATA_V01",
        certified_through=boundary,
        leg_boundaries={leg: boundary for leg in ("common_raw", "common_adjusted", "etf_raw", "etf_adjusted")},
        previous_boundary=None,
        raw_store_version="KRX_RAW_STOCK_V01",
        adjusted_store_version="ADJUSTED_PRICE_STORE_V02",
        instrument_contract_version="REPOSITORY_V2_INSTRUMENT_CONTRACT_V01",
        bootstrap_source=None,
        generated_at="2026-09-18T00:00:00+00:00",
        merged_pit_digest=refs.merged_pit_digest,
        merged_pit_frontier=refs.merged_pit_frontier,
        merged_pit_schema_version=refs.merged_pit_schema_version,
        merged_calendar_digest=refs.merged_calendar_digest,
        merged_calendar_frontier=refs.merged_calendar_frontier,
        merged_calendar_schema_version=refs.merged_calendar_schema_version,
    )
    write_rolling_authority(manifest, authority)
    return authority


class FakeCommonRaw:
    def __init__(self, raw: FakeRawStore, *, fail: bool = False) -> None:
        self.raw = raw
        self.calls: list[tuple[str, str, list[str]]] = []
        self.fail = fail

    def refresh(self, boundary: str, target: str, *, required_dates: list[str]):
        self.calls.append((boundary, target, list(required_dates)))
        if self.fail:
            raise RuntimeError("common raw failure")
        for day in required_dates:
            self.raw.mark_complete(day, "KOSPI")
            self.raw.mark_complete(day, "KOSDAQ")
        return {"new_boundary": max(required_dates, default=boundary), "updated_date_count": len(required_dates), "request_count": len(required_dates)}


class FakeEtfRaw:
    def __init__(self, raw: FakeRawStore, *, fail: bool = False) -> None:
        self.raw = raw
        self.calls: list[tuple[str, str, list[str]]] = []
        self.fail = fail

    def refresh(self, boundary: str, target: str, *, required_dates: list[str]):
        self.calls.append((boundary, target, list(required_dates)))
        if self.fail:
            raise RuntimeError("etf raw failure")
        for day in required_dates:
            self.raw.mark_complete(day, "ETF")
        return {"new_boundary": max(required_dates, default=boundary), "updated_date_count": len(required_dates), "request_count": len(required_dates)}


class FakeAdjusted:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    def refresh(self, *args):
        boundary, target = args[-2], args[-1]
        self.calls.append((str(boundary), str(target)))
        if self.fail:
            raise RuntimeError("adjusted failure")
        return {"new_boundary": target, "updated": ["000001"], "updated_date_count": 1, "request_count": 1}


class FakeAcquisition:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def run_bounded(self, dates, *, resume: bool, execute_live: bool):
        self.calls.append(list(dates))
        return {"status": "COMPLETE", "network_attempts": 0}


class EmptyCorporateActionState:
    def list_states(self):
        return []

    def get(self, _ticker):
        return None

    def evaluate_and_record(self, _snapshot):
        raise AssertionError("the foundation fixture has no corporate-action snapshots")


class EmptyCorporateActionService:
    def __init__(self):
        self.state_store = EmptyCorporateActionState()

    def refresh_dirty(self, *_args):
        raise AssertionError("the foundation fixture has no corporate-action dirty state")


def _foundation(tmp_path: Path, *, calendar: list[str], complete: list[str], certified: str | None = None, **overrides):
    authority = _authority(tmp_path, calendar, certified=certified)
    raw = FakeRawStore(calendar=calendar, complete=complete, etf_complete=complete)
    common_raw = overrides.get("common_raw", FakeCommonRaw(raw))
    etf_raw = overrides.get("etf_raw", FakeEtfRaw(raw))
    common_adjusted = overrides.get("common_adjusted", FakeAdjusted())
    etf_adjusted = overrides.get("etf_adjusted", FakeAdjusted())
    return DailyUpdateFoundation(
        authority_dir=authority,
        raw_store=raw,
        adjusted_store=AdjustedPriceStore(tmp_path / "adjusted"),
        common_adjusted_tickers=["000001"],
        common_raw_updater=common_raw,
        etf_raw_updater=etf_raw,
        common_adjusted_updater=common_adjusted,
        etf_adjusted_updater=etf_adjusted,
        market_index_refresh=lambda target: {"status": "PROMOTED", "new_boundary": target, "request_count": 1},
        repository_validator=lambda target, authority_dir, legs: {"status": "PASS", "target": target},
        corporate_action_state_store=EmptyCorporateActionState(),
        corporate_action_refresh_service=EmptyCorporateActionService(),
        **{key: value for key, value in overrides.items() if key in {"basic_info_runner", "pit_extension_builder"}},
    ), raw, authority, common_raw, etf_raw, common_adjusted, etf_adjusted


def test_target_is_single_and_propagated_to_all_legs(tmp_path):
    foundation, _raw, _authority_dir, common_raw, etf_raw, common_adjusted, etf_adjusted = _foundation(
        tmp_path, calendar=["2026-09-01", "2026-09-02"], complete=["2026-09-01", "2026-09-02"], certified="2026-09-01"
    )
    result = foundation.execute("2026-09-02", dry_run=False)
    assert result["final_status"] == "PASS"
    assert common_raw.calls[0][1] == etf_raw.calls[0][1] == common_adjusted.calls[0][1] == etf_adjusted.calls[0][1] == "2026-09-02"
    assert result["leg_results"]["repository_v2"]["target"] == "2026-09-02"


def test_tail_incremental_and_middle_gap_are_required_minus_complete(tmp_path):
    assert _missing_session_dates(["2026-08-01", "2026-08-02", "2026-08-03"], ["2026-08-01", "2026-08-03"]) == ["2026-08-02"]
    foundation, _raw, _authority, common_raw, *_ = _foundation(
        tmp_path, calendar=["2026-08-01", "2026-08-02", "2026-08-03"], complete=["2026-08-01", "2026-08-03"], certified="2026-08-03"
    )
    assert foundation.plan("2026-08-03")["common_raw"]["missing_dates"] == ["2026-08-02"]
    result = foundation.execute("2026-08-03", dry_run=False)
    assert result["final_status"] == "PASS"
    assert common_raw.calls[0][2] == ["2026-08-01", "2026-08-02", "2026-08-03"]


def test_sunday_target_is_noop_with_zero_network_write_and_promotion(tmp_path):
    foundation, _raw, _authority, common_raw, etf_raw, common_adjusted, etf_adjusted = _foundation(
        tmp_path, calendar=["2026-08-21"], complete=["2026-08-21"], certified="2026-08-21"
    )
    result = foundation.execute("2026-08-23", dry_run=False)
    assert result["final_status"] == "NOOP"
    assert result["network_request_count"] == result["production_write_count"] == result["authority_promotion"] == 0
    assert not common_raw.calls and not etf_raw.calls and not common_adjusted.calls and not etf_adjusted.calls


def test_dry_run_has_no_network_or_write_and_exposes_extension(tmp_path):
    foundation, _raw, _authority, *_ = _foundation(
        tmp_path, calendar=["2026-08-21"], complete=["2026-08-21"], certified="2026-08-21"
    )
    result = foundation.execute("2026-08-24", dry_run=True)
    assert result["status"] == "DRY_RUN"
    assert result["authority_extension_needed"] is True
    assert result["network_request_count"] == result["production_write_count"] == result["authority_promotion"] == 0


def test_pit_extension_is_staged_and_promoted_only_after_validation(tmp_path):
    acquisition = FakeAcquisition()
    extension = PitExtensionResult(
        merged_intervals=(), merged_calendar_dates=("2026-08-21", "2026-08-24"),
        extension_start="2026-08-24", extension_end="2026-08-24",
        frozen_interval_count=0, merged_interval_count=0, new_ticker_count=0,
    )
    foundation, _raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-08-21"],
        complete=["2026-08-21", "2026-08-24"],
        certified="2026-08-21",
        basic_info_runner=acquisition,
        pit_extension_builder=lambda **kwargs: extension,
    )
    result = foundation.execute("2026-08-24", dry_run=False)
    assert result["final_status"] == "PASS"
    assert acquisition.calls == [["2026-08-24"]]
    assert json.loads((authority / "manifest.json").read_text())["certified_through"] == "2026-08-24"


def test_insufficient_pit_authority_blocks_without_current_universe_fallback(tmp_path):
    foundation, _raw, authority, *_ = _foundation(
        tmp_path, calendar=["2026-08-21"], complete=["2026-08-21", "2026-08-24"], certified="2026-08-21"
    )
    before = (authority / "manifest.json").read_bytes()
    result = foundation.execute("2026-08-24", dry_run=False)
    assert result["final_status"] == "BLOCKED"
    assert "BASIC_INFO" in result["reason"]
    assert (authority / "manifest.json").read_bytes() == before


def test_partial_failure_does_not_promote_certified_boundary(tmp_path):
    raw = None
    failing = FakeEtfRaw(None, fail=True)
    foundation, raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-08-01", "2026-08-02"],
        complete=["2026-08-01"],
        certified="2026-08-01",
        etf_raw=failing,
    )
    failing.raw = raw
    before = (authority / "manifest.json").read_bytes()
    result = foundation.execute("2026-08-02", dry_run=False)
    assert result["final_status"] == "FAILED"
    assert result["boundary_unchanged"] is True
    assert (authority / "manifest.json").read_bytes() == before


def test_common_raw_middle_gap_plan_does_not_use_max_date_only(tmp_path):
    foundation, _raw, _authority, common_raw, *_ = _foundation(
        tmp_path, calendar=["2026-08-01", "2026-08-02", "2026-08-03"], complete=["2026-08-01", "2026-08-03"], certified="2026-08-03"
    )
    plan = foundation.plan("2026-08-03")
    assert plan["current_certified_through"] == "2026-08-03"
    assert plan["common_raw"]["missing_dates"] == ["2026-08-02"]
    assert common_raw.calls == []


def test_etf_raw_middle_gap_is_detected_from_common_sessions(tmp_path):
    raw = FakeRawStore(calendar=["2026-08-01", "2026-08-02", "2026-08-03"], complete=["2026-08-01", "2026-08-02", "2026-08-03"], etf_complete=["2026-08-01", "2026-08-03"])
    updater = RollingRawEtfUpdater(None, raw)
    plan = updater.plan("2026-08-03", "2026-08-03", required_dates=["2026-08-01", "2026-08-02", "2026-08-03"])
    assert plan["missing_dates"] == ["2026-08-02"]


def test_market_index_middle_gap_is_detected_before_boundary():
    class Raw:
        def list_manifest(self):
            return [
                {"market": market, "date": day, "status": "COMPLETE"}
                for day in ("2026-08-01", "2026-08-02", "2026-08-03")
                for market in ("KOSPI", "KOSDAQ")
            ]
    frame = pd.DataFrame(
        [
            {"date": day, "family": MARKET_INDEX_FAMILY, "source_index_class": contract["source_index_class"], "index_code": code, "index_name": contract["source_index_name"], "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 1.0, "trading_value": 2.0}
            for day in ("2026-08-01", "2026-08-03")
            for code, contract in KRX_MARKET_INDEX_MAP.items()
        ],
        columns=list(INDEX_STORE_COLUMNS),
    )
    plan = derive_incremental_trading_dates(Raw(), "2026-08-03", "2026-08-03", existing_frame=frame)
    assert plan["missing_dates"] == ["2026-08-02"]


def test_common_adjusted_requests_only_missing_and_preserves_old_rows(tmp_path):
    calendar = tmp_path / "calendar.json"
    calendar.write_text(json.dumps({"trading_dates": ["2026-08-03", "2026-08-04", "2026-08-05"]}))
    pit = tmp_path / "pit.json"
    pit.write_text(json.dumps({"intervals": [{"ticker": "000001", "state": "COMMON", "effective_from": "2026-08-03", "effective_to": "2026-08-05"}]}))
    store = AdjustedPriceStore(tmp_path / "adjusted")
    old = _frame(["2026-08-03", "2026-08-05"], base=10)
    store.save_full("000001", old, {"requested_start": "2026-08-03", "requested_end": "2026-08-05"})

    class Provider:
        calls = []
        def load_daily(self, ticker, start, end):
            self.calls.append((start, end))
            return _frame(["2026-08-04"], base=20)

    provider = Provider()
    from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater
    result = RollingAdjustedPriceUpdater(provider, store, pit_path=pit, historical_calendar_path=calendar).refresh(["000001"], "2026-08-03", "2026-08-05")
    assert provider.calls == [("2026-08-04", "2026-08-04")]
    assert result["updated"] == ["000001"]
    loaded = store.load_daily("000001")
    assert loaded.loc[pd.Timestamp("2026-08-03"), "close"] == old.loc[pd.Timestamp("2026-08-03"), "close"]


def test_etf_adjusted_requests_only_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("trend_scanner.data.rolling_market_data_refresh.ETF_VALIDATED_ACCEPTANCE_TICKERS", ("000001",))
    raw = FakeRawStore(calendar=["2026-08-03", "2026-08-04", "2026-08-05"], complete=["2026-08-03", "2026-08-04", "2026-08-05"])
    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame(["2026-08-03", "2026-08-05"]), {"requested_start": "2026-08-03", "requested_end": "2026-08-05"})

    class Provider:
        calls = []
        def load_daily(self, ticker, start, end):
            self.calls.append((start, end))
            return _frame(["2026-08-04"], base=20)

    provider = Provider()
    result = RollingEtfAdjustedUpdater(provider, store, raw_store=raw).refresh("2026-08-03", "2026-08-05")
    assert provider.calls == [("2026-08-04", "2026-08-04")]
    assert result["updated"] == ["000001"]


def test_adjusted_same_target_does_not_request_or_save(tmp_path):
    calendar = tmp_path / "calendar.json"
    calendar.write_text(json.dumps({"trading_dates": ["2026-08-03", "2026-08-04"]}))
    pit = tmp_path / "pit.json"
    pit.write_text(json.dumps({"intervals": [{"ticker": "000001", "state": "COMMON", "effective_from": "2026-08-03", "effective_to": "2026-08-04"}]}))

    class CountingStore(AdjustedPriceStore):
        save_calls = 0
        def save_full(self, *args, **kwargs):
            self.save_calls += 1
            return super().save_full(*args, **kwargs)

    store = CountingStore(tmp_path / "adjusted")
    store.save_full("000001", _frame(["2026-08-03", "2026-08-04"]), {"requested_start": "2026-08-03", "requested_end": "2026-08-04"})
    store.save_calls = 0

    class Provider:
        def load_daily(self, *args):
            raise AssertionError("same-target rerun must not call provider")

    from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater
    result = RollingAdjustedPriceUpdater(Provider(), store, pit_path=pit, historical_calendar_path=calendar).refresh(["000001"], "2026-08-04", "2026-08-04")
    assert result["updated"] == []
    assert store.save_calls == 0


def test_corporate_action_overlap_remains_in_existing_evidence_gate():
    old = _frame(["2026-08-03"], base=10)
    new = _frame(["2026-08-03", "2026-08-04"], base=20)
    merged = _merge_adjusted_frames(old, [new])
    assert merged.loc[pd.Timestamp("2026-08-03"), "close"] == new.loc[pd.Timestamp("2026-08-03"), "close"]


def test_repository_v2_mismatch_blocks_final_promotion(tmp_path):
    validator_calls = []
    foundation, _raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-08-01", "2026-08-02"],
        complete=["2026-08-01", "2026-08-02"],
        certified="2026-08-01",
    )
    foundation.repository_validator = lambda target, stage, legs: {"status": "BLOCKED", "reason": "REPOSITORY_V2_TRADING_SESSION_MISMATCH"}
    before = (authority / "manifest.json").read_bytes()
    result = foundation.execute("2026-08-02", dry_run=False)
    assert result["final_status"] == "BLOCKED"
    assert result["authority_promotion"] == 0
    assert (authority / "manifest.json").read_bytes() == before


def test_authority_coherence_mismatch_blocks_before_any_leg(tmp_path):
    foundation, _raw, authority, common_raw, *_ = _foundation(
        tmp_path, calendar=["2026-08-01"], complete=["2026-08-01"], certified="2026-08-01"
    )
    payload = json.loads((authority / "manifest.json").read_text())
    payload["merged_pit_digest"] = "0" * 64
    (authority / "manifest.json").write_text(json.dumps(payload))
    result = foundation.execute("2026-08-01", dry_run=False)
    assert result["final_status"] == "BLOCKED"
    assert not common_raw.calls


def test_invalid_target_is_rejected_without_system_date_fallback():
    with pytest.raises(DailyUpdateFoundationError, match="INVALID_TARGET"):
        normalize_target_as_of("today")
    with pytest.raises(DailyUpdateFoundationError, match="INVALID_TARGET"):
        normalize_target_as_of("2026-9-1")
