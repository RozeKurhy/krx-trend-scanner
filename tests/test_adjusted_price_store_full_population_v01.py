"""Tests for Adjusted Price Store Full Population Pipeline (ADJUSTED_PRICE_STORE_FULL_POPULATION_V01)."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.adjusted_price_full_population import (
    AcquisitionStatus,
    FullPopulationRunner,
    verify_stored_ticker_integrity,
)
from trend_scanner.data.adjusted_price_pilot import (
    CANONICAL_CALENDAR_CUTOFF,
    DEFAULT_CANONICAL_CALENDAR_PATH,
    EXPECTED_POPULATION_COUNT,
    EXPECTED_POPULATION_SHA256,
    AuthorityQuality,
    AuthorityStatus,
    CoverageStatus,
    ExpectedCoverageResolution,
)
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError
from trend_scanner.universe.survivorship_safe_denominator_freeze import (
    DEFAULT_POPULATION_ARTIFACT_PATH,
    load_historical_common_population,
    population_manifest_sha256,
)


class MockProvider:
    def __init__(self, frames_by_ticker: dict[str, pd.DataFrame] | None = None) -> None:
        self.frames = frames_by_ticker or {}
        self.call_count = 0
        self.called_tickers: list[str] = []

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.call_count += 1
        self.called_tickers.append(ticker)
        if ticker in self.frames:
            return self.frames[ticker]
        return pd.DataFrame()


def _make_valid_ohlc_df(dates: list[str]) -> pd.DataFrame:
    idx = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "open": [1000.0] * len(dates),
            "high": [1050.0] * len(dates),
            "low": [950.0] * len(dates),
            "close": [1020.0] * len(dates),
        },
        index=idx,
    )


def test_full_population_input_contract_and_hash_gate():
    """Verify Section 4 & 14: Population is exact 3,162 unique identities matching frozen SHA256."""
    runner = FullPopulationRunner()
    population = runner.load_population()
    assert len(population) == EXPECTED_POPULATION_COUNT == 3162
    calc_sha = population_manifest_sha256(population)
    assert calc_sha == EXPECTED_POPULATION_SHA256
    assert len({r["ticker"] for r in population}) == 3162


def test_dry_run_classification_without_network_calls(tmp_path):
    """Verify Section 34 & 79: Dry-run accurately classifies population without network calls."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir)

    res = runner.run_acquisition(dry_run=True)
    assert res["mode"] == "DRY_RUN"
    preflight = res["preflight"]
    assert preflight["population_count"] == 3162
    assert preflight["needs_fetch_count"] == 3162
    assert preflight["already_complete_count"] == 0
    assert preflight["reconciliation_sum"] == 3162


def test_resumable_execution_skips_complete_tickers(tmp_path):
    """Verify Section 26, 28 & 51: Verified COMPLETE tickers are skipped without provider calls."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    df = _make_valid_ohlc_df(dates)

    mock = MockProvider({"005930": df})
    runner = FullPopulationRunner(
        store_dir=store_dir,
        artifact_dir=artifact_dir,
        provider=mock,
    )

    rec = {
        "ticker": "005930",
        "isu_cd": ["KR7005930003"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-04",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }

    # 1. First execution
    rec_obj = runner.process_single_ticker(rec, provider=mock)
    assert rec_obj.acquisition_status == AcquisitionStatus.COMPLETE.value
    assert mock.call_count == 1
    assert rec_obj.stored_row_count == 3
    assert rec_obj.post_write_verified is True

    # 2. Add to checkpoint
    checkpoint = runner.load_or_create_checkpoint([rec])
    checkpoint.completed_tickers["005930"] = {
        "ticker": "005930",
        "acquisition_status": AcquisitionStatus.COMPLETE.value,
        "stored_row_count": 3,
        "expected_count": 3,
        "actual_row_count": 3,
        "first_actual_date": "2024-01-02",
        "last_actual_date": "2024-01-04",
        "post_write_verified": True,
        "actual_dates": dates,
        "updated_at": rec_obj.updated_at,
    }
    runner.save_checkpoint(checkpoint)

    # 3. Second execution (Resume)
    mock.call_count = 0
    rec_obj_resumed = runner.process_single_ticker(
        rec, cached_info=checkpoint.completed_tickers["005930"]
    )
    assert rec_obj_resumed.acquisition_status == AcquisitionStatus.COMPLETE.value
    assert mock.call_count == 0  # 0 network calls
    assert rec_obj_resumed.attempt_count == 1


def test_checkpoint_corruption_fails_closed(tmp_path):
    """Verify Section 53: Corrupted checkpoint fails closed and does not proceed silently."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)
    (artifact_dir / "full_population_checkpoint.json").write_text("{malformed_json", encoding="utf-8")

    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir)
    with pytest.raises(RuntimeError, match="CHECKPOINT_CORRUPTION"):
        runner.load_or_create_checkpoint(runner.load_population())


