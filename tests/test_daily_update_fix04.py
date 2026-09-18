"""Focused offline contracts for Daily Update Foundation FIX04."""

from __future__ import annotations

import pandas as pd

from tests.test_daily_update_fix02 import _ca_foundation, _raw_frame
from tests.test_daily_update_foundation_v01 import (
    FakeAdjusted,
    FakeEtfRaw,
    _foundation,
)
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.corporate_action_detector import CorporateActionSnapshot
from trend_scanner.data.corporate_action_refresh import RefreshResult
from trend_scanner.data.corporate_action_state_store import CorporateActionStateStore
from trend_scanner.data.daily_update_foundation import DailyUpdateFoundation
from trend_scanner.data.krx_raw_stock_store import KrxRawStockStore


def test_etf_raw_failure_after_common_write_cannot_validate_or_promote(tmp_path):
    failing_etf = FakeEtfRaw(None, fail=True)
    foundation, raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-09-01", "2026-09-02"],
        complete=["2026-09-01"],
        certified="2026-09-01",
        etf_raw=failing_etf,
    )
    failing_etf.raw = raw

    class WritingCommonRaw:
        def refresh(self, boundary, target, *, required_dates):
            for day in required_dates:
                raw.mark_complete(day, "KOSPI")
                raw.mark_complete(day, "KOSDAQ")
            return {
                "new_boundary": max(required_dates, default=boundary),
                "required_dates": list(required_dates),
                "updated_date_count": len(required_dates),
                "physical_write_count": len(required_dates) * 2,
                "production_write_performed": bool(required_dates),
            }

    foundation.common_raw_updater = WritingCommonRaw()
    before = (authority / "manifest.json").read_bytes()
    result = foundation.execute("2026-09-02", dry_run=False)

    assert result["final_status"] in {"BLOCKED", "FAILED"}
    assert result["authority_promotion"] == 0
    assert result["certified_through"] == "2026-09-01"
    assert result["production_write_count"] >= 2
    assert (authority / "manifest.json").read_bytes() == before


def test_etf_adjusted_failure_cannot_validate_or_promote(tmp_path):
    foundation, _raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-09-01", "2026-09-02"],
        complete=["2026-09-01"],
        certified="2026-09-01",
        etf_adjusted=FakeAdjusted(fail=True),
    )
    before = (authority / "manifest.json").read_bytes()
    result = foundation.execute("2026-09-02", dry_run=False)

    assert result["final_status"] in {"BLOCKED", "FAILED"}
    assert result["authority_promotion"] == 0
    assert result["certified_through"] == "2026-09-01"
    assert (authority / "manifest.json").read_bytes() == before


def test_common_raw_incomplete_cannot_validate_or_promote(tmp_path):
    foundation, raw, authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-09-01", "2026-09-02"],
        complete=["2026-09-01"],
        certified="2026-09-01",
    )

    class IncompleteCommonRaw:
        def refresh(self, boundary, target, *, required_dates):
            return {
                "new_boundary": boundary,
                "required_dates": list(required_dates),
                "missing_dates": list(required_dates[-1:]),
                "updated_date_count": 0,
                "physical_write_count": 0,
                "production_write_performed": False,
            }

    foundation.common_raw_updater = IncompleteCommonRaw()
    before = (authority / "manifest.json").read_bytes()
    result = foundation.execute("2026-09-02", dry_run=False)

    assert result["final_status"] == "BLOCKED"
    assert "common_raw" in result["reason"]
    assert result["authority_promotion"] == 0
    assert result["certified_through"] == "2026-09-01"
    assert (authority / "manifest.json").read_bytes() == before
    assert raw.get_manifest("KOSPI", "2026-09-02")["status"] == "NO_DATA"


def test_internal_gap_repair_is_validated_without_promotion(tmp_path):
    foundation, _raw, _authority, *_ = _foundation(
        tmp_path,
        calendar=["2026-09-01", "2026-09-02", "2026-09-03"],
        complete=["2026-09-01", "2026-09-03"],
        certified="2026-09-03",
    )
    result = foundation.execute("2026-09-03", dry_run=False)

    assert result["final_status"] == "PASS"
    assert result["status"] == "VALIDATED_NO_PROMOTION"
    assert result["boundary_unchanged"] is True
    assert result["authority_promotion"] == 0


def test_complete_noop_remains_zero_write_zero_promotion(tmp_path):
    foundation, _raw, _authority, common_raw, etf_raw, common_adjusted, etf_adjusted = _foundation(
        tmp_path,
        calendar=["2026-09-01", "2026-09-02"],
        complete=["2026-09-01", "2026-09-02"],
        certified="2026-09-02",
    )
    result = foundation.execute("2026-09-02", dry_run=False)

    assert result["final_status"] == "NOOP"
    assert result["network_request_count"] == 0
    assert result["production_write_count"] == 0
    assert result["authority_promotion"] == 0
    assert not common_raw.calls and not etf_raw.calls
    assert not common_adjusted.calls and not etf_adjusted.calls


