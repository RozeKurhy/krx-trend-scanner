# Pattern A FAST Final Strategy Specification v0.1

================================================================================
1. Executive Summary & Strategy Philosophy
================================================================================
- **전략 명칭**: `PATTERN_A_FAST_FINAL_STRATEGY_V01`
- **전략 상태 (Strategy Status)**: **`FINAL_STRATEGY_FROZEN`**
- **연구 상태 (Research Status)**: **`STRATEGY_FINALIZATION_CLOSED`**
- **연구 분류 (Research Classification)**: `STRATEGY_FINALIZATION_FROZEN_CONTRACT`
- **연구 출처 (Research Source)**: `SAME_SAMPLE_RETROSPECTIVE_FINALIZATION`
- **아키텍처 기준 커밋 (Architecture Authority)**: [`89df82a`](https://github.com/RozeKurhy/krx-trend-scanner/commit/89df82a938dba1961c2342064db2dc0061a5f2ca)
- **사전등록 커밋 (Preregistration Authority)**: [`a5c29e7`](https://github.com/RozeKurhy/krx-trend-scanner/commit/a5c29e7e97cb7e6830c3dcd25d824e5779f2312f)
- **평가 증거 커밋 (Evaluation Evidence)**: [`52acf05`](https://github.com/RozeKurhy/krx-trend-scanner/commit/52acf0555036794e112c0aeb0c73213ddeff4b86)
- **최종 선택 권한 (Selection Authority)**: **`FINAL_STRATEGY_CONTRACT`** (`docs/validation/pattern_a_fast_final_strategy_v01.md` + `artifacts/pattern_a_fast/final_strategy_v01/pattern_a_fast_final_strategy_v01.json`)
- **계약 권한 (Contract Authority)**: **`THIS_FINAL_STRATEGY_CONTRACT_REVISION`**
- **Fresh OOS 상태**: **`READY_FOR_PREREGISTRATION`** (Fresh OOS 실행 여부: `NO`)
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production Candidate 여부**: **`NO` (Fresh OOS 검증 완료 전 운영 배포 불가)**
- **테스트 정책**: `Tests: NOT RUN`

#### 💡 투자자 최상위 원칙 (Investment Mandate & Philosophy)
- **최우선 목적 (Primary Objective)**: **`LARGE_LOSS_MINIMIZATION` (대형 손실 최소화)**
- **차순위 목적 (Secondary Objective)**: **`PRESERVE_SUFFICIENT_UPSIDE` (충분한 상승 수익 보존)**
- **핵심 철학**:
  > *"구조적으로 확인된 상승 초입(`TRANSITION`, `EARLY_TREND`)에만 진입하고, 바닥 반등 및 구조적 불확실성에서 발생하는 추가 수익은 의도적으로 포기한다. 큰 손실 가능성(`Return <= -20%`, `Return <= -30%`, `Deep MAE`)을 우선적으로 억제하면서, 그 위험 범위 안에서 가능한 한 빠른 진입과 충분한 추세 상승 수익을 추구한다."*

================================================================================
2. Entry Contract (진입 계약)
================================================================================
1. **허용 및 제외 국면 (`allowed_pattern_a_stages` / `excluded_pattern_a_stages`)**:
   - **허용 국면**: **`TRANSITION`**, **`EARLY_TREND`**
   - **제외 국면**: **`WEAK`**, **`BASE`**, **`UNAVAILABLE`**, **`PROGRESSED`**
2. **FAST Entry Core Rules (`FROZEN_CORE`)**:
   - **Weekly FAST Machine Stage**: `TRIGGER` & Status `READY`
   - **Monthly FAST Permission**: `PERMITTED_REGIME`
   - **Daily Risk State**: `NORMAL` 또는 `ELEVATED` (`EXTREME` 차단)
   - **FAST Score Status**: `READY` 또는 `PARTIAL` (Numeric 점수 컷오프 없음)
3. **종목당 진입 규칙 (`entry_selection`)**:
   - **`FIRST_QUALIFYING_ENTRY_PER_TICKER`** (연구/검증 구간 내 최초 적격 신호 1회만 진입)
4. **체결 타이밍 (`execution_timing`)**:
   - 신호 발생 주간 익영업일 시가 (**`NEXT_LOCAL_TRADING_DAY_OPEN`**)

================================================================================
3. Pre-PROGRESSED Hold & Loss Guard Contract (보유 및 손실 방어 계약)
================================================================================
1. **손실 가드 규칙 (`HOLD_B_PRE_PROGRESSED_LOSS_GUARD`)**:
   - **발동 조건 (`trigger_condition`)**: `daily_close / entry_open - 1.0 <= -0.15` (체결일 이후 일봉 종가 기준 -15% 이하 도달)
   - **가격 기준 (`price_reference`)**: `ENTRY_EXECUTION_OPEN`
   - **신호 기준가 (`signal_price`)**: `COMPLETED_DAILY_CLOSE`
   - **활성 구간 (`active_window`)**: `AFTER_ENTRY_EXECUTION AND BEFORE_FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE`
   - **유효 정보일 (`progressed_snapshot_information_date`)**: `LAST_LOCAL_TRADING_DAY_USED_TO_FORM_COMPLETED_MONTHLY_SNAPSHOT`
   - **활성 조건 (`loss_guard_active_condition`)**: `CURRENT_TRADING_DATE_LT_FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE`
   - **체결 타이밍**: 신호 발생 익영업일 시가 (**`NEXT_LOCAL_TRADING_DAY_OPEN`**)
   - **청산 식별자**: `LOSS_GUARD_CLOSE_LE_NEG_15`
2. **PROGRESSED 진입 시 전환 규칙**:
   - 최초 `PROGRESSED` 월봉 스냅샷을 형성하는 마지막 로컬 거래일(`FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE`) 종가부터 Loss Guard는 **비활성화(`INACTIVE`)**되며, PROGRESSED 청산 아키텍처 권한으로 전환됨.
3. **금지 규칙**:
   - Time Stop: `NONE`
   - Price Stop in PROGRESSED: `NONE`
   - FAST Reversal Stop: `NONE`
   - Stage 전이로 인한 조기 청산: `NONE`

================================================================================
4. PROGRESSED Exit Contract (추세 국면 청산 계약)
================================================================================

#### 1) 정상 직접 전이 경로 (`NORMAL_EARLY_TREND_HANDOFF`)
- **Exit 4 (Profit Protection)**:
  - 활성화 스냅샷 점수로 `PROGRESSED_HWM` 초기화 (`ARM_SNAPSHOT_PATTERN_A_SCORE`).
  - PROGRESSED 유지 중 `HWM = max(previous HWM, current score)` 갱신.
  - `PROGRESSED_HWM - Current Score >= 15.0pt` (frozen) 시 신호 발생, 익월 첫 로컬 거래일 시가 청산 (`EXIT4_SCORE_DRAWDOWN_GE_15`).
  - 적용 대상 국면: `PROGRESSED_ONLY`.
- **Exit 3 (Structural Backstop)**:
  - `PROGRESSED`에서 다른 유효 구조적 Stage(`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`)로 이탈 시 익월 첫 로컬 거래일 시가 청산 (`EXIT3_PROGRESSED_TO_{STAGE}`).
- **청산 우선순위 (`terminal_precedence`)**: **`EARLIEST_EXECUTABLE_SIGNAL`** (가장 빠른 신호 우선 체결).

#### 2) Coverage Hole 경로 (`SKIPPED_EARLY_TREND_HANDOFF`, `PROGRESSED_WITHOUT_DIRECT_HANDOFF`)
- **Coverage Exit 4 Activation**: 최초 관측된 `PROGRESSED` 스냅샷부터 활성화 (`FIRST_OBSERVED_PROGRESSED_SNAPSHOT`).
- **HWM 및 Trigger**: 최초 관측된 PROGRESSED 점수로 HWM 초기화 후 `HWM - Current Score >= 15.0pt` 시 청산.
- **Coverage Exit 3 확장**: `NONE` (Exit 3는 Coverage Hole에서 확장하지 않음).
- **Exit 4 미발생 이탈 시**: `OPEN_AT_CUTOFF` 유지.

#### 3) NEVER_PROGRESSED & 미청산 거래
- 평가 종료일(Cutoff)까지 미청산된 거래는 **`OPEN_AT_CUTOFF`**로 유지 (`forced_close: false`, `valuation: MARK_TO_CUTOFF`).

================================================================================
5. Known Trade-offs & Risk Characteristics (알려진 위험 및 한계)
================================================================================
1. **대형 손실 방어 vs 승률/기대수익 절단 비용**:
   - Pre-PROGRESSED Loss Guard는 <= -30% 극단 손실을 84.7%, <= -20% 손실을 68.9% 제거하여 파산 위험을 획기적으로 낮춘다.
   - 반면 약 53.2%의 높은 손절 발동률(294건)로 인해 승률(39.6%)과 중앙값 수익률(-14.15%)이 감소하며, Loss Guard가 없었다면 E1 기준 terminal return이 +50% 이상이었을 64건의 대형 승자(및 +100% 이상 31건)가 조기 마감되는 명확한 기회비용이 존재한다.
2. **손절 거래의 Counterfactual MFE 특성**:
   - 손절된 294건 거래의 잠재 최대 상승률(Counterfactual MFE)은 평균 79.08%, 중앙값 37.71%로 나타남.
3. **익일 시가 체결 갭 위험 (Execution Gap Risk)**:
   - 손실 가드는 일봉 종가 -15% 도달 시 발생하여 익영업일 시가에 체결되므로, 갭 하락 시 실제 실현 손실이 -15%를 초과할 수 있다 (표본 내 최악 손실률 -49.4%, 최악 MAE -64.86%).
4. **표본 내 확정 및 독립 검증 필요성**:
   - 본 전략은 동일 과거 표본(2026-08-14 이전)에서 확정된 후보이므로, 일반화 성능 검증을 위한 **Fresh OOS Forward Validation** 사전등록 및 검증이 필수적이다.
