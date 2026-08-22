"""BACKTEST_PERFORMANCE_ENGINEERING_V01_PHASE4_3_PARALLEL_RUNNER_INTEGRATION
tests (w.md Phase 4.3 Section 25's required additions).

Covers: the --workers CLI wiring into scripts/run_backtest_engine_v01_optimized.py,
the parallel_runner.py worker/merge contract, 4-path workers1/workers2 trade
parity, metrics/LG-cohort parity, deterministic canonical ordering, the
persistent-cache never-written-by-workers guarantee, merge_store fail-closed
semantics, workers1/workers2 persistent Fast/Monthly cache content parity, and
a genuine cross-process warm-reuse verification of a parallel-built cache.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.parallel_runner import (
    TickerBundleResult,
    _worker_init,
    run_parallel_universe,
    simulate_ticker_bundle,
)
from trend_scanner.backtest.persistent_cache import PersistentFeatureCacheStore
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.validation.julia_proxy_market_cap_v01 import (
    calculate_strategy_metrics,
    pair_common_entry_trades,
)
from trend_scanner.validation.julia_strategy_v00 import simulate_ticker_strategy_2022

STOCKS_DIR = ROOT / "data/raw/stocks"
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"


def _require_fixtures():
    if not (STOCKS_DIR / "005930.parquet").exists() or not SCORE_CONTRACT_PATH.exists():
        pytest.skip("required fixture files not present in this environment")


def _contracts():
    score = json.loads(SCORE_CONTRACT_PATH.read_text(encoding="utf-8"))
    stage = json.loads(STAGE_CONTRACT_PATH.read_text(encoding="utf-8"))
    return score, stage


def _sample():
    import benchmark_backtest_engine_realistic_v01 as realistic
    universe = realistic._load_universe()
    return realistic.stratified_sample(universe, 10)


def _nan_safe_equal(a, b) -> bool:
    """dict equality where NaN == NaN (plain Python dict equality treats
    float('nan') != float('nan'), which would spuriously fail this parity
    check even when both sides are the identical UNAVAILABLE/NaN state)."""
    import math

    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_nan_safe_equal(a[k], b[k]) for k in a)
    return a == b


def _lg_summary(baseline_trades, julia_trades) -> dict:
    """Mirrors run_optimized_backtest()'s Loss Guard Cohort Accounting block
    exactly, so workers1/workers2 outputs can be compared through it."""
    paired_records, _u_b, _u_j = pair_common_entry_trades(baseline_trades, julia_trades)
    b_lg_trades = [t for t in baseline_trades if t.loss_guard_triggered]
    paired_lookup = {(p["ticker"], p["entry_signal_date"], p["entry_execution_date"]): p for p in paired_records}
    recovered = deeper = progressed = paired_lg = 0
    for t in b_lg_trades:
        key = (t.ticker, t.entry_signal_date, t.entry_execution_date)
        p = paired_lookup.get(key)
        if p is None:
            continue
        paired_lg += 1
        if p["julia_terminal_return"] > p["baseline_terminal_return"]:
            recovered += 1
        if p["julia_terminal_return"] < p["baseline_terminal_return"]:
            deeper += 1
        if p["julia_first_progressed_date"]:
            progressed += 1
    total = len(b_lg_trades)
    return {
        "baseline_loss_guard_total": total,
        "paired_loss_guard_count": paired_lg,
        "unpaired_loss_guard_count": total - paired_lg,
        "julia_recovered_higher_return_count": recovered,
        "julia_deeper_loss_count": deeper,
        "julia_reached_progressed_count": progressed,
    }


# =============================================================================
# [1] --workers CLI parse
# =============================================================================

def test_workers_cli_flag_parses_with_default_1(monkeypatch):
    import run_backtest_engine_v01_optimized as runner

    captured = {}

    def fake_run_optimized_backtest(limit=None, workers=1):
        captured["limit"] = limit
        captured["workers"] = workers
        return {
            "limited": True, "baseline_trades": [], "julia_trades": [],
            "timings": {}, "ticker_data_cache": {}, "fast_snapshot_cache": {},
            "monthly_snapshot_cache": {}, "workers_requested": workers,
            "workers_effective": workers,
        }

    monkeypatch.setattr(runner, "run_optimized_backtest", fake_run_optimized_backtest)
    monkeypatch.setattr(sys, "argv", ["run_backtest_engine_v01_optimized.py", "--limit", "5"])
    runner.main()
    assert captured["workers"] == 1, "default --workers must be 1"

    monkeypatch.setattr(sys, "argv", ["run_backtest_engine_v01_optimized.py", "--limit", "5", "--workers", "2"])
    runner.main()
    assert captured["workers"] == 2


# =============================================================================
# [2] workers=1 legacy path never touches the parallel runner
# =============================================================================

def test_workers1_default_never_calls_parallel_runner(monkeypatch):
    _require_fixtures()
    import run_backtest_engine_v01_optimized as runner

    def _boom(*a, **kw):
        raise AssertionError("run_parallel_universe must not be called when workers<=1")

    monkeypatch.setattr(runner, "run_parallel_universe", _boom)
    result = runner.run_optimized_backtest(limit=5, workers=1)
    assert result["workers_effective"] == 1


# =============================================================================
# [3] worker bundle returns all 4 paths
# =============================================================================

def test_worker_bundle_returns_all_four_paths():
    _require_fixtures()
    score, stage = _contracts()
    _worker_init(str(ROOT), score, stage)
    result = simulate_ticker_bundle(("005930", "005930", "KOSPI"))

    assert isinstance(result, TickerBundleResult)
    assert len(result.baseline_primary_trades) > 0
    assert len(result.baseline_sensitivity_trades) > 0, "Sensitivity results must be returned, not just Primary"
    for key in ("fast_evaluation_count", "fast_cache_hit_count", "monthly_evaluation_count", "monthly_cache_hit_count", "disk_read_count"):
        assert key in result.diagnostics


# =============================================================================
# [4-7] workers=1 vs workers=2 exact parity, all 4 paths
# =============================================================================

@pytest.fixture(scope="module")
def _w1_w2_results():
    _require_fixtures()
    score, stage = _contracts()
    sample = _sample()
    fc1, mc1 = FastSnapshotCache(), MonthlySnapshotCache()
    fc2, mc2 = FastSnapshotCache(), MonthlySnapshotCache()
    w1 = run_parallel_universe(sample, ROOT, score, stage, 1, fc1, mc1)
    w2 = run_parallel_universe(sample, ROOT, score, stage, 2, fc2, mc2)
    return w1, w2, fc1, mc1, fc2, mc2


def test_workers1_workers2_baseline_primary_parity(_w1_w2_results):
    w1, w2, *_ = _w1_w2_results
    assert w1["baseline_primary_trades"] == w2["baseline_primary_trades"]


def test_workers1_workers2_julia_primary_parity(_w1_w2_results):
    w1, w2, *_ = _w1_w2_results
    assert w1["julia_primary_trades"] == w2["julia_primary_trades"]


def test_workers1_workers2_baseline_sensitivity_parity(_w1_w2_results):
    w1, w2, *_ = _w1_w2_results
    assert w1["baseline_sensitivity_trades"] == w2["baseline_sensitivity_trades"]


def test_workers1_workers2_julia_sensitivity_parity(_w1_w2_results):
    w1, w2, *_ = _w1_w2_results
    assert w1["julia_sensitivity_trades"] == w2["julia_sensitivity_trades"]


# =============================================================================
# [8] metrics parity
# =============================================================================

def test_workers1_workers2_metrics_parity(_w1_w2_results):
    w1, w2, *_ = _w1_w2_results
    assert calculate_strategy_metrics(w1["baseline_primary_trades"]) == calculate_strategy_metrics(w2["baseline_primary_trades"])
    assert calculate_strategy_metrics(w1["julia_primary_trades"]) == calculate_strategy_metrics(w2["julia_primary_trades"])


# =============================================================================
# [9] Loss Guard cohort parity
# =============================================================================

def test_workers1_workers2_lg_cohort_parity(_w1_w2_results):
    w1, w2, *_ = _w1_w2_results
    lg1 = _lg_summary(w1["baseline_primary_trades"], w1["julia_primary_trades"])
    lg2 = _lg_summary(w2["baseline_primary_trades"], w2["julia_primary_trades"])
    assert lg1 == lg2


# =============================================================================
# [10] deterministic canonical ordering
# =============================================================================

def test_parallel_output_deterministic_ordering():
    _require_fixtures()
    score, stage = _contracts()
    sample = _sample()
    a = run_parallel_universe(sample, ROOT, score, stage, 2, FastSnapshotCache(), MonthlySnapshotCache())
    b = run_parallel_universe(sample, ROOT, score, stage, 2, FastSnapshotCache(), MonthlySnapshotCache())
    assert a["baseline_primary_trades"] == b["baseline_primary_trades"]
    assert a["julia_sensitivity_trades"] == b["julia_sensitivity_trades"]


# =============================================================================
# [11] worker never writes the persistent cache directly
# =============================================================================

def test_worker_never_writes_persistent_cache_directly():
    """Checks actual usage (import/call), not prose -- the module's own
    docstrings legitimately discuss PersistentFeatureCacheStore/save_from()
    by name to explain why workers must not touch them."""
    import trend_scanner.backtest.parallel_runner as par_mod
    src = inspect.getsource(par_mod)
    assert "import PersistentFeatureCacheStore" not in src
    assert "persistent_cache import" not in src
    assert not hasattr(par_mod, "PersistentFeatureCacheStore")


# =============================================================================
# [12] worker cache export -> main merge
# =============================================================================

def test_fast_and_monthly_cache_merge_from_disjoint_exports():
    fc_main = FastSnapshotCache()
    fc_main.merge_store({("A", 1): {"v": 1}})
    fc_main.merge_store({("B", 1): {"v": 2}})
    assert dict(fc_main.export_store()) == {("A", 1): {"v": 1}, ("B", 1): {"v": 2}}

    mc_main = MonthlySnapshotCache()
    mc_main.merge_store({("A", 1): {"stage": "X"}})
    mc_main.merge_store({("B", 1): {"stage": "Y"}})
    assert dict(mc_main.export_store()) == {("A", 1): {"stage": "X"}, ("B", 1): {"stage": "Y"}}


# =============================================================================
# [13] duplicate-unequal key fails closed; duplicate-equal key is allowed
# =============================================================================

def test_fast_cache_merge_store_fails_closed_on_unequal_duplicate():
    fc = FastSnapshotCache()
    fc.merge_store({("A", 1): {"v": 1}})
    fc.merge_store({("A", 1): {"v": 1}})  # equal duplicate: allowed silently
    with pytest.raises(ValueError):
        fc.merge_store({("A", 1): {"v": 999}})  # unequal duplicate: fail closed


def test_monthly_cache_merge_store_fails_closed_on_unequal_duplicate():
    mc = MonthlySnapshotCache()
    mc.merge_store({("A", 1): {"stage": "X"}})
    mc.merge_store({("A", 1): {"stage": "X"}})
    with pytest.raises(ValueError):
        mc.merge_store({("A", 1): {"stage": "DIFFERENT"}})


# =============================================================================
# [14-15] workers=1 vs workers=2 persistent Fast/Monthly cache content parity
# =============================================================================

def test_legacy_sequential_vs_workers2_four_path_and_cache_parity():
    """Builds the fast/monthly caches AND the 4 trade-record lists via the
    exact two code paths run_backtest_engine_v01_optimized.py itself uses --
    the original sequential shared-context, shared-cache, Primary-loop-then-
    Sensitivity-loop structure for workers<=1, and run_parallel_universe
    (per-ticker fresh caches, all 4 passes together) for workers>1 -- and
    confirms both the exported cache contents AND the 4 canonical trade
    lists are identical (w.md Phase 4.3 Section 15, and closing the
    counts-only gap left by the workers1-vs-workers2-via-run_parallel_universe
    tests above, which never exercised the actual sequential/legacy code
    shape run_optimized_backtest() uses for workers=1)."""
    _require_fixtures()
    score, stage = _contracts()
    sample = _sample()

    # workers=1 style: shared fast/monthly caches + one context per ticker
    # reused across all 4 passes, mirroring run_optimized_backtest()'s
    # sequential Primary+Sensitivity loops (Primary pass first for the whole
    # universe, then Sensitivity pass for the whole universe, matching the
    # real call order in that function).
    import pandas as pd
    from trend_scanner.backtest.context import TickerDataCache
    from trend_scanner.validation.julia_proxy_market_cap_v01 import ProxyHistoricalMarketCapRegistry

    tc = TickerDataCache(base_dir=STOCKS_DIR)
    registry = ProxyHistoricalMarketCapRegistry.load_from_repository(ROOT, cache=tc)

    fc_seq, mc_seq = FastSnapshotCache(), MonthlySnapshotCache()
    contexts = {}
    dailies = {}
    for ticker, name, market in sample:
        p = STOCKS_DIR / f"{ticker}.parquet"
        if not p.exists():
            continue
        daily = pd.read_parquet(p).sort_index()
        dailies[ticker] = daily
        contexts[ticker] = build_precomputed_ticker_context(ticker, name, daily)

    seq_baseline_primary, seq_julia_primary = [], []
    for ticker, name, market in sample:
        if ticker not in dailies:
            continue
        daily, context = dailies[ticker], contexts[ticker]
        seq_baseline_primary.extend(simulate_ticker_strategy_2022(
            ticker, name, market, daily, score, stage,
            enable_loss_guard=True, market_cap_registry=registry,
            fast_snapshot_cache=fc_seq, monthly_snapshot_cache=mc_seq, snapshot_context=context,
        ))
        seq_julia_primary.extend(simulate_ticker_strategy_2022(
            ticker, name, market, daily, score, stage,
            enable_loss_guard=False, market_cap_registry=registry,
            fast_snapshot_cache=fc_seq, monthly_snapshot_cache=mc_seq, snapshot_context=context,
        ))

    seq_baseline_sensitivity, seq_julia_sensitivity = [], []
    for ticker, name, market in sample:
        if ticker not in dailies:
            continue
        daily, context = dailies[ticker], contexts[ticker]
        seq_baseline_sensitivity.extend(simulate_ticker_strategy_2022(
            ticker, name, market, daily, score, stage,
            enable_loss_guard=True, market_cap_registry=registry, sensitivity_mode=True,
            fast_snapshot_cache=fc_seq, monthly_snapshot_cache=mc_seq, snapshot_context=context,
        ))
        seq_julia_sensitivity.extend(simulate_ticker_strategy_2022(
            ticker, name, market, daily, score, stage,
            enable_loss_guard=False, market_cap_registry=registry, sensitivity_mode=True,
            fast_snapshot_cache=fc_seq, monthly_snapshot_cache=mc_seq, snapshot_context=context,
        ))

    fc_par, mc_par = FastSnapshotCache(), MonthlySnapshotCache()
    par = run_parallel_universe(sample, ROOT, score, stage, 2, fc_par, mc_par)

    def _canon(records):
        return sorted(records, key=lambda t: (t.ticker, t.trade_sequence))

    assert _canon(seq_baseline_primary) == par["baseline_primary_trades"], "workers1(legacy sequential)/workers2 Baseline Primary record-level parity mismatch"
    assert _canon(seq_julia_primary) == par["julia_primary_trades"], "workers1(legacy sequential)/workers2 Julia Primary record-level parity mismatch"
    assert _canon(seq_baseline_sensitivity) == par["baseline_sensitivity_trades"], "workers1(legacy sequential)/workers2 Baseline Sensitivity record-level parity mismatch"
    assert _canon(seq_julia_sensitivity) == par["julia_sensitivity_trades"], "workers1(legacy sequential)/workers2 Julia Sensitivity record-level parity mismatch"

    fc_seq_store, fc_par_store = dict(fc_seq.export_store()), dict(fc_par.export_store())
    mc_seq_store, mc_par_store = dict(mc_seq.export_store()), dict(mc_par.export_store())
    assert fc_seq_store.keys() == fc_par_store.keys(), "PERSISTENT_FEATURE_CACHE_PARITY (fast) key mismatch"
    assert all(_nan_safe_equal(fc_seq_store[k], fc_par_store[k]) for k in fc_seq_store), "PERSISTENT_FEATURE_CACHE_PARITY (fast) value mismatch"
    assert mc_seq_store.keys() == mc_par_store.keys(), "PERSISTENT_FEATURE_CACHE_PARITY (monthly) key mismatch"
    assert all(_nan_safe_equal(mc_seq_store[k], mc_par_store[k]) for k in mc_seq_store), "PERSISTENT_FEATURE_CACHE_PARITY (monthly) value mismatch"


# =============================================================================
# [16] cross-process warm verification of a parallel-generated cache
# =============================================================================

_WARM_WORKER_SCRIPT = r"""
import json
import sys
sys.path.insert(0, {src_dir!r})

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.persistent_cache import PersistentFeatureCacheStore

