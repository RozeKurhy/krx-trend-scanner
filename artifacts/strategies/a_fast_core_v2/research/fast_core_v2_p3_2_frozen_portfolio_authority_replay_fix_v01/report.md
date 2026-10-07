| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 0 | CONTROL exact parity 및 A/B 완료 |
| MINOR | 1 | 2026-09-21 original merged PIT bytes 대신 인증 산출물에 저장된 exact survivor projection을 복원 |

# FAST Core V2 P3-2 Frozen Portfolio Authority Replay Fix V01

## 1. 최종 토큰

`FAST_CORE_V2_P3_2_FROZEN_PORTFOLIO_AUTHORITY_REPLAY_FIX_V01_COMPLETE`

## 2. 기존 P3-2 certified portfolio provenance

- 상태: `P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED`; 코드 revision `e15033925177977c026098039c3c29f245c6bf88` → `342d41d1662cf00d33ee1304c75035e04d1301e9`.
- strategy source SHA-256: `a6e70b7bda6507f0913b7553fb8004cb9b2d96460eb4f4dabfc0ab82488351c8`; runner SHA-256: `a48f49d61284b9b558e1172ea907feaa3bc35f6c2a5aaeb735c6db9739a56431`.
- 기간 2022-01-03~2026-08-31, 체결 지원 2026-09-01; reference current COMMON as-of 2026-09-21.
- 초기자본 ₩200,000,000, 종목별 총 매수예산 ₩5,000,000, exact raw signal-date MKTCAP ≥ ₩1조, 매수·매도 수수료 0.015%, 슬리피지 각 0.1%, 동일 시가 매도 후 현금 T+1, 현금 부족 시 전량 skip, 포지션 수 제한 없음.
- 기존 source ledger 405건은 전략 신호 수고, 실제 체결 진입은 228건이야.

## 3. latest authority dependency 원인

공식 runner의 `_load_survivor_context()`는 `load_rolling_authority()`와 `validate_merged_authority_coherence()`를 호출한 뒤 target/frontier 일치를 요구해. 이 latest-only 검사는 historical 경로에서 실행을 막았어. 이번 research replay는 저장된 2026-09-01 PIT/calendar와 P3-2 결과에 기록된 2026-09-21 survivor roster projection을 직접 주입했어. Production authority gate는 수정하지 않았어.

## 4. frozen replay authority

- effective PIT SHA-256 `6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1`; static calendar SHA-256 `cf9560da17674c866c57906b4b8e21ce956a0e7a0a9a3ccd1779d1a83a7111c2`.
- 2026-09-21 original merged PIT bytes는 보존되지 않았지만, certified artifact의 survivor roster 2,539개와 historical interval input을 분리 복원했고, 원본 405 signal, exact market-cap audit, event ledger, equity curve의 parity를 검증했어.
- 최신 authority read 0건, 신규 가격 수집/API 0건.

## 5. 405 vs 1,644 scope 차이

P3-2 portfolio 신호 405건과 후속 study CONTROL 1,644건의 공통 키는 340, study-only는 1,304, portfolio-only는 65건이야. 두 ledger는 permanent exclusion vintage, Repository V2 availability, exact market-cap 필터가 다른 scope야.

## 6. portfolio-only 65건 원인

| 분류 | 건수 | 근거 |
|---|---:|---|
| 후속 study의 다른 permanent exclusion authority | 35 | P3-2 roster에는 생존했지만 6612 study snapshot에서 permanent exclusion 됐고 후보 ledger에서 제외 |
| 후속 study 입력에서 Repository V2 data unavailable | 4 | data-availability audit의 `REPOSITORY_V2_DATA_UNAVAILABLE` |
| 시총 미달 선행 신호가 study re-entry 상태를 소비 | 26 | 선행 신호는 exact P3-2 raw MKTCAP < ₩1조; P3 gate가 선행 신호를 거부해 다음 qualifying 신호를 허용 |

65건 모두 P3-2의 정확한 신호일 MKTCAP ≥ ₩1조를 통과했고, 세 분류는 상호 배타적으로 전체 65건을 설명해.

## 7. CONTROL exact replay parity

- strategy 405건: `True`; exact MKTCAP audit `True` (6244 attempts).
- portfolio event ledger `True`; daily equity `True`; row 수 1140.
- 주요 portfolio parity 검사는 summary에 저장했고, 날짜·키·count는 exact, portfolio 금액은 1e-6원, return/CAGR은 기존 0.1%p tolerance를 적용했어.

## 8. Candidate A/B 결과

