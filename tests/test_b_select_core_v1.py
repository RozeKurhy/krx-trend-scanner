from __future__ import annotations

import pytest

from trend_scanner.strategies.b_select_core_v1 import (
    BSelectLifecycleError,
    exact_month_end_sessions,
    is_entry_signal,
    is_exit_signal,
    next_exact_session,
    replay_lifecycle,
)


@pytest.mark.parametrize("previous_stage", ["EARLY_TREND", "TRANSITION"])
def test_entry_requires_depressed_progressed_and_allowed_previous_stage(previous_stage: str):
    assert is_entry_signal("DEPRESSED", "PROGRESSED", previous_stage)
    assert not is_entry_signal("NORMAL", "PROGRESSED", previous_stage)
    assert not is_entry_signal("DEPRESSED", "EARLY_TREND", previous_stage)


@pytest.mark.parametrize("previous_stage", ["WEAK", "BASE", "PROGRESSED", "UNAVAILABLE", None])
def test_entry_rejects_disallowed_previous_stage(previous_stage: str | None):
    assert not is_entry_signal("DEPRESSED", "PROGRESSED", previous_stage)


def test_only_normal_exits_an_open_position_and_deep_depressed_is_not_a_stop():
    assert is_exit_signal(is_open=True, pattern_b_state="NORMAL")
    for state in ("DEEP_DEPRESSED", "DEPRESSED", "OVERHEATED", "EXTREME_OVERHEATED", None):
        assert not is_exit_signal(is_open=True, pattern_b_state=state)
    assert not is_exit_signal(is_open=False, pattern_b_state="NORMAL")


def test_exact_month_end_sessions_use_exchange_sequence_for_calendar_edges():
    calendar = [
        "2026-01-29", "2026-01-30", "2026-02-02", "2026-02-27",
        "2026-03-02", "2026-03-31", "2026-12-30", "2027-01-04", "2027-01-05",
    ]
    assert exact_month_end_sessions(calendar) == frozenset({
        "2026-01-30", "2026-02-27", "2026-03-31", "2026-12-30",
    })
    assert "2027-01-05" not in exact_month_end_sessions(calendar)


def test_midmonth_entry_signal_is_rejected_even_when_conditions_match():
    with pytest.raises(BSelectLifecycleError, match="ENTRY_SIGNAL_NOT_MONTH_END"):
        replay_lifecycle(
            [{"date": "2026-09-29", "state": "DEPRESSED"}],
            [{"date": "2026-09-29", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "TRANSITION"}],
            trading_dates=["2026-09-29", "2026-09-30", "2026-10-01"],
            exact_opens={},
            reference_market_date="2026-09-29",
        )


def test_midmonth_normal_does_not_exit_open_position():
    result = replay_lifecycle(
        [{"date": "2026-09-29", "state": "NORMAL"}],
        [],
        trading_dates=["2026-09-29", "2026-09-30", "2026-10-01"],
        exact_opens={},
        reference_market_date="2026-09-29",
        initial_position={
            "trade_sequence": 1,
            "entry_signal_date": "2026-08-31",
            "entry_execution_date": "2026-09-01",
            "entry_open": 100.0,
            "exit_signal_date": None,
            "exit_execution_date": None,
        },
        initial_trade_sequence=1,
    )
    assert result["position"]["exit_signal_date"] is None
    assert result["pending"] is None


def test_midmonth_normal_reverting_before_month_end_does_not_exit():
    result = replay_lifecycle(
        [
            {"date": "2026-09-29", "state": "NORMAL"},
            {"date": "2026-09-30", "state": "DEPRESSED"},
        ],
        [],
        trading_dates=["2026-09-29", "2026-09-30", "2026-10-01"],
        exact_opens={},
        reference_market_date="2026-09-30",
        initial_position={
            "trade_sequence": 1,
            "entry_signal_date": "2026-08-31",
            "entry_execution_date": "2026-09-01",
            "entry_open": 100.0,
            "exit_signal_date": None,
            "exit_execution_date": None,
        },
        initial_trade_sequence=1,
    )
    assert result["position"]["exit_signal_date"] is None
    assert result["pending"] is None


def test_next_open_fill_uses_immediate_exact_session_and_normal_exit_stays_pending():
    calendar = ["2026-08-31", "2026-09-01", "2026-09-30", "2026-10-01", "2026-10-02"]
    result = replay_lifecycle(
        [
            {"date": "2026-08-31", "state": "DEPRESSED"},
            {"date": "2026-09-30", "state": "NORMAL"},
        ],
        [{
            "date": "2026-08-31",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "TRANSITION",
        }],
        trading_dates=calendar,
        exact_opens={"2026-09-01": 100.0},
        reference_market_date="2026-09-30",
    )

    assert result["position"]["entry_execution_date"] == "2026-09-01"
    assert result["position"]["entry_open"] == 100.0
    assert result["pending"] == {
        "kind": "EXIT",
        "signal_date": "2026-09-30",
        "execution_date": "2026-10-01",
    }
    assert result["position"]["exit_signal_date"] == "2026-09-30"


