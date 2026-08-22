# Research Report: Julia Strategy V00 vs Baseline V2 Proxy PIT Comparative Backtest (2022+)

> [!WARNING]
> **WARNING — NON-AUTHORITATIVE PROXY PIT RESEARCH**
> 본 백테스트는 공식 KRX 시가총액 데이터가 존재하지 않는 98개 Historical PIT 기준일에 대해 **예상 시가총액(Proxy Market Cap)**을 사용한 **비공식 연구용 실험**입니다.
> 예상 시가총액은 과거 직전 공식 KRX 시총/주가 비율을 이용한 근사치이며 실제 당시 시가총액과 차이가 발생할 수 있습니다.
> 따라서 본 결과는 **100% 정확한 Historical PIT 결과가 아니며**, Julia V00의 공식 검증 완료 또는 Production 승인 근거로 사용할 수 없습니다.

---

## 1. Executive Status & Governance

| Item | Specification / Value |
| :--- | :--- |
| **Strategy ID** | `JULIA_STRATEGY_V00` |
| **Base Strategy ID** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` (A FAST Core V2) |
| **Research Classification** | `RESEARCH_EXPERIMENT` / `NON_AUTHORITATIVE_PROXY_PIT` |
| **Official Julia Status** | `INVALID_INCOMPLETE_PIT_COVERAGE` (54.42% Official KRX Coverage) |
| **Production Recommendation** | `NOT_APPROVED` (Default remains `PATTERN_A_FAST_FINAL_STRATEGY_V02`) |
| **Evaluation Window** | `2022-01-01` ~ `2026-08-14` (Initial Position State: `FLAT`) |
| **Lookback History** | Full pre-2022 daily bars utilized for rolling indicators and snapshots |
| **Only Delta from Base** | Pre-PROGRESSED Loss Guard (-15% Daily Close Stop) `DISABLED` (OFF) |
| **Official Reference Dates** | **117개 (54.42%)** — KRX 공식값 100% 사용 |
| **Proxy Reference Dates** | **98개 (45.58%)** — Method B (Anchor Price Ratio Proxy) 적용 |
| **Future Anchor Usage Count** | **0** (Strictly Prior Anchor Only) |
| **Current Shares Fallback Count** | **0** (Zero Fallback) |
| **Experiment Base SHA** | `030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377` |
| **Proxy Full Run Commit** | `6cdb5a6b00096d02c9cee4cc74f65ff8270056a1` |
| **FIX01 Source Commit** | `afb967d211058bfce9ae053eebc2798b31b822e9` |
| **Run ID** | `JULIA_V00_PROXY_PIT_20260822_064434` |

---

## 2. Proxy Method Accuracy Validation (Known Official Snapshots)

117개 공식 KRX 스냅샷에 대해 직전 공식 과거 anchor만을 이용하여 시총을 예측하고, 실제 공식 KRX 시총과 비교하여 오차를 측정한 결과입니다.

| Metric | Validation Result |
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

## 3. Primary Comparative Strategy Performance (2022+)

| Metric Category | Baseline V2 (Loss Guard ON) | Julia V00 (Loss Guard OFF) | Delta (Julia - Baseline) |
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

## 4. Full Loss Guard Cohort Accounting & Recovery

$$\text{Baseline Loss Guard Total } N = 477 = M(397) + (N-M)(80)$$

- **Baseline Loss Guard Triggered Total ($N$)**: **477건**
- **Paired in Julia ($M$)**: **397건**
- **Unpaired in Julia ($N-M$)**: **80건**
- **Julia Higher Terminal Return (Recovered)**: **197건 (49.62%)**
- **Julia Deeper Terminal Loss**: **200건 (50.38%)**
- **Julia Successfully Reached PROGRESSED Stage**: **160건 (40.30%)**

---

## 5. Proxy Dependence & Boundary Sensitivity Analysis

### A. Proxy Data Dependence Breakdown

| Metric | Baseline V2 | Julia V00 |
| :--- | :--- | :--- |
| **Actual KRX Entry Trades** | 89건 (10.5%) | 65건 (9.5%) |
| **Proxy-Dependent Entry Trades** | 756건 (89.5%) | 622건 (90.5%) |
| **- Near-Threshold (80B~120B) Proxy Entries** | 58건 | 54건 |
| **- High Confidence (<=35d) Proxy Entries** | 225건 | 201건 |
| **- Medium Confidence (36~90d) Proxy Entries** | 237건 | 211건 |
| **- Low Confidence (>90d) Proxy Entries** | 294건 | 210건 |

### B. Conservative Boundary Sensitivity (80B ~ 120B Buffer Excluded)

| Sensitivity Metric | Primary (100B Exact) | Conservative (80B~120B Buffer) | Sensitivity Delta |
| :--- | :--- | :--- | :--- |
| **Baseline Trade Count** | 845건 | 810건 | -4.14% |
| **Julia Trade Count** | 687건 | 656건 | -4.51% |
| **Baseline Mean Return** | +12.80% | +13.24% | +0.44%p |
| **Julia Mean Return** | +23.13% | +24.24% | +1.11%p |
| **Julia - Baseline Return Delta** | **+10.33%p** | **+11.00%p** | **+0.67%p** |
| **Conclusion Robust to Boundary** | - | - | **YES** |

---

## 6. Top Big Winners & Worst Losses in Julia V00 Proxy Run

### Top 10 Big Winners in Julia V00 ($\ge +50\%$)

| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MFE (%) | Exit Type |
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

### Top 10 Deep Losses in Julia V00 ($\le -20\%$)

| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MAE (%) | Exit Type |
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

## 7. Strategic Governance & Verdict

1. **Proxy Research Verdict**: **`MIXED`**
   - **Rationale**: Julia demonstrates substantial performance upside (Mean Return +10.33%p, Median Return +15.70%p, Win Rate +16.54%p), but removing the Loss Guard increases <= -20% drawdown trades from 5.6% to 27.2% (Mean MAE worsens from -15.41% to -26.31%).
2. **Production Status Invariant**:
   - `JULIA_PRODUCTION_STATUS = NOT_APPROVED`
   - `OFFICIAL_FULL_PIT_STATUS = INVALID_INCOMPLETE_PIT_COVERAGE`
   - 기본 프로덕션 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02` (783 historical trades)를 엄격히 유지합니다.
3. **Next Steps**:
   - KRX Open API 98 dates 공식 확보 후 Proxy vs Actual 시총 오차 및 백테스트 결과 Reconciliation 수행 예정.
