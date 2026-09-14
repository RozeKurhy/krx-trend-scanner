# Pattern A FAST Strategy Finalization / Candidate Selection v0.1 사전등록서

================================================================================
1. 연구 목적 및 연구 분류
================================================================================
- **연구명**: Pattern A FAST Strategy Finalization / Candidate Selection v0.1
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_STRATEGY_FINALIZATION_CANDIDATE_SELECTION`
- **검증 유형 (Validation Type)**: `SAME_SAMPLE_RETROSPECTIVE_FINALIZATION`
- **아키텍처 기준 (Architecture Authority)**: `PATTERN_A_FAST_ARCHITECTURE_V03` ([`89df82a`](https://github.com/RozeKurhy/krx-trend-scanner/commit/89df82a938dba1961c2342064db2dc0061a5f2ca))
- **데이터 기준일 (Data Cutoff)**: `2026-08-14` (**LOCAL CACHE ONLY**, 2026-08-15 이후 데이터 일체 사용 금지)
- **Fresh OOS 여부**: `NO` (과거 데이터 기반 전략 확정 연구이며, Fresh OOS 증거가 아님)
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **테스트 정책**: `Tests: NOT RUN`

> **[연구 목적 및 성격]**:
> 본 연구의 목적은 투자자의 최상위 투자 철학 및 위험 관리 원칙(**Investment Mandate**)에 따라, Fresh OOS에 전달할 **단 하나의 최종 트레이딩 전략 후보(Final Strategy Candidate: `PATTERN_A_FAST_FINAL_STRATEGY_V01`)**를 확정하는 것입니다. 진입 규칙은 투자자 원칙에 따라 고정되며, 본 연구에서는 **Pre-PROGRESSED 보유/손실 방어 규칙**과 **PROGRESSED 이후 청산 아키텍처**만을 동일 역사적 표본(553건)에서 체계적으로 비교 검증합니다.

================================================================================
2. 투자자 최상위 원칙 및 철학 (Investment Mandate & Philosophy)
================================================================================

#### 1. 투자 원칙 (Investment Mandate)
- **최우선 목적 (Primary Objective)**: **`LARGE_LOSS_MINIMIZATION` (대형 손실 최소화)**
- **차순위 목적 (Secondary Objective)**: **`PRESERVE_SUFFICIENT_UPSIDE` (충분한 상승 수익 보존)**
- **핵심 원칙**:
  - 높은 수익률은 가치 있으나, 더 높은 기대수익을 위해 구조적 불안정 구간이나 극단적 하방 위험(`Return <= -20%`, `Return <= -30%`, `Deep MAE`)을 감수하지 않는다.
  - 손실의 횟수(승률)보다 **손실의 규모(Loss Magnitude)**를 더 중요하게 통제한다.

#### 2. 투자 철학 (Investment Philosophy)
> *"구조적으로 확인된 상승 초입에만 투자한다. 바닥 반등 및 구조적 불확실성에서 발생하는 추가 수익은 의도적으로 포기하며, 큰 손실 가능성을 우선적으로 억제하면서 그 위험 범위 안에서 가능한 한 빠른 진입과 충분한 상승 수익을 추구한다."*

================================================================================
3. 진입 정책 및 대상 표본 (Frozen Entry Contract)
================================================================================

#### 1. 허용 및 제외 국면 (Investment Mandate Decision)
- **신규 진입 허용 Pattern A Stage**: **`TRANSITION`**, **`EARLY_TREND`**
- **신규 진입 제외 Stage**: **`WEAK`**, **`BASE`**, **`UNAVAILABLE`**, **`PROGRESSED`**
  - **`WEAK` 제외 이유**: 급반등 및 높은 기대수익 가능성은 인정하나, 구조적 약세/역배열 위험 구간이므로 대형 손실 방지 원칙상 신규 투자 제외 (수익률이 높아도 재승격 불가).
  - **`BASE` 제외 이유**: 바닥 형성 가능성은 있으나 추세 전환 확인이 미흡하므로 제외.
  - **`UNAVAILABLE` 제외 이유**: 정보 부족으로 구조 판단이 불가능하므로 "판단할 수 없는 대상에는 투자하지 않는다"는 원칙에 따라 제외.
  - **`PROGRESSED` 제외 이유**: 신규 진입 관점에서는 이미 늦은 생애주기이므로 신규 진입 제외.
  - **`FAST`의 역할**: `WEAK`/`BASE`를 투자 가능하게 만드는 것이 아니라, `TRANSITION`에서 `EARLY_TREND`보다 주봉 신호를 통해 안전하게 한 단계 빠른 진입을 가능하게 하는 것.

#### 2. Frozen FAST Entry Core
- **Weekly FAST Machine Stage**: `TRIGGER` & Status `READY`
- **Monthly FAST Permission**: `PERMITTED_REGIME`
- **Daily Risk State**: `NORMAL` 또는 `ELEVATED` (`EXTREME` 차단)
- **FAST Score Status**: `READY` 또는 `PARTIAL` (Numeric threshold 없음)
- **Execution Timing**: 신호 발생 주간 익영업일 시가 (**NEXT LOCAL TRADING DAY OPEN**)
- **종목당 진입 규칙**: `FIRST_QUALIFYING_ENTRY_PER_TICKER` (최초 1회 진입만 채택)
- **Primary 표본 크기**: 총 553개 거래 (`TRANSITION`: 484건, `EARLY_TREND`: 69건)

================================================================================
4. 검증 후보군 설계 (Hold & Exit Candidate Space)
================================================================================

평가는 그리드 탐색이 아닌 2단계 순차 결정 방식으로 진행한다:

### STEP 1: Pre-PROGRESSED Hold Candidates (보유 및 손실 방어 후보)
- **`HOLD_A` (`NO_PRE_PROGRESSED_PROTECTION`)**:
  - 기존 v0.3 동결 semantics.
  - `PROGRESSED` 도달 전 Time Stop, Price Stop, FAST Reversal Stop, Stage Stop 없이 무조건 보유(`HOLD`).
- **`HOLD_B` (`PRE_PROGRESSED_CATASTROPHIC_LOSS_GUARD`)**:
  - 대형 손실 Tail(`<= -20%`, `<= -30%`) 억제를 위한 사전등록된 단일 손실 가드.
  - `PROGRESSED` 국면 도달 전, 체결일 이후 일봉 종가 기준 `daily_close / entry_open - 1 <= -0.15` 발생 시 손실 방어 신호, 익일 시가 청산.
  - **Sweep 금지**: -10%, -12%, -15%, -18%, -20% 등의 파라미터 스윕을 일체 금지하며, 사전등록된 -15% 단일 기준만 검증.

### STEP 2: PROGRESSED Exit Candidates (추세 국면 청산 후보)
- **`E0` (`EXIT3_ONLY`)**:
  - Exit 4 및 Coverage 미사용.
  - 정상 직접 handoff 후 `PROGRESSED`에서 다른 유효 구조적 국면(`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`)으로 이탈 시 익영업일 시가 청산.
- **`E1` (`EXIT3_PLUS_NORMAL_EXIT4`)**:
  - 정상 직접 handoff 후 Exit 3 + Normal Exit 4 (`PROGRESSED_HWM - Current Score >= 15.0pt`, frozen) 적용.
  - Coverage Hole은 미청산 `OPEN_AT_CUTOFF`.
- **`E2` (`EXIT3_PLUS_EXIT4_PLUS_COVERAGE`)**:
  - E1과 동일하며, Coverage Hole(`SKIPPED`, `PROGRESSED_WITHOUT_DIRECT`)에서 최초 관측된 `PROGRESSED` 스냅샷부터 15.0pt Exit 4 protection 활성화.

================================================================================
5. 평가 지표 및 우선순위 (Evaluation Priorities)
================================================================================

#### 1. Hold Selection 우선순위 (STEP 1)
1. **Return <= -30% 발생률**
2. **Return <= -20% 발생률**
3. **MAE Deep Tail & Worst MAE**
4. **Adverse Excursion (P75, P90)**
5. **Peak Giveback**
6. **Terminal Return**
7. **Winner Truncation 비용** (Stopped 거래수, 조기 청산된 +20%/+50% 대형 승자 비율)

#### 2. Exit Selection 우선순위 (STEP 2)
1. **Return <= -30% 및 <= -20% 극단 손실 방어력**
2. **MAE 및 Peak Giveback 억제력**
3. **Profit Capture Ratio**
4. **Terminal Return**
5. **Right Tail Winner 보존율**

================================================================================
6. 불변 규칙 및 안티-튜닝 원칙 (Freeze Invariants)
================================================================================
1. **Data Cutoff 2026-08-14 엄수 (신규 데이터 일체 조회 금지)**
2. **WEAK / BASE / UNAVAILABLE / PROGRESSED 신규 진입 사후 복원 일체 금지**
3. **Loss Guard Threshold (-15%) 및 Exit 4 Threshold (15.0pt) 단일 고정 (Zero Sweeps)**
4. **임의의 신규 진입/청산 룰 생성 금지**
5. **평가 완료 후 단 하나의 최종 전략(`PATTERN_A_FAST_FINAL_STRATEGY_V01`) 확정**
6. **운영 파이프라인(`PRODUCTION_HOLD`) 상태 불변**
