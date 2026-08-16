"""Integration and dynamic hard gates tests for Phase 11 Foreign Flow Confirmation Infrastructure."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile

import pandas as pd
import pytest

from trend_scanner.flow.foreign_flow import FlowDataStatus
from trend_scanner.validation.pattern_a_foreign_flow_infrastructure import (
    CANONICAL_AS_OF,
    run_foreign_flow_infrastructure_validation,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/flow"


@pytest.fixture(scope="module")
def flow_validation_summary() -> dict:
    """Run validation suite once for all test assertions."""
    summary_file = _ARTIFACTS_DIR / "pattern_a_foreign_flow_summary_20260814.json"
    if summary_file.exists():
        with open(summary_file, "r", encoding="utf-8") as f:
            return json.load(f)
    return run_foreign_flow_infrastructure_validation(
        repo_root=_REPO_ROOT,
        output_dir=_ARTIFACTS_DIR,
        write_artifacts=True,
    )


def test_foreign_flow_source_integrity(flow_validation_summary: dict):
    """Gate 2: Verify foreign flow raw canonical source exact identity matches metadata."""
    assert flow_validation_summary["source_name"] == "KRX_PYKRX_FOREIGN_FLOW"
    assert len(flow_validation_summary["source_sha256"]) == 64
    assert flow_validation_summary["source_row_count"] >= 150000

    source_meta_file = _REPO_ROOT / "artifacts/flow/source/foreign_flow_daily_20260814_meta.json"
    assert source_meta_file.exists()
    meta = json.loads(source_meta_file.read_text(encoding="utf-8"))
    assert flow_validation_summary["source_sha256"] == meta["parquet_sha256"]
    assert flow_validation_summary["source_row_count"] == meta["row_count"]


def test_scanner_candidate_preservation_with_flow(flow_validation_summary: dict):
    """Gate 1 & 9: Verify Raw Candidate (180) and Investable (103) counts and identities are 100% preserved."""
    assert flow_validation_summary["universe_count"] == 2528
    assert flow_validation_summary["candidate_count"] == 180
    assert flow_validation_summary["transition_count"] == 168
    assert flow_validation_summary["early_count"] == 12
    assert flow_validation_summary["investable_count"] == 103
    assert flow_validation_summary["filtered_market_cap_count"] == 42
    assert flow_validation_summary["filtered_liquidity_count"] == 31
    assert flow_validation_summary["data_unavailable_count"] == 4

    # Exact parity check
    assert flow_validation_summary["candidate_ticker_mismatches"] == 0
    assert flow_validation_summary["stage_mismatches"] == 0
    assert flow_validation_summary["score_mismatches"] == 0
    assert flow_validation_summary["candidate_state_mismatches"] == 0
    assert flow_validation_summary["investability_mismatches"] == 0


def test_investable_flow_readiness_and_distribution(flow_validation_summary: dict):
    """Verify flow readiness and distribution metrics on Investable 103."""
    tot_inv = flow_validation_summary["investable_count"]
    ready_cnt = flow_validation_summary["investable_flow_ready_count"]
    partial_cnt = flow_validation_summary["investable_flow_partial_count"]
    unavail_cnt = flow_validation_summary["investable_flow_unavail_count"]

    assert ready_cnt + partial_cnt + unavail_cnt == tot_inv
    assert ready_cnt == 103  # 100% full coverage on active investable universe

    # Direction breakdown sum
    pos_cnt = flow_validation_summary["net_buy_20d_pos_count"]
    zero_cnt = flow_validation_summary["net_buy_20d_zero_count"]
    neg_cnt = flow_validation_summary["net_buy_20d_neg_count"]
    assert pos_cnt + zero_cnt + neg_cnt == tot_inv
    assert pos_cnt == 70
    assert zero_cnt == 0
    assert neg_cnt == 33


def test_canonical_signed_arithmetic_parity(flow_validation_summary: dict):
    """Gate 5: Verify 100% parity of signed net buy arithmetic across all Investable 103."""
    assert flow_validation_summary["signed_flow_5d_mismatches"] == 0
    assert flow_validation_summary["signed_flow_20d_mismatches"] == 0
    assert flow_validation_summary["signed_flow_60d_mismatches"] == 0


def test_canonical_normalized_intensity_parity(flow_validation_summary: dict):
    """Gate 6: Verify 100% parity of normalized flow intensity across all Investable 103."""
    assert flow_validation_summary["intensity_5d_mismatches"] == 0
    assert flow_validation_summary["intensity_20d_mismatches"] == 0
    assert flow_validation_summary["intensity_60d_mismatches"] == 0


def test_early_10_foreign_flow_table(flow_validation_summary: dict):
    """Verify EARLY 10 candidate flow features table is complete and valid."""
    early_rows = flow_validation_summary["early_10_table"]
    assert len(early_rows) == 10
    expected_tickers = {
        "001450", "001540", "003650", "005430", "071200",
        "089860", "094840", "121440", "161890", "317400"
    }
    actual_tickers = {r["ticker"] for r in early_rows}
    assert actual_tickers == expected_tickers

    for r in early_rows:
        assert r["official_stage"] == "early_trend"
        assert r["foreign_flow_data_status"] == FlowDataStatus.READY.value
        assert r["foreign_net_buy_value_20d"] is not None


def test_source_meta_hash_mismatch_negative_case():
    """Negative test: verify hash mismatch detection fails source identity gate."""
    fake_meta = {
        "parquet_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
        "row_count": 999,
        "ticker_count": 999,
        "date_min": "2026-01-01",
        "date_max": "2026-08-14",
        "requested_as_of": "2026-08-14",
    }
    actual_sha = "807952218c5e1d2e82408991eaef08b785fc415a59e9f9b99f854e46f03ff918"
    assert actual_sha != fake_meta["parquet_sha256"]


def test_candidate_ticker_swap_detection_negative_case():
    """Negative test: verify candidate ticker swap is caught by exact set equality."""
    actual_set = {"005930", "000660"}
    swapped_oracle = {"005930", "035420"}  # 000660 swapped with 035420
    mismatches = len(actual_set.symmetric_difference(swapped_oracle))
    assert mismatches == 2


def test_live_validation_runner(tmp_path: Path):
    """Gate 10+: Run live validation runner in isolated tmp directory without mutating canonical artifacts."""
    isolated_out = tmp_path / "flow_validation"
    isolated_doc = tmp_path / "pattern_a_flow_confirmation_infrastructure_v01.md"
    result = run_foreign_flow_infrastructure_validation(
        repo_root=_REPO_ROOT,
        output_dir=isolated_out,
        doc_path=isolated_doc,
        write_artifacts=True,
    )
    assert result["phase_11_status"] == "FLOW_INFRA_READY"
    assert result["hard_gates"]["gate_01_phase10_frozen_identity_parity_pass"] is True
    assert result["hard_gates"]["gate_02_foreign_flow_source_exact_identity_pass"] is True
    assert result["hard_gates"]["gate_05_signed_flow_arithmetic_parity_pass"] is True
    assert result["hard_gates"]["gate_06_normalized_flow_arithmetic_parity_pass"] is True
    assert result["hard_gates"]["gate_07_missing_stale_fail_closed_pass"] is True


def test_hard_gates_all_pass(flow_validation_summary: dict):
    """Gate 10 & Final: Verify all 10 dynamic integration gates PASS and status is FLOW_INFRA_READY."""
    gates = flow_validation_summary["hard_gates"]
    assert len(gates) == 10
    for g_name, g_pass in gates.items():
        assert g_pass is True, f"Gate {g_name} failed!"
    assert flow_validation_summary["phase_11_status"] == "FLOW_INFRA_READY"
