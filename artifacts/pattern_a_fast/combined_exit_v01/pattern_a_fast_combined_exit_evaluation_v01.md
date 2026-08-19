# FAST Entry + Pattern A Exit / Handoff Policy v0.1 전종목 사후 정책 평가 보고서 (Corrected v2)

================================================================================
1. 평가 개요 및 실행 환경
================================================================================
- **연구명**: FAST Entry + Pattern A Exit / Handoff Policy v0.1 Full Investable Universe Retrospective Evaluation (Corrected v2)
- **연구 분류 (Research Classification)**: `RETROSPECTIVE_TRADING_POLICY_EVALUATION`
- **평가 상태 (Evaluation State)**: **`CORRECTED_EVALUATION_COMPLETE`**
- **대체된 이전 커밋 (Superseded Commits)**:
  - `28e3e303687fc64d8156ebc5e153c2143bc5e400` (Original Evaluation, `SUPERSEDED`)
  - `99fcab5826279da7e252ac5e8ebe11aeffe33143` (Corrected v1, `SUPERSEDED`)
- **사전등록 기준 커밋 (Preregistration Authority)**: `42336365d0ce278b28d4790f63d48c375aea7b65` (`PREREGISTERED_BEFORE_EVALUATION`, 수정 없음)
- **데이터 기준일 (Data Cutoff)**: `2026-08-14`
- **데이터 소스**: **로컬 Parquet 캐시 전용 (LOCAL CACHE ONLY, 외부 네트워크 0회)**
- **시뮬레이션 소요 시간**: `250.96초` (8-Core 병렬 처리)
- **Production 상태**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**
- **Production 영향도**: **`NONE` (Production Code/Signal/Ranking 일체 무영향)**
- **테스트 실행 여부**: `Tests: NOT RUN`

> **[주의 및 연구 성격 명시]**:
> 본 평가는 2026-08-14 기준 Phase 10 투자 적격 보통주 유니버스의 과거 데이터를 사후적으로 시뮬레이션한 **사후 거래 정책 평가(Retrospective Policy Evaluation)**입니다. 통계적 유의성 검정(p-value, bootstrap 등)을 수행하지 않았으며, Fresh OOS 또는 OOS Proof가 아니므로 시점 고정 유니버스에 따른 생존 편향이 내재될 수 있습니다.

================================================================================
2. 대상 모집단 및 데이터 적격성 현황 (Population Diagnostics)
================================================================================
- **KRX 전체 보통주 (COMMON)**: `2,528개`
- **Phase 10 투자 적격 유니버스 (Investable)**: `1,081개`
  - 시가총액 ≥ 1,000억원 & 20일 평균 거래대금 ≥ 3억원
- **로컬 캐시 보유 종목 (Cache Present)**: `1,081개` (`100.0%`)
- **로컬 캐시 누락 종목 (Cache Missing)**: `0개`
- **평가 적격 종목 (Evaluation Eligible)**: `1,079개` (**`99.8%`**)
- **제외 종목 (Excluded)**: `2개` (`INSUFFICIENT_HISTORY` 2건: 60일 미만 이력)
- **시뮬레이션 경고 발생 종목 수**: `0개`

================================================================================
3. Entry Gate 영향 및 진입 신호 진단 (Entry Diagnostic)
================================================================================
FAST v0.1 단독 진입 신호 대비, Pattern A Stage Gate(`TRANSITION` 또는 `EARLY_TREND`) 결합에 따른 진입 신호 필터링 현황:

| 항목 | 종목 수 / 수치 | 비율 |
|---|:---:|:---:|
| **FAST v0.1 단독 신호 적격 종목** | `799개` | 100.0% |
| **Combined Policy 신호 적격 종목 (Gate 통과)** | `554개` | `69.3%` |
| **실제 체결 가능 진입 표본 (Executable Entries)** | **`553개`** | **`69.2%`** |
| **Cutoff 직전 미체결 신호 (Non-Executable)** | `1개` | `0.1%` |
| **Gate 탈락 종목 수 (Filtered Out)** | `245개` | `30.7%` |
| **Combined 진입 지연 중앙값 (Entry Delay)** | `+217.0일` | - |

#### 1) Gate 탈락 사유 분포
- **`PATTERN_A_UNAVAILABLE`**: `176개` (71.8%)
- **`PATTERN_A_WEAK`**: `57개` (23.3%)
- **`PATTERN_A_PROGRESSED`**: `9개` (3.7%)
- **`PATTERN_A_BASE`**: `3개` (1.2%)

#### 2) 진입 시점 국면 및 등급 분포 (체결 표본 기준)
- **진입 국면**: `TRANSITION` `484개` (87.5%), `EARLY_TREND` `69개` (12.5%)
- **진입 등급**: Grade A (`NORMAL` Risk) `395개` (71.4%), Grade B (`ELEVATED` Risk) `158개` (28.6%)

