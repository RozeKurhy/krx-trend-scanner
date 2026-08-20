# Pattern A FAST Strategy Architecture Freeze v0.3

================================================================================
1. Executive Summary & Core Philosophy
================================================================================
- **전략 아키텍처명**: `PATTERN_A_FAST_ARCHITECTURE_V03`
- **아키텍처 버전**: `v0.3` (동결 유지)
- **연구 분류 (Research Classification)**: `STRATEGY_ARCHITECTURE_FREEZE`
- **전략 상태 (Research Status)**: **`ARCHITECTURE_FROZEN`**
- **공식 Primary 정책 ID**: **`PRIMARY_V03`** (`OFFICIAL_FRESH_OOS_PRIMARY`)
- **실험적 비교 정책 ID**: **`PRIMARY_V03_WITH_COVERAGE_EXPERIMENT`** (`EXPERIMENTAL_COMPARATOR`)
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Fresh OOS 상태 (Fresh OOS Status)**: **`NOT_STARTED`** (`fresh_oos_boundary_status: TO_BE_PREREGISTERED_BEFORE_EXECUTION`)
- **Production Candidate 여부**: **`NO` (독립 검증 전 운영 반영 불가)**
- **테스트 정책**: `Tests: NOT RUN`

#### 💡 핵심 다중 시계열 원칙 (Core Multi-Timeframe Philosophy)
```
Monthly grants permission.
Weekly pulls the trigger.
Daily times entry.
```

#### 💡 핵심 엔진 및 지표 분리 원칙 (Functional & Metric Separation)
- **`FAST` Engine**: **단기~중기 진입 타이밍 엔진 (Entry Timing Engine)**
  - 주봉 상태 머신(Weekly State Machine)으로 모멘텀 반등/돌파 트리거 포착.
  - 일봉 리스크 엔진(Daily Risk Engine)으로 변동성 및 단기 과열 리스크 필터링.
  - **FAST Score**: 주봉/일봉 모멘텀 및 타이밍 품질 컨텍스트 제공.
- **`Pattern A` Engine**: **장기 거시 구조 및 생애주기 컨텍스트 (Long-term Lifecycle Context)**
  - **Pattern A Score**: 장기 베이스 및 추세 전환 매력도를 수치화한 독립적인 점수이며, Pattern A lifecycle Stage 자체나 단순한 trend strength와 동일하지 않음.
  - **Pattern A Stage**: 종목의 거시적 추세 국면(`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`, `PROGRESSED`) 정의.
- **핵심 구분 정의 (Invariants)**:
  - `Pattern A Score != Pattern A Stage` (점수와 상태는 독립적인 평가 차원)
  - `Pattern A Score != FAST Score` (장기 베이스 매력도 vs 단기 타이밍 품질)
  - `Pattern A Stage != FAST Stage` (월봉 거시 생애주기 vs 주봉 진입 상태머신)
  - `Entry-time Pattern A Stage != Post-entry Lifecycle Class` (진입 시점의 Stage와 진입 후 전개 경로는 독립된 차원)

================================================================================
2. Evidence Authority Commits (연구 기준 커밋)
================================================================================
본 아키텍처는 아래의 확정된 연구 커밋 결과만을 기반으로 수립되었으며, 사후 임의 튜닝을 일체 배제한다:

