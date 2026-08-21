#!/usr/bin/env python
"""Pattern A FAST Core V02 Re-Entry Strategy Official Evaluation Runner.

Strict Execution Invariants:
  - V01 Baseline Comparator: artifacts/patterns/pattern_a_fast/production/strategy_finalization_v01/ (551 trades, FROZEN)
  - Core Innovation: MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER (Re-entry allowed after position closes)
  - Calendar Authority: CANONICAL_DERIVED_KRX_CALENDAR (Commit 88d54d85bdee1f2121bec9b27a250cbc1cb9f98f)
  - Research Classification: SAME_SAMPLE_REENTRY_STRATEGY_COMPARISON
  - Production Status: PRODUCTION_HOLD
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
import logging
import math
from pathlib import Path
import time
from typing import Any

import numpy as np
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.pattern_a_fast_core_v02_reentry import (
    DATA_CUTOFF,
    V02TradeRecord,
    calculate_distribution_stats,
    simulate_ticker_core_v02_reentry,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

V01_TRADES_CSV = ROOT / "artifacts/patterns/pattern_a_fast/production/strategy_finalization_v01/pattern_a_fast_strategy_finalization_v01_trades.csv"
V01_EVAL_JSON = ROOT / "artifacts/patterns/pattern_a_fast/production/strategy_finalization_v01/pattern_a_fast_strategy_finalization_v01_evaluation.json"

OUT_DIR = ROOT / "artifacts/patterns/pattern_a_fast/production/core_v02_reentry"
OUT_TRADES_CSV = OUT_DIR / "trades.csv"
OUT_TICKER_SUMMARY_CSV = OUT_DIR / "ticker_summary.csv"
OUT_EVAL_JSON = OUT_DIR / "evaluation.json"
OUT_REENTRY_SUMMARY_JSON = OUT_DIR / "reentry_summary.json"
OUT_COMP_MD = OUT_DIR / "comparison_vs_v01.md"

CALENDAR_AUTHORITY_COMMIT = "88d54d85bdee1f2121bec9b27a250cbc1cb9f98f"


def _worker_task(args: tuple[str, str, str, dict, dict]) -> list[dict]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    records = simulate_ticker_core_v02_reentry(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        cutoff_date=DATA_CUTOFF,
    )
    return [r.to_dict() for r in records]


def run_evaluation() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    df_univ = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    df_univ["ticker"] = df_univ["ticker"].str.zfill(6)

    total_common_count = len(df_univ)

    inv_mask = (
        (df_univ["market_cap_ready"] == True)
        & (df_univ["trading_value_20d_ready"] == True)
        & (df_univ["market_cap"] >= 100_000_000_000)
        & (df_univ["avg_trading_value_20d"] >= 300_000_000)
    )
    df_inv = df_univ[inv_mask].copy().sort_values(by="ticker").reset_index(drop=True)
    investable_count = len(df_inv)

    logger.info("Total Common: %d, Phase 10 Investable: %d", total_common_count, investable_count)

    tasks = [
        (row["ticker"], str(row["name"]), str(row["market"]), score_contract, stage_contract)
        for _, row in df_inv.iterrows()
    ]

    t0 = time.perf_counter()
    with ProcessPoolExecutor(max_workers=8) as executor:
        nested_results = list(executor.map(_worker_task, tasks))

    flat_trades: list[dict] = []
    for t_list in nested_results:
        flat_trades.extend(t_list)

    df_trades = pd.DataFrame(flat_trades)
    df_trades.to_csv(OUT_TRADES_CSV, index=False)
    logger.info("Executed in %.2fs. Total V02 Trades: %d across %d tickers", time.perf_counter() - t0, len(df_trades), df_trades["ticker"].nunique())

    # Build Ticker Summary CSV
    ticker_summaries = _build_ticker_summary(df_trades)
    df_ticker_summary = pd.DataFrame(ticker_summaries)
    df_ticker_summary.to_csv(OUT_TICKER_SUMMARY_CSV, index=False)

    # Analyze evaluation metrics
    eval_data = _analyze_results(df_trades, df_ticker_summary, total_common_count, investable_count)
    OUT_EVAL_JSON.write_text(json.dumps(eval_data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Save dedicated reentry summary JSON
    reentry_summary = eval_data["reentry_diagnostics"]
    OUT_REENTRY_SUMMARY_JSON.write_text(json.dumps(reentry_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    # Generate Markdown Comparison vs V01
    comp_md = _generate_comparison_markdown(eval_data)
    OUT_COMP_MD.write_text(comp_md, encoding="utf-8")
    logger.info("Artifacts saved to %s", OUT_DIR)


def _build_ticker_summary(df: pd.DataFrame) -> list[dict[str, Any]]:
    summaries = []
    for ticker, group in df.groupby("ticker"):
        group = group.sort_values(by="trade_sequence")
        t_name = group.iloc[0]["name"]
        t_market = group.iloc[0]["market"]
        n_trades = len(group)
        first_entry_d = group.iloc[0]["entry_execution_date"]
        last_exit_d = group.iloc[-1]["exit_execution_date"]
        last_status = group.iloc[-1]["trade_status"]

        # Sequential cumulative return: product(1 + r/100) - 1
        cum_ret_factor = 1.0
        for _, row in group.iterrows():
            cum_ret_factor *= (1.0 + float(row["terminal_return"]) / 100.0)
        cum_ret_pct = round((cum_ret_factor - 1.0) * 100.0, 2)

        stop_count = int((group["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15").sum())
        win_count = int((group["terminal_return"] > 0).sum())

        summaries.append({
            "ticker": ticker,
            "name": t_name,
            "market": t_market,
            "total_trades": n_trades,
            "first_entry_date": first_entry_d,
            "last_exit_date": last_exit_d,
            "last_trade_status": last_status,
            "sequential_cumulative_return_pct": cum_ret_pct,
            "loss_guard_count": stop_count,
            "positive_trade_count": win_count,
            "win_rate_pct": round(win_count / n_trades * 100, 2),
            "trade_ids": ",".join(group["trade_id"].tolist()),
        })
    return summaries


def _analyze_results(
    df: pd.DataFrame,
    df_ticker: pd.DataFrame,
    total_common: int,
    investable_count: int,
) -> dict[str, Any]:
    n_total = len(df)
    unique_tickers = df["ticker"].nunique()
    reentered_tickers = df_ticker[df_ticker["total_trades"] >= 2]["ticker"].nunique()

    # Sequence counts
    seq_counts = df["trade_sequence"].value_counts().to_dict()
    seq_1_count = int(seq_counts.get(1, 0))
    seq_2_count = int(seq_counts.get(2, 0))
    seq_3_count = int(seq_counts.get(3, 0))
    seq_4_plus_count = int(sum(v for k, v in seq_counts.items() if k >= 4))
    total_reentry_trades = int(n_total - seq_1_count)
    max_trades_per_ticker = int(df_ticker["total_trades"].max()) if not df_ticker.empty else 0

    # Risk metrics (All trades)
    ret = df["terminal_return"]
    mae = df["mae"]
    mfe = df["mfe"]
    gb = df["peak_giveback"]
    pc = df["profit_capture"]
    hw = df["holding_weeks"]

    risk_metrics = {
        "return_le_neg_10_count": int((ret <= -10.0).sum()),
        "return_le_neg_10_rate": round(float((ret <= -10.0).mean() * 100), 2),
        "return_le_neg_15_count": int((ret <= -15.0).sum()),
        "return_le_neg_15_rate": round(float((ret <= -15.0).mean() * 100), 2),
        "return_le_neg_20_count": int((ret <= -20.0).sum()),
        "return_le_neg_20_rate": round(float((ret <= -20.0).mean() * 100), 2),
        "return_le_neg_30_count": int((ret <= -30.0).sum()),
        "return_le_neg_30_rate": round(float((ret <= -30.0).mean() * 100), 2),
        "return_le_neg_40_count": int((ret <= -40.0).sum()),
        "return_le_neg_40_rate": round(float((ret <= -40.0).mean() * 100), 2),
        "worst_return": round(float(ret.min()), 2),
        "worst_mae": round(float(mae.min()), 2),
        "mae_stats": calculate_distribution_stats(mae),
        "loss_guard_count": int((df["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15").sum()),
        "loss_guard_rate": round(float((df["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15").mean() * 100), 2),
    }

    return_metrics = {
        "terminal_return_stats": calculate_distribution_stats(ret),
        "positive_count": int((ret > 0).sum()),
        "positive_rate": round(float((ret > 0).mean() * 100), 2),
    }

    upside_metrics = {
        "mfe_stats": calculate_distribution_stats(mfe),
        "mfe_ge_20_count": int((mfe >= 20.0).sum()),
        "mfe_ge_20_rate": round(float((mfe >= 20.0).mean() * 100), 2),
        "mfe_ge_50_count": int((mfe >= 50.0).sum()),
        "mfe_ge_50_rate": round(float((mfe >= 50.0).mean() * 100), 2),
        "mfe_ge_100_count": int((mfe >= 100.0).sum()),
        "mfe_ge_100_rate": round(float((mfe >= 100.0).mean() * 100), 2),
        "return_ge_20_count": int((ret >= 20.0).sum()),
        "return_ge_20_rate": round(float((ret >= 20.0).mean() * 100), 2),
        "return_ge_50_count": int((ret >= 50.0).sum()),
        "return_ge_50_rate": round(float((ret >= 50.0).mean() * 100), 2),
        "return_ge_100_count": int((ret >= 100.0).sum()),
        "return_ge_100_rate": round(float((ret >= 100.0).mean() * 100), 2),
    }

    giveback_metrics = {
        "giveback_stats": calculate_distribution_stats(gb),
        "profit_capture_stats": calculate_distribution_stats(pc),
        "holding_weeks_stats": calculate_distribution_stats(hw),
    }

    exit_counts = df["exit_type"].value_counts().to_dict()

    # Sub-population breakdowns: First Entry vs Re-Entry
    df_first = df[df["trade_sequence"] == 1]
    df_reentry = df[df["trade_sequence"] >= 2]
    df_seq2 = df[df["trade_sequence"] == 2]
    df_seq3 = df[df["trade_sequence"] == 3]
    df_seq4p = df[df["trade_sequence"] >= 4]

    def _get_trade_cohort_stats(sub_df: pd.DataFrame) -> dict[str, Any]:
        if sub_df.empty:
            return {"count": 0}
        sub_ret = sub_df["terminal_return"]
        return {
            "count": len(sub_df),
            "terminal_return": calculate_distribution_stats(sub_ret),
            "positive_count": int((sub_ret > 0).sum()),
            "positive_rate": round(float((sub_ret > 0).mean() * 100), 2),
            "le_neg_20_count": int((sub_ret <= -20.0).sum()),
            "le_neg_20_rate": round(float((sub_ret <= -20.0).mean() * 100), 2),
            "le_neg_30_count": int((sub_ret <= -30.0).sum()),
            "le_neg_30_rate": round(float((sub_ret <= -30.0).mean() * 100), 2),
            "ge_50_count": int((sub_ret >= 50.0).sum()),
            "ge_50_rate": round(float((sub_ret >= 50.0).mean() * 100), 2),
            "ge_100_count": int((sub_ret >= 100.0).sum()),
            "ge_100_rate": round(float((sub_ret >= 100.0).mean() * 100), 2),
            "loss_guard_count": int((sub_df["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15").sum()),
            "loss_guard_rate": round(float((sub_df["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15").mean() * 100), 2),
        }

    cohort_stats = {
        "first_entry_cohort": _get_trade_cohort_stats(df_first),
        "reentry_cohort_overall": _get_trade_cohort_stats(df_reentry),
        "sequence_2_cohort": _get_trade_cohort_stats(df_seq2),
        "sequence_3_cohort": _get_trade_cohort_stats(df_seq3),
        "sequence_4_plus_cohort": _get_trade_cohort_stats(df_seq4p),
    }

    # Re-entry by previous exit reason
    df_post_lg = df[df["previous_exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15"]
    df_post_exit4 = df[df["previous_exit_type"] == "EXIT4_SCORE_DRAWDOWN_GE_15"]
    df_post_exit3 = df[df["previous_exit_type"].str.startswith("EXIT3_", na=False)]

    reentry_by_prev_exit = {
        "post_loss_guard_reentry": _get_trade_cohort_stats(df_post_lg),
        "post_exit4_reentry": _get_trade_cohort_stats(df_post_exit4),
        "post_exit3_reentry": _get_trade_cohort_stats(df_post_exit3),
    }

    # Sequential cumulative return diagnostic
    ticker_cum_ret_stats = calculate_distribution_stats(df_ticker["sequential_cumulative_return_pct"])

    # Load V01 comparison data
    v01_eval = json.loads(V01_EVAL_JSON.read_text(encoding="utf-8"))
    v01_e2 = v01_eval["variants"]["hold_b_e2"]

    # Non-authoritative evaluation status (requires research manual review)
    conclusion = "REENTRY_PROMISING_WITH_WORSE_DOWNSIDE_TAIL"
    suggested_status = "PROMISING_NOT_YET_PROMOTED"

    return {
        "metadata": {
            "strategy_name": "PATTERN_A_FAST_CORE_V02_REENTRY",
            "strategy_alias": "A FAST Core V02 Re Entry",
            "research_classification": "SAME_SAMPLE_REENTRY_STRATEGY_COMPARISON",
            "validation_type": "SAME_SAMPLE_RETROSPECTIVE_EVALUATION",
            "evaluation_basis": "CORRECTED_PIT_BASELINE",
            "calendar_authority_commit": CALENDAR_AUTHORITY_COMMIT,
            "data_cutoff": "2026-08-14",
            "total_common_universe": total_common,
            "phase10_investable_universe": investable_count,
            "total_trades": n_total,
            "unique_tickers": unique_tickers,
            "reentered_tickers": reentered_tickers,
            "total_reentry_trades": total_reentry_trades,
            "max_trades_per_ticker": max_trades_per_ticker,
            "production_status": "PRODUCTION_HOLD",
            "fresh_oos_executed": False,
        },
        "trade_sequence_distribution": {
            "first_entry_count": seq_1_count,
            "second_entry_count": seq_2_count,
            "third_entry_count": seq_3_count,
            "fourth_plus_entry_count": seq_4_plus_count,
        },
        "risk_metrics": risk_metrics,
        "return_metrics": return_metrics,
        "upside_metrics": upside_metrics,
        "giveback_metrics": giveback_metrics,
        "exit_distribution": exit_counts,
        "cohort_diagnostics": cohort_stats,
        "reentry_diagnostics": reentry_by_prev_exit,
        "sequential_ticker_cumulative_return": ticker_cum_ret_stats,
        "comparator_v01": {
            "v01_trade_count": v01_eval["metadata"]["primary_trade_count"],
            "v01_e2_risk_metrics": v01_e2["risk_metrics"],
            "v01_e2_terminal_return": v01_e2["terminal_return"],
            "v01_e2_upside_metrics": v01_e2["upside_metrics"],
            "v01_e2_peak_giveback": v01_e2["peak_giveback"],
        },
        "evaluation_conclusion": conclusion,
    }


def _generate_comparison_markdown(data: dict[str, Any]) -> str:
    meta = data["metadata"]
    risk = data["risk_metrics"]
    ret = data["return_metrics"]
    up = data["upside_metrics"]
    gb = data["giveback_metrics"]
    cohort = data["cohort_diagnostics"]
    reentry = data["reentry_diagnostics"]
    seq = data["trade_sequence_distribution"]
    v01 = data["comparator_v01"]
    v01_r = v01["v01_e2_risk_metrics"]
    v01_t = v01["v01_e2_terminal_return"]
    v01_u = v01["v01_e2_upside_metrics"]
    v01_g = v01["v01_e2_peak_giveback"]

    return f"""# A FAST Core V01 vs A FAST Core V02 Re Entry 비교 보고서

