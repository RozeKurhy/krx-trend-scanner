"""Pattern A Evaluator Integration v0.1 유닛 및 통합 테스트.

이 테스트는 다음을 검증한다:
1. Evaluator 호출 시 Score/Stage 결과가 직접 호출 결과와 정확히 동일함 (동일성 & 무변경)
2. Score나 Stage를 cross-mutate하지 않음
3. 동일한 snapshot 입력 시 항상 deterministic한 결과 반환
4. Candidate State 매핑 (WEAK->BLOCKED, BASE->WATCH, TRANSITION/EARLY->CANDIDATE, PROGRESSED->LATE)
5. Diagnostic conflict flag 감지 동작
6. 5대 대표 통합 케이스 (GS건설, SK텔레콤, JYP, SK하이닉스, 에코프로) 검증
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns.pattern_a_evaluator import (
    PatternACandidateState,
    PatternAEvaluationResult,
    evaluate_pattern_a,
)
from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_score import score_pattern_a
from trend_scanner.patterns.pattern_a_stage import classify_pattern_a_stage
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"

# 대표 integration 케이스 5종
_REPRESENTATIVE_CASES = (
    ("006360", "GS건설", "2022-11-30", PatternAStage.WEAK, PatternACandidateState.BLOCKED),
    ("017670", "SK텔레콤", "2023-12-31", PatternAStage.BASE, PatternACandidateState.WATCH),
    ("035900", "JYP Ent.", "2020-07-31", PatternAStage.TRANSITION, PatternACandidateState.CANDIDATE),
    ("000660", "SK하이닉스", "2023-11-30", PatternAStage.EARLY_TREND, PatternACandidateState.CANDIDATE),
    ("086520", "에코프로", "2023-11-30", PatternAStage.PROGRESSED, PatternACandidateState.LATE),
)


def _has_representative_caches() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    for ticker, _, _, _, _ in _REPRESENTATIVE_CASES:
        daily = cache.load(ticker)
        if daily is None or daily.empty:
            return False
    return True


_HAS_CACHE = _has_representative_caches()
_SKIP_REASON = "대표 케이스 종목의 KRX 캐시(data/raw/stocks)가 없어 skip합니다."


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_evaluator_score_and_stage_match_direct_calls_exactly():
    cache = ParquetCache(base_dir=_CACHE_DIR)

    for ticker, name, date, _, _ in _REPRESENTATIVE_CASES:
        daily = cache.load(ticker)
        assert daily is not None and not daily.empty

        snapshot = build_historical_snapshot(
            ticker=ticker,
            name=name,
            daily=daily,
            snapshot_date=date,
            include_incomplete_periods=False,
        )

        # Direct calls
        direct_score_result = score_pattern_a(snapshot.features)
        direct_stage_result = classify_pattern_a_stage(snapshot)

        # Evaluator call
        eval_result = evaluate_pattern_a(snapshot)

        # 1. 객체 동일성 검증 (Source of truth 보존)
        assert eval_result.score_result == direct_score_result
        assert eval_result.stage_result == direct_stage_result

        # 2. 편의 프로퍼티 일치 검증
        assert eval_result.score == direct_score_result.pattern_a_score
        assert eval_result.stage == direct_stage_result.stage
        assert eval_result.stage_evidence == direct_stage_result.evidence
        assert eval_result.stage_context == direct_stage_result.context
        assert eval_result.stage_reason_codes == direct_stage_result.reason_codes

        # 3. 기본 메타데이터 일치 검증
        assert eval_result.ticker == ticker
        assert eval_result.name == name
        assert eval_result.as_of == snapshot.effective_as_of


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_evaluator_deterministic_execution():
    cache = ParquetCache(base_dir=_CACHE_DIR)
    ticker, name, date, _, _ = _REPRESENTATIVE_CASES[0]
    daily = cache.load(ticker)
    assert daily is not None and not daily.empty

    snapshot = build_historical_snapshot(
        ticker=ticker, name=name, daily=daily, snapshot_date=date, include_incomplete_periods=False
    )

    res1 = evaluate_pattern_a(snapshot)
    res2 = evaluate_pattern_a(snapshot)

    assert res1 == res2
    assert res1.score == res2.score
    assert res1.stage == res2.stage
    assert res1.candidate_state == res2.candidate_state


@pytest.mark.skipif(not _HAS_CACHE, reason=_SKIP_REASON)
def test_representative_cases_candidate_states():
    cache = ParquetCache(base_dir=_CACHE_DIR)

    for ticker, name, date, expected_stage, expected_state in _REPRESENTATIVE_CASES:
        daily = cache.load(ticker)
        assert daily is not None and not daily.empty

        snapshot = build_historical_snapshot(
            ticker=ticker, name=name, daily=daily, snapshot_date=date, include_incomplete_periods=False
        )

        res = evaluate_pattern_a(snapshot)
        assert res.stage == expected_stage
        assert res.candidate_state == expected_state
        assert f"state_{expected_state.value}" in res.evaluator_reason_codes


def test_candidate_state_mapping_logic():
    from trend_scanner.patterns.pattern_a_evaluator import _derive_candidate_state

    # WEAK -> BLOCKED
    assert _derive_candidate_state(PatternAStage.WEAK, 50.0) == PatternACandidateState.BLOCKED

    # BASE -> WATCH
    assert _derive_candidate_state(PatternAStage.BASE, 50.0) == PatternACandidateState.WATCH

    # TRANSITION -> CANDIDATE
    assert _derive_candidate_state(PatternAStage.TRANSITION, 50.0) == PatternACandidateState.CANDIDATE

    # EARLY_TREND -> CANDIDATE (Transition/Early 동등 candidate band)
    assert _derive_candidate_state(PatternAStage.EARLY_TREND, 50.0) == PatternACandidateState.CANDIDATE

    # PROGRESSED -> LATE
    assert _derive_candidate_state(PatternAStage.PROGRESSED, 50.0) == PatternACandidateState.LATE

    # None / Missing -> INSUFFICIENT_DATA
    assert _derive_candidate_state(None, 50.0) == PatternACandidateState.INSUFFICIENT_DATA
    assert _derive_candidate_state(PatternAStage.BASE, None) == PatternACandidateState.INSUFFICIENT_DATA
    assert _derive_candidate_state(None, None) == PatternACandidateState.INSUFFICIENT_DATA


def test_diagnostic_conflicts_detection():
    from trend_scanner.patterns.pattern_a_evaluator import _detect_conflicts

    # 1. High Score on WEAK
    has_conflict, reasons = _detect_conflicts(PatternAStage.WEAK, 65.0)
    assert has_conflict is True
    assert "conflict_high_score_on_weak_stage" in reasons

    # 2. Normal WEAK (Low Score) -> No conflict
    has_conflict, reasons = _detect_conflicts(PatternAStage.WEAK, 20.0)
    assert has_conflict is False
    assert len(reasons) == 0

    # 3. High Score on PROGRESSED
    has_conflict, reasons = _detect_conflicts(PatternAStage.PROGRESSED, 75.0)
    assert has_conflict is True
    assert "conflict_high_score_on_progressed_stage" in reasons

    # 4. Low Score on EARLY_TREND
    has_conflict, reasons = _detect_conflicts(PatternAStage.EARLY_TREND, 35.0)
    assert has_conflict is True
    assert "conflict_low_score_on_early_trend_stage" in reasons

    # 5. Very High Score on BASE
    has_conflict, reasons = _detect_conflicts(PatternAStage.BASE, 80.0)
    assert has_conflict is True
    assert "conflict_high_score_on_base_stage" in reasons
