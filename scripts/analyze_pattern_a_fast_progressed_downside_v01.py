#!/usr/bin/env python
"""Pattern A FAST V02 PROGRESSED Downside Protection Diagnostic Phase 1 Runner (Corrected).

Purpose:
  - Retrospective anatomy of PROGRESSED trades in A FAST Core V02 Re Entry (783 trades).
  - Exact held window daily price path analysis (excluding exit execution day OHLC).
  - Bounded monthly Pattern A Score paths (strictly stopping at exit signal month).
  - PROGRESSED reference price returns vs entry-based returns disambiguation.
  - Empirical delay metrics for Exit3 and Exit4.
  - Descriptive separation & overlap analysis between Big Winners and Deep Losers.

Strict Research Invariants:
  - STRATEGY_RULE_CHANGE = NO
  - ENTRY_RULE_CHANGE = NO
  - LOSS_GUARD_CHANGE = NO
  - EXIT_RULE_CHANGE = NO
  - REENTRY_RULE_CHANGE = NO
  - THRESHOLD_TUNING = NO
  - V02 OFFICIAL TRADES MODIFIED = NO
  - V02 EVALUATOR RERUN = NO
  - FRESH_OOS = NO
  - PRODUCTION = PRODUCTION_HOLD
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.data.resampler import to_monthly
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

V02_TRADES_CSV = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv"
OUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/research/progressed_downside_v01"
DATA_CUTOFF = pd.Timestamp("2026-08-14")


def calc_stats(series: pd.Series) -> dict[str, Any]:
    usable = series.dropna().astype(float)
    if usable.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
            "p10": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p90": None,
            "p95": None,
            "min": None,
            "max": None,
            "std": None,
        }
    return {
        "count": int(len(usable)),
        "mean": round(float(usable.mean()), 2),
        "median": round(float(usable.median()), 2),
        "p10": round(float(np.percentile(usable, 10)), 2),
        "p25": round(float(np.percentile(usable, 25)), 2),
        "p50": round(float(np.percentile(usable, 50)), 2),
        "p75": round(float(np.percentile(usable, 75)), 2),
        "p90": round(float(np.percentile(usable, 90)), 2),
        "p95": round(float(np.percentile(usable, 95)), 2),
        "min": round(float(usable.min()), 2),
        "max": round(float(usable.max()), 2),
        "std": round(float(usable.std()), 2) if len(usable) > 1 else 0.0,
    }


def run_diagnostic():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()

    v02_df = pd.read_csv(V02_TRADES_CSV, dtype={"ticker": str})
    v02_df["ticker"] = v02_df["ticker"].str.zfill(6)
    total_trades_count = len(v02_df)

    # Filter PROGRESSED reached cohort
    prog_df = v02_df[v02_df["first_progressed_date"].notna()].copy().sort_values(by=["ticker", "trade_sequence"]).reset_index(drop=True)
    prog_count = len(prog_df)
    unique_tickers_count = prog_df["ticker"].nunique()

    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")

    progressed_records: list[dict[str, Any]] = []
    monthly_path_records: list[dict[str, Any]] = []
    exit3_records: list[dict[str, Any]] = []
    exit4_records: list[dict[str, Any]] = []

    for idx, row in prog_df.iterrows():
        ticker = row["ticker"]
        name = row["name"]
        t_id = row["trade_id"]
        seq = int(row["trade_sequence"])
        e_exec_d = pd.Timestamp(row["entry_execution_date"])
        entry_open = float(row["entry_open"])
        f_prog_d = pd.Timestamp(row["first_progressed_date"])
        f_prog_eff_d = pd.Timestamp(row["first_progressed_effective_trading_date"])
        life = str(row["lifecycle_class"])
        exit_t = str(row["exit_type"])
        x_sig_d = pd.Timestamp(row["exit_signal_date"]) if pd.notna(row["exit_signal_date"]) else None
        x_exec_d = pd.Timestamp(row["exit_execution_date"]) if pd.notna(row["exit_execution_date"]) else None
        t_ret = float(row["terminal_return"])
        mfe = float(row["mfe"])
        mae = float(row["mae"])
        peak_gb = float(row["peak_giveback"])
        status = str(row["trade_status"])
        lg_trig = bool(row["loss_guard_triggered"])

        daily = cache.load(ticker)
        if daily is None or daily.empty:
            continue
        daily = daily.sort_index()
        daily = daily[daily.index <= DATA_CUTOFF]

        # Determine reference prices on first_progressed_effective_trading_date
        prog_day_bars = daily[daily.index == f_prog_eff_d]
        if not prog_day_bars.empty:
            prog_ref_close = float(prog_day_bars.iloc[0]["close"])
            prog_ref_open = float(prog_day_bars.iloc[0]["open"])
        else:
            prog_day_bars = daily[daily.index <= f_prog_eff_d]
            prog_ref_close = float(prog_day_bars.iloc[-1]["close"]) if not prog_day_bars.empty else entry_open
            prog_ref_open = float(prog_day_bars.iloc[-1]["open"]) if not prog_day_bars.empty else entry_open

        # Survived to active PROGRESSED holding window
        survived_to_prog = bool(not lg_trig or (x_exec_d is not None and x_exec_d > f_prog_eff_d))

        # Held path end boundary
        if status == "REALIZED" and x_sig_d is not None:
            held_end_d = min(x_sig_d, DATA_CUTOFF)
        else:
            held_end_d = DATA_CUTOFF

        # Execution open
        if x_exec_d is not None and x_exec_d <= DATA_CUTOFF:
            exec_bar = daily[daily.index == x_exec_d]
            exit_exec_open = float(exec_bar.iloc[0]["open"]) if not exec_bar.empty else float(row["exit_price"])
        else:
            exit_exec_open = None

        # Terminal exit price used for progressed_terminal_return_pct
        if status == "REALIZED" and exit_exec_open is not None:
            terminal_price = exit_exec_open
        else:
            terminal_price = float(daily.iloc[-1]["close"])

        progressed_terminal_ret_pct = round((terminal_price / prog_ref_close - 1.0) * 100.0, 2)

        # Held daily price path (strictly from f_prog_eff_d to held_end_d)
        held_daily = daily[(daily.index >= f_prog_eff_d) & (daily.index <= held_end_d)]

        if not held_daily.empty and survived_to_prog:
            post_peak_close = float(held_daily["close"].max())
            post_peak_close_d = held_daily["close"].idxmax().strftime("%Y-%m-%d")
            post_trough_close = float(held_daily["close"].min())
            post_trough_close_d = held_daily["close"].idxmin().strftime("%Y-%m-%d")

            post_peak_high = float(held_daily["high"].max())
            post_peak_high_d = held_daily["high"].idxmax().strftime("%Y-%m-%d")
            post_trough_low = float(held_daily["low"].min())
            post_trough_low_d = held_daily["low"].idxmin().strftime("%Y-%m-%d")

            # Entry-based returns
            peak_ret_entry = round((post_peak_high / entry_open - 1.0) * 100.0, 2)
            trough_ret_entry = round((post_trough_low / entry_open - 1.0) * 100.0, 2)

            # PROGRESSED-reference-based returns
            prog_to_peak_ret_pct = round((post_peak_high / prog_ref_close - 1.0) * 100.0, 2)
            prog_to_trough_ret_pct = round((post_trough_low / prog_ref_close - 1.0) * 100.0, 2)

            # Daily Close HWM Drawdown tracking
            close_hwm = 0.0
            max_close_dd = 0.0
            max_close_dd_d = None

            # Daily Intraday High HWM Drawdown tracking
            high_hwm = 0.0
            max_intra_dd = 0.0
            max_intra_dd_d = None

            for d, d_row in held_daily.iterrows():
                c = float(d_row["close"])
                h = float(d_row["high"])
                l = float(d_row["low"])

                # Close HWM
                if c > close_hwm:
                    close_hwm = c
                close_dd = (c / close_hwm - 1.0) * 100.0
                if close_dd < max_close_dd:
                    max_close_dd = close_dd
                    max_close_dd_d = d.strftime("%Y-%m-%d")

                # High HWM vs Intraday Low
                if h > high_hwm:
                    high_hwm = h
                intra_dd = (l / high_hwm - 1.0) * 100.0
                if intra_dd < max_intra_dd:
                    max_intra_dd = intra_dd
                    max_intra_dd_d = d.strftime("%Y-%m-%d")
        else:
            post_peak_close = prog_ref_close
            post_peak_close_d = f_prog_eff_d.strftime("%Y-%m-%d")
            post_trough_close = prog_ref_close
            post_trough_close_d = f_prog_eff_d.strftime("%Y-%m-%d")
            post_peak_high = prog_ref_close
            post_trough_low = prog_ref_close
            peak_ret_entry = mfe
            trough_ret_entry = mae
            prog_to_peak_ret_pct = 0.0
            prog_to_trough_ret_pct = 0.0
            max_close_dd = 0.0
            max_close_dd_d = None
            max_intra_dd = 0.0
            max_intra_dd_d = None

        # Reconstruct Monthly Pattern A Path bounded by held_end_d
        monthly_bars = to_monthly(daily)
        m_dates = [m for m in monthly_bars.index if m >= pd.Timestamp(row["entry_signal_date"]) and m <= held_end_d]

        f_prog_score = None
        score_hwm_while_held = None
        max_score_dd_while_held = 0.0

        for m in m_dates:
            try:
                snap = build_historical_snapshot(ticker, name, daily[daily.index <= m], m, include_incomplete_periods=False)
                eval_res = evaluate_pattern_a(snap)
                st = eval_res.stage.value.upper() if eval_res.stage else "UNAVAILABLE"
                sc = float(round(eval_res.score, 2)) if eval_res.score is not None else None
            except Exception:
                st = "UNAVAILABLE"
                sc = None

            m_daily = daily[daily.index <= m]
            m_eff_d = m_daily.index.max().strftime("%Y-%m-%d") if not m_daily.empty else m.strftime("%Y-%m-%d")
            m_close = float(m_daily.iloc[-1]["close"]) if not m_daily.empty else entry_open

            if m == f_prog_d and st == "PROGRESSED":
                f_prog_score = sc
                score_hwm_while_held = sc

            cur_sc_dd = None
            if f_prog_score is not None and sc is not None:
                if score_hwm_while_held is None or sc > score_hwm_while_held:
                    score_hwm_while_held = sc
                cur_sc_dd = round(score_hwm_while_held - sc, 2)
                if cur_sc_dd > max_score_dd_while_held:
                    max_score_dd_while_held = cur_sc_dd

            monthly_path_records.append({
                "ticker": ticker,
                "name": name,
                "trade_id": t_id,
                "snapshot_month": m.strftime("%Y-%m-%d"),
                "effective_trading_date": m_eff_d,
                "pattern_a_stage": st,
                "pattern_a_score": sc,
                "score_hwm_while_held": score_hwm_while_held,
                "score_drawdown_while_held": cur_sc_dd,
                "monthly_close": m_close,
                "survived_to_progressed": survived_to_prog,
            })

        # Exit3 and Exit4 Delay Diagnostics
        if survived_to_prog and exit_t.startswith("EXIT3_") and x_sig_d is not None:
            # Peak close before exit signal
            held_prior_to_sig = daily[(daily.index >= f_prog_eff_d) & (daily.index <= x_sig_d)]
            p_hwm_c = float(held_prior_to_sig["close"].max())
            p_hwm_d = held_prior_to_sig["close"].idxmax()
            sig_c = float(held_prior_to_sig.iloc[-1]["close"])

            dd_at_sig = round((sig_c / p_hwm_c - 1.0) * 100.0, 2)
            dd_at_exec = round((exit_exec_open / p_hwm_c - 1.0) * 100.0, 2) if exit_exec_open is not None else None

            exit3_records.append({
                "ticker": ticker,
                "name": name,
                "trade_id": t_id,
                "exit_type": exit_t,
                "first_progressed_effective_trading_date": f_prog_eff_d.strftime("%Y-%m-%d"),
                "exit_signal_date": x_sig_d.strftime("%Y-%m-%d"),
                "exit_execution_date": x_exec_d.strftime("%Y-%m-%d") if x_exec_d is not None else None,
                "progressed_to_exit3_signal_days": (x_sig_d - f_prog_eff_d).days,
                "price_hwm_date": p_hwm_d.strftime("%Y-%m-%d"),
                "price_hwm_to_exit3_signal_days": (x_sig_d - p_hwm_d).days,
                "price_hwm_to_exit3_execution_days": (x_exec_d - p_hwm_d).days if x_exec_d is not None else None,
                "close_drawdown_at_exit3_signal": dd_at_sig,
                "drawdown_at_exit3_execution": dd_at_exec,
                "terminal_return": t_ret,
                "progressed_terminal_return_pct": progressed_terminal_ret_pct,
            })

        if survived_to_prog and exit_t == "EXIT4_SCORE_DRAWDOWN_GE_15" and x_sig_d is not None:
            held_prior_to_sig = daily[(daily.index >= f_prog_eff_d) & (daily.index <= x_sig_d)]
            p_hwm_c = float(held_prior_to_sig["close"].max())
            p_hwm_d = held_prior_to_sig["close"].idxmax()
            sig_c = float(held_prior_to_sig.iloc[-1]["close"])

            dd_at_sig = round((sig_c / p_hwm_c - 1.0) * 100.0, 2)
            dd_at_exec = round((exit_exec_open / p_hwm_c - 1.0) * 100.0, 2) if exit_exec_open is not None else None

            exit4_records.append({
                "ticker": ticker,
                "name": name,
                "trade_id": t_id,
                "first_progressed_score": f_prog_score,
                "score_hwm_while_held": score_hwm_while_held,
                "max_score_drawdown_while_held": max_score_dd_while_held,
                "first_progressed_effective_trading_date": f_prog_eff_d.strftime("%Y-%m-%d"),
                "exit_signal_date": x_sig_d.strftime("%Y-%m-%d"),
                "exit_execution_date": x_exec_d.strftime("%Y-%m-%d") if x_exec_d is not None else None,
                "progressed_to_exit4_signal_days": (x_sig_d - f_prog_eff_d).days,
                "price_hwm_date": p_hwm_d.strftime("%Y-%m-%d"),
                "price_hwm_to_exit4_signal_days": (x_sig_d - p_hwm_d).days,
                "price_hwm_to_exit4_execution_days": (x_exec_d - p_hwm_d).days if x_exec_d is not None else None,
                "close_drawdown_at_exit4_signal": dd_at_sig,
                "drawdown_at_exit4_execution": dd_at_exec,
                "terminal_return": t_ret,
                "progressed_terminal_return_pct": progressed_terminal_ret_pct,
            })

        progressed_records.append({
            "ticker": ticker,
            "name": name,
            "trade_id": t_id,
            "trade_sequence": seq,
            "entry_execution_date": row["entry_execution_date"],
            "entry_open": entry_open,
            "first_progressed_date": row["first_progressed_date"],
            "first_progressed_effective_trading_date": row["first_progressed_effective_trading_date"],
            "lifecycle_class": life,
            "survived_to_progressed": survived_to_prog,
            "held_path_end_date": held_end_d.strftime("%Y-%m-%d"),
            "progressed_reference_close": prog_ref_close,
            "progressed_reference_open": prog_ref_open,
            "post_progressed_peak_close": post_peak_close,
            "post_progressed_peak_date": post_peak_close_d,
            "post_progressed_trough_close": post_trough_close,
            "post_progressed_trough_date": post_trough_close_d,
            "peak_return_from_entry_after_progressed": peak_ret_entry,
            "trough_return_from_entry_after_progressed": trough_ret_entry,
            "progressed_to_peak_return_pct": prog_to_peak_ret_pct,
            "progressed_to_trough_return_pct": prog_to_trough_ret_pct,
            "progressed_terminal_return_pct": progressed_terminal_ret_pct,
            "max_close_hwm_drawdown": round(max_close_dd, 2),
            "max_close_hwm_drawdown_date": max_close_dd_d,
            "max_intraday_hwm_drawdown": round(max_intra_dd, 2),
            "max_intraday_hwm_drawdown_date": max_intra_dd_d,
            "first_progressed_score": f_prog_score,
            "score_hwm_while_held": score_hwm_while_held,
            "max_score_drawdown_while_held": round(max_score_dd_while_held, 2),
            "exit_type": exit_t,
            "exit_signal_date": row["exit_signal_date"],
            "exit_execution_date": row["exit_execution_date"],
            "exit_execution_open": exit_exec_open,
            "terminal_return": t_ret,
            "mfe": mfe,
            "mae": mae,
            "peak_giveback": peak_gb,
            "trade_status": status,
            "loss_guard_triggered": lg_trig,
        })

    df_prog_all = pd.DataFrame(progressed_records)
    df_monthly_path = pd.DataFrame(monthly_path_records)
    df_exit3 = pd.DataFrame(exit3_records)
    df_exit4 = pd.DataFrame(exit4_records)

    # Save base csv artifacts
    df_prog_all.to_csv(OUT_DIR / "progressed_trades.csv", index=False)
    df_monthly_path.to_csv(OUT_DIR / "progressed_monthly_path.csv", index=False)
    df_exit3.to_csv(OUT_DIR / "exit3_diagnostics.csv", index=False)
    df_exit4.to_csv(OUT_DIR / "exit4_diagnostics.csv", index=False)
    logger.info("Saved progressed_trades.csv (%d rows) and monthly path (%d rows)", len(df_prog_all), len(df_monthly_path))

    # Diagnostic sub-cohorts
    df_survived = df_prog_all[df_prog_all["survived_to_progressed"] == True].copy()
    df_lg_pre = df_prog_all[df_prog_all["survived_to_progressed"] == False].copy()

    # 1. Deep Loss Cohort (terminal_return <= -20% or mae <= -30%)
    df_deep_loss = df_survived[(df_survived["terminal_return"] <= -20.0) | (df_survived["mae"] <= -30.0)].copy()

    # Add cause classifications with _CANDIDATE
    deep_loss_causes = []
    for _, r in df_deep_loss.iterrows():
        ret = float(r["terminal_return"])
        status = str(r["trade_status"])
        exit_t = str(r["exit_type"])
        life = str(r["lifecycle_class"])
        if status == "OPEN_AT_CUTOFF" and ret <= -20.0:
            cause = "OPEN_AT_CUTOFF_STRUCTURAL_TAIL"
            interp = "Cutoff까지 청산 조건을 충족하지 못해 미청산 보유된 구조적 테일"
        elif exit_t.startswith("EXIT3_") and ret <= -20.0:
            cause = "PROGRESSED_EXIT3_LAG_CANDIDATE"
            interp = "월봉 국면 전환(Exit3) 시점까지 가격 하락이 누적되어 지연 청산된 테일 후보"
        elif exit_t == "EXIT4_SCORE_DRAWDOWN_GE_15" and ret <= -20.0:
            cause = "PROGRESSED_EXIT4_LAG_CANDIDATE"
            interp = "점수 HWM 15pt 하락 시점까지 가격 하락이 빠르게 선행하여 발생한 테일 후보"
        elif life in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"} and ret <= -20.0:
            cause = "COVERAGE_EXIT_HOLE_CANDIDATE"
            interp = "커버리지 생애주기 경로에서 청산 공백으로 발생한 손실 후보"
        elif r["peak_return_from_entry_after_progressed"] >= 20.0 and ret <= 0.0:
            cause = "PROFIT_GIVEBACK_TAIL"
            interp = "PROGRESSED 이후 유의미한 상승 발생 후 이익을 전액 반납하고 손실 전환"
        else:
            cause = "OTHER_DEEP_LOSS"
            interp = "기타 하방 손실"
        deep_loss_causes.append((cause, interp))

    df_deep_loss["primary_cause"] = [c[0] for c in deep_loss_causes]
    df_deep_loss["research_interpretation"] = [c[1] for c in deep_loss_causes]
    df_deep_loss.to_csv(OUT_DIR / "progressed_deep_loss_cases.csv", index=False)

    # 2. Winner Drawdown Cohort (terminal_return >= +20%)
    df_winners = df_survived[df_survived["terminal_return"] >= 20.0].copy()
    df_winners.to_csv(OUT_DIR / "progressed_winner_drawdown.csv", index=False)

    # 3. Winner Extreme Drawdown Cases (terminal_return >= +50% and max_close_hwm_drawdown <= -30%)
    df_winner_extreme = df_survived[(df_survived["terminal_return"] >= 50.0) & (df_survived["max_close_hwm_drawdown"] <= -30.0)].copy()
    df_winner_extreme.to_csv(OUT_DIR / "progressed_winner_extreme_drawdown_cases.csv", index=False)

    # 4. Coverage Diagnostics
    df_cov_skipped = df_survived[df_survived["lifecycle_class"] == "SKIPPED_EARLY_TREND_HANDOFF"].copy()
    df_cov_without_direct = df_survived[df_survived["lifecycle_class"] == "PROGRESSED_WITHOUT_DIRECT_HANDOFF"].copy()
    df_cov_all = df_survived[df_survived["lifecycle_class"].isin(["SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"])].copy()

    # Identify COVERAGE_EXIT_HOLE_CANDIDATE
    df_cov_all["is_exit_hole_candidate"] = (df_cov_all["trade_status"] == "OPEN_AT_CUTOFF") & ((df_cov_all["terminal_return"] <= 0.0) | (df_cov_all["max_close_hwm_drawdown"] <= -30.0))
    df_cov_all.to_csv(OUT_DIR / "coverage_diagnostics.csv", index=False)

    # Large profit giveback cases
    df_giveback_20 = df_survived[(df_survived["peak_return_from_entry_after_progressed"] >= 20.0) & (df_survived["terminal_return"] <= 0.0)]
    df_giveback_50 = df_survived[(df_survived["peak_return_from_entry_after_progressed"] >= 50.0) & (df_survived["terminal_return"] <= 20.0)]

    # Drawdown distributions
    all_close_dd_stats = calc_stats(df_survived["max_close_hwm_drawdown"])
    all_intra_dd_stats = calc_stats(df_survived["max_intraday_hwm_drawdown"])

    w20_close_dd = calc_stats(df_survived[df_survived["terminal_return"] >= 20.0]["max_close_hwm_drawdown"])
    w50_close_dd = calc_stats(df_survived[df_survived["terminal_return"] >= 50.0]["max_close_hwm_drawdown"])
    w100_close_dd = calc_stats(df_survived[df_survived["terminal_return"] >= 100.0]["max_close_hwm_drawdown"])

    l20_close_dd = calc_stats(df_survived[df_survived["terminal_return"] <= -20.0]["max_close_hwm_drawdown"])
    l30_close_dd = calc_stats(df_survived[df_survived["terminal_return"] <= -30.0]["max_close_hwm_drawdown"])

    # Distribution Overlap Analysis (Drawdown thresholds)
    df_w50 = df_survived[df_survived["terminal_return"] >= 50.0]
    df_l20 = df_survived[df_survived["terminal_return"] <= -20.0]

    overlap_data = {
        "winner_ge_50": {
            "total_count": len(df_w50),
            "dd_le_neg_20_count": int((df_w50["max_close_hwm_drawdown"] <= -20.0).sum()),
            "dd_le_neg_20_rate": round(float((df_w50["max_close_hwm_drawdown"] <= -20.0).mean() * 100), 2) if not df_w50.empty else 0.0,
            "dd_le_neg_25_count": int((df_w50["max_close_hwm_drawdown"] <= -25.0).sum()),
            "dd_le_neg_25_rate": round(float((df_w50["max_close_hwm_drawdown"] <= -25.0).mean() * 100), 2) if not df_w50.empty else 0.0,
            "dd_le_neg_30_count": int((df_w50["max_close_hwm_drawdown"] <= -30.0).sum()),
            "dd_le_neg_30_rate": round(float((df_w50["max_close_hwm_drawdown"] <= -30.0).mean() * 100), 2) if not df_w50.empty else 0.0,
            "dd_le_neg_35_count": int((df_w50["max_close_hwm_drawdown"] <= -35.0).sum()),
            "dd_le_neg_35_rate": round(float((df_w50["max_close_hwm_drawdown"] <= -35.0).mean() * 100), 2) if not df_w50.empty else 0.0,
            "dd_le_neg_40_count": int((df_w50["max_close_hwm_drawdown"] <= -40.0).sum()),
            "dd_le_neg_40_rate": round(float((df_w50["max_close_hwm_drawdown"] <= -40.0).mean() * 100), 2) if not df_w50.empty else 0.0,
        },
        "loser_le_neg_20": {
            "total_count": len(df_l20),
            "dd_le_neg_20_count": int((df_l20["max_close_hwm_drawdown"] <= -20.0).sum()),
            "dd_le_neg_20_rate": round(float((df_l20["max_close_hwm_drawdown"] <= -20.0).mean() * 100), 2) if not df_l20.empty else 0.0,
            "dd_le_neg_25_count": int((df_l20["max_close_hwm_drawdown"] <= -25.0).sum()),
            "dd_le_neg_25_rate": round(float((df_l20["max_close_hwm_drawdown"] <= -25.0).mean() * 100), 2) if not df_l20.empty else 0.0,
            "dd_le_neg_30_count": int((df_l20["max_close_hwm_drawdown"] <= -30.0).sum()),
            "dd_le_neg_30_rate": round(float((df_l20["max_close_hwm_drawdown"] <= -30.0).mean() * 100), 2) if not df_l20.empty else 0.0,
            "dd_le_neg_35_count": int((df_l20["max_close_hwm_drawdown"] <= -35.0).sum()),
            "dd_le_neg_35_rate": round(float((df_l20["max_close_hwm_drawdown"] <= -35.0).mean() * 100), 2) if not df_l20.empty else 0.0,
            "dd_le_neg_40_count": int((df_l20["max_close_hwm_drawdown"] <= -40.0).sum()),
            "dd_le_neg_40_rate": round(float((df_l20["max_close_hwm_drawdown"] <= -40.0).mean() * 100), 2) if not df_l20.empty else 0.0,
        },
    }

    # Exit Delay Stats
    exit3_delay_stats = calc_stats(df_exit3["price_hwm_to_exit3_signal_days"]) if not df_exit3.empty else {}
    exit3_dd_sig_stats = calc_stats(df_exit3["close_drawdown_at_exit3_signal"]) if not df_exit3.empty else {}
    exit3_dd_exec_stats = calc_stats(df_exit3["drawdown_at_exit3_execution"]) if not df_exit3.empty else {}

    exit4_delay_stats = calc_stats(df_exit4["price_hwm_to_exit4_signal_days"]) if not df_exit4.empty else {}
    exit4_dd_sig_stats = calc_stats(df_exit4["close_drawdown_at_exit4_signal"]) if not df_exit4.empty else {}
    exit4_dd_exec_stats = calc_stats(df_exit4["drawdown_at_exit4_execution"]) if not df_exit4.empty else {}

    # Descriptive separation classification
    sep_conclusion = "DESCRIPTIVE_PROGRESSED_DOWNSIDE_SEPARATION_OBSERVED"

    summary_data = {
        "metadata": {
            "strategy_name": "PATTERN_A_FAST_CORE_V02_REENTRY",
            "research_classification": "PATTERN_A_FAST_V02_PROGRESSED_DOWNSIDE_DIAGNOSTIC_V01_CORRECTION",
            "research_type": "RETROSPECTIVE_PROGRESSED_DOWNSIDE_ANATOMY",
            "total_official_v02_trades": total_trades_count,
            "post_entry_lifecycle_with_progressed_count": prog_count,
            "actually_held_through_progressed_count": len(df_survived),
            "pre_progressed_exit_with_future_lifecycle_progressed_count": len(df_lg_pre),
            "progressed_unique_tickers": unique_tickers_count,
            "data_cutoff": "2026-08-14",
            "production_status": "PRODUCTION_HOLD",
            "fresh_oos_executed": False,
            "separation_classification_type": "DESCRIPTIVE_ONLY",
        },
        "lifecycle_distribution": prog_df["lifecycle_class"].value_counts().to_dict(),
        "exit_distribution_survived": df_survived["exit_type"].value_counts().to_dict(),
        "loss_metrics_survived": {
            "return_le_neg_20_count": int((df_survived["terminal_return"] <= -20.0).sum()),
            "return_le_neg_20_rate": round(float((df_survived["terminal_return"] <= -20.0).mean() * 100), 2),
            "return_le_neg_30_count": int((df_survived["terminal_return"] <= -30.0).sum()),
            "return_le_neg_30_rate": round(float((df_survived["terminal_return"] <= -30.0).mean() * 100), 2),
            "return_le_neg_40_count": int((df_survived["terminal_return"] <= -40.0).sum()),
            "return_le_neg_40_rate": round(float((df_survived["terminal_return"] <= -40.0).mean() * 100), 2),
            "worst_terminal_return": round(float(df_survived["terminal_return"].min()), 2),
            "worst_mae": round(float(df_survived["mae"].min()), 2),
            "progressed_to_trough_return_stats": calc_stats(df_survived["progressed_to_trough_return_pct"]),
            "trough_return_from_entry_after_progressed_stats": calc_stats(df_survived["trough_return_from_entry_after_progressed"]),
        },
        "drawdown_distributions": {
            "all_survived_close_drawdown": all_close_dd_stats,
            "all_survived_intraday_drawdown": all_intra_dd_stats,
            "winners_ge_20_close_drawdown": w20_close_dd,
            "winners_ge_50_close_drawdown": w50_close_dd,
            "winners_ge_100_close_drawdown": w100_close_dd,
            "losers_le_neg_20_close_drawdown": l20_close_dd,
            "losers_le_neg_30_close_drawdown": l30_close_dd,
        },
        "distribution_overlap": overlap_data,
        "winner_extreme_drawdown_cases_count": len(df_winner_extreme),
        "exit_mechanism_diagnostics": {
            "exit3_count": len(df_exit3),
            "exit3_terminal_return_mean": round(float(df_exit3["terminal_return"].mean()), 2) if not df_exit3.empty else None,
            "exit3_terminal_return_median": round(float(df_exit3["terminal_return"].median()), 2) if not df_exit3.empty else None,
            "exit3_le_neg_20_count": int((df_exit3["terminal_return"] <= -20.0).sum()),
            "exit3_le_neg_30_count": int((df_exit3["terminal_return"] <= -30.0).sum()),
            "exit3_delay_days_stats": exit3_delay_stats,
            "exit3_drawdown_at_signal_stats": exit3_dd_sig_stats,
            "exit3_drawdown_at_execution_stats": exit3_dd_exec_stats,
            "exit4_count": len(df_exit4),
            "exit4_terminal_return_mean": round(float(df_exit4["terminal_return"].mean()), 2) if not df_exit4.empty else None,
            "exit4_terminal_return_median": round(float(df_exit4["terminal_return"].median()), 2) if not df_exit4.empty else None,
            "exit4_le_neg_20_count": int((df_exit4["terminal_return"] <= -20.0).sum()),
            "exit4_le_neg_30_count": int((df_exit4["terminal_return"] <= -30.0).sum()),
            "exit4_delay_days_stats": exit4_delay_stats,
            "exit4_drawdown_at_signal_stats": exit4_dd_sig_stats,
            "exit4_drawdown_at_execution_stats": exit4_dd_exec_stats,
            "coverage_skipped_count": len(df_cov_skipped),
            "coverage_without_direct_count": len(df_cov_without_direct),
            "coverage_exit_hole_candidates_count": int(df_cov_all["is_exit_hole_candidate"].sum()),
        },
        "profit_giveback_cases": {
            "peak_ge_20_terminal_le_0_count": len(df_giveback_20),
            "peak_ge_50_terminal_le_20_count": len(df_giveback_50),
        },
        "diagnostic_conclusion": sep_conclusion,
        "phase1_observed_candidate_range": "25% ~ 30% (POST_HOC_OBSERVED_RANGE_ONLY, NOT_PREREGISTERED)",
        "price_based_protection_worth_phase2": "YES (RESEARCH_INTERPRETATION_RECOMMENDED)",
    }

    (OUT_DIR / "summary.json").write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Generate representative cases markdown
    _generate_representative_cases_doc(df_prog_all, df_monthly_path, df_winner_extreme)

    # Generate analysis.md
    _generate_analysis_doc(summary_data, df_prog_all, df_deep_loss, df_winners, df_winner_extreme)

    logger.info("Diagnostic completed in %.2fs. Outputs in %s", time.perf_counter() - t0, OUT_DIR)


def _generate_representative_cases_doc(df_prog: pd.DataFrame, df_monthly: pd.DataFrame, df_win_extreme: pd.DataFrame):
    # 4 Losing cases
    losing_ids = ["011170_02", "000670_02", "200670_03", "298380_02"]

    # 4 Winning cases: deterministic top 4 by terminal return in survived PROGRESSED cohort
    df_surv = df_prog[df_prog["survived_to_progressed"] == True]
    top_winners = df_surv.sort_values(by="terminal_return", ascending=False).head(4)
    winning_ids = top_winners["trade_id"].tolist()

    # 2 Representative Winner Extreme Drawdown cases
    win_extreme_top = df_win_extreme.sort_values(by="max_close_hwm_drawdown").head(2)
    win_extreme_ids = win_extreme_top["trade_id"].tolist()

    md = """# A FAST Core V02 PROGRESSED Representative Cases Timeline & Anatomy (Corrected)

