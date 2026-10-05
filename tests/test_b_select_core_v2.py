from __future__ import annotations

import pytest

from trend_scanner.strategies import b_select_core_v1, b_select_core_v2


CALENDAR = [
    "2026-01-29",
    "2026-01-30",
    "2026-02-02",
    "2026-02-03",
    "2026-02-04",
    "2026-02-05",
    "2026-02-26",
    "2026-02-27",
    "2026-03-02",
]


def test_v2_entry_qualification_is_exactly_v1_parity():
    states = [None, "DEPRESSED", "NORMAL"]
    stages = [None, "PROGRESSED", "EARLY_TREND", "TRANSITION", "BASE"]
    for state in states:
        for current in stages:
            for previous in stages:
                assert b_select_core_v2.is_entry_signal(state, current, previous) == (
                    b_select_core_v1.is_entry_signal(state, current, previous)
                )


def test_v1_keeps_month_end_exit_cadence_while_v2_exits_on_daily_normal():
    observations = [
        {"date": "2026-01-30", "state": "DEPRESSED"},
        {"date": "2026-02-02", "state": "OVERHEATED"},
        {"date": "2026-02-03", "state": "NORMAL"},
        {"date": "2026-02-04", "state": "OVERHEATED"},
    ]
    entry_signals = [{
        "date": "2026-01-30",
        "pattern_a_stage": "PROGRESSED",
        "previous_pattern_a_stage": "EARLY_TREND",
    }]
    v1 = b_select_core_v1.replay_lifecycle(
        observations,
        entry_signals,
        trading_dates=CALENDAR,
        exact_opens={"2026-02-02": 100.0},
        reference_market_date="2026-02-04",
    )
    assert v1["position"] is not None
    assert v1["pending"] is None

    v2 = b_select_core_v2.replay_lifecycle(
        observations,
        entry_signals,
        trading_dates=CALENDAR,
        exact_opens={"2026-02-02": 100.0, "2026-02-04": 110.0},
        reference_market_date="2026-02-04",
    )
    assert v2["position"] is None
    assert len(v2["completed_trades"]) == 1
    trade = v2["completed_trades"][0]
    assert trade["exit_signal_date"] == "2026-02-03"
    assert trade["exit_execution_date"] == "2026-02-04"
    assert trade["exit_price"] == 110.0
    assert trade["strategy_id"] == b_select_core_v2.STRATEGY_ID
    assert trade["exit_strategy_id"] == b_select_core_v2.STRATEGY_ID


def test_v2_migration_baseline_does_not_create_retroactive_exit():
    result = b_select_core_v2.replay_lifecycle(
        [
            {"date": "2026-01-30", "state": "NORMAL", "exit_signal_eligible": False},
            {"date": "2026-02-02", "state": "NORMAL"},
        ],
        [],
        trading_dates=CALENDAR,
        exact_opens={},
        reference_market_date="2026-02-02",
        initial_position={
            "trade_sequence": 7,
            "entry_signal_date": "2025-12-31",
            "entry_execution_date": "2026-01-02",
            "entry_open": 50.0,
            "strategy_id": b_select_core_v2.V1_STRATEGY_ID,
        },
    )

    assert result["position"]["entry_execution_date"] == "2026-01-02"
    assert result["pending"] == {
        "kind": "EXIT",
        "signal_date": "2026-02-02",
        "execution_date": "2026-02-03",
        "strategy_id": b_select_core_v2.STRATEGY_ID,
    }


def test_v2_never_exits_on_a_non_normal_state():
    result = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-02-02", "state": "OVERHEATED"}],
        [],
        trading_dates=CALENDAR,
        exact_opens={},
        reference_market_date="2026-02-02",
        initial_position={
            "trade_sequence": 1,
            "entry_signal_date": "2026-01-30",
            "entry_execution_date": "2026-02-02",
            "entry_open": 100.0,
            "strategy_id": b_select_core_v2.V1_STRATEGY_ID,
        },
    )
    assert result["position"] is not None
    assert result["pending"] is None


def test_v2_rejects_midmonth_entry_and_requires_exact_valid_open():
    with pytest.raises(b_select_core_v2.BSelectLifecycleError, match="ENTRY_SIGNAL_NOT_MONTH_END"):
        b_select_core_v2.replay_lifecycle(
            [{"date": "2026-02-03", "state": "DEPRESSED"}],
            [{
                "date": "2026-02-03",
                "pattern_a_stage": "PROGRESSED",
                "previous_pattern_a_stage": "TRANSITION",
            }],
            trading_dates=CALENDAR,
            exact_opens={},
            reference_market_date="2026-02-03",
        )

    with pytest.raises(b_select_core_v2.BSelectLifecycleError, match="MISSING_EXACT_NEXT_OPEN"):
        b_select_core_v2.replay_lifecycle(
            [
                {"date": "2026-02-02", "state": "OVERHEATED"},
                {"date": "2026-02-03", "state": "NORMAL"},
            ],
            [],
            trading_dates=CALENDAR,
            exact_opens={},
            reference_market_date="2026-02-04",
            initial_position={
                "trade_sequence": 1,
                "entry_signal_date": "2026-01-30",
                "entry_execution_date": "2026-02-02",
                "entry_open": 100.0,
                "strategy_id": b_select_core_v2.V1_STRATEGY_ID,
            },
        )


def test_v2_carries_v1_entry_identity_when_v2_daily_exit_closes_open_trade():
    result = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-02-03", "state": "NORMAL"}],
        [],
        trading_dates=CALENDAR,
        exact_opens={"2026-02-04": 120.0},
        reference_market_date="2026-02-04",
        initial_position={
            "trade_sequence": 5,
            "entry_signal_date": "2025-10-31",
            "entry_execution_date": "2025-11-03",
            "entry_open": 80.0,
            "strategy_id": b_select_core_v2.V1_STRATEGY_ID,
        },
    )
    assert result["completed_trades"][0]["strategy_id"] == b_select_core_v2.V1_STRATEGY_ID
    assert result["completed_trades"][0]["exit_strategy_id"] == b_select_core_v2.STRATEGY_ID
