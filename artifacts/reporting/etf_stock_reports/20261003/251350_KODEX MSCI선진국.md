# [KODEX MSCI선진국 (251350)] 종목 리포트 v0.6

- **시장 구분 (Listing Market)**: `KOSPI`
- **자산 유형 (Asset Type)**: `ETF`
- **분석 기준일 (Requested As-Of)**: `2026-10-03`
- **신선도 기준일 (Reference Market Date)**: `2026-10-02`
- **리포트 상태**: `PARTIAL`

---

## 0. 핵심 요약 (Executive Summary)
> **KODEX MSCI선진국(251350)의 공식 ETF36 Julia V1 리포트야. 분석 기준일 2026-10-03, 실제 시장 데이터 기준일 2026-10-02야.**
>
> - Julia V1: HOLD_PRE_PROGRESSED
> - 과거 adoption eligibility 참고: PASS · raw 종가 37945.0원 · 20D 평균 거래량 28146.6주
> - 펀더멘털: NOT_APPLICABLE (일반기업 Fundamentals V1 적용 대상 아님)
> - 현재 Pattern A Score는 86.53점(Stage: TRANSITION, Candidate: YES)입니다.
> - 외국인 수급: 외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다.
> - 시장 상대강도: Phase12 Market RS는 KOSPI/KOSDAQ 보통주(COMMON)를 대상으로 정의되어 이 종목에는 적용되지 않습니다.
> - 업종 상대강도: Sector RS는 KOSPI/KOSDAQ COMMON 종목을 대상으로 하므로 이 종목에는 적용되지 않습니다.
> - 거래대금 추세: 최근 거래대금이 특정 방향성 없이 기간별로 혼조세를 나타내고 있습니다. (5일: 16.74억원, 20일: 10.79억원, 60일: 12.74억원)

KODEX MSCI선진국은(는) 기준일 2026-10-02에 Julia V1 상태 HOLD_PRE_PROGRESSED야. 현재 production universe는 고정 Official ETF36이야. 과거 adoption eligibility (ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01)는 PASS로 참고 표시하며, 20일 거래량 10,000주 기준은 현재 membership·진입·기존 포지션 lifecycle gate가 아니야. 시가총액과 Phase10 Investability도 이 ETF 전략의 적격성 기준이 아니야. 공통 기술·수급 섹션은 기존 Stock Report 계산을 재사용했어.

---

## 1. 현재 기술적 국면 및 ETF 스냅샷
- **Pattern A Score / 국면**: `86.53` / `TRANSITION`
- **Official ETF36 membership**: `PASS`
- **상장일 / 상장 2년 요건**: `2016-08-17` / `PASS`
- **기준일 raw 종가**: `37945.0원` (최소 1,000원: `PASS`)
- **20 KRX 거래일 평균 raw 거래량 (과거 검증 참고값)**: `28146.6주` (과거 기준 10,000주: `충족`; 현재 운용 gate 아님)
- **20일 창**: `2026-09-03` ~ `2026-10-02`; 신호일 포함: `True`
- **과거 adoption eligibility 참고 결과**: `PASS` (`ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`; current frozen-universe membership와 별도)
- **Strategy-ready / clean-ready / 유효 시작일**: `2019-08-02 / 2019-08-02 / 2019-08-02`
- **시가총액 / Phase10 Investability**: `NOT_APPLICABLE` (Julia V1 ETF 적격성 조건이 아님)

---
## 1.5. 펀더멘털 (Fundamentals)
- **적용성 (Applicability)**: `NOT_APPLICABLE`
- **데이터 상태 (Data Status)**: `NOT_APPLICABLE`
- **사유 (Reason)**: `ASSET_TYPE_NOT_APPLICABLE`
- **기준일 (Requested As-Of)**: `2026-10-03`
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

