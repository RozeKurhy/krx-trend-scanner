"""FIX02 focused, hermetic closure-semantics tests."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.adjusted_price_full_population import (
    AcquisitionStatus,
    FullPopulationRunner,
)
from trend_scanner.data.adjusted_price_pilot import (
    AuthorityQuality,
    AuthorityStatus,
    ExpectedCoverageResolution,
    DEFAULT_SUSPENSION_AUTHORITY_PATH,
    DEFAULT_SUSPENSION_ERRATA_PATH,
    is_nontradable_or_phantom_row,
    load_effective_historical_suspension_authority,
)
from trend_scanner.data.adjusted_price_provider import NaverDirectAdjustedPriceDataProvider
from trend_scanner.data.adjusted_price_semantics import (
    ClosureState,
    classify_source_row,
)
from trend_scanner.data.adjusted_price_source_authority import CURRENT_SOURCE_DESCRIPTOR
from trend_scanner.data.adjusted_price_store import AdjustedPriceStore
from trend_scanner.data.errors import MarketDataError


def _xml(*items: str) -> str:
    return "<protocol><chartdata>" + "".join(
        f'<item data="{item}"/>' for item in items
    ) + "</chartdata></protocol>"


class _Session:
    status_code = 200

    def __init__(self, payload: str) -> None:
        self.text = payload

    def get(self, *args, **kwargs):
        return self


def _resolution(*dates: str, nontradable: tuple[str, ...] = ()) -> ExpectedCoverageResolution:
    return ExpectedCoverageResolution(
        ticker="005930",
        query_start=dates[0] if dates else "2024-01-01",
        query_end=dates[-1] if dates else "2024-01-03",
        authority_status=AuthorityStatus.VALID.value,
        authority_source="FIX02_TEST_AUTHORITY",
        authority_quality=AuthorityQuality.OBSERVED_DATES_WITH_TRADABILITY.value,
        raw_observed_count=len(dates) + len(nontradable),
        excluded_nontradable_count=len(nontradable),
        expected_tradable_count=len(dates),
        expected_tradable_dates=tuple(dates),
        nontradable_dates=nontradable,
        source_path="fixture",
    )


def _record() -> dict:
    return {
        "ticker": "005930",
        "isu_cd": ["KR7005930003"],
        "market": ["KOSPI"],
        "first_common_date": "2024-01-02",
        "last_common_date": "2024-01-03",
        "numeric_or_alpha": "numeric",
        "currently_common": True,
        "historical_only": False,
    }


def test_activity_aware_zero_ohlc_contract():
    assert is_nontradable_or_phantom_row(0, 0, 0, 100, 0, 0)
    assert not is_nontradable_or_phantom_row(0, 0, 0, 100)
    assert not is_nontradable_or_phantom_row(0, 0, 0, 100, 1, 1)
    assert not is_nontradable_or_phantom_row(0, 0, 0, 100, 1, 0)
    assert not is_nontradable_or_phantom_row(0, 0, 0, 100, 0, 1)
    assert classify_source_row(0, 0, 0, 100, 0, 0) == ClosureState.CONFIRMED_NONTRADING
    assert classify_source_row(0, 0, 0, 100, 1, 1) == ClosureState.ADJUDICATED_SOURCE_NONUSABLE


def test_naver_source_integrity_is_separate_from_analytic_validity():
    provider = NaverDirectAdjustedPriceDataProvider(
        session=_Session(_xml("20240102|100|80|90|105|1"))
    )
    frame = provider.load_daily("005930", "2024-01-02", "2024-01-02")
    assert frame.attrs["source_native_adjusted"] is True
    assert frame.attrs["analytic_invalid_ohlc_count"] == 1
    assert frame.iloc[0]["high"] == 80


def test_runner_closes_relation_anomaly_without_discarding_source_row(tmp_path: Path, monkeypatch):
    provider = NaverDirectAdjustedPriceDataProvider(
        session=_Session(_xml("20240102|100|80|90|105|1"))
    )
    monkeypatch.setattr(
        "trend_scanner.data.adjusted_price_full_population.resolve_expected_coverage",
        lambda *args, **kwargs: _resolution("2024-01-02"),
    )
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    result = runner.process_single_ticker(_record(), provider=provider)
    assert result.acquisition_status == AcquisitionStatus.COMPLETE.value
    assert result.analytic_invalid_ohlc_count == 1
    assert result.invalid_ohlc_count == 0
    assert runner.store.load_daily_source("005930").iloc[0]["high"] == 80


def test_source_native_relation_anomaly_is_stored_without_repair(tmp_path: Path):
    frame = pd.DataFrame(
        {"open": [100.0], "high": [80.0], "low": [90.0], "close": [105.0]},
        index=pd.to_datetime(["2024-01-02"]),
    )
    frame.attrs.update(source_native_adjusted=True, analytic_invalid_ohlc_count=1)
    store = AdjustedPriceStore(tmp_path)
    store.save_full("005930", frame, source_descriptor=CURRENT_SOURCE_DESCRIPTOR)
    loaded = store.load_daily_source("005930")
    assert loaded.iloc[0]["high"] == 80
    with pytest.raises(MarketDataError):
        store.load_daily_analytic("005930")
    assert store.load_metadata("005930")["analytic_invalid_ohlc_count"] == 1


def test_naver_phantom_only_has_explicit_zero_usable_terminal_state(tmp_path, monkeypatch):
    provider = NaverDirectAdjustedPriceDataProvider(
        session=_Session(_xml("20240102|0|0|0|100|0", "20240103|0|0|0|100|0"))
    )
    monkeypatch.setattr(
        "trend_scanner.data.adjusted_price_full_population.resolve_expected_coverage",
        lambda *args, **kwargs: _resolution("2024-01-02", "2024-01-03"),
    )
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    result = runner.process_single_ticker(_record(), provider=provider)
    assert result.acquisition_status == AcquisitionStatus.NO_USABLE_OBSERVATIONS.value
    assert result.terminal_state == "RAW_ROWS_PRESENT_ALL_PHANTOM"
    assert result.phantom_count == 2
    assert result.silent_missing_count == 0
    assert not (tmp_path / "store" / "005930.parquet").exists()


def test_naver_activity_positive_zero_ohlc_is_adjudicated_nonusable():
    provider = NaverDirectAdjustedPriceDataProvider(
        session=_Session(_xml("20240102|0|0|0|100|10"))
    )
    frame = provider.load_daily("005930", "2024-01-02", "2024-01-02")
    assert frame.empty
    assert provider.source_nonusable_row_count == 1
    assert frame.attrs["source_nonusable_dates"] == ("2024-01-02",)


def test_suspension_errata_effective_overlay_resolves_000360_conflict():
    effective, base_sha, errata_sha, records = load_effective_historical_suspension_authority(
        DEFAULT_SUSPENSION_AUTHORITY_PATH, DEFAULT_SUSPENSION_ERRATA_PATH
    )
    assert base_sha != "MISSING"
    assert errata_sha != "MISSING"
    assert "2012-07-16" not in effective.get("000360", set())
    assert any(item["ticker"] == "000360" for item in records)


def test_old_checkpoint_schema_cannot_resume(tmp_path: Path):
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()
    (artifact_dir / "full_population_checkpoint.json").write_text(
        json.dumps({"schema": "full_population_checkpoint_v01"}), encoding="utf-8"
    )
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=artifact_dir)
    with pytest.raises(RuntimeError, match="CHECKPOINT_SCHEMA_MISMATCH"):
        runner.load_or_create_checkpoint([])


def test_new_checkpoint_persists_compatibility_identity(tmp_path: Path):
    runner = FullPopulationRunner(store_dir=tmp_path / "store", artifact_dir=tmp_path / "artifacts")
    records = [{"ticker": "005930"}]
    checkpoint = runner.load_or_create_checkpoint(records)
    assert checkpoint.schema == "full_population_checkpoint_v02"
    runner.save_checkpoint(checkpoint)
    payload = json.loads(runner.checkpoint_path.read_text(encoding="utf-8"))
    assert payload["closure_accounting_schema_version"] == "adjusted_price_closure_accounting_v02"
    assert payload["tradability_contract_version"] == "adjusted_price_tradability_v02"
    assert payload["source_authority_id"] == CURRENT_SOURCE_DESCRIPTOR.source_authority_id
