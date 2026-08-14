"""pattern_a_stage_oos_v01_manifest.py의 OOS Ground Truth Freeze 검증 테스트.

이 테스트는 OOS manifest의 무결성 및 엄격한 독립성(Blind Policy)을 검증한다:
1. 35개 frozen identity (ticker, snapshot_date, manual_stage) 불변 회귀 검증
2. ISO 날짜 파싱 및 PatternAStage enum 유효성
3. 텍스트 필드(selection_reason, manual_stage_reason, episode_notes 등) 비어있지 않음
4. 기존 모든 validation dataset과의 중복 검증 (Code-enforced):
   - Stage calibration 46건: exact key overlap = 0, ticker overlap = 0
   - OOS v0.1 diagnostic 29건: exact key overlap = 0
   - OOS v0.2 validation 22건: exact key overlap = 0
   - Negative Control 8건: exact key overlap = 0
   - Holdout datasets: exact key overlap = 0
5. classifier (`pattern_a_stage`) 및 score (`pattern_a_score`) import 금지 검증 (AST)
6. 5개 Stage(WEAK, BASE, TRANSITION, EARLY_TREND, PROGRESSED) 각각 정확히 7건 (총 35건)
7. HistoricalSnapshot 35건 provenance reconstruction & future bar leakage 없음 검증 (cache guard)
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.oos_v01_manifest import OOS_V01_DIAGNOSTIC_SNAPSHOTS
from trend_scanner.validation.oos_v02_manifest import OOS_V02_VALIDATION_SNAPSHOTS
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

# score_v02_candidate_compare.py 로드 (NEGATIVE_CONTROL_SNAPSHOTS / HOLDOUT_SNAPSHOTS 용)
_COMPARE_SCRIPT_PATH = _REPO_ROOT / "scripts" / "score_v02_candidate_compare.py"
_spec = importlib.util.spec_from_file_location("score_v02_candidate_compare", _COMPARE_SCRIPT_PATH)
_compare = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = _compare
_spec.loader.exec_module(_compare)

# 35개 frozen baseline identity fixture (e3506be 기준)
_FROZEN_35_IDENTITIES: tuple[tuple[str, str, PatternAStage], ...] = (
    # WEAK (7)
    ("006360", "2023-10-31", PatternAStage.WEAK),
    ("006360", "2022-11-30", PatternAStage.WEAK),
    ("009830", "2024-04-30", PatternAStage.WEAK),
    ("018880", "2024-06-30", PatternAStage.WEAK),
    ("000720", "2024-03-31", PatternAStage.WEAK),
    ("035420", "2022-10-31", PatternAStage.WEAK),
    ("004170", "2024-08-31", PatternAStage.WEAK),
    # BASE (7)
    ("017670", "2023-12-31", PatternAStage.BASE),
    ("030200", "2023-10-31", PatternAStage.BASE),
    ("024110", "2023-11-30", PatternAStage.BASE),
    ("028260", "2023-10-31", PatternAStage.BASE),
    ("005940", "2023-10-31", PatternAStage.BASE),
    ("271560", "2024-08-31", PatternAStage.BASE),
    ("068270", "2023-09-30", PatternAStage.BASE),
    # TRANSITION (7)
    ("000660", "2023-05-31", PatternAStage.TRANSITION),
    ("005830", "2023-06-30", PatternAStage.TRANSITION),
    ("006260", "2022-10-31", PatternAStage.TRANSITION),
    ("028050", "2021-03-31", PatternAStage.TRANSITION),
    ("003230", "2022-04-30", PatternAStage.TRANSITION),
    ("035900", "2020-07-31", PatternAStage.TRANSITION),
    ("055550", "2024-01-31", PatternAStage.TRANSITION),
    # EARLY_TREND (7)
    ("000660", "2023-11-30", PatternAStage.EARLY_TREND),
    ("005850", "2023-04-30", PatternAStage.EARLY_TREND),
    ("005830", "2023-12-31", PatternAStage.EARLY_TREND),
    ("006260", "2023-02-28", PatternAStage.EARLY_TREND),
    ("028050", "2021-06-30", PatternAStage.EARLY_TREND),
    ("003230", "2022-11-30", PatternAStage.EARLY_TREND),
    ("272210", "2024-03-31", PatternAStage.EARLY_TREND),
    # PROGRESSED (7)
    ("000660", "2024-06-30", PatternAStage.PROGRESSED),
    ("003230", "2024-06-30", PatternAStage.PROGRESSED),
    ("086520", "2023-07-31", PatternAStage.PROGRESSED),
    ("086520", "2023-11-30", PatternAStage.PROGRESSED),
    ("035900", "2023-06-30", PatternAStage.PROGRESSED),
    ("138040", "2024-08-31", PatternAStage.PROGRESSED),
    ("006260", "2023-07-31", PatternAStage.PROGRESSED),
)


def _cache_has_all_manifest_tickers() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        if daily is None or daily.empty:
            return False
    return True


_HAS_CACHE = _cache_has_all_manifest_tickers()
_SKIP_REASON = "OOS manifest 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


def test_manifest_version_string():
    assert STAGE_OOS_V01_DATASET_VERSION == "pattern_a_stage_oos_v0.1_freeze"


def test_manifest_has_no_duplicate_ticker_snapshot_date_keys():
    keys = [(spec.ticker, spec.snapshot_date) for spec in PATTERN_A_STAGE_OOS_V01_LABELS]
    assert len(keys) == len(set(keys)), f"Duplicate (ticker, date) keys found: {len(keys)} vs {len(set(keys))}"


def test_frozen_identities_and_stages_are_exact_match():
    current_identities = tuple(
        (spec.ticker, spec.snapshot_date, spec.manual_stage)
        for spec in PATTERN_A_STAGE_OOS_V01_LABELS
    )
    assert current_identities == _FROZEN_35_IDENTITIES, "Frozen 35 identities/stages were unexpectedly modified!"


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


def test_exact_overlap_with_all_existing_validation_datasets_is_zero():
    oos_keys = {(s.ticker, s.snapshot_date) for s in PATTERN_A_STAGE_OOS_V01_LABELS}

    # 1. Stage Calibration (46건)
    calib_keys = {(s.ticker, s.snapshot_date) for s in PATTERN_A_STAGE_LABELS}
    assert len(oos_keys & calib_keys) == 0, f"Overlap with Stage calibration set: {oos_keys & calib_keys}"

    # 2. OOS v0.1 Diagnostic (29건)
    oos1_keys = {(s.ticker, s.snapshot_date) for s in OOS_V01_DIAGNOSTIC_SNAPSHOTS}
    assert len(oos_keys & oos1_keys) == 0, f"Overlap with OOS v0.1 diagnostic set: {oos_keys & oos1_keys}"

    # 3. OOS v0.2 Validation (22건)
    oos2_keys = {(s.ticker, s.snapshot_date) for s in OOS_V02_VALIDATION_SNAPSHOTS}
    assert len(oos_keys & oos2_keys) == 0, f"Overlap with OOS v0.2 validation set: {oos_keys & oos2_keys}"

    # 4. Negative Control (8건)
    neg_keys = {(d["ticker"], d["date"]) for d in _compare.NEGATIVE_CONTROL_SNAPSHOTS}
    assert len(oos_keys & neg_keys) == 0, f"Overlap with Negative Control set: {oos_keys & neg_keys}"

    # 5. Holdout Snapshots
    holdout_keys = {(d["ticker"], d["date"]) for d in _compare.HOLDOUT_SNAPSHOTS}
    assert len(oos_keys & holdout_keys) == 0, f"Overlap with Holdout set: {oos_keys & holdout_keys}"


def test_stage_calibration_ticker_overlap_is_zero():
    calib_tickers = {s.ticker for s in PATTERN_A_STAGE_LABELS}
    oos_tickers = {s.ticker for s in PATTERN_A_STAGE_OOS_V01_LABELS}
    overlap_tickers = calib_tickers & oos_tickers
    assert len(overlap_tickers) == 0, f"Found overlapping tickers with Stage calibration set: {overlap_tickers}"
    assert len(oos_tickers) == 24, f"Expected exactly 24 unique tickers, got {len(oos_tickers)}"


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


def test_stage_distribution_is_exactly_seven_per_stage():
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
        assert counts.get(st, 0) == 7, f"Stage {st} expected exactly 7 snapshots, got {counts.get(st, 0)}"
    assert len(PATTERN_A_STAGE_OOS_V01_LABELS) == 35, f"Total snapshots expected 35, got {len(PATTERN_A_STAGE_OOS_V01_LABELS)}"


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_all_oos_snapshots_reconstruct_without_future_data():
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_OOS_V01_LABELS:
        daily = cache.load(spec.ticker)
        assert daily is not None and not daily.empty, f"Missing cache for {spec.ticker} ({spec.name})"

        snapshot = build_historical_snapshot(
            ticker=spec.ticker,
            name=spec.name,
            daily=daily,
            snapshot_date=spec.snapshot_date,
            include_incomplete_periods=False,
        )

        assert snapshot.requested_snapshot_date == pd.Timestamp(spec.snapshot_date)

        req_ts = pd.Timestamp(spec.snapshot_date)

        # 1. Effective date check (never in the future)
        assert snapshot.effective_as_of is not None
        assert pd.Timestamp(snapshot.effective_as_of) <= req_ts

        # 2. Monthly completed bar check
        assert snapshot.monthly_as_of is not None
        assert pd.Timestamp(snapshot.monthly_as_of) <= req_ts
        assert not snapshot.monthly.empty
        assert snapshot.monthly.index.max() <= pd.Timestamp(snapshot.monthly_as_of)

        # 3. Weekly completed bar check
        assert snapshot.weekly_as_of is not None
        assert pd.Timestamp(snapshot.weekly_as_of) <= req_ts

        # 4. Feature Row calculated without crash
        assert snapshot.features is not None
        assert snapshot.features.ticker == spec.ticker