### Julia V1 신규 진입 조건 및 참고 지표
| 진입 검증 항목 | 기준일 관측값 | 충족 여부 |
|---|---|:---:|
| Official ETF36 | `True` | `PASS` |
| 상장 2년 이상 | `2016-08-17` | `PASS` |
| raw 종가 ≥ 1,000원 | `37945.0` | `PASS` |
| 과거 채택 검증용 20일 평균 거래량 기준 (참고값, 현재 진입 gate 아님) | `28146.6` | `기준 통과` |
| Strategy-ready / clean-ready | `2019-08-02 / 2019-08-02` | `PASS` |
| Pattern A 국면 | `TRANSITION` | `PASS` |
| FAST 주별 트리거 | `WATCH (READY)` | `FAIL` |
| 월간 국면 | `PERMITTED_REGIME` | `PASS` |
| 일봉 리스크 | `NORMAL` | `PASS` |
| FAST 점수 | `READY` | `PASS` |
| 미보유 상태 | `OPEN` | `FAIL` |
| 다음 실제 KRX 거래일 raw 시가 | `None / None` | `FAIL` |

- **신규 진입 조건 전체 판정**: `FAIL`
- **미충족 조건**: `FAST_TRIGGER_READY, NO_OPEN_POSITION, EXACT_NEXT_KRX_OPEN_AVAILABLE`
- **거래량 기준 적용 범위**: 과거 adoption/backtest eligibility만을 위한 참고값이야. 고정 Official ETF36 소속, 현재 신규 진입 gate, 기존 포지션 lifecycle에는 적용하지 않아.

### 현재 포지션
- **거래 ID / 순번**: `251350_01` / `1`
- **진입 신호일 / 체결일**: `2023-06-23` / `2023-06-26`
- **진입 시가 / 기준일 종가**: `21930.0` / `37945.0원`
- **수익률**: `73.03%`
- **Lifecycle**: `NEVER_PROGRESSED`
- **청산 신호**: `NO_PROGRESSED_BEFORE_CUTOFF` / `없음`

### 보호 및 재진입
- **Pre-PROGRESSED Loss Guard**: `DISABLED`
- **보호 상태**: `{'phase': 'PRE_PROGRESSED', 'loss_guard_state': 'DISABLED', 'loss_guard_threshold_pct': None, 'first_progressed_date': None, 'lifecycle_class': 'NEVER_PROGRESSED', 'exit3_state': 'MONITORING', 'exit4_state': 'MONITORING'}`
- **재진입 상태**: `{'enabled': True, 'cooldown': 'NONE', 'maximum_reentries': 'NONE', 'completed_trade_count': 0, 'current_trade_sequence': 1, 'next_entry_sequence': 2}`

### Julia V1 전략 거래 이력
| 순번 | 진입 신호일 | 진입 체결일 | 진입 시가 | 청산 유형 | 청산 체결일 | 청산 시가 | 수익률 | 상태 |
|:---:|:---:|:---:|---:|---|:---:|---:|---:|:---:|
| 1 | `2023-06-23` | `2023-06-26` | 21,930원 | `NO_PROGRESSED_BEFORE_CUTOFF` | `-` | - | +73.03% | `OPEN_AT_CUTOFF` |

> V00 lifecycle evaluator를 그대로 사용했고, V1 정책에서 Pre-PROGRESSED Loss Guard를 비활성화했어. 과거 거래는 미래 수익을 보장하지 않아.

---
## 3. Pattern A FAST 현재 신호 (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **기준 주 (As-Of)**: `2026-10-02`
- **FAST Score**: `69.12`
- **Score Availability**: `READY`
- **FAST Stage**: `WATCH`
- **Stage Availability**: `READY`
- **Monthly Regime**: `PERMITTED_REGIME`
- **Daily Risk**: `NORMAL`
- **해석**: FAST 기준 명확한 초기 상승 전환 구조가 아직 확인되지 않았습니다.

> Pattern A FAST는 Pattern A와 독립적인 실험적(Experimental) 조기 신호이며, Pattern A Score/Stage/Candidate/Production Ranking에 영향을 주지 않습니다. 두 모델의 Score를 합산하거나 상대 우열을 계산하지 않습니다.

---

