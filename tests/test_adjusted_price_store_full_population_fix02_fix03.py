"""FIX02_FIX03 resolved/unresolved authority-conflict closure contract tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data import adjusted_price_full_population as population_module
from trend_scanner.data.adjusted_price_full_population import (
    AcquisitionStatus,
    FullPopulationRunner,
    TickerAcquisitionRecord,
    validate_terminal_success_evidence,
)
from trend_scanner.data.adjusted_price_pilot import (
    AuthorityQuality,
    AuthorityStatus,
    CoverageStatus,
    ExpectedCoverageResolution,
    resolve_expected_coverage,
)
from trend_scanner.data.adjusted_price_semantics import ClosureState
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR


def _record(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "isu_cd": [f"KR{ticker}0000"],
        "market": ["KOSPI"],
        "first_common_date": "2012-07-16",
        "last_common_date": "2012-07-16",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }


def _resolution(
    ticker: str,
    *,
    conflicts: tuple[str, ...] = (),
    resolved: tuple[str, ...] = (),
    unresolved: tuple[str, ...] = (),
) -> ExpectedCoverageResolution:
    return ExpectedCoverageResolution(
        ticker=ticker,
        query_start="2012-07-16",
        query_end="2012-07-16",
        authority_status=AuthorityStatus.VALID.value,
        authority_source="CANONICAL_HISTORICAL_SUSPENSION_AUTHORITY",
        authority_quality=AuthorityQuality.INDEPENDENT_HISTORICAL_RAW_WITH_TRADABILITY.value,
        raw_observed_count=1,
        excluded_nontradable_count=0,
        expected_tradable_count=1,
        expected_tradable_dates=("2012-07-16",),
        nontradable_dates=(),
        source_path="fixture",
        authority_conflict_dates=conflicts,
        resolved_authority_conflict_dates=resolved,
        unresolved_authority_conflict_dates=unresolved,
    )


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"open": [100.0], "high": [110.0], "low": [90.0], "close": [105.0]},
        index=pd.to_datetime(["2012-07-16"]),
    )


class _CountingProvider:
    source_descriptor = CURRENT_SOURCE_DESCRIPTOR

    def __init__(self) -> None:
        self.calls = 0

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        return _valid_frame()


def _patch_population(monkeypatch: pytest.MonkeyPatch, population: list[dict]) -> None:
    monkeypatch.setattr(population_module, "EXPECTED_POPULATION_COUNT", len(population))
    monkeypatch.setattr(population_module, "EXPECTED_POPULATION_SHA256", "fix03-test-population")
    monkeypatch.setattr(
        population_module.FullPopulationRunner,
        "load_population",
        lambda self: sorted(population, key=lambda item: item["ticker"]),
    )
    monkeypatch.setattr(population_module.time, "sleep", lambda *_args, **_kwargs: None)


def _base_record(ticker: str, status: str) -> TickerAcquisitionRecord:
    success = status == AcquisitionStatus.COMPLETE.value
    resolved = 1 if ticker == "000360" else 0
    unresolved = 1 if ticker == "000999" else 0
    conflicts = resolved + unresolved
    return TickerAcquisitionRecord(
        ticker=ticker,
        isu_cd="X",
        market="KOSPI",
        first_common_date="2012-07-16",
        last_common_date="2012-07-16",
        numeric_or_alpha="numeric",
        currently_common=True,
        historical_only=False,
        requested_start="2012-07-16",
        requested_end="2012-07-16",
        authority_source="fixture",
        authority_quality="fixture",
        expected_observation_count=1,
        actual_source_row_count=1 if success else 0,
        matched_expected_count=1 if success else 0,
        missing_expected_count=0 if success else 1,
        unexpected_source_date_count=0,
        first_actual_date="2012-07-16" if success else None,
        last_actual_date="2012-07-16" if success else None,
        source_status="SUCCESS" if success else "ERROR",
        coverage_status=(
            CoverageStatus.FULL_EXPECTED_COVERAGE.value
            if success
            else CoverageStatus.INSUFFICIENT_COVERAGE_AUTHORITY.value
        ),
        acquisition_status=status,
        attempt_count=1,
        retry_count=0,
        reused_without_network=False,
        stored_row_count=1 if success else 0,
        stored_start="2012-07-16" if success else None,
        stored_end="2012-07-16" if success else None,
        duplicate_count=0,
        invalid_ohlc_count=0,
        future_row_count=0,
        post_write_verified=success,
        error_type=None if success else "UNRESOLVED_AUTHORITY_CONFLICT",
        error_message_sanitized=None,
        updated_at="2026-08-31T00:00:00+00:00",
        usable_source_count=1 if success else 0,
        silent_missing_count=0 if success else 1,
        authority_conflict_count=conflicts,
        resolved_authority_conflict_count=resolved,
        unresolved_authority_conflict_count=unresolved,
        resolved_authority_conflict_dates=("2012-07-16",) if resolved else (),
        unresolved_authority_conflict_dates=("2012-07-16",) if unresolved else (),
    )


def test_resolved_conflict_allows_terminal_success_evidence():
    valid, error = validate_terminal_success_evidence(
        {
            "acquisition_status": AcquisitionStatus.COMPLETE.value,
            "stored_row_count": 1,
            "usable_source_count": 1,
            "adjudicated_source_nonusable_count": 0,
            "silent_missing_count": 0,
            "unexpected_source_count": 0,
            "authority_conflict_count": 1,
            "resolved_authority_conflict_count": 1,
            "unresolved_authority_conflict_count": 0,
            "resolved_authority_conflict_dates": ["2012-07-16"],
            "unresolved_authority_conflict_dates": [],
            "actual_dates": ["2012-07-16"],
        }
    )
    assert valid, error


def test_unresolved_conflict_blocks_terminal_success_evidence():
    valid, error = validate_terminal_success_evidence(
        {
            "acquisition_status": AcquisitionStatus.COMPLETE.value,
            "stored_row_count": 1,
            "usable_source_count": 1,
            "adjudicated_source_nonusable_count": 0,
            "silent_missing_count": 0,
            "unexpected_source_count": 0,
            "authority_conflict_count": 1,
            "resolved_authority_conflict_count": 0,
            "unresolved_authority_conflict_count": 1,
            "resolved_authority_conflict_dates": [],
            "unresolved_authority_conflict_dates": ["2012-07-16"],
            "actual_dates": ["2012-07-16"],
        }
    )
    assert not valid
    assert error == "UNRESOLVED_TERMINAL_COUNTER"


def test_fallback_resolver_exposes_exact_000360_resolved_conflict(tmp_path: Path):
    calendar_path = tmp_path / "calendar.json"
    pit_path = tmp_path / "pit.json"
    authority_path = tmp_path / "authority.json"
    errata_path = tmp_path / "errata.json"
    calendar_path.write_text(
        json.dumps({"trading_dates": ["2012-07-16"]}), encoding="utf-8"
    )
    pit_path.write_text(
        json.dumps(
            {
                "intervals": [
                    {
                        "ticker": "000360",
                        "state": "COMMON",
                        "effective_from": "2012-07-16",
                        "effective_to": "2012-07-16",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    authority_payload = {"records": [{"ticker": "000360", "date": "2012-07-16"}]}
    authority_path.write_text(json.dumps(authority_payload), encoding="utf-8")
    authority_sha = hashlib.sha256(authority_path.read_bytes()).hexdigest()
    errata_path.write_text(
        json.dumps(
            {
                "schema": "historical_suspension_authority_errata_v01",
                "base_artifact_sha256": authority_sha,
                "records": [
                    {
                        "ticker": "000360",
                        "date": "2012-07-16",
                        "conflict_class": ClosureState.SUSPENSION_METADATA_CONFLICT_WITH_OBSERVED_ACTIVITY.value,
                        "original_classification": "NONTRADING / SUSPENSION_METADATA",
                        "effective_classification": "VALID_OBSERVED_MARKET_ACTIVITY",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    resolution = resolve_expected_coverage(
        "000360",
        "2012-07-16",
        "2012-07-16",
        stocks_dir=tmp_path / "missing-stocks",
        pit_path=pit_path,
        historical_calendar_path=calendar_path,
        suspension_authority_path=authority_path,
        suspension_errata_path=errata_path,
    )
    assert resolution.authority_source == "CANONICAL_HISTORICAL_SUSPENSION_AUTHORITY"
    assert resolution.authority_conflict_dates == ("2012-07-16",)
    assert resolution.resolved_authority_conflict_dates == ("2012-07-16",)
    assert resolution.unresolved_authority_conflict_dates == ()
    assert resolution.expected_tradable_dates == ("2012-07-16",)


def test_000360_first_run_and_immediate_resume_are_zero_call(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    population = [_record("000360")]
    _patch_population(monkeypatch, population)
    monkeypatch.setattr(
        population_module,
        "resolve_expected_coverage",
        lambda *_args, **_kwargs: _resolution(
            "000360",
            conflicts=("2012-07-16",),
            resolved=("2012-07-16",),
        ),
    )
    provider = _CountingProvider()
    runner = FullPopulationRunner(
        store_dir=tmp_path / "store",
        artifact_dir=tmp_path / "artifacts",
        provider=provider,
        max_retries=0,
    )
    first = runner.run_acquisition()
    first_record = first["records"][0]
    assert first_record.acquisition_status == AcquisitionStatus.COMPLETE.value
    assert first_record.authority_conflict_count == 1
    assert first_record.resolved_authority_conflict_count == 1
    assert first_record.unresolved_authority_conflict_count == 0
    assert provider.calls == 1
    checkpoint = json.loads(runner.checkpoint_path.read_text(encoding="utf-8"))
    entry = checkpoint["completed_tickers"]["000360"]
    assert entry["resolved_authority_conflict_dates"] == ["2012-07-16"]
    assert entry["unresolved_authority_conflict_count"] == 0

    provider.calls = 0
    second = runner.run_acquisition()
    second_record = second["records"][0]
    assert provider.calls == 0
    assert second_record.reused_without_network is True
    assert second_record.attempt_count == 0
    assert second_record.retry_count == 0
    assert second["summary"]["authority_conflict_totals"] == {
        "total_authority_conflicts": 1,
        "total_resolved_authority_conflicts": 1,
        "total_unresolved_authority_conflicts": 0,
    }


def test_unresolved_conflict_process_is_non_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    monkeypatch.setattr(
        population_module,
        "resolve_expected_coverage",
        lambda *_args, **_kwargs: _resolution(
            "000999",
            conflicts=("2012-07-16",),
            unresolved=("2012-07-16",),
        ),
    )
    result = runner.process_single_ticker(_record("000999"), provider=_CountingProvider())
    assert result.acquisition_status == AcquisitionStatus.INSUFFICIENT_AUTHORITY.value
    assert result.terminal_state == "UNRESOLVED_AUTHORITY_CONFLICT"
    assert result.unresolved_authority_conflict_count == 1
    assert result.resolved_authority_conflict_count == 0


def test_unresolved_conflict_is_not_reclassified_complete_by_dry_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    population = [_record("000999")]
    _patch_population(monkeypatch, population)
    monkeypatch.setattr(
        population_module,
        "resolve_expected_coverage",
        lambda *_args, **_kwargs: _resolution(
            "000999",
            conflicts=("2012-07-16",),
            unresolved=("2012-07-16",),
        ),
    )
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    result = runner.dry_run_classify()
    assert result["already_complete_count"] == 0
    assert result["needs_fetch_count"] == 1


def test_resolved_conflict_is_excluded_and_unresolved_is_included_in_failure_accounting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "trend_scanner.data.adjusted_price_diagnostics.load_canonical_authority_state",
        lambda *_args, **_kwargs: {"provider_capability_status": "UNKNOWN"},
    )
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    resolved = _base_record("000360", AcquisitionStatus.COMPLETE.value)
    unresolved = _base_record("000999", AcquisitionStatus.INSUFFICIENT_AUTHORITY.value)
    summary = runner.generate_operational_artifacts([resolved, unresolved], {}, 1.0)
    assert summary["status_counts"]["closure_complete_total"] == 1
    assert summary["authority_conflict_totals"] == {
        "total_authority_conflicts": 2,
        "total_resolved_authority_conflicts": 1,
        "total_unresolved_authority_conflicts": 1,
    }
    assert summary["final_verdict"] == "CHANGES_REQUESTED"
    failures = runner.failures_csv_path.read_text(encoding="utf-8")
    assert "000999" in failures
    assert "000360" not in failures
    closure = json.loads(runner.closure_manifest_path.read_text(encoding="utf-8"))
    assert closure["resolved_authority_conflict_count"] == 1
    assert closure["unresolved_authority_conflict_count"] == 1


def test_adjudicator_is_fail_closed_when_unresolved_conflict_is_passed():
    from trend_scanner.data.adjusted_price_diagnostics import (
        adjudicate_adjusted_price_full_population_state,
    )

    result = adjudicate_adjusted_price_full_population_state(
        population_count=1,
        complete_count=1,
        partial_count=0,
        empty_count=0,
        error_count=0,
        provider_capability_status="RECOVERABLE_WITHIN_FROZEN_AUTHORITY",
        quality_clean=True,
        final_resume_passed=True,
        unresolved_authority_conflict_count=1,
    )
    assert result["final_verdict"] == "CHANGES_REQUESTED"
    assert result["recommended_next_state"] == "NEEDS_FIX02_FIX04"
