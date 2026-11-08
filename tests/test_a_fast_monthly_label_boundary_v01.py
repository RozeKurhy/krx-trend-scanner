from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from dataclasses import asdict
import json

import pandas as pd
import pytest

from scripts import run_daily_update_phase4b_v01 as phase4b
from trend_scanner.reporting import a_fast_core_report
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.backtest.snapshot_context import build_historical_snapshot_from_context, build_precomputed_ticker_context
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation import pattern_a_fast_core_v02_reentry as v2


@pytest.fixture
def monthly_inputs():
    sessions = pd.bdate_range("2024-01-01", "2026-10-30")
    ends = pd.Series(sessions, index=sessions).groupby(sessions.to_period("M")).max().tolist()
    calendar = MarketCalendarAuthority.from_dates(sessions, completed_month_ends=ends)
    days = sessions.append(pd.DatetimeIndex(["2026-11-02"]))
    daily = pd.DataFrame(
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0,
         "volume": 1_000.0, "trading_value": 100_000.0}, index=days,
    )
    daily.loc[pd.Timestamp("2026-11-02"), ["open", "high", "low", "close"]] = 9999.0
    return daily, calendar


@pytest.mark.parametrize("use_precomputed_context", [True, False])
@pytest.mark.parametrize(
    ("cutoff", "october_expected"),
    [("2026-10-29", False), ("2026-10-30", True), ("2026-11-01", True)],
)
def test_monthly_replay_uses_certified_session_not_calendar_label(
    monkeypatch, monthly_inputs, cutoff, october_expected, use_precomputed_context,
):
    daily, calendar = monthly_inputs
    observed = []
    fast = {
        "fast_machine_stage": "TRIGGER", "fast_machine_stage_status": "READY",
        "fast_monthly_permission_state": "PERMITTED_REGIME", "fast_daily_risk_state": "NORMAL",
        "fast_score_status": "READY", "pattern_a_stage": "TRANSITION", "fast_score": 50.0,
    }
    monkeypatch.setattr(v2, "evaluate_pattern_a_fast", lambda *_args, **_kw: fast)
    monkeypatch.setattr(v2, "evaluate_pattern_a", lambda _snap: SimpleNamespace(
        stage=SimpleNamespace(value="TRANSITION"), score=50.0,
    ))
    original_fast = v2.build_historical_snapshot_from_context
    original_legacy = v2.build_historical_snapshot

    def record_fast(context, day, **kwargs):
        snapshot = original_fast(context, day, **kwargs)
        observed.append((pd.Timestamp(day), snapshot.effective_as_of, snapshot.monthly.index[-1]))
        return snapshot

    def record_legacy(ticker, name, data, day, **kwargs):
        snapshot = original_legacy(ticker, name, data, day, **kwargs)
        observed.append((pd.Timestamp(day), snapshot.effective_as_of, snapshot.monthly.index[-1]))
        return snapshot

    monkeypatch.setattr(v2, "build_historical_snapshot_from_context", record_fast)
    monkeypatch.setattr(v2, "build_historical_snapshot", record_legacy)
    trades = v2.simulate_ticker_core_v02_reentry(
        ticker="000001", name="fixture", market="KOSPI", daily=daily,
        score_contract={}, stage_contract={}, cutoff_date=pd.Timestamp(cutoff),
        entry_search_start=pd.Timestamp("2026-10-02"), market_calendar=calendar,
        use_precomputed_context=use_precomputed_context, strict_errors=True,
    )
    assert len(trades) == 1
    october = [row for row in observed if row[2] == pd.Timestamp("2026-10-31")]
    assert bool(october) is october_expected
    if october:
        assert october == [(pd.Timestamp("2026-10-30"), pd.Timestamp("2026-10-30"), pd.Timestamp("2026-10-31"))]
    assert all(effective <= pd.Timestamp(cutoff) for _, effective, _ in observed)
    assert trades[0].entry_execution_date == "2026-10-05"
    assert trades[0].exit_execution_date is None


