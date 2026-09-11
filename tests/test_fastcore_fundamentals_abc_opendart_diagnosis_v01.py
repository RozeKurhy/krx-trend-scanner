"""Focused tests for the bounded Q3 empty-binary diagnosis."""

from scripts.recover_fastcore_fundamentals_abc_opendart_pending_v01 import (
    can_finalize_true_unavailable,
    classify_binary_diagnostic,
    validate_filing_selection,
)


def test_01_url_error_empty_is_transport_failure():
    assert classify_binary_diagnostic(
        http_status=None, response_byte_length=0, status=None,
        classification="EMPTY_RESPONSE", error_type="URLError", valid_zip=False,
    ) == "OPENDART_TRANSPORT_FAILURE"


def test_02_timeout_empty_is_transport_failure():
    assert classify_binary_diagnostic(
        http_status=None, response_byte_length=0, status=None,
        classification="EMPTY_RESPONSE", error_type="TimeoutError", valid_zip=False,
    ) == "OPENDART_TRANSPORT_FAILURE"


def test_03_http_200_zero_bytes_is_http200_empty_binary():
    assert classify_binary_diagnostic(
        http_status=200, response_byte_length=0, status=None,
        classification="EMPTY_RESPONSE", error_type="EmptyResponse", valid_zip=False,
    ) == "OPENDART_HTTP200_EMPTY_BINARY"


def test_04_nonempty_invalid_zip_is_distinct():
    assert classify_binary_diagnostic(
        http_status=200, response_byte_length=12, status=None,
        classification=None, error_type=None, valid_zip=False,
    ) == "BINARY_RESPONSE_INVALID_NONEMPTY"


def test_05_status_013_preserves_data_not_found_semantics():
    assert classify_binary_diagnostic(
        http_status=200, response_byte_length=48, status="013",
        classification="DATA_NOT_FOUND", error_type=None, valid_zip=False,
    ) == "DATA_NOT_FOUND"


def test_06_wrong_report_code_is_selection_bug():
    assert validate_filing_selection(
        selected_rcept_no="20210322000867", selected_rcept_dt="2021-03-22",
        selected_reprt_code="11013", expected_reprt_code="11011",
        requested_as_of="2021-07-02",
    ) == "RECOVERY_RUNNER_SELECTION_BUG"


def test_07_future_receipt_date_is_rejected():
    assert validate_filing_selection(
        selected_rcept_no="20210705000001", selected_rcept_dt="2021-07-05",
        selected_reprt_code="11011", expected_reprt_code="11011",
        requested_as_of="2021-07-02",
    ) == "RECOVERY_RUNNER_SELECTION_BUG"


def test_08_known_good_success_is_filing_specific_path():
    assert classify_binary_diagnostic(
        http_status=200, response_byte_length=0, status=None,
        classification="EMPTY_RESPONSE", error_type="EmptyResponse", valid_zip=False,
        known_good_success=True,
    ) == "FILING_SPECIFIC_XBRL_UNAVAILABLE"
    assert can_finalize_true_unavailable(
        selection_ok=True, retry_failed=True, known_good_success=True,
    )


def test_09_retry_success_is_transient_recovered():
    assert classify_binary_diagnostic(
        http_status=200, response_byte_length=10, status="000",
        classification="PASS", error_type=None, valid_zip=True,
        retry_succeeded=True,
    ) == "TRANSIENT_RECOVERED"


def test_10_retry_failure_does_not_hide_original_transport_failure():
    assert classify_binary_diagnostic(
        http_status=None, response_byte_length=0, status=None,
        classification="EMPTY_RESPONSE", error_type="URLError", valid_zip=False,
        retry_succeeded=False,
    ) == "OPENDART_TRANSPORT_FAILURE"


def test_11_source_unavailable_requires_all_strict_pit_checks():
    assert not can_finalize_true_unavailable(
        selection_ok=False, retry_failed=True, known_good_success=True,
    )
    assert not can_finalize_true_unavailable(
        selection_ok=True, retry_failed=False, known_good_success=True,
    )


def test_12_redacted_request_url_does_not_contain_api_key():
    from trend_scanner.fundamentals.opendart_contract import redact_url

    safe = redact_url("https://opendart.fss.or.kr/api/fnlttXbrl.xml?crtfc_key=SECRET_VALUE&rcept_no=1")
    assert "SECRET_VALUE" not in safe
    assert "%3CREDACTED%3E" in safe