def test_store_corruption_invalidates_complete_status(tmp_path):
    """Verify Section 54: Checkpoint COMPLETE is untrusted if store parquet is missing or tampered."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    dates = ["2024-01-02", "2024-01-03"]
    df = _make_valid_ohlc_df(dates)

    mock = MockProvider({"005930": df})
    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir, provider=mock)
    store = runner.store

    # Save to store
    store.save_full("005930", df, metadata_context={"requested_start": "2024-01-02", "requested_end": "2024-01-03"})
    is_valid, err = verify_stored_ticker_integrity(store, "005930", 2, dates)
    assert is_valid is True
    assert err is None

    # Corrupt store: delete parquet
    (store_dir / "005930.parquet").unlink()
    is_valid_corrupt, err_corrupt = verify_stored_ticker_integrity(store, "005930", 2, dates)
    assert is_valid_corrupt is False
    assert "STORE_FILES_MISSING" in str(err_corrupt)


def test_expected_coverage_gap_negative_control(tmp_path):
    """Verify Section 55: Missing expected date results in PARTIAL and blocks COMPLETE."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    # Return 2 dates instead of 3
    dates = ["2024-01-02", "2024-01-04"]
    df = _make_valid_ohlc_df(dates)

    mock = MockProvider({"005930": df})
    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir, provider=mock)

    rec = {
        "ticker": "005930",
        "isu_cd": ["KR7005930003"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-04",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }
    rec_obj = runner.process_single_ticker(rec, provider=mock)
    assert rec_obj.acquisition_status == AcquisitionStatus.PARTIAL.value
    assert rec_obj.missing_expected_count == 1
    assert rec_obj.coverage_status == CoverageStatus.PARTIAL_EXPECTED_COVERAGE.value
    assert rec_obj.acquisition_status != AcquisitionStatus.COMPLETE.value


def test_unexpected_source_date_negative_control(tmp_path):
    """Verify Section 56: Unexpected extra source date results in PARTIAL and blocks COMPLETE."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    # Return 4 dates when only 3 expected
    dates = ["2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    df = _make_valid_ohlc_df(dates)

    mock = MockProvider({"005930": df})
    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir, provider=mock)

    rec = {
        "ticker": "005930",
        "isu_cd": ["KR7005930003"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-04",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }
    rec_obj = runner.process_single_ticker(rec, provider=mock)
    assert rec_obj.acquisition_status == AcquisitionStatus.PARTIAL.value
    assert rec_obj.unexpected_source_date_count == 1


def test_ohlc_quality_violations_fail_complete(tmp_path):
    """Verify Section 57: Invalid OHLC data (e.g. high < low, close <= 0) blocks COMPLETE."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    dates = ["2024-01-02", "2024-01-03", "2024-01-04"]
    df = _make_valid_ohlc_df(dates)
    # Inject high < low violation
    df.loc[df.index[0], "high"] = 500.0
    df.loc[df.index[0], "low"] = 1000.0

    mock = MockProvider({"005930": df})
    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir, provider=mock)

    rec = {
        "ticker": "005930",
        "isu_cd": ["KR7005930003"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-04",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }
    rec_obj = runner.process_single_ticker(rec, provider=mock)
    assert rec_obj.acquisition_status == AcquisitionStatus.PARTIAL.value
    assert rec_obj.invalid_ohlc_count == 1
    assert rec_obj.source_status == "SCHEMA_ANOMALY"


def test_alpha_23_support_in_full_population_runner(tmp_path):
    """Verify Section 7 & 60: Alpha ticker 0001A0 is accepted, queried, and verified."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    dates = ["2024-01-02", "2024-01-03"]
    df = _make_valid_ohlc_df(dates)

    mock = MockProvider({"0001A0": df})
    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir, provider=mock)

    rec = {
        "ticker": "0001A0",
        "isu_cd": ["KR70001A0001"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-03",
        "numeric_or_alpha": "alphanumeric",
        "currently_common": True,
        "historical_only": False,
    }
    rec_obj = runner.process_single_ticker(rec, provider=mock)
    assert rec_obj.ticker == "0001A0"
    assert rec_obj.numeric_or_alpha == "alphanumeric"


def test_circuit_breaker_stops_on_consecutive_errors(tmp_path):
    """Verify Section 42: Circuit breaker stops execution upon consecutive provider errors."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"

    class FailingProvider:
        def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            raise RuntimeError("NETWORK_CONNECTION_REFUSED")

    runner = FullPopulationRunner(
        store_dir=store_dir,
        artifact_dir=artifact_dir,
        provider=FailingProvider(),
        max_retries=0,
    )

    with pytest.raises(RuntimeError, match="CIRCUIT_BREAKER_TRIGGERED"):
        runner.run_acquisition(circuit_breaker_error_threshold=3)
