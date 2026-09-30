# [KODEX 인도Nifty50 (453810)] 종목 리포트 v0.6

- **시장 구분 (Listing Market)**: `KOSPI`
- **자산 유형 (Asset Type)**: `ETF`
- **분석 기준일 (Requested As-Of)**: `2026-09-25`
- **신선도 기준일 (Reference Market Date)**: `2026-09-23`
- **리포트 상태**: `PARTIAL`

---

## 0. 핵심 요약 (Executive Summary)
> **KODEX 인도Nifty50(453810)의 공식 ETF36 Julia V1 리포트야. 분석 기준일 2026-09-25, 실제 시장 데이터 기준일 2026-09-23야.**
>
> - Julia V1: WAIT
> - ETF 적격성: PASS · raw 종가 11125.0원 · 20D 평균 거래량 103774.9주
> - 펀더멘털: NOT_APPLICABLE (일반기업 Fundamentals V1 적용 대상 아님)
> - 현재 Pattern A Score는 52.06점(Stage: BASE, Candidate: NO)입니다.
> - 외국인 수급: 외국인 수급 데이터가 준비되지 않아 수급 분석을 제공할 수 없습니다.
> - 시장 상대강도: Phase12 Market RS는 KOSPI/KOSDAQ 보통주(COMMON)를 대상으로 정의되어 이 종목에는 적용되지 않습니다.
> - 업종 상대강도: Sector RS는 KOSPI/KOSDAQ COMMON 종목을 대상으로 하므로 이 종목에는 적용되지 않습니다.
> - 거래대금 추세: 최근 거래대금이 지속 감소(둔화)하는 흐름입니다. 5일 평균 거래대금(7.41억원)이 20일 평균(11.79억원) 및 60일 평균(16.09억원)을 밑돌고 있습니다.

KODEX 인도Nifty50은(는) 기준일 2026-09-23에 Julia V1 상태 WAIT야. ETF PIT 적격성은 PASS이며 시가총액과 Phase10 Investability는 이 ETF 전략의 적격성 기준이 아니야. 공통 기술·수급 섹션은 기존 Stock Report 계산을 재사용했어.

---

## 1. 현재 기술적 국면 및 ETF 적격성 스냅샷
- **Pattern A Score / 국면**: `52.06` / `BASE`
- **Official ETF36 membership**: `PASS`
- **상장일 / 상장 2년 요건**: `2023-04-21` / `PASS`
- **기준일 raw 종가**: `11125.0원` (최소 1,000원: `PASS`)
- **20 KRX 거래일 평균 raw 거래량**: `103774.9주` (최소 10,000주: `PASS`)
- **20일 창**: `2026-08-27` ~ `2026-09-23`; 신호일 포함: `True`
- **ETF 적격성**: `PASS` (`ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`)
- **Strategy-ready / clean-ready / 유효 시작일**: `2026-04-03 / 2026-04-03 / 2026-04-03`
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
| 상장 2년 이상 | `2023-04-21` | `PASS` |
| raw 종가 ≥ 1,000원 | `11310.0` | `PASS` |
| 20 KRX 거래일 평균 raw 거래량 ≥ 10,000주 | `108408.95` | `PASS` |
| Strategy-ready / clean-ready | `2026-04-03 / 2026-04-03` | `PASS` |
| Pattern A 국면 | `BASE` | `FAIL` |
| FAST 주별 트리거 | `WATCH (READY)` | `FAIL` |
| 월간 국면 | `EARLY_REGIME` | `FAIL` |
| 일봉 리스크 | `NORMAL` | `PASS` |
| FAST 점수 | `PARTIAL` | `PASS` |
| 미보유 상태 | `FLAT` | `PASS` |
| 다음 실제 KRX 거래일 raw 시가 | `2026-09-21 / 11310.0` | `PASS` |

- **신규 진입 조건 전체 판정**: `FAIL`
- **미충족 조건**: `PATTERN_A_TRANSITION_OR_EARLY_TREND, FAST_TRIGGER_READY, MONTHLY_REGIME_PERMITTED, SIGNAL_DATE_IS_CURRENT_REFERENCE`

### 현재 포지션
- 기준일 현재 열린 Julia V1 포지션이 없어.

### 보호 및 재진입
- **Pre-PROGRESSED Loss Guard**: `DISABLED`
- **보호 상태**: `열린 포지션 없음`
- **재진입 상태**: `{'enabled': True, 'cooldown': 'NONE', 'maximum_reentries': 'NONE', 'completed_trade_count': 0, 'current_trade_sequence': None, 'next_entry_sequence': 1}`