| 거래 지표 | CONTROL | Candidate A | Candidate B |
|---|---:|---:|---:|
| trade_count | 405 | 357 | 346 |
| realized_count | 369 | 301 | 279 |
| open_count | 36 | 56 | 67 |
| realized_win_rate_pct | 32.79132791327913 | 41.52823920265781 | 45.51971326164875 |
| terminal_positive_rate_pct | 36.54320987654321 | 44.537815126050425 | 46.24277456647399 |
| average_terminal_return_pct | 17.398864197530862 | 22.19 | 23.233468208092486 |
| median_terminal_return_pct | -14.54 | -11.15 | -8.865 |
| average_realized_return_pct | 15.14783197831978 | 22.129435215946845 | 26.29351254480287 |
| median_realized_return_pct | -14.99 | -14.53 | -11.11 |
| loss_guard_exit_count | 231 | 156 | 132 |
| score_alive_guard_exit_count | 0 | 156 | 132 |
| hard_safety_exit_count | 0 | 0 | 31 |
| progressed_count | 293 | 263 | 257 |
| average_holding_trading_days | 150.66913580246913 | 207.8263305322129 | 236.23121387283237 |
| median_holding_trading_days | 89.0 | 142.0 | 159.5 |
| mae_le_neg_30_count | 9 | 46 | 41 |
| mae_le_neg_40_count | 4 | 18 | 28 |
| mfe_ge_pos_20_count | 210 | 214 | 215 |
| mfe_ge_pos_50_count | 142 | 148 | 148 |
| mfe_ge_pos_100_count | 72 | 75 | 73 |

## 9. 거래 단위 비교

`trade_comparison.csv`에 ticker/entry-signal-date 기준으로 CONTROL/A/B의 거래 ID, entry/exit, 상태, terminal return, MAE/MFE, guard 분류를 저장했어. 이후 re-entry가 달라져 키가 한쪽에만 있는 거래는 그대로 표시했어.

## 10. Portfolio 비교

| 지표 | CONTROL | Candidate A | Candidate B |
|---|---:|---:|---:|
| final_equity | 371154513.82105666 | 361786972.3286551 | 325710882.6996592 |
| cumulative_return_pct | 85.57725691052833 | 80.89348616432757 | 62.85544134982961 |
| CAGR_pct | 14.198241187427874 | 13.57312044703265 | 11.040034689348932 |
| mdd_pct | -15.135469 | -16.92738 | -20.998728 |
| trade_count | 228 | 184 | 158 |
| realized_trade_count | 207 | 156 | 129 |
| cash_shortage_skipped_entries | 177 | 173 | 188 |
| maximum_concurrent_positions | 56 | 56 | 54 |
| average_capital_utilization_pct | 77.81317632850364 | 81.3626443872471 | 81.72818346173628 |
| open_at_effective_cutoff_count | 24 | 32 | 31 |
| unresolved_count | 0 | 0 | 0 |

## 11. 성공 Gate

| 기준 | Candidate A | Candidate B |
|---|---|---|
| 실현 승률 ≥ 50% | False | False |
| 중앙 terminal ≥ +1% | False | False |
| 평균 terminal > CONTROL | True | True |
| portfolio MDD > -30% | True | True |
| 전체 Gate | False | False |

## 12. V2 수정 여부

`False`. Official strategy source와 production Daily Update 경로는 수정하지 않았어. Candidate A/B는 research overlay로만 비교했어.

## 13. 변경 파일

- `run_frozen_replay.py` (research-only runner)
- 생성된 preflight, provenance, reconciliation, 거래 원장, event/equity 산출물은 `files_created`에 기록했어.

## 14. 테스트

{
  "production_daily_update_authority_path": {
    "status": "PASS",
    "rolling_authority_load_preserved": true,
    "frontier_equality_gate_preserved": true,
    "production_gate_unchanged": true
  },
  "frozen_historical_replay_path": "PASS",
  "control_exact_parity": "PASS",
  "candidate_a_b_isolation": "PASS",
  "no_latest_authority_dependency_frozen_mode": "PASS",
  "network_calls": 0,
  "saved_candidate_portfolio_replay_parity": {
    "A": {
      "pass": true,
      "events": {
        "pass": true,
        "actual_rows": 658,
        "expected_rows": 658,
        "mismatch_count": 0,
        "first_mismatches": []
      },
      "daily_equity": {
        "pass": true,
        "actual_rows": 1140,
        "expected_rows": 1140,
        "mismatch_count": 0,
        "first_mismatches": []
      }
    },
    "B": {
      "pass": true,
      "events": {
        "pass": true,
        "actual_rows": 625,
        "expected_rows": 625,
        "mismatch_count": 0,
        "first_mismatches": []
      },
      "daily_equity": {
        "pass": true,
        "actual_rows": 1140,
        "expected_rows": 1140,
        "mismatch_count": 0,
        "first_mismatches": []
      }
    }
  }
}

## 15. git status

- branch `main`, HEAD `2a6b47545fec633fc94382bf1516e78d2dbc488f`, origin/main `2a6b47545fec633fc94382bf1516e78d2dbc488f`.
- tracked source changes: 0; commit/push: 안 했어.
- 기존 unrelated untracked artifact는 유지했어.
