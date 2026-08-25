"""Offline FIX09 repair/resume/closure gate tests."""

from __future__ import annotations

from scripts.validate_krx_historical_backfill_v01_fix09 import (
    FIX07_LIVE_VALIDATION_HEAD,
    PRODUCTION_RUNTIME_HEAD,
    coverage_gate,
    dedupe_failed_dates,
    evaluate_ready_gate,
    idempotency_gate,
    partition_counts,
    repair_2023_gate,
    resume_gate,
)


def _coverage(*, complete: bool = True) -> dict:
    return {
        "candidate_date_count": 4340,
        "complete_date_count": 4340 if complete else 3449,
        "finalized_no_data_date_count": 0 if complete else 195,
        "complete_partition_count": 8680 if complete else 6898,
        "no_data_partition_count": 0 if complete else 390,
        "missing_date_count": 0 if complete else 695,
        "failed_date_count": 0,
        "partial_date_count": 0,
        "missing_partition_count": 0 if complete else 1390,
        "failed_partition_count": 0,
    }


def _diagnostic() -> dict:
    return {"status": "PASS", "source_head": PRODUCTION_RUNTIME_HEAD}


def _pilot() -> dict:
    return {
        "validation_generation": "FIX07",
        "mode": "live-pilot",
        "legacy": False,
        "status": "PASS",
        "request_count": 6,
        "retry_count": 0,
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": FIX07_LIVE_VALIDATION_HEAD,
    }


def _samsung() -> dict:
    return {
        **_pilot(),
        "observations": [
            {"date": "2018-04-27", "observed": 128386494, "match": True},
            {"date": "2018-05-04", "observed": 6419324700, "match": True},
        ],
    }


def _repair_2019() -> dict:
    return {
        "status": "PASS",
        "date": "2019-04-26",
        "market": "KOSDAQ",
        "records_key_verified": "OutBlock_1",
        "repair_runner_implementation_head": FIX07_LIVE_VALIDATION_HEAD,
        "repair_execution_head": "5398d62761c80b9960cd61986a585a3b06a5b3e2",
    }


def _repair_2023(head: str = "fix09-head") -> dict:
    return {
        "validation_generation": "FIX09",
        "status": "PASS",
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": head,
        "date": "2023-12-21",
        "market": "KOSPI",
        "previous_status": "FAILED",
        "paired_market": "KOSDAQ",
        "paired_market_status": "COMPLETE",
        "attempt_count": 1,
        "retry_count": 0,
        "http_status": 200,
        "row_count": 1500,
        "new_status": "COMPLETE",
        "verification": {"valid": True},
        "records_key_verified": "OutBlock_1",
    }


