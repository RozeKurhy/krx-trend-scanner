# Pattern B Horizon Outcome Censoring Diagnostic V01

- Verdict: `PATTERN_B_FORWARD_CENSORING_DIAGNOSTIC_CAUTION`
- 기준 forward-study verdict: `PATTERN_B_FORWARD_SIGNAL_MIXED` (이번 작업에서 변경하지 않음)
- Baseline commit at run start: `272016f6dca62e32af66c67bdfb9f072d8de8bbf`.
- Source samples: 290,008; existing outcome rows: 1,033,473; frontier: 2026-09-21.
- Method: frozen source sample/outcome key join + existing merged PIT identity intervals and trading calendar. No price replay, return recalculation, imputation, or strategy backtest.
- Rates in CSV are percentages. Mature terminal and endpoint-price missing rates use `mature_sample_n = total_snapshot_n - frontier_incomplete_n` as denominator.

## Core completion results

### PANEL_A_ALL — ALL PIT Eligible

#### 12M

| State | Total | Done | Frontier | Terminal | Endpoint price missing | Other | Raw | Mature N | Mature | Terminal rate | Endpoint missing rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DEEP_DEPRESSED | 34142 | 27544 | 4468 | 391 | 1739 | 0 | 80.67% | 29674 | 92.82% | 1.32% | 5.86% |
| DEPRESSED | 77478 | 67831 | 7366 | 404 | 1877 | 0 | 87.55% | 70112 | 96.75% | 0.58% | 2.68% |
| NORMAL | 124096 | 112391 | 9497 | 495 | 1713 | 0 | 90.57% | 114599 | 98.07% | 0.43% | 1.49% |

#### 24M

| State | Total | Done | Frontier | Terminal | Endpoint price missing | Other | Raw | Mature N | Mature | Terminal rate | Endpoint missing rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DEEP_DEPRESSED | 34142 | 20572 | 10868 | 861 | 1841 | 0 | 60.25% | 23274 | 88.39% | 3.70% | 7.91% |
| DEPRESSED | 77478 | 57141 | 17013 | 1065 | 2259 | 0 | 73.75% | 60465 | 94.50% | 1.76% | 3.74% |
| NORMAL | 124096 | 102946 | 17938 | 1075 | 2137 | 0 | 82.96% | 106158 | 96.97% | 1.01% | 2.01% |

### PANEL_B_PIT_1T_PLUS — Exact snapshot PIT market cap >= 1T KRW

#### 12M

| State | Total | Done | Frontier | Terminal | Endpoint price missing | Other | Raw | Mature N | Mature | Terminal rate | Endpoint missing rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DEEP_DEPRESSED | 1504 | 1429 | 46 | 5 | 24 | 0 | 95.01% | 1458 | 98.01% | 0.34% | 1.65% |
| DEPRESSED | 5187 | 4878 | 253 | 21 | 35 | 0 | 94.04% | 4934 | 98.87% | 0.43% | 0.71% |
| NORMAL | 14332 | 12819 | 1350 | 66 | 97 | 0 | 89.44% | 12982 | 98.74% | 0.51% | 0.75% |

#### 24M

| State | Total | Done | Frontier | Terminal | Endpoint price missing | Other | Raw | Mature N | Mature | Terminal rate | Endpoint missing rate |
|---|---|---|---|---|---|---|---|---|---|---|---|
| DEEP_DEPRESSED | 1504 | 1211 | 277 | 8 | 8 | 0 | 80.52% | 1227 | 98.70% | 0.65% | 0.65% |
| DEPRESSED | 5187 | 4293 | 817 | 47 | 30 | 0 | 82.76% | 4370 | 98.24% | 1.08% | 0.69% |
| NORMAL | 14332 | 11628 | 2501 | 127 | 76 | 0 | 81.13% | 11831 | 98.28% | 1.07% | 0.64% |

## State contrasts (target minus reference, percentage points)

