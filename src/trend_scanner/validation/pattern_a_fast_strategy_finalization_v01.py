"""Pattern A FAST Strategy Finalization / Candidate Selection v0.1 Simulation Module.

Simulates:
  Step 1: HOLD_A (No Pre-PROGRESSED Protection) vs HOLD_B (Pre-PROGRESSED Catastrophic Loss Guard at -15% Daily Close)
  Step 2: E0 (Exit 3 Only) vs E1 (Exit 3 + Normal Exit 4 15pt) vs E2 (Exit 3 + Exit 4 + Coverage 15pt)

Across all 553 Primary Executable Combined v0.1 Entries (TRANSITION + EARLY_TREND).
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
class FinalizationTradeRecord:
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

    # Hold B diagnostic
    loss_guard_triggered: bool
    loss_guard_signal_date: str | None
    loss_guard_exec_date: str | None
    loss_guard_exec_price: float | None

    # Combination outcomes:
    # 1. HOLD_A + E0
    hold_a_e0_exit_type: str
    hold_a_e0_terminal_return: float
    hold_a_e0_mfe: float
    hold_a_e0_mae: float
    hold_a_e0_peak_giveback: float
    hold_a_e0_profit_capture: float | None
    hold_a_e0_holding_weeks: float

    # 2. HOLD_A + E1 (Baseline Frozen v0.3 Primary Policy)
    hold_a_e1_exit_type: str
    hold_a_e1_terminal_return: float
    hold_a_e1_mfe: float
    hold_a_e1_mae: float
    hold_a_e1_peak_giveback: float
    hold_a_e1_profit_capture: float | None
    hold_a_e1_holding_weeks: float

    # 3. HOLD_A + E2 (Coverage Activated Policy)
    hold_a_e2_exit_type: str
    hold_a_e2_terminal_return: float
    hold_a_e2_mfe: float
    hold_a_e2_mae: float
    hold_a_e2_peak_giveback: float
    hold_a_e2_profit_capture: float | None
    hold_a_e2_holding_weeks: float

    # 4. HOLD_B + E0
    hold_b_e0_exit_type: str
    hold_b_e0_terminal_return: float
    hold_b_e0_mfe: float
    hold_b_e0_mae: float
    hold_b_e0_peak_giveback: float
    hold_b_e0_profit_capture: float | None
    hold_b_e0_holding_weeks: float

    # 5. HOLD_B + E1
    hold_b_e1_exit_type: str
    hold_b_e1_terminal_return: float
    hold_b_e1_mfe: float
    hold_b_e1_mae: float
    hold_b_e1_peak_giveback: float
    hold_b_e1_profit_capture: float | None
    hold_b_e1_holding_weeks: float

    # 6. HOLD_B + E2
    hold_b_e2_exit_type: str
    hold_b_e2_terminal_return: float
    hold_b_e2_mfe: float
    hold_b_e2_mae: float
    hold_b_e2_peak_giveback: float
    hold_b_e2_profit_capture: float | None
    hold_b_e2_holding_weeks: float

    # Forward Horizon returns (Matured on entry price)
    return_4w: float | None
    return_8w: float | None
    return_12w: float | None
    return_26w: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_ticker_strategy_finalization(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    cutoff_date: pd.Timestamp = DATA_CUTOFF,
) -> FinalizationTradeRecord | None:
    if daily is None or daily.empty:
        return None

    daily = daily.sort_index()
    daily = daily[daily.index <= cutoff_date]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns) or len(daily) < 60:
        return None

    weekly_bars = to_weekly(daily)
    valid_weeks = [
        w for w in weekly_bars.index
        if daily[daily.index <= w].index.max().normalize() == w.normalize()
    ]

    fast_first_w: pd.Timestamp | None = None
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

            raw_stage = res.get("pattern_a_stage")
            pa_stage = str(raw_stage).upper() if (raw_stage is not None and not pd.isna(raw_stage)) else "UNAVAILABLE"

            if is_fast and fast_first_w is None:
                fast_first_w = w

            if is_fast and pa_stage in {"TRANSITION", "EARLY_TREND"} and combined_first_w is None:
                combined_first_w = w
                combined_first_res = res
                break
        except Exception:
            continue

    if combined_first_w is None or combined_first_res is None:
        return None

    fut_daily = daily[(daily.index > combined_first_w) & (daily.index <= cutoff_date)]
    if fut_daily.empty:
        return None

    entry_exec_date = fut_daily.index[0]
    entry_open_price = float(fut_daily.iloc[0]["open"])

    pa_stage_at_entry = (combined_first_res["pattern_a_stage"] or "").upper()
    fast_score = combined_first_res.get("fast_score")
    fast_score_avail = combined_first_res.get("fast_score_status", "UNKNOWN")
    daily_risk = combined_first_res.get("fast_daily_risk_state", "UNKNOWN")
    monthly_regime = combined_first_res.get("fast_monthly_permission_state", "UNKNOWN")

    # Monthly snapshots
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
    elif skipped_handoff:
        coverage_path = "SKIPPED_EARLY_TREND_HANDOFF"
    elif progressed_observed:
        coverage_path = "PROGRESSED_WITHOUT_DIRECT_HANDOFF"
    else:
        coverage_path = "NEVER_PROGRESSED"

    # Pre-PROGRESSED Loss Guard Check (HOLD_B)
    # The pre-progressed window is from entry_exec_date up to first_progressed_d (or cutoff if never progressed)
    pre_prog_cutoff = first_progressed_d if first_progressed_d is not None else cutoff_date
    pre_prog_daily = daily[(daily.index >= entry_exec_date) & (daily.index <= pre_prog_cutoff)]

    loss_guard_triggered = False
    loss_guard_sig_d: pd.Timestamp | None = None
    loss_guard_exec_d: pd.Timestamp | None = None
    loss_guard_exec_price: float | None = None

    for d, row in pre_prog_daily.iterrows():
        c_price = float(row["close"])
        if (c_price / entry_open_price - 1.0) <= -0.15:
            loss_guard_triggered = True
            loss_guard_sig_d = d
            fut_after_stop = daily[(daily.index > d) & (daily.index <= cutoff_date)]
            if not fut_after_stop.empty:
                loss_guard_exec_d = fut_after_stop.index[0]
                loss_guard_exec_price = float(fut_after_stop.iloc[0]["open"])
            break

    # -------------------------------------------------------------
    # Simulate PROGRESSED Exits: E0, E1, E2
    # -------------------------------------------------------------
    # E0: Exit 3 only
    e0_sig_d: pd.Timestamp | None = None
    e0_exit_type: str | None = None
    if early_trend_to_prog_d is not None and coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
        in_p = False
        for row in monthly_snapshots:
            m = row["date"]
            st = row["stage"]
            if m < early_trend_to_prog_d:
                continue
            if m == early_trend_to_prog_d:
                in_p = True
                continue
            if in_p and st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
                e0_sig_d = m
                e0_exit_type = f"EXIT3_PROGRESSED_TO_{st}"
                break
        if e0_sig_d is None:
            e0_exit_type = "NO_EXIT_BEFORE_CUTOFF"
    else:
        e0_exit_type = "NO_PROGRESSED_DIRECT_HANDOFF"

    # E1: Exit 3 + Normal Exit 4 (Policy B)
    e1_sig_d: pd.Timestamp | None = None
    e1_exit_type: str | None = None
    if early_trend_to_prog_d is not None and coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
        in_p = False
        hwm_1 = None
        for row in monthly_snapshots:
            m = row["date"]
            st = row["stage"]
            sc = row["score"]
            if m < early_trend_to_prog_d:
                continue
            if m == early_trend_to_prog_d:
                in_p = True
                hwm_1 = sc if sc is not None else 0.0
                continue
            if in_p:
                if st == "PROGRESSED":
                    if sc is not None and hwm_1 is not None:
                        hwm_1 = max(hwm_1, sc)
                        if hwm_1 - sc >= 15.0:
                            e1_sig_d = m
                            e1_exit_type = "EXIT4_SCORE_DRAWDOWN_GE_15"
                            break
                elif st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
                    e1_sig_d = m
                    e1_exit_type = f"EXIT3_PROGRESSED_TO_{st}"
                    break
        if e1_sig_d is None:
            e1_exit_type = "NO_EXIT_BEFORE_CUTOFF"
    else:
        e1_exit_type = "NO_PROGRESSED_DIRECT_HANDOFF"

    # E2: Exit 3 + Exit 4 + Coverage (Policy C)
    e2_sig_d: pd.Timestamp | None = None
    e2_exit_type: str | None = None
    if coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
        e2_sig_d = e1_sig_d
        e2_exit_type = e1_exit_type
    elif coverage_path in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"}:
        if first_progressed_d is not None:
            hwm_2 = first_prog_score if first_prog_score is not None else 0.0
            in_p = True
            for row in monthly_snapshots:
                m = row["date"]
                st = row["stage"]
                sc = row["score"]
                if m <= first_progressed_d:
                    continue
                if in_p:
                    if st == "PROGRESSED":
                        if sc is not None:
                            hwm_2 = max(hwm_2, sc)
                            if hwm_2 - sc >= 15.0:
                                e2_sig_d = m
                                e2_exit_type = "EXIT4_SCORE_DRAWDOWN_GE_15"
                                break
                    else:
                        in_p = False
                        break
            if e2_sig_d is None:
                e2_exit_type = "NO_EXIT_BEFORE_CUTOFF"
        else:
            e2_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"
    else:
        e2_exit_type = "NO_PROGRESSED_BEFORE_CUTOFF"

    # Calculate outcomes for 6 combinations:
    # 1. HOLD_A + E0
    res_ha_e0 = _calc_trade_outcome(entry_exec_date, entry_open_price, e0_sig_d, daily, cutoff_date)
    # 2. HOLD_A + E1
    res_ha_e1 = _calc_trade_outcome(entry_exec_date, entry_open_price, e1_sig_d, daily, cutoff_date)
    # 3. HOLD_A + E2
    res_ha_e2 = _calc_trade_outcome(entry_exec_date, entry_open_price, e2_sig_d, daily, cutoff_date)

    # 4. HOLD_B + E0
    if loss_guard_triggered and loss_guard_sig_d is not None:
        res_hb_e0 = _calc_trade_outcome(entry_exec_date, entry_open_price, loss_guard_sig_d, daily, cutoff_date)
        hb_e0_type = "LOSS_GUARD_CLOSE_LE_NEG_15"
    else:
        res_hb_e0 = res_ha_e0
        hb_e0_type = e0_exit_type or "NO_EXIT"

    # 5. HOLD_B + E1
    if loss_guard_triggered and loss_guard_sig_d is not None:
        res_hb_e1 = _calc_trade_outcome(entry_exec_date, entry_open_price, loss_guard_sig_d, daily, cutoff_date)
        hb_e1_type = "LOSS_GUARD_CLOSE_LE_NEG_15"
    else:
        res_hb_e1 = res_ha_e1
        hb_e1_type = e1_exit_type or "NO_EXIT"

    # 6. HOLD_B + E2
    if loss_guard_triggered and loss_guard_sig_d is not None:
        res_hb_e2 = _calc_trade_outcome(entry_exec_date, entry_open_price, loss_guard_sig_d, daily, cutoff_date)
        hb_e2_type = "LOSS_GUARD_CLOSE_LE_NEG_15"
    else:
        res_hb_e2 = res_ha_e2
        hb_e2_type = e2_exit_type or "NO_EXIT"

    # Forward returns
    ret_4w = _calc_forward_return(entry_exec_date, entry_open_price, daily, 20, cutoff_date)
    ret_8w = _calc_forward_return(entry_exec_date, entry_open_price, daily, 40, cutoff_date)
    ret_12w = _calc_forward_return(entry_exec_date, entry_open_price, daily, 60, cutoff_date)
    ret_26w = _calc_forward_return(entry_exec_date, entry_open_price, daily, 130, cutoff_date)

    return FinalizationTradeRecord(
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
        loss_guard_triggered=loss_guard_triggered,
        loss_guard_signal_date=loss_guard_sig_d.strftime("%Y-%m-%d") if loss_guard_sig_d else None,
        loss_guard_exec_date=loss_guard_exec_d.strftime("%Y-%m-%d") if loss_guard_exec_d else None,
        loss_guard_exec_price=round(loss_guard_exec_price, 2) if loss_guard_exec_price is not None else None,
        hold_a_e0_exit_type=e0_exit_type or "NO_EXIT",
        hold_a_e0_terminal_return=res_ha_e0["terminal_ret"],
        hold_a_e0_mfe=res_ha_e0["mfe"],
        hold_a_e0_mae=res_ha_e0["mae"],
        hold_a_e0_peak_giveback=res_ha_e0["terminal_giveback"],
        hold_a_e0_profit_capture=res_ha_e0["terminal_profit_capture"],
        hold_a_e0_holding_weeks=res_ha_e0["holding_weeks"],
        hold_a_e1_exit_type=e1_exit_type or "NO_EXIT",
        hold_a_e1_terminal_return=res_ha_e1["terminal_ret"],
        hold_a_e1_mfe=res_ha_e1["mfe"],
        hold_a_e1_mae=res_ha_e1["mae"],
        hold_a_e1_peak_giveback=res_ha_e1["terminal_giveback"],
        hold_a_e1_profit_capture=res_ha_e1["terminal_profit_capture"],
        hold_a_e1_holding_weeks=res_ha_e1["holding_weeks"],
        hold_a_e2_exit_type=e2_exit_type or "NO_EXIT",
        hold_a_e2_terminal_return=res_ha_e2["terminal_ret"],
        hold_a_e2_mfe=res_ha_e2["mfe"],
        hold_a_e2_mae=res_ha_e2["mae"],
        hold_a_e2_peak_giveback=res_ha_e2["terminal_giveback"],
        hold_a_e2_profit_capture=res_ha_e2["terminal_profit_capture"],
        hold_a_e2_holding_weeks=res_ha_e2["holding_weeks"],
        hold_b_e0_exit_type=hb_e0_type,
        hold_b_e0_terminal_return=res_hb_e0["terminal_ret"],
        hold_b_e0_mfe=res_hb_e0["mfe"],
        hold_b_e0_mae=res_hb_e0["mae"],
        hold_b_e0_peak_giveback=res_hb_e0["terminal_giveback"],
        hold_b_e0_profit_capture=res_hb_e0["terminal_profit_capture"],
        hold_b_e0_holding_weeks=res_hb_e0["holding_weeks"],
        hold_b_e1_exit_type=hb_e1_type,
        hold_b_e1_terminal_return=res_hb_e1["terminal_ret"],
        hold_b_e1_mfe=res_hb_e1["mfe"],
        hold_b_e1_mae=res_hb_e1["mae"],
        hold_b_e1_peak_giveback=res_hb_e1["terminal_giveback"],
        hold_b_e1_profit_capture=res_hb_e1["terminal_profit_capture"],
        hold_b_e1_holding_weeks=res_hb_e1["holding_weeks"],
        hold_b_e2_exit_type=hb_e2_type,
        hold_b_e2_terminal_return=res_hb_e2["terminal_ret"],
        hold_b_e2_mfe=res_hb_e2["mfe"],
        hold_b_e2_mae=res_hb_e2["mae"],
        hold_b_e2_peak_giveback=res_hb_e2["terminal_giveback"],
        hold_b_e2_profit_capture=res_hb_e2["terminal_profit_capture"],
        hold_b_e2_holding_weeks=res_hb_e2["holding_weeks"],
        return_4w=ret_4w,
        return_8w=ret_8w,
        return_12w=ret_12w,
        return_26w=ret_26w,
    )


def _calc_forward_return(
    entry_exec_d: pd.Timestamp,
    entry_open: float,
    daily: pd.DataFrame,
    horizon_days: int,
    cutoff_date: pd.Timestamp,
) -> float | None:
    fut = daily[(daily.index >= entry_exec_d) & (daily.index <= cutoff_date)]
    if len(fut) >= horizon_days:
        target_close = float(fut.iloc[horizon_days - 1]["close"])
        return round(((target_close - entry_open) / entry_open) * 100, 2)
    return None


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
            "p90": None,
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
        "p90": round(float(np.percentile(usable, 90)), 2),
        "std": round(float(usable.std()), 2) if len(usable) > 1 else 0.0,
        "min": round(float(usable.min()), 2),
        "max": round(float(usable.max()), 2),
        "positive_rate": round(pos_rate, 1),
    }
