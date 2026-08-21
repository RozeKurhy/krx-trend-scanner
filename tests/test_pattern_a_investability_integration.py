"""Integration and Parity Verification Tests for Phase 10C Downstream Integration."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.filters.investability import InvestabilityStatus
from trend_scanner.patterns.pattern_a_evaluator import PatternACandidateState
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.scanner.full_universe_scanner import scan_pattern_a_universe
from trend_scanner.validation.pattern_a_investability_integration import (
    run_investability_integration_validation,
    CANONICAL_AS_OF,
    EXPECTED_RAW_CANDIDATES,
    EXPECTED_TRANSITION_COUNT,
    EXPECTED_EARLY_COUNT,
    EXPECTED_INVESTABLE_COUNT,
    EXPECTED_FILTERED_MARKET_CAP_COUNT,
    EXPECTED_FILTERED_LIQUIDITY_COUNT,
    EXPECTED_DATA_UNAVAILABLE_COUNT,
    EXPECTED_UNAVAILABLE_TICKERS,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/patterns/pattern_a/production/investability"


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
    assert bd["filtered_market_cap_count"] == EXPECTED_FILTERED_MARKET_CAP_COUNT  # 42
    assert bd["filtered_liquidity_count"] == EXPECTED_FILTERED_LIQUIDITY_COUNT  # 31
    assert bd["data_unavailable_count"] == EXPECTED_DATA_UNAVAILABLE_COUNT  # 4
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


def test_provenance_contract_on_candidates():
    """Gate 4: Verify PIT provenance timestamps <= requested_as_of on all candidate rows."""
    comp_csv = _ARTIFACTS_DIR / "pattern_a_investability_integration_20260814.csv"
    df = pd.read_csv(comp_csv, dtype={"ticker": str})

    for _, r in df.iterrows():
        if pd.notna(r.get("market_cap_effective_date")):
            assert r["market_cap_effective_date"] <= CANONICAL_AS_OF
        if pd.notna(r.get("close_effective_date")):
            assert r["close_effective_date"] <= CANONICAL_AS_OF
        if pd.notna(r.get("tv20_last_observation_date")):
            assert r["tv20_last_observation_date"] <= CANONICAL_AS_OF


def test_canonical_candidate_summary_breakdown(integration_summary: dict):
    """Verify canonical Phase 10 integration summary candidate downstream counts sum to 180.

    TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_V01 (P1) / FIX_01 (Major 2):
    이 invariant는 `integration_summary`(canonical, 이미 파일에서 읽거나 1회만
    계산됨)에 이미 담겨 있으므로, 동일 값을 다시 확인하기 위해 2,528종목
    Full Universe Scan을 별도로 재실행하지 않는다. 이 test는 canonical
    integration summary의 내용 자체(180/103/42/31/4)를 검증하는 것이며,
    "실제 scanner가 candidate/investability를 올바르게 집계하는가"라는
    scanner aggregation coverage가 아니다 — 이름을 `test_scanner_...`에서
    `test_canonical_...`로 바꿔 그 의미를 명확히 했다(과거 이 이름이었을 때
    scanner를 실제로 호출했던 것과 혼동되지 않도록). Scanner aggregation
    자체의 회귀 검증은 `tests/test_full_universe_scanner.py`의
    synthetic universe 기반 test가 별도로 전담한다.
    """
    bd = integration_summary["investability_breakdown"]
    candidate_raw_count = integration_summary["candidate_count"]

    assert candidate_raw_count == 180
    assert bd["investable_count"] == 103
    assert bd["filtered_market_cap_count"] == 42
    assert bd["filtered_liquidity_count"] == 31
    assert bd["data_unavailable_count"] == 4
    assert candidate_raw_count == (
        bd["investable_count"]
        + bd["filtered_market_cap_count"]
        + bd["filtered_liquidity_count"]
        + bd["data_unavailable_count"]
    )


def test_historical_lookahead_negative_case():
    """Verify that scanning historical as_of (2025-01-31) with future reference date (2026-08-14) uses PIT source and prevents future market cap leakage."""
    cache = ParquetCache(base_dir=_REPO_ROOT / "data/raw/stocks")
    # Scan single ticker with as_of = 2025-01-31 and reference_market_date = 2026-08-14 (B > A)
    scan_res = scan_pattern_a_universe(
        cache=cache,
        as_of="2025-01-31",
        reference_market_date="2026-08-14",
        target_tickers=["005930"],
    )
    assert len(scan_res.rows) == 1
    row = scan_res.rows[0]
    # Market cap snapshot for 2025-01-31 does not exist in canonical snapshot dir (only 20260814 exists)
    # -> Must safely fall back to None / DATA_UNAVAILABLE, NEVER load 2026-08-14 snapshot!
    assert row.market_cap is None or row.market_cap_effective_date == "2025-01-31"
    assert row.market_cap_effective_date != "2026-08-14"
    if row.market_cap is None:
        assert row.investability_status == InvestabilityStatus.DATA_UNAVAILABLE


def test_ticker_set_exact_equality(integration_summary: dict):
    """Gate 5: Verify candidate ticker set exactly matches Phase 10B canonical oracle ticker set."""
    assert integration_summary["ticker_set_mismatch_count"] == 0
    assert len(integration_summary["missing_tickers"]) == 0
    assert len(integration_summary["extra_tickers"]) == 0
    assert integration_summary["stage_mismatch_count"] == 0
    assert integration_summary["candidate_state_mismatch_count"] == 0
    assert integration_summary["score_mismatch_count"] == 0
    assert integration_summary["market_cap_mismatch_count"] == 0
    assert integration_summary["tv20_mismatch_count"] == 0
    assert integration_summary["status_mismatch_count"] == 0


def test_gate8_fail_closed_on_missing_report(tmp_path: Path):
    """Gate 8 Negative Test: Verify _read_pytest_report fails closed when report.json is missing."""
    from trend_scanner.validation.pattern_a_investability_integration import _read_pytest_report
    exit_code, failed, blocking_failed = _read_pytest_report(tmp_path)
    assert exit_code == -1
    assert failed == -1
    assert blocking_failed == -1


def test_gate8_fail_closed_on_corrupted_or_missing_keys(tmp_path: Path):
    """Gate 8 Negative Test: Verify _read_pytest_report fails closed when report.json is corrupted or lacks required keys."""
    from trend_scanner.validation.pattern_a_investability_integration import _read_pytest_report
    res_dir = tmp_path / ".pytest_results"
    res_dir.mkdir(parents=True)
    report_file = res_dir / "report.json"

    # Case 1: Corrupted JSON
    report_file.write_text("NOT_A_JSON", encoding="utf-8")
    assert _read_pytest_report(tmp_path) == (-1, -1, -1)

    # Case 2: Missing 'failed' or 'passed' key
    report_file.write_text(json.dumps({"exit_code": 0}), encoding="utf-8")
    assert _read_pytest_report(tmp_path) == (-1, -1, -1)


def test_numeric_parity_null_asymmetry_detection():
    """Negative Test: Verify _compare_numeric_parity strictly detects null asymmetry and tolerance violations."""
    from trend_scanner.validation.pattern_a_investability_integration import _compare_numeric_parity

    # Case 1: Both null -> MATCH
    is_match, err = _compare_numeric_parity(None, None)
    assert is_match is True and err is None

    # Case 2: Production null, Oracle non-null -> MISMATCH (Null asymmetry)
    is_match, err = _compare_numeric_parity(None, 1500.0)
    assert is_match is False and "NULL_ASYMMETRY" in str(err)

    # Case 3: Production non-null, Oracle null -> MISMATCH (Null asymmetry)
    is_match, err = _compare_numeric_parity(1500.0, None)
    assert is_match is False and "NULL_ASYMMETRY" in str(err)

    # Case 4: Both non-null within tolerance -> MATCH
    is_match, err = _compare_numeric_parity(100.001, 100.002, tolerance=0.01)
    assert is_match is True and err is None

    # Case 5: Both non-null exceeding tolerance -> MISMATCH
    is_match, err = _compare_numeric_parity(100.0, 105.0, tolerance=0.05)
    assert is_match is False and "TOLERANCE_EXCEEDED" in str(err)


def test_integration_hard_gates_all_pass(integration_summary: dict):
    """Gate 8 & Final: Verify all 8 dynamic integration gates PASS and status is INTEGRATION_READY."""
    gates = integration_summary["hard_gates"]
    assert len(gates) == 8
    for g_name, g_pass in gates.items():
        assert g_pass is True, f"Gate {g_name} failed!"
    assert integration_summary["phase_10c_status"] == "INTEGRATION_READY"

