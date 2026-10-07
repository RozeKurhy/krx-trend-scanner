| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | CONTROL provenance 및 모든 계산 무결성 검증 통과 |
| MAJOR | 0 | 확인된 무결성 차이 없음 |
| MINOR | 2 | MA60 계산 불가 28건은 보간하지 않았고, MA5/10/20 비교 및 resistance 상위 그룹은 표본이 작거나 비어 있어 방향 해석을 제한해야 해 |

## 1. 최종 토큰 / 판단

`FAST_CORE_V2_P3_2_MONTHLY_MA_ENTRY_POSITION_DIAGNOSTIC_V01_COMPLETE`<br>
판단: `MONTHLY_MA_ENTRY_POSITION_STRONG_SIGNAL`

## 2. CONTROL provenance

- CONTROL 토큰: `FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE`; frozen CONTROL 원장 405건.
- 다섯 기준 파일 hash가 이전 frozen replay snapshot 및 HEAD blob과 일치해.
- survivor 2,539개; 최신 rolling authority, API/network, 신규 가격 수집 의존은 0이야.

## 3. 월봉 PIT 계약 / 가격 source

- 진입 비교가격은 CONTROL의 실제 `entry_open`이며, 거래별 anchor는 `entry_execution_date`의 직전 확정 월이야.
- 월봉은 해당 월의 마지막 저장 adjusted close로 만들었고, MA5/10/20/60은 anchor 월까지 연속된 N개 월만 평균했어. 데이터가 빠지거나 부족하면 보간 없이 UNAVAILABLE로 뒀어.
- source: 로컬 Repository V2 AdjustedPriceStore, `ADJUSTED_OHLC_ONLY`, 권위 있는 Naver direct adjusted OHLC partition. 파티션·metadata hash와 date coverage를 기록했어.
- entry open 405건이 저장소 시가와 모두 일치. 진입월 또는 그 이후 월봉이 계산에 들어간 건 0건이야.

## 4. MA coverage

| MA | 계산 가능 | 불가 | 불가 사유별 건수 |
|---|---:|---:|---|
| MA5 | 405 | 0 | {} |
| MA10 | 405 | 0 | {} |
| MA20 | 405 | 0 | {} |
| MA60 | 377 | 28 | {"MISSING_MONTHLY_OBSERVATION": 2, "INSUFFICIENT_HISTORY": 26} |

CONTROL 거래 전체 405건. MA별 available + unavailable는 각 405건이야. Resistance 0~4 계산 불가 28건; 사유: `{"MA60:INSUFFICIENT_HISTORY": 26, "MA60:MISSING_MONTHLY_OBSERVATION": 2}`.

## 5. MA5/10/20/60 개별 비교

각 셀은 Above / At-or-below / 차이(pp) 순서야. MA 별 full metrics는 `ma_binary_metrics.csv`에 있어.

| MA | Above n | At/below n | 승률 % A/B/Δ | 평균 terminal % A/B/Δ | 중앙 terminal % A/B/Δ | Loss Guard율 % A/B/Δ | PROGRESSED율 % A/B/Δ | MFE +50율 % A/B/Δ | MFE +100율 % A/B/Δ | MAE -30율 % A/B/Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MA5 | 402 | 3 | 32.70 / 50 / -17.30 | 16.99 / 72.37 / -55.38 | -14.56 / 65.27 / -79.83 | 57.21 / 33.33 / 23.88 | 72.64 / 33.33 / 39.30 | 34.83 / 66.67 / -31.84 | 17.66 / 33.33 / -15.67 | 2.24 / 0 / 2.24 |
| MA10 | 403 | 2 | 32.79 / — / — | 17.46 / 4.41 / 13.05 | -14.59 / 4.41 / -19.00 | 57.32 / 0 / 57.32 | 72.70 / 0 / 72.70 | 34.99 / 50 / -15.01 | 17.87 / 0 / 17.87 | 2.23 / 0 / 2.23 |
| MA20 | 380 | 25 | 33.72 / 18.18 / 15.54 | 18.14 / 6.10 / 12.05 | -14.50 / -15.05 / 0.55 | 56.05 / 72 / -15.95 | 72.89 / 64 / 8.89 | 35.79 / 24 / 11.79 | 18.16 / 12 / 6.16 | 2.37 / 0 / 2.37 |
| MA60 | 274 | 103 | 35.20 / 27.96 / 7.24 | 19.43 / 11.74 / 7.69 | -14.34 / -14.96 / 0.62 | 54.74 / 60.19 / -5.45 | 77.74 / 59.22 / 18.51 | 35.40 / 33.98 / 1.42 | 19.34 / 13.59 / 5.75 | 2.55 / 1.94 / 0.61 |

