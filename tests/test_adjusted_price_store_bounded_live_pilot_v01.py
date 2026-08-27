"""Contract tests for AdjustedPriceStore Bounded Live Pilot v01 (ADJUSTED_PRICE_STORE_BOUNDED_LIVE_PILOT_V01)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_pilot import (
    EXPECTED_POPULATION_COUNT,
    EXPECTED_POPULATION_SHA256,
    PilotLiveAdjustedPriceProvider,
    PilotResult,
    PilotSample,
    PilotSampleGroup,
    SourceEligibilityStatus,
    build_pilot_sample_manifest,
    execute_single_pilot_query,
    run_bounded_live_pilot,
)
from trend_scanner.data.adjusted_price_provider import (
    AdjustedPriceDataProvider,
    normalize_ticker,
    validate_adjusted_ohlc,
)
from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
    load_historical_common_population,
    population_manifest_sha256,
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PILOT_ARTIFACTS_DIR = (
    ROOT
    / "artifacts/data/end_to_end_data_parity/v01"
    / "adjusted_price_store_bounded_live_pilot/v01"
)


# ---------------------------------------------------------------------------
# Section 39: FROZEN HASH GATE
# ---------------------------------------------------------------------------


def test_frozen_population_hash_gate_passes() -> None:
    records = load_historical_common_population(ROOT / DEFAULT_POPULATION_ARTIFACT_PATH)
    assert len(records) == EXPECTED_POPULATION_COUNT
    assert population_manifest_sha256(records) == EXPECTED_POPULATION_SHA256


def test_frozen_population_hash_gate_fails_on_tampered_artifact(tmp_path: Path) -> None:
    tampered_file = tmp_path / "tampered_population.json"
    tampered_payload = {
        "records": [
            {
                "ticker": "999999",
                "isu_cd": ["KR9999990001"],
                "market": ["KOSPI"],
                "numeric_or_alpha": "numeric",
                "first_common_date": "2020-01-01",
                "last_common_date": "2020-12-31",
                "common_interval_count": 1,
            }
        ]
    }
    tampered_file.write_text(json.dumps(tampered_payload), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Population manifest SHA mismatch"):
        build_pilot_sample_manifest(population_path=tampered_file)


# ---------------------------------------------------------------------------
# Section 40: UNIVERSE IMMUTABILITY
# ---------------------------------------------------------------------------


def test_universe_immutability_preserved_even_if_source_unsupported() -> None:
    """Source eligibility outcomes must never alter or mutate the frozen population count."""
    manifest = build_pilot_sample_manifest(ROOT / DEFAULT_POPULATION_ARTIFACT_PATH)
    assert len(manifest) >= 40

    # Ensure all samples are from frozen population
    pop_records = load_historical_common_population(ROOT / DEFAULT_POPULATION_ARTIFACT_PATH)
    pop_tickers = {r["ticker"] for r in pop_records}
    for sample in manifest:
        assert sample.ticker in pop_tickers


# ---------------------------------------------------------------------------
# Section 41: ALPHA SUPPORT CLASSIFICATION
# ---------------------------------------------------------------------------


def test_alpha_support_classification_mock() -> None:
    sample = PilotSample(
        ticker="0008Z0",
        isu_cd=["KR70008Z0005"],
        market=["KOSDAQ"],
        sample_group=PilotSampleGroup.GROUP_D_ALPHA,
        numeric_or_alpha="alphanumeric",
        first_common_date="2025-08-19",
        last_common_date="2026-08-21",
        query_start="2025-08-19",
        query_end="2026-08-21",
        sample_reason="test",
        currently_common=True,
        historical_only=False,
    )

    # 1. Success mock
    mock_provider_success = MagicMock(spec=AdjustedPriceDataProvider)
    valid_df = pd.DataFrame(
        {
            "open": [1000.0, 1010.0],
            "high": [1020.0, 1030.0],
            "low": [990.0, 1000.0],
            "close": [1010.0, 1020.0],
        },
        index=pd.DatetimeIndex(["2025-08-19", "2025-08-20"]),
    )
    mock_provider_success.load_daily.return_value = valid_df
    res_success = execute_single_pilot_query(sample, provider=mock_provider_success)
    assert res_success.source_status == "SUCCESS"
    assert res_success.eligibility_status == SourceEligibilityStatus.ELIGIBLE_FULL.value
    assert res_success.row_count == 2

    # 2. Empty mock
    mock_provider_empty = MagicMock(spec=AdjustedPriceDataProvider)
    mock_provider_empty.load_daily.return_value = pd.DataFrame()
    res_empty = execute_single_pilot_query(sample, provider=mock_provider_empty)
    assert res_empty.source_status == "EMPTY"
    assert res_empty.eligibility_status == SourceEligibilityStatus.INELIGIBLE_SOURCE_EMPTY.value
    assert res_empty.row_count == 0

    # 3. Error mock
    mock_provider_error = MagicMock(spec=AdjustedPriceDataProvider)
    mock_provider_error.load_daily.side_effect = MarketDataError("Network timeout")
    res_error = execute_single_pilot_query(sample, provider=mock_provider_error, max_retries=0)
    assert res_error.source_status == "ERROR"
    assert res_error.eligibility_status == SourceEligibilityStatus.SOURCE_TRANSIENT_ERROR.value


# ---------------------------------------------------------------------------
# Section 42: DELISTED HISTORICAL QUERY
# ---------------------------------------------------------------------------


def test_delisted_historical_query_semantics() -> None:
    sample = PilotSample(
        ticker="000060",
        isu_cd=["KR7000060002"],
        market=["KOSPI"],
        sample_group=PilotSampleGroup.GROUP_B_HISTORICAL_DELISTED,
        numeric_or_alpha="numeric",
        first_common_date="2010-12-20",
        last_common_date="2023-02-20",
        query_start="2010-12-20",
        query_end="2023-02-20",
        sample_reason="test delisted",
        currently_common=False,
        historical_only=True,
    )
    mock_provider = MagicMock(spec=AdjustedPriceDataProvider)
    valid_df = pd.DataFrame(
        {
            "open": [5000.0],
            "high": [5100.0],
            "low": [4900.0],
            "close": [5050.0],
        },
        index=pd.DatetimeIndex(["2010-12-20"]),
    )
    mock_provider.load_daily.return_value = valid_df
    res = execute_single_pilot_query(sample, provider=mock_provider)
    assert res.source_status == "SUCCESS"
    assert res.eligibility_status == SourceEligibilityStatus.ELIGIBLE_FULL.value


# ---------------------------------------------------------------------------
# Section 43: NO RAW OHLC FALLBACK
# ---------------------------------------------------------------------------


def test_no_raw_ohlc_fallback() -> None:
    """If adjusted source fails, fail closed without silently substituting raw OHLC."""
    provider = AdjustedPriceDataProvider()
    with patch("pykrx.stock.get_market_ohlcv_by_date", side_effect=Exception("API failure")):
        with pytest.raises(MarketDataError, match="PyKRX adjusted=True 조회 실패"):
            provider.load_daily("005930", "2024-01-02", "2024-01-05")


# ---------------------------------------------------------------------------
# Section 45: OHLC INVARIANTS
# ---------------------------------------------------------------------------


def test_ohlc_invariants_validation() -> None:
    # High < Low violation
    bad_high_low = pd.DataFrame(
        {
            "open": [1000.0],
            "high": [900.0],
            "low": [950.0],
            "close": [920.0],
        },
        index=pd.DatetimeIndex(["2024-01-02"]),
    )
    with pytest.raises(MarketDataError, match="수정주가 OHLC 관계가 깨졌습니다"):
        validate_adjusted_ohlc(bad_high_low)

    # Close <= 0 violation
    bad_zero_close = pd.DataFrame(
        {
            "open": [1000.0],
            "high": [1000.0],
            "low": [0.0],
            "close": [0.0],
        },
        index=pd.DatetimeIndex(["2024-01-02"]),
    )
    with pytest.raises(MarketDataError, match="0 이하의 가격"):
        validate_adjusted_ohlc(bad_zero_close)


def test_pilot_provider_supports_alphanumeric_and_numeric() -> None:
    provider = PilotLiveAdjustedPriceProvider()
    with patch("pykrx.stock.get_market_ohlcv_by_date", return_value=pd.DataFrame()):
        res_numeric = provider.load_daily("005930", "2024-01-02", "2024-01-03")
        assert res_numeric.empty
        res_alpha = provider.load_daily("0008Z0", "2025-08-19", "2026-08-21")
        assert res_alpha.empty

    with pytest.raises(MarketDataError):
        provider.load_daily("", "2024-01-02", "2024-01-03")
    with pytest.raises(MarketDataError):
        provider.load_daily("TOOLONG123", "2024-01-02", "2024-01-03")


# ---------------------------------------------------------------------------
# Real Artifact Verification
# ---------------------------------------------------------------------------


def test_real_pilot_artifacts_integrity_and_verdict() -> None:
    manifest_path = DEFAULT_PILOT_ARTIFACTS_DIR / "pilot_sample_manifest.json"
    results_path = DEFAULT_PILOT_ARTIFACTS_DIR / "pilot_results.csv"
    summary_path = DEFAULT_PILOT_ARTIFACTS_DIR / "pilot_summary.json"

    assert manifest_path.exists()
    assert results_path.exists()
    assert summary_path.exists()

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["final_verdict"] == "ACCEPT"
    assert summary["status"] == "PILOT_COMPLETED"
    assert summary["next_state"] == "READY_FOR_ADJUSTED_PRICE_STORE_FULL_POPULATION"

    assert summary["frozen_authority"]["population_count"] == 3162
    assert summary["frozen_authority"]["population_manifest_sha256"] == EXPECTED_POPULATION_SHA256
    assert summary["frozen_authority"]["population_mutated"] is False

    assert summary["sample_counts"]["total_samples"] == 43
    assert summary["sample_counts"]["group_d_alpha"] == 23
    assert summary["sample_counts"]["group_b_historical_delisted"] == 5

    assert summary["outcome_counts"]["success"] == 43
    assert summary["outcome_counts"]["empty"] == 0
    assert summary["outcome_counts"]["error"] == 0

    assert summary["group_summaries"]["alpha_23_census"]["supported"] == 23
    assert summary["group_summaries"]["historical_delisted"]["supported"] == 5

    assert summary["data_quality"]["total_duplicate_rows"] == 0
    assert summary["data_quality"]["total_invalid_ohlc_rows"] == 0
    assert summary["data_quality"]["total_future_rows"] == 0
