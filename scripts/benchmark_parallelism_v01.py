#!/usr/bin/env python
"""BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE4_2 -- 2-worker bounded parallelism benchmark.

w.md Phase 4.2 Section 16 CASE C (realistic projected Cold Full > 50 min):
2-worker bounded parallelism benchmark is recommended. This script compares
workers=1 vs workers=2 on the SAME realistic N=100 stratified sample used by
scripts/benchmark_backtest_engine_realistic_v01.py.

Worker unit is a whole ticker (w.md Section 19): one worker builds the
PrecomputedTickerContext and runs the full Baseline/Julia x Primary/
Sensitivity 4-pass for that ticker, so daily data/context/feature caches are
reused within the worker instead of crossing a process boundary per pass.

Persistent cache write is never touched here (w.md Section 20) -- this
benchmark only measures Cold compute wall-clock. Each worker process builds
its own ProxyHistoricalMarketCapRegistry once at process start (via
ProcessPoolExecutor's initializer), not per ticker, and results are merged
back in the main process with a canonical (ticker, trade_sequence) sort so
workers=1 vs workers=2 output is order-independent and directly comparable
(w.md Section 21).
"""

from __future__ import annotations

import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.backtest.context import TickerDataCache
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.validation.julia_proxy_market_cap_v01 import ProxyHistoricalMarketCapRegistry
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"
STOCKS_DIR = ROOT / "data/raw/stocks"
PERF_DIR = ROOT / "artifacts/performance/backtest_engine_v01"

# Populated once per worker PROCESS by _worker_init (w.md Section 22: never
# replicate a huge shared cache into every worker; each worker builds its
# own lightweight registry/cache exactly once, not once per ticker task).
_WORKER_STATE: dict = {}


def _worker_init(score_json: str, stage_json: str) -> None:
    ticker_cache = TickerDataCache(base_dir=STOCKS_DIR)
    registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=ticker_cache)
    _WORKER_STATE["ticker_cache"] = ticker_cache
    _WORKER_STATE["registry"] = registry
    _WORKER_STATE["score"] = json.loads(score_json)
    _WORKER_STATE["stage"] = json.loads(stage_json)


def simulate_one_ticker_bundle(args: tuple[str, str, str, bool]) -> dict:
    """w.md Section 19: one worker task = one ticker's full 4-pass bundle."""
    ticker, name, market, enable_pre_window_pruning = args
    ticker_cache = _WORKER_STATE["ticker_cache"]
    registry = _WORKER_STATE["registry"]
    score = _WORKER_STATE["score"]
    stage = _WORKER_STATE["stage"]

    daily = ticker_cache.load(ticker)
    if daily is None or daily.empty:
        return {"ticker": ticker, "baseline_trades": [], "julia_trades": []}

    context = build_precomputed_ticker_context(ticker, name, daily)
    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()

    baseline_trades = simulate_ticker_strategy_2022(
        ticker, name, market, daily, score, stage,
        enable_loss_guard=True, market_cap_registry=registry,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
        snapshot_context=context, enable_pre_window_pruning=enable_pre_window_pruning,
    )
    julia_trades = simulate_ticker_strategy_2022(
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

    return {
        "ticker": ticker,
        "baseline_trades": [(t.ticker, t.trade_sequence, t.entry_execution_date, t.exit_type, t.terminal_return) for t in baseline_trades],
        "julia_trades": [(t.ticker, t.trade_sequence, t.entry_execution_date, t.exit_type, t.terminal_return) for t in julia_trades],
    }


def _canonical_sorted(records: list[dict], key: str) -> list[tuple]:
    flat = [row for r in records for row in r[key]]
    return sorted(flat, key=lambda row: (row[0], row[1]))


def run_workers(sample: list[tuple[str, str, str]], workers: int, *, enable_pre_window_pruning: bool = True) -> dict:
    score_json = SCORE_CONTRACT_PATH.read_text(encoding="utf-8")
    stage_json = STAGE_CONTRACT_PATH.read_text(encoding="utf-8")
    tasks = [(t, n, m, enable_pre_window_pruning) for t, n, m in sample]

    t0 = time.perf_counter()
    if workers <= 1:
        _worker_init(score_json, stage_json)
        results = [simulate_one_ticker_bundle(task) for task in tasks]
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init, initargs=(score_json, stage_json)) as executor:
            results = list(executor.map(simulate_one_ticker_bundle, tasks))
    elapsed = time.perf_counter() - t0

    baseline_sorted = _canonical_sorted(results, "baseline_trades")
    julia_sorted = _canonical_sorted(results, "julia_trades")

    return {
        "workers": workers,
        "n_tickers": len(sample),
        "elapsed_seconds": round(elapsed, 3),
        "sec_per_ticker": round(elapsed / len(sample), 4) if sample else None,
        "baseline_trade_count": len(baseline_sorted),
        "julia_trade_count": len(julia_sorted),
        "baseline_trades_canonical": baseline_sorted,
        "julia_trades_canonical": julia_sorted,
    }


def main() -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    import benchmark_backtest_engine_realistic_v01 as realistic

    universe = realistic._load_universe()
    sample = realistic.stratified_sample(universe, 100)

    print(f"=== workers=1 vs workers=2, N={len(sample)} ===", flush=True)
    w1 = run_workers(sample, 1)
    print(f"workers=1: elapsed={w1['elapsed_seconds']}s baseline={w1['baseline_trade_count']} julia={w1['julia_trade_count']}", flush=True)
    w2 = run_workers(sample, 2)
    print(f"workers=2: elapsed={w2['elapsed_seconds']}s baseline={w2['baseline_trade_count']} julia={w2['julia_trade_count']}", flush=True)

    speedup = round(w1["elapsed_seconds"] / w2["elapsed_seconds"], 3) if w2["elapsed_seconds"] > 0 else None
    parity_baseline = w1["baseline_trades_canonical"] == w2["baseline_trades_canonical"]
    parity_julia = w1["julia_trades_canonical"] == w2["julia_trades_canonical"]

    result = {
        "n_tickers": len(sample),
        "workers1": {k: v for k, v in w1.items() if not k.endswith("_canonical")},
        "workers2": {k: v for k, v in w2.items() if not k.endswith("_canonical")},
        "speedup_x": speedup,
        "baseline_parity_pass": parity_baseline,
        "julia_parity_pass": parity_julia,
        "adopt_recommended": bool(speedup and speedup >= 1.35 and parity_baseline and parity_julia),
    }
    print(json.dumps(result, indent=2), flush=True)

    PERF_DIR.mkdir(parents=True, exist_ok=True)
    (PERF_DIR / "phase4_2_parallelism_benchmark.json").write_text(json.dumps(result, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
