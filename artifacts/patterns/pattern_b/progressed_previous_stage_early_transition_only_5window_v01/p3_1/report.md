# P3-1: NEW_TEST previous Pattern A stage EARLY_TREND / TRANSITION

Effective: 2022-01-03 through 2025-05-30; support: 2025-06-02.
Only NEW_TEST was replayed. Frozen Pattern B CONTROL/TEST were read from committed artifacts.

## NEW_TEST realized gross

| Filled | Realized | Open | Mean | Win rate | Median | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 203 | 161 | 42 | 15.89% | 82.61% | 14.25% | 8 / 4.97% | 2 / 1.24% | 0 / 0.00% | 0 / 0.00% |

## 이전 Stage 후보 분포

- BASE: 16
- EARLY_TREND: 93
- TRANSITION: 111
- UNAVAILABLE: 17
- WEAK: 45

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
- execution_support_exit_fill_count: 1
- new_test_candidate_count: 204
- new_test_filled_count: 203
- new_test_realized_count: 161
- new_test_open_count: 42
- lifecycle_spot_check_count: 30
- lifecycle_spot_check_pass_count: 30
- workers: 10
- repository_ticker_count: 183
- repository_price_rows_loaded: 150125
- previous_stage_forbidden_fill_count: 0
- carry_in_position_count: 0

## 기존 TEST의 사후 E/T 추출 vs 독립 NEW_TEST

| Scenario | Filled | Realized | Mean | Win rate | Median | -30 | -50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| FROZEN_TEST | 236 | 186 | 15.50% | 83.33% | 13.69% | 9 (4.84%) | 0 (0.00%) |
| POSTHOC_EARLY_TRANSITION | 203 | 161 | 15.89% | 82.61% | 14.25% | 8 (4.97%) | 0 (0.00%) |
| NEW_TEST | 203 | 161 | 15.89% | 82.61% | 14.25% | 8 (4.97%) | 0 (0.00%) |

전체 비교 원자료는 ../five_window_synthesis.csv에 있어.