## 4. Pattern A Monthly History — 최근 12개월 월별 추이 (Recent 12M Trajectory)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available |
|---|---:|---:|---|---|---|
| 2025-09-30 | 34,495 | 100.00 | EARLY_TREND | candidate | True |
| 2025-10-31 | 35,875 | 100.00 | TRANSITION | candidate | True |
| 2025-11-28 | 36,795 | 100.00 | TRANSITION | candidate | True |
| 2025-12-30 | 36,760 | 100.00 | TRANSITION | candidate | True |
| 2026-01-30 | 37,045 | 93.66 | TRANSITION | candidate | True |
| 2026-02-27 | 37,360 | 93.65 | TRANSITION | candidate | True |
| 2026-03-31 | 36,760 | 92.45 | TRANSITION | candidate | True |
| 2026-04-30 | 38,980 | 91.67 | TRANSITION | candidate | True |
| 2026-05-29 | 41,925 | 90.99 | EARLY_TREND | candidate | True |
| 2026-06-30 | 42,605 | 99.12 | EARLY_TREND | candidate | True |
| 2026-07-31 | 39,520 | 98.11 | TRANSITION | candidate | True |
| 2026-08-31 | 38,805 | 88.43 | TRANSITION | candidate | True |
| 2026-09-30 | 38,040 | 86.53 | TRANSITION | candidate | True |

- **점수 변화 모멘텀**: 1M (-1.90), 3M (-12.59), 6M (-5.92), 12M (-13.47)

---

## 5. Pattern A 국면 전환 이력 (Stage Transition History)
- **2019-07-31**: `UNAVAILABLE` -> `TRANSITION`
- **2020-06-30**: `TRANSITION` -> `EARLY_TREND`
- **2020-09-29**: `EARLY_TREND` -> `TRANSITION`
- **2021-01-29**: `TRANSITION` -> `EARLY_TREND`
- **2021-03-31**: `EARLY_TREND` -> `TRANSITION`
- **2021-12-30**: `TRANSITION` -> `PROGRESSED`
- **2022-03-31**: `PROGRESSED` -> `TRANSITION`
- **2024-01-31**: `TRANSITION` -> `EARLY_TREND`
- **2024-04-30**: `EARLY_TREND` -> `TRANSITION`
- **2024-12-30**: `TRANSITION` -> `EARLY_TREND`
- **2025-01-31**: `EARLY_TREND` -> `TRANSITION`
- **2025-07-31**: `TRANSITION` -> `EARLY_TREND`
- **2025-08-29**: `EARLY_TREND` -> `TRANSITION`
- **2025-09-30**: `TRANSITION` -> `EARLY_TREND`
- **2025-10-31**: `EARLY_TREND` -> `TRANSITION`
- **2026-05-29**: `TRANSITION` -> `EARLY_TREND`
- **2026-07-31**: `EARLY_TREND` -> `TRANSITION`

---

## 6. Pattern A FAST Weekly History (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **History 시작 주**: `2025-10-10`
- **History 종료 주**: `2026-10-02`
- **총 주별 관측 개수**: `49주`

