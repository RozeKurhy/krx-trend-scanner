"""Frozen KRX sector-membership authority for the current-only Sector RS path.

The generic historical mapping helpers intentionally keep their legacy
``effective_date <= as_of`` behaviour.  This module is the explicit production
consumer for the approved 2026-08-14 snapshot and therefore rejects every
other evaluation date instead of silently carrying the snapshot forward or
backward.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


SNAPSHOT_EFFECTIVE_DATE = "2026-08-14"
POLICY_VERSION = "MOST_SPECIFIC_NATIVE_SECTOR_V01"
SOURCE_AUTHORITY = "KRX_FROZEN_CANONICAL_SECTOR_MEMBERSHIP"
DEFAULT_STORE_DIR = Path("data/market/sector_membership/v01")
DEFAULT_STORE_FILE = "sector_membership_20260814.parquet"
DEFAULT_META_FILE = "sector_membership_20260814_meta.json"

STORE_COLUMNS = (
    "ticker",
    "market",
    "effective_date",
    "sector_code",
    "sector_name",
    "resolution_status",
    "policy_version",
    "source_authority",
    "source_artifact_sha256",
)


class SectorMembershipSnapshotUnavailable(ValueError):
    """Raised when the exact frozen snapshot cannot be used for ``as_of``."""


def _normalise_as_of(as_of: str | pd.Timestamp) -> str:
    value = pd.Timestamp(as_of).strftime("%Y-%m-%d")
    return value


def default_sector_membership_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[3]
    return root / DEFAULT_STORE_DIR / DEFAULT_STORE_FILE


def default_sector_membership_meta_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[3]
    return root / DEFAULT_STORE_DIR / DEFAULT_META_FILE


def _validate_snapshot(frame: pd.DataFrame, *, path: Path) -> pd.DataFrame:
    missing = [column for column in STORE_COLUMNS if column not in frame.columns]
    if missing:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_SCHEMA_MISSING:{','.join(missing)}"
        )
    result = frame.loc[:, list(STORE_COLUMNS)].copy()
    result["ticker"] = result["ticker"].astype(str).str.strip().str.zfill(6)
    result["market"] = result["market"].astype(str).str.strip().str.upper()
    result["effective_date"] = result["effective_date"].astype(str).str[:10]
    if result["effective_date"].nunique() != 1 or result["effective_date"].iloc[0] != SNAPSHOT_EFFECTIVE_DATE:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_EFFECTIVE_DATE_INVALID:{path}"
        )
    if result["ticker"].duplicated().any():
        raise SectorMembershipSnapshotUnavailable("SECTOR_MEMBERSHIP_DUPLICATE_TICKER")
    if len(result) != 2528:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_POPULATION_INVALID:{len(result)}"
        )
    allowed = {"MAPPED", "AGGREGATE_ONLY", "UNMAPPED"}
    if not set(result["resolution_status"].astype(str)).issubset(allowed):
        raise SectorMembershipSnapshotUnavailable("SECTOR_MEMBERSHIP_RESOLUTION_STATUS_INVALID")
    unmapped = result["resolution_status"].eq("UNMAPPED")
    if result.loc[unmapped, ["sector_code", "sector_name"]].notna().any().any():
        raise SectorMembershipSnapshotUnavailable("SECTOR_MEMBERSHIP_UNMAPPED_NOT_NULL")
    if result.loc[~unmapped, ["sector_code", "sector_name"]].isna().any().any():
        raise SectorMembershipSnapshotUnavailable("SECTOR_MEMBERSHIP_MAPPED_NULL")
    return result.sort_values(["market", "ticker"], kind="mergesort").reset_index(drop=True)


def load_sector_membership_snapshot(
    as_of: str | pd.Timestamp,
    *,
    path: Path | str | None = None,
    repo_root: Path | None = None,
) -> pd.DataFrame:
    """Load the approved exact snapshot; never reuse it for another date."""

    requested = _normalise_as_of(as_of)
    if requested != SNAPSHOT_EFFECTIVE_DATE:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE:{requested}"
        )
    store_path = Path(path) if path is not None else default_sector_membership_path(repo_root)
    if not store_path.exists():
        raise SectorMembershipSnapshotUnavailable(f"SECTOR_MEMBERSHIP_STORE_MISSING:{store_path}")
    suffix = store_path.suffix.lower()
    frame = pd.read_parquet(store_path) if suffix == ".parquet" else pd.read_csv(store_path)
    return _validate_snapshot(frame, path=store_path)


def load_sector_mapping_exact_snapshot(
    as_of: str | pd.Timestamp,
    *,
    path: Path | str | None = None,
    repo_root: Path | None = None,
) -> dict[str, tuple[str | None, str | None, str, str]]:
    """Return ticker mapping plus explicit resolution status for all 2528 rows."""

    frame = load_sector_membership_snapshot(as_of, path=path, repo_root=repo_root)
    return {
        row.ticker: (
            None if pd.isna(row.sector_code) else str(row.sector_code),
            None if pd.isna(row.sector_name) else str(row.sector_name),
            str(row.effective_date),
            str(row.resolution_status),
        )
        for row in frame.itertuples(index=False)
    }


def load_sector_membership_meta(
    *,
    path: Path | str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    meta_path = Path(path) if path is not None else default_sector_membership_meta_path(repo_root)
    if not meta_path.exists():
        raise SectorMembershipSnapshotUnavailable(f"SECTOR_MEMBERSHIP_META_MISSING:{meta_path}")
    with meta_path.open("r", encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("snapshot_effective_date") != SNAPSHOT_EFFECTIVE_DATE:
        raise SectorMembershipSnapshotUnavailable("SECTOR_MEMBERSHIP_META_DATE_INVALID")
    return meta


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
