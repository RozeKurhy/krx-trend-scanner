# [ACE MSCI인도네시아(합성) (256440)] 종목 리포트 v0.6

- **시장 구분 (Listing Market)**: `KOSPI`
- **자산 유형 (Asset Type)**: `ETF`
- **분석 기준일 (Requested As-Of)**: `2026-09-25`
- **신선도 기준일 (Reference Market Date)**: `2026-09-23`
- **리포트 상태**: `PARTIAL`

---

## 0. 핵심 요약 (Executive Summary)
> **ACE MSCI인도네시아(합성)(256440)의 공식 ETF36 Julia V1 리포트야. 분석 기준일 2026-09-25, 실제 시장 데이터 기준일 2026-09-23야.**
>
> - Julia V1: HOLD_PRE_PROGRESSED
> - ETF 적격성: PASS · raw 종가 4915.0원 · 20D 평균 거래량 37467.1주
> - 펀더멘털: NOT_APPLICABLE (일반기업 Fundamentals V1 적용 대상 아님)
> - 현재 Pattern A Score는 0.00점(Stage: WEAK, Candidate: NO)입니다.
> - 외국인 수급: 외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다.
> - 시장 상대강도: Phase12 Market RS는 KOSPI/KOSDAQ 보통주(COMMON)를 대상으로 정의되어 이 종목에는 적용되지 않습니다.
> - 업종 상대강도: Sector RS는 KOSPI/KOSDAQ COMMON 종목을 대상으로 하므로 이 종목에는 적용되지 않습니다.
> - 거래대금 추세: 최근 거래대금이 특정 방향성 없이 기간별로 혼조세를 나타내고 있습니다. (5일: 2.43억원, 20일: 1.92억원, 60일: 3.37억원)

ACE MSCI인도네시아(합성)은(는) 기준일 2026-09-23에 Julia V1 상태 HOLD_PRE_PROGRESSED야. ETF PIT 적격성은 PASS이며 시가총액과 Phase10 Investability는 이 ETF 전략의 적격성 기준이 아니야. 공통 기술·수급 섹션은 기존 Stock Report 계산을 재사용했어.

---

## 1. 현재 기술적 국면 및 ETF 적격성 스냅샷
- **Pattern A Score / 국면**: `0.0` / `WEAK`
- **Official ETF36 membership**: `PASS`
- **상장일 / 상장 2년 요건**: `2016-11-01` / `PASS`
- **기준일 raw 종가**: `4915.0원` (최소 1,000원: `PASS`)
- **20 KRX 거래일 평균 raw 거래량**: `37467.1주` (최소 10,000주: `PASS`)
- **20일 창**: `2026-08-27` ~ `2026-09-23`; 신호일 포함: `True`
- **ETF 적격성**: `PASS` (`ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`)
- **Strategy-ready / clean-ready / 유효 시작일**: `2019-11-01 / 2019-11-01 / 2019-11-01`
- **시가총액 / Phase10 Investability**: `NOT_APPLICABLE` (Julia V1 ETF 적격성 조건이 아님)

---
## 1.5. 펀더멘털 (Fundamentals)
- **적용성 (Applicability)**: `NOT_APPLICABLE`
- **데이터 상태 (Data Status)**: `NOT_APPLICABLE`
- **사유 (Reason)**: `ASSET_TYPE_NOT_APPLICABLE`
- **기준일 (Requested As-Of)**: `2026-09-25`
- **회사 분류 (Company Family)**: `N/A`
- **Fundamentals Filter**: `NOT_APPLICABLE`
- **Filter Passed**: `NO`
- **Filter Reasons**: `N/A`

### 요약 (Summary)
| 항목 | 값 |
|---|---:|
| 최신 FY / 최신 분기 | `N/A` / `N/A` |
| 최신 FY 매출 | N/A |
| 최근 4분기 평균 매출 | N/A |
| TTM 매출 | N/A |
| TTM 영업이익 | N/A |
| TTM 순이익 | N/A |
| TTM 영업현금흐름 | N/A |
| TTM 영업이익률 / 순이익률 / OCF 마진 | N/A / N/A / N/A |
| TTM ROE / 최신 부채비율 | N/A / N/A |

