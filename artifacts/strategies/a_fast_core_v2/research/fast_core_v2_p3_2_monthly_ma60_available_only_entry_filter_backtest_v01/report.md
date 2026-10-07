# P3-2 MA60 Available-Only 신호 종가 진입 필터 백테스트

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 0 | Frozen CONTROL과 PRIOR 재사용, NEW MA60 독립 replay 완료 |
| MINOR | 2 | P3-2 단일 구간으로 공식 전략 승격 불가; MA 미가용 신호는 통과 정책 |

## 1. 최종 토큰

FAST_CORE_V2_P3_2_MONTHLY_MA60_AVAILABLE_ONLY_ENTRY_FILTER_BACKTEST_V01_COMPLETE

## 2. Authority / PIT

- Frozen CONTROL 405건과 survivor identity 2,539개를 사용했어.
- 기간 P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED의 frozen P3-2 구간이며, CONTROL replay는 하지 않았고 PRIOR MA60 결과도 재실행하지 않았어.
- 작업자 10개. 기존 로컬 Repository V2 adjusted-price partition을 read-only로 사용했고 새 network/API/가격 호출은 0회야.
- 신호일 completed daily close와 신호 월 직전 60개 확정 월봉 adjusted close만 사용했어. 현재 월봉과 신호일 이후 데이터는 사용하지 않았어.
- production/canonical 파일 변경은 0건이야.

## 3. NEW MA60 exact rule

- 가용: signal_day_close > prior completed-month MA60이면 통과, 같거나 낮으면 차단.
- 불가: insufficient history 또는 월봉 누락이어도 UNAVAILABLE_PASS_THROUGH로 기존 V2 진입 규칙을 진행.
- 통과 신호의 체결은 기존 NEXT_LOCAL_TRADING_DAY_OPEN. entry_open은 필터 판단에 사용하지 않아.

## 4. Signal filter audit

| 신호 그룹 | raw V2 eligible | PIT 통과 | 필터 통과 | 실제 전략 진입 | 실제 포트폴리오 진입 | 현금 부족 건너뜀 |
|---|---:|---:|---:|---:|---:|---:|
| MA60_AVAILABLE_ABOVE_PASS | 4353 | 335 | 4353 | 335 | 219 | 116 |
| MA60_AVAILABLE_AT_OR_BELOW_BLOCK | 1763 | 356 | 0 | 0 | 0 | 0 |
| MA60_UNAVAILABLE_PASS_THROUGH | 452 | 28 | 452 | 28 | 15 | 13 |

UNAVAILABLE 이유(raw / PIT-qualified): insufficient history 402 / 26, missing monthly observation 50 / 2, other 0 / 0.

## 5. 전략 성과

| 지표 | CONTROL | PRIOR MA60 fail-closed | NEW MA60 available-only |
|---|---:|---:|---:|
| trade_count | 405 | 337 | 363 |
| realized_count | 369 | 305 | 329 |
| open_count | 36 | 32 | 34 |
| realized_win_rate_pct | 32.79132791327913 | 36.0655737704918 | 34.954407294832826 |
| terminal_positive_rate_pct | 36.54320987654321 | 40.0593471810089 | 38.84297520661157 |
| average_terminal_return_pct | 17.398864197530862 | 18.641958456973295 | 17.978953168044075 |
| median_terminal_return_pct | -14.54 | -14.35 | -14.45 |
| average_realized_return_pct | 15.14783197831978 | 16.77544262295082 | 16.112097264437686 |
| median_realized_return_pct | -14.99 | -14.77 | -14.81 |
| average_holding_trading_days | 150.66913580246913 | 144.99109792284867 | 144.62809917355372 |
| median_holding_trading_days | 89.0 | 85.0 | 83.0 |
| progressed_count | 293 | 258 | 275 |
| progressed_rate_pct | 72.34567901234567 | 76.55786350148368 | 75.75757575757575 |
| loss_guard_exit_count | 231 | 183 | 202 |
| loss_guard_rate_pct | None | 54.3026706231454 | 55.64738292011019 |
| exit3_count | None | 9 | 9 |
| exit4_count | None | 113 | 118 |
| terminal_ge_pos_20_count | None | 105 | 110 |
| terminal_ge_pos_50_count | None | 81 | 85 |
| terminal_ge_pos_100_count | None | 30 | 32 |
| mfe_ge_pos_20_count | 210 | 175 | 186 |
| mfe_ge_pos_50_count | 142 | 117 | 125 |
| mfe_ge_pos_100_count | 72 | 64 | 68 |
| terminal_le_neg_20_count | None | 18 | 18 |
| terminal_le_neg_30_count | None | 4 | 4 |
| terminal_le_neg_40_count | None | 2 | 2 |
| mae_le_neg_20_count | None | 48 | 49 |
| mae_le_neg_30_count | 9 | 10 | 10 |
| mae_le_neg_40_count | 4 | 4 | 4 |