- Julia V1 거래 이력이 없어.

> V00 lifecycle evaluator를 그대로 사용했고, V1 정책에서 Pre-PROGRESSED Loss Guard를 비활성화했어. 과거 거래는 미래 수익을 보장하지 않아.

---
## 3. Pattern A FAST 현재 신호 (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **기준 주 (As-Of)**: `2026-09-18`
- **FAST Score**: `49.38`
- **Score Availability**: `PARTIAL`
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
| 2025-08-29 | 13,250 | N/A | UNAVAILABLE | insufficient_data | False |
| 2025-09-30 | 13,305 | N/A | UNAVAILABLE | insufficient_data | False |
| 2025-10-31 | 14,080 | N/A | UNAVAILABLE | insufficient_data | False |
| 2025-11-28 | 14,635 | N/A | UNAVAILABLE | insufficient_data | False |
| 2025-12-30 | 14,105 | N/A | UNAVAILABLE | insufficient_data | False |
| 2026-01-30 | 13,450 | N/A | UNAVAILABLE | insufficient_data | False |
| 2026-02-27 | 13,560 | N/A | UNAVAILABLE | insufficient_data | False |
| 2026-03-31 | 12,355 | 72.31 | TRANSITION | candidate | True |
| 2026-04-30 | 12,545 | 67.98 | TRANSITION | candidate | True |
| 2026-05-29 | 12,625 | 63.55 | BASE | watch | True |
| 2026-06-30 | 13,280 | 62.55 | BASE | watch | True |
| 2026-07-31 | 12,270 | 58.29 | BASE | watch | True |
| 2026-08-31 | 11,620 | 52.06 | BASE | watch | True |

- **점수 변화 모멘텀**: 1M (-6.23), 3M (-11.49), 6M (N/A), 12M (N/A)

---

## 5. Pattern A 국면 전환 이력 (Stage Transition History)
- **2026-03-31**: `UNAVAILABLE` -> `TRANSITION`
- **2026-05-29**: `TRANSITION` -> `BASE`

---

## 6. Pattern A FAST Weekly History (`Experimental / Early Signal`)
- **Contract**: `HIERARCHICAL_V01` (`PHASE_13_RESEARCH_CLOSED / HIERARCHICAL_V01_PRODUCTION_HOLD`)
- **History 시작 주**: `2025-09-26`
- **History 종료 주**: `2026-09-18`
- **총 주별 관측 개수**: `49주`

| 기준 주 (Week Ending) | 종가 | FAST Score | Score Availability | FAST Stage | Stage Availability | Monthly Regime | Daily Risk |
|---|---:|---:|---|---|---|---|---|
| 2025-09-26 | 13,385 | 73.62 | PARTIAL | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-10-10 | 13,665 | 73.62 | PARTIAL | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2025-10-17 | 14,085 | 77.12 | PARTIAL | TREND | READY | PERMITTED_REGIME | NORMAL |
| 2025-10-24 | 14,405 | 77.12 | PARTIAL | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2025-10-31 | 14,080 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-07 | 14,205 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-14 | 14,355 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-21 | 14,725 | 69.18 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-11-28 | 14,635 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-05 | 14,520 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-12 | 14,445 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-19 | 14,465 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2025-12-26 | 14,245 | 69.68 | PARTIAL | TRIGGER | READY | LATE_OR_EXTENDED_REGIME | NORMAL |
| 2026-01-02 | 14,330 | 79.13 | PARTIAL | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-09 | 14,185 | 79.13 | PARTIAL | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-16 | 14,245 | 74.12 | PARTIAL | TRIGGER | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-23 | 13,740 | 74.12 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-01-30 | 13,450 | 70.62 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-02-06 | 14,055 | 74.12 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-02-13 | 13,765 | 74.12 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-02-20 | 13,810 | 68.12 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-02-27 | 13,560 | 68.12 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-03-06 | 13,425 | 63.63 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-03-13 | 12,815 | 51.38 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-03-20 | 12,700 | 51.38 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-03-27 | 12,420 | 51.38 | PARTIAL | WATCH | READY | PERMITTED_REGIME | NORMAL |
| 2026-04-03 | 12,400 | 40.88 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-04-10 | 12,970 | 40.88 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-04-17 | 13,085 | 46.88 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-04-24 | 12,755 | 46.88 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-05-08 | 12,720 | 40.88 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-05-15 | 12,535 | 40.88 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-05-22 | 12,710 | 49.38 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-05-29 | 12,625 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-06-05 | 12,750 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-06-12 | 12,525 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-06-19 | 13,000 | 54.37 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-06-26 | 13,125 | 54.37 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-07-03 | 13,190 | 73.62 | PARTIAL | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-07-10 | 12,875 | 64.87 | PARTIAL | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-07-24 | 12,160 | 59.88 | PARTIAL | SETUP | READY | PERMITTED_REGIME | NORMAL |
| 2026-07-31 | 12,270 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-08-07 | 12,310 | 54.37 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-08-14 | 12,115 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-08-21 | 11,795 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-08-28 | 11,645 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-09-04 | 11,540 | 49.38 | PARTIAL | SETUP | READY | EARLY_REGIME | NORMAL |
| 2026-09-11 | 10,990 | 49.38 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |
| 2026-09-18 | 11,310 | 49.38 | PARTIAL | WATCH | READY | EARLY_REGIME | NORMAL |

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
- **규칙 기반 해석**: 최근 거래대금이 지속 감소(둔화)하는 흐름입니다. 5일 평균 거래대금(7.41억원)이 20일 평균(11.79억원) 및 60일 평균(16.09억원)을 밑돌고 있습니다.
| 구간 | 평균 거래대금 |
|---|---:|
| 1D | 8.14억원 |
| 5D | 7.41억원 |
| 10D | 9.20억원 |
| 20D | 11.79억원 |
| 60D | 16.09억원 |
- **20일 평균 거래대금**: `11.79억원`
- **60일 평균 거래대금**: `16.09억원`
- **단기 확장 비율 (5D / 20D)**: `0.63배`
- **중기 확장 비율 (20D / 60D)**: `0.73배`

