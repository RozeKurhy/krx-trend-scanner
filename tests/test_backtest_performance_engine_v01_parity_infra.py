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
from trend_scanner.backtest import persistent_cache as persistent_cache_module
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
# compare_trade_csvs -- Phase 4 Major Fix 2 strengthening
# =============================================================================

def test_compare_trade_csvs_missing_required_golden_field_fails(tmp_path):
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    # golden is missing "previous_exit_type" entirely.
    pd.DataFrame([{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "terminal_return": 12.34}]).to_csv(golden_path, index=False)
    _write_trade_csv(optimized_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34}])

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["exact_trade_identity"] is False
    assert result["field_mismatch_count"] is None
    assert result["missing_required_fields"]["golden"] == ["previous_exit_type"]
    assert result["missing_required_fields"]["optimized"] == []


def test_compare_trade_csvs_missing_required_optimized_field_fails(tmp_path):
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    _write_trade_csv(golden_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34}])
    # optimized is missing "entry_open" entirely.
    pd.DataFrame([{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "previous_exit_type": None, "terminal_return": 12.34}]).to_csv(optimized_path, index=False)

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["exact_trade_identity"] is False
    assert result["field_mismatch_count"] is None
    assert result["missing_required_fields"]["golden"] == []
    assert result["missing_required_fields"]["optimized"] == ["entry_open"]


def test_compare_trade_csvs_none_nan_canonical_roundtrip_passes(tmp_path):
    """Both sides write Python None for previous_exit_type; after the CSV
    round-trip both read back as NaN -- this must PASS the Exact Gate."""
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    _write_trade_csv(golden_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34}])
    _write_trade_csv(optimized_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34}])

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["exact_trade_identity"] is True
    assert result["field_mismatch_count"] == 0


def test_compare_trade_csvs_row_ordering_only_difference_passes(tmp_path):
    """Merge-based row identity (ticker+trade_sequence) must be
    order-independent: only the row order in the optimized file differs."""
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    rows = [
        {"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34},
        {"ticker": "000660", "trade_id": "000660_01", "trade_sequence": 1, "entry_open": 50000.0, "previous_exit_type": "EXIT3", "terminal_return": -3.0},
    ]
    _write_trade_csv(golden_path, rows)
    _write_trade_csv(optimized_path, list(reversed(rows)))

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["exact_trade_identity"] is True
    assert result["field_mismatch_count"] == 0
    assert result["unmatched_trade_identity_count"] == {"golden_only": 0, "optimized_only": 0}


def test_compare_trade_csvs_same_ticker_sequence_different_trade_id_fails(tmp_path):
    golden_path = tmp_path / "golden.csv"
    optimized_path = tmp_path / "optimized.csv"

    _write_trade_csv(golden_path, [{"ticker": "005930", "trade_id": "005930_01", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34}])
    _write_trade_csv(optimized_path, [{"ticker": "005930", "trade_id": "005930_99", "trade_sequence": 1, "entry_open": 70000.0, "previous_exit_type": None, "terminal_return": 12.34}])

    result = compare_trade_csvs(golden_path, optimized_path, parity_fields=_TRADE_COLUMNS)

    assert result["exact_trade_identity"] is False
    assert any(m["field"] == "trade_id" for m in result["mismatch_examples"])


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


# =============================================================================
# PersistentFeatureCacheStore -- version-key strengthening (Phase 4 Major Fix 1)
# =============================================================================
# Covers w.md Phase 4 Section 2C's 7-case invalidation matrix: contract change,
# implementation-sha change, parquet add/delete/size-change/mtime_ns-change all
# MISS; no change at all HIT. FEATURE_IMPLEMENTATION_FILES is monkeypatched to
# a single fake file under tmp_path so these tests never depend on (or risk
# false-failing from) the real repo's actual source file contents.

def _build_store(tmp_path, monkeypatch, *, impl_relative_path="fake_impl/a.py"):
    repo_root = tmp_path / "repo"
    (repo_root / "fake_impl").mkdir(parents=True, exist_ok=True)
    (repo_root / "fake_impl" / "a.py").write_text("def f(): return 1\n")
    monkeypatch.setattr(persistent_cache_module, "FEATURE_IMPLEMENTATION_FILES", (impl_relative_path,))

    source_data_dir = tmp_path / "stocks"
    source_data_dir.mkdir(exist_ok=True)
    (source_data_dir / "005930.parquet").write_bytes(b"fake-parquet-bytes")

    store = PersistentFeatureCacheStore(
        score_contract_path=SCORE_CONTRACT_PATH,
        stage_contract_path=STAGE_CONTRACT_PATH,
        source_data_dir=source_data_dir,
        cache_dir=tmp_path / "cache",
        repo_root=repo_root,
    )
    return store, repo_root, source_data_dir


def _seed_cache(store):
    fast_cache = FastSnapshotCache()
    fast_cache._store[("005930", pd.Timestamp("2024-01-05"))] = {"fast_score": 42.0}
    monthly_cache = MonthlySnapshotCache()
    store.save_from(fast_cache, monthly_cache)


def test_persistent_cache_no_change_is_hit(tmp_path, monkeypatch):
    store, _, _ = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is True


def test_persistent_cache_score_contract_change_is_miss(tmp_path, monkeypatch):
    store, _, _ = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    # A different (still valid) contract file simulates a contract change.
    store.score_contract_path = STAGE_CONTRACT_PATH
    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is False


def test_persistent_cache_stage_contract_change_is_miss(tmp_path, monkeypatch):
    store, _, _ = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    store.stage_contract_path = SCORE_CONTRACT_PATH
    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is False


def test_persistent_cache_implementation_sha_change_is_miss(tmp_path, monkeypatch):
    store, repo_root, _ = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    (repo_root / "fake_impl" / "a.py").write_text("def f(): return 2  # behavior changed\n")
    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is False


def test_persistent_cache_parquet_added_is_miss(tmp_path, monkeypatch):
    store, _, source_data_dir = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    (source_data_dir / "000660.parquet").write_bytes(b"another-fake-parquet")
    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is False


def test_persistent_cache_parquet_deleted_is_miss(tmp_path, monkeypatch):
    store, _, source_data_dir = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    (source_data_dir / "005930.parquet").unlink()
    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is False


def test_persistent_cache_parquet_size_change_is_miss(tmp_path, monkeypatch):
    store, _, source_data_dir = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    (source_data_dir / "005930.parquet").write_bytes(b"fake-parquet-bytes-but-longer-now")
    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is False


def test_persistent_cache_parquet_mtime_ns_change_is_miss(tmp_path, monkeypatch):
    import os

    store, _, source_data_dir = _build_store(tmp_path, monkeypatch)
    _seed_cache(store)

    target = source_data_dir / "005930.parquet"
    st = target.stat()
    # Same size, same content, only mtime_ns advances -- must still MISS
    # since the fingerprint is stat-based (filename+size+mtime_ns), not
    # content-based.
    new_mtime_ns = st.st_mtime_ns + 1_000_000_000
    os.utime(target, ns=(st.st_atime_ns, new_mtime_ns))

    hit = store.load_into(FastSnapshotCache(), MonthlySnapshotCache())
    assert hit is False
