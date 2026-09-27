# Pattern B: PROGRESSED + previous EARLY_TREND / TRANSITION — 5-window independent replay

## 결과 요약

판정: PROMISING. frozen TEST 대비 NEW_TEST 평균 개선은 5/5 창, 중앙값 개선은 5/5 창이야. 승률 하락이 2pp 이내인 창은 5/5야.
-30 realized tail count가 늘지 않은 창은 5/5야. -30 tail rate 변화가 +0.25pp 이내인 창은 5/5, -50 tail rate가 악화되지 않은 창은 5/5야. 단일 종합 점수는 사용하지 않았어.
NEW_TEST의 거래 identity 집합은 frozen TEST의 사후 E/T 추출과 5/5 창에서 완전히 같아. 독립 replay의 평균은 사후 값과 5/5 창, 중앙값은 5/5 창에서 수치상 일치해.

독립 NEW_TEST만 재생했고, 기존 Pattern B CONTROL/TEST 산출물은 커밋된 frozen reference로 읽었어. FAST Core V2도 저장된 공식 요약만 사용했어.

## Realized gross — window 비교

P2-1/P2-2와 P3-1/P3-2는 기간 종료일이 다른 창이야. 아래에서는 frozen CONTROL/TEST, 사후 E/T 거래 묶음, 독립 NEW_TEST를 함께 보여줘.

| Window | Scenario | Filled | Realized | Open | Mean | Win rate | Median | +30 | +50 | +100 | -30 | -40 | -50 | -60 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | CONTROL | 798 | 715 | 83 | 12.01% | 77.20% | 12.10% | 125 | 44 | 7 | 50 | 29 | 18 | 11 |
| P1 | FROZEN_TEST | 694 | 622 | 72 | 12.52% | 78.94% | 12.25% | 109 | 39 | 6 | 39 | 21 | 14 | 9 |
| P1 | POSTHOC_EARLY_TRANSITION | 582 | 521 | 61 | 13.22% | 80.04% | 12.63% | 94 | 33 | 6 | 30 | 17 | 11 | 7 |
| P1 | NEW_TEST | 582 | 521 | 61 | 13.22% | 80.04% | 12.63% | 94 | 33 | 6 | 30 | 17 | 11 | 7 |
| P2-1 | CONTROL | 329 | 258 | 71 | 15.71% | 81.01% | 13.46% | 52 | 19 | 4 | 12 | 4 | 0 | 0 |
| P2-1 | FROZEN_TEST | 284 | 228 | 56 | 15.74% | 81.14% | 12.80% | 45 | 17 | 4 | 10 | 3 | 0 | 0 |
| P2-1 | POSTHOC_EARLY_TRANSITION | 246 | 199 | 47 | 16.39% | 80.90% | 13.60% | 42 | 16 | 4 | 9 | 3 | 0 | 0 |
| P2-1 | NEW_TEST | 246 | 199 | 47 | 16.39% | 80.90% | 13.60% | 42 | 16 | 4 | 9 | 3 | 0 | 0 |
| P2-2 | CONTROL | 453 | 379 | 74 | 12.84% | 78.63% | 12.65% | 71 | 27 | 4 | 29 | 15 | 8 | 5 |
| P2-2 | FROZEN_TEST | 403 | 339 | 64 | 13.50% | 79.65% | 12.64% | 63 | 25 | 4 | 22 | 11 | 6 | 4 |
| P2-2 | POSTHOC_EARLY_TRANSITION | 353 | 297 | 56 | 14.43% | 80.47% | 13.24% | 58 | 22 | 4 | 17 | 8 | 4 | 2 |
| P2-2 | NEW_TEST | 353 | 297 | 56 | 14.43% | 80.47% | 13.24% | 58 | 22 | 4 | 17 | 8 | 4 | 2 |
| P3-1 | CONTROL | 279 | 215 | 64 | 15.52% | 82.79% | 14.04% | 46 | 16 | 2 | 11 | 3 | 0 | 0 |
| P3-1 | FROZEN_TEST | 236 | 186 | 50 | 15.50% | 83.33% | 13.69% | 39 | 14 | 2 | 9 | 2 | 0 | 0 |
| P3-1 | POSTHOC_EARLY_TRANSITION | 203 | 161 | 42 | 15.89% | 82.61% | 14.25% | 36 | 13 | 2 | 8 | 2 | 0 | 0 |
| P3-1 | NEW_TEST | 203 | 161 | 42 | 15.89% | 82.61% | 14.25% | 36 | 13 | 2 | 8 | 2 | 0 | 0 |
| P3-2 | CONTROL | 403 | 332 | 71 | 13.27% | 80.42% | 13.57% | 65 | 24 | 2 | 24 | 10 | 4 | 2 |
| P3-2 | FROZEN_TEST | 355 | 294 | 61 | 13.82% | 81.63% | 13.28% | 57 | 22 | 2 | 18 | 7 | 3 | 2 |
| P3-2 | POSTHOC_EARLY_TRANSITION | 310 | 257 | 53 | 14.45% | 82.10% | 13.79% | 52 | 19 | 2 | 14 | 5 | 2 | 1 |
| P3-2 | NEW_TEST | 310 | 257 | 53 | 14.45% | 82.10% | 13.79% | 52 | 19 | 2 | 14 | 5 | 2 | 1 |

