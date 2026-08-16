"""Integration and Parity Verification Tests for Phase 10C Downstream Integration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.filters.investability import InvestabilityStatus
from trend_scanner.patterns.pattern_a_evaluator import PatternACandidateState
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.pattern_a_investability_integration import (
    run_investability_integration_validation,
    CANONICAL_AS_OF,
    EXPECTED_RAW_CANDIDATES,
    EXPECTED_TRANSITION_COUNT,
    EXPECTED_EARLY_COUNT,
    EXPECTED_INVESTABLE_COUNT,
    EXPECTED_UNAVAILABLE_TICKERS,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/investability"


@pytest.fixture(scope="module")
def integration_summary() -> dict:
    """Load or execute Phase 10C downstream integration validation summary."""
    summary_path = _ARTIFACTS_DIR / "pattern_a_investability_integration_summary_20260814.json"
    if summary_path.exists():
        return json.loads(summary_path.read_text(encoding="utf-8"))
    return run_investability_integration_validation(_REPO_ROOT)


def test_raw_candidate_preservation(integration_summary: dict):
    """Gate 1 & 2: Verify Pattern A candidate detection is 100% unmutated (180 candidates)."""
    assert integration_summary["candidate_count"] == EXPECTED_RAW_CANDIDATES
    assert integration_summary["transition_count"] == EXPECTED_TRANSITION_COUNT
    assert integration_summary["early_count"] == EXPECTED_EARLY_COUNT
    assert integration_summary["hard_gates"]["gate_01_frozen_pattern_a_identity_pass"] is True
    assert integration_summary["hard_gates"]["gate_02_raw_candidate_preservation_pass"] is True


def test_ticker_level_parity_with_phase10b(integration_summary: dict):
    """Gate 5: Verify 1:1 ticker-level status parity with Phase 10B canonical oracle."""
    assert integration_summary["parity_mismatches_count"] == 0
    assert len(integration_summary["parity_mismatches"]) == 0
    assert integration_summary["hard_gates"]["gate_05_ticker_level_phase10b_parity_pass"] is True


def test_investability_status_breakdown(integration_summary: dict):
    """Verify exact breakdown of 180 raw candidates across investability statuses."""
    bd = integration_summary["investability_breakdown"]
    assert bd["investable_count"] == EXPECTED_INVESTABLE_COUNT  # 103
    assert bd["filtered_market_cap_count"] == 42
    assert bd["filtered_liquidity_count"] == 31
    assert bd["data_unavailable_count"] == 4
    total = bd["investable_count"] + bd["filtered_market_cap_count"] + bd["filtered_liquidity_count"] + bd["data_unavailable_count"]
    assert total == EXPECTED_RAW_CANDIDATES


def test_regression_specific_tickers():
    """Verify specific regression tickers have exact expected candidate and investability states."""
    comp_csv = _ARTIFACTS_DIR / "pattern_a_investability_integration_20260814.csv"
    assert comp_csv.exists()
    df = pd.read_csv(comp_csv, dtype={"ticker": str})

    expected_cases = {
        "086060": {"stage": "early_trend", "cand": "candidate", "status": "FILTERED_MARKET_CAP"},
        "033560": {"stage": "early_trend", "cand": "candidate", "status": "FILTERED_MARKET_CAP"},
        "003800": {"stage": "transition", "cand": "candidate", "status": "FILTERED_LIQUIDITY"},
        "001540": {"stage": "early_trend", "cand": "candidate", "status": "INVESTABLE"},
        "003650": {"stage": "early_trend", "cand": "candidate", "status": "INVESTABLE"},
        "034950": {"stage": "transition", "cand": "candidate", "status": "FILTERED_LIQUIDITY"},
    }

    for t, exp in expected_cases.items():
        row = df[df["ticker"] == t]
        assert not row.empty, f"Ticker {t} not found in candidate integration output"
        r = row.iloc[0]
        assert r["official_stage"] == exp["stage"]
        assert r["candidate_state"] == exp["cand"]
        assert r["investability_status"] == exp["status"]


def test_missing_fail_closed_tickers():
    """Gate 6: Verify 4 stale/halted tickers are categorized as DATA_UNAVAILABLE."""
    comp_csv = _ARTIFACTS_DIR / "pattern_a_investability_integration_20260814.csv"
    df = pd.read_csv(comp_csv, dtype={"ticker": str})

    for t in EXPECTED_UNAVAILABLE_TICKERS:
        row = df[df["ticker"] == t]
        assert not row.empty
        assert row.iloc[0]["investability_status"] == InvestabilityStatus.DATA_UNAVAILABLE.value


def test_integration_hard_gates_all_pass(integration_summary: dict):
    """Gate 8 & Final: Verify all 8 dynamic integration gates PASS and status is INTEGRATION_READY."""
    gates = integration_summary["hard_gates"]
    assert len(gates) == 8
    for g_name, g_pass in gates.items():
        assert g_pass is True, f"Gate {g_name} failed!"
    assert integration_summary["phase_10c_status"] == "INTEGRATION_READY"
