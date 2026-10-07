| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 저장 replay 결과의 PIT·원장·현금 검사 통과 |
| MAJOR | 1 | 첫 보고서 집계에서 난 KeyError를 저장 산출물로 복구했고 후보를 재생하지 않음 |
| MINOR | 2 | P3-2 단일 window라 공식 채택 미판정; MA unavailable 신호 fail-closed |

최종 토큰: FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_BULLISH_ALIGNMENT_BACKTEST_V01_COMPLETE

## 1. Authority / PIT

- Frozen CONTROL: FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE; 405 trades, 2,539 identities.
- Prior MA20/MA60 files: 26 files matched byte-for-byte with commit 8edb3f5179ff1c9608fc79ec01f93c4fc596ae89; CONTROL and prior MA60 were reused, not replayed.
- Local Repository V2 adjusted-price partitions only; zero API/network calls. Monthly averages use only completed months before each signal month.

## 2. Exact rule

- Allow only when signal-day close > prior completed month MA20 > prior completed month MA60.
- Missing MA20 or MA60 fails closed. Execution remains next local session open. Entry open is not passed to the filter.

## 3. MA20/MA60 structure groups

| Sample | Group | Count | Share |
|---|---|---:|---:|
| CONTROL_405 | PRICE > MA20 > MA60 | 140 | 34.57% |
| CONTROL_405 | PRICE > MA60 >= MA20 | 117 | 28.89% |
| CONTROL_405 | MA20 >= PRICE > MA60 | 16 | 3.95% |
| CONTROL_405 | PRICE <= MA60 | 104 | 25.68% |
| CONTROL_405 | MA20 unavailable | 0 | 0.00% |
| CONTROL_405 | MA60 unavailable | 28 | 6.91% |
| PRIOR_MA60_337 | PRICE > MA20 > MA60 | 144 | 42.73% |
| PRIOR_MA60_337 | PRICE > MA60 >= MA20 | 175 | 51.93% |
| PRIOR_MA60_337 | MA20 >= PRICE > MA60 | 18 | 5.34% |
| PRIOR_MA60_337 | PRICE <= MA60 | 0 | 0.00% |
| PRIOR_MA60_337 | MA20 unavailable | 0 | 0.00% |
| PRIOR_MA60_337 | MA60 unavailable | 0 | 0.00% |
| NEW_RAW_V2_SIGNALS | PRICE > MA20 > MA60 | 2055 | 28.24% |
| NEW_RAW_V2_SIGNALS | PRICE > MA60 >= MA20 | 2713 | 37.29% |
| NEW_RAW_V2_SIGNALS | MA20 >= PRICE > MA60 | 164 | 2.25% |
| NEW_RAW_V2_SIGNALS | PRICE <= MA60 | 1819 | 25.00% |
| NEW_RAW_V2_SIGNALS | MA20 unavailable | 0 | 0.00% |
| NEW_RAW_V2_SIGNALS | MA60 unavailable | 525 | 7.22% |

Of the 337 PRIOR MA60 trades: aligned 144; blocked by MA20 <= MA60 175; close not above MA20 while MA20 > MA60 18; MA20 unavailable 0.

## 4. Strategy metrics

| Metric | CONTROL | PRIOR MA60 | NEW ALIGNMENT |
|---|---:|---:|---:|
| trade count | 405 | 337 | 179 |
| realized | 369 | 305 | 165 |
| open | 36 | 32 | 14 |
| realized win rate % | 32.79132791327913 | 36.0655737704918 | 44.84848484848485 |
| terminal positive % | 36.54320987654321 | 40.0593471810089 | 48.04469273743017 |
| average terminal % | 17.398864197530862 | 18.641958456973295 | 23.073631284916196 |
| median terminal % | -14.54 | -14.35 | -9.17 |
| average realized % | 15.14783197831978 | 16.77544262295082 | 22.185151515151517 |
| median realized % | -14.99 | -14.77 | -13.29 |
| average holding days | 150.66913580246913 | 144.99109792284867 | 159.0949720670391 |
| median holding days | 89.0 | 85.0 | 100.0 |
| PROGRESSED | 293 | 258 | 143 |
| PROGRESSED % | 72.34567901234567 | 76.55786350148368 | 79.88826815642457 |
| Loss Guard | 231 | 183 | 87 |
| Loss Guard % | 57.03703703703704 | 54.3026706231454 | 48.60335195530726 |
| Exit 3 | 12 | 9 | 7 |
| Exit 4 | 126 | 113 | 71 |
| terminal >= +20 | 121 | 105 | 66 |
| terminal >= +50 | 95 | 81 | 51 |
| terminal >= +100 | 38 | 30 | 18 |
| MFE >= +20 | 210 | 175 | 104 |
| MFE >= +50 | 142 | 117 | 74 |
| MFE >= +100 | 72 | 64 | 40 |
| terminal <= -20 | 20 | 18 | 7 |
| terminal <= -30 | 4 | 4 | 1 |
| terminal <= -40 | 2 | 2 | 0 |
| MAE <= -20 | 52 | 48 | 22 |
| MAE <= -30 | 9 | 10 | 4 |
| MAE <= -40 | 4 | 4 | 1 |

## 5. Realistic portfolio

