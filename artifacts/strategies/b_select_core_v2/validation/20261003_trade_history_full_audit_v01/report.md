# B Select Core V2 canonical trade history full audit

- Status: `B_SELECT_CORE_V02_TRADE_HISTORY_AUDIT_PASS`
- CRITICAL / MAJOR / MINOR: 0 / 0 / 0
- Authority: frozen 2026-10-03 V2 canonical status; local exact Repository V2 evaluator and adjusted OHLC; PIT identity/calendar authorities.

## Coverage and lifecycle

| Check | Result |
|---|---:|
| canonical_trade_rows | 488 |
| unique_exact_identities | 399 |
| realized_trade_rows | 451 |
| open_trade_rows | 37 |
| identity_interval_errors | 0 |
| permanent_exclusion_leakage | 0 |
| midmonth_entry_signals | 0 |
| invalid_pattern_b_entry | 0 |
| invalid_pattern_a_stage_entry | 0 |
| invalid_previous_pattern_a_stage_entry | 0 |
| lookahead_or_unverified_pattern_a_entry | 0 |
| wrong_entry_next_session | 0 |
| missing_or_invalid_entry_open | 0 |
| entry_open_price_mismatch | 0 |
| invalid_exit_normal_signal | 0 |
| exit_signal_without_open_position | 0 |
| wrong_exit_next_session | 0 |
| missing_or_invalid_exit_open | 0 |
| exit_open_price_mismatch | 0 |
| current_open_executable_normal_exit_missing | 0 |
| current_open_latest_valuation_missing | 0 |
| current_open_latest_valuation_mismatch | 0 |
| duplicate_trade_rows | 0 |
| duplicate_executions | 0 |
| overlapping_same_identity_positions | 0 |
| trade_sequence_errors | 0 |
| monitor_parity_mismatches | 0 |
| monitor_extra_rows | 0 |
| pending_entry_events | 0 |
| pending_exit_events | 0 |
| current_v1_source_rows | 0 |
| broken_or_wrong_identity_report_routes | 0 |
| current_open_report_routes | 37 |

## Exact identity report coverage

- Exact identities: 399; exact published report routes before this change: 251; missing before: 148.
- Current OPEN reports before: 20/37; missing before: 17.
- Current OPEN route coverage: 37/37; all history: 399/399.
- Current stock reports: 251; current identity-only: 132; historical archive: 16.
- Routes are resolved only by exact `(ticker, ISU_CD)`; ticker-only fallback count: 0.

## EXIT cadence

- Month-end signal: 205; midmonth signal: 246.
- Non-first-month-session execution: 246; non-NORMAL exit: 0.