## 6. Realistic portfolio

| 지표 | CONTROL | PRIOR MA60 fail-closed | NEW MA60 available-only |
|---|---:|---:|---:|
| final_equity | 371154513.82105666 | 414501155.7604295 | 403584951.8044694 |
| cumulative_return_pct | 85.57725691052833 | 107.25057788021476 | 101.7924759022347 |
| CAGR_pct | 14.198241187427874 | 16.939185958690352 | 16.27094892012164 |
| mdd_pct | -15.135469 | -14.641254 | -15.022442 |
| trade_count | 228 | 240 | 234 |
| realized_trade_count | 207 | 216 | 210 |
| open_at_effective_cutoff_count | 24 | 27 | 27 |
| cash_shortage_skipped_entries | 177 | 97 | 129 |
| average_concurrent_positions | 30.962247585601403 | 30.22212467076383 | 30.15891132572432 |
| maximum_concurrent_positions | 56 | 58 | 58 |
| average_capital_utilization_pct | 77.81317632850364 | 71.95476463180793 | 74.01519389686324 |
| average_cash_ratio_pct | 22.186823671496363 | 28.045235368192067 | 25.984806103136776 |
| turnover_multiple | 11.508117143910003 | 12.215347382965 | 11.831676144895 |
| average_holding_trading_days | 143.33333333333334 | 131.88425925925927 | 135.2952380952381 |
| median_holding_trading_days | 72 | 72.5 | 74.0 |
| realized_return_ge_pos_50_count | 43 | 52 | 49 |
| realized_return_ge_pos_100_count | 21 | 20 | 19 |
| realized_return_le_neg_30_count | 2 | 3 | 3 |
| realized_return_le_neg_40_count | 1 | 1 | 1 |
| realized_return_le_neg_50_count | 0 | 0 | 0 |
| realized_return_le_neg_60_count | 0 | 0 | 0 |
| cash_conservation_pass | True | True | True |
| unresolved_count | 0 | 0 | 0 |

## 7. UNAVAILABLE pass-through effect

