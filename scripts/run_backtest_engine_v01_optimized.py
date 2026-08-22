#!/usr/bin/env python
"""BACKTEST_PERFORMANCE_ENGINEERING_V01 -- Optimized Full-Universe Golden Parity Run.

Re-executes the exact same 2022-01-01..2026-08-14 controlled comparative
backtest as scripts/run_julia_proxy_market_cap_v01.py (Baseline V2 vs Julia
V00, Primary vs Conservative Boundary Sensitivity, Proxy Method Validation),
using the caching layer introduced for this performance-engineering task:

  - trend_scanner.backtest.context.TickerDataCache: memoizes per-ticker
    parquet loads (used both directly and via
    ProxyHistoricalMarketCapRegistry(cache=...)).
  - trend_scanner.backtest.feature_cache.FastSnapshotCache /
    MonthlySnapshotCache: memoizes per-(ticker, reference_date) Pattern
    A / FAST evaluations, shared across all 4 strategy passes
    (Baseline/Julia x Primary/Sensitivity) since those passes are
    strategy-invariant with respect to Pattern A / FAST.
  - trend_scanner.backtest.persistent_cache.PersistentFeatureCacheStore:
    disk-backed cross-process reuse of the above two caches, so a future
    research run (e.g. a different min_market_cap_krw experiment) does not
    pay the full Pattern A / FAST rebuild cost again if the frozen
    contracts and source OHLCV universe are unchanged.

This script NEVER writes into artifacts/strategies/julia/proxy_market_cap_v01/
(the frozen golden research namespace, w.md Section 61). Optimized-engine
trade-level CSVs and aggregate summaries ARE persisted (not just held in
memory) under artifacts/performance/backtest_engine_v01/full_run/, in a
namespace distinct from the golden research directory, specifically so that
a parity-comparator bug fix can be re-verified via
scripts/compare_backtest_engine_v01_parity.py without re-running this
(80+ minute) simulation.

Usage:
  python scripts/run_backtest_engine_v01_optimized.py             # full 2,506-ticker run
  python scripts/run_backtest_engine_v01_optimized.py --limit 30  # plumbing smoke test only
    (a --limit run will NOT match golden counts -- it only proves the script
    runs end-to-end; counts/parity are expected to differ from the golden
    845/687 full-universe run, and --limit runs do not persist to
    artifacts/ or update the persistent feature cache.)
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from typing import Any
import warnings

warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=DeprecationWarning)

import pandas as pd

from trend_scanner.backtest.context import TickerDataCache
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.parity import compare_trade_csvs, diff_summary_dicts
from trend_scanner.backtest.persistent_cache import PersistentFeatureCacheStore
from trend_scanner.backtest.snapshot_context import (
    PrecomputedTickerContext,
    build_precomputed_ticker_context,
)
from trend_scanner.validation.julia_proxy_market_cap_v01 import (
    ProxyHistoricalMarketCapRegistry,
    calculate_strategy_metrics,
    pair_common_entry_trades,
    run_proxy_method_validation,
)
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

GOLDEN_DIR = ROOT / "artifacts/strategies/julia/proxy_market_cap_v01"
PERF_DIR = ROOT / "artifacts/performance/backtest_engine_v01"
FULL_RUN_DIR = PERF_DIR / "full_run"


def run_optimized_backtest(limit: int | None = None) -> dict[str, Any]:
    logger.info("Initializing Optimized Backtest Engine V01 (BACKTEST_PERFORMANCE_ENGINEERING_V01)...")

    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    ticker_cache = TickerDataCache(base_dir=ROOT / "data/raw/stocks")
    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()

    persistent_store = PersistentFeatureCacheStore(
        score_contract_path=SCORE_CONTRACT_PATH,
        stage_contract_path=STAGE_CONTRACT_PATH,
        source_data_dir=ROOT / "data/raw/stocks",
    )
    persistent_cache_hit = persistent_store.load_into(fast_cache, monthly_cache)
    preloaded_fast_count = len(fast_cache)
    preloaded_monthly_count = len(monthly_cache)

    timings: dict[str, float] = {}

    # 1. Proxy Method Validation (reuses ticker_cache instead of a fresh ParquetCache)
    t0 = time.perf_counter()
    df_val, val_summary = run_proxy_method_validation(ROOT, cache=ticker_cache)
    timings["proxy_validation_seconds"] = round(time.perf_counter() - t0, 3)
    logger.info("Proxy Validation Complete: N=%d, MAPE=%.2f%%", val_summary["validation_sample_count"], val_summary["mean_absolute_percentage_error"])

    # 2. Registry + Universe
    proxy_registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=ticker_cache)
    stock_files = sorted((ROOT / "data/raw/stocks").glob("*.parquet"))
    if limit is not None:
        stock_files = stock_files[:limit]
    master_path = ROOT / "data/raw/stocks_master.csv"
    master_dict: dict[str, tuple[str, str]] = {}
    if master_path.exists():
        df_m = pd.read_csv(master_path, dtype={"ticker": str})
        for _, r in df_m.iterrows():
            master_dict[str(r["ticker"]).zfill(6)] = (str(r.get("name", "")), str(r.get("market", "KOSPI")))
    universe = [(sf.stem, *master_dict.get(sf.stem, (sf.stem, "KOSPI"))) for sf in stock_files]
    logger.info("Universe size: %d tickers%s", len(universe), " (--limit smoke test)" if limit else "")

    # Precomputed Ticker Snapshot Context (BACKTEST_PERFORMANCE_ENGINEERING_V01
    # Phase 4): one per ticker, built lazily on first use and reused across
    # Baseline/Julia x Primary/Sensitivity (all 4 passes share the same
    # strategy-invariant weekly/monthly resample for that ticker).
    ticker_contexts: dict[str, PrecomputedTickerContext] = {}

    def _context_for(ticker: str, name: str, daily_df: pd.DataFrame) -> PrecomputedTickerContext:
        ctx = ticker_contexts.get(ticker)
        if ctx is None:
            ctx = build_precomputed_ticker_context(ticker, name, daily_df)
            ticker_contexts[ticker] = ctx
        return ctx

    # 3. Primary Simulation (Baseline V2 vs Julia V00)
    t0 = time.perf_counter()
    baseline_trades, julia_trades = [], []
    for idx, (ticker, name, market) in enumerate(universe):
        if (idx + 1) % 500 == 0 or idx == len(universe) - 1:
            logger.info("Primary: simulated %d / %d tickers...", idx + 1, len(universe))
        daily_df = ticker_cache.load(ticker)
        if daily_df is None or daily_df.empty:
            continue
        context = _context_for(ticker, name, daily_df)
        b_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=True, market_cap_registry=proxy_registry,
            fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
            snapshot_context=context,
        )
        j_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=False, market_cap_registry=proxy_registry,
            fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
            snapshot_context=context,
        )
        baseline_trades.extend(b_t)
        julia_trades.extend(j_t)
    timings["primary_simulation_seconds"] = round(time.perf_counter() - t0, 3)
    logger.info("Primary Simulation Complete: Baseline=%d, Julia=%d", len(baseline_trades), len(julia_trades))

    # 4. Conservative Boundary Sensitivity Simulation
    t0 = time.perf_counter()
    sens_baseline_trades, sens_julia_trades = [], []
    for ticker, name, market in universe:
        daily_df = ticker_cache.load(ticker)
        if daily_df is None or daily_df.empty:
            continue
        context = _context_for(ticker, name, daily_df)
        sb_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=True, market_cap_registry=proxy_registry, sensitivity_mode=True,
            fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
            snapshot_context=context,
        )
        sj_t = simulate_ticker_strategy_2022(
            ticker, name, market, daily_df, score_contract, stage_contract,
            enable_loss_guard=False, market_cap_registry=proxy_registry, sensitivity_mode=True,
            fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
            snapshot_context=context,
        )
        sens_baseline_trades.extend(sb_t)
        sens_julia_trades.extend(sj_t)
    timings["sensitivity_simulation_seconds"] = round(time.perf_counter() - t0, 3)
    logger.info("Sensitivity Simulation Complete: Baseline=%d, Julia=%d", len(sens_baseline_trades), len(sens_julia_trades))

    b_metrics = calculate_strategy_metrics(baseline_trades)
    j_metrics = calculate_strategy_metrics(julia_trades)

    # 5. Loss Guard Cohort Accounting (mirrors run_julia_proxy_market_cap_v01.py Step 6)
    paired_records, _unpaired_b, _unpaired_j = pair_common_entry_trades(baseline_trades, julia_trades)
    b_lg_trades = [t for t in baseline_trades if t.loss_guard_triggered]
    paired_lookup = {(p["ticker"], p["entry_signal_date"], p["entry_execution_date"]): p for p in paired_records}
    lg_recovered_count = lg_deeper_loss_count = lg_progressed_count = 0
    paired_lg_count = 0
    for t in b_lg_trades:
        key = (t.ticker, t.entry_signal_date, t.entry_execution_date)
        p = paired_lookup.get(key)
        if p is None:
            continue
        paired_lg_count += 1
        if p["julia_terminal_return"] > p["baseline_terminal_return"]:
            lg_recovered_count += 1
        if p["julia_terminal_return"] < p["baseline_terminal_return"]:
            lg_deeper_loss_count += 1
        if p["julia_first_progressed_date"]:
            lg_progressed_count += 1
    total_lg_b = len(b_lg_trades)
    unpaired_lg_count = total_lg_b - paired_lg_count
    lg_summary = {
        "baseline_loss_guard_total": total_lg_b,
        "paired_loss_guard_count": paired_lg_count,
        "unpaired_loss_guard_count": unpaired_lg_count,
        "cohort_accounting_identity_holds": bool(total_lg_b == paired_lg_count + unpaired_lg_count),
        "julia_recovered_higher_return_count": lg_recovered_count,
        "julia_deeper_loss_count": lg_deeper_loss_count,
        "julia_reached_progressed_count": lg_progressed_count,
    }

    total_elapsed = sum(timings.values())
    timings["total_elapsed_seconds"] = round(total_elapsed, 3)

    if limit is None:
        persistent_store.save_from(fast_cache, monthly_cache)

    return {
        "timings": timings,
        "ticker_data_cache": ticker_cache.diagnostics(),
        "fast_snapshot_cache": {"evaluation_count": fast_cache.evaluation_count, "cache_hit_count": fast_cache.cache_hit_count},
        "monthly_snapshot_cache": {"evaluation_count": monthly_cache.evaluation_count, "cache_hit_count": monthly_cache.cache_hit_count},
        "persistent_cache": {
            "hit": persistent_cache_hit,
            "preloaded_fast_snapshot_count": preloaded_fast_count,
            "preloaded_monthly_snapshot_count": preloaded_monthly_count,
        },
        "baseline_trades": baseline_trades,
        "julia_trades": julia_trades,
        "b_metrics": b_metrics,
        "j_metrics": j_metrics,
        "lg_summary": lg_summary,
        "val_summary": val_summary,
        "limited": limit is not None,
    }


def persist_optimized_artifacts(run_result: dict[str, Any]) -> None:
    FULL_RUN_DIR.mkdir(parents=True, exist_ok=True)
    pd.DataFrame([asdict(t) for t in run_result["baseline_trades"]]).to_csv(FULL_RUN_DIR / "optimized_baseline_trades.csv", index=False)
    pd.DataFrame([asdict(t) for t in run_result["julia_trades"]]).to_csv(FULL_RUN_DIR / "optimized_julia_trades.csv", index=False)
    (FULL_RUN_DIR / "optimized_b_metrics.json").write_text(json.dumps(run_result["b_metrics"], indent=2, ensure_ascii=False), encoding="utf-8")
    (FULL_RUN_DIR / "optimized_j_metrics.json").write_text(json.dumps(run_result["j_metrics"], indent=2, ensure_ascii=False), encoding="utf-8")
    (FULL_RUN_DIR / "optimized_lg_summary.json").write_text(json.dumps(run_result["lg_summary"], indent=2, ensure_ascii=False), encoding="utf-8")
    (FULL_RUN_DIR / "optimized_val_summary.json").write_text(json.dumps(run_result["val_summary"], indent=2, ensure_ascii=False), encoding="utf-8")


def compare_against_golden() -> dict[str, Any]:
    """Re-verifiable from persisted artifacts alone -- see
    scripts/compare_backtest_engine_v01_parity.py for the standalone
    re-verification entry point that calls this same logic without
    re-running the simulation."""
    baseline_cmp = compare_trade_csvs(GOLDEN_DIR / "baseline_v2_proxy_trades.csv", FULL_RUN_DIR / "optimized_baseline_trades.csv")
    julia_cmp = compare_trade_csvs(GOLDEN_DIR / "julia_v00_proxy_trades.csv", FULL_RUN_DIR / "optimized_julia_trades.csv")

    golden_summary = json.loads((GOLDEN_DIR / "strategy_comparison_summary.json").read_text(encoding="utf-8"))
    golden_lg = json.loads((GOLDEN_DIR / "loss_guard_recovery_summary.json").read_text(encoding="utf-8"))
    golden_val = json.loads((GOLDEN_DIR / "proxy_market_cap_validation_summary.json").read_text(encoding="utf-8"))
    opt_b_metrics = json.loads((FULL_RUN_DIR / "optimized_b_metrics.json").read_text(encoding="utf-8"))
    opt_j_metrics = json.loads((FULL_RUN_DIR / "optimized_j_metrics.json").read_text(encoding="utf-8"))
    opt_lg = json.loads((FULL_RUN_DIR / "optimized_lg_summary.json").read_text(encoding="utf-8"))
    opt_val = json.loads((FULL_RUN_DIR / "optimized_val_summary.json").read_text(encoding="utf-8"))

    baseline_metrics_diff = diff_summary_dicts(golden_summary["baseline_v2_proxy"], opt_b_metrics)
    julia_metrics_diff = diff_summary_dicts(golden_summary["julia_v00_proxy"], opt_j_metrics)
    loss_guard_cohort_diff = diff_summary_dicts(golden_lg, opt_lg)
    proxy_validation_diff = diff_summary_dicts(golden_val, opt_val)

    exact_identity = (
        baseline_cmp["exact_trade_identity"] and julia_cmp["exact_trade_identity"]
        and not baseline_metrics_diff and not julia_metrics_diff
        and not loss_guard_cohort_diff and not proxy_validation_diff
    )

    return {
        "baseline": {**{k: v for k, v in baseline_cmp.items() if k != "mismatch_examples"}, "metrics_diff": baseline_metrics_diff},
        "julia": {**{k: v for k, v in julia_cmp.items() if k != "mismatch_examples"}, "metrics_diff": julia_metrics_diff},
        "loss_guard_cohort_diff": loss_guard_cohort_diff,
        "proxy_validation_diff": proxy_validation_diff,
        "mismatch_examples": {"baseline": baseline_cmp["mismatch_examples"], "julia": julia_cmp["mismatch_examples"]},
        "overall_exact_parity": exact_identity,
    }


def main() -> None:
    # w.md Phase 4 Section 4: wall_clock_total_seconds must cover the entire
    # user-perceived run lifecycle (run start / persistent cache load through
    # parity comparison completion), NOT just the sum of the individual
    # simulation-phase timings recorded in `timings["total_elapsed_seconds"]`
    # (which omits persistent cache load/save, universe build, artifact
    # serialization, and parity comparison itself).
    wall_clock_start = time.perf_counter()

    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Restrict universe to first N tickers (plumbing smoke test only, not a parity run)")
    args = parser.parse_args()

    run_result = run_optimized_backtest(limit=args.limit)

    if run_result["limited"]:
        wall_clock_total_seconds = round(time.perf_counter() - wall_clock_start, 3)
        print(json.dumps({
            "limited_smoke_test": True,
            "baseline_trade_count": len(run_result["baseline_trades"]),
            "julia_trade_count": len(run_result["julia_trades"]),
            "timings": run_result["timings"],
            "wall_clock_total_seconds": wall_clock_total_seconds,
            "ticker_data_cache": run_result["ticker_data_cache"],
            "fast_snapshot_cache": run_result["fast_snapshot_cache"],
            "monthly_snapshot_cache": run_result["monthly_snapshot_cache"],
        }, indent=2, ensure_ascii=False), flush=True)
        return

    persist_optimized_artifacts(run_result)
    full_parity_summary = compare_against_golden()
    full_parity_summary["limited_smoke_test"] = False
    wall_clock_total_seconds = round(time.perf_counter() - wall_clock_start, 3)
    (PERF_DIR / "full_parity_summary.json").write_text(json.dumps(full_parity_summary, indent=2, ensure_ascii=False), encoding="utf-8")

    runtime_comparison = {
        "historical_runtime_minutes": 330,
        "historical_runtime_source": "w.md Section 51 (37da35e closure commit reference), not re-executed this run",
        "optimized_cold_runtime_seconds": run_result["timings"]["total_elapsed_seconds"],
        "optimized_cold_runtime_minutes": round(run_result["timings"]["total_elapsed_seconds"] / 60.0, 2),
        "wall_clock_total_seconds": wall_clock_total_seconds,
        "wall_clock_total_minutes": round(wall_clock_total_seconds / 60.0, 2),
        "wall_clock_measurement_scope": (
            "run start (before persistent cache load) -> persistent cache load -> "
            "proxy validation -> universe build -> Primary -> Sensitivity -> aggregation -> "
            "persistent cache save -> artifact serialization -> parity comparison "
            "(w.md Phase 4 Section 4); excludes only the write of this summary JSON itself, "
            "which cannot self-report its own write time"
        ),
        "speedup_cold_x": round((330 * 60) / run_result["timings"]["total_elapsed_seconds"], 2) if run_result["timings"]["total_elapsed_seconds"] > 0 else None,
        "speedup_cold_wall_clock_x": round((330 * 60) / wall_clock_total_seconds, 2) if wall_clock_total_seconds > 0 else None,
        "timings_breakdown": run_result["timings"],
        "ticker_data_cache_diagnostics": run_result["ticker_data_cache"],
        "fast_snapshot_cache_diagnostics": run_result["fast_snapshot_cache"],
        "monthly_snapshot_cache_diagnostics": run_result["monthly_snapshot_cache"],
        "persistent_cache_diagnostics": run_result["persistent_cache"],
        "proxy_validation_observation_count": run_result["val_summary"].get("validation_sample_count"),
        "machine_context": {"python": "3.13", "note": "single local run, no controlled machine isolation"},
    }
    (PERF_DIR / "runtime_comparison.json").write_text(json.dumps(runtime_comparison, indent=2, ensure_ascii=False), encoding="utf-8")

    optimization_manifest = {
        "engine": "BACKTEST_PERFORMANCE_ENGINEERING_V01_OPTIMIZED",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "golden_reference_namespace": "artifacts/strategies/julia/proxy_market_cap_v01/ (untouched, read-only)",
        "output_namespace": "artifacts/performance/backtest_engine_v01/full_run/ (optimized-engine evidence, distinct namespace from golden research artifacts)",
        "production_logic_changed": False,
        "julia_proxy_research_artifacts_modified": False,
        "overall_exact_parity": full_parity_summary["overall_exact_parity"],
    }
    (PERF_DIR / "optimization_manifest.json").write_text(json.dumps(optimization_manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    print(json.dumps(full_parity_summary, indent=2, ensure_ascii=False), flush=True)

    if not full_parity_summary["overall_exact_parity"]:
        raise SystemExit("PERFORMANCE_OPTIMIZATION_REJECTED: golden parity mismatch detected. See full_parity_summary.json.")


if __name__ == "__main__":
    main()
