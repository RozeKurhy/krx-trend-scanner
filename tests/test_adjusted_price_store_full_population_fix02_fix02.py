"""FIX02_FIX02 orchestration and closure-accounting tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data import adjusted_price_full_population as population_module
from trend_scanner.data.adjusted_price_full_population import (
    AcquisitionStatus,
    CLOSURE_SUCCESS_STATUSES,
    FullPopulationRunner,
    TickerAcquisitionRecord,
    compute_true_resume_pass,
    is_closure_success,
    validate_terminal_success_evidence,
    validate_operational_artifact_invariants,
)
from trend_scanner.data.adjusted_price_pilot import (
    AuthorityQuality,
    AuthorityStatus,
    CoverageStatus,
    ExpectedCoverageResolution,
)
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR


def _resolution(ticker: str, *, expected: tuple[str, ...] = (), nontrading: tuple[str, ...] = ()):
    return ExpectedCoverageResolution(
        ticker=ticker,
        query_start="2024-01-02",
        query_end="2024-01-02",
        authority_status=(
            AuthorityStatus.VALID.value
            if expected
            else AuthorityStatus.NO_EXPECTED_OBSERVATIONS.value
        ),
        authority_source="FIX02_FIX02_TEST_AUTHORITY",
        authority_quality=AuthorityQuality.OBSERVED_DATES_WITH_TRADABILITY.value,
        raw_observed_count=len(expected) + len(nontrading),
        excluded_nontradable_count=len(nontrading),
        expected_tradable_count=len(expected),
        expected_tradable_dates=expected,
        nontradable_dates=nontrading,
        source_path="fixture",
    )


def _record(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "isu_cd": [f"KR{ticker}0000"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-02",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [100.0], "high": [110.0], "low": [90.0], "close": [105.0]},
        index=pd.to_datetime(["2024-01-02"]),
    )


def _phantom_frame() -> pd.DataFrame:
    frame = pd.DataFrame(
        columns=["open", "high", "low", "close"],
        index=pd.DatetimeIndex([], name="date"),
    )
    frame.attrs.update(
        raw_source_row_count=1,
        phantom_row_count=1,
        phantom_dates=("2024-01-02",),
        source_nonusable_row_count=0,
        source_nonusable_dates=(),
        source_row_audit=(),
    )
    return frame


def _minimal_record(ticker: str, status: str) -> TickerAcquisitionRecord:
    return TickerAcquisitionRecord(
        ticker=ticker,
        isu_cd="X",
        market="KOSPI",
        first_common_date="2024-01-02",
        last_common_date="2024-01-02",
        numeric_or_alpha="numeric",
        currently_common=True,
        historical_only=False,
        requested_start="2024-01-02",
        requested_end="2024-01-02",
        authority_source="fixture",
        authority_quality="fixture",
        expected_observation_count=1,
        actual_source_row_count=1,
        matched_expected_count=1,
        missing_expected_count=0,
        unexpected_source_date_count=0,
        first_actual_date="2024-01-02",
        last_actual_date="2024-01-02",
        source_status="SUCCESS",
        coverage_status=CoverageStatus.FULL_EXPECTED_COVERAGE.value,
        acquisition_status=status,
        attempt_count=1,
        retry_count=0,
        reused_without_network=False,
        stored_row_count=1 if status == AcquisitionStatus.COMPLETE.value else 0,
        stored_start="2024-01-02" if status == AcquisitionStatus.COMPLETE.value else None,
        stored_end="2024-01-02" if status == AcquisitionStatus.COMPLETE.value else None,
        duplicate_count=0,
        invalid_ohlc_count=0,
        future_row_count=0,
        post_write_verified=status == AcquisitionStatus.COMPLETE.value,
        error_type=None,
        error_message_sanitized=None,
        updated_at="2026-08-31T00:00:00+00:00",
        usable_source_count=1 if status == AcquisitionStatus.COMPLETE.value else 0,
        adjudicated_source_nonusable_count=1
        if status == AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value
        else 0,
        terminal_state=(
            "RAW_ROWS_PRESENT_ALL_PHANTOM"
            if status
            in {
                AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
                AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
            }
            else None
        ),
    )


class _CountingProvider:
    source_descriptor = CURRENT_SOURCE_DESCRIPTOR

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.calls = 0
        self.called_tickers: list[str] = []

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        self.called_tickers.append(ticker)
        return self.frames[ticker].copy()


def _patch_small_population(monkeypatch: pytest.MonkeyPatch, population: list[dict]) -> None:
    monkeypatch.setattr(population_module, "EXPECTED_POPULATION_COUNT", len(population))
    monkeypatch.setattr(population_module, "EXPECTED_POPULATION_SHA256", "fix02-fix02-test-population")
    monkeypatch.setattr(
        population_module.FullPopulationRunner,
        "load_population",
        lambda self: sorted(population, key=lambda item: item["ticker"]),
    )
    monkeypatch.setattr(population_module.time, "sleep", lambda *_args, **_kwargs: None)


def test_closure_success_contract_is_exactly_three_statuses():
    assert CLOSURE_SUCCESS_STATUSES == frozenset(
        {
            AcquisitionStatus.COMPLETE.value,
            AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
            AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
        }
    )
    assert all(is_closure_success(status) for status in CLOSURE_SUCCESS_STATUSES)
    assert not any(
        is_closure_success(status)
        for status in (
            AcquisitionStatus.PARTIAL.value,
            AcquisitionStatus.EMPTY.value,
            AcquisitionStatus.ERROR.value,
            AcquisitionStatus.INSUFFICIENT_AUTHORITY.value,
        )
    )


def test_true_resume_pass_requires_complete_population_and_zero_execution():
    assert compute_true_resume_pass(
        closure_complete_count=3149,
        total_count=3149,
        expected_population_count=3149,
        new_live_queries=0,
        physical_attempts=0,
    ) is True
    assert compute_true_resume_pass(
        closure_complete_count=3148,
        total_count=3149,
        expected_population_count=3149,
        new_live_queries=0,
        physical_attempts=0,
    ) is False
    assert compute_true_resume_pass(
        closure_complete_count=3149,
        total_count=3149,
        expected_population_count=3149,
        new_live_queries=1,
        physical_attempts=0,
    ) is False
    assert compute_true_resume_pass(
        closure_complete_count=3149,
        total_count=3149,
        expected_population_count=3149,
        new_live_queries=0,
        physical_attempts=1,
    ) is False


@pytest.mark.parametrize(
    ("complete_count", "new_live_queries", "physical_attempts"),
    [(3148, 0, 0), (3149, 1, 0), (3149, 0, 1)],
)
def test_incomplete_or_nonzero_execution_never_adjudicates_accept(
    complete_count: int, new_live_queries: int, physical_attempts: int
):
    from trend_scanner.data.adjusted_price_diagnostics import (
        adjudicate_adjusted_price_full_population_state,
    )

    result = adjudicate_adjusted_price_full_population_state(
        population_count=3149,
        complete_count=complete_count,
        partial_count=0 if complete_count == 3149 else 1,
        empty_count=0,
        error_count=0,
        provider_capability_status="UNKNOWN",
        quality_clean=True,
        final_resume_passed=compute_true_resume_pass(
            closure_complete_count=complete_count,
            total_count=3149,
            expected_population_count=3149,
            new_live_queries=new_live_queries,
            physical_attempts=physical_attempts,
        ),
    )
    assert result["final_verdict"] == "CHANGES_REQUESTED"


@pytest.mark.parametrize(
    ("summary", "resume", "closure", "execution", "error"),
    [
        (
            {"execution_id": "e", "final_verdict": "CHANGES_REQUESTED", "next_state": "x"},
            {"execution_id": "e", "is_idempotent": True},
            {"execution_id": "e", "final_verdict": "CHANGES_REQUESTED", "next_state": "x"},
            {"execution_id": "e"},
            "RESUME_VERDICT_INVARIANT_FAILED",
        ),
        (
            {"execution_id": "e", "final_verdict": "ACCEPT", "next_state": "x"},
            {"execution_id": "e", "is_idempotent": False},
            {"execution_id": "e", "final_verdict": "CHANGES_REQUESTED", "next_state": "x"},
            {"execution_id": "e"},
            "SUMMARY_CLOSURE_VERDICT_MISMATCH",
        ),
        (
            {"execution_id": "e", "final_verdict": "ACCEPT", "next_state": "x"},
            {"execution_id": "e", "is_idempotent": False},
            {"execution_id": "e", "final_verdict": "ACCEPT", "next_state": "y"},
            {"execution_id": "e"},
            "SUMMARY_CLOSURE_NEXT_STATE_MISMATCH",
        ),
        (
            {"execution_id": "e", "final_verdict": "ACCEPT", "next_state": "x"},
            {"execution_id": "e", "is_idempotent": False},
            {"execution_id": "e", "final_verdict": "ACCEPT", "next_state": "x"},
            {"execution_id": "other"},
            "OPERATIONAL_EXECUTION_ID_MISMATCH",
        ),
    ],
)
def test_operational_artifact_invariants_fail_closed(summary, resume, closure, execution, error):
    with pytest.raises(RuntimeError, match=error):
        validate_operational_artifact_invariants(summary, resume, closure, execution)


@pytest.mark.parametrize(
    "status",
    [
        AcquisitionStatus.COMPLETE.value,
        AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
        AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
        AcquisitionStatus.PARTIAL.value,
        AcquisitionStatus.EMPTY.value,
        AcquisitionStatus.ERROR.value,
        AcquisitionStatus.INSUFFICIENT_AUTHORITY.value,
    ],
)
def test_runner_places_successes_in_completed_and_failures_in_progress(
    status: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    population = [_record("000001")]
    _patch_small_population(monkeypatch, population)
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    monkeypatch.setattr(runner, "dry_run_classify", lambda: {})
    monkeypatch.setattr(
        runner,
        "process_single_ticker",
        lambda rec, provider=None: _minimal_record(rec["ticker"], status),
    )
    monkeypatch.setattr(runner, "generate_operational_artifacts", lambda *args, **kwargs: {})
    provider = _CountingProvider({})
    runner.run_acquisition(provider=provider)
    checkpoint = json.loads(runner.checkpoint_path.read_text(encoding="utf-8"))
    if is_closure_success(status):
        assert "000001" in checkpoint["completed_tickers"]
        assert "000001" not in checkpoint["in_progress_tickers"]
    else:
        assert "000001" in checkpoint["in_progress_tickers"]
        assert "000001" not in checkpoint["completed_tickers"]


@pytest.mark.parametrize(
    ("status", "terminal_state", "stored", "usable", "adjudicated"),
    [
        (AcquisitionStatus.COMPLETE.value, None, 1, 1, 0),
        (AcquisitionStatus.NO_USABLE_OBSERVATIONS.value, "RAW_ROWS_PRESENT_ALL_PHANTOM", 0, 0, 0),
        (
            AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
            "RAW_ROWS_PRESENT_ALL_PHANTOM",
            0,
            0,
            1,
        ),
    ],
)
def test_terminal_success_evidence_accepts_each_valid_shape(
    status: str, terminal_state: str | None, stored: int, usable: int, adjudicated: int
):
    valid, error = validate_terminal_success_evidence(
        {
            "acquisition_status": status,
            "terminal_state": terminal_state,
            "stored_row_count": stored,
            "usable_source_count": usable,
            "adjudicated_source_nonusable_count": adjudicated,
            "silent_missing_count": 0,
            "unexpected_source_count": 0,
            "authority_conflict_count": 0,
        }
    )
    assert valid, error


@pytest.mark.parametrize(
    "info",
    [
        {
            "acquisition_status": AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
            "terminal_state": "RAW_ROWS_PRESENT_ALL_PHANTOM",
            "stored_row_count": 0,
            "usable_source_count": 1,
        },
        {
            "acquisition_status": AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
            "terminal_state": "RAW_ROWS_PRESENT_ALL_PHANTOM",
            "stored_row_count": 0,
            "usable_source_count": 0,
            "silent_missing_count": 1,
        },
        {
            "acquisition_status": AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
            "terminal_state": "RAW_ROWS_PRESENT_ALL_PHANTOM",
            "stored_row_count": 0,
            "usable_source_count": 0,
            "adjudicated_source_nonusable_count": 0,
        },
        {
            "acquisition_status": AcquisitionStatus.COMPLETE.value,
            "stored_row_count": 0,
            "usable_source_count": 0,
        },
        {
            "acquisition_status": AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
            "terminal_state": "ARBITRARY_UNVERIFIED_STATE",
            "stored_row_count": 1,
            "usable_source_count": 1,
            "adjudicated_source_nonusable_count": 1,
        },
    ],
)
def test_malformed_terminal_success_evidence_is_rejected(info: dict):
    valid, error = validate_terminal_success_evidence(info)
    assert not valid
    assert error


def test_mixed_population_closes_all_statuses_and_second_run_is_zero_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    population = [_record("000001"), _record("000610"), _record("000003")]
    _patch_small_population(monkeypatch, population)
    resolutions = {
        "000001": _resolution("000001", expected=("2024-01-02",)),
        "000610": _resolution("000610", nontrading=("2024-01-02",)),
        "000003": _resolution("000003", expected=("2024-01-02",)),
    }
    monkeypatch.setattr(
        population_module,
        "resolve_expected_coverage",
        lambda ticker, *_args, **_kwargs: resolutions[ticker],
    )
    monkeypatch.setattr(
        "trend_scanner.data.adjusted_price_diagnostics.load_canonical_authority_state",
        lambda *_args, **_kwargs: {"provider_capability_status": "UNKNOWN"},
    )
    provider = _CountingProvider(
        {"000001": _valid_frame(), "000610": _phantom_frame(), "000003": _phantom_frame()}
    )
    runner = FullPopulationRunner(
        store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts", provider=provider, max_retries=0
    )
    first = runner.run_acquisition()
    statuses = {record.ticker: record.acquisition_status for record in first["records"]}
    assert statuses == {
        "000001": AcquisitionStatus.COMPLETE.value,
        "000610": AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
        "000003": AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
    }
    assert provider.calls == 3
    checkpoint = json.loads(runner.checkpoint_path.read_text(encoding="utf-8"))
    assert set(checkpoint["completed_tickers"]) == {"000001", "000610", "000003"}
    assert checkpoint["in_progress_tickers"] == {}
    assert checkpoint["completed_tickers"]["000610"]["stored_row_count"] == 0
    assert checkpoint["completed_tickers"]["000003"]["adjudicated_source_nonusable_count"] == 1

    provider.calls = 0
    provider.called_tickers.clear()
    second = runner.run_acquisition()
    assert provider.calls == 0
    assert all(record.reused_without_network for record in second["records"])
    assert all(record.attempt_count == 0 and record.retry_count == 0 for record in second["records"])
    assert second["summary"]["status_counts"]["closure_complete_total"] == 3
    assert second["summary"]["final_verdict"] == "ACCEPT"
    assert second["summary"]["next_state"] == "READY_FOR_MARKET_DATA_REPOSITORY_V02_PARITY"
    assert second["summary"]["network_accounting"]["physical_provider_attempts"] == 0
    resume_audit = json.loads(runner.resume_audit_path.read_text(encoding="utf-8"))
    assert resume_audit["verified_complete"] == 3
    assert resume_audit["is_idempotent"] is True
    assert resume_audit["eligibility"] == "PASS"
    closure = json.loads(runner.closure_manifest_path.read_text(encoding="utf-8"))
    summary = json.loads(runner.summary_path.read_text(encoding="utf-8"))
    execution = json.loads((runner.artifact_dir / "full_population_execution_audit.json").read_text(encoding="utf-8"))
    assert closure["final_verdict"] == summary["final_verdict"] == "ACCEPT"
    assert closure["next_state"] == summary["next_state"]
    assert {summary["execution_id"], resume_audit["execution_id"], closure["execution_id"], execution["execution_id"]} == {runner.execution_id}


def test_completed_zero_store_status_with_unexpected_evidence_is_not_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    population = [_record("000002")]
    _patch_small_population(monkeypatch, population)
    monkeypatch.setattr(
        population_module,
        "resolve_expected_coverage",
        lambda *_args, **_kwargs: _resolution("000002", nontrading=("2024-01-02",)),
    )
    provider = _CountingProvider({"000002": _phantom_frame()})
    runner = FullPopulationRunner(
        store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts", provider=provider, max_retries=0
    )
    checkpoint = runner.load_or_create_checkpoint(population)
    checkpoint.completed_tickers["000002"] = {
        "ticker": "000002",
        "acquisition_status": AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
        "terminal_state": "RAW_ROWS_PRESENT_ALL_PHANTOM",
        "stored_row_count": 0,
        "usable_source_count": 0,
        "adjudicated_source_nonusable_count": 0,
        "silent_missing_count": 0,
        "unexpected_source_count": 1,
        "authority_conflict_count": 0,
        "actual_dates": [],
    }
    runner.save_checkpoint(checkpoint)
    runner.run_acquisition()
    assert provider.calls == 1


def test_dry_run_recognizes_status_aware_zero_store_completion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    population = [_record("000002")]
    _patch_small_population(monkeypatch, population)
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    checkpoint = runner.load_or_create_checkpoint(population)
    checkpoint.completed_tickers["000002"] = {
        "ticker": "000002",
        "acquisition_status": AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
        "terminal_state": "RAW_ROWS_PRESENT_ALL_PHANTOM",
        "stored_row_count": 0,
        "usable_source_count": 0,
        "adjudicated_source_nonusable_count": 0,
        "silent_missing_count": 0,
        "unexpected_source_count": 0,
        "authority_conflict_count": 0,
        "actual_dates": [],
    }
    runner.save_checkpoint(checkpoint)
    result = runner.dry_run_classify()
    assert result["already_complete_count"] == 1
    assert result["reconciliation_sum"] == 1


def test_aggregate_closure_counts_and_failures_exclude_terminal_successes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "trend_scanner.data.adjusted_price_diagnostics.load_canonical_authority_state",
        lambda *_args, **_kwargs: {"provider_capability_status": "UNKNOWN"},
    )
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    base = {
        "ticker": "000001",
        "isu_cd": "X",
        "market": "KOSPI",
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-02",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
        "requested_start": "2024-01-02",
        "requested_end": "2024-01-02",
        "authority_source": "fixture",
        "authority_quality": "fixture",
        "expected_observation_count": 0,
        "actual_source_row_count": 0,
        "matched_expected_count": 0,
        "missing_expected_count": 0,
        "unexpected_source_date_count": 0,
        "first_actual_date": None,
        "last_actual_date": None,
        "source_status": "SUCCESS",
        "coverage_status": CoverageStatus.NO_EXPECTED_OBSERVATIONS.value,
        "attempt_count": 0,
        "retry_count": 0,
        "reused_without_network": True,
        "stored_row_count": 0,
        "stored_start": None,
        "stored_end": None,
        "duplicate_count": 0,
        "invalid_ohlc_count": 0,
        "future_row_count": 0,
        "post_write_verified": False,
        "error_type": None,
        "error_message_sanitized": None,
        "updated_at": "2026-08-31T00:00:00+00:00",
    }
    no_usable = TickerAcquisitionRecord(
        **{**base, "ticker": "000002"},
        acquisition_status=AcquisitionStatus.NO_USABLE_OBSERVATIONS.value,
        terminal_state="RAW_ROWS_PRESENT_ALL_PHANTOM",
        phantom_count=1,
    )
    adjudicated = TickerAcquisitionRecord(
        **{**base, "ticker": "000003"},
        acquisition_status=AcquisitionStatus.COMPLETE_WITH_ADJUDICATED_NONUSABLE.value,
        terminal_state="RAW_ROWS_PRESENT_ALL_PHANTOM",
        adjudicated_source_nonusable_count=1,
        phantom_count=1,
    )
    partial = TickerAcquisitionRecord(
        **{
            **base,
            "ticker": "000004",
            "coverage_status": CoverageStatus.PARTIAL_EXPECTED_COVERAGE.value,
            "expected_observation_count": 1,
            "missing_expected_count": 1,
            "silent_missing_count": 1,
        },
        acquisition_status=AcquisitionStatus.PARTIAL.value,
    )
    summary = runner.generate_operational_artifacts([no_usable, adjudicated, partial], {}, 1.0)
    counts = summary["status_counts"]
    assert counts["normal_complete"] == 0
    assert counts["no_usable_observations"] == 1
    assert counts["complete_with_adjudicated_nonusable"] == 1
    assert counts["closure_complete_total"] == 2
    assert summary["closure_accounting"]["failure_count"] == 1
    closure = json.loads(runner.closure_manifest_path.read_text(encoding="utf-8"))
    assert closure["completed_count"] == 2
    assert closure["failure_count"] == 1
    failures = runner.failures_csv_path.read_text(encoding="utf-8")
    assert "000004" in failures
    assert "000002" not in failures and "000003" not in failures
