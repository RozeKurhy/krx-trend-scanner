"""Tests for OpenDART API environment resolution, secret scrubbing, and connectivity preflight.

Directives:
- ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_5 (Section 4)
"""

import json
import os
from pathlib import Path
import pytest

from trend_scanner.data.opendart_preflight import (
    OpenDARTCredentialMissingError,
    get_opendart_api_key,
    load_local_dotenv_if_present,
    run_opendart_preflight,
    sanitize_url,
)


def test_missing_credential_raises_explicit_error(monkeypatch):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(OpenDARTCredentialMissingError):
        get_opendart_api_key()


def test_preflight_verdict_fail_when_credential_missing(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    monkeypatch.setattr(Path, "exists", lambda self: False)
    res = run_opendart_preflight(output_dir=tmp_path, allow_network=False)
    assert res["verdict"] == "FAIL"
    assert res["credential_resolved"] is False


def test_secret_scrubbed_from_sanitized_endpoint():
    raw_url = "https://opendart.fss.or.kr/api/list.json?crtfc_key=MY_SECRET_KEY_123&corp_code=00126380"
    sanitized = sanitize_url(raw_url, "MY_SECRET_KEY_123")
    assert "MY_SECRET_KEY_123" not in sanitized
    assert "REDACTED" in sanitized


def test_offline_preflight_ready_when_credential_present(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENDART_API_KEY", "TEST_KEY_DUMMY")
    res = run_opendart_preflight(output_dir=tmp_path, allow_network=False)
    assert res["verdict"] == "READY"
    assert res["credential_resolved"] is True
    assert res["live_ping_success"] is True


def test_live_ping_against_opendart_if_key_available(tmp_path):
    key = os.environ.get("OPENDART_API_KEY")
    if not key:
        pytest.skip("OPENDART_API_KEY not in environment for live ping")
    res = run_opendart_preflight(output_dir=tmp_path, allow_network=True)
    assert res["verdict"] == "READY"
    assert res["credential_resolved"] is True
    assert res["http_status"] == 200
    assert res["opendart_status"] in ["000", "013"]


def test_preflight_artifact_created_with_expected_schema(tmp_path):
    key = os.environ.get("OPENDART_API_KEY", "TEST_KEY")
    res = run_opendart_preflight(output_dir=tmp_path, allow_network=False)
    af = tmp_path / "opendart_preflight_v01_fix03_correction_5.json"
    assert af.exists()
    data = json.loads(af.read_text(encoding="utf-8"))
    assert data["schema"] == "opendart_preflight_v01_fix03_correction_5"
    assert data["verdict"] == "READY"
