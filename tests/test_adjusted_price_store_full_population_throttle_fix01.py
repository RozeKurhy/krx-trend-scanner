"""Throttle-only FIX01 tests for fresh-run acquisition and checkpoint reuse."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from trend_scanner.data import adjusted_price_full_population as population_module
from trend_scanner.data.adjusted_price_full_population import AcquisitionStatus, FullPopulationRunner
from trend_scanner.data.adjusted_price_pilot import (
    AuthorityQuality,
    AuthorityStatus,
    ExpectedCoverageResolution,
)
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR


def _record(ticker: str) -> dict[str, object]:
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


def _resolution(ticker: str) -> ExpectedCoverageResolution:
    return ExpectedCoverageResolution(
        ticker=ticker,
        query_start="2024-01-02",
        query_end="2024-01-02",
        authority_status=AuthorityStatus.VALID.value,
        authority_source="THROTTLE_FIX01_TEST_AUTHORITY",
        authority_quality=AuthorityQuality.OBSERVED_DATES_WITH_TRADABILITY.value,
        raw_observed_count=1,
        excluded_nontradable_count=0,
        expected_tradable_count=1,
        expected_tradable_dates=("2024-01-02",),
        nontradable_dates=(),
        source_path="fixture",
    )


class _CountingProvider:
    source_descriptor = CURRENT_SOURCE_DESCRIPTOR

    def __init__(self) -> None:
        self.calls = 0

    def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        self.calls += 1
        return pd.DataFrame(
            {"open": [100.0], "high": [110.0], "low": [90.0], "close": [105.0]},
            index=pd.to_datetime(["2024-01-02"]),
        )


def test_fresh_fetch_uses_half_second_throttle_and_reuse_skips_it(
    tmp_path: Path, monkeypatch
) -> None:
    population = [_record("000001")]
    monkeypatch.setattr(population_module, "EXPECTED_POPULATION_COUNT", 1)
    monkeypatch.setattr(population_module, "EXPECTED_POPULATION_SHA256", "throttle-fix01-test-population")
    monkeypatch.setattr(
        population_module.FullPopulationRunner,
        "load_population",
        lambda self: population,
    )
    monkeypatch.setattr(
        population_module,
        "resolve_expected_coverage",
        lambda ticker, *_args, **_kwargs: _resolution(ticker),
    )

    sleeps: list[float] = []
    monkeypatch.setattr(population_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    provider = _CountingProvider()
    runner = FullPopulationRunner(
        store_dir=tmp_path / "store",
        artifact_dir=tmp_path / "artifacts",
        provider=provider,
        max_retries=0,
    )

    first = runner.run_acquisition()
    assert first["records"][0].acquisition_status == AcquisitionStatus.COMPLETE.value
    assert provider.calls == 1
    assert sleeps == [0.50]

    provider.calls = 0
    second = runner.run_acquisition()
    assert provider.calls == 0
    assert second["records"][0].reused_without_network is True
    assert second["records"][0].attempt_count == 0
    assert second["records"][0].retry_count == 0
    assert sleeps == [0.50]
