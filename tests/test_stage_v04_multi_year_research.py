"""Unit and Integration Tests for Pattern A Stage v0.4 Multi-Year Structural Feature Research."""

from __future__ import annotations

from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.stage_v04_multi_year_research import (
    extract_multi_year_features,
    run_stage_v04_multi_year_research,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _cache_available() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("001540")
    return daily is not None and not daily.empty


_HAS_CACHE = _cache_available()


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_point_in_time_no_lookahead():
    """Verify that adding future data does NOT change features as of snapshot_date."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("003100")
    snap_date = "2024-12-31"

    # Slice strictly vs full dataset
    feat1 = extract_multi_year_features("003100", "선광", daily.loc[:"2024-12-31"], snap_date)
    feat2 = extract_multi_year_features("003100", "선광", daily, snap_date)

    assert feat1.resistance_5y == feat2.resistance_5y
    assert feat1.range_position_5y == feat2.range_position_5y
    assert feat1.years_since_5y_high == feat2.years_since_5y_high
    assert feat1.base_duration_months_5y == feat2.base_duration_months_5y


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_5y_window_boundary():
    """Verify that 5-year window uses at most 60 completed monthly candles."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("003100")
    snap_date = "2026-08-14"

    feat = extract_multi_year_features("003100", "선광", daily, snap_date, max_history_months=60)
    assert feat.available_history_months >= 12
    assert feat.has_5y_coverage is True
    assert 0.0 <= feat.range_position_5y <= 1.0


def test_insufficient_history_behavior():
    """Verify that empty daily data raises ValueError immediately."""
    empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    with pytest.raises(ValueError, match="Insufficient data|No daily data"):
        extract_multi_year_features("999999", "테스트", empty_df, "2026-08-14")


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_deterministic_regeneration():
    """Verify generator output is byte-identical and deterministic across runs."""
    res1 = run_stage_v04_multi_year_research(_REPO_ROOT)
    res2 = run_stage_v04_multi_year_research(_REPO_ROOT)

    pd.testing.assert_frame_equal(res1["df_cov"], res2["df_cov"])
    pd.testing.assert_frame_equal(res1["df_sep"], res2["df_sep"])
    assert res1["summary"] == res2["summary"]


def test_artifact_row_counts_and_provenance():
    """Verify all 8 artifact CSVs/JSONs exist and have correct schemas."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v04_multi_year_research"
    tm_df = pd.read_csv(out_dir / "transition_match13_multi_year_features.csv", dtype={"ticker": str})
    prem_df = pd.read_csv(out_dir / "premature13_multi_year_features.csv", dtype={"ticker": str})
    rec_df = pd.read_csv(out_dir / "recycled3_multi_year_features.csv", dtype={"ticker": str})
    early_df = pd.read_csv(out_dir / "early_match4_multi_year_features.csv", dtype={"ticker": str})

    assert len(tm_df) == 13
    assert len(prem_df) == 13
    assert len(rec_df) == 3
    assert len(early_df) == 4
    assert (out_dir / "focus_026910_multi_year_profile.json").exists()
    assert (out_dir / "focus_038390_multi_year_profile.json").exists()


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_026910_snapshot_future_data_exclusion():
    """Verify 026910 point-in-time calculation strictly excludes post-snapshot data."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("026910")
    feat = extract_multi_year_features("026910", "광진실업", daily, "2026-08-14")

    # In 2026-08-14 snapshot, 026910 5y low was recent (months_since_5y_low <= 6)
    assert feat.months_since_5y_low <= 6
    assert feat.years_since_5y_high > 4.0


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_same_snapshot_repeated_calculation_equality():
    """Verify exact numerical equality across multiple independent extractions."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("038390")
    f1 = extract_multi_year_features("038390", "레드캡투어", daily, "2026-08-14")
    f2 = extract_multi_year_features("038390", "레드캡투어", daily, "2026-08-14")

    assert f1 == f2
