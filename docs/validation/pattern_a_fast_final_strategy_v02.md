# Pattern A FAST Final Strategy Specification v0.2

================================================================================
1. Executive Summary & Strategy Philosophy
================================================================================
- **전략 명칭 (Formal Strategy ID)**: **`PATTERN_A_FAST_FINAL_STRATEGY_V02`**
- **한국어 공식 명칭**: **`패턴A FAST 최종 전략 V02`**
- **기본 통용 명칭 (Preferred / Default Alias)**: **`A FAST Core V2`**, **`패스트 코어 V2`** *(별도 버전 언급 없이 `A FAST Core`, `패스트 코어` 지칭 시 본 V02 전략을 기본 의미함)*
- **전략 상태 (Strategy Status)**: **`FINAL_STRATEGY_FROZEN`**
- **연구 상태 (Research Status)**: **`STRATEGY_FINALIZATION_CLOSED` (패스트 코어 전략 연구 완료)**
- **연구 분류 (Research Classification)**: `STRATEGY_FINALIZATION_FROZEN_CONTRACT`
- **역사적 기준선 (Historical Baseline)**: **`PATTERN_A_FAST_FINAL_STRATEGY_V01`** (V01은 불변 기준선으로 영구 보존)
- **V01 대비 변경점 (Delta from V01)**: **`REENTRY_ONLY`** (동일 종목 독립 재진입 허용 단 하나만 변경)
- **아키텍처 기준 커밋 (Architecture Authority)**: [`89df82a`](https://github.com/RozeKurhy/krx-trend-scanner/commit/89df82a938dba1961c2342064db2dc0061a5f2ca)
- **캘린더 권한 커밋 (Calendar Authority)**: [`88d54d8`](https://github.com/RozeKurhy/krx-trend-scanner/commit/88d54d85bdee1f2121bec9b27a250cbc1cb9f98f)
- **평가 증거 커밋 (Evaluation Evidence)**: [`cdfeaed`](https://github.com/RozeKurhy/krx-trend-scanner/commit/cdfeaed579f880c437d1a95d4227dd3051843008)
- **Fresh OOS 실행 여부**: **`NO`** (본 증거는 동일 과거 표본 retrospective 확정임)
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**

#### 💡 투자자 최상위 원칙 (Investment Mandate & Philosophy)
- **최우선 목적 (Primary Objective)**: **`LARGE_LOSS_MINIMIZATION` (대형 손실 최소화)**
- **차순위 목적 (Secondary Objective)**: **`PRESERVE_SUFFICIENT_UPSIDE` (충분한 상승 기회 회수 및 추세 확장)**
- **V02 핵심 운영 철학**:
  > *"구조적으로 확인된 상승 초입(`TRANSITION`, `EARLY_TREND`)에만 진입하고, Pre-PROGRESSED 손실가드(-15%)와 추세 청산(Exit 3/4)으로 위험을 통제한다. 첫 진입이 손절 또는 정상 청산으로 종료되었더라도, 이후 동일한 구조적 Entry Contract가 다시 충족된다면 과거 거래 결과 때문에 미래의 독립적인 진입 기회를 영구적으로 차단하지 않는다."*

================================================================================
2. V01 vs V02 Component Comparison (전략 구성 요소 비교표)
================================================================================

| 전략 구성 요소 | V01 (Historical Frozen Baseline) | V02 (Current Preferred Strategy) | V01 대비 일치 여부 |
|---|---|---|:---:|
| **진입 허용 국면 (Stage Eligibility)** | `TRANSITION`, `EARLY_TREND` | `TRANSITION`, `EARLY_TREND` | **SAME AS V1** |
| **진입 제외 국면 (Excluded Stages)** | `WEAK`, `BASE`, `PROGRESSED`, `UNAVAILABLE` | `WEAK`, `BASE`, `PROGRESSED`, `UNAVAILABLE` | **SAME AS V1** |
| **FAST 진입 조건 (FAST Machine)** | `TRIGGER` & Status `READY` | `TRIGGER` & Status `READY` | **SAME AS V1** |
| **월간 거시 국면 (Monthly Permission)** | `PERMITTED_REGIME` | `PERMITTED_REGIME` | **SAME AS V1** |
| **일봉 리스크 상태 (Daily Risk)** | `NORMAL`, `ELEVATED` (`EXTREME` 차단) | `NORMAL`, `ELEVATED` (`EXTREME` 차단) | **SAME AS V1** |
| **점수 적격성 (Score Status)** | `READY`, `PARTIAL` (Numeric Cutoff 없음) | `READY`, `PARTIAL` (Numeric Cutoff 없음) | **SAME AS V1** |
| **진입 체결 타이밍 (Execution)** | `NEXT_LOCAL_TRADING_DAY_OPEN` | `NEXT_LOCAL_TRADING_DAY_OPEN` | **SAME AS V1** |
| **Pre-PROGRESSED 손실가드** | 일봉 종가 `-15%` 도달 시 익일 시가 손절 | 일봉 종가 `-15%` 도달 시 익일 시가 손절 | **SAME AS V1** |
| **손실가드 해제 시점** | `FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE` | `FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE` | **SAME AS V1** |
| **PROGRESSED Exit 4** | Score HWM 대비 `15.0pt` 하락 청산 | Score HWM 대비 `15.0pt` 하락 청산 | **SAME AS V1** |
| **PROGRESSED Exit 3** | 월봉 Stage 이탈 (`WEAK`/`BASE`/`TRANSITION`/`EARLY`) | 월봉 Stage 이탈 (`WEAK`/`BASE`/`TRANSITION`/`EARLY`) | **SAME AS V1** |
| **Coverage 경로 청산** | 최초 관측 PROGRESSED부터 Exit 4만 적용 | 최초 관측 PROGRESSED부터 Exit 4만 적용 | **SAME AS V1** |
| **동일 종목 재진입 (Re Entry)** | **`FIRST_QUALIFYING_ENTRY_PER_TICKER` (1회 한정)** | **`MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER` (독립 재진입 허용)** | **`MODIFIED` (유일한 변경점)** |
| **상태 초기화 (State Reset)** | N/A (단일 진입) | **`FULL` (새 entry_open, 손실가드, 생애주기, HWM 완전 재설정)** | **`V02 SPECIFIC`** |

================================================================================
3. Re Entry Contract (재진입 계약)
================================================================================
1. **재진입 기본 원칙 (`reentry_eligibility`)**:
   - 이전 거래의 손실가드(Loss Guard), Exit 3, Exit 4 또는 기타 정상 청산 여부와 관계없이, **보유 포지션이 완전히 청산된 상태**에서 신규 진입 조건이 다시 충족되면 동일 종목의 재진입을 허용한다.
2. **운영 제약 없음 (`unconstrained_reentry`)**:
   - **대기 기간 (`cooldown`)**: **`NONE`** (인위적 쿨다운 없음)
   - **재진입 횟수 제한 (`maximum_reentries`)**: **`NONE`** (횟수 제한 없음)
   - **피라미딩 (`pyramiding`)**: **`FORBIDDEN`** (포지션 보유 중 추가 매수 금지)
   - **동일 종목 포지션 중복 (`overlapping_same_ticker_position`)**: **`FORBIDDEN`** (단일 종목 동시 보유 불가)
3. **체결 타이밍 및 동시 체결 금지 (`timing_and_non_overlap`)**:
   - 이전 거래 종료 체결일(Execution Open) 이후 도래하는 정규 거래일의 완료된 일봉 종가(Completed Close)부터 새로운 진입 신호 형성이 가능하다.
   - **동일 시가 청산 및 재진입 (`same_open_exit_and_reentry`)**: **`FORBIDDEN`** (동일 일자 시가에서 청산과 재진입이 동시 발생하는 것 엄격 금지).
4. **상태 독립성 및 완전 리셋 (`full_state_reset`)**:
   - 모든 재진입 거래는 완전히 독립된 신규 거래로 취급된다.
   - **`entry_open` 리셋**: 새 진입 체결일의 시가를 기준으로 기준가를 독립 산출.
   - **`Loss Guard` 리셋**: 새 `entry_open`의 85%를 기준으로 -15% 손실가드를 재계산.
   - **`PROGRESSED Lifecycle` 리셋**: 새 진입일 이후 형성되는 월봉 스냅샷부터 독립적으로 생애주기를 추적.
   - **`Exit 4 HWM` 리셋**: 새 거래 안에서 최초 PROGRESSED에 도달한 시점의 점수부터 HWM을 초기화하며, 이전 거래의 HWM을 승계하지 않음.

================================================================================
4. Entry & Protection Core Rules (진입 및 방어 상세 규칙)
================================================================================

#### 1) Entry Contract (진입 규칙 - V01 동일)
- **허용 국면**: `TRANSITION`, `EARLY_TREND`
- **제외 국면**: `WEAK`, `BASE`, `PROGRESSED`, `UNAVAILABLE`
- **FAST Trigger**: Weekly FAST Machine `TRIGGER` & Status `READY`
- **Monthly Regime**: `PERMITTED_REGIME`
- **Daily Risk**: `NORMAL` 또는 `ELEVATED` (`EXTREME` 차단)
- **FAST Score**: `READY` 또는 `PARTIAL`
- **체결 타이밍**: 신호 발생 주간 익영업일 시가 (**`NEXT_LOCAL_TRADING_DAY_OPEN`**)

#### 2) Pre-PROGRESSED Loss Guard (손실 방어 - V01 동일)
- **발동 조건**: `daily_close / entry_open - 1.0 <= -0.15` (일봉 종가 기준 -15% 이하 도달)
- **활성 구간**: 체결일 이후부터 `FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE` 이전까지
- **체결 타이밍**: 신호 발생 익영업일 시가 (**`NEXT_LOCAL_TRADING_DAY_OPEN`**)
- **해제 조건**: 최초 `PROGRESSED` 월봉 스냅샷을 형성하는 마지막 거래일(`FIRST_PROGRESSED_EFFECTIVE_TRADING_DATE`) 종가부터 손실가드는 영구 비활성화(`INACTIVE`)됨.

#### 3) PROGRESSED Exit Contract (추세 청산 - V01 동일)
- **Exit 4 (Score Drawdown)**:
  - PROGRESSED 도달 시점 점수로 `PROGRESSED_HWM` 초기화.
  - `PROGRESSED_HWM - Current Score >= 15.0pt` 시 신호 발생, 익월 첫 로컬 거래일 시가 청산 (`EXIT4_SCORE_DRAWDOWN_GE_15`).
- **Exit 3 (Stage Transition)**:
  - `PROGRESSED`에서 다른 유효 Stage(`WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`)로 이탈 시 익월 첫 로컬 거래일 시가 청산 (`EXIT3_PROGRESSED_TO_{STAGE}`).
- **Coverage 경로 (SKIPPED / WITHOUT DIRECT)**:
  - 최초 관측 PROGRESSED 스냅샷부터 Exit 4만 활성화, Exit 3는 미적용 (`OPEN_AT_CUTOFF` 유지).

================================================================================
5. Retrospective Evidence Summary (V02 회고적 실증 지표 요약)
================================================================================
*본 수치는 공식 확정 아티팩트(`artifacts/pattern_a_fast/core_v02_reentry/trades.csv`)에 근거합니다.*

- **총 거래 수 (`Total Trades`)**: **`783건`**
  - **1차 진입 (`First Entries`)**: **551건** (V01과 100% 동일)
  - **재진입 (`Re Entries`)**: **232건**
- **참여 종목 수 (`Unique Tickers`)**: **551개**
- **재진입 발생 종목 수 (`Reentered Tickers`)**: **151개**
- **전체 평균 수익률 (`Mean Terminal Return`)**: **`+18.84%`** (V01 +18.48%)
- **전체 승률 (`Positive Rate`)**: **`40.10%`** (314건 승리, V01 39.93%)
- **재진입 코호트 단독 성과 (232건)**:
  - 평균 수익률: **`+19.69%`** / 중앙값: **`-13.66%`** / 승률: **`40.52%`**
  - 대형 승자 (>= +50%): **51건 (21.98%)** / 초대형 승자 (>= +100%): **17건 (7.33%)**
  - Return <= -20% 손실: **14건 (6.03%)** / Return <= -30% 손실: **4건 (1.72%)**
- **종목 생애주기 누적 수익률 (`Sequential Cumulative Return`)**:
  - 평균: **`+25.68%`** (V01 대비 +7.20%p 상승) / 중앙값: **`-2.32%`** (V01 -13.60% 대비 대폭 개선)
  - 생애주기 플러스 종목 비율: **`49.18%`** (271개 종목, V01 대비 +9.25%p 상승)

================================================================================
6. Known Risks & Deferred Research (알려진 위험 및 보류된 연구)
================================================================================

#### 1) 알려진 위험 (Known Trade-offs)
1. **재진입 시 테일 손실 증가**:
   - 재진입 허용 시 추가적인 대형 상승 기회를 회수할 수 있으나, Return <= -20% 손실(39건, 4.98%) 및 Return <= -30% 극단 손실(10건, 1.28%)의 절대 건수가 소폭 증가함.
2. **PROGRESSED 진입 후 비대칭 보호 구조**:
   - PROGRESSED 도달 후 일봉 손실가드가 해제되고 월봉 국면/점수 청산만 남게 되어, 가격 급락 시 월말 스냅샷까지 청산이 지연되는 특성이 존재함.

#### 2) 보류된 후속 연구 (Deferred Research: PROGRESSED Downside Protection)
- **연구 사실**: PROGRESSED 실제 보유 328건에 대한 진단(`Phase 1`)에서 대형 손실자(중앙값 -44.62%)와 대형 승자(중앙값 -16.65%) 간에 가격 HWM Drawdown의 기술적 분리가 관측됨.
- **보류 사유**: 대형 승자(>= +50%) 중에서도 **18.29%(30건)는 -30% 이하의 깊은 조정을 견디고 최종 승자가 된 우측 꼬리 중첩(Right-Tail Overlap)**이 확인됨. 단순 가격 Trailing Stop을 성급히 적용할 경우 대형 승자가 조기 청산되는 심각한 기회손실 위험이 존재함.
- **처리 방침**:
  - 현재 V02 전략에는 **추가적인 가격 Trailing Stop, Coverage Exit 3 확장, MFE Giveback Guard 등의 규칙을 일체 반영하지 않음**.
  - 25%~30%는 사후 관찰된 후보 범위(`PHASE1_OBSERVED_CANDIDATE_RANGE_ONLY`)일 뿐이며, 정식 전략 규칙이 아님.
  - 해당 과제는 향후 별도 전진 연구(`PROGRESSED_DOWNSIDE_PROTECTION_PHASE2`)로 보류함.

================================================================================
7. Strategy Research Closure Statement
================================================================================
- **`FAST_CORE_STRATEGY_RESEARCH_STATUS`**: **`CLOSED` (연구 공식 종료)**
- **`CURRENT_OFFICIAL_STRATEGY`**: **`PATTERN_A_FAST_FINAL_STRATEGY_V02`**
- **`NEXT_STRATEGY_RESEARCH`**: **`NONE_SCHEDULED` (추가 튜닝 및 전략 수정 계획 없음)**
- **`DEFERRED_RESEARCH`**: **`PROGRESSED_DOWNSIDE_PROTECTION_PHASE2` (보류 상태 유지)**
