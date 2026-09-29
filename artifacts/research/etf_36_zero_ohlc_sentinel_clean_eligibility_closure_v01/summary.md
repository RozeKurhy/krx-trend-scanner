# ETF-36 Zero-OHLC Sentinel Clean Eligibility Closure V01

**Verdict:** `ETF_36_ZERO_OHLC_SENTINEL_CLEAN_ELIGIBILITY_CLOSURE_CHECK_REQUIRED`

## Signal-path history

Lookbacks were resolved from the frozen evaluator and FeatureSpec metadata. The longest consumed bar history is the optional-but-stage-consumed `close_vs_wma200_pct` at 200 completed weekly bars; it is included because the FAST stage uses it in the EXTENDED and TRIGGER rules. Pattern A's longest direct price feature is 36 completed monthly bars. The Pattern A lifecycle scan is explanation-only for WEAK, which cannot enter.

## Clean-ready dates

| Ticker | Existing ready | Clean ready | Last sentinel |
|---|---|---|---|
| 133690 | 2017-01-06 | 2018-06-15 | 2014-08-14 |
| 139230 | 2017-01-06 | 2019-04-05 | 2015-06-04 |
| 140700 | 2017-01-06 | 2019-09-20 | 2015-11-13 |
| 157490 | 2017-01-06 | 2020-10-16 | 2016-12-09 |
| 160580 | 2017-01-06 | 2022-04-01 | 2018-05-31 |
| 195980 | 2017-04-28 | 2018-09-21 | 2014-11-21 |
| 228800 | 2018-09-28 | 2020-10-16 | 2016-12-06 |
| 228810 | 2018-09-28 | 2021-07-16 | 2017-09-15 |
| 241180 | 2019-03-08 | 2021-03-19 | 2017-05-16 |
| 266410 | 2020-02-28 | 2021-06-18 | 2017-08-16 |

Changed target spans: 20; targeted replay windows: 20.

## Prior risk identity closure

12 identities / 4 unique ticker-date events. Identity dispositions: `{"REPLACED_BY_LATER_ENTRY": 12}`.
Unique event dispositions: `{"REPLACED_BY_LATER_ENTRY": 4}`.

## Revised OVERALL window metrics

| Window | ETFs | V2 trades | Julia trades | V2 mean realized % | Julia mean realized % | Delta Julia−V2 pp |
|---|---:|---:|---:|---:|---:|---:|
| P1 | 36 | 83 | 52 | 22.15 | 61.32 | 39.17 |
| P2-1 | 34 | 52 | 38 | -2.06 | 26.21 | 28.28 |
| P2-2 | 36 | 66 | 45 | 22.76 | 59.74 | 36.98 |
| P3-1 | 34 | 43 | 30 | -9.02 | 33.48 | 42.50 |
| P3-2 | 36 | 59 | 37 | 22.00 | 74.76 | 52.76 |

## Integrity

`validation.json` checks: {"affected_ticker_count_10": true, "forty_day_recomputation_0": true, "frozen_universe_36": true, "full_36_etf_5window_rerun_0": true, "mandatory_nan_inf_0": true, "market_refetch_0": true, "no_unresolved_risk_disposition": true, "original_ledger_unchanged": true, "original_risk_identity_count_12": true, "original_spans_unchanged": true, "original_universe_unchanged": true, "raw_row_modification_0": true, "raw_target_partition_hash_errors_0": true, "revised_summary_rows_20": true, "revised_trade_identity_duplicates_0": true, "risk_closure_rows_12": true, "signal_path_clean_at_each_clean_ready": true, "strategy_source_changed_0": true, "strategy_span_parity": true, "targeted_replay_error_count_0": true, "targeted_replay_only_affected_tickers": true, "unaffected_etf_span_changes_0": true, "unexpected_nan_0": true, "unique_original_risk_event_count_4": true, "validation_replay_contract": false}

## Check required 사유

단일 validator 오류는 `OPEN_TRADE_HAS_REALIZED_EXIT_FIELDS`야. 이 실행에서는 원본 ledger CSV의 빈 exit 칸을 읽을 때 `keep_default_na=False`로 빈 문자열(`""`)을 보존했고, `_validate_backtest`의 `.notna()` 검사가 그 빈 문자열을 값이 있는 것으로 판정했어. 저장된 certified CSV를 일반 CSV 방식으로 다시 읽으면 open trade 181건 모두 exit execution/price가 null로 읽혀. 다만 이 실행의 validator 자체는 실패했으므로 지시서 기준 verdict는 `CHECK_REQUIRED`로 유지하고 certified PASS를 주장하지 않아. 이 실패를 확인한 뒤 후속 replay나 보정은 하지 않았어.
