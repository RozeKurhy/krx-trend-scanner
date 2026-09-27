from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_deep_exit_simple_v01 as runner
from scripts import run_pattern_b_pure_simple_backtest_v01 as base


IDENTITY = ("000001", "KR7000000001")
COMPONENT = "000001:KR7000000001:000"


def _observation(date: str, state: str) -> dict:
    return {
        "ticker": IDENTITY[0],
        "isu_cd": IDENTITY[1],
        "market": "KOSPI",
        "snapshot_date": date,
        "state": state,
        "component_id": COMPONENT,
    }


def _daily(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"open": open_, "high": high, "low": low, "close": close, "market": "KOSPI"}
            for _, open_, high, low, close in rows
        ],
        index=[date for date, *_ in rows],
    )


def _run(observations: list[dict], daily: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    signals, blocked = base._make_entry_signals(pd.DataFrame(observations))
    assert not blocked
    events = signals[IDENTITY]
    trades, _ = runner._simulate_identity_deep_exit(
        observations,
        events,
        {COMPONENT: daily},
        "2020-05-29",
    )
    return trades, events


def test_first_deep_exit_stays_pending_until_first_later_open() -> None:
    observations = [
        _observation("2019-12-30", "NORMAL"),
        _observation("2020-01-31", "DEPRESSED"),
        _observation("2020-02-28", "DEEP_DEPRESSED"),
        _observation("2020-03-31", "NORMAL"),
    ]
    daily = _daily([
        ("2020-02-03", 100.0, 106.0, 95.0, 102.0),
        ("2020-03-02", 96.0, 98.0, 40.0, 90.0),
        ("2020-04-01", 105.0, 110.0, 100.0, 108.0),
    ])

    trades, events = _run(observations, daily)

    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_signal_date"] == "2020-01-31"
    assert trade["entry_execution_date"] == "2020-02-03"
    assert trade["exit_signal_date"] == "2020-02-28"
    assert trade["exit_signal_state"] == "DEEP_DEPRESSED"
    assert trade["exit_reason"] == "DEEP_DEPRESSED_STOP"
    assert trade["exit_execution_date"] == "2020-03-02"
    assert trade["trade_status"] == "REALIZED"
    assert events[0]["entry_signal_status"] == "FILLED"
    assert abs(runner._pre_exit_mae_pct(trade, daily) + 5.0) < 1e-12


def test_normal_recovery_exit_remains_unchanged_when_no_deep_state_occurs() -> None:
    observations = [
        _observation("2019-12-30", "NORMAL"),
        _observation("2020-01-31", "DEPRESSED"),
        _observation("2020-02-28", "DEPRESSED"),
        _observation("2020-03-31", "NORMAL"),
    ]
    daily = _daily([
        ("2020-02-03", 100.0, 106.0, 95.0, 102.0),
        ("2020-04-01", 110.0, 115.0, 105.0, 112.0),
    ])

    trades, _ = _run(observations, daily)

    assert len(trades) == 1
    assert trades[0]["exit_signal_date"] == "2020-03-31"
    assert trades[0]["exit_signal_state"] == "NORMAL"
    assert trades[0]["exit_reason"] == "NORMAL_RECOVERY"
    assert trades[0]["exit_execution_date"] == "2020-04-01"


def test_deep_exit_without_later_open_remains_open_and_unfilled_by_cutoff() -> None:
    observations = [
        _observation("2019-12-30", "NORMAL"),
        _observation("2020-01-31", "DEPRESSED"),
        _observation("2020-02-28", "DEEP_DEPRESSED"),
    ]
    daily = _daily([("2020-02-03", 100.0, 106.0, 95.0, 102.0)])

    trades, _ = _run(observations, daily)

    assert len(trades) == 1
    assert trades[0]["exit_signal_state"] == "DEEP_DEPRESSED"
    assert trades[0]["exit_execution_date"] is None
    assert trades[0]["exit_fill_status"] == "UNFILLED_BY_CUTOFF"
    assert trades[0]["trade_status"] == "OPEN_AT_CUTOFF"


def test_open_mark_coverage_treats_csv_nan_as_unresolved() -> None:
    trades = [
        {"trade_status": "OPEN_AT_CUTOFF", "mark_to_cutoff_gross_return_pct": 5.0},
        {"trade_status": "OPEN_AT_CUTOFF", "mark_to_cutoff_gross_return_pct": float("nan")},
    ]

    summary = runner._trade_summary(trades)

    assert summary["open_positions"]["marked_count"] == 1
    assert summary["open_positions"]["unresolved_count"] == 1
    assert summary["open_positions"]["mean_pct"] == 5.0