### 최근 12개 분기 (Latest 12 Quarters)
| 분기 | 상태 | 매출 | 매출 YoY | 영업이익 | 영업이익 YoY | 영업이익률 | 순이익 | 순이익률 | OCF |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|

### 최근 5개년 (Latest 5 Fiscal Years)
| FY | 상태 | 매출 | 매출 YoY | 영업이익 | 영업이익 YoY | 영업이익률 | 순이익 | 순이익률 | ROE | 부채비율 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|

---

## 2. Julia V1 전략 상태
- **전략 ID**: `JULIA_ETF_STRATEGY_V01`
- **전략 상태**: `HOLD_PRE_PROGRESSED`
- **전략 포지션**: `OPEN`
- **현재 행동**: `HOLD`
- **행동 사유**: `OPEN_POSITION_PRE_PROGRESSED`
- **실행 시점**: `해당 없음`
- **해석**: Julia V1 포지션을 PROGRESSED 이전 구간에서 보유 중이야. Pre-PROGRESSED Loss Guard는 비활성이야.

### ETF 진입 조건 체크리스트
| 진입 검증 항목 | 기준일 관측값 | 충족 여부 |
|---|---|:---:|
| Official ETF36 | `True` | `PASS` |
| 상장 2년 이상 | `2016-11-01` | `PASS` |
| raw 종가 ≥ 1,000원 | `5115.0` | `PASS` |
| 20 KRX 거래일 평균 raw 거래량 ≥ 10,000주 | `29984.05` | `PASS` |
| Strategy-ready / clean-ready | `2019-11-01 / 2019-11-01` | `PASS` |
| Pattern A 국면 | `WEAK` | `FAIL` |
| FAST 주별 트리거 | `WATCH (READY)` | `FAIL` |
| 월간 국면 | `EARLY_REGIME` | `FAIL` |
| 일봉 리스크 | `NORMAL` | `PASS` |
| FAST 점수 | `READY` | `PASS` |
| 미보유 상태 | `OPEN` | `FAIL` |
| 다음 실제 KRX 거래일 raw 시가 | `2026-09-21 / 5110.0` | `PASS` |

- **신규 진입 조건 전체 판정**: `FAIL`
- **미충족 조건**: `PATTERN_A_TRANSITION_OR_EARLY_TREND, FAST_TRIGGER_READY, MONTHLY_REGIME_PERMITTED, NO_OPEN_POSITION, SIGNAL_DATE_IS_CURRENT_REFERENCE`

### 현재 포지션
- **거래 ID / 순번**: `256440_01` / `1`
- **진입 신호일 / 체결일**: `2021-10-08` / `2021-10-12`
- **진입 시가 / 기준일 종가**: `9375.0` / `4915.0원`
- **수익률**: `-47.57%`
- **Lifecycle**: `NEVER_PROGRESSED`
- **청산 신호**: `NO_PROGRESSED_BEFORE_CUTOFF` / `없음`

### 보호 및 재진입
- **Pre-PROGRESSED Loss Guard**: `DISABLED`
- **보호 상태**: `{'phase': 'PRE_PROGRESSED', 'loss_guard_state': 'DISABLED', 'loss_guard_threshold_pct': None, 'first_progressed_date': None, 'lifecycle_class': 'NEVER_PROGRESSED', 'exit3_state': 'MONITORING', 'exit4_state': 'MONITORING'}`
- **재진입 상태**: `{'enabled': True, 'cooldown': 'NONE', 'maximum_reentries': 'NONE', 'completed_trade_count': 0, 'current_trade_sequence': 1, 'next_entry_sequence': 2}`

