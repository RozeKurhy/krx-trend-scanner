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
_ARTIFACTS_DIR = _REPO_ROOT / "artifacts/patterns/pattern_a/production/flow"
_REAL_PRODUCTION_SCAN_EXECUTION_COUNT = 0


@pytest.fixture(scope="module")
def base_scan_result():
    """Run the real 2,528-row production scan once for this module.

    The result is shared read-only by validator negative tests; each mutation
    test still creates an independent copy before exercising fail-closed logic.
    This fixture is intentionally not marked slow so the default Full Pytest
    workload retains the real production scan path.
    """
    from trend_scanner.data.cache import ParquetCache
    from trend_scanner.scanner.full_universe_scanner import scan_pattern_a_universe

    cache_dir = _REPO_ROOT / "data" / "raw" / "stocks"
    parquet_cache = ParquetCache(base_dir=cache_dir)
    source_parquet = _REPO_ROOT / "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_20260814.parquet"
    df_flow = pd.read_parquet(source_parquet) if source_parquet.exists() else pd.DataFrame()
    global _REAL_PRODUCTION_SCAN_EXECUTION_COUNT
    result = scan_pattern_a_universe(
        cache=parquet_cache,
        as_of=CANONICAL_AS_OF,
        flow_df=df_flow,
        enrich_flow_for_candidates=True,
    )
    _REAL_PRODUCTION_SCAN_EXECUTION_COUNT += 1
    return result


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


def test_real_production_scan_execution_contract(base_scan_result):
    """The default suite must execute the real 2,528-row scanner path."""
    assert _REAL_PRODUCTION_SCAN_EXECUTION_COUNT == 1
    # Includes 25 valid alphanumeric COMMON tickers previously misclassified as UNKNOWN.
    assert base_scan_result.summary.official_common_total == 2553
    assert base_scan_result.summary.rows_emitted == 2553
    # 138040 (Meritz Financial Group) is the one raw candidate among the 25-ticker delta;
    # EARLY_TREND stage, INVESTABLE.
    assert base_scan_result.summary.candidate_raw_count == 181
    assert base_scan_result.summary.candidate_investable_count == 104
    assert base_scan_result.summary.scanner_error_count == 0


def test_foreign_flow_source_integrity(flow_validation_summary: dict):
    """Gate 2: Verify foreign flow raw canonical source exact identity matches metadata."""
    assert flow_validation_summary["source_name"] == "KRX_PYKRX_FOREIGN_FLOW"
    assert len(flow_validation_summary["source_sha256"]) == 64
    assert flow_validation_summary["source_row_count"] >= 150000

    source_meta_file = _REPO_ROOT / "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_20260814_meta.json"
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


def test_oracle_missing_fail_closed_negative_test(base_scan_result, monkeypatch, tmp_path: Path):
    """Gate 1 & 9 Negative Test: Verify missing Phase 10 canonical oracle fails closed."""
    import copy
    import trend_scanner.validation.pattern_a_foreign_flow_infrastructure as val_mod

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", lambda *args, **kwargs: copy.deepcopy(base_scan_result))

    missing_oracle = tmp_path / "non_existent_oracle.csv"
    res = val_mod.run_foreign_flow_infrastructure_validation(
        repo_root=_REPO_ROOT,
        output_dir=tmp_path / "out",
        doc_path=tmp_path / "doc.md",
        write_artifacts=False,
        integration_oracle_path=missing_oracle,
        candidate_oracle_path=missing_oracle,
    )
    assert res["hard_gates"]["gate_01_phase10_frozen_identity_parity_pass"] is False
    assert res["hard_gates"]["gate_09_raw180_investable103_preservation_pass"] is False
    assert res["phase_11_status"] == "HOLD_FLOW_INFRA"


def test_candidate_ticker_swap_negative_test(base_scan_result, monkeypatch, tmp_path: Path):
    """Gate 1 & 9 Negative Test: Verify swapped ticker in oracle triggers validator mismatch."""
    import copy
    import trend_scanner.validation.pattern_a_foreign_flow_infrastructure as val_mod

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", lambda *args, **kwargs: copy.deepcopy(base_scan_result))

    canonical_oracle = _REPO_ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_integration_20260814.csv"
    df = pd.read_csv(canonical_oracle)
    # Swap first ticker to a fake ticker
    df.loc[0, "ticker"] = "999999"
    swapped_oracle = tmp_path / "swapped_oracle.csv"
    df.to_csv(swapped_oracle, index=False)

    res = val_mod.run_foreign_flow_infrastructure_validation(
        repo_root=_REPO_ROOT,
        output_dir=tmp_path / "out",
        doc_path=tmp_path / "doc.md",
        write_artifacts=False,
        integration_oracle_path=swapped_oracle,
    )
    assert res["candidate_ticker_mismatches"] > 0
    assert res["hard_gates"]["gate_01_phase10_frozen_identity_parity_pass"] is False
    assert res["hard_gates"]["gate_09_raw180_investable103_preservation_pass"] is False
    assert res["phase_11_status"] == "HOLD_FLOW_INFRA"


