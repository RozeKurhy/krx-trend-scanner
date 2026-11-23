"""Continue the published A FAST strategy from a certified ledger boundary."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import math
import re
from typing import Any, Callable

import pandas as pd

from trend_scanner.backtest.snapshot_context import build_historical_snapshot_from_context, build_precomputed_ticker_context
from trend_scanner.data.market_calendar import MarketCalendarAuthority
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.reporting.a_fast_core_report import OPEN_EVALUATION_UNAVAILABLE
from trend_scanner.reporting.models import (
    AFastCoreCurrentTrade,
    AFastCoreEntryConditions,
    AFastCoreProtectionState,
    AFastCoreProvenance,
    AFastCoreReentryState,
    AFastCoreSection,
    AFastCoreTradeHistoryItem,
)
from trend_scanner.validation.pattern_a_fast_alignment_mcap_500b import (
    AlignmentGateIntegrityError,
    AlignmentMcap500BGate,
    HISTORICAL_ALIGNMENT_REPLAY_MODE,
    PROMOTED_STRATEGY_ID,
    PROMOTED_STRATEGY_NAME,
)
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (
    _next_execution_open,
    _simulate_causal_lifecycle,
    is_v02_entry_signal,
)

CANONICAL_LEDGER_INCREMENTAL_V01 = "CANONICAL_LEDGER_INCREMENTAL_V01"
PUBLISHED_FAST_LEDGER_MODES = {HISTORICAL_ALIGNMENT_REPLAY_MODE, CANONICAL_LEDGER_INCREMENTAL_V01}
LOSS_GUARD_EXIT = "LOSS_GUARD_CLOSE_LE_NEG_15"


def valid_published_fast_scope(mode: str, scope: dict) -> bool:
    if mode == HISTORICAL_ALIGNMENT_REPLAY_MODE:
        return True
    if mode != CANONICAL_LEDGER_INCREMENTAL_V01:
        return False
    try:
        prior = scope["prior_canonical"]
        market, request = scope["reference_market_date"], scope["requested_as_of"]
        sessions = scope["new_sessions"]
        date_fields = (prior["reference_market_date"], prior["requested_as_of"], market, request, *sessions)
        return (
            all(date.fromisoformat(day).isoformat() == day for day in date_fields)
            and prior["reference_market_date"] <= prior["requested_as_of"] < request
            and prior["reference_market_date"] < sessions[0] <= sessions[-1] == market <= request
            and sessions == sorted(set(sessions))
            and prior["strategy_replay_mode"] in PUBLISHED_FAST_LEDGER_MODES
            and all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (
                prior["strategy_replay_digest"], prior["report_files_sha256"], scope["events_sha256"],
            ))
            and type(scope["event_count"]) is int and scope["event_count"] >= 0
        )
    except (KeyError, IndexError, TypeError, ValueError):
        return False


@dataclass(frozen=True)
class PendingSignal:
    actual_date: pd.Timestamp
    ledger_date: str
    reason: str
    entry: AFastCoreEntryConditions | None = None


def _day(value: pd.Timestamp) -> str:
    return value.date().isoformat()


def _actual_exit_session(signal: str, reason: str, calendar: MarketCalendarAuthority) -> pd.Timestamp:
    label = pd.Timestamp(signal)
    if reason.startswith(("EXIT3_", "EXIT4_")):
        day = calendar.get_actual_month_end(label.year, label.month)
        if day is not None and label == label + pd.offsets.MonthEnd(0):
            return day
    if not calendar.is_trading_day(label):
        raise AlignmentGateIntegrityError("INCREMENTAL_UNCERTIFIED_PENDING_SIGNAL")
    return label


def _pending_entry(core: dict[str, Any], reference: pd.Timestamp, ticker: str, identity: Any) -> PendingSignal | None:
    if core.get("action") != "ENTER_NEXT_OPEN":
        return None
    conditions = AFastCoreEntryConditions(**core["entry_conditions"])
    details = conditions.alignment_mcap_500b_details or {}
    audits = core.get("promotion_gate_audit") or []
    if (
        core["canonical_position"] != "FLAT"
        or not conditions.all_conditions_met
        or conditions.pattern_a_stage not in {"TRANSITION", "EARLY_TREND"}
        or conditions.alignment_mcap_500b_status != "PASS_ALIGNMENT_MCAP_500B"
        or details.get("ticker") != ticker
        or identity != (details.get("isu_cd"), details.get("market"))
        or details.get("signal_date") != _day(reference)
        or not any(a.get("allowed") is True and a.get("signal_date") == _day(reference)
                   and a.get("details") == details for a in audits)
    ):
        raise AlignmentGateIntegrityError("INCREMENTAL_PENDING_ENTRY_AUTHORITY_MISMATCH")
    return PendingSignal(reference, _day(reference), "ALL_ENTRY_CONDITIONS_MET", conditions)


def _entry_conditions(point: dict[str, Any], gate: Any) -> AFastCoreEntryConditions:
    return AFastCoreEntryConditions(
        instrument_eligible=True, investability_pass=None, pattern_a_stage_eligible=True,
        fast_trigger_ready=True, monthly_regime_permitted=True, daily_risk_allowed=True,
        fast_score_status_allowed=True, no_open_position=True, all_conditions_met=True,
        investability_required=False, pattern_a_stage=str(point["pattern_a_stage"]).upper(),
        fast_stage=point["fast_machine_stage"], fast_stage_status=point["fast_machine_stage_status"],
        monthly_regime=point["fast_monthly_permission_state"], daily_risk=point["fast_daily_risk_state"],
        fast_score_status=point["fast_score_status"], alignment_mcap_500b_pass=True,
        alignment_mcap_500b_status=gate.reason_code, alignment_mcap_500b_details=dict(gate.details),
    )


def _record_entry(
    ticker: str, history: list[AFastCoreTradeHistoryItem], signal: PendingSignal, session: str, price: float,
) -> tuple[AFastCoreCurrentTrade, AFastCoreProtectionState]:
    previous = history[-1] if history else None
    sequence = previous.trade_sequence + 1 if previous else 1
    common = dict(
        trade_id=f"{ticker}_{sequence:02d}", trade_sequence=sequence,
        entry_signal_date=signal.ledger_date, entry_execution_date=session, entry_open=round(price, 2),
        entry_pattern_a_stage=signal.entry.pattern_a_stage,
        previous_exit_type=previous.exit_type if previous else None,
        lifecycle_class="NEVER_PROGRESSED",
        strategy_id=PROMOTED_STRATEGY_ID, entry_strategy_id=PROMOTED_STRATEGY_ID, exit_strategy_id=PROMOTED_STRATEGY_ID,
    )
    history.append(AFastCoreTradeHistoryItem(
        **common, exit_type="NO_PROGRESSED_BEFORE_CUTOFF", exit_signal_date=None,
        exit_execution_date=None, exit_price=None, trade_status="OPEN_AT_CUTOFF", return_pct=0.0,
    ))
    current = AFastCoreCurrentTrade(
        **common, previous_exit_execution_date=previous.exit_execution_date if previous else None,
        first_progressed_date=None, first_progressed_effective_trading_date=None,
        current_close=price, current_return_pct=0.0, trade_status="OPEN",
    )
    protection = AFastCoreProtectionState(
        phase="PRE_PROGRESSED", loss_guard_state="ACTIVE", loss_guard_threshold_pct=-15.0,
        first_progressed_date=None, first_progressed_effective_trading_date=None,
        lifecycle_class="NEVER_PROGRESSED", exit3_state="INACTIVE", exit4_state="INACTIVE",
        progressed_hwm_score=None, current_pattern_a_score=None, score_drawdown_from_hwm_pt=None,
    )
    return current, protection


def _seed_monthly_observations(prior: dict[str, Any], current: AFastCoreCurrentTrade, calendar: MarketCalendarAuthority) -> list[dict]:
    """Decode the stored stage facts only when a new month needs a causal continuation."""
    observations = []
    for row in prior["monthly_history"]["full_monthly_history"]:
        day = pd.Timestamp(row["as_of"])
        if current.entry_signal_date <= row["as_of"] <= prior["reference_market_date"]:
            if calendar.get_actual_month_end(day.year, day.month) != day:
                raise AlignmentGateIntegrityError("INCREMENTAL_SEED_MONTH_END_NOT_CERTIFIED")
            observations.append({
                "date": day + pd.offsets.MonthEnd(0), "effective_trading_date": day,
                "stage": row["stage"], "score": row["score"],
            })
    seed = _simulate_causal_lifecycle(observations, current.entry_pattern_a_stage)
    progressed = seed["first_progressed_date"]
    if (
        seed["exit_signal_date"] is not None
        or seed["coverage_path"] != current.lifecycle_class
        or (_day(progressed) if progressed is not None else None) != current.first_progressed_date
    ):
        raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_MONTHLY_STATE_UNPROVEN")
    return observations


def advance_a_fast_ledger(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame,
    *,
    prior_report: dict[str, Any] | None,
    prior_reference: pd.Timestamp,
    reference: pd.Timestamp,
    requested: pd.Timestamp,
    calendar: MarketCalendarAuthority,
    score_contract: dict,
    stage_contract: dict,
    promotion_gate: AlignmentMcap500BGate,
    execution_open_resolver: Callable[[pd.Timestamp], float | None] | None,
    inactive_session: Callable[[pd.Timestamp], bool] | None = None,
) -> AFastCoreSection:
    """Apply only new certified events to the sealed book; price lookbacks remain PIT."""
    if (
        not prior_reference < reference <= requested
        or not calendar.is_trading_day(prior_reference) or not calendar.is_trading_day(reference)
        or daily.index.has_duplicates or not daily.index.is_monotonic_increasing
    ):
        raise AlignmentGateIntegrityError("INCREMENTAL_INVALID_CERTIFIED_WINDOW")
    prior = (prior_report or {}).get("a_fast_core") or {}
    if prior_report is not None and (
        prior_report["ticker"] != ticker or prior_report["asset_type"] != "COMMON"
        or prior_report["reference_market_date"] != _day(prior_reference)
        or prior["strategy_id"] != PROMOTED_STRATEGY_ID
        or prior["strategy_replay_mode"] not in PUBLISHED_FAST_LEDGER_MODES
    ):
        raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_REPORT_MISMATCH")
    history = [AFastCoreTradeHistoryItem(**row) for row in prior.get("trade_history", [])]
    current = AFastCoreCurrentTrade(**prior["current_trade"]) if prior.get("current_trade") else None
    protection = AFastCoreProtectionState(**prior["protection_state"]) if current else None
    component = promotion_gate.resolve_common_pit_component(ticker, _day(reference))
    same_identity = (component["isu_cd"], component["market"]) if component else None
    if (history or prior.get("action") == "ENTER_NEXT_OPEN") and (
        component is None or component != promotion_gate.resolve_common_pit_component(ticker, _day(prior_reference))
    ):
        raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_PIT_COMPONENT_CHANGED")
    if history and (
        sum(row.trade_status == "OPEN_AT_CUTOFF" for row in history) != int(current is not None)
        or (current and (history[-1].trade_id != current.trade_id or history[-1].entry_open != current.entry_open))
    ):
        raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_OPEN_MISMATCH")
    if current and (
        current.trade_status != "OPEN" or not math.isfinite(current.entry_open) or current.entry_open <= 0
        or current.entry_execution_date > _day(prior_reference)
        or (protection.phase, protection.loss_guard_state) not in {("PROGRESSED", "INACTIVE"), ("PRE_PROGRESSED", "ACTIVE")}
    ):
        raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_OPEN_PROTECTION_INVALID")
    carried_id = current.trade_id if current else None
    carried_history_return = history[-1].return_pct if current else None
    audits = []
    pending = _pending_entry(prior, prior_reference, ticker, same_identity)
    if pending:
        audits.extend(a for a in prior["promotion_gate_audit"] if a.get("signal_date") == pending.ledger_date)
    if current and current.pending_exit_signal_date:
        reason = current.pending_exit_type
        if reason != LOSS_GUARD_EXIT and not str(reason).startswith(("EXIT3_", "EXIT4_")):
            raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_EXIT_REASON_INVALID")
        label = current.pending_exit_signal_date
        pending = PendingSignal(_actual_exit_session(label, reason, calendar), label, reason)
        if pending.actual_date > prior_reference or history[-1].exit_signal_date != label:
            raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_EXIT_NOT_SEALED")
    elif current and (current.pending_exit_type or history[-1].exit_signal_date):
        raise AlignmentGateIntegrityError("INCREMENTAL_PRIOR_EXIT_NOT_SEALED")

    daily = daily.loc[:reference]
    context = build_precomputed_ticker_context(ticker, name, daily) if not daily.empty else None
    months = {day for day in calendar.get_month_ends(reference) if day > prior_reference}
    monthly = None
    missing_month = False
    sessions = calendar.trading_dates[(calendar.trading_dates > prior_reference) & (calendar.trading_dates <= reference)]
    for day in sessions:
        day_text = _day(day)
        if current is not None or pending is not None:
            if component is None or promotion_gate.resolve_common_pit_component(ticker, day_text) != component:
                raise AlignmentGateIntegrityError(f"INCREMENTAL_PIT_COMPONENT_CHANGED:{ticker}:{day_text}")
        if pending is not None:
            fill_day, price = _next_execution_open(pending.actual_date, daily, day, calendar, execution_open_resolver)
            if fill_day is not None:
                if fill_day != day:
                    raise AlignmentGateIntegrityError("INCREMENTAL_PENDING_EXECUTION_OUTSIDE_WINDOW")
                if current is None:
                    current, protection = _record_entry(ticker, history, pending, day_text, price)
                    monthly = []
                    missing_month = False
                else:
                    row = history[-1]
                    row.exit_type, row.exit_signal_date = pending.reason, pending.ledger_date
                    row.exit_execution_date, row.exit_price = day_text, round(price, 2)
                    row.trade_status = "REALIZED"
                    row.return_pct = round((price / row.entry_open - 1.0) * 100, 2)
                    current, protection, monthly = None, None, None
                pending = None
        if current is not None and pending is None:
            if day in months and not missing_month:
                if day in daily.index:
                    snapshot = build_historical_snapshot_from_context(context, day, False, market_calendar=calendar)
                    result = evaluate_pattern_a(snapshot)
                else:
                    result = None
                if result is None or result.stage is None or result.score is None:
                    missing_month = True
                if not missing_month:
                    if monthly is None:
                        monthly = _seed_monthly_observations(prior_report, current, calendar)
                    label = day + pd.offsets.MonthEnd(0)
                    monthly.append({"date": label, "effective_trading_date": day,
                                    "stage": result.stage.value.upper(), "score": round(result.score, 2)})
                    lifecycle = _simulate_causal_lifecycle(monthly, current.entry_pattern_a_stage)
                    if not current.first_progressed_date and lifecycle["first_progressed_date"] is not None:
                        current.first_progressed_date = protection.first_progressed_date = _day(label)
                        current.first_progressed_effective_trading_date = protection.first_progressed_effective_trading_date = day_text
                        protection.phase, protection.loss_guard_state, protection.loss_guard_threshold_pct = "PROGRESSED", "INACTIVE", None
                        protection.exit4_state = "ARMED"
                    if protection.phase == "PROGRESSED":
                        current.lifecycle_class = protection.lifecycle_class = lifecycle["coverage_path"]
                        protection.exit3_state = "ARMED" if lifecycle["direct_handoff_observed"] else "DISABLED_BY_COVERAGE_CONTRACT"
                        if protection.progressed_hwm_score is None or result.score > protection.progressed_hwm_score:
                            protection.progressed_hwm_score = round(result.score, 2)
                    if lifecycle["exit_signal_date"] is not None:
                        pending = PendingSignal(day, _day(label), lifecycle["exit_type"])
            if pending is None and protection.loss_guard_state == "ACTIVE":
                if day not in daily.index:
                    if inactive_session is None or not inactive_session(day):
                        raise AlignmentGateIntegrityError(f"INCREMENTAL_LOSS_GUARD_CLOSE_UNVERIFIED:{ticker}:{day_text}")
                else:
                    close = float(daily.at[day, "close"])
                    if not math.isfinite(close) or close <= 0:
                        raise AlignmentGateIntegrityError(f"INCREMENTAL_LOSS_GUARD_CLOSE_UNVERIFIED:{ticker}:{day_text}")
                    if close / current.entry_open - 1.0 <= -0.15:
                        if missing_month:
                            raise AlignmentGateIntegrityError(f"INCREMENTAL_LOSS_GUARD_PHASE_UNVERIFIED:{ticker}:{day_text}")
                        pending = PendingSignal(day, day_text, LOSS_GUARD_EXIT)
        elif current is None and pending is None and day.weekday() == 4 and day in daily.index:
            point = evaluate_pattern_a_fast(ticker, name, daily, day, score_contract, stage_contract, context=context, market_calendar=calendar)
            if is_v02_entry_signal(point):
                decision = promotion_gate.evaluate_historical_alignment(ticker, market, daily, day)
                audits.append(decision.to_dict(day))
                if decision.allowed:
                    if component is None or component != promotion_gate.resolve_common_pit_component(ticker, day_text):
                        raise AlignmentGateIntegrityError(f"INCREMENTAL_ENTRY_PIT_IDENTITY_CHANGED:{ticker}:{day_text}")
                    pending = PendingSignal(day, day_text, "ALL_ENTRY_CONDITIONS_MET", _entry_conditions(point, decision))
        if pending is not None and current is not None:
            current.pending_exit_signal_date, current.pending_exit_type = pending.ledger_date, pending.reason
            history[-1].exit_signal_date, history[-1].exit_type = pending.ledger_date, pending.reason

    available = False
    snapshot = None
    if context is not None and reference in daily.index:
        snapshot = build_historical_snapshot_from_context(context, reference, False, market_calendar=calendar)
        result = evaluate_pattern_a(snapshot)
        available = result.stage is not None and result.score is not None and not missing_month
    reason = "ENTRY_CONDITIONS_NOT_MET"
    state, action, interpretation = "WAIT", "WAIT", "새 인증 세션의 진입 조건을 평가했습니다."
    if pending is not None:
        state, action = ("ENTRY", "ENTER_NEXT_OPEN") if pending.entry else ("EXIT", "EXIT_NEXT_OPEN")
        reason = pending.reason
        interpretation = "확인된 신호의 다음 거래일 시가를 대기합니다."
    elif not available:
        state, action = "DATA_UNAVAILABLE", "NONE"
        reason = OPEN_EVALUATION_UNAVAILABLE if current else "CERTIFIED_PERIOD_CLOSE_UNAVAILABLE"
        interpretation = "현재 보호 평가를 보류하고 봉인된 포지션을 유지합니다." if current else "현재 진입 평가에 필요한 데이터가 부족합니다."
    elif current is not None:
        state, action = f"HOLD_{protection.phase}", "HOLD"
        reason = f"OPEN_POSITION_{protection.phase}"
        interpretation = "기존 진입과 보호 이력을 이어받아 현재 포지션을 유지합니다."

    if current is not None:
        if reference in daily.index:
            current.current_close = float(daily.at[reference, "close"])
            current.current_return_pct = round((current.current_close / current.entry_open - 1.0) * 100, 2)
        protection.current_pattern_a_score = round(result.score, 2) if available else None
        hwm = protection.progressed_hwm_score
        protection.score_drawdown_from_hwm_pt = round(hwm - protection.current_pattern_a_score, 2) if available and hwm is not None else None
        if available or current.trade_id != carried_id:
            history[-1].return_pct = current.current_return_pct
        elif history[-1].return_pct != carried_history_return:
            raise AlignmentGateIntegrityError("INCREMENTAL_UNAVAILABLE_MARK_CHANGED")
        if available or current.trade_id != carried_id or current.lifecycle_class != prior["current_trade"]["lifecycle_class"]:
            history[-1].lifecycle_class = current.lifecycle_class
        if pending is None and (available or current.trade_id != carried_id or monthly):
            history[-1].exit_type = "NO_EXIT_BEFORE_CUTOFF" if protection.phase == "PROGRESSED" else "NO_PROGRESSED_BEFORE_CUTOFF"
        if not available and pending is None:
            interpretation += (
                f" {_day(prior_reference)} 기준 보호 기록은 {protection.phase}, "
                f"HWM {hwm}, Exit 3 {protection.exit3_state}, Exit 4 {protection.exit4_state}입니다."
            )
    last_sequence = history[-1].trade_sequence if history else 0
    return AFastCoreSection(
        strategy_id=PROMOTED_STRATEGY_ID, strategy_version="V02_ALIGNMENT_MCAP_500B",
        strategy_alias=PROMOTED_STRATEGY_NAME, as_of=_day(requested), strategy_state=state,
        canonical_position="OPEN" if current else "FLAT", action=action, action_reason=reason,
        execution_timing="NEXT_LOCAL_TRADING_DAY_OPEN" if pending else None,
        entry_conditions=pending.entry if pending else None, current_trade=current, protection_state=protection,
        reentry_state=AFastCoreReentryState(
            completed_trade_count=len(history) - int(current is not None),
            current_trade_sequence=current.trade_sequence if current else None, next_entry_sequence=last_sequence + 1,
        ),
        trade_history=history, interpretation=interpretation,
        provenance=AFastCoreProvenance(
            strategy_contract=PROMOTED_STRATEGY_ID,
            strategy_contract_path="docs/patterns/pattern_a_fast/strategy/version_02_alignment_mcap_500b/README.md",
        ),
        research_group_id="ALIGNMENT_MCAP_500B", promotion_gate_audit=audits,
        strategy_replay_mode=CANONICAL_LEDGER_INCREMENTAL_V01,
    )