### Julia V1 전략 거래 이력
| 순번 | 진입 신호일 | 진입 체결일 | 진입 시가 | 청산 유형 | 청산 체결일 | 청산 시가 | 수익률 | 상태 |
|:---:|:---:|:---:|---:|---|:---:|---:|---:|:---:|
| 1 | `2021-10-08` | `2021-10-12` | 9,375원 | `NO_PROGRESSED_BEFORE_CUTOFF` | `-` | - | -47.57% | `OPEN_AT_CUTOFF` |

> V00 lifecycle evaluator를 그대로 사용했고, V1 정책에서 Pre-PROGRESSED Loss Guard를 비활성화했어. 과거 거래는 미래 수익을 보장하지 않아.

---
## 3. Pattern A FAST 현재 신호 (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **기준 주 (As-Of)**: `2026-09-18`
- **FAST Score**: `36.77`
- **Score Availability**: `READY`
- **FAST Stage**: `WATCH`
- **Stage Availability**: `READY`
- **Monthly Regime**: `EARLY_REGIME`
- **Daily Risk**: `NORMAL`
- **해석**: FAST 기준 명확한 초기 상승 전환 구조가 아직 확인되지 않았습니다.

> Pattern A FAST는 Pattern A와 독립적인 실험적(Experimental) 조기 신호이며, Pattern A Score/Stage/Candidate/Production Ranking에 영향을 주지 않습니다. 두 모델의 Score를 합산하거나 상대 우열을 계산하지 않습니다.

---

## 4. Pattern A Monthly History — 최근 12개월 월별 추이 (Recent 12M Trajectory)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available |
|---|---:|---:|---|---|---|
| 2025-08-29 | 8,425 | 33.65 | BASE | watch | True |
| 2025-09-30 | 8,270 | 34.47 | BASE | watch | True |
| 2025-10-31 | 8,630 | 40.74 | BASE | watch | True |
| 2025-11-28 | 9,045 | 47.54 | BASE | watch | True |
| 2025-12-30 | 8,570 | 49.40 | BASE | watch | True |
| 2026-01-30 | 8,125 | 42.78 | BASE | watch | True |
| 2026-02-27 | 8,150 | 32.78 | BASE | watch | True |
| 2026-03-31 | 7,285 | 22.54 | WEAK | blocked | True |
| 2026-04-30 | 6,490 | 11.62 | WEAK | blocked | True |
| 2026-05-29 | 5,880 | 3.20 | WEAK | blocked | True |
| 2026-06-30 | 5,270 | 0.00 | WEAK | blocked | True |
| 2026-07-31 | 5,335 | 0.00 | WEAK | blocked | True |
| 2026-08-31 | 5,345 | 0.00 | WEAK | blocked | True |

- **점수 변화 모멘텀**: 1M (+0.00), 3M (-3.20), 6M (-32.78), 12M (-33.65)

---

## 5. Pattern A 국면 전환 이력 (Stage Transition History)
- **2019-10-31**: `UNAVAILABLE` -> `BASE`
- **2019-12-30**: `BASE` -> `TRANSITION`
- **2020-01-31**: `TRANSITION` -> `BASE`
- **2020-03-31**: `BASE` -> `WEAK`
- **2020-04-29**: `WEAK` -> `BASE`
- **2020-06-30**: `BASE` -> `TRANSITION`
- **2020-09-29**: `TRANSITION` -> `BASE`
- **2020-10-30**: `BASE` -> `WEAK`
- **2021-04-30**: `WEAK` -> `BASE`
- **2021-10-29**: `BASE` -> `TRANSITION`
- **2021-12-30**: `TRANSITION` -> `BASE`
- **2022-03-31**: `BASE` -> `EARLY_TREND`
- **2022-05-31**: `EARLY_TREND` -> `TRANSITION`
- **2022-09-30**: `TRANSITION` -> `EARLY_TREND`
- **2022-11-30**: `EARLY_TREND` -> `TRANSITION`
- **2023-04-28**: `TRANSITION` -> `EARLY_TREND`
- **2023-05-31**: `EARLY_TREND` -> `TRANSITION`
- **2024-05-31**: `TRANSITION` -> `BASE`
- **2024-09-30**: `BASE` -> `TRANSITION`
- **2024-10-31**: `TRANSITION` -> `BASE`
- **2025-02-28**: `BASE` -> `WEAK`
- **2025-04-30**: `WEAK` -> `BASE`
- **2025-06-30**: `BASE` -> `WEAK`
- **2025-07-31**: `WEAK` -> `BASE`
- **2026-03-31**: `BASE` -> `WEAK`

