# V06 A FAST / Julia CLOSED vs TERMINAL 및 Category 재집계

- 판정: ETF_V06_AFAST_VS_JULIA_POST_ANALYSIS_COMPLETE
- 범위: V06 ledger의 재집계만 수행. 새 백테스트·전략 replay·signal generation은 하지 않았어.
- 원본 V06 artifact는 읽기만 했고 수정하지 않았어.
- CLOSED는 ledger trade_status=REALIZED, TERMINAL은 ledger trade_status=OPEN_AT_CUTOFF로 그대로 분류했어.
- 수익률 aggregate 교차검증 허용오차: absolute 0.1 percentage point.

## CLOSED / TERMINAL

| 전략 | 구분 | 거래 | 거래 ETF | 양수율 | Gross 평균 / 중앙값 | 비용 반영 평균 / 중앙값 | Gross P10/P25/P50/P75/P90 | 보유 평균 / 중앙값 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | CLOSED | 281 | 153 | 50.89% | 30.79% / 3.97% | 30.49% / 3.73% | -18.09/-15.93/3.97/57.64/132.00% | 278.77 / 184.00 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | TERMINAL | 69 | 69 | 88.41% | 48.53% / 28.09% | 48.36% / 27.94% | -0.47/4.88/28.09/78.81/131.18% | 642.13 / 573.00 |
| JULIA_STRATEGY_V00 | CLOSED | 159 | 128 | 93.08% | 69.19% / 49.27% | 68.81% / 48.93% | 4.33/28.74/49.27/115.34/148.49% | 536.51 / 406.00 |
| JULIA_STRATEGY_V00 | TERMINAL | 87 | 87 | 68.97% | 34.19% / 10.77% | 34.04% / 10.64% | -25.57/-4.69/10.77/65.29/131.27% | 735.28 / 624.00 |

### Julia 지표의 TERMINAL 의존 여부

Julia 전체 ledger에서 양수율 84.55% / 중앙값 41.72%였어. CLOSED만 보면 양수율 93.08% / 중앙값 49.27%, TERMINAL만 보면 68.97% / 10.77%야. CLOSED 양수율은 전체보다 +8.53pp, CLOSED 중앙값은 +7.55pp 높아. 따라서 Julia의 높은 전체 양수율과 중앙값은 TERMINAL 평가에만 의존하지 않고 CLOSED 거래에서도 유지돼. TERMINAL은 cutoff 종가 평가이며 실현 수익으로 해석하면 안 돼.

### CLOSED / TERMINAL count와 ETF coverage

| 전략 | 전체 거래 / ETF | CLOSED 거래 / ETF | CLOSED 비율 | TERMINAL 거래 / ETF | TERMINAL 비율 |
|---|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 350 / 193 | 281 / 153 | 80.29% | 69 / 69 | 19.71% |
| JULIA_STRATEGY_V00 | 246 / 193 | 159 / 128 | 64.63% | 87 / 87 | 35.37% |

## Category × Strategy

| Category | 전략 | Universe ETF | 거래 ETF | 거래 | 양수율 | Gross 평균 / 중앙값 | 비용 반영 평균 / 중앙값 | Gross P25/P50/P75 | +20/+50/+100 | -15/-30/-40/-50 | 보유 중앙값 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MARKET_INDEX | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 140 | 88 | 152 | 65.79% | 39.62% / 20.53% | 39.33% / 20.32% | -13.60/20.53/73.80% | 77/50/29 | 31/1/0/0 | 209.00 |
| MARKET_INDEX | JULIA_STRATEGY_V00 | 140 | 88 | 108 | 92.59% | 65.87% / 48.59% | 65.54% / 48.25% | 16.96/48.59/115.56% | 80/52/32 | 1/1/1/0 | 432.00 |
| SECTOR_INDUSTRY | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 270 | 93 | 172 | 52.33% | 29.62% / 4.24% | 29.35% / 4.00% | -15.60/4.24/53.89% | 73/46/19 | 53/1/1/1 | 183.50 |
| SECTOR_INDUSTRY | JULIA_STRATEGY_V00 | 270 | 93 | 122 | 77.05% | 48.52% / 33.22% | 48.24% / 33.07% | 3.42/33.22/86.85% | 74/46/23 | 18/5/3/2 | 292.00 |
| COMMODITY_RESOURCE | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 17 | 12 | 26 | 53.85% | 34.05% / 12.88% | 33.75% / 12.62% | -16.23/12.88/60.02% | 12/8/5 | 10/0/0/0 | 226.00 |
| COMMODITY_RESOURCE | JULIA_STRATEGY_V00 | 17 | 12 | 16 | 87.50% | 58.94% / 39.90% | 58.60% / 39.58% | 30.49/39.90/83.01% | 13/6/4 | 2/0/0/0 | 859.50 |