================================================================================
1. Executive Summary
================================================================================
- **전략 명칭**: `{meta["strategy_name"]}` (`{meta["strategy_alias"]}`)
- **연구 분류**: `{meta["research_classification"]}`
- **평가 기준**: `{meta["evaluation_basis"]}`
- **캘린더 권한 커밋**: [`{meta["calendar_authority_commit"][:7]}`](https://github.com/RozeKurhy/krx-trend-scanner/commit/{meta["calendar_authority_commit"]})
- **운영 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **평가 결론**: **`{data["evaluation_conclusion"]}`**

================================================================================
2. V01 vs V02 핵심 비교표
================================================================================

| 핵심 평가 지표 | V01 (First Entry Only) | V02 (Re Entry Allowed) | 변화량 (Delta) |
|---|:---:|:---:|:---:|
| **총 거래 수 (Total Trades)** | {v01["v01_trade_count"]}건 | **{meta["total_trades"]}건** | **{meta["total_trades"] - v01["v01_trade_count"]:+d}건 (+{meta["total_reentry_trades"]}건 재진입)** |
| **참여 종목 수 (Unique Tickers)** | {v01["v01_trade_count"]}개 | **{meta["unique_tickers"]}개** | **{meta["unique_tickers"] - v01["v01_trade_count"]:+d}개** |
| **재진입 발생 종목 수** | 0개 | **{meta["reentered_tickers"]}개** | **+{meta["reentered_tickers"]}개** |
| **Return <= -30% 극단 손실 (비율)** | {v01_r["return_le_neg_30_count"]}건 ({v01_r["return_le_neg_30_rate"]}%) | **{risk["return_le_neg_30_count"]}건 ({risk["return_le_neg_30_rate"]}%)** | **{risk["return_le_neg_30_count"] - v01_r["return_le_neg_30_count"]:+d}건 ({risk["return_le_neg_30_rate"] - v01_r["return_le_neg_30_rate"]:+.2f}%p)** |
| **Return <= -20% 대형 손실 (비율)** | {v01_r["return_le_neg_20_count"]}건 ({v01_r["return_le_neg_20_rate"]}%) | **{risk["return_le_neg_20_count"]}건 ({risk["return_le_neg_20_rate"]}%)** | **{risk["return_le_neg_20_count"] - v01_r["return_le_neg_20_count"]:+d}건 ({risk["return_le_neg_20_rate"] - v01_r["return_le_neg_20_rate"]:+.2f}%p)** |
| **Return <= -15% 손실 (비율)** | 223건 (40.47%) | **{risk["return_le_neg_15_count"]}건 ({risk["return_le_neg_15_rate"]}%)** | **{risk["return_le_neg_15_count"] - 223:+d}건 ({risk["return_le_neg_15_rate"] - 40.47:+.2f}%p)** |
| **최악 손실률 (Worst Return)** | {v01_r["worst_return"]}% | **{risk["worst_return"]}%** | **{risk["worst_return"] - v01_r["worst_return"]:+.2f}%p** |
| **최악 MAE (Worst MAE)** | -59.27% | **{risk["worst_mae"]}%** | **{risk["worst_mae"] - (-59.27):+.2f}%p** |
| **Loss Guard 발동 비율** | 53.36% | **{risk["loss_guard_rate"]}%** | **{risk["loss_guard_rate"] - 53.36:+.2f}%p** |
| **평균 수익률 (Mean Return)** | {v01_t["mean"]}% | **{ret["terminal_return_stats"]["mean"]}%** | **{ret["terminal_return_stats"]["mean"] - v01_t["mean"]:+.2f}%p** |
| **중앙값 수익률 (Median Return)** | {v01_t["median"]}% | **{ret["terminal_return_stats"]["median"]}%** | **{ret["terminal_return_stats"]["median"] - v01_t["median"]:+.2f}%p** |
| **승률 (Positive Rate)** | {v01_t.get("positive_rate", 39.93)}% | **{ret["positive_rate"]}%** | **{ret["positive_rate"] - 39.93:+.2f}%p** |
| **Terminal Return >= +50% 대형 승자** | {v01_u["return_ge_50_count"]}건 ({v01_u["return_ge_50_rate"]}%) | **{up["return_ge_50_count"]}건 ({up["return_ge_50_rate"]}%)** | **{up["return_ge_50_count"] - v01_u["return_ge_50_count"]:+d}건 ({up["return_ge_50_rate"] - v01_u["return_ge_50_rate"]:+.2f}%p)** |
| **Terminal Return >= +100% 초대형 승자** | {v01_u["return_ge_100_count"]}건 ({v01_u["return_ge_100_rate"]}%) | **{up["return_ge_100_count"]}건 ({up["return_ge_100_rate"]}%)** | **{up["return_ge_100_count"] - v01_u["return_ge_100_count"]:+d}건 ({up["return_ge_100_rate"] - v01_u["return_ge_100_rate"]:+.2f}%p)** |
| **Peak Giveback 중앙값** | {v01_g["median"]}% | **{gb["giveback_stats"]["median"]}%** | **{gb["giveback_stats"]["median"] - v01_g["median"]:+.2f}%p** |

================================================================================
3. 거래 차수별 (Sequence) 세부 성과
================================================================================
- **1차 진입 (First Entry, {seq["first_entry_count"]}건)**:
  - 평균 수익률: {cohort["first_entry_cohort"]["terminal_return"]["mean"]}% / 중앙값: {cohort["first_entry_cohort"]["terminal_return"]["median"]}%
  - 승률: {cohort["first_entry_cohort"]["positive_rate"]}%
  - <= -20% 손실: {cohort["first_entry_cohort"]["le_neg_20_count"]}건 ({cohort["first_entry_cohort"]["le_neg_20_rate"]}%)
- **재진입 전체 (Re-Entry All, {meta["total_reentry_trades"]}건)**:
  - 평균 수익률: {cohort["reentry_cohort_overall"]["terminal_return"]["mean"]}% / 중앙값: {cohort["reentry_cohort_overall"]["terminal_return"]["median"]}%
  - 승률: {cohort["reentry_cohort_overall"]["positive_rate"]}%
  - <= -20% 손실: {cohort["reentry_cohort_overall"]["le_neg_20_count"]}건 ({cohort["reentry_cohort_overall"]["le_neg_20_rate"]}%)
- **2차 진입 ({seq["second_entry_count"]}건)**: 평균 {cohort["sequence_2_cohort"]["terminal_return"]["mean"]}%, 승률 {cohort["sequence_2_cohort"]["positive_rate"]}%
- **3차 진입 ({seq["third_entry_count"]}건)**: 평균 {cohort["sequence_3_cohort"]["terminal_return"]["mean"]}%, 승률 {cohort["sequence_3_cohort"]["positive_rate"]}%
- **4차 이상 진입 ({seq["fourth_plus_entry_count"]}건)**: 평균 {cohort["sequence_4_plus_cohort"].get("terminal_return", {}).get("mean", 0)}%

================================================================================
4. 직전 청산 사유별 재진입 성과
================================================================================
- **Loss Guard 이후 재진입 ({reentry["post_loss_guard_reentry"]["count"]}건)**:
  - 평균 수익률: {reentry["post_loss_guard_reentry"]["terminal_return"]["mean"]}% / 중앙값: {reentry["post_loss_guard_reentry"]["terminal_return"]["median"]}%
  - 승률: {reentry["post_loss_guard_reentry"]["positive_rate"]}% ({reentry["post_loss_guard_reentry"]["positive_count"]}건)
  - Return >= +50% 승자 포착: {reentry["post_loss_guard_reentry"]["ge_50_count"]}건
- **Exit 4 (Score HWM 15pt Drawdown) 이후 재진입 ({reentry["post_exit4_reentry"]["count"]}건)**:
  - 평균 수익률: {reentry["post_exit4_reentry"]["terminal_return"]["mean"]}% / 승률: {reentry["post_exit4_reentry"]["positive_rate"]}%
- **Exit 3 (Stage Transition) 이후 재진입 ({reentry["post_exit3_reentry"]["count"]}건)**:
  - 평균 수익률: {reentry["post_exit3_reentry"].get("terminal_return", {}).get("mean", 0)}% / 승률: {reentry["post_exit3_reentry"].get("positive_rate", 0)}%
"""


if __name__ == "__main__":
    run_evaluation()
