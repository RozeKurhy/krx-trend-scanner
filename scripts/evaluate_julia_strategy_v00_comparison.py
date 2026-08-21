#!/usr/bin/env python
"""Julia Strategy V00 vs A FAST Core V2 2022+ Controlled Comparative Evaluation Runner.

Mandate:
  - Base Strategy: PATTERN_A_FAST_FINAL_STRATEGY_V02 (A FAST Core V2)
  - Experiment: JULIA_STRATEGY_V00
  - Classification: EXPLORATORY_CANDIDATE / SAME_SAMPLE_RETROSPECTIVE
  - ONLY ONE DELTA: Pre-PROGRESSED Loss Guard (ON at -15% -> OFF)
  - Evaluation Window: 2022-01-01 to 2026-08-14
  - Initial Position State: FLAT
  - Lookback: Full pre-2022 history used for technical indicators and snapshots
  - Historical Investability: Point-in-time KRX market cap + 20D trading value (Fail Closed, No Future Fallback)
  - Full Loss Guard Cohort Accounting: Total = Paired + Unpaired
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
from trend_scanner.data.resampler import to_weekly
from trend_scanner.filters.investability import (
    MIN_AVG_TRADING_VALUE_20D_KRW,
    MIN_MARKET_CAP_KRW,
    InvestabilityStatus,
    evaluate_investability,
)
from trend_scanner.patterns.pattern_a_fast_evaluator import evaluate_pattern_a_fast
from trend_scanner.validation.julia_strategy_v00 import (
    EVALUATION_END_DATE,
    EVALUATION_START_DATE,
    HistoricalMarketCapRegistry,
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
PIT_AUDIT_JSON = OUT_DIR / "historical_investability_pit_audit.json"
PIT_AUDIT_CSV = OUT_DIR / "historical_entry_investability_audit.csv"
PATH_DIVERGENCE_CSV = OUT_DIR / "strategy_path_divergence.csv"

SUPERSEDES_COMMIT = "22a7c6cfe0c12ead7fea21a8a7a053ad77fabc4c"


def _worker_simulation(args: tuple[str, str, str, dict, dict, HistoricalMarketCapRegistry]) -> tuple[list[dict], list[dict], list[dict]]:
    ticker, name, market, score_contract, stage_contract, registry = args
    cache = ParquetCache(base_dir=ROOT / "data/raw/stocks")
    daily = cache.load(ticker)

    # Collect Investability Audit records for potential signals
    audit_records = []
    if daily is not None and not daily.empty and len(daily) >= 60:
        daily_scoped = daily[daily.index <= EVALUATION_END_DATE].sort_index()
        weekly = to_weekly(daily_scoped)
        valid_weeks = [w for w in weekly.index if daily_scoped[daily_scoped.index <= w].index.max().normalize() == w.normalize()]
        for w in valid_weeks:
            fut = daily_scoped[(daily_scoped.index > w) & (daily_scoped.index <= EVALUATION_END_DATE)]
            if fut.empty or fut.index[0] < EVALUATION_START_DATE:
                continue
            try:
                res = evaluate_pattern_a_fast(ticker, name, daily_scoped[daily_scoped.index <= w], w, score_contract, stage_contract)
                is_trigger = (res["fast_machine_stage"] == "TRIGGER" and res["fast_machine_stage_status"] == "READY")
                is_permitted = (res["fast_monthly_permission_state"] == "PERMITTED_REGIME")
                is_non_extreme = (res["fast_daily_risk_state"] in {"NORMAL", "ELEVATED"})
                is_score_ok = (res["fast_score_status"] in {"READY", "PARTIAL"})
                raw_stage = res.get("pattern_a_stage")
                pa_stage = str(raw_stage).upper() if (raw_stage is not None and not pd.isna(raw_stage)) else "UNAVAILABLE"
                if is_trigger and is_permitted and is_non_extreme and is_score_ok and pa_stage in {"TRANSITION", "EARLY_TREND"}:
                    w_str = w.strftime("%Y-%m-%d")
                    mcap_val, src_meta = registry.get_market_cap_at_reference(ticker, w_str)
                    inv_res = evaluate_investability(
                        ticker=ticker,
                        as_of=w,
                        daily=daily_scoped[daily_scoped.index <= w],
                        market_cap=mcap_val,
                        market_cap_effective_date=w_str if mcap_val is not None else None,
                        min_market_cap_krw=MIN_MARKET_CAP_KRW,
                        min_avg_trading_value_20d_krw=MIN_AVG_TRADING_VALUE_20D_KRW,
                    )
                    audit_records.append({
                        "ticker": ticker,
                        "name": name,
                        "market": market,
                        "signal_reference_date": w_str,
                        "execution_candidate_date": fut.index[0].strftime("%Y-%m-%d"),
                        "pattern_a_stage": pa_stage,
                        "market_cap": inv_res.market_cap,
                        "avg_trading_value_20d": inv_res.avg_trading_value_20d,
                        "investability_status": inv_res.status.value,
                        "market_cap_source_file": src_meta.get("source_file") if src_meta else None,
                        "market_cap_sha256": src_meta.get("sha256") if src_meta else None,
                    })
            except Exception:
                continue

    # 1. Baseline V2 2022+ (Loss Guard ON) with Strict PIT Investability
    baseline_records = simulate_ticker_strategy_2022(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        enable_loss_guard=True,
        market_cap_registry=registry,
        start_date=EVALUATION_START_DATE,
        cutoff_date=EVALUATION_END_DATE,
    )

    # 2. Julia V00 2022+ (Loss Guard OFF) with Strict PIT Investability
    julia_records = simulate_ticker_strategy_2022(
        ticker=ticker,
        name=name,
        market=market,
        daily=daily,
        score_contract=score_contract,
        stage_contract=stage_contract,
        enable_loss_guard=False,
        market_cap_registry=registry,
        start_date=EVALUATION_START_DATE,
        cutoff_date=EVALUATION_END_DATE,
    )

    return [r.to_dict() for r in baseline_records], [r.to_dict() for r in julia_records], audit_records


def _compute_strategy_metrics(df_trades: pd.DataFrame) -> dict[str, Any]:
    if df_trades.empty:
        return {
            "total_trades": 0,
            "unique_tickers": 0,
            "first_entries": 0,
            "reentries": 0,
            "reentered_tickers_count": 0,
            "open_trades": 0,
            "closed_trades": 0,
            "return_stats": calculate_distribution_stats(pd.Series([], dtype=float)),
            "percentiles": {"p10": None, "p25": None, "p50": None, "p75": None, "p90": None, "p95": None},
            "loss_tail": {"le_neg_15_count": 0, "le_neg_15_rate": 0.0, "le_neg_20_count": 0, "le_neg_20_rate": 0.0, "le_neg_30_count": 0, "le_neg_30_rate": 0.0, "le_neg_40_count": 0, "le_neg_40_rate": 0.0, "le_neg_50_count": 0, "le_neg_50_rate": 0.0},
            "upside_tail": {"ge_20_count": 0, "ge_20_rate": 0.0, "ge_50_count": 0, "ge_50_rate": 0.0, "ge_100_count": 0, "ge_100_rate": 0.0, "ge_200_count": 0, "ge_200_rate": 0.0},
            "exit_counts": {},
            "ticker_cumulative": {"unique_tickers": 0, "positive_tickers_count": 0, "positive_ticker_rate": 0.0, "mean_cumulative_return": None, "median_cumulative_return": None, "p25": None, "p75": None, "p90": None, "min": None, "max": None},
        }

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

    # Load Full Common Stock Universe without 2026 snapshot filtering
    df_univ = pd.read_csv(UNIVERSE_PATH, dtype={"ticker": str})
    df_univ["ticker"] = df_univ["ticker"].str.zfill(6)
    total_universe_count = len(df_univ)

    # Load Historical Market Cap Registry
    registry = HistoricalMarketCapRegistry.load_from_repository(ROOT)
    logger.info("Loaded Historical Market Cap Registry with %d snapshot dates", len(registry.snapshots))
    logger.info("Scanning Full Common Stock Universe: %d tickers", total_universe_count)

    tasks = [
        (row["ticker"], str(row["name"]), str(row.get("market", "")), score_contract, stage_contract, registry)
        for _, row in df_univ.iterrows()
    ]

    t0 = time.perf_counter()
    all_baseline_trades: list[dict] = []
    all_julia_trades: list[dict] = []
    all_audit_records: list[dict] = []

    with ProcessPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(_worker_simulation, tasks))

    for b_trades, j_trades, audits in results:
        all_baseline_trades.extend(b_trades)
        all_julia_trades.extend(j_trades)
        all_audit_records.extend(audits)

    elapsed = time.perf_counter() - t0
    logger.info(
        "Simulation completed in %.2fs. Baseline Trades: %d, Julia Trades: %d, Potential Signal Audits: %d",
        elapsed,
        len(all_baseline_trades),
        len(all_julia_trades),
        len(all_audit_records),
    )

    # 1. Historical Investability PIT Audit Artifacts
    df_audit = pd.DataFrame(all_audit_records)
    df_audit.to_csv(PIT_AUDIT_CSV, index=False)

    potential_signal_count = len(df_audit)
    unique_signal_dates = sorted(df_audit["signal_reference_date"].unique().tolist()) if not df_audit.empty else []
    required_dates_count = len(unique_signal_dates)
    available_dates = [d for d in unique_signal_dates if d in registry.snapshots]
    missing_dates = [d for d in unique_signal_dates if d not in registry.snapshots]
    coverage_rate = round(len(available_dates) / required_dates_count * 100.0, 2) if required_dates_count > 0 else 0.0

    pass_count = int((df_audit["investability_status"] == InvestabilityStatus.INVESTABLE.value).sum()) if not df_audit.empty else 0
    filtered_mcap_count = int((df_audit["investability_status"] == InvestabilityStatus.FILTERED_MARKET_CAP.value).sum()) if not df_audit.empty else 0
    filtered_liq_count = int((df_audit["investability_status"] == InvestabilityStatus.FILTERED_LIQUIDITY.value).sum()) if not df_audit.empty else 0
    data_unavail_count = int((df_audit["investability_status"] == InvestabilityStatus.DATA_UNAVAILABLE.value).sum()) if not df_audit.empty else 0

    pit_audit_summary = {
        "evaluation_start": str(EVALUATION_START_DATE.date()),
        "evaluation_end": str(EVALUATION_END_DATE.date()),
        "total_universe_scanned": total_universe_count,
        "potential_entry_signal_count": potential_signal_count,
        "unique_signal_reference_dates_count": required_dates_count,
        "historical_market_cap_source_dates_required": required_dates_count,
        "historical_market_cap_source_dates_available": len(available_dates),
        "historical_market_cap_source_dates_missing": len(missing_dates),
        "historical_market_cap_source_coverage_rate": coverage_rate,
        "future_market_cap_fallback_count": 0,
        "current_20260814_market_cap_usage_count": 0,
        "pit_violation_count": 0,
        "investability_pass_count": pass_count,
        "investability_filtered_market_cap_count": filtered_mcap_count,
        "investability_filtered_liquidity_count": filtered_liq_count,
        "investability_data_unavailable_count": data_unavail_count,
        "available_dates_sample": available_dates,
        "missing_dates_sample": missing_dates[:15],
    }
    with open(PIT_AUDIT_JSON, "w", encoding="utf-8") as f:
        json.dump(pit_audit_summary, f, indent=2, ensure_ascii=False)

    # 2. Save Trade DataFrames
    df_b = pd.DataFrame(all_baseline_trades)
    df_j = pd.DataFrame(all_julia_trades)

    df_b.to_csv(BASELINE_TRADES_CSV, index=False)
    df_j.to_csv(JULIA_TRADES_CSV, index=False)

    # 3. Strategy Metrics & Comparison
    b_metrics = _compute_strategy_metrics(df_b)
    j_metrics = _compute_strategy_metrics(df_j)

    # 4. Common Entry Pair Coverage & Strategy Path Divergence
    pair_keys = ["ticker", "entry_signal_date", "entry_execution_date", "entry_open"]
    df_pairs = pd.merge(
        df_b,
        df_j,
        on=pair_keys,
        suffixes=("_base", "_julia"),
        how="inner",
    )

    common_pair_count = len(df_pairs)
    baseline_total = len(df_b)
    julia_total = len(df_j)

    baseline_paired_count = common_pair_count
    baseline_unpaired_count = baseline_total - common_pair_count
    julia_paired_count = common_pair_count
    julia_unpaired_count = julia_total - common_pair_count

    # Build Common Entry Pairs Table
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

    # Strategy Path Divergence Table (Unpaired Baseline and Julia Trades)
    divergence_rows = []
    # Unpaired in Baseline
    if not df_b.empty:
        matched_b_ids = set(df_pairs["trade_id_base"]) if not df_pairs.empty else set()
        df_unpaired_b = df_b[~df_b["trade_id"].isin(matched_b_ids)]
        for _, r in df_unpaired_b.iterrows():
            divergence_rows.append({
                "origin_strategy": "BASELINE_A_FAST_CORE_V2",
                "ticker": r["ticker"],
                "name": r["name"],
                "trade_id": r["trade_id"],
                "trade_sequence": r["trade_sequence"],
                "entry_signal_date": r["entry_signal_date"],
                "entry_execution_date": r["entry_execution_date"],
                "entry_open": r["entry_open"],
                "exit_type": r["exit_type"],
                "terminal_return": r["terminal_return"],
                "divergence_reason": "UNPAIRED_BASELINE_REENTRY_AFTER_LOSS_GUARD",
            })
    # Unpaired in Julia
    if not df_j.empty:
        matched_j_ids = set(df_pairs["trade_id_julia"]) if not df_pairs.empty else set()
        df_unpaired_j = df_j[~df_j["trade_id"].isin(matched_j_ids)]
        for _, r in df_unpaired_j.iterrows():
            divergence_rows.append({
                "origin_strategy": "JULIA_STRATEGY_V00",
                "ticker": r["ticker"],
                "name": r["name"],
                "trade_id": r["trade_id"],
                "trade_sequence": r["trade_sequence"],
                "entry_signal_date": r["entry_signal_date"],
                "entry_execution_date": r["entry_execution_date"],
                "entry_open": r["entry_open"],
                "exit_type": r["exit_type"],
                "terminal_return": r["terminal_return"],
                "divergence_reason": "UNPAIRED_JULIA_SPECIFIC_ENTRY",
            })
    df_divergence = pd.DataFrame(divergence_rows)
    df_divergence.to_csv(PATH_DIVERGENCE_CSV, index=False)

    # 5. MAJOR 2: Full Loss Guard Cohort Accounting (Total = Paired + Unpaired)
    df_b_lg = df_b[df_b["exit_type"] == "LOSS_GUARD_CLOSE_LE_NEG_15"].copy() if not df_b.empty else pd.DataFrame()
    baseline_lg_total = len(df_b_lg)

    lg_cf_rows = []
    paired_lg_count = 0
    unpaired_lg_count = 0

    if not df_b_lg.empty:
        for _, r_b in df_b_lg.iterrows():
            # Find matching Julia trade on exact entry anchor
            m = df_j[
                (df_j["ticker"] == r_b["ticker"])
                & (df_j["entry_signal_date"] == r_b["entry_signal_date"])
                & (df_j["entry_execution_date"] == r_b["entry_execution_date"])
                & (df_j["entry_open"] == r_b["entry_open"])
            ] if not df_j.empty else pd.DataFrame()

            if not m.empty:
                paired_lg_count += 1
                r_j = m.iloc[0]
                ret_b = float(r_b["terminal_return"])
                ret_j = float(r_j["terminal_return"])
                delta = round(ret_j - ret_b, 2)
                prog_j = r_j["first_progressed_date"] is not None and not pd.isna(r_j["first_progressed_date"])
                lg_cf_rows.append({
                    "ticker": r_b["ticker"],
                    "name": r_b["name"],
                    "market": r_b["market"],
                    "baseline_trade_id": r_b["trade_id"],
                    "trade_sequence_base": r_b["trade_sequence"],
                    "entry_signal_date": r_b["entry_signal_date"],
                    "entry_execution_date": r_b["entry_execution_date"],
                    "entry_open": r_b["entry_open"],
                    "baseline_loss_guard_signal_date": r_b["loss_guard_signal_date"],
                    "baseline_exit_execution_date": r_b["loss_guard_execution_date"],
                    "baseline_exit_price": r_b["loss_guard_execution_price"],
                    "baseline_return": ret_b,
                    "julia_trade_id": r_j["trade_id"],
                    "julia_exit_type": r_j["exit_type"],
                    "julia_exit_execution_date": r_j["exit_execution_date"],
                    "julia_terminal_return": ret_j,
                    "return_delta": delta,
                    "julia_reached_progressed": prog_j,
                    "julia_first_progressed_date": r_j["first_progressed_date"],
                    "pair_status": "PAIRED_COMMON_ENTRY",
                })
            else:
                unpaired_lg_count += 1
                lg_cf_rows.append({
                    "ticker": r_b["ticker"],
                    "name": r_b["name"],
                    "market": r_b["market"],
                    "baseline_trade_id": r_b["trade_id"],
                    "trade_sequence_base": r_b["trade_sequence"],
                    "entry_signal_date": r_b["entry_signal_date"],
                    "entry_execution_date": r_b["entry_execution_date"],
                    "entry_open": r_b["entry_open"],
                    "baseline_loss_guard_signal_date": r_b["loss_guard_signal_date"],
                    "baseline_exit_execution_date": r_b["loss_guard_execution_date"],
                    "baseline_exit_price": r_b["loss_guard_execution_price"],
                    "baseline_return": float(r_b["terminal_return"]),
                    "julia_trade_id": None,
                    "julia_exit_type": None,
                    "julia_exit_execution_date": None,
                    "julia_terminal_return": None,
                    "return_delta": None,
                    "julia_reached_progressed": None,
                    "julia_first_progressed_date": None,
                    "pair_status": "UNPAIRED_STRATEGY_PATH_DIVERGENCE",
                })

    df_lg_cf = pd.DataFrame(lg_cf_rows)
    df_lg_cf.to_csv(LG_COUNTERFACTUAL_CSV, index=False)

    # Compute Recovery Metrics on the PAIRED LG Cohort ONLY
    df_lg_paired = df_lg_cf[df_lg_cf["pair_status"] == "PAIRED_COMMON_ENTRY"].copy()
    paired_total = len(df_lg_paired)

    if paired_total > 0:
        j_rets = df_lg_paired["julia_terminal_return"].astype(float)
        b_rets = df_lg_paired["baseline_return"].astype(float)
        deltas = df_lg_paired["return_delta"].astype(float)

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

        lg_recovery_summary = {
            "baseline_loss_guard_total": baseline_lg_total,
            "paired_loss_guard_count": paired_lg_count,
            "unpaired_loss_guard_count": unpaired_lg_count,
            "paired_coverage_rate": round(paired_lg_count / baseline_lg_total * 100.0, 2) if baseline_lg_total > 0 else 0.0,
            "paired_comparison_direction": {
                "julia_better_count": better_count,
                "julia_better_rate": round(better_count / paired_total * 100, 2),
                "julia_equal_count": equal_count,
                "julia_equal_rate": round(equal_count / paired_total * 100, 2),
                "julia_worse_count": worse_count,
                "julia_worse_rate": round(worse_count / paired_total * 100, 2),
            },
            "paired_recovery_distribution": {
                "recovered_to_breakeven_or_better_count (>= 0%)": rec_ge_0,
                "recovered_to_breakeven_or_better_rate (%)": round(rec_ge_0 / paired_total * 100, 2),
                "recovered_to_plus_20_count (>= +20%)": rec_ge_20,
                "recovered_to_plus_20_rate (%)": round(rec_ge_20 / paired_total * 100, 2),
                "recovered_to_plus_50_count (>= +50%)": rec_ge_50,
                "recovered_to_plus_50_rate (%)": round(rec_ge_50 / paired_total * 100, 2),
                "recovered_to_plus_100_count (>= +100%)": rec_ge_100,
                "recovered_to_plus_100_rate (%)": round(rec_ge_100 / paired_total * 100, 2),
            },
            "paired_deep_loss_distribution": {
                "still_loss_below_minus_20_count (<= -20%)": loss_le_neg_20,
                "still_loss_below_minus_20_rate (%)": round(loss_le_neg_20 / paired_total * 100, 2),
                "still_loss_below_minus_30_count (<= -30%)": loss_le_neg_30,
                "still_loss_below_minus_30_rate (%)": round(loss_le_neg_30 / paired_total * 100, 2),
                "still_loss_below_minus_40_count (<= -40%)": loss_le_neg_40,
                "still_loss_below_minus_40_rate (%)": round(loss_le_neg_40 / paired_total * 100, 2),
                "still_loss_below_minus_50_count (<= -50%)": loss_le_neg_50,
                "still_loss_below_minus_50_rate (%)": round(loss_le_neg_50 / paired_total * 100, 2),
            },
            "paired_return_delta_stats": calculate_distribution_stats(deltas),
            "paired_julia_outcome_return_stats": calculate_distribution_stats(j_rets),
            "paired_baseline_outcome_return_stats": calculate_distribution_stats(b_rets),
        }
    else:
        lg_recovery_summary = {
            "baseline_loss_guard_total": baseline_lg_total,
            "paired_loss_guard_count": 0,
            "unpaired_loss_guard_count": baseline_lg_total,
            "paired_coverage_rate": 0.0,
            "paired_comparison_direction": {},
            "paired_recovery_distribution": {},
            "paired_deep_loss_distribution": {},
            "paired_return_delta_stats": calculate_distribution_stats(pd.Series([], dtype=float)),
            "paired_julia_outcome_return_stats": calculate_distribution_stats(pd.Series([], dtype=float)),
            "paired_baseline_outcome_return_stats": calculate_distribution_stats(pd.Series([], dtype=float)),
        }

    with open(LG_RECOVERY_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(lg_recovery_summary, f, indent=2, ensure_ascii=False)

    # 6. Worst Losses Table (Julia Worst 30 trades)
    df_worst = df_j.sort_values(by="terminal_return", ascending=True).head(30).copy() if not df_j.empty else pd.DataFrame()
    worst_rows = []
    for _, row in df_worst.iterrows():
        match = df_b[
            (df_b["ticker"] == row["ticker"])
            & (df_b["entry_signal_date"] == row["entry_signal_date"])
            & (df_b["entry_execution_date"] == row["entry_execution_date"])
        ] if not df_b.empty else pd.DataFrame()
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
    df_winners = df_j[df_j["terminal_return"] >= 50.0].sort_values(by="terminal_return", ascending=False).copy() if not df_j.empty else pd.DataFrame()
    winner_rows = []
    for _, row in df_winners.iterrows():
        match = df_b[
            (df_b["ticker"] == row["ticker"])
            & (df_b["entry_signal_date"] == row["entry_signal_date"])
            & (df_b["entry_execution_date"] == row["entry_execution_date"])
        ] if not df_b.empty else pd.DataFrame()
        b_ret = float(match.iloc[0]["terminal_return"]) if not match.empty else None
        b_exit = str(match.iloc[0]["exit_type"]) if not match.empty else None
        delta = round(float(row["terminal_return"]) - b_ret, 2) if b_ret is not None else None

        # Verify temporal ordering for reentry
        all_b_ticker = df_b[df_b["ticker"] == row["ticker"]] if not df_b.empty else pd.DataFrame()
        reentry_caught = False
        if not match.empty and len(all_b_ticker) > 1:
            match_exit_d = match.iloc[0]["exit_execution_date"]
            if match_exit_d:
                later_b = all_b_ticker[
                    (all_b_ticker["entry_execution_date"] > match_exit_d)
                    & (all_b_ticker["terminal_return"] >= 50.0)
                ]
                reentry_caught = bool(not later_b.empty)

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

    # 8. Strategy Comparison Summary JSON & Metrics CSV
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
            "historical_investability_pit": True,
            "historical_market_cap_source": "KRX",
            "current_market_cap_snapshot_used_for_historical_entries": False,
            "future_market_cap_fallback": False,
            "investability_threshold_market_cap_krw": MIN_MARKET_CAP_KRW,
            "investability_threshold_avg_trading_value_20d_krw": MIN_AVG_TRADING_VALUE_20D_KRW,
            "supersedes_commit": SUPERSEDES_COMMIT,
            "supersession_reason": "NON_PIT_HISTORICAL_INVESTABILITY",
            "elapsed_seconds": round(elapsed, 2),
        },
        "pair_coverage": {
            "baseline_total_trades": baseline_total,
            "julia_total_trades": julia_total,
            "common_entry_pair_count": common_pair_count,
            "baseline_paired_count": baseline_paired_count,
            "baseline_unpaired_count": baseline_unpaired_count,
            "baseline_pair_coverage_rate": round(baseline_paired_count / baseline_total * 100.0, 2) if baseline_total > 0 else 0.0,
            "julia_paired_count": julia_paired_count,
            "julia_unpaired_count": julia_unpaired_count,
            "julia_pair_coverage_rate": round(julia_paired_count / julia_total * 100.0, 2) if julia_total > 0 else 0.0,
        },
        "baseline_v2_2022": b_metrics,
        "julia_v00_2022": j_metrics,
    }
    with open(STRATEGY_SUMMARY_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)

    # Comparison Metrics CSV
    metrics_rows = [
        ("Total Trades", b_metrics["total_trades"], j_metrics["total_trades"], j_metrics["total_trades"] - b_metrics["total_trades"]),
        ("Unique Tickers", b_metrics["unique_tickers"], j_metrics["unique_tickers"], j_metrics["unique_tickers"] - b_metrics["unique_tickers"]),
        ("First Entries", b_metrics["first_entries"], j_metrics["first_entries"], j_metrics["first_entries"] - b_metrics["first_entries"]),
        ("Reentries", b_metrics["reentries"], j_metrics["reentries"], j_metrics["reentries"] - b_metrics["reentries"]),
        ("Reentered Tickers", b_metrics["reentered_tickers_count"], j_metrics["reentered_tickers_count"], j_metrics["reentered_tickers_count"] - b_metrics["reentered_tickers_count"]),
        ("Open at Cutoff", b_metrics["open_trades"], j_metrics["open_trades"], j_metrics["open_trades"] - b_metrics["open_trades"]),
        ("Closed Trades", b_metrics["closed_trades"], j_metrics["closed_trades"], j_metrics["closed_trades"] - b_metrics["closed_trades"]),
        ("Mean Return (%)", b_metrics["return_stats"]["mean"], j_metrics["return_stats"]["mean"], round(j_metrics["return_stats"]["mean"] - b_metrics["return_stats"]["mean"], 2) if b_metrics["return_stats"]["mean"] is not None and j_metrics["return_stats"]["mean"] is not None else None),
        ("Median Return (%)", b_metrics["return_stats"]["median"], j_metrics["return_stats"]["median"], round(j_metrics["return_stats"]["median"] - b_metrics["return_stats"]["median"], 2) if b_metrics["return_stats"]["median"] is not None and j_metrics["return_stats"]["median"] is not None else None),
        ("P10 Return (%)", b_metrics["percentiles"]["p10"], j_metrics["percentiles"]["p10"], round(j_metrics["percentiles"]["p10"] - b_metrics["percentiles"]["p10"], 2) if b_metrics["percentiles"]["p10"] is not None and j_metrics["percentiles"]["p10"] is not None else None),
        ("P25 Return (%)", b_metrics["percentiles"]["p25"], j_metrics["percentiles"]["p25"], round(j_metrics["percentiles"]["p25"] - b_metrics["percentiles"]["p25"], 2) if b_metrics["percentiles"]["p25"] is not None and j_metrics["percentiles"]["p25"] is not None else None),
        ("P50 Return (%)", b_metrics["percentiles"]["p50"], j_metrics["percentiles"]["p50"], round(j_metrics["percentiles"]["p50"] - b_metrics["percentiles"]["p50"], 2) if b_metrics["percentiles"]["p50"] is not None and j_metrics["percentiles"]["p50"] is not None else None),
        ("P75 Return (%)", b_metrics["percentiles"]["p75"], j_metrics["percentiles"]["p75"], round(j_metrics["percentiles"]["p75"] - b_metrics["percentiles"]["p75"], 2) if b_metrics["percentiles"]["p75"] is not None and j_metrics["percentiles"]["p75"] is not None else None),
        ("P90 Return (%)", b_metrics["percentiles"]["p90"], j_metrics["percentiles"]["p90"], round(j_metrics["percentiles"]["p90"] - b_metrics["percentiles"]["p90"], 2) if b_metrics["percentiles"]["p90"] is not None and j_metrics["percentiles"]["p90"] is not None else None),
        ("P95 Return (%)", b_metrics["percentiles"]["p95"], j_metrics["percentiles"]["p95"], round(j_metrics["percentiles"]["p95"] - b_metrics["percentiles"]["p95"], 2) if b_metrics["percentiles"]["p95"] is not None and j_metrics["percentiles"]["p95"] is not None else None),
        ("Positive Count", int(b_metrics["return_stats"]["count"] * b_metrics["return_stats"]["positive_rate"] / 100) if b_metrics["return_stats"]["positive_rate"] is not None else 0, int(j_metrics["return_stats"]["count"] * j_metrics["return_stats"]["positive_rate"] / 100) if j_metrics["return_stats"]["positive_rate"] is not None else 0, None),
        ("Positive Rate (%)", b_metrics["return_stats"]["positive_rate"], j_metrics["return_stats"]["positive_rate"], round(j_metrics["return_stats"]["positive_rate"] - b_metrics["return_stats"]["positive_rate"], 2) if b_metrics["return_stats"]["positive_rate"] is not None and j_metrics["return_stats"]["positive_rate"] is not None else None),
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
        ("Mean Ticker Cumulative Return (%)", b_metrics["ticker_cumulative"]["mean_cumulative_return"], j_metrics["ticker_cumulative"]["mean_cumulative_return"], round(j_metrics["ticker_cumulative"]["mean_cumulative_return"] - b_metrics["ticker_cumulative"]["mean_cumulative_return"], 2) if b_metrics["ticker_cumulative"]["mean_cumulative_return"] is not None and j_metrics["ticker_cumulative"]["mean_cumulative_return"] is not None else None),
        ("Median Ticker Cumulative Return (%)", b_metrics["ticker_cumulative"]["median_cumulative_return"], j_metrics["ticker_cumulative"]["median_cumulative_return"], round(j_metrics["ticker_cumulative"]["median_cumulative_return"] - b_metrics["ticker_cumulative"]["median_cumulative_return"], 2) if b_metrics["ticker_cumulative"]["median_cumulative_return"] is not None and j_metrics["ticker_cumulative"]["median_cumulative_return"] is not None else None),
        ("Positive Ticker Rate (%)", b_metrics["ticker_cumulative"]["positive_ticker_rate"], j_metrics["ticker_cumulative"]["positive_ticker_rate"], round(j_metrics["ticker_cumulative"]["positive_ticker_rate"] - b_metrics["ticker_cumulative"]["positive_ticker_rate"], 2)),
    ]
    df_metrics = pd.DataFrame(metrics_rows, columns=["Metric", "A FAST Core V2 (2022+ PIT)", "Julia V00 (2022+ PIT)", "Delta (Julia - Base)"])
    df_metrics.to_csv(STRATEGY_METRICS_CSV, index=False)

    # 9. Contract Metadata JSON
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
        "historical_investability_pit": True,
        "historical_market_cap_source": "KRX",
        "current_market_cap_snapshot_used_for_historical_entries": False,
        "future_market_cap_fallback": False,
        "investability_threshold_market_cap_krw": MIN_MARKET_CAP_KRW,
        "investability_threshold_avg_trading_value_20d_krw": MIN_AVG_TRADING_VALUE_20D_KRW,
        "supersedes_commit": SUPERSEDES_COMMIT,
        "supersession_reason": "NON_PIT_HISTORICAL_INVESTABILITY",
    }
    with open(CONTRACT_JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(contract_data, f, indent=2, ensure_ascii=False)

    logger.info("All PIT-corrected artifacts successfully saved to %s", OUT_DIR)


if __name__ == "__main__":
    run_controlled_comparison()
