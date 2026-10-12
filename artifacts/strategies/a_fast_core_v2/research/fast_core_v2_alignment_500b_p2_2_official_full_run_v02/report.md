# FAST Core V2 Alignment + 500B — P2-2 전수 결과 V02

## 이슈 유형 수

| 심각도 | 유형 수 | 유형 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 1 | NAV_MARK_UNRESOLVED |
| MINOR | 2 | CASH_SHORTAGE_SKIP_DIAGNOSTIC, CUTOFF_OPEN_POSITIONS_MARKED_WITHOUT_HYPOTHETICAL_EXIT_COST |

## 실행 범위와 입력 검증

- 실제 평가 구간 2021-01-04~2026-08-31, 1,387 exact KRX 세션. 2026-09-01은 cutoff 전 신호의 체결 확인만 지원했어.
- 종목 2,573/2,573, 신호 worker 10개, worker 오류 0건.
- P2-2 COMMON interval 2,749; 182쌍 적용 뒤 적격 ticker 2,573. 380440/KR7380440008은 영구 제외 registry로 제외.
- rolling authority/소스/코드/계약 hash 재검증: PASS (106/106); signal filter 상태 {"PASS": 284, "REJECT_ALIGNMENT": 6259, "REJECT_MA_UNAVAILABLE": 728, "REJECT_MCAP_BELOW_500B": 1812}.
- exact market-cap unresolved 0; Repository V2 미가용 종목 0; projection mismatch 종목 0.

## 공식 A~E

| 게이트 | CONTROL | ALIGNMENT_MCAP_500B |
|---|---|---|
| A 무결성 | PASS | PASS |
| B 비용 | PASS | PASS |
| C 수익성 | CHECK_REQUIRED | CHECK_REQUIRED |
| D MDD | CHECK_REQUIRED | CHECK_REQUIRED |
| E 유효성 | CHECK_REQUIRED | CHECK_REQUIRED |

## 포트폴리오 비교

거래 수익률과 승률의 분모는 cutoff 이전 실제 매수 후 실제 청산한 거래야. 순수익률은 양쪽 비용·슬리피지를 포함하고 보유 거래일은 진입/청산 체결 세션을 포함해 계산했어.

| 지표 | CONTROL | 후보 | 후보−CONTROL |
|---|---:|---:|---:|
| 종료 자산(원) | — | — | — |
| 총수익률(%) | — | — | — |
| CAGR(%) | — | — | — |
| MDD(%) | — | — | — |
| NAV coverage(%) | 68.85 | 61.86 | -6.99 |
| NAV 결측일 | 432.00 | 529.00 | 97.00 |
| 진입 시도 | 2,287.00 | 283.00 | -2,004.00 |
| 현금 부족 skip | 1,829.00 | 33.00 | -1,796.00 |
| 현금 부족률(%) | 79.97 | 11.66 | -68.31 |
| 실매수 | 458.00 | 250.00 | -208.00 |
| 실현 청산 | 410.00 | 228.00 | -182.00 |
| cutoff 미청산 | 48.00 | 22.00 | -26.00 |
| 실현 거래 | 410.00 | 228.00 | -182.00 |
| 승률(%) | 26.83 | 37.72 | 10.89 |
| 평균 순수익률(%) | 6.16 | 15.84 | 9.68 |
| 중앙 순수익률(%) | -15.63 | -14.95 | 0.68 |
| 평균 보유 거래일 | 101.02 | 128.15 | 27.13 |
| 중앙 보유 거래일 | 58.00 | 86.00 | 28.00 |
| 최대 거래수익률(%) | 434.05 | 249.20 | -184.85 |
| 최대 거래손실률(%) | -35.80 | -38.18 | -2.39 |
| +20% 이상 거래 | 86.00 | 70.00 | -16.00 |
| +50% 이상 거래 | 57.00 | 50.00 | -7.00 |
| +100% 이상 거래 | 23.00 | 18.00 | -5.00 |
| -10% 이하 거래 | 289.00 | 139.00 | -150.00 |
| -15% 이하 거래 | 250.00 | 113.00 | -137.00 |
| -20% 이하 거래 | 22.00 | 8.00 | -14.00 |
| -30% 이하 거래 | 4.00 | 4.00 | 0.00 |
| Loss Guard 매수 | 280.00 | 134.00 | -146.00 |
| PROGRESSED 매수 | 149.00 | 108.00 | -41.00 |
| 최대 동시보유 | 67.00 | 53.00 | -14.00 |
| 평균 현금비중(%) | 9.31 | 47.07 | 37.76 |
| 회전율 배수 | 22.25 | 12.74 | -9.51 |
| 수수료(원) | 667,636.80 | 382,306.17 | -285,330.63 |
| 슬리피지(원) | 4,450,804.35 | 2,548,782.92 | -1,902,021.43 |
| 최대 티커 양의 손익 점유율(%) | 5.99 | 4.56 | -1.43 |