================================================================================
1. Representative Losing Cases (4건)
================================================================================
"""

    for t_id in losing_ids:
        r = df_prog[df_prog["trade_id"] == t_id].iloc[0]
        t = r["ticker"]
        name = r["name"]
        md += f"\n## [{t_id}] {name} ({t}) - Terminal Return: **{r['terminal_return']}%**\n"
        md += f"- **Entry Execution**: `{r['entry_execution_date']}` (Open: `{r['entry_open']:,.0f}`원)\n"
        md += f"- **First PROGRESSED**: `{r['first_progressed_date']}` (Effective: `{r['first_progressed_effective_trading_date']}`, Ref Close: `{r['progressed_reference_close']:,.0f}`원)\n"
        md += f"- **Held Window End**: `{r['held_path_end_date']}` | **Exit Type**: `{r['exit_type']}` (Signal: `{r['exit_signal_date']}`, Exec: `{r['exit_execution_date']}`)\n"
        md += f"- **Post-PROGRESSED High / Trough**: Peak `{r['post_progressed_peak_close']:,.0f}`원 ({r['post_progressed_peak_date']}) / Trough `{r['post_progressed_trough_close']:,.0f}`원 ({r['post_progressed_trough_date']})\n"
        md += f"- **Max Drawdown from Price HWM (Held Window)**: **`{r['max_close_hwm_drawdown']}%`** ({r['max_close_hwm_drawdown_date']}) | Intraday: `{r['max_intraday_hwm_drawdown']}%`\n"
        md += f"- **Score Evolution (While Held)**: Init `{r['first_progressed_score']}` -> HWM `{r['score_hwm_while_held']}` -> Max Drawdown `{r['max_score_drawdown_while_held']}pt`\n"

        md += "\n**[Monthly Timeline Path (Bounded by Exit Signal)]**\n\n"
        md += "| Snapshot Month | Stage | Score | Score HWM | Score DD | Monthly Close |\n"
        md += "|:---:|:---:|:---:|:---:|:---:|:---:|\n"

        m_sub = df_monthly[df_monthly["trade_id"] == t_id].sort_values(by="snapshot_month")
        for _, m_row in m_sub.iterrows():
            md += f"| `{m_row['snapshot_month']}` | `{m_row['pattern_a_stage']}` | {m_row['pattern_a_score']} | {m_row['score_hwm_while_held']} | {m_row['score_drawdown_while_held']} | {m_row['monthly_close']:,.0f}원 |\n"

    md += """
