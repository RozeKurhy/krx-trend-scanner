# FAST Core V2 Alignment + 500B — P2-2 184쌍 공식 재생 V01

## 이슈 유형 수

| 심각도 | 유형 수 | 유형 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 1 | NAV_MARK_UNRESOLVED |
| MINOR | 2 | CASH_SHORTAGE_SKIP_DIAGNOSTIC, CUTOFF_OPEN_POSITIONS_MARKED_WITHOUT_HYPOTHETICAL_EXIT_COST |

## 실행 범위와 입력 검증

- 실제 평가 구간 2021-01-04~2026-08-31, 1,387 exact KRX 세션. 2026-09-01은 cutoff 전 신호의 체결 확인만 지원했어.
- 저장된 신호 원장 재사용: evaluator 0회, CONTROL/후보 포트폴리오 재생 1/1회; 새 유니버스 2,571 ticker, worker 오류 0건.
- P2-2 COMMON interval 2,749; 184쌍 적용 뒤 적격 ticker 2,571. 380440/KR7380440008은 영구 제외 registry로 제외.
- rolling authority/소스/코드/계약 hash 재검증: PASS (300/300); signal filter 상태 {"PASS": 283, "REJECT_ALIGNMENT": 6259, "REJECT_MA_UNAVAILABLE": 718, "REJECT_MCAP_BELOW_500B": 1802}.
- exact market-cap unresolved 0; Repository V2 미가용 종목 0; projection mismatch 종목 0.

## 공식 A~E

| 게이트 | CONTROL | ALIGNMENT_MCAP_500B |
|---|---|---|
| A 무결성 | PASS | PASS |
| B 비용 | PASS | PASS |
| C 수익성 | PASS | PASS |
| D MDD | PASS | PASS |
| E 유효성 | OBSERVED | OBSERVED |

## 포트폴리오 비교

거래 수익률과 승률의 분모는 cutoff 이전 실제 매수 후 실제 청산한 거래야. 순수익률은 양쪽 비용·슬리피지를 포함하고 보유 거래일은 진입/청산 체결 세션을 포함해 계산했어.

| 지표 | CONTROL | 후보 | 후보−CONTROL |
|---|---:|---:|---:|
| 종료 자산(원) | 365,230,670.59 | 407,509,388.00 | 42,278,717.42 |
| 총수익률(%) | 82.62 | 103.75 | 21.14 |
| CAGR(%) | 11.24 | 13.42 | 2.18 |
| MDD(%) | -36.87 | -18.75 | 18.11 |
| NAV coverage(%) | 99.86 | 99.28 | -0.58 |
| NAV 결측일 | 2.00 | 10.00 | 8.00 |
| 진입 시도 | 2,283.00 | 282.00 | -2,001.00 |
| 현금 부족 skip | 1,821.00 | 29.00 | -1,792.00 |
| 현금 부족률(%) | 79.76 | 10.28 | -69.48 |
| 실매수 | 462.00 | 253.00 | -209.00 |
| 실현 청산 | 414.00 | 233.00 | -181.00 |
| cutoff 미청산 | 48.00 | 20.00 | -28.00 |
| 실현 거래 | 414.00 | 233.00 | -181.00 |
| 승률(%) | 26.81 | 37.34 | 10.53 |
| 평균 순수익률(%) | 6.59 | 15.51 | 8.92 |
| 중앙 순수익률(%) | -15.63 | -14.97 | 0.66 |
| 평균 보유 거래일 | 99.96 | 127.93 | 27.97 |
| 중앙 보유 거래일 | 55.00 | 86.00 | 31.00 |
| 최대 거래수익률(%) | 434.05 | 249.20 | -184.85 |
| 최대 거래손실률(%) | -35.80 | -44.39 | -8.60 |
| +20% 이상 거래 | 89.00 | 71.00 | -18.00 |
| +50% 이상 거래 | 58.00 | 51.00 | -7.00 |
| +100% 이상 거래 | 24.00 | 18.00 | -6.00 |
| -10% 이하 거래 | 293.00 | 142.00 | -151.00 |
| -15% 이하 거래 | 253.00 | 116.00 | -137.00 |
| -20% 이하 거래 | 23.00 | 10.00 | -13.00 |
| -30% 이하 거래 | 5.00 | 5.00 | 0.00 |
| Loss Guard 매수 | 284.00 | 136.00 | -148.00 |
| PROGRESSED 매수 | 149.00 | 109.00 | -40.00 |
| 최대 동시보유 | 67.00 | 53.00 | -14.00 |
| 평균 현금비중(%) | 8.80 | 40.46 | 31.66 |
| 회전율 배수 | 22.50 | 12.94 | -9.56 |
| 수수료(원) | 674,997.43 | 388,301.70 | -286,695.73 |
| 슬리피지(원) | 4,499,885.98 | 2,588,763.30 | -1,911,122.68 |
| 최대 티커 양의 손익 점유율(%) | 5.77 | 3.94 | -1.82 |

