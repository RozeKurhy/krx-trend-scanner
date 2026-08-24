"""Secret-safe, production-neutral transport for the KRX Data Marketplace Open API.

This module deliberately stops at authenticated HTTP and schema-safe JSON
reading.  It is not a ``MarketDataProvider`` and is not imported by the
production PyKRX repository path.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from trend_scanner.data.krx_openapi_quota import LocalKrxOpenApiQuota


DEFAULT_BASE_URL = "https://data-dbg.krx.co.kr/svc/apis"
DEFAULT_AUTH_HEADER = "AUTH_KEY"
DEFAULT_DATE_PARAMETER = "basDd"
DEFAULT_MAX_REQUESTS = 80
DEFAULT_MAX_TRANSIENT_RETRIES = 2


class KrxOpenApiError(RuntimeError):
    """Base error for transport and response-contract failures."""


class KrxOpenApiAuthorizationError(KrxOpenApiError):
    """The service rejected the supplied credentials (401/403)."""


class KrxOpenApiRateLimitError(KrxOpenApiError):
    """The service returned 429; validation must stop without retrying."""


class KrxOpenApiBudgetError(KrxOpenApiError):
    """The bounded validation request budget was exhausted."""


class KrxOpenApiSchemaError(KrxOpenApiError):
    """The response is not a JSON object with the expected record shape."""


@dataclass(frozen=True)
class KrxOpenApiResponse:
    """Redaction-safe response information used by validators and audit logs."""

    url: str
    http_status: int | None
    payload: dict[str, Any]
    top_level_keys: tuple[str, ...]
    records_key: str | None
    records: tuple[dict[str, Any], ...]
    elapsed_ms: int
    attempt: int
    error_type: str | None = None
    error_message: str | None = None
    headers: Mapping[str, str] = field(default_factory=dict)

    @property
    def record_count(self) -> int:
        return len(self.records)


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return an audit representation that never contains an auth value."""

    secret_names = {"AUTH_KEY", "AUTHORIZATION", "COOKIE", "SET-COOKIE"}
    return {
        str(name): "<redacted>" if str(name).upper() in secret_names else str(value)
        for name, value in headers.items()
    }


def _parse_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _find_records(payload: Mapping[str, Any]) -> tuple[str | None, tuple[dict[str, Any], ...]]:
    """Find a list-of-object records container without silently coercing values."""

    candidates: list[tuple[str, tuple[dict[str, Any], ...]]] = []
    for key, value in payload.items():
        if not isinstance(value, list):
            continue
        if all(isinstance(row, dict) for row in value):
            candidates.append((str(key), tuple(value)))
    if not candidates:
        return None, ()
    # Prefer the conventional KRX container; otherwise require deterministic
    # choice by taking the largest list (the API can expose metadata lists).
    candidates.sort(key=lambda item: (item[0] != "OutBlock_1", -len(item[1]), item[0]))
    return candidates[0]