def test_etf_dirty_state_is_excluded_but_common_dirty_state_still_refreshes(tmp_path):
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")
    for ticker in ("000001", "069500"):
        state.evaluate_and_record(CorporateActionSnapshot(ticker, "2026-09-01", 100))
        state.evaluate_and_record(CorporateActionSnapshot(ticker, "2026-09-02", 200))

    class Service:
        def __init__(self):
            self.state_store = state
            self.calls: list[str] = []

        def refresh_dirty(self, ticker, target):
            self.calls.append(ticker)
            assert state.claim_refresh(ticker)
            state.mark_clean(ticker)
            return RefreshResult(ticker, "CLEAN", "TEST_REFRESH", 0, None, None, None, target)

    service = Service()
    foundation = DailyUpdateFoundation(
        authority_dir=tmp_path / "authority",
        raw_store=object(),
        adjusted_store=AdjustedPriceStore(tmp_path / "adjusted"),
        common_adjusted_tickers=["000001"],
        common_raw_updater=None,
        etf_raw_updater=None,
        common_adjusted_updater=None,
        etf_adjusted_updater=None,
        corporate_action_state_store=state,
        corporate_action_refresh_service=service,
        corporate_action_snapshot_loader=lambda _day: [],
    )

    managed = foundation._managed_universe("2026-09-02")
    result = foundation._run_corporate_action_phase(
        "2026-09-02", [], managed_universe=managed
    )

    assert managed == {"000001"}
    assert service.calls == ["000001"]
    assert result["status"] == "PASS"
    assert result["remaining_dirty_tickers"] == []
    assert state.get("069500").status == "DIRTY"


def test_new_identity_skips_historical_baseline_scan(tmp_path, monkeypatch):
    raw = KrxRawStockStore(tmp_path / "raw")
    raw.save_snapshot("KOSPI", "2026-09-01", _raw_frame("2026-09-01", "123456", 100), "/test")
    raw.save_snapshot("KOSPI", "2026-09-02", _raw_frame("2026-09-02", "123456", 200), "/test")
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")

    class Provider:
        def load_daily(self, *_args):
            raise AssertionError("a new identity must use its first observation as baseline")

    foundation = _ca_foundation(tmp_path, raw, state, Provider(), ticker="123456")
    historical_loads: list[tuple[str, str]] = []
    original_load = raw.load_snapshot

    def counted_load(market, day):
        if day <= "2026-09-01":
            historical_loads.append((market, day))
        return original_load(market, day)

    monkeypatch.setattr(raw, "load_snapshot", counted_load)
    result = foundation._run_corporate_action_phase(
        "2026-09-02",
        ["2026-09-02"],
        managed_universe={"123456"},
        baseline_boundary="2026-09-01",
        current_identities={
            "123456": {
                "ticker": "123456",
                "market": "KOSPI",
                "markets": ("KOSPI",),
                "effective_from": "2026-09-02",
            }
        },
    )

    assert result["baseline_count"] == 0
    assert historical_loads == []
    assert state.get("123456").status == "CLEAN"


def test_mixed_identity_baseline_scans_only_existing_identity(tmp_path, monkeypatch):
    raw = KrxRawStockStore(tmp_path / "raw")
    old_day = pd.concat(
        [
            _raw_frame("2026-09-01", "000001", 100),
            _raw_frame("2026-09-01", "123456", 100),
        ],
        ignore_index=True,
    )
    new_day = pd.concat(
        [
            _raw_frame("2026-09-02", "000001", 100),
            _raw_frame("2026-09-02", "123456", 200),
        ],
        ignore_index=True,
    )
    raw.save_snapshot("KOSPI", "2026-09-01", old_day, "/test")
    raw.save_snapshot("KOSPI", "2026-09-02", new_day, "/test")
    state = CorporateActionStateStore(tmp_path / "state.sqlite3")

    class Provider:
        def load_daily(self, *_args):
            raise AssertionError("unchanged observations must not refresh")

    foundation = _ca_foundation(tmp_path, raw, state, Provider(), ticker="000001")
    historical_loads: list[tuple[str, str]] = []
    original_load = raw.load_snapshot

    def counted_load(market, day):
        if day <= "2026-09-01":
            historical_loads.append((market, day))
        return original_load(market, day)

    monkeypatch.setattr(raw, "load_snapshot", counted_load)
    result = foundation._run_corporate_action_phase(
        "2026-09-02",
        ["2026-09-02"],
        managed_universe={"000001", "123456"},
        baseline_boundary="2026-09-01",
        current_identities={
            "000001": {
                "ticker": "000001",
                "market": "KOSPI",
                "markets": ("KOSPI",),
                "effective_from": "2026-08-01",
            },
            "123456": {
                "ticker": "123456",
                "market": "KOSPI",
                "markets": ("KOSPI",),
                "effective_from": "2026-09-02",
            },
        },
    )

    assert result["baseline_count"] == 1
    assert historical_loads == [("KOSPI", "2026-09-01")]
    assert state.get("000001").status == "CLEAN"
    assert state.get("123456").status == "CLEAN"
