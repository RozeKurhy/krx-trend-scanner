"""Pattern A Evaluator Integration v0.1.

Frozen Pattern A Score v0.2(`pattern_a_score.py`)와
Frozen Stage Classifier v0.1(`pattern_a_stage.py`)을 단일 HistoricalSnapshot 입력에서
독립적으로 계산하고 하나의 `PatternAEvaluationResult` 객체로 통합하여 반환하는
Orchestration & Candidate Interpretation Layer.

[핵심 설계 원칙]
1. **Score와 Stage의 독립성 보장 (No Cross-Mutation)**:
   - Evaluator는 Stage 결과에 따라 Score를 가감하거나, Score에 따라 Stage를 덮어쓰지 않는다.
   - 단일 통합 숫자 점수(Unified/Meta/Weighted Score)를 강제로 합성하지 않는다.
   - Score = "구조 품질 및 매력도 (Attractiveness)" (Raw Score 0~100 그대로 노출)
   - Stage = "생애주기상 위치 (Lifecycle Location)"
2. **공식 Lifecycle Stage Authority**:
   - 공식 Pattern A lifecycle stage는 반드시 `stage_result.stage` (`classify_pattern_a_stage()`)이다.
   - `score_result.stage`는 Score v0.2 내부의 legacy heuristic field이며, Evaluator나 Scanner의 lifecycle 판정에 절대 사용하지 않는다.
   - `evaluation.stage` 및 `evaluation.lifecycle_stage`는 모두 `stage_result.stage`를 반환한다.
3. **단일 평가 컨텍스트 (HistoricalSnapshot 기반 Data Flow)**:
   - Evaluator는 하나의 공유 `HistoricalSnapshot`을 컨텍스트로 사용한다.
   - Score v0.2는 `snapshot.features`를 소비한다.
   - Stage Classifier v0.1은 과거 이력 및 사이클 컨텍스트를 보존하기 위해 전체 `HistoricalSnapshot`을 소비한다.
4. **Candidate Interpretation (Stage 기반 Categorical State)**:
   - 대세 상승 초입 탐지 목적에 따라 TRANSITION과 EARLY_TREND를 동등한 핵심 `CANDIDATE` 밴드로 다루고,
     BASE는 `WATCH`, PROGRESSED는 `LATE`, WEAK는 `BLOCKED`로 범주화한다.
   - Candidate State는 Score 임계값에 의존하지 않는 순수 Stage 기반 해석 레이어이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

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

    Raw Score나 Stage를 변경하지 않는 순수 Stage 기반 파생 categorical interpretation이다.
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
    종목 자체는 우량하거나 강할 수 있으나 Pattern A의 '초입 탐지' 관점에서는 이미 진행된 상태.
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
        """공식 Pattern A Stage Classifier v0.1 판정 단계."""
        return self.stage_result.stage

    @property
    def lifecycle_stage(self) -> PatternAStage | None:
        """공식 Pattern A lifecycle stage alias (stage와 동일, score_result.stage 사용 방지용 명시적 프로퍼티)."""
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


def _derive_candidate_state(stage: PatternAStage | None) -> PatternACandidateState:
    """Stage 판정 결과로부터 순수하게 Candidate State를 파생한다 (Score에 의존하지 않음)."""
    if stage is None:
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


def evaluate_pattern_a(snapshot: HistoricalSnapshot) -> PatternAEvaluationResult:
    """HistoricalSnapshot을 받아 Pattern A Score v0.2와 Stage Classifier v0.1을 통합 평가한다.

    Evaluator uses one shared HistoricalSnapshot as the evaluation context.
    - Pattern A Score v0.2 consumes snapshot.features.
    - Pattern A Stage Classifier v0.1 consumes the full HistoricalSnapshot.

    Args:
        snapshot: HistoricalSnapshot 객체 (lookahead가 배제된 daily/monthly/weekly 데이터 및 FeatureRow 포함)

    Returns:
        PatternAEvaluationResult: 통합 평가 결과 객체
    """
    ticker = snapshot.features.ticker if snapshot.features else ""
    name = snapshot.features.name if snapshot.features else ""
    as_of = snapshot.effective_as_of

    # 1. Frozen Score v0.2 계산 (snapshot.features 소비)
    score_result = score_pattern_a(snapshot.features)

    # 2. Frozen Stage Classifier v0.1 계산 (full snapshot 소비)
    stage_result = classify_pattern_a_stage(snapshot)

    # 3. Candidate State 파생 (Score가 결측이면 INSUFFICIENT_DATA)
    if score_result.pattern_a_score is None:
        candidate_state = PatternACandidateState.INSUFFICIENT_DATA
    else:
        candidate_state = _derive_candidate_state(stage_result.stage)

    # 4. Evaluator Reasons 수집
    evaluator_reasons: list[str] = [f"state_{candidate_state.value}"]
    if stage_result.stage is not None:
        evaluator_reasons.append(f"stage_{stage_result.stage.value}")

    return PatternAEvaluationResult(
        ticker=ticker,
        name=name,
        as_of=as_of,
        score_result=score_result,
        stage_result=stage_result,
        candidate_state=candidate_state,
        evaluator_reason_codes=tuple(evaluator_reasons),
        stage_score_conflict=False,
    )
