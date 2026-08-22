"""2-worker bounded ticker-bundle parallel runner
(BACKTEST_PERFORMANCE_ENGINEERING_V01 Phase 4.3).

w.md Phase 4.3's central integration piece: a worker task is ONE ticker,
which runs all 4 strategy passes (Baseline/Julia x Primary/Sensitivity) for
that ticker so its ``daily``/``PrecomputedTickerContext``/
``FastSnapshotCache``/``MonthlySnapshotCache`` are shared across the 4
passes inside the worker, never split across a process boundary. Baseline
and Julia are never split into separate workers.

No strategy semantics live here -- ``simulate_ticker_strategy_2022`` is
called exactly as ``scripts/run_backtest_engine_v01_optimized.py`` already
calls it; this module only adds the process-parallel orchestration and the
worker-result merge back into the main process.

Persistent cache safety (w.md Section 7-8): workers NEVER call
``PersistentFeatureCacheStore.save_from()`` themselves -- each worker only
returns its own ticker-local ``export_store()`` snapshots, and the caller
(main process) merges them into its own ``FastSnapshotCache``/
``MonthlySnapshotCache`` via ``merge_store()`` (fail-closed on a duplicate
key with an unequal value) before doing the single atomic
``save_from()`` call itself.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from trend_scanner.backtest.context import TickerDataCache
from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.validation.julia_proxy_market_cap_v01 import ProxyHistoricalMarketCapRegistry
from trend_scanner.validation.julia_strategy_v00 import StrategyTradeRecord, simulate_ticker_strategy_2022

# Populated once per worker PROCESS by _worker_init (w.md Section 6: never
# reload the registry per ticker task -- only once per worker process).
_WORKER_STATE: dict[str, Any] = {}


@dataclass
class TickerBundleResult:
    """Worker Result Contract (w.md Phase 4.3 Section 4). Full
    ``StrategyTradeRecord`` objects are returned (not a reduced tuple
    subset) so ``calculate_strategy_metrics``/``pair_common_entry_trades``/
    ``persist_optimized_artifacts`` can consume them completely unchanged
    in the main process."""

    ticker: str
    baseline_primary_trades: list[StrategyTradeRecord] = field(default_factory=list)
    julia_primary_trades: list[StrategyTradeRecord] = field(default_factory=list)
    baseline_sensitivity_trades: list[StrategyTradeRecord] = field(default_factory=list)
    julia_sensitivity_trades: list[StrategyTradeRecord] = field(default_factory=list)
    fast_cache_export: dict = field(default_factory=dict)
    monthly_cache_export: dict = field(default_factory=dict)
    diagnostics: dict[str, int] = field(default_factory=dict)


def _worker_init(root: str, score_contract: dict, stage_contract: dict) -> None:
    """ProcessPoolExecutor initializer (w.md Section 6): builds
    TickerDataCache/ProxyHistoricalMarketCapRegistry/contracts exactly once
    per worker process, not once per ticker task. Also used directly (not
    via a pool) for the workers<=1 sequential path so that path exercises
    the identical worker code, differing only in concurrency."""
    root_path = Path(root)
    ticker_cache = TickerDataCache(base_dir=root_path / "data/raw/stocks")
    registry = ProxyHistoricalMarketCapRegistry.load_from_repository(root_path, cache=ticker_cache)
    _WORKER_STATE["ticker_cache"] = ticker_cache
    _WORKER_STATE["registry"] = registry
    _WORKER_STATE["score_contract"] = score_contract
    _WORKER_STATE["stage_contract"] = stage_contract


def simulate_ticker_bundle(args: tuple[str, str, str]) -> TickerBundleResult:
    """Worker task unit (w.md Section 3): one ticker, all 4 strategy passes,
    sharing daily/context/feature-caches within this call. Baseline and
    Julia are never split into separate workers."""
    ticker, name, market = args
    ticker_cache: TickerDataCache = _WORKER_STATE["ticker_cache"]
    registry = _WORKER_STATE["registry"]
    score_contract = _WORKER_STATE["score_contract"]
    stage_contract = _WORKER_STATE["stage_contract"]

    daily = ticker_cache.load(ticker)
    if daily is None or daily.empty:
        return TickerBundleResult(
            ticker=ticker,
            diagnostics={
                "fast_evaluation_count": 0, "fast_cache_hit_count": 0,
                "monthly_evaluation_count": 0, "monthly_cache_hit_count": 0,
                "disk_read_count": 0,
            },
        )

    context = build_precomputed_ticker_context(ticker, name, daily)
    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()

    baseline_primary = simulate_ticker_strategy_2022(
        ticker, name, market, daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=registry,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
        snapshot_context=context,
    )
    julia_primary = simulate_ticker_strategy_2022(
        ticker, name, market, daily, score_contract, stage_contract,
        enable_loss_guard=False, market_cap_registry=registry,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
        snapshot_context=context,
    )
    baseline_sensitivity = simulate_ticker_strategy_2022(
        ticker, name, market, daily, score_contract, stage_contract,
        enable_loss_guard=True, market_cap_registry=registry, sensitivity_mode=True,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
        snapshot_context=context,
    )
    julia_sensitivity = simulate_ticker_strategy_2022(
        ticker, name, market, daily, score_contract, stage_contract,
        enable_loss_guard=False, market_cap_registry=registry, sensitivity_mode=True,
        fast_snapshot_cache=fast_cache, monthly_snapshot_cache=monthly_cache,
        snapshot_context=context,
    )

    return TickerBundleResult(
        ticker=ticker,
        baseline_primary_trades=baseline_primary,
        julia_primary_trades=julia_primary,
        baseline_sensitivity_trades=baseline_sensitivity,
        julia_sensitivity_trades=julia_sensitivity,
        fast_cache_export=fast_cache.export_store(),
        monthly_cache_export=monthly_cache.export_store(),
        diagnostics={
            "fast_evaluation_count": fast_cache.evaluation_count,
            "fast_cache_hit_count": fast_cache.cache_hit_count,
            "monthly_evaluation_count": monthly_cache.evaluation_count,
            "monthly_cache_hit_count": monthly_cache.cache_hit_count,
            "disk_read_count": 1,
        },
    )


def _canonical_sort(records: list[StrategyTradeRecord]) -> list[StrategyTradeRecord]:
    """w.md Section 12: canonical (ticker, trade_sequence) sort so output
    order never depends on worker-completion order."""
    return sorted(records, key=lambda t: (t.ticker, t.trade_sequence))


def run_parallel_universe(
    universe: list[tuple[str, str, str]],
    root: Path,
    score_contract: dict,
    stage_contract: dict,
    workers: int,
    fast_cache: FastSnapshotCache,
    monthly_cache: MonthlySnapshotCache,
) -> dict[str, Any]:
    """Runs the full 4-path strategy simulation for every (ticker, name,
    market) in ``universe`` via ``simulate_ticker_bundle`` -- sequentially
    when ``workers <= 1`` (still going through the exact same worker
    function, just without a process pool, so a workers=1 vs workers=2
    comparison differs ONLY in concurrency, not in code path), or via a
    ``ProcessPoolExecutor`` when ``workers > 1``.

    Each ticker's exported fast/monthly cache snapshot is merged into the
    CALLER-owned ``fast_cache``/``monthly_cache`` (fail-closed on a
    duplicate key with an unequal value, w.md Section 8) -- this function
    never calls ``PersistentFeatureCacheStore.save_from()`` itself; that
    remains the caller's single, main-process-only responsibility.

    Note: this is a COLD-BUILD-ONLY path (w.md Section 9-10) -- callers
    should not invoke this when reusing an already-warm persistent cache
    (fall back to the existing single-process workers=1 path instead, see
    scripts/run_backtest_engine_v01_optimized.py).
    """
    baseline_primary_trades: list[StrategyTradeRecord] = []
    julia_primary_trades: list[StrategyTradeRecord] = []
    baseline_sensitivity_trades: list[StrategyTradeRecord] = []
    julia_sensitivity_trades: list[StrategyTradeRecord] = []
    disk_read_count = 0
    fast_evaluation_count = 0
    fast_cache_hit_count = 0
    monthly_evaluation_count = 0
    monthly_cache_hit_count = 0

    def _absorb(result: TickerBundleResult) -> None:
        nonlocal disk_read_count, fast_evaluation_count, fast_cache_hit_count
        nonlocal monthly_evaluation_count, monthly_cache_hit_count
        baseline_primary_trades.extend(result.baseline_primary_trades)
        julia_primary_trades.extend(result.julia_primary_trades)
        baseline_sensitivity_trades.extend(result.baseline_sensitivity_trades)
        julia_sensitivity_trades.extend(result.julia_sensitivity_trades)
        fast_cache.merge_store(result.fast_cache_export)
        monthly_cache.merge_store(result.monthly_cache_export)
        disk_read_count += result.diagnostics.get("disk_read_count", 0)
        fast_evaluation_count += result.diagnostics.get("fast_evaluation_count", 0)
        fast_cache_hit_count += result.diagnostics.get("fast_cache_hit_count", 0)
        monthly_evaluation_count += result.diagnostics.get("monthly_evaluation_count", 0)
        monthly_cache_hit_count += result.diagnostics.get("monthly_cache_hit_count", 0)

    if workers <= 1:
        _worker_init(str(root), score_contract, stage_contract)
        for task in universe:
            _absorb(simulate_ticker_bundle(task))
    else:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_worker_init,
            initargs=(str(root), score_contract, stage_contract),
        ) as executor:
            for result in executor.map(simulate_ticker_bundle, universe):
                _absorb(result)

    return {
        "baseline_primary_trades": _canonical_sort(baseline_primary_trades),
        "julia_primary_trades": _canonical_sort(julia_primary_trades),
        "baseline_sensitivity_trades": _canonical_sort(baseline_sensitivity_trades),
        "julia_sensitivity_trades": _canonical_sort(julia_sensitivity_trades),
        "disk_read_count": disk_read_count,
        "fast_evaluation_count": fast_evaluation_count,
        "fast_cache_hit_count": fast_cache_hit_count,
        "monthly_evaluation_count": monthly_evaluation_count,
        "monthly_cache_hit_count": monthly_cache_hit_count,
    }
