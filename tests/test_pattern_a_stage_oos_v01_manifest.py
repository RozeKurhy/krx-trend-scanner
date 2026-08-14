"""pattern_a_stage_oos_v01_manifest.py의 OOS Ground Truth Freeze 검증 테스트.

이 테스트는 OOS manifest의 무결성 및 엄격한 독립성(Blind Policy)을 검증한다:
- 중복 키 없음
- ISO 날짜 파싱 가능
- PatternAStage enum 유효성
- 텍스트 필드(selection_reason, manual_stage_reason, episode_notes 등) 비어있지 않음
- 기존 Stage calibration dataset(46건)과의 (ticker, date) 중복 없음
- 기존 calibration ticker(27개)와의 완전한 ticker 독립성
- classifier (`pattern_a_stage`) 및 score (`pattern_a_score`) import 금지 검증
- 5개 Stage(WEAK, BASE, TRANSITION, EARLY_TREND, PROGRESSED) 전 영역 커버리지
- 캐시 데이터 로드 가능성
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS
from trend_scanner.validation.pattern_a_stage_oos_v01_manifest import (
    PATTERN_A_STAGE_OOS_V01_LABELS,
    STAGE_OOS_V01_DATASET_VERSION,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"
_MANIFEST_PATH = (
    _REPO_ROOT
    / "src"
    / "trend_scanner"
    / "validation"
    / "pattern_a_stage_oos_v01_manifest.py"
)


def test_manifest_version_string():
    assert STAGE_OOS_V01_DATASET_VERSION == "pattern_a_stage_oos_v0.1_freeze"


def test_manifest_has_no_duplicate_ticker_snapshot_date_keys():
    keys = [(spec.ticker, spec.snapshot_date) for spec in PATTERN_A_STAGE_OOS_V01_LABELS]
    assert len(keys) == len(set(keys)), f"Duplicate (ticker, date) keys found: {len(keys)} vs {len(set(keys))}"


def test_all_snapshot_dates_are_iso_parseable():
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        parsed = date.fromisoformat(spec.snapshot_date)
        assert parsed.year >= 2011, f"Unexpected date: {spec.snapshot_date}"


def test_all_manual_stages_are_valid_pattern_a_stage_enums():
    valid_stages = {
        PatternAStage.WEAK,
        PatternAStage.BASE,
        PatternAStage.TRANSITION,
        PatternAStage.EARLY_TREND,
        PatternAStage.PROGRESSED,
    }
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        assert isinstance(spec.manual_stage, PatternAStage)
        assert spec.manual_stage in valid_stages


def test_all_required_text_fields_are_non_empty():
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        assert spec.ticker and len(spec.ticker) == 6, f"Invalid ticker: {spec.ticker}"
        assert spec.name.strip(), f"Empty name for {spec.ticker}"
        assert spec.selection_group.strip(), f"Empty selection_group for {spec.ticker}"
        assert spec.selection_reason.strip(), f"Empty selection_reason for {spec.ticker}"
        assert spec.manual_stage_reason.strip(), f"Empty manual_stage_reason for {spec.ticker}"
        assert spec.episode_notes.strip(), f"Empty episode_notes for {spec.ticker}"
        assert spec.source_notes.strip(), f"Empty source_notes for {spec.ticker}"
        assert spec.manual_confidence in {"HIGH", "MEDIUM"}, f"Invalid confidence for {spec.ticker}"


def test_no_overlap_with_calibration_truth_set():
    calib_keys = {(s.ticker, s.snapshot_date) for s in PATTERN_A_STAGE_LABELS}
    oos_keys = {(s.ticker, s.snapshot_date) for s in PATTERN_A_STAGE_OOS_V01_LABELS}
    overlap = calib_keys & oos_keys
    assert len(overlap) == 0, f"Found overlapping keys with calibration set: {overlap}"


def test_all_tickers_are_independent_new_tickers():
    calib_tickers = {s.ticker for s in PATTERN_A_STAGE_LABELS}
    oos_tickers = {s.ticker for s in PATTERN_A_STAGE_OOS_V01_LABELS}
    overlap_tickers = calib_tickers & oos_tickers
    assert len(overlap_tickers) == 0, f"Found overlapping tickers with calibration set: {overlap_tickers}"
    assert len(oos_tickers) >= 20, f"Expected at least 20 unique tickers, got {len(oos_tickers)}"


def test_manifest_module_does_not_import_classifier_or_score():
    source = _MANIFEST_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert "pattern_a_stage" not in alias.name, f"Imported pattern_a_stage in manifest: {alias.name}"
                assert "pattern_a_score" not in alias.name, f"Imported pattern_a_score in manifest: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            module_name = node.module or ""
            assert "pattern_a_stage" not in module_name, f"Imported from pattern_a_stage in manifest: {module_name}"
            assert "pattern_a_score" not in module_name, f"Imported from pattern_a_score in manifest: {module_name}"


def test_stage_distribution_covers_all_five_stages():
    counts: dict[PatternAStage, int] = {}
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        counts[spec.manual_stage] = counts.get(spec.manual_stage, 0) + 1

    expected_stages = [
        PatternAStage.WEAK,
        PatternAStage.BASE,
        PatternAStage.TRANSITION,
        PatternAStage.EARLY_TREND,
        PatternAStage.PROGRESSED,
    ]
    for st in expected_stages:
        assert counts.get(st, 0) >= 5, f"Stage {st} has only {counts.get(st, 0)} snapshots (min 5 required)"


def test_total_snapshot_count_within_target_range():
    total = len(PATTERN_A_STAGE_OOS_V01_LABELS)
    assert 30 <= total <= 40, f"Total snapshots {total} outside recommended range 30~40"


def test_all_candidates_have_valid_cached_raw_data():
    import pandas as pd
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        df = cache.load(spec.ticker)
        assert df is not None and not df.empty, f"Missing cache for {spec.ticker} ({spec.name})"
        ts = pd.Timestamp(spec.snapshot_date)
        assert df.index.min() <= ts, f"Cache start date {df.index.min()} after snapshot {spec.snapshot_date}"
        assert df.index.max() >= ts, f"Cache end date {df.index.max()} before snapshot {spec.snapshot_date}"
