# Pattern A FAST Architecture v0.3 Fresh OOS Forward Validation 사전등록서

================================================================================
1. 연구 목적 및 연구 질문
================================================================================
- **연구명**: Pattern A FAST Architecture v0.3 Fresh OOS Forward Validation
- **연구 분류 (Research Classification)**: `FRESH_OOS_FORWARD_VALIDATION_PREREGISTRATION`
- **전략 아키텍처 기준 (Architecture Authority)**: `PATTERN_A_FAST_ARCHITECTURE_V03` ([`89df82a`](https://github.com/RozeKurhy/krx-trend-scanner/commit/89df82a938dba1961c2342064db2dc0061a5f2ca))
- **공식 Primary 정책 ID**: **`PRIMARY_V03`** (`OFFICIAL_FRESH_OOS_PRIMARY`)
- **실험적 비교 정책 ID**: **`PRIMARY_V03_WITH_COVERAGE_EXPERIMENT`** (`EXPERIMENTAL_COMPARATOR`)
- **사전등록 상태 (Fresh OOS Status)**: **`PREREGISTERED_NOT_STARTED`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **독립 시점 검증 여부 (Independent Time Validation)**: **`YES` (완전 독립 전진 검증)**
- **독립 규칙 탐색/최적화 (Rule Discovery / Tuning)**: **`NO` (Zero Rule Tuning)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[연구 목적 및 성격 명시]**:
> 본 사전등록서는 확정 동결된 `PATTERN_A_FAST_ARCHITECTURE_V03`를 과거 retrospective 표본(2026-08-14 이전)과 완전히 격리된 **새로운 미래 시간 구간(Fresh OOS)**에서 단 1개의 규칙 및 파라미터 변경 없이 검증하기 위한 공식 검증 계약서입니다. 본 사전등록 커밋 이전의 시장 데이터는 Fresh OOS 검증 증거에 일체 포함되지 않으며, 데이터 사전 확인(No-Data-Peeking) 및 사후 튜닝(No-Tuning) 원칙을 엄격히 준수합니다.

#### 핵심 검증 질문 (Primary Fresh OOS Questions)
1. **Q1 (FAST Entry Forward Value)**: FAST v0.1 진입 신호가 새로운 미래 시간 구간에서도 지속적인 상승 기회(Forward Return & MFE)를 포착하는가?
2. **Q2 (FAST + WEAK Reversal Robustness)**: Retrospective 표본에서 강세를 보였던 `FAST + WEAK` 초기 반등 유형이 새 시간 구간에서도 방향적으로 우수한 성과를 재현하는가?
3. **Q3 (Pattern A Context Value)**: `TRANSITION` 및 `EARLY_TREND` 거시적 컨텍스트가 새 구간에서 진입 품질 및 손실 방어와 유의미하게 연계되는가?
4. **Q4 (UNAVAILABLE Semantic Stability)**: `UNAVAILABLE` 상태가 약세 구조가 아닌 순수 정보 부족(Information Insufficiency) 특성을 지속 유지하는가?
5. **Q5 (EARLY → PROGRESSED Hold Benefit)**: `EARLY_TREND → PROGRESSED` 국면 전환 시 매도하지 않고 보유(`HOLD`)하는 규칙이 우측 꼬리 대형 승자(Right Tail Winner)의 추세 확장을 보존하는가?
6. **Q6 (Exit 4 Profit Protection)**: 정상 전이 경로의 15.0pt Exit 4가 Peak Giveback 및 극단 손실 tail을 효과적으로 방어하는가?
7. **Q7 (Coverage Experimental Trade-off)**: Coverage Hole 활성화가 새 구간에서도 Giveback 방어 혜택과 Right Tail Winner 절단(Truncation)의 상충 관계(Trade-off)를 동일하게 나타내는가?

================================================================================
2. Fresh OOS 시간 경계 및 윈도우 설계
================================================================================
1. **Enrollment 시작 경계 (`enrollment_start_rule`)**:
   - **`FIRST_KRX_TRADING_DAY_AFTER_PREREGISTRATION_COMMIT`**
   - 본 사전등록 커밋 시점 이후에 도래하는 **최초 KRX 정규 거래일**부터 Fresh OOS 등록을 시작한다.
   - 사전등록 커밋 타임스탬프 이전에 발생했거나 완료된 신호는 Fresh OOS 표본에 절대 포함할 수 없다.
2. **Enrollment 등록 기간 (`enrollment_window_calendar_weeks`)**:
   - **`26 Calendar Weeks`** (고정 캘린더 기간)
   - 시작일로부터 정확히 26 캘린더 주가 경과하는 시점의 마지막 포함 가능 거래일까지 신호를 등록한다.
   - **조기 종료 금지**: 시장 상황, 진입 건수(N), 수익률에 따른 등록 기간의 사후 연장/단축을 엄격히 금지한다.
3. **최대 관찰 성숙 기간 (`maximum_forward_horizon_weeks`)**:
   - **`26 Weeks`**
   - 26주 장기 성과 및 Peak Giveback 측정을 위해, 마지막 등록된 거래가 최소 26주를 경과할 때까지 공식 최종 판정을 보류한다. (전체 관찰 프레임워크 총 52주 구조)
4. **최종 평가 시점 (`final_evaluation_rule`)**:
   - 등록 윈도우 종료 후 마지막 등록 거래의 26W 성숙 시점에 도달한 이후에만 공식 최종 평가(`FINAL_EVALUATION`)를 수행한다.

================================================================================
3. 대상 모집단 및 단일 진입 원칙
================================================================================
1. **유니버스 계약 (PIT Investability)**:
   - KRX 보통주(KOSPI / KOSDAQ Common Stocks) 중 해당 시점의 Phase 10 투자 적격 기준 충족 종목:
     - 시가총액: **`>= KRW 100B`**
     - 20일 평균 거래대금: **`>= KRW 300M`**
     - 가격 필터: `NONE`
   - **생존 편향 방지**: 현재 시점의 상장 종목 목록을 소급 적용하지 않으며, 각 신호 발생 시점의 Point-In-Time 적격성을 엄격히 적용한다.
2. **단일 종목당 1회 진입 원칙 (`entry_selection`)**:
   - **`FIRST_QUALIFYING_ENTRY_PER_TICKER_WITHIN_ENROLLMENT_WINDOW`**
   - retrospective 연구와의 표본 독립성 및 비교 가능성을 보장하기 위해, 동일 종목에서 등록 기간 중 복수의 신호가 발생하더라도 **최초 적격 신호 1건만** Primary 표본으로 채택한다. (후속 신호는 Diagnostic 보조 이벤트로만 기록)

================================================================================
4. 진입, 보유 및 청산 정책 계약 (Architecture Freeze v0.3 일치)
================================================================================

### 1. Entry Policy Core (`FROZEN_CORE`)
- **Weekly FAST Machine Stage**: `TRIGGER` & Status `READY`
- **Monthly FAST Permission**: `PERMITTED_REGIME`
- **Daily Risk State**: `NORMAL` 또는 `ELEVATED` (`EXTREME`은 진입 차단)
- **FAST Score Status**: `READY` 또는 `PARTIAL` (Numeric threshold 없음)
- **Pattern A Hard Gate**: `NONE` (모든 Pattern A Stage 진입 허용, Context로만 관찰)
- **Execution Timing**: 신호 발생 주간 익영업일 시가 (**NEXT LOCAL TRADING DAY OPEN**)

### 2. Hold Policy & Pre-PROGRESSED Semantics (`FROZEN_CORE`)
- **Pre-PROGRESSED Hold**: 진입 후 `PROGRESSED`에 도달하기 전까지 **무조건 보유(`HOLD`)**한다.
- **Time Stop / Price Stop / FAST Reversal Exit**: 전부 **`NONE`**
- **Pre-PROGRESSED Stage Exit**: **`NONE`** (`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`, `UNAVAILABLE` 간 전이로 인한 청산 없음)
- **NEVER_PROGRESSED Terminal Status**: 평가 시점까지 `PROGRESSED` 미도달 거래는 **`OPEN_AT_CUTOFF`** 유지 (`forced_close: false`, `valuation: MARK_TO_CUTOFF`).
- **PROGRESSED Lifecycle Hold**: `EARLY_TREND → PROGRESSED` 전이는 정상 추세 확장이므로 매도하지 않고 지속 보유.

### 3. Exit Architecture: Primary vs Experimental Comparator
Fresh OOS에서는 공식 Primary 정책과 실험적 비교군을 명확히 분리하여 병렬 추적한다:

#### 1) OFFICIAL PRIMARY POLICY: `PRIMARY_V03` (공식 기준 정책)
- **활성화 조건 (`activation_condition`)**: `POST_ENTRY_DIRECT_EARLY_TREND_TO_PROGRESSED`
- **활성화 범위 (`activation_scope`)**: `NORMAL_EARLY_TREND_HANDOFF_ONLY`
- **Exit 4 (Profit Protection)**:
  - `PROGRESSED` 진입 월 스냅샷 점수로 `PROGRESSED_HWM` 초기화 (`ARM_SNAPSHOT_PATTERN_A_SCORE`).
  - PROGRESSED 국면 유지 중 `HWM = max(previous HWM, current score)` 갱신.
  - `PROGRESSED_HWM - Current Score >= 15.0pt` (frozen) 시 신호 발생, 익월 첫 로컬 거래일 시가 청산.
- **Exit 3 (Structural Backstop)**:
  - 직접 handoff 활성화 필수 (`exit3_requires_primary_activation: true`).
  - `PROGRESSED`에서 다른 유효 구조적 Stage(`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`)로 이탈 시 익월 첫 로컬 거래일 시가 청산.
  - Coverage Hole 확장 없음 (`exit3_coverage_expansion: NONE`).
- **Terminal Precedence**: `EARLIEST_EXECUTABLE_SIGNAL` (가장 빠른 신호 우선 체결).
- **Primary Coverage Hole Policy**: `coverage_activation: false`, `exit4_armed: false`, `exit3_expansion: NONE`, `terminal_status: OPEN_AT_CUTOFF`.

#### 2) EXPERIMENTAL COMPARATOR: `PRIMARY_V03_WITH_COVERAGE_EXPERIMENT` (실험적 비교군)
- **역할**: `EXPERIMENTAL_COMPARATOR` (`PROMISING_EXPERIMENTAL`)
- **기본 정책**: `PRIMARY_V03`와 Entry, Hold, Normal Exit semantics 100% 동일.
- **Coverage 활성화 조건**: `FIRST_OBSERVED_PROGRESSED_SNAPSHOT`
- **Coverage 활성화 범위**: `SKIPPED_EARLY_TREND_HANDOFF`, `PROGRESSED_WITHOUT_DIRECT_HANDOFF`
- **Coverage Exit 4 Trigger**: `PROGRESSED_HWM - Current Score >= 15.0pt` (frozen)
- **Coverage Exit 3 확장**: `NONE` (Exit 3는 확장하지 않음, PROGRESSED 이탈 시 `OPEN_AT_CUTOFF` 유지)
- **불변 원칙**: Fresh OOS 실행 후 결과에 따라 Primary 정책을 사후 교체하는 행위를 일체 금지하며, 공식 평가 권위는 항상 `PRIMARY_V03`에 귀속됨.

================================================================================
5. 관찰 코호트 (Observation Cohorts)
================================================================================
Fresh OOS 결과는 정책 변경이 아닌 순수 방향성 검증 목적으로 아래 4개 독립 차원으로 분리 집계한다:

1. **Pattern A Entry Stage**: `WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`, `PROGRESSED` (`ENTRY_STAGE_PROGRESSED`), `UNAVAILABLE`
2. **Daily Risk State**: `NORMAL`, `ELEVATED`
3. **Market**: `KOSPI`, `KOSDAQ`
4. **Post-entry Lifecycle Class**: `NORMAL_EARLY_TREND_HANDOFF`, `SKIPPED_EARLY_TREND_HANDOFF`, `PROGRESSED_WITHOUT_DIRECT_HANDOFF`, `NEVER_PROGRESSED`

> **[Cohort 해석 불변 원칙]**:
> 특정 코호트의 성과가 우수하거나 부진하더라도, 본 Fresh OOS 연구 진행 중에 새로운 진입 차단 필터나 승격 규칙을 신설하는 것을 엄격히 금지한다.

================================================================================
6. 필수 평가 지표군 및 검열 규칙 (Metrics & Censoring)
================================================================================

#### 1. Forward Return Horizons
- **4W, 8W, 12W, 26W Return & Terminal Return**:
  - 각 지표별 N, Mean, Median, P25, P75, Std, Min, Max, Positive Rate(%) 산출.
  - **검열 규칙 (`censoring_rules`)**: 평가 시점에 해당 기간에 도달하지 않은 미성숙 거래는 **`CENSORED_NOT_MATURED`**로 제외 집계하며, 절대 0% 수익률로 처리하지 않는다.

#### 2. Path Metrics
- **MFE (Maximum Favorable Excursion)**: N, Mean, Median, P25, P75
- **MAE (Maximum Adverse Excursion)**: N, Mean, Median, P25, P75
- **Peak Giveback**: Distribution Median & Paired Delta
- **Profit Capture Ratio**: Distribution Median & Paired Delta
- **Holding Weeks**: Mean, Median, Distribution

#### 3. Exit Type Distribution
- `PRIMARY_V03`: Exit 3 Count, Exit 4 Count, Open at Cutoff Count, NEVER_PROGRESSED Count
- `PRIMARY_V03_WITH_COVERAGE_EXPERIMENT`: Coverage Armed, Triggered, Executed Count

#### 4. Tail & Paired Metrics
- **Right Tail**: Return ≥ +20%, ≥ +50%, ≥ +100% 도달 건수 및 비율, Primary 대형 승자 조기 청산 손실률(Truncation Rate)
- **Failure Tail**: Return < 0, Return ≤ -20%, Return ≤ -30% 손실 발생률
- **Paired Deltas (Experimental - Primary)**: Return Delta, Giveback Delta, Profit Capture Delta, Holding Weeks Delta (Mean, Median, P25, P75, Better/Equal/Worse 분포)

================================================================================
7. 중간 점검 및 최종 판정 체계 (Interim & Final Interpretation)
================================================================================

#### 1. 중간 보고 규칙 (`interim_rules`)
- Enrollment 진행 중 4W, 8W, 12W 조기 성숙 결과는 **`FRESH_OOS_IN_PROGRESS`** 상태의 방향성 모니터링 목적으로만 보고할 수 있다.
- 중간 결과를 근거로 한 Production 승격, 전략 수정, 또는 최종 판정을 일체 금지한다.

#### 2. 최종 판정 상태 후보 (`final_interpretation_states`)
26W 완전 성숙 후 아래 4개 기준 중 하나로 최종 종합 판정한다:
- **`FRESH_OOS_DIRECTIONALLY_SUPPORTED`**: 핵심 retrospective findings(진입 기회 포착, Giveback 방어, 생애주기 보유 효과)가 새 시간 표본에서도 전반적으로 같은 방향으로 재현되고 중대한 반대 증거가 없는 경우.
- **`FRESH_OOS_MIXED`**: 일부 핵심 finding은 재현되나 다른 핵심 finding 또는 subgroup/tail 증거와 상충하는 경우.
- **`FRESH_OOS_NOT_REPLICATED`**: 핵심 retrospective findings가 재현되지 않거나 명백한 반대 방향 증거가 두드러지는 경우.
- **`INSUFFICIENT_FRESH_OOS_SAMPLE`**: 표본수(N) 또는 성숙도 부족으로 방향성 판단이 불가능한 경우. (표본 부족 시 사후 기간 연장 금지)

================================================================================
8. 데이터 무결성 및 No-Peeking / No-Tuning 원칙
================================================================================
1. **데이터 사전 확인 금지 (No Data Peeking)**:
   - 본 사전등록 커밋 전 Fresh OOS 구간의 후보 종목 수 조회, 신호 검색, 예상 수익률 계산을 일체 수행하지 않는다.
2. **사후 튜닝 일체 금지 (No Post-hoc Tuning)**:
   - 15.0pt 드로우다운 임계값, FAST 머신 룰, PIT 익일 시가 체결 룰을 100% 불변 적용한다.
3. **수치 목표 최적화 금지**:
   - 승률 ≥ X%, 수익률 ≥ Y% 등의 사후 허들 수치를 임의 생성하지 않는다.
4. **운영 정책 불변**:
   - Fresh OOS 결과가 SUPPORTED이더라도 즉시 Production에 적용하지 않으며, **`PRODUCTION_HOLD`**를 유지한다.