def test_investability_status_mutation_negative_test(base_scan_result, monkeypatch, tmp_path: Path):
    """Gate 1 Negative Test: Verify mutated investability status in oracle triggers mismatch."""
    import copy
    import trend_scanner.validation.pattern_a_foreign_flow_infrastructure as val_mod

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", lambda *args, **kwargs: copy.deepcopy(base_scan_result))

    canonical_oracle = _REPO_ROOT / "artifacts/patterns/pattern_a/production/investability/pattern_a_investability_integration_20260814.csv"
    df = pd.read_csv(canonical_oracle)
    # Mutate investability_status of the first row (INVESTABLE -> FILTERED_MARKET_CAP)
    df.loc[0, "investability_status"] = "FILTERED_MARKET_CAP"
    mutated_oracle = tmp_path / "mutated_oracle.csv"
    df.to_csv(mutated_oracle, index=False)

    res = val_mod.run_foreign_flow_infrastructure_validation(
        repo_root=_REPO_ROOT,
        output_dir=tmp_path / "out",
        doc_path=tmp_path / "doc.md",
        write_artifacts=False,
        integration_oracle_path=mutated_oracle,
    )
    assert res["investability_mismatches"] >= 1
    assert res["hard_gates"]["gate_01_phase10_frozen_identity_parity_pass"] is False
    assert res["phase_11_status"] == "HOLD_FLOW_INFRA"


def test_intensity_5d_mutation_negative_test(base_scan_result, monkeypatch, tmp_path: Path):
    """Gate 6 Negative Test: Verify mutated 5D intensity in scan results fails Gate 6."""
    from trend_scanner.scanner.full_universe_scanner import PatternAUniverseScanResult
    import trend_scanner.validation.pattern_a_foreign_flow_infrastructure as val_mod

    mutated_rows = list(base_scan_result.rows)
    mutated = False
    for idx, r in enumerate(mutated_rows):
        if r.ticker == "001540":
            mutated_rows[idx] = type(r)(
                **{**r.__dict__, "foreign_flow_intensity_5d": 999.0}
            )
            mutated = True
            break
    assert mutated, "Target investable candidate 001540 not found in scan rows"

    mutated_scan = PatternAUniverseScanResult(
        requested_as_of=base_scan_result.requested_as_of,
        summary=base_scan_result.summary,
        rows=tuple(mutated_rows),
    )

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", lambda *args, **kwargs: mutated_scan)

    res = val_mod.run_foreign_flow_infrastructure_validation(
        repo_root=_REPO_ROOT,
        output_dir=tmp_path / "out",
        doc_path=tmp_path / "doc.md",
        write_artifacts=False,
    )
    assert res["intensity_5d_mismatches"] >= 1
    assert res["hard_gates"]["gate_06_normalized_flow_arithmetic_parity_pass"] is False
    assert res["phase_11_status"] == "HOLD_FLOW_INFRA"


def test_intensity_60d_mutation_negative_test(base_scan_result, monkeypatch, tmp_path: Path):
    """Gate 6 Negative Test: Verify mutated 60D intensity in scan results fails Gate 6."""
    from trend_scanner.scanner.full_universe_scanner import PatternAUniverseScanResult
    import trend_scanner.validation.pattern_a_foreign_flow_infrastructure as val_mod

    mutated_rows = list(base_scan_result.rows)
    mutated = False
    for idx, r in enumerate(mutated_rows):
        if r.ticker == "001540":
            mutated_rows[idx] = type(r)(
                **{**r.__dict__, "foreign_flow_intensity_60d": 999.0}
            )
            mutated = True
            break
    assert mutated, "Target investable candidate 001540 not found in scan rows"

    mutated_scan = PatternAUniverseScanResult(
        requested_as_of=base_scan_result.requested_as_of,
        summary=base_scan_result.summary,
        rows=tuple(mutated_rows),
    )

    monkeypatch.setattr(val_mod, "scan_pattern_a_universe", lambda *args, **kwargs: mutated_scan)

    res = val_mod.run_foreign_flow_infrastructure_validation(
        repo_root=_REPO_ROOT,
        output_dir=tmp_path / "out",
        doc_path=tmp_path / "doc.md",
        write_artifacts=False,
    )
    assert res["intensity_60d_mismatches"] >= 1
    assert res["hard_gates"]["gate_06_normalized_flow_arithmetic_parity_pass"] is False
    assert res["phase_11_status"] == "HOLD_FLOW_INFRA"


@pytest.mark.slow
def test_live_validation_runner(tmp_path: Path):
    """Gate 10+: Run live validation runner in isolated tmp directory without mutating canonical artifacts.

    TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_V01 (P0/§12): 이 test는
    `run_foreign_flow_infrastructure_validation()`을 실제 repo_root로 호출해
    2,528종목 Full Universe Scan을 다시 발생시킨다 — `base_scan_result`
    module fixture(다른 5개 negative test가 재사용)와 완전히 별개의 추가 scan.
    검증하는 Gate(1,2,5,6,7)는 이미 `flow_validation_summary`(canonical 요약,
    파일에서 읽거나 1회만 계산) 기반 test들이 커버하므로, "실제 live validator
    경로가 isolated tmp 출력에서도 canonical artifact를 건드리지 않는다"는
    이 test 고유의 나머지 가치만 slow로 격리해 보존한다. 삭제가 아니다 —
    `uv run pytest ... -m slow`로 실행 가능."""
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
