"""Dedicated Unit & Diagnostic Tests for OpenDART Environment and Preflight Module.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_2 (Section 4-17, 79-81)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from trend_scanner.data.opendart_preflight import (
    OpenDARTCredentialMissingError,
    get_opendart_api_key,
    run_opendart_preflight,
)


def test_get_opendart_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENDART_API_KEY", "env_secret_key_abc123")
    assert get_opendart_api_key() == "env_secret_key_abc123"


def test_get_opendart_api_key_missing_raises_error(monkeypatch):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with patch("trend_scanner.data.opendart_preflight.load_dotenv"):
        with pytest.raises(OpenDARTCredentialMissingError) as exc_info:
            get_opendart_api_key()
        assert "OPENDART_CREDENTIAL_MISSING" in str(exc_info.value)


def test_opendart_preflight_success(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "valid_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "000", "message": "정상"}

    with patch("requests.Session.get", return_value=mock_resp):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["verdict"] == "READY"
        assert res["credential_present"] is True
        assert res["credential_value"] == "REDACTED"
        assert res["network_reachable"] is True
        assert res["authenticated_request_success"] is True
        assert res["response_identity_valid"] is True

        artifact_p = tmp_path / "opendart_preflight_v01_fix03_correction_2.json"
        assert artifact_p.exists()
        art_data = json.loads(artifact_p.read_text(encoding="utf-8"))
        assert art_data["verdict"] == "READY"
        assert art_data["credential_value"] == "REDACTED"


def test_opendart_preflight_missing_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    with patch("trend_scanner.data.opendart_preflight.load_dotenv"):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["verdict"] == "FAIL"
        assert res["credential_present"] is False
        assert res["error_reason"] == "OPENDART_CREDENTIAL_MISSING"


def test_opendart_preflight_invalid_key_error(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "bad_key")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "010", "message": "등록되지 않은 인증키입니다."}

    with patch("requests.Session.get", return_value=mock_resp):
        res = run_opendart_preflight(output_dir=tmp_path)
        assert res["verdict"] == "FAIL"
        assert "OPENDART_AUTH_FAILED" in res["error_reason"]
