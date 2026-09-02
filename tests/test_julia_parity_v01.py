"""Offline Julia V00 behavioral parity evidence checks.

The current frozen manifest contains 117 available PIT dates, while the
historical Julia trade checkpoint was sealed before all of those dates were
usable.  These tests deliberately preserve that finding as an explicit
``CHANGES_REQUESTED`` result; they never bless the mismatch as performance or
production evidence.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "artifacts/data/end_to_end_data_parity/v01/julia_parity/v01"
JULIA_DIR = ROOT / "artifacts/strategies/julia/v00"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load(name: str):
    return json.loads((EVIDENCE / name).read_text(encoding="utf-8"))


def test_frozen_authority_manifest_is_unchanged():
    payload = _load("authority/frozen_artifact_manifest.json")
    assert payload["all_match"] is True
    assert payload["start_head"] == "449ff47d8bcf7c15fdbff9eb9af0fd9cd812b836"
    assert payload["start_tree"] == "9220e27455b59e52a4ee64c897a7bfa23115a311"
    assert all(item["git_blob_match"] for item in payload["files"].values())


def test_frozen_pit_boundary_is_preserved():
    payload = _load("checkpoint/pit_coverage.json")
    assert payload["required_dates"] == 215
    assert payload["available_dates"] == 117
    assert payload["missing_dates"] == 98
    assert payload["coverage_rate"] == 54.42
    assert payload["new_available_date_usage"] == 0
    assert payload["new_open_api_date_usage"] == 0
    assert payload["missing_date_fallback"] == 0


def test_two_offline_runs_are_deterministic():
    payload = _load("validation/deterministic_regeneration.json")
    assert payload["successful_pipeline_runs"] == 2
    assert payload["network_run1"] == payload["network_run2"] == 0
    assert payload["pass"] is True
    assert payload["julia_rerun_sha_run1"] == payload["julia_rerun_sha_run2"]
    assert payload["baseline_rerun_sha_run1"] == payload["baseline_rerun_sha_run2"]
    assert payload["julia_parity_sha_run1"] == payload["julia_parity_sha_run2"]


def test_current_execution_mismatch_is_explicit_and_not_hidden():
    payload = _load("final/closure_decision.json")
    parity = _load("parity/parity_summary.json")
    assert payload["verdict"] == "CHANGES_REQUESTED"
    assert payload["julia_parity_v01"] == payload["julia_parity"] == "OPEN"
    assert payload["next_state"] == "JULIA_PARITY_V01_FIX01"
    assert parity["julia"]["authority_trades"] == 152
    assert parity["julia"]["production_trades"] == 169
    assert parity["julia"]["extra_trades"] == 17
    assert parity["baseline"]["authority_trades"] == 157
    assert parity["baseline"]["production_trades"] == 194
    assert parity["hard_gates"]["julia_exact"] is False
    assert parity["hard_gates"]["baseline_exact"] is False


def test_loss_guard_and_governance_remain_fail_closed():
    cohort = _load("metrics/loss_guard_cohort_parity.json")
    status = _load("governance/production_status.json")
    suppression = _load("governance/performance_suppression.json")
    proxy = _load("governance/proxy_exclusion.json")
    assert cohort["julia_loss_guard_trigger_count"] == 0
    assert cohort["julia_loss_guard_exit_count"] == 0
    assert status["julia_production_status"] == "NOT_APPROVED"
    assert status["current_default_strategy"] == "PATTERN_A_FAST_FINAL_STRATEGY_V02"
    assert suppression["performance_interpretation"] == "SUPPRESSED"
    assert proxy["proxy_julia_input_usage"] == 0


def test_canary_records_capture_checkpoint_input_drift():
    canary = _load("canaries/005930.json")
    julia = pd.DataFrame(canary["julia"])
    baseline = pd.DataFrame(canary["baseline"])
    assert not julia.empty and not baseline.empty
    assert julia.iloc[0]["entry_signal_date"] == "2023-06-02"
    assert baseline.iloc[0]["entry_signal_date"] == "2023-06-02"
    assert _load("canaries/summary.json")["pass"] is False


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
