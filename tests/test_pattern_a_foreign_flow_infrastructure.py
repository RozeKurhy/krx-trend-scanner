"""Integration and dynamic hard gates tests for Phase 11 Foreign Flow Confirmation Infrastructure."""

from __future__ import annotations

import json
from dataclasses import MISSING, fields
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


@pytest.fixture(scope="module")
def base_scan_result():
    """Load the immutable production scan once for validator negative tests.

    The canonical scanner CSV contains the full 2,528-row structural result;
    the canonical flow CSV contains the complete downstream fields for the
    180 candidates.  Reconstructing the frozen result here keeps the negative
    tests focused on validator fail-closed behavior instead of repeating the
    multi-minute production scan.  The ``test_live_validation_runner`` below
    still executes the real scanner path independently.
    """
    from trend_scanner.scanner.full_universe_scanner import (
        PatternAUniverseScanResult,
        PatternAUniverseScanRow,
        PatternAUniverseScanSummary,
        ScannerRowStatus,
    )
    from trend_scanner.filters.investability import InvestabilityStatus
    from trend_scanner.patterns.pattern_a_evaluator import PatternACandidateState
    from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
    from trend_scanner.universe.models import AssetType, FreshnessStatus, MarketType

    scanner_csv = _REPO_ROOT / "artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260814.csv"
    flow_csv = _REPO_ROOT / "artifacts/patterns/pattern_a/production/flow/pattern_a_foreign_flow_features_20260814.csv"
    summary_json = _REPO_ROOT / "artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260814_summary.json"
    if not scanner_csv.exists() or not flow_csv.exists() or not summary_json.exists():
        pytest.fail("canonical scanner/flow artifacts required for immutable negative-test fixture")

    scanner_df = pd.read_csv(scanner_csv, dtype={"ticker": str})
    flow_df = pd.read_csv(flow_csv, dtype={"ticker": str})
    scanner_df["ticker"] = scanner_df["ticker"].str.zfill(6)
    flow_df["ticker"] = flow_df["ticker"].str.zfill(6)
    flow_by_ticker = flow_df.set_index("ticker", drop=False)

    def _value(row: pd.Series, name: str, default=None):
        value = row.get(name, default)
        return default if pd.isna(value) else value

    def _optional_timestamp(value):
        return None if value is None or pd.isna(value) else pd.Timestamp(value)

    def _optional_float(value):
        return None if value is None or pd.isna(value) else float(value)

    def _bool(value, default=False):
        if value is None or pd.isna(value):
            return default
        if isinstance(value, str):
            return value.strip().lower() in {"true", "1", "yes"}
        return bool(value)

    def _tuple(value):
        if value is None or pd.isna(value) or str(value).strip() == "":
            return ()
        return tuple(part for part in str(value).split(";") if part)

    rows = []
    for _, structural in scanner_df.iterrows():
        ticker = structural["ticker"]
        merged = structural.copy()
        if ticker in flow_by_ticker.index:
            flow_row = flow_by_ticker.loc[ticker]
            for column, value in flow_row.items():
                if column != "ticker":
                    merged[column] = value

        def _enum(enum_type, name, default):
            raw = _value(merged, name, default.value if hasattr(default, "value") else default)
            return enum_type(str(raw))

        rows.append(
            PatternAUniverseScanRow(
                ticker=ticker,
                name=str(_value(merged, "name", "")),
                market=_enum(MarketType, "market", MarketType.UNKNOWN),
                asset_type=_enum(AssetType, "asset_type", AssetType.COMMON),
                requested_as_of=pd.Timestamp(_value(merged, "requested_as_of", CANONICAL_AS_OF)),
                effective_as_of=_optional_timestamp(_value(merged, "effective_as_of")),
                cache_present=_bool(_value(merged, "cache_present")),
                cache_first_date=_optional_timestamp(_value(merged, "cache_first_date")),
                cache_last_date=_optional_timestamp(_value(merged, "cache_last_date")),
                daily_rows=int(_value(merged, "daily_rows", 0)),
                completed_month_count=int(_value(merged, "completed_month_count", 0)),
                freshness_status=_enum(FreshnessStatus, "freshness_status", FreshnessStatus.UNKNOWN),
                staleness_trading_days=int(_value(merged, "staleness_trading_days", -1)),
                quality_flags=_tuple(_value(merged, "quality_flags")),
                quality_reason_codes=_tuple(_value(merged, "quality_reason_codes")),
                raw_data_ready=_bool(_value(merged, "raw_data_ready")),
                feature_ready=_bool(_value(merged, "feature_ready")),
                score_ready=_bool(_value(merged, "score_ready")),
                stage_ready=_bool(_value(merged, "stage_ready")),
                evaluator_ready=_bool(_value(merged, "evaluator_ready")),
                momentum_current_ready=_bool(_value(merged, "momentum_current_ready")),
                momentum_1m_ready=_bool(_value(merged, "momentum_1m_ready")),
                momentum_3m_ready=_bool(_value(merged, "momentum_3m_ready")),
                momentum_6m_ready=_bool(_value(merged, "momentum_6m_ready")),
                pattern_a_score=_optional_float(_value(merged, "pattern_a_score")),
                official_stage=_enum(PatternAStage, "official_stage", PatternAStage.WEAK) if _value(merged, "official_stage") is not None else None,
                candidate_state=_enum(PatternACandidateState, "candidate_state", PatternACandidateState.INSUFFICIENT_DATA),
                evaluator_reason_codes=_tuple(_value(merged, "evaluator_reason_codes")),
                base_score=_optional_float(_value(merged, "base_score")),
                transition_score=_optional_float(_value(merged, "transition_score")),
                core_score=_optional_float(_value(merged, "core_score")),
                support_score=_optional_float(_value(merged, "support_score")),
                confirmation_bonus=_optional_float(_value(merged, "confirmation_bonus")),
                balanced_core_score=_optional_float(_value(merged, "balanced_core_score")),
                alignment_bonus=_optional_float(_value(merged, "alignment_bonus")),
                progressed_penalty=_optional_float(_value(merged, "progressed_penalty")),
                score_delta_1m=_optional_float(_value(merged, "score_delta_1m")),
                score_delta_3m=_optional_float(_value(merged, "score_delta_3m")),
                score_delta_6m=_optional_float(_value(merged, "score_delta_6m")),
                momentum_reason_codes_1m=_tuple(_value(merged, "momentum_reason_codes_1m")),
                momentum_reason_codes_3m=_tuple(_value(merged, "momentum_reason_codes_3m")),
                momentum_reason_codes_6m=_tuple(_value(merged, "momentum_reason_codes_6m")),
                base_score_delta_1m=_optional_float(_value(merged, "base_score_delta_1m")),
                base_score_delta_3m=_optional_float(_value(merged, "base_score_delta_3m")),
                base_score_delta_6m=_optional_float(_value(merged, "base_score_delta_6m")),
                transition_score_delta_1m=_optional_float(_value(merged, "transition_score_delta_1m")),
                transition_score_delta_3m=_optional_float(_value(merged, "transition_score_delta_3m")),
                transition_score_delta_6m=_optional_float(_value(merged, "transition_score_delta_6m")),
                market_cap=_optional_float(_value(merged, "market_cap")),
                market_cap_eok=_optional_float(_value(merged, "market_cap_eok")),
                avg_trading_value_20d=_optional_float(_value(merged, "avg_trading_value_20d")),
                avg_trading_value_20d_eok=_optional_float(_value(merged, "avg_trading_value_20d_eok")),
                avg_trading_value_60d=_optional_float(_value(merged, "avg_trading_value_60d")),
                avg_trading_value_60d_eok=_optional_float(_value(merged, "avg_trading_value_60d_eok")),
                investability_status=_enum(InvestabilityStatus, "investability_status", InvestabilityStatus.DATA_UNAVAILABLE),
                investability_reason=str(_value(merged, "investability_reason", "REQUIRED_METRIC_UNAVAILABLE")),
                investability_ready=_bool(_value(merged, "investability_ready")),
                market_cap_effective_date=_value(merged, "market_cap_effective_date"),
                close_effective_date=_value(merged, "close_effective_date"),
                tv20_last_observation_date=_value(merged, "tv20_last_observation_date"),
                foreign_flow_data_status=str(_value(merged, "foreign_flow_data_status", "NOT_EVALUATED")),
                foreign_flow_last_observation_date=_value(merged, "foreign_flow_last_observation_date"),
                foreign_flow_first_observation_date=_value(merged, "foreign_flow_first_observation_date"),
                foreign_flow_observation_count=int(_value(merged, "foreign_flow_observation_count", 0)),
                foreign_net_buy_value_1d=_optional_float(_value(merged, "foreign_net_buy_value_1d")),
                foreign_net_buy_value_5d=_optional_float(_value(merged, "foreign_net_buy_value_5d")),
                foreign_net_buy_value_20d=_optional_float(_value(merged, "foreign_net_buy_value_20d")),
                foreign_net_buy_value_60d=_optional_float(_value(merged, "foreign_net_buy_value_60d")),
                foreign_flow_intensity_5d=_optional_float(_value(merged, "foreign_flow_intensity_5d")),
                foreign_flow_intensity_20d=_optional_float(_value(merged, "foreign_flow_intensity_20d")),
                foreign_flow_intensity_60d=_optional_float(_value(merged, "foreign_flow_intensity_60d")),
                foreign_positive_days_5d=_optional_float(_value(merged, "foreign_positive_days_5d")),
                foreign_positive_days_20d=_optional_float(_value(merged, "foreign_positive_days_20d")),
                foreign_positive_days_60d=_optional_float(_value(merged, "foreign_positive_days_60d")),
                foreign_positive_day_ratio_5d=_optional_float(_value(merged, "foreign_positive_day_ratio_5d")),
                foreign_positive_day_ratio_20d=_optional_float(_value(merged, "foreign_positive_day_ratio_20d")),
                foreign_positive_day_ratio_60d=_optional_float(_value(merged, "foreign_positive_day_ratio_60d")),
                foreign_net_buy_avg_5d=_optional_float(_value(merged, "foreign_net_buy_avg_5d")),
                foreign_net_buy_avg_20d=_optional_float(_value(merged, "foreign_net_buy_avg_20d")),
                foreign_net_buy_avg_60d=_optional_float(_value(merged, "foreign_net_buy_avg_60d")),
                row_status=_enum(ScannerRowStatus, "row_status", ScannerRowStatus.UNAVAILABLE),
                error_type=_value(merged, "error_type"),
                error_message=_value(merged, "error_message"),
            )
        )

    summary_payload = json.loads(summary_json.read_text(encoding="utf-8"))
    summary_kwargs = {}
    for item in fields(PatternAUniverseScanSummary):
        if item.name in summary_payload:
            summary_kwargs[item.name] = summary_payload[item.name]
        elif item.default is not MISSING:
            summary_kwargs[item.name] = item.default
        elif item.default_factory is not MISSING:  # type: ignore[comparison-overlap]
            summary_kwargs[item.name] = item.default_factory()
        elif item.name in {"investability_distribution", "score_distribution", "momentum_1m_distribution", "momentum_3m_distribution", "momentum_6m_distribution"}:
            summary_kwargs[item.name] = {}
        elif item.name.endswith("_count"):
            summary_kwargs[item.name] = 0
        else:
            summary_kwargs[item.name] = {}
    summary = PatternAUniverseScanSummary(**summary_kwargs)
    return PatternAUniverseScanResult(
        requested_as_of=pd.Timestamp(CANONICAL_AS_OF),
        summary=summary,
        rows=tuple(rows),
    )


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