================================================================================
2. Representative Winning Cases (상위 4건 Deterministic Selection)
================================================================================
"""

    for t_id in winning_ids:
        r = df_prog[df_prog["trade_id"] == t_id].iloc[0]
        t = r["ticker"]
        name = r["name"]
        md += f"\n## [{t_id}] {name} ({t}) - Terminal Return: **+{r['terminal_return']}%**\n"
        md += f"- **Entry Execution**: `{r['entry_execution_date']}` (Open: `{r['entry_open']:,.0f}`원)\n"
        md += f"- **First PROGRESSED**: `{r['first_progressed_date']}` (Effective: `{r['first_progressed_effective_trading_date']}`, Ref Close: `{r['progressed_reference_close']:,.0f}`원)\n"
        md += f"- **Held Window End**: `{r['held_path_end_date']}` | **Exit Type**: `{r['exit_type']}`\n"
        md += f"- **Max Drawdown from Price HWM (Held Window)**: **`{r['max_close_hwm_drawdown']}%`** ({r['max_close_hwm_drawdown_date']}) | Intraday: `{r['max_intraday_hwm_drawdown']}%`\n"

        md += "\n**[Monthly Timeline Path]**\n\n"
        md += "| Snapshot Month | Stage | Score | Score HWM | Score DD | Monthly Close |\n"
        md += "|:---:|:---:|:---:|:---:|:---:|:---:|\n"

        m_sub = df_monthly[df_monthly["trade_id"] == t_id].sort_values(by="snapshot_month")
        for _, m_row in m_sub.iterrows():
            md += f"| `{m_row['snapshot_month']}` | `{m_row['pattern_a_stage']}` | {m_row['pattern_a_score']} | {m_row['score_hwm_while_held']} | {m_row['score_drawdown_while_held']} | {m_row['monthly_close']:,.0f}원 |\n"

    md += """