`ENTRY_ABOVE`는 entry_open > MA, `ENTRY_AT_OR_BELOW`는 entry_open <= MA야. 비교 불가 거래는 별도 `UNAVAILABLE` 그룹이야.

## 6. Resistance 0~4 비교

| 진입가 위 MA 수 | n | 승률 | 평균 terminal | 중앙 terminal | Loss Guard율 | PROGRESSED율 | Exit3율 | Exit4율 | cutoff 미청산율 | MFE >= +50율 | MFE >= +100율 | MAE <= -30율 |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 259 | 35.59% | 19.62% | -14.17% | 54.05% | 77.99% | 2.70% | 34.36% | 8.88% | 35.91% | 19.31% | 2.70% |
| 1 | 108 | 30.30% | 13.64% | -14.86% | 59.26% | 62.04% | 4.63% | 27.78% | 8.33% | 35.19% | 15.74% | 1.85% |
| 2 | 10 | 0% | -2.42% | -15.28% | 80% | 50% | 0% | 0% | 20% | 10% | 0% | 0% |
| 3 | 0 | —% | —% | —% | —% | —% | —% | —% | —% | —% | —% | —% |
| 4 | 0 | —% | —% | —% | —% | —% | —% | —% | —% | —% | —% | —% |

RESISTANCE_0~4 및 UNAVAILABLE 전체 통계는 `ma_resistance_count_metrics.csv`에 있어.

## 7. Loss Guard / PROGRESSED

| 구분 | 그룹 | n | Loss Guard n (율) | PROGRESSED n (율) | Exit3 n (율) | Exit4 n (율) | cutoff 미청산 n (율) |
|---|---|---:|---:|---:|---:|---:|---:|
| MA5 | ENTRY_ABOVE | 402 | 230 (57.21%) | 292 (72.64%) | 12 (2.99%) | 125 (31.09%) | 35 (8.71%) |
| MA5 | ENTRY_AT_OR_BELOW | 3 | 1 (33.33%) | 1 (33.33%) | 0 (0%) | 1 (33.33%) | 1 (33.33%) |
| MA10 | ENTRY_ABOVE | 403 | 231 (57.32%) | 293 (72.70%) | 12 (2.98%) | 126 (31.27%) | 34 (8.44%) |
| MA10 | ENTRY_AT_OR_BELOW | 2 | 0 (0%) | 0 (0%) | 0 (0%) | 0 (0%) | 2 (100%) |
| MA20 | ENTRY_ABOVE | 380 | 213 (56.05%) | 277 (72.89%) | 11 (2.89%) | 123 (32.37%) | 33 (8.68%) |
| MA20 | ENTRY_AT_OR_BELOW | 25 | 18 (72%) | 16 (64%) | 1 (4%) | 3 (12%) | 3 (12%) |
| MA60 | ENTRY_ABOVE | 274 | 150 (54.74%) | 213 (77.74%) | 8 (2.92%) | 92 (33.58%) | 24 (8.76%) |
| MA60 | ENTRY_AT_OR_BELOW | 103 | 62 (60.19%) | 61 (59.22%) | 4 (3.88%) | 27 (26.21%) | 10 (9.71%) |
| Resistance 0 | all MA status | 259 | 140 (54.05%) | 202 (77.99%) | 7 (2.70%) | 89 (34.36%) | 23 (8.88%) |
| Resistance 1 | all MA status | 108 | 64 (59.26%) | 67 (62.04%) | 5 (4.63%) | 30 (27.78%) | 9 (8.33%) |
| Resistance 2 | all MA status | 10 | 8 (80%) | 5 (50%) | 0 (0%) | 0 (0%) | 2 (20%) |
| Resistance 3 | all MA status | 0 | 0 (—%) | 0 (—%) | 0 (—%) | 0 (—%) | 0 (—%) |
| Resistance 4 | all MA status | 0 | 0 (—%) | 0 (—%) | 0 (—%) | 0 (—%) | 0 (—%) |

