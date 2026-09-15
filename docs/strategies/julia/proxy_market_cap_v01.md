# Julia 전략 V00과 기준 V2의 과거 비공식 Proxy PIT 비교 연구 (2022+)

> [!WARNING]
> **주의 — `NON-AUTHORITATIVE_PROXY_PIT` 비공식 연구**
> 이 문서는 공식 KRX 시가총액 데이터가 없었던 98개 Historical PIT 기준일에
> **예상 시가총액(Proxy Market Cap)**을 사용한 과거 연구 기록이다.
> 예상 시가총액은 과거 직전 공식 KRX 시총/주가 비율을 이용한 근사치이므로
> 실제 당시 시가총액과 차이가 발생할 수 있다.
> 따라서 이 결과는 **100% 정확한 Historical PIT 결과가 아니며**, Julia V00의
> 공식 검증 완료 또는 프로덕션 승인 근거로 사용할 수 없다.

---

## 1. 당시 상태와 관리 정보

| 항목 | 값 |
| :--- | :--- |
| **전략 ID** | `JULIA_STRATEGY_V00` |
| **기준 전략 ID** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2) |
| **연구 분류** | `RESEARCH_EXPERIMENT` / `NON_AUTHORITATIVE_PROXY_PIT` |
| **Julia 공식 상태** | `INVALID_INCOMPLETE_PIT_COVERAGE` (공식 KRX 커버리지 54.42%) |
| **프로덕션 권고** | `NOT_APPROVED` (기본 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02`로 유지) |
| **평가 기간** | `2022-01-01` ~ `2026-08-14` (초기 포지션 상태: `FLAT`) |
| **조회 이력** | 롤링 지표와 스냅샷에 2022년 이전 일봉 전체를 사용 |
| **기준 전략과의 유일한 차이** | 사전 진행 단계의 Loss Guard (-15% Daily Close Stop) `DISABLED` (OFF) |
| **공식 기준일** | **117개 (54.42%)** — KRX 공식값 100% 사용 |
| **Proxy 기준일** | **98개 (45.58%)** — Method B (Anchor Price Ratio Proxy) 적용 |
| **미래 Anchor 사용 수** | **0** (Strictly Prior Anchor Only) |
| **현재 Shares 대체 사용 수** | **0** (Zero Fallback) |
| **실험 기준 SHA** | `030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377` |
| **Proxy 전체 실행 커밋** | `6cdb5a6b00096d02c9cee4cc74f65ff8270056a1` |
| **FIX01 원본 커밋** | `afb967d211058bfce9ae053eebc2798b31b822e9` |
| **실행 ID** | `JULIA_V00_PROXY_PIT_20260822_065109` |

---

## 2. Proxy 방법 정확도 검증 (확인 가능한 공식 스냅샷)

117개 공식 KRX 스냅샷에 대해 직전 공식 과거 anchor만을 이용하여 시총을 예측하고,
실제 공식 KRX 시총과 비교하여 오차를 측정한 결과다.

| 지표 | 검증 결과 |
| :--- | :--- |
| **Total Validation Observations ($N$)** | **258,055건** |
| **Mean Absolute Percentage Error (MAPE)** | **0.27%** |
| **Median Absolute Percentage Error** | **0.00%** |
| **75th Percentile Error (P75)** | **0.00%** |
| **90th Percentile Error (P90)** | **0.00%** |
| **95th Percentile Error (P95)** | **0.02%** |
| **Max Error** | **1922.17%** |
| **1,000억원 Threshold Classification Agreement** | **99.90% (257,807/258,055)** |
| **False Pass Count** | **80건** |
| **False Fail Count** | **168건** |

---

## 3. 주요 전략 비교 성과 (2022+)

| 지표 | 기준 V2 (Loss Guard ON) | Julia V00 (Loss Guard OFF) | 차이 (Julia - 기준) |
| :--- | :--- | :--- | :--- |
| **Total Trades** | **845건** | **687건** | **-158건** |
| **Unique Tickers** | **673개** | **673개** | **+0개** |
| **Mean Return (%)** | **+12.80%** | **+23.13%** | **+10.33%p** |
| **Median Return (%)** | **-14.57%** | **+1.13%** | **+15.70%p** |
| **Positive Return Rate (%)** | **34.56%** | **51.09%** | **+16.54%p** |
| **Deep Losses ($\\le -10\%$)** | 508건 (60.1%) | 263건 (38.3%) | -245건 |
| **Deep Losses ($\\le -15\%$)** | 393건 (46.5%) | 226건 (32.9%) | -167건 |
| **Deep Losses ($\\le -20\%$)** | 47건 (5.6%) | 187건 (27.2%) | +140건 |
| **Deep Losses ($\\le -30\%$)** | 14건 (1.7%) | 113건 (16.4%) | +99건 |
| **Big Winners ($\\ge +20\%$)** | 214건 (25.3%) | 256건 (37.3%) | +42건 |
| **Big Winners ($\\ge +30\%$)** | 184건 (21.8%) | 222건 (32.3%) | +38건 |
| **Big Winners ($\\ge +50\%$)** | 152건 (18.0%) | 182건 (26.5%) | +30건 |
| **Mega Winners ($\\ge +100\%$)** | 52건 (6.2%) | 69건 (10.0%) | +17건 |
| **Mean MAE (%)** | **-15.41%** | **-26.31%** | **-10.91%p** |
| **Median MAE (%)** | **-16.37%** | **-22.05%** | **-5.68%p** |
| **Worst MAE (%)** | **-73.66%** | **-90.09%** | **-16.43%p** |
| **Mean MFE (%)** | **53.24%** | **77.92%** | **+24.68%p** |
| **Median MFE (%)** | **23.44%** | **48.81%** | **+25.37%p** |
| **Mean Holding Time** | **23.77 weeks** | **47.52 weeks** | **+23.75 weeks** |
| **Median Holding Time** | **16.40 weeks** | **41.60 weeks** | **+25.20 weeks** |

---

## 4. 전체 Loss Guard 코호트 집계와 회복

$$\text{Baseline Loss Guard Total } N = 477 = M(397) + (N-M)(80)$$

- **Baseline Loss Guard Triggered Total ($N$)**: **477건**
- **Paired in Julia ($M$)**: **397건**
- **Unpaired in Julia ($N-M$)**: **80건**
- **Julia Higher Terminal Return (Recovered)**: **197건 (49.62%)**
- **Julia Deeper Terminal Loss**: **200건 (50.38%)**
- **Julia Successfully Reached PROGRESSED Stage**: **160건 (40.30%)**

---

## 5. Proxy 의존도와 경계 민감도 분석

### A. Proxy 데이터 의존도

| 지표 | 기준 V2 | Julia V00 |
| :--- | :--- | :--- |
| **Actual KRX Entry Trades** | 89건 (10.5%) | 65건 (9.5%) |
| **Proxy-Dependent Entry Trades** | 756건 (89.5%) | 622건 (90.5%) |
| **- Near-Threshold (80B~120B) Proxy Entries** | 58건 | 54건 |
| **- High Confidence (<=35d) Proxy Entries** | 225건 | 201건 |
| **- Medium Confidence (36~90d) Proxy Entries** | 237건 | 211건 |
| **- Low Confidence (>90d) Proxy Entries** | 294건 | 210건 |

### B. 보수적 경계 민감도 (80B ~ 120B 완충 구간 제외)

| 민감도 지표 | 기본 (100B 정확 기준) | 보수적 (80B~120B 완충 구간) | 민감도 차이 |
| :--- | :--- | :--- | :--- |
| **Baseline Trade Count** | 845건 | 810건 | -4.14% |
| **Julia Trade Count** | 687건 | 656건 | -4.51% |
| **Baseline Mean Return** | +12.80% | +13.24% | +0.44%p |
| **Julia Mean Return** | +23.13% | +24.24% | +1.11%p |
| **Julia - Baseline Return Delta** | **+10.33%p** | **+11.00%p** | **+0.67%p** |
| **Conclusion Robust to Boundary** | - | - | **YES** |

---

## 6. Julia V00 Proxy 실행의 주요 고수익·최대 손실

### Julia V00 상위 10개 고수익 ($\ge +50\%$)

| 티커 | 종목명 | 진입일 | 청산일 | Julia 수익률 (%) | Julia MFE (%) | 청산 유형 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `043260` | 43260 | 2025-11-03 | Cutoff (Open) | **+912.41%** | +2857.82% | `NO_EXIT_BEFORE_CUTOFF` |
| `047040` | 47040 | 2025-06-02 | 2026-05-04 | **+718.71%** | +843.86% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `058610` | 58610 | 2025-02-03 | 2026-02-02 | **+391.80%** | +443.28% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `131290` | 131290 | 2025-10-13 | Cutoff (Open) | **+391.49%** | +455.77% | `NO_EXIT_BEFORE_CUTOFF` |
| `036930` | 36930 | 2025-03-24 | 2026-06-01 | **+375.33%** | +495.95% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `001820` | 1820 | 2025-10-13 | 2026-07-01 | **+338.42%** | +455.93% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `006340` | 6340 | 2025-11-03 | 2026-05-04 | **+328.24%** | +333.46% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `226950` | 226950 | 2024-10-14 | Cutoff (Open) | **+327.48%** | +728.24% | `NO_EXIT_BEFORE_CUTOFF` |
| `080220` | 80220 | 2025-09-22 | Cutoff (Open) | **+323.38%** | +616.88% | `NO_EXIT_BEFORE_CUTOFF` |
| `241770` | 241770 | 2025-03-04 | Cutoff (Open) | **+310.33%** | +386.32% | `NO_EXIT_BEFORE_CUTOFF` |

### Julia V00 상위 10개 큰 손실 ($\le -20\%$)

| 티커 | 종목명 | 진입일 | 청산일 | Julia 수익률 (%) | Julia MAE (%) | 청산 유형 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `195990` | 195990 | 2024-11-11 | Cutoff (Open) | **-87.32%** | -90.09% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `091810` | 91810 | 2024-09-23 | Cutoff (Open) | **-80.11%** | -84.34% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `058970` | 58970 | 2025-02-10 | Cutoff (Open) | **-79.03%** | -85.14% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `014990` | 14990 | 2025-07-14 | Cutoff (Open) | **-74.01%** | -80.20% | `NO_EXIT_BEFORE_CUTOFF` |
| `217270` | 217270 | 2025-07-07 | Cutoff (Open) | **-73.47%** | -79.34% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `058820` | 58820 | 2024-08-19 | Cutoff (Open) | **-72.76%** | -74.94% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `069460` | 69460 | 2025-05-07 | Cutoff (Open) | **-72.09%** | -73.66% | `NO_EXIT_BEFORE_CUTOFF` |
| `039240` | 39240 | 2025-01-20 | Cutoff (Open) | **-71.86%** | -77.57% | `NO_EXIT_BEFORE_CUTOFF` |
| `307870` | 307870 | 2024-08-05 | Cutoff (Open) | **-70.74%** | -84.54% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `311390` | 311390 | 2025-04-14 | Cutoff (Open) | **-69.34%** | -75.18% | `NO_PROGRESSED_BEFORE_CUTOFF` |

---

## 7. 전략 관리와 결론

1. **Proxy 연구 결론**: **`MIXED`**
   - **근거**: Julia는 성과 상승 여지(Mean Return +10.33%p, Median Return
     +15.70%p, Win Rate +16.54%p)를 보였지만, Loss Guard를 제거하면
     $\le -20\%$ 손실 거래가 5.6%에서 27.2%로 늘고 Mean MAE가
     -15.41%에서 -26.31%로 악화된다.
2. **프로덕션 상태 유지**:
   - `JULIA_PRODUCTION_STATUS = NOT_APPROVED`
   - `OFFICIAL_FULL_PIT_STATUS = INVALID_INCOMPLETE_PIT_COVERAGE`
   - 기본 프로덕션 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02` (783 historical trades)로 유지된다.
3. **당시 후속 계획**:
   - 이 항목은 당시 기록된 계획이며 현재 공식 검증 완료를 뜻하지 않는다.
   - KRX Open API로 98개 기준일을 공식 확보한 후 Proxy와 Actual 시총 오차 및
     백테스트 결과를 대조할 예정이었다.
