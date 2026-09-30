# [KODEX WTI원유선물(H) (261220)] 종목 리포트 v0.6

- **시장 구분 (Listing Market)**: `KOSPI`
- **자산 유형 (Asset Type)**: `ETF`
- **분석 기준일 (Requested As-Of)**: `2026-09-25`
- **신선도 기준일 (Reference Market Date)**: `2026-09-23`
- **리포트 상태**: `PARTIAL`

---

## 0. 핵심 요약 (Executive Summary)
> **KODEX WTI원유선물(H)(261220)의 공식 ETF36 Julia V1 리포트야. 분석 기준일 2026-09-25, 실제 시장 데이터 기준일 2026-09-23야.**
>
> - Julia V1: WAIT
> - ETF 적격성: PASS · raw 종가 26095.0원 · 20D 평균 거래량 115566.4주
> - 펀더멘털: NOT_APPLICABLE (일반기업 Fundamentals V1 적용 대상 아님)
> - 현재 Pattern A Score는 63.20점(Stage: PROGRESSED, Candidate: NO)입니다.
> - 외국인 수급: 외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다.
> - 시장 상대강도: Phase12 Market RS는 KOSPI/KOSDAQ 보통주(COMMON)를 대상으로 정의되어 이 종목에는 적용되지 않습니다.
> - 업종 상대강도: Sector RS는 KOSPI/KOSDAQ COMMON 종목을 대상으로 하므로 이 종목에는 적용되지 않습니다.
> - 거래대금 추세: 최근 거래대금이 지속 감소(둔화)하는 흐름입니다. 5일 평균 거래대금(25.73억원)이 20일 평균(31.01억원) 및 60일 평균(36.88억원)을 밑돌고 있습니다.

KODEX WTI원유선물(H)은(는) 기준일 2026-09-23에 Julia V1 상태 WAIT야. ETF PIT 적격성은 PASS이며 시가총액과 Phase10 Investability는 이 ETF 전략의 적격성 기준이 아니야. 공통 기술·수급 섹션은 기존 Stock Report 계산을 재사용했어.

---

## 1. 현재 기술적 국면 및 ETF 적격성 스냅샷
- **Pattern A Score / 국면**: `63.2` / `PROGRESSED`
- **Official ETF36 membership**: `PASS`
- **상장일 / 상장 2년 요건**: `2016-12-27` / `PASS`
- **기준일 raw 종가**: `26095.0원` (최소 1,000원: `PASS`)
- **20 KRX 거래일 평균 raw 거래량**: `115566.4주` (최소 10,000주: `PASS`)
- **20일 창**: `2026-08-27` ~ `2026-09-23`; 신호일 포함: `True`
- **ETF 적격성**: `PASS` (`ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`)
- **Strategy-ready / clean-ready / 유효 시작일**: `2019-11-29 / 2019-11-29 / 2019-11-29`
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
- **전략 상태**: `WAIT`
- **전략 포지션**: `FLAT`
- **현재 행동**: `WAIT`
- **행동 사유**: `NO_OPEN_POSITION`
- **실행 시점**: `해당 없음`
- **해석**: Julia V1의 현재 보유 포지션은 없어. 다음 진입은 완료된 주봉 신호와 exact KRX PIT·익일 시가 조건이 모두 확인돼야 해.

### ETF 진입 조건 체크리스트
| 진입 검증 항목 | 기준일 관측값 | 충족 여부 |
|---|---|:---:|
| Official ETF36 | `True` | `PASS` |
| 상장 2년 이상 | `2016-12-27` | `PASS` |
| raw 종가 ≥ 1,000원 | `27915.0` | `PASS` |
| 20 KRX 거래일 평균 raw 거래량 ≥ 10,000주 | `117622.85` | `PASS` |
| Strategy-ready / clean-ready | `2019-11-29 / 2019-11-29` | `PASS` |
| Pattern A 국면 | `PROGRESSED` | `FAIL` |
| FAST 주별 트리거 | `EXTENDED (READY)` | `FAIL` |
| 월간 국면 | `PERMITTED_REGIME` | `PASS` |
| 일봉 리스크 | `NORMAL` | `PASS` |
| FAST 점수 | `READY` | `PASS` |
| 미보유 상태 | `FLAT` | `PASS` |
| 다음 실제 KRX 거래일 raw 시가 | `2026-09-21 / 27860.0` | `PASS` |

