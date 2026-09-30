# [PLUS 신흥국MSCI(합성 H) (195980)] 종목 리포트 v0.6

- **시장 구분 (Listing Market)**: `KOSPI`
- **자산 유형 (Asset Type)**: `ETF`
- **분석 기준일 (Requested As-Of)**: `2026-09-25`
- **신선도 기준일 (Reference Market Date)**: `2026-09-23`
- **리포트 상태**: `PARTIAL`

---

## 0. 핵심 요약 (Executive Summary)
> **PLUS 신흥국MSCI(합성 H)(195980)의 공식 ETF36 Julia V1 리포트야. 분석 기준일 2026-09-25, 실제 시장 데이터 기준일 2026-09-23야.**
>
> - Julia V1: HOLD_PROGRESSED
> - ETF 적격성: PASS · raw 종가 15560.0원 · 20D 평균 거래량 18563.65주
> - 펀더멘털: NOT_APPLICABLE (일반기업 Fundamentals V1 적용 대상 아님)
> - 현재 Pattern A Score는 83.23점(Stage: PROGRESSED, Candidate: NO)입니다.
> - 외국인 수급: 외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다.
> - 시장 상대강도: Phase12 Market RS는 KOSPI/KOSDAQ 보통주(COMMON)를 대상으로 정의되어 이 종목에는 적용되지 않습니다.
> - 업종 상대강도: Sector RS는 KOSPI/KOSDAQ COMMON 종목을 대상으로 하므로 이 종목에는 적용되지 않습니다.
> - 거래대금 추세: 최근 거래대금이 지속 감소(둔화)하는 흐름입니다. 5일 평균 거래대금(1.79억원)이 20일 평균(2.84억원) 및 60일 평균(3.90억원)을 밑돌고 있습니다.

PLUS 신흥국MSCI(합성 H)은(는) 기준일 2026-09-23에 Julia V1 상태 HOLD_PROGRESSED야. ETF PIT 적격성은 PASS이며 시가총액과 Phase10 Investability는 이 ETF 전략의 적격성 기준이 아니야. 공통 기술·수급 섹션은 기존 Stock Report 계산을 재사용했어.

---

## 1. 현재 기술적 국면 및 ETF 적격성 스냅샷
- **Pattern A Score / 국면**: `83.23` / `PROGRESSED`
- **Official ETF36 membership**: `PASS`
- **상장일 / 상장 2년 요건**: `2014-05-13` / `PASS`
- **기준일 raw 종가**: `15560.0원` (최소 1,000원: `PASS`)
- **20 KRX 거래일 평균 raw 거래량**: `18563.65주` (최소 10,000주: `PASS`)
- **20일 창**: `2026-08-27` ~ `2026-09-23`; 신호일 포함: `True`
- **ETF 적격성**: `PASS` (`ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`)
- **Strategy-ready / clean-ready / 유효 시작일**: `2017-04-28 / 2018-09-21 / 2018-09-21`
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
- **전략 상태**: `HOLD_PROGRESSED`
- **전략 포지션**: `OPEN`
- **현재 행동**: `HOLD`
- **행동 사유**: `OPEN_POSITION_PROGRESSED`
- **실행 시점**: `해당 없음`
- **해석**: Julia V1 포지션을 PROGRESSED 구간에서 보유 중이야. Pre-PROGRESSED Loss Guard는 비활성이야.

### ETF 진입 조건 체크리스트
| 진입 검증 항목 | 기준일 관측값 | 충족 여부 |
|---|---|:---:|
| Official ETF36 | `True` | `PASS` |
| 상장 2년 이상 | `2014-05-13` | `PASS` |
| raw 종가 ≥ 1,000원 | `15375.0` | `PASS` |
| 20 KRX 거래일 평균 raw 거래량 ≥ 10,000주 | `19459.9` | `PASS` |
| Strategy-ready / clean-ready | `2017-04-28 / 2018-09-21` | `PASS` |
| Pattern A 국면 | `PROGRESSED` | `FAIL` |
| FAST 주별 트리거 | `SETUP (READY)` | `FAIL` |
| 월간 국면 | `PERMITTED_REGIME` | `PASS` |
| 일봉 리스크 | `NORMAL` | `PASS` |
| FAST 점수 | `READY` | `PASS` |
| 미보유 상태 | `OPEN` | `FAIL` |
| 다음 실제 KRX 거래일 raw 시가 | `2026-09-21 / 15375.0` | `PASS` |

