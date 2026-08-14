# Pattern A Evaluator Integration v0.1 설계 및 통합 검증

## 1. 목적 및 핵심 철학

`Pattern A Evaluator v0.1`은 사전에 독립적으로 개발 및 검증·봉인된 두 핵심 모듈:
1. **Pattern A Score v0.2** (`src/trend_scanner/patterns/pattern_a_score.py`): 장기 베이스 구조와 추세 전환 매력도(Quality / Attractiveness, Raw Score 0~100) 산출
2. **Pattern A Stage Classifier v0.1** (`src/trend_scanner/patterns/pattern_a_stage.py`, commit `43ee01c`): 추세 생애주기상의 위치(Lifecycle Stage) 판정

을 단일 `HistoricalSnapshot` 컨텍스트에서 독립적으로 계산하고, 하나의 일관된 `PatternAEvaluationResult` 객체로 통합하여 반환하는 **Orchestration & Candidate Interpretation Layer**이다.

### 1.1 두 신호의 엄격한 분리 원칙 (No Cross-Mutation)
* **Score ≠ Stage**: Score는 "얼마나 구조적으로 매력적인가?"를 평가하고, Stage는 "현재 생애주기 어디에 있는가?"를 판정한다.
* **상호 변조 금지**: Evaluator는 Stage 결과를 바탕으로 Score를 가감하거나, Score 결과를 바탕으로 Stage를 덮어쓰지 않는다.
* **단일 숫자 점수화 금지**: Evaluator v0.1은 `Unified Score`, `Meta Score`, `Stage Weighted Score` 같은 인위적인 단일 랭킹 숫자를 강제로 합성하지 않는다.
* **독립 보존**: 기존 Score와 Stage의 원본 객체(`score_result`, `stage_result`)를 source of truth로 온전히 보존한다.

---

## 2. Data Flow 및 공식 Lifecycle Stage Authority

### 2.1 단일 평가 컨텍스트 (HistoricalSnapshot Data Flow)
Evaluator는 하나의 공유 `HistoricalSnapshot`을 공통 평가 컨텍스트로 사용한다.
* **Pattern A Score v0.2**: `snapshot.features` (`FeatureRow`)를 소비한다.
* **Pattern A Stage Classifier v0.1**: 장기 이력과 과거 확장/사이클 리셋 컨텍스트를 보존하기 위해 전체 `HistoricalSnapshot`을 소비한다.

### 2.2 공식 Lifecycle Stage Authority (중요)
> [!IMPORTANT]
> **공식 Lifecycle Stage**:
> * `PatternAEvaluationResult.stage` 및 `PatternAEvaluationResult.lifecycle_stage`는 **공식 Pattern A Stage Classifier v0.1 (commit `43ee01c`)의 결과(`stage_result.stage`)**를 가리키며, 이것이 유일한 공식 lifecycle stage authority이다.
> * `score_result.stage`는 Score v0.2 모듈 내부의 legacy heuristic 필드로 하위 호환성을 위해 남아 있는 것이며, **Evaluator, Scanner, 필터링 또는 랭킹 로직에서 공식 lifecycle stage로 절대 사용해서는 안 된다.**

---

## 3. Candidate State 해석 레이어

Evaluator v0.1은 final Pattern A Score에 대한 임의의 cutoff(예: High/Medium/Low 등)를 강제하지 않고, raw Score(0~100)를 그대로 노출한다. 대신 대세 상승 초입 탐지 관점에서 Stage 기반의 단순 명확한 categorical interpretation(`candidate_state`)을 제공한다.

### 3.1 Stage ➔ Candidate State 매핑

| Stage (`lifecycle_stage`) | Candidate State (`candidate_state`) | 해석 (Interpretation) |
|---|---|---|
| **`WEAK`** | **`BLOCKED`** | **진입 제외 상태**. 장기 활성 하락 또는 구조 붕괴 국면. |
| **`BASE`** | **`WATCH`** | **초입 직전 관찰 대상**. 아직 상방 전환이 확정되지 않았으나 바닥을 다지는 중인 잠재 후보. |
| **`TRANSITION`** | **`CANDIDATE`** | **Pattern A 핵심 관심/초입 탐지 밴드**. |
| **`EARLY_TREND`** | **`CANDIDATE`** | **Pattern A 핵심 관심/초입 탐지 밴드**. (OOS 검증에서 확인된 EARLY->TRANSITION 지연 특성을 반영하여 두 단계를 동등한 초입 후보 밴드로 취급) |
| **`PROGRESSED`** | **`LATE`** | **성숙 확장 국면**. 종목의 추세 자체는 강할 수 있으나 Pattern A의 '초입 탐지' 관점에서는 이미 진행된 상태. |
| **`None` / 결측** | **`INSUFFICIENT_DATA`** | 데이터 부족 등으로 평가 불가. |

