"""Regression coverage for certified month-end labels and exact fills."""

import json
from types import SimpleNamespace

import pandas as pd
import pytest

from scripts import run_daily_update_phase4b_v01 as phase4b
from trend_scanner.data.market_calendar import MarketCalendarAuthority


@pytest.fixture
def case(tmp_path):
    previous, staging = tmp_path / "previous", tmp_path / "staging"
    (previous / "json").mkdir(parents=True)
    (staging / "json").mkdir(parents=True)
    strategy = phase4b.PROMOTED_STRATEGY_ID
    lineage = {key: strategy for key in ("strategy_id", "entry_strategy_id", "exit_strategy_id")}
    opened = {
        "trade_id": "000001_01", "trade_sequence": 1, "trade_status": "OPEN_AT_CUTOFF",
        "entry_signal_date": "2024-08-01", "entry_execution_date": "2024-08-02", "entry_open": 100.0,
        "exit_type": "EXIT3_PROGRESSED_TO_WEAK", "exit_signal_date": "2024-08-31",
        "exit_execution_date": None, "exit_price": None, **lineage,
    }
    settled = {**opened, "trade_status": "REALIZED", "exit_execution_date": "2024-09-02",
               "exit_price": 110.0, "return_pct": 10.0}
    pending = {"trade_id": opened["trade_id"], "trade_status": "OPEN",
               "pending_exit_type": opened["exit_type"], "pending_exit_signal_date": opened["exit_signal_date"], **lineage}
    old = {"ticker": "000001", "asset_type": "COMMON", "reference_market_date": "2024-08-30",
           "a_fast_core": {"strategy_id": strategy, "canonical_position": "OPEN", "action": "EXIT_NEXT_OPEN",
                           "current_trade": pending, "trade_history": [opened]}}
    new = {"ticker": "000001", "asset_type": "COMMON", "reference_market_date": "2024-09-04",
           "a_fast_core": {"strategy_id": strategy, "canonical_position": "FLAT", "trade_history": [settled]}}
    dates = pd.to_datetime(["2024-08-29", "2024-08-30", "2024-09-02", "2024-09-03", "2024-09-04"])
    calendar = MarketCalendarAuthority.from_dates(dates, completed_month_ends=[pd.Timestamp("2024-08-30")])
    opens = {"2024-08-29": 100.0, "2024-08-30": 100.0, "2024-09-02": 110.0,
             "2024-09-03": 111.0, "2024-09-04": 112.0}
    return {"previous": previous, "staging": staging, "old": old, "new": new,
            "calendar": calendar, "opens": opens}


def check(case, identity=None):
    for directory, report in ((case["previous"], case["old"]), (case["staging"], case["new"])):
        (directory / "json" / "000001.json").write_text(json.dumps(report), encoding="utf-8")
    def observation(_ticker, day):
        value = case["opens"].get(day)
        if isinstance(value, Exception):
            raise value
        return value
    return phase4b.validate_prior_trade_continuity(
        case["previous"], case["staging"], reference_market_date=case.get("reference", "2024-09-04"),
        market_calendar=case["calendar"], identity_resolver=identity or (lambda _ticker, _day: "KR7000001000"),
        adjusted_open_resolver=observation,
    )


def test_weekend_monthend_label_transitions_at_first_verified_open(case):
    assert check(case)["open_to_realized_count"] == 1


def test_monthend_that_is_a_session_transitions_at_first_verified_open(case):
    dates = pd.to_datetime(["2024-07-30", "2024-07-31", "2024-08-01", "2024-08-02"])
    case["calendar"] = MarketCalendarAuthority.from_dates(dates, completed_month_ends=[pd.Timestamp("2024-07-31")])
    case["opens"] = {"2024-07-31": 100.0, "2024-08-01": 110.0, "2024-08-02": 112.0}
    case["reference"] = "2024-08-02"
    case["old"]["reference_market_date"] = "2024-07-31"
    case["new"]["reference_market_date"] = case["reference"]
    for report in (case["old"], case["new"]):
        report["a_fast_core"]["trade_history"][0].update(
            entry_signal_date="2024-07-01", entry_execution_date="2024-07-02", exit_signal_date="2024-07-31"
        )
    case["old"]["a_fast_core"]["current_trade"]["pending_exit_signal_date"] = "2024-07-31"
    case["new"]["a_fast_core"]["trade_history"][0]["exit_execution_date"] = "2024-08-01"
    assert check(case)["open_to_realized_count"] == 1


def test_closed_ticker_waits_for_first_valid_ticker_open(case):
    case["opens"]["2024-09-02"] = None
    case["new"]["a_fast_core"]["trade_history"][0].update(
        exit_execution_date="2024-09-03", exit_price=111.0, return_pct=11.0
    )
    assert check(case)["open_to_realized_count"] == 1


def test_pending_exit_remains_open_when_all_later_sessions_are_unobserved(case):
    for day in ("2024-09-02", "2024-09-03", "2024-09-04"):
        case["opens"][day] = None
    before = case["old"]["a_fast_core"]["trade_history"][0]
    case["new"]["a_fast_core"].update(canonical_position="OPEN", trade_history=[dict(before)])
    assert check(case)["prior_open_still_open_count"] == 1