def _resume(head: str = "fix09-head") -> dict:
    return {
        "validation_generation": "FIX09",
        "status": "PASS",
        "production_runtime_head": PRODUCTION_RUNTIME_HEAD,
        "validation_source_head": head,
        "resume": True,
        "retry_failures": False,
        "max_transient_retries": 0,
        "retry_count": 0,
        "status_counts": {"401": 0, "403": 0, "429": 0, "5xx": 0, "transport_error": 0},
        "final_missing_partition_count": 0,
        "final_failed_partition_count": 0,
        "final_nonterminal_partition_count": 0,
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


def _audit():
    return ({key: 0 for key in (
        "integrity_error_count", "content_hash_mismatch_count", "file_hash_mismatch_count",
        "row_count_mismatch_count", "physical_schema_error_count", "source_date_mismatch_count",
        "duplicate_ticker_count", "no_data_integrity_error_count",
    )}, {"cross_market_ticker_conflict_count": 0}, {"invalid_short_code_count": 0})


def test_fix09_repair_targets_only_2023_12_21_kospi():
    source = open("scripts/run_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert 'REPAIR_DATE = "2023-12-21"' in source
    assert 'market": "KOSPI"' in source
    assert 'max_requests=1' in source


def test_fix09_repair_uses_retry_failures_true():
    source = open("scripts/run_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert "resume=True, retry_failures=True, max_task_attempts=1" in source


def test_fix09_repair_max_task_attempts_one():
    source = open("scripts/run_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert "max_task_attempts=1" in source


def test_fix09_repair_skips_complete_kosdaq():
    source = open("scripts/run_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert 'paired = store.get_manifest("KOSDAQ", REPAIR_DATE)' in source
    assert 'paired or {}).get("status") != "COMPLETE"' in source


def test_fix09_resume_uses_retry_failures_false_after_repair():
    source = open("scripts/run_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert "resume=True, retry_failures=False" in source


def test_fix09_resume_rejects_existing_failed_partition():
    source = open("scripts/run_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert 'before["failed"] > 0' in source
    assert "BLOCKED_REPAIR_PRECONDITION" in source


def test_fix09_failed_dates_csv_deduplicates_dates():
    rows = dedupe_failed_dates({
        "2023-12-21": {"KOSPI": {"status": "FAILED"}, "KOSDAQ": {"status": "COMPLETE"}}
    })
    assert rows == [{"date": "2023-12-21", "classification": "FAILED_OR_PARTIAL", "markets": "KOSPI:FAILED;KOSDAQ:COMPLETE"}]


def test_fix09_missing_failed_nonterminal_counts_are_distinct():
    counts = partition_counts(
        [{"status": "COMPLETE"}, {"status": "NO_DATA"}, {"status": "FAILED"}],
        candidate_date_count=2,
    )
    assert counts["missing"] == 1
    assert counts["failed"] == 1
    assert counts["nonterminal"] == 2


def test_fix09_ready_requires_zero_failed():
    integrity, cross, identifier = _audit()
    coverage = _coverage()
    coverage["failed_partition_count"] = 1
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), _repair_2019(), _repair_2023(), _resume(), _idempotency(), coverage, integrity, cross, identifier, "fix09-head")
    assert result["all_pass"] is False
    assert "BLOCKED_COVERAGE" in result["blockers"]


def test_fix09_ready_requires_zero_partial():
    integrity, cross, identifier = _audit()
    coverage = _coverage()
    coverage["partial_date_count"] = 1
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), _repair_2019(), _repair_2023(), _resume(), _idempotency(), coverage, integrity, cross, identifier, "fix09-head")
    assert result["all_pass"] is False


def test_fix09_ready_requires_zero_missing():
    integrity, cross, identifier = _audit()
    coverage = _coverage()
    coverage["missing_partition_count"] = 1
    result = evaluate_ready_gate(_diagnostic(), _pilot(), _samsung(), _repair_2019(), _repair_2023(), _resume(), _idempotency(), coverage, integrity, cross, identifier, "fix09-head")
    assert result["all_pass"] is False


def test_fix09_idempotency_requires_zero_pending():
    payload = _idempotency()
    payload["pending_partition_count"] = 1
    assert idempotency_gate(payload) is False


def test_fix09_execution_head_may_differ_only_by_artifacts():
    source = open("scripts/validate_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert "executable_source_changed_after_implementation" in source
    assert "production_runtime_compatible" in source


def test_fix09_executable_source_frozen_after_network():
    source = open("scripts/validate_krx_historical_backfill_v01_fix09.py", encoding="utf-8").read()
    assert 'EXECUTABLE_PATHS = (' in source
    assert 'return any(path in EXECUTABLE_PATHS or path.startswith("src/") for path in paths)' in source


def test_fix09_repair_gate_requires_current_head():
    assert repair_2023_gate(_repair_2023("fix09-head"), "fix09-head") is True
    assert repair_2023_gate(_repair_2023("wrong"), "fix09-head") is False


def test_fix09_resume_gate_requires_zero_nonterminal():
    payload = _resume()
    payload["final_nonterminal_partition_count"] = 1
    assert resume_gate(payload, "fix09-head") is False
