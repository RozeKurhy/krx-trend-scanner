# Pattern A Evaluator Integration v0.1 설계 및 통합 검증

## 1. 목적 및 핵심 철학

`Pattern A Evaluator v0.1`은 사전에 독립적으로 개발 및 검증·봉인된 두 핵심 모듈:
1. **Pattern A Score v0.2** (`src/trend_scanner/patterns/pattern_a_score.py`): 장기 베이스 구조와 추세 전환 매력도(Quality/Attractiveness) 산출
2. **Pattern A Stage Classifier v0.1** (`src/trend_scanner/patterns/pattern_a_stage.py`, commit `43ee01c`): 추세 생애주기상의 위치(Lifecycle Stage) 판정

을 동일한 `HistoricalSnapshot`(FeatureRow) 입력에서 독립적으로 계산하고, 하나의 일관된 `PatternAEvaluationResult` 객체로 통합하여 반환하는 **Orchestration & Candidate Interpretation Layer**이다.

### 1.1 두 신호의 엄격한 분리 원칙 (No Cross-Mutation)
* **Score ≠ Stage**: Score는 "얼마나 구조적으로 매력적인가?"를 평가하고, Stage는 "현재 생애주기 어디에 있는가?"를 판정한다.
* **상호 변조 금지**: Evaluator는 Stage 결과를 바탕으로 Score를 가감하거나, Score 결과를 바탕으로 Stage를 덮어쓰지 않는다.
* **단일 숫자 점수화 금지**: Evaluator v0.1은 `Unified Score`, `Meta Score`, `Stage Weighted Score` 같은 인위적인 단일 랭킹 숫자를 강제로 합성하지 않는다.
* **독립 보존**: 기존 Score와 Stage의 원본 객체(`score_result`, `stage_result`)를 source of truth로 온전히 보존한다.

---

## 2. API 명세 및 데이터 구조

### 2.1 Evaluator Entry Point
```python
from trend_scanner.patterns.pattern_a_evaluator import evaluate_pattern_a
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

# HistoricalSnapshot 기반 단일 평가 호출
snapshot = build_historical_snapshot(ticker, name, daily, snapshot_date, include_incomplete_periods=False)
result: PatternAEvaluationResult = evaluate_pattern_a(snapshot)
```

### 2.2 `PatternACandidateState` (해석적 후보 상태 Enum)
대세 상승 초입 탐지 목적에 맞추어 Stage와 Score를 읽기 쉽게 범주화한 categorical interpretation이다.

| Candidate State | 매핑 대상 Stage | 의미론적 해석 |
|---|---|---|
| **`CANDIDATE`** | `TRANSITION`, `EARLY_TREND` | **Pattern A 핵심 관심/초입 탐지 밴드**. (OOS 검증에서 확인된 EARLY->TRANSITION 지연 특성을 고려하여 두 단계를 동등한 핵심 후보 밴드로 취급) |
| **`WATCH`** | `BASE` | **초입 직전 관찰 대상**. 아직 상방 전환이 확정되지 않았으나 베이스를 형성 중인 잠재 후보. |
| **`LATE`** | `PROGRESSED` | **성숙 확장 국면**. 종목의 추세 자체는 강할 수 있으나 Pattern A의 '초입 탐지' 관점에서는 이미 진행된 상태. |
| **`BLOCKED`** | `WEAK` | **진입 제외 상태**. 활성 하락 또는 구조적 붕괴가 진행 중인 상태. |
| **`INSUFFICIENT_DATA`** | `None` / 결측 | 데이터 부족으로 평가 불가. |

### 2.3 `PatternAEvaluationResult` 구조
```python
@dataclass(frozen=True)
class PatternAEvaluationResult:
    ticker: str
    name: str
    as_of: pd.Timestamp | str | None
    score_result: PatternAResult             # Score v0.2 원본 결과
    stage_result: StageClassificationResult  # Stage v0.1 원본 결과
    candidate_state: PatternACandidateState  # 해석적 상태
    evaluator_reason_codes: tuple[str, ...]  # Evaluator 레벨 사유 코드
    stage_score_conflict: bool = False       # 의미론적 불일치 진단 플래그

    # 편의 프로퍼티 (Source of truth 직접 위임)
    @property
    def score(self) -> float | None: ...
    @property
    def stage(self) -> PatternAStage | None: ...
    @property
    def stage_evidence(self) -> StageEvidence: ...
    @property
    def stage_context(self) -> StageLifecycleContext: ...
    @property
    def stage_reason_codes(self) -> tuple[str, ...]: ...
```