## 거래 수·보유기간·DEEP·previous Stage 분포

previous Stage 분포는 새 gate 적용 전 현재 Pattern A Stage가 PROGRESSED인 후보 전체 기준이야. Exact/unresolved open은 effective_end cutoff valuation 기준이야.

보유기간은 CONTROL/FROZEN_TEST/POSTHOC/NEW_TEST 모두 각 scenario의 전체 filled ledger(realized + cutoff-open) 기준이야.

| Window | Scenario | Filled | Mean holding sessions | Median holding sessions |
|---|---|---:|---:|---:|
| P1 | CONTROL | 798 | 188.24 | 44.0 |
| P1 | FROZEN_TEST | 694 | 177.97 | 43.0 |
| P1 | POSTHOC_EARLY_TRANSITION | 582 | 168.83 | 43.0 |
| P1 | NEW_TEST | 582 | 168.83 | 43.0 |
| P2-1 | CONTROL | 329 | 175.11 | 60.0 |
| P2-1 | FROZEN_TEST | 284 | 168.55 | 44.0 |
| P2-1 | POSTHOC_EARLY_TRANSITION | 246 | 167.94 | 44.0 |
| P2-1 | NEW_TEST | 246 | 167.94 | 44.0 |
| P2-2 | CONTROL | 453 | 169.54 | 43.0 |
| P2-2 | FROZEN_TEST | 403 | 158.61 | 43.0 |
| P2-2 | POSTHOC_EARLY_TRANSITION | 353 | 155.43 | 43.0 |
| P2-2 | NEW_TEST | 353 | 155.43 | 43.0 |
| P3-1 | CONTROL | 279 | 173.58 | 62.0 |
| P3-1 | FROZEN_TEST | 236 | 168.17 | 62.0 |
| P3-1 | POSTHOC_EARLY_TRANSITION | 203 | 168.77 | 61.0 |
| P3-1 | NEW_TEST | 203 | 168.77 | 61.0 |
| P3-2 | CONTROL | 403 | 165.11 | 43.0 |
| P3-2 | FROZEN_TEST | 355 | 154.03 | 43.0 |
| P3-2 | POSTHOC_EARLY_TRANSITION | 310 | 150.89 | 43.0 |
| P3-2 | NEW_TEST | 310 | 150.89 | 43.0 |

