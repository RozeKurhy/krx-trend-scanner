from __future__ import annotations

from scripts.validate_market_data_repository_v02 import (
    _error_record,
    _runtime_network_guard,
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
        "status": "FAIL",
        "error_code": "BLOCKED_LIVE_ADJUSTED_SAMPLE",
        "error_message": "BLOCKED_LIVE_ADJUSTED_SAMPLE: timeout",
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