- **신규 진입 조건 전체 판정**: `FAIL`
- **미충족 조건**: `PATTERN_A_TRANSITION_OR_EARLY_TREND, FAST_TRIGGER_READY, NO_OPEN_POSITION, SIGNAL_DATE_IS_CURRENT_REFERENCE`

### 현재 포지션
- **거래 ID / 순번**: `195980_01` / `1`
- **진입 신호일 / 체결일**: `2019-04-19` / `2019-04-22`
- **진입 시가 / 기준일 종가**: `10965.0` / `15560.0원`
- **수익률**: `41.91%`
- **Lifecycle**: `NORMAL_EARLY_TREND_HANDOFF`
- **청산 신호**: `NO_EXIT_BEFORE_CUTOFF` / `없음`

### 보호 및 재진입
- **Pre-PROGRESSED Loss Guard**: `DISABLED`
- **보호 상태**: `{'phase': 'PROGRESSED', 'loss_guard_state': 'DISABLED', 'loss_guard_threshold_pct': None, 'first_progressed_date': '2026-07-31', 'lifecycle_class': 'NORMAL_EARLY_TREND_HANDOFF', 'exit3_state': 'MONITORING', 'exit4_state': 'MONITORING'}`
- **재진입 상태**: `{'enabled': True, 'cooldown': 'NONE', 'maximum_reentries': 'NONE', 'completed_trade_count': 0, 'current_trade_sequence': 1, 'next_entry_sequence': 2}`

### Julia V1 전략 거래 이력
| 순번 | 진입 신호일 | 진입 체결일 | 진입 시가 | 청산 유형 | 청산 체결일 | 청산 시가 | 수익률 | 상태 |
|:---:|:---:|:---:|---:|---|:---:|---:|---:|:---:|
| 1 | `2019-04-19` | `2019-04-22` | 10,965원 | `NO_EXIT_BEFORE_CUTOFF` | `-` | - | +41.91% | `OPEN_AT_CUTOFF` |

> V00 lifecycle evaluator를 그대로 사용했고, V1 정책에서 Pre-PROGRESSED Loss Guard를 비활성화했어. 과거 거래는 미래 수익을 보장하지 않아.

---
## 3. Pattern A FAST 현재 신호 (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **기준 주 (As-Of)**: `2026-09-18`
- **FAST Score**: `75.55`
- **Score Availability**: `READY`
- **FAST Stage**: `SETUP`
- **Stage Availability**: `READY`
- **Monthly Regime**: `PERMITTED_REGIME`
- **Daily Risk**: `NORMAL`
- **해석**: 주봉 기준 상승 전환 가능성을 보여주는 초기 구조가 형성되고 있으나 아직 Trigger 단계는 아닙니다.

> Pattern A FAST는 Pattern A와 독립적인 실험적(Experimental) 조기 신호이며, Pattern A Score/Stage/Candidate/Production Ranking에 영향을 주지 않습니다. 두 모델의 Score를 합산하거나 상대 우열을 계산하지 않습니다.

---

## 4. Pattern A Monthly History — 최근 12개월 월별 추이 (Recent 12M Trajectory)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available |
|---|---:|---:|---|---|---|
| 2025-08-29 | 11,195 | 94.08 | TRANSITION | candidate | True |
| 2025-09-30 | 11,910 | 98.37 | TRANSITION | candidate | True |
| 2025-10-31 | 12,635 | 100.00 | EARLY_TREND | candidate | True |
| 2025-11-28 | 12,180 | 100.00 | TRANSITION | candidate | True |
| 2025-12-30 | 12,365 | 100.00 | TRANSITION | candidate | True |
| 2026-01-30 | 13,600 | 100.00 | TRANSITION | candidate | True |
| 2026-02-27 | 14,315 | 100.00 | EARLY_TREND | candidate | True |
| 2026-03-31 | 12,265 | 100.00 | TRANSITION | candidate | True |
| 2026-04-30 | 14,180 | 98.98 | TRANSITION | candidate | True |
| 2026-05-29 | 15,480 | 88.00 | EARLY_TREND | candidate | True |
| 2026-06-30 | 15,480 | 92.98 | EARLY_TREND | candidate | True |
| 2026-07-31 | 14,980 | 91.97 | PROGRESSED | late | True |
| 2026-08-31 | 15,260 | 91.26 | PROGRESSED | late | True |

- **점수 변화 모멘텀**: 1M (-8.74), 3M (-4.77), 6M (-16.77), 12M (-10.85)