### MDD 및 청산 사유

- CONTROL: OBSERVED -36.87% (peak 2023-04-07, trough 2023-10-31, recovery 2026-01-30).
- 후보: OBSERVED -18.75% (peak 2021-08-09, trough 2022-10-13, recovery 2023-07-25); CONTROL−후보 -18.11%p.
- CONTROL 청산 사유 {"EXIT3_PROGRESSED_TO_EARLY_TREND": 2, "EXIT3_PROGRESSED_TO_TRANSITION": 6, "EXIT3_PROGRESSED_TO_WEAK": 5, "EXIT4_SCORE_DRAWDOWN_GE_15": 117, "LOSS_GUARD_CLOSE_LE_NEG_15": 284}.
- 후보 청산 사유 {"EXIT3_PROGRESSED_TO_BASE": 1, "EXIT3_PROGRESSED_TO_EARLY_TREND": 2, "EXIT3_PROGRESSED_TO_TRANSITION": 6, "EXIT3_PROGRESSED_TO_WEAK": 3, "EXIT4_SCORE_DRAWDOWN_GE_15": 85, "LOSS_GUARD_CLOSE_LE_NEG_15": 136}.
- 최대 티커 손익 점유율: CONTROL 5.77% (101670); 후보 3.94% (032190).
- 연도/시장별 실현손익은 control_annual_market_diagnostics.csv와 alignment_mcap_500b_annual_market_diagnostics.csv에 저장했어.

## 무결성 및 판정 범위

- 신호 원장 exact PIT/MA60/시총 검사: {"duplicate_exact_pit_signal_audit_keys": 0, "control_trade_without_one_active_common_identity_audit": 0, "candidate_trade_alignment_mcap_or_prior_60m_mismatch": [], "control_trade_set_matches_pit_pass_audit": true, "candidate_trade_set_matches_candidate_pass_audit": true, "excluded_identity_trade_leakage": [], "control_missing_examples": []}.
- NAV는 1,387일 기준 CONTROL 99.86% / 후보 99.28%; 최장 연속 결측 1 / 1일.
- 가격 해시/PIT/현금·비용 독립 검산 결과는 integrity_audit.json, 029960·128940·003690 및 380440 노출 감사는 identity_exposure_audit.csv.
- 현금 부족 skip은 진단값이지 공식 게이트가 아니야. cutoff 미청산은 cutoff 종가 평가만 하며 가상 매도비용을 부과하지 않았어.
- 단일 P2-2 결과야. 5기간 채택 NOT_FINAL_5WINDOW, 후보 채택과 baseline 승격 NOT_EVALUATED, 기본 전략 PATTERN_A_FAST_FINAL_STRATEGY_V02 유지.

## 주요 산출물

plan.md, execution_contract.json, preflight.json, active_pit_missing_sessions.csv, source_manifest.json, sample_benchmark.json, full_run_execution.json, 그룹별 trades/events/cash/NAV/valuation/missing marks, metrics_comparison.csv, gate_results.json, integrity_audit.json, artifact_hashes.json.
