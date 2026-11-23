from copy import deepcopy
from dataclasses import asdict

import pandas as pd
import pytest

from scripts.export_strategy_monitor_web import _project_item
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.reporting.a_fast_core_report import (
    OPEN_EVALUATION_UNAVAILABLE,
    build_unavailable_open_section,
)
from trend_scanner.reporting.models import (
    AFastCoreCurrentTrade,
    AFastCoreProtectionState,
    AFastCoreReentryState,
    AFastCoreSection,
    AFastCoreTradeHistoryItem,
)
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import (
    HISTORICAL_ALIGNMENT_REPLAY_MODE,
    PROMOTED_STRATEGY_ID,
    AlignmentGateIntegrityError,
)


@pytest.fixture
def open_authority():
    dates = pd.to_datetime(["2025-01-03", "2025-01-06", "2025-01-31", "2025-02-03", "2025-02-04", "2025-02-05"])
    prior = AFastCoreSection(
        strategy_id=PROMOTED_STRATEGY_ID,
        strategy_replay_mode=HISTORICAL_ALIGNMENT_REPLAY_MODE,
        as_of="2025-02-03",
        canonical_position="OPEN",
        strategy_state="HOLD_PROGRESSED",
        action="HOLD",
        current_trade=AFastCoreCurrentTrade(
            trade_id="000001_01", trade_sequence=1, entry_signal_date="2025-01-03",
            entry_execution_date="2025-01-06", entry_open=100.0, entry_pattern_a_stage="TRANSITION",
            previous_exit_type=None, previous_exit_execution_date=None,
            first_progressed_date="2025-01-31", first_progressed_effective_trading_date="2025-01-31",
            lifecycle_class="PROGRESSED_WITHOUT_DIRECT_HANDOFF", current_close=95.0, current_return_pct=-5.0,
            trade_status="OPEN", strategy_id=PROMOTED_STRATEGY_ID,
        ),
        protection_state=AFastCoreProtectionState(
            phase="PROGRESSED", loss_guard_state="INACTIVE", loss_guard_threshold_pct=None,
            first_progressed_date="2025-01-31", first_progressed_effective_trading_date="2025-01-31",
            lifecycle_class="PROGRESSED_WITHOUT_DIRECT_HANDOFF", exit3_state="DISABLED_BY_COVERAGE_CONTRACT",
            exit4_state="ARMED", progressed_hwm_score=85.0, current_pattern_a_score=0.0,
            score_drawdown_from_hwm_pt=85.0,
        ),
        reentry_state=AFastCoreReentryState(current_trade_sequence=1, next_entry_sequence=2),
        trade_history=[AFastCoreTradeHistoryItem(
            trade_id="000001_01", trade_sequence=1, entry_signal_date="2025-01-03",
            entry_execution_date="2025-01-06", entry_open=100.0, entry_pattern_a_stage="TRANSITION",
            exit_type="NO_EXIT_BEFORE_CUTOFF", exit_signal_date=None, exit_execution_date=None, exit_price=None,
            trade_status="OPEN_AT_CUTOFF", return_pct=-5.0, strategy_id=PROMOTED_STRATEGY_ID,
        )],
    )
    report = {"ticker": "000001", "market": "KOSPI", "asset_type": "COMMON", "reference_market_date": "2025-02-03",
              "a_fast_core": asdict(prior)}
    return report, pd.DataFrame({"close": [96.0, 97.0]}, index=dates[-2:]), dates


def carry(report, daily, dates, *, extra_month_end=False):
    month_ends = [dates[2], dates[-1]] if extra_month_end else [dates[2]]
    calendar = MarketCalendarAuthority(dates, month_ends)
    return build_unavailable_open_section(
        report, daily, ticker="000001", market="KOSPI", requested_as_of=pd.Timestamp("2025-02-05"),
        reference_market_date="2025-02-05", market_calendar=calendar,
    )


def test_carry_open_preserves_trade_and_historical_protection(open_authority):
    report, daily, dates = open_authority
    original = deepcopy(report)
    result = carry(report, daily, dates)
    assert report == original
    assert (result.canonical_position, result.strategy_state, result.action) == ("OPEN", "DATA_UNAVAILABLE", "NONE")
    assert result.action_reason == OPEN_EVALUATION_UNAVAILABLE
    assert result.current_trade.trade_id == "000001_01"
    assert result.current_trade.entry_open == 100.0 and result.current_trade.current_close == 97.0
    assert [asdict(row) for row in result.trade_history] == original["a_fast_core"]["trade_history"]
    protection = asdict(result.protection_state)
    expected = original["a_fast_core"]["protection_state"]
    assert protection == {**expected, "current_pattern_a_score": None, "score_drawdown_from_hwm_pt": None}
    assert "2025-02-03" in result.interpretation and "Exit 4 ARMED" in result.interpretation


@pytest.mark.parametrize(
    "problem,message",
    [("pending", "EXIT_REQUIRES_PROCESSING"), ("month-end", "MONTH_END_REQUIRES"), ("missing", "CLOSE_MISSING"),
     ("loss-guard", "NEW_LOSS_GUARD_SIGNAL")],
)
def test_carry_never_skips_an_exit_authority(open_authority, problem, message):
    report, daily, dates = open_authority
    core = report["a_fast_core"]
    if problem == "pending":
        core["current_trade"]["pending_exit_signal_date"] = "2025-02-03"
    elif problem == "missing":
        daily = daily.iloc[-1:]
    elif problem == "loss-guard":
        core["protection_state"].update(phase="PRE_PROGRESSED", loss_guard_state="ACTIVE", loss_guard_threshold_pct=-15.0)
        daily.loc[dates[-2], "close"] = 84.0
    with pytest.raises(AlignmentGateIntegrityError, match=message):
        carry(report, daily, dates, extra_month_end=problem == "month-end")


def test_strategy_monitor_keeps_unavailable_open_and_ready_zero_separate(open_authority):
    report, daily, dates = open_authority
    result = carry(report, daily, dates)
    identity = {"ticker": "000001", "name": "Fixture", "market": "KOSPI", "asset_type": "COMMON"}
    payload = {
        "identity": identity,
        "decision": {"canonical_position": "OPEN", "strategy_state": result.strategy_state,
                     "action": result.action, "action_reason": result.action_reason},
        "strategy": {"position": "OPEN", "state": result.strategy_state, "action": result.action,
                     "history": [asdict(trade) for trade in result.trade_history]},
        "pattern": {"official_stage": "UNAVAILABLE", "score": None},
    }
    item = _project_item(identity, payload)
    assert (item["data_status"], item["bucket"], item["canonical_position"]) == ("UNAVAILABLE", "unavailable", "OPEN")
    assert item["current_trade"]["entry_execution_date"] == "2025-01-06"
    assert item["current_trade"]["entry_open"] == 100.0

    payload["pattern"] = {"official_stage": "WEAK", "score": 0.0}
    with pytest.raises(ValueError, match="invalid carried OPEN evaluation"):
        _project_item(identity, payload)
    payload["decision"].update(strategy_state="HOLD_PROGRESSED", action="HOLD", action_reason="POSITION_OPEN")
    payload["strategy"].update(state="HOLD_PROGRESSED", action="HOLD")
    item = _project_item(identity, payload)
    assert (item["data_status"], item["bucket"], item["pattern_score"]) == ("READY", "hold", 0.0)
