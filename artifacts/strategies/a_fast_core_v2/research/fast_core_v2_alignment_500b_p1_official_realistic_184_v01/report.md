# FAST Core V2 Alignment + 500B — P1 공식 실전형 결과

**P1 판정: CHECK_REQUIRED** · CRITICAL 0종 / MAJOR 2종 / MINOR 2종.

## 독립 이슈 유형 수

| 심각도 | 유형 수 | 유형 |
|---|---:|---|
| CRITICAL | 0 | 없음 |
| MAJOR | 2 | CUTOFF_NAV_UNRESOLVED, NAV_MARK_UNRESOLVED |
| MINOR | 2 | CASH_SHORTAGE_SKIP_DIAGNOSTIC, CUTOFF_OPEN_POSITIONS_MARKED_WITHOUT_HYPOTHETICAL_EXIT_COST |

## 실행 범위와 입력 검증

- 실제 평가 구간 2014-01-02~2026-08-31, 3,107 exact KRX 세션. 2026-09-01은 cutoff 이전 신호로 발생한 기존 보유분의 청산만 지원하며 신규 매수와 P1 cutoff NAV/성과에는 포함하지 않았어.
- 종목 2,709/2,709, 신호 worker 10개, worker 오류 0건.
- 표본 검증 PASS / 전수 허가 True; 전수 실제 소요 0.429시간 (표본 추정 0.9964시간). 재생 authorization guard를 통과했어.
- P1 공통 PIT interval 2,911; 영구 제외 184쌍 후 2,726 interval / 2,709 ticker. Exact pair SHA-256 `5d3bd9a1e27e7e558235f0fba211263cdc90eb0b477978c8338eb019b1a6ec2e`.
- 입력 원천 범위: PIT identity 2010-01-04~2026-10-08; adjusted 파일 2010-01-04~2026-10-08 (2,709 files); KRX raw 2014-01-02~2026-09-01 (6,216 partitions).
- MA60 예열: 첫 P1 신호 전 완료월 48/60개, 필요 구간 2009-01~2013-12, 달력상 첫 가능 신호월 2015-01. 부족 신호만 REJECT_MA_UNAVAILABLE 처리했어.
- source manifest 재검증: PASS (8,996/8,996; runtime 71, adjusted 2,709, raw partitions 6,216). 신호일 raw partition 1,198건은 frozen manifest와 해시 일치 True.
- signal filter 상태: {"PASS": 514, "REJECT_ALIGNMENT": 10744, "REJECT_MA_UNAVAILABLE": 5026, "REJECT_MCAP_BELOW_500B": 5378}.
- candidate_status PASS 514건 중 2건은 candidate scan에서 발생하지 않은 control-only 감사행이야. 실제 candidate scan PASS 512건과 candidate 거래 원장이 일치해.
- exact market-cap unresolved 0; Repository V2 미가용 종목 0; projection mismatch 종목 0. P1 입력/전략 기준은 동결 V2와 동일하고 평가 기간·2억원 독립 시작 자금만 P1 계약으로 확정했어; 후보에는 지시된 MA 정배열과 당일 시총 조건만 추가했어.

## 공식 A~E

| 게이트 | CONTROL | ALIGNMENT_MCAP_500B |
|---|---|---|
| A 무결성 | PASS | PASS |
| B 비용 | PASS | PASS |
| C 수익성 | CHECK_REQUIRED | PASS |
| D MDD | CHECK_REQUIRED | CHECK_REQUIRED |
| E 유효성 | CHECK_REQUIRED | OBSERVED |

## 포트폴리오 비교

거래 수익률과 승률의 분모는 cutoff 이전 실제 매수 후 실제 청산한 거래야. 순수익률은 양쪽 비용·슬리피지를 포함하고 보유 거래일은 진입/청산 체결 세션을 포함해 계산했어.

