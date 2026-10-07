# P3-2 월간 MA20 / MA60 신호 종가 진입 필터 백테스트

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 0 | Frozen CONTROL과 MA20/MA60 독립 replay 완료 |
| MINOR | 2 | P3-2 단일 구간으로 공식 전략 승격 불가; MA 미가용 신호는 fail-closed 처리 |

## 1. 최종 토큰

`FAST_CORE_V2_P3_2_MONTHLY_MA20_MA60_ENTRY_FILTER_BACKTEST_V01_COMPLETE`

## 2. Authority / PIT

- Frozen CONTROL 405건을 재사용했고 CONTROL replay는 다시 돌리지 않았어. 저장 CONTROL parity, 파일 SHA-256, 현재 HEAD blob, frozen P3-2 source/PIT/calendar 검증은 모두 PASS야.
- 기간 2022-01-03~2026-08-31, execution support 2026-09-01, survivor identity 2539개, worker 10개.
- 이전 rolling authority를 읽지 않았고 네트워크/API/신규 가격 수집은 0회야. 공식 전략 파일과 production 경로는 수정하지 않았어.

## 3. 신호 종가 vs 다음 날 시가 분류 일치

두 가격 모두 `entry_signal_date` 직전 확정 월봉 MA와 비교했어. 비교 가능한 거래만 분모로 한 동일 분류율과 전체 405건 분류율을 함께 표시해.

| MA | comparable | unavailable | same | same rate (comparable) | same rate (405) | gap flip | Above→At/Below | At/Below→Above |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| MA20 | 405 | 0 | 401 | 99.01% | 99.01% | 4 | 3 | 1 |
| MA60 | 377 | 28 | 368 | 97.61% | 97.78% | 9 | 5 | 4 |

## 4. Candidate 규칙

- MA20: 기존 V2 eligible 신호에서 signal-day completed close가 signal 월 직전 확정월까지의 연속 20개 월봉 adjusted close 평균보다 클 때 통과.
- MA60: 같은 기준으로 연속 60개 월봉 평균보다 클 때 통과.
- 이력이 부족하거나 누락된 월봉이 있으면 해당 신호는 통과하지 않고 unavailable로 기록했어. 필터 통과 후 체결은 기존 next local trading day open이야.
- 기존 PIT 시총 gate가 먼저 그대로 평가되고 MA gate가 뒤따라. 차단은 포지션·cooldown·가상 exit를 만들지 않고 다음 eligible signal로 진행해.

## 5. 전략 성과

| 지표 | CONTROL | MA20 | MA60 |
|---|---:|---:|---:|
| trade_count | 405 | 394 | 337 |
| realized_count | 369 | 360 | 305 |
| open_count | 36 | 34 | 32 |
| realized_win_rate_pct | 32.79132791327913 | 33.611111111111114 | 36.0655737704918 |
| terminal_positive_rate_pct | 36.54320987654321 | 37.309644670050766 | 40.0593471810089 |
| average_terminal_return_pct | 17.398864197530862 | 17.90467005076142 | 18.641958456973295 |
| median_terminal_return_pct | -14.54 | -14.535 | -14.35 |
| average_realized_return_pct | 15.14783197831978 | 15.780583333333334 | 16.77544262295082 |
| median_realized_return_pct | -14.99 | -14.945 | -14.77 |
| average_holding_trading_days | 150.66913580246913 | 148.7030456852792 | 144.99109792284867 |
| median_holding_trading_days | 89.0 | 88.0 | 85.0 |
| progressed_count | 293 | 284 | 258 |
| progressed_rate_pct | 72.34567901234567 | 72.08121827411168 | 76.55786350148368 |
| loss_guard_exit_count | 231 | 222 | 183 |
| loss_guard_rate_pct | None | 56.34517766497462 | 54.3026706231454 |
| exit3_count | None | 12 | 9 |
| exit4_count | None | 126 | 113 |
| terminal_ge_pos_20_count | None | 120 | 105 |
| terminal_ge_pos_50_count | None | 93 | 81 |
| terminal_ge_pos_100_count | None | 38 | 30 |
| mfe_ge_pos_20_count | 210 | 206 | 175 |
| mfe_ge_pos_50_count | 142 | 140 | 117 |
| mfe_ge_pos_100_count | 72 | 71 | 64 |
| terminal_le_neg_20_count | None | 20 | 18 |
| terminal_le_neg_30_count | None | 4 | 4 |
| terminal_le_neg_40_count | None | 2 | 2 |
| mae_le_neg_20_count | None | 51 | 48 |
| mae_le_neg_30_count | 9 | 9 | 10 |
| mae_le_neg_40_count | 4 | 4 | 4 |