| Metric | CONTROL | PRIOR MA60 | NEW ALIGNMENT |
|---|---:|---:|---:|
| final equity | 371154513.82105666 | 414501155.7604295 | 401104602.05585915 |
| cumulative return % | 85.57725691052833 | 107.25057788021476 | 100.55230102792959 |
| CAGR % | 14.198241187427874 | 16.939185958690352 | 16.1171385400769 |
| MDD % | -15.135469 | -14.641254 | -11.375289 |
| actual entries | 228 | 240 | 178 |
| realized trades | 207 | 216 | 164 |
| open at cutoff | 24 | 27 | 16 |
| cash-shortage skips | 177 | 97 | 1 |
| average concurrent positions | 30.962247585601403 | 30.22212467076383 | 24.90517998244074 |
| max concurrent positions | 56 | 58 | 48 |
| average capital utilization % | 77.81317632850364 | 71.95476463180793 | 58.459491573539566 |
| max capital utilization % | 99.89013693819325 | 99.96223190506961 | 99.91922277708616 |
| average cash ratio % | 22.186823671496363 | 28.045235368192067 | 41.54050842646043 |
| turnover multiple | 11.508117143910003 | 12.215347382965 | 9.35622383593 |
| average holding days | 143.33333333333334 | 131.88425925925927 | 153.21951219512195 |
| median holding days | 72 | 72.5 | 97.5 |
| realized >= +50 | 43 | 52 | 46 |
| realized >= +100 | 21 | 20 | 17 |
| realized <= -30 | 2 | 3 | 1 |
| realized <= -40 | 1 | 1 | 0 |
| realized <= -50 | 0 | 0 | 0 |
| realized <= -60 | 0 | 0 | 0 |

## 6. MA20 > MA60 incremental effect

- PRIOR trade-cohort counts and blocked sample metrics are in prior_ma60_vs_alignment_analysis.csv and summary.json.
- Actual-entry comparison: prior-only 139, new-only 77, common 101.
- Cash-shortage skip change: -96; realized P&L delta (new-prior): after tax -6670223.413656145 KRW, tax excluded -7188206.293674707 KRW.

## 7. Opportunity cost

| Comparison | Left-only entries | Right-only entries | Common | +50 lost/gained/net | +100 lost/gained/net |
|---|---:|---:|---:|---:|---:|
| CONTROL_VS_NEW_ALIGNMENT | 153 | 103 | 75 | 27/30/+3 | 11/7/-4 |
| PRIOR_MA60_VS_NEW_ALIGNMENT | 139 | 77 | 101 | 24/18/-6 | 6/3/-3 |

## 8. Official criteria

- Official adoption state: NOT_EVALUATED. This run covers P3-2 only; it does not replace five-window A-E review or promote a strategy/default.
- Official return/CAGR/MDD criteria exclude transaction tax and require all five standard windows. The realistic portfolio replay retains the frozen P3-2 settlement convention and is a research comparison, not an official adoption judgment.

## 9. User preference goals

| Goal | Value | Result |
|---|---:|---|
| 실현 승률 >= 50% | 44.84848484848485 | not met |
| 중앙 terminal >= +1% | -9.17 | not met |
| 평균 terminal > CONTROL | {'alignment_pct': 23.073631284916196, 'control_pct': 17.398864197530862, 'delta_percentage_points': 5.674767087385334} | met |
| CONTROL 대비 +10%p 이상 (선호 참고치) | 5.674767087385334 | not met |
| 현실 portfolio MDD > -30% | -11.375289 | met |

## 10. P3-2 comparison judgment

MIXED_NO_CLEAR_WINNER

수익·위험·거래 품질·승자 보존 지표가 엇갈려 P3-2만으로 우열을 정하기 어려워.

## 11. Integrity

{"accepted_signal_to_trade_ledger_one_to_one": true, "all_candidate_trades_pass_alignment": true, "candidate_replay_not_repeated": true, "candidate_signal_count_reconciles": true, "cash_conservation_pass": true, "control_hashes_match_frozen_snapshot": true, "control_replayed": false, "control_structure_groups_exhaustive": true, "current_or_future_month_observations_used": 0, "daily_equity_rows_1140": true, "entry_open_used_in_filter": false, "frozen_authority_and_provenance_pass": true, "latest_rolling_authority_reads": 0, "ma_unavailable_fail_closed": true, "network_api_or_new_price_calls": 0, "prior_artifacts_byte_match_reference_commit": true, "prior_ma60_replayed": false, "prior_structure_groups_exhaustive": true, "production_or_canonical_changes": 0, "report_reconstructed_from_saved_outputs": true, "repository_v2_adjusted_price_parity": true, "saved_control_exact_parity": true, "unresolved_count_zero": true, "worker_count": 10, "worker_errors": 0}

## 12. Git

- Before output: branch main, HEAD c7e104bb51536e75b5f71e4ac5cb40f6dfa992ed, origin/main c7e104bb51536e75b5f71e4ac5cb40f6dfa992ed, ahead/behind 0	0.
- Push SHA and HEAD==origin/main verification are recorded in r.md.

## Artifacts

- alignment_daily_equity.csv
- alignment_portfolio_events.csv
- alignment_signal_audit.csv
- alignment_skipped.csv
- alignment_strategy_trades.csv
- alignment_valuation_carry_audit.csv
- control_signal_close_vs_entry_open_ma_parity.csv
- ma20_ma60_structure_groups.csv
- opportunity_cost_analysis.csv
- preflight.json
- price_store_audit.csv
- prior_ma60_vs_alignment_analysis.csv
- report.md
- report_recovery_audit.json
- run_bullish_alignment_backtest.py
- summary.json