class KrxOpenApiClient:
    """Bounded KRX Open API client with header-only authentication."""

    def __init__(
        self,
        auth_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        auth_header: str = DEFAULT_AUTH_HEADER,
        max_requests: int = DEFAULT_MAX_REQUESTS,
        max_transient_retries: int = DEFAULT_MAX_TRANSIENT_RETRIES,
        timeout: float = 30.0,
        opener: Callable[..., Any] = urlopen,
        sleeper: Callable[[float], None] = time.sleep,
        quota: LocalKrxOpenApiQuota | None = None,
    ) -> None:
        if not auth_key or not auth_key.strip():
            raise ValueError("KRX Open API auth key is required")
        if max_requests < 1:
            raise ValueError("max_requests must be positive")
        if max_transient_retries < 0 or max_transient_retries > 2:
            raise ValueError("max_transient_retries must be between 0 and 2")
        self._auth_key = auth_key.strip()
        self.base_url = base_url.rstrip("/")
        self.auth_header = auth_header
        self.max_requests = max_requests
        self.max_transient_retries = max_transient_retries
        self.timeout = timeout
        self._opener = opener
        self._sleeper = sleeper
        self.quota = quota
        self.request_count = 0
        self.retry_count = 0
        self.status_counts: dict[str, int] = {"401": 0, "403": 0, "429": 0, "5xx": 0, "transport_error": 0}
        self.audit: list[dict[str, Any]] = []

    @property
    def auth_key_present(self) -> bool:
        return bool(self._auth_key)

    def fetch(
        self,
        endpoint_path: str,
        date: str,
        *,
        date_parameter: str = DEFAULT_DATE_PARAMETER,
        extra_params: Mapping[str, str] | None = None,
        quota_endpoint_key: str | None = None,
    ) -> KrxOpenApiResponse:
        """Fetch one date snapshot; the secret is sent only as an HTTP header."""

        if not endpoint_path.startswith("/"):
            endpoint_path = "/" + endpoint_path
        params = {date_parameter: date.replace("-", "")}
        if extra_params:
            params.update({str(k): str(v) for k, v in extra_params.items()})
        url = f"{self.base_url}{endpoint_path}?{urlencode(params)}"
        headers = {self.auth_header: self._auth_key, "Accept": "application/json"}
        endpoint_key = (quota_endpoint_key or endpoint_path).strip("/").split("/")[-1]
        last: KrxOpenApiResponse | None = None
        transient_seen = 0

        while True:
            if self.request_count >= self.max_requests:
                raise KrxOpenApiBudgetError(f"KRX Open API request budget exhausted ({self.max_requests})")
            quota_info = self.quota.reserve_attempt(endpoint_key) if self.quota is not None else None
            self.request_count += 1
            attempt = transient_seen + 1
            started = monotonic()
            try:
                request = Request(url, headers=headers, method="GET")
                with self._opener(request, timeout=self.timeout) as response:
                    raw = response.read()
                    status = int(response.status)
                    response_headers = dict(response.headers.items()) if response.headers else {}
                payload = _parse_json(raw)
                response_obj = self._make_response(
                    url, status, payload, started, attempt, response_headers
                )
            except HTTPError as exc:
                raw = exc.read()
                payload = _parse_json(raw)
                response_obj = self._make_response(
                    url, int(exc.code), payload, started, attempt, dict(exc.headers.items()) if exc.headers else {}
                )
            except (URLError, TimeoutError, OSError) as exc:
                self.status_counts["transport_error"] += 1
                response_obj = KrxOpenApiResponse(
                    url=url,
                    http_status=None,
                    payload={},
                    top_level_keys=(),
                    records_key=None,
                    records=(),
                    elapsed_ms=int((monotonic() - started) * 1000),
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    error_message=type(exc).__name__,
                )
            last = response_obj
            self.audit.append(
                {
                    "url": f"{self.base_url}{endpoint_path}",
                    "date": date.replace("-", ""),
                    "attempt": last.attempt,
                    "http_status": last.http_status,
                    "elapsed_ms": last.elapsed_ms,
                    "record_count": last.record_count,
                    "top_level_keys": list(last.top_level_keys),
                    "headers": redact_headers({self.auth_header: "<present>"}),
                    "endpoint_key": endpoint_key,
                    "error_type": last.error_type,
                    "quota_usage_date_kst": quota_info.get("usage_date_kst") if quota_info else None,
                    "quota_endpoint_before": quota_info.get("quota_endpoint_before") if quota_info else None,
                    "quota_endpoint_after": quota_info.get("quota_endpoint_after") if quota_info else None,
                    "quota_global_before": quota_info.get("quota_global_before") if quota_info else None,
                    "quota_global_after": quota_info.get("quota_global_after") if quota_info else None,
                }
            )
            status = response_obj.http_status
            if status == 401:
                self.status_counts["401"] += 1
                raise KrxOpenApiAuthorizationError("KRX Open API returned HTTP 401")
            if status == 403:
                self.status_counts["403"] += 1
                raise KrxOpenApiAuthorizationError("KRX Open API returned HTTP 403")
            if status == 429:
                self.status_counts["429"] += 1
                raise KrxOpenApiRateLimitError("KRX Open API returned HTTP 429")
            if status is not None and 500 <= status <= 599:
                self.status_counts["5xx"] += 1
                if transient_seen < self.max_transient_retries:
                    transient_seen += 1
                    self.retry_count += 1
                    self._sleeper(min(2**transient_seen, 4))
                    continue
            if status is None and response_obj.error_type is not None and transient_seen < self.max_transient_retries:
                transient_seen += 1
                self.retry_count += 1
                self._sleeper(min(2**transient_seen, 4))
                continue
            break

        assert last is not None
        return last

    @staticmethod
    def _make_response(
        url: str,
        status: int,
        payload: dict[str, Any],
        started: float,
        attempt: int,
        headers: Mapping[str, str],
    ) -> KrxOpenApiResponse:
        records_key, records = _find_records(payload)
        return KrxOpenApiResponse(
            url=url,
            http_status=status,
            payload=payload,
            top_level_keys=tuple(sorted(payload)),
            records_key=records_key,
            records=records,
            elapsed_ms=int((monotonic() - started) * 1000),
            attempt=attempt,
            error_type=None,
            error_message=None,
            headers=redact_headers(headers),
        )
