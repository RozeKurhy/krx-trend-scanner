# FAST Core V2 Alignment + 500B — P2-1 결과

## 이슈 유형 수

| 심각도 | 유형 수 | 유형 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 0 | 없음 |
| MINOR | 3 | CASH_SHORTAGE_SKIP_DIAGNOSTIC, CUTOFF_OPEN_POSITIONS_MARKED_WITHOUT_HYPOTHETICAL_EXIT_COST, OBSERVED_NAV_MARK_GAPS |

## 실행 범위와 입력 검증

- 실제 평가 구간 2021-01-04~2025-05-30, 1,082 exact KRX 세션. 2025-06-02은 cutoff 전 신호의 체결 확인만 지원했어.
- 종목 2,480/2,480, 신호 worker 10개, worker 오류 0건.
- 표본 검증 PASS / 전수 허가 True; 전수 실제 소요 1.026시간 (표본 추정 0.8501시간). 재생 authorization guard를 통과했어.
- P2-1 COMMON interval 2,658; 184쌍 적용 뒤 적격 ticker 2,480. 380440/KR7380440008은 영구 제외 registry로 제외.
- rolling authority/소스/코드/계약 hash 재검증: PASS (313/313); adjusted 주가 2480개와 KRX raw partition 2166개의 해시 재검증 PASS. signal filter 상태 {"PASS": 214, "REJECT_ALIGNMENT": 4188, "REJECT_MA_UNAVAILABLE": 589, "REJECT_MCAP_BELOW_500B": 1394}.
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
| 종료 자산(원) | 281,875,564.60 | 262,290,783.59 | -19,584,781.01 |
| 총수익률(%) | 40.94 | 31.15 | -9.79 |
| CAGR(%) | 8.11 | 6.36 | -1.76 |
| MDD(%) | -36.87 | -18.75 | 18.11 |
| NAV coverage(%) | 99.82 | 99.08 | -0.74 |
| NAV 결측일 | 2.00 | 10.00 | 8.00 |
| 지원일 청산 | 0.00 | 0.00 | 0.00 |
| 진입 시도 | 1,704.00 | 208.00 | -1,496.00 |
| 현금 부족 skip | 1,336.00 | 20.00 | -1,316.00 |
| 현금 부족률(%) | 78.40 | 9.62 | -68.79 |
| 실매수 | 368.00 | 188.00 | -180.00 |
| 실현 청산 | 323.00 | 156.00 | -167.00 |
| cutoff 미청산 | 45.00 | 32.00 | -13.00 |
| 실현 거래 | 323.00 | 156.00 | -167.00 |
| 승률(%) | 24.46 | 28.85 | 4.39 |
| 평균 순수익률(%) | 1.69 | 3.23 | 1.55 |
| 중앙 순수익률(%) | -15.78 | -15.48 | 0.30 |
| 평균 보유 거래일 | 82.89 | 101.13 | 18.24 |
| 중앙 보유 거래일 | 54.00 | 64.50 | 10.50 |
| 최대 거래수익률(%) | 434.05 | 217.63 | -216.42 |
| 최대 거래손실률(%) | -35.80 | -44.39 | -8.60 |
| +20% 이상 거래 | 61.00 | 33.00 | -28.00 |
| +50% 이상 거래 | 35.00 | 19.00 | -16.00 |
| +100% 이상 거래 | 11.00 | 6.00 | -5.00 |
| -10% 이하 거래 | 237.00 | 109.00 | -128.00 |
| -15% 이하 거래 | 209.00 | 92.00 | -117.00 |
| -20% 이하 거래 | 19.00 | 8.00 | -11.00 |
| -30% 이하 거래 | 5.00 | 4.00 | -1.00 |
| Loss Guard 매수 | 229.00 | 105.00 | -124.00 |
| PROGRESSED 매수 | 111.00 | 60.00 | -51.00 |
| 평균 동시보유 | 38.70 | 21.64 | -17.06 |
| 최대 동시보유 | 47.00 | 39.00 | -8.00 |
| 평균 자본 활용률(%) | 91.39 | 55.75 | -35.64 |
| 최대 자본 활용률(%) | 100.00 | 98.82 | -1.18 |
| 평균 현금비중(%) | 8.61 | 44.25 | 35.64 |
| 회전율 배수 | 17.34 | 8.64 | -8.70 |
| 수수료(원) | 520,240.62 | 259,276.94 | -260,963.68 |
| 슬리피지(원) | 3,468,078.78 | 1,728,382.47 | -1,739,696.31 |
| 최대 티커 양의 손익 점유율(%) | 9.61 | 10.16 | 0.55 |

### MDD 및 청산 사유

