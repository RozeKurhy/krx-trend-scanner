"""Phase 3E exact-date KRX sector membership update orchestration.

This module is a thin coordinator for the Daily Update pipeline.  It does not
implement a new membership engine, a new collector, or custom resolution
rules.  Instead, it strictly adheres to the exact-date contract:
  - If a valid exact-date snapshot already exists: NOOP_ALREADY_COMPLETE
  - If an existing target snapshot is incomplete or invalid: BLOCKED (no overwrite)
  - If the target date exceeds the Phase 1 certified boundary: BLOCKED
  - Otherwise, delegates to build_rolling_sector_membership() and re-verifies.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from trend_scanner.data.rolling_market_data_refresh import (
    DEFAULT_ROLLING_AUTHORITY_DIR,
    load_rolling_authority,
)
from trend_scanner.data.sector_membership import (
    SectorMembershipSnapshotUnavailable,
    load_sector_membership_meta,
    load_sector_membership_snapshot,
    sector_membership_meta_path_for_date,
    sector_membership_path_for_date,
)
from trend_scanner.data.sector_membership_rolling import (
    EXPECTED_SECTOR_COUNT,
    RollingMembershipError,
    RollingMembershipRun,
    build_rolling_sector_membership,
    load_local_target_universe,
)


PASS = "PASS"
NOOP_ALREADY_COMPLETE = "NOOP_ALREADY_COMPLETE"
BLOCKED = "BLOCKED"
FAILED = "FAILED"

REASON_BOUNDARY_EXCEEDED = "TARGET_BEYOND_PHASE1_CERTIFIED_BOUNDARY"
REASON_EXISTING_INVALID = "EXISTING_TARGET_SNAPSHOT_INVALID"
REASON_NOOP_COMPLETE = "TARGET_SNAPSHOT_ALREADY_COMPLETE"
REASON_POST_VERIFY_FAILED = "POST_PUBLICATION_VERIFICATION_FAILED"


@dataclass(frozen=True)
class SectorMembershipExactUpdateResult:
    """Structured result for Phase 3E sector membership update."""

    target_as_of: str
    status: str
    reason: str
    snapshot_path: str | None = None
    meta_path: str | None = None
    target_population: int = 0
    snapshot_population: int = 0
    mapped: int = 0
    aggregate_only: int = 0
    unmapped: int = 0
    builder_called: bool = False
    published: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_as_of": self.target_as_of,
            "status": self.status,
            "reason": self.reason,
            "snapshot_path": self.snapshot_path,
            "meta_path": self.meta_path,
            "target_population": int(self.target_population),
            "snapshot_population": int(self.snapshot_population),
            "mapped": int(self.mapped),
            "aggregate_only": int(self.aggregate_only),
            "unmapped": int(self.unmapped),
            "builder_called": bool(self.builder_called),
            "published": bool(self.published),
        }


def _normalise_date(value: Any) -> str:
    try:
        return pd.Timestamp(value).strftime("%Y-%m-%d")
    except Exception as exc:
        raise ValueError(f"INVALID_TARGET_AS_OF:{value}") from exc


def _relative_or_str(path: Path, repo_root: Path) -> str:
    try:
        return str(path.relative_to(repo_root))
    except ValueError:
        return str(path)


def _verify_exact_snapshot_and_population(
    target: str,
    *,
    snapshot_path: Path,
    meta_path: Path,
    repo_root: Path,
) -> tuple[pd.DataFrame, dict[str, Any], pd.DataFrame]:
    """Verify an existing or newly published snapshot against the official contract."""
    snapshot = load_sector_membership_snapshot(target, path=snapshot_path, repo_root=repo_root)
    meta = load_sector_membership_meta(target, path=meta_path, repo_root=repo_root)

    if snapshot.empty or (snapshot["effective_date"] != target).any():
        raise ValueError("effective_date mismatch")
    if snapshot["ticker"].duplicated().any():
        raise ValueError("ticker duplicate detected")
    if not snapshot["market"].isin({"KOSPI", "KOSDAQ"}).all():
        raise ValueError("market invalid")
    if not set(snapshot["resolution_status"]).issubset({"MAPPED", "AGGREGATE_ONLY", "UNMAPPED"}):
        raise ValueError("invalid resolution_status")
    if meta.get("snapshot_effective_date") != target:
        raise ValueError("meta date mismatch")
    if meta.get("sector_count") != EXPECTED_SECTOR_COUNT:
        raise ValueError(f"meta sector_count mismatch: expected {EXPECTED_SECTOR_COUNT}, got {meta.get('sector_count')}")

    target_universe = load_local_target_universe(target, repo_root=repo_root)
    if len(snapshot) != len(target_universe):
        raise ValueError(f"target population mismatch: snapshot={len(snapshot)} target={len(target_universe)}")
    if set(snapshot["ticker"]) != set(target_universe["ticker"]):
        raise ValueError("target ticker set mismatch")

    snap_markets = dict(zip(snapshot["ticker"], snapshot["market"]))
    tgt_markets = dict(zip(target_universe["ticker"], target_universe["market"]))
    if snap_markets != tgt_markets:
        raise ValueError("ticker to market mapping mismatch")

    return snapshot, meta, target_universe


def update_sector_membership_exact(
    target_as_of: str,
    *,
    repo_root: Path | str = Path.cwd(),
    builder: Callable[..., RollingMembershipRun] | None = None,
) -> SectorMembershipExactUpdateResult:
    """Coordinate exact-date sector membership publication or verify NOOP."""
    repo_root = Path(repo_root).resolve()

    try:
        target = _normalise_date(target_as_of)
    except ValueError as exc:
        return SectorMembershipExactUpdateResult(
            target_as_of=str(target_as_of),
            status=FAILED,
            reason=str(exc),
        )

    # 1. Check Phase 1 certified boundary
    try:
        manifest = load_rolling_authority(repo_root / DEFAULT_ROLLING_AUTHORITY_DIR)
        certified_through = _normalise_date(manifest.certified_through)
    except Exception as exc:
        return SectorMembershipExactUpdateResult(
            target_as_of=target,
            status=BLOCKED,
            reason=f"PHASE1_ROLLING_AUTHORITY_UNAVAILABLE:{exc}",
        )

    if target > certified_through:
        return SectorMembershipExactUpdateResult(
            target_as_of=target,
            status=BLOCKED,
            reason=REASON_BOUNDARY_EXCEEDED,
            builder_called=False,
            published=False,
        )

    # 2. Check existing exact-date snapshot & meta
    snapshot_path = sector_membership_path_for_date(target, repo_root=repo_root)
    meta_path = sector_membership_meta_path_for_date(target, repo_root=repo_root)
    parquet_exists = snapshot_path.is_file()
    meta_exists = meta_path.is_file()

    # Partial artifact: either parquet-only or meta-only
    if parquet_exists != meta_exists:
        return SectorMembershipExactUpdateResult(
            target_as_of=target,
            status=BLOCKED,
            reason=REASON_EXISTING_INVALID,
            snapshot_path=_relative_or_str(snapshot_path, repo_root) if parquet_exists else None,
            meta_path=_relative_or_str(meta_path, repo_root) if meta_exists else None,
            builder_called=False,
            published=False,
        )

    # Both exist: validate integrity and reconciliation
    if parquet_exists and meta_exists:
        try:
            snapshot, meta, target_universe = _verify_exact_snapshot_and_population(
                target,
                snapshot_path=snapshot_path,
                meta_path=meta_path,
                repo_root=repo_root,
            )
            mapped_count = int((snapshot["resolution_status"] == "MAPPED").sum())
            agg_count = int((snapshot["resolution_status"] == "AGGREGATE_ONLY").sum())
            unmapped_count = int((snapshot["resolution_status"] == "UNMAPPED").sum())

            return SectorMembershipExactUpdateResult(
                target_as_of=target,
                status=NOOP_ALREADY_COMPLETE,
                reason=REASON_NOOP_COMPLETE,
                snapshot_path=_relative_or_str(snapshot_path, repo_root),
                meta_path=_relative_or_str(meta_path, repo_root),
                target_population=len(target_universe),
                snapshot_population=len(snapshot),
                mapped=mapped_count,
                aggregate_only=agg_count,
                unmapped=unmapped_count,
                builder_called=False,
                published=False,
            )
        except Exception:
            return SectorMembershipExactUpdateResult(
                target_as_of=target,
                status=BLOCKED,
                reason=REASON_EXISTING_INVALID,
                snapshot_path=_relative_or_str(snapshot_path, repo_root),
                meta_path=_relative_or_str(meta_path, repo_root),
                builder_called=False,
                published=False,
            )

    # 3. Snapshot absent: delegate to 46-sector builder
    builder_fn = builder if builder is not None else build_rolling_sector_membership
    try:
        run = builder_fn(target, repo_root=repo_root)
    except RollingMembershipError as exc:
        return SectorMembershipExactUpdateResult(
            target_as_of=target,
            status=BLOCKED,
            reason=str(exc),
            builder_called=True,
            published=False,
        )
    except Exception as exc:
        return SectorMembershipExactUpdateResult(
            target_as_of=target,
            status=FAILED,
            reason=f"BUILDER_UNEXPECTED_ERROR:{exc}",
            builder_called=True,
            published=False,
        )

    if not run.report.get("published"):
        reason = run.report.get("publication_reason") or "BUILDER_PUBLICATION_FAILED"
        return SectorMembershipExactUpdateResult(
            target_as_of=target,
            status=BLOCKED,
            reason=str(reason),
            target_population=int(run.report.get("target_population") or 0),
            builder_called=True,
            published=False,
        )

    # 4. Mandatory post-publication re-verification
    try:
        snapshot, meta, target_universe = _verify_exact_snapshot_and_population(
            target,
            snapshot_path=snapshot_path,
            meta_path=meta_path,
            repo_root=repo_root,
        )
    except Exception as exc:
        return SectorMembershipExactUpdateResult(
            target_as_of=target,
            status=FAILED,
            reason=f"{REASON_POST_VERIFY_FAILED}:{exc}",
            snapshot_path=_relative_or_str(snapshot_path, repo_root) if snapshot_path.is_file() else None,
            meta_path=_relative_or_str(meta_path, repo_root) if meta_path.is_file() else None,
            builder_called=True,
            published=True,
        )

    mapped_count = int((snapshot["resolution_status"] == "MAPPED").sum())
    agg_count = int((snapshot["resolution_status"] == "AGGREGATE_ONLY").sum())
    unmapped_count = int((snapshot["resolution_status"] == "UNMAPPED").sum())

    return SectorMembershipExactUpdateResult(
        target_as_of=target,
        status=PASS,
        reason=str(run.report.get("publication_reason") or "ALL_GATES_PASS"),
        snapshot_path=_relative_or_str(snapshot_path, repo_root),
        meta_path=_relative_or_str(meta_path, repo_root),
        target_population=len(target_universe),
        snapshot_population=len(snapshot),
        mapped=mapped_count,
        aggregate_only=agg_count,
        unmapped=unmapped_count,
        builder_called=True,
        published=True,
    )