def test_uncertified_terminal_month_is_not_evaluated(monkeypatch, monthly_inputs):
    daily, calendar = monthly_inputs
    incomplete = MarketCalendarAuthority.from_dates(
        calendar.trading_dates,
        completed_month_ends=[d for d in calendar.completed_month_ends if d.month != 10 or d.year != 2026],
    )
    monkeypatch.setattr(v2, "evaluate_pattern_a_fast", lambda *_a, **_k: {
        "fast_machine_stage": "TRIGGER", "fast_machine_stage_status": "READY",
        "fast_monthly_permission_state": "PERMITTED_REGIME", "fast_daily_risk_state": "NORMAL",
        "fast_score_status": "READY", "pattern_a_stage": "TRANSITION", "fast_score": 50.0,
    })
    monkeypatch.setattr(v2, "build_historical_snapshot_from_context", lambda *_a, **_k: pytest.fail(
        "uncertified terminal month cannot be evaluated"
    ))
    trades = v2.simulate_ticker_core_v02_reentry(
        "000001", "fixture", "KOSPI", daily, {}, {}, cutoff_date=pd.Timestamp("2026-11-01"),
        entry_search_start=pd.Timestamp("2026-10-02"), market_calendar=incomplete, strict_errors=True,
    )
    assert len(trades) == 1


def _write_report(stage: Path, *, action_reason: str) -> None:
    folder = stage / "json"
    folder.mkdir(parents=True)
    payload = {
        "ticker": "000001", "asset_type": "COMMON", "requested_as_of": "2026-11-01",
        "reference_market_date": "2026-10-30", "a_fast_core": {
            "strategy_id": phase4b.PROMOTED_STRATEGY_ID,
            "strategy_replay_mode": phase4b.FULL_HISTORY_ALIGNMENT_WEB,
            "canonical_position": "DATA_UNAVAILABLE", "action_reason": action_reason,
            "current_trade": None, "trade_history": [],
        },
    }
    (folder / "000001.json").write_text(json.dumps(payload), encoding="utf-8")


def test_phase4b_rejects_evaluator_execution_failed_before_finalization(tmp_path):
    _write_report(tmp_path, action_reason="EVALUATOR_EXECUTION_FAILED")
    with pytest.raises(phase4b.Phase4BError, match="EVALUATOR_EXECUTION_FAILED"):
        phase4b.finalize_full_history_alignment_reports(
            tmp_path, {"000001"}, "2026-11-01", "2026-10-30"
        )


def test_phase4b_allows_legitimate_unavailable_without_failed_evaluator(tmp_path):
    _write_report(tmp_path, action_reason="CURRENT_SESSION_PRICE_UNAVAILABLE")
    phase4b.finalize_full_history_alignment_reports(tmp_path, {"000001"}, "2026-11-01", "2026-10-30")
    assert phase4b.validate_full_history_alignment_corpus(
        tmp_path, "2026-11-01", "2026-10-30", {"000001"}
    )["valid"]


@pytest.mark.parametrize(
    ("sessions", "label", "cutoff", "expected"),
    [
        (["2016-09-30", "2016-10-04"], "2016-09-30", "2016-09-30", "2016-09-30"),
        (["2021-12-29", "2021-12-30"], "2021-12-31", "2021-12-30", "2021-12-30"),
        (["2026-02-26", "2026-02-27"], "2026-02-28", "2026-02-27", "2026-02-27"),
        (["2024-02-28", "2024-02-29"], "2024-02-29", "2024-02-29", "2024-02-29"),
    ],
)
def test_calendar_label_maps_to_authorized_month_end(sessions, label, cutoff, expected):
    dates = pd.to_datetime(sessions)
    month_ends = pd.Series(dates, index=dates).groupby(dates.to_period("M")).max().tolist()
    calendar = MarketCalendarAuthority.from_dates(dates, completed_month_ends=month_ends)
    observed = v2._completed_monthly_observations(
        pd.DatetimeIndex([label]), pd.Timestamp(sessions[0]), pd.Timestamp(cutoff), calendar,
    )
    assert observed == [(pd.Timestamp(label), pd.Timestamp(expected))]


