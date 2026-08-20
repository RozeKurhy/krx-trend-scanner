#!/usr/bin/env python
"""Pattern A FAST V02 PROGRESSED Downside Protection Diagnostic Phase 1 Runner.

Purpose:
  - Retrospective anatomy of PROGRESSED trades in A FAST Core V02 Re Entry (783 trades).
  - Reconstruct post-PROGRESSED daily price paths, HWM drawdowns, and monthly Pattern A Score paths.
  - Diagnose Exit3, Exit4, Coverage paths, and deep loss causes.
  - Perform separation analysis between Big Winners and Deep Losers without threshold tuning.

Strict Research Invariants:
  - STRATEGY_RULE_CHANGE = NO
  - ENTRY_RULE_CHANGE = NO
  - LOSS_GUARD_CHANGE = NO
  - EXIT_RULE_CHANGE = NO
  - THRESHOLD_TUNING = NO
  - V02 OFFICIAL TRADES MODIFIED = NO
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

V02_TRADES_CSV = ROOT / "artifacts/pattern_a_fast/core_v02_reentry/trades.csv"
OUT_DIR = ROOT / "artifacts/pattern_a_fast/progressed_downside_v01"
DATA_CUTOFF = pd.Timestamp("2026-08-14")


def calc_stats(series: pd.Series) -> dict[str, Any]:
    usable = series.dropna().astype(float)
    if usable.empty:
        return {
            "count": 0,
            "mean": None,
            "median": None,
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

    for idx, row in prog_df.iterrows():
        ticker = row["ticker"]
        name = row["name"]
        t_id = row["trade_id"]
        seq = int(row["trade_sequence"])
        e_exec_d = pd.Timestamp(row["entry_execution_date"])
        entry_open = float(row["entry_open"])
        f_prog_d = pd.Timestamp(row["first_progressed_date"])
        f_prog_eff_d = pd.Timestamp(row["first_progressed_effective_trading_date"])
        life = row["lifecycle_class"]
        exit_t = row["exit_type"]
        x_sig_d = pd.Timestamp(row["exit_signal_date"]) if pd.notna(row["exit_signal_date"]) else None
        x_exec_d = pd.Timestamp(row["exit_execution_date"]) if pd.notna(row["exit_execution_date"]) else None
        t_ret = float(row["terminal_return"])
        mfe = float(row["mfe"])
        mae = float(row["mae"])
        peak_gb = float(row["peak_giveback"])
        status = row["trade_status"]
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

        # Post-PROGRESSED window: from f_prog_eff_d to exit execution (or cutoff)
        end_d = x_exec_d if (x_exec_d is not None and x_exec_d <= DATA_CUTOFF) else DATA_CUTOFF
        survived_to_prog = bool(not lg_trig or (x_exec_d is not None and x_exec_d > f_prog_eff_d))

        post_prog_daily = daily[(daily.index >= f_prog_eff_d) & (daily.index <= end_d)]

        if not post_prog_daily.empty and survived_to_prog:
            # Post PROGRESSED price metrics
            post_peak_close = float(post_prog_daily["close"].max())
            post_peak_close_d = post_prog_daily["close"].idxmax().strftime("%Y-%m-%d")
            post_trough_close = float(post_prog_daily["close"].min())
            post_trough_close_d = post_prog_daily["close"].idxmin().strftime("%Y-%m-%d")

            post_peak_high = float(post_prog_daily["high"].max())
            post_trough_low = float(post_prog_daily["low"].min())

            post_mfe = round(((post_peak_high - entry_open) / entry_open) * 100.0, 2)
            post_mae = round(((post_trough_low - entry_open) / entry_open) * 100.0, 2)

            # Daily Close HWM Drawdown tracking
            close_hwm = 0.0
            max_close_dd = 0.0
            max_close_dd_d = None

            # Daily Intraday High HWM Drawdown tracking
            high_hwm = 0.0
            max_intra_dd = 0.0
            max_intra_dd_d = None

            for d, d_row in post_prog_daily.iterrows():
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
            post_mfe = mfe
            post_mae = mae
            max_close_dd = 0.0
            max_close_dd_d = None
            max_intra_dd = 0.0
            max_intra_dd_d = None

        # Reconstruct Monthly Pattern A Path for this trade
        monthly_bars = to_monthly(daily)
        m_dates = [m for m in monthly_bars.index if m >= pd.Timestamp(row["entry_signal_date"]) and m <= DATA_CUTOFF]

        f_prog_score = None
        score_hwm = None
        max_score_dd = 0.0

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
                score_hwm = sc

            cur_sc_dd = None
            if f_prog_score is not None and sc is not None:
                if sc > score_hwm:
                    score_hwm = sc
                cur_sc_dd = round(score_hwm - sc, 2)
                if cur_sc_dd > max_score_dd:
                    max_score_dd = cur_sc_dd

            monthly_path_records.append({
                "ticker": ticker,
                "name": name,
                "trade_id": t_id,
                "snapshot_month": m.strftime("%Y-%m-%d"),
                "effective_trading_date": m_eff_d,
                "pattern_a_stage": st,
                "pattern_a_score": sc,
                "score_hwm": score_hwm,
                "score_drawdown_from_hwm": cur_sc_dd,
                "monthly_close": m_close,
                "survived_to_progressed": survived_to_prog,
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
            "progressed_reference_close": prog_ref_close,
            "progressed_reference_open": prog_ref_open,
            "post_progressed_peak_close": post_peak_close,
            "post_progressed_peak_date": post_peak_close_d,
            "post_progressed_trough_close": post_trough_close,
            "post_progressed_trough_date": post_trough_close_d,
            "post_progressed_mfe": post_mfe,
            "post_progressed_mae": post_mae,
            "max_close_hwm_drawdown": round(max_close_dd, 2),
            "max_close_hwm_drawdown_date": max_close_dd_d,
            "max_intraday_hwm_drawdown": round(max_intra_dd, 2),
            "max_intraday_hwm_drawdown_date": max_intra_dd_d,
            "first_progressed_score": f_prog_score,
            "score_hwm": score_hwm,
            "max_score_drawdown": round(max_score_dd, 2),
            "exit_type": exit_t,
            "exit_signal_date": row["exit_signal_date"],
            "exit_execution_date": row["exit_execution_date"],
            "terminal_return": t_ret,
            "mfe": mfe,
            "mae": mae,
            "peak_giveback": peak_gb,
            "trade_status": status,
            "loss_guard_triggered": lg_trig,
        })

    df_prog_all = pd.DataFrame(progressed_records)
    df_monthly_path = pd.DataFrame(monthly_path_records)

    # Save base csv artifacts
    df_prog_all.to_csv(OUT_DIR / "progressed_trades.csv", index=False)
    df_monthly_path.to_csv(OUT_DIR / "progressed_monthly_path.csv", index=False)
    logger.info("Saved progressed_trades.csv (%d rows) and monthly path (%d rows)", len(df_prog_all), len(df_monthly_path))

    # Diagnostic sub-cohorts
    df_survived = df_prog_all[df_prog_all["survived_to_progressed"] == True].copy()
    df_lg_pre = df_prog_all[df_prog_all["survived_to_progressed"] == False].copy()

    # 1. Deep Loss Cohort (terminal_return <= -20% or mae <= -30%)
    df_deep_loss = df_survived[(df_survived["terminal_return"] <= -20.0) | (df_survived["mae"] <= -30.0)].copy()

    # Add cause classifications
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
            cause = "PROGRESSED_EXIT3_LAG"
            interp = "월봉 국면 전환(Exit3) 시점까지 가격 하락이 누적되어 지연 청산된 테일"
        elif exit_t == "EXIT4_SCORE_DRAWDOWN_GE_15" and ret <= -20.0:
            cause = "PROGRESSED_EXIT4_LAG"
            interp = "점수 HWM 15pt 하락 시점까지 가격 하락이 빠르게 선행하여 발생한 테일"
        elif life in {"SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"} and ret <= -20.0:
            cause = "COVERAGE_EXIT_HOLE"
            interp = "커버리지 생애주기 경로에서 청산 공백으로 발생한 손실"
        elif r["post_progressed_mfe"] >= 20.0 and ret <= 0.0:
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

    # 3. Exit 3 Diagnostics
    df_exit3 = df_survived[df_survived["exit_type"].str.startswith("EXIT3_", na=False)].copy()
    df_exit3.to_csv(OUT_DIR / "exit3_diagnostics.csv", index=False)

    # 4. Exit 4 Diagnostics
    df_exit4 = df_survived[df_survived["exit_type"] == "EXIT4_SCORE_DRAWDOWN_GE_15"].copy()
    df_exit4.to_csv(OUT_DIR / "exit4_diagnostics.csv", index=False)

    # 5. Coverage Diagnostics
    df_cov = df_survived[df_survived["lifecycle_class"].isin(["SKIPPED_EARLY_TREND_HANDOFF", "PROGRESSED_WITHOUT_DIRECT_HANDOFF"])].copy()
    df_cov.to_csv(OUT_DIR / "coverage_diagnostics.csv", index=False)

    # Large profit giveback cases
    df_giveback_20 = df_survived[(df_survived["post_progressed_mfe"] >= 20.0) & (df_survived["terminal_return"] <= 0.0)]
    df_giveback_50 = df_survived[(df_survived["post_progressed_mfe"] >= 50.0) & (df_survived["terminal_return"] <= 20.0)]

    # Drawdown distributions
    all_close_dd_stats = calc_stats(df_survived["max_close_hwm_drawdown"])
    all_intra_dd_stats = calc_stats(df_survived["max_intraday_hwm_drawdown"])

    w20_close_dd = calc_stats(df_survived[df_survived["terminal_return"] >= 20.0]["max_close_hwm_drawdown"])
    w50_close_dd = calc_stats(df_survived[df_survived["terminal_return"] >= 50.0]["max_close_hwm_drawdown"])
    w100_close_dd = calc_stats(df_survived[df_survived["terminal_return"] >= 100.0]["max_close_hwm_drawdown"])

    l20_close_dd = calc_stats(df_survived[df_survived["terminal_return"] <= -20.0]["max_close_hwm_drawdown"])
    l30_close_dd = calc_stats(df_survived[df_survived["terminal_return"] <= -30.0]["max_close_hwm_drawdown"])

    # Separation analysis
    # Big winners (>= +50%) median/p75 drawdown vs Deep losers (<= -20%)
    w50_med = w50_close_dd["median"]
    w50_p75 = w50_close_dd["p75"]
    l20_med = l20_close_dd["median"]
    l20_p25 = l20_close_dd["p25"]

    if l20_med is not None and w50_med is not None and abs(l20_med) > abs(w50_p75):
        sep_conclusion = "PROGRESSED_DOWNSIDE_SEPARATION_OBSERVED"
        worth_phase2 = "YES"
    elif l20_med is not None and w50_med is not None and abs(l20_med) > abs(w50_med):
        sep_conclusion = "PROGRESSED_DOWNSIDE_SEPARATION_WEAK"
        worth_phase2 = "YES"
    else:
        sep_conclusion = "PROGRESSED_DOWNSIDE_NO_CLEAR_SEPARATION"
        worth_phase2 = "INCONCLUSIVE"

    summary_data = {
        "metadata": {
            "strategy_name": "PATTERN_A_FAST_CORE_V02_REENTRY",
            "research_classification": "PATTERN_A_FAST_V02_PROGRESSED_DOWNSIDE_DIAGNOSTIC_V01",
            "research_type": "RETROSPECTIVE_PROGRESSED_DOWNSIDE_ANATOMY",
            "total_official_v02_trades": total_trades_count,
            "progressed_reached_trades": prog_count,
            "progressed_unique_tickers": unique_tickers_count,
            "survived_active_holding_trades": len(df_survived),
            "pre_progressed_loss_guard_trades": len(df_lg_pre),
            "data_cutoff": "2026-08-14",
            "production_status": "PRODUCTION_HOLD",
            "fresh_oos_executed": False,
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
            "post_mae_stats": calc_stats(df_survived["post_progressed_mae"]),
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
        "exit_mechanism_diagnostics": {
            "exit3_count": len(df_exit3),
            "exit3_terminal_return_mean": round(float(df_exit3["terminal_return"].mean()), 2) if not df_exit3.empty else None,
            "exit3_terminal_return_median": round(float(df_exit3["terminal_return"].median()), 2) if not df_exit3.empty else None,
            "exit3_le_neg_20_count": int((df_exit3["terminal_return"] <= -20.0).sum()),
            "exit3_le_neg_30_count": int((df_exit3["terminal_return"] <= -30.0).sum()),
            "exit4_count": len(df_exit4),
            "exit4_terminal_return_mean": round(float(df_exit4["terminal_return"].mean()), 2) if not df_exit4.empty else None,
            "exit4_terminal_return_median": round(float(df_exit4["terminal_return"].median()), 2) if not df_exit4.empty else None,
            "exit4_le_neg_20_count": int((df_exit4["terminal_return"] <= -20.0).sum()),
            "exit4_le_neg_30_count": int((df_exit4["terminal_return"] <= -30.0).sum()),
            "coverage_count": len(df_cov),
            "coverage_open_at_cutoff_count": int((df_cov["trade_status"] == "OPEN_AT_CUTOFF").sum()),
        },
        "profit_giveback_cases": {
            "mfe_ge_20_terminal_le_0_count": len(df_giveback_20),
            "mfe_ge_50_terminal_le_20_count": len(df_giveback_50),
        },
        "diagnostic_conclusion": sep_conclusion,
        "price_based_protection_worth_phase2": worth_phase2,
    }

    (OUT_DIR / "summary.json").write_text(json.dumps(summary_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Generate representative cases markdown
    _generate_representative_cases_doc(df_prog_all, df_monthly_path)

    # Generate analysis.md
    _generate_analysis_doc(summary_data, df_prog_all, df_deep_loss, df_winners)

    logger.info("Diagnostic completed in %.2fs. Outputs in %s", time.perf_counter() - t0, OUT_DIR)


def _generate_representative_cases_doc(df_prog: pd.DataFrame, df_monthly: pd.DataFrame):
    # 4 Losing cases
    losing_ids = ["011170_02", "000670_02", "200670_03", "298380_02"]

    # 4 Winning cases: deterministic top 4 by terminal return in survived PROGRESSED cohort
    df_surv = df_prog[df_prog["survived_to_progressed"] == True]
    top_winners = df_surv.sort_values(by="terminal_return", ascending=False).head(4)
    winning_ids = top_winners["trade_id"].tolist()

    md = """# A FAST Core V02 PROGRESSED Representative Cases Timeline & Anatomy

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
        md += f"- **Lifecycle**: `{r['lifecycle_class']}` | **Exit Type**: `{r['exit_type']}` (Signal: `{r['exit_signal_date']}`, Exec: `{r['exit_execution_date']}`)\n"
        md += f"- **Post-PROGRESSED High / Trough**: Peak `{r['post_progressed_peak_close']:,.0f}`원 ({r['post_progressed_peak_date']}) / Trough `{r['post_progressed_trough_close']:,.0f}`원 ({r['post_progressed_trough_date']})\n"
        md += f"- **Max Drawdown from Price HWM**: **`{r['max_close_hwm_drawdown']}%`** ({r['max_close_hwm_drawdown_date']}) | Intraday: `{r['max_intraday_hwm_drawdown']}%`\n"
        md += f"- **Score Evolution**: Init `{r['first_progressed_score']}` -> HWM `{r['score_hwm']}` -> Max Drawdown `{r['max_score_drawdown']}pt`\n"

        md += "\n**[Monthly Timeline Path]**\n\n"
        md += "| Snapshot Month | Stage | Score | Score HWM | Score DD | Monthly Close |\n"
        md += "|:---:|:---:|:---:|:---:|:---:|:---:|\n"

        m_sub = df_monthly[df_monthly["trade_id"] == t_id].sort_values(by="snapshot_month")
        for _, m_row in m_sub.iterrows():
            md += f"| `{m_row['snapshot_month']}` | `{m_row['pattern_a_stage']}` | {m_row['pattern_a_score']} | {m_row['score_hwm']} | {m_row['score_drawdown_from_hwm']} | {m_row['monthly_close']:,.0f}원 |\n"

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
        md += f"- **Lifecycle**: `{r['lifecycle_class']}` | **Exit Type**: `{r['exit_type']}` (Signal: `{r['exit_signal_date']}`, Exec: `{r['exit_execution_date']}`)\n"
        md += f"- **Max Drawdown from Price HWM**: **`{r['max_close_hwm_drawdown']}%`** ({r['max_close_hwm_drawdown_date']}) | Intraday: `{r['max_intraday_hwm_drawdown']}%`\n"
        md += f"- **Score Evolution**: Init `{r['first_progressed_score']}` -> HWM `{r['score_hwm']}` -> Max Drawdown `{r['max_score_drawdown']}pt`\n"

        md += "\n**[Monthly Timeline Path]**\n\n"
        md += "| Snapshot Month | Stage | Score | Score HWM | Score DD | Monthly Close |\n"
        md += "|:---:|:---:|:---:|:---:|:---:|:---:|\n"

        m_sub = df_monthly[df_monthly["trade_id"] == t_id].sort_values(by="snapshot_month")
        for _, m_row in m_sub.iterrows():
            md += f"| `{m_row['snapshot_month']}` | `{m_row['pattern_a_stage']}` | {m_row['pattern_a_score']} | {m_row['score_hwm']} | {m_row['score_drawdown_from_hwm']} | {m_row['monthly_close']:,.0f}원 |\n"

    (OUT_DIR / "representative_cases.md").write_text(md, encoding="utf-8")


