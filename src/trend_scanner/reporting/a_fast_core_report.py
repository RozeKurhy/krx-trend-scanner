"""A FAST Core V2 Strategy Reporting Representation Module.

Purpose:
  - Transforms Frozen Strategy Contract (PATTERN_A_FAST_FINAL_STRATEGY_V02) state into
    Stock Report v0.2 data structures (AFastCoreSection).
  - Strictly preserves point-in-time constraints (requested_as_of) with zero lookahead.
  - Generates deterministic narrative templates without LLM hallucination.
  - Zero Network Requests (local execution only).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.reporting.models import (
    AFastCoreCurrentTrade,
    AFastCoreEntryConditions,
    AFastCoreProtectionState,
    AFastCoreProvenance,
    AFastCoreReentryState,
    AFastCoreSection,
    AFastCoreTradeHistoryItem,
)
from trend_scanner.universe.asset_classifier import AssetType, classify_asset_type
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import simulate_ticker_core_v02_reentry

logger = logging.getLogger(__name__)


def build_a_fast_core_section(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    requested_as_of: pd.Timestamp,
    is_investable: bool,
    is_common_stock: bool | None,
    score_contract: dict,
    stage_contract: dict,
) -> AFastCoreSection:
    """단일 종목에 대해 requested_as_of 시점의 A FAST Core V2 전략 상태 섹션을 생성한다."""
    as_of_str = requested_as_of.strftime("%Y-%m-%d")

    # 1. Check Common Stock Asset Classification
    if is_common_stock is None:
        asset_t = classify_asset_type(ticker, name)
        is_common_stock = (asset_t == AssetType.COMMON)

    # 2. Check Data Availability
    if daily is None or daily.empty or len(daily) < 60:
        return AFastCoreSection(
            as_of=as_of_str,
            applicability="DATA_UNAVAILABLE",
            strategy_state="DATA_UNAVAILABLE",
            canonical_position="DATA_UNAVAILABLE",
            action="NONE",
            action_reason="INSUFFICIENT_DATA",
            execution_timing=None,
            interpretation="필수 시계열 데이터가 부족하여 패스트 코어 V2 전략 상태를 판정할 수 없습니다.",
            provenance=AFastCoreProvenance(),
        )

    # 3. Check Instrument Applicability
    if not is_common_stock:
        return AFastCoreSection(
            as_of=as_of_str,
            applicability="NOT_APPLICABLE",
            strategy_state="NOT_APPLICABLE",
            canonical_position="NOT_APPLICABLE",
            action="NONE",
            action_reason="NON_COMMON_STOCK",
            execution_timing=None,
            interpretation="보통주가 아닌 종목(ETF/ETN/우선주 등)으로 패스트 코어 V2 전략 적용 대상이 아닙니다.",
            provenance=AFastCoreProvenance(),
        )

    # 4. Filter Daily Series up to requested_as_of (Strict PIT)
    daily_as_of = daily[daily.index <= requested_as_of].sort_index()
    if daily_as_of.empty or len(daily_as_of) < 60:
        return AFastCoreSection(
            as_of=as_of_str,
            applicability="DATA_UNAVAILABLE",
            strategy_state="DATA_UNAVAILABLE",
            canonical_position="DATA_UNAVAILABLE",
            action="NONE",
            action_reason="INSUFFICIENT_DATA",
            execution_timing=None,
            interpretation="분석 기준일 이전 일봉 데이터가 부족하여 패스트 코어 V2 전략 상태를 판정할 수 없습니다.",
            provenance=AFastCoreProvenance(),
        )

    # 5. Simulate Frozen V2 Re-entry Trajectory up to requested_as_of
    trades = simulate_ticker_core_v02_reentry(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily_as_of,
        score_contract=score_contract,
        stage_contract=stage_contract,
        cutoff_date=requested_as_of,
    )

    # Build Trade History Items
    trade_history_items: list[AFastCoreTradeHistoryItem] = []
    for tr in trades:
        ret = tr.terminal_return
        trade_history_items.append(
            AFastCoreTradeHistoryItem(
                trade_id=tr.trade_id,
                trade_sequence=tr.trade_sequence,
                entry_signal_date=tr.entry_signal_date,
                entry_execution_date=tr.entry_execution_date,
                entry_open=tr.entry_open,
                entry_pattern_a_stage=tr.entry_pattern_a_stage,
                exit_type=tr.exit_type,
                exit_signal_date=tr.exit_signal_date,
                exit_execution_date=tr.exit_execution_date,
                exit_price=tr.exit_price,
                trade_status=tr.trade_status,
                return_pct=ret,
                previous_exit_type=tr.previous_exit_type,
                lifecycle_class=tr.lifecycle_class,
            )
        )

    # 6. Check Active Position on requested_as_of
    is_position_open = False
    active_trade = None
    if trades:
        last_trade = trades[-1]
        # Position is OPEN if trade is OPEN_AT_CUTOFF
        if last_trade.trade_status == "OPEN_AT_CUTOFF":
            is_position_open = True
            active_trade = last_trade
        # Or if exit signal triggered on or before requested_as_of, but execution date is after requested_as_of
        elif last_trade.exit_signal_date is not None and pd.Timestamp(last_trade.exit_signal_date) <= requested_as_of:
            if last_trade.exit_execution_date is None or pd.Timestamp(last_trade.exit_execution_date) > requested_as_of:
                is_position_open = True
                active_trade = last_trade

    current_close = float(daily_as_of.iloc[-1]["close"])

    # 7. Evaluate Section States
    if is_position_open and active_trade is not None:
        canonical_pos = "OPEN"
        entry_open = active_trade.entry_open
        cur_return_pct = round((current_close / entry_open - 1.0) * 100.0, 2)

        # First PROGRESSED effective date check
        f_prog_d = active_trade.first_progressed_date
        f_prog_eff_d = active_trade.first_progressed_effective_trading_date
        has_reached_prog = bool(
            f_prog_d is not None
            and (f_prog_eff_d is None or pd.Timestamp(f_prog_eff_d) <= requested_as_of)
        )

        # Protection State Tracking
        phase = "PROGRESSED" if has_reached_prog else "PRE_PROGRESSED"
        loss_guard_state = "INACTIVE" if has_reached_prog else "ACTIVE"
        loss_guard_thresh = None if has_reached_prog else -15.0

        exit3_state = "INACTIVE"
        exit4_state = "INACTIVE"
        prog_hwm_score = None
        score_dd_from_hwm = None

        # Reconstruct current Pattern A score on requested_as_of
        try:
            cur_snap = build_historical_snapshot(ticker, name, daily_as_of, requested_as_of, include_incomplete_periods=False)
            cur_eval = evaluate_pattern_a(cur_snap)
            cur_pa_score = float(round(cur_eval.score, 2)) if cur_eval.score is not None else None
        except Exception:
            cur_pa_score = None

        if has_reached_prog:
            exit4_state = "ARMED"
            if active_trade.lifecycle_class == "NORMAL_EARLY_TREND_HANDOFF":
                exit3_state = "ARMED"
            else:
                exit3_state = "DISABLED_BY_COVERAGE_CONTRACT"

            # Compute PROGRESSED HWM score up to requested_as_of
            monthly_bars = to_monthly(daily_as_of)
            prog_m_dates = [m for m in monthly_bars.index if f_prog_d and m >= pd.Timestamp(f_prog_d) and m <= requested_as_of]
            for m in prog_m_dates:
                try:
                    m_snap = build_historical_snapshot(ticker, name, daily_as_of[daily_as_of.index <= m], m, include_incomplete_periods=False)
                    m_eval = evaluate_pattern_a(m_snap)
                    if m_eval.score is not None:
                        sc = float(round(m_eval.score, 2))
                        if prog_hwm_score is None or sc > prog_hwm_score:
                            prog_hwm_score = sc
                except Exception:
                    pass

            if prog_hwm_score is not None and cur_pa_score is not None:
                score_dd_from_hwm = round(prog_hwm_score - cur_pa_score, 2)

        protection_state = AFastCoreProtectionState(
            phase=phase,
            loss_guard_state=loss_guard_state,
            loss_guard_threshold_pct=loss_guard_thresh,
            first_progressed_date=f_prog_d,
            first_progressed_effective_trading_date=f_prog_eff_d,
            lifecycle_class=active_trade.lifecycle_class,
            exit3_state=exit3_state,
            exit4_state=exit4_state,
            progressed_hwm_score=prog_hwm_score,
            current_pattern_a_score=cur_pa_score,
            score_drawdown_from_hwm_pt=score_dd_from_hwm,
        )

        current_trade = AFastCoreCurrentTrade(
            trade_id=active_trade.trade_id,
            trade_sequence=active_trade.trade_sequence,
            entry_signal_date=active_trade.entry_signal_date,
            entry_execution_date=active_trade.entry_execution_date,
            entry_open=entry_open,
            entry_pattern_a_stage=active_trade.entry_pattern_a_stage,
            previous_exit_type=active_trade.previous_exit_type,
            previous_exit_execution_date=active_trade.previous_exit_execution_date,
            first_progressed_date=f_prog_d,
            first_progressed_effective_trading_date=f_prog_eff_d,
            lifecycle_class=active_trade.lifecycle_class,
            current_close=current_close,
            current_return_pct=cur_return_pct,
            trade_status="OPEN",
            pending_exit_type=active_trade.exit_type if active_trade.exit_signal_date else None,
            pending_exit_signal_date=active_trade.exit_signal_date,
        )

        # Check pending exit
        if active_trade.exit_signal_date is not None and pd.Timestamp(active_trade.exit_signal_date) <= requested_as_of:
            strategy_state = "EXIT"
            action = "EXIT_NEXT_OPEN"
            execution_timing = "NEXT_LOCAL_TRADING_DAY_OPEN"
            if active_trade.loss_guard_triggered or active_trade.exit_type == "LOSS_GUARD_CLOSE_LE_NEG_15":
                action_reason = "LOSS_GUARD_SIGNAL"
                interp = "패스트 코어 V2 Pre-PROGRESSED Loss Guard(-15%) 신호가 발생했습니다. 다음 로컬 거래일 시가에 청산합니다."
            elif active_trade.exit_type.startswith("EXIT3_"):
                action_reason = "EXIT3_SIGNAL"
                interp = f"패스트 코어 V2 월봉 국면 전환 청산 신호({active_trade.exit_type})가 발생했습니다. 다음 로컬 거래일 시가에 청산합니다."
            elif active_trade.exit_type == "EXIT4_SCORE_DRAWDOWN_GE_15":
                action_reason = "EXIT4_SIGNAL"
                interp = "패스트 코어 V2 Score HWM 15pt 하락 청산 신호(Exit4)가 발생했습니다. 다음 로컬 거래일 시가에 청산합니다."
            else:
                action_reason = "EXIT_SIGNAL"
                interp = "패스트 코어 V2 청산 신호가 발생했습니다. 다음 로컬 거래일 시가에 청산합니다."
        else:
            if not has_reached_prog:
                strategy_state = "HOLD_PRE_PROGRESSED"
                action = "HOLD"
                action_reason = "OPEN_POSITION_PRE_PROGRESSED"
                execution_timing = None
                interp = "패스트 코어 V2 전략 포지션을 보유 중이며 아직 PROGRESSED 이전입니다. Pre-PROGRESSED Loss Guard(-15%)가 활성화되어 있습니다."
            else:
                strategy_state = "HOLD_PROGRESSED"
                action = "HOLD"
                action_reason = "OPEN_POSITION_PROGRESSED"
                execution_timing = None
                interp = "패스트 코어 V2 전략 포지션은 PROGRESSED 구간에 있습니다. 초기 Loss Guard는 비활성화되었으며 Exit3 / Exit4 기준으로 추세 종료 여부를 관찰합니다."

        completed_cnt = len(trades) - 1 if (trades and trades[-1].trade_status == "OPEN_AT_CUTOFF") else len(trades)
        reentry_state = AFastCoreReentryState(
            enabled=True,
            cooldown="NONE",
            maximum_reentries="NONE",
            pyramiding=False,
            overlapping_position=False,
            same_open_exit_and_reentry=False,
            completed_trade_count=completed_cnt,
            current_trade_sequence=active_trade.trade_sequence,
            next_entry_sequence=active_trade.trade_sequence + 1,
        )

        entry_conditions = AFastCoreEntryConditions(
            instrument_eligible=is_common_stock,
            investability_pass=is_investable,
            pattern_a_stage_eligible=False,
            fast_trigger_ready=False,
            monthly_regime_permitted=False,
            daily_risk_allowed=False,
            fast_score_status_allowed=False,
            no_open_position=False,
            all_conditions_met=False,
            failed_conditions=["POSITION_ALREADY_OPEN"],
        )

    else:
        # FLAT position on requested_as_of
        canonical_pos = "FLAT"
        current_trade = None
        protection_state = None

        completed_cnt = len(trades)
        next_seq = (trades[-1].trade_sequence + 1) if trades else 1
        reentry_state = AFastCoreReentryState(
            enabled=True,
            cooldown="NONE",
            maximum_reentries="NONE",
            pyramiding=False,
            overlapping_position=False,
            same_open_exit_and_reentry=False,
            completed_trade_count=completed_cnt,
            current_trade_sequence=None,
            next_entry_sequence=next_seq,
        )

        # Evaluate entry conditions on the latest completed week on or before requested_as_of
        weekly_bars = to_weekly(daily_as_of)
        valid_weeks = [
            w for w in weekly_bars.index
            if daily_as_of[daily_as_of.index <= w].index.max().normalize() == w.normalize()
        ]

        if valid_weeks:
            latest_w = valid_weeks[-1]
            try:
                fast_res = evaluate_pattern_a_fast(
                    ticker, name, daily_as_of[daily_as_of.index <= latest_w], latest_w, score_contract, stage_contract
                )
            except Exception:
                fast_res = {}
        else:
            fast_res = {}

        raw_pa_stage = fast_res.get("pattern_a_stage")
        pa_stage = str(raw_pa_stage).upper() if (raw_pa_stage and not pd.isna(raw_pa_stage)) else "UNAVAILABLE"
        pa_ok = pa_stage in {"TRANSITION", "EARLY_TREND"}

        fast_st = fast_res.get("fast_machine_stage")
        fast_stat = fast_res.get("fast_machine_stage_status")
        fast_trig_ok = (fast_st == "TRIGGER" and fast_stat == "READY")

        m_reg = fast_res.get("fast_monthly_permission_state")
        m_reg_ok = (m_reg == "PERMITTED_REGIME")

        d_risk = fast_res.get("fast_daily_risk_state")
        d_risk_ok = (d_risk in {"NORMAL", "ELEVATED"})

        sc_stat = fast_res.get("fast_score_status")
        sc_stat_ok = (sc_stat in {"READY", "PARTIAL"})

        inst_ok = is_common_stock
        inv_ok = is_investable
        no_pos_ok = True

        failed_conds: list[str] = []
        if not inst_ok:
            failed_conds.append("NON_COMMON_STOCK")
        if not inv_ok:
            failed_conds.append("NOT_INVESTABLE")
        if not pa_ok:
            failed_conds.append("PATTERN_A_STAGE_NOT_ELIGIBLE")
        if not fast_trig_ok:
            failed_conds.append("FAST_NOT_TRIGGER_READY")
        if not m_reg_ok:
            failed_conds.append("MONTHLY_REGIME_NOT_PERMITTED")
        if not d_risk_ok:
            failed_conds.append("DAILY_RISK_EXTREME")
        if not sc_stat_ok:
            failed_conds.append("FAST_SCORE_STATUS_NOT_ALLOWED")

        all_met = bool(
            inst_ok and inv_ok and pa_ok and fast_trig_ok and m_reg_ok and d_risk_ok and sc_stat_ok and no_pos_ok
        )

        entry_conditions = AFastCoreEntryConditions(
            instrument_eligible=inst_ok,
            investability_pass=inv_ok,
            pattern_a_stage_eligible=pa_ok,
            fast_trigger_ready=fast_trig_ok,
            monthly_regime_permitted=m_reg_ok,
            daily_risk_allowed=d_risk_ok,
            fast_score_status_allowed=sc_stat_ok,
            no_open_position=no_pos_ok,
            all_conditions_met=all_met,
            pattern_a_stage=pa_stage,
            fast_stage=fast_st,
            fast_stage_status=fast_stat,
            monthly_regime=m_reg,
            daily_risk=d_risk,
            fast_score_status=sc_stat,
            failed_conditions=failed_conds,
        )

        if all_met:
            strategy_state = "ENTRY"
            action = "ENTER_NEXT_OPEN"
            action_reason = "ALL_ENTRY_CONDITIONS_MET"
            execution_timing = "NEXT_LOCAL_TRADING_DAY_OPEN"
            interp = "패스트 코어 V2 신규 진입 조건이 충족되었습니다. 전략 체결 기준은 다음 로컬 거래일 시가입니다."
        else:
            strategy_state = "WAIT"
            action = "WAIT"
            action_reason = "ENTRY_CONDITIONS_NOT_MET" if inv_ok else "NOT_INVESTABLE"
            execution_timing = None
            interp = "현재 패스트 코어 V2 신규 진입 조건을 충족하지 않습니다."

    return AFastCoreSection(
        strategy_id="PATTERN_A_FAST_FINAL_STRATEGY_V02",
        strategy_version="V02",
        strategy_alias="A FAST Core",
        strategy_status="FINAL_STRATEGY_FROZEN",
        production_status="PRODUCTION_DECISION_SUPPORT",
        fresh_oos_status="NOT_EXECUTED",
        as_of=as_of_str,
        applicability="APPLICABLE",
        strategy_state=strategy_state,
        canonical_position=canonical_pos,
        action=action,
        action_reason=action_reason,
        execution_timing=execution_timing,
        entry_conditions=entry_conditions,
        current_trade=current_trade,
        protection_state=protection_state,
        reentry_state=reentry_state,
        trade_history=trade_history_items,
        interpretation=interp,
        provenance=AFastCoreProvenance(),
    )
