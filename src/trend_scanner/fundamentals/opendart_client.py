"""Small, redacting OpenDART HTTP client used by the fundamentals core."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from os import getenv
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .opendart_contract import redact_url


BASE_URL = "https://opendart.fss.or.kr/api"
STATUS_CLASSIFICATION = {
    "000": "PASS",
    "010": "ACCESS/AUTH",
    "011": "ACCESS/AUTH",
    "012": "ACCESS/AUTH",
    "013": "DATA_NOT_FOUND",
    "014": "REQUEST",
    "020": "RATE_LIMIT",
    "021": "RATE_LIMIT",
    "100": "REQUEST",
    "101": "REQUEST",
    "800": "SERVICE",
    "900": "SERVICE",
    "901": "SERVICE",
}


class OpenDartError(RuntimeError):
    """An explicit, non-redacted diagnostic for an HTTP/API failure."""

    def __init__(self, message: str, *, status: str | None = None, classification: str | None = None):
        super().__init__(message)
        self.status = status
        self.classification = classification


class BinaryResponseInvalid(OpenDartError):
    pass


@dataclass(frozen=True)
class JsonResponse:
    payload: dict[str, Any]
    raw: bytes
    http_status: int | None
    content_type: str | None
    request_url_redacted: str
    status: str | None
    classification: str | None


@dataclass(frozen=True)
class BinaryResponse:
    raw: bytes
    http_status: int
    content_type: str | None
    request_url_redacted: str
    status: str | None = None
    classification: str | None = None


def classify_status(status: Any) -> str | None:
    return STATUS_CLASSIFICATION.get(str(status)) if status is not None else None


def _decode_status(raw: bytes) -> tuple[str | None, str | None]:
    if not raw:
        return None, None
    try:
        value = json.loads(raw.decode("utf-8"))
        if isinstance(value, dict):
            status = str(value.get("status")) if value.get("status") is not None else None
            return status, classify_status(status)
    except (UnicodeDecodeError, json.JSONDecodeError):
        pass
    text = raw[:8192].decode("utf-8", errors="ignore")
    match = re.search(r"<status>\s*([^<]+)\s*</status>", text)
    if match:
        status = match.group(1).strip()
        return status, classify_status(status)
    return None, None


class OpenDartClient:
    """OpenDART client with injectable transport-friendly public methods.

    The key is read from ``OPENDART_API_KEY`` only.  No request URL containing
    the key is retained; ``audit`` entries always use :func:`redact_url`.
    """

    def __init__(self, api_key: str | None = None, *, base_url: str = BASE_URL, timeout: float = 30.0):
        self.api_key = (api_key if api_key is not None else getenv("OPENDART_API_KEY", "")).strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.audit: list[dict[str, Any]] = []

    def _key(self) -> str:
        if not self.api_key:
            raise OpenDartError("OPENDART_API_KEY is not configured", classification="ACCESS/AUTH")
        return self.api_key

    def _url(self, endpoint: str, params: Mapping[str, Any]) -> tuple[str, str]:
        transport = {str(k): str(v) for k, v in params.items() if v is not None}
        transport["crtfc_key"] = self._key()
        raw_url = f"{self.base_url}/{endpoint.lstrip('/')}?{urlencode(transport)}"
        return raw_url, redact_url(raw_url)

    def _record(self, **fields: Any) -> None:
        self.audit.append(fields)

    def get_json(self, endpoint: str, params: Mapping[str, Any]) -> JsonResponse:
        raw_url, safe_url = self._url(endpoint, params)
        raw = b""
        http_status: int | None = None
        content_type: str | None = None
        error_type: str | None = None
        try:
            request = Request(raw_url, headers={"Accept": "application/json"}, method="GET")
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                http_status = int(response.status)
                content_type = response.headers.get("Content-Type")
        except HTTPError as exc:
            raw = exc.read()
            http_status = int(exc.code)
            content_type = exc.headers.get("Content-Type") if exc.headers else None
            error_type = "HTTPError"
        except (URLError, TimeoutError, OSError) as exc:
            error_type = type(exc).__name__
        payload: dict[str, Any]
        try:
            value = json.loads(raw.decode("utf-8")) if raw else {}
            payload = value if isinstance(value, dict) else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
            error_type = error_type or "InvalidJSON"
        status = str(payload.get("status")) if payload.get("status") is not None else None
        classification = classify_status(status)
        self._record(
            endpoint=endpoint,
            request_url_redacted=safe_url,
            http_status=http_status,
            content_type=content_type,
            response_byte_length=len(raw),
            status=status,
            classification=classification,
            error_type=error_type,
        )
        if error_type and not raw:
            raise OpenDartError(f"OpenDART JSON request failed: {error_type}", classification="SERVICE")
        return JsonResponse(payload, raw, http_status, content_type, safe_url, status, classification)

    def get_binary(self, endpoint: str, params: Mapping[str, Any]) -> BinaryResponse:
        raw_url, safe_url = self._url(endpoint, params)
        raw = b""
        http_status: int | None = None
        content_type: str | None = None
        error_type: str | None = None
        try:
            request = Request(raw_url, headers={"Accept": "application/zip, application/octet-stream"}, method="GET")
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                http_status = int(response.status)
                content_type = response.headers.get("Content-Type")
        except HTTPError as exc:
            raw = exc.read()
            http_status = int(exc.code)
            content_type = exc.headers.get("Content-Type") if exc.headers else None
            error_type = "HTTPError"
        except (URLError, TimeoutError, OSError) as exc:
            error_type = type(exc).__name__
        status, classification = _decode_status(raw)
        if not raw:
            self._record(endpoint=endpoint, request_url_redacted=safe_url, http_status=http_status,
                         content_type=content_type, response_byte_length=0, status=status,
                         classification=classification or "EMPTY_RESPONSE", error_type=error_type or "EmptyResponse")
            raise BinaryResponseInvalid("Empty binary response", status=status, classification=classification)
        if not zipfile.is_zipfile(BytesIO(raw)):
            self._record(endpoint=endpoint, request_url_redacted=safe_url, http_status=http_status,
                         content_type=content_type, response_byte_length=len(raw), status=status,
                         classification=classification or "BINARY_RESPONSE_INVALID", error_type=error_type or "BadZipFile")
            raise BinaryResponseInvalid("HTTP response is not a valid ZIP", status=status,
                                        classification=classification or "BINARY_RESPONSE_INVALID")
        self._record(endpoint=endpoint, request_url_redacted=safe_url, http_status=http_status,
                     content_type=content_type, response_byte_length=len(raw), status=status,
                     classification="PASS" if http_status == 200 else "HTTP_ERROR_WITH_ZIP_BODY", error_type=error_type)
        if http_status != 200:
            raise OpenDartError(f"Unexpected HTTP status {http_status}", status=status, classification=classification)
        return BinaryResponse(raw, http_status, content_type, safe_url, status, "PASS")

    def corp_code(self) -> BinaryResponse:
        return self.get_binary("corpCode.xml", {})

    def list_filings(self, corp_code: str, *, bgn_de: str, end_de: str, page_no: int = 1, page_count: int = 100) -> JsonResponse:
        return self.get_json("list.json", {
            "corp_code": corp_code, "bgn_de": bgn_de, "end_de": end_de,
            "page_no": page_no, "page_count": page_count,
        })

    def financial_statements(self, corp_code: str, bsns_year: str, reprt_code: str, fs_div: str) -> JsonResponse:
        return self.get_json("fnlttSinglAcntAll.json", {
            "corp_code": corp_code, "bsns_year": bsns_year, "reprt_code": reprt_code, "fs_div": fs_div,
        })

    def xbrl(self, rcept_no: str, reprt_code: str) -> BinaryResponse:
        return self.get_binary("fnlttXbrl.xml", {"rcept_no": rcept_no, "reprt_code": reprt_code})