* **Score 독립성**: `candidate_state`는 Score 수치에 의존하지 않고 오직 Stage 판정에 의해서만 결정된다.
* **No Validated Conflict Thresholds**: Evaluator v0.1에서는 사전 검증되지 않은 임의의 Score-Stage cross conflict threshold를 도입하지 않는다 (`stage_score_conflict = False` 고정).

---

## 4. API 명세 및 데이터 구조

### 4.1 Evaluator Entry Point
```python
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

snapshot = build_historical_snapshot(ticker, name, daily, snapshot_date, include_incomplete_periods=False)
result: PatternAEvaluationResult = evaluate_pattern_a(snapshot)
```

### 4.2 `PatternAEvaluationResult` 구조
```python
@dataclass(frozen=True)
class PatternAEvaluationResult:
    ticker: str
    name: str
    as_of: pd.Timestamp | str | None
    score_result: PatternAResult             # Score v0.2 원본 결과 (Source of Truth)
    stage_result: StageClassificationResult  # Stage v0.1 원본 결과 (Source of Truth)
    candidate_state: PatternACandidateState  # Stage 기반 해석적 상태
    evaluator_reason_codes: tuple[str, ...]  # Evaluator 레벨 사유 코드
    stage_score_conflict: bool = False       # 호환용 플래그 (v0.1은 False 고정)

    # 편의 프로퍼티 (Source of truth 직접 위임)
    @property
    def score(self) -> float | None: ...
    @property
    def stage(self) -> PatternAStage | None: ...
    @property
    def lifecycle_stage(self) -> PatternAStage | None: ...
    @property
    def stage_evidence(self) -> StageEvidence: ...
    @property
    def stage_context(self) -> StageLifecycleContext: ...
    @property
    def stage_reason_codes(self) -> tuple[str, ...]: ...
```

---

## 5. Known Limitations 전달

Evaluator는 하위 모듈들의 알려진 한계점을 왜곡 없이 그대로 보존하여 상위 Scanner 및 분석가에게 전달한다.

### 5.1 Stage Classifier v0.1 Known Limitations (OOS Frozen)
1. **EARLY_TREND 탐지 지연 (Detection Lag)**: OOS 7건 중 4건이 `weekly_ma12_slope < 0.03` 미달 등으로 TRANSITION으로 1단계 보수적으로 분류됨.
2. **BASE 경계 민감도 (Boundary Sensitivity)**: 미세한 24개월선 기울기 양전환으로 TRANSITION 승격(2건) 또는 잔여 음수 기울기로 WEAK 인접 분류(2건) 발생.
3. **Active Decline False Negative 위험**: 24개월선 잔여 음수로 인해 초기 전환 종목이 WEAK로 과소평가될 수 있는 비용 존재 (LS 2022-10-31 사례).
4. **WEAK Non-Ordinal Semantics**: WEAK는 ordinal stage가 아닌 active decline failure state에 가까움.

### 5.2 Pattern A Score v0.2 Known Limitations
1. **Supporting Confirmation 의존성**: Core(ma24_slope)가 약한 구간에서는 주간/가속도 보너스가 엄격히 차단됨.
2. **Already Progressed Penalty Composite 구조**: 다중 확장 신호가 동시에 나타나야 감점이 적용되므로 단일 극단값에 대한 즉각 감점은 제한적임.

---

## 6. 대표 통합 케이스 검증 (Integration Verification)

| 종목명 (Ticker) | Snapshot Date | Raw Score | Official Stage (`lifecycle_stage`) | Candidate State |
|---|---|---|---|---|
| **GS건설** (`006360`) | 2022-11-30 | 17.5 | `WEAK` | `BLOCKED` |
| **SK텔레콤** (`017670`) | 2023-12-31 | 54.2 | `BASE` | `WATCH` |
| **JYP Ent.** (`035900`) | 2020-07-31 | 58.7 | `TRANSITION` | `CANDIDATE` |
| **SK하이닉스** (`000660`) | 2023-11-30 | 72.1 | `EARLY_TREND` | `CANDIDATE` |
| **에코프로** (`086520`) | 2023-11-30 | 48.3 | `PROGRESSED` | `LATE` |

* 모든 케이스에서 직접 호출 결과와 Evaluator 내부 결과의 100% 일치 및 Deterministic 실행이 확인되었다 (`tests/test_pattern_a_evaluator.py` 전원 통과).
