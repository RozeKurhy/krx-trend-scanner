#!/usr/bin/env python
"""BACKTEST_PERFORMANCE_ENGINEERING_V01 -- Phase 1 Profiling.

Measures real elapsed time and call/IO counts for the current (legacy) 2022+
Julia/Baseline comparative backtest pipeline against the optimized pipeline
(trend_scanner.backtest.context.TickerDataCache +
trend_scanner.backtest.feature_cache caches), on a representative ticker
subset -- per w.md Section 12 policy, this script does NOT re-run the full
~5h30 universe benchmark. It measures bottlenecks on a small subset first.

Strategy semantics are never touched here: this script only calls the
existing simulate_ticker_strategy_2022 / ProxyHistoricalMarketCapRegistry /
run_proxy_method_validation functions, with and without the new caches.

Outputs:
  artifacts/performance/backtest_engine_v01/baseline_profile.json
  artifacts/performance/backtest_engine_v01/optimization_profile.json
"""

from __future__ import annotations

import cProfile
import io
import json
import pstats
import sys
import time
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from trend_scanner.backtest.context import TickerDataCache
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.julia_proxy_market_cap_v01 import (
    ProxyHistoricalMarketCapRegistry,
    run_proxy_method_validation,
)
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
PERF_DIR = ROOT / "artifacts/performance/backtest_engine_v01"
STOCKS_DIR = ROOT / "data/raw/stocks"

# Representative sample per w.md Section 30 (§30 Representative Parity Sample).
REPRESENTATIVE_TICKERS = ["005930", "000660", "068270", "035420", "006730", "005710"]


class CountingParquetCache(ParquetCache):
    """Instrumentation-only subclass: counts .load() calls without changing behavior."""

    def __init__(self, base_dir: Path):
        super().__init__(base_dir=base_dir)
        self.disk_read_count = 0

    def load(self, ticker: str) -> pd.DataFrame | None:
        self.disk_read_count += 1
        return super().load(ticker)


def _pick_subset(n: int) -> list[str]:
    all_tickers = sorted(p.stem for p in STOCKS_DIR.glob("*.parquet"))
    subset = list(REPRESENTATIVE_TICKERS)
    if n > len(subset):
        stride = max(1, len(all_tickers) // (n - len(subset)))
        for t in all_tickers[::stride]:
            if t not in subset:
                subset.append(t)
            if len(subset) >= n:
                break
    return subset[:n]


def _run_pipeline(tickers: list[str], score_contract: dict, stage_contract: dict, use_caches: bool) -> dict:
    if use_caches:
        cache = TickerDataCache(base_dir=STOCKS_DIR)
        registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=cache)
        fast_cache = FastSnapshotCache()
        monthly_cache = MonthlySnapshotCache()
    else:
        cache = CountingParquetCache(base_dir=STOCKS_DIR)
        registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=cache)
        fast_cache = None
        monthly_cache = None

    total_trades = 0
    t_start = time.perf_counter()
    for ticker in tickers:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            continue
        for enable_lg in (True, False):
            for sens in (False, True):
                trades = simulate_ticker_strategy_2022(
                    ticker, ticker, "KOSPI", daily, score_contract, stage_contract,
                    enable_loss_guard=enable_lg, market_cap_registry=registry, sensitivity_mode=sens,
                    fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
                )
                total_trades += len(trades)
    elapsed = time.perf_counter() - t_start

    result = {
        "ticker_count": len(tickers),
        "pass_count_per_ticker": 4,
        "total_trades_all_passes": total_trades,
        "elapsed_seconds": round(elapsed, 4),
        "tickers_per_sec": round(len(tickers) / elapsed, 4) if elapsed > 0 else None,
    }
    if use_caches:
        result["ticker_data_cache"] = cache.diagnostics()
        result["fast_snapshot_cache"] = {"evaluation_count": fast_cache.evaluation_count, "cache_hit_count": fast_cache.cache_hit_count}
        result["monthly_snapshot_cache"] = {"evaluation_count": monthly_cache.evaluation_count, "cache_hit_count": monthly_cache.cache_hit_count}
    else:
        result["parquet_disk_reads"] = cache.disk_read_count
        result["fast_snapshot_cache"] = None
        result["monthly_snapshot_cache"] = None
    return result


def _profile_single_ticker_hotspots(ticker: str, score_contract: dict, stage_contract: dict, top_n: int = 15) -> list[dict]:
    """cProfile a single legacy (uncached) full 4-pass run for one ticker to
    identify top bottleneck functions by cumulative time (w.md Section 31)."""
    cache = ParquetCache(base_dir=STOCKS_DIR)
    registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=ParquetCache(base_dir=STOCKS_DIR))
    daily = cache.load(ticker)

    profiler = cProfile.Profile()
    profiler.enable()
    for enable_lg in (True, False):
        for sens in (False, True):
            simulate_ticker_strategy_2022(
                ticker, ticker, "KOSPI", daily, score_contract, stage_contract,
                enable_loss_guard=enable_lg, market_cap_registry=registry, sensitivity_mode=sens,
            )
    profiler.disable()

    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream).sort_stats("cumulative")
    stats.print_stats(top_n)

    rows = []
    stats_dict = stats.stats  # type: ignore[attr-defined]
    ranked = sorted(stats_dict.items(), key=lambda kv: kv[1][3], reverse=True)[:top_n]
    for (filename, lineno, funcname), (cc, nc, tt, ct, _callers) in ranked:
        rows.append({
            "function": f"{Path(filename).name}:{lineno}({funcname})",
            "call_count": nc,
            "total_time_seconds": round(tt, 4),
            "cumulative_time_seconds": round(ct, 4),
        })
    return rows


