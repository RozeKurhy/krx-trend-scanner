# Pattern A Entry Gate Incremental Value v0.2A 사전등록서

================================================================================
1. 연구 목적 및 핵심 연구 질문
================================================================================
- **연구명**: Pattern A Entry Gate Incremental Value v0.2A Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_ENTRY_GATE_INCREMENTAL_VALUE_EVALUATION` (사후 진입 게이트 증분 가치 평가)
- **사전등록 상태**: `PREREGISTERED_BEFORE_EVALUATION` (평가 실행 전 프로토콜 및 가설 확정)
- **Production 상태**: `PRODUCTION_HOLD` (운영 불변, 연구 전용)
- **Production 영향도**: `NONE` (Production Code/Signal/Ranking 일체 무영향)

> **[주의 및 연구 성격 명시]**:
> 본 연구는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스를 대상으로 FAST v0.1 진입 신호 시점에 결합된 Pattern A Stage Gate의 증분 가치(Incremental Value)를 사후적으로 검증하는 **사후 거래 정책 평가(Retrospective Policy Evaluation)**입니다. 본 평가는 **Fresh OOS 또는 OOS Proof가 아니며**, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있음을 명시합니다.

#### 핵심 연구 질문
1. **Primary Question**:
   > "동일한 최초 FAST v0.1 신호 시점에서 Pattern A Stage가 TRANSITION / EARLY_TREND인 종목(Gate Pass)은 Gate Reject 종목보다 이후 성과(4W, 8W, 12W, 26W Return / MFE / MAE)가 실제로 더 좋은가?"
2. **Secondary Question**:
   > "최초 FAST 신호에서는 Gate를 통과하지 못했지만 나중에 Combined Entry 조건을 만족한 종목에서, Pattern A Gate 때문에 대기한 기간은 실제로 손실을 회피한 것인가, 아니면 상승 초입의 기회를 상실한 것인가?"

================================================================================
2. 데이터 소스 및 무결성 원칙 (LOCAL CACHE ONLY)
================================================================================
1. **로컬 캐시 전용**: 기존 로컬 Parquet 일봉 캐시(`data/raw/stocks/`) 데이터만 100% 사용한다.
2. **외부 네트워크 호출 일체 금지**: `pykrx`, `requests`, API 호출, 캐시 refresh, 누락 데이터 자동 다운로드를 일체 수행하지 않는다.
3. **Data Cutoff**: `2026-08-14` (절대적 상한 기준일, 미래 데이터 사용 금지).
4. **대상 모집단 (Population)**: 2026-08-14 기준 KRX KOSPI / KOSDAQ 보통주(COMMON) 중 Phase 10 투자 적격성(Investability) 기준을 충족하는 종목
   - 시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원

================================================================================
3. 연구 설계 및 Anchor Signal 정의 (Primary Evaluation)
================================================================================
1. **Anchor Signal**:
   - 종목당 관찰 기간 내 발생한 **최초 FAST v0.1 Qualifying Signal 1개만**을 앵커로 사용한다.
   - FAST v0.1 조건: `TRIGGER` + `READY` + `PERMITTED_REGIME` + `NORMAL/ELEVATED` Risk + `READY/PARTIAL` Score.
   - 가상 체결(Hypothetical Execution): 신호 발생 주간 이후 **다음 로컬 거래일 시가 (NEXT LOCAL TRADING DAY OPEN)**.
2. **Gate Cohort 분류 (최초 FAST 신호 시점 기준)**:
   - FAST 신호 시점에 이용 가능한 latest completed monthly Pattern A Stage를 기준으로 분류:
   - **`GATE_PASS_ALL`**:
     - `PASS_TRANSITION` (Pattern A == TRANSITION)
     - `PASS_EARLY_TREND` (Pattern A == EARLY_TREND)
   - **`GATE_REJECT_ALL`**:
     - `REJECT_WEAK` (Pattern A == WEAK)
     - `REJECT_BASE` (Pattern A == BASE)
     - `REJECT_PROGRESSED` (Pattern A == PROGRESSED)
     - `REJECT_UNAVAILABLE` (Pattern A == UNAVAILABLE)
3. **불변 원칙**:
   - 나중에 Combined Entry가 발생하더라도 최초 FAST 신호 시점의 분류(Reject)를 소급하여 변경하지 않는다.

================================================================================
4. 전방 성과 측정 지표 (Forward Horizon Metrics)
================================================================================
최초 FAST hypothetical Entry Open 가격을 기준으로 동일하게 산출:
- **Horizons**: `4W`, `8W`, `12W`, `26W`
- **Forward Return**: 해당 horizon의 completed weekly close 기준 총수익률 `(Close - Entry Open) / Entry Open`
- **MFE (Maximum Favorable Excursion)**: Entry Open 이후 해당 horizon까지의 daily high 기준 최대 상승률
- **MAE (Maximum Adverse Excursion)**: Entry Open 이후 해당 horizon까지의 daily low 기준 최대 하락률
- **Censoring**: horizon 완료일이 2026-08-14 Cutoff를 초과하면 `CENSORED` 처리

================================================================================
5. Secondary 대기 비용 및 편익 진단 (Gate Waiting Diagnostic)
================================================================================
최초 FAST 신호에서 Reject되었으나 이후 Combined Entry 조건을 만족한 종목 대상:
1. `waiting_period_return_pct`: `(LATER_COMBINED_OPEN - FAST_FIRST_OPEN) / FAST_FIRST_OPEN`
2. `waiting_mfe_pct` & `waiting_mae_pct`: 최초 FAST Entry Open부터 Later Combined Entry Open 직전까지의 최대 상승/하락폭
3. `combined_entry_delay_days`: 최초 FAST 신호일과 Later Combined 신호일 사이의 일수
4. `REJECT_NEVER_LATER_QUALIFIED`: Cutoff까지 끝내 Combined Entry를 만족하지 못하고 영구 차단된 신호의 4W~26W 성과 추적

================================================================================
6. 연구 한계 및 불변 사항 (No Tuning & Production Invariant)
================================================================================
1. **청산 정책 배제**: 본 연구는 Entry Gate의 고유 변별력(Discrimination)을 검증하기 위한 연구이며, Exit 3/4 등 청산 정책을 성과 평가에 적용하지 않는다.
2. **사후 파라미터 튜닝 금지**: 본 결과를 본 뒤 Gate 임계값이나 Stage 조합을 사후 최적화하지 않는다.
3. **Production 영향 없음**: 본 연구는 연구 전용(`PRODUCTION_HOLD`)이며 운영 파이프라인(Production FAST/Pattern A)을 변경하지 않는다.
4. **최종 결론 상태**: 결과에 따라 `GATE_VALUE_SUPPORTED`, `GATE_VALUE_MIXED`, `GATE_VALUE_NOT_SUPPORTED`, `INSUFFICIENT_SAMPLE_SIZE` 중 하나로 객관 기록한다.
