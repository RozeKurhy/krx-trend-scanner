"""Validation tests for Stage v0.2 Comparator Parity and Baseline Non-Regression."""

from __future__ import annotations

from pathlib import Path
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import PATTERN_A_STAGE_OOS_V01_LABELS
from trend_scanner.validation.stage_v02.comparator import (
    StageMatchClass,
    classify_stage_match,
)
from trend_scanner.validation.stage_v02.candidate_classifier import (
    classify_pattern_a_stage_v02_candidate,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _cache_available() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_LABELS[:3]:
        daily = cache.load(spec.ticker)
        if daily is None or daily.empty:
            return False
    return True


_HAS_CACHE = _cache_available()


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_comparator_parity_on_calibration46():
    """Verify 46/46 comparator parity on Calibration 46 manifest."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    exact_count = 0
    adj_count = 0
    sev_count = 0

    for spec in PATTERN_A_STAGE_LABELS:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False)
        v01_res = classify_pattern_a_stage(snap)
        match_res = classify_stage_match(spec.audited_stage, v01_res.stage)

        if match_res == StageMatchClass.EXACT:
            exact_count += 1
        elif match_res == StageMatchClass.ADJACENT:
            adj_count += 1
        elif match_res == StageMatchClass.SEVERE:
            sev_count += 1

    assert exact_count == 38
    assert adj_count == 5
    assert sev_count == 3


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_comparator_parity_on_oos35():
    """Verify 35/35 comparator parity on Existing OOS 35 manifest."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    exact_count = 0
    adj_count = 0
    sev_count = 0

    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False)
        v01_res = classify_pattern_a_stage(snap)
        match_res = classify_stage_match(spec.manual_stage, v01_res.stage)

        if match_res == StageMatchClass.EXACT:
            exact_count += 1
        elif match_res == StageMatchClass.ADJACENT:
            adj_count += 1
        elif match_res == StageMatchClass.SEVERE:
            sev_count += 1

    assert exact_count == 24
    assert adj_count == 10
    assert sev_count == 1


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_candidate_benchmark_protection_and_non_regression():
    """Verify Candidate preserves baseline exact cases and satisfies benchmark protection criteria."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    c_exact = 0
    c_sev = 0
    o_exact = 0
    o_sev = 0

    for spec in PATTERN_A_STAGE_LABELS:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False)
        cand_res = classify_pattern_a_stage_v02_candidate(snap)
        match_res = classify_stage_match(spec.audited_stage, cand_res.candidate_stage)
        if match_res == StageMatchClass.EXACT:
            c_exact += 1
        elif match_res == StageMatchClass.SEVERE:
            c_sev += 1

    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        snap = build_historical_snapshot(spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False)
        cand_res = classify_pattern_a_stage_v02_candidate(snap)
        match_res = classify_stage_match(spec.manual_stage, cand_res.candidate_stage)
        if match_res == StageMatchClass.EXACT:
            o_exact += 1
        elif match_res == StageMatchClass.SEVERE:
            o_sev += 1

    assert c_exact >= 38, f"Calibration Exact expected >= 38, got {c_exact}"
    assert c_sev <= 3, f"Calibration Severe expected <= 3, got {c_sev}"
    assert o_exact >= 24, f"OOS Exact expected >= 24, got {o_exact}"
    assert o_sev <= 1, f"OOS Severe expected <= 1, got {o_sev}"