================================================================================
4. Handoff Lifecycle 4분류 분석 (Direct Handoff & Coverage)
================================================================================
진입 이후 Pattern A 월별 국면의 전이 경로를 4가지 상호 배타적 경로로 분류한 결과:

| Handoff 경로 분류 | 종목 수 | 비율 | 정의 및 Exit 활성화 여부 |
|---|:---:|:---:|---|
| **정상 직접 전이 (`NORMAL_EARLY_TREND_HANDOFF`)** | **`270개`** | **`48.8%`** | 직전 유효 국면이 EARLY_TREND이고 현재 국면이 PROGRESSED인 직접 전이 (Exit 3/4 활성화) |
| **직행 Coverage Hole (`SKIPPED_EARLY_TREND_HANDOFF`)** | **`32개`** | **`5.8%`** | EARLY_TREND를 한 번도 관찰하지 않은 상태에서 TRANSITION ➔ PROGRESSED로 직행 (Exit 미활성화, Open 유지) |
| **간접 도달 (`PROGRESSED_WITHOUT_DIRECT_HANDOFF`)** | **`75개`** | **`13.6%`** | PROGRESSED는 관찰되었으나 위 두 직접 전이 조건에 미해당 (Exit 미활성화, Open 유지) |
| **미도달 (`NEVER_PROGRESSED`)** | **`176개`** | **`31.8%`** | Cutoff까지 PROGRESSED를 단 한 번도 관찰하지 않음 (Exit 미활성화, Open 유지) |
| **합계 (Total Executable Entries)** | **`553개`** | **`100.0%`** | **합계 정합성 검증 완료 (`True`)** |

================================================================================
5. 동일 표본 1:1 Paired 청산 정책 비교 (Policy A vs Policy B)
================================================================================
동일한 `553개` 체결 포지션에 대해 각 정책의 Terminal Outcome(청산 완료 시 실현수익률, 미청산 시 Cutoff 시가평가수익률)을 1:1로 대응 비교한 결과:

| 성과 지표 | Policy A (Exit 3 Only) | Policy B (Exit 3 + Exit 4 15pt) | Paired Delta (Policy B - Policy A) |
|---|:---:|:---:|:---:|
| **평가 대상 표본 수 (Paired Entries)** | `553개` | `553개` | 동일 표본 1:1 대응 |
| **Terminal Return 분포 중앙값** | **`+6.65%`** | **`+15.05%`** | - |
| **개별 거래별 Paired Return Delta 중앙값** | - | - | **`+0.00%p`** |
| **Terminal Return 평균** | `+43.79%` | `+36.82%` | `-6.98%p` |
| **Policy B 우세 종목 수 (B Better)** | - | **`110개`** | **`19.9%`** |
| **동일 결과 종목 수 (Equal)** | - | `351개` | `63.5%` |
| **Policy A 우세 종목 수 (A Better)** | - | `92개` | `16.6%` |
| **Terminal Peak Giveback 분포 중앙값** | **`64.03%`** | **`43.23%`** | - |
| **개별 거래별 Paired Giveback Delta 중앙값** | - | - | **`+0.00%p`** |
| **Policy B 반납 축소 비율 (Lower Giveback)** | - | **`176개`** | **`31.8%`** |
| **Terminal MFE 중앙값** | `+73.16%` | `+65.78%` | `-7.38%p` |
| **Terminal MAE 중앙값** | `-23.94%` | `-21.05%` | `+2.89%p` |
| **보유 주수 중앙값 (Total Holding Weeks)** | `57.4주` | `45.6주` | `-11.8주` |

================================================================================
6. Exit 4 선제 청산 집단 Counterfactual 비교
================================================================================
Policy B에서 Exit 4(15pt Drawdown)가 선제 발동하여 청산된 `202개` 거래를 대상으로, Exit 4가 없었을 경우(Policy A 동일 거래의 사후 결과)와의 1:1 반사실 분석:

| 지표 | Policy B (Exit 4 실현 결과) | Policy A (Exit 4 부재 시 사후 결과) | 차이 (Policy B - Policy A) |
|---|:---:|:---:|:---:|
| **대상 표본 수 (Exit 4 Triggered)** | `202개` | `202개` | 동일 표본 |
| **수익률 중앙값 (Median Return)** | **`+60.06%`** | **`+47.53%`** | **`+7.43%p`** |
| **수익률 평균 (Mean Return)** | `+74.57%` | `+93.66%` | `-19.10%p` |
| **Policy B 실현 수익률 우세 비율** | - | - | **`54.5%` (`110개`)** |

================================================================================
7. 정책별 개별 청산 현황 및 보조 통계 (Auxiliary Statistics)
================================================================================

