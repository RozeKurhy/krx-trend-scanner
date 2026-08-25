"""Offline FIX08 acceptance and closure gate tests."""

from __future__ import annotations

from pathlib import Path

from scripts.validate_krx_historical_backfill_v01_fix08 import (
    FIX07_PILOT_VALIDATION_HEAD,
    PRODUCTION_RUNTIME_HEAD,
    coverage_gate,
    evaluate_ready_gate,
    idempotency_gate,
    pilot_gate,
    repair_gate,
    resume_gate,
    samsung_gate,
)


def _coverage(complete: bool = True) -> dict:
    return {
        "candidate_date_count": 4340,
        "complete_date_count": 4209 if complete else 2300,
        "finalized_no_data_date_count": 131,
        "complete_partition_count": 8418 if complete else 4600,
        "no_data_partition_count": 262,
        "missing_date_count": 0 if complete else 1909,
        "missing_partition_count": 0 if complete else 3818,
        "failed_partition_count": 0,
        "partial_date_count": 0,
    }


def _pilot(head: str = FIX07_PILOT_VALIDATION_HEAD) -> dict:
    return {
        "validation_generation": "FIX07",
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": head,
        "legacy": False,
        "mode": "live-pilot",
        "status": "PASS",
        "request_count": 6,
        "retry_count": 0,
    }


def _samsung(head: str = FIX07_PILOT_VALIDATION_HEAD) -> dict:
    return {
        "validation_generation": "FIX07",
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": head,
        "legacy": False,
        "mode": "live-pilot",
        "status": "PASS",
        "observations": [
            {"date": "2018-04-27", "snapshot_available": True, "ticker_found": True, "observed": 128386494, "match": True},
            {"date": "2018-05-04", "snapshot_available": True, "ticker_found": True, "observed": 6419324700, "match": True},
        ],
    }


def _diagnostic() -> dict:
    return {"status": "PASS", "source_head": PRODUCTION_RUNTIME_HEAD}


def _repair() -> dict:
    return {
        "status": "PASS",
        "original_repair_status": "PASS",
        "date": "2019-04-26",
        "market": "KOSDAQ",
        "attempt_count": 1,
        "retry_count": 0,
        "http_status": 200,
        "row_count": 1334,
        "new_status": "COMPLETE",
        "paired_market": "KOSPI",
        "paired_market_status": "COMPLETE",
        "verification": {"valid": True},
        "repair_runner_implementation_head": FIX07_PILOT_VALIDATION_HEAD,
        "repair_execution_head": "5398d62761c80b9960cd61986a585a3b06a5b3e2",
        "original_validation_source_head": "5398d62761c80b9960cd61986a585a3b06a5b3e2",
        "runner_compatible_between_heads": True,
        "runner_code_diff_count": 0,
        "production_runtime_diff_count": 0,
        "records_key_verified": "OutBlock_1",
    }


def _resume(implementation_head: str = "fix08-implementation-head") -> dict:
    return {
        "validation_generation": "FIX08",
        "status": "PASS",
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": implementation_head,
        "resume": True,
        "retry_failures": False,
        "retry_count": 0,
        "status_counts": {"401": 0, "403": 0, "429": 0, "5xx": 0, "transport_error": 0},
        "failed_partition_count": 0,
        "final_missing_partition_count": 0,
    }


def _idempotency() -> dict:
    return {
        "candidate_partition_count": 8680,
        "terminal_partition_count": 8680,
        "pending_partition_count": 0,
        "would_fetch_partition_count": 0,
        "actual_network_request_count": 0,
        "status": "PASS",
    }


def test_pilot_gate_uses_independent_expected_head():
    assert pilot_gate(_pilot()) is True
    assert pilot_gate(_pilot("wrong")) is False


def test_pilot_gate_rejects_self_consistent_but_wrong_head():
    payload = _pilot("self-consistent-but-wrong")
    assert payload["validation_source_head"] == "self-consistent-but-wrong"
    assert pilot_gate(payload) is False


def test_samsung_gate_rejects_wrong_validation_head():
    assert samsung_gate(_samsung("wrong")) is False


def test_repair_gate_accepts_execution_head_with_artifact_only_delta():
    assert repair_gate(_repair()) is True


def test_repair_gate_rejects_runner_source_delta():
    payload = _repair()
    payload["runner_code_diff_count"] = 1
    assert repair_gate(payload) is False


def test_repair_gate_accepts_provider_verified_records_key():
    assert repair_gate(_repair()) is True


def test_ready_requires_repair_gate(monkeypatch):
    coverage = _coverage()
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), {}, _resume(), _idempotency(), coverage, {}, {"cross_market_ticker_conflict_count": 0}, {"invalid_short_code_count": 0}, "fix08-implementation-head")
    assert result["all_pass"] is False
    assert "BLOCKED_PROVENANCE" in result["blockers"]


def test_ready_requires_resume_gate():
    coverage = _coverage()
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), _repair(), {}, _idempotency(), coverage, {}, {"cross_market_ticker_conflict_count": 0}, {"invalid_short_code_count": 0}, "fix08-implementation-head")
    assert result["all_pass"] is False
    assert "BLOCKED_COVERAGE" in result["blockers"]


def test_ready_requires_idempotency_gate():
    coverage = _coverage()
    bad = _idempotency()
    bad["pending_partition_count"] = 1
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), _repair(), _resume(), bad, coverage, {}, {"cross_market_ticker_conflict_count": 0}, {"invalid_short_code_count": 0}, "fix08-implementation-head")
    assert result["all_pass"] is False


def test_resume_missing_artifact_cannot_ready():
    assert resume_gate(None, "fix08-implementation-head") is False


def test_provenance_status_independent_from_coverage():
    coverage = _coverage(complete=False)
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), _repair(), _resume(), _idempotency(), coverage, {}, {"cross_market_ticker_conflict_count": 0}, {"invalid_short_code_count": 0}, "fix08-implementation-head")
    assert result["provenance_status"] == "PASS"
    assert result["coverage_status"] == "INCOMPLETE"
    assert "BLOCKED_PROVENANCE" not in result["blockers"]


def test_coverage_blocker_does_not_create_provenance_blocker():
    coverage = _coverage(complete=False)
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), _repair(), _resume(), _idempotency(), coverage, {}, {"cross_market_ticker_conflict_count": 0}, {"invalid_short_code_count": 0}, "fix08-implementation-head")
    assert result["provenance_status"] == "PASS"
    assert result["blockers"] == ["BLOCKED_COVERAGE"]


def test_idempotency_gate_requires_zero_network():
    assert idempotency_gate(_idempotency()) is True
    payload = _idempotency()
    payload["actual_network_request_count"] = 1
    assert idempotency_gate(payload) is False
