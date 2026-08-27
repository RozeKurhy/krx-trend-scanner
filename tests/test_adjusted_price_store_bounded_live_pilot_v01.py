"""Tests for Adjusted Price Store Bounded Live Pilot (FIX04)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_pilot import (
    DEFAULT_ACTUAL_SOURCE_DATES_PATH,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    EXPECTED_POPULATION_COUNT,
    EXPECTED_POPULATION_SHA256,
    AuthorityQuality,
    AuthorityStatus,
    CoverageStatus,
    ExpectedCoverageResolution,
    PilotResult,
    PilotSample,
    PilotSampleGroup,
    SourceEligibilityStatus,
    SourceResponseStatus,
    build_pilot_sample_manifest,
    evaluate_pilot_acceptance,
    execute_single_pilot_query,
    is_nontradable_or_phantom_row,
    load_historical_suspension_authority,
    resolve_expected_coverage,
    run_bounded_live_pilot,
)
from trend_scanner.data.adjusted_price_provider import (
    AdjustedPriceDataProvider,
    normalize_ticker,
)
from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
    load_historical_common_population,
    population_manifest_sha256,
)


def test_frozen_population_hash_gate_matches_canonical():
    """Verify frozen population count and SHA256 integrity."""
    records = load_historical_common_population(DEFAULT_POPULATION_ARTIFACT_PATH)
    assert len(records) == EXPECTED_POPULATION_COUNT == 3162
    calc_sha = population_manifest_sha256(records)
    assert calc_sha == EXPECTED_POPULATION_SHA256


def test_sample_authority_assertions_group_b_rejects_current_common():
    """Verify Group B sample authority strictly rejects currently-common tickers like 001040."""
    manifest = build_pilot_sample_manifest()
    group_b_samples = [s for s in manifest if s.sample_group == PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED]
    assert len(group_b_samples) == 5

    group_b_tickers = {s.ticker for s in group_b_samples}
    assert "001040" not in group_b_tickers
    assert group_b_tickers == {"000030", "000060", "000360", "000470", "002670"}

    for s in group_b_samples:
        assert s.historical_only is True
        assert s.currently_common is False
        assert s.last_common_date < "2026-08-21"


def test_sample_authority_assertions_group_d_is_exact_23_census():
    """Verify Group D contains all 23 alphanumeric common stocks in the population."""
    manifest = build_pilot_sample_manifest()
    group_d_samples = [s for s in manifest if s.sample_group == PilotSampleGroup.GROUP_D_ALPHA]
    assert len(group_d_samples) == 23
    for s in group_d_samples:
        assert s.numeric_or_alpha == "alphanumeric"


def test_production_provider_normalizes_valid_alpha_and_numeric():
    """Verify production normalize_ticker supports ^[0-9A-Z]{6}$ and rejects invalid."""
    assert normalize_ticker("005930") == "005930"
    assert normalize_ticker("5930") == "005930"
    assert normalize_ticker("0008Z0") == "0008Z0"
    assert normalize_ticker("0001A0") == "0001A0"
    assert normalize_ticker("00781K") == "00781K"

    with pytest.raises(MarketDataError):
        normalize_ticker("")
    with pytest.raises(MarketDataError):
        normalize_ticker("TOOLONG123")
    with pytest.raises(MarketDataError):
        normalize_ticker("00593#")
    with pytest.raises(MarketDataError):
        normalize_ticker("abc")


class MockDummyProvider:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame
        self.call_count = 0

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.call_count += 1
        return self._frame


def test_true_reuse_mode_uses_persisted_actual_dates_without_provider_calls():
    """Verify Section 30: true reuse mode uses genuine persisted actual dates and makes 0 provider calls."""
    res = run_bounded_live_pilot(mode="reuse")
    summary = res["summary"]

    assert summary["final_verdict"] == "ACCEPT"
    assert summary["execution_provenance"]["execution_mode"] == "REUSE"
    assert summary["execution_provenance"]["new_live_request_count"] == 0
    assert summary["execution_provenance"]["reused_sample_count"] == 43


def test_reuse_mode_fails_closed_if_artifact_missing(tmp_path):
    """Verify Section 31: reuse mode fails closed if actual source dates artifact is missing."""
    empty_dir = tmp_path / "empty_pilot"
    empty_dir.mkdir()

    with pytest.raises(RuntimeError, match="REUSE_UNAVAILABLE"):
        run_bounded_live_pilot(output_dir=empty_dir, mode="reuse")


def test_suspension_authority_artifact_sha_and_records():
    """Verify Section 36: suspension authority artifact loads valid records and SHA256."""
    halts_map, sha = load_historical_suspension_authority(DEFAULT_SUSPENSION_AUTHORITY_PATH)
    assert len(sha) == 64
    assert "000030" in halts_map
    assert len(halts_map["000030"]) == 22
    assert "000060" in halts_map
    assert len(halts_map["000060"]) == 29
    assert "000360" in halts_map
    assert len(halts_map["000360"]) == 71
    assert "000470" in halts_map
    assert len(halts_map["000470"]) == 25
    assert "002670" in halts_map
    assert len(halts_map["002670"]) == 27
    assert "035720" in halts_map
    assert len(halts_map["035720"]) == 3


def test_no_circular_expected_mutation_and_pit_approximation_gap_fails():
    """Verify PIT approximation gap without independent evidence does NOT rewrite expected and fails FULL."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05", "2024-01-08"])
    frame = pd.DataFrame(
        {"open": [100.0] * 4, "high": [105.0] * 4, "low": [95.0] * 4, "close": [100.0] * 4},
        index=dates,
    )
    mock = MockDummyProvider(frame)
    sample = PilotSample(
        ticker="999999",
        isu_cd=["KR7999999001"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED,
        numeric_or_alpha="numeric",
        first_common_date="2024-01-02",
        last_common_date="2024-01-08",
        query_start="2024-01-02",
        query_end="2024-01-08",
        sample_reason="test",
        currently_common=False,
        historical_only=True,
    )
    resolution = ExpectedCoverageResolution(
        ticker="999999",
        query_start="2024-01-02",
        query_end="2024-01-08",
        authority_status=AuthorityStatus.VALID.value,
        authority_source="PIT_COMMON_INTERVAL_CALENDAR",
        authority_quality=AuthorityQuality.PIT_CALENDAR_APPROXIMATION.value,
        raw_observed_count=5,
        excluded_nontradable_count=0,
        expected_tradable_count=5,
        expected_tradable_dates=("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"),
        nontradable_dates=(),
        source_path="test",
    )

    res, act_dates = execute_single_pilot_query(sample, provider=mock, resolution=resolution)

    # 1. Expected resolution is NOT mutated to 4 dates
    assert res.expected_observation_count == 5
    assert resolution.expected_tradable_count == 5

    # 2. Missing is detected honestly
    assert res.missing_expected_count == 1
    assert res.coverage_status == CoverageStatus.INTERNAL_GAPS.value

    # 3. Not promoted to FULL
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_PARTIAL.value


def test_all_group_acceptance_gate_negative_controls():
    """Verify Section 29: evaluating acceptance fails if any group (A, B, C, D, E) or global metric fails."""
    def _dummy_res(group: str, status: str = "ELIGIBLE_FULL", missing: int = 0, unexpected: int = 0, auth_status: str = "VALID") -> PilotResult:
        return PilotResult(
            ticker="005930",
            isu_cd="KR7005930003",
            market="KOSPI",
            sample_group=group,
            numeric_or_alpha="numeric",
            source="PyKRX",
            adjusted=True,
            request_start="2024-01-02",
            request_end="2024-01-04",
            attempt_count=1,
            source_status="SUCCESS",
            coverage_status="FULL_EXPECTED_COVERAGE" if (missing == 0 and unexpected == 0) else "INTERNAL_GAPS",
            eligibility_status=status,
            expected_authority_status=auth_status,
            expected_authority_source="TEST",
            expected_authority_quality="TEST",
            raw_observed_count=3,
            excluded_nontradable_count=0,
            expected_observation_count=3,
            actual_source_row_count=3 if missing == 0 else 2,
            matched_expected_count=3 if missing == 0 else 2,
            missing_expected_count=missing,
            unexpected_source_date_count=unexpected,
            first_expected_date="2024-01-02",
            last_expected_date="2024-01-04",
            first_actual_date="2024-01-02",
            last_actual_date="2024-01-04",
            coverage_ratio=1.0 if missing == 0 else 0.67,
            duplicate_count=0,
            invalid_ohlc_count=0,
            future_row_count=0,
            error_type=None,
            error_message_sanitized=None,
            evidence_summary="test",
        )

    base_results = (
        [_dummy_res(PilotSampleGroup.GROUP_A_NUMERIC.value) for _ in range(8)]
        + [_dummy_res(PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED.value) for _ in range(5)]
        + [_dummy_res(PilotSampleGroup.GROUP_C_CORPORATE_ACTION.value) for _ in range(4)]
        + [_dummy_res(PilotSampleGroup.GROUP_D_ALPHA.value) for _ in range(23)]
        + [_dummy_res(PilotSampleGroup.GROUP_E_MARKET_TRANSFER.value) for _ in range(3)]
    )

    eval_pass = evaluate_pilot_acceptance(base_results)
    assert eval_pass["final_verdict"] == "ACCEPT"

    # 1. Group A inject failure
    res_fail_a = list(base_results)
    res_fail_a[0] = _dummy_res(PilotSampleGroup.GROUP_A_NUMERIC.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(res_fail_a)["final_verdict"] == "CHANGES_REQUESTED"

    # 2. Group B inject failure
    res_fail_b = list(base_results)
    res_fail_b[8] = _dummy_res(PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(res_fail_b)["final_verdict"] == "CHANGES_REQUESTED"

    # 3. Group C inject failure
    res_fail_c = list(base_results)
    res_fail_c[13] = _dummy_res(PilotSampleGroup.GROUP_C_CORPORATE_ACTION.value, status="ELIGIBLE_PARTIAL", unexpected=1)
    assert evaluate_pilot_acceptance(res_fail_c)["final_verdict"] == "CHANGES_REQUESTED"

    # 4. Group D inject failure (22/23)
    res_fail_d = list(base_results)
    res_fail_d[17] = _dummy_res(PilotSampleGroup.GROUP_D_ALPHA.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(res_fail_d)["final_verdict"] == "CHANGES_REQUESTED"

    # 5. Group E inject failure
    res_fail_e = list(base_results)
    res_fail_e[40] = _dummy_res(PilotSampleGroup.GROUP_E_MARKET_TRANSFER.value, status="ELIGIBLE_PARTIAL", auth_status="INSUFFICIENT_AUTHORITY")
    assert evaluate_pilot_acceptance(res_fail_e)["final_verdict"] == "CHANGES_REQUESTED"


def test_real_pilot_artifacts_integrity_and_acceptance():
    """Verify committed pilot artifacts match summary exactly and satisfy ACCEPT gate."""
    artifact_dir = Path("artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_bounded_live_pilot/v01")
    manifest_file = artifact_dir / "pilot_sample_manifest.json"
    results_file = artifact_dir / "pilot_results.csv"
    summary_file = artifact_dir / "pilot_summary.json"
    actual_dates_file = artifact_dir / "pilot_actual_source_dates.json"
    suspension_file = artifact_dir / "historical_suspension_authority_v01.json"

    assert manifest_file.exists()
    assert results_file.exists()
    assert summary_file.exists()
    assert actual_dates_file.exists()
    assert suspension_file.exists()

    with open(manifest_file, encoding="utf-8") as f:
        manifest_data = json.load(f)
    with open(summary_file, encoding="utf-8") as f:
        summary_data = json.load(f)
    with open(actual_dates_file, encoding="utf-8") as f:
        actual_dates_data = json.load(f)

    results_df = pd.read_csv(results_file)

    assert len(manifest_data) == 43 == len(results_df) == summary_data["sample_counts"]["total_samples"] == len(actual_dates_data["samples"])
    assert summary_data["final_verdict"] == "ACCEPT"
    assert summary_data["next_state"] == "READY_FOR_ADJUSTED_PRICE_STORE_FULL_POPULATION"
    assert summary_data["outcome_counts"]["eligible_full"] == 43
    assert summary_data["group_summaries"]["alpha_23_census"]["supported"] == 23
    assert summary_data["group_summaries"]["historical_delisted"]["supported"] == 5
    assert summary_data["group_summaries"]["corporate_action"]["supported"] == 4
    assert summary_data["group_summaries"]["market_transfer"]["supported"] == 3
    assert summary_data["coverage_totals"]["total_missing_expected_dates"] == 0
    assert summary_data["coverage_totals"]["total_unexpected_source_dates"] == 0
    assert summary_data["data_quality"]["total_duplicate_rows"] == 0
    assert summary_data["data_quality"]["total_invalid_ohlc_rows"] == 0
    assert summary_data["data_quality"]["total_future_rows"] == 0
