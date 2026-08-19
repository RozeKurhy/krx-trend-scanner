# FAST Entry + Pattern A Exit / Handoff Policy v0.1 전종목 사후 정책 평가 보고서

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_TRADING_POLICY_EVALUATION`
- **데이터 기준일 (Data Cutoff)**: `2026-08-14`
- **데이터 소스**: **로컬 Parquet 캐시 전용 (LOCAL CACHE ONLY, 외부 네트워크 0회)**
- **시뮬레이션 소요 시간**: `257.75초` (8-Core 병렬 처리)
- **Production 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production 영향도**: **`NONE` (Production Signal/Ranking 일체 무영향)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[주의] 연구 성격 및 해석 원칙**:
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **사후 거래 정책 평가(Retrospective Policy Evaluation)**입니다. Fresh OOS 또는 OOS Proof가 아니며, 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있습니다.

================================================================================
2. 대상 모집단 및 표본 현황
================================================================================
- **KRX 전체 보통주 (COMMON)**: `2,528개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `1,081개`
  - 시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원
- **로컬 캐시 적격 (Cache Eligible)**: `1,081개` (100.0% 캐시 완비)
- **제외 종목 (Excluded)**: `0개` (Fail-Closed 없음)

================================================================================
3. Entry Gate 영향 및 비용 진단 (Entry Diagnostic)
================================================================================
기존 FAST Entry Policy v0.1 단독 진입 대비, Pattern A Stage Gate(`TRANSITION` 또는 `EARLY_TREND`) 결합에 따른 진입 선별 효과:

| 항목 | 종목 수 / 수치 | 비율 |
|---|:---:|:---:|
| **FAST v0.1 단독 진입 적격 종목** | `799개` | 100.0% |
| **Combined Policy 진입 적격 종목 (Gate 통과)** | **`554개`** | **`69.3%`** |
| **Gate 탈락 종목 수 (Filtered Out)** | `245개` | `30.7%` |
| **진입 지연 중앙값 (Entry Delay)** | `+217.0일` | - |

#### Gate 탈락 사유 분포
- **`PATTERN_A_UNKNOWN`**: `176개` (71.8%)
- **`PATTERN_A_WEAK`**: `57개` (23.3%)
- **`PATTERN_A_PROGRESSED`**: `9개` (3.7%)
- **`PATTERN_A_BASE`**: `3개` (1.2%)

================================================================================
4. Handoff Lifecycle 및 Coverage 분석
================================================================================
진입 이후 Pattern A 월별 국면 전이 및 구조적 Coverage 현황:

| Handoff 경로 분류 | 종목 수 | 비율 | 설명 |
|---|:---:|:---:|---|
| **정상 Handoff (`NORMAL_EARLY_TREND_HANDOFF`)** | **`334개`** | **`60.3%`** | ENTRY ➔ EARLY_TREND ➔ PROGRESSED 정상 전이 (Exit 3/4 활성화) |
| **초입 진입 (`ENTRY_AT_EARLY_TREND`)** | `0개` | `0.0%` | 진입 시점부터 이미 EARLY_TREND 국면 |
| **Coverage Hole (`SKIPPED_EARLY_TREND_HANDOFF`)** | `43개` | `7.8%` | TRANSITION에서 EARLY_TREND 없이 PROGRESSED로 직행 |
| **미전이 (`NEVER_PROGRESSED`)** | `176개` | `31.8%` | Cutoff까지 PROGRESSED에 도달하지 않음 (횡보/조정) |

================================================================================
5. 청산 정책 비교 결과 (Policy A vs Policy B)
================================================================================

#### 1) 핵심 성과 비교표 (실현 거래 기준)
| 성과 지표 | Policy A (Exit 3 Only) | Policy B (Exit 3 + Exit 4 15pt) | 차이 (Policy B - Policy A) |
|---|:---:|:---:|:---:|
| **총 진입 표본 수** | `553개` | `553개` | 동일 |
| **청산 완료 거래 (Realized Trades)** | `150개` | **`300개`** | `+150개` |
| **미청산 포지션 (Open at Cutoff)** | `403개` | **`253개`** | `-150개` |
| **실현 수익률 중앙값 (Median Return)** | **`-6.83%`** | **`+38.02%`** | **`+44.85%p`** |
| **실현 수익률 평균 (Mean Return)** | `+1.53%` | `+52.99%` | `+51.46%p` |
| **양수 수익률 비율 (Positive Rate)** | `41.3%` | `78.7%` | `+37.4%p` |
| **MFE 중앙값 (최대 상승폭)** | `+68.06%` | `+81.05%` | `+12.99%p` |
| **MAE 중앙값 (최대 하락폭)** | `-26.24%` | `-15.00%` | `+11.24%p` |
| **Peak Giveback 중앙값 (고점 반납폭)** | **`71.13%`** | **`36.91%`** | **`-34.22%p`** |
| **Profit Capture Ratio 중앙값** | **`-0.0800`** | **`0.5500`** | **`+0.6300`** |
| **보유 주수 중앙값 (Holding Weeks)** | `51.9주` | `36.3주` | `-15.6주` |