---

## 6. Pattern A FAST Weekly History (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **History 시작 주**: `2025-09-26`
- **History 종료 주**: `2026-09-18`
- **총 주별 관측 개수**: `49주`

| 기준 주 (Week Ending) | 종가 | FAST Score | Score Availability | FAST Stage | Stage Availability | Monthly Regime | Daily Risk |
|---|---:|---:|---|---|---|---|---|
| 2025-09-26 | 8,265 | 51.30 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2025-10-10 | 8,325 | 50.25 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2025-10-17 | 8,185 | 44.12 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2025-10-24 | 8,820 | 50.25 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2025-10-31 | 8,630 | 64.25 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-11-07 | 8,970 | 64.25 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-11-14 | 8,795 | 64.25 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-11-21 | 9,020 | 71.60 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2025-11-28 | 9,045 | 71.60 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-05 | 9,070 | 71.60 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-12 | 8,940 | 65.30 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-19 | 9,045 | 71.60 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-26 | 8,695 | 65.30 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-02 | 8,605 | 65.30 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-09 | 8,845 | 65.30 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-16 | 8,945 | 65.30 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-23 | 8,720 | 65.30 | READY | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-30 | 8,125 | 47.36 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-02-06 | 8,275 | 47.36 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-02-13 | 8,285 | 47.36 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-02-20 | 8,215 | 47.36 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-02-27 | 8,150 | 46.38 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-03-06 | 7,700 | 46.38 | READY | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-03-13 | 7,455 | 46.38 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-03-20 | 7,325 | 41.12 | READY | WATCH | READY | EARLY_REGIME | ELEVATED |
| 2026-03-27 | 7,340 | 46.38 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-04-03 | 7,155 | 39.92 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-04-10 | 7,275 | 39.92 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-04-17 | 7,430 | 39.92 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-04-24 | 6,850 | 32.58 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-05-08 | 6,750 | 32.58 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-05-15 | 6,320 | 32.58 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-05-22 | 5,855 | 32.58 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-05-29 | 5,880 | 32.58 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-06-05 | 5,290 | 26.01 | READY | WATCH | READY | EARLY_REGIME | ELEVATED |
| 2026-06-12 | 5,725 | 31.26 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-06-19 | 5,730 | 31.26 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-06-26 | 5,385 | 31.26 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-07-03 | 5,465 | 31.26 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-07-10 | 5,395 | 31.26 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-07-24 | 5,465 | 32.58 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-07-31 | 5,335 | 31.26 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-08-07 | 5,485 | 36.77 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-08-14 | 5,355 | 36.77 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-08-21 | 5,355 | 36.77 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-08-28 | 5,355 | 36.77 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-09-04 | 5,240 | 36.77 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-09-11 | 5,040 | 36.77 | READY | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-09-18 | 5,115 | 36.77 | READY | WATCH | READY | EARLY_REGIME | NORMAL |

> Pattern A와 동일 timeline 표로 합치지 않습니다. Pattern A는 월 단위, Pattern A FAST는 주 단위가 각 모델의 핵심 시간축입니다. FAST Score가 `N/A`(UNAVAILABLE)인 경우 `0`이 아니라 데이터 부족을 의미합니다.

---

