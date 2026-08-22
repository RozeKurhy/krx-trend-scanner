#!/usr/bin/env python
"""BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE4_2 -- Realistic Partial Backtest Benchmark.

w.md Phase 4.2 Major Fix 2 / Architect Review Major 2: the prior Phase 4.1
benchmark (scripts/benchmark_phase4_1.py) never passed a market_cap_registry
into simulate_ticker_strategy_2022(), so investability always failed
DATA_UNAVAILABLE and every measured trade_count was 0 -- it was measuring
FAST-scanning cost only, not the real strategy lifecycle (market-cap lookup
-> investability -> entry -> monthly lifecycle -> Loss Guard -> Exit3/Exit4
-> reentry). This script fixes that: it uses the SAME core dependencies and
execution path as scripts/run_backtest_engine_v01_optimized.py (TickerDataCache,
a real ProxyHistoricalMarketCapRegistry built from repository authority,
FastSnapshotCache, MonthlySnapshotCache, PrecomputedTickerContext, real
stocks_master.csv market info, real daily OHLCV) on a deterministic
stratified sample of the full ~2,506-ticker universe (not a sorted-first-N
slice, which would bias toward one listing cohort).

Proxy Method Validation itself (258,055 observations) is NOT re-run here --
only strategy_simulation runtime is measured; the previously-measured ~33s
proxy validation cost is added as a separate fixed overhead component when
projecting full wall-clock (w.md Section 5/15).

Compares the SAME two paths as benchmark_phase4_1.py (phase4_head:
enable_pre_window_pruning=False; phase4_1: True), both now realistic (real
registry passed through), each with its own fresh registry instance +
fresh empty FastSnapshotCache/MonthlySnapshotCache (w.md Section 11/12:
no audit-state cross-contamination, no persistent-cache interference,
registry construction excluded from strategy-simulation timing).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import numpy as np
import pandas as pd

from trend_scanner.backtest.context import TickerDataCache
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
import trend_scanner.validation.julia_strategy_v00 as julia_strategy_module
from trend_scanner.validation.julia_proxy_market_cap_v01 import ProxyHistoricalMarketCapRegistry
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
PERF_DIR = ROOT / "artifacts/performance/backtest_engine_v01"
STOCKS_DIR = ROOT / "data/raw/stocks"
MASTER_PATH = ROOT / "data/raw/stocks_master.csv"

# Measured previously (scripts/run_backtest_engine_v01_optimized.py full-universe
# run, see r.md Phase 4 report) -- not re-run in this partial benchmark.
MEASURED_PROXY_VALIDATION_SECONDS = 33.0
SERIALIZATION_AND_AGGREGATION_ALLOWANCE_MINUTES = 1.5


def _load_universe() -> list[tuple[str, str, str]]:
    """(ticker, name, market) for every ticker with a parquet file, matching
    scripts/run_backtest_engine_v01_optimized.py's universe construction."""
    stock_files = sorted(STOCKS_DIR.glob("*.parquet"))
    master_dict: dict[str, tuple[str, str]] = {}
    if MASTER_PATH.exists():
        df_m = pd.read_csv(MASTER_PATH, dtype={"ticker": str})
        for _, r in df_m.iterrows():
            master_dict[str(r["ticker"]).zfill(6)] = (str(r.get("name", "")), str(r.get("market", "KOSPI")))
    return [(sf.stem, *master_dict.get(sf.stem, (sf.stem, "KOSPI"))) for sf in stock_files]


def stratified_sample(universe: list[tuple[str, str, str]], n: int) -> list[tuple[str, str, str]]:
    """w.md Phase 4.2 Section 6/7: deterministic, evenly-spaced sample across
    the ENTIRE sorted universe (not sorted(...)[:n]), so listing-cohort /
    history-length / market bias in the ticker-code ordering doesn't skew
    the sample. Simple linspace-over-sorted-universe, no random seed needed
    since it's fully deterministic."""
    if n >= len(universe):
        return list(universe)
    idx = np.linspace(0, len(universe) - 1, n, dtype=int)
    seen: set[int] = set()
    sample = []
    for i in idx:
        if i not in seen:
            sample.append(universe[i])
            seen.add(i)
    return sample


def _classify_exit(exit_type: str) -> str | None:
    if exit_type.startswith("EXIT3"):
        return "exit3"
    if exit_type.startswith("EXIT4"):
        return "exit4"
    return None