| Panel | Horizon | Contrast | Mature completion | Terminal identity | Endpoint price missing |
|---|---|---|---:|---:|---:|
| PANEL_A_ALL | 12M | DEPRESSED_vs_NORMAL | -1.33 pp | +0.14 pp | +1.18 pp |
| PANEL_A_ALL | 12M | DEEP_DEPRESSED_vs_NORMAL | -5.25 pp | +0.89 pp | +4.37 pp |
| PANEL_A_ALL | 12M | DEEP_DEPRESSED_vs_DEPRESSED | -3.92 pp | +0.74 pp | +3.18 pp |
| PANEL_A_ALL | 24M | DEPRESSED_vs_NORMAL | -2.47 pp | +0.75 pp | +1.72 pp |
| PANEL_A_ALL | 24M | DEEP_DEPRESSED_vs_NORMAL | -8.58 pp | +2.69 pp | +5.90 pp |
| PANEL_A_ALL | 24M | DEEP_DEPRESSED_vs_DEPRESSED | -6.11 pp | +1.94 pp | +4.17 pp |
| PANEL_B_PIT_1T_PLUS | 12M | DEPRESSED_vs_NORMAL | +0.12 pp | -0.08 pp | -0.04 pp |
| PANEL_B_PIT_1T_PLUS | 12M | DEEP_DEPRESSED_vs_NORMAL | -0.73 pp | -0.17 pp | +0.90 pp |
| PANEL_B_PIT_1T_PLUS | 12M | DEEP_DEPRESSED_vs_DEPRESSED | -0.85 pp | -0.08 pp | +0.94 pp |
| PANEL_B_PIT_1T_PLUS | 24M | DEPRESSED_vs_NORMAL | -0.05 pp | +0.00 pp | +0.04 pp |
| PANEL_B_PIT_1T_PLUS | 24M | DEEP_DEPRESSED_vs_NORMAL | +0.41 pp | -0.42 pp | +0.01 pp |
| PANEL_B_PIT_1T_PLUS | 24M | DEEP_DEPRESSED_vs_DEPRESSED | +0.46 pp | -0.42 pp | -0.03 pp |

## Terminal identity evidence

Terminal rows: 6,363 distinct sample/horizon records; reason-code counts: `NO_INTERVAL_COVERS_ENDPOINT` 6,326, `SAME_ISU_INTERVAL_NOT_COVERING_ENDPOINT` 37.
Reason codes describe only PIT interval/chain evidence. ISU changes are not asserted to be mergers, and no terminal case is assigned a return or economic loss.
A deterministic 20-row spot-check is in `terminal_identity_spot_checks.csv`; each row verifies source sample retained, outcome absent, exact endpoint in calendar and classifier reproduced from PIT authority.

## Interpretation

Prior verdict interpretation: **기존 해석에 censoring caution 필요**. This diagnostic verdict does not alter `PATTERN_B_FORWARD_SIGNAL_MIXED`.

### DEPRESSED forward-return 우위와 censoring

전부 설명할 가능성이 크다고 보긴 어렵지만, PANEL A에서는 일부 기여 가능성이 있다. 12M/24M mature completion이 NORMAL보다 각각 1.33/2.47 pp 낮고, missing 비율은 더 높다. 차이는 terminal identity 자체보다 endpoint price missing에서 더 크다. PANEL B의 차이는 두 horizon에서 거의 0에 가까워 반복되지 않는다. 기존 forward-return 우위가 생존 표본 조건부 결과일 가능성은 남지만, 전체 우위를 censoring 탓으로 돌릴 증거는 아니다. 기존 연구의 PANEL B에서 DEPRESSED/NORMAL median return은 12M +1.6%/-3.9%, 24M +3.8%/-5.1%였고, 이번 PANEL B mature completion은 각각 98.87%/98.74%, 98.24%/98.28%로 거의 같았다. 이 비교에서는 horizon censoring이 우위를 설명할 가능성이 낮아 보인다.

### `DEPRESSED -> NORMAL` Pure Pattern B 전략 백테스트

탐색적 백테스트 단계로는 넘어갈 수 있다. 다만 표본 기간·진입/청산·거래 비용·성숙 표본 및 terminal/endpoint missing 처리를 사전 고정해야 한다. 이번 기술통계만으로 전략 우위가 확인된 것은 아니다.
