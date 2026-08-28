"""OpenDART Credential Loader, Diagnostic Preflight, and Environment Hard Gate.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01_FIX03_CORRECTION_4 (Section 4-5)
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any
import requests
from dotenv import load_dotenv


class OpenDARTCredentialMissingError(RuntimeError):
    """Raised when OPENDART_API_KEY is not available in environment or project .env."""
    pass


def get_opendart_api_key() -> str:
    """Load OpenDART API key securely via central project dotenv / environment without logging secret."""
    load_dotenv()
    key = os.environ.get("OPENDART_API_KEY", "").strip()
    if not key:
        raise OpenDARTCredentialMissingError(
            "OPENDART_CREDENTIAL_MISSING: OPENDART_API_KEY environment variable is not set. "
            "Please set OPENDART_API_KEY in your environment or repo-root .env file."
        )
    return key


def run_opendart_preflight(
    output_dir: Path | None = None,
    allow_network: bool = True,
    timeout: float = 5.0,
    canonical_run_id: str = "",
) -> dict[str, Any]:
    """Execute preflight checks before canonical corporate authority evidence acquisition.

    Checks:
    1. Credential available via central environment
    2. Endpoint reachable
    3. Small authenticated request succeeds
    4. OpenDART status in response payload is '000' (OK) or '013' (Authenticated No Data)
    5. Correct OpenDART 013 vs 000 semantics (Section 5)
    """
    preflight_result: dict[str, Any] = {
        "schema": "opendart_preflight_v01_fix03_correction_4",
        "canonical_run_id": canonical_run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "credential_present": False,
        "credential_source": "PROJECT_ENVIRONMENT_OR_DOTENV",
        "credential_value": "REDACTED",
        "network_reachable": False,
        "authentication_valid": False,
        "probe_response_status": "",
        "opendart_status": "",
        "opendart_message": "",
        "response_identity_status": "UNCHECKED",
        "verdict": "FAIL",
        "error_reason": "",
    }

    try:
        key = get_opendart_api_key()
        preflight_result["credential_present"] = True
    except OpenDARTCredentialMissingError as exc:
        preflight_result["error_reason"] = "OPENDART_CREDENTIAL_MISSING"
        if output_dir:
            output_dir.mkdir(parents=True, exist_ok=True)
            p = output_dir / "opendart_preflight_v01_fix03_correction_4.json"
            p.write_text(json.dumps(preflight_result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return preflight_result

    if not allow_network:
        preflight_result["error_reason"] = "NETWORK_DISABLED"
        return preflight_result

    # Bounded authenticated probe query (Samsung Electronics, 5-day range, 1 row)
    probe_url = "https://opendart.fss.or.kr/api/list.json"
    probe_params = {
        "crtfc_key": key,
        "corp_code": "00126380",
        "bgn_de": "20240101",
        "end_de": "20240105",
        "page_count": "1",
    }

    session = requests.Session()
    session.headers.update({"User-Agent": "TrendScanner/1.0 OpenDARTPreflight"})

    try:
        resp = session.get(probe_url, params=probe_params, timeout=timeout)
        preflight_result["network_reachable"] = True
        if resp.status_code == 200:
            data = resp.json()
            status_code = data.get("status", "")
            msg = data.get("message", "")
            preflight_result["opendart_status"] = status_code
            preflight_result["opendart_message"] = msg

            if status_code == "000":
                preflight_result["authentication_valid"] = True
                preflight_result["probe_response_status"] = "AUTHENTICATED_WITH_DATA"
                preflight_result["response_identity_status"] = "VALID"
                preflight_result["verdict"] = "READY"
            elif status_code == "013":
                preflight_result["authentication_valid"] = True
                preflight_result["probe_response_status"] = "AUTHENTICATED_NO_DATA"
                preflight_result["response_identity_status"] = "NOT_APPLICABLE"
                preflight_result["verdict"] = "READY"
            elif status_code == "010":
                preflight_result["error_reason"] = "OPENDART_AUTH_FAILED: Invalid API Key"
            elif status_code == "020":
                preflight_result["error_reason"] = "OPENDART_API_RATE_LIMIT_EXCEEDED"
            else:
                preflight_result["error_reason"] = f"OPENDART_API_ERROR: status={status_code}, msg={msg}"
        else:
            preflight_result["error_reason"] = f"OPENDART_HTTP_ERROR: {resp.status_code}"
    except requests.exceptions.RequestException as exc:
        preflight_result["network_reachable"] = False
        preflight_result["error_reason"] = f"OPENDART_NETWORK_UNREACHABLE: {type(exc).__name__}"

    if output_dir:
        output_dir.mkdir(parents=True, exist_ok=True)
        p = output_dir / "opendart_preflight_v01_fix03_correction_4.json"
        p.write_text(json.dumps(preflight_result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return preflight_result


if __name__ == "__main__":
    res = run_opendart_preflight()
    print("=== OpenDART Preflight Result ===")
    print("Credential Present:", res["credential_present"])
    print("Network Reachable:", res["network_reachable"])
    print("Auth Valid:", res["authentication_valid"])
    print("Probe Status:", res["probe_response_status"])
    print("OpenDART Status:", res["opendart_status"])
    print("Verdict:", res["verdict"])
    if res["error_reason"]:
        print("Error Reason:", res["error_reason"])
