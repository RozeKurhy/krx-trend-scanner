from __future__ import annotations

import pytest

from trend_scanner.strategies.b_select_core_v1 import (
    BSelectLifecycleError,
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


def test_next_open_fill_uses_immediate_exact_session_and_normal_exit_stays_pending():
    calendar = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-07"]
    result = replay_lifecycle(
        [
            {"date": "2026-09-01", "state": "DEPRESSED"},
            {"date": "2026-09-03", "state": "NORMAL"},
        ],
        [{
            "date": "2026-09-01",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "TRANSITION",
        }],
        trading_dates=calendar,
        exact_opens={"2026-09-02": 100.0},
        reference_market_date="2026-09-03",
    )

    assert result["position"]["entry_execution_date"] == "2026-09-02"
    assert result["position"]["entry_open"] == 100.0
    assert result["pending"] == {
        "kind": "EXIT",
        "signal_date": "2026-09-03",
        "execution_date": "2026-09-04",
    }
    assert result["position"]["exit_signal_date"] == "2026-09-03"


def test_future_next_open_is_not_read_or_filled():
    calendar = ["2026-09-01", "2026-09-02", "2026-09-03"]
    result = replay_lifecycle(
        [{"date": "2026-09-02", "state": "DEPRESSED"}],
        [{
            "date": "2026-09-02",
            "pattern_a_stage": "PROGRESSED",
            "previous_pattern_a_stage": "EARLY_TREND",
        }],
        trading_dates=calendar,
        exact_opens={},
        reference_market_date="2026-09-02",
    )

    assert result["position"] is None
    assert result["pending"] == {
        "kind": "ENTRY",
        "signal_date": "2026-09-02",
        "execution_date": "2026-09-03",
        "sequence": 1,
    }


def test_missing_past_exact_open_fails_closed():
    with pytest.raises(BSelectLifecycleError, match="MISSING_EXACT_NEXT_OPEN:2026-09-02"):
        replay_lifecycle(
            [{"date": "2026-09-01", "state": "DEPRESSED"}],
            [{
                "date": "2026-09-01",
                "pattern_a_stage": "PROGRESSED",
                "previous_pattern_a_stage": "TRANSITION",
            }],
            trading_dates=["2026-09-01", "2026-09-02"],
            exact_opens={},
            reference_market_date="2026-09-02",
        )


def test_overlapping_entry_is_suppressed_while_position_is_open():
    result = replay_lifecycle(
        [
            {"date": "2026-09-01", "state": "DEPRESSED"},
            {"date": "2026-09-03", "state": "DEPRESSED"},
        ],
        [
            {"date": "2026-09-01", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "TRANSITION"},
            {"date": "2026-09-03", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "EARLY_TREND"},
        ],
        trading_dates=["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"],
        exact_opens={"2026-09-02": 100.0},
        reference_market_date="2026-09-03",
    )

    assert result["position"]["entry_signal_date"] == "2026-09-01"
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
            [{"date": "2026-09-01", "state": "NORMAL"}],
            [{
                "date": "2026-09-01",
                "pattern_a_stage": "PROGRESSED",
                "previous_pattern_a_stage": "TRANSITION",
            }],
            trading_dates=["2026-09-01", "2026-09-02"],
            exact_opens={},
            reference_market_date="2026-09-01",
        )
