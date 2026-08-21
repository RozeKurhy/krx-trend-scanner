# FAST + Pattern A WEAK Early Reversal Validation v0.2B 사전등록서

================================================================================
1. 연구 목적 및 핵심 연구 질문
================================================================================
- **연구명**: FAST + Pattern A WEAK Early Reversal Validation v0.2B Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_FAST_WEAK_EARLY_REVERSAL_VALIDATION` (사후 FAST WEAK 조기 반전 가설 검증)
- **사전등록 상태**: `PREREGISTERED_BEFORE_EVALUATION` (평가 실행 전 프로토콜 및 가설 확정)
- **Production 상태**: `PRODUCTION_HOLD` (운영 불변, 연구 전용)
- **Production 영향도**: `NONE` (Production Code/Signal/Ranking 일체 무영향)

> **[주의 및 연구 성격 명시]**:
> 본 연구는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스를 대상으로 FAST v0.1 Trigger 발생 시점에 Pattern A Stage가 WEAK(역배열)인 종목이 장기 구조 개선보다 앞서 조기 반전을 포착하는지 독립적으로 검증하는 **사후 거래 정책 평가(Retrospective Policy Evaluation)**입니다. 본 평가는 **Fresh OOS 또는 OOS Proof가 아니며**, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있음을 명시합니다.

#### 핵심 연구 질문
1. **Primary Question**:
   > "최초 FAST v0.1 Trigger가 발생했을 때 Pattern A == WEAK인 종목(FAST_WEAK)은 Pattern A == TRANSITION인 종목(FAST_TRANSITION)과 비교해 이후 중장기 상승 성과(4W, 8W, 12W, 26W Return / MFE / MAE)가 실제로 더 강한가?"
2. **Secondary Question**:
   > "FAST_WEAK 이후 실제 Pattern A 구조가 TRANSITION / EARLY_TREND / PROGRESSED 방향으로 개선되는 경우가 얼마나 자주 발생하며, 그 개선 이전에 FAST가 얼마나 먼저 선행 신호를 냈는가(Lead Time)?"

================================================================================
2. 데이터 소스 및 무결성 원칙 (LOCAL CACHE ONLY)
================================================================================
1. **로컬 캐시 전용**: 기존 로컬 Parquet 일봉 캐시(`data/raw/stocks/`) 데이터만 100% 사용한다.
2. **외부 네트워크 호출 일체 금지**: `pykrx`, `requests`, API 호출, 캐시 refresh, 누락 데이터 자동 다운로드를 일체 수행하지 않는다.
3. **Data Cutoff**: `2026-08-14` (절대적 상한 기준일, 미래 데이터 사용 금지).
4. **대상 모집단 (Population)**: 2026-08-14 기준 KRX KOSPI / KOSDAQ 보통주(COMMON) 중 Phase 10 투자 적격성 기준(시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원) 충족 종목.

================================================================================
3. 연구 설계 및 코호트 정의 (Primary Cohort Definition)
================================================================================
1. **Anchor Signal**:
   - 종목당 관찰 기간 내 발생한 **최초 FAST v0.1 Qualifying Signal 1개만**을 앵커로 사용한다.
   - FAST v0.1 조건: `TRIGGER` + `READY` + `PERMITTED_REGIME` + `NORMAL/ELEVATED` Risk + `READY/PARTIAL` Score.
   - 가상 체결(Hypothetical Execution): 신호 발생 주간 이후 **다음 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN)**.
2. **PRIMARY 비교 코호트 (최초 FAST 신호 시점의 latest completed monthly Pattern A Stage 기준)**:
   - **`FAST_WEAK`**: Pattern A == `WEAK`
   - **`FAST_TRANSITION`**: Pattern A == `TRANSITION`
3. **PRIMARY 제외 코호트 (별도 보존)**:
   - `UNAVAILABLE`, `BASE`, `EARLY_TREND`, `PROGRESSED`는 표본 특성 및 이력 문제 분리를 위해 PRIMARY WEAK vs TRANSITION 비교에서 제외하되 데이터셋에는 보존함.
4. **불변 원칙**:
   - 사후의 Pattern A Stage 변화나 Combined Entry 여부는 진입 시점 코호트 분류에 일체 사용하지 않는다.

================================================================================
4. 전방 성과 및 분포 진단 지표
================================================================================
최초 FAST hypothetical Entry Open 가격을 기준으로 동일하게 산출:
- **Horizons**: `4W`, `8W`, `12W`, `26W` (Completed Weekly Close Return, Daily MFE, Daily MAE)
- **분포 통계**: N (Completed / Censored), Positive Rate, P25, Median, Mean, P75, Min, Max
- **Winner Tail 진단**:
  - 26W Return ≥ +20%, ≥ +50%, ≥ +100% 비율
  - 26W MFE ≥ +30%, ≥ +50%, ≥ +100% 비율
- **Failure Tail 진단**:
  - 26W Return Negative Rate, Return ≤ -20%, Return ≤ -30% 비율
  - 26W MAE ≤ -20%, MAE ≤ -30% 비율

================================================================================
5. Secondary 사후 라이프사이클 및 선행성 진단 (Lifecycle Follow-through)
================================================================================
`FAST_WEAK` 진입 표본을 대상으로 진입 이후 completed monthly PIT Pattern A 변화를 추적:
1. `ever_transition`, `first_transition_date`, `days_to_transition` (FAST 진입일로부터의 일수)
2. `ever_early_trend`, `first_early_trend_date`, `days_to_early_trend`
3. `ever_progressed`, `first_progressed_date`, `days_to_progressed`
4. **Lead Time 통계**: 각 milestone에 도달한 표본의 선행 일수 분포(Median, Mean, P25, P75)
5. **통제 분석 (Descriptive Cross-tabs)**:
   - FAST Daily Risk Grade (NORMAL vs ELEVATED)
   - 시대별 (2016-2020, 2021-2023, 2024-2026)
   - 시장별 (KOSPI vs KOSDAQ)

================================================================================
6. 연구 한계 및 불변 사항 (No Tuning & Production Invariant)
================================================================================
1. **청산 정책 배제**: Entry 신호의 고유 전방 잠재력을 평가하기 위해 Exit 정책을 개입시키지 않는다.
2. **사후 파라미터 튜닝 및 정책 변경 금지**: 본 결과를 바탕으로 WEAK을 허용하거나 임계값을 탐색하지 않는다.
3. **Production 영향 없음**: 연구 전용(`PRODUCTION_HOLD`)이며 운영 코드를 변경하지 않는다.
4. **최종 결론 상태**: `FAST_WEAK_EARLY_REVERSAL_SUPPORTED`, `FAST_WEAK_EARLY_REVERSAL_MIXED`, `FAST_WEAK_EARLY_REVERSAL_NOT_SUPPORTED`, `INSUFFICIENT_SAMPLE_SIZE` 중 하나로 객관 기록한다.
