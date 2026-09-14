"""Small offline tests for the final direct-Naver price spot validation."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from scripts.final_market_price_validation_v01 import (
    OHLC_FIELDS,
    build_sample_manifest,
    compare_observation,
    run_validation,
)


def _dates() -> list[str]:
    return [f"2026-01-{day:02d}" for day in range(1, 21)]


def _row(value: float = 100.0) -> dict[str, float]:
    return {"open": value, "high": value + 2, "low": value - 2, "close": value + 1}


def test_deterministic_sample_reproducibility() -> None:
    mapping = {f"{number:06d}": _dates() for number in range(1, 41)}
    first, first_replacements = build_sample_manifest(mapping, mapping.get)
    second, second_replacements = build_sample_manifest(mapping, mapping.get)
    assert first == second
    assert first_replacements == second_replacements


def test_sample_shape_is_30_tickers_and_20_dates_each() -> None:
    mapping = {f"{number:06d}": _dates() for number in range(1, 41)}
    manifest, _ = build_sample_manifest(mapping, mapping.get)
    assert len(manifest) == 30
    assert len(set(manifest)) == 30
    assert all(len(days) == 20 and len(set(days)) == 20 for days in manifest.values())


def test_numeric_equivalent_ohlc_types_match() -> None:
    result = compare_observation("005930", "2026-01-01", _row(100), _row(100.0))
    assert result["status"] == "MATCH"
    assert result["field_mismatch_count"] == 0


def test_one_field_difference_is_detected() -> None:
    naver = _row(100.0)
    naver["close"] = 101.01
    result = compare_observation("005930", "2026-01-01", _row(100), naver)
    assert result["status"] == "MISMATCH"
    assert result["field_mismatch_count"] == 1


def test_missing_naver_date_is_detected() -> None:
    result = compare_observation("005930", "2026-01-01", _row(100), None)
    assert result["status"] == "NAVER_DATE_MISSING"
    assert result["field_mismatch_count"] == len(OHLC_FIELDS)


def test_validation_performs_no_production_store_writes(tmp_path: Path) -> None:
    tickers = [f"{number:06d}" for number in range(1, 41)]
    dates = pd.to_datetime(_dates())

    class ReadOnlyStore:
        def __init__(self) -> None:
            self.write_calls = 0

        def load_metadata(self, ticker: str) -> dict[str, object]:
            return {"row_count": 20, "actual_date_max": "2026-01-20"}

        def load_daily_source(self, ticker: str, start=None, end=None) -> pd.DataFrame:
            return pd.DataFrame([_row(float(index + 100)) for index in range(20)], index=dates)

        def save_full(self, *args, **kwargs):
            self.write_calls += 1
            raise AssertionError("validation must not write production stores")

    class FakeProvider:
        def __init__(self) -> None:
            self.calls = 0

        def load_daily(self, ticker: str, start: str, end: str) -> pd.DataFrame:
            self.calls += 1
            return pd.DataFrame([_row(float(index + 100)) for index in range(20)], index=dates)

        def call_audit(self) -> dict[str, int]:
            return {"logical_fetch_count": self.calls, "naver_http_call_count": self.calls}

    roots = {name: tmp_path / name for name in ("adjusted", "raw", "index")}
    for path in roots.values():
        path.mkdir()
        (path / "sentinel").write_text("unchanged", encoding="utf-8")
    store = ReadOnlyStore()
    provider = FakeProvider()
    result = run_validation(
        active_common_tickers=tickers,
        store=store,
        provider=provider,
        adjusted_root=roots["adjusted"],
        artifact_dir=tmp_path / "artifacts",
        fingerprint_roots=roots,
    )
    assert result["final_verdict"] == "PASS"
    assert store.write_calls == 0
    assert result["production_adjusted_store_unchanged"] is True
    assert result["production_raw_store_unchanged"] is True
    assert result["production_index_store_unchanged"] is True