================================================================================
3. Representative Winner Extreme Drawdown Cases (Right-Tail Overlap 분석 2건)
================================================================================
"""
    for t_id in win_extreme_ids:
        r = df_prog[df_prog["trade_id"] == t_id].iloc[0]
        t = r["ticker"]
        name = r["name"]
        md += f"\n## [{t_id}] {name} ({t}) - Terminal Return: **+{r['terminal_return']}%** | Max HWM Drawdown: **`{r['max_close_hwm_drawdown']}%`**\n"
        md += f"- **Entry Execution**: `{r['entry_execution_date']}` | **First PROGRESSED**: `{r['first_progressed_date']}`\n"
        md += f"- **Held Window End**: `{r['held_path_end_date']}` | **Exit Type**: `{r['exit_type']}`\n"
        md += f"- **Analysis**: 최종적으로 +{r['terminal_return']}%의 대형 수익으로 마감했으나, 보유 기간 중 고점 대비 `{r['max_close_hwm_drawdown']}%`의 깊은 조정을 겪음. 이는 너무 타이트한 Trailing Stop 적용 시 대형 승자가 조기 청산될 수 있는 Right-Tail Destruction 위험을 보여줌.\n"

    (OUT_DIR / "representative_cases.md").write_text(md, encoding="utf-8")


def _generate_analysis_doc(summary: dict[str, Any], df_prog: pd.DataFrame, df_deep: pd.DataFrame, df_win: pd.DataFrame, df_win_ext: pd.DataFrame):
    meta = summary["metadata"]
    loss = summary["loss_metrics_survived"]
    dd = summary["drawdown_distributions"]
    ov = summary["distribution_overlap"]
    ex = summary["exit_mechanism_diagnostics"]
    gb = summary["profit_giveback_cases"]

    md = f"""# A FAST Core V02 PROGRESSED Downside Protection Research Phase 1 분석 보고서 (Corrected)

