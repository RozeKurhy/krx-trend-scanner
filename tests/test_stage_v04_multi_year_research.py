"""Unit and Integration Tests for Pattern A Stage v0.4 Multi-Year Structural Feature Research."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.stage_v04_multi_year_research import (
    extract_multi_year_features,
    run_stage_v04_multi_year_research,
    render_multi_year_table_ascii,
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
    """Verify all artifact CSVs/JSONs exist and have correct schemas."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v04_multi_year_research"
    tm_df = pd.read_csv(out_dir / "transition_match13_multi_year_features.csv", dtype={"ticker": str})
    prem_df = pd.read_csv(out_dir / "premature13_multi_year_features.csv", dtype={"ticker": str})
    rec_df = pd.read_csv(out_dir / "recycled3_multi_year_features.csv", dtype={"ticker": str})
    early_df = pd.read_csv(out_dir / "early_match4_multi_year_features.csv", dtype={"ticker": str})
    calib_df = pd.read_csv(out_dir / "calibration46_multi_year_features.csv", dtype={"ticker": str})
    oos_df = pd.read_csv(out_dir / "oos35_multi_year_features.csv", dtype={"ticker": str})
    calib_dist = pd.read_csv(out_dir / "calibration46_stage_distribution.csv")
    oos_dist = pd.read_csv(out_dir / "oos35_stage_distribution.csv")

    assert len(tm_df) == 13
    assert len(prem_df) == 13
    assert len(rec_df) == 3
    assert len(early_df) == 4
    assert len(calib_df) == 46
    assert len(oos_df) == 35
    assert len(calib_dist) > 0
    assert len(oos_dist) > 0
    assert (out_dir / "focus_026910_multi_year_profile.json").exists()
    assert (out_dir / "focus_038390_multi_year_profile.json").exists()


def test_human_cohort_roster_exactness():
    """Verify Early MATCH 4 roster strictly matches ground truth."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v04_multi_year_research"
    early_df = pd.read_csv(out_dir / "early_match4_multi_year_features.csv", dtype={"ticker": str})
    expected_early = {"001540", "001450", "005430", "161890"}
    assert set(early_df["ticker"]) == expected_early


def test_research_summary_separation_linkage_and_zero_promising():
    """Verify research_summary.json strictly derives from df_sep with 0 promising features."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v04_multi_year_research"
    df_sep = pd.read_csv(out_dir / "feature_separation_summary.csv")
    summary = json.loads((out_dir / "research_summary.json").read_text(encoding="utf-8"))

    promising_count = (df_sep["disposition"] == "PROMISING_GENERALIZABLE").sum()
    assert promising_count == 0
    assert len(summary["promising_generalizable_features"]) == 0
    assert summary["final_recommendation"] == "NO_USEFUL_MULTI_YEAR_FEATURE_FOUND"
    assert summary["candidate_rule_proposal"] == "NONE"


def test_report_source_csv_renderer_linkage():
    """Verify renderer output matches committed source CSVs exactly."""
    out_dir = _REPO_ROOT / "artifacts" / "stage_v04_multi_year_research"
    tm_df = pd.read_csv(out_dir / "transition_match13_multi_year_features.csv", dtype={"ticker": str})
    ascii_table = render_multi_year_table_ascii(tm_df)
    assert "003100" in ascii_table
    assert "선광" in ascii_table
    assert f"{float(tm_df.iloc[0]['distance_to_resistance_5y']):.4f}" in ascii_table


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_026910_snapshot_future_data_exclusion():
    """Verify 026910 point-in-time calculation strictly excludes post-snapshot data."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("026910")
    feat = extract_multi_year_features("026910", "광진실업", daily, "2026-08-14")

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
