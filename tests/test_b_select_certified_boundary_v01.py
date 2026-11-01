from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from trend_scanner.data import rolling_market_data_refresh as rolling
from trend_scanner.data.market_calendar import (
    MarketCalendarAuthority,
    load_rolling_production_market_calendar,
)
from trend_scanner.data.period_derivation import COMPLETE, PROVISIONAL, derive_periods
from trend_scanner.strategies import b_select_core_v1, b_select_core_v2


OCTOBER_SESSIONS = [
    "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-29", "2026-10-30",
]


def test_terminal_month_end_requires_explicit_certification():
    dates = OCTOBER_SESSIONS
    assert "2026-10-30" not in b_select_core_v1.exact_month_end_sessions(dates)
    assert "2026-10-30" not in b_select_core_v1.exact_month_end_sessions(
        dates, certified_through="2026-10-30"
    )
    completed = b_select_core_v1.exact_month_end_sessions(
        dates, certified_through="2026-11-01"
    )
    assert "2026-10-30" in completed
    assert "2026-10-29" not in completed
    assert completed == b_select_core_v1.exact_month_end_sessions(dates + ["2026-11-02"])


@pytest.mark.parametrize(
    ("dates", "certified_through", "expected"),
    [
        (["2026-02-26", "2026-02-27"], "2026-02-28", "2026-02-27"),
        (["2026-12-29", "2026-12-30"], "2026-12-31", "2026-12-30"),
        (["2024-02-28", "2024-02-29"], "2024-02-29", "2024-02-29"),
    ],
)
def test_certified_terminal_month_end_handles_calendar_boundaries(dates, certified_through, expected):
    assert expected in b_select_core_v1.exact_month_end_sessions(
        dates, certified_through=certified_through
    )


def _rolling_calendar(tmp_path, monkeypatch, certified_through):
    root = tmp_path / certified_through
    path = root / "data/market/rolling_authority/merged_trading_calendar.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    manifest = SimpleNamespace(
        manifest_sha256=certified_through,
        certified_through=certified_through,
        merged_calendar_frontier="2026-10-30",
        merged_calendar_digest="fixture-digest",
        authority_version="fixture-authority",
    )
    payload = {"trading_dates": OCTOBER_SESSIONS, "built_against_certified_through": certified_through}
    monkeypatch.setattr(rolling, "load_rolling_authority", lambda _: manifest)
    monkeypatch.setattr(rolling, "validate_merged_authority_coherence", lambda *_: ({}, payload))
    return load_rolling_production_market_calendar(root)


def _daily_frame():
    dates = pd.to_datetime(OCTOBER_SESSIONS + ["2026-11-02"])
    close = [100.0, 101.0, 102.0, 103.0, 104.0, 9999.0]
    return pd.DataFrame(
        {"open": close, "high": close, "low": close, "close": close,
         "volume": [1000.0] * len(dates), "trading_value": [100000.0] * len(dates)},
        index=dates,
    )


def test_certified_rolling_calendar_completes_october_without_future_price(tmp_path, monkeypatch):
    calendar = _rolling_calendar(tmp_path, monkeypatch, "2026-11-01")
    assert calendar.get_actual_month_end(2026, 10) == pd.Timestamp("2026-10-30")
    assert derive_periods(_daily_frame(), "2026-10-29", calendar).monthly_status == PROVISIONAL
    result = derive_periods(_daily_frame(), "2026-10-30", calendar)
    assert result.monthly_status == COMPLETE
    assert result.monthly.iloc[-1]["close"] == 104.0
    assert result.effective_daily_boundary == "2026-10-30"

    old = MarketCalendarAuthority.from_dates(
        OCTOBER_SESSIONS[:2], completed_month_ends=["2026-09-30"]
    )
    before = derive_periods(_daily_frame(), "2026-09-30", old)
    after = derive_periods(_daily_frame(), "2026-09-30", calendar)
    assert before.monthly_status == after.monthly_status == COMPLETE
    pd.testing.assert_frame_equal(before.monthly, after.monthly)


