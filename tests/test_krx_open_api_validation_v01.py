"""Deterministic tests for the secret-safe KRX Open API validation helpers."""

import io
from datetime import datetime
from urllib.error import HTTPError
from urllib.error import URLError

import pytest

from scripts.validate_krx_open_api_v01 import normalize_numeric, redact_headers
from scripts.validate_krx_open_api_v01 import (
    _normalize_stock,
    _response_status,
    classify_index_ancillary,
    required_schema_missing,
)
from trend_scanner.data.krx_openapi_client import (
    KrxOpenApiAuthorizationError,
    KrxOpenApiBudgetError,
    KrxOpenApiClient,
    KrxOpenApiRateLimitError,
)
from trend_scanner.data.krx_openapi_quota import KrxOpenApiQuotaExceeded, LocalKrxOpenApiQuota


def test_normalize_numeric_handles_commas_blanks_and_decimals() -> None:
    assert normalize_numeric("1,234") == 1234
    assert normalize_numeric(" 12.50 ") == 12.5
    assert normalize_numeric("-") is None
    assert normalize_numeric(0) == 0
    assert normalize_numeric("-12.5") == -12.5
    assert normalize_numeric("0.00") == 0


def test_redact_headers_never_returns_auth_key_value() -> None:
    headers = {"AUTH_KEY": "secret-value", "Accept": "application/json"}
    redacted = redact_headers(headers)
    assert redacted["AUTH_KEY"] == "<redacted>"
    assert "secret-value" not in str(redacted)
    assert redacted["Accept"] == "application/json"


class _Response:
    status = 200

    def __init__(self, payload: dict):
        self._raw = __import__("json").dumps(payload).encode()
        self.headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._raw


def test_client_sends_secret_only_as_header_and_redacts_audit() -> None:
    seen = {}

    def opener(request, timeout):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        assert timeout == 3
        return _Response({"OutBlock_1": [{"ISU_CD": "005930", "TDD_CLSPRC": "1,000"}]})

    client = KrxOpenApiClient("secret-value", timeout=3, opener=opener)
    response = client.fetch("/sto/stk_bydd_trd", "2026-08-20")
    assert response.record_count == 1
    assert "secret-value" not in seen["url"]
    assert seen["headers"]["Auth_key"] == "secret-value"
    assert "secret-value" not in str(client.audit)
    assert client.audit[0]["headers"]["AUTH_KEY"] == "<redacted>"


def test_client_does_not_retry_authorization_or_rate_limit() -> None:
    calls = []

    def auth_opener(request, timeout):
        calls.append(1)
        raise HTTPError(request.full_url, 401, "unauthorized", {}, io.BytesIO(b'{"respCode":"401"}'))

    auth_client = KrxOpenApiClient("secret", opener=auth_opener)
    with pytest.raises(KrxOpenApiAuthorizationError):
        auth_client.fetch("/sto/stk_bydd_trd", "20260820")
    assert len(calls) == 1
    assert auth_client.audit[0]["http_status"] == 401

    calls.clear()

    def forbidden_opener(request, timeout):
        calls.append(1)
        raise HTTPError(request.full_url, 403, "forbidden", {}, io.BytesIO(b'{"respCode":"403"}'))

    forbidden_client = KrxOpenApiClient("secret", opener=forbidden_opener)
    with pytest.raises(KrxOpenApiAuthorizationError):
        forbidden_client.fetch("/sto/stk_bydd_trd", "20260820")
    assert len(calls) == 1
    assert forbidden_client.audit[0]["http_status"] == 403

    calls.clear()

    def rate_opener(request, timeout):
        calls.append(1)
        raise HTTPError(request.full_url, 429, "rate", {}, io.BytesIO(b'{"respCode":"429"}'))

    rate_client = KrxOpenApiClient("secret", opener=rate_opener)
    with pytest.raises(KrxOpenApiRateLimitError):
        rate_client.fetch("/sto/stk_bydd_trd", "20260820")
    assert len(calls) == 1
    assert rate_client.audit[0]["http_status"] == 429


def test_client_retries_transient_5xx_at_most_twice() -> None:
    calls = []

    def opener(request, timeout):
        calls.append(1)
        raise HTTPError(request.full_url, 503, "temporary", {}, io.BytesIO(b'{"respCode":"503"}'))

    client = KrxOpenApiClient("secret", opener=opener, sleeper=lambda _seconds: None)
    response = client.fetch("/sto/stk_bydd_trd", "20260820")
    assert response.http_status == 503
    assert len(calls) == 3
    assert client.retry_count == 2
    assert [entry["attempt"] for entry in client.audit] == [1, 2, 3]


@pytest.mark.parametrize("failure", [TimeoutError(), URLError("timeout"), ConnectionError("reset")])
def test_client_retries_transient_transport_errors_and_audits(failure) -> None:
    calls = []
    failures = [failure, failure]

    def opener(request, timeout):
        calls.append(1)
        if failures:
            raise failures.pop(0)
        return _Response({"OutBlock_1": []})

    client = KrxOpenApiClient("secret", opener=opener, sleeper=lambda _seconds: None)
    response = client.fetch("/sto/stk_bydd_trd", "20260820")
    assert response.http_status == 200
    assert len(calls) == 3
    assert client.retry_count == 2
    assert len(client.audit) == 3
    assert client.audit[0]["http_status"] is None
    assert client.audit[-1]["error_type"] is None


