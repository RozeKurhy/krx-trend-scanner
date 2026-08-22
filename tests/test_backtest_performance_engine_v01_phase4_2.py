"""BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE4_2_REALISTIC_BENCHMARK tests.

Covers w.md Phase 4.2 Section 25's required additions: the corrected
Phase4-HEAD benchmark emulation, the realistic (registry-backed) benchmark's
core behavior, sample-trade parity with a real market_cap_registry, and the
Section 13 weekly-reconstruction-duplicate-elimination fix.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.snapshot_context import PrecomputedTickerContext, build_precomputed_ticker_context
from trend_scanner.validation.julia_proxy_market_cap_v01 import ProxyHistoricalMarketCapRegistry
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

STOCKS_DIR = ROOT / "data/raw/stocks"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

SAMPLE_TICKERS = ["005930", "000660", "068270", "035420"]


def _require_fixtures():
    if not (STOCKS_DIR / "005930.parquet").exists() or not SCORE_CONTRACT_PATH.exists():
        pytest.skip("required fixture files not present in this environment")


def _contracts():
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    return score, stage


# =============================================================================
# [1-2] Phase4 HEAD emulation correctness
# =============================================================================

def test_phase4_head_emulation_uses_snapshot_context(monkeypatch):
    """w.md Section 25 item 1: the phase4_head benchmark path must build and
    pass a PrecomputedTickerContext (matching actual 18e4078 behavior),
    not omit it."""
    _require_fixtures()
    import benchmark_phase4_1 as bench

    score, stage = _contracts()
    tickers = ["005930"]

    build_calls = []
    real_build = bench.build_precomputed_ticker_context

    def counting_build(ticker, name, daily):
        build_calls.append(ticker)
        return real_build(ticker, name, daily)

    monkeypatch.setattr(bench, "build_precomputed_ticker_context", counting_build)
    bench._run_phase4_head(tickers, score, stage)

    assert build_calls == ["005930"], "phase4_head must build a PrecomputedTickerContext per ticker"


def test_phase4_head_emulation_disables_only_pruning():
    """w.md Section 25 item 2: phase4_head vs phase4_1 must differ ONLY in
    enable_pre_window_pruning -- both call simulate_ticker_strategy_2022
    with a snapshot_context and shared fast/monthly caches."""
    import benchmark_phase4_1 as bench
    import inspect

    head_src = inspect.getsource(bench._run_phase4_head)
    optimized_src = inspect.getsource(bench._run_phase4_1_optimized)

    assert "snapshot_context=context" in head_src, "phase4_head must pass snapshot_context"
    assert "enable_pre_window_pruning=False" in head_src
    assert "enable_pre_window_pruning=True" in optimized_src


# =============================================================================
# [3-6] Realistic benchmark core behavior
# =============================================================================

def test_realistic_benchmark_passes_real_market_cap_registry():
    """w.md Section 25 item 3."""
    _require_fixtures()
    import benchmark_backtest_engine_realistic_v01 as realistic

    src = __import__("inspect").getsource(realistic._run_realistic_path)
    assert "market_cap_registry=registry" in src
    assert "ProxyHistoricalMarketCapRegistry.load_from_repository" in __import__("inspect").getsource(realistic)


def test_realistic_benchmark_small_sample_has_nonzero_trade_counts():
    """w.md Section 25 items 4-5, Section 8 Sanity Gate: baseline_trade_count
    > 0 and julia_trade_count > 0 on a real sample (proves this is NOT the
    old FAST-scan-only benchmark that always reported trade_count=0)."""
    _require_fixtures()
    import benchmark_backtest_engine_realistic_v01 as realistic

    score, stage = _contracts()
    universe = realistic._load_universe()
    sample = realistic.stratified_sample(universe, 30)

    result = realistic._run_realistic_path(sample, score, stage, enable_pre_window_pruning=True)

    assert result["baseline_trade_count"] > 0, "BENCHMARK_INVALID: baseline_trade_count == 0"
    assert result["julia_trade_count"] > 0, "BENCHMARK_INVALID: julia_trade_count == 0"
    assert result["BENCHMARK_INVALID"] is False


def test_realistic_benchmark_records_market_cap_query_evidence():
    """w.md Section 25 item 6: actual and/or proxy market-cap query counts
    must be nonzero on a representative sample (proves investability/market
    cap lookups actually ran, not skipped due to a missing registry)."""
    _require_fixtures()
    import benchmark_backtest_engine_realistic_v01 as realistic

    score, stage = _contracts()
    universe = realistic._load_universe()
    sample = realistic.stratified_sample(universe, 30)

    result = realistic._run_realistic_path(sample, score, stage, enable_pre_window_pruning=True)

    total_queries = result["market_cap_actual_query_count"] + result["market_cap_proxy_query_count"]
    assert total_queries > 0, "no market-cap queries recorded -- registry not actually used"
    assert sum(result["investability_counts"].values()) > 0, "no investability evaluations recorded"


# =============================================================================
# [7-8] Sample trade parity WITH a real registry (w.md Section 10)
# =============================================================================

@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_pruning_on_off_baseline_parity_with_real_registry(ticker):
    """REALISTIC_SAMPLE_TRADE_PARITY_MISMATCH = 0 target, Baseline."""
    _require_fixtures()
    score, stage = _contracts()
    daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()

    ticker_cache_dir = STOCKS_DIR
    from trend_scanner.backtest.context import TickerDataCache
    tc = TickerDataCache(base_dir=ticker_cache_dir)
    registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=tc)
    context = build_precomputed_ticker_context(ticker, ticker, daily)

    off = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=True, market_cap_registry=registry,
        snapshot_context=context, enable_pre_window_pruning=False,
    )
    on = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=True, market_cap_registry=registry,
        snapshot_context=context, enable_pre_window_pruning=True,
    )
    assert off == on, f"REALISTIC_SAMPLE_TRADE_PARITY_MISMATCH for {ticker} (Baseline, with real registry)"


@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_pruning_on_off_julia_parity_with_real_registry(ticker):
    """REALISTIC_SAMPLE_TRADE_PARITY_MISMATCH = 0 target, Julia."""
    _require_fixtures()
    score, stage = _contracts()
    daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()

    from trend_scanner.backtest.context import TickerDataCache
    tc = TickerDataCache(base_dir=STOCKS_DIR)
    registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=tc)
    context = build_precomputed_ticker_context(ticker, ticker, daily)

    off = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=False, market_cap_registry=registry,
        snapshot_context=context, enable_pre_window_pruning=False,
    )
    on = simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=False, market_cap_registry=registry,
        snapshot_context=context, enable_pre_window_pruning=True,
    )
    assert off == on, f"REALISTIC_SAMPLE_TRADE_PARITY_MISMATCH for {ticker} (Julia, with real registry)"


# =============================================================================
# [9] weekly cutoff reconstruction duplicate eliminated (w.md Section 13)
# =============================================================================

@pytest.mark.parametrize("ticker", SAMPLE_TICKERS)
def test_weekly_up_to_not_called_twice_per_strategy_pass(ticker, monkeypatch):
    _require_fixtures()
    score, stage = _contracts()
    daily = pd.read_parquet(STOCKS_DIR / f"{ticker}.parquet").sort_index()
    context = build_precomputed_ticker_context(ticker, ticker, daily)

    call_count = {"weekly_up_to": 0}
    real_weekly_up_to = PrecomputedTickerContext.weekly_up_to

    def counting_weekly_up_to(self, cutoff_date):
        call_count["weekly_up_to"] += 1
        return real_weekly_up_to(self, cutoff_date)

    monkeypatch.setattr(PrecomputedTickerContext, "weekly_up_to", counting_weekly_up_to)

    simulate_ticker_strategy_2022(
        ticker, ticker, "KOSPI", daily, score, stage,
        enable_loss_guard=True, snapshot_context=context,
    )

    assert call_count["weekly_up_to"] == 1, (
        f"weekly_up_to called {call_count['weekly_up_to']} times in one strategy pass "
        "(expected exactly 1 -- valid_weeks_up_to must reuse the caller's weekly_bars, not recompute it)"
    )


# =============================================================================
# [10-14] 2-worker bounded parallelism (w.md Phase 4.2 Sections 16-23, 25 items 10-14)
# =============================================================================
# Sections 16/23: workers=2 was benchmarked (N=100: 1.881x, N=250: 1.912x,
# both with baseline_parity_pass=julia_parity_pass=True), well above the
# >=1.35x adoption threshold -- see artifacts/performance/backtest_engine_v01/
# phase4_2_parallelism_benchmark.json. These tests re-verify the same
# guarantees on a small sample so the parity/determinism proof is part of
# the regular targeted test suite, not just the one-off benchmark run.

def test_workers1_workers2_baseline_and_julia_parity(monkeypatch):
    """[10-11] workers=1 vs workers=2 trade records must be identical for
    both Baseline and Julia."""
    _require_fixtures()
    sys.path.insert(0, str(ROOT / "scripts"))
    import benchmark_parallelism_v01 as par
    import benchmark_backtest_engine_realistic_v01 as realistic

    universe = realistic._load_universe()
    sample = realistic.stratified_sample(universe, 8)

    w1 = par.run_workers(sample, 1)
    w2 = par.run_workers(sample, 2)

    assert w1["baseline_trades_canonical"] == w2["baseline_trades_canonical"], "workers1/workers2 Baseline parity mismatch"
    assert w1["julia_trades_canonical"] == w2["julia_trades_canonical"], "workers1/workers2 Julia parity mismatch"


def test_workers1_workers2_aggregate_parity():
    """[12] Aggregate trade counts must also match (redundant with [10-11]'s
    exact record match, but this is the cheap sanity check a reviewer would
    check first)."""
    _require_fixtures()
    sys.path.insert(0, str(ROOT / "scripts"))
    import benchmark_parallelism_v01 as par
    import benchmark_backtest_engine_realistic_v01 as realistic

    universe = realistic._load_universe()
    sample = realistic.stratified_sample(universe, 8)

    w1 = par.run_workers(sample, 1)
    w2 = par.run_workers(sample, 2)

    assert w1["baseline_trade_count"] == w2["baseline_trade_count"]
    assert w1["julia_trade_count"] == w2["julia_trade_count"]


def test_parallel_output_deterministic_ordering():
    """[13] The canonical (ticker, trade_sequence) sort must make output
    order independent of worker-completion order -- run workers=2 twice and
    confirm the canonical trade list is byte-identical both times."""
    _require_fixtures()
    sys.path.insert(0, str(ROOT / "scripts"))
    import benchmark_parallelism_v01 as par
    import benchmark_backtest_engine_realistic_v01 as realistic

    universe = realistic._load_universe()
    sample = realistic.stratified_sample(universe, 8)

    run_a = par.run_workers(sample, 2)
    run_b = par.run_workers(sample, 2)

    assert run_a["baseline_trades_canonical"] == run_b["baseline_trades_canonical"]
    assert run_a["julia_trades_canonical"] == run_b["julia_trades_canonical"]


def test_parallel_worker_never_writes_persistent_cache():
    """[14] w.md Section 20: the parallel benchmark path must never touch
    the persistent feature cache file -- simulate_one_ticker_bundle never
    references PersistentFeatureCacheStore at all."""
    import inspect
    sys.path.insert(0, str(ROOT / "scripts"))
    import benchmark_parallelism_v01 as par

    src = inspect.getsource(par)
    assert "PersistentFeatureCacheStore" not in src
    assert "persistent" not in src.lower() or "Persistent cache write is never touched" in src