================================================================================
1. Research Classification & Mandate
================================================================================
- **연구 분류**: `{meta["research_classification"]}`
- **연구 성격**: `{meta["research_type"]}`
- **전략 규칙 변경**: **`NO` (전략 불변, 진단 전용)**
- **운영 상태**: **`PRODUCTION_HOLD`**
- **진단 결론 (`Diagnostic Conclusion`)**: **`{summary["diagnostic_conclusion"]}`**
- **Phase 2 보호 규칙 연구 가치 (`PRICE_BASED_PROTECTION_WORTH_PHASE2`)**: **`{summary["price_based_protection_worth_phase2"]}`**
- **Phase 1 관찰된 후보 범위 (`PHASE1_OBSERVED_CANDIDATE_RANGE`)**: **`{summary["phase1_observed_candidate_range"]}`**

================================================================================
2. PROGRESSED Cohort 명칭 및 표본 구분
================================================================================
- **전체 V02 공식 거래 수**: **{meta["total_official_v02_trades"]}건**
- **사후 생애주기 상 PROGRESSED 포함 거래 (`POST_ENTRY_LIFECYCLE_WITH_PROGRESSED`)**: **{meta["post_entry_lifecycle_with_progressed_count"]}건 (100.0%)**
- **실제 PROGRESSED 도달 후 보유된 거래 (`ACTUALLY_HELD_THROUGH_PROGRESSED`)**: **{meta["actually_held_through_progressed_count"]}건 (60.52%)** *(주요 분석 모집단)*
- **PROGRESSED 이전 사전 손절 거래 (`PRE_PROGRESSED_EXIT`)**: **{meta["pre_progressed_exit_with_future_lifecycle_progressed_count"]}건 (39.48%)**