- PRIOR MA60에서 fail-closed된 PIT-qualified unavailable signal: 101건. 원인별 건수는 위 audit과 summary에 기록했어.
- 이 신호 중 대응 CONTROL 전략 거래: 28건. 그 거래 성과: {"average_holding_trading_days": 150.46428571428572, "average_realized_return_pct": 17.508846153846154, "average_terminal_return_pct": 18.388571428571424, "exit3_count": 0, "exit4_count": 7, "loss_guard_exit_count": 19, "loss_guard_rate_pct": 67.85714285714286, "mae_le_neg_20_count": 1, "mae_le_neg_30_count": 0, "mae_le_neg_40_count": 0, "median_holding_trading_days": 69.0, "median_realized_return_pct": -15.05, "median_terminal_return_pct": -14.83, "mfe_ge_pos_100_count": 5, "mfe_ge_pos_20_count": 13, "mfe_ge_pos_50_count": 10, "open_count": 2, "progressed_count": 19, "progressed_rate_pct": 67.85714285714286, "realized_count": 26, "realized_win_rate_pct": 26.923076923076923, "terminal_ge_pos_100_count": 3, "terminal_ge_pos_20_count": 7, "terminal_ge_pos_50_count": 6, "terminal_le_neg_20_count": 0, "terminal_le_neg_30_count": 0, "terminal_le_neg_40_count": 0, "terminal_positive_rate_pct": 28.57142857142857, "trade_count": 28}
- NEW 재생에서 기존 unavailable signal key가 다시 emit된 수: 28; 새 전략 거래 28; 실제 포트폴리오 진입 15; 현금 부족 skip 13.
- NEW MA60 unavailable 그룹 전체: 전략 거래 28건, 실제 포트폴리오 진입 15건, 현금 부족 skip 13건.
- 해당 실제 포트폴리오 실현 성과: {"average_realized_return_pct": 3.830608870360008, "median_realized_return_pct": -15.704355845351737, "net_realized_profit_krw": 2519037.6586660086, "realized_ge_pos_100_count": 1, "realized_ge_pos_50_count": 2, "realized_le_neg_30_count": 0, "realized_le_neg_40_count": 0, "realized_le_neg_50_count": 0, "realized_le_neg_60_count": 0, "realized_trade_count": 13, "realized_win_rate_pct": 23.076923076923077}
- 해당 전략 거래의 terminal/MFE/MAE/Loss Guard/PROGRESSED 성과: {"average_holding_trading_days": 150.46428571428572, "average_realized_return_pct": 17.508846153846154, "average_terminal_return_pct": 18.388571428571424, "exit3_count": 0, "exit4_count": 7, "loss_guard_exit_count": 19, "loss_guard_rate_pct": 67.85714285714286, "mae_le_neg_20_count": 1, "mae_le_neg_30_count": 0, "mae_le_neg_40_count": 0, "median_holding_trading_days": 69.0, "median_realized_return_pct": -15.05, "median_terminal_return_pct": -14.83, "mfe_ge_pos_100_count": 5, "mfe_ge_pos_20_count": 13, "mfe_ge_pos_50_count": 10, "open_count": 2, "progressed_count": 19, "progressed_rate_pct": 67.85714285714286, "realized_count": 26, "realized_win_rate_pct": 26.923076923076923, "terminal_ge_pos_100_count": 3, "terminal_ge_pos_20_count": 7, "terminal_ge_pos_50_count": 6, "terminal_le_neg_20_count": 0, "terminal_le_neg_30_count": 0, "terminal_le_neg_40_count": 0, "terminal_positive_rate_pct": 28.57142857142857, "trade_count": 28}

## 8. Opportunity cost

- 포트폴리오 델타: {"NEW_MINUS_CONTROL": {"CAGR_pct": 2.0727077326937664, "average_capital_utilization_pct": -3.7979824316404063, "average_cash_ratio_pct": 3.7979824316404134, "average_concurrent_positions": -0.803336259877085, "average_holding_trading_days": -8.038095238095252, "cash_shortage_skipped_entries": -48, "cumulative_return_pct": 16.215218991706365, "final_equity": 32430437.983412743, "maximum_concurrent_positions": 2, "mdd_pct": 0.11302700000000065, "median_holding_trading_days": 2.0, "open_at_effective_cutoff_count": 3, "realized_return_ge_pos_100_count": -2, "realized_return_ge_pos_50_count": 6, "realized_trade_count": 3, "trade_count": 6, "turnover_multiple": 0.32355900098499824}, "NEW_MINUS_PRIOR_MA60_FAIL_CLOSED": {"CAGR_pct": -0.6682370385687122, "average_capital_utilization_pct": 2.060429265055305, "average_cash_ratio_pct": -2.0604292650552907, "average_concurrent_positions": -0.06321334503951093, "average_holding_trading_days": 3.410978835978824, "cash_shortage_skipped_entries": 32, "cumulative_return_pct": -5.458101977980064, "final_equity": -10916203.955960095, "maximum_concurrent_positions": 0, "mdd_pct": -0.38118799999999986, "median_holding_trading_days": 1.5, "open_at_effective_cutoff_count": 0, "realized_return_ge_pos_100_count": -1, "realized_return_ge_pos_50_count": -3, "realized_trade_count": -6, "trade_count": -6, "turnover_multiple": -0.3836712380699989}}
- Winner entry-key 변화와 실제 global cash path 비교는 opportunity_cost_analysis.csv에 있어.

## 9. 성공 Gate

| 기준 | NEW MA60 |
|---|---|
| realized win rate >= 50% | False |
| median terminal >= +1% | False |
| average terminal > CONTROL | True |
| realistic portfolio MDD > -30% | True |
| 전체 Gate 통과 | False |