#### 1) Policy A (Exit 3 Only)
- **청산 완료 거래 (Realized)**: `113개` (실현 수익률 중앙값: `-4.82%`, Peak Giveback 중앙값: `83.92%`, 보유 주수 중앙값: `57.2주`)
- **미청산 포지션 (Open at Cutoff)**: `440개` (Mark-to-Cutoff 수익률 중앙값: `+14.29%`, 보유 주수 중앙값: `57.4주`)
- **Exit Reason 분포**:
  - `NO_PROGRESSED_BEFORE_CUTOFF`: `176건`
  - `NO_EXIT_BEFORE_CUTOFF`: `157건`
  - `PROGRESSED_WITHOUT_DIRECT_HANDOFF`: `75건`
  - `EXIT3_PROGRESSED_TO_WEAK`: `47건`
  - `EXIT3_PROGRESSED_TO_TRANSITION`: `40건`
  - `SKIPPED_EARLY_TREND_HANDOFF`: `32건`
  - `EXIT3_PROGRESSED_TO_EARLY_TREND`: `14건`
  - `EXIT3_PROGRESSED_TO_BASE`: `12건`

#### 2) Policy B (Exit 3 + Exit 4 15pt)
- **청산 완료 거래 (Realized)**: `243개` (실현 수익률 중앙값: `+48.83%`, Peak Giveback 중앙값: `34.43%`, 보유 주수 중앙값: `35.4주`)
- **미청산 포지션 (Open at Cutoff)**: `310개` (Mark-to-Cutoff 수익률 중앙값: `-4.09%`, 보유 주수 중앙값: `55.4주`)
- **Exit Reason 분포**:
  - `EXIT4_SCORE_DRAWDOWN_GE_15`: `202건`
  - `NO_PROGRESSED_BEFORE_CUTOFF`: `176건`
  - `PROGRESSED_WITHOUT_DIRECT_HANDOFF`: `75건`
  - `SKIPPED_EARLY_TREND_HANDOFF`: `32건`
  - `NO_EXIT_BEFORE_CUTOFF`: `27건`
  - `EXIT3_PROGRESSED_TO_WEAK`: `19건`
  - `EXIT3_PROGRESSED_TO_TRANSITION`: `11건`
  - `EXIT3_PROGRESSED_TO_EARLY_TREND`: `6건`
  - `EXIT3_PROGRESSED_TO_BASE`: `5건`

> *주의: Policy A와 B는 Realized 표본 크기(113개 vs 243개)가 서로 상이하므로, Realized-only 단독 통계는 보조 참고 자료로만 사용하며 정책 간 비교는 제5장 Paired Comparison을 정본으로 합니다.*

================================================================================
8. 핵심 관찰 (Key Observations)
================================================================================
1. 전체 1,081개 투자적격 종목 중 FAST v0.1 신호는 799개 종목에서 발생했고, Pattern A Gate 적용 시 Combined 진입 신호는 554개(553개 실제 체결)로 선별됨 (Gate 제거율 30.7%).
2. Gate 거절 신호의 대다수는 PATTERN_A_UNAVAILABLE(176건) 및 PATTERN_A_WEAK(57건)였음.
3. 동일한 553개 체결 포지션 전체에 대한 1:1 Paired Terminal Outcome 비교 결과, Policy B의 Terminal Return 분포 중앙값은 15.05%로 Policy A(6.65%) 대비 높았으며, 개별 거래별 Paired Return Delta 중앙값은 0.0%p (우세율 19.89%)를 기록함.
4. Exit 4(15pt Drawdown)가 선제 발동한 202건의 동일 거래 Counterfactual 비교에서, Policy B의 실현수익률 중앙값은 60.06%로 동일 거래 Policy A 사후 결과(47.53%) 대비 Paired Delta 중앙값 +7.43%p (우세율 54.46%)를 나타냄.
5. Handoff 4분류(합계 553건) 집계 결과: 정상 Handoff 270건(48.8%), TRANSITION 직행 Hole 32건(5.8%), 간접 도달 75건(13.6%), 미도달 176건(31.8%)으로 정밀 구분됨.

================================================================================
9. 최종 결론 및 Production 불변 확인
================================================================================
- **최종 연구 결론 상태 (Evaluation Status)**: **`MIXED`**
- **운영 상태 (Production Status)**: **`PRODUCTION_HOLD`**
- **Production 영향도**: **`NONE`**
- **테스트 실행 여부**: **`Tests: NOT RUN`**

#### 요약 평가
사전등록된 프로토콜에 따라 수행된 전종목 Paired 사후 평가 결과:
1. Exit 4가 선제 발동한 202건의 동일 거래 비교에서 Policy B의 paired return delta 중앙값은 +7.43%p, Policy B 우세율은 54.46%로 관찰되었습니다.
2. 반면 paired delta 평균은 -19.1%p로, 소수 장기 대형 Winner 종목을 조기 청산하는 tradeoff가 함께 확인되었습니다.
3. 이에 따라 전체 정책 평가는 중앙값 및 고점 반납 개선 효과와 장기 대세 승자의 평균 수익률 희생 간의 절충을 고려하여 `MIXED`로 판정하며, `PRODUCTION_HOLD`를 유지합니다.