| 지표 | CONTROL | 후보 | 후보−CONTROL |
|---|---:|---:|---:|
| 종료 자산(원) | — | 415,303,249.76 | — |
| 총수익률(%) | — | 107.65 | — |
| CAGR(%) | — | 5.94 | — |
| MDD(%) | — | -32.58 | — |
| NAV coverage(%) | 82.78 | 93.27 | 10.49 |
| NAV 결측일 | 535.00 | 209.00 | -326.00 |
| 지원일 청산 | 0.00 | 1.00 | 1.00 |
| 진입 시도 | 4,795.00 | 512.00 | -4,283.00 |
| 현금 부족 skip | 4,046.00 | 61.00 | -3,985.00 |
| 현금 부족률(%) | 84.38 | 11.91 | -72.47 |
| 실매수 | 749.00 | 451.00 | -298.00 |
| 실현 청산 | 697.00 | 428.00 | -269.00 |
| cutoff 미청산 | 52.00 | 23.00 | -29.00 |
| 실현 거래 | 697.00 | 428.00 | -269.00 |
| 승률(%) | 23.39 | 31.54 | 8.16 |
| 평균 순수익률(%) | 3.34 | 9.20 | 5.85 |
| 중앙 순수익률(%) | -15.64 | -15.29 | 0.34 |
| 평균 보유 거래일 | 153.01 | 145.81 | -7.20 |
| 중앙 보유 거래일 | 71.00 | 93.00 | 22.00 |
| 최대 거래수익률(%) | 434.05 | 249.20 | -184.85 |
| 최대 거래손실률(%) | -39.12 | -44.39 | -5.27 |
| +20% 이상 거래 | 136.00 | 110.00 | -26.00 |
| +50% 이상 거래 | 90.00 | 70.00 | -20.00 |
| +100% 이상 거래 | 27.00 | 28.00 | 1.00 |
| -10% 이하 거래 | 513.00 | 284.00 | -229.00 |
| -15% 이하 거래 | 434.00 | 236.00 | -198.00 |
| -20% 이하 거래 | 43.00 | 26.00 | -17.00 |
| -30% 이하 거래 | 6.00 | 5.00 | -1.00 |
| Loss Guard 매수 | 497.00 | 276.00 | -221.00 |
| PROGRESSED 매수 | 224.00 | 167.00 | -57.00 |
| 평균 동시보유 | 43.99 | 24.03 | -19.96 |
| 최대 동시보유 | 65.00 | 55.00 | -10.00 |
| 평균 자본 활용률(%) | 94.63 | 57.77 | -36.85 |
| 최대 자본 활용률(%) | 100.00 | 99.95 | -0.05 |
| 평균 현금비중(%) | 5.37 | 42.23 | 36.85 |
| 회전율 배수 | 36.55 | 22.71 | -13.84 |
| 수수료(원) | 1,096,478.23 | 681,300.68 | -415,177.55 |
| 슬리피지(원) | 7,309,721.27 | 4,542,093.56 | -2,767,627.71 |
| 최대 티커 양의 손익 점유율(%) | 4.22 | 3.27 | -0.95 |

### MDD 및 청산 사유

- CONTROL: CHECK_REQUIRED —% (peak 2015-07-20, trough 2020-03-19, recovery 2023-03-29).
- 후보: OBSERVED -32.58% (peak 2018-01-29, trough 2020-03-19, recovery 2024-03-21); CONTROL−후보 —%p.
- CONTROL peak/trough/recovery dates are diagnostics from available NAV dates only; coverage is below 90%, so no official CONTROL MDD value is reported.
- CONTROL 청산 사유 {"EXIT3_PROGRESSED_TO_BASE": 2, "EXIT3_PROGRESSED_TO_EARLY_TREND": 4, "EXIT3_PROGRESSED_TO_TRANSITION": 14, "EXIT3_PROGRESSED_TO_WEAK": 10, "EXIT4_SCORE_DRAWDOWN_GE_15": 170, "LOSS_GUARD_CLOSE_LE_NEG_15": 497}.
- 후보 청산 사유 {"EXIT3_PROGRESSED_TO_BASE": 1, "EXIT3_PROGRESSED_TO_EARLY_TREND": 5, "EXIT3_PROGRESSED_TO_TRANSITION": 19, "EXIT3_PROGRESSED_TO_WEAK": 4, "EXIT4_SCORE_DRAWDOWN_GE_15": 123, "LOSS_GUARD_CLOSE_LE_NEG_15": 276}.
- 최대 티커 손익 점유율: CONTROL 4.22% (101670); 후보 3.27% (025980).
- 연도/시장별 실현손익은 control_annual_market_diagnostics.csv와 alignment_mcap_500b_annual_market_diagnostics.csv에 저장했어.

## 무결성 및 판정 범위