| Window | Allowed signals | Filled | Realized / open | Exact open / unresolved | Mean / median holding sessions | Mean MFE / MAE | DEEP count / filled rate | Previous-stage distribution |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| P1 | 584 | 582 | 521 / 61 | 52 / 9 | 168.8 / 43.0 | 35.13% / -22.51% | 106 / 18.21% | BASE 42, EARLY_TREND 285, TRANSITION 299, UNAVAILABLE 70, WEAK 107 |
| P2-1 | 247 | 246 | 199 / 47 | 43 / 4 | 167.9 / 44.0 | 35.29% / -22.68% | 56 / 22.76% | BASE 20, EARLY_TREND 120, TRANSITION 127, UNAVAILABLE 18, WEAK 47 |
| P2-2 | 355 | 353 | 297 / 56 | 52 / 4 | 155.4 / 43.0 | 35.49% / -22.62% | 69 / 19.55% | BASE 24, EARLY_TREND 176, TRANSITION 179, UNAVAILABLE 26, WEAK 52 |
| P3-1 | 204 | 203 | 161 / 42 | 39 / 3 | 168.8 / 61.0 | 31.81% / -23.67% | 50 / 24.63% | BASE 16, EARLY_TREND 93, TRANSITION 111, UNAVAILABLE 17, WEAK 45 |
| P3-2 | 312 | 310 | 257 / 53 | 50 / 3 | 150.9 / 43.0 | 33.24% / -23.11% | 63 / 20.32% | BASE 20, EARLY_TREND 149, TRANSITION 163, UNAVAILABLE 25, WEAK 50 |

## NEW_TEST vs frozen TEST

| Window | Mean Δ | Win rate Δ | Median Δ | Filled Δ | -30 rate Δ | -40 rate Δ | -50 rate Δ | -60 rate Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 0.70pp | 1.10pp | 0.38pp | -112.0 (-16.14%) | -0.51pp | -0.11pp | -0.14pp | -0.10pp |
| P2-1 | 0.65pp | -0.24pp | 0.80pp | -38.0 (-13.38%) | 0.14pp | 0.19pp | 0.00pp | 0.00pp |
| P2-2 | 0.93pp | 0.83pp | 0.60pp | -50.0 (-12.41%) | -0.77pp | -0.55pp | -0.42pp | -0.51pp |
| P3-1 | 0.40pp | -0.72pp | 0.55pp | -33.0 (-13.98%) | 0.13pp | 0.17pp | 0.00pp | 0.00pp |
| P3-2 | 0.63pp | 0.47pp | 0.51pp | -45.0 (-12.68%) | -0.67pp | -0.44pp | -0.24pp | -0.29pp |

## NEW_TEST vs 사후 E/T 거래 묶음

| Window | Mean Δ | Win rate Δ | Median Δ | Filled Δ | -30 rate Δ | -40 rate Δ | -50 rate Δ | -60 rate Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 0.00pp | 0.00pp | 0.00pp | 0 | 0.00pp | 0.00pp | 0.00pp | 0.00pp |
| P2-1 | 0.00pp | 0.00pp | 0.00pp | 0 | 0.00pp | 0.00pp | 0.00pp | 0.00pp |
| P2-2 | 0.00pp | 0.00pp | 0.00pp | 0 | 0.00pp | 0.00pp | 0.00pp | 0.00pp |
| P3-1 | 0.00pp | 0.00pp | 0.00pp | 0 | 0.00pp | 0.00pp | 0.00pp | 0.00pp |
| P3-2 | 0.00pp | 0.00pp | 0.00pp | 0 | 0.00pp | 0.00pp | 0.00pp | 0.00pp |

## Resolved-terminal sensitivity

실현 gross와 effective_end 당일의 exact close로 mark한 open을 합산했어. 미해결 open은 분모에서 제외하고 별도 표기했어.

