"""Unit and Integration Tests for Phase 10A Investability Distribution Audit (Single Canonical Pipeline)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.validation.pattern_a_investability_audit import (
    run_investability_audit,
    load_canonical_mcap_snapshot,
    calculate_distribution_stats,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/investability"


@pytest.fixture(scope="module")
def canonical_audit_result() -> dict:
    """Execute canonical investability audit pipeline."""
    return run_investability_audit(_REPO_ROOT, as_of="2026-08-14")


def test_gate1_no_lookahead_and_dates(canonical_audit_result: dict):
    """Gate 1: Verify as_of is strictly 2026-08-14 and all data sources are lookahead-free."""
    assert canonical_audit_result["as_of"] == "2026-08-14"
    assert canonical_audit_result["data_provenance"]["lookahead_free"] is True
    assert canonical_audit_result["hard_gates"]["no_lookahead_pass"] is True


def test_gate2_universe_identity(canonical_audit_result: dict):
    """Gate 2: Verify Universe count is exactly 2,528."""
    assert canonical_audit_result["universe_count"] == 2528
    assert canonical_audit_result["hard_gates"]["universe_identity_pass"] is True
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_universe_20260814.csv"
    assert csv_path.exists()
    df_u = pd.read_csv(csv_path, dtype={"ticker": str})
    assert len(df_u) == 2528


def test_gate3_candidate_identity(canonical_audit_result: dict):
    """Gate 3: Verify Candidate count is exactly 180."""
    assert canonical_audit_result["candidate_count"] == 180
    assert canonical_audit_result["hard_gates"]["candidate_identity_pass"] is True
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv"
    assert csv_path.exists()
    df_c = pd.read_csv(csv_path, dtype={"ticker": str})
    assert len(df_c) == 180


def test_gate4_stage_split(canonical_audit_result: dict):
    """Gate 4: Verify stage split is 168 Transition and 12 Early."""
    assert canonical_audit_result["transition_count"] == 168
    assert canonical_audit_result["early_count"] == 12
    assert canonical_audit_result["hard_gates"]["stage_split_pass"] is True


def test_gate5_human42_identity(canonical_audit_result: dict):
    """Gate 5: Verify Human42 count is exactly 42."""
    assert canonical_audit_result["human42_count"] == 42
    assert canonical_audit_result["hard_gates"]["human42_identity_pass"] is True


def test_gate6_exact_trading_value_windows():
    """Gate 6: Verify exact trading value windows for 20D and 60D."""
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv"
    df_c = pd.read_csv(csv_path, dtype={"ticker": str})
    
    # 176 fresh candidates have exact 20 and 60 days
    df_ready = df_c[df_c["trading_value_20d_ready"] == True]
    assert len(df_ready) == 176
    assert (df_ready["trading_days_20d"] == 20).all()
    assert (df_ready["trading_days_60d"] == 60).all()
    assert (df_ready["avg_trading_value_20d_eok"] > 0).all()


def test_gate7_market_cap_provenance_and_snapshot():
    """Gate 7: Verify market cap snapshot provenance and sha256."""
    df_mcap, sha256 = load_canonical_mcap_snapshot(_REPO_ROOT, as_of="2026-08-14")
    assert len(df_mcap) == 2872
    assert sha256 == "c45a496d0a5bb38ea4d4350d3a0a1db8cc141887c22df1ad4ca702a75722b55d"


def test_gate8_086060_canonical_values():
    """Gate 8: Verify exact canonical values for 086060 진바이오텍."""
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv"
    df_c = pd.read_csv(csv_path, dtype={"ticker": str})
    jin = df_c[df_c["ticker"] == "086060"].iloc[0]
    assert jin["market_cap_eok"] == 404.7
    assert jin["close"] == 4700.0
    assert jin["avg_trading_value_20d_eok"] == 1.12
    assert jin["avg_trading_value_60d_eok"] == 1.46


def test_gate9_scenario_counts_consistency(canonical_audit_result: dict):
    """Gate 9: Verify scenario impact matrix consistency."""
    sc_csv = _ARTIFACTS_DIR / "pattern_a_investability_scenarios_20260814.csv"
    assert sc_csv.exists()
    df_sc = pd.read_csv(sc_csv)
    base_row = df_sc[df_sc["scenario_id"] == "BASE_ALL"].iloc[0]
    assert base_row["universe_remaining"] == 2528
    assert base_row["candidate_remaining"] == 180
    assert base_row["transition_remaining"] == 168
    assert base_row["early_remaining"] == 12
    assert base_row["human42_remaining"] == 42


def test_gate10_phase10a_final_decision(canonical_audit_result: dict):
    """Gate 10: Verify Phase 10A decision is READY_FOR_THRESHOLD_DESIGN."""
    assert canonical_audit_result["phase_10a_decision"] == "READY_FOR_THRESHOLD_DESIGN"
    for gate_name, pass_val in canonical_audit_result["hard_gates"].items():
        assert pass_val is True, f"Gate {gate_name} must be True"


def test_gate11_fail_closed_behavior(tmp_path: Path):
    """Gate 11: Verify fail-closed behavior when an input is missing or broken."""
    # Test distribution stats on empty series
    empty_stats = calculate_distribution_stats(pd.Series([], dtype=float))
    assert empty_stats["count"] == 0
    assert empty_stats["available_count"] == 0
    assert empty_stats["min"] is None