def test_uncertified_terminal_month_stays_incomplete(tmp_path, monkeypatch):
    calendar = _rolling_calendar(tmp_path, monkeypatch, "2026-10-30")
    assert calendar.get_actual_month_end(2026, 10) is None
    assert derive_periods(_daily_frame(), "2026-10-30", calendar).monthly_status == PROVISIONAL


def _entry_signal():
    return {
        "date": "2026-10-30",
        "pattern_a_stage": "PROGRESSED",
        "previous_pattern_a_stage": "TRANSITION",
    }


def test_certified_month_end_entry_stays_pending_then_fills_once_on_observed_open():
    first = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-10-30", "state": "DEPRESSED"}], [_entry_signal()],
        trading_dates=OCTOBER_SESSIONS, certified_through="2026-11-01",
        exact_opens={}, reference_market_date="2026-10-30",
    )
    assert first["position"] is None
    assert first["completed_trades"] == []
    assert first["pending"]["kind"] == "ENTRY"
    assert first["pending"]["execution_date"] is None
    assert first["pending"]["sequence"] == 1

    later = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-11-02", "state": "DEPRESSED"}], [],
        trading_dates=OCTOBER_SESSIONS + ["2026-11-02"],
        certified_through="2026-11-02", exact_opens={"2026-11-02": 100.0},
        execution_by_signal_date={"2026-10-30": "2026-11-02"},
        reference_market_date="2026-11-02", initial_pending=first["pending"],
    )
    assert later["pending"] is None
    assert later["position"]["trade_sequence"] == 1
    assert later["position"]["entry_execution_date"] == "2026-11-02"
    assert later["position"]["entry_open"] == 100.0
    assert later["completed_trades"] == []

    again = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-11-03", "state": "DEPRESSED"}], [],
        trading_dates=OCTOBER_SESSIONS + ["2026-11-02", "2026-11-03"],
        certified_through="2026-11-03", exact_opens={}, reference_market_date="2026-11-03",
        initial_position=later["position"],
    )
    assert again["position"]["trade_sequence"] == 1
    assert again["pending"] is None
    assert again["completed_trades"] == []


def test_daily_normal_exit_stays_pending_without_unobserved_open():
    position = {"trade_sequence": 4, "entry_signal_date": "2026-09-30",
                "entry_execution_date": "2026-10-01", "entry_open": 100.0,
                "strategy_id": b_select_core_v2.STRATEGY_ID}
    result = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-10-30", "state": "NORMAL"}], [],
        trading_dates=OCTOBER_SESSIONS, certified_through="2026-11-01",
        exact_opens={}, reference_market_date="2026-10-30", initial_position=position,
    )
    assert result["position"] is not None
    assert result["pending"]["kind"] == "EXIT"
    assert result["pending"]["execution_date"] is None
    assert result["completed_trades"] == []

    later = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-11-02", "state": "NORMAL"}], [],
        trading_dates=OCTOBER_SESSIONS + ["2026-11-02"], certified_through="2026-11-02",
        exact_opens={"2026-11-02": 110.0}, execution_by_signal_date={"2026-10-30": "2026-11-02"},
        reference_market_date="2026-11-02", initial_position=result["position"], initial_pending=result["pending"],
    )
    assert later["position"] is None and later["pending"] is None
    assert len(later["completed_trades"]) == 1
    assert later["completed_trades"][0]["exit_execution_date"] == "2026-11-02"
    assert later["completed_trades"][0]["exit_price"] == 110.0


def test_unresolved_pending_cannot_hide_observed_missing_open():
    pending = {"kind": "ENTRY", "signal_date": "2026-10-30", "execution_date": None,
               "sequence": 1, "strategy_id": b_select_core_v2.STRATEGY_ID}
    with pytest.raises(b_select_core_v2.BSelectLifecycleError, match="MISSING|UNRESOLVED"):
        b_select_core_v2.replay_lifecycle(
            [{"date": "2026-11-02", "state": "DEPRESSED"}], [],
            trading_dates=OCTOBER_SESSIONS + ["2026-11-02"], certified_through="2026-11-02",
            exact_opens={}, reference_market_date="2026-11-02", initial_pending=pending,
        )


