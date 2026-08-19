"""FAST Entry + Pattern A Exit / Handoff Policy v0.1 Evaluation Module.

Evaluates:
  Entry:
    FAST v0.1: TRIGGER + READY + PERMITTED_REGIME + NORMAL/ELEVATED risk + READY/PARTIAL score
    AND Pattern A Stage at Entry IN {"TRANSITION", "EARLY_TREND"}
  Handoff & Exit:
    - Policy A (Exit 3 Only): After EARLY_TREND -> PROGRESSED, hold through PROGRESSED.
      Exit on first PROGRESSED -> OTHER_VALID_STAGE (WEAK, BASE, TRANSITION, EARLY_TREND).
    - Policy B (Exit 3 + Exit 4): After EARLY_TREND -> PROGRESSED, hold through PROGRESSED.
      Exit on FIRST(Exit 3, Exit 4: PROGRESSED_SCORE_HWM - current_score >= 15.0).
    - Coverage Hole: TRANSITION -> PROGRESSED without EARLY_TREND (SKIPPED_EARLY_TREND_HANDOFF).

Strict Rules:
  - Local cache only (zero external network requests).
  - Point-in-time (PIT) evaluation only.
  - Next local trading day OPEN execution.
  - Research evaluation only (PRODUCTION_HOLD, no production impact).
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
    mfe_pct: float | None
    mae_pct: float | None
    peak_price_after_entry: float | None
    peak_date: str | None
    peak_giveback_pct: float | None
    profit_capture_ratio: float | None
    holding_days: int | None
    holding_weeks: float | None
    coverage_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TickerEntryDiagnostic:
    ticker: str
    name: str
    market: str
    fast_v01_qualified: bool
    fast_v01_first_entry_date: str | None
    fast_v01_pa_stage: str | None
    combined_qualified: bool
    combined_first_entry_date: str | None
    combined_pa_stage: str | None
    gate_rejection_reason: str | None
    entry_delay_days: int | None


def simulate_ticker_combined_policy(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame,
    score_contract: dict,
    stage_contract: dict,
    cutoff_date: pd.Timestamp = DATA_CUTOFF,
) -> tuple[TickerEntryDiagnostic, TradeRecord | None, TradeRecord | None]:
    """Simulate FAST + Pattern A Combined Policy on a single ticker.

    Returns:
      (diagnostic, trade_policy_a, trade_policy_b)
    """
    daily = daily.sort_index()
    daily = daily[daily.index <= cutoff_date]
    if daily.empty or len(daily) < 60:
        diag = TickerEntryDiagnostic(
            ticker=ticker,
            name=name,
            market=market,
            fast_v01_qualified=False,
            fast_v01_first_entry_date=None,
            fast_v01_pa_stage=None,
            combined_qualified=False,
            combined_first_entry_date=None,
            combined_pa_stage=None,
            gate_rejection_reason="INSUFFICIENT_HISTORY",
            entry_delay_days=None,
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

    for w in valid_weeks:
        try:
            res = evaluate_pattern_a_fast(ticker, name, daily[daily.index <= w], w, score_contract, stage_contract)
            is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
            is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
            is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
            is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})
            is_fast = bool(is_trigger and is_permitted and is_non_extreme and is_score_ok)
            pa_stage = (res["pattern_a_stage"] or "").upper()

            if is_fast and fast_first_w is None:
                fast_first_w = w
                fast_first_pa_stage = pa_stage

            if is_fast and pa_stage in {"TRANSITION", "EARLY_TREND"} and combined_first_w is None:
                combined_first_w = w
                combined_first_res = res
                break
        except Exception:
            pass

    gate_rejection = None
    delay_days = None
    if fast_first_w is not None:
        if combined_first_w is not None:
            delay_days = (combined_first_w - fast_first_w).days
        else:
            gate_rejection = f"PATTERN_A_{fast_first_pa_stage}" if fast_first_pa_stage else "PATTERN_A_UNKNOWN"

    diag = TickerEntryDiagnostic(
        ticker=ticker,
        name=name,
        market=market,
        fast_v01_qualified=fast_first_w is not None,
        fast_v01_first_entry_date=fast_first_w.strftime("%Y-%m-%d") if fast_first_w else None,
        fast_v01_pa_stage=fast_first_pa_stage,
        combined_qualified=combined_first_w is not None,
        combined_first_entry_date=combined_first_w.strftime("%Y-%m-%d") if combined_first_w else None,
        combined_pa_stage=(combined_first_res["pattern_a_stage"] or "").upper() if combined_first_res else None,
        gate_rejection_reason=gate_rejection,
        entry_delay_days=delay_days,
    )

    if combined_first_w is None or combined_first_res is None:
        return diag, None, None

    # Check execution feasibility
    fut_daily = daily[(daily.index > combined_first_w) & (daily.index <= cutoff_date)]
    if fut_daily.empty:
        return diag, None, None

    entry_exec_date = fut_daily.index[0]
    entry_open_price = float(fut_daily.iloc[0]["open"])
    pa_stage_at_entry = (combined_first_res["pattern_a_stage"] or "").upper()
    fast_score = combined_first_res.get("fast_score")
    fast_score_avail = combined_first_res.get("fast_score_status", "UNKNOWN")
    daily_risk = combined_first_res.get("fast_daily_risk_state", "UNKNOWN")
    monthly_regime = combined_first_res.get("fast_monthly_permission_state", "UNKNOWN")

    # Trace monthly PIT Pattern A lifecycle after entry
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
        except Exception:
            monthly_snapshots.append({"date": m, "stage": "UNAVAILABLE", "score": None})

    # Trace handoff events
    first_early_trend_d: pd.Timestamp | None = None
    early_trend_to_prog_d: pd.Timestamp | None = None
    first_prog_score: float | None = None

    if pa_stage_at_entry == "EARLY_TREND":
        first_early_trend_d = combined_first_w
        coverage_path = "ENTRY_AT_EARLY_TREND"
    else:
        coverage_path = "ENTRY_AT_TRANSITION"

    for row in monthly_snapshots:
        m = row["date"]
        st = row["stage"]
        sc = row["score"]

        if st == "EARLY_TREND" and first_early_trend_d is None:
            first_early_trend_d = m

        if st == "PROGRESSED":
            if first_early_trend_d is not None and early_trend_to_prog_d is None:
                early_trend_to_prog_d = m
                first_prog_score = sc
            elif first_early_trend_d is None:
                # Direct transition without early trend
                coverage_path = "SKIPPED_EARLY_TREND_HANDOFF"

    if early_trend_to_prog_d is not None and coverage_path != "SKIPPED_EARLY_TREND_HANDOFF":
        coverage_path = "NORMAL_EARLY_TREND_HANDOFF"
    elif coverage_path != "SKIPPED_EARLY_TREND_HANDOFF":
        coverage_path = "NEVER_PROGRESSED"

    # Simulate Policy A (Exit 3 Only) and Policy B (Exit 3 + Exit 4)
    trade_a = _simulate_exit_for_policy(
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
    )

    trade_b = _simulate_exit_for_policy(
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
    )

    return diag, trade_a, trade_b


def _simulate_exit_for_policy(
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
) -> TradeRecord:
    exit_sig_d: pd.Timestamp | None = None
    exit_reason: str | None = None
    prog_hwm: float | None = None
    max_drawdown: float | None = None

    if early_trend_to_prog_d is not None and coverage_path != "SKIPPED_EARLY_TREND_HANDOFF":
        # Exit 3 & Exit 4 lifecycle activated
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
                    # Exit 3 trigger
                    exit_sig_d = m
                    exit_reason = f"EXIT3_PROGRESSED_TO_{st}"
                    in_progressed_zone = False
                    break
    else:
        if coverage_path == "SKIPPED_EARLY_TREND_HANDOFF":
            exit_reason = "SKIPPED_EARLY_TREND_HANDOFF"
        else:
            exit_reason = "NO_PROGRESSED_BEFORE_CUTOFF"

    # Execution and Return Metrics Calculation
    exit_exec_d: pd.Timestamp | None = None
    exit_open: float | None = None
    trade_status: str = "OPEN_AT_CUTOFF"
    realized_ret: float | None = None
    mark_to_cutoff_ret: float | None = None
    mfe_pct: float | None = None
    mae_pct: float | None = None
    peak_price: float | None = None
    peak_d: str | None = None
    peak_giveback: float | None = None
    profit_capture: float | None = None
    holding_days: int | None = None
    holding_weeks: float | None = None

    if exit_sig_d is not None:
        fut_after_exit = daily[(daily.index > exit_sig_d) & (daily.index <= cutoff_date)]
        if not fut_after_exit.empty:
            exit_exec_d = fut_after_exit.index[0]
            exit_open = float(fut_after_exit.iloc[0]["open"])
            trade_status = "REALIZED"
            realized_ret = round(((exit_open - entry_open) / entry_open) * 100, 2)

            # Horizon daily slice
            per_daily = daily[(daily.index >= entry_exec_d) & (daily.index <= exit_exec_d)]
            holding_days = len(per_daily)
            holding_weeks = round(holding_days / 5.0, 1)

            peak_price = float(per_daily["high"].max())
            peak_d = per_daily["high"].idxmax().strftime("%Y-%m-%d")
            mfe_pct = round(((peak_price - entry_open) / entry_open) * 100, 2)
            min_price = float(per_daily["low"].min())
            mae_pct = round(((min_price - entry_open) / entry_open) * 100, 2)

            peak_giveback = round(mfe_pct - realized_ret, 2)
            profit_capture = round(realized_ret / mfe_pct, 4) if mfe_pct > 0 else None
        else:
            # Signal on or right before cutoff, execution beyond cutoff -> Open at cutoff
            trade_status = "OPEN_AT_CUTOFF"

    if trade_status == "OPEN_AT_CUTOFF":
        per_daily = daily[(daily.index >= entry_exec_d) & (daily.index <= cutoff_date)]
        if not per_daily.empty:
            holding_days = len(per_daily)
            holding_weeks = round(holding_days / 5.0, 1)
            cutoff_close = float(per_daily.iloc[-1]["close"])
            mark_to_cutoff_ret = round(((cutoff_close - entry_open) / entry_open) * 100, 2)

            peak_price = float(per_daily["high"].max())
            peak_d = per_daily["high"].idxmax().strftime("%Y-%m-%d")
            mfe_pct = round(((peak_price - entry_open) / entry_open) * 100, 2)
            min_price = float(per_daily["low"].min())
            mae_pct = round(((min_price - entry_open) / entry_open) * 100, 2)

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
        mfe_pct=mfe_pct,
        mae_pct=mae_pct,
        peak_price_after_entry=round(peak_price, 2) if peak_price is not None else None,
        peak_date=peak_d,
        peak_giveback_pct=peak_giveback,
        profit_capture_ratio=profit_capture,
        holding_days=holding_days,
        holding_weeks=holding_weeks,
        coverage_path=coverage_path,
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