| 기준 주 (Week Ending) | 종가 | FAST Score | Score Availability | FAST Stage | Stage Availability | Monthly Regime | Daily Risk |
|---|---:|---:|---|---|---|---|---|
| 2025-10-10 | 35,320 | 75.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-10-17 | 34,745 | 75.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-10-24 | 35,925 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-10-31 | 35,875 | 75.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-07 | 36,125 | 75.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-14 | 36,200 | 75.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-21 | 35,635 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-28 | 36,795 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-05 | 37,210 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-12 | 37,560 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-19 | 37,040 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-26 | 36,880 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-02 | 36,740 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-09 | 37,395 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-16 | 38,180 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-23 | 37,810 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-30 | 37,045 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-06 | 37,245 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-13 | 37,190 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-20 | 37,470 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-02-27 | 37,360 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-03-06 | 37,565 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-03-13 | 37,115 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-03-20 | 36,915 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-03-27 | 36,805 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-04-03 | 36,970 | 63.85 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | ELEVATED |
| 2026-04-10 | 37,700 | 69.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-04-17 | 39,190 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-04-24 | 39,370 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-05-08 | 40,070 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-05-15 | 40,880 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-05-22 | 41,625 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-05-29 | 41,925 | 72.10 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-05 | 42,665 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-12 | 41,410 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-19 | 42,090 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-06-26 | 41,550 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-07-03 | 42,520 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-07-10 | 41,760 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-07-24 | 40,110 | 72.60 | READY | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-07-31 | 39,520 | 82.05 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-08-07 | 40,295 | 82.05 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-08-14 | 40,660 | 82.05 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-08-21 | 39,280 | 78.55 | READY | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-08-28 | 39,175 | 73.30 | READY | WATCH | READY | PERMITTED_REGIME | ELEVATED |
| 2026-09-04 | 38,685 | 72.42 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-09-11 | 37,750 | 68.22 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-09-18 | 38,935 | 71.38 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-10-02 | 37,945 | 69.12 | READY | WATCH | READY | PERMITTED_REGIME | NORMAL |

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
- **규칙 기반 해석**: 최근 거래대금이 특정 방향성 없이 기간별로 혼조세를 나타내고 있습니다. (5일: 16.74억원, 20일: 10.79억원, 60일: 12.74억원)
| 구간 | 평균 거래대금 |
|---|---:|
| 1D | 7.37억원 |
| 5D | 16.74억원 |
| 10D | 14.31억원 |
| 20D | 10.79억원 |
| 60D | 12.74억원 |
- **20일 평균 거래대금**: `10.79억원`
- **60일 평균 거래대금**: `12.74억원`
- **단기 확장 비율 (5D / 20D)**: `1.55배`
- **중기 확장 비율 (20D / 60D)**: `0.85배`

---