- **신규 진입 조건 전체 판정**: `FAIL`
- **미충족 조건**: `PATTERN_A_TRANSITION_OR_EARLY_TREND, FAST_TRIGGER_READY, SIGNAL_DATE_IS_CURRENT_REFERENCE`

### 현재 포지션
- 기준일 현재 열린 Julia V1 포지션이 없어.

### 보호 및 재진입
- **Pre-PROGRESSED Loss Guard**: `DISABLED`
- **보호 상태**: `열린 포지션 없음`
- **재진입 상태**: `{'enabled': True, 'cooldown': 'NONE', 'maximum_reentries': 'NONE', 'completed_trade_count': 1, 'current_trade_sequence': None, 'next_entry_sequence': 2}`

### Julia V1 전략 거래 이력
| 순번 | 진입 신호일 | 진입 체결일 | 진입 시가 | 청산 유형 | 청산 체결일 | 청산 시가 | 수익률 | 상태 |
|:---:|:---:|:---:|---:|---|:---:|---:|---:|:---:|
| 1 | `2020-01-03` | `2020-01-06` | 22,145원 | `EXIT4_SCORE_DRAWDOWN_GE_15` | `2026-09-01` | 24,300원 | +9.73% | `REALIZED` |

> V00 lifecycle evaluator를 그대로 사용했고, V1 정책에서 Pre-PROGRESSED Loss Guard를 비활성화했어. 과거 거래는 미래 수익을 보장하지 않아.

---
## 3. Pattern A FAST 현재 신호 (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **기준 주 (As-Of)**: `2026-09-18`
- **FAST Score**: `75.75`
- **Score Availability**: `READY`
- **FAST Stage**: `EXTENDED`
- **Stage Availability**: `READY`
- **Monthly Regime**: `PERMITTED_REGIME`
- **Daily Risk**: `NORMAL`
- **해석**: FAST 관점에서는 초기 진입 구간이 상당 부분 진행된 상태입니다.

> Pattern A FAST는 Pattern A와 독립적인 실험적(Experimental) 조기 신호이며, Pattern A Score/Stage/Candidate/Production Ranking에 영향을 주지 않습니다. 두 모델의 Score를 합산하거나 상대 우열을 계산하지 않습니다.

---

## 4. Pattern A Monthly History — 최근 12개월 월별 추이 (Recent 12M Trajectory)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available |
|---|---:|---:|---|---|---|
| 2025-08-29 | 14,685 | 75.79 | TRANSITION | candidate | True |
| 2025-09-30 | 14,505 | 62.75 | BASE | watch | True |
| 2025-10-31 | 13,895 | 54.86 | BASE | watch | True |
| 2025-11-28 | 13,640 | 52.16 | BASE | watch | True |
| 2025-12-30 | 13,455 | 57.51 | BASE | watch | True |
| 2026-01-30 | 14,965 | 63.18 | BASE | watch | True |
| 2026-02-27 | 15,340 | 70.48 | EARLY_TREND | candidate | True |
| 2026-03-31 | 24,780 | 95.22 | EARLY_TREND | candidate | True |
| 2026-04-30 | 28,625 | 97.29 | EARLY_TREND | candidate | True |
| 2026-05-29 | 23,705 | 91.86 | EARLY_TREND | candidate | True |
| 2026-06-30 | 19,435 | 79.19 | PROGRESSED | late | True |
| 2026-07-31 | 22,850 | 75.97 | PROGRESSED | late | True |
| 2026-08-31 | 24,045 | 62.32 | PROGRESSED | late | True |

- **점수 변화 모멘텀**: 1M (-12.77), 3M (-28.66), 6M (-7.28), 12M (-12.59)

---

