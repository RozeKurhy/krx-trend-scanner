"""pattern_a_stage_manifest.py의 Stage Label Audit Freeze 검증 테스트.

이 테스트는 manifest 구조만 검증한다(중복 키, 날짜 파싱, enum 유효성,
source_dataset 기록, Stage별 최소 건수) — Stage classifier(threshold/
rule)는 아직 구현되지 않았으므로 여기서 분류 정확도를 검증하지 않는다.
그건 Commit B(classifier v0.1) 이후 별도 테스트로 다룬다.
"""

from __future__ import annotations

from datetime import date

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.validation.pattern_a_stage_manifest import PATTERN_A_STAGE_LABELS

_ALLOWED_SOURCE_DATASETS = {
    "OOS2_v0.2_manifest",
    "OOS_v0.1_stage_audit",
    "negative_control_compare",
    "holdout_early_trend_compare",
}

_MIN_PER_STAGE = 5


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
