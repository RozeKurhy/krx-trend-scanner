"""Unit tests for the acquisition closure summary writer (FIX02 Section A/E)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from trend_scanner.data.krx_acquisition_closure import (
    NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    build_acquisition_closure_summary,
    write_acquisition_closure_summary,
)

ROOT = Path(__file__).resolve().parents[1]
CALENDAR_PATH = ROOT / "data/reference/source/history/krx_instrument_master/v01/historical_trading_calendar.json"


def _complete_result(**overrides: object) -> dict[str, object]:
    base = {
        "status": "COMPLETE",
        "target_count": 4,
        "completed_count": 4,
        "pending_count": 0,
        "failures": 0,
        "schema_failures": 0,
        "identity_failures": 0,
        "quota_pause": False,
        "raw_file_count": 4,
        "manifest_sha256": "a" * 64,
        "network_attempts": 4,
        "retry_attempts": 0,
        "quota_day_kst": "2026-08-27",
        "quota_global_start": 0,
        "quota_global_end": 4,
        "completed_at_utc": "2026-08-27T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_successful_closure_writer_produces_ready_summary(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    result = _complete_result()
    payload = build_acquisition_closure_summary(
        result, checkpoint_path=checkpoint_path, raw_root=tmp_path / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
    )
    assert payload["status"] == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
    assert payload["runner_status"] == "COMPLETE"
    # Authoritative digest is copied verbatim from the runner result, never
    # recomputed from the checkpoint bytes this module just read (Section 9).
    assert payload["checkpoint_manifest_sha256"] == "a" * 64


def test_partial_run_never_produces_ready_summary(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    result = _complete_result(status="PARTIAL", completed_count=2, pending_count=2)
    payload = build_acquisition_closure_summary(
        result, checkpoint_path=checkpoint_path, raw_root=tmp_path / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
    )
    assert payload["status"] == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
    assert payload["runner_status"] == "PARTIAL"


def test_paused_quota_never_produces_ready_summary(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    result = _complete_result(status="PAUSED_QUOTA", quota_pause=True, completed_count=1, pending_count=3)
    payload = build_acquisition_closure_summary(
        result, checkpoint_path=checkpoint_path, raw_root=tmp_path / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
    )
    assert payload["status"] == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION


def test_missing_manifest_sha_never_produces_ready_summary(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    result = _complete_result(manifest_sha256=None)
    payload = build_acquisition_closure_summary(
        result, checkpoint_path=checkpoint_path, raw_root=tmp_path / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
    )
    assert payload["status"] == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION


def test_stale_ready_summary_is_overwritten_by_later_non_ready_run(tmp_path: Path) -> None:
    """§39: a previous READY summary must not survive a later failed/partial run."""
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    summary_path = tmp_path / "acquisition_final_summary.json"

    ready_payload = build_acquisition_closure_summary(
        _complete_result(), checkpoint_path=checkpoint_path, raw_root=tmp_path / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
    )
    write_acquisition_closure_summary(ready_payload, summary_path)
    assert json.loads(summary_path.read_text())["status"] == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION

    partial_payload = build_acquisition_closure_summary(
        _complete_result(status="PARTIAL", completed_count=2, pending_count=2),
        checkpoint_path=checkpoint_path, raw_root=tmp_path / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
    )
    write_acquisition_closure_summary(partial_payload, summary_path)
    on_disk = json.loads(summary_path.read_text())
    assert on_disk["status"] == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
    assert on_disk["runner_status"] == "PARTIAL"


def test_write_is_atomic_and_leaves_no_partial_file(tmp_path: Path) -> None:
    checkpoint_path = tmp_path / "checkpoint.json"
    checkpoint_path.write_text(json.dumps({"entries": {}}), encoding="utf-8")
    summary_path = tmp_path / "acquisition_final_summary.json"
    payload = build_acquisition_closure_summary(
        _complete_result(), checkpoint_path=checkpoint_path, raw_root=tmp_path / "basic_info", calendar_path=CALENDAR_PATH, expected_pairs=4,
    )
    write_acquisition_closure_summary(payload, summary_path)
    leftovers = [p for p in tmp_path.iterdir() if p.name.startswith(".acquisition_final_summary.json.")]
    assert leftovers == []
