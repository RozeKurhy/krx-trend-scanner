# FAST + Pattern A UNAVAILABLE Decomposition Validation v0.2C 사전등록서

================================================================================
1. 연구 목적 및 핵심 연구 질문
================================================================================
- **연구명**: FAST + Pattern A UNAVAILABLE Decomposition Validation v0.2C Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_FAST_UNAVAILABLE_DECOMPOSITION_VALIDATION`
- **연구 성격 명시**: `SAME_SAMPLE_RETROSPECTIVE_FOLLOWUP_CHARACTERIZATION` (v0.2A 동일 표본 후속 특성 분석, 독립 재현 검증 아님)
- **사전등록 상태**: `PREREGISTERED_BEFORE_EVALUATION` (평가 실행 전 프로토콜 및 가설 확정)
- **Production 상태**: `PRODUCTION_HOLD` (운영 불변, 연구 전용)
- **Production 영향도**: `NONE` (Production Code/Signal/Ranking 일체 무영향)

> **[주의 및 연구 성격 명시]**:
> 본 연구는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스를 대상으로 FAST 최초 신호 시점에 Pattern A가 `UNAVAILABLE`로 분류되었던 473건(Gate Reject 631건의 약 75%)의 원인을 분해하고 전방 성과 및 사후 유효 국면 전이를 분석하는 **사후 거래 정책 분석(Retrospective Policy Characterization)**입니다. 본 평가는 **Fresh OOS 또는 독립 재현 검증(Independent Replication)이 아니며**, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있음을 명시합니다.

#### 핵심 연구 질문
1. **Primary Question 1 (Reason Decomposition)**:
   > "최초 FAST v0.1 Trigger 발생 시점에 Pattern A == UNAVAILABLE이었던 신호들은 왜 UNAVAILABLE이었는가? (장기 월봉 이력 부족 vs 피처 결측 vs 평가 예외)"
2. **Primary Question 2 (Forward Outcomes vs Comparators)**:
   > "FAST_UNAVAILABLE의 전방 성과(4W, 8W, 12W, 26W Return / MFE / MAE)는 FAST_TRANSITION 및 FAST_WEAK과 비교해 어떠한가? (구조적 약세 신호인가, 단순 정보 미비 신호인가?)"
3. **Primary Question 3 (First Valid Stage Transition & Lead Time)**:
   > "UNAVAILABLE이었던 종목들이 사후에 Pattern A Stage 계산이 가능해졌을 때 어떤 Stage(WEAK, BASE, TRANSITION, EARLY_TREND, PROGRESSED)로 처음 진입하며, FAST 신호 발생 시점으로부터 얼마나 선행하였는가?"

================================================================================
2. 데이터 소스 및 무결성 원칙 (LOCAL CACHE ONLY)
================================================================================
1. **로컬 캐시 전용**: 기존 로컬 Parquet 일봉 캐시(`data/raw/stocks/`) 데이터만 100% 사용한다.
2. **외부 네트워크 호출 일체 금지**: `pykrx`, `requests`, API 호출, 캐시 refresh, 누락 데이터 자동 다운로드를 일체 수행하지 않는다.
3. **Data Cutoff**: `2026-08-14` (절대적 상한 기준일, 미래 데이터 사용 금지).
4. **대상 모집단 (Population)**: 2026-08-14 기준 KRX KOSPI / KOSDAQ 보통주(COMMON) 중 Phase 10 투자 적격성 기준(시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원) 충족 종목.

================================================================================
3. 연구 설계 및 사전등록 원인 분류 체계 (Reason Taxonomy)
================================================================================
1. **Anchor Signal**:
   - 종목당 관찰 기간 내 발생한 **최초 FAST v0.1 Qualifying Signal 1개만**을 앵커로 사용한다.
   - 가상 체결(Hypothetical Execution): 신호 발생 주간 이후 **다음 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN)**.
2. **UNAVAILABLE Primary Reason Taxonomy (상호 배타적 단일 주원인)**:
   - **`INSUFFICIENT_PATTERN_A_HISTORY`**: Pattern A 공식 계산에 요구되는 최소 장기 월봉 이력(36개월 미만, `available_monthly_bars < 36`)으로 인해 장기 지표(`range_position`, `ma24_slope` 등) 산출 불가.
   - **`PATTERN_A_FEATURE_UNAVAILABLE`**: 월봉 이력(≥ 36개월)은 존재하나 필수 피처 중 일부가 결측되어 `insufficient_data` 반환.
   - **`PATTERN_A_EVALUATION_EXCEPTION`**: 평가 모듈 실행 중 예외(Exception) 발생.
   - **`PATTERN_A_STAGE_MISSING`**: 피처는 정상 계산되었으나 규칙 매칭 실패로 stage=None 반환.
   - **`OTHER_UNAVAILABLE`**: 기타 미분류 원인.
3. **이력 길이 고정 진단 구간 (Available History Length Buckets)**:
   - `< 12 months`
   - `12 to < 24 months`
   - `24 to < 36 months`
   - `>= 36 months`

================================================================================
4. 전방 성과 및 사후 라이프사이클 추적 지표
================================================================================
1. **전방 성과 지표 (동일 FAST Next Day Open 체결 기준)**:
   - **Horizons**: `4W`, `8W`, `12W`, `26W` (Completed Weekly Close Return, Daily MFE, Daily MAE)
   - **분포 통계**: N (Completed / Censored), Positive Rate, P25, Median, Mean, P75
   - **Winner Tail**: 26W Return ≥ +20%, ≥ +50%, ≥ +100% / MFE ≥ +30%, ≥ +50%, ≥ +100%
   - **Failure Tail**: 26W Return < 0, Return ≤ -20%, Return ≤ -30% / MAE ≤ -20%, MAE ≤ -30%
2. **First Valid Pattern A Stage 추적 (사후 completed monthly PIT)**:
   - `first_valid_pa_stage_date`, `first_valid_pa_stage` (WEAK, BASE, TRANSITION, EARLY_TREND, PROGRESSED, NEVER_AVAILABLE)
   - `days_to_first_valid_pa_stage` (FAST 신호일로부터의 경과 일수 및 Lead Time 통계)
3. **사후 라이프사이클 전이 (Post-entry Lifecycle Milestones)**:
   - `ever_weak`, `ever_base`, `ever_transition`, `ever_early_trend`, `ever_progressed` 및 최초 도달 일자/경과 일수.
4. **통제 분석**:
   - Daily Risk Grade (NORMAL vs ELEVATED)
   - Era (2016-2020, 2021-2023, 2024-2026)
   - Market (KOSPI vs KOSDAQ)
   - FAST Score 분포 (Median, P25, P75)

================================================================================
5. 결론 판정 원칙 (Decision Evaluation Rules)
================================================================================
임의의 숫자 튜닝이나 단일 지표에 의한 기계적 판정을 금지하고, 전체 정량 결과와 원인 분해를 종합하여 아래 4개 상태 중 하나로 평가한다:
- **`FAST_UNAVAILABLE_RISK_SUPPORTED`**: UNAVAILABLE이 주요 원인 전반에서 뚜렷하게 낮은 성과 또는 심각한 하방 실패 테일을 나타내어 현행 Reject 정책에 명확한 위험 차단 근거가 있는 경우.
- **`FAST_UNAVAILABLE_MIXED`**: 원인별/구간별 성과 편차가 크고 일관된 결론을 내리기 어려운 경우.
- **`FAST_UNAVAILABLE_NOT_STRUCTURAL_REJECT`**: UNAVAILABLE의 절대다수가 단순 이력 부족(Information Insufficiency)에 기인하고, 전방 성과 및 사후 유효 국면 전이가 구조적 약세(Structural Bearish Reject)와 명확히 구분되는 경우.
- **`INSUFFICIENT_SAMPLE_SIZE`**: 표본수가 부족한 경우.

================================================================================
6. 연구 한계 및 불변 사항 (No Tuning & Production Invariant)
================================================================================
1. **운영 정책 변경 일체 없음**: 본 연구는 UNAVAILABLE을 실전 Entry로 허용하거나 게이트를 수정하지 않는다 (`PRODUCTION_HOLD`).
2. **사후 파라미터 튜닝 금지**: 결과를 확인한 후 원인 분류 기준이나 이력 버킷을 재조정하지 않는다.
3. **용어 사용 제한**: "인과적 증명", "입증(Proof)", "Production Ready" 등의 단정적 표현을 금지하고 "관찰(Observed)", "특성 분석(Characterization)"으로 서술한다.