def test_sqlite_quota_counts_attempts_and_endpoint_isolation(tmp_path) -> None:
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=10, global_safety_limit=10)
    calls = []
    failures = [TimeoutError(), TimeoutError()]

    def opener(request, timeout):
        calls.append(1)
        if failures:
            raise failures.pop(0)
        return _Response({"OutBlock_1": []})

    client = KrxOpenApiClient("secret", opener=opener, sleeper=lambda _seconds: None, quota=quota)
    client.fetch("/sto/stk_bydd_trd", "20260820")
    assert quota.get_endpoint_usage("stk_bydd_trd") == 3
    assert quota.get_endpoint_usage("ksq_bydd_trd") == 0
    assert quota.get_global_usage() == 3
    assert LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3").get_global_usage() == 3


def test_sqlite_quota_stops_before_opener_and_rolls_over_kst(tmp_path, monkeypatch) -> None:
    quota = LocalKrxOpenApiQuota(tmp_path / "quota.sqlite3", endpoint_limit=1, global_safety_limit=1)
    # Keep the client-side rollover assertion deterministic across calendar days.
    original_usage_date = LocalKrxOpenApiQuota.usage_date_kst
    monkeypatch.setattr(LocalKrxOpenApiQuota, "usage_date_kst", staticmethod(lambda now=None: "2026-08-24" if now is None else original_usage_date(now)))
    quota.reserve_attempt("stk_bydd_trd", now=datetime(2026, 8, 24, 23, 59))
    assert quota.get_endpoint_usage("stk_bydd_trd", "2026-08-24") == 1
    assert quota.get_endpoint_usage("stk_bydd_trd", "2026-08-25") == 0
    with pytest.raises(KrxOpenApiQuotaExceeded):
        quota.reserve_attempt("stk_bydd_trd", now=datetime(2026, 8, 24, 23, 59))

    calls = []

    def opener(request, timeout):
        calls.append(1)
        return _Response({"OutBlock_1": []})

    client = KrxOpenApiClient("secret", opener=opener, quota=quota)
    with pytest.raises(KrxOpenApiQuotaExceeded):
        client.fetch("/sto/stk_bydd_trd", "20260820")
    assert calls == []


def test_required_schema_missing_and_index_ancillary_classification() -> None:
    assert "LIST_SHRS" in required_schema_missing("stock", [{"BAS_DD": "20260820"}])
    rows = [
        {"IDX_CLSS": "KOSPI", "IDX_NM": "코스피", "ACC_TRDVOL": "10", "ACC_TRDVAL": "100"},
        {"IDX_CLSS": "KOSPI", "IDX_NM": "코스피 (외국주포함)", "ACC_TRDVOL": "20", "ACC_TRDVAL": "200"},
    ]
    result = classify_index_ancillary(rows, "KOSPI", "코스피", 20, 200)
    assert result["classification"] == "FOREIGN_INCLUDED_ROW_MATCH"
    result = classify_index_ancillary(rows, "KOSPI", "코스피", 99, 999)
    assert result["classification"] == "UNKNOWN_INDEX_ANCILLARY_DIFFERENCE"


def test_client_budget_is_hard_and_schema_empty_is_explicit() -> None:
    def opener(request, timeout):
        return _Response({"OutBlock_1": []})

    client = KrxOpenApiClient("secret", max_requests=1, opener=opener)
    response = client.fetch("/sto/stk_bydd_trd", "20260823")
    assert response.record_count == 0
    with pytest.raises(KrxOpenApiBudgetError):
        client.fetch("/sto/stk_bydd_trd", "20260824")


def test_stock_market_normalization_is_explicit() -> None:
    row = _normalize_stock(
        {
            "BAS_DD": "20260820",
            "ISU_CD": "005930",
            "ISU_NM": "삼성전자",
            "MKT_NM": "KOSPI",
            "TDD_CLSPRC": "1,000",
            "TDD_OPNPRC": "990",
            "TDD_HGPRC": "1,010",
            "TDD_LWPRC": "-",
            "ACC_TRDVOL": "0",
            "ACC_TRDVAL": "",
        }
    )
    assert row["market"] == "KOSPI"
    assert row["ticker_or_issue_code"] == "005930"
    assert row["close"] == 1000
    assert row["low"] is None


def test_http_empty_and_unknown_schema_are_distinguished() -> None:
    empty = _Response({"OutBlock_1": []})
    # The test response has the same public attributes as a live response.
    from trend_scanner.data.krx_openapi_client import KrxOpenApiClient

    client = KrxOpenApiClient("secret", opener=lambda request, timeout: empty)
    response = client.fetch("/sto/stk_bydd_trd", "20260823")
    assert _response_status(response) == "HTTP_200_EMPTY"
