"""FIX01 authority-generation reconciliation evidence checks."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/data/end_to_end_data_parity/v01/julia_parity/v01/fix01"


def load(name: str):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_authority_generations_are_explicitly_separated():
    payload = load("authority/authority_generation_model.json")
    assert payload["legacy"]["generation"] == "JULIA_LEGACY_SPARSE_PIT_CHECKPOINT_V00"
    assert payload["legacy"]["pit_available_dates"] == 13
    assert payload["legacy"]["pit_missing_dates"] == 202
    assert payload["current"]["generation"] == "JULIA_CURRENT_PIT_CHECKPOINT_117_V01"
    assert payload["current"]["pit_available_dates"] == 117
    assert payload["current"]["pit_missing_dates"] == 98
    assert payload["mixed_generation_authority"] is False


def test_legacy_trade_files_are_unchanged():
    assert load("authority/legacy_hash_verification.json")["all_unchanged"] is True


def test_current_snapshot_is_deterministic_and_offline():
    payload = load("parity/deterministic_summary.json")
    assert payload["successful_runs"] == 2
    assert payload["julia_run_sha_match"] is True
    assert payload["baseline_run_sha_match"] is True
    assert payload["network_run1"] == payload["network_run2"] == 0
    assert payload["pass"] is True


def test_delta_is_fully_explained_by_pit_expansion():
    payload = load("delta/delta_summary.json")
    assert payload["julia"]["legacy_trades"] == 152
    assert payload["julia"]["current_trades"] == 169
    assert payload["baseline"]["legacy_trades"] == 157
    assert payload["baseline"]["current_trades"] == 194
    assert payload["unexplained_extra_trades"] == 0
    assert payload["unexplained_missing_trades"] == 0


def test_current_provenance_and_common_entry_pass():
    provenance = load("pit/source_integrity.json")
    common = load("common_entry/current_common_entry_summary.json")
    assert provenance["current_provenance_unresolved"] == 0
    assert provenance["pit_violations"] == 0
    assert provenance["proxy_usage"] == 0
    assert common["identity_mismatch_rows"] == 0


def test_005930_generation_delta_is_explicit():
    payload = load("canaries/005930_authority_generation.json")
    assert payload["legacy_entry_signal_date"] == "2023-06-30"
    assert payload["current_entry_signal_date"] == "2023-06-02"
    assert payload["classification"] == "EXPECTED_PIT_INPUT_BOUNDARY_DELTA"
    assert payload["pass"] is True


def test_governance_remains_fail_closed():
    status = load("governance/production_status.json")
    evidence = load("governance/evidence_status.json")
    suppression = load("governance/performance_suppression.json")
    assert status["julia_production_status"] == "NOT_APPROVED"
    assert status["current_default_strategy"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert evidence["final_pit_backtest_ready"] is False
    assert evidence["performance_interpretation"] == "SUPPRESSED"
    assert suppression["performance_interpretation"] == "SUPPRESSED"


def test_current_execution_snapshots_have_expected_shape():
    julia = pd.read_csv(EVIDENCE / "execution/current_julia_trades.csv", dtype={"ticker": str})
    baseline = pd.read_csv(EVIDENCE / "execution/current_baseline_trades.csv", dtype={"ticker": str})
    assert len(julia) == 169
    assert len(baseline) == 194
    assert set(julia["ticker"].astype(str).str.zfill(6))
