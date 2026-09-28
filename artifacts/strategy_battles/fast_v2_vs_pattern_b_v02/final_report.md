# V2 vs Pattern B 3-Way Portfolio Battle V02

- 실행 상태: **COMPLETE**; 검증: **CHECK_REQUIRED**.
- 결과: **30/30**; worker: **10**; permanent exclusions: **166 → 173** exact pairs.
- 기준 HEAD: `a4bc4f6895a3550746cac07450bef79210753cd8`; same-day entry order: `ticker, exact ISU_CD, entry_signal_date, entry_execution_date`.
- 초기자본 2억원, 종목별 500만원 예산, 재투자, position cap 없음, 정수주, partial fill/pyramiding 없음, commission 0.015%, slippage 0.1%, sell tax 0%.
- Coverage 90% 미만은 CHECK_REQUIRED로 남기고 수정·보간·재실행하지 않았어.

## Battle A — 전체 universe

| Window | Return V2 / B | Δ pp | CAGR V2 / B | MDD V2 / B | Coverage V2 / B | Eligible V2 / B | Executed / closed (V2 · B) | Cash skip % V2 / B | Positive % V2 / B | Median % V2 / B | +50 / +100 V2 / B | Turnover KRW V2 / B | Avg util % V2 / B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 105.88 / 95.64 | -10.24 | 5.87 / 5.44 | -54.61 (OBSERVED) / -20.30 (EXACT) | 95.46 / 100.00 | 4638 / 483 | 701 / 640 · 464 / 419 | 84.89 / 3.93 | 23.91 / 79.24 | -15.64 / 12.08 | 87 / 23 · 34 / 5 | 6858422764 / 4673757246 | 95.04 / 27.82 |
| P2-1 | 50.73 / 27.46 | -23.27 | 9.77 / 5.67 | -36.25 (OBSERVED) / -20.50 (EXACT) | 99.82 / 100.00 | 1700 / 215 | 370 / 321 · 195 / 158 | 78.24 / 9.30 | 24.61 / 79.11 | -15.73 / 12.66 | 36 / 11 · 13 / 3 | 3483664724 / 1885899802 | 92.43 / 46.16 |
| P2-2 | 91.38 / 29.13 | -62.25 | 12.17 / 4.63 | -34.98 (OBSERVED) / -26.08 (EXACT) | 99.71 / 100.00 | 2249 / 319 | 455 / 404 · 257 / 216 | 79.77 / 19.44 | 26.73 / 76.39 | -15.62 / 11.26 | 59 / 13 · 26 / 3 | 4433681207 / 2492900148 | 92.41 / 45.57 |
| P3-1 | 16.74 / 17.46 | 0.73 | 4.65 / 4.84 | -38.64 (OBSERVED) / -17.08 (EXACT) | 99.88 / 100.00 | 1098 / 178 | 239 / 202 · 156 / 121 | 78.23 / 12.36 | 16.83 / 80.99 | -15.86 / 14.00 | 18 / 10 · 5 / 2 | 2172783409 / 1477900990 | 89.46 / 57.05 |
| P3-2 | 42.46 / 16.77 | -25.69 | 7.90 / 3.39 | -38.64 (OBSERVED) / -27.11 (EXACT) | 99.91 / 100.00 | 1683 / 282 | 303 / 259 · 214 / 174 | 82.00 / 24.11 | 22.39 / 77.01 | -15.70 / 11.73 | 36 / 11 · 14 / 2 | 2845101489 / 2039924991 | 90.58 / 54.12 |

## Battle B — entry-date exact PIT 시총 ≥ 1조원