def test_completed_trade_is_recorded_at_exact_next_open_without_changing_lifecycle():
    result = replay_lifecycle(
        [
            {"date": "2026-08-31", "state": "DEPRESSED"},
            {"date": "2026-09-30", "state": "NORMAL"},
        ],
        [{
            "date": "2026-08-31",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "TRANSITION",
        }],
        trading_dates=["2026-08-31", "2026-09-01", "2026-09-30", "2026-10-01"],
        exact_opens={"2026-09-01": 100.0, "2026-10-01": 125.0},
        reference_market_date="2026-10-01",
    )

    assert result["position"] is None
    assert result["pending"] is None
    assert result["completed_trades"] == [{
        "trade_sequence": 1,
        "entry_signal_date": "2026-08-31",
        "entry_execution_date": "2026-09-01",
        "entry_open": 100.0,
        "exit_signal_date": "2026-09-30",
        "exit_execution_date": "2026-10-01",
        "exit_price": 125.0,
        "exit_reason": "PATTERN_B_NORMAL_NEXT_OPEN",
        "trade_status": "REALIZED",
        "return_pct": 25.0,
    }]


def test_replay_continues_trade_sequence_after_completed_history():
    result = replay_lifecycle(
        [{"date": "2026-08-31", "state": "DEPRESSED"}],
        [{
            "date": "2026-08-31",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "TRANSITION",
        }],
        trading_dates=["2026-08-31", "2026-09-01"],
        exact_opens={},
        reference_market_date="2026-08-31",
        initial_trade_sequence=4,
    )

    assert result["pending"]["sequence"] == 5


def test_future_next_open_is_not_read_or_filled():
    calendar = ["2026-09-30", "2026-10-01"]
    result = replay_lifecycle(
        [{"date": "2026-09-30", "state": "DEPRESSED"}],
        [{
            "date": "2026-09-30",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "EARLY_TREND",
        }],
        trading_dates=calendar,
        exact_opens={},
        reference_market_date="2026-09-30",
    )

    assert result["position"] is None
    assert result["pending"] == {
        "kind": "ENTRY",
        "signal_date": "2026-09-30",
        "execution_date": "2026-10-01",
        "sequence": 1,
    }


def test_missing_past_exact_open_fails_closed():
    with pytest.raises(BSelectLifecycleError, match="MISSING_EXACT_NEXT_OPEN:2026-09-01"):
        replay_lifecycle(
            [{"date": "2026-08-31", "state": "DEPRESSED"}],
            [{
                "date": "2026-08-31",
                "pattern_a_stage": "PROGRESSED",
                "previous_pattern_a_stage": "TRANSITION",
            }],
            trading_dates=["2026-08-31", "2026-09-01"],
            exact_opens={},
            reference_market_date="2026-09-01",
        )


def test_overlapping_entry_is_suppressed_while_position_is_open():
    result = replay_lifecycle(
        [
            {"date": "2026-08-31", "state": "DEPRESSED"},
            {"date": "2026-09-30", "state": "DEPRESSED"},
        ],
        [
            {"date": "2026-08-31", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "TRANSITION"},
            {"date": "2026-09-30", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "EARLY_TREND"},
        ],
        trading_dates=["2026-08-31", "2026-09-01", "2026-09-30", "2026-10-01"],
        exact_opens={"2026-09-01": 100.0},
        reference_market_date="2026-09-30",
    )

    assert result["position"]["entry_signal_date"] == "2026-08-31"
    assert result["suppressed_entry_count"] == 1
    assert result["pending"] is None


def test_replay_rejects_future_observation_and_unbacked_entry():
    with pytest.raises(BSelectLifecycleError, match="FUTURE_OBSERVATION"):
        replay_lifecycle(
            [{"date": "2026-09-03", "state": "DEPRESSED"}],
            [],
            trading_dates=["2026-09-01", "2026-09-02", "2026-09-03"],
            exact_opens={},
            reference_market_date="2026-09-02",
        )
    with pytest.raises(BSelectLifecycleError, match="ENTRY_SIGNAL_NOT_BACKED"):
        replay_lifecycle(
            [{"date": "2026-08-31", "state": "NORMAL"}],
            [{
                "date": "2026-08-31",
                "pattern_a_stage": "PROGRESSED",
                "previous_pattern_a_stage": "TRANSITION",
            }],
            trading_dates=["2026-08-31", "2026-09-01"],
            exact_opens={},
            reference_market_date="2026-08-31",
        )


def test_gap_replay_fills_entry_from_exact_next_session_open():
    calendar = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]
    result = replay_lifecycle(
        [
            {"date": "2026-09-28", "state": "DEPRESSED"},
            {"date": "2026-09-29", "state": "DEPRESSED"},
            {"date": "2026-09-30", "state": "DEPRESSED"},
        ],
        [{
            "date": "2026-09-30",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "TRANSITION",
        }],
        trading_dates=calendar,
        exact_opens={"2026-10-01": 101.5},
        reference_market_date="2026-10-01",
    )

    assert result["position"]["entry_signal_date"] == "2026-09-30"
    assert result["position"]["entry_execution_date"] == "2026-10-01"
    assert result["position"]["entry_open"] == 101.5
    assert result["pending"] is None
    assert result["completed_trades"] == []


