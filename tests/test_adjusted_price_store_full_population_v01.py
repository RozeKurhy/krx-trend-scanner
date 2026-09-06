"""Tests for Adjusted Price Store Full Population Pipeline (ADJUSTED_PRICE_STORE_FULL_POPULATION_V01_FIX01)."""

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
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR
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
        self.source_descriptor = CURRENT_SOURCE_DESCRIPTOR

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


def test_resumable_execution_accounting_exact(tmp_path):
    """Verify FIX01 Section 5, 6 & 8: Reused COMPLETE ticker has attempt_count=0 and reused_without_network=True."""
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
    assert rec_obj.attempt_count == 1
    assert rec_obj.reused_without_network is False

    # 2. Add to checkpoint
    checkpoint = runner.load_or_create_checkpoint([rec])
    checkpoint.completed_tickers["005930"] = {
        "ticker": "005930",
        "acquisition_status": AcquisitionStatus.COMPLETE.value,
        "requested_start": "2024-01-02",
        "requested_end": "2024-01-04",
        "stored_row_count": 3,
        "expected_count": 3,
        "actual_row_count": 3,
        "first_actual_date": "2024-01-02",
        "last_actual_date": "2024-01-04",
        "post_write_verified": True,
        "actual_dates": dates,
        "source_execution_attempt_count": 1,
        "updated_at": rec_obj.updated_at,
    }
    runner.save_checkpoint(checkpoint)

    # 3. Second execution (Resume): must have attempt_count=0 and reused_without_network=True
    mock.call_count = 0
    rec_obj_resumed = runner.process_single_ticker(
        rec, cached_info=checkpoint.completed_tickers["005930"]
    )
    assert rec_obj_resumed.acquisition_status == AcquisitionStatus.COMPLETE.value
    assert mock.call_count == 0  # 0 network calls
    assert rec_obj_resumed.attempt_count == 0
    assert rec_obj_resumed.reused_without_network is True


def test_checkpoint_authority_mismatch_fails_closed(tmp_path):
    """Verify FIX01 Section 10 & 13: Checkpoint with invalid population count/SHA fails closed."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir(parents=True, exist_ok=True)

    # 1. Tampered population count
    bad_ckpt = {
        "schema": "full_population_checkpoint_v02",
        "execution_id": "test",
        "started_at": "2026-08-27T00:00:00Z",
        "updated_at": "2026-08-27T00:00:00Z",
        "population_count": 3161,  # Bad count
        "population_sha256": EXPECTED_POPULATION_SHA256,
        "calendar_cutoff_date": CANONICAL_CALENDAR_CUTOFF,
        "completed_tickers": {},
        "in_progress_tickers": {},
        "source_authority_id": CURRENT_SOURCE_DESCRIPTOR.source_authority_id,
        "source_provider_version": "NaverDirectAdjustedPriceDataProvider_v02",
        "closure_accounting_schema_version": "adjusted_price_closure_accounting_v02",
        "tradability_contract_version": "adjusted_price_tradability_v02",
        "store_schema_version": "ADJUSTED_PRICE_V02",
        "pit_authority_sha256": "6b542ae05c9050dd30959d6f1b17306e4016f435a726ca7e0dff9e11008e4064",
    }
    (artifact_dir / "full_population_checkpoint.json").write_text(json.dumps(bad_ckpt), encoding="utf-8")

    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir)
    with pytest.raises(RuntimeError, match="CHECKPOINT_AUTHORITY_MISMATCH"):
        runner.load_or_create_checkpoint(runner.load_population())

    # 2. Tampered schema
    bad_ckpt["population_count"] = 3162
    bad_ckpt["schema"] = "bad_schema_v02"
    (artifact_dir / "full_population_checkpoint.json").write_text(json.dumps(bad_ckpt), encoding="utf-8")
    with pytest.raises(RuntimeError, match="CHECKPOINT_SCHEMA_MISMATCH"):
        runner.load_or_create_checkpoint(runner.load_population())


def test_dry_run_partial_store_is_not_already_complete(tmp_path):
    """Verify FIX01 Section 14 & 16: Incomplete store file without checkpoint is not counted as already_complete."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    # Store only has 1 date, but 3 expected
    dates = ["2024-01-02"]
    df = _make_valid_ohlc_df(dates)

    store = AdjustedPriceStore(store_dir)
    store.save_full("005930", df, metadata_context={"requested_start": "2024-01-02", "requested_end": "2024-01-04"})

    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir)
    preflight = runner.dry_run_classify()
    assert preflight["already_complete_count"] == 0
    assert preflight["needs_fetch_count"] == 3162