---

## 3. Score × Stage Matrix & Diagnostic Conflict

### 3.1 Score × Stage 해석 매트릭스

| Stage \ Score Band | High Score (>= 60) | Medium Score (40 ~ 60) | Low Score (< 40) |
|---|---|---|---|
| **`WEAK`** | `BLOCKED` *(Conflict Review)* | `BLOCKED` | `BLOCKED` *(전형적 약세)* |
| **`BASE`** | `WATCH` *(High Quality Base)* | `WATCH` *(Standard Base)* | `WATCH` *(Low Priority Base)* |
| **`TRANSITION`** | `CANDIDATE` *(Prime Transition)* | `CANDIDATE` *(Standard Transition)* | `CANDIDATE` *(Weak Transition)* |
| **`EARLY_TREND`** | `CANDIDATE` *(Prime Breakout)* | `CANDIDATE` *(Standard Breakout)* | `CANDIDATE` *(Conflict Review)* |
| **`PROGRESSED`** | `LATE` *(Strong Momentum Late)* | `LATE` *(Standard Late)* | `LATE` *(Exhausted Late)* |

### 3.2 Diagnostic Conflict 감지
Score와 Stage 간의 이례적인 조합을 감지하여 수동 검토(Manual Review) 대상으로 마킹한다 (판정을 임의로 수정하지 않음).
* `conflict_high_score_on_weak_stage`: 하락 국면(WEAK)인데 점수가 높음 (>= 60)
* `conflict_high_score_on_progressed_stage`: 과열 확장(PROGRESSED)인데 점수가 매우 높음 (>= 70)
* `conflict_low_score_on_early_trend_stage`: 돌파 추세(EARLY_TREND)인데 구조 점수가 낮음 (< 40)
* `conflict_high_score_on_base_stage`: 베이스 구간(BASE)인데 점수가 이례적으로 높음 (>= 75)

---

## 4. Known Limitations 전달

Evaluator는 하위 모듈들의 알려진 한계점을 왜곡 없이 그대로 보존하여 상위 Scanner 및 분석가에게 전달한다.

### 4.1 Stage Classifier v0.1 Known Limitations (OOS Frozen)
1. **EARLY_TREND 탐지 지연 (Detection Lag)**: OOS 7건 중 4건이 `weekly_ma12_slope < 0.03` 미달 등으로 TRANSITION으로 1단계 보수적으로 분류됨.
2. **BASE 경계 민감도 (Boundary Sensitivity)**: 미세한 24개월선 기울기 양전환으로 TRANSITION 승격(2건) 또는 잔여 음수 기울기로 WEAK 인접 분류(2건) 발생.
3. **Active Decline False Negative 위험**: 24개월선 잔여 음수로 인해 초기 전환 종목이 WEAK로 과소평가될 수 있는 비용 존재 (LS 2022-10-31 사례).
4. **WEAK Non-Ordinal Semantics**: WEAK는 ordinal stage가 아닌 active decline failure state에 가까움.

### 4.2 Pattern A Score v0.2 Known Limitations
1. **Supporting Confirmation 의존성**: Core(ma24_slope)가 약한 구간에서는 주간/가속도 보너스가 엄격히 차단됨.
2. **Already Progressed Penalty Composite 구조**: 다중 확장 신호가 동시에 나타나야 감점이 적용되므로 단일 극단값에 대한 즉각 감점은 제한적임.

---

## 5. 대표 통합 케이스 검증 (Integration Verification)

| 종목명 (Ticker) | Snapshot Date | Direct Score | Direct Stage | Evaluator State | Conflict Flag |
|---|---|---|---|---|---|
| **GS건설** (`006360`) | 2022-11-30 | 17.5 | `WEAK` | `BLOCKED` | False |
| **SK텔레콤** (`017670`) | 2023-12-31 | 54.2 | `BASE` | `WATCH` | False |
| **JYP Ent.** (`035900`) | 2020-07-31 | 58.7 | `TRANSITION` | `CANDIDATE` | False |
| **SK하이닉스** (`000660`) | 2023-11-30 | 72.1 | `EARLY_TREND` | `CANDIDATE` | False |
| **에코프로** (`086520`) | 2023-11-30 | 48.3 | `PROGRESSED` | `LATE` | False |

* 모든 케이스에서 직접 호출 결과와 Evaluator 내부 결과의 100% 일치 및 Deterministic 실행이 확인되었다 (`tests/test_pattern_a_evaluator.py` 전원 통과).