- 추가 포트폴리오 개선 기준: {"new_cagr_above_control": true, "new_cagr_above_prior": false, "new_cash_shortage_skips_below_control": true, "new_cash_shortage_skips_below_prior": false, "new_final_equity_above_control": true, "new_final_equity_above_prior": false, "new_mdd_above_neg_30_pct": true, "new_realized_100_winners_at_least_prior": false, "new_realized_50_winners_at_least_prior": false}

## 10. 결론 / 후속 연구

공식 전략 승격은 하지 않아. NEW MA60은 CONTROL보다 최종 자산과 CAGR이 높지만, PRIOR MA60 fail-closed보다 낮고 현금 부족 skip이 늘었으며 +50%/+100% 실현 승자도 줄었어. 모든 개선 조건을 충족하지 않아 추가 구간 검증 후보로 권고하지 않아.

## 11. Integrity

- {"accepted_signal_to_trade_ledger_one_to_one": true, "all_checks_pass": true, "all_new_trades_pass_filter": true, "available_above_never_blocked": true, "available_at_or_below_always_blocked": true, "blocked_signals_do_not_create_strategy_trades": true, "candidate_filter_pass_count_reconciles": true, "candidate_worker_errors_zero": true, "cash_conservation_pass": true, "current_or_future_month_observations_used_zero": true, "entry_open_not_used_for_filter": true, "equity_curve_1140_rows": true, "filter_group_semantics": {"MA60_AVAILABLE_ABOVE_PASS": true, "MA60_AVAILABLE_AT_OR_BELOW_BLOCK": true, "MA60_UNAVAILABLE_PASS_THROUGH": true}, "filter_group_semantics_all_pass": true, "frozen_control_and_saved_prior_preflight_pass": true, "frozen_control_exact_parity": true, "frozen_control_hashes_and_head_blobs": true, "frozen_control_not_replayed": true, "latest_rolling_authority_reads_zero": true, "network_api_or_new_price_calls_zero": true, "portfolio_event_counts_match_comparison": true, "price_partition_and_metadata_hashes_match_saved_audit": true, "prior_and_new_first_eligible_signal_equal_by_shared_identity": true, "prior_artifact_hashes_and_commit_blobs": true, "prior_ma60_not_replayed": true, "prior_signal_count_matches_summary": true, "production_or_canonical_source_changes_zero": true, "raw_signal_group_counts_reconcile": true, "saved_signal_close_matches_adjusted_store_and_first_run_repository_v2_check_completed": true, "saved_signal_group_tables_reconcile": true, "unavailable_always_passes_filter": true, "unavailable_detail_and_opportunity_rows_reconcile": true, "unavailable_pit_passes_are_accepted": true, "unresolved_count_zero": true, "worker_count_is_10": true}
- BLOCK은 V2의 entry_signal_filter callback에서 거절되어 position/cooldown/가상 exit를 생성하지 않아. 후속 신호는 같은 V2 lifecycle에서 다시 평가했어.
- accepted signal과 strategy trade를 identity/signal-date 기준으로 one-to-one 대조했어.
- 보고서 복구 기록: 첫 전체 재생의 저장 CSV 및 이벤트 원장으로 요약·보고서를 재구성했어. 백테스트나 포트폴리오 재생은 다시 실행하지 않았어. 첫 report writer 오류 원문은 report_generation_failure.json에 보존했어.

## 12. Git

- 산출물 생성 전 branch main, HEAD 8edb3f5179ff1c9608fc79ec01f93c4fc596ae89, origin/main 8edb3f5179ff1c9608fc79ec01f93c4fc596ae89; 일치 True; ahead/behind 0	0.
- 이번 산출물 디렉터리만 stage/commit/push하고, push 후 HEAD == origin/main 확인 결과는 r.md에 기록해.

## 산출물

- ma60_filter_group_summary.csv
- ma60_signal_filter_audit.csv
- ma60_unavailable_reason_counts.csv
- new_ma60_daily_equity.csv
- new_ma60_portfolio_events.csv
- new_ma60_skipped.csv
- new_ma60_strategy_trades.csv
- new_ma60_valuation_carry_audit.csv
- opportunity_cost_analysis.csv
- preflight.json
- price_store_audit.csv
- prior_artifact_hashes.csv
- prior_vs_new_ma60_comparison.csv
- recover_saved_outputs.py
- report.md
- report_generation_failure.json
- run_monthly_ma60_available_only_backtest.py
- summary.json
- unavailable_pass_through_analysis.csv