### MDD 및 청산 사유

- CONTROL: CHECK_REQUIRED —% (peak 2023-04-07, trough 2023-10-31, recovery 미회복).
- 후보: CHECK_REQUIRED —% (peak 2021-08-09, trough 2022-10-13, recovery 2023-07-28); CONTROL−후보 —%p.
- CONTROL 청산 사유 {"EXIT3_PROGRESSED_TO_EARLY_TREND": 2, "EXIT3_PROGRESSED_TO_TRANSITION": 6, "EXIT3_PROGRESSED_TO_WEAK": 4, "EXIT4_SCORE_DRAWDOWN_GE_15": 118, "LOSS_GUARD_CLOSE_LE_NEG_15": 280}.
- 후보 청산 사유 {"EXIT3_PROGRESSED_TO_BASE": 1, "EXIT3_PROGRESSED_TO_EARLY_TREND": 2, "EXIT3_PROGRESSED_TO_TRANSITION": 6, "EXIT3_PROGRESSED_TO_WEAK": 2, "EXIT4_SCORE_DRAWDOWN_GE_15": 83, "LOSS_GUARD_CLOSE_LE_NEG_15": 134}.
- 최대 티커 손익 점유율: CONTROL 5.99% (101670); 후보 4.56% (319660).
- 연도/시장별 실현손익은 control_annual_market_diagnostics.csv와 alignment_mcap_500b_annual_market_diagnostics.csv에 저장했어.

## 무결성 및 판정 범위

- 신호 원장 exact PIT/MA60/시총 검사: {"duplicate_exact_pit_signal_audit_keys": 0, "control_trade_without_one_active_common_identity_audit": 0, "candidate_trade_alignment_mcap_or_prior_60m_mismatch": [], "control_trade_set_matches_pit_pass_audit": true, "candidate_trade_set_matches_candidate_pass_audit": true, "excluded_identity_trade_leakage": [], "control_missing_examples": []}.
- NAV는 1,387일 기준 CONTROL 68.85% / 후보 61.86%; 최장 연속 결측 430 / 521일.
- 가격 해시/PIT/현금·비용 독립 검산 결과는 integrity_audit.json, 029960·128940·003690 및 380440 노출 감사는 identity_exposure_audit.csv.
- 현금 부족 skip은 진단값이지 공식 게이트가 아니야. cutoff 미청산은 cutoff 종가 평가만 하며 가상 매도비용을 부과하지 않았어.
- 단일 P2-2 결과야. 5기간 채택 NOT_FINAL_5WINDOW, 후보 채택과 baseline 승격 NOT_EVALUATED, 기본 전략 PATTERN_A_FAST_FINAL_STRATEGY_V02 유지.

## 주요 산출물

plan.md, execution_contract.json, preflight.json, active_pit_missing_sessions.csv, source_manifest.json, sample_benchmark.json, full_run_execution.json, 그룹별 trades/events/cash/NAV/valuation/missing marks, metrics_comparison.csv, gate_results.json, integrity_audit.json, artifact_hashes.json.

## 전수 Koentec 노출 감사

대상은 `029960 / KR7029960002`야. 신호 원장에 남은 trade row는 실제 보유로 보지 않고, 전수 portfolio event의 EXECUTED 체결만 포지션으로 계산했어.