| Window | Return V2 / B | Δ pp | CAGR V2 / B | MDD V2 / B | Coverage V2 / B | Eligible V2 / B | Executed / closed (V2 · B) | Cash skip % V2 / B | Positive % V2 / B | Median % V2 / B | +50 / +100 V2 / B | Turnover KRW V2 / B | Avg util % V2 / B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 76.43 / 8.18 | -68.25 | 4.59 / 0.62 | -49.67 (OBSERVED) / -3.61 (EXACT) | 94.08 / 100.00 | 711 / 33 | 415 / 388 · 33 / 30 | 41.63 / 0.00 | 26.29 / 83.33 | -15.51 / 12.23 | 59 / 2 · 19 / 1 | 4072525669 / 332271815 | 87.44 / 1.84 |
| P2-1 | 25.18 / 2.50 | -22.69 | 5.24 / 0.56 | -24.36 (OBSERVED) / -3.27 (EXACT) | 99.63 / 100.00 | 310 / 12 | 195 / 155 · 12 / 10 | 37.10 / 0.00 | 27.10 / 80.00 | -15.44 / 5.84 | 13 / 2 · 5 / 1 | 1733830616 / 120729153 | 83.42 / 2.47 |
| P2-2 | 61.54 / 7.34 | -54.20 | 8.85 / 1.26 | -26.21 (OBSERVED) / -3.64 (EXACT) | 99.71 / 100.00 | 419 / 26 | 244 / 218 · 26 / 23 | 41.77 / 0.00 | 29.82 / 86.96 | -15.20 / 13.31 | 35 / 2 · 13 / 1 | 2382198405 / 261223884 | 85.10 / 2.76 |
| P3-1 | 24.32 / 4.58 | -19.74 | 6.61 / 1.33 | -14.30 (OBSERVED) / -1.75 (EXACT) | 98.92 / 100.00 | 235 / 9 | 165 / 130 · 9 / 8 | 29.79 / 0.00 | 23.08 / 87.50 | -15.59 / 8.02 | 12 / 2 · 4 / 1 | 1449181469 / 96069192 | 73.97 / 1.95 |
| P3-2 | 71.29 / 9.31 | -61.98 | 12.25 / 1.93 | -16.63 (OBSERVED) / -3.57 (EXACT) | 99.21 / 100.00 | 350 / 23 | 223 / 199 · 23 / 20 | 36.29 / 0.00 | 30.15 / 95.00 | -15.33 / 16.23 | 39 / 2 · 15 / 1 | 2197717508 / 235271156 | 76.60 / 2.42 |

## Battle C — entry-date exact PIT KOSPI only (시총 필터 없음)

| Window | Return V2 / B | Δ pp | CAGR V2 / B | MDD V2 / B | Coverage V2 / B | Eligible V2 / B | Executed / closed (V2 · B) | Cash skip % V2 / B | Positive % V2 / B | Median % V2 / B | +50 / +100 V2 / B | Turnover KRW V2 / B | Avg util % V2 / B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | — / 43.02 | — | — / 2.87 | -46.27 (OBSERVED_BELOW_90_COVERAGE) / -10.59 (EXACT) | 63.34 / 100.00 | 2046 / 164 | 553 / 511 · 164 / 156 | 72.97 / 0.00 | 23.29 / 79.49 | -15.61 / 9.88 | 63 / 10 · 26 / 2 | 5379157351 / 1691312185 | 91.93 / 12.27 |
| P2-1 | — / 13.98 | — | — / 3.02 | -27.02 (OBSERVED_BELOW_90_COVERAGE) / -10.66 (EXACT) | 45.47 / 100.00 | 794 / 70 | 279 / 241 · 70 / 62 | 64.86 / 0.00 | 24.48 / 79.03 | -15.58 / 12.45 | 20 / 5 · 5 / 0 | 2572528478 / 704807161 | 75.59 / 18.60 |
| P2-2 | — / 23.22 | — | — / 3.76 | -26.96 (OBSERVED_BELOW_90_COVERAGE) / -10.66 (EXACT) | 35.47 / 100.00 | 1033 / 101 | 323 / 291 · 101 / 93 | 68.73 / 0.00 | 26.12 / 79.57 | -15.51 / 10.92 | 34 / 6 · 14 / 0 | 3096986260 / 1023324304 | 77.33 / 16.96 |
| P3-1 | — / 14.41 | — | — / 4.04 | -24.62 (OBSERVED_BELOW_90_COVERAGE) / -8.64 (EXACT) | 29.14 / 100.00 | 485 / 58 | 178 / 151 · 58 / 52 | 63.30 / 0.00 | 13.91 / 78.85 | -15.98 / 14.44 | 8 / 5 · 1 / 0 | 1570931886 / 588500308 | 59.28 / 20.72 |
| P3-2 | — / 23.94 | — | — / 4.72 | -24.62 (OBSERVED_BELOW_90_COVERAGE) / -8.64 (EXACT) | 21.33 / 100.00 | 746 / 89 | 210 / 183 · 89 / 82 | 71.85 / 0.00 | 18.58 / 80.49 | -15.74 / 11.89 | 17 / 6 · 7 / 0 | 1929905283 / 905724686 | 59.28 / 18.03 |

## PIT authority 사전검수

### Battle B exact PIT 시총

| Strategy | Window | Covered | ≥1조 | <1조 | Missing | Coverage | Status |
|---|---|---:|---:|---:|---:|---:|---|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P1 | 4638 | 711 | 3927 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-1 | 1700 | 310 | 1390 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-2 | 2249 | 419 | 1830 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-1 | 1098 | 235 | 863 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-2 | 1683 | 350 | 1333 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P1 | 483 | 33 | 450 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-1 | 215 | 12 | 203 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-2 | 319 | 26 | 293 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-1 | 178 | 9 | 169 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-2 | 282 | 23 | 259 | 0 | 100.00% | PASS |

### Battle C exact PIT market

