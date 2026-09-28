# A FAST Core V2 vs Pattern B E/T PROGRESSED 공식 Portfolio Battle

- 실행 상태: **COMPLETE**; validation: **CHECK_REQUIRED**
- 기준 HEAD: `265bd02ea0630d615fef6ad8e99659b4d18b130d`
- 기준 제외 authority: 166 exact `(ticker, ISU_CD)` pairs; ticker-only exclusion 0.
- 실행 worker: 10
- 결과 수: 20/20
- 공통 same-day 진입 순서: `ticker, exact ISU_CD, entry_signal_date, entry_execution_date`.
- coverage 90% 미만 결과는 `CHECK_REQUIRED`로 남겼고, 평가누락을 복구하거나 채우지 않았어.

## Battle A — 전체 universe

| Window | Return V2 / B | Δ return pp | CAGR V2 / B | Δ CAGR pp | MDD V2 / B (type) | Δ MDD pp | Coverage V2 / B |
|---|---:|---:|---:|---:|---|---:|---:|
| P1 | CHECK_REQUIRED (52.33%) / 95.64 | — | — / 5.44 | — | -54.72 / OBSERVED_BELOW_90_COVERAGE · -20.30 / EXACT | 34.42 | 52.33 / 100.00 |
| P2-1 | 50.73 / 27.46 | -23.27 | 9.77 / 5.67 | -4.10 | -36.25 / OBSERVED · -20.50 / EXACT | 15.75 | 99.82 / 100.00 |
| P2-2 | CHECK_REQUIRED (5.19%) / 29.13 | — | — / 4.63 | — | -6.11 / OBSERVED_BELOW_90_COVERAGE · -26.08 / EXACT | -19.97 | 5.19 / 100.00 |
| P3-1 | 16.74 / 17.46 | 0.73 | 4.65 / 4.84 | 0.19 | -38.64 / OBSERVED · -17.08 / EXACT | 21.56 | 99.88 / 100.00 |
| P3-2 | 42.46 / 16.77 | -25.69 | 7.90 / 3.39 | -4.51 | -38.64 / OBSERVED · -27.11 / EXACT | 11.53 | 99.91 / 100.00 |

## Battle B — entry-date exact PIT 시총 ≥ 1조원

| Window | Return V2 / B | Δ return pp | CAGR V2 / B | Δ CAGR pp | MDD V2 / B (type) | Δ MDD pp | Coverage V2 / B |
|---|---:|---:|---:|---:|---|---:|---:|
| P1 | 75.24 / 8.18 | -67.05 | 4.53 / 0.62 | -3.91 | -50.41 / OBSERVED · -3.61 / EXACT | 46.80 | 94.08 / 100.00 |
| P2-1 | 25.18 / 2.50 | -22.69 | 5.24 / 0.56 | -4.68 | -24.36 / OBSERVED · -3.27 / EXACT | 21.10 | 99.63 / 100.00 |
| P2-2 | 61.54 / 7.34 | -54.20 | 8.85 / 1.26 | -7.59 | -26.21 / OBSERVED · -3.64 / EXACT | 22.57 | 99.71 / 100.00 |
| P3-1 | CHECK_REQUIRED (36.57%) / 4.58 | — | — / 1.33 | — | -14.24 / OBSERVED_BELOW_90_COVERAGE · -1.75 / EXACT | 12.49 | 36.57 / 100.00 |
| P3-2 | CHECK_REQUIRED (26.78%) / 9.31 | — | — / 1.93 | — | -14.24 / OBSERVED_BELOW_90_COVERAGE · -3.57 / EXACT | 10.67 | 26.78 / 100.00 |

## 거래 특성 정면 비교

수익률·MDD 이외의 필수 비교 지표야. cash shortage rate 분모는 각 엔진의 eligible entry attempts야.

### Battle A

| Window | Positive rate V2 / B | Median V2 / B | +50 V2 / B | +100 V2 / B | Trades V2 / B | Cash skip count V2 / B | Cash skip rate V2 / B | Turnover KRW V2 / B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 23.85 / 79.24 | -15.64 / 12.08 | 89 / 23 | 35 / 5 | 715 / 464 | 3937 / 19 | 84.63 / 3.93% | 7000092591 / 4673757246 |
| P2-1 | 24.61 / 79.11 | -15.73 / 12.66 | 36 / 11 | 13 / 3 | 370 / 195 | 1330 / 20 | 78.24 / 9.30% | 3483664724 / 1885899802 |
| P2-2 | 27.59 / 76.39 | -15.58 / 11.26 | 58 / 13 | 26 / 3 | 448 / 257 | 1809 / 62 | 80.15 / 19.44% | 4362072718 / 2492900148 |
| P3-1 | 16.83 / 80.99 | -15.86 / 14.00 | 18 / 10 | 5 / 2 | 239 / 156 | 861 / 22 | 78.27 / 12.36% | 2172783409 / 1477900990 |
| P3-2 | 22.39 / 77.01 | -15.70 / 11.73 | 36 / 11 | 14 / 2 | 303 / 214 | 1382 / 68 | 82.02 / 24.11% | 2845101489 / 2039924991 |
### Battle B