- 신호 원장 exact PIT/MA60/시총 검사: {"duplicate_exact_pit_signal_audit_keys": 0, "control_trade_without_one_active_common_identity_audit": 0, "candidate_trade_alignment_mcap_or_prior_60m_mismatch": [], "control_trade_set_matches_pit_pass_audit": true, "candidate_trade_set_matches_candidate_pass_audit": true, "excluded_identity_trade_leakage": [], "control_missing_examples": []}.
- NAV는 3,107일 기준 CONTROL 82.78% / 후보 93.27%; 최장 연속 결측 297 / 4일.
- 2026-08-31 cutoff NAV 미확정 (CONTROL —원 / 후보 415,303,249.76원); C/E는 CHECK_REQUIRED.
- 미해결 mark는 CONTROL 556건, 후보 238건이야. 원인/날짜/종목별 근거는 integrity_audit.json의 nav_mark_resolution에 기록했어. 허용된 거래정지 placeholder 외 정상 세션 결측은 보간·carry하지 않고 해당 날짜 전체 NAV를 UNRESOLVED 처리했어. 분류: CHECK_REQUIRED.
- CONTROL 기말 NAV를 막은 보유는 029960/KR7029960002(KOSDAQ, 매수 체결 2024-11-18)야. exact ticker row가 297개 mark일에 없어 기간은 2025-06-16~2026-08-31이고, 임의 정산은 적용하지 않았어.
- 가격 해시/PIT/현금·비용 독립 검산 결과는 integrity_audit.json, 029960·128940·003690 및 380440 노출 감사는 identity_exposure_audit.csv.
- 현금 부족 skip은 진단값이지 공식 게이트가 아니야. cutoff 미청산은 cutoff 종가 평가만 하며 가상 매도비용을 부과하지 않았어.
- 단일 P1 결과야. 5기간 채택, 후보 채택 및 baseline 승격은 NOT_EVALUATED이고 기본 전략 PATTERN_A_FAST_FINAL_STRATEGY_V02를 유지해.

## 주요 산출물

plan.md, execution_contract.json, preflight.json, active_pit_missing_sessions.csv, source_manifest.json, sample_benchmark.json, full_run_execution.json, 그룹별 trades/events/cash/NAV/valuation/missing marks, metrics_comparison.csv, candidate_signal_filter_by_year.csv, gate_results.json, integrity_audit.json, artifact_hashes.json.

### 연도별 후보 진입 필터 진단

| 연도 | 평가 신호 | MA60 미가용 | 시총 미해결 | 시총 500B 미만 | 정배열 탈락 | 통과 |
|---:|---:|---:|---:|---:|---:|---:|
| 2014 | 3,250 | 3,250 | 0 | 0 | 0 | 0 |
| 2015 | 1,980 | 286 | 0 | 849 | 803 | 42 |
| 2016 | 1,546 | 133 | 0 | 782 | 604 | 27 |
| 2017 | 1,769 | 80 | 0 | 795 | 847 | 47 |
| 2018 | 1,204 | 140 | 0 | 472 | 548 | 44 |
| 2019 | 1,496 | 216 | 0 | 455 | 786 | 39 |
| 2020 | 1,385 | 216 | 0 | 223 | 908 | 38 |
| 2021 | 2,286 | 190 | 0 | 307 | 1,765 | 24 |
| 2022 | 744 | 73 | 0 | 224 | 408 | 39 |
| 2023 | 1,473 | 144 | 0 | 506 | 756 | 67 |
| 2024 | 1,189 | 101 | 0 | 272 | 765 | 51 |
| 2025 | 2,292 | 147 | 0 | 368 | 1,703 | 74 |
| 2026 | 1,048 | 50 | 0 | 125 | 851 | 22 |

- P1 시작 당시 MA60 선행 이력은 48/60개월이라 2014년의 후보 신호만 데이터 규칙대로 미가용 처리했어. 달력상 60개월이 처음 완성되는 신호월은 2015-01이야. 전체 P1 평가 시작일은 2014-01-02로 유지했어.
- 기존 공식 P2/P3 실행 계약 대비 P1 차이는 평가 기간/지원일과 P1 초기 2억원 독립 자금 경로야. V2 상태 전이·손절/청산·비용·T+1·NAV 원칙은 고정하고, 후보에는 같은 alignment 및 정확 신호일 시총 조건만 적용했어. 선행 산출물 해시 검증 6/6 PASS.
