# P1: NEW_TEST previous Pattern A stage EARLY_TREND / TRANSITION

Effective: 2014-01-02 through 2026-08-31; support: 2026-09-01.
Only NEW_TEST was replayed. Frozen Pattern B CONTROL/TEST were read from committed artifacts.

## NEW_TEST realized gross

| Filled | Realized | Open | Mean | Win rate | Median | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 582 | 521 | 61 | 13.22% | 80.04% | 12.63% | 30 / 5.76% | 17 / 3.26% | 11 / 2.11% | 7 / 1.34% |

## 이전 Stage 후보 분포

- BASE: 42
- EARLY_TREND: 285
- TRANSITION: 299
- UNAVAILABLE: 70
- WEAK: 107

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
- new_test_candidate_count: 584
- new_test_filled_count: 582
- new_test_realized_count: 521
- new_test_open_count: 61
- lifecycle_spot_check_count: 30
- lifecycle_spot_check_pass_count: 30
- workers: 10
- repository_ticker_count: 471
- repository_price_rows_loaded: 1328121
- previous_stage_forbidden_fill_count: 0
- carry_in_position_count: 0

## 기존 TEST의 사후 E/T 추출 vs 독립 NEW_TEST

| Scenario | Filled | Realized | Mean | Win rate | Median | -30 | -50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| FROZEN_TEST | 694 | 622 | 12.52% | 78.94% | 12.25% | 39 (6.27%) | 14 (2.25%) |
| POSTHOC_EARLY_TRANSITION | 582 | 521 | 13.22% | 80.04% | 12.63% | 30 (5.76%) | 11 (2.11%) |
| NEW_TEST | 582 | 521 | 13.22% | 80.04% | 12.63% | 30 (5.76%) | 11 (2.11%) |

전체 비교 원자료는 ../five_window_synthesis.csv에 있어.