| 진입 신호→체결 | 상태 | 사유 | 당시 현금 | T+1 대기 매도대금 | 필요 총매수비용 | 부족액 |
|---|---|---|---:|---:|---:|---:|
| 2021-07-09→2021-07-12 | SKIPPED_CASH_UNAVAILABLE | INSUFFICIENT_AVAILABLE_CASH | 2,550,668.66원 | 0.00원 | 4,997,230.96원 | 2,446,562.30원 |
| 2024-11-15→2024-11-18 | SKIPPED_CASH_UNAVAILABLE | INSUFFICIENT_AVAILABLE_CASH | 3,353,280.77원 | 4,083,778.86원 | 4,999,843.96원 | 1,646,563.19원 |

2024-11-18의 deterministic entry 순서는 아래와 같아. `017960` 매도대금 4,083,778.86원은 그날 pending으로 남아 신규 매수 현금으로 쓰이지 않았고, `010640`을 먼저 매수한 뒤 현금 3,353,280.77원만 남아 코엔텍의 558주 주문(총 4,999,843.96원)이 전량 skip됐어.

| 순번 | 종목 | 이벤트 | 상태 | 현금 전→후 | 사유 |
|---:|---|---|---|---:|---|
| 1 | 017960 | EXIT | EXECUTED | 8347720.525137298→8347720.525137298 | STRATEGY_EXIT |
| 2 | 010640 | ENTRY | EXECUTED | 8347720.525137298→3353280.769531998 | V2_CONTROL_SIGNAL |
| 3 | 029960 | ENTRY | SKIPPED_CASH_UNAVAILABLE | 3353280.769531998→3353280.769531998 | INSUFFICIENT_AVAILABLE_CASH |
| 4 | 084010 | ENTRY | SKIPPED_CASH_UNAVAILABLE | 3353280.769531998→3353280.769531998 | INSUFFICIENT_AVAILABLE_CASH |
| 5 | 105550 | ENTRY | SKIPPED_CASH_UNAVAILABLE | 3353280.769531998→3353280.769531998 | INSUFFICIENT_AVAILABLE_CASH |

| 확인 날짜 | 의미 | CONTROL 보유주 | 후보 보유주 |
|---|---|---:|---:|
| 2025-05-30 | SHARE_EXCHANGE_DATE | 0 | 0 |
| 2025-06-16 | DELISTING_DATE | 0 | 0 |
| 2026-08-31 | P2_2_CUTOFF | 0 | 0 |

결론은 `NO_EXPOSURE_AFTER_FULL_REPLAY`야. 2021-07-12 및 2024-11-18 진입 시도가 모두 현금 부족으로 미체결이고, 2025-05-30 주식교환일·2025-06-16 상장폐지일·cutoff에 실제 보유는 0주야. 해당 기업행위로 인한 NAV 결측도 0일이야. 9,000원/주 지급이나 2025-06-20 입금예정 채권은 반영하지 않았어. P3-2 evidence에서도 실제 지급일 입증과 회계 계약이 없고 특수 정산을 넣지 않았다고 기록돼 있어.

## 미해결 NAV mark 전수 분해

| 그룹 | 미해결 mark | 종목 | 원인 요약 |
|---|---:|---|---|
| CONTROL | 2 | 068240 | 2일 raw 거래행 존재, 조정 행 2건은 OHLC 검사 제외 (high<close) |
| CONTROL | 430 | 138580 | 430일 조정 소스 행 없음 (2024-11-22~2026-08-31); 정확한 raw 종목 행도 없음 |
| CANDIDATE | 521 | 003410 | 521일 조정 소스 행 없음 (2024-07-09~2026-08-31); 정확한 raw 종목 행도 없음 |
| CANDIDATE | 4 | 003690 | 4일 raw 거래행 존재, 조정 행 4건은 OHLC 검사 제외 (high<close) |
| CANDIDATE | 2 | 068240 | 2일 raw 거래행 존재, 조정 행 2건은 OHLC 검사 제외 (high<close) |
| CANDIDATE | 4 | 085660 | 4일 raw 거래행 존재, 조정 행 4건은 OHLC 검사 제외 (high<close) |

정상 거래일의 포트폴리오 mark와 원시/조정 소스를 분리해 확인했어. `003690` 후보 4일(2023-04-25, 2023-06-28, 2024-02-16, 2024-06-27), `068240` 양쪽 각 2일, `085660` 후보 4일은 raw partition에 거래량·거래대금이 있고 adjusted parquet에도 양수 OHLC 행이 있어. 다만 각 날짜 adjusted close가 adjusted high보다 1원 높아 Repository V2의 OHLC 관계 검사에서 composed view로 나오지 않아. 같은 날 raw 거래활동이 확인돼 비거래 placeholder carry도 적용되지 않았어. 날짜별 원시 값·adjusted OHLC·제외 사유는 `unresolved_mark_reconciliation.csv`에 전부 있어.