@pytest.mark.parametrize("cutoff", ["2026-10-29", "2026-10-30"])
def test_legacy_and_optimized_snapshot_parity_and_no_future_price(monthly_inputs, cutoff):
    daily, calendar = monthly_inputs
    target = pd.Timestamp(cutoff)
    legacy = build_historical_snapshot("000001", "fixture", daily, target,
                                       include_incomplete_periods=False, market_calendar=calendar)
    context = build_precomputed_ticker_context("000001", "fixture", daily)
    optimized = build_historical_snapshot_from_context(context, target,
                                                       include_incomplete_periods=False, market_calendar=calendar)
    limited = build_historical_snapshot("000001", "fixture", daily.loc[:target], target,
                                        include_incomplete_periods=False, market_calendar=calendar)
    pd.testing.assert_frame_equal(legacy.monthly, optimized.monthly)
    pd.testing.assert_frame_equal(legacy.weekly, optimized.weekly)
    pd.testing.assert_frame_equal(legacy.monthly, limited.monthly)
    pd.testing.assert_frame_equal(legacy.weekly, limited.weekly)
    pd.testing.assert_frame_equal(pd.DataFrame([asdict(legacy.features)]), pd.DataFrame([asdict(optimized.features)]))
    pd.testing.assert_frame_equal(pd.DataFrame([asdict(legacy.features)]), pd.DataFrame([asdict(limited.features)]))
    a, b = evaluate_pattern_a(legacy), evaluate_pattern_a(optimized)
    assert a.stage == b.stage and a.score == b.score
    assert legacy.effective_as_of == optimized.effective_as_of == target


@pytest.fixture
def continuity_case(tmp_path):
    previous = tmp_path / "20261024"
    staging = tmp_path / "20261101"
    (previous / "json").mkdir(parents=True)
    (staging / "json").mkdir(parents=True)
    strategy = phase4b.PROMOTED_STRATEGY_ID
    lineage = {"strategy_id": strategy, "entry_strategy_id": strategy, "exit_strategy_id": strategy}
    realized = {"trade_id": "005180_01", "trade_sequence": 1, "trade_status": "REALIZED",
                "entry_signal_date": "2026-02-13", "entry_execution_date": "2026-02-19", "entry_open": 84800.0,
                "exit_signal_date": "2026-03-30", "exit_execution_date": "2026-03-31", "exit_price": 71100.0,
                "exit_type": "LOSS_GUARD_CLOSE_LE_NEG_15", "return_pct": -16.16, **lineage}
    opened = {"trade_id": "005180_02", "trade_sequence": 2, "trade_status": "OPEN_AT_CUTOFF",
              "entry_signal_date": "2026-09-04", "entry_execution_date": "2026-09-07", "entry_open": 88700.0,
              "exit_signal_date": "2026-10-23", "exit_execution_date": None, "exit_price": None,
              "exit_type": "LOSS_GUARD_CLOSE_LE_NEG_15", "return_pct": -15.11, **lineage}
    settled = {**opened, "trade_status": "REALIZED", "exit_execution_date": "2026-10-26",
               "exit_price": 74200.0, "return_pct": -16.35}
    old = {"ticker": "005180", "asset_type": "COMMON", "reference_market_date": "2026-10-23",
           "a_fast_core": {"canonical_position": "OPEN", "trade_history": [realized, opened]}}
    new = {"ticker": "005180", "asset_type": "COMMON", "reference_market_date": "2026-10-30",
           "a_fast_core": {"canonical_position": "FLAT", "trade_history": [realized, settled]}}
    (previous / "json/005180.json").write_text(json.dumps(old), encoding="utf-8")
    (staging / "json/005180.json").write_text(json.dumps(new), encoding="utf-8")
    sessions = pd.to_datetime(["2026-10-23", "2026-10-26", "2026-10-30"])
    calendar = MarketCalendarAuthority.from_dates(sessions, completed_month_ends=[sessions[-1]])
    return previous, staging, old, new, calendar


