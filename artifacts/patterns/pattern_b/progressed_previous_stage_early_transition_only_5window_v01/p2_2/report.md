# P2-2: NEW_TEST previous Pattern A stage EARLY_TREND / TRANSITION

Effective: 2021-01-04 through 2026-08-31; support: 2026-09-01.
Only NEW_TEST was replayed. Frozen Pattern B CONTROL/TEST were read from committed artifacts.

## NEW_TEST realized gross

| Filled | Realized | Open | Mean | Win rate | Median | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 353 | 297 | 56 | 14.43% | 80.47% | 13.24% | 17 / 5.72% | 8 / 2.69% | 4 / 1.35% | 2 / 0.67% |

## 이전 Stage 후보 분포

- BASE: 24
- EARLY_TREND: 176
- TRANSITION: 179
- UNAVAILABLE: 26
- WEAK: 52

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
- new_test_candidate_count: 355
- new_test_filled_count: 353
- new_test_realized_count: 297
- new_test_open_count: 56
- lifecycle_spot_check_count: 30
- lifecycle_spot_check_pass_count: 30
- workers: 10
- repository_ticker_count: 310
- repository_price_rows_loaded: 417499
- previous_stage_forbidden_fill_count: 0
- carry_in_position_count: 0

## 기존 TEST의 사후 E/T 추출 vs 독립 NEW_TEST

| Scenario | Filled | Realized | Mean | Win rate | Median | -30 | -50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| FROZEN_TEST | 403 | 339 | 13.50% | 79.65% | 12.64% | 22 (6.49%) | 6 (1.77%) |
| POSTHOC_EARLY_TRANSITION | 353 | 297 | 14.43% | 80.47% | 13.24% | 17 (5.72%) | 4 (1.35%) |
| NEW_TEST | 353 | 297 | 14.43% | 80.47% | 13.24% | 17 (5.72%) | 4 (1.35%) |

전체 비교 원자료는 ../five_window_synthesis.csv에 있어.
