from __future__ import annotations

from scripts.validate_market_data_repository_v02 import (
    _error_record,
    _runtime_network_guard,
    _stage_evidence_status,
    _stage_blocker,
    evidence_consistency_gate,
    git_diff_gate_from_result,
    probe_range_from_metadata,
    sample_gate,
)
from trend_scanner.data.errors import MarketDataError


def _comparison(status: str = "PASS", ticker: str = "005930") -> dict[str, str]:
    return {"ticker": ticker, "status": status}


def test_sample_gate_zero_samples_is_blocked() -> None:
    result = sample_gate(3, 0, 0, [])
    assert result["status"] == "BLOCKED_NO_LIVE_AUTHORITY_SAMPLE"
    assert result["usable_sample_count"] == 0
    assert result["all_requested_samples_pass"] is False


def test_sample_gate_one_sample_is_insufficient() -> None:
    result = sample_gate(3, 1, 1, [_comparison()])
    assert result["status"] == "BLOCKED_INSUFFICIENT_LIVE_AUTHORITY_SAMPLES"


def test_generic_two_sample_gate_can_pass() -> None:
    result = sample_gate(
        2,
        2,
        2,
        [_comparison("PASS", "005930"), _comparison("PASS", "000660")],
    )
    assert result["status"] == "PASS"
    assert result["usable_sample_count"] == 2
    assert result["all_requested_samples_pass"] is False


def test_failed_requested_sample_cannot_pass_three_sample_gate() -> None:
    result = sample_gate(
        3,
        3,
        2,
        [_comparison("PASS", "005930"), _comparison("PASS", "000660"), _comparison("FAIL", "068270")],
    )
    assert result["status"] == "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
    assert result["usable_sample_count"] == 2


def test_empty_comparisons_cannot_pass_even_with_counts() -> None:
    result = sample_gate(3, 3, 3, [])
    assert result["status"] == "BLOCKED_NO_LIVE_AUTHORITY_SAMPLE"


def test_probe_range_comes_from_actual_metadata() -> None:
    assert probe_range_from_metadata(
        {"actual_date_min": "2018-04-27", "actual_date_max": "2018-06-29"}
    ) == ("2018-04-27", "2018-06-29")


def test_empty_or_invalid_metadata_range_is_blocked() -> None:
    for metadata in (
        {},
        {"actual_date_min": "", "actual_date_max": ""},
        {"actual_date_min": "2024-01-03", "actual_date_max": "2024-01-02"},
    ):
        try:
            probe_range_from_metadata(metadata)
        except MarketDataError as exc:
            assert str(exc) == "BLOCKED_LIVE_ADJUSTED_SAMPLE"
        else:
            raise AssertionError("invalid metadata range unexpectedly passed")


def test_failed_ticker_exception_is_structured_without_stacktrace() -> None:
    record = _error_record("068270", MarketDataError("BLOCKED_LIVE_ADJUSTED_SAMPLE: timeout"))
    assert record == {
        "ticker": "068270",
        "requested_start": "",
        "requested_end": "",
        "stage": "UNKNOWN",
        "status": "FAIL",
        "error_code": "BLOCKED_LIVE_ADJUSTED_SAMPLE",
        "error_message": "BLOCKED_LIVE_ADJUSTED_SAMPLE: timeout",
        "record_type": "failure",
    }
    assert "Traceback" not in record["error_message"]


def test_runtime_network_guard_finds_no_forbidden_dependency_in_repository() -> None:
    result = _runtime_network_guard()
    assert result["runtime_forbidden_network_dependency_count"] == 0


def test_failed_git_diff_check_is_not_ready() -> None:
    result = git_diff_gate_from_result(2, "", "whitespace error")
    assert result["status"] == "BLOCKED_GIT_DIFF_CHECK"
    assert result["return_code"] == 2
    assert result["command"].startswith("git diff --check ")


def test_passed_git_diff_check_captures_command_and_streams() -> None:
    result = git_diff_gate_from_result(0, "", "")
    assert result["status"] == "PASS"
    assert result["stdout"] == ""
    assert result["stderr"] == ""


def test_provider_failure_stage_is_explicit_and_maps_external_blocker() -> None:
    record = _error_record(
        "005930",
        MarketDataError("provider exploded"),
        requested_start="2018-04-01",
        requested_end="2018-06-30",
        stage="ADJUSTED_PROVIDER_FETCH",
        record_type="provider_fetch",
    )
    assert record["stage"] == "ADJUSTED_PROVIDER_FETCH"
    assert _stage_blocker(record["stage"]) == "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE"


def test_composition_exception_does_not_map_to_external_pykrx() -> None:
    record = _error_record(
        "005930", MarketDataError("INVALID_REPOSITORY_V2_OUTPUT"), stage="REPOSITORY_COMPOSITION"
    )
    assert _stage_blocker(record["stage"]) == "BLOCKED_PRODUCTION_COMPOSITION_PROBE"
    assert _stage_blocker(record["stage"]) != "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE"


def test_temp_store_failure_stage_is_explicit() -> None:
    record = _error_record("005930", MarketDataError("hash"), stage="TEMP_ADJUSTED_STORE_READBACK")
    assert _stage_blocker(record["stage"]) == "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY"


def test_raw_load_failure_stage_is_explicit() -> None:
    record = _error_record("005930", MarketDataError("raw"), stage="RAW_PRODUCTION_LOAD")
    assert _stage_blocker(record["stage"]) == "BLOCKED_PRODUCTION_RAW_PROBE"