---

## 9. Pattern A 전체 월별 이력 (Full Monthly History)
- **전체 관측 시작월**: `2023-04-28`
- **전체 관측 종료월**: `2026-08-31`
- **최초 Pattern A 산출월**: `2026-03-31`
- **총 월별 관측 개수**: `41개월` (Pattern A 산출 가능: `6개월`)

| 기준일 | 종가 | Pattern A Score | Stage | Candidate State | Data Available | Reason |
|---|---:|---:|---|---|---|---|
| 2023-04-28 | 10,315 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-05-31 | 10,440 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-06-30 | 10,870 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-07-31 | 10,700 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-08-31 | 10,875 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-09-27 | 11,200 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-10-31 | 10,855 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-11-30 | 10,900 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2023-12-28 | 11,800 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-01-31 | 12,170 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-02-29 | 12,295 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-03-29 | 12,595 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-04-30 | 13,050 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-05-31 | 13,000 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-06-28 | 13,870 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-07-31 | 14,200 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-08-30 | 13,930 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-09-30 | 14,030 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-10-31 | 13,740 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-11-29 | 13,690 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2024-12-30 | 14,145 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-01-31 | 13,475 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-02-28 | 12,755 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-03-31 | 13,665 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-04-30 | 13,890 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-05-30 | 13,640 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-06-30 | 13,745 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-07-31 | 13,370 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-08-29 | 13,250 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-09-30 | 13,305 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-10-31 | 14,080 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-11-28 | 14,635 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2025-12-30 | 14,105 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2026-01-30 | 13,450 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2026-02-27 | 13,560 | N/A | UNAVAILABLE | insufficient_data | False | INSUFFICIENT_LOOKBACK |
| 2026-03-31 | 12,355 | 72.31 | TRANSITION | candidate | True | - |
| 2026-04-30 | 12,545 | 67.98 | TRANSITION | candidate | True | - |
| 2026-05-29 | 12,625 | 63.55 | BASE | watch | True | - |
| 2026-06-30 | 13,280 | 62.55 | BASE | watch | True | - |
| 2026-07-31 | 12,270 | 58.29 | BASE | watch | True | - |
| 2026-08-31 | 11,620 | 52.06 | BASE | watch | True | - |

---

## 10. 데이터 품질 및 신원 (Data Quality & Provenance)
- **로컬 일봉 캐시**: `정상 로드 (834행)`
- **데이터 기간**: `2023-04-21` ~ `2026-09-23`
- **완성 월봉 수**: `41개월`
- **데이터 품질 상태**: `OK`
- **적용 계약**: Score(`pattern_a_score_v0.2`), Stage(`pattern_a_stage_v0.1`), Strategy(`PATTERN_A_FAST_FINAL_STRATEGY_V02`), Investability(`phase10`), Flow(`phase11`)
- **외부 네트워크 요청**: `0회` (Zero Network Request)

---

*주의 (Disclaimer): 본 리포트는 기술적 지표 및 과거 수급/유동성 통계에 기반한 설명 자료이며, 매수/매도 추천이나 목표가를 제시하지 않습니다.*