`138580` CONTROL의 430일(2024-11-22~2026-08-31)은 adjusted 파일의 마지막 행이 2024-11-05이고 이후 해당 날짜의 raw 종목 행과 adjusted source 행이 모두 없어. `003410` 후보의 521일(2024-07-09~2026-08-31)은 adjusted 파일 마지막 행이 2024-06-20이고 이후 exact raw/adjusted 행이 없어. 두 포지션은 거래 원장에서 `OPEN_AT_CUTOFF`로 남아 있어 cutoff 가치가 확정되지 않아. 미확인 사건·정산값이나 마지막 값을 채워 넣지 않았어.

`128940`는 양 그룹 전체에서 unresolved mark 0건이야. 후보의 2024-10-18 신호 포지션은 2024-10-21 진입 후 2024-11-18 청산됐고, 2025년 진입 포지션도 2026-06-01 청산돼.

NAV 결측 합계는 CONTROL 432/1,387일(68.85%), 후보 531/1,387일(61.86%)이야. 결과 원장 비용·현금·신호 무결성 검사는 통과했지만, 이 coverage가 90% 미만이라 cutoff 자산가치·총수익률·CAGR과 공식 MDD를 확정하지 않았어. 따라서 양 그룹 C, D, E는 `CHECK_REQUIRED`; 단일 P2-2 전체 판정도 `CHECK_REQUIRED`야.

## 필터 행 수와 portfolio 체결 지원일

후보 필터 감사에는 PASS 284행이 있고, 그중 후보 스캔에 실제 포함된 PASS는 283행이야. 나머지 1행은 후보 스캔은 아니고 CONTROL 스캔에만 보인 신호라 후보 trade 원장 집합과 차이를 만들지 않아. `signal_ledger_checks`에서도 CONTROL/PASS 원장 일치가 양쪽 모두 true야.
2026-09-01 지원 세션 청산은 CONTROL 1건, 후보 1건이며 P2-2 성과·NAV에는 포함하지 않았어. 신호 평가 2,573/2,573, worker 10개, 오류 0건, 전체 wall 4,787.042초, CPU 5,349.323초, peak RSS 3,111.7MB야. 기존 표본 실행은 32종목·10 workers·0 error·191.241초이며, 표본 거래/자금 결과는 전수 결과에 합치지 않았어.

## Provenance 재확인

| 파일 | SHA-256 |
|---|---|
| `docs/validation/backtest_common_rules.md` | `e8783958064ddfc54f57bef3500ad41de6d3b6bc853fce2464845f9c4cc4d06b` |
| `docs/validation/official_strategy_adoption_criteria.md` | `380f34cd7e24fd9881d7a154000d9b51512d905d7c7ef24b1940f5fa4e22cb88` |
| `docs/strategies/strategy_lifecycle.md` | `c89bad3f56b95a9bac3284fb9817067940534b52c87c29f57f3009ea5a1e25e8` |
| `docs/patterns/pattern_a_fast/strategy/version_02/README.md` | `d353afec7e26ad4adb296dc14e337a78c88466d3ddcee887932ef1fd58f295ef` |
| `data/market/rolling_authority/manifest.json` | `5c4a9e346d7460c4a28b30a3cd9ab19c9c17527f1c4409282206e8ec2a731570` |
| `data/market/rolling_authority/merged_pit_intervals.json` | `d93a958d7bbae9142ef1fa5aded36080d1d107739e777eb4ec3b6566fea90654` |
| `data/market/rolling_authority/merged_trading_calendar.json` | `ab7635de160e06d538d9d0dc7225c8e1b307f191f54f2584d4c79e47a94a7480` |
| `src/trend_scanner/data/repository_v2.py` | `c252835604b0fd8f2e839d438052670d9700e773f1c34cb83582c5c29a198215` |
| `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/run_official_realistic_replay.py` | `3d7f573bb908b904758427e59967d698fc471cf3af0de699815aa5516ab9705b` |
| P2-2 조정가격 해시 inventory (2,573 files) | `da0f34e85c72d6dedb28fd93468721953329753cee23ca9015afb92bb59a29f8` |
| P2-2 신호일 KRX partition inventory (557 rows) | `f1c60ffa9360dfd09789051d16554f7e305a1ef659d4f4adfcc98481de8073ed` |
| 영구 제외 (182 pairs; canonical) | `9091a40d5dfc3dc115e00166ea3ef806ef5a4ca3b595d76864598ec050904b12` |
| 실행 전 고정 source manifest (106/106 검증) | `5e3915a2c06f557e1c8ee512e8c0fb2772925a06205b5e49486671d0b297a836` |
| 재사용 PIT missing-session evidence | `df84569dad960361dc4bd9e995f820c286aacd0ac864057256dbab9b066da0fe` |