## 9. Pattern A 전체 월별 이력 (Full Monthly History)
- **전체 관측 시작월**: `2016-08-31`
- **전체 관측 종료월**: `2026-09-30`
- **최초 Pattern A 산출월**: `2019-07-31`
- **총 월별 관측 개수**: `122개월` (Pattern A 산출 가능: `87개월`)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available | Reason |
|---|---:|---:|---|---|---|---|
| 2016-08-31 | 10,015 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-09-30 | 9,900 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-10-31 | 10,115 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-11-30 | 10,535 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2016-12-29 | 11,145 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-01-31 | 10,990 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-02-28 | 10,955 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-03-31 | 10,960 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-04-28 | 11,345 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-05-31 | 11,355 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-06-30 | 11,675 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-07-31 | 11,680 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-08-31 | 11,700 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-09-29 | 12,205 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-10-31 | 12,225 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-11-30 | 12,100 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2017-12-28 | 12,145 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-01-31 | 12,725 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-02-28 | 12,530 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-03-30 | 11,840 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-04-30 | 12,155 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-05-31 | 12,235 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-06-29 | 12,565 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-07-31 | 13,025 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-08-31 | 13,215 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-09-28 | 13,160 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-10-31 | 12,320 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-11-30 | 12,420 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2018-12-28 | 11,300 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-01-31 | 12,200 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-02-28 | 12,800 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-03-29 | 12,960 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-04-30 | 13,905 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-05-31 | 13,305 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-06-28 | 13,725 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2019-07-31 | 14,290 | 91.28 | TRANSITION | candidate | True | - |
| 2019-08-30 | 14,110 | 92.11 | TRANSITION | candidate | True | - |
| 2019-09-30 | 14,225 | 91.91 | TRANSITION | candidate | True | - |
| 2019-10-31 | 14,355 | 82.49 | TRANSITION | candidate | True | - |
| 2019-11-29 | 14,940 | 83.59 | TRANSITION | candidate | True | - |
| 2019-12-30 | 15,160 | 93.54 | TRANSITION | candidate | True | - |
| 2020-01-31 | 15,545 | 94.44 | TRANSITION | candidate | True | - |
| 2020-02-28 | 14,140 | 91.07 | TRANSITION | candidate | True | - |
| 2020-03-31 | 12,475 | 78.03 | TRANSITION | candidate | True | - |
| 2020-04-29 | 13,715 | 75.52 | TRANSITION | candidate | True | - |
| 2020-05-29 | 14,560 | 77.03 | TRANSITION | candidate | True | - |
| 2020-06-30 | 14,210 | 88.46 | EARLY_TREND | candidate | True | - |
| 2020-07-31 | 15,165 | 89.55 | EARLY_TREND | candidate | True | - |
| 2020-08-31 | 16,125 | 90.45 | EARLY_TREND | candidate | True | - |
| 2020-09-29 | 15,290 | 91.06 | TRANSITION | candidate | True | - |
| 2020-10-30 | 14,175 | 82.19 | TRANSITION | candidate | True | - |
| 2020-11-30 | 15,855 | 83.08 | TRANSITION | candidate | True | - |
| 2020-12-30 | 16,225 | 97.12 | TRANSITION | candidate | True | - |
| 2021-01-29 | 16,535 | 100.00 | EARLY_TREND | candidate | True | - |
| 2021-02-26 | 17,185 | 100.00 | EARLY_TREND | candidate | True | - |
| 2021-03-31 | 17,725 | 100.00 | TRANSITION | candidate | True | - |
| 2021-04-30 | 18,485 | 100.00 | TRANSITION | candidate | True | - |
| 2021-05-31 | 18,700 | 100.00 | TRANSITION | candidate | True | - |
| 2021-06-30 | 19,110 | 100.00 | TRANSITION | candidate | True | - |
| 2021-07-30 | 19,800 | 99.88 | TRANSITION | candidate | True | - |
| 2021-08-31 | 20,640 | 99.47 | TRANSITION | candidate | True | - |
| 2021-09-30 | 20,335 | 98.84 | TRANSITION | candidate | True | - |
| 2021-10-29 | 20,785 | 97.25 | TRANSITION | candidate | True | - |
| 2021-11-30 | 20,865 | 94.41 | TRANSITION | candidate | True | - |
| 2021-12-30 | 21,700 | 75.68 | PROGRESSED | late | True | - |
| 2022-01-28 | 20,265 | 82.92 | PROGRESSED | late | True | - |
| 2022-02-28 | 20,025 | 83.46 | PROGRESSED | late | True | - |
| 2022-03-31 | 21,480 | 86.60 | TRANSITION | candidate | True | - |
| 2022-04-29 | 20,600 | 97.40 | TRANSITION | candidate | True | - |
| 2022-05-31 | 19,955 | 90.62 | TRANSITION | candidate | True | - |
| 2022-06-30 | 19,000 | 87.87 | TRANSITION | candidate | True | - |
| 2022-07-29 | 20,510 | 86.95 | TRANSITION | candidate | True | - |
| 2022-08-31 | 20,365 | 86.95 | TRANSITION | candidate | True | - |
| 2022-09-30 | 19,605 | 87.19 | TRANSITION | candidate | True | - |
| 2022-10-31 | 20,925 | 89.29 | TRANSITION | candidate | True | - |
| 2022-11-30 | 20,135 | 89.53 | TRANSITION | candidate | True | - |
| 2022-12-29 | 18,785 | 87.12 | TRANSITION | candidate | True | - |
| 2023-01-31 | 19,600 | 82.05 | TRANSITION | candidate | True | - |
| 2023-02-28 | 20,720 | 80.96 | TRANSITION | candidate | True | - |
| 2023-03-31 | 20,730 | 82.00 | TRANSITION | candidate | True | - |
| 2023-04-28 | 21,715 | 82.34 | TRANSITION | candidate | True | - |
| 2023-05-31 | 21,480 | 80.93 | TRANSITION | candidate | True | - |
| 2023-06-30 | 22,385 | 81.30 | TRANSITION | candidate | True | - |
| 2023-07-31 | 22,400 | 80.18 | TRANSITION | candidate | True | - |
| 2023-08-31 | 22,850 | 79.34 | TRANSITION | candidate | True | - |
| 2023-09-27 | 22,155 | 77.13 | TRANSITION | candidate | True | - |
| 2023-10-31 | 21,310 | 73.89 | TRANSITION | candidate | True | - |
| 2023-11-30 | 22,505 | 73.00 | TRANSITION | candidate | True | - |
| 2023-12-28 | 23,725 | 73.39 | TRANSITION | candidate | True | - |
| 2024-01-31 | 24,835 | 87.80 | EARLY_TREND | candidate | True | - |
| 2024-02-29 | 25,595 | 93.36 | EARLY_TREND | candidate | True | - |
| 2024-03-29 | 26,885 | 97.04 | EARLY_TREND | candidate | True | - |
| 2024-04-30 | 26,740 | 97.20 | TRANSITION | candidate | True | - |
| 2024-05-31 | 27,400 | 97.55 | TRANSITION | candidate | True | - |
| 2024-06-28 | 28,160 | 99.87 | TRANSITION | candidate | True | - |
| 2024-07-31 | 28,130 | 100.00 | TRANSITION | candidate | True | - |
| 2024-08-30 | 28,015 | 98.86 | TRANSITION | candidate | True | - |
| 2024-09-30 | 28,310 | 89.21 | TRANSITION | candidate | True | - |
| 2024-10-31 | 29,495 | 88.71 | TRANSITION | candidate | True | - |
| 2024-11-29 | 30,540 | 98.22 | TRANSITION | candidate | True | - |
| 2024-12-30 | 31,820 | 99.12 | EARLY_TREND | candidate | True | - |
| 2025-01-31 | 32,340 | 99.16 | TRANSITION | candidate | True | - |
| 2025-02-28 | 31,955 | 98.56 | TRANSITION | candidate | True | - |
| 2025-03-31 | 30,540 | 89.57 | TRANSITION | candidate | True | - |
| 2025-04-30 | 29,730 | 89.08 | TRANSITION | candidate | True | - |
| 2025-05-30 | 30,610 | 88.49 | TRANSITION | candidate | True | - |
| 2025-06-30 | 31,280 | 88.72 | TRANSITION | candidate | True | - |
| 2025-07-31 | 32,850 | 91.53 | EARLY_TREND | candidate | True | - |
| 2025-08-29 | 33,410 | 100.00 | TRANSITION | candidate | True | - |
| 2025-09-30 | 34,495 | 100.00 | EARLY_TREND | candidate | True | - |
| 2025-10-31 | 35,875 | 100.00 | TRANSITION | candidate | True | - |
| 2025-11-28 | 36,795 | 100.00 | TRANSITION | candidate | True | - |
| 2025-12-30 | 36,760 | 100.00 | TRANSITION | candidate | True | - |
| 2026-01-30 | 37,045 | 93.66 | TRANSITION | candidate | True | - |
| 2026-02-27 | 37,360 | 93.65 | TRANSITION | candidate | True | - |
| 2026-03-31 | 36,760 | 92.45 | TRANSITION | candidate | True | - |
| 2026-04-30 | 38,980 | 91.67 | TRANSITION | candidate | True | - |
| 2026-05-29 | 41,925 | 90.99 | EARLY_TREND | candidate | True | - |
| 2026-06-30 | 42,605 | 99.12 | EARLY_TREND | candidate | True | - |
| 2026-07-31 | 39,520 | 98.11 | TRANSITION | candidate | True | - |
| 2026-08-31 | 38,805 | 88.43 | TRANSITION | candidate | True | - |
| 2026-09-30 | 38,040 | 86.53 | TRANSITION | candidate | True | - |

---

## 10. 데이터 품질 및 신원 (Data Quality & Provenance)
- **로컬 일봉 캐시**: `정상 로드 (2483행)`
- **데이터 기간**: `2016-08-17` ~ `2026-10-02`
- **완성 월봉 수**: `122개월`
- **데이터 품질 상태**: `OK`
- **적용 계약**: Score(`pattern_a_score_v0.2`), Stage(`pattern_a_stage_v0.1`), Strategy(`PATTERN_A_FAST_FINAL_STRATEGY_V02`), Investability(`phase10`), Flow(`phase11`)
- **외부 네트워크 요청**: `0회` (Zero Network Request)

---

*주의 (Disclaimer): 본 리포트는 기술적 지표 및 과거 수급/유동성 통계에 기반한 설명 자료이며, 매수/매도 추천이나 목표가를 제시하지 않습니다.*