- CONTROL: OBSERVED -36.87% (peak 2023-04-07, trough 2023-10-31, recovery 미회복).
- 후보: OBSERVED -18.75% (peak 2021-08-09, trough 2022-10-13, recovery 2023-07-25); CONTROL−후보 -18.11%p.
- CONTROL 청산 사유 {"EXIT3_PROGRESSED_TO_EARLY_TREND": 1, "EXIT3_PROGRESSED_TO_TRANSITION": 5, "EXIT3_PROGRESSED_TO_WEAK": 3, "EXIT4_SCORE_DRAWDOWN_GE_15": 85, "LOSS_GUARD_CLOSE_LE_NEG_15": 229}.
- 후보 청산 사유 {"EXIT3_PROGRESSED_TO_TRANSITION": 4, "EXIT3_PROGRESSED_TO_WEAK": 2, "EXIT4_SCORE_DRAWDOWN_GE_15": 45, "LOSS_GUARD_CLOSE_LE_NEG_15": 105}.
- 최대 티커 손익 점유율: CONTROL 9.61% (101670); 후보 10.16% (032190).
- 연도/시장별 실현손익은 control_annual_market_diagnostics.csv와 alignment_mcap_500b_annual_market_diagnostics.csv에 저장했어.

## 무결성 및 판정 범위

- 신호 원장 exact PIT/MA60/시총 검사: {"duplicate_exact_pit_signal_audit_keys": 0, "control_trade_without_one_active_common_identity_audit": 0, "candidate_trade_alignment_mcap_or_prior_60m_mismatch": [], "control_trade_set_matches_pit_pass_audit": true, "candidate_trade_set_matches_candidate_pass_audit": true, "excluded_identity_trade_leakage": [], "control_missing_examples": []}.
- NAV는 1,082일 기준 CONTROL 99.82% / 후보 99.08%; 최장 연속 결측 1 / 1일.
- cutoff 2025-05-30 NAV는 CONTROL 281,875,564.60원 / 후보 262,290,783.59원으로 확인됐어.
- 미해결 mark는 CONTROL 2건, 후보 10건이야. 원인/증거: `{"CONTROL": {"missing_mark_rows": 2, "unresolved_nav_dates": ["2022-01-20", "2022-01-28"], "by_ticker": {"068240": {"count": 2, "dates": ["2022-01-20", "2022-01-28"], "reasons": ["UNRESOLVED_DAILY_MARK"], "evidence_states": ["RAW_ROW_NOT_PLACEHOLDER"]}}}, "ALIGNMENT_MCAP_500B": {"missing_mark_rows": 10, "unresolved_nav_dates": ["2022-01-20", "2022-01-28", "2022-02-25", "2022-05-13", "2023-04-25", "2023-06-28", "2024-02-16", "2024-06-27", "2024-10-31", "2024-11-25"], "by_ticker": {"003690": {"count": 4, "dates": ["2023-04-25", "2023-06-28", "2024-02-16", "2024-06-27"], "reasons": ["UNRESOLVED_DAILY_MARK"], "evidence_states": ["RAW_ROW_NOT_PLACEHOLDER"]}, "068240": {"count": 2, "dates": ["2022-01-20", "2022-01-28"], "reasons": ["UNRESOLVED_DAILY_MARK"], "evidence_states": ["RAW_ROW_NOT_PLACEHOLDER"]}, "085660": {"count": 4, "dates": ["2022-02-25", "2022-05-13", "2024-10-31", "2024-11-25"], "reasons": ["UNRESOLVED_DAILY_MARK"], "evidence_states": ["RAW_ROW_NOT_PLACEHOLDER"]}}}}`. RAW_ROW_NOT_PLACEHOLDER인 해당 세션은 보간·carry하지 않아 일별 NAV를 UNRESOLVED로 남겼어. cutoff NAV는 정상 확인됐고 양쪽 coverage가 90% 이상이라 공식 E는 OBSERVED, MDD는 관측치로 보고 이 mark 공백은 MINOR 진단으로 분류했어.
- 가격 해시/PIT/현금·비용 독립 검산 결과는 integrity_audit.json, 029960·128940·003690 및 380440 노출 감사는 identity_exposure_audit.csv.
- 현금 부족 skip은 진단값이지 공식 게이트가 아니야. cutoff 미청산은 cutoff 종가 평가만 하며 가상 매도비용을 부과하지 않았어.
- 단일 P2-1 결과야. 5기간 채택 NOT_FINAL_5WINDOW, 후보 채택과 baseline 승격 NOT_EVALUATED, 기본 전략 PATTERN_A_FAST_FINAL_STRATEGY_V02 유지.

## 주요 산출물

plan.md, execution_contract.json, preflight.json, active_pit_missing_sessions.csv, source_manifest.json, sample_benchmark.json, full_run_execution.json, 그룹별 trades/events/cash/NAV/valuation/missing marks, metrics_comparison.csv, gate_results.json, integrity_audit.json, artifact_hashes.json.