## 5. Pattern A 국면 전환 이력 (Stage Transition History)
- **2019-11-29**: `UNAVAILABLE` -> `TRANSITION`
- **2020-01-31**: `TRANSITION` -> `BASE`
- **2020-02-28**: `BASE` -> `WEAK`
- **2022-03-31**: `WEAK` -> `PROGRESSED`
- **2023-04-28**: `PROGRESSED` -> `TRANSITION`
- **2023-08-31**: `TRANSITION` -> `EARLY_TREND`
- **2023-11-30**: `EARLY_TREND` -> `TRANSITION`
- **2024-05-31**: `TRANSITION` -> `BASE`
- **2025-01-31**: `BASE` -> `TRANSITION`
- **2025-04-30**: `TRANSITION` -> `WEAK`
- **2025-06-30**: `WEAK` -> `TRANSITION`
- **2025-07-31**: `TRANSITION` -> `EARLY_TREND`
- **2025-08-29**: `EARLY_TREND` -> `TRANSITION`
- **2025-09-30**: `TRANSITION` -> `BASE`
- **2026-02-27**: `BASE` -> `EARLY_TREND`
- **2026-06-30**: `EARLY_TREND` -> `PROGRESSED`

---

## 6. Pattern A FAST Weekly History (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **History 시작 주**: `2025-09-26`
- **History 종료 주**: `2026-09-18`
- **총 주별 관측 개수**: `49주`

| 기준 주 (Week Ending) | 종가 | FAST Score | Score Availability | FAST Stage | Stage Availability | Monthly Regime | Daily Risk |
|---|---:|---:|---|---|---|---|---|
| 2025-09-26 | 14,960 | 75.42 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-10-10 | 14,065 | 58.97 | READY | WATCH | READY | PERMITTED_REGIME | ELEVATED |
| 2025-10-17 | 13,140 | 57.92 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2025-10-24 | 14,215 | 63.17 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2025-10-31 | 13,895 | 60.92 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-11-07 | 13,850 | 60.92 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-11-14 | 13,765 | 55.67 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2025-11-21 | 13,490 | 60.92 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2025-11-28 | 13,640 | 56.72 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-05 | 13,765 | 60.92 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-12 | 13,445 | 50.42 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-19 | 12,970 | 50.42 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2025-12-26 | 13,535 | 60.92 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-02 | 13,410 | 54.62 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-09 | 13,510 | 55.67 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-01-16 | 13,680 | 60.92 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-23 | 13,940 | 60.92 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-30 | 14,965 | 70.55 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-02-06 | 14,925 | 75.80 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-02-13 | 14,590 | 70.55 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-02-20 | 15,645 | 73.00 | READY | TRIGGER | READY | PERMITTED_REGIME | ELEVATED |
| 2026-02-27 | 15,340 | 79.80 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-03-06 | 18,900 | 67.49 | READY | TRIGGER | READY | PERMITTED_REGIME | EXTREME |
| 2026-03-13 | 22,735 | 66.17 | READY | EXTENDED | READY | PERMITTED_REGIME | EXTREME |
| 2026-03-20 | 22,680 | 69.17 | READY | EXTENDED | READY | PERMITTED_REGIME | EXTREME |
| 2026-03-27 | 22,665 | 70.49 | READY | EXTENDED | READY | PERMITTED_REGIME | EXTREME |
| 2026-04-03 | 26,205 | 58.04 | READY | EXTENDED | READY | LATE_OR_EXTENDED_REGIME | EXTREME |
| 2026-04-10 | 23,925 | 52.41 | READY | EXTENDED | READY | LATE_OR_EXTENDED_REGIME | EXTREME |
| 2026-04-17 | 23,390 | 57.66 | READY | EXTENDED | READY | LATE_OR_EXTENDED_REGIME | ELEVATED |
| 2026-04-24 | 24,985 | 57.66 | READY | EXTENDED | READY | LATE_OR_EXTENDED_REGIME | ELEVATED |
| 2026-05-08 | 24,715 | 49.41 | READY | EXTENDED | READY | LATE_OR_EXTENDED_REGIME | EXTREME |
| 2026-05-15 | 26,920 | 60.79 | READY | EXTENDED | READY | LATE_OR_EXTENDED_REGIME | ELEVATED |
| 2026-05-22 | 26,595 | 60.79 | READY | EXTENDED | READY | LATE_OR_EXTENDED_REGIME | ELEVATED |
| 2026-05-29 | 23,705 | 64.11 | READY | EXTENDED | READY | PERMITTED_REGIME | ELEVATED |
| 2026-06-05 | 25,240 | 64.11 | READY | EXTENDED | READY | PERMITTED_REGIME | ELEVATED |
| 2026-06-12 | 23,420 | 64.11 | READY | EXTENDED | READY | PERMITTED_REGIME | ELEVATED |
| 2026-06-19 | 21,220 | 56.76 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-06-26 | 19,670 | 53.26 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-07-03 | 19,370 | 58.51 | READY | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-07-10 | 19,910 | 54.57 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-07-24 | 25,380 | 64.11 | READY | EXTENDED | READY | PERMITTED_REGIME | ELEVATED |
| 2026-07-31 | 22,850 | 58.86 | READY | SETUP | READY | PERMITTED_REGIME | EXTREME |
| 2026-08-07 | 21,610 | 48.01 | READY | SETUP | READY | PERMITTED_REGIME | EXTREME |
| 2026-08-14 | 22,880 | 59.56 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-08-21 | 24,285 | 64.38 | READY | EXTENDED | READY | PERMITTED_REGIME | ELEVATED |
| 2026-08-28 | 23,375 | 60.88 | READY | SETUP | READY | PERMITTED_REGIME | ELEVATED |
| 2026-09-04 | 25,695 | 64.38 | READY | EXTENDED | READY | PERMITTED_REGIME | ELEVATED |
| 2026-09-11 | 28,315 | 63.94 | READY | EXTENDED | READY | PERMITTED_REGIME | EXTREME |
| 2026-09-18 | 27,915 | 75.75 | READY | EXTENDED | READY | PERMITTED_REGIME | NORMAL |

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
- **규칙 기반 해석**: 최근 거래대금이 지속 감소(둔화)하는 흐름입니다. 5일 평균 거래대금(25.73억원)이 20일 평균(31.01억원) 및 60일 평균(36.88억원)을 밑돌고 있습니다.
| 구간 | 평균 거래대금 |
|---|---:|
| 1D | 26.05억원 |
| 5D | 25.73억원 |
| 10D | 37.27억원 |
| 20D | 31.01억원 |
| 60D | 36.88억원 |
- **20일 평균 거래대금**: `31.01억원`
- **60일 평균 거래대금**: `36.88억원`
- **단기 확장 비율 (5D / 20D)**: `0.83배`
- **중기 확장 비율 (20D / 60D)**: `0.84배`

