#!/usr/bin/env python
"""BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE4_1 -- n=20/50/100 benchmark.

Compares "Phase 4 HEAD (18e4078)" behavior against "Phase 4.1 optimized"
using a CURRENT-tree dual-path toggle (w.md Phase 4.1 Section 15), since
re-running the actual 18e4078 commit against today's data hit an unrelated
proxy-validation schema drift (see r.md's Phase 4 report). Both paths run in
the SAME process on the SAME data:

  - "phase4_head": a PrecomputedTickerContext built once per ticker and
    shared FastSnapshotCache/MonthlySnapshotCache across all 4 Baseline/
    Julia x Primary/Sensitivity passes -- matching what 18e4078 ACTUALLY
    did -- with ONLY enable_pre_window_pruning=False (the one behavior
    that did not exist yet at 18e4078).
  - "phase4_1_optimized": the same context/cache structure, with
    enable_pre_window_pruning=True (default) -- the current d95e96b
    production optimized behavior.

w.md Phase 4.2 Architect Review Major 1 correction: an earlier version of
this benchmark's "phase4_head" path omitted snapshot_context entirely, so
its measured "Phase 4 -> Phase 4.1" speedup incorrectly included the
context-reuse gains Phase 4 itself had already banked. Isolating
enable_pre_window_pruning as the only toggle measures Phase 4.1's actual
incremental contribution.

Measures: wall clock, sec/ticker, FAST evaluation count, weekly/monthly
resample call count (distinguishing full-history vs tail-window calls),
trade count (for a cheap sanity check -- NOT a real strategy-lifecycle
benchmark, since no market_cap_registry is passed here, so investability
always fails DATA_UNAVAILABLE and trade_count is always 0; see
scripts/benchmark_backtest_engine_realistic_v01.py for the realistic,
registry-backed benchmark this cycle also adds).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
import trend_scanner.backtest.snapshot_context as snapshot_context_module
import trend_scanner.data.resampler as resampler_module
import trend_scanner.validation.historical_snapshot as historical_snapshot_module
import trend_scanner.validation.julia_strategy_v00 as julia_strategy_module
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

# `from trend_scanner.data.resampler import to_weekly, to_monthly` in both
# historical_snapshot.py and julia_strategy_v00.py binds a LOCAL reference at
# import time -- patching resampler_module.to_weekly afterward does not
# affect those already-bound names, so the counter must patch all three
# modules' own bindings to see every call site (legacy path included).
_PATCH_TARGETS = (resampler_module, snapshot_context_module, historical_snapshot_module, julia_strategy_module)

SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
PERF_DIR = ROOT / "artifacts/performance/backtest_engine_v01"
STOCKS_DIR = ROOT / "data/raw/stocks"


class _ResampleCounter:
    """Counts calls to to_weekly/to_monthly, split into full-history vs
    tail-window calls by input row count, without altering behavior."""

    def __init__(self, large_threshold: int = 200):
        self.large_threshold = large_threshold
        self.weekly_calls = 0
        self.monthly_calls = 0
        self.weekly_large_calls = 0
        self.monthly_large_calls = 0
        self._real_to_weekly = resampler_module.to_weekly
        self._real_to_monthly = resampler_module.to_monthly

    def __enter__(self):
        def counting_to_weekly(df):
            self.weekly_calls += 1
            if len(df) >= self.large_threshold:
                self.weekly_large_calls += 1
            return self._real_to_weekly(df)

        def counting_to_monthly(df):
            self.monthly_calls += 1
            if len(df) >= self.large_threshold:
                self.monthly_large_calls += 1
            return self._real_to_monthly(df)

        for mod in _PATCH_TARGETS:
            mod.to_weekly = counting_to_weekly
            mod.to_monthly = counting_to_monthly
        return self

    def __exit__(self, *exc):
        for mod in _PATCH_TARGETS:
            mod.to_weekly = self._real_to_weekly
            mod.to_monthly = self._real_to_monthly


def _run_phase4_head(tickers: list[str], score: dict, stage: dict) -> dict:
    """Emulates the ACTUAL 18e4078 (Phase 4 HEAD) runtime path (w.md Phase
    4.2 Major Fix 1 -- Architect Review Major 1 finding). 18e4078 already
    built a PrecomputedTickerContext and passed snapshot_context to every
    Baseline/Julia x Primary/Sensitivity pass, sharing FastSnapshotCache/
    MonthlySnapshotCache across all 4 -- the ONLY Phase-4.1-specific delta
    is enable_pre_window_pruning (introduced in Phase 4.1; False here
    reproduces the exact pre-4.1 full-valid-weeks search range). The
    previous version of this function incorrectly omitted snapshot_context
    entirely, which credited Phase 4.1 with speedup that was actually
    already banked by Phase 4 itself."""
    fast_cache_evals = 0
    monthly_cache_evals = 0
    trade_count = 0
    with _ResampleCounter() as counter:
        t0 = time.perf_counter()
        for ticker in tickers:
            daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()
            context = build_precomputed_ticker_context(ticker, ticker, daily)
            fc = FastSnapshotCache()
            mc = MonthlySnapshotCache()
            for enable_loss_guard in (True, False):
                for sensitivity_mode in (True, False):
                    trades = simulate_ticker_strategy_2022(
                        ticker, ticker, "KOSPI", daily, score, stage,
                        enable_loss_guard=enable_loss_guard, sensitivity_mode=sensitivity_mode,
                        fast_snapshot_cache=fc, monthly_snapshot_cache=mc,
                        snapshot_context=context, enable_pre_window_pruning=False,
                    )
                    trade_count += len(trades)
            fast_cache_evals += fc.evaluation_count
            monthly_cache_evals += mc.evaluation_count
        elapsed = time.perf_counter() - t0

    return {
        "elapsed_seconds": round(elapsed, 3),
        "sec_per_ticker": round(elapsed / len(tickers), 4),
        "fast_evaluation_count": fast_cache_evals,
        "monthly_evaluation_count": monthly_cache_evals,
        "weekly_resample_calls": counter.weekly_calls,
        "monthly_resample_calls": counter.monthly_calls,
        "weekly_resample_large_calls": counter.weekly_large_calls,
        "monthly_resample_large_calls": counter.monthly_large_calls,
        "trade_count": trade_count,
    }


def _run_phase4_1_optimized(tickers: list[str], score: dict, stage: dict) -> dict:
    trade_count = 0
    fast_cache_evals = 0
    monthly_cache_evals = 0
    with _ResampleCounter() as counter:
        t0 = time.perf_counter()
        for ticker in tickers:
            daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()
            context = build_precomputed_ticker_context(ticker, ticker, daily)
            fast_cache = FastSnapshotCache()
            monthly_cache = MonthlySnapshotCache()
            for enable_loss_guard in (True, False):
                for sensitivity_mode in (True, False):
                    trades = simulate_ticker_strategy_2022(
                        ticker, ticker, "KOSPI", daily, score, stage,
                        enable_loss_guard=enable_loss_guard, sensitivity_mode=sensitivity_mode,
                        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
                        snapshot_context=context, enable_pre_window_pruning=True,
                    )
                    trade_count += len(trades)
            fast_cache_evals += fast_cache.evaluation_count
            monthly_cache_evals += monthly_cache.evaluation_count
        elapsed = time.perf_counter() - t0

    return {
        "elapsed_seconds": round(elapsed, 3),
        "sec_per_ticker": round(elapsed / len(tickers), 4),
        "fast_evaluation_count": fast_cache_evals,
        "monthly_evaluation_count": monthly_cache_evals,
        "weekly_resample_calls": counter.weekly_calls,
        "monthly_resample_calls": counter.monthly_calls,
        "weekly_resample_large_calls": counter.weekly_large_calls,
        "monthly_resample_large_calls": counter.monthly_large_calls,
        "trade_count": trade_count,
    }


def main() -> None:
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    all_tickers = sorted(p.stem for p in STOCKS_DIR.glob("*.parquet"))

    results = {}
    for n in (20, 50, 100):
        tickers = all_tickers[:n]
        print(f"=== n={n} ===", flush=True)
        head = _run_phase4_head(tickers, score, stage)
        print(f"phase4_head: {json.dumps(head)}", flush=True)
        optimized = _run_phase4_1_optimized(tickers, score, stage)
        print(f"phase4_1_optimized: {json.dumps(optimized)}", flush=True)
        speedup = round(head["elapsed_seconds"] / optimized["elapsed_seconds"], 2) if optimized["elapsed_seconds"] > 0 else None
        results[f"n={n}"] = {"phase4_head": head, "phase4_1_optimized": optimized, "speedup_x": speedup}
        print(f"speedup_x: {speedup}", flush=True)

    PERF_DIR.mkdir(parents=True, exist_ok=True)
    (PERF_DIR / "phase4_1_benchmark.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2), flush=True)


if __name__ == "__main__":
    main()