전체 source manifest는 full run 종료 후에도 106/106 일치야. V01 표본 coverage 기준만 전수 실행 허가에서 제외했고 공식 A~E 기준은 그대로 적용했어.

## 산출물 추가

`koentec_full_exposure_audit.json`, `unresolved_mark_reconciliation.csv`, `active_pit_missing_sessions.csv`, `finalize_v02_addenda.py`, `run_finalizer_numeric_compat.py`.

## V02 final audit addenda

## 전수 Koentec 노출 감사

대상은 `029960 / KR7029960002`야. 신호 원장에 남은 trade row는 실제 보유로 보지 않고, 전수 portfolio event의 EXECUTED 체결만 포지션으로 계산했어.

| 진입 신호→체결 | 상태 | 사유 | 당시 현금 | T+1 대기 매도대금 | 필요 총매수비용 | 부족액 |
|---|---|---|---:|---:|---:|---:|
| 2021-07-09→2021-07-12 | SKIPPED_CASH_UNAVAILABLE | INSUFFICIENT_AVAILABLE_CASH | 2,550,668.66원 | 0.00원 | 4,997,230.96원 | 2,446,562.30원 |
| 2024-11-15→2024-11-18 | SKIPPED_CASH_UNAVAILABLE | INSUFFICIENT_AVAILABLE_CASH | 3,353,280.77원 | 4,083,778.86원 | 4,999,843.96원 | 1,646,563.19원 |

2024-11-18의 deterministic entry 순서는 아래와 같아. `017960` 매도대금 4,083,778.86원은 그날 pending으로 남아 신규 매수 현금으로 쓰이지 않았고, `010640`을 먼저 매수한 뒤 현금 3,353,280.77원만 남아 코엔텍의 558주 주문(총 4,999,843.96원)이 전량 skip됐어.

| 순번 | 종목 | 이벤트 | 상태 | 현금 전→후 | 사유 |
|---:|---|---|---|---:|---|
| 1 | 017960 | EXIT | EXECUTED | 8347720.525137298→8347720.525137298 | STRATEGY_EXIT |
| 2 | 010640 | ENTRY | EXECUTED | 8347720.525137298→3353280.769531998 | V2_CONTROL_SIGNAL |
| 3 | 029960 | ENTRY | SKIPPED_CASH_UNAVAILABLE | 3353280.769531998→3353280.769531998 | INSUFFICIENT_AVAILABLE_CASH |
| 4 | 084010 | ENTRY | SKIPPED_CASH_UNAVAILABLE | 3353280.769531998→3353280.769531998 | INSUFFICIENT_AVAILABLE_CASH |
| 5 | 105550 | ENTRY | SKIPPED_CASH_UNAVAILABLE | 3353280.769531998→3353280.769531998 | INSUFFICIENT_AVAILABLE_CASH |

| 확인 날짜 | 의미 | CONTROL 보유주 | 후보 보유주 |
|---|---|---:|---:|
| 2025-05-30 | SHARE_EXCHANGE_DATE | 0 | 0 |
| 2025-06-16 | DELISTING_DATE | 0 | 0 |
| 2026-08-31 | P2_2_CUTOFF | 0 | 0 |

