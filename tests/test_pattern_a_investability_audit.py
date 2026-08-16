"""Unit and Integration Tests for Phase 10A Investability Distribution Audit."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.validation.pattern_a_investability_audit import run_investability_audit

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/investability"


@pytest.fixture(scope="module")
def investability_summary() -> dict:
    """Load or run investability audit summary."""
    summary_path = _ARTIFACTS_DIR / "pattern_a_investability_summary_20260814.json"
    if not summary_path.exists():
        return run_investability_audit(_REPO_ROOT, as_of="2026-08-14")
    return json.loads(summary_path.read_text(encoding="utf-8"))


def test_gate1_no_lookahead(investability_summary: dict):
    """Gate 1: Verify as_of is strictly 2026-08-14 without lookahead."""
    assert investability_summary["as_of"] == "2026-08-14"
    assert investability_summary["data_provenance"]["lookahead_free"] is True


def test_gate2_universe_identity(investability_summary: dict):
    """Gate 2: Verify Universe count is exactly 2,528."""
    assert investability_summary["universe_count"] == 2528
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_universe_20260814.csv"
    assert csv_path.exists()
    df_u = pd.read_csv(csv_path, dtype={"ticker": str})
    assert len(df_u) == 2528


def test_gate3_candidate_identity(investability_summary: dict):
    """Gate 3: Verify Candidate count is exactly 180."""
    assert investability_summary["candidate_count"] == 180
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv"
    assert csv_path.exists()
    df_c = pd.read_csv(csv_path, dtype={"ticker": str})
    assert len(df_c) == 180


def test_gate4_stage_split(investability_summary: dict):
    """Gate 4: Verify stage split is 168 Transition and 12 Early."""
    assert investability_summary["transition_count"] == 168
    assert investability_summary["early_count"] == 12


def test_gate5_human42_identity(investability_summary: dict):
    """Gate 5: Verify Human42 count is exactly 42."""
    assert investability_summary["human42_count"] == 42


def test_gate6_trading_value_windows():
    """Gate 6: Verify trading value windows for 20D and 60D."""
    csv_path = _ARTIFACTS_DIR / "pattern_a_investability_candidates_20260814.csv"
    df_c = pd.read_csv(csv_path, dtype={"ticker": str})
    assert (df_c["trading_days_20d"] == 20).all()
    assert (df_c["trading_days_60d"] == 60).all()
    assert (df_c["avg_trading_value_20d_eok"] > 0).all()
    assert (df_c["avg_trading_value_60d_eok"] > 0).all()


def test_gate7_market_cap_provenance(investability_summary: dict):
    """Gate 7: Verify market cap provenance and zero missing in candidates."""
    assert "pykrx" in investability_summary["data_provenance"]["market_cap_source"]
    assert investability_summary["missing_audit"]["candidate_missing_count"] == 0
    assert investability_summary["missing_audit"]["universe_mcap_missing_count"] == 0


def test_gate8_missing_ticker_report_consistency(investability_summary: dict):
    """Gate 8: Verify universe cache missing count is 42."""
    assert investability_summary["missing_audit"]["universe_cache_missing_count"] == 42
    assert len(investability_summary["missing_audit"]["universe_cache_missing_tickers"]) == 42


def test_gate9_scenario_counts_consistency():
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


def test_gate10_phase10a_final_decision(investability_summary: dict):
    """Gate 10: Verify Phase 10A decision is READY_FOR_THRESHOLD_DESIGN."""
    assert investability_summary["phase_10a_decision"] == "READY_FOR_THRESHOLD_DESIGN"