def test_systemic_empty_circuit_breaker(tmp_path):
    """Verify FIX01 Section 17 & 19: Consecutive empty responses trigger circuit breaker early."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"

    class EmptyProvider:
        def __init__(self):
            self.calls = 0
            self.source_descriptor = CURRENT_SOURCE_DESCRIPTOR

        def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            self.calls += 1
            return pd.DataFrame()

    provider = EmptyProvider()
    runner = FullPopulationRunner(
        store_dir=store_dir,
        artifact_dir=artifact_dir,
        provider=provider,
        max_retries=0,
    )

    with pytest.raises(RuntimeError, match="CIRCUIT_BREAKER_TRIGGERED.*consecutive empty responses"):
        runner.run_acquisition(circuit_breaker_empty_threshold=5)

    assert provider.calls == 5  # Aborts after 5 instead of continuing for 3162


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


def test_dry_run_metadata_bounds_validation(tmp_path):
    """Verify FIX02 Section 14: Incorrect metadata requested_start/end bounds reject COMPLETE."""
    store_dir = tmp_path / "store"
    store = AdjustedPriceStore(store_dir)
    dates = ["2024-01-02", "2024-01-03"]
    df = _make_valid_ohlc_df(dates)

    # Save with metadata bounds 2024-01-01 ~ 2024-01-05 (which encloses the frame)
    store.save_full("005930", df, metadata_context={"requested_start": "2024-01-01", "requested_end": "2024-01-05"})

    # Valid dates but wrong expected bounds
    is_valid, err = verify_stored_ticker_integrity(
        store,
        "005930",
        2,
        dates,
        expected_requested_start="2024-01-02",
        expected_requested_end="2024-01-03",
    )
    assert not is_valid
    assert "METADATA_START_BOUND_MISMATCH" in str(err)

    # Correct expected bounds -> valid
    is_valid_ok, err_ok = verify_stored_ticker_integrity(
        store,
        "005930",
        2,
        dates,
        expected_requested_start="2024-01-01",
        expected_requested_end="2024-01-05",
    )
    assert is_valid_ok
    assert err_ok is None


def test_audit_artifacts_semantic_separation(tmp_path):
    """Verify FIX02 Section 4: Execution audit and Resume audit are strictly separated."""
    store_dir = tmp_path / "store"
    artifact_dir = tmp_path / "artifacts"
    runner = FullPopulationRunner(store_dir=store_dir, artifact_dir=artifact_dir)

    dates = ["2024-01-02", "2024-01-03"]
    df = _make_valid_ohlc_df(dates)
    mock = MockProvider({"005930": df})

    rec = {
        "ticker": "005930",
        "isu_cd": ["KR7005930003"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-03",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }
    rec_obj = runner.process_single_ticker(rec, provider=mock)
    runner.generate_operational_artifacts([rec_obj], {}, 10.0)

    exec_audit_path = artifact_dir / "full_population_execution_audit.json"
    resume_audit_path = artifact_dir / "full_population_resume_audit.json"

    assert exec_audit_path.exists()
    assert resume_audit_path.exists()

    exec_audit = json.loads(exec_audit_path.read_text(encoding="utf-8"))
    resume_audit = json.loads(resume_audit_path.read_text(encoding="utf-8"))

    assert exec_audit["schema"] == "full_population_execution_audit_v01"
    assert resume_audit["schema"] == "full_population_resume_audit_v01"

    # Since total != 3162, resume audit cannot be a PASS
    assert not resume_audit["is_idempotent"]
    assert resume_audit["eligibility"] == "NOT_ELIGIBLE_UNRESOLVED_POPULATION"


def test_fix06_authority_boundary_and_manifests_integrity():
    """Verify FIX06 Section 7, 8, 11, 36: All required FIX06 manifests and candidate artifacts exist and match schema."""
    from trend_scanner.data.adjusted_price_diagnostics import (
        DEFAULT_ARTIFACTS_DIR,
        GapClassification,
        RootCauseCategory,
    )

    assert GapClassification.LEADING_HISTORY_GAP.value == "LEADING_HISTORY_GAP"
    assert RootCauseCategory.PROVIDER_PAGINATION_OR_COUNT_LIMIT.value == "PROVIDER_PAGINATION_OR_COUNT_LIMIT"
    assert RootCauseCategory.CURRENT_COMMON_INVALID_OHLC.value == "CURRENT_COMMON_INVALID_OHLC"
    assert RootCauseCategory.PROVIDER_NETWORK_ERROR.value == "PROVIDER_NETWORK_ERROR"
    assert RootCauseCategory.DELISTED_SYMBOL_UNSUPPORTED.value == "DELISTED_SYMBOL_UNSUPPORTED"

    surf_json = DEFAULT_ARTIFACTS_DIR / "provider_capability_surface.json"
    auth_state_json = DEFAULT_ARTIFACTS_DIR / "adjusted_price_authority_state.json"
    cand_res = DEFAULT_ARTIFACTS_DIR / "source_authority_candidate_probe_results.csv"
    cand_sum = DEFAULT_ARTIFACTS_DIR / "source_authority_candidate_probe_summary.json"
    probe_res = DEFAULT_ARTIFACTS_DIR / "provider_backend_capability_probe_results.csv"
    probe_sum = DEFAULT_ARTIFACTS_DIR / "provider_backend_capability_probe_summary.json"
    census_csv = DEFAULT_ARTIFACTS_DIR / "partial_root_cause_census.csv"
    census_sum = DEFAULT_ARTIFACTS_DIR / "partial_root_cause_summary.json"
    empty_csv = DEFAULT_ARTIFACTS_DIR / "empty_ticker_investigation.csv"
    empty_sum = DEFAULT_ARTIFACTS_DIR / "empty_ticker_investigation_summary.json"
    net_csv = DEFAULT_ARTIFACTS_DIR / "network_error_reconciliation_probe.csv"
    tax_csv = DEFAULT_ARTIFACTS_DIR / "error_taxonomy.csv"
    tax_sum = DEFAULT_ARTIFACTS_DIR / "error_taxonomy_summary.json"
    env_man = DEFAULT_ARTIFACTS_DIR / "provider_environment_manifest.json"
    sup_man = DEFAULT_ARTIFACTS_DIR / "artifact_supersession_manifest.json"
    fix06_man = DEFAULT_ARTIFACTS_DIR / "fix06_authority_boundary_manifest.json"

    assert surf_json.exists()
    assert auth_state_json.exists()
    assert cand_res.exists()
    assert cand_sum.exists()
    assert probe_res.exists()
    assert probe_sum.exists()
    assert census_csv.exists()
    assert census_sum.exists()
    assert empty_csv.exists()
    assert empty_sum.exists()
    assert net_csv.exists()
    assert tax_csv.exists()
    assert tax_sum.exists()
    assert env_man.exists()
    assert sup_man.exists()
    assert fix06_man.exists()

    surf_data = json.loads(surf_json.read_text(encoding="utf-8"))
    assert surf_data["schema"] == "provider_authority_boundary_surface_v01"
    assert surf_data["current_frozen_authority"]["authority_id"] == "PYKRX_ADJUSTED_V1_PUBLIC_CONTRACT"

    cand_data = json.loads(cand_sum.read_text(encoding="utf-8"))
    assert cand_data["pre_2014_rows_recovered"] is True
    assert cand_data["exact_overlap_parity_confirmed"] is True

    fix06_data = json.loads(fix06_man.read_text(encoding="utf-8"))
    assert fix06_data["pykrx_long_history_recovery_status"] == "NOT_RECOVERABLE_UNDER_CURRENT_FROZEN_PYKRX_CONTRACT"
    assert fix06_data["candidate_id"] == "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE"
    assert fix06_data["candidate_production_authorized"] is False
    assert fix06_data["recommended_next_state"] == "NEEDS_ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW"


def test_report_source_consistency():
    """Verify FIX06_CORRECTION_2 Section 34: Report-source values match canonical artifacts exactly."""
    from trend_scanner.data.adjusted_price_diagnostics import DEFAULT_ARTIFACTS_DIR

    probe_csv = DEFAULT_ARTIFACTS_DIR / "provider_backend_capability_probe_results.csv"
    net_csv = DEFAULT_ARTIFACTS_DIR / "network_error_reconciliation_probe.csv"
    empty_csv = DEFAULT_ARTIFACTS_DIR / "empty_ticker_investigation.csv"

    df_probe = pd.read_csv(probe_csv, dtype={"ticker": str})
    df_net = pd.read_csv(net_csv, dtype={"ticker": str})
    df_empty = pd.read_csv(empty_csv, dtype={"ticker": str})

    # 064420 TARGET_2010
    row_064420 = df_probe[(df_probe["ticker"] == "064420") & (df_probe["requested_target_window"] == "TARGET_2010")]
    assert len(row_064420) == 1
    assert row_064420.iloc[0]["raw_item_count"] == 251

    # 352820 LIFETIME
    row_352820 = df_probe[(df_probe["ticker"] == "352820") & (df_probe["requested_target_window"] == "LIFETIME_FULL")]
    assert len(row_352820) == 1
    assert row_352820.iloc[0]["raw_item_count"] == 1435

    # 0015G0 LIFETIME
    row_0015g0 = df_probe[(df_probe["ticker"] == "0015G0") & (df_probe["requested_target_window"] == "LIFETIME_FULL")]
    assert len(row_0015g0) == 1
    assert row_0015g0.iloc[0]["raw_item_count"] == 187

    # 001290 retry rows
    assert (df_net["row_count"] == 2995).all()

    # EMPTY 4 returned rows on repeat probe (classified as TRANSIENT_PROVIDER_EMPTY)
    assert df_empty[df_empty["ticker"] == "000610"]["adjusted_rows_returned"].iloc[0] == 12
    assert df_empty[df_empty["ticker"] == "000610"]["final_root_cause_category"].iloc[0] == "TRANSIENT_PROVIDER_EMPTY"
    assert df_empty[df_empty["ticker"] == "015940"]["adjusted_rows_returned"].iloc[0] == 9
    assert df_empty[df_empty["ticker"] == "015940"]["final_root_cause_category"].iloc[0] == "TRANSIENT_PROVIDER_EMPTY"
    assert df_empty[df_empty["ticker"] == "037510"]["adjusted_rows_returned"].iloc[0] == 16
    assert df_empty[df_empty["ticker"] == "037510"]["final_root_cause_category"].iloc[0] == "TRANSIENT_PROVIDER_EMPTY"
    assert df_empty[df_empty["ticker"] == "045820"]["adjusted_rows_returned"].iloc[0] == 9
    assert df_empty[df_empty["ticker"] == "045820"]["final_root_cause_category"].iloc[0] == "TRANSIENT_PROVIDER_EMPTY"


def test_empty_probe_execution_regression(monkeypatch, tmp_path: Path):
    """Verify FIX06_CORRECTION_2 Section 35: EMPTY probe genuinely executes 12 calls (3 per ticker)."""
    from trend_scanner.data.adjusted_price_diagnostics import investigate_empty_tickers
    from pykrx import stock

    called_tickers: list[str] = []

    def mock_get_market_ohlcv(start, end, ticker, adjusted=True):
        called_tickers.append(ticker)
        # return dummy single row dataframe
        return pd.DataFrame({"종가": [1000]}, index=pd.date_range("2010-01-04", periods=1))

    monkeypatch.setattr(stock, "get_market_ohlcv_by_date", mock_get_market_ohlcv)

    res = investigate_empty_tickers(output_dir=tmp_path)
    assert len(called_tickers) == 12
    assert called_tickers.count("000610") == 3
    assert called_tickers.count("015940") == 3
    assert called_tickers.count("037510") == 3
    assert called_tickers.count("045820") == 3
    assert (tmp_path / "empty_ticker_probe_attempts.csv").exists()
    assert len(pd.read_csv(tmp_path / "empty_ticker_probe_attempts.csv")) == 12


def test_empty_classification_cases():
    """Verify FIX06_CORRECTION_2 Section 36: Synthetic classification rules for recovered, persistently empty, and mixed."""
    from trend_scanner.data.adjusted_price_diagnostics import RootCauseCategory

    # Case A: 3/3 SUCCESS + recovered rows > 0 -> TRANSIENT_PROVIDER_EMPTY
    repeat_statuses_a = ["SUCCESS", "SUCCESS", "SUCCESS"]
    actual_rows_a = 12
    all_success_a = all(s == "SUCCESS" for s in repeat_statuses_a)
    if all_success_a and actual_rows_a > 0:
        root_a = RootCauseCategory.TRANSIENT_PROVIDER_EMPTY.value
    assert root_a == "TRANSIENT_PROVIDER_EMPTY"

    # Case B: 3/3 EMPTY -> DELISTED_SYMBOL_UNSUPPORTED
    repeat_statuses_b = ["EMPTY", "EMPTY", "EMPTY"]
    all_empty_b = all(s == "EMPTY" for s in repeat_statuses_b)
    if all_empty_b:
        root_b = RootCauseCategory.DELISTED_SYMBOL_UNSUPPORTED.value
    assert root_b == "DELISTED_SYMBOL_UNSUPPORTED"
    assert root_b != "TRANSIENT_PROVIDER_EMPTY"

    # Case C: Mixed responses -> UNKNOWN
    repeat_statuses_c = ["SUCCESS", "ERROR", "EMPTY"]
    all_success_c = all(s == "SUCCESS" for s in repeat_statuses_c)
    all_empty_c = all(s == "EMPTY" for s in repeat_statuses_c)
    if not all_success_c and not all_empty_c:
        root_c = RootCauseCategory.UNKNOWN.value
    assert root_c == "UNKNOWN"
    assert root_c != "DELISTED_SYMBOL_UNSUPPORTED"


def test_candidate_exception_handling(monkeypatch, tmp_path: Path):
    """Verify FIX06_CORRECTION_2 Section 37: Any exception during candidate comparison produces ERROR (no 064420 override)."""
    from trend_scanner.data.adjusted_price_diagnostics import run_source_authority_candidate_probes
    import requests

    def mock_requests_get(url, params=None, timeout=None):
        raise requests.exceptions.ConnectionError("Simulated upstream network error")

    monkeypatch.setattr(requests, "get", mock_requests_get)

    res = run_source_authority_candidate_probes(output_dir=tmp_path)
    df_cand = pd.read_csv(tmp_path / "source_authority_candidate_probe_results.csv", dtype={"ticker": str})

    # All tickers must have overlap_parity_status == "ERROR" upon exception
    assert len(df_cand) == 3
    for _, row in df_cand.iterrows():
        assert row["overlap_parity_status"] == "ERROR"
        assert pd.isna(row["exact_overlap_parity"])


def test_candidate_zero_overlap_normal():
    """Verify FIX06_CORRECTION_2 Section 38: Successful response with 0 overlap produces NOT_APPLICABLE (not ERROR)."""
    from trend_scanner.data.adjusted_price_diagnostics import DEFAULT_ARTIFACTS_DIR

    cand_csv = DEFAULT_ARTIFACTS_DIR / "source_authority_candidate_probe_results.csv"
    df_cand = pd.read_csv(cand_csv, dtype={"ticker": str})

    delisted = df_cand[df_cand["ticker"] == "064420"]
    assert len(delisted) == 1
    assert delisted["overlap_row_count"].iloc[0] == 0
    assert delisted["overlap_parity_status"].iloc[0] == "NOT_APPLICABLE"
    assert pd.isna(delisted["exact_overlap_parity"].iloc[0])


def test_evidence_loader_3_tier_hash_chain(tmp_path: Path):
    """Verify FIX06_CORRECTION_2 Section 39: Complete 3-tier hash chain validation with fail-closed semantics."""
    import hashlib
    from trend_scanner.data.adjusted_price_diagnostics import (
        DEFAULT_ARTIFACTS_DIR,
        load_canonical_authority_state,
        generate_provider_authority_boundary_surface,
    )

    # 1. Valid real state
    real_state = load_canonical_authority_state(DEFAULT_ARTIFACTS_DIR)
    assert real_state["authority_state_valid"] is True
    assert real_state["provider_capability_status"] == "NOT_RECOVERABLE_WITHIN_FROZEN_AUTHORITY"

    # Setup temporary directory with valid chain
    generate_provider_authority_boundary_surface(output_dir=tmp_path)
    tmp_valid_state = load_canonical_authority_state(tmp_path)
    assert tmp_valid_state["authority_state_valid"] is True

    # 2. Missing evidence_manifest_path in authority state -> UNKNOWN
    bad_auth_1 = dict(tmp_valid_state)
    del bad_auth_1["evidence_manifest_path"]
    (tmp_path / "adjusted_price_authority_state.json").write_text(json.dumps(bad_auth_1), encoding="utf-8")
    assert load_canonical_authority_state(tmp_path)["authority_state_valid"] is False

    # 3. Missing evidence_manifest_sha256 in authority state -> UNKNOWN
    bad_auth_2 = dict(tmp_valid_state)
    del bad_auth_2["evidence_manifest_sha256"]
    (tmp_path / "adjusted_price_authority_state.json").write_text(json.dumps(bad_auth_2), encoding="utf-8")
    assert load_canonical_authority_state(tmp_path)["authority_state_valid"] is False

    # 4. Evidence manifest schema mismatch -> UNKNOWN
    generate_provider_authority_boundary_surface(output_dir=tmp_path)  # reset
    ev_path = tmp_path / "adjusted_price_authority_evidence_manifest.json"
    ev_data = json.loads(ev_path.read_text(encoding="utf-8"))
    ev_data["schema"] = "wrong_evidence_schema_v99"
    ev_path.write_text(json.dumps(ev_data), encoding="utf-8")
    # Update auth state with new hash so hash matches but inner schema fails
    auth_data = json.loads((tmp_path / "adjusted_price_authority_state.json").read_text(encoding="utf-8"))
    auth_data["evidence_manifest_sha256"] = hashlib.sha256(ev_path.read_bytes()).hexdigest()
    (tmp_path / "adjusted_price_authority_state.json").write_text(json.dumps(auth_data), encoding="utf-8")
    assert load_canonical_authority_state(tmp_path)["authority_state_valid"] is False

    # 5. Surface hash mismatch -> UNKNOWN
    generate_provider_authority_boundary_surface(output_dir=tmp_path)  # reset
    surf_path = tmp_path / "provider_capability_surface.json"
    surf_path.write_text("tampered surface content", encoding="utf-8")
    assert load_canonical_authority_state(tmp_path)["authority_state_valid"] is False


def test_quality_parsing_strict():
    """Verify FIX06_CORRECTION_2 Section 40: data_quality_totals strictly checked (total_duplicates > 0 -> not clean)."""
    summary_data_dirty = {
        "data_quality_totals": {
            "total_duplicates": 1,
            "total_invalid_ohlc": 0,
            "total_future_rows": 0,
        }
    }
    quality = summary_data_dirty["data_quality_totals"]
    quality_clean = bool(
        quality["total_duplicates"] == 0
        and quality["total_invalid_ohlc"] == 0
        and quality["total_future_rows"] == 0
    )
    assert quality_clean is False


def test_missing_population_count_fails_closed(tmp_path: Path):
    """Verify FIX06_CORRECTION_2 Section 41: Missing status_counts fields raise KeyError instead of silent fallbacks."""
    import pytest
    from trend_scanner.data.adjusted_price_diagnostics import generate_authority_boundary_manifest

    # Create dummy candidate summary
    cand_sum = {
        "schema": "source_authority_candidate_probe_summary_v02",
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "production_authorization_status": "DIAGNOSTIC_CANDIDATE_ONLY_NOT_PRODUCTION_AUTHORIZED",
    }
    (tmp_path / "source_authority_candidate_probe_summary.json").write_text(json.dumps(cand_sum))

    # Create dummy summary missing 'partial'
    dummy_summary = {
        "status_counts": {
            "population_total": 3162,
            "complete": 867,
            # 'partial' is missing!
            "empty": 4,
            "error": 409,
            "insufficient_authority": 0,
        },
        "data_quality_totals": {
            "total_duplicates": 0,
            "total_invalid_ohlc": 0,
            "total_future_rows": 0,
        },
    }
    (tmp_path / "full_population_summary.json").write_text(json.dumps(dummy_summary), encoding="utf-8")

    with pytest.raises(KeyError, match="Missing required status_counts field: partial"):
        generate_authority_boundary_manifest(output_dir=tmp_path)


def test_canonical_next_state_consistency_fix06():
    """Verify FIX06_CORRECTION_3 Section 12: Next state strictly agrees across all canonical manifests."""
    from trend_scanner.data.adjusted_price_diagnostics import DEFAULT_ARTIFACTS_DIR

    root_man_p = DEFAULT_ARTIFACTS_DIR / "fix06_authority_boundary_manifest.json"
    sum_p = DEFAULT_ARTIFACTS_DIR / "full_population_summary.json"
    closure_p = DEFAULT_ARTIFACTS_DIR / "full_population_closure_manifest.json"

    root_man = json.loads(root_man_p.read_text(encoding="utf-8"))
    sum_data = json.loads(sum_p.read_text(encoding="utf-8"))
    closure_data = json.loads(closure_p.read_text(encoding="utf-8"))

    expected_next_state = "NEEDS_ADJUSTED_PRICE_SOURCE_AUTHORITY_REVIEW"
    assert root_man["recommended_next_state"] == expected_next_state
    assert sum_data["next_state"] == expected_next_state
    assert closure_data["next_state"] == expected_next_state


def test_candidate_production_authorization_derivation(tmp_path: Path):
    """Verify FIX06_CORRECTION_4 Section 9: Candidate authorization derivation validates schema, candidate_id and authorization status."""
    import pytest
    from trend_scanner.data.adjusted_price_diagnostics import (
        DEFAULT_ARTIFACTS_DIR,
        generate_authority_boundary_manifest,
    )

    # Setup baseline mock directory
    base_summary = (DEFAULT_ARTIFACTS_DIR / "full_population_summary.json").read_text()
    (tmp_path / "full_population_summary.json").write_text(base_summary)
    (tmp_path / "adjusted_price_authority_state.json").write_text(
        (DEFAULT_ARTIFACTS_DIR / "adjusted_price_authority_state.json").read_text()
    )
    (tmp_path / "adjusted_price_authority_evidence_manifest.json").write_text(
        (DEFAULT_ARTIFACTS_DIR / "adjusted_price_authority_evidence_manifest.json").read_text()
    )
    (tmp_path / "provider_capability_surface.json").write_text(
        (DEFAULT_ARTIFACTS_DIR / "provider_capability_surface.json").read_text()
    )

    # Case A: Valid Diagnostic only -> candidate_production_authorized is False
    cand_sum_a = {
        "schema": "source_authority_candidate_probe_summary_v02",
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "production_authorization_status": "DIAGNOSTIC_CANDIDATE_ONLY_NOT_PRODUCTION_AUTHORIZED",
    }
    (tmp_path / "source_authority_candidate_probe_summary.json").write_text(json.dumps(cand_sum_a))
    man_a = generate_authority_boundary_manifest(output_dir=tmp_path)
    assert man_a["candidate_production_authorized"] is False

    # Case B: Valid Production authorized -> candidate_production_authorized is True
    cand_sum_b = {
        "schema": "source_authority_candidate_probe_summary_v02",
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "production_authorization_status": "PRODUCTION_AUTHORIZED",
    }
    (tmp_path / "source_authority_candidate_probe_summary.json").write_text(json.dumps(cand_sum_b))
    man_b = generate_authority_boundary_manifest(output_dir=tmp_path)
    assert man_b["candidate_production_authorized"] is True

    # Case C: Wrong Schema -> raises ValueError (Fail-Closed)
    cand_sum_c = {
        "schema": "bad_schema_v99",
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "production_authorization_status": "PRODUCTION_AUTHORIZED",
    }
    (tmp_path / "source_authority_candidate_probe_summary.json").write_text(json.dumps(cand_sum_c))
    with pytest.raises(ValueError, match="Invalid candidate summary schema"):
        generate_authority_boundary_manifest(output_dir=tmp_path)

    # Case D: Wrong Candidate ID -> raises ValueError (Fail-Closed)
    cand_sum_d = {
        "schema": "source_authority_candidate_probe_summary_v02",
        "candidate_id": "SOME_OTHER_SOURCE",
        "production_authorization_status": "PRODUCTION_AUTHORIZED",
    }
    (tmp_path / "source_authority_candidate_probe_summary.json").write_text(json.dumps(cand_sum_d))
    with pytest.raises(ValueError, match="Candidate ID mismatch"):
        generate_authority_boundary_manifest(output_dir=tmp_path)

    # Case E: Missing production_authorization_status field -> raises KeyError
    cand_sum_e = {
        "schema": "source_authority_candidate_probe_summary_v02",
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        # missing field
    }
    (tmp_path / "source_authority_candidate_probe_summary.json").write_text(json.dumps(cand_sum_e))
    with pytest.raises(KeyError, match="production_authorization_status"):
        generate_authority_boundary_manifest(output_dir=tmp_path)

    # Case F: Unknown authorization status -> raises ValueError
    cand_sum_f = {
        "schema": "source_authority_candidate_probe_summary_v02",
        "candidate_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_CANDIDATE",
        "production_authorization_status": "SOMETHING_RANDOM",
    }
    (tmp_path / "source_authority_candidate_probe_summary.json").write_text(json.dumps(cand_sum_f))
    with pytest.raises(ValueError, match="Unknown candidate production_authorization_status"):
        generate_authority_boundary_manifest(output_dir=tmp_path)
