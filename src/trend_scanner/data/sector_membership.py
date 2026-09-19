"""KRX sector-membership authority for the Sector RS path.

Exact-date loading remains available for refresh and historical consumers.
Daily consumers use the latest approved snapshot whose effective date is not
after the requested target date; future snapshots are never back-applied.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd


SNAPSHOT_EFFECTIVE_DATE = "2026-08-14"
LEGACY_SNAPSHOT_POPULATION = 2528
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
    """Raised when no valid approved membership snapshot can serve a target."""


def _normalise_as_of(as_of: str | pd.Timestamp) -> str:
    value = pd.Timestamp(as_of).strftime("%Y-%m-%d")
    return value


def default_sector_membership_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[3]
    return root / DEFAULT_STORE_DIR / DEFAULT_STORE_FILE


def default_sector_membership_meta_path(repo_root: Path | None = None) -> Path:
    root = repo_root or Path(__file__).resolve().parents[3]
    return root / DEFAULT_STORE_DIR / DEFAULT_META_FILE


def sector_membership_path_for_date(
    effective_date: str | pd.Timestamp,
    repo_root: Path | None = None,
) -> Path:
    root = repo_root or Path(__file__).resolve().parents[3]
    date_text = _normalise_as_of(effective_date).replace("-", "")
    return root / DEFAULT_STORE_DIR / f"sector_membership_{date_text}.parquet"


def sector_membership_meta_path_for_date(
    effective_date: str | pd.Timestamp,
    repo_root: Path | None = None,
) -> Path:
    root = repo_root or Path(__file__).resolve().parents[3]
    date_text = _normalise_as_of(effective_date).replace("-", "")
    return root / DEFAULT_STORE_DIR / f"sector_membership_{date_text}_meta.json"


def _validate_snapshot(
    frame: pd.DataFrame,
    *,
    path: Path,
    expected_effective_date: str,
    expected_population: int | None = None,
) -> pd.DataFrame:
    missing = [column for column in STORE_COLUMNS if column not in frame.columns]
    if missing:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_SCHEMA_MISSING:{','.join(missing)}"
        )
    result = frame.loc[:, list(STORE_COLUMNS)].copy()
    result["ticker"] = result["ticker"].astype(str).str.strip().str.zfill(6)
    result["market"] = result["market"].astype(str).str.strip().str.upper()
    result["effective_date"] = result["effective_date"].astype(str).str[:10]
    if result.empty or result["effective_date"].nunique() != 1 or result["effective_date"].iloc[0] != expected_effective_date:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_EFFECTIVE_DATE_INVALID:{path}"
        )
    if result["ticker"].duplicated().any():
        raise SectorMembershipSnapshotUnavailable("SECTOR_MEMBERSHIP_DUPLICATE_TICKER")
    if expected_population is not None and len(result) != expected_population:
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
    """Load the exact snapshot for ``as_of``; never carry a date forward/backward."""

    requested = _normalise_as_of(as_of)
    store_path = Path(path) if path is not None else sector_membership_path_for_date(requested, repo_root)
    if not store_path.exists():
        if path is None and requested != SNAPSHOT_EFFECTIVE_DATE:
            raise SectorMembershipSnapshotUnavailable(
                f"SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE:{requested}"
            )
        raise SectorMembershipSnapshotUnavailable(f"SECTOR_MEMBERSHIP_STORE_MISSING:{store_path}")
    suffix = store_path.suffix.lower()
    frame = pd.read_parquet(store_path) if suffix == ".parquet" else pd.read_csv(store_path)
    expected_population = LEGACY_SNAPSHOT_POPULATION if requested == SNAPSHOT_EFFECTIVE_DATE else None
    return _validate_snapshot(
        frame,
        path=store_path,
        expected_effective_date=requested,
        expected_population=expected_population,
    )


def _snapshot_date_from_name(name: str, suffix: str) -> str | None:
    prefix = "sector_membership_"
    if not name.startswith(prefix) or not name.endswith(suffix):
        return None
    compact = name[len(prefix) : -len(suffix)]
    if len(compact) != 8 or not compact.isdigit():
        return None
    try:
        return pd.Timestamp(compact).strftime("%Y-%m-%d")
    except Exception:
        return None


def resolve_sector_membership_snapshot_for_target(
    target_as_of: str | pd.Timestamp,
    *,
    repo_root: Path | None = None,
) -> tuple[pd.DataFrame, str, Path, dict[str, Any]]:
    """Resolve the latest approved membership snapshot available by target date.

    Candidate discovery is pair-based: the latest candidate date at or before
    ``target_as_of`` must have both parquet and metadata files and pass the
    existing exact-date loaders.  An invalid or partial latest candidate is a
    hard failure and is never silently replaced by an older snapshot.
    """

    requested = _normalise_as_of(target_as_of)
    root = repo_root or Path(__file__).resolve().parents[3]
    store_dir = root / DEFAULT_STORE_DIR
    candidates: dict[str, dict[str, Path]] = {}
    for path in store_dir.glob("sector_membership_*"):
        if path.name.endswith("_meta.json"):
            date_text = _snapshot_date_from_name(path.name, "_meta.json")
            kind = "meta"
        elif path.suffix == ".parquet":
            date_text = _snapshot_date_from_name(path.name, ".parquet")
            kind = "parquet"
        else:
            continue
        if date_text is not None:
            candidates.setdefault(date_text, {})[kind] = path

    eligible_dates = sorted(date_text for date_text in candidates if date_text <= requested)
    if not eligible_dates:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_NO_APPROVED_SNAPSHOT:{requested}"
        )

    selected = eligible_dates[-1]
    candidate = candidates[selected]
    parquet_path = candidate.get("parquet")
    meta_path = candidate.get("meta")
    if parquet_path is None or meta_path is None:
        raise SectorMembershipSnapshotUnavailable(
            f"SECTOR_MEMBERSHIP_SNAPSHOT_INCOMPLETE:{selected}"
        )

    snapshot = load_sector_membership_snapshot(
        selected,
        path=parquet_path,
        repo_root=root,
    )
    meta = load_sector_membership_meta(
        selected,
        path=meta_path,
        repo_root=root,
    )
    if meta.get("target_population") is not None:
        try:
            target_population = int(meta["target_population"])
        except (TypeError, ValueError):
            raise SectorMembershipSnapshotUnavailable(
                f"SECTOR_MEMBERSHIP_META_POPULATION_INVALID:{selected}"
            ) from None
        if target_population != len(snapshot):
            raise SectorMembershipSnapshotUnavailable(
                f"SECTOR_MEMBERSHIP_META_POPULATION_INVALID:{selected}"
            )
    return snapshot, selected, parquet_path, meta


def load_sector_mapping_exact_snapshot(
    as_of: str | pd.Timestamp,
    *,
    path: Path | str | None = None,
    repo_root: Path | None = None,
) -> dict[str, tuple[str | None, str | None, str, str]]:
    """Return ticker mapping plus explicit resolution status for an exact snapshot."""

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
    effective_date: str | pd.Timestamp = SNAPSHOT_EFFECTIVE_DATE,
    *,
    path: Path | str | None = None,
    repo_root: Path | None = None,
) -> dict[str, Any]:
    requested = _normalise_as_of(effective_date)
    meta_path = Path(path) if path is not None else sector_membership_meta_path_for_date(requested, repo_root)
    if not meta_path.exists():
        raise SectorMembershipSnapshotUnavailable(f"SECTOR_MEMBERSHIP_META_MISSING:{meta_path}")
    with meta_path.open("r", encoding="utf-8") as handle:
        meta = json.load(handle)
    if meta.get("snapshot_effective_date") != requested:
        raise SectorMembershipSnapshotUnavailable("SECTOR_MEMBERSHIP_META_DATE_INVALID")
    return meta


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
