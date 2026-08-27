"""Tests for Adjusted Price Store Bounded Live Pilot (FIX01)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_pilot import (
    EXPECTED_POPULATION_COUNT,
    EXPECTED_POPULATION_SHA256,
    CoverageStatus,
    PilotResult,
    PilotSample,
    PilotSampleGroup,
    SourceEligibilityStatus,
    SourceResponseStatus,
    build_pilot_sample_manifest,
    execute_single_pilot_query,
    resolve_expected_observation_dates,
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


def test_sample_authority_assertions_group_b_rejects_current_common(tmp_path):
    """Verify Group B sample authority strictly rejects currently-common tickers like 001040."""
    manifest = build_pilot_sample_manifest()
    group_b_samples = [s for s in manifest if s.sample_group == PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED]
    assert len(group_b_samples) == 5

    # Ensure 001040 is not in Group B
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
        normalize_ticker("abc")  # lowercase rejected or invalid length


class MockDummyProvider:
    def __init__(self, frame: pd.DataFrame):
        self._frame = frame

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        return self._frame


def test_coverage_classifier_partial_when_expected_dates_missing():
    """Verify fixture with 5 expected dates and 3 returned rows is classified as PARTIAL."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"])
    frame = pd.DataFrame(
        {"open": [100.0, 101.0, 102.0], "high": [105.0, 106.0, 107.0], "low": [99.0, 100.0, 101.0], "close": [104.0, 105.0, 106.0]},
        index=dates,
    )
    mock = MockDummyProvider(frame)
    sample = PilotSample(
        ticker="005930",
        isu_cd=["KR7005930003"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_A_NUMERIC,
        numeric_or_alpha="numeric",
        first_common_date="2010-01-04",
        last_common_date="2026-08-21",
        query_start="2024-01-02",
        query_end="2024-01-08",
        sample_reason="test",
        currently_common=True,
        historical_only=False,
    )
    expected_dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05", "2024-01-08"]
    res = execute_single_pilot_query(sample, provider=mock, expected_dates=expected_dates)

    assert res.coverage_status == CoverageStatus.SOURCE_ENDS_EARLY.value
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_PARTIAL.value
    assert res.missing_expected_count == 2
    assert res.coverage_ratio == 0.6


def test_coverage_classifier_full_when_request_window_wider_than_expected():
    """Verify request Jan 1 ~ Jan 31 with official expected Jan 10 ~ Jan 20 matching is FULL."""
    dates = pd.to_datetime(["2024-01-10", "2024-01-11", "2024-01-12"])
    frame = pd.DataFrame(
        {"open": [100.0, 101.0, 102.0], "high": [105.0, 106.0, 107.0], "low": [99.0, 100.0, 101.0], "close": [104.0, 105.0, 106.0]},
        index=dates,
    )
    mock = MockDummyProvider(frame)
    sample = PilotSample(
        ticker="005930",
        isu_cd=["KR7005930003"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_A_NUMERIC,
        numeric_or_alpha="numeric",
        first_common_date="2024-01-10",
        last_common_date="2024-01-12",
        query_start="2024-01-01",
        query_end="2024-01-31",
        sample_reason="test",
        currently_common=True,
        historical_only=False,
    )
    expected_dates = ["2024-01-10", "2024-01-11", "2024-01-12"]
    res = execute_single_pilot_query(sample, provider=mock, expected_dates=expected_dates)

    assert res.coverage_status == CoverageStatus.FULL_EXPECTED_COVERAGE.value
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_FULL.value
    assert res.missing_expected_count == 0
    assert res.coverage_ratio == 1.0


def test_coverage_classifier_internal_gaps():
    """Verify missing intermediate expected date results in INTERNAL_GAPS."""
    dates = pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-05"])
    frame = pd.DataFrame(
        {"open": [100.0, 101.0, 102.0], "high": [105.0, 106.0, 107.0], "low": [99.0, 100.0, 101.0], "close": [104.0, 105.0, 106.0]},
        index=dates,
    )
    mock = MockDummyProvider(frame)
    sample = PilotSample(
        ticker="005930",
        isu_cd=["KR7005930003"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_A_NUMERIC,
        numeric_or_alpha="numeric",
        first_common_date="2024-01-02",
        last_common_date="2024-01-05",
        query_start="2024-01-02",
        query_end="2024-01-05",
        sample_reason="test",
        currently_common=True,
        historical_only=False,
    )
    expected_dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    res = execute_single_pilot_query(sample, provider=mock, expected_dates=expected_dates)

    assert res.coverage_status == CoverageStatus.INTERNAL_GAPS.value
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_PARTIAL.value
    assert res.missing_expected_count == 1


def test_real_pilot_artifacts_integrity_and_acceptance(tmp_path):
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
    assert summary_data["data_quality"]["total_duplicate_rows"] == 0
    assert summary_data["data_quality"]["total_invalid_ohlc_rows"] == 0
    assert summary_data["data_quality"]["total_future_rows"] == 0