| Window | Positive rate V2 / B | Median V2 / B | +50 V2 / B | +100 V2 / B | Trades V2 / B | Cash skip count V2 / B | Cash skip rate V2 / B | Turnover KRW V2 / B |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 26.20 / 83.33 | -15.50 / 12.23 | 55 / 2 | 19 / 1 | 402 / 33 | 311 / 0 | 43.62 / 0.00% | 3933584410 / 332271815 |
| P2-1 | 27.10 / 80.00 | -15.44 / 5.84 | 13 / 2 | 5 / 1 | 195 / 12 | 115 / 0 | 37.10 / 0.00% | 1733830616 / 120729153 |
| P2-2 | 29.82 / 86.96 | -15.20 / 13.31 | 35 / 2 | 13 / 1 | 244 / 26 | 177 / 0 | 42.04 / 0.00% | 2382198405 / 261223884 |
| P3-1 | 22.31 / 87.50 | -15.63 / 8.02 | 11 / 2 | 4 / 1 | 157 / 9 | 79 / 0 | 33.47 / 0.00% | 1365332065 / 96069192 |
| P3-2 | 29.26 / 95.00 | -15.41 / 16.23 | 37 / 2 | 15 / 1 | 213 / 23 | 138 / 0 | 39.32 / 0.00% | 2087821926 / 235271156 |

## 시총 PIT 사전검수

| Strategy | Window | Covered | ≥1조 통과 | <1조 제외 | exact 누락 | Coverage | Status |
|---|---|---:|---:|---:|---:|---:|---|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P1 | 4652 | 713 | 3939 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-1 | 1700 | 310 | 1390 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-2 | 2257 | 421 | 1836 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-1 | 1100 | 236 | 864 | 0 | 100.00% | PASS |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-2 | 1685 | 351 | 1334 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P1 | 483 | 33 | 450 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-1 | 215 | 12 | 203 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-2 | 319 | 26 | 293 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-1 | 178 | 9 | 169 | 0 | 100.00% | PASS |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-2 | 282 | 23 | 259 | 0 | 100.00% | PASS |

## 전체 universe 대비 시총 ≥1조 변화

| Strategy | Window | Return Δ pp | CAGR Δ pp | MDD Δ pp | Trades Δ | Positive rate Δ pp | Median Δ pp | +50 Δ | +100 Δ | Cash skip Δ pp | Turnover Δ KRW |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P1 | — | — | 4.31 | -313 | 2.35 | 0.15 | -34 | -16 | -41.01 | -3066508181 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-1 | -25.54 | -4.54 | 11.89 | -175 | 2.49 | 0.29 | -23 | -8 | -41.14 | -1749834109 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P2-2 | — | — | -20.10 | -204 | 2.22 | 0.38 | -23 | -13 | -38.11 | -1979874313 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-1 | — | — | 24.40 | -82 | 5.48 | 0.23 | -7 | -1 | -44.80 | -807451345 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | P3-2 | — | — | 24.40 | -90 | 6.86 | 0.29 | 1 | 1 | -42.70 | -757279563 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P1 | -87.46 | -4.82 | 16.68 | -431 | 4.10 | 0.16 | -21 | -4 | -3.93 | -4341485431 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-1 | -24.96 | -5.11 | 17.23 | -183 | 0.89 | -6.82 | -9 | -2 | -9.30 | -1765170648 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P2-2 | -21.78 | -3.36 | 22.44 | -231 | 10.57 | 2.05 | -11 | -2 | -19.44 | -2231676264 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-1 | -12.88 | -3.52 | 15.33 | -147 | 6.51 | -5.98 | -8 | -1 | -12.36 | -1381831799 |
| PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01 | P3-2 | -7.46 | -1.46 | 23.54 | -191 | 17.99 | 4.50 | -9 | -1 | -24.11 | -1804653834 |

전체 수치는 `universe_filter_sensitivity.csv`에도 있어.

## 검증 요약

- 구조 검증: **PASS**; 비용 mismatch 0 (V2) / 0 (Pattern B), frozen date/price mismatch 0 (V2), Pattern B next-session 위반 0, 제외 누수 0 (V2) / 0 (Pattern B).
- V2 frozen CONTROL에서 즉시 다음 공통 KRX 세션보다 늦은 실제 체결 schedule: 9건. 원장 날짜·가격과 정확히 일치해 그대로 보존했고 재일정하지 않았어. 상세: `artifacts/strategy_battles/fast_v2_vs_pattern_b_v01/v2_calendar_next_session_deviations.csv`.
- 현금 보존: PASS; 포지션 cap 없음: PASS; Battle B exact PIT entry parity: PASS.
- 90% 미만 valuation coverage 결과: 4건; 최종 상태는 이에 따라 `CHECK_REQUIRED`야.
- 수익률이 낮거나 cash shortage/MDD가 높다는 이유로 실행을 수정하거나 재실행하지 않았어.
- 전략 rule은 동결됐고 cash-shortage 기반 신호 재생성 및 사후 거래 선택은 없어.
- 산출물: `artifacts/strategy_battles/fast_v2_vs_pattern_b_v01/`.