def test_early_stop_after_composition_failure_does_not_imply_external_failure() -> None:
    result = sample_gate(
        3,
        1,
        0,
        [],
        successful_provider_fetch_count=1,
        successful_temp_store_integrity_count=1,
        failure_records=[
            {
                "status": "FAIL",
                "stage": "REPOSITORY_COMPOSITION",
            }
        ],
    )
    assert result["status"] == "BLOCKED_PRODUCTION_COMPOSITION_PROBE"


def test_provider_success_and_composition_failure_are_distinct() -> None:
    result = sample_gate(
        3,
        1,
        0,
        [],
        successful_provider_fetch_count=1,
        successful_temp_store_integrity_count=1,
        failure_records=[{"status": "FAIL", "stage": "REPOSITORY_COMPOSITION"}],
    )
    assert result["successful_provider_fetch_count"] == 1
    assert result["successful_temp_store_integrity_count"] == 1
    assert result["status"] != "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE"


def test_evidence_counter_record_consistency_requires_matching_temp_pairs() -> None:
    provider_records = [{"status": "PASS"}]
    temp_records = [{"status": "PASS"}]
    composition_records = [{"status": "FAIL"}]
    consistent = evidence_consistency_gate(
        provider_records, temp_records, composition_records, temporary_store_ticker_count=1
    )
    assert consistent["status"] == "PASS"
    inconsistent = evidence_consistency_gate(
        provider_records, temp_records, composition_records, temporary_store_ticker_count=0
    )
    assert inconsistent["status"] == "BLOCKED_EVIDENCE_INCONSISTENCY"


def test_temp_store_count_matches_integrity_records() -> None:
    result = evidence_consistency_gate(
        [{"status": "PASS"}, {"status": "PASS"}],
        [{"status": "PASS"}, {"status": "FAIL"}],
        [{"status": "FAIL"}],
        temporary_store_ticker_count=1,
    )
    assert result["successful_temp_store_integrity_count"] == 1
    assert result["temporary_store_ticker_count"] == 1
    assert result["status"] == "PASS"


def test_composition_failure_does_not_mark_temp_store_evidence_failed() -> None:
    assert _stage_evidence_status([{"status": "PASS"}], "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY") == "PASS"
    assert _stage_evidence_status([{"status": "FAIL"}], "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY") == "BLOCKED_TEMP_ADJUSTED_STORE_INTEGRITY"


def _composition_evidence_record(**overrides):
    record = {
        "record_type": "composition",
        "status": "PASS",
        "explicit_placeholder_projection_count": 1,
        "rejected_raw_only_dates": [],
        "shared_placeholder_conflict_dates": [],
    }
    record.update(overrides)
    return record


def test_placeholder_counters_are_never_null() -> None:
    result = evidence_consistency_gate(
        [{"status": "PASS"}],
        [{"status": "PASS"}],
        [_composition_evidence_record()],
        temporary_store_ticker_count=1,
    )
    assert result["status"] == "PASS"
    assert result["accepted_placeholder_projection_count"] == 1
    assert result["rejected_raw_only_count"] == 0
    assert result["shared_placeholder_conflict_count"] == 0
    assert all(result[key] is not None for key in (
        "accepted_placeholder_projection_count",
        "rejected_raw_only_count",
        "shared_placeholder_conflict_count",
    ))


def test_placeholder_counters_are_aggregated_from_composition_records() -> None:
    result = evidence_consistency_gate(
        [{"status": "PASS"}, {"status": "PASS"}],
        [{"status": "PASS"}, {"status": "PASS"}],
        [
            _composition_evidence_record(
                explicit_placeholder_projection_count=2,
                rejected_raw_only_dates=["2024-01-02"],
                shared_placeholder_conflict_dates=["2024-01-03"],
            ),
            _composition_evidence_record(
                explicit_placeholder_projection_count=1,
                rejected_raw_only_dates=[],
                shared_placeholder_conflict_dates=[],
            ),
        ],
        temporary_store_ticker_count=2,
    )
    assert result["accepted_placeholder_projection_count"] == 3
    assert result["rejected_raw_only_count"] == 1
    assert result["shared_placeholder_conflict_count"] == 1


def test_counter_mismatch_blocks_ready() -> None:
    result = evidence_consistency_gate(
        [{"status": "PASS"}],
        [{"status": "PASS"}],
        [_composition_evidence_record()],
        temporary_store_ticker_count=1,
        accepted_placeholder_projection_count=0,
        rejected_raw_only_count=0,
        shared_placeholder_conflict_count=0,
    )
    assert result["status"] == "BLOCKED_EVIDENCE_INCONSISTENCY"
    assert "accepted_placeholder_projection_count" in result["mismatches"]


def test_null_placeholder_counter_blocks_closure_evidence() -> None:
    result = evidence_consistency_gate(
        [{"status": "PASS"}],
        [{"status": "PASS"}],
        [
            _composition_evidence_record(
                explicit_placeholder_projection_count=None,
            )
        ],
        temporary_store_ticker_count=1,
    )
    assert result["status"] == "BLOCKED_EVIDENCE_INCONSISTENCY"
    assert result["accepted_placeholder_projection_count"] == 0


def test_shared_conflict_composition_failure_is_not_external_pykrx() -> None:
    result = sample_gate(
        3,
        3,
        2,
        [{"status": "PASS"}, {"status": "PASS"}],
        successful_provider_fetch_count=3,
        successful_temp_store_integrity_count=3,
        failure_records=[
            {
                "status": "FAIL",
                "stage": "REPOSITORY_COMPOSITION",
                "session_projection_blocker": "BLOCKED_SHARED_DATE_PLACEHOLDER_CONFLICT",
            }
        ],
    )
    assert result["status"] == "BLOCKED_SHARED_DATE_PLACEHOLDER_CONFLICT"
    assert result["status"] != "BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE"
