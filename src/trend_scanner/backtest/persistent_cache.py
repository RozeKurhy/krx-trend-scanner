"""Persistent (cross-process) Pattern A / FAST snapshot cache (w.md Sections 27-28).

``FastSnapshotCache``/``MonthlySnapshotCache`` (see
``trend_scanner.backtest.feature_cache``) are in-memory only: they are
rebuilt from zero every time a new process starts, so a fresh research run
(e.g. a future 300B/500B/1T market-cap threshold experiment,
``MARKET_CAP_THRESHOLD_STRATEGY_COMPARISON_V01``) still pays the full
Pattern A / FAST evaluation cost once per process, even though those
snapshots are strategy-invariant and would already be sitting in a
previous run's cache.

``PersistentFeatureCacheStore`` adds a disk-backed layer under
``data/cache/backtest_features/`` (already covered by the repo's existing
``/data/*`` .gitignore rule -- no repo binary is committed). On load, it
computes a version key from the two frozen contract files' sha256, an
aggregate hash over the actual Pattern A / FAST implementation source
files, and a stat-based fingerprint of the raw OHLCV universe, and only
reuses the persisted cache if that key matches exactly what is currently
on disk -- otherwise it is treated as fully stale and NOT loaded (w.md
Section 27: "stale cache를 silent reuse 하면 안 된다"; Section 28:
"version mismatch: fail or rebuild" -- this implementation rebuilds
rather than fails, since a cold cache is just the pre-this-task baseline,
not an error).

Cache version contract (w.md Section 28, ``BACKTEST_FEATURE_CACHE_V01``;
Phase 4 Major Fix 1 and Phase 4.1 Sections 2-3 strengthened this further):
  - schema_version
  - score_contract_sha256 / stage_contract_sha256 (Pattern A FAST version identity)
  - feature_implementation_sha256: aggregate sha256 over a sorted
    {relative_path: sha256} manifest of the source files that directly
    determine Pattern A / FAST snapshot output (see
    ``FEATURE_IMPLEMENTATION_FILES`` below, which includes the Phase 4.1
    ``snapshot_context.py`` performance module now that the precomputed-
    context code lives there instead of inside the frozen
    ``historical_snapshot.py``). A JSON-contract-only version key cannot
    detect a code change to these files, so relying on schema_version +
    contract hashes alone risks a stale HIT after an implementation change
    with no contract change. Deliberately NOT a raw git commit SHA (w.md:
    unrelated changes such as docs must not invalidate the whole cache).
  - source_data_fingerprint: sha256 over a sorted
    [relative_filename, file_size, mtime_ns] manifest for every parquet
    under ``source_data_dir`` -- stat-only, never reads file content
    (reading 2,506 parquet files' content to hash them would reintroduce
    the exact IO cost this cache exists to avoid).
  - runtime_identity: {python_version, pandas_version, numpy_version} full
    version strings (w.md Phase 4.1 Section 3) -- a persisted cache built
    under a different interpreter/library version may not be safe to reuse
    silently, so any of these changing forces a cold rebuild rather than a
    silent stale HIT.
  - generated_at
"""

from __future__ import annotations

import hashlib
import json
import logging
import pickle
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import numpy
import pandas

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = "BACKTEST_FEATURE_CACHE_V01"
DEFAULT_CACHE_DIR = Path("data/cache/backtest_features")

# Source files that directly determine Pattern A / FAST snapshot output
# (w.md Phase 4 Major Fix 1 Section 2 / Phase 4.1 Section 2's explicit
# list). Paths are relative to the repository root (the parent of ``src/``).
FEATURE_IMPLEMENTATION_FILES: tuple[str, ...] = (
    "src/trend_scanner/patterns/pattern_a_fast_evaluator.py",
    "src/trend_scanner/validation/historical_snapshot.py",
    "src/trend_scanner/backtest/snapshot_context.py",
    "src/trend_scanner/patterns/pattern_a_evaluator.py",
    "src/trend_scanner/validation/feature_report.py",
    "src/trend_scanner/research/pattern_a_fast_daily_features.py",
    "src/trend_scanner/research/pattern_a_fast_weekly_features.py",
    "src/trend_scanner/research/pattern_a_fast_monthly_features.py",
    "src/trend_scanner/data/resampler.py",
    "src/trend_scanner/data/market_calendar.py",
)


def _python_version() -> str:
    return platform.python_version()


