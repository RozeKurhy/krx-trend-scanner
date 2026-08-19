"""FAST Entry + Pattern A Exit / Handoff Policy v0.1 Evaluation Module (Corrected).

Evaluates:
  Entry:
    FAST v0.1: TRIGGER + READY + PERMITTED_REGIME + NORMAL/ELEVATED risk + READY/PARTIAL score
    AND Pattern A Stage at Entry IN {"TRANSITION", "EARLY_TREND"}
  Handoff & Exit:
    - Policy A (Exit 3 Only): After DIRECT EARLY_TREND -> PROGRESSED, hold through PROGRESSED.
      Exit on first PROGRESSED -> OTHER_VALID_STAGE (WEAK, BASE, TRANSITION, EARLY_TREND).
    - Policy B (Exit 3 + Exit 4): After DIRECT EARLY_TREND -> PROGRESSED, hold through PROGRESSED.
      Exit on FIRST(Exit 3, Exit 4: PROGRESSED_SCORE_HWM - current_score >= 15.0).
    - Coverage Hole: Direct TRANSITION -> PROGRESSED without EARLY_TREND (SKIPPED_EARLY_TREND_HANDOFF).

Correctness Fixes:
  1. Direct transition EARLY_TREND -> PROGRESSED (previous_valid_stage == EARLY_TREND).
  2. Same-cohort paired comparison between Policy A and Policy B (Terminal Return & Terminal Peak Giveback).
  3. Exit 4 triggered cohort counterfactual evaluation.
  4. MFE / MAE price extraction strictly before exit execution day (excluding exit day intraday price).
  5. Exact eligibility / exclusion tracking without swallowed exceptions.
  6. Independent recording of pattern_a_stage_at_entry vs coverage_path.
  7. Clear distinction between combined_signal_qualified vs combined_executable_entry.
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
class TradeRecord:
    ticker: str
    name: str
    market: str
    entry_signal_date: str
    entry_execution_date: str
    entry_open_price: float
    pattern_a_stage_at_entry: str
    fast_stage_at_entry: str
    fast_monthly_regime_at_entry: str
    daily_risk_at_entry: str
    fast_score: float | None
    fast_score_availability: str
    first_early_trend_date: str | None
    early_trend_to_progressed_date: str | None
    first_progressed_score: float | None
    progressed_score_hwm: float | None
    max_progressed_score_drawdown: float | None
    exit_policy: str
    exit_reason: str | None
    exit_signal_date: str | None
    exit_execution_date: str | None
    exit_open_price: float | None
    trade_status: str
    realized_return_pct: float | None
    mark_to_cutoff_return_pct: float | None
    terminal_return_pct: float
    mfe_pct: float
    mae_pct: float
    terminal_mfe_pct: float
    terminal_mae_pct: float
    peak_price_after_entry: float
    peak_date: str
    peak_giveback_pct: float | None
    terminal_peak_giveback_pct: float
    profit_capture_ratio: float | None
    terminal_profit_capture_ratio: float | None
    holding_days: int
    holding_weeks: float
    coverage_path: str
    entry_executable: bool
    entry_non_executable_reason: str | None
    evaluation_warning_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TickerEntryDiagnostic:
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
    evaluation_warning_count: int
    first_exception_type: str | None
    first_exception_message: str | None


def simulate_ticker_combined_policy(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    cutoff_date: pd.Timestamp = DATA_CUTOFF,
) -> tuple[TickerEntryDiagnostic, TradeRecord | None, TradeRecord | None]:
    """Simulate FAST + Pattern A Combined Policy on a single ticker with corrected PIT tracking."""
    if daily is None or daily.empty:
        diag = TickerEntryDiagnostic(
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
            evaluation_warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None, None

    daily = daily.sort_index()
    daily = daily[daily.index <= cutoff_date]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns):
        diag = TickerEntryDiagnostic(
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
            evaluation_warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None, None

    if len(daily) < 60:
        diag = TickerEntryDiagnostic(
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
            evaluation_warning_count=0,
            first_exception_type=None,
            first_exception_message=None,
        )
        return diag, None, None

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

    # Check executable feasibility
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

    diag = TickerEntryDiagnostic(
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
        combined_executable=combined_executable,
        non_executable_reason=non_executable_reason,
        gate_rejection_reason=gate_rejection,
        combined_entry_delay_days=delay_days,
        evaluation_warning_count=warning_count,
        first_exception_type=first_ex_type,
        first_exception_message=first_ex_msg,
    )

    if not combined_executable or combined_first_w is None or combined_first_res is None or entry_exec_date is None or entry_open_price is None:
        return diag, None, None

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
            monthly_snapshots.append({"date": m, "stage": "UNAVAILABLE", "score": None})

    # Major Fix 1: Direct transition tracking (prev_stage == EARLY_TREND -> current == PROGRESSED)
    first_early_trend_d: pd.Timestamp | None = combined_first_w if pa_stage_at_entry == "EARLY_TREND" else None
    direct_handoff_observed = False
    early_trend_to_prog_d: pd.Timestamp | None = None
    first_prog_score: float | None = None
    skipped_handoff = False

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
            if prev_valid_stage == "EARLY_TREND" and not direct_handoff_observed:
                direct_handoff_observed = True
                early_trend_to_prog_d = m
                first_prog_score = sc
            elif not had_early_trend and not direct_handoff_observed and not skipped_handoff:
                # Direct transition from TRANSITION to PROGRESSED without ever seeing EARLY_TREND
                skipped_handoff = True

        prev_valid_stage = st

    if direct_handoff_observed and early_trend_to_prog_d is not None:
        coverage_path = "NORMAL_EARLY_TREND_HANDOFF"
    elif skipped_handoff:
        coverage_path = "SKIPPED_EARLY_TREND_HANDOFF"
    else:
        coverage_path = "NEVER_PROGRESSED"

    # Simulate Policy A (Exit 3 Only) and Policy B (Exit 3 + Exit 4)
    trade_a = _simulate_exit_for_policy_corrected(
        policy_name="POLICY_A_EXIT3_ONLY",
        use_exit4=False,
        ticker=ticker,
        name=name,
        market=market,
        entry_sig_d=combined_first_w,
        entry_exec_d=entry_exec_date,
        entry_open=entry_open_price,
        pa_stage_at_entry=pa_stage_at_entry,
        fast_score=fast_score,
        fast_score_avail=fast_score_avail,
        daily_risk=daily_risk,
        monthly_regime=monthly_regime,
        first_early_trend_d=first_early_trend_d,
        early_trend_to_prog_d=early_trend_to_prog_d,
        first_prog_score=first_prog_score,
        coverage_path=coverage_path,
        monthly_snapshots=monthly_snapshots,
        daily=daily,
        cutoff_date=cutoff_date,
        warning_count=warning_count,
    )

    trade_b = _simulate_exit_for_policy_corrected(
        policy_name="POLICY_B_COMBINED_EXIT3_EXIT4",
        use_exit4=True,
        ticker=ticker,
        name=name,
        market=market,
        entry_sig_d=combined_first_w,
        entry_exec_d=entry_exec_date,
        entry_open=entry_open_price,
        pa_stage_at_entry=pa_stage_at_entry,
        fast_score=fast_score,
        fast_score_avail=fast_score_avail,
        daily_risk=daily_risk,
        monthly_regime=monthly_regime,
        first_early_trend_d=first_early_trend_d,
        early_trend_to_prog_d=early_trend_to_prog_d,
        first_prog_score=first_prog_score,
        coverage_path=coverage_path,
        monthly_snapshots=monthly_snapshots,
        daily=daily,
        cutoff_date=cutoff_date,
        warning_count=warning_count,
    )

    return diag, trade_a, trade_b


def _simulate_exit_for_policy_corrected(
    policy_name: str,
    use_exit4: bool,
    ticker: str,
    name: str,
    market: str,
    entry_sig_d: pd.Timestamp,
    entry_exec_d: pd.Timestamp,
    entry_open: float,
    pa_stage_at_entry: str,
    fast_score: float | None,
    fast_score_avail: str,
    daily_risk: str,
    monthly_regime: str,
    first_early_trend_d: pd.Timestamp | None,
    early_trend_to_prog_d: pd.Timestamp | None,
    first_prog_score: float | None,
    coverage_path: str,
    monthly_snapshots: list[dict[str, Any]],
    daily: pd.DataFrame,
    cutoff_date: pd.Timestamp,
    warning_count: int,
) -> TradeRecord:
    exit_sig_d: pd.Timestamp | None = None
    exit_reason: str | None = None
    prog_hwm: float | None = None
    max_drawdown: float | None = None

    if early_trend_to_prog_d is not None and coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
        in_progressed_zone = False
        for row in monthly_snapshots:
            m = row["date"]
            st = row["stage"]
            sc = row["score"]

            if m < early_trend_to_prog_d:
                continue

            if m == early_trend_to_prog_d:
                in_progressed_zone = True
                prog_hwm = sc if sc is not None else 0.0
                max_drawdown = 0.0
                continue

            if in_progressed_zone:
                if st == "PROGRESSED":
                    if sc is not None:
                        if prog_hwm is not None:
                            prog_hwm = max(prog_hwm, sc)
                            dd = prog_hwm - sc
                            max_drawdown = max(max_drawdown or 0.0, dd)
                            if use_exit4 and dd >= 15.0:
                                exit_sig_d = m
                                exit_reason = "EXIT4_SCORE_DRAWDOWN_GE_15"
                                break
                        else:
                            prog_hwm = sc
                elif st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
                    exit_sig_d = m
                    exit_reason = f"EXIT3_PROGRESSED_TO_{st}"
                    in_progressed_zone = False
                    break
    else:
        if coverage_path == "SKIPPED_EARLY_TREND_HANDOFF":
            exit_reason = "SKIPPED_EARLY_TREND_HANDOFF"
        else:
            exit_reason = "NO_PROGRESSED_BEFORE_CUTOFF"

    # Execution & Corrected MFE/MAE Calculation
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
        # Major Fix 3: Daily slice strictly before exit execution day + exit_open
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index < exit_exec_d)]
        holding_days = len(daily[(daily.index >= entry_exec_d) & (daily.index <= exit_exec_d)])
        holding_weeks = round(holding_days / 5.0, 1)

        if not holding_daily.empty:
            high_cand = holding_daily["high"].tolist() + [exit_open]
            low_cand = holding_daily["low"].tolist() + [exit_open]
            peak_price = float(max(high_cand))
            min_price = float(min(low_cand))
            if peak_price == exit_open:
                peak_d = exit_exec_d.strftime("%Y-%m-%d")
            else:
                peak_d = holding_daily["high"].idxmax().strftime("%Y-%m-%d")
        else:
            peak_price = float(max(entry_open, exit_open))
            min_price = float(min(entry_open, exit_open))
            peak_d = exit_exec_d.strftime("%Y-%m-%d")

        mfe_pct = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae_pct = round(((min_price - entry_open) / entry_open) * 100, 2)
        peak_giveback = round(mfe_pct - realized_ret, 2)
        profit_capture = round(realized_ret / mfe_pct, 4) if mfe_pct > 0 else None
        terminal_ret = realized_ret
    else:
        # OPEN_AT_CUTOFF
        holding_daily = daily[(daily.index >= entry_exec_d) & (daily.index <= cutoff_date)]
        holding_days = len(holding_daily)
        holding_weeks = round(holding_days / 5.0, 1)

        cutoff_close = float(holding_daily.iloc[-1]["close"]) if not holding_daily.empty else entry_open
        mark_to_cutoff_ret = round(((cutoff_close - entry_open) / entry_open) * 100, 2)

        peak_price = float(holding_daily["high"].max()) if not holding_daily.empty else entry_open
        min_price = float(holding_daily["low"].min()) if not holding_daily.empty else entry_open
        peak_d = holding_daily["high"].idxmax().strftime("%Y-%m-%d") if not holding_daily.empty else entry_exec_d.strftime("%Y-%m-%d")

        mfe_pct = round(((peak_price - entry_open) / entry_open) * 100, 2)
        mae_pct = round(((min_price - entry_open) / entry_open) * 100, 2)
        peak_giveback = None
        profit_capture = None
        terminal_ret = mark_to_cutoff_ret

    terminal_mfe = mfe_pct
    terminal_mae = mae_pct
    terminal_giveback = round(terminal_mfe - terminal_ret, 2)
    terminal_profit_capture = round(terminal_ret / terminal_mfe, 4) if terminal_mfe > 0 else None

    return TradeRecord(
        ticker=ticker,
        name=name,
        market=market,
        entry_signal_date=entry_sig_d.strftime("%Y-%m-%d"),
        entry_execution_date=entry_exec_d.strftime("%Y-%m-%d"),
        entry_open_price=round(entry_open, 2),
        pattern_a_stage_at_entry=pa_stage_at_entry,
        fast_stage_at_entry="TRIGGER",
        fast_monthly_regime_at_entry=monthly_regime,
        daily_risk_at_entry=daily_risk,
        fast_score=round(fast_score, 2) if fast_score is not None else None,
        fast_score_availability=fast_score_avail,
        first_early_trend_date=first_early_trend_d.strftime("%Y-%m-%d") if first_early_trend_d else None,
        early_trend_to_progressed_date=early_trend_to_prog_d.strftime("%Y-%m-%d") if early_trend_to_prog_d else None,
        first_progressed_score=round(first_prog_score, 2) if first_prog_score is not None else None,
        progressed_score_hwm=round(prog_hwm, 2) if prog_hwm is not None else None,
        max_progressed_score_drawdown=round(max_drawdown, 2) if max_drawdown is not None else None,
        exit_policy=policy_name,
        exit_reason=exit_reason,
        exit_signal_date=exit_sig_d.strftime("%Y-%m-%d") if exit_sig_d else None,
        exit_execution_date=exit_exec_d.strftime("%Y-%m-%d") if exit_exec_d else None,
        exit_open_price=round(exit_open, 2) if exit_open is not None else None,
        trade_status=trade_status,
        realized_return_pct=realized_ret,
        mark_to_cutoff_return_pct=mark_to_cutoff_ret,
        terminal_return_pct=terminal_ret,
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        terminal_mfe_pct=terminal_mfe,
        terminal_mae_pct=terminal_mae,
        peak_price_after_entry=round(peak_price, 2),
        peak_date=peak_d,
        peak_giveback_pct=peak_giveback,
        terminal_peak_giveback_pct=terminal_giveback,
        profit_capture_ratio=profit_capture,
        terminal_profit_capture_ratio=terminal_profit_capture,
        holding_days=holding_days,
        holding_weeks=holding_weeks,
        coverage_path=coverage_path,
        entry_executable=True,
        entry_non_executable_reason=None,
        evaluation_warning_count=warning_count,
    )


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
