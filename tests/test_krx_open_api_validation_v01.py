"""Deterministic tests for the secret-safe KRX Open API validation helpers."""

from scripts.validate_krx_open_api_v01 import normalize_numeric, redact_headers


def test_normalize_numeric_handles_commas_blanks_and_decimals() -> None:
    assert normalize_numeric("1,234") == 1234
    assert normalize_numeric(" 12.50 ") == 12.5
    assert normalize_numeric("-") is None
    assert normalize_numeric(0) == 0


def test_redact_headers_never_returns_auth_key_value() -> None:
    headers = {"AUTH_KEY": "secret-value", "Accept": "application/json"}
    redacted = redact_headers(headers)
    assert redacted["AUTH_KEY"] == "<redacted>"
    assert "secret-value" not in str(redacted)
    assert redacted["Accept"] == "application/json"