결론은 `NO_EXPOSURE_AFTER_FULL_REPLAY`야. 2021-07-12 및 2024-11-18 진입 시도가 모두 현금 부족으로 미체결이고, 2025-05-30 주식교환일·2025-06-16 상장폐지일·cutoff에 실제 보유는 0주야. 해당 기업행위로 인한 NAV 결측도 0일이야. 9,000원/주 지급이나 2025-06-20 입금예정 채권은 반영하지 않았어. P3-2 evidence에서도 실제 지급일 입증과 회계 계약이 없고 특수 정산을 넣지 않았다고 기록돼 있어.

## 미해결 NAV mark 전수 분해

| 그룹 | 미해결 mark | 종목 | 원인 요약 |
|---|---:|---|---|
| CONTROL | 2 | 068240 | 2일 raw 거래행 존재, 조정 행 2건은 OHLC 검사 제외 (high<close) |
| CONTROL | 430 | 138580 | 430일 조정 소스 행 없음 (2024-11-22~2026-08-31); 정확한 raw 종목 행도 없음 |
| CANDIDATE | 521 | 003410 | 521일 조정 소스 행 없음 (2024-07-09~2026-08-31); 정확한 raw 종목 행도 없음 |
| CANDIDATE | 4 | 003690 | 4일 raw 거래행 존재, 조정 행 4건은 OHLC 검사 제외 (high<close) |
| CANDIDATE | 2 | 068240 | 2일 raw 거래행 존재, 조정 행 2건은 OHLC 검사 제외 (high<close) |
| CANDIDATE | 4 | 085660 | 4일 raw 거래행 존재, 조정 행 4건은 OHLC 검사 제외 (high<close) |

정상 거래일의 포트폴리오 mark와 원시/조정 소스를 분리해 확인했어. `003690` 후보 4일(2023-04-25, 2023-06-28, 2024-02-16, 2024-06-27), `068240` 양쪽 각 2일, `085660` 후보 4일은 raw partition에 거래량·거래대금이 있고 adjusted parquet에도 양수 OHLC 행이 있어. 다만 각 날짜 adjusted close가 adjusted high보다 1원 높아 Repository V2의 OHLC 관계 검사에서 composed view로 나오지 않아. 같은 날 raw 거래활동이 확인돼 비거래 placeholder carry도 적용되지 않았어. 날짜별 원시 값·adjusted OHLC·제외 사유는 `unresolved_mark_reconciliation.csv`에 전부 있어.

`138580` CONTROL의 430일(2024-11-22~2026-08-31)은 adjusted 파일의 마지막 행이 2024-11-05이고 이후 해당 날짜의 raw 종목 행과 adjusted source 행이 모두 없어. `003410` 후보의 521일(2024-07-09~2026-08-31)은 adjusted 파일 마지막 행이 2024-06-20이고 이후 exact raw/adjusted 행이 없어. 두 포지션은 거래 원장에서 `OPEN_AT_CUTOFF`로 남아 있어 cutoff 가치가 확정되지 않아. 미확인 사건·정산값이나 마지막 값을 채워 넣지 않았어.

`128940`는 양 그룹 전체에서 unresolved mark 0건이야. 후보의 2024-10-18 신호 포지션은 2024-10-21 진입 후 2024-11-18 청산됐고, 2025년 진입 포지션도 2026-06-01 청산돼.

NAV 결측 합계는 CONTROL 432/1,387일(68.85%), 후보 531/1,387일(61.86%)이야. 결과 원장 비용·현금·신호 무결성 검사는 통과했지만, 이 coverage가 90% 미만이라 cutoff 자산가치·총수익률·CAGR과 공식 MDD를 확정하지 않았어. 따라서 양 그룹 C, D, E는 `CHECK_REQUIRED`; 단일 P2-2 전체 판정도 `CHECK_REQUIRED`야.

## Observed MDD 진단값

| 그룹 | Observed MDD (진단 전용) | Peak | Trough | Recovery | 유효 NAV |
|---|---:|---|---|---|---:|
| CONTROL | -36.78% | 2023-04-07 | 2023-10-31 | 미회복 | 955/1,387 |
| 후보 | -19.45% | 2021-08-09 | 2022-10-13 | 2023-07-28 | 858/1,387 |
공식 D 비교식은 `CONTROL MDD - Candidate MDD`이며 실패 임계값은 `>= +5.0%p`야. 두 그룹 모두 coverage가 90% 미만이라 공식 MDD 및 상대폭은 확정하지 않았어. Observed 값만으로 계산한 `-17.33%p`는 진단값이며 공식 D 판정에 사용하지 않아.

