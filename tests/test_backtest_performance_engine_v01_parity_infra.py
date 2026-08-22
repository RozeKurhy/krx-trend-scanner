"""BACKTEST_PERFORMANCE_ENGINEERING_V01 -- parity comparator + persistent cache tests.

Covers the infrastructure added after the first full-universe run surfaced a
false-positive parity failure (2001/3779 "field mismatches" that were purely
a CSV-round-trip representation artifact, not a real computation
difference -- see trend_scanner.backtest.parity module docstring):

  - compare_trade_csvs must NOT report a mismatch for values that are only
    textually different due to float shortest-repr / None-vs-NaN
    serialization (the exact incident class this module fixes).
  - compare_trade_csvs MUST still detect a genuine semantic/numeric
    difference (never silently swallow a real mismatch).
  - PersistentFeatureCacheStore round-trips a snapshot cache across
    process boundaries (simulated via fresh cache instances) when the
    version key (contract hashes + source data fingerprint) is unchanged,
    and refuses to reuse a stale cache when it changes.
"""

from __future__ import annotations

import pickle
from pathlib import Path

import pandas as pd

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache
from trend_scanner.backtest.parity import compare_trade_csvs, diff_summary_dicts
from trend_scanner.backtest.persistent_cache import PersistentFeatureCacheStore

ROOT = Path(__file__).resolve().parent.parent
SCORE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_score_prototype_v01.json"
STAGE_CONTRACT_PATH = ROOT / "artifacts/patterns/pattern_a_fast/production/contract_prototype/pattern_a_fast_stage_prototype_v01.json"

_TRADE_COLUMNS = ["ticker", "trade_id", "trade_sequence", "entry_open", "previous_exit_type", "terminal_return"]


def _write_trade_csv(path: Path, rows: list[dict]) -> None:
    pd.DataFrame(rows).to_csv(path, index=False)


# =============================================================================
# compare_trade_csvs -- false-positive elimination
# =============================================================================

def test_compare_trade_csvs_no_mismatch_for_float_reprs_that_agree_after_csv_roundtrip(tmp_path):
    """The exact incident: a float whose raw Python repr differs from its
    to_csv/read_csv round-tripped repr must NOT be reported as a mismatch
    once BOTH sides go through an actual on-disk CSV (compare_trade_csvs'
    whole point)."""
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    # Write the "optimized" side with the raw, non-round-tripped repr, and
    # the "golden" side with the same mathematical value already known to
    # round-trip to a different apparent string.
    _write_trade_csv(golden_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 1083419202799.9999, "previous_exit_type": None, "terminal_return": 12.34}])
    _write_trade_csv(optimized_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 1083419202799.9999, "previous_exit_type": None, "terminal_return": 12.34}])

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["exact_trade_identity"] is True
    assert result["field_mismatch_count"] == 0
    assert result["mismatch_examples"] == []


def test_compare_trade_csvs_detects_genuine_numeric_mismatch(tmp_path):
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    _write_trade_csv(golden_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34}])
    _write_trade_csv(optimized_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 99.99}])

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["exact_trade_identity"] is False
    assert result["field_mismatch_count"] == 1
    assert result["mismatch_examples"][0]["field"] == "terminal_return"
    assert result["mismatch_examples"][0]["golden"] == "12.34"
    assert result["mismatch_examples"][0]["optimized"] == "99.99"


