"""Pattern A FAST Core V02 Re-Entry Strategy Simulation Module.

Core Innovation:
  - Replaces FIRST_QUALIFYING_ENTRY_PER_TICKER with MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER.
  - Allows full re-entry after previous position exits (Loss Guard, Exit 3, Exit 4, Coverage Exit 4).
  - Strictly no overlapping positions / no pyramiding.
  - Full state reset on re-entry (HWM, Loss Guard window, Stage, Entry Open).

Strategy Mandate:
  - Primary: LARGE_LOSS_MINIMIZATION
  - Secondary: PRESERVE_SUFFICIENT_UPSIDE
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
class V02TradeRecord:
    ticker: str
    name: str
    market: str
    trade_id: str
    trade_sequence: int

    entry_signal_date: str
    entry_execution_date: str
    entry_open: float

    entry_pattern_a_stage: str
    fast_stage: str
    monthly_regime: str
    daily_risk: str
    fast_score: float | None
    fast_score_state: str

    previous_exit_type: str | None
    previous_exit_execution_date: str | None

    loss_guard_triggered: bool
    loss_guard_signal_date: str | None
    loss_guard_execution_date: str | None
    loss_guard_execution_price: float | None

    first_progressed_date: str | None
    first_progressed_effective_trading_date: str | None

    lifecycle_class: str

    exit_type: str
    exit_signal_date: str | None
    exit_execution_date: str | None
    exit_price: float | None

    terminal_return: float
    mfe: float
    mae: float
    peak_giveback: float
    profit_capture: float | None
    holding_weeks: float
    trade_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def simulate_ticker_core_v02_reentry(
    ticker: str,
    name: str,
    market: str,
    daily: pd.DataFrame | None,
    score_contract: dict,
    stage_contract: dict,
    cutoff_date: pd.Timestamp = DATA_CUTOFF,
) -> list[V02TradeRecord]:
    if daily is None or daily.empty:
        return []

    daily = daily.sort_index()
    daily = daily[daily.index <= cutoff_date]

    required_cols = {"open", "high", "low", "close"}
    if not required_cols.issubset(daily.columns) or len(daily) < 60:
        return []

    weekly_bars = to_weekly(daily)
    valid_weeks = [
        w for w in weekly_bars.index
        if daily[daily.index <= w].index.max().normalize() == w.normalize()
    ]

    if not valid_weeks:
        return []

    monthly_bars = to_monthly(daily)

    trades: list[V02TradeRecord] = []
    trade_seq = 0
    cur_search_date: pd.Timestamp | None = valid_weeks[0]
    prev_exit_type: str | None = None
    prev_exit_exec_date: str | None = None

    while cur_search_date is not None and cur_search_date <= cutoff_date:
        # Find next qualifying entry weekly signal on or after cur_search_date
        found_signal_w: pd.Timestamp | None = None
        found_signal_res: dict | None = None

        candidate_weeks = [w for w in valid_weeks if w >= cur_search_date]
        for w in candidate_weeks:
            try:
                res = evaluate_pattern_a_fast(ticker, name, daily[daily.index <= w], w, score_contract, stage_contract)
                is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
                is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
                is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
                is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})
                is_fast = bool(is_trigger and is_permitted and is_non_extreme and is_score_ok)

                raw_stage = res.get("pattern_a_stage")
                pa_stage = str(raw_stage).upper() if (raw_stage is not None and not pd.isna(raw_stage)) else "UNAVAILABLE"

                if is_fast and pa_stage in {"TRANSITION", "EARLY_TREND"}:
                    found_signal_w = w
                    found_signal_res = res
                    break
            except Exception:
                continue

        if found_signal_w is None or found_signal_res is None:
            break

        # Check execution date
        fut_daily = daily[(daily.index > found_signal_w) & (daily.index <= cutoff_date)]
        if fut_daily.empty:
            break

        entry_exec_date = fut_daily.index[0]
        entry_open_price = float(fut_daily.iloc[0]["open"])

        trade_seq += 1
        trade_id = f"{ticker}_{trade_seq:02d}"

        pa_stage_at_entry = (found_signal_res["pattern_a_stage"] or "").upper()
        fast_score = found_signal_res.get("fast_score")
        fast_score_avail = found_signal_res.get("fast_score_status", "UNKNOWN")
        daily_risk = found_signal_res.get("fast_daily_risk_state", "UNKNOWN")
        monthly_regime = found_signal_res.get("fast_monthly_permission_state", "UNKNOWN")

        # Monthly snapshots strictly for this trade lifecycle (from found_signal_w to cutoff_date)
        m_dates = [
            m for m in monthly_bars.index
            if m >= found_signal_w and m <= cutoff_date
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

        first_early_trend_d: pd.Timestamp | None = found_signal_w if pa_stage_at_entry == "EARLY_TREND" else None
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
        first_prog_eff_trading_d: pd.Timestamp | None = None
        if first_progressed_d is not None:
            month_daily = daily[daily.index <= first_progressed_d]
            if not month_daily.empty:
                first_prog_eff_trading_d = month_daily.index.max()
            pre_prog_daily = daily[(daily.index >= entry_exec_date) & (daily.index < first_prog_eff_trading_d)]
        else:
            pre_prog_daily = daily[(daily.index >= entry_exec_date) & (daily.index <= cutoff_date)]

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

        # Simulate PROGRESSED Exits (E2: Exit 3 + Exit 4 + Coverage)
        e2_sig_d: pd.Timestamp | None = None
        e2_exit_type: str | None = None

        if coverage_path == "NORMAL_EARLY_TREND_HANDOFF":
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
                                e2_sig_d = m
                                e2_exit_type = "EXIT4_SCORE_DRAWDOWN_GE_15"
                                break
                    elif st in {"WEAK", "BASE", "TRANSITION", "EARLY_TREND"}:
                        e2_sig_d = m
                        e2_exit_type = f"EXIT3_PROGRESSED_TO_{st}"
                        break
            if e2_sig_d is None:
                e2_exit_type = "NO_EXIT_BEFORE_CUTOFF"

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

        # Final trade outcome determination (HOLD_B + E2)
        if loss_guard_triggered and loss_guard_sig_d is not None:
            final_sig_d = loss_guard_sig_d
            final_exit_type = "LOSS_GUARD_CLOSE_LE_NEG_15"
        else:
            final_sig_d = e2_sig_d
            final_exit_type = e2_exit_type or "NO_EXIT"

        res_outcome = _calc_trade_outcome(entry_exec_date, entry_open_price, final_sig_d, daily, cutoff_date)

        record = V02TradeRecord(
            ticker=ticker,
            name=name,
            market=market,
            trade_id=trade_id,
            trade_sequence=trade_seq,
            entry_signal_date=found_signal_w.strftime("%Y-%m-%d"),
            entry_execution_date=entry_exec_date.strftime("%Y-%m-%d"),
            entry_open=round(entry_open_price, 2),
            entry_pattern_a_stage=pa_stage_at_entry,
            fast_stage="TRIGGER",
            monthly_regime=monthly_regime,
            daily_risk=daily_risk,
            fast_score=round(fast_score, 2) if fast_score is not None else None,
            fast_score_state=fast_score_avail,
            previous_exit_type=prev_exit_type,
            previous_exit_execution_date=prev_exit_exec_date,
            loss_guard_triggered=loss_guard_triggered,
            loss_guard_signal_date=loss_guard_sig_d.strftime("%Y-%m-%d") if loss_guard_sig_d else None,
            loss_guard_execution_date=loss_guard_exec_d.strftime("%Y-%m-%d") if loss_guard_exec_d else None,
            loss_guard_execution_price=round(loss_guard_exec_price, 2) if loss_guard_exec_price is not None else None,
            first_progressed_date=first_progressed_d.strftime("%Y-%m-%d") if first_progressed_d else None,
            first_progressed_effective_trading_date=first_prog_eff_trading_d.strftime("%Y-%m-%d") if first_prog_eff_trading_d else None,
            lifecycle_class=coverage_path,
            exit_type=final_exit_type,
            exit_signal_date=final_sig_d.strftime("%Y-%m-%d") if final_sig_d else None,
            exit_execution_date=res_outcome["exit_exec_d"].strftime("%Y-%m-%d") if res_outcome["exit_exec_d"] else None,
            exit_price=round(res_outcome["exit_open"], 2) if res_outcome["exit_open"] is not None else None,
            terminal_return=res_outcome["terminal_ret"],
            mfe=res_outcome["mfe"],
            mae=res_outcome["mae"],
            peak_giveback=res_outcome["terminal_giveback"],
            profit_capture=res_outcome["terminal_profit_capture"],
            holding_weeks=res_outcome["holding_weeks"],
            trade_status=res_outcome["trade_status"],
        )
        trades.append(record)

        # Update state for next search
        prev_exit_type = final_exit_type
        if res_outcome["trade_status"] == "REALIZED" and res_outcome["exit_exec_d"] is not None:
            prev_exit_exec_date = res_outcome["exit_exec_d"].strftime("%Y-%m-%d")
            # Next trade signal must complete on or after exit execution date
            cur_search_date = res_outcome["exit_exec_d"]
        else:
            # Position remained OPEN_AT_CUTOFF
            cur_search_date = None
            break

    return trades


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
        "positive_rate": round(pos_rate, 2),
    }