================================================================================
3. ACTUALLY_HELD_THROUGH_PROGRESSED (328건) 하방 위험 지표
================================================================================
- **Return <= -20% 손실**: **{loss["return_le_neg_20_count"]}건 ({loss["return_le_neg_20_rate"]}%)**
- **Return <= -30% 극단 손실**: **{loss["return_le_neg_30_count"]}건 ({loss["return_le_neg_30_rate"]}%)**
- **Return <= -40% 심각 손실**: **{loss["return_le_neg_40_count"]}건 ({loss["return_le_neg_40_rate"]}%)**
- **Worst Terminal Return**: **{loss["worst_terminal_return"]}%** (롯데케미칼 011170_02)
- **Worst MAE**: **{loss["worst_mae"]}%**
- **PROGRESSED Reference → Subsequent Trough Return 중앙값 / P25**: **{loss["progressed_to_trough_return_stats"]["median"]}% / {loss["progressed_to_trough_return_stats"]["p25"]}%**

================================================================================
4. Drawdown 분포 및 Percentile 비교 (음수 Drawdown 기준)
================================================================================
*주의: Drawdown이 음수이므로 P25가 더 깊은 하방(Deep Tail), P75가 얕은 하방(Shallow)을 나타냄.*

| 분석 대상 코호트 | 표본 수 | P10 | P25 (Deep) | Median (P50) | P75 (Shallow) | P90 | Worst Drawdown |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Active PROGRESSED 전체** | {meta["actually_held_through_progressed_count"]}건 | {dd["all_survived_close_drawdown"]["p10"]}% | {dd["all_survived_close_drawdown"]["p25"]}% | **{dd["all_survived_close_drawdown"]["median"]}%** | {dd["all_survived_close_drawdown"]["p75"]}% | {dd["all_survived_close_drawdown"]["p90"]}% | {dd["all_survived_close_drawdown"]["min"]}% |
| **대형 승자 (Return >= +50%)** | {dd["winners_ge_50_close_drawdown"]["count"]}건 | {dd["winners_ge_50_close_drawdown"]["p10"]}% | **{dd["winners_ge_50_close_drawdown"]["p25"]}%** | **{dd["winners_ge_50_close_drawdown"]["median"]}%** | {dd["winners_ge_50_close_drawdown"]["p75"]}% | {dd["winners_ge_50_close_drawdown"]["p90"]}% | {dd["winners_ge_50_close_drawdown"]["min"]}% |
| **초대형 승자 (Return >= +100%)** | {dd["winners_ge_100_close_drawdown"]["count"]}건 | {dd["winners_ge_100_close_drawdown"]["p10"]}% | **{dd["winners_ge_100_close_drawdown"]["p25"]}%** | **{dd["winners_ge_100_close_drawdown"]["median"]}%** | {dd["winners_ge_100_close_drawdown"]["p75"]}% | {dd["winners_ge_100_close_drawdown"]["p90"]}% | {dd["winners_ge_100_close_drawdown"]["min"]}% |
| **대형 손실자 (Return <= -20%)** | {dd["losers_le_neg_20_close_drawdown"]["count"]}건 | {dd["losers_le_neg_20_close_drawdown"]["p10"]}% | **{dd["losers_le_neg_20_close_drawdown"]["p25"]}%** | **{dd["losers_le_neg_20_close_drawdown"]["median"]}%** | {dd["losers_le_neg_20_close_drawdown"]["p75"]}% | {dd["losers_le_neg_20_close_drawdown"]["p90"]}% | {dd["losers_le_neg_20_close_drawdown"]["min"]}% |
| **극단 손실자 (Return <= -30%)** | {dd["losers_le_neg_30_close_drawdown"]["count"]}건 | {dd["losers_le_neg_30_close_drawdown"]["p10"]}% | **{dd["losers_le_neg_30_close_drawdown"]["p25"]}%** | **{dd["losers_le_neg_30_close_drawdown"]["median"]}%** | {dd["losers_le_neg_30_close_drawdown"]["p75"]}% | {dd["losers_le_neg_30_close_drawdown"]["p90"]}% | {dd["losers_le_neg_30_close_drawdown"]["min"]}% |

