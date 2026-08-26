"""CLI integration tests for the acquisition script's closure-writer wiring
(FIX02 Section C / §37-38).

Network is never used here: ``HistoricalInstrumentAcquisitionRunner.run_full_historical``
is monkeypatched to return a synthetic result, matching the repo's existing
monkeypatch convention for this kind of CLI-path test.
"""

from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

import scripts.run_krx_historical_instrument_acquisition_v01 as cli_module
from trend_scanner.data.krx_acquisition_closure import (
    NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
    READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION,
)
from trend_scanner.data.krx_historical_instrument_acquisition import HistoricalInstrumentAcquisitionRunner


def _synthetic_complete_result(runner: HistoricalInstrumentAcquisitionRunner, *args: object, **kwargs: object) -> dict[str, object]:
    # CLI wiring uses the production EXPECTED_PRIMARY_PAIRS (8190) default —
    # a small count here would (correctly) yield a NOT_READY closure, so this
    # fixture matches full production scale to exercise the READY path.
    return {
        "status": "COMPLETE", "target_count": 8190, "completed_count": 8190, "pending_count": 0,
        "failures": 0, "schema_failures": 0, "identity_failures": 0, "quota_pause": False,
        "network_attempts": 8190, "retry_attempts": 0, "quota_day_kst": "2026-08-27",
        "quota_global_start": 0, "quota_global_end": 8190, "raw_file_count": 8190, "raw_bytes": 100,
        "manifest_sha256": "b" * 64, "started_at_utc": "2026-08-27T00:00:00+00:00",
        "completed_at_utc": "2026-08-27T00:00:01+00:00",
    }


def test_execute_live_complete_result_writes_ready_closure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(HistoricalInstrumentAcquisitionRunner, "run_full_historical", _synthetic_complete_result)
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "unused-because-monkeypatched")
    closure_path = tmp_path / "acquisition_final_summary.json"
    argv = [
        "run_krx_historical_instrument_acquisition_v01.py",
        "--quota-db", str(tmp_path / "quota.sqlite3"),
        "--closure-summary", str(closure_path),
        "--execute-live",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    exit_code = cli_module.main()
    assert exit_code == 0
    assert closure_path.is_file()
    payload = json.loads(closure_path.read_text(encoding="utf-8"))
    assert payload["status"] == READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
    assert payload["runner_status"] == "COMPLETE"
    assert payload["checkpoint_manifest_sha256"] == "b" * 64
    # §18: the single --execute-live command must wire the runner's own
    # checkpoint_path/raw_root into the closure it builds. Monkeypatching
    # run_full_historical alone would not catch a wiring regression that
    # passed some other path into the closure builder, so assert the closure
    # payload actually carries the runner's real (default-constructed) paths.
    assert payload["checkpoint_path"] == str(
        Path("data/reference/source/history/krx_instrument_master/v01/checkpoint.json")
    )
    assert payload["raw_root"] == str(
        Path("data/reference/source/history/krx_instrument_master/v01/basic_info")
    )


def test_execute_live_partial_result_overwrites_previous_ready_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closure_path = tmp_path / "acquisition_final_summary.json"
    closure_path.write_text(
        json.dumps({"status": READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION, "runner_status": "COMPLETE"}),
        encoding="utf-8",
    )

    def _partial(runner: HistoricalInstrumentAcquisitionRunner, *args: object, **kwargs: object) -> dict[str, object]:
        result = _synthetic_complete_result(runner)
        result.update(status="PARTIAL", completed_count=1, pending_count=1)
        return result

    monkeypatch.setattr(HistoricalInstrumentAcquisitionRunner, "run_full_historical", _partial)
    monkeypatch.setenv("KRX_OPEN_API_AUTH_KEY", "unused-because-monkeypatched")
    argv = [
        "run_krx_historical_instrument_acquisition_v01.py",
        "--quota-db", str(tmp_path / "quota.sqlite3"),
        "--closure-summary", str(closure_path),
        "--execute-live",
    ]
    monkeypatch.setattr(sys, "argv", argv)
    exit_code = cli_module.main()
    assert exit_code == 0
    payload = json.loads(closure_path.read_text(encoding="utf-8"))
    assert payload["status"] == NOT_READY_FOR_HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION
    assert payload["runner_status"] == "PARTIAL"


def test_dry_run_never_touches_closure_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    closure_path = tmp_path / "acquisition_final_summary.json"
    argv = [
        "run_krx_historical_instrument_acquisition_v01.py",
        "--quota-db", str(tmp_path / "quota.sqlite3"),
        "--closure-summary", str(closure_path),
    ]
    monkeypatch.setattr(sys, "argv", argv)
    exit_code = cli_module.main()
    assert exit_code == 0
    assert not closure_path.exists()