| Window | Scenario | N | Mean | Positive | Median | Exact open | Unresolved open | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | CONTROL | 782 | 8.40% | 72.25% | 10.59% | 67 | 16 | 80 / 10.23% | 57 / 7.29% | 42 / 5.37% | 32 / 4.09% |
| P1 | FROZEN_TEST | 682 | 8.91% | 73.90% | 10.82% | 60 | 12 | 64 / 9.38% | 45 / 6.60% | 34 / 4.99% | 27 / 3.96% |
| P1 | POSTHOC_EARLY_TRANSITION | 573 | 9.45% | 74.87% | 11.00% | 52 | 9 | 50 / 8.73% | 36 / 6.28% | 26 / 4.54% | 21 / 3.66% |
| P1 | NEW_TEST | 573 | 9.45% | 74.87% | 11.00% | 52 | 9 | 50 / 8.73% | 36 / 6.28% | 26 / 4.54% | 21 / 3.66% |
| P2-1 | CONTROL | 323 | 4.77% | 66.25% | 9.03% | 65 | 6 | 55 / 17.03% | 41 / 12.69% | 22 / 6.81% | 13 / 4.02% |
| P2-1 | FROZEN_TEST | 280 | 5.46% | 67.50% | 8.72% | 52 | 4 | 45 / 16.07% | 33 / 11.79% | 19 / 6.79% | 13 / 4.64% |
| P2-1 | POSTHOC_EARLY_TRANSITION | 242 | 6.94% | 67.77% | 9.15% | 43 | 4 | 36 / 14.88% | 25 / 10.33% | 13 / 5.37% | 8 / 3.31% |
| P2-1 | NEW_TEST | 242 | 6.94% | 67.77% | 9.15% | 43 | 4 | 36 / 14.88% | 25 / 10.33% | 13 / 5.37% | 8 / 3.31% |
| P2-2 | CONTROL | 446 | 6.38% | 69.73% | 10.06% | 67 | 7 | 59 / 13.23% | 43 / 9.64% | 32 / 7.17% | 26 / 5.83% |
| P2-2 | FROZEN_TEST | 399 | 7.18% | 70.93% | 9.98% | 60 | 4 | 47 / 11.78% | 35 / 8.77% | 26 / 6.52% | 22 / 5.51% |
| P2-2 | POSTHOC_EARLY_TRANSITION | 349 | 8.05% | 71.92% | 10.59% | 52 | 4 | 37 / 10.60% | 27 / 7.74% | 19 / 5.44% | 16 / 4.58% |
| P2-2 | NEW_TEST | 349 | 8.05% | 71.92% | 10.59% | 52 | 4 | 37 / 10.60% | 27 / 7.74% | 19 / 5.44% | 16 / 4.58% |
| P3-1 | CONTROL | 274 | 4.45% | 66.79% | 9.18% | 59 | 5 | 48 / 17.52% | 34 / 12.41% | 16 / 5.84% | 9 / 3.28% |
| P3-1 | FROZEN_TEST | 233 | 5.01% | 68.24% | 9.17% | 47 | 3 | 39 / 16.74% | 27 / 11.59% | 14 / 6.01% | 9 / 3.86% |
| P3-1 | POSTHOC_EARLY_TRANSITION | 200 | 6.27% | 68.00% | 9.31% | 39 | 3 | 31 / 15.50% | 20 / 10.00% | 9 / 4.50% | 5 / 2.50% |
| P3-1 | NEW_TEST | 200 | 6.27% | 68.00% | 9.31% | 39 | 3 | 31 / 15.50% | 20 / 10.00% | 9 / 4.50% | 5 / 2.50% |
| P3-2 | CONTROL | 397 | 6.43% | 70.53% | 10.50% | 65 | 6 | 52 / 13.10% | 36 / 9.07% | 26 / 6.55% | 21 / 5.29% |
| P3-2 | FROZEN_TEST | 352 | 7.16% | 71.88% | 10.50% | 58 | 3 | 41 / 11.65% | 29 / 8.24% | 21 / 5.97% | 18 / 5.11% |
| P3-2 | POSTHOC_EARLY_TRANSITION | 307 | 7.84% | 72.64% | 10.79% | 50 | 3 | 32 / 10.42% | 22 / 7.17% | 15 / 4.89% | 13 / 4.23% |
| P3-2 | NEW_TEST | 307 | 7.84% | 72.64% | 10.79% | 50 | 3 | 32 / 10.42% | 22 / 7.17% | 15 / 4.89% | 13 / 4.23% |

## 필수 질문에 대한 답