def _pandas_version() -> str:
    return pandas.__version__


def _numpy_version() -> str:
    return numpy.__version__


def _runtime_identity() -> dict[str, str]:
    """{python_version, pandas_version, numpy_version} full version strings
    (w.md Phase 4.1 Section 3). Implemented as separate injectable
    functions (rather than inlined ``sys``/``pandas``/``numpy`` lookups) so
    tests can monkeypatch exactly one of the three independently."""
    return {
        "python_version": _python_version(),
        "pandas_version": _pandas_version(),
        "numpy_version": _numpy_version(),
    }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_json(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _feature_implementation_fingerprint(repo_root: Path) -> str:
    """Aggregate sha256 over a sorted {relative_path: file_sha256} manifest.

    Missing files hash to a fixed sentinel rather than raising, so a file
    rename/deletion is itself a version-key change (MISS) instead of a
    crash -- consistent with this store's "never error on version drift,
    always treat as cold start" contract.
    """
    manifest = {}
    for relative_path in sorted(FEATURE_IMPLEMENTATION_FILES):
        path = repo_root / relative_path
        manifest[relative_path] = _sha256_file(path) if path.exists() else "__MISSING__"
    return _sha256_json(manifest)


def _source_data_fingerprint(source_data_dir: Path) -> str:
    """sha256 over a sorted [filename, size, mtime_ns] manifest. Stat-only --
    never reads parquet content (w.md Phase 4 Major Fix 1B)."""
    manifest = []
    for f in sorted(source_data_dir.glob("*.parquet"), key=lambda p: p.name):
        st = f.stat()
        manifest.append([f.name, st.st_size, st.st_mtime_ns])
    return _sha256_json(manifest)


@dataclass
class PersistentFeatureCacheStore:
    score_contract_path: Path
    stage_contract_path: Path
    source_data_dir: Path
    cache_dir: Path = DEFAULT_CACHE_DIR
    repo_root: Path = Path(__file__).resolve().parents[3]

    def _version_key(self) -> dict[str, Any]:
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "score_contract_sha256": _sha256_file(self.score_contract_path),
            "stage_contract_sha256": _sha256_file(self.stage_contract_path),
            "feature_implementation_sha256": _feature_implementation_fingerprint(self.repo_root),
            "source_data_fingerprint": _source_data_fingerprint(self.source_data_dir),
            "runtime_identity": _runtime_identity(),
        }

    def _cache_file(self) -> Path:
        return self.cache_dir / "pattern_a_fast_snapshot_cache_v01.pkl"

    def load_into(self, fast_cache: FastSnapshotCache, monthly_cache: MonthlySnapshotCache) -> bool:
        """Returns True if a matching persisted cache was found and loaded."""
        path = self._cache_file()
        if not path.exists():
            logger.info("Persistent feature cache: no cache file at %s (cold start)", path)
            return False
        try:
            with path.open("rb") as f:
                payload = pickle.load(f)
        except Exception:
            logger.warning("Persistent feature cache: failed to read %s, treating as cold start", path)
            return False

        current_key = self._version_key()
        if payload.get("version_key") != current_key:
            logger.info(
                "Persistent feature cache: version mismatch (stored=%s, current=%s) -- rebuilding, not reusing stale entries",
                payload.get("version_key"), current_key,
            )
            return False

        fast_cache.import_store(payload["fast_store"])
        monthly_cache.import_store(payload["monthly_store"])
        logger.info(
            "Persistent feature cache: loaded %d fast snapshots + %d monthly snapshots from %s (generated_at=%s)",
            len(payload["fast_store"]), len(payload["monthly_store"]), path, payload.get("generated_at"),
        )
        return True

    def save_from(self, fast_cache: FastSnapshotCache, monthly_cache: MonthlySnapshotCache) -> None:
        """Atomically persists the current cache contents (temp file + rename,
        matching this repo's existing ParquetCache.save() convention)."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "version_key": self._version_key(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fast_store": fast_cache.export_store(),
            "monthly_store": monthly_cache.export_store(),
        }
        final_path = self._cache_file()
        temp_path = self.cache_dir / f".{final_path.name}.tmp"
        with temp_path.open("wb") as f:
            pickle.dump(payload, f)
        temp_path.replace(final_path)
        logger.info(
            "Persistent feature cache: saved %d fast snapshots + %d monthly snapshots to %s",
            len(payload["fast_store"]), len(payload["monthly_store"]), final_path,
        )
