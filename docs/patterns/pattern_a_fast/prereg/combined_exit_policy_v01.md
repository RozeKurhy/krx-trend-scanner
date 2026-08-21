# FAST Entry + Pattern A Exit / Handoff Policy v0.1 전종목 사후 정책 평가 사전등록서

================================================================================
1. 연구 목적 및 핵심 연구 질문
================================================================================
- **연구명**: FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_TRADING_POLICY_EVALUATION` (전종목 사후 거래 정책 평가)
- **사전등록 상태**: `PREREGISTERED_BEFORE_EVALUATION` (평가 실행 전 프로토콜 및 가설 사전 고정)
- **Production 상태**: `PRODUCTION_HOLD` (Production 적용 보류, 연구 전용)
- **Production 영향도**: `NONE` (기존 Pattern A / FAST 운영 로직 및 Candidate/Ranking에 일체 무영향)

> **[주의 및 연구 성격 명시]**:
> 본 연구는 2026-08-14 기준 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션하는 **사후 거래 정책 평가(Retrospective Policy Evaluation)**입니다. 본 평가는 **Fresh OOS 또는 OOS Proof가 아니며**, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있음을 명시합니다.

#### 핵심 연구 질문
> "기존 FAST Entry를 Pattern A TRANSITION / EARLY_TREND 구간으로 제한한 뒤, EARLY_TREND → PROGRESSED 구간을 장기 보유하고, PROGRESSED lifecycle 이탈을 메인 Exit로 사용하면서 PROGRESSED Score high-watermark 대비 15점 하락을 조기 Profit Protection으로 추가하면, 큰 추세를 유지하면서 Peak Giveback을 의미 있게 줄일 수 있는가?"

================================================================================
2. 데이터 소스 및 무결성 원칙 (LOCAL CACHE ONLY)
================================================================================
1. **로컬 캐시 전용**: 기존 로컬 Parquet 일봉 캐시(`data/raw/stocks/`) 데이터만 100% 사용한다.
2. **외부 네트워크 호출 절대 금지**: `pykrx`, `requests`, 외부 API, 캐시 refresh, 누락 데이터 자동 다운로드를 일체 수행하지 않는다.
3. **Fail-Closed 원칙**: 데이터가 누락되거나 부족한 종목은 외부에서 보완하지 않고 즉시 사유를 명시하여 제외(Fail-Closed) 처리한다.
   - 제외 사유 코드: `CACHE_MISSING`, `INSUFFICIENT_HISTORY`, `PATTERN_A_UNAVAILABLE`, `FAST_UNAVAILABLE`, `INVALID_OHLCV`, `UNIVERSE_METADATA_UNAVAILABLE`
4. **Source of Truth**: 로컬 일봉 캐시에서 Point-in-Time(PIT) 방식으로 재계산한 결과만을 정본으로 한다.

================================================================================
3. 대상 모집단 및 기준일자 (Population & Data Cutoff)
================================================================================
- **기준일자 (Data Cutoff)**: `2026-08-14` (2026-08-14 이후의 미래 데이터 사용 절대 금지)
- **대상 모집단 (Population)**: 2026-08-14 기준 KRX KOSPI / KOSDAQ 보통주(COMMON) 중 Phase 10 투자 적격성(Investability) 기준을 충족하는 종목
  - 시가총액 ≥ 1,000억원 (`artifacts/investability/source/krx_market_cap_20260814.csv`)
  - 20일 평균 거래대금 ≥ 3억원 (`artifacts/investability/pattern_a_investability_universe_20260814.csv`)
- **평가 기간**: 각 종목의 로컬 캐시 내에서 Pattern A와 FAST 두 evaluator가 모두 PIT 평가 가능한 최초 시점(Warmup 이후)부터 `2026-08-14`까지.

================================================================================
4. 진입 정책 (Entry Policy Contract)
================================================================================
기존 FAST Entry Policy v0.1에 Pattern A Stage Gate를 결합한다.

1. **FAST Entry Policy v0.1 조건 (동일 유지)**:
   - `FAST Stage == "TRIGGER"`
   - `FAST Stage Status == "READY"`
   - `FAST Monthly Permission State == "PERMITTED_REGIME"`
   - `FAST Daily Risk State IN {"NORMAL", "ELEVATED"}` (Grade A: NORMAL, Grade B: ELEVATED)
   - `FAST Score Status IN {"READY", "PARTIAL"}`
   - FAST 숫자 점수 임계값(Score threshold) 없음
2. **Pattern A Stage Gate (추가 조건)**:
   - FAST 신호 주간 시점에 PIT로 관측 가능한 직전 completed monthly snapshot의 Pattern A Stage가:
     - `TRANSITION` 또는 `EARLY_TREND`
   - Pattern A Candidate 여부나 숫자 점수 임계값은 요구하지 않음
3. **체결 규칙 (Execution Rule)**:
   - 신호 발생 주간(`signal_date`) 이후 **다음 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN)** 체결. 신호 당일 종가 체결 금지.
4. **진입 횟수 제한**:
   - 종목당 최초 만족 시점 **최대 1회 (Primary Entry Only)** 허용. 재진입은 본 v0.1 평가 범위에서 제외.

================================================================================
5. Pattern A Handoff 상태 추적 및 이벤트 정의
================================================================================
Entry 이후 매월 completed monthly Pattern A snapshot을 추적하며 아래 이벤트를 기록한다:
1. `ENTRY_AT_TRANSITION`: 진입 시점 Stage가 TRANSITION
2. `ENTRY_AT_EARLY_TREND`: 진입 시점 Stage가 EARLY_TREND
3. `EARLY_TREND_OBSERVED_AFTER_ENTRY`: 진입 이후 EARLY_TREND 도달 관측
4. `EARLY_TREND_TO_PROGRESSED`: EARLY_TREND 도달 후 PROGRESSED로 정상 전이
5. `TRANSITION_TO_PROGRESSED_WITHOUT_EARLY_TREND`: TRANSITION에서 EARLY_TREND를 거치지 않고 PROGRESSED로 직행 (`SKIPPED_EARLY_TREND_HANDOFF`)
6. `PROGRESSED_EXIT`: PROGRESSED 도달 후 청산 신호 발생
7. `NO_PROGRESSED_BEFORE_CUTOFF`: Cutoff까지 PROGRESSED에 도달하지 못함
8. `NO_EXIT_BEFORE_CUTOFF`: Cutoff까지 청산 신호가 발생하지 않음 (`OPEN_AT_CUTOFF`)

================================================================================
6. 청산 정책 정의 (Exit Policy 3 & Exit Policy 4)
================================================================================

#### 1) Exit Policy 3 (메인 구조적 청산)
- **활성화 조건**: Entry 이후 `EARLY_TREND → PROGRESSED` 전이가 실제로 완료된 거래만 활성화.
- **보유 규칙**: PROGRESSED 국면 유지 중에는 지속 HOLD.
- **청산 신호 (Trigger)**: 최초로 `PROGRESSED → OTHER_VALID_STAGE` 전이 발생 시.
  - 유효 구조 Stage: `WEAK`, `BASE`, `TRANSITION`, `EARLY_TREND`
  - (UNAVAILABLE은 시장 구조적 전환이 아니므로 데이터 이슈로 별도 기록)
- **체결**: 청산 신호 확인 다음 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN).

#### 2) Exit Policy 4 (조기 이익 보호 보조 청산, 15pt Drawdown)
- **활성화 조건**: `EARLY_TREND → PROGRESSED` 전이가 완료된 이후 활성화 (EARLY_TREND 시기 점수는 HWM 미포함).
- **HWM 관리**: PROGRESSED에 최초 진입한 월의 Pattern A Score를 `PROGRESSED_SCORE_HWM` 초기값으로 설정 후, PROGRESSED 유지 기간 동안 `HWM = max(HWM, current_score)` 갱신.
- **청산 신호 (Trigger)**: `PROGRESSED_SCORE_HWM - current_pattern_a_score >= 15.0`
- **고정 임계값**: 15.0점 고정 (결과 사후 파라미터 스윕 금지).
- **체결**: 청산 신호 확인 다음 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN).

#### 3) Primary Combined Policy (Policy B)
- `EARLY_TREND → PROGRESSED` 완료 후, **`FIRST(Exit 3, Exit 4)`** 먼저 발생하는 신호에 따라 다음 거래일 시가 청산.

================================================================================
7. 비교 실험군 정의 (Comparative Policy Variants)
================================================================================
동일한 진입 표본을 대상으로 아래 2가지 청산 정책을 독립 비교한다:
- **Policy A**: Exit 3 Only (구조적 국면 이탈 청산 단독)
- **Policy B**: Exit 3 + Exit 4 (15pt Score Drawdown 조기 이익 보호 결합)

================================================================================
8. 예외 및 Coverage Hole 처리 규칙
================================================================================
1. **`SKIPPED_EARLY_TREND_HANDOFF`**:
   - `TRANSITION → PROGRESSED`로 직행하고 `EARLY_TREND`를 건너뛴 거래는 임의로 청산 규칙을 덧붙이지 않고 coverage hole로 별도 분류 및 집계한다.
   - Cutoff까지 유지 시 `OPEN_AT_CUTOFF`로 처리하며, 해당 비율 자체를 주요 연구 결과로 보고한다.
2. **`OPEN_AT_CUTOFF`**:
   - 2026-08-14까지 청산 신호가 발생하지 않은 포지션은 실현 거래(Realized Trade)와 엄격히 분리하여 `mark_to_cutoff_return_pct`, `MFE`, `MAE`, `holding_weeks`를 별도 산출한다.

================================================================================
9. 평가 메트릭 정의 (Metrics Definition)
================================================================================
1. **Realized Return**: `(Exit Open Price - Entry Open Price) / Entry Open Price`
2. **MFE (Maximum Favorable Excursion)**: 진입 체결일부터 청산일(또는 Cutoff)까지 일봉 최고가 기준 최대 상승률 `(Max High - Entry Open) / Entry Open`
3. **MAE (Maximum Adverse Excursion)**: 진입 체결일부터 청산일(또는 Cutoff)까지 일봉 최저가 기준 최대 하락률 `(Min Low - Entry Open) / Entry Open` (음수 부호)
4. **Peak Giveback (Same-Trade)**: 실현 거래 내에서 동일하게 산출 `Peak Giveback = MFE Return - Realized Return`
5. **Profit Capture Ratio**: `MFE > 0`인 실현 거래에 대해 `Realized Return / MFE`
6. **Holding Duration**: 체결일부터 청산일까지의 거래일수(`holding_days`) 및 주수(`holding_weeks`)
7. **Entry Gate Cost Diagnostic**: FAST v0.1 단독 진입 수 vs Pattern A Gate 결합 진입 수, Gate Rejection 사유 분포 (`WEAK`, `BASE`, `PROGRESSED`, `UNAVAILABLE`)

================================================================================
10. 연구 한계 및 금지 사항 (No Tuning & Production Invariant)
================================================================================
1. **파라미터 튜닝 절대 금지**: 본 전종목 평가 결과를 확인한 후 Exit 4 임계값(15점), Entry 조건, FAST/Pattern A 규칙을 사후 수정하지 않는다.
2. **Production 불변**: 본 연구는 사후 기술 평가이며, 실전 운영 파이프라인(Candidate, Ranking, Stock Report)의 동작이나 코드를 변경하지 않는다.
3. **최종 결론 상태 제한**: 평가 결과에 따라 결론은 `PROMISING`, `MIXED`, `NOT_PROMISING`, `INSUFFICIENT_SAMPLE_SIZE` 중 하나로 기록하고 `PRODUCTION_HOLD`를 유지한다.
