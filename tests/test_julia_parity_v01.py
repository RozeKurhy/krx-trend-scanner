"""Offline Julia V00 parity checks against the accepted v01/fix01 authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/data/end_to_end_data_parity/v01/julia_parity/v01/fix01"
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name: str):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_frozen_authority_manifest_is_unchanged():
    payload = _load("authority/legacy_hash_verification.json")
    assert payload["all_unchanged"] is True
    for item in payload["files"].values():
        path = ROOT / item["path"]
        assert item["sha256_match"] is True
        assert _sha256(path) == item["after_sha256"]


def test_frozen_pit_boundary_is_preserved():
    payload = _load("pit/current_manifest_partition.json")
    classification = _load("authority/current_checkpoint_classification.json")
    assert payload["available_dates"] + payload["missing_dates"] == payload["required_dates"]
    assert payload["coverage_rate"] == classification["pit_coverage"]
    assert classification["pit_available_dates"] == payload["available_dates"]
    assert classification["pit_missing_dates"] == payload["missing_dates"]
    assert payload["krx_open_api_dates"] == payload["missing_date_recovery"] == 0
    assert classification["production_approved"] is False
    assert classification["performance_authoritative"] is False


def test_two_offline_runs_are_deterministic():
    payload = _load("parity/deterministic_summary.json")
    assert payload["successful_runs"] == 2
    assert payload["network_run1"] == payload["network_run2"] == 0
    assert payload["pass"] is True
    assert payload["julia_run_sha_match"] is True
    assert payload["baseline_run_sha_match"] is True
    assert payload["julia_sha_run1"] == payload["julia_sha_run2"]
    assert payload["baseline_sha_run1"] == payload["baseline_sha_run2"]
    assert payload["julia_run1_run2"]["missing_trades"] == payload["julia_run1_run2"]["extra_trades"] == 0
    assert payload["baseline_run1_run2"]["missing_trades"] == payload["baseline_run1_run2"]["extra_trades"] == 0


def test_current_execution_delta_is_explicit_and_fully_explained():
    closure = _load("final/closure_decision.json")
    delta = _load("delta/delta_summary.json")
    assert closure["verdict"] == "ACCEPT"
    assert closure["julia_parity_v01_fix01"] == closure["julia_parity"] == "CLOSED"
    assert delta["julia"]["legacy_trades"] + delta["julia"]["current_extra_trade_keys"] == delta["julia"]["current_trades"]
    assert delta["baseline"]["legacy_trades"] + delta["baseline"]["current_extra_trade_keys"] == delta["baseline"]["current_trades"]
    assert delta["julia"]["fully_explained"] is True
    assert delta["baseline"]["fully_explained"] is True
    assert delta["unexplained_extra_trades"] == delta["unexplained_missing_trades"] == 0


def test_loss_guard_and_governance_remain_fail_closed():
    closure = _load("final/closure_decision.json")
    status = _load("governance/production_status.json")
    suppression = _load("governance/performance_suppression.json")
    provenance = _load("pit/source_integrity.json")
    assert closure["hard_gates"]["loss_guard_isolation"] is True
    assert status["julia_production_status"] == "NOT_APPROVED"
    assert status["current_default_strategy"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert suppression["performance_interpretation"] == "SUPPRESSED"
    assert provenance["proxy_usage"] == 0


def test_canary_records_capture_checkpoint_input_drift():
    canary = _load("canaries/005930_authority_generation.json")
    current = _load("canaries/005930.json")
    julia = pd.DataFrame(current["julia"])
    baseline = pd.DataFrame(current["baseline"])
    assert canary["pass"] is True
    assert not julia.empty and not baseline.empty
    assert canary["classification"] == "EXPECTED_PIT_INPUT_BOUNDARY_DELTA"
    assert canary["legacy_entry_signal_date"] != canary["current_entry_signal_date"]
    assert canary["baseline_current_entry_signal_date"] == canary["current_entry_signal_date"]


def test_frozen_files_remain_byte_identical_after_parity_run():
    expected = {
        "julia_v00_2022_trades.csv": "a3d4abdd376b8830fdb2b00c2f74bf4408b1ab98",
        "baseline_a_fast_core_v2_2022_trades.csv": "bb4912af9f7fd92a2ec20b9ce30804f4eff0ce39",
        "contract.json": "e82ac4145ebd3f491184a23b3920657d3b406363",
        "strategy_comparison_summary.json": "cc27310ead9a4048c530e53aa0966d511ee7b347",
        "historical_market_cap_source_manifest.csv": "8d598254ff578388d783ae0a306b2d0b9366fb40",
        "historical_investability_pit_audit.json": "a6cb05557e786e87f56339e4c7cac6d04d8ae9ae",
        "common_entry_pairs.csv": "863b2b9363288957ce3878cf81cef85a1a1b394a",
    }
    import subprocess

    for name, blob in expected.items():
        actual = subprocess.run(["git", "hash-object", str(JULIA_DIR / name)], check=True, capture_output=True, text=True).stdout.strip()
        assert actual == blob