def _check_continuity(case, *, identity=None, adjusted_open=None):
    previous, staging, _old, _new, calendar = case
    return phase4b.validate_prior_trade_continuity(
        previous, staging, reference_market_date="2026-10-30", market_calendar=calendar,
        identity_resolver=identity or (lambda _ticker, _date: "KR7005180005"),
        adjusted_open_resolver=adjusted_open or (lambda _ticker, _date: 74200.0),
    )


def test_prior_realized_and_verified_open_to_realized_are_preserved(continuity_case):
    result = _check_continuity(continuity_case)
    assert result["prior_realized_count"] == 1
    assert result["prior_open_count"] == 1
    assert result["open_to_realized_count"] == 1
    assert result["lost_trade_count"] == result["changed_realized_count"] == 0


@pytest.mark.parametrize("defect", ["lost_realized", "changed_realized", "lost_open", "duplicate", "wrong_open", "identity_change"])
def test_prior_trade_continuity_fails_closed(continuity_case, defect):
    _previous, staging, _old, new, _calendar = continuity_case
    history = new["a_fast_core"]["trade_history"]
    identity = None
    adjusted_open = None
    if defect == "lost_realized":
        del history[0]
    elif defect == "changed_realized":
        history[0]["exit_price"] = 70000.0
    elif defect == "lost_open":
        del history[1]
    elif defect == "duplicate":
        history.append(dict(history[0]))
    elif defect == "wrong_open":
        adjusted_open = lambda _ticker, _date: 70000.0
    elif defect == "identity_change":
        identity = lambda _ticker, day: "KR7005180005" if day == "2026-10-23" else "KR7005180999"
    (staging / "json/005180.json").write_text(json.dumps(new), encoding="utf-8")
    with pytest.raises(phase4b.Phase4BError):
        _check_continuity(continuity_case, identity=identity, adjusted_open=adjusted_open)


def test_completed_month_label_is_not_a_future_execution(continuity_case):
    previous, staging, old, new, _calendar = continuity_case
    old["a_fast_core"].update({"canonical_position": "FLAT", "trade_history": []})
    new["a_fast_core"].update({"canonical_position": "OPEN", "trade_history": [{
        **new["a_fast_core"]["trade_history"][1],
        "trade_status": "OPEN_AT_CUTOFF", "exit_type": "EXIT3_PROGRESSED_TO_BASE",
        "exit_signal_date": "2026-10-31", "exit_execution_date": None, "exit_price": None,
    }]})
    (previous / "json/005180.json").write_text(json.dumps(old), encoding="utf-8")
    (staging / "json/005180.json").write_text(json.dumps(new), encoding="utf-8")
    assert _check_continuity(continuity_case)["status"] == "PASS"