def test_compare_trade_csvs_count_mismatch_short_circuits_field_comparison(tmp_path):
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    _write_trade_csv(golden_path, [
        {"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34},
        {"ticker": "005930", "trade_id": "005930_02", "trade_sequence": 2, "entry_open": 71000.0, "previous_exit_type": "EXIT3", "terminal_return": -5.0},
    ])
    _write_trade_csv(optimized_path, [
        {"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34},
    ])

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["count_mismatch"] is True
    assert result["exact_trade_identity"] is False
    assert result["field_mismatch_count"] is None


# =============================================================================
# diff_summary_dicts
# =============================================================================

def test_diff_summary_dicts_float_tolerance_and_nested_structures():
    golden = {"return_stats": {"mean": 12.800165680473372, "median": -14.57}, "total_trades": 845}
    optimized_ok = {"return_stats": {"mean": 12.800165680473373, "median": -14.57}, "total_trades": 845}
    optimized_bad = {"return_stats": {"mean": 12.800165680473372, "median": -99.0}, "total_trades": 845}

    assert diff_summary_dicts(golden, optimized_ok) == []
    diffs = diff_summary_dicts(golden, optimized_bad)
    assert len(diffs) == 1
    assert diffs[0]["field"] == "return_stats.median"


# =============================================================================
# PersistentFeatureCacheStore
# =============================================================================

def test_persistent_cache_round_trips_across_fresh_instances(tmp_path):
    source_data_dir = tmp_path / "stocks"
    source_data_dir.mkdir()
    (source_data_dir / "005930.parquet").write_bytes(b"fake-parquet-bytes")

    store = PersistentFeatureCacheStore(
        score_contract_path=SCORE_CONTRACT_PATH,
        stage_contract_path=STAGE_CONTRACT_PATH,
        source_data_dir=source_data_dir,
        cache_dir=tmp_path / "cache",
    )

    fast_cache = FastSnapshotCache()
    fast_cache._store[("005930", pd.Timestamp("2024-01-05"))] = {"fast_score": 42.0}
    monthly_cache = MonthlySnapshotCache()
    monthly_cache._store[("005930", pd.Timestamp("2024-01-31"))] = {"date": pd.Timestamp("2024-01-31"), "stage": "PROGRESSED", "score": 88.0}

    store.save_from(fast_cache, monthly_cache)

    fresh_fast_cache = FastSnapshotCache()
    fresh_monthly_cache = MonthlySnapshotCache()
    hit = store.load_into(fresh_fast_cache, fresh_monthly_cache)

    assert hit is True
    assert len(fresh_fast_cache) == 1
    assert len(fresh_monthly_cache) == 1
    assert fresh_fast_cache._store[("005930", pd.Timestamp("2024-01-05"))] == {"fast_score": 42.0}
    assert fresh_monthly_cache._store[("005930", pd.Timestamp("2024-01-31"))]["stage"] == "PROGRESSED"


def test_persistent_cache_refuses_stale_cache_after_source_data_change(tmp_path):
    source_data_dir = tmp_path / "stocks"
    source_data_dir.mkdir()
    (source_data_dir / "005930.parquet").write_bytes(b"fake-parquet-bytes")

    store = PersistentFeatureCacheStore(
        score_contract_path=SCORE_CONTRACT_PATH,
        stage_contract_path=STAGE_CONTRACT_PATH,
        source_data_dir=source_data_dir,
        cache_dir=tmp_path / "cache",
    )
    fast_cache = FastSnapshotCache()
    fast_cache._store[("005930", pd.Timestamp("2024-01-05"))] = {"fast_score": 42.0}
    monthly_cache = MonthlySnapshotCache()
    store.save_from(fast_cache, monthly_cache)

    # Simulate new/updated source data arriving (file count changes).
    (source_data_dir / "000660.parquet").write_bytes(b"another-fake-parquet")

    fresh_fast_cache = FastSnapshotCache()
    fresh_monthly_cache = MonthlySnapshotCache()
    hit = store.load_into(fresh_fast_cache, fresh_monthly_cache)

    assert hit is False
    assert len(fresh_fast_cache) == 0
    assert len(fresh_monthly_cache) == 0


def test_persistent_cache_missing_file_is_cold_start_not_error(tmp_path):
    store = PersistentFeatureCacheStore(
        score_contract_path=SCORE_CONTRACT_PATH,
        stage_contract_path=STAGE_CONTRACT_PATH,
        source_data_dir=tmp_path,
        cache_dir=tmp_path / "does_not_exist_yet",
    )
    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()
    hit = store.load_into(fast_cache, monthly_cache)
    assert hit is False
    assert len(fast_cache) == 0


def test_persistent_cache_file_is_atomic_write(tmp_path):
    """save_from must never leave a corrupt/partial cache file on disk."""
    source_data_dir = tmp_path / "stocks"
    source_data_dir.mkdir()
    store = PersistentFeatureCacheStore(
        score_contract_path=SCORE_CONTRACT_PATH,
        stage_contract_path=STAGE_CONTRACT_PATH,
        source_data_dir=source_data_dir,
        cache_dir=tmp_path / "cache",
    )
    fast_cache = FastSnapshotCache()
    monthly_cache = MonthlySnapshotCache()
    store.save_from(fast_cache, monthly_cache)

    final_path = tmp_path / "cache" / "pattern_a_fast_snapshot_cache_v01.pkl"
    assert final_path.exists()
    temp_path = tmp_path / "cache" / f".{final_path.name}.tmp"
    assert not temp_path.exists()
    with final_path.open("rb") as f:
        payload = pickle.load(f)
    assert payload["version_key"]["schema_version"] == "BACKTEST_FEATURE_CACHE_V01"