def _run_realistic_path(
    sample: list[tuple[str, str, str]],
    score: dict,
    stage: dict,
    *,
    enable_pre_window_pruning: bool,
) -> dict:
    ticker_cache = TickerDataCache(base_dir=STOCKS_DIR)
    # Fresh registry per path (w.md Section 11): avoids one path's audit-log/
    # estimates-cache state leaking into the other's timing or counts.
    registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=ticker_cache)

    # Investability status tally via a counting wrapper -- InvestabilityEvaluationResult
    # has no built-in audit log (unlike the market-cap registry's _audit_records),
    # so this is instrumented the same way the earlier resample-call counter was.
    investability_counts: dict[str, int] = {}
    real_evaluate_investability = julia_strategy_module.evaluate_investability

    def counting_evaluate_investability(*args, **kwargs):
        res = real_evaluate_investability(*args, **kwargs)
        key = res.status.value if hasattr(res.status, "value") else str(res.status)
        investability_counts[key] = investability_counts.get(key, 0) + 1
        return res

    julia_strategy_module.evaluate_investability = counting_evaluate_investability

    baseline_trades: list = []
    julia_trades: list = []
    baseline_loss_guard_count = 0
    julia_loss_guard_count = 0
    baseline_exit3_count = baseline_exit4_count = 0
    julia_exit3_count = julia_exit4_count = 0
    baseline_multi_trade_ticker_count = 0
    julia_multi_trade_ticker_count = 0
    fast_cache_evals_total = 0
    monthly_cache_evals_total = 0
    disk_read_count_before = ticker_cache.disk_read_count

    try:
        t0 = time.perf_counter()
        for ticker, name, market in sample:
            daily = ticker_cache.load(ticker)
            if daily is None or daily.empty:
                continue
            context = build_precomputed_ticker_context(ticker, name, daily)
            fast_cache = FastSnapshotCache()
            monthly_cache = MonthlySnapshotCache()

            b_primary = simulate_ticker_strategy_2022(
                ticker, name, market, daily, score, stage,
                enable_loss_guard=True, market_cap_registry=registry,
                fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
                snapshot_context=context, enable_pre_window_pruning=enable_pre_window_pruning,
            )
            j_primary = simulate_ticker_strategy_2022(
                ticker, name, market, daily, score, stage,
                enable_loss_guard=False, market_cap_registry=registry,
                fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
                snapshot_context=context, enable_pre_window_pruning=enable_pre_window_pruning,
            )
            simulate_ticker_strategy_2022(
                ticker, name, market, daily, score, stage,
                enable_loss_guard=True, market_cap_registry=registry, sensitivity_mode=True,
                fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
                snapshot_context=context, enable_pre_window_pruning=enable_pre_window_pruning,
            )
            simulate_ticker_strategy_2022(
                ticker, name, market, daily, score, stage,
                enable_loss_guard=False, market_cap_registry=registry, sensitivity_mode=True,
                fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
                snapshot_context=context, enable_pre_window_pruning=enable_pre_window_pruning,
            )

            baseline_trades.extend(b_primary)
            julia_trades.extend(j_primary)
            if len(b_primary) > 1:
                baseline_multi_trade_ticker_count += 1
            if len(j_primary) > 1:
                julia_multi_trade_ticker_count += 1
            for t in b_primary:
                if t.loss_guard_triggered:
                    baseline_loss_guard_count += 1
                cls = _classify_exit(t.exit_type)
                if cls == "exit3":
                    baseline_exit3_count += 1
                elif cls == "exit4":
                    baseline_exit4_count += 1
            for t in j_primary:
                if t.loss_guard_triggered:
                    julia_loss_guard_count += 1
                cls = _classify_exit(t.exit_type)
                if cls == "exit3":
                    julia_exit3_count += 1
                elif cls == "exit4":
                    julia_exit4_count += 1

            fast_cache_evals_total += fast_cache.evaluation_count
            monthly_cache_evals_total += monthly_cache.evaluation_count
        elapsed = time.perf_counter() - t0
    finally:
        julia_strategy_module.evaluate_investability = real_evaluate_investability

    audit_records = registry.get_all_audit_records()
    market_cap_actual_query_count = sum(1 for r in audit_records if r.source_type == "ACTUAL_KRX")
    market_cap_proxy_query_count = sum(1 for r in audit_records if r.source_type != "ACTUAL_KRX")

    n = len(sample)
    return {
        "n_tickers": n,
        "elapsed_seconds": round(elapsed, 3),
        "sec_per_ticker": round(elapsed / n, 4) if n else None,
        "baseline_trade_count": len(baseline_trades),
        "julia_trade_count": len(julia_trades),
        "baseline_loss_guard_count": baseline_loss_guard_count,
        "julia_loss_guard_count": julia_loss_guard_count,
        "baseline_exit3_count": baseline_exit3_count,
        "baseline_exit4_count": baseline_exit4_count,
        "julia_exit3_count": julia_exit3_count,
        "julia_exit4_count": julia_exit4_count,
        "baseline_multi_trade_ticker_count": baseline_multi_trade_ticker_count,
        "julia_multi_trade_ticker_count": julia_multi_trade_ticker_count,
        "fast_evaluation_count": fast_cache_evals_total,
        "monthly_evaluation_count": monthly_cache_evals_total,
        "disk_read_count": ticker_cache.disk_read_count - disk_read_count_before,
        "market_cap_actual_query_count": market_cap_actual_query_count,
        "market_cap_proxy_query_count": market_cap_proxy_query_count,
        "investability_counts": investability_counts,
        "BENCHMARK_INVALID": not (len(baseline_trades) > 0 and len(julia_trades) > 0),
    }


