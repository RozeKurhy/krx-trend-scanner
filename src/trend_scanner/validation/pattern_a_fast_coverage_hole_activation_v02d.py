"""FAST + Pattern A Coverage Hole Activation Validation v0.2D Evaluation Module.

Evaluates:
  Primary Question 1:
    "When Exit 4 (15pt PROGRESSED Score HWM Protection) is activated for the 107 Coverage Hole
     trades (SKIPPED_EARLY_TREND_HANDOFF [32] and PROGRESSED_WITHOUT_DIRECT_HANDOFF [75]) at
     first observed PROGRESSED snapshot (Policy C), how does it compare against Policy B in
     Terminal Return, Peak Giveback, Profit Capture, and Holding Period?"
  Primary Question 2:
    "Does Coverage Activation compromise large Right Tail winners (Return >= +50%, >= +100%)
     through premature exit, or does it effectively reduce Peak Giveback?"
  Primary Question 3:
    "Are results consistent between SKIPPED and PROGRESSED_WITHOUT_DIRECT subgroups, and is full
     system impact on all 553 Combined Executable entries fully aligned with Coverage Hole deltas?"

Strict Invariants:
  - Local cache only (zero external network requests).
  - Frozen 15.0pt drawdown threshold (strictly no sweep/tuning).
  - Frozen Entry population (553 Combined Executable trades).
  - NORMAL cohort and NEVER_PROGRESSED cohort are 100% identical between Policy B and Policy C.
  - Next local trading day OPEN execution.
  - PRODUCTION_HOLD (research evaluation only, zero production impact).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly, to_weekly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

logger = logging.getLogger(__name__)

DATA_CUTOFF = pd.Timestamp("2026-08-14")


@dataclass
class PairedCoverageTradeRecord:
    ticker: str
    name: str
    market: str

    entry_signal_date: str
    entry_execution_date: str
    entry_open: float

    entry_pattern_a_stage: str
    fast_stage_at_entry: str
    fast_monthly_regime_at_entry: str
    daily_risk_at_entry: str
    fast_score: float | None
    fast_score_availability: str

    lifecycle_class: str
    first_early_trend_date: str | None
    first_progressed_date: str | None
    direct_early_to_progressed_handoff: bool
    coverage_hole_type: str

    # Policy B (Frozen Baseline Comparator)
    policy_b_exit_type: str | None
    policy_b_exit_signal_date: str | None
    policy_b_exit_execution_date: str | None
    policy_b_exit_price: float | None
    policy_b_trade_status: str
    policy_b_realized_return: float | None
    policy_b_mark_to_cutoff_return: float | None
    policy_b_terminal_return: float
    policy_b_mfe: float
    policy_b_mae: float
    policy_b_peak_giveback: float
    policy_b_profit_capture: float | None
    policy_b_holding_days: int
    policy_b_holding_weeks: float

    # Policy C (Coverage Activated)
    policy_c_armed: bool
    policy_c_arm_date: str | None
    policy_c_initial_progressed_score: float | None
    policy_c_hwm_score: float | None
    policy_c_trigger_score: float | None
    policy_c_score_drawdown: float | None

    policy_c_exit_type: str | None
    policy_c_exit_signal_date: str | None
    policy_c_exit_execution_date: str | None
    policy_c_exit_price: float | None
    policy_c_trade_status: str
    policy_c_realized_return: float | None
    policy_c_mark_to_cutoff_return: float | None
    policy_c_terminal_return: float
    policy_c_mfe: float
    policy_c_mae: float
    policy_c_peak_giveback: float
    policy_c_profit_capture: float | None
    policy_c_holding_days: int
    policy_c_holding_weeks: float

    # Paired Deltas (Policy C - Policy B)
    paired_return_delta: float
    paired_giveback_delta: float
    paired_profit_capture_delta: float | None
    paired_holding_weeks_delta: float

    evaluation_status: str
    warning_count: int
    first_exception_type: str | None
    first_exception_message: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TickerCoverageDiagnostic:
    ticker: str
    name: str
    market: str
    evaluation_status: str
    fast_v01_qualified: bool
    fast_v01_first_entry_date: str | None
    fast_v01_pa_stage: str | None
    combined_qualified: bool
    combined_first_entry_date: str | None
    combined_pa_stage: str | None
    combined_executable: bool
    non_executable_reason: str | None
    gate_rejection_reason: str | None
    combined_entry_delay_days: int | None
    lifecycle_class: str | None
    coverage_hole_type: str | None
    warning_count: int
    first_exception_type: str | None
    first_exception_message: str | None


def simulate_ticker_coverage_hole_activation(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    cutoff_date: pd.Timestamp = DATA_CUTOFF,
) -> tuple[TickerCoverageDiagnostic, PairedCoverageTradeRecord | None]:
    """Simulate Combined v0.1 Entry and evaluate Policy B vs Policy C Coverage Activation."""
    if daily is None or daily.empty:
        diag = TickerCoverageDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="CACHE_MISSING",
            fast_v01_qualified=False,
            fast_v01_first_entry_date=None,
            fast_v01_pa_stage=None,
            combined_qualified=False,
            combined_first_entry_date=None,
            combined_pa_stage=None,
            combined_executable=False,
            non_executable_reason=None,
            gate_rejection_reason=None,
            combined_entry_delay_days=None,
            lifecycle_class=None,
            coverage_hole_type=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    daily = daily.sort_index()
    daily = daily[daily.index <= cutoff_date]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns):
        diag = TickerCoverageDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="INVALID_OHLCV",
            fast_v01_qualified=False,
            fast_v01_first_entry_date=None,
            fast_v01_pa_stage=None,
            combined_qualified=False,
            combined_first_entry_date=None,
            combined_pa_stage=None,
            combined_executable=False,
            non_executable_reason=None,
            gate_rejection_reason=None,
            combined_entry_delay_days=None,
            lifecycle_class=None,
            coverage_hole_type=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    if len(daily) < 60:
        diag = TickerCoverageDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="INSUFFICIENT_HISTORY",
            fast_v01_qualified=False,
            fast_v01_first_entry_date=None,
            fast_v01_pa_stage=None,
            combined_qualified=False,
            combined_first_entry_date=None,
            combined_pa_stage=None,
            combined_executable=False,
            non_executable_reason=None,
            gate_rejection_reason=None,
            combined_entry_delay_days=None,
            lifecycle_class=None,
            coverage_hole_type=None,
            warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None

    weekly_bars = to_weekly(daily)
    valid_weeks = [
        w for w in weekly_bars.index
        if daily[daily.index <= w].index.max().normalize() == w.normalize()
    ]

    fast_first_w: pd.Timestamp | None = None
    fast_first_pa_stage: str | None = None
    combined_first_w: pd.Timestamp | None = None
    combined_first_res: dict | None = None
    warning_count = 0
    first_ex_type: str | None = None
    first_ex_msg: str | None = None

    for w in valid_weeks:
        try:
            res = evaluate_pattern_a_fast(ticker, name, daily[daily.index <= w], w, score_contract, stage_contract)
            is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
            is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
            is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
            is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})
            is_fast = bool(is_trigger and is_permitted and is_non_extreme and is_score_ok)

            raw_stage = res.get("pattern_a_stage")
            pa_stage = str(raw_stage).upper() if (raw_stage is not None and not pd.isna(raw_stage)) else "UNAVAILABLE"

            if is_fast and fast_first_w is None:
                fast_first_w = w
                fast_first_pa_stage = pa_stage

            if is_fast and pa_stage in {"TRANSITION", "EARLY_TREND"} and combined_first_w is None:
                combined_first_w = w
                combined_first_res = res
                break
        except Exception as e:
            warning_count += 1
            if first_ex_type is None:
                first_ex_type = type(e).__name__
                first_ex_msg = str(e)

    gate_rejection = None
    delay_days = None
    if fast_first_w is not None:
        if combined_first_w is not None:
            delay_days = (combined_first_w - fast_first_w).days
        else:
            if fast_first_pa_stage in {"TRANSITION", "EARLY_TREND"}:
                gate_rejection = None
            elif fast_first_pa_stage in {"WEAK", "BASE", "PROGRESSED"}:
                gate_rejection = f"PATTERN_A_{fast_first_pa_stage}"
            else:
                gate_rejection = "PATTERN_A_UNAVAILABLE"

    combined_executable = False
    non_executable_reason: str | None = None
    entry_exec_date: pd.Timestamp | None = None
    entry_open_price: float | None = None

    if combined_first_w is not None:
        fut_daily = daily[(daily.index > combined_first_w) & (daily.index <= cutoff_date)]
        if fut_daily.empty:
            non_executable_reason = "NO_NEXT_TRADING_DAY_BEFORE_CUTOFF"
        else:
            combined_executable = True
            entry_exec_date = fut_daily.index[0]
            entry_open_price = float(fut_daily.iloc[0]["open"])

    if not combined_executable or combined_first_w is None or combined_first_res is None or entry_exec_date is None or entry_open_price is None:
        diag = TickerCoverageDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            evaluation_status="ELIGIBLE",
            fast_v01_qualified=fast_first_w is not None,
            fast_v01_first_entry_date=fast_first_w.strftime("%Y-%m-%d") if fast_first_w else None,
            fast_v01_pa_stage=fast_first_pa_stage,
            combined_qualified=combined_first_w is not None,
            combined_first_entry_date=combined_first_w.strftime("%Y-%m-%d") if combined_first_w else None,
            combined_pa_stage=(combined_first_res["pattern_a_stage"] or "").upper() if combined_first_res else None,
            combined_executable=False,
            non_executable_reason=non_executable_reason,
            gate_rejection_reason=gate_rejection,
            combined_entry_delay_days=delay_days,
            lifecycle_class=None,
            coverage_hole_type=None,
            warning_count=warning_count,
            first_exception_type=first_ex_type,
            first_exception_message=first_ex_msg,
        )
        return diag, None

    pa_stage_at_entry = (combined_first_res["pattern_a_stage"] or "").upper()
    fast_score = combined_first_res.get("fast_score")
    fast_score_avail = combined_first_res.get("fast_score_status", "UNKNOWN")
    daily_risk = combined_first_res.get("fast_daily_risk_state", "UNKNOWN")
    monthly_regime = combined_first_res.get("fast_monthly_permission_state", "UNKNOWN")

    # Trace completed monthly PIT Pattern A snapshots starting from entry signal month
    monthly_bars = to_monthly(daily)
    m_dates = [
        m for m in monthly_bars.index
        if m >= combined_first_w and m <= cutoff_date
    ]

    monthly_snapshots: list[dict[str, Any]] = []
    for m in m_dates:
        try:
            snap = build_historical_snapshot(ticker, name, daily[daily.index <= m], m, include_incomplete_periods=False)
            eval_res = evaluate_pattern_a(snap)
            st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"
            sc = float(round(eval_res.score, 2)) if eval_res.score is not None else None
            monthly_snapshots.append({"date": m, "stage": st, "score": sc})
        except Exception as e:
            warning_count += 1
            if first_ex_type is None:
                first_ex_type = type(e).__name__
                first_ex_msg = str(e)
            monthly_snapshots.append({"date": m, "stage": "UNAVAILABLE", "score": None})

    # Exact Handoff & Lifecycle Classification
    first_early_trend_d: pd.Timestamp | None = combined_first_w if pa_stage_at_entry == "EARLY_TREND" else None
    direct_handoff_observed = False
    early_trend_to_prog_d: pd.Timestamp | None = None
    first_progressed_d: pd.Timestamp | None = None
    first_prog_score: float | None = None
    skipped_handoff = False
    progressed_observed = False

    prev_valid_stage = pa_stage_at_entry
    had_early_trend = (pa_stage_at_entry == "EARLY_TREND")

    for row in monthly_snapshots:
        m = row["date"]
        st = row["stage"]
        sc = row["score"]

        if st == "UNAVAILABLE":
            continue

        if st == "EARLY_TREND":
            had_early_trend = True
            if first_early_trend_d is None:
                first_early_trend_d = m

        if st == "PROGRESSED":
            progressed_observed = True
            if first_progressed_d is None:
                first_progressed_d = m
                first_prog_score = sc

            if prev_valid_stage == "EARLY_TREND" and not direct_handoff_observed:
                direct_handoff_observed = True
                early_trend_to_prog_d = m
            elif (
                prev_valid_stage == "TRANSITION"
                and not had_early_trend
                and not direct_handoff_observed
                and not skipped_handoff
            ):
                skipped_handoff = True

        prev_valid_stage = st

    if direct_handoff_observed and early_trend_to_prog_d is not None:
        coverage_path = "NORMAL_EARLY_TREND_HANDOFF"
        cov_hole_type = "NONE"
    elif skipped_handoff:
        coverage_path = "SKIPPED_EARLY_TREND_HANDOFF"
        cov_hole_type = "SKIPPED_EARLY_TREND_HANDOFF"
    elif progressed_observed:
        coverage_path = "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
        cov_hole_type = "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
    else:
        coverage_path = "NEVER_PROGRESSED"
        cov_hole_type = "NONE"

    diag = TickerCoverageDiagnostic(
        ticker=ticker,
        name=name,
        market=market,
        evaluation_status="ELIGIBLE",
        fast_v01_qualified=True,
        fast_v01_first_entry_date=fast_first_w.strftime("%Y-%m-%d") if fast_first_w else None,
        fast_v01_pa_stage=fast_first_pa_stage,
        combined_qualified=True,
        combined_first_entry_date=combined_first_w.strftime("%Y-%m-%d"),
        combined_pa_stage=pa_stage_at_entry,
        combined_executable=True,
        non_executable_reason=None,
        gate_rejection_reason=None,
        combined_entry_delay_days=delay_days,
        lifecycle_class=coverage_path,
        coverage_hole_type=cov_hole_type,
        warning_count=warning_count,
        first_exception_type=first_ex_type,
        first_exception_message=first_ex_msg,
    )

    # -------------------------------------------------------------
    # 1. Simulate Policy B (Exit 3 + Exit 4 Baseline Frozen)
    # -------------------------------------------------------------
    pb_exit_sig_d: pd.Timestamp | None = None
    pb_exit_type: str | None = None

    if early_trend_to_prog_d is not None and coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
        in_prog_b = False
        prog_hwm_b: float | None = None
        for row in monthly_snapshots:
            m = row["date"]
            st = row["stage"]
            sc = row["score"]

            if m < early_trend_to_prog_d:
                continue

            if m == early_trend_to_prog_d:
                in_prog_b = True
                prog_hwm_b = sc if sc is not None else 0.0
                continue

            if in_prog_b:
                if st == "PROGRESSED":
                    if sc is not None and prog_hwm_b is not None:
                        prog_hwm_b = max(prog_hwm_b, sc)
                        dd_b = prog_hwm_b - sc
                        if dd_b >= 15.0:
                            pb_exit_sig_d = m
                            pb_exit_type = "EXIT4_SCORE_DRAWDOWN_GE_15"
                            break
                elif st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
                    pb_exit_sig_d = m
                    pb_exit_type = f"EXIT3_PROGRESSED_TO_{st}"
                    in_prog_b = False
                    break
        if pb_exit_sig_d is None:
            pb_exit_type = "NO_EXIT_BEFORE_CUTOFF"
    else:
        if coverage_path == "SKIPPED_EARLY_TREND_HANDOFF":
            pb_exit_type = "SKIPPED_EARLY_TREND_HANDOFF"
        elif coverage_path == "PROGRESSED_WITHOUT_DIRECT_HANDOFF":
            pb_exit_type = "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
        else:
            pb_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"

    pb_res = _calc_trade_outcome(
        entry_exec_d=entry_exec_date,
        entry_open=entry_open_price,
        exit_sig_d=pb_exit_sig_d,
        daily=daily,
        cutoff_date=cutoff_date,
    )

    # -------------------------------------------------------------
    # 2. Simulate Policy C (Coverage Activated)
    # -------------------------------------------------------------
    pc_armed = False
    pc_arm_date_str: str | None = None
    pc_initial_prog_score: float | None = None
    pc_hwm_score: float | None = None
    pc_trigger_score: float | None = None
    pc_score_drawdown: float | None = None
    pc_exit_sig_d: pd.Timestamp | None = None
    pc_exit_type: str | None = None

    if coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
        # NORMAL: Policy C == Policy B exactly
        pc_armed = early_trend_to_prog_d is not None
        pc_arm_date_str = early_trend_to_prog_d.strftime("%Y-%m-%d") if early_trend_to_prog_d else None
        pc_initial_prog_score = first_prog_score
        pc_exit_sig_d = pb_exit_sig_d
        pc_exit_type = pb_exit_type

        # Extract HWM and drawdown for NORMAL
        if early_trend_to_prog_d is not None:
            hwm_c = None
            in_p = False
            for row in monthly_snapshots:
                m = row["date"]
                st = row["stage"]
                sc = row["score"]
                if m < early_trend_to_prog_d:
                    continue
                if m == early_trend_to_prog_d:
                    in_p = True
                    hwm_c = sc if sc is not None else 0.0
                    continue
                if in_p and st == "PROGRESSED" and sc is not None and hwm_c is not None:
                    hwm_c = max(hwm_c, sc)
                    if hwm_c - sc >= 15.0:
                        pc_hwm_score = round(hwm_c, 2)
                        pc_trigger_score = round(sc, 2)
                        pc_score_drawdown = round(hwm_c - sc, 2)
                        break
            if pc_hwm_score is None and hwm_c is not None:
                pc_hwm_score = round(hwm_c, 2)

    elif coverage_path in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"}:
        # Coverage Hole: Activate from first observed PROGRESSED
        if first_progressed_d is not None:
            pc_armed = True
            pc_arm_date_str = first_progressed_d.strftime("%Y-%m-%d")
            pc_initial_prog_score = first_prog_score
            hwm_c = first_prog_score if first_prog_score is not None else 0.0
            max_dd_c = 0.0
            in_prog_c = True

            for row in monthly_snapshots:
                m = row["date"]
                st = row["stage"]
                sc = row["score"]

                if m <= first_progressed_d:
                    continue

                if in_prog_c:
                    if st == "PROGRESSED":
                        if sc is not None:
                            hwm_c = max(hwm_c, sc)
                            dd_c = hwm_c - sc
                            max_dd_c = max(max_dd_c, dd_c)
                            if dd_c >= 15.0:
                                pc_exit_sig_d = m
                                pc_exit_type = "EXIT4_SCORE_DRAWDOWN_GE_15"
                                pc_hwm_score = round(hwm_c, 2)
                                pc_trigger_score = round(sc, 2)
                                pc_score_drawdown = round(dd_c, 2)
                                break
                    else:
                        # Left PROGRESSED (Exit 3 not active in coverage hole as per v0.1)
                        in_prog_c = False
                        break

            if pc_hwm_score is None:
                pc_hwm_score = round(hwm_c, 2)
                pc_score_drawdown = round(max_dd_c, 2)

            if pc_exit_sig_d is None:
                pc_exit_type = "NO_EXIT_BEFORE_CUTOFF"
        else:
            pc_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"

    else:
        # NEVER_PROGRESSED: Policy C == Policy B
        pc_exit_type = pb_exit_type

    pc_res = _calc_trade_outcome(
        entry_exec_d=entry_exec_date,
        entry_open=entry_open_price,
        exit_sig_d=pc_exit_sig_d,
        daily=daily,
        cutoff_date=cutoff_date,
    )

    paired_ret_delta = round(pc_res["terminal_ret"] - pb_res["terminal_ret"], 2)
    paired_gb_delta = round(pc_res["terminal_giveback"] - pb_res["terminal_giveback"], 2)
    paired_pc_delta = (
        round(pc_res["terminal_profit_capture"] - pb_res["terminal_profit_capture"], 4)
        if (pc_res["terminal_profit_capture"] is not None and pb_res["terminal_profit_capture"] is not None)
        else None
    )
    paired_hw_delta = round(pc_res["holding_weeks"] - pb_res["holding_weeks"], 1)

    record = PairedCoverageTradeRecord(
        ticker=ticker,
        name=name,
        market=market,
        entry_signal_date=combined_first_w.strftime("%Y-%m-%d"),
        entry_execution_date=entry_exec_date.strftime("%Y-%m-%d"),
        entry_open=round(entry_open_price, 2),
        entry_pattern_a_stage=pa_stage_at_entry,
        fast_stage_at_entry="TRIGGER",
        fast_monthly_regime_at_entry=monthly_regime,
        daily_risk_at_entry=daily_risk,
        fast_score=round(fast_score, 2) if fast_score is not None else None,
        fast_score_availability=fast_score_avail,
        lifecycle_class=coverage_path,
        first_early_trend_date=first_early_trend_d.strftime("%Y-%m-%d") if first_early_trend_d else None,
        first_progressed_date=first_progressed_d.strftime("%Y-%m-%d") if first_progressed_d else None,
        direct_early_to_progressed_handoff=direct_handoff_observed,
        coverage_hole_type=cov_hole_type,
        policy_b_exit_type=pb_exit_type,
        policy_b_exit_signal_date=pb_exit_sig_d.strftime("%Y-%m-%d") if pb_exit_sig_d else None,
        policy_b_exit_execution_date=pb_res["exit_exec_d"].strftime("%Y-%m-%d") if pb_res["exit_exec_d"] else None,
        policy_b_exit_price=round(pb_res["exit_open"], 2) if pb_res["exit_open"] is not None else None,
        policy_b_trade_status=pb_res["trade_status"],
        policy_b_realized_return=pb_res["realized_ret"],
        policy_b_mark_to_cutoff_return=pb_res["mark_to_cutoff_ret"],
        policy_b_terminal_return=pb_res["terminal_ret"],
        policy_b_mfe=pb_res["mfe"],
        policy_b_mae=pb_res["mae"],
        policy_b_peak_giveback=pb_res["terminal_giveback"],
        policy_b_profit_capture=pb_res["terminal_profit_capture"],
        policy_b_holding_days=pb_res["holding_days"],
        policy_b_holding_weeks=pb_res["holding_weeks"],
        policy_c_armed=pc_armed,
        policy_c_arm_date=pc_arm_date_str,
        policy_c_initial_progressed_score=round(pc_initial_prog_score, 2) if pc_initial_prog_score is not None else None,
        policy_c_hwm_score=pc_hwm_score,
        policy_c_trigger_score=pc_trigger_score,
        policy_c_score_drawdown=pc_score_drawdown,
        policy_c_exit_type=pc_exit_type,
        policy_c_exit_signal_date=pc_exit_sig_d.strftime("%Y-%m-%d") if pc_exit_sig_d else None,
        policy_c_exit_execution_date=pc_res["exit_exec_d"].strftime("%Y-%m-%d") if pc_res["exit_exec_d"] else None,
        policy_c_exit_price=round(pc_res["exit_open"], 2) if pc_res["exit_open"] is not None else None,
        policy_c_trade_status=pc_res["trade_status"],
        policy_c_realized_return=pc_res["realized_ret"],
        policy_c_mark_to_cutoff_return=pc_res["mark_to_cutoff_ret"],
        policy_c_terminal_return=pc_res["terminal_ret"],
        policy_c_mfe=pc_res["mfe"],
        policy_c_mae=pc_res["mae"],
        policy_c_peak_giveback=pc_res["terminal_giveback"],
        policy_c_profit_capture=pc_res["terminal_profit_capture"],
        policy_c_holding_days=pc_res["holding_days"],
        policy_c_holding_weeks=pc_res["holding_weeks"],
        paired_return_delta=paired_ret_delta,
        paired_giveback_delta=paired_gb_delta,
        paired_profit_capture_delta=paired_pc_delta,
        paired_holding_weeks_delta=paired_hw_delta,
        evaluation_status="ELIGIBLE",
        warning_count=warning_count,
        first_exception_type=first_ex_type,
        first_exception_message=first_ex_msg,
    )

    return diag, record


def _calc_trade_outcome(
    entry_exec_d: pd.Timestamp,
    entry_open: float,
    exit_sig_d: pd.Timestamp | None,
    daily: pd.DataFrame,
    cutoff_date: pd.Timestamp,
) -> dict[str, Any]:
    exit_exec_d: pd.Timestamp | None = None
    exit_open: float | None = None
    trade_status: str = "OPEN_AT_CUTOFF"
    realized_ret: float | None = None
    mark_to_cutoff_ret: float | None = None

    if exit_sig_d is not None:
        fut_after_exit = daily[(daily.index > exit_sig_d) & (daily.index <= cutoff_date)]
        if not fut_after_exit.empty:
            exit_exec_d = fut_after_exit.index[0]
            exit_open = float(fut_after_exit.iloc[0]["open"])
            trade_status = "REALIZED"
            realized_ret = round(((exit_open - entry_open) / entry_open) * 100, 2)
        else:
            trade_status = "OPEN_AT_CUTOFF"

    if trade_status == "REALIZED" and exit_exec_d is not None and exit_open is not None:
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index < exit_exec_d)]
        holding_days = len(daily[(daily.index >= entry_exec_d) & (daily.index <= exit_exec_d)])
        holding_weeks = round(holding_days / 5.0, 1)

        if not holding_daily.empty:
            high_cand = holding_daily["high"].tolist() + [exit_open]
            low_cand = holding_daily["low"].tolist() + [exit_open]
            peak_price = float(max(high_cand))
            min_price = float(min(low_cand))
        else:
            peak_price = float(max(entry_open, exit_open))
            min_price = float(min(entry_open, exit_open))

        mfe = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae = round(((min_price - entry_open) / entry_open) * 100, 2)
        terminal_ret = realized_ret
    else:
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index <= cutoff_date)]
        holding_days = len(holding_daily)
        holding_weeks = round(holding_days / 5.0, 1)

        cutoff_close = float(holding_daily.iloc[-1]["close"]) if not holding_daily.empty else entry_open
        mark_to_cutoff_ret = round(((cutoff_close - entry_open) / entry_open) * 100, 2)

        peak_price = float(holding_daily["high"].max()) if not holding_daily.empty else entry_open
        min_price = float(holding_daily["low"].min()) if not holding_daily.empty else entry_open

        mfe = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae = round(((min_price - entry_open) / entry_open) * 100, 2)
        terminal_ret = mark_to_cutoff_ret

    terminal_gb = round(mfe - terminal_ret, 2)
    terminal_pc = round(terminal_ret / mfe, 4) if mfe > 0 else None

    return {
        "exit_exec_d": exit_exec_d,
        "exit_open": exit_open,
        "trade_status": trade_status,
        "realized_ret": realized_ret,
        "mark_to_cutoff_ret": mark_to_cutoff_ret,
        "terminal_ret": terminal_ret,
        "mfe": mfe,
        "mae": mae,
        "terminal_giveback": terminal_gb,
        "terminal_profit_capture": terminal_pc,
        "holding_days": holding_days,
        "holding_weeks": holding_weeks,
    }


def calculate_distribution_stats(series: pd.Series) -> dict[str, Any]:
    usable = series.dropna().astype(float)
    if usable.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p25": None,
            "p75": None,
            "std": None,
            "min": None,
            "max": None,
            "positive_rate": None,
        }
    pos_rate = float((usable > 0).mean() * 100)
    return {
        "count": int(len(usable)),
        "mean": round(float(usable.mean()), 2),
        "median": round(float(usable.median()), 2),
        "p25": round(float(np.percentile(usable, 25)), 2),
        "p75": round(float(np.percentile(usable, 75)), 2),
        "std": round(float(usable.std()), 2) if len(usable) > 1 else 0.0,
        "min": round(float(usable.min()), 2),
        "max": round(float(usable.max()), 2),
        "positive_rate": round(pos_rate, 1),
    }