| Strategy | Window | Candidates | KOSPI eligible | Non-KOSPI rejected | Authority missing | Status |
|---|---|---:|---:|---:|---:|---|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P1 | 4638 | 2046 | 2592 | 0 | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-1 | 1700 | 794 | 906 | 0 | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-2 | 2249 | 1033 | 1216 | 0 | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-1 | 1098 | 485 | 613 | 0 | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-2 | 1683 | 746 | 937 | 0 | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P1 | 483 | 164 | 319 | 0 | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-1 | 215 | 70 | 145 | 0 | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-2 | 319 | 101 | 218 | 0 | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-1 | 178 | 58 | 120 | 0 | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-2 | 282 | 89 | 193 | 0 | PASS |

Allowed frozen signal authority audit:

| Strategy | Window | Signals | KOSPI | Rejected | Missing |
|---|---|---:|---:|---:|---:|
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P1 | 485 | 165 | 320 | 0 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-1 | 216 | 71 | 145 | 0 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-2 | 321 | 102 | 219 | 0 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-1 | 179 | 59 | 120 | 0 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-2 | 284 | 90 | 194 | 0 |

## Universe sensitivity

B−A는 PIT 시총 ≥1조 filter 효과, C−A는 KOSPI-only 효과야. 각 전략 안에서만 비교했어.

| Strategy | Window | Return Δ B−A / C−A | CAGR Δ B−A / C−A | MDD Δ B−A / C−A | Trades Δ B−A / C−A | Positive rate Δ B−A / C−A | Median Δ B−A / C−A | +50 Δ B−A / C−A | +100 Δ B−A / C−A | Cash skip Δ B−A / C−A | Avg util Δ B−A / C−A |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P1 | -29.45 / — | -1.28 / — | 4.94 / 8.34 | -286 / -148 | 2.38 / -0.62 | 0.13 / 0.03 | -28 / -24 | -15 / -8 | -43.25 / -11.91 | -7.60 / -3.12 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-1 | -25.54 / — | -4.54 / — | 11.89 / 9.23 | -175 / -91 | 2.49 / -0.13 | 0.29 / 0.15 | -23 / -16 | -8 / -8 | -41.14 / -13.37 | -9.02 / -16.84 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-2 | -29.84 / — | -3.31 / — | 8.77 / 8.02 | -211 / -132 | 3.08 / -0.62 | 0.42 / 0.10 | -24 / -25 | -13 / -12 | -38.00 / -11.04 | -7.31 / -15.08 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-1 | 7.59 / — | 1.95 / — | 24.34 / 14.02 | -74 / -61 | 6.25 / -2.92 | 0.27 / -0.12 | -6 / -10 | -1 / -4 | -48.45 / -14.93 | -15.49 / -30.18 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-2 | 28.83 / — | 4.36 / — | 22.01 / 14.02 | -80 / -93 | 7.76 / -3.81 | 0.37 / -0.04 | 3 / -19 | 1 / -7 | -45.71 / -10.15 | -13.98 / -31.30 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P1 | -87.46 / -52.62 | -4.82 / -2.58 | 16.68 / 9.71 | -431 / -300 | 4.10 / 0.25 | 0.16 / -2.20 | -21 / -13 | -4 / -3 | -3.93 / -3.93 | -25.99 / -15.56 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-1 | -24.96 / -13.47 | -5.11 / -2.65 | 17.23 / 9.84 | -183 / -125 | 0.89 / -0.08 | -6.82 / -0.21 | -9 / -6 | -2 / -3 | -9.30 / -9.30 | -43.69 / -27.56 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-2 | -21.78 / -5.91 | -3.36 / -0.86 | 22.44 / 15.42 | -231 / -156 | 10.57 / 3.18 | 2.05 / -0.34 | -11 / -7 | -2 / -3 | -19.44 / -19.44 | -42.81 / -28.61 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-1 | -12.88 / -3.05 | -3.52 / -0.81 | 15.33 / 8.44 | -147 / -98 | 6.51 / -2.15 | -5.98 / 0.44 | -8 / -5 | -1 / -2 | -12.36 / -12.36 | -55.10 / -36.32 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-2 | -7.46 / 7.17 | -1.46 / 1.33 | 23.54 / 18.48 | -191 / -125 | 17.99 / 3.48 | 4.50 / 0.16 | -9 / -5 | -1 / -2 | -24.11 / -24.11 | -51.70 / -36.09 |

## 검증

- 구조 검증: **PASS**; 비용 mismatch 0 (V2) / 0 (Pattern B).
- frozen V2 date/price mismatch: 0; calendar deviation: 16 (원 schedule 유지); Pattern B next-session violation: 0.
- exclusion leakage: 0 (V2) / 0 (Pattern B); cash conservation: True; no position cap: True.
- Battle B exact PIT cap parity: True; Battle C executed KOSPI PIT parity: True.
- Coverage <90%: 5 result(s); status **CHECK_REQUIRED**.
- Output: `artifacts/strategy_battles/fast_v2_vs_pattern_b_v02/`.