def _profile_proxy_validation(sample_stride: int) -> dict:
    """Compare cold ParquetCache vs TickerDataCache on the proxy validation
    loop (the 258,055-observation date-outer/ticker-inner loop), at a reduced
    sample_stride so the profiling run stays representative-scale (w.md
    Section 12: measure on a subset first, do not force a full-scale rerun
    here)."""
    cold_cache = CountingParquetCache(base_dir=STOCKS_DIR)
    t0 = time.perf_counter()
    df_cold, _ = run_proxy_method_validation(ROOT, sample_stride=sample_stride, cache=cold_cache)
    t_cold = time.perf_counter() - t0

    warm_cache = TickerDataCache(base_dir=STOCKS_DIR)
    t0 = time.perf_counter()
    df_warm, _ = run_proxy_method_validation(ROOT, sample_stride=sample_stride, cache=warm_cache)
    t_warm = time.perf_counter() - t0

    return {
        "sample_stride": sample_stride,
        "observation_count": int(len(df_cold)),
        "output_identical": bool(df_cold.equals(df_warm)),
        "cold_parquetcache": {"elapsed_seconds": round(t_cold, 4), "disk_read_count": cold_cache.disk_read_count},
        "warm_tickerdatacache": {"elapsed_seconds": round(t_warm, 4), **warm_cache.diagnostics()},
        "note": "Reduced-scale measurement (stride>1). Full sample_stride=1 IO reduction is realized identically at full scale in the optimized production run because the memoization is per-ticker, not per-stride.",
    }


def main() -> None:
    PERF_DIR.mkdir(parents=True, exist_ok=True)
    score_contract = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage_contract = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))

    # n=20/50 is sufficient to establish the bottleneck signature and speedup
    # factor representatively (w.md Section 10/12: measure on a subset, do
    # not force expensive full-scale reruns). n=100 legacy (uncached) was
    # measured to be prohibitively slow for a Phase 1 profiling pass and was
    # dropped in favor of finishing Phase 1 promptly; the optimized full
    # 2,506-ticker run (Section 49) is still executed once, in full, later.
    subset_sizes = [20, 50]
    baseline_runs = {}
    optimized_runs = {}
    for n in subset_sizes:
        tickers = _pick_subset(n)
        print(f"[profile] legacy pipeline, {n} tickers...", flush=True)
        baseline_runs[f"n{n}"] = _run_pipeline(tickers, score_contract, stage_contract, use_caches=False)
        print(f"[profile]   -> {baseline_runs[f'n{n}']['elapsed_seconds']}s", flush=True)
        print(f"[profile] optimized pipeline, {n} tickers...", flush=True)
        optimized_runs[f"n{n}"] = _run_pipeline(tickers, score_contract, stage_contract, use_caches=True)
        print(f"[profile]   -> {optimized_runs[f'n{n}']['elapsed_seconds']}s", flush=True)
        (PERF_DIR / "baseline_profile.partial.json").write_text(
            json.dumps({"runs_by_subset_size": baseline_runs}, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        (PERF_DIR / "optimization_profile.partial.json").write_text(
            json.dumps({"runs_by_subset_size": optimized_runs}, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    print("[profile] cProfile hotspot breakdown for 005930 (legacy, 4 passes)...", flush=True)
    hotspots = _profile_single_ticker_hotspots("005930", score_contract, stage_contract)
    print("[profile]   -> done", flush=True)

    print("[profile] proxy validation loop IO comparison (sample_stride=20)...", flush=True)
    proxy_validation = _profile_proxy_validation(sample_stride=20)
    print("[profile]   -> done", flush=True)

    baseline_profile = {
        "phase": "BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE1_PROFILING",
        "engine": "legacy_uncached",
        "runs_by_subset_size": baseline_runs,
        "top_bottleneck_functions_005930_4passes": hotspots,
        "proxy_validation_cold_vs_warm": proxy_validation,
        "historical_full_universe_runtime_minutes_reference": 330,
        "historical_full_universe_runtime_source": "w.md Section 2 (37da35e closure commit), not re-executed here per Section 12 policy",
    }
    (PERF_DIR / "baseline_profile.json").write_text(json.dumps(baseline_profile, indent=2, ensure_ascii=False), encoding="utf-8")

    optimization_profile = {
        "phase": "BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE1_PROFILING",
        "engine": "optimized_cached",
        "runs_by_subset_size": optimized_runs,
        "speedup_by_subset_size": {
            k: round(baseline_runs[k]["elapsed_seconds"] / optimized_runs[k]["elapsed_seconds"], 3)
            for k in baseline_runs
            if optimized_runs[k]["elapsed_seconds"] > 0
        },
    }
    (PERF_DIR / "optimization_profile.json").write_text(json.dumps(optimization_profile, indent=2, ensure_ascii=False), encoding="utf-8")

    for partial in ("baseline_profile.partial.json", "optimization_profile.partial.json"):
        p = PERF_DIR / partial
        if p.exists():
            p.unlink()

    print(json.dumps({"baseline": baseline_profile["runs_by_subset_size"], "optimized": optimization_profile["runs_by_subset_size"], "speedup": optimization_profile["speedup_by_subset_size"]}, indent=2, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
