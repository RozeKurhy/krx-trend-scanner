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
computes a version key from the two frozen contract files' sha256 and a
cheap fingerprint of the raw OHLCV universe (file count + max mtime under
``data/raw/stocks/``), and only reuses the persisted cache if that key
matches exactly what is currently on disk -- otherwise it is treated as
fully stale and NOT loaded (w.md Section 27: "stale cache를 silent reuse
하면 안 된다"; Section 28: "version mismatch: fail or rebuild" -- this
implementation rebuilds rather than fails, since a cold cache is just the
pre-this-task baseline, not an error).

Cache version contract (w.md Section 28, ``BACKTEST_FEATURE_CACHE_V01``):
  - schema_version
  - score_contract_sha256 / stage_contract_sha256 (Pattern A FAST version identity)
  - source_data_fingerprint (ticker file_count + max mtime; cheap invalidation
    signal for "new/updated OHLCV data since last cache build" -- NOT a full
    content hash of every parquet file, which would itself cost as much as
    the disk-read problem this task addresses. Documented limitation: a
    source-data change that does not alter file count or advance mtime
    beyond the recorded fingerprint would not be detected. See
    docs/architecture/backtest_performance_engine_v01.md Section 12.)
  - generated_at
"""

from __future__ import annotations

import hashlib
import logging
import pickle
from dataclasses import dataclass
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from trend_scanner.backtest.feature_cache import FastSnapshotCache, MonthlySnapshotCache

logger = logging.getLogger(__name__)

CACHE_SCHEMA_VERSION = "BACKTEST_FEATURE_CACHE_V01"
DEFAULT_CACHE_DIR = Path("data/cache/backtest_features")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_data_fingerprint(source_data_dir: Path) -> dict[str, Any]:
    files = list(source_data_dir.glob("*.parquet"))
    max_mtime = max((f.stat().st_mtime for f in files), default=0.0)
    return {"file_count": len(files), "max_mtime": max_mtime}


@dataclass
class PersistentFeatureCacheStore:
    score_contract_path: Path
    stage_contract_path: Path
    source_data_dir: Path
    cache_dir: Path = DEFAULT_CACHE_DIR

    def _version_key(self) -> dict[str, Any]:
        return {
            "schema_version": CACHE_SCHEMA_VERSION,
            "score_contract_sha256": _sha256_file(self.score_contract_path),
            "stage_contract_sha256": _sha256_file(self.stage_contract_path),
            "source_data_fingerprint": _source_data_fingerprint(self.source_data_dir),
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
