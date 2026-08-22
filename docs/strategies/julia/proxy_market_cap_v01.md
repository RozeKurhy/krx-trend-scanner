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
| **Authoritative Start SHA** | `030e9c6145d8dd8b584ea8ce6cc0097cbbf4e377` |
| **Run ID** | `JULIA_V00_PROXY_PIT_20260822_062127` |

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
| **Mean Return (%)** | **+1280.02%** | **+2313.09%** | **+1033.07%p** |
| **Median Return (%)** | **-1457.00%** | **+113.00%** | **+1570.00%p** |
| **Positive Return Rate (%)** | **34.56%** | **51.09%** | **+16.54%p** |
| **Deep Losses ($\le -20\%$)** | **551건 (65.2%)** | **335건 (48.8%)** | **-216건** |
| **Deep Losses ($\le -30\%$)** | **551건 (65.2%)** | **335건 (48.8%)** | **-216건** |
| **Big Winners ($\ge +50\%$)** | **292건 (34.6%)** | **350건 (50.9%)** | **+58건** |
| **Mega Winners ($\ge +100\%$)** | **289건 (34.2%)** | **346건 (50.4%)** | **+57건** |
| **Mean MAE (%)** | **-1540.59%** | **-2631.29%** | **-1090.70%p** |
| **Mean MFE (%)** | **5323.73%** | **7792.14%** | **+2468.40%p** |

---

## 4. Full Loss Guard Cohort Accounting & Recovery

$$\text{Baseline Loss Guard Total } N = 477 = M(397) + (N-M)(80)$$

- **Baseline Loss Guard Triggered Total ($N$)**: **477건**
- **Paired in Julia ($M$)**: **397건**
- **Julia Higher Terminal Return (Recovered)**: **197건**
- **Julia Deeper Terminal Loss**: **200건**
- **Julia Successfully Reached PROGRESSED Stage**: **160건**

---

## 5. Proxy Dependence & Boundary Sensitivity Analysis

### A. Proxy Data Dependence

| Metric | Baseline V2 | Julia V00 |
| :--- | :--- | :--- |
| **Actual KRX Entry Trades** | 89건 (10.5%) | 65건 (9.5%) |
| **Proxy-Dependent Entry Trades** | 756건 (89.5%) | 622건 (90.5%) |

### B. Conservative Boundary Sensitivity (80B ~ 120B Buffer Excluded)

| Sensitivity Metric | Primary (100B Exact) | Conservative (80B~120B Buffer) | Sensitivity Delta |
| :--- | :--- | :--- | :--- |
| **Baseline Trade Count** | 845건 | 810건 | -4.14% |
| **Julia Trade Count** | 687건 | 656건 | -4.51% |
| **Baseline Mean Return** | +1280.02% | +1324.46% | +44.44%p |
| **Julia Mean Return** | +2313.09% | +2423.68% | +110.59%p |
| **Julia - Baseline Return Delta** | **+1033.07%p** | **+1099.22%p** | **+66.15%p** |
| **Conclusion Robust to Boundary** | - | - | **YES** |

---

## 6. Top Big Winners & Worst Losses in Julia V00 Proxy Run

### Top 10 Big Winners in Julia V00 ($\ge +50\%$)

| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MFE (%) | Exit Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `043260` | 043260 | 2025-10-31 | Cutoff (Open) | **+91241.00%** | +285782.00% | `NO_EXIT_BEFORE_CUTOFF` |
| `047040` | 047040 | 2025-05-30 | 2026-05-04 | **+71871.00%** | +84386.00% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `058610` | 058610 | 2025-01-31 | 2026-02-02 | **+39180.00%** | +44328.00% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `131290` | 131290 | 2025-10-10 | Cutoff (Open) | **+39149.00%** | +45577.00% | `NO_EXIT_BEFORE_CUTOFF` |
| `036930` | 036930 | 2025-03-21 | 2026-06-01 | **+37533.00%** | +49595.00% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `001820` | 001820 | 2025-10-10 | 2026-07-01 | **+33842.00%** | +45593.00% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `006340` | 006340 | 2025-10-31 | 2026-05-04 | **+32824.00%** | +33346.00% | `EXIT4_SCORE_DRAWDOWN_GE_15` |
| `226950` | 226950 | 2024-10-11 | Cutoff (Open) | **+32748.00%** | +72824.00% | `NO_EXIT_BEFORE_CUTOFF` |
| `080220` | 080220 | 2025-09-19 | Cutoff (Open) | **+32338.00%** | +61688.00% | `NO_EXIT_BEFORE_CUTOFF` |
| `241770` | 241770 | 2025-02-28 | Cutoff (Open) | **+31033.00%** | +38632.00% | `NO_EXIT_BEFORE_CUTOFF` |

### Top 10 Deep Losses in Julia V00 ($\le -20\%$)

| Ticker | Name | Entry Date | Exit Date | Julia Ret (%) | Julia MAE (%) | Exit Type |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `195990` | 195990 | 2024-11-08 | Cutoff (Open) | **-8732.00%** | -9009.00% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `091810` | 091810 | 2024-09-20 | Cutoff (Open) | **-8011.00%** | -8434.00% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `058970` | 058970 | 2025-02-07 | Cutoff (Open) | **-7903.00%** | -8514.00% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `014990` | 014990 | 2025-07-11 | Cutoff (Open) | **-7401.00%** | -8020.00% | `NO_EXIT_BEFORE_CUTOFF` |
| `217270` | 217270 | 2025-07-04 | Cutoff (Open) | **-7347.00%** | -7934.00% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `058820` | 058820 | 2024-08-16 | Cutoff (Open) | **-7276.00%** | -7494.00% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `069460` | 069460 | 2025-05-02 | Cutoff (Open) | **-7209.00%** | -7366.00% | `NO_EXIT_BEFORE_CUTOFF` |
| `039240` | 039240 | 2025-01-17 | Cutoff (Open) | **-7186.00%** | -7757.00% | `NO_EXIT_BEFORE_CUTOFF` |
| `307870` | 307870 | 2024-08-02 | Cutoff (Open) | **-7074.00%** | -8454.00% | `NO_PROGRESSED_BEFORE_CUTOFF` |
| `311390` | 311390 | 2025-04-11 | Cutoff (Open) | **-6934.00%** | -7518.00% | `NO_PROGRESSED_BEFORE_CUTOFF` |

---

## 7. Strategic Governance & Next Steps

1. **Proxy Research Verdict**:
   - **`SUPPORTIVE_OF_JULIA`**
2. **Production Status Invariant**:
   - `JULIA_PRODUCTION_STATUS = NOT_APPROVED`
   - 기본 프로덕션 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02` (783 historical trades)를 엄격히 유지합니다.
3. **Next Steps**:
   - KRX Open API 98 dates 공식 확보 후 Proxy vs Actual 시총 오차 및 백테스트 결과 Reconciliation 수행 예정.