## 7. 외국인 수급 확증 (Foreign Flow Analysis - Phase 11)
- **수급 데이터 상태**: `DATA_UNAVAILABLE`
- **수급 국면 판정**: `FLOW_UNAVAILABLE`
- **규칙 기반 해석**: 외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다.


---

## 7.5. 시장 상대강도 (RS)
- **적용 상태**: `NOT_APPLICABLE`
- **데이터 상태**: `NOT_EVALUATED`
- **해석**: Phase12 Market RS는 KOSPI/KOSDAQ 보통주(COMMON)를 대상으로 정의되어 이 종목에는 적용되지 않습니다.

---

## 7.6. 업종 상대강도 (Sector RS)
- **적용 상태**: `NOT_APPLICABLE`
- **데이터 상태**: `NOT_EVALUATED`
- **규칙 기반 해석**: Sector RS는 KOSPI/KOSDAQ COMMON 종목을 대상으로 하므로 이 종목에는 적용되지 않습니다.

---

## 8. 거래대금 추세 분석 (Trading Value Flow)
- **거래대금 상태**: `TRADING_VALUE_MIXED`
- **규칙 기반 해석**: 최근 거래대금이 특정 방향성 없이 기간별로 혼조세를 나타내고 있습니다. (5일: 2.43억원, 20일: 1.92억원, 60일: 3.37억원)
| 구간 | 평균 거래대금 |
|---|---:|
| 1D | 3.07억원 |
| 5D | 2.43억원 |
| 10D | 1.90억원 |
| 20D | 1.92억원 |
| 60D | 3.37억원 |
- **20일 평균 거래대금**: `1.92억원`
- **60일 평균 거래대금**: `3.37억원`
- **단기 확장 비율 (5D / 20D)**: `1.26배`
- **중기 확장 비율 (20D / 60D)**: `0.57배`

---