@pytest.mark.parametrize("cutoff", ["2026-10-30", "2026-11-01"])
def test_month_end_exit_is_actionable_on_observed_session_without_future_fill(monkeypatch, monthly_inputs, cutoff):
    daily, calendar = monthly_inputs
    fast = {"fast_machine_stage": "TRIGGER", "fast_machine_stage_status": "READY",
            "fast_monthly_permission_state": "PERMITTED_REGIME", "fast_daily_risk_state": "NORMAL",
            "fast_score_status": "READY", "pattern_a_stage": "EARLY_TREND", "fast_score": 50.0}
    monkeypatch.setattr(v2, "evaluate_pattern_a_fast", lambda *_args, **_kw: fast)

    def stage(snapshot):
        month = snapshot.effective_as_of.month
        value = "PROGRESSED" if month == 9 else "BASE"
        return SimpleNamespace(stage=SimpleNamespace(value=value), score=70.0 if month == 9 else 30.0)

    monkeypatch.setattr(v2, "evaluate_pattern_a", stage)
    trades = v2.simulate_ticker_core_v02_reentry(
        "000001", "fixture", "KOSPI", daily, {}, {}, cutoff_date=pd.Timestamp(cutoff),
        entry_search_start=pd.Timestamp("2026-09-04"), market_calendar=calendar, strict_errors=True,
    )
    assert len(trades) == 1 and trades[0].exit_signal_date == "2026-10-31"
    assert trades[0].exit_execution_date is None and trades[0].trade_status == "OPEN_AT_CUTOFF"
    monkeypatch.setattr(a_fast_core_report, "simulate_ticker_core_v02_reentry", lambda **_kwargs: trades)
    monkeypatch.setattr(a_fast_core_report, "evaluate_pattern_a", stage)
    section = a_fast_core_report._build_a_fast_core_section_impl(
        ticker="000001", name="fixture", market="KOSPI", daily=daily,
        requested_as_of=pd.Timestamp(cutoff), score_contract={"test": True}, stage_contract={"test": True},
        metadata_trusted=True, market_calendar=calendar, promotion_gate=SimpleNamespace(),
        historical_alignment_replay=True,
    )
    assert section.action == "EXIT_NEXT_OPEN"
    assert section.current_trade.pending_exit_signal_date == "2026-10-31"
    assert section.trade_history[0].exit_execution_date is None
    assert section.protection_state.progressed_hwm_score == 70.0


def test_suspended_ticker_uses_market_month_end_without_fake_daily_row(monkeypatch, monthly_inputs):
    daily, calendar = monthly_inputs
    daily = daily.drop(pd.Timestamp("2026-10-30"))
    monkeypatch.setattr(v2, "evaluate_pattern_a_fast", lambda *_args, **_kw: {
        "fast_machine_stage": "TRIGGER", "fast_machine_stage_status": "READY",
        "fast_monthly_permission_state": "PERMITTED_REGIME", "fast_daily_risk_state": "NORMAL",
        "fast_score_status": "READY", "pattern_a_stage": "TRANSITION", "fast_score": 50.0,
    })
    monkeypatch.setattr(v2, "evaluate_pattern_a", lambda _snap: SimpleNamespace(
        stage=SimpleNamespace(value="TRANSITION"), score=50.0,
    ))
    observed = []
    original = v2.build_historical_snapshot_from_context

    def capture(context, day, **kwargs):
        snap = original(context, day, **kwargs)
        observed.append((pd.Timestamp(day), snap.effective_as_of, snap.monthly.index[-1]))
        return snap

    monkeypatch.setattr(v2, "build_historical_snapshot_from_context", capture)
    trades = v2.simulate_ticker_core_v02_reentry(
        "000001", "fixture", "KOSPI", daily, {}, {}, cutoff_date=pd.Timestamp("2026-10-30"),
        entry_search_start=pd.Timestamp("2026-10-02"), market_calendar=calendar, strict_errors=True,
    )
    assert len(trades) == 1
    assert observed == [(pd.Timestamp("2026-10-30"), pd.Timestamp("2026-10-29"), pd.Timestamp("2026-10-31"))]
    assert pd.Timestamp("2026-10-30") not in daily.index


def test_inconsistent_completed_month_authority_fails_closed(monthly_inputs):
    _, calendar = monthly_inputs
    ends = [pd.Timestamp("2026-10-29") if d == pd.Timestamp("2026-10-30") else d
            for d in calendar.completed_month_ends]
    inconsistent = MarketCalendarAuthority.from_dates(calendar.trading_dates, completed_month_ends=ends)
    with pytest.raises(v2.MarketCalendarUnavailableError, match="AUTHORITY_MISMATCH"):
        v2._completed_monthly_observations(pd.DatetimeIndex(["2026-10-31"]),
                                           pd.Timestamp("2026-10-01"), pd.Timestamp("2026-10-30"), inconsistent)