## 필터 행 수와 portfolio 체결 지원일

후보 필터 감사에는 PASS 284행이 있고, 그중 후보 스캔에 실제 포함된 PASS는 283행이야. 나머지 1행은 후보 스캔은 아니고 CONTROL 스캔에만 보인 신호라 후보 trade 원장 집합과 차이를 만들지 않아. `signal_ledger_checks`에서도 CONTROL/PASS 원장 일치가 양쪽 모두 true야.
2026-09-01 지원 세션 청산은 CONTROL 1건, 후보 1건이며 P2-2 성과·NAV에는 포함하지 않았어. 신호 평가 2,573/2,573, worker 10개, 오류 0건, 전체 wall 4,787.042초, CPU 5,349.323초, peak RSS 3,111.7MB야. 기존 표본 실행은 32종목·10 workers·0 error·191.241초이며, 표본 거래/자금 결과는 전수 결과에 합치지 않았어.

## Provenance 재확인

| 파일 | SHA-256 |
|---|---|
| `docs/validation/backtest_common_rules.md` | `e8783958064ddfc54f57bef3500ad41de6d3b6bc853fce2464845f9c4cc4d06b` |
| `docs/validation/official_strategy_adoption_criteria.md` | `380f34cd7e24fd9881d7a154000d9b51512d905d7c7ef24b1940f5fa4e22cb88` |
| `docs/strategies/strategy_lifecycle.md` | `c89bad3f56b95a9bac3284fb9817067940534b52c87c29f57f3009ea5a1e25e8` |
| `docs/patterns/pattern_a_fast/strategy/version_02/README.md` | `d353afec7e26ad4adb296dc14e337a78c88466d3ddcee887932ef1fd58f295ef` |
| `data/market/rolling_authority/manifest.json` | `5c4a9e346d7460c4a28b30a3cd9ab19c9c17527f1c4409282206e8ec2a731570` |
| `data/market/rolling_authority/merged_pit_intervals.json` | `d93a958d7bbae9142ef1fa5aded36080d1d107739e777eb4ec3b6566fea90654` |
| `data/market/rolling_authority/merged_trading_calendar.json` | `ab7635de160e06d538d9d0dc7225c8e1b307f191f54f2584d4c79e47a94a7480` |
| `src/trend_scanner/data/repository_v2.py` | `c252835604b0fd8f2e839d438052670d9700e773f1c34cb83582c5c29a198215` |
| `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_p3_1_official_realistic_v01/run_official_realistic_replay.py` | `3d7f573bb908b904758427e59967d698fc471cf3af0de699815aa5516ab9705b` |
| P2-2 조정가격 해시 inventory (2,573 files) | `da0f34e85c72d6dedb28fd93468721953329753cee23ca9015afb92bb59a29f8` |
| P2-2 전체 raw date-market partition preflight (2,776/2,776 COMPLETE) | `ba3146b533267a5c54c61d3ef0e836d278bc9d69cb230bab7a66ede30b292d02` |
| P2-2 신호일 KRX partition inventory (557 rows) | `f1c60ffa9360dfd09789051d16554f7e305a1ef659d4f4adfcc98481de8073ed` |
| 영구 제외 (182 pairs; canonical) | `9091a40d5dfc3dc115e00166ea3ef806ef5a4ca3b595d76864598ec050904b12` |
| 실행 전 고정 source manifest (106/106 검증) | `5e3915a2c06f557e1c8ee512e8c0fb2772925a06205b5e49486671d0b297a836` |
| 재사용 PIT missing-session evidence | `df84569dad960361dc4bd9e995f820c286aacd0ac864057256dbab9b066da0fe` |

전체 source manifest는 full run 종료 후에도 106/106 일치야. V01 표본 coverage 기준만 전수 실행 허가에서 제외했고 공식 A~E 기준은 그대로 적용했어.

## 산출물 추가

`koentec_full_exposure_audit.json`, `unresolved_mark_reconciliation.csv`, `active_pit_missing_sessions.csv`, `finalize_v02_addenda.py`, `run_finalizer_numeric_compat.py`.