PROGRESSED는 거래 lifecycle의 사후 관측값으로 진입 예측 신호가 아니야.

## 8. MFE / MAE / 대형 승리·손실

| 구분 | 그룹 | n | Terminal >= +20 / +50 / +100 | Terminal <= -20 / -30 / -40 | Realized <= -20 / -30 / -40 | MFE >= +20 / +50 / +100 | MAE <= -20 / -30 / -40 |
|---|---|---:|---:|---:|---:|---:|---:|
| MA 분류 | MA5 ENTRY_ABOVE | 402 | 119 (29.60%) / 93 (23.13%) / 37 (9.20%) | 20 (4.98%) / 4 (1.00%) / 2 (0.50%) | 18 (4.90%) / 3 (0.82%) / 1 (0.27%) | 208 (51.74%) / 140 (34.83%) / 71 (17.66%) | 52 (12.94%) / 9 (2.24%) / 4 (1.00%) |
| MA 분류 | MA5 ENTRY_AT_OR_BELOW | 3 | 2 (66.67%) / 2 (66.67%) / 1 (33.33%) | 0 (0%) / 0 (0%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) | 2 (66.67%) / 2 (66.67%) / 1 (33.33%) | 0 (0%) / 0 (0%) / 0 (0%) |
| MA 분류 | MA5 UNAVAILABLE | 0 | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) |
| MA 분류 | MA10 ENTRY_ABOVE | 403 | 121 (30.02%) / 95 (23.57%) / 38 (9.43%) | 20 (4.96%) / 4 (0.99%) / 2 (0.50%) | 18 (4.88%) / 3 (0.81%) / 1 (0.27%) | 208 (51.61%) / 141 (34.99%) / 72 (17.87%) | 52 (12.90%) / 9 (2.23%) / 4 (0.99%) |
| MA 분류 | MA10 ENTRY_AT_OR_BELOW | 2 | 0 (0%) / 0 (0%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) | 0 (—%) / 0 (—%) / 0 (—%) | 2 (100%) / 1 (50%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) |
| MA 분류 | MA10 UNAVAILABLE | 0 | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) |
| MA 분류 | MA20 ENTRY_ABOVE | 380 | 116 (30.53%) / 90 (23.68%) / 37 (9.74%) | 20 (5.26%) / 4 (1.05%) / 2 (0.53%) | 18 (5.19%) / 3 (0.86%) / 1 (0.29%) | 200 (52.63%) / 136 (35.79%) / 69 (18.16%) | 51 (13.42%) / 9 (2.37%) / 4 (1.05%) |
| MA 분류 | MA20 ENTRY_AT_OR_BELOW | 25 | 5 (20%) / 5 (20%) / 1 (4%) | 0 (0%) / 0 (0%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) | 10 (40%) / 6 (24%) / 3 (12%) | 1 (4%) / 0 (0%) / 0 (0%) |
| MA 분류 | MA20 UNAVAILABLE | 0 | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) |
| MA 분류 | MA60 ENTRY_ABOVE | 274 | 84 (30.66%) / 67 (24.45%) / 26 (9.49%) | 15 (5.47%) / 3 (1.09%) / 1 (0.36%) | 15 (6%) / 3 (1.20%) / 1 (0.40%) | 143 (52.19%) / 97 (35.40%) / 53 (19.34%) | 38 (13.87%) / 7 (2.55%) / 3 (1.09%) |
| MA 분류 | MA60 ENTRY_AT_OR_BELOW | 103 | 30 (29.13%) / 22 (21.36%) / 9 (8.74%) | 5 (4.85%) / 1 (0.97%) / 1 (0.97%) | 3 (3.23%) / 0 (0%) / 0 (0%) | 54 (52.43%) / 35 (33.98%) / 14 (13.59%) | 13 (12.62%) / 2 (1.94%) / 1 (0.97%) |
| MA 분류 | MA60 UNAVAILABLE | 28 | 7 (25%) / 6 (21.43%) / 3 (10.71%) | 0 (0%) / 0 (0%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) | 13 (46.43%) / 10 (35.71%) / 5 (17.86%) | 1 (3.57%) / 0 (0%) / 0 (0%) |
| Resistance | RESISTANCE_0 | 259 | 80 (30.89%) / 63 (24.32%) / 25 (9.65%) | 15 (5.79%) / 3 (1.16%) / 1 (0.39%) | 15 (6.36%) / 3 (1.27%) / 1 (0.42%) | 136 (52.51%) / 93 (35.91%) / 50 (19.31%) | 38 (14.67%) / 7 (2.70%) / 3 (1.16%) |
| Resistance | RESISTANCE_1 | 108 | 33 (30.56%) / 25 (23.15%) / 10 (9.26%) | 5 (4.63%) / 1 (0.93%) / 1 (0.93%) | 3 (3.03%) / 0 (0%) / 0 (0%) | 58 (53.70%) / 38 (35.19%) / 17 (15.74%) | 12 (11.11%) / 2 (1.85%) / 1 (0.93%) |
| Resistance | RESISTANCE_2 | 10 | 1 (10%) / 1 (10%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) | 3 (30%) / 1 (10%) / 0 (0%) | 1 (10%) / 0 (0%) / 0 (0%) |
| Resistance | RESISTANCE_3 | 0 | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) |
| Resistance | RESISTANCE_4 | 0 | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) | 0 (—%) / 0 (—%) / 0 (—%) |
| Resistance | UNAVAILABLE | 28 | 7 (25%) / 6 (21.43%) / 3 (10.71%) | 0 (0%) / 0 (0%) / 0 (0%) | 0 (0%) / 0 (0%) / 0 (0%) | 13 (46.43%) / 10 (35.71%) / 5 (17.86%) | 1 (3.57%) / 0 (0%) / 0 (0%) |