@pytest.mark.parametrize("open_price", [0.0, -1.0, float("nan")])
def test_pending_rejects_invalid_observed_open(open_price):
    pending = {"kind": "ENTRY", "signal_date": "2026-10-30", "execution_date": None,
               "sequence": 2, "strategy_id": b_select_core_v2.STRATEGY_ID}
    with pytest.raises(b_select_core_v2.BSelectLifecycleError, match="MISSING"):
        b_select_core_v2.replay_lifecycle(
            [{"date": "2026-11-02", "state": "DEPRESSED"}], [],
            trading_dates=OCTOBER_SESSIONS + ["2026-11-02"], certified_through="2026-11-02",
            exact_opens={"2026-11-02": open_price}, reference_market_date="2026-11-02", initial_pending=pending,
        )


def test_entry_requires_month_end_and_all_three_signal_criteria():
    for signal in [
        {"date": "2026-10-29", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "TRANSITION"},
        {"date": "2026-10-30", "pattern_a_stage": "TRANSITION", "previous_pattern_a_stage": "EARLY_TREND"},
        {"date": "2026-10-30", "pattern_a_stage": "PROGRESSED", "previous_pattern_a_stage": "UNAVAILABLE"},
    ]:
        with pytest.raises(b_select_core_v2.BSelectLifecycleError):
            b_select_core_v2.replay_lifecycle(
                [{"date": signal["date"], "state": "DEPRESSED"}], [signal],
                trading_dates=OCTOBER_SESSIONS, certified_through="2026-11-01",
                exact_opens={}, reference_market_date="2026-10-30",
            )


def test_unobserved_session_cannot_fill_even_when_price_is_supplied():
    pending = {"kind": "ENTRY", "signal_date": "2026-10-30", "execution_date": None,
               "sequence": 1, "strategy_id": b_select_core_v2.STRATEGY_ID}
    with pytest.raises(b_select_core_v2.BSelectLifecycleError, match="REFERENCE_NOT_EXACT"):
        b_select_core_v2.replay_lifecycle(
            [], [], trading_dates=OCTOBER_SESSIONS, certified_through="2026-11-01",
            exact_opens={"2026-11-02": 100.0}, reference_market_date="2026-11-02", initial_pending=pending,
        )


def test_non_normal_open_position_remains_held():
    position = {"trade_sequence": 1, "entry_signal_date": "2026-09-30",
                "entry_execution_date": "2026-10-01", "entry_open": 100.0,
                "strategy_id": b_select_core_v2.STRATEGY_ID}
    result = b_select_core_v2.replay_lifecycle(
        [{"date": "2026-10-30", "state": "DEPRESSED"}], [],
        trading_dates=OCTOBER_SESSIONS, certified_through="2026-11-01", exact_opens={},
        reference_market_date="2026-10-30", initial_position=position,
    )
    assert result["position"] == position
    assert result["pending"] is None and result["completed_trades"] == []


def test_prior_pending_cannot_skip_an_observed_first_open():
    pending = {"kind": "ENTRY", "signal_date": "2026-10-30", "execution_date": "2026-11-03",
               "sequence": 1, "strategy_id": b_select_core_v2.STRATEGY_ID}
    with pytest.raises(b_select_core_v2.BSelectLifecycleError, match="SCHEDULE_MISMATCH"):
        b_select_core_v2.replay_lifecycle(
            [{"date": "2026-11-02", "state": "DEPRESSED"}, {"date": "2026-11-03", "state": "DEPRESSED"}], [],
            trading_dates=OCTOBER_SESSIONS + ["2026-11-02", "2026-11-03"], certified_through="2026-11-03",
            exact_opens={"2026-11-02": 100.0, "2026-11-03": 110.0},
            reference_market_date="2026-11-03", initial_pending=pending,
        )