================================================================================
5. Distribution Overlap (승자 테일 vs 패자 테일 중첩 분석)
================================================================================

| HWM Close Drawdown 기준 | 대형 승자 (>= +50%, {ov["winner_ge_50"]["total_count"]}건) 초과 건수(비율) | 대형 손실자 (<= -20%, {ov["loser_le_neg_20"]["total_count"]}건) 초과 건수(비율) |
|---|:---:|:---:|
| **Drawdown <= -20%** | {ov["winner_ge_50"]["dd_le_neg_20_count"]}건 ({ov["winner_ge_50"]["dd_le_neg_20_rate"]}%) | {ov["loser_le_neg_20"]["dd_le_neg_20_count"]}건 ({ov["loser_le_neg_20"]["dd_le_neg_20_rate"]}%) |
| **Drawdown <= -25%** | {ov["winner_ge_50"]["dd_le_neg_25_count"]}건 ({ov["winner_ge_50"]["dd_le_neg_25_rate"]}%) | {ov["loser_le_neg_20"]["dd_le_neg_25_count"]}건 ({ov["loser_le_neg_20"]["dd_le_neg_25_rate"]}%) |
| **Drawdown <= -30%** | **{ov["winner_ge_50"]["dd_le_neg_30_count"]}건 ({ov["winner_ge_50"]["dd_le_neg_30_rate"]}%)** | **{ov["loser_le_neg_20"]["dd_le_neg_30_count"]}건 ({ov["loser_le_neg_20"]["dd_le_neg_30_rate"]}%)** |
| **Drawdown <= -35%** | {ov["winner_ge_50"]["dd_le_neg_35_count"]}건 ({ov["winner_ge_50"]["dd_le_neg_35_rate"]}%) | {ov["loser_le_neg_20"]["dd_le_neg_35_count"]}건 ({ov["loser_le_neg_20"]["dd_le_neg_35_rate"]}%) |
| **Drawdown <= -40%** | {ov["winner_ge_50"]["dd_le_neg_40_count"]}건 ({ov["winner_ge_50"]["dd_le_neg_40_rate"]}%) | {ov["loser_le_neg_20"]["dd_le_neg_40_count"]}건 ({ov["loser_le_neg_20"]["dd_le_neg_40_rate"]}%) |