각 셀은 count (group 내 비율 %) 순서야. Terminal, realized tail, MFE, MAE를 분리해서 집계했어.

## 9. 실제 portfolio 체결 진단

기존 CONTROL의 실제 체결 entry/exit만 `pair_id`로 연결했어. 순 실현손익은 매수 notional+commission과 매도 notional-commission-sell tax의 차이야. 체결가에 반영된 슬리피지는 다시 빼지 않았어.

| Dimension | Group | 실제 진입 | 실현 | 실현 승률 | 평균 / 중앙 순 실현수익률 | 순 >= +50 / +100 | 순 <= -30 / -40 | 순 실현손익 | 기여율 |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MA5 | ENTRY_ABOVE | 225 | 205 | 30.24% | 13.83% / -15.59% | 42 / 20 | 2 / 1 | 141,556,084원 | 94.99% |
| MA5 | ENTRY_AT_OR_BELOW | 3 | 2 | 50% | 75.16% / 75.16% | 1 / 1 | 0 / 0 | 7,469,992원 | 5.01% |
| MA5 | UNAVAILABLE | 0 | 0 | —% | —% / —% | 0 / 0 | 0 / 0 | 0원 | 0% |
| MA10 | ENTRY_ABOVE | 227 | 207 | 30.43% | 14.43% / -15.59% | 43 / 21 | 2 / 1 | 149,026,077원 | 100% |
| MA10 | ENTRY_AT_OR_BELOW | 1 | 0 | —% | —% / —% | 0 / 0 | 0 / 0 | 0원 | 0% |
| MA10 | UNAVAILABLE | 0 | 0 | —% | —% / —% | 0 / 0 | 0 / 0 | 0원 | 0% |
| MA20 | ENTRY_ABOVE | 209 | 189 | 31.22% | 15.22% / -15.59% | 40 / 20 | 2 / 1 | 143,523,684원 | 96.31% |
| MA20 | ENTRY_AT_OR_BELOW | 19 | 18 | 22.22% | 6.10% / -15.53% | 3 / 1 | 0 / 0 | 5,502,392원 | 3.69% |
| MA20 | UNAVAILABLE | 0 | 0 | —% | —% / —% | 0 / 0 | 0 / 0 | 0원 | 0% |
| MA60 | ENTRY_ABOVE | 149 | 137 | 33.58% | 16.92% / -15.69% | 30 / 15 | 2 / 1 | 115,799,750원 | 77.70% |
| MA60 | ENTRY_AT_OR_BELOW | 63 | 56 | 25% | 6.50% / -15.54% | 10 / 4 | 0 / 0 | 18,173,984원 | 12.20% |
| MA60 | UNAVAILABLE | 16 | 14 | 21.43% | 21.74% / -15.64% | 3 / 2 | 0 / 0 | 15,052,342원 | 10.10% |
| RESISTANCE_COUNT | RESISTANCE_0 | 138 | 126 | 33.33% | 16.29% / -15.73% | 27 / 14 | 2 / 1 | 102,606,093원 | 68.85% |
| RESISTANCE_COUNT | RESISTANCE_1 | 67 | 60 | 30% | 12.35% / -15.38% | 13 / 5 | 0 / 0 | 36,932,413원 | 24.78% |
| RESISTANCE_COUNT | RESISTANCE_2 | 7 | 7 | 0% | -15.98% / -15.99% | 0 / 0 | 0 / 0 | -5,564,771원 | -3.73% |
| RESISTANCE_COUNT | RESISTANCE_3 | 0 | 0 | —% | —% / —% | 0 / 0 | 0 / 0 | 0원 | 0% |
| RESISTANCE_COUNT | RESISTANCE_4 | 0 | 0 | —% | —% / —% | 0 / 0 | 0 / 0 | 0원 | 0% |
| RESISTANCE_COUNT | UNAVAILABLE | 16 | 14 | 21.43% | 21.74% / -15.64% | 3 / 2 | 0 / 0 | 15,052,342원 | 10.10% |

