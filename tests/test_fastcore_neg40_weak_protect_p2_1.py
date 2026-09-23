from types import SimpleNamespace

import pandas as pd

import scripts.run_fastcore_neg40_weak_protect_p2_1 as runner
from scripts.run_fastcore_neg40_weak_protect_p2_1 import IdentitySegment, _candidate_trade, _pct


def _base_trade() -> dict:
    return {
        "ticker": "000001",
        "name": "000001",
        "market": "KOSPI",
        "trade_id": "000001_01",
        "trade_sequence": 1,
        "entry_signal_date": "2025-01-03",
        "entry_execution_date": "2025-01-06",
        "entry_open": 100.0,
        "entry_pattern_a_stage": "EARLY_TREND",
        "first_progressed_effective_trading_date": "2025-01-07",
        "exit_type": "EXIT3_PROGRESSED_TO_WEAK",
        "exit_signal_date": "2025-01-07",
        "exit_execution_date": "2025-01-08",
        "exit_price": 55.0,
        "terminal_return": -45.0,
        "mfe": 0.0,
        "mae": -45.0,
        "peak_giveback": 45.0,
        "profit_capture": None,
        "holding_weeks": 0.6,
        "trade_status": "REALIZED",
    }


def _segment() -> IdentitySegment:
    return IdentitySegment(
        ticker="000001",
        isu_cd="KR7000000001",
        market="KOSPI",
        effective_from=pd.Timestamp("2020-01-01"),
        effective_to=pd.Timestamp("2025-12-31"),
    )


def _daily(closes: list[float]) -> pd.DataFrame:
    dates = pd.to_datetime(["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10"][: len(closes)])
    return pd.DataFrame(
        {
            "open": [100.0, 90.0, 80.0, 70.0, 60.0][: len(closes)],
            "high": [101.0, 95.0, 85.0, 75.0, 65.0][: len(closes)],
            "low": [99.0, 55.0, 50.0, 55.0, 54.0][: len(closes)],
            "close": closes,
        },
        index=dates,
    )


def test_candidate_return_uses_exact_v2_arithmetic_for_rounding_ties():
    assert _pct(2055.0, 2400.0) == round(((2055.0 - 2400.0) / 2400.0) * 100.0, 2)
    assert _pct(2055.0, 2400.0) == -14.37


def test_weak_protect_defers_v2_exit_and_keeps_trade_open_through_cutoff():
    daily = _daily([100.0, 60.0, 55.0, 60.0])
    candidate, diagnostics = _candidate_trade(
        _base_trade(),
        pair_id="pair-1",
        segment=_segment(),
        daily=daily,
        stage_timeline={pd.Timestamp("2025-01-07"): "WEAK"},
        window=SimpleNamespace(
            effective_end=pd.Timestamp("2025-01-09"),
            execution_support=pd.Timestamp("2025-01-10"),
        ),
    )

    assert candidate["candidate_action"] == "WEAK_PROTECT_HOLD_OPEN"
    assert candidate["trade_status"] == "OPEN_AT_CUTOFF"
    assert candidate["control_exit_signal_date"] == "2025-01-07"
    assert candidate["exit_signal_date"] is None
    assert candidate["terminal_return"] == -40.0
    assert candidate["weak_protect_eod_events"] == 3
    assert diagnostics["deferred_control_exit_open_at_cutoff"] is True
    assert [event["date"] for event in diagnostics["soft_events"]] == [
        "2025-01-07",
        "2025-01-08",
        "2025-01-09",
    ]
    assert all(event["event_type"] == "WEAK_PROTECT" for event in diagnostics["soft_events"])
    assert all(event["pattern_a_stage"] == "WEAK" for event in diagnostics["soft_events"])
    assert all(event["execution_date"] is None for event in diagnostics["soft_events"])


def test_weak_is_rechecked_and_nonweak_neg40_soft_exits_next_local_open():
    daily = _daily([100.0, 60.0, 55.0, 58.0, 54.0])
    candidate, diagnostics = _candidate_trade(
        _base_trade(),
        pair_id="pair-2",
        segment=_segment(),
        daily=daily,
        stage_timeline={
            pd.Timestamp("2025-01-07"): "WEAK",
            pd.Timestamp("2025-01-09"): "BASE",
        },
        window=SimpleNamespace(
            effective_end=pd.Timestamp("2025-01-09"),
            execution_support=pd.Timestamp("2025-01-10"),
        ),
    )

    assert candidate["candidate_action"] == "SOFT_EXIT"
    assert candidate["exit_type"] == "SOFT_EXIT_NEG40_NON_WEAK"
    assert candidate["exit_signal_date"] == "2025-01-09"
    assert candidate["exit_execution_date"] == "2025-01-10"
    assert candidate["exit_price"] == 60.0
    assert candidate["terminal_return"] == -40.0
    assert diagnostics["soft_signal"] is True
    assert [event["event_type"] for event in diagnostics["soft_events"]] == [
        "WEAK_PROTECT",
        "WEAK_PROTECT",
        "SOFT_EXIT_SIGNAL",
    ]
    signal = diagnostics["soft_events"][-1]
    assert signal["date"] == "2025-01-09"
    assert signal["pattern_a_stage"] == "BASE"
    assert signal["execution_date"] == "2025-01-10"
    assert signal["execution_open"] == 60.0