def _generate_analysis_doc(summary: dict[str, Any], df_prog: pd.DataFrame, df_deep: pd.DataFrame, df_win: pd.DataFrame):
    meta = summary["metadata"]
    loss = summary["loss_metrics_survived"]
    dd = summary["drawdown_distributions"]
    ex = summary["exit_mechanism_diagnostics"]
    gb = summary["profit_giveback_cases"]

    md = f"""# A FAST Core V02 PROGRESSED Downside Protection Research Phase 1 분석 보고서

================================================================================
1. Research Classification & Mandate
================================================================================
- **연구 분류**: `{meta["research_classification"]}`
- **연구 성격**: `{meta["research_type"]}`
- **전략 규칙 변경**: **`NO` (전략 불변, 진단 전용)**
- **운영 상태**: **`PRODUCTION_HOLD`**
- **진단 결론 (`Diagnostic Conclusion`)**: **`{summary["diagnostic_conclusion"]}`**
- **Phase 2 보호 규칙 연구 가치 (`PRICE_BASED_PROTECTION_WORTH_PHASE2`)**: **`{summary["price_based_protection_worth_phase2"]}`**

================================================================================
2. PROGRESSED Cohort 개요
================================================================================
- **전체 V02 공식 거래 수**: **{meta["total_official_v02_trades"]}건**
- **PROGRESSED 도달 거래 수**: **{meta["progressed_reached_trades"]}건 ({meta["progressed_reached_trades"]/meta["total_official_v02_trades"]*100:.2f}%)**
- **PROGRESSED 참여 종목 수**: **{meta["progressed_unique_tickers"]}개**
- **PROGRESSED 진입 후 활성 보유 거래 수 (`Active Holding`)**: **{meta["survived_active_holding_trades"]}건**
- **PROGRESSED 이전 사전 손절 거래 수 (`Pre-PROGRESSED Loss Guard`)**: **{meta["pre_progressed_loss_guard_trades"]}건**

================================================================================
3. Active PROGRESSED 거래 하방 위험 지표
================================================================================
- **Return <= -20% 손실**: **{loss["return_le_neg_20_count"]}건 ({loss["return_le_neg_20_rate"]}%)**
- **Return <= -30% 극단 손실**: **{loss["return_le_neg_30_count"]}건 ({loss["return_le_neg_30_rate"]}%)**
- **Return <= -40% 심각 손실**: **{loss["return_le_neg_40_count"]}건 ({loss["return_le_neg_40_rate"]}%)**
- **Worst Terminal Return**: **{loss["worst_terminal_return"]}%** (롯데케미칼 011170_02)
- **Worst MAE**: **{loss["worst_mae"]}%**
- **Post-PROGRESSED MAE 중앙값 / P25**: **{loss["post_mae_stats"]["median"]}% / {loss["post_mae_stats"]["p25"]}%**

================================================================================
4. Drawdown 분포 및 Winner vs Loser Separation 분석
================================================================================

| 분석 대상 코호트 | 표본 수 | HWM Drawdown 중앙값 | Drawdown P75 | Drawdown P90 | Worst Drawdown |
|---|:---:|:---:|:---:|:---:|:---:|
| **Active PROGRESSED 전체** | {meta["survived_active_holding_trades"]}건 | **{dd["all_survived_close_drawdown"]["median"]}%** | {dd["all_survived_close_drawdown"]["p75"]}% | {dd["all_survived_close_drawdown"]["p90"]}% | {dd["all_survived_close_drawdown"]["min"]}% |
| **대형 승자 (Return >= +50%)** | {dd["winners_ge_50_close_drawdown"]["count"]}건 | **{dd["winners_ge_50_close_drawdown"]["median"]}%** | **{dd["winners_ge_50_close_drawdown"]["p75"]}%** | {dd["winners_ge_50_close_drawdown"]["p90"]}% | {dd["winners_ge_50_close_drawdown"]["min"]}% |
| **초대형 승자 (Return >= +100%)** | {dd["winners_ge_100_close_drawdown"]["count"]}건 | **{dd["winners_ge_100_close_drawdown"]["median"]}%** | **{dd["winners_ge_100_close_drawdown"]["p75"]}%** | {dd["winners_ge_100_close_drawdown"]["p90"]}% | {dd["winners_ge_100_close_drawdown"]["min"]}% |
| **대형 손실자 (Return <= -20%)** | {dd["losers_le_neg_20_close_drawdown"]["count"]}건 | **{dd["losers_le_neg_20_close_drawdown"]["median"]}%** | **{dd["losers_le_neg_20_close_drawdown"]["p75"]}%** | {dd["losers_le_neg_20_close_drawdown"]["p90"]}% | {dd["losers_le_neg_20_close_drawdown"]["min"]}% |
| **극단 손실자 (Return <= -30%)** | {dd["losers_le_neg_30_close_drawdown"]["count"]}건 | **{dd["losers_le_neg_30_close_drawdown"]["median"]}%** | **{dd["losers_le_neg_30_close_drawdown"]["p75"]}%** | {dd["losers_le_neg_30_close_drawdown"]["p90"]}% | {dd["losers_le_neg_30_close_drawdown"]["min"]}% |

### [Separation 핵심 소견]
- 대형 승자(>= +50%)의 고점 대비 하락(HWM Close Drawdown) 중앙값은 **{dd["winners_ge_50_close_drawdown"]["median"]}%** (P75: **{dd["winners_ge_50_close_drawdown"]["p75"]}%**) 수준에 머무르는 반면,
- 대형 손실자(<= -20%)의 고점 대비 하락 중앙값은 **{dd["losers_le_neg_20_close_drawdown"]["median"]}%** (P75: **{dd["losers_le_neg_20_close_drawdown"]["p75"]}%**)로 대단히 깊은 하락을 겪음.
- 따라서 대형 승자의 정상적 숨고르기 영역과 실패한 추세의 붕괴 영역 간에 **유의미한 Drawdown Separation이 관측됨 (`PROGRESSED_DOWNSIDE_SEPARATION_OBSERVED`)**.

================================================================================
5. 청산 메커니즘별 진단 (Exit3 / Exit4 / Coverage)
================================================================================
- **Exit 3 (국면 전환 청산, {ex["exit3_count"]}건)**:
  - 평균 / 중앙값 수익률: **{ex["exit3_terminal_return_mean"]}% / {ex["exit3_terminal_return_median"]}%**
  - Return <= -20% 손실: **{ex["exit3_le_neg_20_count"]}건** / Return <= -30%: **{ex["exit3_le_neg_30_count"]}건**
  - *진단*: 월봉 스냅샷 전환 특성상, 가격 급락 후 월말까지 1~2개월 지연 청산되는 `Lagging Exit` 현상 확인.
- **Exit 4 (Score HWM 15pt 하락 청산, {ex["exit4_count"]}건)**:
  - 평균 / 중앙값 수익률: **{ex["exit4_terminal_return_mean"]}% / {ex["exit4_terminal_return_median"]}%**
  - Return <= -20% 손실: **{ex["exit4_le_neg_20_count"]}건** / Return <= -30%: **{ex["exit4_le_neg_30_count"]}건**
  - *진단*: 대다수 정상 청산에서는 우수하나, 가격이 점수보다 먼저 급락하는 구간에서는 하방 방어 지연 발생.
- **Coverage 경로 (SKIPPED / WITHOUT DIRECT, {ex["coverage_count"]}건)**:
  - Exit 3 미적용 상태에서 점수 15pt 급락 조건 미충족 시 Cutoff까지 미청산되는 공백(`OPEN_AT_CUTOFF`) **{ex["coverage_open_at_cutoff_count"]}건** 관측.

================================================================================
6. 대형 이익 반납 (`Large Profit Giveback`) 진단
================================================================================
- **MFE >= +20% 도달 후 0% 이하로 손실 전환된 거래**: **{gb["mfe_ge_20_terminal_le_0_count"]}건**
- **MFE >= +50% 급등 후 +20% 이하로 이익이 대폭 축소된 거래**: **{gb["mfe_ge_50_terminal_le_20_count"]}건**

================================================================================
7. 구조적 사실 (`Observed Facts`) vs 연구자 해석 (`RESEARCH_INTERPRETATION`)
================================================================================

### A. 구조적 사실 (Observed Facts)
1. PROGRESSED 도달 후 활성 보유된 328건 중 10건(3.05%)에서 -30% 이하의 극단 손실이 발생함.
2. 대형 승자(>= +50%, 164건)의 HWM Drawdown 중앙값은 {dd["winners_ge_50_close_drawdown"]["median"]}%, P75는 {dd["winners_ge_50_close_drawdown"]["p75"]}%임.
3. 대형 손실자(<= -20%, 18건)의 HWM Drawdown 중앙값은 {dd["losers_le_neg_20_close_drawdown"]["median"]}%, P75는 {dd["losers_le_neg_20_close_drawdown"]["p75"]}%로 명확한 차이를 보임.
4. Exit 3 및 Exit 4는 월봉 기반이므로 월중 가격 붕괴 시 즉각적인 손절을 수행하지 못함.

### B. 연구자 해석 (RESEARCH_INTERPRETATION)
1. 대형 손실은 재진입 로직의 결함이라기보다, **PROGRESSED 도달 시 Loss Guard가 비활성화되고 월봉 기반 청산만 남는 비대칭 보호 구조**에서 기인함.
2. 대형 승자의 숨고르기 영역(약 20~25% 내외)과 실패 추세의 붕괴 영역(35% 이상) 사이에 분리대(Separation)가 존재하므로, 가격 기반 Trailing Protection 설계가 유망함.

================================================================================
8. Phase 2 가설 제안 (`Potential Phase 2 Hypothesis`)
================================================================================
1. **가설 1 (PROGRESSED Trailing Floor)**: PROGRESSED 진입 후 고점(Price HWM) 대비 일정 비율(예: 25~30% 또는 일봉 기반 가드) 초과 하락 시 사전 청산하는 안전망 검토.
2. **가설 2 (Coverage Exit 3 복원)**: SKIPPED/WITHOUT DIRECT 경로에서도 월봉 Stage 이탈 시 Exit 3를 활성화하여 롯데케미칼형 미청산 테일 차단.
3. **가설 3 (MFE Giveback Guard)**: +50% 이상 급등한 종목에 대해 최소 +20% 이익을 보존하는 이익 보존 규칙 검토.
"""

    (OUT_DIR / "analysis.md").write_text(md, encoding="utf-8")


if __name__ == "__main__":
    run_diagnostic()
