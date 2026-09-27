from __future__ import annotations

import pandas as pd

from scripts import run_pattern_b_pure_simple_backtest_v01 as runner


def _observation(date: str, state: str, component: str = "000001:KR7000000001:000") -> dict:
    return {
        "ticker": "000001",
        "isu_cd": "KR7000000001",
        "market": "KOSPI",
        "snapshot_date": date,
        "state": state,
        "component_id": component,
    }


def _daily(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"open": open_, "high": high, "low": low, "close": close, "market": "KOSPI"}
            for _, open_, high, low, close in rows
        ],
        index=[date for date, *_ in rows],
    )


def test_deep_depressed_to_depressed_is_an_entry_transition() -> None:
    assert runner.is_entry_transition("DEEP_DEPRESSED", "DEPRESSED")
    assert runner.is_entry_transition("NORMAL", "DEPRESSED")
    assert not runner.is_entry_transition("DEPRESSED", "DEPRESSED")
    assert not runner.is_entry_transition("DEPRESSED", "DEEP_DEPRESSED")


def test_entry_requires_adjacent_month_and_connected_authority() -> None:
    frame = pd.DataFrame(
        [
            _observation("2019-12-30", "NORMAL"),
            _observation("2020-01-31", "DEPRESSED"),
            _observation("2020-03-31", "DEPRESSED"),
        ]
    )
    signals, _ = runner._make_entry_signals(frame)
    assert [event["entry_signal_date"] for event in signals[("000001", "KR7000000001")]] == [
        "2020-01-31"
    ]

    discontinuous = frame.iloc[:2].copy()
    discontinuous.loc[1, "component_id"] = "000001:KR7000000001:001"
    signals, blocked = runner._make_entry_signals(discontinuous)
    assert signals == {}
    assert len(blocked) == 1
    assert blocked[0]["entry_signal_status"] == "BLOCKED_AUTHORITY_DISCONTINUITY"


def test_next_open_is_strictly_after_signal() -> None:
    dates = pd.to_datetime(["2020-01-31", "2020-02-03", "2020-02-04"])
    assert runner.next_observed_open_date(dates, "2020-01-31") == "2020-02-03"
    assert runner.next_observed_open_date(dates, "2020-02-04") is None


def test_closed_statistics_use_realized_returns_and_pf_needs_wins_and_losses() -> None:
    summary = runner._metric_summary([10.0, 0.0, -20.0, 30.0])
    assert summary["n"] == 4
    assert summary["win_rate_pct"] == 50.0
    assert summary["mean_pct"] == 5.0
    assert summary["profit_factor"] == 2.0
    assert summary["expectancy_pct"] == 5.0
    assert runner._metric_summary([10.0, 20.0])["profit_factor"] is None
    assert runner._metric_summary([-10.0, -20.0])["profit_factor"] is None
    assert runner._metric_summary([])["n"] == 0


def test_state_machine_holds_deep_and_suppresses_entry_while_open() -> None:
    observations = [
        _observation("2019-12-30", "NORMAL"),
        _observation("2020-01-31", "DEPRESSED"),
        _observation("2020-02-28", "DEEP_DEPRESSED"),
        _observation("2020-03-31", "DEPRESSED"),
        _observation("2020-04-30", "NORMAL"),
    ]
    frame = pd.DataFrame(observations)
    signals, blocked = runner._make_entry_signals(frame)
    assert not blocked
    identity = ("000001", "KR7000000001")
    daily = _daily(
        [
            ("2020-02-03", 100.0, 112.0, 95.0, 108.0),
            ("2020-03-02", 105.0, 110.0, 100.0, 103.0),
            ("2020-04-01", 108.0, 115.0, 105.0, 111.0),
            ("2020-05-04", 120.0, 121.0, 116.0, 119.0),
        ]
    )
    trades, _ = runner._simulate_identity(
        observations,
        signals[identity],
        {"000001:KR7000000001:000": daily},
        "2020-06-01",
    )
    assert len(trades) == 1
    trade = trades[0]
    assert trade["entry_execution_date"] == "2020-02-03"
    assert trade["exit_signal_date"] == "2020-04-30"
    assert trade["exit_execution_date"] == "2020-05-04"
    assert trade["trade_status"] == "REALIZED"
    assert [event["entry_signal_status"] for event in signals[identity]] == [
        "FILLED",
        "SUPPRESSED_ALREADY_HOLDING",
    ]


def test_open_trade_remains_open_and_uses_exact_cutoff_close() -> None:
    observations = [
        _observation("2019-12-30", "NORMAL"),
        _observation("2020-01-31", "DEPRESSED"),
        _observation("2020-02-28", "DEEP_DEPRESSED"),
    ]
    signals, _ = runner._make_entry_signals(pd.DataFrame(observations))
    identity = ("000001", "KR7000000001")
    daily = _daily(
        [
            ("2020-02-03", 100.0, 105.0, 90.0, 98.0),
            ("2020-06-01", 110.0, 118.0, 108.0, 115.0),
        ]
    )
    trades, _ = runner._simulate_identity(
        observations,
        signals[identity],
        {"000001:KR7000000001:000": daily},
        "2020-06-01",
    )
    assert len(trades) == 1
    assert trades[0]["trade_status"] == "OPEN_AT_CUTOFF"
    assert trades[0]["exit_execution_date"] is None
    assert trades[0]["cutoff_close"] == 115.0
    assert trades[0]["valuation_status"] == "MARKED_EXACT_CUTOFF_CLOSE"
