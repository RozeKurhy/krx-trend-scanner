"""Offline contract tests for the one-target Daily Update foundation."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path

import pandas as pd
import pytest

from scripts.refresh_market_index_v01 import derive_incremental_trading_dates
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.data.daily_update_foundation import (
    DailyUpdateFoundation,
    DailyUpdateFoundationError,
    normalize_target_as_of,
)
from trend_scanner.data.index_store import INDEX_STORE_COLUMNS, IndexStore, MARKET_INDEX_FAMILY
from trend_scanner.data.krx_market_index import KRX_MARKET_INDEX_MAP
from trend_scanner.data.krx_raw_stock_provider import RAW_COLUMNS
from trend_scanner.data.rolling_market_data_refresh import (
    ETF_ADJUSTED_COVERAGE_START,
    ETF_RAW_COVERAGE_START,
    ETF_VALIDATED_ACCEPTANCE_TICKERS,
    PitExtensionResult,
    RollingEtfAdjustedUpdater,
    RollingRawEtfUpdater,
    _missing_session_dates,
    _merge_adjusted_frames,
    _normalise_session_dates,
    _session_ranges,
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


def _foundation(
    tmp_path: Path,
    *,
    calendar: list[str],
    complete: list[str],
    certified: str | None = None,
    etf_complete: list[str] | None = None,
    **overrides,
):
    authority = _authority(tmp_path, calendar, certified=certified)
    raw = FakeRawStore(
        calendar=calendar,
        complete=complete,
        etf_complete=complete if etf_complete is None else etf_complete,
    )
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


def test_repository_validator_uses_etf_adjusted_lower_bound_and_keeps_common_legacy_start(monkeypatch, tmp_path):
    calls = []

    class RecordingRepository:
        query_audit = {"calls": 0}

        def __init__(self, *_args, **_kwargs):
            pass

        def get_daily(self, ticker, start, end):
            calls.append((ticker, start, end))
            return pd.DataFrame()

    monkeypatch.setattr("trend_scanner.data.daily_update_foundation.MarketDataRepositoryV2", RecordingRepository)
    foundation, _raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-09-16"],
        complete=["2026-09-16"],
        certified="2026-09-16",
    )
    etf = ETF_VALIDATED_ACCEPTANCE_TICKERS[0]
    result = foundation._default_repository_validator(
        "2026-09-16",
        authority,
        {"common_adjusted": {"validation_tickers": ["005930"]}, "etf_adjusted": {"validation_tickers": [etf]}},
    )

    assert result["status"] == "PASS"
    assert ("005930", "1900-01-01", "2026-09-16") in calls
    assert (etf, ETF_ADJUSTED_COVERAGE_START, "2026-09-16") in calls


def test_repository_validator_still_blocks_etf_session_mismatch_after_lower_bound(monkeypatch, tmp_path):
    class MismatchRepository:
        query_audit = {"calls": 0}

        def __init__(self, *_args, **_kwargs):
            pass

        def get_daily(self, ticker, start, end):
            raise RuntimeError("REPOSITORY_V2_TRADING_SESSION_MISMATCH")

    monkeypatch.setattr("trend_scanner.data.daily_update_foundation.MarketDataRepositoryV2", MismatchRepository)
    foundation, _raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-09-16"],
        complete=["2026-09-16"],
        certified="2026-09-16",
    )
    etf = ETF_VALIDATED_ACCEPTANCE_TICKERS[0]
    result = foundation._default_repository_validator(
        "2026-09-16",
        authority,
        {"etf_adjusted": {"validation_tickers": [etf]}},
    )

    assert result["status"] == "BLOCKED"
    assert result["failures"] == [{"ticker": etf, "error": "REPOSITORY_V2_TRADING_SESSION_MISMATCH"}]


def test_repository_validator_keeps_all_28_etf_validation_targets(monkeypatch, tmp_path):
    calls = []

    class RecordingRepository:
        query_audit = {"calls": 0}

        def __init__(self, *_args, **_kwargs):
            pass

        def get_daily(self, ticker, start, end):
            calls.append((ticker, start, end))
            return pd.DataFrame()

    monkeypatch.setattr("trend_scanner.data.daily_update_foundation.MarketDataRepositoryV2", RecordingRepository)
    foundation, _raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-09-16"],
        complete=["2026-09-16"],
        certified="2026-09-16",
    )
    result = foundation._default_repository_validator(
        "2026-09-16",
        authority,
        {"etf_adjusted": {"validation_tickers": list(ETF_VALIDATED_ACCEPTANCE_TICKERS)}},
    )

    assert result["status"] == "PASS"
    assert result["checked_ticker_count"] == 28
    assert {ticker for ticker, _start, _end in calls} == set(ETF_VALIDATED_ACCEPTANCE_TICKERS)
    assert {start for _ticker, start, _end in calls} == {ETF_ADJUSTED_COVERAGE_START}


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


def test_etf_raw_coverage_start_clamps_foundation_and_updater_required_dates(tmp_path):
    calendar = ["2013-12-30", ETF_RAW_COVERAGE_START, "2014-01-03"]
    foundation, raw, *_ = _foundation(
        tmp_path,
        calendar=calendar,
        complete=calendar,
        etf_complete=[ETF_RAW_COVERAGE_START],
        certified=ETF_RAW_COVERAGE_START,
    )

    foundation_plan = foundation.plan("2014-01-03")
    assert foundation_plan["etf_raw"]["required_dates"] == [ETF_RAW_COVERAGE_START, "2014-01-03"]
    assert foundation_plan["etf_raw"]["missing_dates"] == ["2014-01-03"]

    updater_plan = RollingRawEtfUpdater(None, raw).plan(
        ETF_RAW_COVERAGE_START,
        "2014-01-03",
        required_dates=calendar,
    )
    assert updater_plan["trading_sessions"] == [ETF_RAW_COVERAGE_START, "2014-01-03"]
    assert updater_plan["missing_dates"] == ["2014-01-03"]


def test_etf_raw_coverage_start_live_refresh_targets_start_date_only():
    pre_coverage = "2013-12-30"

    class Provider:
        def __init__(self):
            self.calls = []

        def fetch_snapshot(self, requested_day):
            self.calls.append(requested_day)
            return pd.DataFrame()

    class WritableFakeRawStore(FakeRawStore):
        def save_snapshot(self, market, day, frame, endpoint):
            self.mark_complete(day, market)

    writable = WritableFakeRawStore(
        calendar=[pre_coverage, ETF_RAW_COVERAGE_START],
        complete=[pre_coverage, ETF_RAW_COVERAGE_START],
        etf_complete=[],
    )
    provider = Provider()
    result = RollingRawEtfUpdater(provider, writable).refresh(
        "2013-12-27",
        ETF_RAW_COVERAGE_START,
        required_dates=[pre_coverage, ETF_RAW_COVERAGE_START],
    )
    assert provider.calls == [ETF_RAW_COVERAGE_START]
    assert result["required_dates"] == [ETF_RAW_COVERAGE_START]
    assert result["missing_dates"] == []


def test_etf_raw_precoverage_absence_does_not_call_provider_or_block_completion(tmp_path):
    day = "2013-12-30"
    foundation, raw, *_ = _foundation(
        tmp_path,
        calendar=[day],
        complete=[day],
        etf_complete=[],
        certified=day,
    )
    foundation_plan = foundation.plan(day)
    assert foundation_plan["etf_raw"]["required_dates"] == []
    assert foundation_plan["etf_raw"]["missing_dates"] == []

    class Provider:
        def __init__(self):
            self.calls = []

        def fetch_snapshot(self, requested_day):
            self.calls.append(requested_day)
            raise AssertionError("pre-coverage ETF session must not call the provider")

    provider = Provider()
    result = RollingRawEtfUpdater(provider, raw).refresh(
        "2013-12-27",
        day,
        required_dates=[day],
    )
    assert provider.calls == []
    assert result["required_dates"] == []
    assert result["missing_dates"] == []

    dry_run = foundation.execute(day, dry_run=True)
    assert dry_run["final_status"] == "NOOP"
    assert dry_run["etf_raw"]["missing_dates"] == []


def test_etf_raw_current_tail_remains_required_after_coverage_clamp(tmp_path):
    tail = ["2026-09-14", "2026-09-15", "2026-09-16", "2026-09-17", "2026-09-18"]
    calendar = ["2013-12-30", ETF_RAW_COVERAGE_START, "2014-01-03", *tail]
    raw = FakeRawStore(
        calendar=calendar,
        complete=calendar,
        etf_complete=[ETF_RAW_COVERAGE_START, "2014-01-03"],
    )
    plan = RollingRawEtfUpdater(None, raw).plan(
        "2026-09-11",
        "2026-09-18",
        required_dates=calendar,
    )
    assert plan["missing_dates"] == tail


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


def test_session_ranges_follow_required_trading_sequence():
    required = ["2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    assert _session_ranges(["2026-08-07", "2026-08-10"], required) == [
        ("2026-08-07", "2026-08-10"),
    ]
    assert _session_ranges(["2026-08-07", "2026-08-11"], required) == [
        ("2026-08-07", "2026-08-07"),
        ("2026-08-11", "2026-08-11"),
    ]
    holiday_required = ["2026-10-08", "2026-10-12"]
    assert _session_ranges(holiday_required, holiday_required) == [
        ("2026-10-08", "2026-10-12"),
    ]


def test_common_adjusted_refresh_uses_required_sequence_ranges(tmp_path):
    calendar = tmp_path / "calendar.json"
    required = ["2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]
    calendar.write_text(json.dumps({"trading_dates": required}))
    pit = tmp_path / "pit.json"
    pit.write_text(json.dumps({"intervals": [{
        "ticker": "000001",
        "state": "COMMON",
        "effective_from": required[0],
        "effective_to": required[-1],
    }]}))
    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame([required[0], required[-1]]), {
        "requested_start": required[0],
        "requested_end": required[-1],
    })

    class Provider:
        calls = []

        def load_daily(self, ticker, start, end):
            self.calls.append((ticker, start, end))
            return _frame(required[1:3], base=20)

    from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater

    provider = Provider()
    result = RollingAdjustedPriceUpdater(
        provider,
        store,
        pit_path=pit,
        historical_calendar_path=calendar,
    ).refresh(["000001"], "2026-08-05", required[-1])
    assert provider.calls == [("000001", required[1], required[2])]
    assert result["updated"] == ["000001"]


def test_etf_adjusted_refresh_uses_required_sequence_ranges(monkeypatch, tmp_path):
    monkeypatch.setattr("trend_scanner.data.rolling_market_data_refresh.ETF_VALIDATED_ACCEPTANCE_TICKERS", ("000001",))
    required = ["2026-08-06", "2026-08-07", "2026-08-10", "2026-08-11"]

    class PresenceRawStore:
        def list_manifest(self, market=None):
            if market == "KOSPI":
                return [{"market": market, "date": day, "status": "COMPLETE"} for day in required]
            if market == "ETF":
                return [{"market": market, "date": day, "status": "COMPLETE"} for day in required]
            return []

        def load_snapshot(self, market, day):
            return pd.DataFrame({"ticker": ["000001"]})

    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame([required[0], required[-1]]), {
        "requested_start": required[0],
        "requested_end": required[-1],
    })

    class Provider:
        calls = []

        def load_daily(self, ticker, start, end):
            self.calls.append((ticker, start, end))
            return _frame(required[1:3], base=20)

    provider = Provider()
    result = RollingEtfAdjustedUpdater(
        provider,
        store,
        raw_store=PresenceRawStore(),
    ).refresh("2026-08-05", required[-1])
    assert provider.calls == [("000001", required[1], required[2])]
    assert result["updated"] == ["000001"]


def test_etf_adjusted_uses_ticker_presence_to_remove_prelisting_gap_and_keep_tail(monkeypatch, tmp_path):
    monkeypatch.setattr("trend_scanner.data.rolling_market_data_refresh.ETF_VALIDATED_ACCEPTANCE_TICKERS", ("0115D0",))
    base_sessions = ["2023-01-02", "2025-10-27", "2025-10-28", "2025-10-29", "2026-09-01"]
    observed_sessions = ["2025-10-28", "2025-10-29", "2026-09-01"]

    class PresenceRawStore:
        def list_manifest(self, market=None):
            if market == "KOSPI":
                return [{"market": market, "date": day, "status": "COMPLETE"} for day in base_sessions]
            if market == "ETF":
                return [{"market": market, "date": day, "status": "COMPLETE"} for day in observed_sessions]
            return []

        def load_snapshot(self, market, day):
            return pd.DataFrame({"ticker": ["0115D0"]})

    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("0115D0", _frame(observed_sessions[:2]), {
        "requested_start": "2023-01-02",
        "requested_end": observed_sessions[-1],
    })
    updater = RollingEtfAdjustedUpdater(None, store, raw_store=PresenceRawStore())
    plan = updater.plan("2026-08-21", "2026-09-01")

    record = plan["ticker_records"][0]
    assert plan["requested_start"] == "2023-01-02"
    assert plan["required_dates"] == observed_sessions
    assert record["required_start"] == "2025-10-28"
    assert record["missing_dates"] == ["2026-09-01"]
    assert record["missing_date_count"] == 1
    assert "2023-01-02" not in record["missing_dates"]
    assert "2025-10-27" not in record["missing_dates"]


def test_etf_adjusted_scope_remains_28_without_ticker_hardcode():
    source = Path("src/trend_scanner/data/rolling_market_data_refresh.py").read_text(encoding="utf-8")
    assert len(ETF_VALIDATED_ACCEPTANCE_TICKERS) == 28
    updater_source = source[source.index("class RollingEtfAdjustedUpdater"):]
    assert "0115D0" not in updater_source


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


def _source_native_relation_anomaly(days: list[str], base: float = 10.0) -> pd.DataFrame:
    frame = _frame(days, base=base)
    frame.loc[pd.Timestamp(days[-1]), "high"] = frame.loc[pd.Timestamp(days[-1]), "open"] - 1
    frame.attrs.update(source_native_adjusted=True, analytic_invalid_ohlc_count=1)
    return frame


def test_adjusted_merge_preserves_source_native_semantics_and_recomputes_anomalies():
    old = _frame(["2026-08-03"], base=10)
    fetched = _source_native_relation_anomaly(["2026-08-04"], base=20)
    merged = _merge_adjusted_frames(old, [fetched])

    assert merged.attrs["source_native_adjusted"] is True
    assert merged.attrs["analytic_invalid_ohlc_count"] == 1
    assert merged.loc[pd.Timestamp("2026-08-04"), "high"] == 19


def test_non_source_native_invalid_merge_keeps_strict_store_validation(tmp_path):
    invalid = _frame(["2026-08-03"], base=10)
    invalid.loc[pd.Timestamp("2026-08-03"), "high"] = 8
    merged = _merge_adjusted_frames(None, [invalid])

    assert "source_native_adjusted" not in merged.attrs
    with pytest.raises(MarketDataError):
        AdjustedPriceStore(tmp_path / "adjusted").save_full("000001", merged)


def test_common_adjusted_source_native_merge_saves_source_view_and_rejects_analytic_view(tmp_path):
    calendar = tmp_path / "calendar.json"
    required = ["2026-08-03", "2026-08-04", "2026-08-05"]
    calendar.write_text(json.dumps({"trading_dates": required}))
    pit = tmp_path / "pit.json"
    pit.write_text(json.dumps({"intervals": [{
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "state": "COMMON",
        "effective_from": required[0],
        "effective_to": required[-1],
    }]}))
    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame([required[0], required[-1]]), {
        "requested_start": required[0],
        "requested_end": required[-1],
    })

    class Provider:
        def load_daily(self, ticker, start, end):
            assert (ticker, start, end) == ("000001", required[1], required[1])
            return _source_native_relation_anomaly([required[1]], base=20)

    from trend_scanner.data.rolling_market_data_refresh import RollingAdjustedPriceUpdater

    result = RollingAdjustedPriceUpdater(
        Provider(), store, pit_path=pit, historical_calendar_path=calendar
    ).refresh(["000001"], required[0], required[-1])
    assert result["updated"] == ["000001"]
    metadata = store.load_metadata("000001")
    assert metadata["source_native_adjusted"] is True
    assert metadata["analytic_invalid_ohlc_count"] == 1
    source = store.load_daily_source("000001")
    assert source.loc[pd.Timestamp(required[1]), "high"] == 19
    with pytest.raises(MarketDataError):
        store.load_daily_analytic("000001")


def test_etf_adjusted_source_native_merge_saves_source_view_and_rejects_analytic_view(monkeypatch, tmp_path):
    monkeypatch.setattr("trend_scanner.data.rolling_market_data_refresh.ETF_VALIDATED_ACCEPTANCE_TICKERS", ("000001",))
    required = ["2026-08-06", "2026-08-07", "2026-08-10"]

    class PresenceRawStore:
        def list_manifest(self, market=None):
            if market in ("KOSPI", "ETF"):
                return [{"market": market, "date": day, "status": "COMPLETE"} for day in required]
            return []

        def load_snapshot(self, market, day):
            return pd.DataFrame({"ticker": ["000001"]})

    store = AdjustedPriceStore(tmp_path / "adjusted")
    store.save_full("000001", _frame([required[0], required[-1]]), {
        "requested_start": required[0],
        "requested_end": required[-1],
    })

    class Provider:
        def load_daily(self, ticker, start, end):
            assert (ticker, start, end) == ("000001", required[1], required[1])
            return _source_native_relation_anomaly([required[1]], base=20)

    result = RollingEtfAdjustedUpdater(
        Provider(), store, raw_store=PresenceRawStore()
    ).refresh(required[0], required[-1])
    assert result["updated"] == ["000001"]
    metadata = store.load_metadata("000001")
    assert metadata["source_native_adjusted"] is True
    assert metadata["analytic_invalid_ohlc_count"] == 1
    source = store.load_daily_source("000001")
    assert source.loc[pd.Timestamp(required[1]), "high"] == 19
    with pytest.raises(MarketDataError):
        store.load_daily_analytic("000001")


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