---

## 5. Pattern A 국면 전환 이력 (Stage Transition History)
- **2017-04-28**: `UNAVAILABLE` -> `BASE`
- **2017-07-31**: `BASE` -> `TRANSITION`
- **2019-08-30**: `TRANSITION` -> `BASE`
- **2020-06-30**: `BASE` -> `TRANSITION`
- **2020-12-30**: `TRANSITION` -> `EARLY_TREND`
- **2021-03-31**: `EARLY_TREND` -> `TRANSITION`
- **2022-07-29**: `TRANSITION` -> `BASE`
- **2022-09-30**: `BASE` -> `WEAK`
- **2023-07-31**: `WEAK` -> `BASE`
- **2023-09-27**: `BASE` -> `WEAK`
- **2023-12-28**: `WEAK` -> `BASE`
- **2024-08-30**: `BASE` -> `TRANSITION`
- **2025-07-31**: `TRANSITION` -> `EARLY_TREND`
- **2025-08-29**: `EARLY_TREND` -> `TRANSITION`
- **2025-10-31**: `TRANSITION` -> `EARLY_TREND`
- **2025-11-28**: `EARLY_TREND` -> `TRANSITION`
- **2026-02-27**: `TRANSITION` -> `EARLY_TREND`
- **2026-03-31**: `EARLY_TREND` -> `TRANSITION`
- **2026-05-29**: `TRANSITION` -> `EARLY_TREND`
- **2026-07-31**: `EARLY_TREND` -> `PROGRESSED`

---

## 6. Pattern A FAST Weekly History (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **History 시작 주**: `2025-09-26`
- **History 종료 주**: `2026-09-18`
- **총 주별 관측 개수**: `49주`

| 기준 주 (Week Ending) | 종가 | FAST Score | Score Availability | FAST Stage | Stage Availability | Monthly Regime | Daily Risk |
|---|---:|---:|---|---|---|---|---|
| 2025-09-26 | 12,015 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-10-10 | 12,150 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-10-17 | 12,160 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-10-24 | 12,370 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-10-31 | 12,635 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-07 | 12,235 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-14 | 12,370 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-21 | 12,015 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-28 | 12,180 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-05 | 12,220 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-12 | 12,250 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-19 | 12,035 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-26 | 12,275 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-02 | 12,620 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-09 | 12,925 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-16 | 13,130 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-23 | 13,270 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-30 | 13,600 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-06 | 13,330 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-13 | 13,865 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-20 | 13,745 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-27 | 14,315 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-03-06 | 13,330 | 68.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-03-13 | 13,145 | 63.04 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | ELEVATED |
| 2026-03-20 | 13,130 | 68.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-03-27 | 12,895 | 62.16 | READY | SETUP | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-04-03 | 12,410 | 66.36 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-04-10 | 13,575 | 72.49 | READY | TRIGGER | READY | PERMITTED_REGIME | ELEVATED |
| 2026-04-17 | 14,180 | 72.49 | READY | TRIGGER | READY | PERMITTED_REGIME | ELEVATED |
| 2026-04-24 | 14,275 | 79.05 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-05-08 | 15,155 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-05-15 | 14,765 | 71.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-05-22 | 14,945 | 71.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-05-29 | 15,480 | 71.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-05 | 15,145 | 71.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-12 | 15,105 | 71.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-19 | 16,085 | 70.79 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-26 | 15,140 | 71.29 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-07-03 | 15,520 | 80.74 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-07-10 | 15,220 | 80.74 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-07-24 | 14,470 | 62.86 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-07-31 | 14,980 | 62.86 | READY | WATCH | READY | PERMITTED_REGIME | ELEVATED |
| 2026-08-07 | 14,765 | 68.11 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-08-14 | 15,185 | 75.55 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-08-21 | 15,345 | 75.55 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-08-28 | 15,285 | 75.55 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-09-04 | 15,385 | 75.55 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-09-11 | 15,410 | 75.55 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-09-18 | 15,375 | 75.55 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |

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
- **거래대금 상태**: `TRADING_VALUE_WEAKENING`
- **규칙 기반 해석**: 최근 거래대금이 지속 감소(둔화)하는 흐름입니다. 5일 평균 거래대금(1.79억원)이 20일 평균(2.84억원) 및 60일 평균(3.90억원)을 밑돌고 있습니다.
| 구간 | 평균 거래대금 |
|---|---:|
| 1D | 1.74억원 |
| 5D | 1.79억원 |
| 10D | 1.66억원 |
| 20D | 2.84억원 |
| 60D | 3.90억원 |
- **20일 평균 거래대금**: `2.84억원`
- **60일 평균 거래대금**: `3.90억원`
- **단기 확장 비율 (5D / 20D)**: `0.63배`
- **중기 확장 비율 (20D / 60D)**: `0.73배`