root = {root!r}
cache_dir = {cache_dir!r}

fast_cache = FastSnapshotCache()
monthly_cache = MonthlySnapshotCache()

store = PersistentFeatureCacheStore(
    score_contract_path=root + "/artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json",
    stage_contract_path=root + "/artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json",
    source_data_dir=root + "/data/raw/stocks",
    cache_dir=cache_dir,
)
from pathlib import Path as _P
store.score_contract_path = _P(store.score_contract_path)
store.stage_contract_path = _P(store.stage_contract_path)
store.source_data_dir = _P(store.source_data_dir)
store.cache_dir = _P(store.cache_dir)

hit = store.load_into(fast_cache, monthly_cache)
print(json.dumps({{
    "persistent_cache_hit": hit,
    "preloaded_fast_snapshot_count": len(fast_cache),
    "preloaded_monthly_snapshot_count": len(monthly_cache),
}}))
"""


def test_parallel_generated_persistent_cache_is_warm_hit_in_new_process(tmp_path):
    _require_fixtures()
    score, stage = _contracts()
    sample = _sample()
    cache_dir = tmp_path / "phase4_3_parallel_cache"

    fc, mc = FastSnapshotCache(), MonthlySnapshotCache()
    run_parallel_universe(sample, ROOT, score, stage, 2, fc, mc)

    store = PersistentFeatureCacheStore(
        score_contract_path=SCORE_CONTRACT_PATH,
        stage_contract_path=STAGE_CONTRACT_PATH,
        source_data_dir=STOCKS_DIR,
        cache_dir=cache_dir,
    )
    store.save_from(fc, mc)

    script = _WARM_WORKER_SCRIPT.format(src_dir=str(ROOT / "src"), root=str(ROOT), cache_dir=str(cache_dir))
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"worker process failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    result = json.loads(proc.stdout.strip().splitlines()[-1])

    assert result["persistent_cache_hit"] is True, "a workers=2-built persistent cache must warm-HIT in a brand new process"
    assert result["preloaded_fast_snapshot_count"] == len(fc)
    assert result["preloaded_monthly_snapshot_count"] == len(mc)