전체 실제 진입 228건, 실현 207건, 현금 부족 skip 177건, 순 실현손익 149,026,077원이야.

## 10. 단조성 여부

- MA20 Above vs At/Below 핵심 방향: `{"realized_win_rate_pct": true, "median_terminal_return_pct": true, "average_terminal_return_pct": true}`
- RESISTANCE_0 vs RESISTANCE_1~4 pooled: `{"realized_win_rate_pct": true, "median_terminal_return_pct": true, "average_terminal_return_pct": true, "loss_guard_exit_rate_pct_lower": true, "mae_le_neg_30_rate_pct_lower": false}`
- Resistance count 증가 방향 체크: `{"realized_win_rate_pct_nonincreasing": false, "average_terminal_return_pct_nonincreasing": false, "median_terminal_return_pct_nonincreasing": false, "loss_guard_exit_rate_pct_nondecreasing": false, "mae_le_neg_30_rate_pct_nondecreasing": false}`
- 통계적 유의성은 검사하거나 주장하지 않았고, cutoff 탐색·회귀·threshold tuning도 하지 않았어.

## 11. 후속 필터 백테스트 추천 여부

`MONTHLY_MA_ENTRY_POSITION_STRONG_SIGNAL`. `후보 백테스트 별도 검토를 추천`. MA20 Above 핵심 세 지표는 모두 At/Below보다 높았지만 비교 표본은 각각 380건과 25건이야. 이는 방향성 후보일 뿐 통계적 유의성을 뜻하지 않아. Resistance 0→4 단조 패턴은 없고 3·4 그룹은 비어 있어. 이번 진단에서 필터를 적용하거나 후속 백테스트를 실행하지 않았어.

## 12. 검증 / Git status

- 결과 토큰은 모든 무결성 검증 통과 후에만 COMPLETE로 설정했어.
- Check 요약: `{"control_trade_count_exact_405": true, "control_pair_id_unique": true, "realized_plus_open_equals_control_count": true, "ma_available_plus_unavailable_equals_control_for_each_ma": true, "resistance_0_to_4_plus_unavailable_equals_control": true, "no_current_or_future_month_used": true, "entry_open_matches_adjusted_price_store": true, "monthly_adjusted_price_hash_and_coverage_verified": true, "control_entry_dates_match_frozen_calendar": true, "all_actual_portfolio_events_reconcile_to_control_summary": true, "portfolio_ma_groups_reconcile_entries_exits_and_pnl": true, "network_api_or_new_price_calls": 0, "production_canonical_changes": 0}`
- HEAD: `f2e4cabe4ab867c7f0cc5a90fb20a10b3b361e70`; origin/main: `f2e4cabe4ab867c7f0cc5a90fb20a10b3b361e70`.
- commit/push는 하지 않았고, tracked production/canonical 파일 변경도 없어. 기존 unrelated 미추적 research 산출물은 그대로 뒀어.