## 6. PROGRESSED / Loss Guard / MFE / MAE

상세 건수는 전략 성과 표에 포함했어. terminal은 cutoff 평가를 포함하고 realized return은 실현 거래에 한정했어.

## 7. 현실 포트폴리오

| 지표 | CONTROL | MA20 | MA60 |
|---|---:|---:|---:|
| final_equity | 371154513.82105666 | 396791082.6335583 | 414501155.7604295 |
| cumulative_return_pct | 85.57725691052833 | 98.39554131677914 | 107.25057788021476 |
| CAGR_pct | 14.198241187427874 | 15.847862289564407 | 16.939185958690352 |
| mdd_pct | -15.135469 | -16.183555 | -14.641254 |
| trade_count | 228 | 242 | 240 |
| realized_trade_count | 207 | 216 | 216 |
| open_at_effective_cutoff_count | 24 | 29 | 27 |
| cash_shortage_skipped_entries | 177 | 152 | 97 |
| average_concurrent_positions | 30.962247585601403 | 31.98419666374012 | 30.22212467076383 |
| maximum_concurrent_positions | 56 | 60 | 58 |
| average_capital_utilization_pct | 77.81317632850364 | 76.23976880980625 | 71.95476463180793 |
| average_cash_ratio_pct | 22.186823671496363 | 23.76023119019375 | 28.045235368192067 |
| turnover_multiple | 11.508117143910003 | 12.09790818907 | 12.215347382965 |
| average_holding_trading_days | 143.33333333333334 | 136.8101851851852 | 131.88425925925927 |
| median_holding_trading_days | 72 | 73.5 | 72.5 |
| realized_return_ge_pos_50_count | 43 | 45 | 52 |
| realized_return_ge_pos_100_count | 21 | 23 | 20 |
| realized_return_le_neg_30_count | 2 | 3 | 3 |
| realized_return_le_neg_40_count | 1 | 1 | 1 |
| realized_return_le_neg_50_count | 0 | 0 | 0 |
| realized_return_le_neg_60_count | 0 | 0 | 0 |
| cash_conservation_pass | True | True | True |
| unresolved_count | 0 | 0 | 0 |

## 8. 차단 거래 / 신규 후속 거래

| 후보 | CONTROL 신호 차단 | 실현 승률 | 평균 terminal | 중앙 terminal | Loss Guard | PROGRESSED | terminal +50 / +100 | MFE +50 / +100 | MAE -30 / -40 | 새 후속 거래 | 차단 후 나중 accepted 신호가 있었던 차단 수 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MA20 | 27 | 20.833333333333336% | 6.172592592592593% | -14.86% | 19 (70.37037037037037%) | 19 (70.37037037037037%) | 5 / 1 | 7 / 3 | 0 / 0 | 17 | 26 |
| MA60 | 132 | 27.500000000000004% | 13.25090909090909% | -15.005% | 82 (62.121212121212125%) | 82 (62.121212121212125%) | 29 / 11 | 47 / 20 | 2 / 1 | 64 | 91 |

새 후속 거래별 연결 정보는 `filter_blocked_signal_analysis.csv`에 있고, Control의 앞선 차단 신호와 같은 PIT identity 안에서 후속 거래를 연결했어.

## 9. Portfolio opportunity cost

| 후보 | CONTROL-only actual entries | Candidate-only actual entries | common actual entries | cash skip CONTROL→후보 | +50 winners lost/gained/net | +100 winners lost/gained/net |
|---|---:|---:|---:|---:|---:|---:|
| MA20 | 37 | 51 | 191 | 177→152 (-25) | 9 / 11 / +2 | 2 / 4 / +2 |
| MA60 | 86 | 98 | 142 | 177→97 (-80) | 15 / 24 / +9 | 6 / 5 / -1 |

