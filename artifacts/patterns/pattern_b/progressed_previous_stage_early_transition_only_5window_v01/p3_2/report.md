# P3-2: NEW_TEST previous Pattern A stage EARLY_TREND / TRANSITION

Effective: 2022-01-03 through 2026-08-31; support: 2026-09-01.
Only NEW_TEST was replayed. Frozen Pattern B CONTROL/TEST were read from committed artifacts.

## NEW_TEST realized gross

| Filled | Realized | Open | Mean | Win rate | Median | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 310 | 257 | 53 | 14.45% | 82.10% | 13.79% | 14 / 5.45% | 5 / 1.95% | 2 / 0.78% | 1 / 0.39% |

## 이전 Stage 후보 분포

- BASE: 20
- EARLY_TREND: 149
- TRANSITION: 163
- UNAVAILABLE: 25
- WEAK: 50

## 무결성

- new_test_previous_stage_forbidden_fill_count: 0
- entry_after_window_end_count: 0
- execution_support_new_entry_count: 0
- future_pattern_a_input_count: 0
- duplicate_trade_identity_count: 0
- duplicate_trade_id_count: 0
- lifecycle_settlement_contract_violation_count: 0
- raw_candidate_key_mismatch_count: 0
- same_isu_overlap_count: 0
- pattern_b_authority_discontinuity_count: 0
- repository_v2_silent_inner_drop_count: 0
- execution_support_exit_fill_count: 51
- new_test_candidate_count: 312
- new_test_filled_count: 310
- new_test_realized_count: 257
- new_test_open_count: 53
- lifecycle_spot_check_count: 30
- lifecycle_spot_check_pass_count: 30
- workers: 10
- repository_ticker_count: 280
- repository_price_rows_loaded: 312187
- previous_stage_forbidden_fill_count: 0
- carry_in_position_count: 0

## 기존 TEST의 사후 E/T 추출 vs 독립 NEW_TEST

| Scenario | Filled | Realized | Mean | Win rate | Median | -30 | -50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| FROZEN_TEST | 355 | 294 | 13.82% | 81.63% | 13.28% | 18 (6.12%) | 3 (1.02%) |
| POSTHOC_EARLY_TRANSITION | 310 | 257 | 14.45% | 82.10% | 13.79% | 14 (5.45%) | 2 (0.78%) |
| NEW_TEST | 310 | 257 | 14.45% | 82.10% | 13.79% | 14 (5.45%) | 2 (0.78%) |

전체 비교 원자료는 ../five_window_synthesis.csv에 있어.