@pytest.mark.parametrize("condition", ["absent", "placeholder", "unverified_partition", "source_gap", "volume_mismatch"])
def test_production_observation_requires_raw_v2_and_pit(case, monkeypatch, condition):
    for directory, report in ((case["previous"], case["old"]), (case["staging"], case["new"])):
        if report is case["new"] and condition in {"absent", "placeholder"}:
            report["a_fast_core"]["trade_history"][0].update(
                exit_execution_date="2024-09-03", exit_price=111.0, return_pct=11.0
            )
        (directory / "json" / "000001.json").write_text(json.dumps(report), encoding="utf-8")

    class FakeRawStore:
        def __init__(self, _root):
            pass

        def verify_snapshot(self, market, day):
            good = not (condition == "unverified_partition" and day == "2024-09-02" and market == "KOSPI")
            return {"valid": good, "status": "COMPLETE" if good else "FAILED"}

    class FakeRepository:
        def get_raw_daily(self, _ticker, day, _end):
            if day == "2024-09-02" and condition == "absent":
                return pd.DataFrame()
            if day == "2024-09-02" and condition == "placeholder":
                row = {"open": 0, "high": 0, "low": 0, "close": 100, "volume": 0, "trading_value": 0}
            else:
                price = case["opens"][day]
                row = {"open": price, "high": price, "low": price, "close": price,
                       "volume": 1000, "trading_value": 100000}
            return pd.DataFrame([row], index=pd.to_datetime([day]))

        def get_daily(self, ticker, day, end):
            if day == "2024-09-02" and condition in {"absent", "placeholder", "source_gap"}:
                return pd.DataFrame()
            frame = self.get_raw_daily(ticker, day, end).copy()
            if day == "2024-09-02" and condition == "volume_mismatch":
                frame.loc[:, "volume"] = 999
            return frame

    dates = [str(day)[:10] for day in case["calendar"].trading_dates]
    intervals = [{"state": "COMMON", "ticker": "000001", "isu_cd": "KR7000001000",
                  "effective_from": "2024-08-01", "effective_to": "2024-09-04"}]
    monkeypatch.setattr(phase4b, "load_rolling_authority", lambda _path: SimpleNamespace(certified_through="2024-09-04"))
    monkeypatch.setattr(phase4b, "validate_merged_authority_coherence", lambda *_: ({"intervals": intervals}, {"trading_dates": dates}))
    monkeypatch.setattr(phase4b, "load_rolling_production_market_calendar", lambda _root: case["calendar"])
    monkeypatch.setattr(phase4b, "KrxRawStockStore", FakeRawStore)
    monkeypatch.setattr(phase4b, "build_production_repository_v2", lambda *_args, **_kwargs: FakeRepository())

    def run():
        return phase4b._validate_production_trade_continuity(
            case["previous"].parent, case["previous"], case["staging"], "2024-09-04"
        )
    if condition in {"absent", "placeholder"}:
        assert run()["open_to_realized_count"] == 1
    else:
        with pytest.raises(phase4b.Phase4BError):
            run()


@pytest.mark.parametrize("defect", [
    "non_monthend_label", "uncertified_month", "different_month", "inconsistent_month_end",
    "future_fill", "wrong_strategy", "unproven_signal", "changed_signal", "no_signal_observation",
    "zero_open", "skipped_valid_open", "identity_change", "unknown_open",
])
def test_invalid_signal_or_fill_fails_closed(case, monkeypatch, defect):
    identity = None
    before = case["old"]["a_fast_core"]["trade_history"][0]
    after = case["new"]["a_fast_core"]["trade_history"][0]
    pending = case["old"]["a_fast_core"]["current_trade"]
    if defect == "non_monthend_label":
        before["exit_signal_date"] = after["exit_signal_date"] = pending["pending_exit_signal_date"] = "2024-08-24"
    elif defect == "uncertified_month":
        monkeypatch.setattr(case["calendar"], "get_actual_month_end", lambda *_: None)
    elif defect == "different_month":
        monkeypatch.setattr(case["calendar"], "get_actual_month_end", lambda *_: pd.Timestamp("2024-07-31"))
    elif defect == "inconsistent_month_end":
        monkeypatch.setattr(case["calendar"], "get_actual_month_end", lambda *_: pd.Timestamp("2024-08-29"))
    elif defect == "future_fill":
        after["exit_execution_date"] = "2024-09-05"
    elif defect == "wrong_strategy":
        before["exit_strategy_id"] = after["exit_strategy_id"] = "OTHER_STRATEGY"
    elif defect == "unproven_signal":
        case["old"]["a_fast_core"]["action"] = "WAIT"
    elif defect == "changed_signal":
        pending["pending_exit_signal_date"] = "2024-08-30"
    elif defect == "no_signal_observation":
        case["opens"]["2024-08-30"] = None
    elif defect == "zero_open":
        case["opens"]["2024-09-02"] = 0.0
        after.update(exit_execution_date="2024-09-03", exit_price=111.0, return_pct=11.0)
    elif defect == "skipped_valid_open":
        after.update(exit_execution_date="2024-09-03", exit_price=111.0, return_pct=11.0)
    elif defect == "identity_change":
        identity = lambda _ticker, day: "KR7000001999" if day == "2024-09-02" else "KR7000001000"
    elif defect == "unknown_open":
        case["opens"]["2024-09-02"] = RuntimeError("source unavailable")
    with pytest.raises(phase4b.Phase4BError):
        check(case, identity=identity)
