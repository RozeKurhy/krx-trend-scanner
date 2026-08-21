"""pattern_a_stage_manifest.py의 Stage Label Audit Freeze 검증 테스트.

이 테스트는 manifest 구조만 검증한다(중복 키, 날짜 파싱, enum 유효성,
source_dataset 기록, Stage별 최소 건수, provenance, Feature reconstruction,
BASE 정의의 semantic consistency) — Stage classifier(threshold/rule)는
아직 구현되지 않았으므로 여기서 분류 정확도를 검증하지 않는다. 그건
Commit B(classifier v0.1) 이후 별도 테스트로 다룬다.

provenance/reconstruction test는 이 manifest가 참조하는 4개 원본
dataset(OOS_V02_VALIDATION_SNAPSHOTS/OOS_V01_STAGE_AUDIT/
NEGATIVE_CONTROL_SNAPSHOTS/HOLDOUT_SNAPSHOTS)을 import한다.
score_v02_candidate_compare.py는 scripts/라 패키지가 아니라서 importlib로
파일 경로 기준 직접 로드한다 — 다른 재현성 테스트 파일과 동일한 패턴.
"""

from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path

import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot
from trend_scanner.validation.oos_v01_manifest import OOS_V01_STAGE_AUDIT
from trend_scanner.validation.oos_v02_manifest import OOS_V02_VALIDATION_SNAPSHOTS
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"

_COMPARE_SCRIPT_PATH = _REPO_ROOT / "scripts" / "score_v02_candidate_compare.py"
_spec = importlib.util.spec_from_file_location("score_v02_candidate_compare", _COMPARE_SCRIPT_PATH)
_compare = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
sys.modules[_spec.name] = _compare
_spec.loader.exec_module(_compare)

_ALLOWED_SOURCE_DATASETS = {
    "OOS2_v0.2_manifest",
    "OOS_v0.1_stage_audit",
    "negative_control_compare",
    "holdout_early_trend_compare",
}

_MIN_PER_STAGE = 5

_OOS2_KEYS = {(s.ticker, s.snapshot_date) for s in OOS_V02_VALIDATION_SNAPSHOTS}
_NEGCTRL_KEYS = {(d["ticker"], d["date"]) for d in _compare.NEGATIVE_CONTROL_SNAPSHOTS}
_HOLDOUT_EARLY_TREND_KEYS = {
    (d["ticker"], d["date"]) for d in _compare.HOLDOUT_SNAPSHOTS if d["label"] == "early_trend"
}


def _cache_has_all_manifest_tickers() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for spec in PATTERN_A_STAGE_LABELS:
        daily = cache.load(spec.ticker)
        if daily is None or daily.empty:
            return False
    return True


_HAS_CACHE = _cache_has_all_manifest_tickers()
_SKIP_REASON = "Stage manifest 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


def test_manifest_has_no_duplicate_ticker_snapshot_date_keys():
    keys = [(spec.ticker, spec.snapshot_date) for spec in PATTERN_A_STAGE_LABELS]
    assert len(keys) == len(set(keys))


def test_all_snapshot_dates_are_iso_parseable():
    for spec in PATTERN_A_STAGE_LABELS:
        date.fromisoformat(spec.snapshot_date)


def test_all_audited_stage_values_are_valid_pattern_a_stage_members():
    for spec in PATTERN_A_STAGE_LABELS:
        assert isinstance(spec.audited_stage, PatternAStage)
        assert spec.audited_stage in PatternAStage


def test_all_rows_have_non_empty_source_dataset_and_reason():
    for spec in PATTERN_A_STAGE_LABELS:
        assert spec.source_dataset in _ALLOWED_SOURCE_DATASETS
        assert spec.stage_reason.strip() != ""


def test_stage_reason_does_not_reference_forward_looking_outcome_language():
    """stage_reason은 snapshot 시점까지의 Feature 값만 근거로 든다 —
    forward-looking 표현("이후")은 notes에만 허용하고 stage_reason에는
    쓰지 않는다."""
    for spec in PATTERN_A_STAGE_LABELS:
        assert "이후" not in spec.stage_reason


def test_each_stage_category_has_minimum_five_cases():
    counts: dict[PatternAStage, int] = {stage: 0 for stage in PatternAStage}
    for spec in PATTERN_A_STAGE_LABELS:
        counts[spec.audited_stage] += 1
    for stage, count in counts.items():
        assert count >= _MIN_PER_STAGE, f"{stage} has only {count} cases"


def test_manifest_totals_46_rows_across_four_source_datasets():
    assert len(PATTERN_A_STAGE_LABELS) == 46
    by_source: dict[str, int] = {}
    for spec in PATTERN_A_STAGE_LABELS:
        by_source[spec.source_dataset] = by_source.get(spec.source_dataset, 0) + 1
    assert by_source == {
        "OOS2_v0.2_manifest": 22,
        "OOS_v0.1_stage_audit": 13,
        "negative_control_compare": 8,
        "holdout_early_trend_compare": 3,
    }


