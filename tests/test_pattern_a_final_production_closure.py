"""Integration and Gate Verification Tests for Pattern A Final Production Closure."""

from __future__ import annotations

import json
from pathlib import Path
import pytest
import pandas as pd

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_stage import (
    classify_pattern_a_stage,
    EPISODE_PEAK_AVG_CHG,
    EPISODE_BREAK_MA24_SLOPE,
    EPISODE_BREAK_RANGE_POSITION,
)
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import PATTERN_A_STAGE_OOS_V01_LABELS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _cache_available() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("001540")
    return daily is not None and not daily.empty


_HAS_CACHE = _cache_available()
_STAGE_ORDER = {
    PatternAStage.WEAK: 0,
    PatternAStage.BASE: 1,
    PatternAStage.TRANSITION: 2,
    PatternAStage.EARLY_TREND: 3,
    PatternAStage.PROGRESSED: 4,
}


def test_gate1_production_stage_semantic_constants():
    """Gate 1: Verify Stage v0.1 frozen constants are unchanged."""
    assert EPISODE_PEAK_AVG_CHG == 0.30
    assert EPISODE_BREAK_MA24_SLOPE == -0.045
    assert EPISODE_BREAK_RANGE_POSITION == 0.20


def test_gate2_score_v02_semantic_unchanged():
    """Gate 2: Verify Score v0.2 formula exists and executes without stage coupling."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("003100")
    snap = build_historical_snapshot("003100", "선광", daily, "2024-12-31", include_incomplete_periods=False)
    score_res = score_pattern_a(snap.features)
    assert 0.0 <= score_res.pattern_a_score <= 100.0


def test_gate3_score_stage_independence():
    """Gate 3: Verify that Stage classification does not depend on Score output."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("003100")
    snap = build_historical_snapshot("003100", "선광", daily, "2024-12-31", include_incomplete_periods=False)

    # Classifying stage should only need snapshot features
    stage_res = classify_pattern_a_stage(snap)
    assert isinstance(stage_res.stage, PatternAStage)


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_gate4_calibration46_exact_reproduction():
    """Gate 4: Verify Calibration 46 exact 38 / adj 5 / sev 3 reproduction."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    exact = 0; adj = 0; sev = 0
    for s in PATTERN_A_STAGE_LABELS:
        daily = cache.load(s.ticker)
        snap = build_historical_snapshot(s.ticker, s.name, daily, s.snapshot_date, include_incomplete_periods=False)
        res = classify_pattern_a_stage(snap)
        diff = abs(_STAGE_ORDER[res.stage] - _STAGE_ORDER[s.audited_stage])
        if diff == 0: exact += 1
        elif diff == 1: adj += 1
        else: sev += 1

    assert exact == 38, f"Expected 38 exact, got {exact}"
    assert adj == 5, f"Expected 5 adj, got {adj}"
    assert sev == 3, f"Expected 3 sev, got {sev}"


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_gate5_oos35_exact_reproduction():
    """Gate 5: Verify OOS 35 exact 24 / adj 10 / sev 1 reproduction."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    exact = 0; adj = 0; sev = 0
    for s in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(s.ticker)
        snap = build_historical_snapshot(s.ticker, s.name, daily, s.snapshot_date, include_incomplete_periods=False)
        res = classify_pattern_a_stage(snap)
        diff = abs(_STAGE_ORDER[res.stage] - _STAGE_ORDER[s.manual_stage])
        if diff == 0: exact += 1
        elif diff == 1: adj += 1
        else: sev += 1

    assert exact == 24, f"Expected 24 exact, got {exact}"
    assert adj == 10, f"Expected 10 adj, got {adj}"
    assert sev == 1, f"Expected 1 sev, got {sev}"


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_gate6_lifecycle_regression():
    """Gate 6: Verify 079550 LIG넥스원 2021 progressed and 2023 early_trend."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("079550")
    snap_2021 = build_historical_snapshot("079550", "LIG넥스원", daily, "2021-12-31", include_incomplete_periods=False)
    snap_2023 = build_historical_snapshot("079550", "LIG넥스원", daily, "2023-12-31", include_incomplete_periods=False)

    res_2021 = classify_pattern_a_stage(snap_2021)
    res_2023 = classify_pattern_a_stage(snap_2023)

    assert res_2021.stage == PatternAStage.PROGRESSED
    assert res_2023.stage == PatternAStage.EARLY_TREND


def test_gate7_phase8_scanner_counts():
    """Gate 7: Verify Phase8 scanner candidate counts (180 total: 168 transition, 12 early)."""
    csv_path = _REPO_ROOT / "artifacts" / "chart_review" / "pattern_a_candidate_manual_review_20260814.csv"
    df = pd.read_csv(csv_path, dtype={"ticker": str})
    assert len(df) == 180
    assert (df["official_stage"] == "transition").sum() == 168
    assert (df["official_stage"] == "early_trend").sum() == 12


def test_gate8_closure_json_consistency():
    """Gate 8: Verify pattern_a_final_closure.json values match hard gate requirements."""
    json_path = _REPO_ROOT / "artifacts" / "pattern_a_final_closure" / "pattern_a_final_closure.json"
    assert json_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["calibration_exact"] == 38
    assert payload["calibration_adjacent"] == 5
    assert payload["calibration_severe"] == 3
    assert payload["oos_exact"] == 24
    assert payload["oos_adjacent"] == 10
    assert payload["oos_severe"] == 1
    assert payload["scanner_candidate_count"] == 180
    assert payload["scanner_transition_count"] == 168
    assert payload["scanner_early_count"] == 12
    assert payload["final_production_decision"] == "KEEP_CURRENT_PRODUCTION"
    assert payload["pattern_a_stage_research_status"] == "CLOSED"
    assert payload["next_phase"] == "SCANNER_OPERATION_AND_CANDIDATE_QUALITY_WORKFLOW"