1. 사후 E/T 추출에서 본 평균 개선은 독립 lifecycle replay에서도 frozen TEST 대비 5/5 창에서 반복됐어. 독립 NEW_TEST와 사후 E/T ledger의 거래 identity는 5/5 창에서 전부 일치해.
2. 중앙값 개선도 frozen TEST 대비 5/5 창에서 반복됐고, NEW_TEST와 사후값은 5/5 창에서 일치해.
3. 승률 하락은 가장 낮은 창도 -0.72pp였고, 2pp 이상 하락한 창은 0개야.
4. BASE / UNAVAILABLE 제거 후 realized -30 count는 5/5 창에서 늘지 않았고, -50 rate 악화는 0/5 창이야. -30 rate는 P2-1/P3-1에서 각각 0.14pp/0.13pp 올랐지만 count는 줄었어. -40/-60을 포함한 count와 rate를 함께 저장했어.
5. 거래 수: NEW_TEST는 previous stage 허용 후보만 새 lifecycle에 넣었어. 창별 전체 filled 및 frozen TEST 대비/사후 추출 대비 차이는 five_window_synthesis.csv의 count 열에 있어.
6. 사후 추출과 독립 replay의 trade set은 다섯 창에서 ticker+ISU+entry signal date identity 기준 전부 일치했어. BASE/UNAVAILABLE 제외 때문에 이번 데이터에서는 다른 진입이나 state path 변화가 발생하지 않았어.
7. P1/P2/P3 방향 일관성은 P1 단일 창, P2 두 창, P3 두 창의 Mean/Median/Win Δ로 판단해. 자세한 값은 realized 비교표 및 CSV에 있어.

## 저장된 FAST Core V2 공식 terminal 참고

FAST Core V2는 같은 날짜 범위의 저장된 공식 V2 control 요약이야. 재실행하지 않았어. 표본 universe, terminal 및 settlement 계약이 Pattern B와 달라 unpaired 참고 비교야.

| Window | FAST mean / win / median | FAST -30 / -40 / -50 / -60 count | NEW resolved mean / positive / median | NEW -30 / -40 / -50 / -60 rate |
|---|---|---|---|---|
| P1 | 9.53% / 30.07% / -15.29% | 109 / 66 / 42 / 31 | 9.45% / 74.87% / 11.00% | 8.73% / 6.28% / 4.54% / 3.66% |
| P2-1 | 3.86% / 32.17% / -15.18% | 37 / 24 / 11 / 6 | 6.94% / 67.77% / 9.15% | 14.88% / 10.33% / 5.37% / 3.31% |
| P2-2 | 7.93% / 30.73% / -15.16% | 57 / 37 / 22 / 13 | 8.05% / 71.92% / 10.59% | 10.60% / 7.74% / 5.44% / 4.58% |
| P3-1 | 0.79% / 29.24% / -15.29% | 22 / 14 / 7 / 4 | 6.27% / 68.00% / 9.31% | 15.50% / 10.00% / 4.50% / 2.50% |
| P3-2 | 6.41% / 27.90% / -15.27% | 37 / 22 / 8 / 5 | 7.84% / 72.64% / 10.79% | 10.42% / 7.17% / 4.89% / 4.23% |

8. FAST Core V2와의 성격 비교는 동일 window 방향 참고에 한정돼. 거래 수와 return 수준만으로 전략 우열을 판정하지 않았고, terminal 계약 차이는 fast_core_v2_terminal_reference.csv에 명시했어.

## 산출물

- window별 test_trade_ledger.csv, test_open_positions.csv, previous_stage_audit.csv, lifecycle_spot_checks.csv, posthoc_trade_set_comparison.csv, summary.json, metadata.json
- five_window_synthesis.csv, resolved_terminal_synthesis.csv, fast_core_v2_terminal_reference.csv, summary.json, metadata.json

## 검증 방식

PIT stage linkage와 Pattern B event key 집합을 매칭해 누락/중복 여부를 확인했어. Repository V2 OHLC는 worker 10으로 불러왔고 silent inner drop을 집계했어. window마다 trade identity/date/state 검사를 수행하고 무작위 30건의 lifecycle spotcheck를 정확 비교했어.
이 검증은 과거 데이터 기반 시뮬레이션 및 내부 계약 검사야. 외부 시세 검수는 이 지시서 범위에 포함되어 있지 않아.