Gross median의 절대 격차가 가장 큰 category는 SECTOR_INDUSTRY (Julia − A FAST = +28.98pp)야. 양수율 격차가 가장 큰 category는 COMMODITY_RESOURCE (Julia − A FAST = +33.65pp)야.
CLOSED-only에서도 SECTOR_INDUSTRY의 median gross 차이가 +54.93pp로 가장 커. category별 median 격차는 TERMINAL 평가만으로 설명되지 않아.
A FAST는 CLOSED 양수율/중앙값 50.89% / 3.97%이고 TERMINAL은 88.41% / 28.09%야.

## CLOSED-only Category 보조표

| Category | 전략 | CLOSED 거래 | 양수율 | Gross 평균 / 중앙값 | +50 | -15 |
|---|---|---:|---:|---:|---:|---:|
| MARKET_INDEX | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 116 | 56.90% | 41.07% / 29.72% | 37 | 31 |
| MARKET_INDEX | JULIA_STRATEGY_V00 | 70 | 95.71% | 82.75% / 59.08% | 40 | 0 |
| SECTOR_INDUSTRY | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 141 | 46.10% | 21.95% / -12.28% | 34 | 50 |
| SECTOR_INDUSTRY | JULIA_STRATEGY_V00 | 76 | 90.79% | 57.03% / 42.65% | 34 | 3 |
| COMMODITY_RESOURCE | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 24 | 50.00% | 33.07% / -2.84% | 7 | 10 |
| COMMODITY_RESOURCE | JULIA_STRATEGY_V00 | 13 | 92.31% | 67.31% / 41.46% | 5 | 1 |

CLOSED-only gross median의 Julia − A FAST 차이:

- COMMODITY_RESOURCE: +44.31pp
- MARKET_INDEX: +29.35pp
- SECTOR_INDUSTRY: +54.93pp

## ETF-weighted (V06 계약)

| 범위 | 전략 | 거래 ETF | ETF별 평균수익률 중앙값 | ETF별 양수율 중앙값 |
|---|---|---:|---:|---:|
| ALL | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 193 | 29.05% | 66.67% |
| ALL | JULIA_STRATEGY_V00 | 193 | 44.85% | 100.00% |
| MARKET_INDEX | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 88 | 35.04% | 100.00% |
| MARKET_INDEX | JULIA_STRATEGY_V00 | 88 | 56.62% | 100.00% |
| SECTOR_INDUSTRY | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 93 | 23.58% | 50.00% |
| SECTOR_INDUSTRY | JULIA_STRATEGY_V00 | 93 | 35.33% | 100.00% |
| COMMODITY_RESOURCE | PATTERN_A_FAST_FINAL_STRATEGY_V02 | 12 | 42.56% | 50.00% |
| COMMODITY_RESOURCE | JULIA_STRATEGY_V00 | 12 | 47.73% | 100.00% |

ETF별 mean trade return의 중앙값과 ETF별 positive rate의 중앙값을 사용했어. 새 composite score는 만들지 않았어.

## 재집계 검증

- 검증 통과: True
- overall/category aggregate mismatch: 0
- 중복 trade ID: 0
- unknown category: 0
- CLOSED + TERMINAL count mismatch: 0
- category count sum mismatch: 0
- 상세 검증은 validation.json에 저장했어.

## 산출물

- closed_terminal_summary.csv
- category_summary.csv
- closed_only_category_summary.csv
- etf_weighted_summary.csv
- top_bottom_by_status.csv
- validation.json

이 표는 V06 거래를 상태와 기존 category별로 기술적으로 비교한 재집계야. 새로운 전략 winner 판정은 하지 않았어.