1. **Pattern A Production Closure**: [`05d03e1`](https://github.com/RozeKurhy/krx-trend-scanner/commit/05d03e16501adbca889488294aaaaa0bd84005de)
2. **FAST Phase 13 Closure**: [`935f9be`](https://github.com/RozeKurhy/krx-trend-scanner/commit/935f9be7c0e790b7b4efedc04ea4149a90ad78a8)
3. **Combined FAST + Pattern A v0.1 Corrected Final**: [`3a207d2`](https://github.com/RozeKurhy/krx-trend-scanner/commit/3a207d2806df31be9cc0de52be9b2ddb47b097eb)
4. **v0.2A Entry Gate Closure**: [`0e95666`](https://github.com/RozeKurhy/krx-trend-scanner/commit/0e95666ec75a23ea62edf680382a138e5813391c) (`GATE_VALUE_MIXED`)
5. **v0.2B FAST + WEAK Early Reversal Closure**: [`99f7a98`](https://github.com/RozeKurhy/krx-trend-scanner/commit/99f7a9879390784a9a94e5f82e5bdf9cf2b8e33f) (`FAST_WEAK_EARLY_REVERSAL_MIXED`)
6. **v0.2C UNAVAILABLE Decomposition Closure**: [`91b7e4b`](https://github.com/RozeKurhy/krx-trend-scanner/commit/91b7e4beb0b52d5f718533490620b7fa01457a8b) (`FAST_UNAVAILABLE_MIXED`, `UNAVAILABLE_IS_INFORMATION_INSUFFICIENCY`)
7. **v0.2D Coverage Hole Activation Closure**: [`9c4bbad`](https://github.com/RozeKurhy/krx-trend-scanner/commit/9c4bbad0d1248abeb904deccfc8cefd4f94e4a88) (`COVERAGE_ACTIVATION_MIXED`, `COVERAGE_ACTIVATION_PROMISING`)

================================================================================
3. Strategy Component Status Matrix (컴포넌트 상태 매트릭스)
================================================================================

| 컴포넌트명 | 기반 연구 및 근거 | 상태 (Status) | 역할 (Role) | Fresh OOS 처리 방식 |
|---|---|:---:|---|---|
| **FAST Entry Timing v0.1** | Phase 13 / Combined v0.1 | **`FROZEN_CORE`** | Primary 진입 타이밍 신호 | Primary Entry Engine으로 100% 동결 적용 |
| **Pattern A Stage Hard Gate** | v0.2A (`GATE_VALUE_MIXED`) | **`NOT_ESTABLISHED`** | 거시적 컨텍스트 (차단기 아님) | 진입 차단기로 쓰지 않고 관찰 코호트로 분리 |
| **FAST + WEAK Variant** | v0.2B (`MIXED`) | **`PROMISING`** | 초기 반등형 타이밍 컨텍스트 | 진입 정책 승격 없이 OOS 관찰 코호트로 유지 |
| **FAST + UNAVAILABLE Variant** | v0.2C (`MIXED` / `INSUFFICIENCY`) | **`INFORMATIONAL`** | 정보 부족 (약세 구조 아님) | 진입 허용/차단 없이 OOS 관찰 코호트로 유지 |
| **Pre-PROGRESSED Hold** | Architecture v0.3 Freeze | **`FROZEN_CORE`** | PROGRESSED 도달 전 지속 보유 | Time/Price/Stage Stop 없음, 지속 보유 |
| **EARLY_TREND → PROGRESSED Hold** | Combined v0.1 | **`FROZEN_CORE`** | 정상 추세 전개 및 보유 지속 | PROGRESSED 진입 시 매도 금지, 지속 보유 |
| **Exit 1 (EARLY → ANY STAGE)** | Combined v0.1 (`REJECTED`) | **`REJECTED`** | 과도한 조기 청산 | **완전 폐기 (Fresh OOS 평가 제외)** |
| **Exit 2 (Score Deterioration)** | Combined v0.1 (`REJECTED`) | **`INFORMATIONAL`** | 진단용 리스크 플래그 | **청산 규칙에서 제외 (진단 지표로만 유지)** |
| **Exit 3 (PROGRESSED → OTHER)** | Combined v0.1 | **`FROZEN_CORE_BACKSTOP`** | 구조적 이탈 최종 방어선 | 완만한 구조적 이탈 시 최종 청산 |
| **Exit 4 (PROGRESSED HWM - 15pt)** | Combined v0.1 / v0.2D | **`PROMISING`** | 수익 반납 방어 및 조기 경보 | PROGRESSED 국면 내 15.0pt 하락 시 청산 |
| **Coverage Hole Activation** | v0.2D (`PROMISING` / `MIXED`) | **`PROMISING_EXPERIMENTAL`** | 간접 PROGRESSED 보호 확장 | OOS에서 별도 실험군(Experimental)으로 추적 |

================================================================================
4. Detailed Strategy Architecture Specification
================================================================================

### 1. Entry Architecture (진입 아키텍처)
1. **FROZEN CORE Entry Rules**:
   - **Weekly FAST Machine Stage**: `TRIGGER` & Status `READY`
   - **Monthly FAST Permission**: `PERMITTED_REGIME`
   - **Daily Risk State**: `NORMAL` 또는 `ELEVATED` (`EXTREME`은 진입 차단)
   - **FAST Score Status**: `READY` 또는 `PARTIAL` (Numeric 점수 컷오프는 적용하지 않음)
   - **Execution**: 신호 발생 주간 익영업일 시가 (**NEXT LOCAL TRADING DAY OPEN**)
2. **Pattern A Macro Context (Not Hard Gate)**:
   - Pattern A Stage는 hard filtering gate가 아닌 **Context Dimension**으로 취급한다.
   - Fresh OOS에서 아래 코호트별 성과를 독립적으로 기록 및 추적한다:
     - `FAST + TRANSITION`
     - `FAST + EARLY_TREND`
     - `FAST + WEAK`
     - `FAST + UNAVAILABLE`
     - `FAST + BASE`
     - `FAST + PROGRESSED` (`ENTRY_STAGE_PROGRESSED` 코호트로 별도 기록)

### 2. Hold Architecture & Pre-PROGRESSED Policy (보유 아키텍처)
1. **Pre-PROGRESSED Hold Policy (`FROZEN_CORE`)**:
   - 진입 후 아직 `PROGRESSED` 국면이 관측되지 않은 구간에서는 **무조건 보유(`HOLD`)**한다.
   - **Time Stop**: `NONE` (임의적 보유 기간 만료 매도 없음)
   - **Price Stop**: `NONE` (단기 손실률/가격 기반 매도 없음)
   - **FAST Reversal Exit**: `NONE` (주봉 머신 상태 역전 매도 없음)
   - **Stage Transition Exit Before PROGRESSED**: `NONE` (`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`, `UNAVAILABLE` 상호 간의 전이로 인한 청산 없음)
2. **NEVER_PROGRESSED Terminal Valuation (`FROZEN_CORE`)**:
   - 평가 종료일(Cutoff)까지 `PROGRESSED`가 한 번도 관측되지 않은 거래는 **`OPEN_AT_CUTOFF`**로 분류한다.
   - 강제 청산(Forced Close)을 적용하지 않으며, 평가 목적의 `MARK_TO_CUTOFF` 수익률만 산출한다.
3. **PROGRESSED Lifecycle Progression 원칙**:
   - `PROGRESSED`는 신규 진입 관점에서는 "신규 진입에 너무 늦은 국면(Late for fresh entry)"이지만, 이미 보유 중인 포지션에게는 "강력한 추세 확장 국면"이다.
   - `EARLY_TREND → PROGRESSED` 전이 자체는 매도 사유가 아니며, 정상적인 추세 확장으로 간주하여 보유를 지속한다.

### 3. Exit Architecture (청산 아키텍처 및 정책 분리)
Fresh OOS에서는 공식 Primary 정책과 실험적 비교군을 명확히 분리하여 병렬 추적한다:

#### 1) OFFICIAL PRIMARY POLICY: `PRIMARY_V03` (공식 기준 정책)
- **정상 전이 경로 (`NORMAL_EARLY_TREND_HANDOFF`)**:
  - 진입 후 `EARLY_TREND → PROGRESSED` 직접 handoff가 관측된 경우에만 Exit 3과 Exit 4가 활성화됨.
  - **Exit 4 (Profit Protection)**: `PROGRESSED` 진입 이후 최고점 Pattern A 점수(`PROGRESSED_HWM`) 대비 현재 점수가 **15.0pt 이상 하락(`PROGRESSED_HWM - Current Score >= 15.0`)** 시 익월 첫 로컬 거래일 시가 청산.
  - **Exit 3 (Structural Backstop)**: `PROGRESSED` 국면에서 다른 유효 구조적 Stage(`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`)로 이탈 시 익월 첫 로컬 거래일 시가 청산.
  - **Terminal Exit**: `min(Exit 3, Exit 4)` 적용 (가장 빠른 신호 우선 체결).
- **Coverage Hole 경로 (`SKIPPED` / `PROGRESSED_WITHOUT_DIRECT`)**:
  - `PRIMARY_V03`에서는 Coverage Activated Exit 4를 적용하지 않으며, 기존 baseline semantics(미청산 `OPEN_AT_CUTOFF`)를 유지함.

#### 2) EXPERIMENTAL COMPARATOR: `PRIMARY_V03_WITH_COVERAGE_EXPERIMENT` (실험적 비교군)
- `PRIMARY_V03`와 Entry, Hold, Normal Exit semantics가 100% 동일함.
- **유일한 차이점**: Coverage Hole (`SKIPPED_EARLY_TREND_HANDOFF`, `PROGRESSED_WITHOUT_DIRECT_HANDOFF`) 거래에서 최초 관측된 completed monthly `PROGRESSED` 스냅샷부터 frozen 15.0pt Exit 4 protection을 활성화함.
- **불변 원칙**: Fresh OOS 실행 후 결과에 따라 Primary 정책을 사후 교체하는 행위를 금지하며, 공식 평가 권위는 항상 `PRIMARY_V03`에 귀속됨.

================================================================================
5. Known Trade-offs & Risk Characteristics
================================================================================
1. **Right Tail Truncation vs Peak Giveback Defense**:
   - Exit 4(15.0pt 보호) 및 Coverage Activation은 Peak Giveback을 크게 줄이고 손실 거래를 축소하는 탁월한 방어력을 제공한다.
   - 그러나 기존 대형 승자(Return ≥ +50%) 중 약 47.1%, 초대형 승자(Return ≥ +100%) 중 약 60.0%에서 조기 청산으로 인한 수익 감소(Right Tail Truncation)가 발생한다.
   - Fresh OOS 검증 시 **Individual Winner Truncation**과 **Aggregate Winner Preservation**을 동시에 측정해야 한다.
2. **Subgroup Heterogeneity**:
   - `SKIPPED_EARLY_TREND_HANDOFF`는 Giveback 방어와 Return 개선이 강력한 반면, `PROGRESSED_WITHOUT_DIRECT_HANDOFF`는 효과가 일부 거래에 집중된다.

================================================================================
6. Fresh OOS Protocol & Metrics Contract
================================================================================
- **Fresh OOS Boundary Status**: `TO_BE_PREREGISTERED_BEFORE_EXECUTION` (데이터 확인 전 시작일/종료일/관찰기간 사전등록 확정)
- **Primary vs Experimental Paired Comparison Contract**:
  - Return Delta, Giveback Delta, Profit Capture Delta, Holding Period Delta를 산출하여 v0.2D의 Trade-off를 독립 재현함.

#### 1. 필수 평가 지표군
- **Entry & Execution**: Entry Count (N), Execution Delay Days, Non-executable Reason Count
- **Forward Horizon Returns**: 4W, 8W, 12W, 26W Return, Terminal Return (Mean, Median, P25, P75, Positive Rate)
- **Path Metrics**: MFE (Mean, Median), MAE (Mean, Median), Peak Giveback (Distribution Median & Paired Delta), Profit Capture Ratio
- **Exit Breakdown**: Exit 3 Count, Exit 4 Count, No Exit (Open at cutoff) Count, Holding Weeks
- **Tail Metrics**:
  - Right Tail: Return ≥ +20%, ≥ +50%, ≥ +100% 도달 건수 및 보존율, 대형 승자 조기 청산 손실률
  - Failure Tail: Return < 0, Return ≤ -20%, Return ≤ -30% 손실 발생률

#### 2. 필수 관찰 코호트 (Observation Cohorts)
- **Pattern A Entry Stage**: `WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`, `PROGRESSED` (`ENTRY_STAGE_PROGRESSED`), `UNAVAILABLE`
- **Daily Risk State**: `NORMAL`, `ELEVATED`
- **Market**: `KOSPI`, `KOSDAQ`
- **Post-entry Lifecycle Cohort**: `NORMAL_EARLY_TREND_HANDOFF`, `SKIPPED_EARLY_TREND_HANDOFF`, `PROGRESSED_WITHOUT_DIRECT_HANDOFF`, `NEVER_PROGRESSED`

================================================================================
7. 절대적 불변 규칙 (Freeze Invariants)
================================================================================
Fresh OOS 및 후속 연구 과정에서 다음 항목의 임의 변경을 엄격히 금지한다:
1. **FAST v0.1 Trigger Semantics & Machine Rules 불변**
2. **FAST Monthly Permission State (`PERMITTED_REGIME`) 불변**
3. **FAST Daily Risk State (`NORMAL`, `ELEVATED`) 불변**
4. **FAST Score Status (`READY`, `PARTIAL`) 불변**
5. **Pattern A Score & Stage 산출 로직 불변**
6. **Exit 4 Drawdown Threshold `15.0pt` 불변 (Sweep/Tuning 금지)**
7. **Pre-PROGRESSED Time/Price Stop 금지 (무조건 HOLD)**
8. **Point-In-Time (PIT) 스냅샷 원칙 및 익영업일 시가 체결 원칙 불변**
9. **Primary Policy(`PRIMARY_V03`)의 사전 확정 및 사후 교체 금지**
10. **운영 파이프라인(`PRODUCTION_HOLD`) 상태 유지**
