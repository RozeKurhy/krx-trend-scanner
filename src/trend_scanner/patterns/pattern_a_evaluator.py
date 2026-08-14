"""Pattern A Evaluator Integration v0.1.

Frozen Pattern A Score v0.2(`pattern_a_score.py`)와
Frozen Stage Classifier v0.1(`pattern_a_stage.py`)을 동일한 입력(HistoricalSnapshot)에서
독립적으로 계산하고 하나의 `PatternAEvaluationResult` 객체로 통합하여 반환하는
Orchestration & Candidate Interpretation Layer.

[핵심 설계 원칙]
1. **Score와 Stage의 독립성 보장 (No Cross-Mutation)**:
   - Evaluator는 Stage 결과에 따라 Score를 가감하거나, Score에 따라 Stage를 덮어쓰지 않는다.
   - 단일 통합 숫자 점수(Unified/Meta/Weighted Score)를 강제로 합성하지 않는다.
   - Score = "구조 품질 및 매력도 (Attractiveness)"
   - Stage = "생애주기상 위치 (Lifecycle Location)"
2. **단일 계산 경로 (HistoricalSnapshot 호환)**:
   - 동일한 snapshot.features(FeatureRow)에서 Score와 Stage를 각각 도출하여
     중복 연산이나 리샘플링 왜곡을 방지한다.
3. **Candidate Interpretation (Categorical State)**:
   - 대세 상승 초입 탐지 목적에 따라 TRANSITION과 EARLY_TREND를 핵심 `CANDIDATE` 밴드로 다루고,
     BASE는 `WATCH`, PROGRESSED는 `LATE`, WEAK는 `BLOCKED`로 범주화한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd

from trend_scanner.patterns.pattern_a_feature_set import PatternAStage
from trend_scanner.patterns.pattern_a_score import PatternAResult, score_pattern_a
from trend_scanner.patterns.pattern_a_stage import (
    StageClassificationResult,
    StageEvidence,
    StageLifecycleContext,
    classify_pattern_a_stage,
)
from trend_scanner.validation.historical_snapshot import HistoricalSnapshot


class PatternACandidateState(str, Enum):
    """Pattern A 대세 상승 초입 탐지 관점에서의 해석적 후보 상태.

    Raw Score나 Stage를 변경하지 않는 순수 파생 categorical interpretation이다.
    """

    CANDIDATE = "candidate"
    """핵심 관심 밴드 (TRANSITION, EARLY_TREND).
    OOS 검증에서 관찰된 EARLY->TRANSITION 지연 특성을 반영하여 두 단계를 동등한 초입 후보 밴드로 취급한다.
    """

    WATCH = "watch"
    """초입 직전 관찰 대상 (BASE).
    아직 상방 전환이 확정되지 않았으나 베이스를 형성 중인 잠재 후보.
    """

    LATE = "late"
    """이미 많이 진행된 성숙 확장 상태 (PROGRESSED).
    종목 자체는 우량하거나 강할 수 있으나 Pattern A의 '초입 탐지' 관점에서는 늦은 국면.
    """

    BLOCKED = "blocked"
    """진입 제외 상태 (WEAK).
    장기 활성 하락 또는 구조 붕괴가 진행 중인 상태.
    """

    INSUFFICIENT_DATA = "insufficient_data"
    """데이터 부족 등으로 평가가 불가능한 상태."""


@dataclass(frozen=True)
class PatternAEvaluationResult:
    """Pattern A Evaluator 통합 평가 결과 객체."""

    ticker: str
    name: str
    as_of: pd.Timestamp | str | None
    score_result: PatternAResult
    stage_result: StageClassificationResult
    candidate_state: PatternACandidateState
    evaluator_reason_codes: tuple[str, ...] = ()
    stage_score_conflict: bool = False

    @property
    def score(self) -> float | None:
        """Pattern A Score v0.2 원본 점수 (0~100)."""
        return self.score_result.pattern_a_score

    @property
    def stage(self) -> PatternAStage | None:
        """Pattern A Stage Classifier v0.1 원본 단계."""
        return self.stage_result.stage

    @property
    def stage_evidence(self) -> StageEvidence:
        """Stage 판정에 사용된 개별 Evidence."""
        return self.stage_result.evidence

    @property
    def stage_context(self) -> StageLifecycleContext:
        """과거 확장 및 cycle reset 관련 Stage 컨텍스트."""
        return self.stage_result.context

    @property
    def stage_reason_codes(self) -> tuple[str, ...]:
        """Stage 판정 사유 코드."""
        return self.stage_result.reason_codes


def _derive_candidate_state(
    stage: PatternAStage | None, score: float | None
) -> PatternACandidateState:
    if stage is None or score is None:
        return PatternACandidateState.INSUFFICIENT_DATA

    if stage == PatternAStage.WEAK:
        return PatternACandidateState.BLOCKED
    if stage == PatternAStage.BASE:
        return PatternACandidateState.WATCH
    if stage in (PatternAStage.TRANSITION, PatternAStage.EARLY_TREND):
        return PatternACandidateState.CANDIDATE
    if stage == PatternAStage.PROGRESSED:
        return PatternACandidateState.LATE

    return PatternACandidateState.INSUFFICIENT_DATA


def _detect_conflicts(
    stage: PatternAStage | None, score: float | None
) -> tuple[bool, list[str]]:
    """Score와 Stage 사이의 의미론적 불일치(Conflict)를 진단용으로 감지한다.

    이 플래그는 점수나 단계를 수정하지 않고 수동 검토(manual review) 대상으로 식별하기 위함이다.
    """
    if stage is None or score is None:
        return False, []

    reasons: list[str] = []
    has_conflict = False

    # 1. Active decline(WEAK)인데 점수가 높은 경우 (위험 신호)
    if stage == PatternAStage.WEAK and score >= 60.0:
        has_conflict = True
        reasons.append("conflict_high_score_on_weak_stage")

    # 2. 이미 과열 확장(PROGRESSED)인데 점수가 매우 높은 경우 (초입 오판 주의)
    if stage == PatternAStage.PROGRESSED and score >= 70.0:
        has_conflict = True
        reasons.append("conflict_high_score_on_progressed_stage")

    # 3. 명확한 상승 추세(EARLY_TREND)인데 구조 점수가 매우 낮은 경우
    if stage == PatternAStage.EARLY_TREND and score < 40.0:
        has_conflict = True
        reasons.append("conflict_low_score_on_early_trend_stage")

    # 4. 베이스 구간(BASE)인데 점수가 이례적으로 높은 경우
    if stage == PatternAStage.BASE and score >= 75.0:
        has_conflict = True
        reasons.append("conflict_high_score_on_base_stage")

    return has_conflict, reasons


def evaluate_pattern_a(snapshot: HistoricalSnapshot) -> PatternAEvaluationResult:
    """HistoricalSnapshot을 받아 Pattern A Score v0.2와 Stage Classifier v0.1을 통합 평가한다.

    Args:
        snapshot: HistoricalSnapshot 객체 (lookahead가 배제된 daily/monthly/weekly 데이터 및 FeatureRow 포함)

    Returns:
        PatternAEvaluationResult: 통합 평가 결과 객체
    """
    ticker = snapshot.features.ticker if snapshot.features else ""
    name = snapshot.features.name if snapshot.features else ""
    as_of = snapshot.effective_as_of

    # 1. Frozen Score v0.2 계산
    score_result = score_pattern_a(snapshot.features)

    # 2. Frozen Stage Classifier v0.1 계산
    stage_result = classify_pattern_a_stage(snapshot)

    # 3. Candidate State 파생 (순수 categorical interpretation)
    candidate_state = _derive_candidate_state(stage_result.stage, score_result.pattern_a_score)

    # 4. Diagnostic Conflict 감지 및 Evaluator Reasons 수집
    has_conflict, conflict_reasons = _detect_conflicts(
        stage_result.stage, score_result.pattern_a_score
    )

    evaluator_reasons: list[str] = [f"state_{candidate_state.value}"]
    if stage_result.stage is not None:
        evaluator_reasons.append(f"stage_{stage_result.stage.value}")
    if has_conflict:
        evaluator_reasons.extend(conflict_reasons)

    return PatternAEvaluationResult(
        ticker=ticker,
        name=name,
        as_of=as_of,
        score_result=score_result,
        stage_result=stage_result,
        candidate_state=candidate_state,
        evaluator_reason_codes=tuple(evaluator_reasons),
        stage_score_conflict=has_conflict,
    )