## 9. Pattern A 전체 월별 이력 (Full Monthly History)
- **전체 관측 시작월**: `2016-11-30`
- **전체 관측 종료월**: `2026-08-31`
- **최초 Pattern A 산출월**: `2019-10-31`
- **총 월별 관측 개수**: `118개월` (Pattern A 산출 가능: `83개월`)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available | Reason |
|---|---:|---:|---|---|---|---|
| 2016-11-30 | 9,040 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-12-29 | 9,580 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-01-31 | 9,405 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-02-28 | 9,335 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-03-31 | 9,605 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-04-28 | 10,005 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-05-31 | 9,970 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-06-30 | 10,450 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-07-31 | 10,210 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-08-31 | 10,260 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-09-29 | 10,300 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-10-31 | 10,125 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-11-30 | 9,925 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-12-28 | 10,265 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-01-31 | 10,715 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-02-28 | 10,585 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-03-30 | 9,560 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-04-30 | 9,050 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-05-31 | 8,980 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-06-29 | 8,415 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-07-31 | 8,820 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-08-31 | 8,720 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-09-28 | 8,630 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-10-31 | 8,425 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-11-30 | 9,560 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-12-28 | 9,385 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-01-31 | 10,200 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-02-28 | 9,960 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-03-29 | 9,960 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-04-30 | 10,320 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-05-31 | 9,950 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-06-28 | 10,285 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-07-31 | 10,595 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-08-30 | 10,425 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-09-30 | 10,115 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-10-31 | 10,130 | 66.61 | BASE | watch | True | - |
| 2019-11-29 | 9,940 | 66.03 | BASE | watch | True | - |
| 2019-12-30 | 10,410 | 67.20 | TRANSITION | candidate | True | - |
| 2020-01-31 | 10,475 | 66.18 | BASE | watch | True | - |
| 2020-02-28 | 8,915 | 59.47 | BASE | watch | True | - |
| 2020-03-31 | 6,450 | 44.32 | WEAK | blocked | True | - |
| 2020-04-29 | 6,750 | 32.76 | BASE | watch | True | - |
| 2020-05-29 | 7,555 | 33.88 | BASE | watch | True | - |
| 2020-06-30 | 7,895 | 47.39 | TRANSITION | candidate | True | - |
| 2020-07-31 | 8,095 | 54.40 | TRANSITION | candidate | True | - |
| 2020-08-31 | 8,420 | 59.23 | TRANSITION | candidate | True | - |
| 2020-09-29 | 7,325 | 55.78 | BASE | watch | True | - |
| 2020-10-30 | 7,290 | 54.02 | WEAK | blocked | True | - |
| 2020-11-30 | 8,540 | 50.96 | WEAK | blocked | True | - |
| 2020-12-30 | 8,710 | 54.03 | WEAK | blocked | True | - |
| 2021-01-29 | 8,570 | 51.48 | WEAK | blocked | True | - |
| 2021-02-26 | 8,685 | 50.15 | WEAK | blocked | True | - |
| 2021-03-31 | 8,230 | 44.63 | WEAK | blocked | True | - |
| 2021-04-30 | 8,075 | 41.00 | BASE | watch | True | - |
| 2021-05-31 | 8,120 | 37.49 | BASE | watch | True | - |
| 2021-06-30 | 7,755 | 32.11 | BASE | watch | True | - |
| 2021-07-30 | 7,800 | 27.89 | BASE | watch | True | - |
| 2021-08-31 | 8,220 | 24.76 | BASE | watch | True | - |
| 2021-09-30 | 8,485 | 30.54 | BASE | watch | True | - |
| 2021-10-29 | 9,295 | 42.69 | TRANSITION | candidate | True | - |
| 2021-11-30 | 9,270 | 51.23 | TRANSITION | candidate | True | - |
| 2021-12-30 | 9,235 | 53.55 | BASE | watch | True | - |
| 2022-01-28 | 9,430 | 52.36 | BASE | watch | True | - |
| 2022-02-28 | 9,700 | 59.79 | BASE | watch | True | - |
| 2022-03-31 | 10,265 | 89.74 | EARLY_TREND | candidate | True | - |
| 2022-04-29 | 11,105 | 100.00 | EARLY_TREND | candidate | True | - |
| 2022-05-31 | 10,130 | 100.00 | TRANSITION | candidate | True | - |
| 2022-06-30 | 10,010 | 93.17 | TRANSITION | candidate | True | - |
| 2022-07-29 | 10,105 | 84.72 | TRANSITION | candidate | True | - |
| 2022-08-31 | 10,885 | 83.64 | TRANSITION | candidate | True | - |
| 2022-09-30 | 11,595 | 87.07 | EARLY_TREND | candidate | True | - |
| 2022-10-31 | 11,500 | 99.30 | EARLY_TREND | candidate | True | - |
| 2022-11-30 | 10,785 | 89.71 | TRANSITION | candidate | True | - |
| 2022-12-29 | 9,845 | 82.57 | TRANSITION | candidate | True | - |
| 2023-01-31 | 10,040 | 76.30 | TRANSITION | candidate | True | - |
| 2023-02-28 | 10,485 | 75.64 | TRANSITION | candidate | True | - |
| 2023-03-31 | 10,590 | 81.31 | TRANSITION | candidate | True | - |
| 2023-04-28 | 11,530 | 97.15 | EARLY_TREND | candidate | True | - |
| 2023-05-31 | 11,070 | 100.00 | TRANSITION | candidate | True | - |
| 2023-06-30 | 10,840 | 100.00 | TRANSITION | candidate | True | - |
| 2023-07-31 | 10,590 | 91.32 | TRANSITION | candidate | True | - |
| 2023-08-31 | 10,740 | 90.57 | TRANSITION | candidate | True | - |
| 2023-09-27 | 10,635 | 88.12 | TRANSITION | candidate | True | - |
| 2023-10-31 | 9,645 | 81.74 | TRANSITION | candidate | True | - |
| 2023-11-30 | 10,015 | 76.72 | TRANSITION | candidate | True | - |
| 2023-12-28 | 10,525 | 74.15 | TRANSITION | candidate | True | - |
| 2024-01-31 | 10,400 | 76.19 | TRANSITION | candidate | True | - |
| 2024-02-29 | 10,825 | 85.41 | TRANSITION | candidate | True | - |
| 2024-03-29 | 10,735 | 77.76 | TRANSITION | candidate | True | - |
| 2024-04-30 | 10,135 | 68.68 | TRANSITION | candidate | True | - |
| 2024-05-31 | 9,440 | 62.37 | BASE | watch | True | - |
| 2024-06-28 | 9,470 | 58.52 | BASE | watch | True | - |
| 2024-07-31 | 9,790 | 61.02 | BASE | watch | True | - |
| 2024-08-30 | 10,400 | 61.79 | BASE | watch | True | - |
| 2024-09-30 | 10,525 | 59.74 | TRANSITION | candidate | True | - |
| 2024-10-31 | 10,435 | 56.74 | BASE | watch | True | - |
| 2024-11-29 | 9,880 | 54.99 | BASE | watch | True | - |
| 2024-12-30 | 9,785 | 59.05 | BASE | watch | True | - |
| 2025-01-31 | 9,695 | 61.83 | BASE | watch | True | - |
| 2025-02-28 | 8,230 | 56.42 | WEAK | blocked | True | - |
| 2025-03-31 | 8,495 | 47.45 | WEAK | blocked | True | - |
| 2025-04-30 | 8,520 | 33.78 | BASE | watch | True | - |
| 2025-05-30 | 8,855 | 33.62 | BASE | watch | True | - |
| 2025-06-30 | 8,260 | 30.40 | WEAK | blocked | True | - |
| 2025-07-31 | 8,400 | 34.54 | BASE | watch | True | - |
| 2025-08-29 | 8,425 | 33.65 | BASE | watch | True | - |
| 2025-09-30 | 8,270 | 34.47 | BASE | watch | True | - |
| 2025-10-31 | 8,630 | 40.74 | BASE | watch | True | - |
| 2025-11-28 | 9,045 | 47.54 | BASE | watch | True | - |
| 2025-12-30 | 8,570 | 49.40 | BASE | watch | True | - |
| 2026-01-30 | 8,125 | 42.78 | BASE | watch | True | - |
| 2026-02-27 | 8,150 | 32.78 | BASE | watch | True | - |
| 2026-03-31 | 7,285 | 22.54 | WEAK | blocked | True | - |
| 2026-04-30 | 6,490 | 11.62 | WEAK | blocked | True | - |
| 2026-05-29 | 5,880 | 3.20 | WEAK | blocked | True | - |
| 2026-06-30 | 5,270 | 0.00 | WEAK | blocked | True | - |
| 2026-07-31 | 5,335 | 0.00 | WEAK | blocked | True | - |
| 2026-08-31 | 5,345 | 0.00 | WEAK | blocked | True | - |

---

## 10. 데이터 품질 및 신원 (Data Quality & Provenance)
- **로컬 일봉 캐시**: `정상 로드 (2428행)`
- **데이터 기간**: `2016-11-01` ~ `2026-09-23`
- **완성 월봉 수**: `118개월`
- **데이터 품질 상태**: `OK`
- **적용 계약**: Score(`pattern_a_score_v0.2`), Stage(`pattern_a_stage_v0.1`), Strategy(`PATTERN_A_FAST_FINAL_STRATEGY_V02`), Investability(`phase10`), Flow(`phase11`)
- **외부 네트워크 요청**: `0회` (Zero Network Request)

---

*주의 (Disclaimer): 본 리포트는 기술적 지표 및 과거 수급/유동성 통계에 기반한 설명 자료이며, 매수/매도 추천이나 목표가를 제시하지 않습니다.*