실제 체결 키는 종목·PIT identity·신호일·체결일로 비교했어. 포트폴리오 재생은 각 정책별 global cash path를 그대로 사용했어.

## 10. 성공 Gate

| 기준 | MA20 | MA60 |
|---|---|---|
| 실현 승률 ≥ 50% | False | False |
| 중앙 terminal ≥ +1% | False | False |
| 평균 terminal > CONTROL | True | True |
| portfolio MDD > -30% | True | True |
| 전체 gate 통과 | False | False |

final equity / CAGR / cash shortage / winner 수 / turnover·utilization 비교는 위 현실 포트폴리오 표와 기계 판독용 `summary.json`에 있어.

## 11. 후속 5-window 검증 추천

이번 P3-2 결과에서는 명확한 우위 기준을 충족한 후보가 없어 5-window validation을 추천하지 않아.

P3-2 단일 구간 결과만으로 공식 전략 승격은 하지 않았어.

## 12. 테스트 / integrity

- Check 결과: `{"MA20": {"cash_conservation_pass": true, "equity_curve_1140_rows": true, "signal_count_reconciles": true, "trades_equal_executable_accepted_signals": true, "unresolved_count_zero": true, "worker_errors_zero": true}, "MA60": {"cash_conservation_pass": true, "equity_curve_1140_rows": true, "signal_count_reconciles": true, "trades_equal_executable_accepted_signals": true, "unresolved_count_zero": true, "worker_errors_zero": true}, "accepted_signal_to_trade_ledger_one_to_one": true, "all_candidate_checks_pass": true, "all_candidate_trades_passed_signal_close_filter": true, "candidate_worker_errors": 0, "current_or_future_month_observations_used": 0, "entry_open_equals_repository_v2_and_adjusted_store": true, "frozen_authority_hashes_and_head_blobs": true, "frozen_control_not_replayed": true, "latest_rolling_authority_reads": 0, "network_api_or_new_price_calls": 0, "production_or_canonical_source_changes": 0, "saved_control_exact_parity": true, "signal_close_equals_repository_v2_and_adjusted_store": true, "workers": 10}`
- candidate 각 worker 수 10, raw eligible signals = PIT rejected + PIT-qualified MA blocked + PIT-qualified MA passed로 reconciled.
- accepted signals와 후보 거래 원장을 identity/signal-date 기준으로 one-to-one 대조했어.
- 현금 보존, unresolved positions, daily equity row count 1,140개를 후보별 확인했어.
- MA 입력 경로는 signal-day close만 사용해. `entry_open`은 진입 필터에 전달되지 않아.

## 13. Git commit / push

- 산출물 생성 전 상태: branch `main`, HEAD `1efe28697caad98ba2564211428d8cb26f68d81a`, origin/main `1efe28697caad98ba2564211428d8cb26f68d81a`.
- 산출물 생성 전 HEAD == origin/main: True; ahead/behind: 0	0.
- 이 산출물 디렉터리만 커밋·푸시하고, 완료 후 HEAD == origin/main 검증 결과와 commit SHA를 r.md에 기록해.

## 산출물

- `attempt_02_failure.json`
- `attempt_02_preflight.json`
- `filter_blocked_signal_analysis.csv`
- `initial_attempt_failure.json`
- `initial_attempt_preflight.json`
- `initial_attempt_report.md`
- `initial_attempt_summary.json`
- `ma20_daily_equity.csv`
- `ma20_portfolio_events.csv`
- `ma20_signal_audit.csv`
- `ma20_skipped.csv`
- `ma20_strategy_trades.csv`
- `ma20_valuation_carry_audit.csv`
- `ma60_daily_equity.csv`
- `ma60_portfolio_events.csv`
- `ma60_signal_audit.csv`
- `ma60_skipped.csv`
- `ma60_strategy_trades.csv`
- `ma60_valuation_carry_audit.csv`
- `opportunity_cost_analysis.csv`
- `preflight.json`
- `price_store_audit.csv`
- `report.md`
- `run_monthly_ma_entry_filter_backtest.py`
- `signal_close_vs_entry_open_ma_parity.csv`
- `summary.json`
