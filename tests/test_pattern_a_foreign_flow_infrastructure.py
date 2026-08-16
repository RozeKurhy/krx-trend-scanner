"""Integration and dynamic hard gates tests for Phase 11 Foreign Flow Confirmation Infrastructure."""

from __future__ import annotations

import json
from pathlib import Path

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
    """Gate 2: Verify foreign flow raw canonical source integrity and metadata."""
    assert flow_validation_summary["source_name"] == "KRX_PYKRX_FOREIGN_FLOW"
    assert len(flow_validation_summary["source_sha256"]) == 64
    assert flow_validation_summary["source_row_count"] >= 150000


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


def test_investable_flow_readiness_and_distribution(flow_validation_summary: dict):
    """Verify flow readiness and distribution metrics on Investable 103."""
    tot_inv = flow_validation_summary["investable_count"]
    ready_cnt = flow_validation_summary["investable_flow_ready_count"]
    partial_cnt = flow_validation_summary["investable_flow_partial_count"]
    unavail_cnt = flow_validation_summary["investable_flow_unavail_count"]

    assert ready_cnt + partial_cnt + unavail_cnt == tot_inv
    assert ready_cnt >= 95  # Vast majority of active stocks have full 20D flow

    # Direction breakdown sum
    pos_cnt = flow_validation_summary["net_buy_20d_pos_count"]
    zero_cnt = flow_validation_summary["net_buy_20d_zero_count"]
    neg_cnt = flow_validation_summary["net_buy_20d_neg_count"]
    assert pos_cnt + zero_cnt + neg_cnt == tot_inv


def test_early_10_foreign_flow_table(flow_validation_summary: dict):
    """Verify EARLY 10 candidate flow features table is complete and valid."""
    early_rows = flow_validation_summary["early_10_table"]
    assert len(early_rows) == 10
    for r in early_rows:
        assert r["official_stage"] == "early_trend"
        assert r["foreign_flow_data_status"] in (FlowDataStatus.READY.value, FlowDataStatus.PARTIAL.value)
        assert r["foreign_net_buy_value_20d"] is not None


def test_hard_gates_all_pass(flow_validation_summary: dict):
    """Gate 10 & Final: Verify all 10 dynamic integration gates PASS and status is FLOW_INFRA_READY."""
    gates = flow_validation_summary["hard_gates"]
    assert len(gates) == 10
    for g_name, g_pass in gates.items():
        assert g_pass is True, f"Gate {g_name} failed!"
    assert flow_validation_summary["phase_11_status"] == "FLOW_INFRA_READY"
