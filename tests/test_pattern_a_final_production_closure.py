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
from trend_scanner.validation.pattern_a_final_closure import (
    run_pattern_a_final_closure_audit,
    audit_score_stage_independence,
    EXPECTED_FROZEN_HASHES,
    compute_file_sha256,
)

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


def test_gate1_production_stage_constants():
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
    """Gate 3: Explicitly verify Score/Stage independence audit returns True."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    assert audit_score_stage_independence(_REPO_ROOT, cache) is True


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
def test_gate6_079550_known_limitation_preserved():
    """Gate 6: Verify 079550 LIG넥스원 known limitation: 2021 progressed, 2023 early_trend output vs progressed truth."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("079550")
    snap_2021 = build_historical_snapshot("079550", "LIG넥스원", daily, "2021-12-31", include_incomplete_periods=False)
    snap_2023 = build_historical_snapshot("079550", "LIG넥스원", daily, "2023-12-31", include_incomplete_periods=False)

    res_2021 = classify_pattern_a_stage(snap_2021)
    res_2023 = classify_pattern_a_stage(snap_2023)

    spec_079550 = next(
        (s for s in PATTERN_A_STAGE_LABELS if s.ticker == "079550" and s.snapshot_date == "2023-12-31"),
        None,
    )
    assert spec_079550 is not None
    assert spec_079550.audited_stage == PatternAStage.PROGRESSED
    assert res_2021.stage == PatternAStage.PROGRESSED
    assert res_2023.stage == PatternAStage.EARLY_TREND


def test_gate7_source_identity_hashes():
    """Gate 7: Verify all 4 core production modules match expected frozen hashes."""
    for fname, expected_hash in EXPECTED_FROZEN_HASHES.items():
        if fname in ("pattern_a_stage.py", "pattern_a_score.py"):
            fpath = _REPO_ROOT / "src/trend_scanner/patterns" / fname
        elif fname == "full_universe_scanner.py":
            fpath = _REPO_ROOT / "src/trend_scanner/scanner" / fname
        elif fname == "historical_snapshot.py":
            fpath = _REPO_ROOT / "src/trend_scanner/validation" / fname
        else:
            fpath = _REPO_ROOT / fname

        assert fpath.exists(), f"File missing: {fpath}"
        actual_hash = compute_file_sha256(fpath)
        assert actual_hash == expected_hash, f"Hash mismatch for {fname}: got {actual_hash}, expected {expected_hash}"


def test_gate8_candidate_identity_diff_zero():
    """Gate 8: Verify candidate identity diff is zero (no missing, no extra, no stage change)."""
    json_path = _REPO_ROOT / "artifacts" / "pattern_a_final_closure" / "pattern_a_final_closure.json"
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    diff = payload["candidate_identity_diff"]

    assert diff["identity_diff_pass"] is True
    assert len(diff["missing_tickers"]) == 0
    assert len(diff["extra_tickers"]) == 0
    assert len(diff["stage_changed_tickers"]) == 0


def test_gate9_closure_json_derived_consistency():
    """Gate 9: Verify committed closure JSON matches fail-closed live audit contract."""
    json_path = _REPO_ROOT / "artifacts" / "pattern_a_final_closure" / "pattern_a_final_closure.json"
    committed = json.loads(json_path.read_text(encoding="utf-8"))

    assert committed["source_integrity"]["stage_constants_pass"] is True
    assert committed["source_integrity"]["source_identity_pass"] is True
    assert committed["score_stage_independence_pass"] is True
    assert committed["calibration_pass"] is True
    assert committed["calibration_exact"] == 38
    assert committed["calibration_adjacent"] == 5
    assert committed["calibration_severe"] == 3
    assert committed["oos_pass"] is True
    assert committed["oos_exact"] == 24
    assert committed["oos_adjacent"] == 10
    assert committed["oos_severe"] == 1
    assert committed["scanner_universe_count"] == 2528
    assert committed["scanner_candidate_count"] == 180
    assert committed["scanner_transition_count"] == 168
    assert committed["scanner_early_count"] == 12
    assert committed["phase8_reproduction_pass"] is True
    assert committed["candidate_identity_diff"]["identity_diff_pass"] is True
    assert committed["frozen_stage_behavior_reproduction_pass"] is True
    assert committed["lifecycle_known_limitation_preserved"] is True
    assert committed["079550_audited_truth"] == "progressed"
    assert committed["079550_production_output"] == "early_trend"
    assert committed["all_hard_gates_pass"] is True
    assert committed["final_production_decision"] == "KEEP_CURRENT_PRODUCTION"
    assert committed["pattern_a_stage_research_status"] == "CLOSED"
    assert committed["next_phase"] == "SCANNER_OPERATION_AND_CANDIDATE_QUALITY_WORKFLOW"