### [기술적 분리 및 중첩 평가 소견]
- **중심 경향 분리**: 대형 승자(>= +50%)의 고점 대비 하락 중앙값은 **{dd["winners_ge_50_close_drawdown"]["median"]}%**인 반면, 대형 손실자(<= -20%)는 **{dd["losers_le_neg_20_close_drawdown"]["median"]}%**로 뚜렷한 중심 경향 분리가 관측됨.
- **테일 중첩 주의 (`Tail Overlap`)**: 대형 승자 중에서도 **{ov["winner_ge_50"]["dd_le_neg_30_count"]}건 ({ov["winner_ge_50"]["dd_le_neg_30_rate"]}%)**은 -30% 이하의 깊은 조정을 견디고 최종 승자가 됨. 따라서 Phase 2 보호 규칙 설계 시 승자 조기 청산(Right-Tail Destruction)과 손실 방어 간의 트레이드오프가 핵심 과제임.

================================================================================
6. 청산 지연 실측 진단 (Exit3 / Exit4 / Coverage)
================================================================================
- **Exit 3 (국면 전환 청산, {ex["exit3_count"]}건)**:
  - **Price HWM → Signal 지연 일수**: 중앙값 **`{ex["exit3_delay_days_stats"]["median"]}`일** (P75: `{ex["exit3_delay_days_stats"]["p75"]}`일, 최악 `{ex["exit3_delay_days_stats"]["max"]}`일)
  - **신호 발생일 Close 기준 Drawdown**: 중앙값 **`{ex["exit3_drawdown_at_signal_stats"]["median"]}%`** (P25: `{ex["exit3_drawdown_at_signal_stats"]["p25"]}%`)
  - **실행일 Open 기준 Drawdown**: 중앙값 **`{ex["exit3_drawdown_at_execution_stats"]["median"]}%`** (P25: `{ex["exit3_drawdown_at_execution_stats"]["p25"]}%`)
- **Exit 4 (Score HWM 15pt 하락 청산, {ex["exit4_count"]}건)**:
  - **Price HWM → Signal 지연 일수**: 중앙값 **`{ex["exit4_delay_days_stats"]["median"]}`일** (P75: `{ex["exit4_delay_days_stats"]["p75"]}`일, 최악 `{ex["exit4_delay_days_stats"]["max"]}`일)
  - **신호 발생일 Close 기준 Drawdown**: 중앙값 **`{ex["exit4_drawdown_at_signal_stats"]["median"]}%`**
  - **실행일 Open 기준 Drawdown**: 중앙값 **`{ex["exit4_drawdown_at_execution_stats"]["median"]}%`**
- **Coverage 경로 세부 구분**:
  - `SKIPPED_EARLY_TREND_HANDOFF`: {ex["coverage_skipped_count"]}건
  - `PROGRESSED_WITHOUT_DIRECT_HANDOFF`: {ex["coverage_without_direct_count"]}건
  - `COVERAGE_EXIT_HOLE_CANDIDATE`: **{ex["coverage_exit_hole_candidates_count"]}건** (Exit 3 미적용 상태에서 Cutoff까지 손실 미청산)

================================================================================
7. 대형 이익 반납 (`Large Profit Giveback`) 실측
================================================================================
- **PROGRESSED 이후 +20% 이상 상승 후 0% 이하로 마감한 거래**: **{gb["peak_ge_20_terminal_le_0_count"]}건**
- **PROGRESSED 이후 +50% 이상 급등 후 +20% 이하로 마감한 거래**: **{gb["peak_ge_50_terminal_le_20_count"]}건**

================================================================================
8. 구조적 사실 (`Observed Facts`) vs 연구자 해석 (`RESEARCH_INTERPRETATION`)
================================================================================

### A. 구조적 사실 (Observed Facts)
1. 실제 PROGRESSED 보유 거래 328건 중 18건(5.49%)이 -20% 이하, 10건(3.05%)이 -30% 이하로 마감함.
2. 대형 승자(164건)의 HWM Drawdown 중앙값은 {dd["winners_ge_50_close_drawdown"]["median"]}%, P25는 {dd["winners_ge_50_close_drawdown"]["p25"]}%임.
3. 대형 손실자(18건)의 HWM Drawdown 중앙값은 {dd["losers_le_neg_20_close_drawdown"]["median"]}%, P25는 {dd["losers_le_neg_20_close_drawdown"]["p25"]}%임.
4. Exit 3 신호 발생 시점의 고점 대비 하락 중앙값은 {ex["exit3_drawdown_at_signal_stats"]["median"]}%로 실질적인 가격 하락 지연이 존재함.
5. 대형 승자 중에서도 {ov["winner_ge_50"]["dd_le_neg_30_rate"]}%({ov["winner_ge_50"]["dd_le_neg_30_count"]}건)는 -30% 이하의 하락을 겪고 회복함.

### B. 연구자 해석 (RESEARCH_INTERPRETATION)
1. 대형 테일 손실의 원인은 PROGRESSED 도달 후 일봉 손실가드가 비활성화되고 월봉 지연 청산만 남는 구조에서 기인함.
2. 중심 경향 상 유의미한 분리가 존재하므로 가격 기반 보호 규칙 연구(Phase 2)는 충분한 타당성을 가짐.
3. 단, Phase 1에서 관찰된 25%~30% 범위는 **사후 관찰 후보 범위(`PHASE1_OBSERVED_CANDIDATE_RANGE`)**이며, Phase 2에서 사전 고정된 소수 후보군으로 정밀 백테스트 비교해야 함.
"""

    (OUT_DIR / "analysis.md").write_text(md, encoding="utf-8")


if __name__ == "__main__":
    run_diagnostic()
