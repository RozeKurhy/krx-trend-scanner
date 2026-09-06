final_user_adjudication_summary.md
=================================

USER_ADJUDICATION_REQUIRED=true
DECISION_COUNT=4

DECISION_1 — Pattern A
------------------------
baseline_tickers=2528
output_changed_tickers=842
non_behavior_changed_tickers=563
behavior_changed_tickers=279
score_only_tickers=361
multi_field_non_decision_tickers=9
ranking_changed_tickers=0
gate_or_stage_changed_tickers=18
final_candidate_changed_tickers=261
other_behavior_changed_tickers=0
canonical_cause_summary={"KNOWN_AUTHORITY_GAP": 47, "MULTIPLE_CANONICAL_INPUT_EFFECTS": 365, "NON_TRADING_SESSION_PROJECTION": 12, "OHLC_AUTHORITY_CHANGE": 12, "RAW_VOLUME_AUTHORITY_CHANGE": 406}
decision_required=true
previous_288_reclassification=279 decision-state behavior + 9 multi-field non-decision

DECISION_2 — FastCore
-----------------------
baseline_trade_rows=783
canonical_trade_rows=781
trade_added_trades=0
trade_removed_trades=2
matched_trades_with_behavior_change=5
entry_changed_trades=1
exit_changed_trades=4
signal_changed_trades=4
price_only_changed_trades=0
behavior_changed_tickers=6
non_behavior_changed_tickers=320
canonical_cause_summary={"ANALYTIC_SESSION_EXCLUSION": 1, "KNOWN_AUTHORITY_GAP": 2, "MULTIPLE_CANONICAL_INPUT_EFFECTS": 82, "RAW_VOLUME_AUTHORITY_CHANGE": 241}
decision_required=true
removed_trade_details=[{"canonical_cause": "KNOWN_AUTHORITY_GAP", "canonical_entry": null, "canonical_exit": null, "legacy_entry": {"entry_execution_date": "2025-08-11", "entry_open": 38600.0, "entry_signal_date": "2025-08-08"}, "legacy_exit": {"exit_execution_date": "2025-08-22", "exit_price": 30950.0, "exit_signal_date": "2025-08-21"}, "ticker": "107640", "trade_id": "107640_01"}, {"canonical_cause": "KNOWN_AUTHORITY_GAP", "canonical_entry": null, "canonical_exit": null, "legacy_entry": {"entry_execution_date": "2026-02-23", "entry_open": 12510.0, "entry_signal_date": "2026-02-20"}, "legacy_exit": {"exit_execution_date": "2026-02-27", "exit_price": 10500.0, "exit_signal_date": "2026-02-26"}, "ticker": "176750", "trade_id": "176750_01"}]

DECISION_3 — Julia
--------------------
baseline_trade_rows=152
canonical_trade_rows=153
trade_added_trades=1
trade_removed_trades=0
matched_trades_with_behavior_change=21
entry_changed_trades=21
exit_changed_trades=3
signal_changed_trades=6
price_only_changed_trades=0
behavior_changed_tickers=20
non_behavior_changed_tickers=66
canonical_cause_summary={"ANALYTIC_SESSION_EXCLUSION": 1, "MULTIPLE_CANONICAL_INPUT_EFFECTS": 24, "OHLC_AUTHORITY_CHANGE": 1, "RAW_VOLUME_AUTHORITY_CHANGE": 60}
decision_required=true
added_trade_details=[{"canonical_cause": "RAW_VOLUME_AUTHORITY_CHANGE", "canonical_entry": {"entry_execution_date": "2024-06-03", "entry_open": 467000.0, "entry_signal_date": "2024-05-31"}, "canonical_exit": {"exit_execution_date": null, "exit_price": null, "exit_signal_date": null}, "legacy_entry": null, "legacy_exit": null, "ticker": "004370", "trade_id": "004370_02"}]

DECISION_4 — ETF Canonical Price Authority
--------------------------------------------
unique_affected_tickers=17
stock_report_affected_tickers=17
cross_consumer_mapping_rows=0
affected_consumers=Stock Report
canonical_problem=V2 adjusted/raw authority absent
relation_case=CASE_B
available_options=A. Repository V2 ETF support extension | B. ETF-specific canonical price path | C. explicit unsupported policy
decision_required=true

AUTHORITY GAP RELATION
-----------------------
known_authority_gap_mapping_rows=49
known_authority_gap_unique_tickers=47
stock_report_etf_authority_gap_tickers=17
etf_overlap_ticker_count=0
case_explanation=49 mapping rows represent 47 unique non-ETF/common tickers; Stock Report has a separate disjoint set of 17 ETF authority-gap tickers.

TARGETED REPLAY
---------------
required=True
ticker_count=1
tickers=004370
reason=Julia added trade entry/exit fields were absent from FIX03 serialized artifact
network_requests=0
full_shadow_run2=NOT_RUN
full_pytest_runs=0