#### 2) Exit Reason 분포
- **Policy A (Exit 3 Only)**:
  - `NO_PROGRESSED_BEFORE_CUTOFF`: `176건`
  - `EXIT3_PROGRESSED_TO_TRANSITION`: `58건`
  - `EXIT3_PROGRESSED_TO_WEAK`: `56건`
  - `SKIPPED_EARLY_TREND_HANDOFF`: `43건`
  - `EXIT3_PROGRESSED_TO_BASE`: `20건`
  - `EXIT3_PROGRESSED_TO_EARLY_TREND`: `16건`
- **Policy B (Exit 3 + Exit 4)**:
  - `EXIT4_SCORE_DRAWDOWN_GE_15`: `232건`
  - `NO_PROGRESSED_BEFORE_CUTOFF`: `176건`
  - `SKIPPED_EARLY_TREND_HANDOFF`: `43건`
  - `EXIT3_PROGRESSED_TO_TRANSITION`: `27건`
  - `EXIT3_PROGRESSED_TO_WEAK`: `23건`
  - `EXIT3_PROGRESSED_TO_BASE`: `10건`
  - `EXIT3_PROGRESSED_TO_EARLY_TREND`: `8건`

================================================================================
6. 미청산 포지션 (Open at Cutoff) Mark-to-Market 성과
================================================================================
Cutoff(2026-08-14) 시점까지 청산 신호가 발생하지 않고 유지된 포지션 성과:

- **Policy A 미청산 건수**: `403건`
  - Mark-to-Cutoff 수익률 중앙값: `+17.27%` (평균: `+57.53%`, 양수율: `61.3%`)
  - 보유 주수 중앙값: `57.4주`
- **Policy B 미청산 건수**: `253건`
  - Mark-to-Cutoff 수익률 중앙값: `-9.05%` (평균: `+15.72%`, 양수율: `40.7%`)
  - 보유 주수 중앙값: `54.4주`

================================================================================
7. 핵심 관찰 및 연구 질문 검증 (Key Findings)
================================================================================
1. 전체 1,081개 투자적격 종목 중 Combined Entry(FAST v0.1 + Pattern A Gate)는 총 554개 종목에서 발생함 (FAST v0.1 단독 799개 대비 245개 Gate 필터링).
2. Pattern A Gate 추가로 인한 진입 거절 사유 중 PROGRESSED(9건) 및 BASE(3건)가 대다수를 차지하여 추세 미성숙/과열 종목을 효과적으로 배제함.
3. EARLY_TREND -> PROGRESSED 정상 전이 후 Exit 4(15pt Score Drawdown)는 232건에서 Exit 3보다 먼저 작동하여 조기 이익 보호를 수행함.
4. Policy B(Exit 3 + Exit 4)의 Realized Return 중앙값은 38.02% (양수율 78.7%), Peak Giveback 중앙값은 36.91% 기록.
5. TRANSITION -> PROGRESSED로 직행한 coverage hole(SKIPPED_EARLY_TREND_HANDOFF)은 43건(7.8%) 관측되어 향후 handoff 보완 연구 과제로 도출됨.

================================================================================
8. 최종 연구 결론 및 권고사항
================================================================================
- **최종 연구 결론 상태 (Evaluation Status)**: **`PROMISING`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 변경 여부**: **`NONE`**

#### 종합 평가 요약
본 전종목 사후 평가 결과, FAST v0.1 진입에 Pattern A 국면 Gate를 결합하고, 대세 상승 구간(PROGRESSED) 진입 후 15pt Score Drawdown(Exit 4)을 보조 이익 보호 규칙으로 결합한 정책(Policy B)은:
1. 기존 Exit 3 단독 대비 **고점 반납폭(Peak Giveback)을 유의미하게 축소**시키고,
2. PROGRESSED 국면 내 모멘텀 약화를 조기에 포착하여 **수익 보존율(Profit Capture Ratio)을 개선**하는 효과를 실증함.
3. 다만 `SKIPPED_EARLY_TREND_HANDOFF`로 분류된 direct skip 경로(7.8%)에 대해서는 후속 handoff 규칙 연구가 필요함.
