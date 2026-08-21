#!/usr/bin/env python
"""Julia Strategy V00 vs A FAST Core V2 2022+ Controlled Comparative Evaluation Runner.

Mandate:
  - Base Strategy: PATTERN_A_FAST_FINAL_STRATEGY_V02 (A FAST Core V2)
  - Experiment: JULIA_STRATEGY_V00
  - Classification: EXPLORATORY_CANDIDATE
  - ONLY ONE DELTA: Pre-PROGRESSED Loss Guard (ON at -15% -> OFF)
  - Evaluation Window: 2022-01-01 to 2026-08-14
  - Initial Position State: FLAT
  - Lookback: Full pre-2022 history used for technical indicators and snapshots
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
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
    StrategyTradeRecord,
    calculate_distribution_stats,
    simulate_ticker_strategy_2022,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent

UNIVERSE_PATH = ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_universe_20260814.csv"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

OUT_DIR = ROOT / "artifacts/strategies/julia/v00"

CONTRACT_JSON_PATH = OUT_DIR / "contract.json"
BASELINE_TRADES_CSV = OUT_DIR / "baseline_a_fast_core_v2_2022_trades.csv"
JULIA_TRADES_CSV = OUT_DIR / "julia_v00_2022_trades.csv"
STRATEGY_SUMMARY_JSON = OUT_DIR / "strategy_comparison_summary.json"
STRATEGY_METRICS_CSV = OUT_DIR / "strategy_comparison_metrics.csv"
COMMON_ENTRY_PAIRS_CSV = OUT_DIR / "common_entry_pairs.csv"
LG_COUNTERFACTUAL_CSV = OUT_DIR / "loss_guard_counterfactual.csv"
LG_RECOVERY_SUMMARY_JSON = OUT_DIR / "loss_guard_recovery_summary.json"
WORST_LOSSES_CSV = OUT_DIR / "worst_losses.csv"
BIG_WINNERS_CSV = OUT_DIR / "big_winners.csv"


def _worker_simulation(args: tuple[str, str, str, dict, dict]) -> tuple[list[dict], list[dict]]:
    ticker, name, market, score_contract, stage_contract = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    # 1. Baseline V2 2022+ (Loss Guard ON)
    baseline_records = simulate_ticker_strategy_2022(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        enable_loss_guard=True,
        start_date=EVALUATION_START_DATE,
        cutoff_date=EVALUATION_END_DATE,
    )

    # 2. Julia V00 2022+ (Loss Guard OFF)
    julia_records = simulate_ticker_strategy_2022(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        enable_loss_guard=False,
        start_date=EVALUATION_START_DATE,
        cutoff_date=EVALUATION_END_DATE,
    )

    return [r.to_dict() for r in baseline_records], [r.to_dict() for r in julia_records]


def _compute_strategy_metrics(df_trades: pd.DataFrame) -> dict[str, Any]:
    if df_trades.empty:
        return {}

    total_trades = len(df_trades)
    unique_tickers = df_trades["ticker"].nunique()
    first_entries = int((df_trades["trade_sequence"] == 1).sum())
    reentries = int((df_trades["trade_sequence"] > 1).sum())

    reentered_tickers_count = int((df_trades.groupby("ticker")["trade_sequence"].max() > 1).sum())
    open_trades = int((df_trades["trade_status"] == "OPEN_AT_CUTOFF").sum())
    closed_trades = int((df_trades["trade_status"] == "REALIZED").sum())

    ret_series = df_trades["terminal_return"]
    ret_stats = calculate_distribution_stats(ret_series)

    # Percentiles
    usable_ret = ret_series.dropna().values
    p10 = float(np.percentile(usable_ret, 10)) if len(usable_ret) > 0 else None
    p25 = float(np.percentile(usable_ret, 25)) if len(usable_ret) > 0 else None
    p50 = float(np.percentile(usable_ret, 50)) if len(usable_ret) > 0 else None
    p75 = float(np.percentile(usable_ret, 75)) if len(usable_ret) > 0 else None
    p90 = float(np.percentile(usable_ret, 90)) if len(usable_ret) > 0 else None
    p95 = float(np.percentile(usable_ret, 95)) if len(usable_ret) > 0 else None

    # Loss tail
    le_neg_15_count = int((ret_series <= -15.0).sum())
    le_neg_20_count = int((ret_series <= -20.0).sum())
    le_neg_30_count = int((ret_series <= -30.0).sum())
    le_neg_40_count = int((ret_series <= -40.0).sum())
    le_neg_50_count = int((ret_series <= -50.0).sum())

    # Upside tail
    ge_20_count = int((ret_series >= 20.0).sum())
    ge_50_count = int((ret_series >= 50.0).sum())
    ge_100_count = int((ret_series >= 100.0).sum())
    ge_200_count = int((ret_series >= 200.0).sum())

    # Exit breakdown
    exit_counts = df_trades["exit_type"].value_counts().to_dict()

    # Ticker lifecycle cumulative returns
    # Cumulative return per ticker: product of (1 + r/100) - 1
    ticker_cum_rets: list[float] = []
    for _, group in df_trades.groupby("ticker"):
        cum_factor = 1.0
        for r in group["terminal_return"]:
            cum_factor *= (1.0 + float(r) / 100.0)
        ticker_cum_rets.append(round((cum_factor - 1.0) * 100.0, 2))

    df_ticker_cum = pd.Series(ticker_cum_rets)
    ticker_cum_stats = calculate_distribution_stats(df_ticker_cum)
    positive_tickers_count = int((df_ticker_cum > 0).sum())
    positive_ticker_rate = round(float(positive_tickers_count / unique_tickers * 100.0), 2) if unique_tickers > 0 else 0.0

    return {
        "total_trades": total_trades,
        "unique_tickers": unique_tickers,
        "first_entries": first_entries,
        "reentries": reentries,
        "reentered_tickers_count": reentered_tickers_count,
        "open_trades": open_trades,
        "closed_trades": closed_trades,
        "return_stats": ret_stats,
        "percentiles": {
            "p10": p10,
            "p25": p25,
            "p50": p50,
            "p75": p75,
            "p90": p90,
            "p95": p95,
        },
        "loss_tail": {
            "le_neg_15_count": le_neg_15_count,
            "le_neg_15_rate": round(le_neg_15_count / total_trades * 100, 2),
            "le_neg_20_count": le_neg_20_count,
            "le_neg_20_rate": round(le_neg_20_count / total_trades * 100, 2),
            "le_neg_30_count": le_neg_30_count,
            "le_neg_30_rate": round(le_neg_30_count / total_trades * 100, 2),
            "le_neg_40_count": le_neg_40_count,
            "le_neg_40_rate": round(le_neg_40_count / total_trades * 100, 2),
            "le_neg_50_count": le_neg_50_count,
            "le_neg_50_rate": round(le_neg_50_count / total_trades * 100, 2),
        },
        "upside_tail": {
            "ge_20_count": ge_20_count,
            "ge_20_rate": round(ge_20_count / total_trades * 100, 2),
            "ge_50_count": ge_50_count,
            "ge_50_rate": round(ge_50_count / total_trades * 100, 2),
            "ge_100_count": ge_100_count,
            "ge_100_rate": round(ge_100_count / total_trades * 100, 2),
            "ge_200_count": ge_200_count,
            "ge_200_rate": round(ge_200_count / total_trades * 100, 2),
        },
        "exit_counts": exit_counts,
        "ticker_cumulative": {
            "unique_tickers": unique_tickers,
            "positive_tickers_count": positive_tickers_count,
            "positive_ticker_rate": positive_ticker_rate,
            "mean_cumulative_return": ticker_cum_stats["mean"],
            "median_cumulative_return": ticker_cum_stats["median"],
            "p25": ticker_cum_stats["p25"],
            "p75": ticker_cum_stats["p75"],
            "p90": ticker_cum_stats["p90"],
            "min": ticker_cum_stats["min"],
            "max": ticker_cum_stats["max"],
        },
    }


def run_controlled_comparison() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    df_univ = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    df_univ["ticker"] = df_univ["ticker"].str.zfill(6)

    inv_mask = (
        (df_univ["market_cap_ready"] == True)
        & (df_univ["trading_value_20d_ready"] == True)
        & (df_univ["market_cap"] >= 100_000_000_000)
        & (df_univ["avg_trading_value_20d"] >= 300_000_000)
    )
    df_inv = df_univ[inv_mask].copy().sort_values(by="ticker").reset_index(drop=True)
    investable_count = len(df_inv)

    logger.info("Total Investable Universe to Evaluate: %d tickers", investable_count)

    tasks = [
        (row["ticker"], str(row["name"]), str(row["market"]), score_contract, stage_contract)
        for _, row in df_inv.iterrows()
    ]

    t0 = time.perf_counter()
    all_baseline_trades: list[dict] = []
    all_julia_trades: list[dict] = []

    with ProcessPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_worker_simulation, tasks))

    for b_trades, j_trades in results:
        all_baseline_trades.extend(b_trades)
        all_julia_trades.extend(j_trades)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Simulation completed in %.2fs. Baseline Trades: %d, Julia Trades: %d",
        elapsed,
        len(all_baseline_trades),
        len(all_julia_trades),
    )

    # 1. Save Trade DataFrames
    df_b = pd.DataFrame(all_baseline_trades)
    df_j = pd.DataFrame(all_julia_trades)

    df_b.to_csv(BASELINE_TRADES_CSV, index=False)
    df_j.to_csv(JULIA_TRADES_CSV, index=False)

    # 2. Strategy Metrics & Comparison
    b_metrics = _compute_strategy_metrics(df_b)
    j_metrics = _compute_strategy_metrics(df_j)

    # Build Comparison Summary
    summary = {
        "metadata": {
            "task": "JULIA_STRATEGY_V00_2022_CONTROLLED_COMPARATIVE_BACKTEST",
            "base_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
            "experiment_strategy_id": "JULIA_STRATEGY_V00",
            "classification": "EXPLORATORY_CANDIDATE",
            "evidence_classification": "SAME_SAMPLE_RETROSPECTIVE",
            "evaluation_start": str(EVALUATION_START_DATE.date()),
            "evaluation_end": str(EVALUATION_END_DATE.date()),
            "only_delta": "PRE_PROGRESSED_LOSS_GUARD_OFF",
            "no_tuning": True,
            "pre_2022_lookback_used": True,
            "pre_2022_trades_included": False,
            "initial_position_state": "FLAT",
            "investable_universe_count": investable_count,
            "elapsed_seconds": round(elapsed, 2),
        },
        "baseline_v2_2022": b_metrics,
        "julia_v00_2022": j_metrics,
    }

    with open(STRATEGY_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # 3. Strategy Comparison Metrics CSV Table
    metrics_rows = [
        ("Total Trades", b_metrics["total_trades"], j_metrics["total_trades"], j_metrics["total_trades"] - b_metrics["total_trades"]),
        ("Unique Tickers", b_metrics["unique_tickers"], j_metrics["unique_tickers"], j_metrics["unique_tickers"] - b_metrics["unique_tickers"]),
        ("First Entries", b_metrics["first_entries"], j_metrics["first_entries"], j_metrics["first_entries"] - b_metrics["first_entries"]),
        ("Reentries", b_metrics["reentries"], j_metrics["reentries"], j_metrics["reentries"] - b_metrics["reentries"]),
        ("Reentered Tickers", b_metrics["reentered_tickers_count"], j_metrics["reentered_tickers_count"], j_metrics["reentered_tickers_count"] - b_metrics["reentered_tickers_count"]),
        ("Open at Cutoff", b_metrics["open_trades"], j_metrics["open_trades"], j_metrics["open_trades"] - b_metrics["open_trades"]),
        ("Closed Trades", b_metrics["closed_trades"], j_metrics["closed_trades"], j_metrics["closed_trades"] - b_metrics["closed_trades"]),
        ("Mean Return (%)", b_metrics["return_stats"]["mean"], j_metrics["return_stats"]["mean"], round(j_metrics["return_stats"]["mean"] - b_metrics["return_stats"]["mean"], 2)),
        ("Median Return (%)", b_metrics["return_stats"]["median"], j_metrics["return_stats"]["median"], round(j_metrics["return_stats"]["median"] - b_metrics["return_stats"]["median"], 2)),
        ("P10 Return (%)", b_metrics["percentiles"]["p10"], j_metrics["percentiles"]["p10"], round(j_metrics["percentiles"]["p10"] - b_metrics["percentiles"]["p10"], 2)),
        ("P25 Return (%)", b_metrics["percentiles"]["p25"], j_metrics["percentiles"]["p25"], round(j_metrics["percentiles"]["p25"] - b_metrics["percentiles"]["p25"], 2)),
        ("P50 Return (%)", b_metrics["percentiles"]["p50"], j_metrics["percentiles"]["p50"], round(j_metrics["percentiles"]["p50"] - b_metrics["percentiles"]["p50"], 2)),
        ("P75 Return (%)", b_metrics["percentiles"]["p75"], j_metrics["percentiles"]["p75"], round(j_metrics["percentiles"]["p75"] - b_metrics["percentiles"]["p75"], 2)),
        ("P90 Return (%)", b_metrics["percentiles"]["p90"], j_metrics["percentiles"]["p90"], round(j_metrics["percentiles"]["p90"] - b_metrics["percentiles"]["p90"], 2)),
        ("P95 Return (%)", b_metrics["percentiles"]["p95"], j_metrics["percentiles"]["p95"], round(j_metrics["percentiles"]["p95"] - b_metrics["percentiles"]["p95"], 2)),
        ("Positive Count", b_metrics["return_stats"]["count"] * b_metrics["return_stats"]["positive_rate"] / 100, j_metrics["return_stats"]["count"] * j_metrics["return_stats"]["positive_rate"] / 100, None),
        ("Positive Rate (%)", b_metrics["return_stats"]["positive_rate"], j_metrics["return_stats"]["positive_rate"], round(j_metrics["return_stats"]["positive_rate"] - b_metrics["return_stats"]["positive_rate"], 2)),
        ("<= -15% Count", b_metrics["loss_tail"]["le_neg_15_count"], j_metrics["loss_tail"]["le_neg_15_count"], j_metrics["loss_tail"]["le_neg_15_count"] - b_metrics["loss_tail"]["le_neg_15_count"]),
        ("<= -15% Rate (%)", b_metrics["loss_tail"]["le_neg_15_rate"], j_metrics["loss_tail"]["le_neg_15_rate"], round(j_metrics["loss_tail"]["le_neg_15_rate"] - b_metrics["loss_tail"]["le_neg_15_rate"], 2)),
        ("<= -20% Count", b_metrics["loss_tail"]["le_neg_20_count"], j_metrics["loss_tail"]["le_neg_20_count"], j_metrics["loss_tail"]["le_neg_20_count"] - b_metrics["loss_tail"]["le_neg_20_count"]),
        ("<= -20% Rate (%)", b_metrics["loss_tail"]["le_neg_20_rate"], j_metrics["loss_tail"]["le_neg_20_rate"], round(j_metrics["loss_tail"]["le_neg_20_rate"] - b_metrics["loss_tail"]["le_neg_20_rate"], 2)),
        ("<= -30% Count", b_metrics["loss_tail"]["le_neg_30_count"], j_metrics["loss_tail"]["le_neg_30_count"], j_metrics["loss_tail"]["le_neg_30_count"] - b_metrics["loss_tail"]["le_neg_30_count"]),
        ("<= -30% Rate (%)", b_metrics["loss_tail"]["le_neg_30_rate"], j_metrics["loss_tail"]["le_neg_30_rate"], round(j_metrics["loss_tail"]["le_neg_30_rate"] - b_metrics["loss_tail"]["le_neg_30_rate"], 2)),
        ("<= -40% Count", b_metrics["loss_tail"]["le_neg_40_count"], j_metrics["loss_tail"]["le_neg_40_count"], j_metrics["loss_tail"]["le_neg_40_count"] - b_metrics["loss_tail"]["le_neg_40_count"]),
        ("<= -40% Rate (%)", b_metrics["loss_tail"]["le_neg_40_rate"], j_metrics["loss_tail"]["le_neg_40_rate"], round(j_metrics["loss_tail"]["le_neg_40_rate"] - b_metrics["loss_tail"]["le_neg_40_rate"], 2)),
        ("<= -50% Count", b_metrics["loss_tail"]["le_neg_50_count"], j_metrics["loss_tail"]["le_neg_50_count"], j_metrics["loss_tail"]["le_neg_50_count"] - b_metrics["loss_tail"]["le_neg_50_count"]),
        ("<= -50% Rate (%)", b_metrics["loss_tail"]["le_neg_50_rate"], j_metrics["loss_tail"]["le_neg_50_rate"], round(j_metrics["loss_tail"]["le_neg_50_rate"] - b_metrics["loss_tail"]["le_neg_50_rate"], 2)),
        (">= +20% Count", b_metrics["upside_tail"]["ge_20_count"], j_metrics["upside_tail"]["ge_20_count"], j_metrics["upside_tail"]["ge_20_count"] - b_metrics["upside_tail"]["ge_20_count"]),
        (">= +20% Rate (%)", b_metrics["upside_tail"]["ge_20_rate"], j_metrics["upside_tail"]["ge_20_rate"], round(j_metrics["upside_tail"]["ge_20_rate"] - b_metrics["upside_tail"]["ge_20_rate"], 2)),
        (">= +50% Count", b_metrics["upside_tail"]["ge_50_count"], j_metrics["upside_tail"]["ge_50_count"], j_metrics["upside_tail"]["ge_50_count"] - b_metrics["upside_tail"]["ge_50_count"]),
        (">= +50% Rate (%)", b_metrics["upside_tail"]["ge_50_rate"], j_metrics["upside_tail"]["ge_50_rate"], round(j_metrics["upside_tail"]["ge_50_rate"] - b_metrics["upside_tail"]["ge_50_rate"], 2)),
        (">= +100% Count", b_metrics["upside_tail"]["ge_100_count"], j_metrics["upside_tail"]["ge_100_count"], j_metrics["upside_tail"]["ge_100_count"] - b_metrics["upside_tail"]["ge_100_count"]),
        (">= +100% Rate (%)", b_metrics["upside_tail"]["ge_100_rate"], j_metrics["upside_tail"]["ge_100_rate"], round(j_metrics["upside_tail"]["ge_100_rate"] - b_metrics["upside_tail"]["ge_100_rate"], 2)),
        (">= +200% Count", b_metrics["upside_tail"]["ge_200_count"], j_metrics["upside_tail"]["ge_200_count"], j_metrics["upside_tail"]["ge_200_count"] - b_metrics["upside_tail"]["ge_200_count"]),
        (">= +200% Rate (%)", b_metrics["upside_tail"]["ge_200_rate"], j_metrics["upside_tail"]["ge_200_rate"], round(j_metrics["upside_tail"]["ge_200_rate"] - b_metrics["upside_tail"]["ge_200_rate"], 2)),
        ("Mean Ticker Cumulative Return (%)", b_metrics["ticker_cumulative"]["mean_cumulative_return"], j_metrics["ticker_cumulative"]["mean_cumulative_return"], round(j_metrics["ticker_cumulative"]["mean_cumulative_return"] - b_metrics["ticker_cumulative"]["mean_cumulative_return"], 2)),
        ("Median Ticker Cumulative Return (%)", b_metrics["ticker_cumulative"]["median_cumulative_return"], j_metrics["ticker_cumulative"]["median_cumulative_return"], round(j_metrics["ticker_cumulative"]["median_cumulative_return"] - b_metrics["ticker_cumulative"]["median_cumulative_return"], 2)),
        ("Positive Ticker Rate (%)", b_metrics["ticker_cumulative"]["positive_ticker_rate"], j_metrics["ticker_cumulative"]["positive_ticker_rate"], round(j_metrics["ticker_cumulative"]["positive_ticker_rate"] - b_metrics["ticker_cumulative"]["positive_ticker_rate"], 2)),
    ]
    df_metrics = pd.DataFrame(metrics_rows, columns=["Metric", "A FAST Core V2 (2022+)", "Julia V00 (2022+)", "Delta (Julia - Base)"])
    df_metrics.to_csv(STRATEGY_METRICS_CSV, index=False)

    # 4. Common-Entry Paired Counterfactual Comparison
    # Match on: ticker, entry_signal_date, entry_execution_date, entry_open
    pair_keys = ["ticker", "entry_signal_date", "entry_execution_date", "entry_open"]
    df_pairs = pd.merge(
        df_b,
        df_j,
        on=pair_keys,
        suffixes=("_base", "_julia"),
        how="inner",
    )

    paired_rows = []
    for _, row in df_pairs.iterrows():
        ret_b = float(row["terminal_return_base"])
        ret_j = float(row["terminal_return_julia"])
        paired_rows.append({
            "ticker": row["ticker"],
            "name": row["name_base"],
            "market": row["market_base"],
            "entry_signal_date": row["entry_signal_date"],
            "entry_execution_date": row["entry_execution_date"],
            "entry_open": row["entry_open"],
            "baseline_trade_id": row["trade_id_base"],
            "baseline_trade_sequence": row["trade_sequence_base"],
            "baseline_exit_type": row["exit_type_base"],
            "baseline_exit_date": row["exit_execution_date_base"],
            "baseline_return": ret_b,
            "baseline_first_progressed": row["first_progressed_date_base"],
            "julia_trade_id": row["trade_id_julia"],
            "julia_trade_sequence": row["trade_sequence_julia"],
            "julia_exit_type": row["exit_type_julia"],
            "julia_exit_date": row["exit_execution_date_julia"],
            "julia_return": ret_j,
            "julia_first_progressed": row["first_progressed_date_julia"],
            "return_delta": round(ret_j - ret_b, 2),
            "pair_status": "PAIRED_COMMON_ENTRY",
        })

    df_common_pairs = pd.DataFrame(paired_rows)
    df_common_pairs.to_csv(COMMON_ENTRY_PAIRS_CSV, index=False)
    logger.info("Common Entry Pairs Found: %d", len(df_common_pairs))

    # 5. Loss Guard Triggered Baseline Cohort Analysis
    df_b_lg = df_b[df_b["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15"].copy()
    logger.info("Baseline Loss Guard Exits in 2022+: %d", len(df_b_lg))

    # Match baseline LG exits with Julia on the same entry anchor
    df_lg_matched = pd.merge(
        df_b_lg,
        df_j,
        on=pair_keys,
        suffixes=("_base", "_julia"),
        how="inner",
    )

    lg_cf_rows = []
    for _, row in df_lg_matched.iterrows():
        ret_b = float(row["terminal_return_base"])
        ret_j = float(row["terminal_return_julia"])
        delta = round(ret_j - ret_b, 2)
        prog_j = row["first_progressed_date_julia"] is not None and not pd.isna(row["first_progressed_date_julia"])

        lg_cf_rows.append({
            "ticker": row["ticker"],
            "name": row["name_base"],
            "market": row["market_base"],
            "trade_sequence_base": row["trade_sequence_base"],
            "entry_signal_date": row["entry_signal_date"],
            "entry_execution_date": row["entry_execution_date"],
            "entry_open": row["entry_open"],
            "baseline_loss_guard_signal_date": row["loss_guard_signal_date_base"],
            "baseline_exit_execution_date": row["loss_guard_execution_date_base"],
            "baseline_exit_price": row["loss_guard_execution_price_base"],
            "baseline_return": ret_b,
            "julia_exit_type": row["exit_type_julia"],
            "julia_exit_execution_date": row["exit_execution_date_julia"],
            "julia_terminal_return": ret_j,
            "return_delta": delta,
            "julia_reached_progressed": prog_j,
            "julia_first_progressed_date": row["first_progressed_date_julia"],
        })

    df_lg_cf = pd.DataFrame(lg_cf_rows)
    df_lg_cf.to_csv(LG_COUNTERFACTUAL_CSV, index=False)

    # Compute Recovery Metrics on the LG Triggered Cohort
    lg_total = len(df_lg_cf)
    j_rets = df_lg_cf["julia_terminal_return"]
    b_rets = df_lg_cf["baseline_return"]
    deltas = df_lg_cf["return_delta"]

    better_count = int((deltas > 0).sum())
    equal_count = int((deltas == 0).sum())
    worse_count = int((deltas < 0).sum())

    rec_ge_0 = int((j_rets >= 0.0).sum())
    rec_ge_20 = int((j_rets >= 20.0).sum())
    rec_ge_50 = int((j_rets >= 50.0).sum())
    rec_ge_100 = int((j_rets >= 100.0).sum())

    loss_le_neg_20 = int((j_rets <= -20.0).sum())
    loss_le_neg_30 = int((j_rets <= -30.0).sum())
    loss_le_neg_40 = int((j_rets <= -40.0).sum())
    loss_le_neg_50 = int((j_rets <= -50.0).sum())

    lg_summary = {
        "total_baseline_loss_guard_trades": lg_total,
        "comparison_direction": {
            "julia_better_count": better_count,
            "julia_better_rate": round(better_count / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "julia_equal_count": equal_count,
            "julia_equal_rate": round(equal_count / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "julia_worse_count": worse_count,
            "julia_worse_rate": round(worse_count / lg_total * 100, 2) if lg_total > 0 else 0.0,
        },
        "recovery_distribution": {
            "recovered_to_breakeven_or_better_count (>= 0%)": rec_ge_0,
            "recovered_to_breakeven_or_better_rate (%)": round(rec_ge_0 / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "recovered_to_plus_20_count (>= +20%)": rec_ge_20,
            "recovered_to_plus_20_rate (%)": round(rec_ge_20 / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "recovered_to_plus_50_count (>= +50%)": rec_ge_50,
            "recovered_to_plus_50_rate (%)": round(rec_ge_50 / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "recovered_to_plus_100_count (>= +100%)": rec_ge_100,
            "recovered_to_plus_100_rate (%)": round(rec_ge_100 / lg_total * 100, 2) if lg_total > 0 else 0.0,
        },
        "deep_loss_deterioration": {
            "still_loss_below_minus_20_count (<= -20%)": loss_le_neg_20,
            "still_loss_below_minus_20_rate (%)": round(loss_le_neg_20 / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "still_loss_below_minus_30_count (<= -30%)": loss_le_neg_30,
            "still_loss_below_minus_30_rate (%)": round(loss_le_neg_30 / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "still_loss_below_minus_40_count (<= -40%)": loss_le_neg_40,
            "still_loss_below_minus_40_rate (%)": round(loss_le_neg_40 / lg_total * 100, 2) if lg_total > 0 else 0.0,
            "still_loss_below_minus_50_count (<= -50%)": loss_le_neg_50,
            "still_loss_below_minus_50_rate (%)": round(loss_le_neg_50 / lg_total * 100, 2) if lg_total > 0 else 0.0,
        },
        "return_delta_stats": calculate_distribution_stats(deltas),
        "julia_outcome_return_stats": calculate_distribution_stats(j_rets),
        "baseline_outcome_return_stats": calculate_distribution_stats(b_rets),
    }

    with open(LG_RECOVERY_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(lg_summary, f, indent=2, ensure_ascii=False)

    # 6. Worst Losses Table (Julia Worst 30 trades)
    df_worst = df_j.sort_values(by="terminal_return", ascending=True).head(30).copy()
    worst_rows = []
    for _, row in df_worst.iterrows():
        # Find corresponding baseline return on the same entry anchor if exists
        match = df_b[
            (df_b["ticker"] == row["ticker"])
            & (df_b["entry_signal_date"] == row["entry_signal_date"])
            & (df_b["entry_execution_date"] == row["entry_execution_date"])
        ]
        b_ret = float(match.iloc[0]["terminal_return"]) if not match.empty else None
        b_exit = str(match.iloc[0]["exit_type"]) if not match.empty else None
        delta = round(float(row["terminal_return"]) - b_ret, 2) if b_ret is not None else None

        worst_rows.append({
            "ticker": row["ticker"],
            "name": row["name"],
            "market": row["market"],
            "trade_sequence": row["trade_sequence"],
            "entry_signal_date": row["entry_signal_date"],
            "entry_execution_date": row["entry_execution_date"],
            "entry_open": row["entry_open"],
            "julia_exit_type": row["exit_type"],
            "julia_exit_date": row["exit_execution_date"],
            "julia_terminal_return": row["terminal_return"],
            "julia_mae": row["mae"],
            "baseline_exit_type": b_exit,
            "baseline_terminal_return": b_ret,
            "return_delta": delta,
        })
    pd.DataFrame(worst_rows).to_csv(WORST_LOSSES_CSV, index=False)

    # 7. Big Winners Table (Julia Trades >= +50%)
    df_winners = df_j[df_j["terminal_return"] >= 50.0].sort_values(by="terminal_return", ascending=False).copy()
    winner_rows = []
    for _, row in df_winners.iterrows():
        match = df_b[
            (df_b["ticker"] == row["ticker"])
            & (df_b["entry_signal_date"] == row["entry_signal_date"])
            & (df_b["entry_execution_date"] == row["entry_execution_date"])
        ]
        b_ret = float(match.iloc[0]["terminal_return"]) if not match.empty else None
        b_exit = str(match.iloc[0]["exit_type"]) if not match.empty else None
        delta = round(float(row["terminal_return"]) - b_ret, 2) if b_ret is not None else None

        # Check if baseline caught this ticker later via reentry
        all_b_ticker_trades = df_b[df_b["ticker"] == row["ticker"]]
        reentry_caught = bool(len(all_b_ticker_trades) > 1 and any(all_b_ticker_trades["terminal_return"] >= 50.0))

        winner_rows.append({
            "ticker": row["ticker"],
            "name": row["name"],
            "market": row["market"],
            "trade_sequence": row["trade_sequence"],
            "entry_signal_date": row["entry_signal_date"],
            "entry_execution_date": row["entry_execution_date"],
            "entry_open": row["entry_open"],
            "julia_exit_type": row["exit_type"],
            "julia_exit_date": row["exit_execution_date"],
            "julia_terminal_return": row["terminal_return"],
            "julia_mfe": row["mfe"],
            "julia_mae": row["mae"],
            "baseline_exit_type": b_exit,
            "baseline_terminal_return": b_ret,
            "return_delta": delta,
            "baseline_caught_via_reentry": reentry_caught,
        })
    pd.DataFrame(winner_rows).to_csv(BIG_WINNERS_CSV, index=False)

    # 8. Contract Metadata JSON
    contract_data = {
        "strategy_id": "JULIA_STRATEGY_V00",
        "base_strategy_id": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "classification": "EXPLORATORY_CANDIDATE",
        "evidence_classification": "SAME_SAMPLE_RETROSPECTIVE",
        "production_status": "NOT_APPROVED",
        "current_default_strategy": "PATTERN_A_FAST_FINAL_STRATEGY_V02",
        "evaluation_start": str(EVALUATION_START_DATE.date()),
        "evaluation_end": str(EVALUATION_END_DATE.date()),
        "pre_progressed_loss_guard": "DISABLED",
        "only_delta_from_base": "PRE_PROGRESSED_LOSS_GUARD_OFF",
        "no_tuning": True,
        "initial_position_state": "FLAT",
        "pre_2022_lookback_used": True,
        "pre_2022_trades_included": False,
    }
    with open(CONTRACT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(contract_data, f, indent=2, ensure_ascii=False)

    logger.info("All artifacts successfully saved to %s", OUT_DIR)


if __name__ == "__main__":
    run_controlled_comparison()
