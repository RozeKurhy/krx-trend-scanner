"""Tests for OpenDART API key resolution, secret scrubbing, preflight connectivity, and document readiness probe.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_7_RESUME (Section 4, 28-32)
"""

from __future__ import annotations

import os
from pathlib import Path
import pytest

from trend_scanner.data.opendart_preflight import (
    OpenDARTCredentialMissingError,
    get_opendart_api_key,
    run_document_endpoint_readiness_probe,
    run_opendart_preflight,
    sanitize_url,
)


def test_missing_api_key_raises_fail_closed_error(monkeypatch):
    """Ensure missing OPENDART_API_KEY raises a clean error."""
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    monkeypatch.setattr(Path, "exists", lambda self: False)

    with pytest.raises(OpenDARTCredentialMissingError):
        get_opendart_api_key()


def test_sanitize_url_scrubs_secret():
    """Ensure API key secret is replaced with REDACTED in query strings."""
    secret = "test_secret_key_12345"
    raw_url = f"https://opendart.fss.or.kr/api/list.json?crtfc_key={secret}&corp_code=00126380"
    sanitized = sanitize_url(raw_url, secret)

    assert secret not in sanitized
    assert "crtfc_key=REDACTED" in sanitized


def test_preflight_output_artifact_structure(tmp_path, monkeypatch):
    """Ensure preflight writes a valid schema JSON with scrubbed endpoint."""
    monkeypatch.setenv("OPENDART_API_KEY", "mock_key_abc")

    out = run_opendart_preflight(output_dir=tmp_path, allow_network=False)
    assert out["verdict"] == "READY"
    assert out["schema"] == "opendart_preflight_v01_fix03_correction_7_resume"
    assert "mock_key_abc" not in out["sanitized_endpoint"]

    p = tmp_path / "opendart_preflight_v01_fix03_correction_7_resume.json"
    assert p.exists()


def test_preflight_live_network(tmp_path):
    """Ensure live network preflight succeeds if key is provided in environment."""
    key = os.environ.get("OPENDART_API_KEY")
    if not key:
        pytest.skip("OPENDART_API_KEY not set in environment")

    out = run_opendart_preflight(output_dir=tmp_path, allow_network=True)
    assert out["verdict"] == "READY"
    assert out["http_status"] == 200
    assert out["opendart_status"] in ["000", "013"]


def test_no_synthetic_preflight_in_production(tmp_path, monkeypatch):
    """Ensure missing key produces FAIL verdict in artifact."""
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    orig_exists = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: False if self.name == ".env" else orig_exists(self))

    out = run_opendart_preflight(output_dir=tmp_path, allow_network=False)
    assert out["verdict"] == "FAIL"
    assert out["credential_resolved"] is False
    assert (tmp_path / "opendart_preflight_v01_fix03_correction_7_resume.json").exists()


def test_document_endpoint_readiness_probe_contract(tmp_path, monkeypatch):
    """Section 28-32: Document endpoint readiness probe produces valid structured artifact."""
    monkeypatch.setenv("OPENDART_API_KEY", "mock_key_abc")
    out = run_document_endpoint_readiness_probe(output_dir=tmp_path, allow_network=False)
    assert out["schema"] == "opendart_document_readiness_v01_fix03_correction_7_resume"
    assert out["verdict"] == "READY"
    assert (tmp_path / "opendart_document_readiness_v01_fix03_correction_7_resume.json").exists()