---

## 9. Pattern A 전체 월별 이력 (Full Monthly History)
- **전체 관측 시작월**: `2014-05-30`
- **전체 관측 종료월**: `2026-08-31`
- **최초 Pattern A 산출월**: `2017-04-28`
- **총 월별 관측 개수**: `148개월` (Pattern A 산출 가능: `113개월`)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available | Reason |
|---|---:|---:|---|---|---|---|
| 2014-05-30 | 10,290 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2014-06-30 | 10,455 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2014-07-31 | 10,730 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2014-08-29 | 10,875 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2014-09-30 | 10,105 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2014-10-31 | 10,135 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2014-11-28 | 10,085 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2014-12-30 | 9,545 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-01-30 | 9,725 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-02-27 | 9,940 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-03-31 | 9,775 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-04-30 | 10,430 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-05-29 | 10,055 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-06-30 | 9,650 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-07-31 | 8,885 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-08-31 | 8,130 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-09-30 | 7,805 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-10-30 | 8,440 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-11-30 | 8,150 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2015-12-30 | 7,920 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-01-29 | 7,185 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-02-29 | 7,270 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-03-31 | 8,180 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-04-29 | 8,220 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-05-31 | 7,975 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-06-30 | 8,215 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-07-29 | 8,650 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-08-31 | 8,845 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-09-30 | 8,930 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-10-31 | 8,905 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-11-30 | 8,455 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-12-29 | 8,375 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-01-31 | 8,975 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-02-28 | 9,265 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-03-31 | 9,465 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-04-28 | 9,655 | 53.08 | BASE | watch | True | - |
| 2017-05-31 | 9,985 | 55.35 | BASE | watch | True | - |
| 2017-06-30 | 10,035 | 48.26 | BASE | watch | True | - |
| 2017-07-31 | 10,570 | 58.65 | TRANSITION | candidate | True | - |
| 2017-08-31 | 10,810 | 70.79 | TRANSITION | candidate | True | - |
| 2017-09-29 | 10,710 | 76.30 | TRANSITION | candidate | True | - |
| 2017-10-31 | 11,115 | 69.16 | UNAVAILABLE | insufficient_data | True | - |
| 2017-11-30 | 11,240 | 91.45 | UNAVAILABLE | insufficient_data | True | - |
| 2017-12-28 | 11,460 | 89.92 | UNAVAILABLE | insufficient_data | True | - |
| 2018-01-31 | 12,485 | 99.39 | TRANSITION | candidate | True | - |
| 2018-02-28 | 11,945 | 99.47 | TRANSITION | candidate | True | - |
| 2018-03-30 | 11,640 | 98.80 | TRANSITION | candidate | True | - |
| 2018-04-30 | 11,625 | 89.23 | TRANSITION | candidate | True | - |
| 2018-05-31 | 11,155 | 87.45 | TRANSITION | candidate | True | - |
| 2018-06-29 | 10,535 | 86.32 | TRANSITION | candidate | True | - |
| 2018-07-31 | 10,825 | 84.89 | TRANSITION | candidate | True | - |
| 2018-08-31 | 10,600 | 82.21 | TRANSITION | candidate | True | - |
| 2018-09-28 | 10,505 | 80.92 | TRANSITION | candidate | True | - |
| 2018-10-31 | 9,450 | 77.54 | TRANSITION | candidate | True | - |
| 2018-11-30 | 10,015 | 77.82 | TRANSITION | candidate | True | - |
| 2018-12-28 | 9,600 | 76.81 | TRANSITION | candidate | True | - |
| 2019-01-31 | 10,470 | 87.70 | TRANSITION | candidate | True | - |
| 2019-02-28 | 10,570 | 87.09 | TRANSITION | candidate | True | - |
| 2019-03-29 | 10,520 | 86.73 | TRANSITION | candidate | True | - |
| 2019-04-30 | 10,820 | 77.49 | TRANSITION | candidate | True | - |
| 2019-05-31 | 9,995 | 73.51 | TRANSITION | candidate | True | - |
| 2019-06-28 | 10,655 | 72.21 | TRANSITION | candidate | True | - |
| 2019-07-31 | 10,515 | 68.49 | TRANSITION | candidate | True | - |
| 2019-08-30 | 9,755 | 64.96 | BASE | watch | True | - |
| 2019-09-30 | 10,080 | 60.42 | BASE | watch | True | - |
| 2019-10-31 | 10,530 | 58.40 | BASE | watch | True | - |
| 2019-11-29 | 10,470 | 59.46 | BASE | watch | True | - |
| 2019-12-30 | 11,175 | 60.76 | BASE | watch | True | - |
| 2020-01-31 | 10,665 | 55.92 | BASE | watch | True | - |
| 2020-02-28 | 10,030 | 51.09 | BASE | watch | True | - |
| 2020-03-31 | 8,300 | 36.54 | BASE | watch | True | - |
| 2020-04-29 | 8,975 | 31.78 | BASE | watch | True | - |
| 2020-05-29 | 9,075 | 30.51 | BASE | watch | True | - |
| 2020-06-30 | 9,650 | 43.06 | TRANSITION | candidate | True | - |
| 2020-07-31 | 10,595 | 54.04 | TRANSITION | candidate | True | - |
| 2020-08-31 | 10,910 | 63.67 | TRANSITION | candidate | True | - |
| 2020-09-29 | 10,440 | 69.72 | TRANSITION | candidate | True | - |
| 2020-10-30 | 10,760 | 75.23 | TRANSITION | candidate | True | - |
| 2020-11-30 | 11,760 | 80.02 | TRANSITION | candidate | True | - |
| 2020-12-30 | 12,280 | 94.17 | EARLY_TREND | candidate | True | - |
| 2021-01-29 | 12,910 | 96.81 | EARLY_TREND | candidate | True | - |
| 2021-02-26 | 12,950 | 97.38 | EARLY_TREND | candidate | True | - |
| 2021-03-31 | 12,640 | 93.75 | TRANSITION | candidate | True | - |
| 2021-04-30 | 12,950 | 82.98 | TRANSITION | candidate | True | - |
| 2021-05-31 | 13,165 | 83.20 | TRANSITION | candidate | True | - |
| 2021-06-30 | 13,150 | 90.94 | TRANSITION | candidate | True | - |
| 2021-07-30 | 12,265 | 81.49 | TRANSITION | candidate | True | - |
| 2021-08-31 | 12,400 | 80.51 | TRANSITION | candidate | True | - |
| 2021-09-30 | 12,030 | 79.21 | TRANSITION | candidate | True | - |
| 2021-10-29 | 12,125 | 78.90 | TRANSITION | candidate | True | - |
| 2021-11-30 | 11,590 | 75.88 | TRANSITION | candidate | True | - |
| 2021-12-30 | 11,665 | 72.83 | TRANSITION | candidate | True | - |
| 2022-01-28 | 11,355 | 71.31 | TRANSITION | candidate | True | - |
| 2022-02-28 | 11,105 | 72.07 | TRANSITION | candidate | True | - |
| 2022-03-31 | 10,895 | 78.52 | TRANSITION | candidate | True | - |
| 2022-04-29 | 10,200 | 80.07 | TRANSITION | candidate | True | - |
| 2022-05-31 | 10,140 | 80.00 | TRANSITION | candidate | True | - |
| 2022-06-30 | 9,520 | 72.24 | TRANSITION | candidate | True | - |
| 2022-07-29 | 9,485 | 65.29 | BASE | watch | True | - |
| 2022-08-31 | 9,490 | 56.83 | BASE | watch | True | - |
| 2022-09-30 | 8,260 | 48.73 | WEAK | blocked | True | - |
| 2022-10-31 | 7,985 | 41.65 | WEAK | blocked | True | - |
| 2022-11-30 | 8,955 | 35.42 | WEAK | blocked | True | - |
| 2022-12-29 | 8,870 | 29.08 | WEAK | blocked | True | - |
| 2023-01-31 | 9,500 | 25.28 | WEAK | blocked | True | - |
| 2023-02-28 | 8,810 | 16.94 | WEAK | blocked | True | - |
| 2023-03-31 | 9,055 | 15.02 | WEAK | blocked | True | - |
| 2023-04-28 | 8,860 | 9.55 | WEAK | blocked | True | - |
| 2023-05-31 | 8,795 | 6.60 | WEAK | blocked | True | - |
| 2023-06-30 | 9,020 | 1.23 | WEAK | blocked | True | - |
| 2023-07-31 | 9,495 | 9.66 | BASE | watch | True | - |
| 2023-08-31 | 8,885 | 14.38 | BASE | watch | True | - |
| 2023-09-27 | 8,510 | 17.43 | WEAK | blocked | True | - |
| 2023-10-31 | 8,270 | 8.70 | WEAK | blocked | True | - |
| 2023-11-30 | 8,745 | 12.58 | WEAK | blocked | True | - |
| 2023-12-28 | 9,250 | 19.51 | BASE | watch | True | - |
| 2024-01-31 | 8,815 | 27.43 | BASE | watch | True | - |
| 2024-02-29 | 9,170 | 32.63 | BASE | watch | True | - |
| 2024-03-29 | 9,400 | 37.77 | BASE | watch | True | - |
| 2024-04-30 | 9,495 | 47.66 | BASE | watch | True | - |
| 2024-05-31 | 9,510 | 54.10 | BASE | watch | True | - |
| 2024-06-28 | 9,840 | 62.39 | BASE | watch | True | - |
| 2024-07-31 | 9,795 | 66.67 | BASE | watch | True | - |
| 2024-08-30 | 9,950 | 74.04 | TRANSITION | candidate | True | - |
| 2024-09-30 | 10,690 | 86.79 | TRANSITION | candidate | True | - |
| 2024-10-31 | 10,075 | 93.13 | TRANSITION | candidate | True | - |
| 2024-11-29 | 9,740 | 85.43 | TRANSITION | candidate | True | - |
| 2024-12-30 | 9,810 | 79.79 | TRANSITION | candidate | True | - |
| 2025-01-31 | 9,635 | 73.28 | TRANSITION | candidate | True | - |
| 2025-02-28 | 9,835 | 74.08 | TRANSITION | candidate | True | - |
| 2025-03-31 | 9,880 | 73.70 | TRANSITION | candidate | True | - |
| 2025-04-30 | 9,990 | 85.05 | TRANSITION | candidate | True | - |
| 2025-05-30 | 10,400 | 87.07 | TRANSITION | candidate | True | - |
| 2025-06-30 | 10,980 | 90.98 | TRANSITION | candidate | True | - |
| 2025-07-31 | 11,165 | 92.56 | EARLY_TREND | candidate | True | - |
| 2025-08-29 | 11,195 | 94.08 | TRANSITION | candidate | True | - |
| 2025-09-30 | 11,910 | 98.37 | TRANSITION | candidate | True | - |
| 2025-10-31 | 12,635 | 100.00 | EARLY_TREND | candidate | True | - |
| 2025-11-28 | 12,180 | 100.00 | TRANSITION | candidate | True | - |
| 2025-12-30 | 12,365 | 100.00 | TRANSITION | candidate | True | - |
| 2026-01-30 | 13,600 | 100.00 | TRANSITION | candidate | True | - |
| 2026-02-27 | 14,315 | 100.00 | EARLY_TREND | candidate | True | - |
| 2026-03-31 | 12,265 | 100.00 | TRANSITION | candidate | True | - |
| 2026-04-30 | 14,180 | 98.98 | TRANSITION | candidate | True | - |
| 2026-05-29 | 15,480 | 88.00 | EARLY_TREND | candidate | True | - |
| 2026-06-30 | 15,480 | 92.98 | EARLY_TREND | candidate | True | - |
| 2026-07-31 | 14,980 | 91.97 | PROGRESSED | late | True | - |
| 2026-08-31 | 15,260 | 91.26 | PROGRESSED | late | True | - |

---

## 10. 데이터 품질 및 신원 (Data Quality & Provenance)
- **로컬 일봉 캐시**: `정상 로드 (3036행)`
- **데이터 기간**: `2014-05-13` ~ `2026-09-23`
- **완성 월봉 수**: `148개월`
- **데이터 품질 상태**: `OK`
- **적용 계약**: Score(`pattern_a_score_v0.2`), Stage(`pattern_a_stage_v0.1`), Strategy(`PATTERN_A_FAST_FINAL_STRATEGY_V02`), Investability(`phase10`), Flow(`phase11`)
- **외부 네트워크 요청**: `0회` (Zero Network Request)

---

*주의 (Disclaimer): 본 리포트는 기술적 지표 및 과거 수급/유동성 통계에 기반한 설명 자료이며, 매수/매도 추천이나 목표가를 제시하지 않습니다.*