def test_gap_replay_realizes_normal_exit_and_preserves_completed_trade():
    calendar = ["2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"]
    result = replay_lifecycle(
        [
            {"date": "2026-09-28", "state": "DEPRESSED"},
            {"date": "2026-09-29", "state": "NORMAL"},
            {"date": "2026-09-30", "state": "NORMAL"},
        ],
        [],
        trading_dates=calendar,
        exact_opens={"2026-10-01": 120.0},
        reference_market_date="2026-10-01",
        initial_position={
            "trade_sequence": 4,
            "entry_signal_date": "2026-08-31",
            "entry_execution_date": "2026-09-01",
            "entry_open": 100.0,
            "exit_signal_date": None,
            "exit_execution_date": None,
        },
        initial_trade_sequence=4,
    )

    assert result["position"] is None
    assert result["pending"] is None
    trade = result["completed_trades"][0]
    assert {key: value for key, value in trade.items() if key != "return_pct"} == {
        "trade_sequence": 4,
        "entry_signal_date": "2026-08-31",
        "entry_execution_date": "2026-09-01",
        "entry_open": 100.0,
        "exit_signal_date": "2026-09-30",
        "exit_execution_date": "2026-10-01",
        "exit_price": 120.0,
        "exit_reason": "PATTERN_B_NORMAL_NEXT_OPEN",
        "trade_status": "REALIZED",
    }
    assert trade["return_pct"] == pytest.approx(20.0)


def test_gap_replay_executes_prior_pending_entry_once():
    calendar = ["2026-08-31", "2026-09-01", "2026-09-30", "2026-10-01"]
    result = replay_lifecycle(
        [
            {"date": "2026-08-31", "state": "DEPRESSED"},
            {"date": "2026-09-01", "state": "DEPRESSED"},
            {"date": "2026-09-30", "state": "DEPRESSED"},
        ],
        [{
            "date": "2026-09-30",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "EARLY_TREND",
        }],
        trading_dates=calendar,
        exact_opens={"2026-09-01": 55.0},
        reference_market_date="2026-09-30",
        initial_pending={
            "kind": "ENTRY",
            "signal_date": "2026-08-31",
            "execution_date": "2026-09-01",
            "sequence": 1,
        },
        initial_trade_sequence=1,
    )

    assert result["position"]["entry_signal_date"] == "2026-08-31"
    assert result["position"]["entry_execution_date"] == "2026-09-01"
    assert result["position"]["entry_open"] == 55.0
    assert result["pending"] is None
    assert result["suppressed_entry_count"] == 1


def test_gap_catchup_matches_session_by_session_reference_replay():
    calendar = ["2026-08-31", "2026-09-01", "2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]
    observations = [
        {"date": "2026-08-31", "state": "DEPRESSED"},
        {"date": "2026-09-01", "state": "DEPRESSED"},
        {"date": "2026-09-25", "state": "NORMAL"},
        {"date": "2026-09-28", "state": "DEPRESSED"},
        {"date": "2026-09-29", "state": "DEPRESSED"},
        {"date": "2026-09-30", "state": "NORMAL"},
        {"date": "2026-10-01", "state": "NORMAL"},
        {"date": "2026-10-02", "state": "DEPRESSED"},
    ]
    signals = [
        {"date": "2026-08-31", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "TRANSITION"},
    ]
    exact_opens = {"2026-09-01": 100.0, "2026-10-01": 115.0}
    batch = replay_lifecycle(
        observations,
        signals,
        trading_dates=calendar + ["2026-10-05"],
        exact_opens=exact_opens,
        reference_market_date="2026-10-02",
    )

    position = None
    pending = None
    completed = []
    suppressed = 0
    sequence = 0
    signal_by_date = {row["date"]: row for row in signals}
    for observation in observations:
        day = observation["date"]
        current = replay_lifecycle(
            [observation],
            [signal_by_date[day]] if day in signal_by_date else [],
            trading_dates=calendar + ["2026-10-05"],
            exact_opens={key: value for key, value in exact_opens.items() if key <= day},
            reference_market_date=day,
            initial_position=position,
            initial_pending=pending,
            initial_trade_sequence=sequence,
        )
        position = current["position"]
        pending = current["pending"]
        completed.extend(current["completed_trades"])
        suppressed += current["suppressed_entry_count"]
        sequence = max(
            sequence,
            int(position.get("trade_sequence") or 0) if position else 0,
            int(pending.get("sequence") or 0) if pending else 0,
        )

    sequential = {
        "position": position,
        "pending": pending,
        "completed_trades": completed,
        "suppressed_entry_count": suppressed,
        "last_observation_date": observations[-1]["date"],
        "last_pattern_b_state": observations[-1]["state"],
    }
    assert batch == sequential
    assert batch["position"] is None
    assert batch["completed_trades"][0]["exit_signal_date"] == "2026-09-30"
    assert batch["completed_trades"][0]["exit_execution_date"] == "2026-10-01"
    assert batch["pending"] is None