---

## 9. Pattern A 전체 월별 이력 (Full Monthly History)
- **전체 관측 시작월**: `2016-12-29`
- **전체 관측 종료월**: `2026-08-31`
- **최초 Pattern A 산출월**: `2019-11-29`
- **총 월별 관측 개수**: `117개월` (Pattern A 산출 가능: `82개월`)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available | Reason |
|---|---:|---:|---|---|---|---|
| 2016-12-29 | 20,300 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-01-31 | 19,460 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-02-28 | 19,905 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-03-31 | 18,140 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-04-28 | 17,815 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-05-31 | 17,590 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-06-30 | 16,055 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-07-31 | 17,600 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-08-31 | 16,210 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-09-29 | 17,980 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-10-31 | 18,730 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-11-30 | 19,805 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-12-28 | 20,535 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-01-31 | 22,005 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-02-28 | 21,660 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-03-30 | 22,390 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-04-30 | 23,535 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-05-31 | 23,645 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-06-29 | 25,505 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-07-31 | 24,760 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-08-31 | 25,180 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-09-28 | 25,975 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-10-31 | 23,895 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-11-30 | 18,505 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-12-28 | 16,375 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-01-31 | 19,320 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-02-28 | 19,950 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-03-29 | 20,845 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-04-30 | 22,130 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-05-31 | 19,540 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-06-28 | 20,440 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-07-31 | 20,230 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-08-30 | 19,415 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-09-30 | 19,390 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-10-31 | 19,100 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-11-29 | 20,035 | 69.82 | TRANSITION | candidate | True | - |
| 2019-12-30 | 21,395 | 69.00 | TRANSITION | candidate | True | - |
| 2020-01-31 | 18,390 | 62.10 | BASE | watch | True | - |
| 2020-02-28 | 15,500 | 48.98 | WEAK | blocked | True | - |
| 2020-03-31 | 7,215 | 3.08 | WEAK | blocked | True | - |
| 2020-04-29 | 3,385 | 0.00 | WEAK | blocked | True | - |
| 2020-05-29 | 5,380 | 0.00 | WEAK | blocked | True | - |
| 2020-06-30 | 6,255 | 0.00 | WEAK | blocked | True | - |
| 2020-07-31 | 6,380 | 0.00 | WEAK | blocked | True | - |
| 2020-08-31 | 6,770 | 0.00 | WEAK | blocked | True | - |
| 2020-09-29 | 6,270 | 0.00 | WEAK | blocked | True | - |
| 2020-10-30 | 5,540 | 0.00 | WEAK | blocked | True | - |
| 2020-11-30 | 6,760 | 0.00 | WEAK | blocked | True | - |
| 2020-12-30 | 7,260 | 0.00 | WEAK | blocked | True | - |
| 2021-01-29 | 7,810 | 0.00 | WEAK | blocked | True | - |
| 2021-02-26 | 9,430 | 0.00 | WEAK | blocked | True | - |
| 2021-03-31 | 9,140 | 0.00 | WEAK | blocked | True | - |
| 2021-04-30 | 9,675 | 0.00 | WEAK | blocked | True | - |
| 2021-05-31 | 10,030 | 0.00 | WEAK | blocked | True | - |
| 2021-06-30 | 11,030 | 0.00 | WEAK | blocked | True | - |
| 2021-07-30 | 11,060 | 0.00 | WEAK | blocked | True | - |
| 2021-08-31 | 10,515 | 0.00 | WEAK | blocked | True | - |
| 2021-09-30 | 11,415 | 0.00 | WEAK | blocked | True | - |
| 2021-10-29 | 12,665 | 0.00 | WEAK | blocked | True | - |
| 2021-11-30 | 10,650 | 0.00 | WEAK | blocked | True | - |
| 2021-12-30 | 11,950 | 0.00 | WEAK | blocked | True | - |
| 2022-01-28 | 13,670 | 0.00 | WEAK | blocked | True | - |
| 2022-02-28 | 15,380 | 0.00 | WEAK | blocked | True | - |
| 2022-03-31 | 16,870 | 24.67 | PROGRESSED | late | True | - |
| 2022-04-29 | 17,505 | 19.23 | PROGRESSED | late | True | - |
| 2022-05-31 | 19,955 | 11.23 | PROGRESSED | late | True | - |
| 2022-06-30 | 18,725 | 14.54 | PROGRESSED | late | True | - |
| 2022-07-29 | 17,035 | 3.20 | PROGRESSED | late | True | - |
| 2022-08-31 | 16,405 | 2.58 | PROGRESSED | late | True | - |
| 2022-09-30 | 14,475 | 1.78 | PROGRESSED | late | True | - |
| 2022-10-31 | 15,750 | 6.24 | PROGRESSED | late | True | - |
| 2022-11-30 | 14,430 | 17.57 | PROGRESSED | late | True | - |
| 2022-12-29 | 14,315 | 19.52 | PROGRESSED | late | True | - |
| 2023-01-31 | 14,120 | 42.12 | PROGRESSED | late | True | - |
| 2023-02-28 | 13,830 | 46.52 | PROGRESSED | late | True | - |
| 2023-03-31 | 13,465 | 52.78 | PROGRESSED | late | True | - |
| 2023-04-28 | 13,665 | 70.00 | TRANSITION | candidate | True | - |
| 2023-05-31 | 12,635 | 77.82 | TRANSITION | candidate | True | - |
| 2023-06-30 | 12,695 | 74.38 | TRANSITION | candidate | True | - |
| 2023-07-31 | 14,620 | 74.09 | TRANSITION | candidate | True | - |
| 2023-08-31 | 14,960 | 77.94 | EARLY_TREND | candidate | True | - |
| 2023-09-27 | 16,870 | 93.15 | EARLY_TREND | candidate | True | - |
| 2023-10-31 | 15,620 | 91.76 | EARLY_TREND | candidate | True | - |
| 2023-11-30 | 14,810 | 84.29 | TRANSITION | candidate | True | - |
| 2023-12-28 | 13,980 | 79.49 | TRANSITION | candidate | True | - |
| 2024-01-31 | 14,620 | 77.11 | TRANSITION | candidate | True | - |
| 2024-02-29 | 14,850 | 69.49 | TRANSITION | candidate | True | - |
| 2024-03-29 | 15,795 | 63.17 | TRANSITION | candidate | True | - |
| 2024-04-30 | 15,875 | 57.12 | TRANSITION | candidate | True | - |
| 2024-05-31 | 15,095 | 44.72 | BASE | watch | True | - |
| 2024-06-28 | 16,045 | 39.37 | BASE | watch | True | - |
| 2024-07-31 | 15,070 | 38.09 | BASE | watch | True | - |
| 2024-08-30 | 15,340 | 50.37 | BASE | watch | True | - |
| 2024-09-30 | 14,065 | 56.91 | BASE | watch | True | - |
| 2024-10-31 | 14,245 | 58.16 | BASE | watch | True | - |
| 2024-11-29 | 14,310 | 60.74 | BASE | watch | True | - |
| 2024-12-30 | 14,700 | 63.46 | BASE | watch | True | - |
| 2025-01-31 | 15,500 | 73.79 | TRANSITION | candidate | True | - |
| 2025-02-28 | 14,805 | 76.32 | TRANSITION | candidate | True | - |
| 2025-03-31 | 14,810 | 75.30 | TRANSITION | candidate | True | - |
| 2025-04-30 | 12,855 | 70.13 | WEAK | blocked | True | - |
| 2025-05-30 | 13,195 | 69.19 | WEAK | blocked | True | - |
| 2025-06-30 | 14,455 | 70.18 | TRANSITION | candidate | True | - |
| 2025-07-31 | 15,735 | 77.85 | EARLY_TREND | candidate | True | - |
| 2025-08-29 | 14,685 | 75.79 | TRANSITION | candidate | True | - |
| 2025-09-30 | 14,505 | 62.75 | BASE | watch | True | - |
| 2025-10-31 | 13,895 | 54.86 | BASE | watch | True | - |
| 2025-11-28 | 13,640 | 52.16 | BASE | watch | True | - |
| 2025-12-30 | 13,455 | 57.51 | BASE | watch | True | - |
| 2026-01-30 | 14,965 | 63.18 | BASE | watch | True | - |
| 2026-02-27 | 15,340 | 70.48 | EARLY_TREND | candidate | True | - |
| 2026-03-31 | 24,780 | 95.22 | EARLY_TREND | candidate | True | - |
| 2026-04-30 | 28,625 | 97.29 | EARLY_TREND | candidate | True | - |
| 2026-05-29 | 23,705 | 91.86 | EARLY_TREND | candidate | True | - |
| 2026-06-30 | 19,435 | 79.19 | PROGRESSED | late | True | - |
| 2026-07-31 | 22,850 | 75.97 | PROGRESSED | late | True | - |
| 2026-08-31 | 24,045 | 62.32 | PROGRESSED | late | True | - |

---

## 10. 데이터 품질 및 신원 (Data Quality & Provenance)
- **로컬 일봉 캐시**: `정상 로드 (2388행)`
- **데이터 기간**: `2016-12-27` ~ `2026-09-23`
- **완성 월봉 수**: `117개월`
- **데이터 품질 상태**: `OK`
- **적용 계약**: Score(`pattern_a_score_v0.2`), Stage(`pattern_a_stage_v0.1`), Strategy(`PATTERN_A_FAST_FINAL_STRATEGY_V02`), Investability(`phase10`), Flow(`phase11`)
- **외부 네트워크 요청**: `0회` (Zero Network Request)

---

*주의 (Disclaimer): 본 리포트는 기술적 지표 및 과거 수급/유동성 통계에 기반한 설명 자료이며, 매수/매도 추천이나 목표가를 제시하지 않습니다.*