def test_matched_ledger_is_one_row_per_identical_trade_and_recomputable():
    common = {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "identity_effective_from": "2020-01-01",
        "identity_effective_to": "2025-12-31",
        "entry_signal_date": "2025-01-03",
        "entry_execution_date": "2025-01-06",
        "entry_open": 100.0,
    }
    control = pd.DataFrame(
        [
            {
                **common,
                "pair_id": "p1",
                "trade_id": "000001_01",
                "exit_signal_date": "2025-02-03",
                "exit_execution_date": "2025-02-04",
                "exit_type": "V2_EXIT",
                "terminal_return": -10.0,
                "holding_days": 20,
                "trade_status": "REALIZED",
            },
            {
                **common,
                "pair_id": "p2",
                "trade_id": "000001_02",
                "exit_signal_date": None,
                "exit_execution_date": None,
                "exit_type": "NO_EXIT",
                "terminal_return": 2.0,
                "holding_days": 30,
                "trade_status": "OPEN_AT_CUTOFF",
            },
        ]
    )
    candidate = pd.DataFrame(
        [
            {
                **common,
                "pair_id": "p1",
                "trade_id": "000001_01",
                "exit_signal_date": "2025-02-05",
                "exit_execution_date": "2025-02-06",
                "exit_type": "SOFT_EXIT_NEG40_NON_WEAK",
                "terminal_return": -12.0,
                "holding_days": 22,
                "trade_status": "REALIZED",
                "candidate_action": "SOFT_EXIT",
            },
            {
                **common,
                "pair_id": "p2",
                "trade_id": "000001_02",
                "exit_signal_date": None,
                "exit_execution_date": None,
                "exit_type": "NO_EXIT",
                "terminal_return": 2.0,
                "holding_days": 30,
                "trade_status": "OPEN_AT_CUTOFF",
                "candidate_action": "CONTROL_PRESERVED",
            },
        ]
    )

    ledger = runner._build_matched_trade_ledger(control, candidate, cutoff_date="2025-05-30")

    assert len(ledger) == 2
    assert set(ledger["trade_id"]) == {"000001_01", "000001_02"}
    first = ledger.set_index("trade_id").loc["000001_01"]
    assert first["control_exit_or_cutoff_date"] == "2025-02-04"
    assert first["candidate_exit_or_cutoff_date"] == "2025-02-06"
    assert first["candidate_soft_exit"]
    assert first["paired_delta"] == -2.0
    second = ledger.set_index("trade_id").loc["000001_02"]
    assert second["control_exit_or_cutoff_date"] == "2025-05-30"
    assert second["candidate_exit_or_cutoff_date"] == "2025-05-30"
    assert second["control_open_at_cutoff"]
    assert second["candidate_open_at_cutoff"]
    assert runner._ledger_aggregates(ledger)["paired"]["count"] == 2


def test_calendar_month_end_v2_signal_uses_last_trading_eod_and_preserves_next_open():
    base = _base_trade()
    base.update(
        {
            "exit_signal_date": "2025-01-12",  # Sunday calendar label
            "exit_execution_date": "2025-01-13",
            "exit_price": 80.0,
            "terminal_return": -20.0,
        }
    )
    dates = pd.to_datetime(
        ["2025-01-06", "2025-01-07", "2025-01-08", "2025-01-09", "2025-01-10", "2025-01-13"]
    )
    daily = pd.DataFrame(
        {
            "open": [100.0, 99.0, 98.0, 97.0, 96.0, 80.0],
            "high": [101.0, 100.0, 99.0, 98.0, 97.0, 81.0],
            "low": [99.0, 98.0, 97.0, 96.0, 95.0, 79.0],
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 80.0],
        },
        index=dates,
    )
    candidate, _ = _candidate_trade(
        base,
        pair_id="pair-calendar-month-end",
        segment=_segment(),
        daily=daily,
        stage_timeline={pd.Timestamp("2025-01-10"): "BASE"},
        window=SimpleNamespace(
            effective_end=pd.Timestamp("2025-01-10"),
            execution_support=pd.Timestamp("2025-01-13"),
        ),
    )

    assert candidate["candidate_action"] == "CONTROL_EXIT"
    assert candidate["exit_signal_date"] == "2025-01-12"
    assert candidate["exit_execution_date"] == "2025-01-13"
    assert candidate["terminal_return"] == -20.0


def test_monthly_pattern_stage_is_available_at_last_local_eod_for_calendar_label(monkeypatch):
    daily = _daily([100.0, 100.0, 100.0, 100.0, 100.0])
    month_end = pd.Timestamp("2025-01-12")  # Sunday; last local session is Jan 10.
    context = SimpleNamespace(monthly_up_to=lambda _cutoff: pd.DataFrame(index=[month_end]))
    monkeypatch.setattr(runner.v2, "build_historical_snapshot_from_context", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        runner,
        "evaluate_pattern_a",
        lambda _snapshot: SimpleNamespace(stage=SimpleNamespace(value="WEAK")),
    )

    timeline = runner._stage_timeline(
        daily,
        context,
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-01-10"),
        calendar=None,
    )

    assert timeline == {pd.Timestamp("2025-01-10"): "WEAK"}
