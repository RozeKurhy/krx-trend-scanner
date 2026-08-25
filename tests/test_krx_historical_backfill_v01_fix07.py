"""Offline FIX07 closure-gate and provenance contract tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate_krx_historical_backfill_v01_fix07 import (
    PRODUCTION_RUNTIME_HEAD,
    coverage_gate,
    evaluate_ready_gate,
    pilot_gate,
    samsung_gate,
)


ROOT = Path(__file__).resolve().parents[1]
VALIDATION_HEAD = "fix07-committed-head"


def _coverage() -> dict:
    return {
        "candidate_date_count": 4340,
        "complete_date_count": 4209,
        "finalized_no_data_date_count": 131,
        "complete_partition_count": 8418,
        "no_data_partition_count": 262,
        "missing_date_count": 0,
        "missing_partition_count": 0,
        "failed_partition_count": 0,
        "partial_date_count": 0,
    }


def _diagnostic() -> dict:
    return {"status": "PASS", "source_head": PRODUCTION_RUNTIME_HEAD}


def _pilot() -> dict:
    return {
        "validation_generation": "FIX07",
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": VALIDATION_HEAD,
        "legacy": False,
        "mode": "live-pilot",
        "status": "PASS",
        "request_count": 6,
        "retry_count": 0,
    }


def _samsung() -> dict:
    return {
        "validation_generation": "FIX07",
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": VALIDATION_HEAD,
        "legacy": False,
        "mode": "live-pilot",
        "status": "PASS",
        "observations": [
            {"date": "2018-04-27", "snapshot_available": True, "ticker_found": True, "observed": 128386494, "match": True},
            {"date": "2018-05-04", "snapshot_available": True, "ticker_found": True, "observed": 6419324700, "match": True},
        ],
    }


def _audit() -> tuple[dict, dict, dict, dict]:
    return (
        _coverage(),
        {key: 0 for key in ("integrity_error_count", "content_hash_mismatch_count", "file_hash_mismatch_count", "row_count_mismatch_count", "physical_schema_error_count", "source_date_mismatch_count", "duplicate_ticker_count", "no_data_integrity_error_count")},
        {"cross_market_ticker_conflict_count": 0},
        {"invalid_short_code_count": 0},
    )


def test_ready_requires_current_diagnostic_pass(monkeypatch):
    monkeypatch.setattr("scripts.validate_krx_historical_backfill_v01_fix07.production_runtime_compatible", lambda: True)
    coverage, integrity, cross, identifier = _audit()
    result = evaluate_ready_gate(diagnostic={"status": "FAIL", "source_head": PRODUCTION_RUNTIME_HEAD}, pilot=_pilot(), samsung=_samsung(), coverage=coverage, integrity=integrity, cross_market=cross, identifier=identifier, validation_head=VALIDATION_HEAD)
    assert result["all_pass"] is False
    assert "BLOCKED_PROVENANCE" in result["blockers"]


def test_ready_requires_current_pilot_pass(monkeypatch):
    monkeypatch.setattr("scripts.validate_krx_historical_backfill_v01_fix07.production_runtime_compatible", lambda: True)
    coverage, integrity, cross, identifier = _audit()
    pilot = _pilot()
    pilot["status"] = "BLOCKED_PILOT"
    result = evaluate_ready_gate(diagnostic=_diagnostic(), pilot=pilot, samsung=_samsung(), coverage=coverage, integrity=integrity, cross_market=cross, identifier=identifier, validation_head=VALIDATION_HEAD)
    assert result["all_pass"] is False


def test_ready_requires_samsung_pass(monkeypatch):
    monkeypatch.setattr("scripts.validate_krx_historical_backfill_v01_fix07.production_runtime_compatible", lambda: True)
    coverage, integrity, cross, identifier = _audit()
    samsung = _samsung()
    samsung["observations"][1]["match"] = False
    result = evaluate_ready_gate(diagnostic=_diagnostic(), pilot=_pilot(), samsung=samsung, coverage=coverage, integrity=integrity, cross_market=cross, identifier=identifier, validation_head=VALIDATION_HEAD)
    assert result["all_pass"] is False


def test_ready_rejects_stale_pilot_validation_source(monkeypatch):
    monkeypatch.setattr("scripts.validate_krx_historical_backfill_v01_fix07.production_runtime_compatible", lambda: True)
    coverage, integrity, cross, identifier = _audit()
    pilot = _pilot()
    pilot["validation_source_head"] = "uncommitted-or-stale"
    assert pilot_gate(pilot, VALIDATION_HEAD) is False
    result = evaluate_ready_gate(diagnostic=_diagnostic(), pilot=pilot, samsung=_samsung(), coverage=coverage, integrity=integrity, cross_market=cross, identifier=identifier, validation_head=VALIDATION_HEAD)
    assert result["all_pass"] is False


def test_ready_rejects_missing_pilot(monkeypatch):
    monkeypatch.setattr("scripts.validate_krx_historical_backfill_v01_fix07.production_runtime_compatible", lambda: True)
    coverage, integrity, cross, identifier = _audit()
    result = evaluate_ready_gate(diagnostic=_diagnostic(), pilot=None, samsung=_samsung(), coverage=coverage, integrity=integrity, cross_market=cross, identifier=identifier, validation_head=VALIDATION_HEAD)
    assert result["all_pass"] is False


def test_ready_rejects_samsung_mismatch(monkeypatch):
    monkeypatch.setattr("scripts.validate_krx_historical_backfill_v01_fix07.production_runtime_compatible", lambda: True)
    coverage, integrity, cross, identifier = _audit()
    samsung = _samsung()
    samsung["observations"][0]["observed"] = 1
    assert samsung_gate(samsung, VALIDATION_HEAD) is False


def test_coverage_pass_alone_cannot_produce_ready(monkeypatch):
    monkeypatch.setattr("scripts.validate_krx_historical_backfill_v01_fix07.production_runtime_compatible", lambda: True)
    coverage, integrity, cross, identifier = _audit()
    result = evaluate_ready_gate(diagnostic=None, pilot=None, samsung=None, coverage=coverage, integrity=integrity, cross_market=cross, identifier=identifier, validation_head=VALIDATION_HEAD)
    assert coverage_gate(coverage) is True
    assert result["all_pass"] is False


def test_errata_implementation_head_remains_e508005():
    payload = json.loads((ROOT / "artifacts/data/architecture/krx_production_data/v01/errata/errata_manifest.json").read_text(encoding="utf-8"))
    summary = json.loads((ROOT / "artifacts/data/architecture/krx_production_data/v01/errata/errata_validation_summary.json").read_text(encoding="utf-8"))
    assert payload["implementation_head"] == PRODUCTION_RUNTIME_HEAD
    assert payload["validation_source_head"] == PRODUCTION_RUNTIME_HEAD
    assert summary["implementation_head"] == PRODUCTION_RUNTIME_HEAD
    assert summary["validation_source_head"] == PRODUCTION_RUNTIME_HEAD


def test_resume_failed_partition_requires_retry_failures():
    source = (ROOT / "scripts/run_krx_historical_backfill_v01_fix07.py").read_text(encoding="utf-8")
    assert "resume=True, retry_failures=True, max_task_attempts=1" in source
    assert "resume=True, retry_failures=False" in source


def test_fix07_repair_fetches_only_failed_kosdaq_side():
    source = (ROOT / "scripts/run_krx_historical_backfill_v01_fix07.py").read_text(encoding="utf-8")
    assert 'runner.run(REPAIR_DATE, REPAIR_DATE' in source
    assert 'client = KrxOpenApiClient(auth, max_requests=1' in source
    assert 'paired = store.get_manifest("KOSPI", REPAIR_DATE)' in source


def test_terminal_partition_equation():
    coverage = _coverage()
    assert coverage_gate(coverage) is True
    assert coverage["complete_partition_count"] + coverage["no_data_partition_count"] == 8680


def test_quota_counters_are_evidence_derived():
    source = (ROOT / "scripts/validate_krx_historical_backfill_v01_fix07.py").read_text(encoding="utf-8")
    assert "pilot_request_count" in source
    assert "repair_request_count" in source
    assert "resume_request_count" in source
    assert "transport_error_count" in source