def test_manifest_does_not_import_score_pattern_a():
    """Stage classifier -> Score dependency 금지 원칙: manifest 모듈이
    pattern_a_score 모듈을 import하지 않는지 확인한다(docstring 설명
    문장에서 "score_pattern_a"를 언급하는 것과는 별개 — 실제 import 여부만
    본다)."""
    import trend_scanner.validation.pattern_a_stage_manifest as manifest_module

    assert not hasattr(manifest_module, "score_pattern_a")


def test_source_provenance_matches_original_dataset():
    """각 StageLabelSpec의 (ticker, snapshot_date, source_dataset) 조합이
    실제로 해당 원본 dataset 안에 존재하는지 확인한다. source_dataset
    문자열 오타나 잘못된 provenance 연결을 여기서 잡는다."""
    for spec in PATTERN_A_STAGE_LABELS:
        key = (spec.ticker, spec.snapshot_date)
        if spec.source_dataset == "OOS2_v0.2_manifest":
            assert key in _OOS2_KEYS, f"{key} not found in OOS_V02_VALIDATION_SNAPSHOTS"
        elif spec.source_dataset == "OOS_v0.1_stage_audit":
            assert key in OOS_V01_STAGE_AUDIT, f"{key} not found in OOS_V01_STAGE_AUDIT"
        elif spec.source_dataset == "negative_control_compare":
            assert key in _NEGCTRL_KEYS, f"{key} not found in NEGATIVE_CONTROL_SNAPSHOTS"
        elif spec.source_dataset == "holdout_early_trend_compare":
            assert key in _HOLDOUT_EARLY_TREND_KEYS, (
                f"{key} not found in HOLDOUT_SNAPSHOTS with label=early_trend"
            )
        else:
            pytest.fail(f"unrecognized source_dataset: {spec.source_dataset!r}")


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_base_stage_does_not_require_weekly_positive_or_mild_slope():
    """semantic consistency 회귀: docs/patterns/pattern_a/validation/stage_label_audit_freeze.md의
    BASE 최종 정의는 weekly_ma12_slope>0/ma24_slope cutoff/range_position
    cutoff를 필수조건으로 두지 않는다고 명시한다. 이 매니페스트에는 이미
    weekly_ma12_slope<=0이거나 ma24_slope가 가파른(<=-0.045) BASE 사례가
    존재한다 — 이 테스트는 그 사례들이 실제로 존재하고 여전히 BASE로
    남아있는지 확인해서, 누군가 나중에 diagnostic checklist를 global
    rule처럼 다시 강제하는 방향으로 라벨을 "정리"하지 못하게 막는다."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    base_specs = {(s.ticker, s.snapshot_date): s for s in PATTERN_A_STAGE_LABELS if s.audited_stage == PatternAStage.BASE}

    weekly_negative_or_zero = []
    steep_ma24_slope = []
    for (ticker, snapshot_date), spec in base_specs.items():
        daily = cache.load(ticker)
        snap = build_historical_snapshot(
            ticker, spec.name, daily, snapshot_date, include_incomplete_periods=False
        )
        f = snap.features
        if f.weekly_ma12_slope <= 0:
            weekly_negative_or_zero.append((ticker, snapshot_date))
        if f.ma24_slope <= -0.045:
            steep_ma24_slope.append((ticker, snapshot_date))

    assert weekly_negative_or_zero, "BASE 중 weekly_ma12_slope<=0인 사례가 없다 — 필수조건화됐을 가능성"
    assert steep_ma24_slope, "BASE 중 ma24_slope<=-0.045인 사례가 없다 — checklist가 필수조건화됐을 가능성"


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_all_46_snapshots_reconstruct_without_exception():
    """manifest 46건 전부가 build_historical_snapshot을 예외 없이
    통과해야 한다. try/except로 감춰서 "돌긴 돌았다"만 증명하는 걸
    피한다 — 여기서 실제로 예외가 나면 이 테스트가 그대로 실패해야
    한다(OOS2 라운드의 test_every_manifest_snapshot_produces_exactly_
    one_output_row와 동일 원칙)."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    seen = set()
    for spec in PATTERN_A_STAGE_LABELS:
        daily = cache.load(spec.ticker)
        build_historical_snapshot(
            spec.ticker, spec.name, daily, spec.snapshot_date, include_incomplete_periods=False
        )
        seen.add((spec.ticker, spec.snapshot_date))
    manifest_keys = {(spec.ticker, spec.snapshot_date) for spec in PATTERN_A_STAGE_LABELS}
    assert seen == manifest_keys
    assert len(seen) == len(PATTERN_A_STAGE_LABELS)
