"""Acquisition closure summary writer (FIX02).

Pure/local helpers, deliberately kept separate from
``HistoricalInstrumentAcquisitionRunner`` — this module never touches the
network, the quota, or the checkpoint entry semantics.  It only reads an
already-completed runner result plus the checkpoint file it produced, and
freezes the acquisition-time checkpoint digest into a small closure artifact
that ``historical_authority_reconciliation.py`` binds against later.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from trend_scanner.data.krx_historical_instrument_acquisition import (
    EXPECTED_PRIMARY_PAIRS,
    HISTORICAL_CALENDAR_PATH,
    load_historical_trading_calendar,
)

DEFAULT_CLOSURE_PATH = Path("data/reference/source/history/krx_instrument_master/v01/acquisition_final_summary.json")
READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION = "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION"
NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION = "NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION"
RUNNER_COMPLETE_STATUS = "COMPLETE"


def _closure_ready(result: Mapping[str, Any], *, expected_pairs: int) -> bool:
    return (
        result.get("status") == RUNNER_COMPLETE_STATUS
        and result.get("target_count") == expected_pairs
        and result.get("completed_count") == expected_pairs
        and result.get("pending_count") == 0
        and result.get("failures") == 0
        and result.get("schema_failures") == 0
        and result.get("identity_failures") == 0
        and not result.get("quota_pause")
        and result.get("raw_file_count") == expected_pairs
        and bool(result.get("manifest_sha256"))
    )


def build_acquisition_closure_summary(
    result: Mapping[str, Any],
    *,
    checkpoint_path: str | Path,
    raw_root: str | Path,
    calendar_path: str | Path = HISTORICAL_CALENDAR_PATH,
    expected_pairs: int = EXPECTED_PRIMARY_PAIRS,
    source_commit: str | None = None,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """Build the closure summary payload from an already-finished runner result.

    Never recomputes the checkpoint digest — ``checkpoint_manifest_sha256``
    is copied verbatim from ``result["manifest_sha256"]`` (Section 9): the
    runner already computed it from the checkpoint bytes it just wrote, and
    this module must not substitute a value of its own.
    """

    calendar = load_historical_trading_calendar(calendar_path)
    ready = _closure_ready(result, expected_pairs=expected_pairs)
    payload: dict[str, Any] = {
        "schema_version": "KRX_HISTORICAL_UNIVERSE_ACQUISITION_CLOSURE_V01",
        "status": (
            READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
            if ready
            else NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
        ),
        "runner_status": result.get("status"),
        "target_count": result.get("target_count"),
        "completed_count": result.get("completed_count"),
        "pending_count": result.get("pending_count"),
        "failures": result.get("failures"),
        "schema_failures": result.get("schema_failures"),
        "identity_failures": result.get("identity_failures"),
        "quota_pause": bool(result.get("quota_pause")),
        "raw_file_count": result.get("raw_file_count"),
        "checkpoint_path": str(checkpoint_path),
        # Authoritative value: copied from the runner's own already-computed
        # digest, never a digest this module derives independently.
        "checkpoint_manifest_sha256": result.get("manifest_sha256"),
        "calendar_path": str(calendar_path),
        "calendar_date_count": calendar["trading_date_count"],
        "calendar_sha256": calendar["trading_dates_sha256"],
        "raw_root": str(raw_root),
        "network_attempts": result.get("network_attempts"),
        "retry_attempts": result.get("retry_attempts"),
        "quota_day_kst": result.get("quota_day_kst"),
        "quota_global_start": result.get("quota_global_start"),
        "quota_global_end": result.get("quota_global_end"),
        "completed_at_utc": result.get("completed_at_utc"),
    }
    if source_commit is not None:
        payload["source_commit"] = source_commit
    if execution_id is not None:
        payload["execution_id"] = execution_id
    return payload


def write_acquisition_closure_summary(payload: Mapping[str, Any], path: str | Path = DEFAULT_CLOSURE_PATH) -> Path:
    """Atomic write; never leaves a partial closure file behind (Section 10).

    Always overwrites in place — a failed/partial run's non-ready summary
    replaces any previous READY one, so a stale READY state can never survive
    a later non-ready run (Section 11 policy B / Section 39).
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8")
    with tempfile.NamedTemporaryFile("wb", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, target)
    return target


__all__ = [
    "DEFAULT_CLOSURE_PATH",
    "NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION",
    "READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION",
    "RUNNER_COMPLETE_STATUS",
    "build_acquisition_closure_summary",
    "write_acquisition_closure_summary",
]
