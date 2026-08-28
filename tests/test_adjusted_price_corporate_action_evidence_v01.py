"""Unit and regression tests for Corporate Action Authority Evidence Acquisition and Gate 06.

Directive: ADJUSTED_PRICE_SOURCE_AUTHORITY_CORPORATE_ACTION_EVIDENCE_V01 (Section 50-54)
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_provider import normalize_ticker
from trend_scanner.data.corporate_action_authority import (
    DEFAULT_CORP_EVIDENCE_DIR,
    PARENT_FIX03_CORRECTION_DIR,
    START_HEAD_CORP_EVIDENCE,
    AuthoritySourceTier,
    ClaimAdjudicationStatus,
    CorporateActionNetworkAccounting,
    get_official_evidence_definitions,
    run_corporate_action_evidence_acquisition,
    verify_parent_authority_freeze,
)


def test_parent_authority_freeze_validation():
    res = verify_parent_authority_freeze()
    assert res["all_parent_inputs_unchanged"] is True
    assert res["parent_artifacts_verified_count"] == 8
    assert len(res["mismatches"]) == 0


def test_official_evidence_definitions_count_and_diversity():
    defs = get_official_evidence_definitions()
    assert len(defs) >= 8

    tickers = {d["ticker"] for d in defs}
    assert len(tickers) >= 8

    event_types = {d["normalized_event_type"] for d in defs}
    assert "STOCK_SPLIT" in event_types
    assert "MERGER" in event_types
    assert "RIGHTS_OFFERING" in event_types
    assert "BONUS_ISSUE" in event_types


def test_raw_evidence_manifest_hashes_match():
    manifest_p = DEFAULT_CORP_EVIDENCE_DIR / "corporate_action_raw_evidence_manifest_v01.json"
    assert manifest_p.exists()

    data = json.loads(manifest_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 8

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Raw snapshot file {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"Raw SHA mismatch for {fname}"


def test_event_sensitive_parity_artifact_all_match():
    parity_p = DEFAULT_CORP_EVIDENCE_DIR / "corporate_action_event_sensitive_parity_v01.csv"
    assert parity_p.exists()

    df = pd.read_csv(parity_p, dtype={"ticker": str})
    assert len(df) >= 8
    assert (df["parity_status"] == "MATCH").all()
    assert (df["open_mismatch_count"] == 0).all()
    assert (df["high_mismatch_count"] == 0).all()
    assert (df["low_mismatch_count"] == 0).all()
    assert (df["close_mismatch_count"] == 0).all()
    assert (df["overlap_rows"] > 0).all()


def test_gate_06_reassessment_passed():
    gate06_p = DEFAULT_CORP_EVIDENCE_DIR / "gate06_corporate_action_reassessment_v01.json"
    assert gate06_p.exists()

    data = json.loads(gate06_p.read_text(encoding="utf-8"))
    assert data["gate_06_pass"] is True
    assert data["authority_valid_controls_count"] >= 8
    assert data["event_type_diversity_satisfied"] is True
    assert len(data["gate_06_blockers"]) == 0


def test_final_formal_decision_approved_for_production():
    dec_p = DEFAULT_CORP_EVIDENCE_DIR / "adjusted_price_source_authority_corporate_action_evidence_v01.json"
    assert dec_p.exists()

    data = json.loads(dec_p.read_text(encoding="utf-8"))
    assert data["review_decision"] == "APPROVED_FOR_PRODUCTION_INTEGRATION"
    assert data["production_integration_authorized"] is True
    assert data["active_production_authority_changed"] is False
    assert data["recommended_next_state"] == "ADJUSTED_PRICE_SOURCE_INTEGRATION_V01"
    assert data["all_gates_passed"] is True
    assert all(data["gate_results"].values())


def test_corporate_action_evidence_manifest_integrity():
    man_p = DEFAULT_CORP_EVIDENCE_DIR / "artifact_manifest.json"
    assert man_p.exists()

    data = json.loads(man_p.read_text(encoding="utf-8"))
    artifacts = data.get("artifacts", {})
    assert len(artifacts) >= 10

    for fname, meta in artifacts.items():
        fp = Path(meta["path"])
        assert fp.exists(), f"Artifact {fp} missing on disk"
        actual_sha = hashlib.sha256(fp.read_bytes()).hexdigest()
        assert actual_sha == meta["sha256"], f"SHA mismatch for {fname}"


def test_shuffled_evidence_pool_invariance():
    defs1 = get_official_evidence_definitions()
    defs2 = list(reversed(defs1))

    tickers1 = sorted(d["ticker"] for d in defs1)
    tickers2 = sorted(d["ticker"] for d in defs2)
    assert tickers1 == tickers2


def test_network_accounting_redacted_secrets():
    net_p = DEFAULT_CORP_EVIDENCE_DIR / "corporate_action_evidence_network_accounting_v01.json"
    assert net_p.exists()

    raw_text = net_p.read_text(encoding="utf-8")
    assert "crtfc_key" not in raw_text
    assert "Authorization" not in raw_text
    assert "secret" not in raw_text.lower()
