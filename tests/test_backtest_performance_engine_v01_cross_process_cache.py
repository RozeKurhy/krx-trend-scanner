"""BACKTEST_PERFORMANCE_ENGINEERING_V01 -- genuine cross-process persistent
feature cache verification (w.md Phase 4 Section 15).

The existing same-process "Sensitivity phase reuses the Primary phase's warm
cache" measurement does NOT prove cross-process reuse works, because the
in-memory FastSnapshotCache/MonthlySnapshotCache objects are still literally
the same Python objects across both phases within one process. This module
spawns two REAL, independent ``python3`` subprocesses:

  - Process A: builds a persistent cache from cold (no existing cache file),
    evaluates a small ticker sample, saves to disk, and exits.
  - Process B: a brand-new interpreter process (no shared memory with A)
    that loads the SAME on-disk cache and must report
    ``persistent_cache_hit: true`` plus a preloaded snapshot count > 0,
    proving the cache genuinely survived a process boundary.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

_WORKER_SCRIPT = r"""
import json
import sys
import time

sys.path.insert(0, {src_dir!r})

import pandas as pd

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.persistent_cache import PersistentFeatureCacheStore
from trend_scanner.backtest.snapshot_context import build_precomputed_ticker_context
from trend_scanner.data.resampler import to_weekly

root = {root!r}
tickers = {tickers!r}
cache_dir = {cache_dir!r}

score = json.loads(open(root + "/artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json").read())
stage = json.loads(open(root + "/artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json").read())

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
preloaded_fast = len(fast_cache)
preloaded_monthly = len(monthly_cache)

t0 = time.perf_counter()
for ticker in tickers:
    daily = pd.read_parquet(root + f"/data/raw/stocks/{{ticker}}.parquet").sort_index()
    weekly_bars = to_weekly(daily)
    daily_dates = set(daily.index)
    valid_weeks = [w for w in weekly_bars.index if w in daily_dates][-10:]
    for w in valid_weeks:
        fast_cache.get(ticker, ticker, daily, w, score, stage)
    month_dates = daily.index.to_period("M").unique()[-3:]
    import pandas as _pd
    for period in month_dates:
        m = _pd.Timestamp(period.to_timestamp(how="end").date())
        monthly_cache.get(ticker, ticker, daily, m)
elapsed = time.perf_counter() - t0

store.save_from(fast_cache, monthly_cache)

print(json.dumps({{
    "persistent_cache_hit": hit,
    "preloaded_fast_snapshot_count": preloaded_fast,
    "preloaded_monthly_snapshot_count": preloaded_monthly,
    "new_fast_evaluation_count": fast_cache.evaluation_count,
    "new_monthly_evaluation_count": monthly_cache.evaluation_count,
    "fast_cache_hit_count": fast_cache.cache_hit_count,
    "monthly_cache_hit_count": monthly_cache.cache_hit_count,
    "elapsed_seconds": round(elapsed, 4),
}}))
"""


def _run_worker(cache_dir: Path, tickers: list[str]) -> dict:
    script = _WORKER_SCRIPT.format(
        src_dir=str(ROOT / "src"),
        root=str(ROOT),
        tickers=tickers,
        cache_dir=str(cache_dir),
    )
    proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, f"worker process failed:\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
    return json.loads(proc.stdout.strip().splitlines()[-1])


def test_persistent_cache_survives_a_real_process_boundary(tmp_path):
    if not (ROOT / "data/raw/stocks/005930.parquet").exists():
        import pytest
        pytest.skip("real stock data not present in this environment")

    cache_dir = tmp_path / "cross_process_cache"
    tickers = ["005930", "000660", "068270", "035420"]

    # Process A: genuinely cold (fresh cache_dir, never seen before).
    result_a = _run_worker(cache_dir, tickers)
    assert result_a["persistent_cache_hit"] is False
    assert result_a["preloaded_fast_snapshot_count"] == 0
    assert result_a["new_fast_evaluation_count"] > 0
    assert result_a["new_monthly_evaluation_count"] > 0

    # Process B: a COMPLETELY SEPARATE python3 interpreter (no shared
    # in-memory state whatsoever with Process A), pointed at the SAME
    # on-disk cache directory Process A just saved to.
    result_b = _run_worker(cache_dir, tickers)
    assert result_b["persistent_cache_hit"] is True, "cache must survive the process boundary"
    assert result_b["preloaded_fast_snapshot_count"] == result_a["new_fast_evaluation_count"]
    assert result_b["preloaded_monthly_snapshot_count"] == result_a["new_monthly_evaluation_count"]
    # Everything Process A computed must come back as cache hits in Process
    # B, with zero new evaluations needed for the same (ticker, date) set.
    assert result_b["new_fast_evaluation_count"] == 0
    assert result_b["new_monthly_evaluation_count"] == 0
    assert result_b["fast_cache_hit_count"] == result_a["new_fast_evaluation_count"]
    assert result_b["monthly_cache_hit_count"] == result_a["new_monthly_evaluation_count"]