def _projection_from_n(result: dict, universe_size: int) -> dict:
    per_ticker = result["sec_per_ticker"]
    projected_seconds = per_ticker * universe_size
    return {
        "projected_simulation_minutes": round(projected_seconds / 60.0, 2),
    }


def run_benchmark_for_n(universe: list[tuple[str, str, str]], n: int, score: dict, stage: dict) -> dict:
    sample = stratified_sample(universe, n)
    print(f"=== N={n} (actual sample size {len(sample)}) ===", flush=True)
    head = _run_realistic_path(sample, score, stage, enable_pre_window_pruning=False)
    print(f"phase4_head: {json.dumps(head)}", flush=True)
    optimized = _run_realistic_path(sample, score, stage, enable_pre_window_pruning=True)
    print(f"phase4_1: {json.dumps(optimized)}", flush=True)

    if head["BENCHMARK_INVALID"] or optimized["BENCHMARK_INVALID"]:
        print(f"WARNING: N={n} BENCHMARK_INVALID (trade_count=0 on at least one path) -- not usable for runtime projection", flush=True)

    speedup = round(head["elapsed_seconds"] / optimized["elapsed_seconds"], 2) if optimized["elapsed_seconds"] > 0 else None
    return {
        "sample_size": len(sample),
        "phase4_head": head,
        "phase4_1": optimized,
        "phase4_1_speedup_x": speedup,
        "projection": _projection_from_n(optimized, len(universe)) if not optimized["BENCHMARK_INVALID"] else None,
    }


def main() -> None:
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    universe = _load_universe()

    results: dict = {
        "sample_definition": {
            "method": "deterministic evenly-spaced (np.linspace) over the full sorted universe",
            "universe_size": len(universe),
        },
    }

    n100 = run_benchmark_for_n(universe, 100, score, stage)
    results["n100"] = n100

    n250 = run_benchmark_for_n(universe, 250, score, stage)
    results["n250"] = n250

    n100_proj = n100["projection"]["projected_simulation_minutes"] if n100["projection"] else None
    n250_proj = n250["projection"]["projected_simulation_minutes"] if n250["projection"] else None

    projection: dict = {
        "projected_simulation_minutes_n100": n100_proj,
        "projected_simulation_minutes_n250": n250_proj,
    }
    if n100_proj and n250_proj:
        diff_pct = abs(n100_proj - n250_proj) / max(n100_proj, n250_proj) * 100
        projection["n100_n250_diff_pct"] = round(diff_pct, 1)
        projection["projection_stable"] = diff_pct <= 10.0
        primary_minutes = n250_proj if diff_pct <= 10.0 else max(n100_proj, n250_proj)
        projection["strategy_projection_minutes"] = round(primary_minutes, 2)
        projection["proxy_validation_minutes"] = round(MEASURED_PROXY_VALIDATION_SECONDS / 60.0, 2)
        projection["serialization_and_parity_allowance_minutes"] = SERIALIZATION_AND_AGGREGATION_ALLOWANCE_MINUTES
        projection["projected_wall_clock_minutes"] = round(
            primary_minutes + MEASURED_PROXY_VALIDATION_SECONDS / 60.0 + SERIALIZATION_AND_AGGREGATION_ALLOWANCE_MINUTES, 2
        )
    projection["NOT_MEASURED_FULL_RUN"] = True
    results["projection"] = projection

    PERF_DIR.mkdir(parents=True, exist_ok=True)
    (PERF_DIR / "phase4_2_realistic_benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
