# P2-1: NEW_TEST previous Pattern A stage EARLY_TREND / TRANSITION

Effective: 2021-01-04 through 2025-05-30; support: 2025-06-02.
Only NEW_TEST was replayed. Frozen Pattern B CONTROL/TEST were read from committed artifacts.

## NEW_TEST realized gross

| Filled | Realized | Open | Mean | Win rate | Median | -30 count/rate | -40 count/rate | -50 count/rate | -60 count/rate |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 246 | 199 | 47 | 16.39% | 80.90% | 13.60% | 9 / 4.52% | 3 / 1.51% | 0 / 0.00% | 0 / 0.00% |

## 이전 Stage 후보 분포

- BASE: 20
- EARLY_TREND: 120
- TRANSITION: 127
- UNAVAILABLE: 18
- WEAK: 47

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
- new_test_candidate_count: 247
- new_test_filled_count: 246
- new_test_realized_count: 199
- new_test_open_count: 47
- lifecycle_spot_check_count: 30
- lifecycle_spot_check_pass_count: 30
- workers: 10
- repository_ticker_count: 214
- repository_price_rows_loaded: 226796
- previous_stage_forbidden_fill_count: 0
- carry_in_position_count: 0

## 기존 TEST의 사후 E/T 추출 vs 독립 NEW_TEST

| Scenario | Filled | Realized | Mean | Win rate | Median | -30 | -50 |
|---|---:|---:|---:|---:|---:|---:|---:|
| FROZEN_TEST | 284 | 228 | 15.74% | 81.14% | 12.80% | 10 (4.39%) | 0 (0.00%) |
| POSTHOC_EARLY_TRANSITION | 246 | 199 | 16.39% | 80.90% | 13.60% | 9 (4.52%) | 0 (0.00%) |
| NEW_TEST | 246 | 199 | 16.39% | 80.90% | 13.60% | 9 (4.52%) | 0 (0.00%) |

전체 비교 원자료는 ../five_window_synthesis.csv에 있어.
