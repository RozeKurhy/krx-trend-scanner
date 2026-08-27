"""Tests for Adjusted Price Store Bounded Live Pilot (FIX02)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_pilot import (
    EXPECTED_POPULATION_COUNT,
    EXPECTED_POPULATION_SHA256,
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
    resolve_expected_coverage,
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

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        return self._frame


def test_expected_zero_actual_positive_is_not_full():
    """Verify Section 40: expected=0 and actual>0 is UNEXPECTED_SOURCE_ONLY and NOT ELIGIBLE_FULL."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    frame = pd.DataFrame(
        {"open": [100.0, 101.0], "high": [105.0, 106.0], "low": [99.0, 100.0], "close": [104.0, 105.0]},
        index=dates,
    )
    mock = MockDummyProvider(frame)
    sample = PilotSample(
        ticker="005930",
        isu_cd=["KR7005930003"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_C_CORPORATE_ACTION,
        numeric_or_alpha="numeric",
        first_common_date="2010-01-04",
        last_common_date="2026-08-21",
        query_start="2024-01-02",
        query_end="2024-01-03",
        sample_reason="test",
        currently_common=True,
        historical_only=False,
    )
    resolution = ExpectedCoverageResolution(
        ticker="005930",
        query_start="2024-01-02",
        query_end="2024-01-03",
        authority_status=AuthorityStatus.VALID.value,
        authority_source="TEST",
        authority_quality="TEST",
        raw_observed_count=0,
        excluded_nontradable_count=0,
        expected_tradable_count=0,
        expected_tradable_dates=[],
        nontradable_dates=[],
        source_path="test",
    )
    res = execute_single_pilot_query(sample, provider=mock, resolution=resolution)

    assert res.coverage_status == CoverageStatus.UNEXPECTED_SOURCE_ONLY.value
    assert res.eligibility_status != SourceEligibilityStatus.ELIGIBLE_FULL.value
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_PARTIAL.value
    assert res.unexpected_source_date_count == 2


def test_coverage_resolver_failure_returns_insufficient_authority(tmp_path):
    """Verify Section 41: broken resolver returns INSUFFICIENT_AUTHORITY and never silent []."""
    fake_empty_dir = tmp_path / "empty_stocks"
    fake_empty_dir.mkdir()
    res = resolve_expected_coverage("999999", "2024-01-02", "2024-01-05", stocks_dir=fake_empty_dir, pit_path=tmp_path / "nonexistent.json")

    assert res.authority_status == AuthorityStatus.INSUFFICIENT_AUTHORITY.value
    assert res.expected_tradable_count == 0


def test_group_b_no_blanket_exemption_missing_is_partial():
    """Verify Section 42: Group B with missing tradable date is ELIGIBLE_PARTIAL, not FULL."""
    dates = pd.to_datetime(["2010-01-04", "2010-01-05", "2010-01-06"])
    frame = pd.DataFrame(
        {"open": [100.0, 101.0, 102.0], "high": [105.0, 106.0, 107.0], "low": [99.0, 100.0, 101.0], "close": [104.0, 105.0, 106.0]},
        index=dates,
    )
    mock = MockDummyProvider(frame)
    sample = PilotSample(
        ticker="000030",
        isu_cd=["KR7000030007"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED,
        numeric_or_alpha="numeric",
        first_common_date="2010-01-04",
        last_common_date="2019-02-12",
        query_start="2010-01-04",
        query_end="2010-01-07",
        sample_reason="test",
        currently_common=False,
        historical_only=True,
    )
    resolution = ExpectedCoverageResolution(
        ticker="000030",
        query_start="2010-01-04",
        query_end="2010-01-07",
        authority_status=AuthorityStatus.VALID.value,
        authority_source="TEST",
        authority_quality="TEST",
        raw_observed_count=4,
        excluded_nontradable_count=0,
        expected_tradable_count=4,
        expected_tradable_dates=["2010-01-04", "2010-01-05", "2010-01-06", "2010-01-07"],
        nontradable_dates=[],
        source_path="test",
    )
    res = execute_single_pilot_query(sample, provider=mock, resolution=resolution)

    assert res.coverage_status == CoverageStatus.SOURCE_ENDS_EARLY.value
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_PARTIAL.value
    assert res.missing_expected_count == 1


def test_suspension_aware_expected_dates_excludes_phantom_rows(tmp_path):
    """Verify Section 43: suspension rows (open=0, high=0, low=0, close>0) are excluded from tradable expected dates."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    raw_df = pd.DataFrame(
        {
            "open": [100.0, 0.0, 102.0],
            "high": [105.0, 0.0, 107.0],
            "low": [99.0, 0.0, 101.0],
            "close": [104.0, 104.0, 106.0],
        },
        index=dates,
    )
    stock_dir = tmp_path / "stocks"
    stock_dir.mkdir()
    raw_df.to_parquet(stock_dir / "005930.parquet")

    resolution = resolve_expected_coverage("005930", "2024-01-02", "2024-01-04", stocks_dir=stock_dir)

    assert resolution.authority_status == AuthorityStatus.VALID.value
    assert resolution.raw_observed_count == 3
    assert resolution.excluded_nontradable_count == 1
    assert resolution.expected_tradable_count == 2
    assert resolution.expected_tradable_dates == ["2024-01-02", "2024-01-04"]
    assert resolution.nontradable_dates == ["2024-01-03"]


def test_all_group_acceptance_gate_negative_controls():
    """Verify Section 46: evaluating acceptance fails if any group has a non-full or missing sample."""
    def _dummy_res(group: str, status: str = "ELIGIBLE_FULL", missing: int = 0) -> PilotResult:
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
            coverage_status="FULL_EXPECTED_COVERAGE" if missing == 0 else "INTERNAL_GAPS",
            eligibility_status=status,
            expected_authority_status="VALID",
            expected_authority_source="TEST",
            raw_observed_count=3,
            excluded_nontradable_count=0,
            expected_observation_count=3,
            actual_source_row_count=3 if missing == 0 else 2,
            matched_expected_count=3 if missing == 0 else 2,
            missing_expected_count=missing,
            unexpected_source_date_count=0,
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

    # Base valid results (8 A, 5 B, 4 C, 23 D, 3 E)
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
    results_fail_a = list(base_results)
    results_fail_a[0] = _dummy_res(PilotSampleGroup.GROUP_A_NUMERIC.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(results_fail_a)["final_verdict"] == "CHANGES_REQUESTED"

    # 2. Group B inject failure
    results_fail_b = list(base_results)
    results_fail_b[8] = _dummy_res(PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(results_fail_b)["final_verdict"] == "CHANGES_REQUESTED"

    # 3. Group D inject failure (22/23)
    results_fail_d = list(base_results)
    results_fail_d[17] = _dummy_res(PilotSampleGroup.GROUP_D_ALPHA.value, status="ELIGIBLE_PARTIAL", missing=1)
    assert evaluate_pilot_acceptance(results_fail_d)["final_verdict"] == "CHANGES_REQUESTED"


def test_real_pilot_artifacts_integrity_and_acceptance():
    """Verify committed pilot artifacts match summary exactly and satisfy ACCEPT gate."""
    artifact_dir = Path("artifacts/data/end_to_end_data_parity/v01/adjusted_price_store_bounded_live_pilot/v01")
    manifest_file = artifact_dir / "pilot_sample_manifest.json"
    results_file = artifact_dir / "pilot_results.csv"
    summary_file = artifact_dir / "pilot_summary.json"

    assert manifest_file.exists()
    assert results_file.exists()
    assert summary_file.exists()

    with open(manifest_file, encoding="utf-8") as f:
        manifest_data = json.load(f)
    with open(summary_file, encoding="utf-8") as f:
        summary_data = json.load(f)
    results_df = pd.read_csv(results_file)

    assert len(manifest_data) == 43 == len(results_df) == summary_data["sample_counts"]["total_samples"]
    assert summary_data["final_verdict"] == "ACCEPT"
    assert summary_data["next_state"] == "READY_FOR_ADJUSTED_PRICE_STORE_FULL_POPULATION"
    assert summary_data["outcome_counts"]["eligible_full"] == 43
    assert summary_data["group_summaries"]["alpha_23_census"]["supported"] == 23
    assert summary_data["group_summaries"]["historical_delisted"]["supported"] == 5
    assert summary_data["coverage_totals"]["total_missing_expected_dates"] == 0
    assert summary_data["coverage_totals"]["total_unexpected_source_dates"] == 0
    assert summary_data["data_quality"]["total_duplicate_rows"] == 0
    assert summary_data["data_quality"]["total_invalid_ohlc_rows"] == 0
    assert summary_data["data_quality"]["total_future_rows"] == 0
