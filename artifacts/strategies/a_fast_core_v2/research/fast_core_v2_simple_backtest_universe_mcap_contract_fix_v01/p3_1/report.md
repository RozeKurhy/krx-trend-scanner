# FAST Core V2 P3-1 단순 백테스트 universe / 시총 계약 수정

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 필수 무결성 검증 오류 없음 |
| MAJOR | 0 | 결과 범위 안에서 확인된 중대 이슈 없음 |
| MINOR | 0 | simple trade-level 범위 밖인 포트폴리오 MDD는 미평가 항목으로 분류하지 않음 |

- 최종 판정: FAST_CORE_V2_SIMPLE_BACKTEST_UNIVERSE_MCAP_CONTRACT_FIX_V01_P3_1_PASS
- 실제 거래 기간: 2022-01-03~2025-05-30. Execution support: 2025-06-02. Cutoff 이후 신규 진입은 허용하지 않았어.
- 수정 전 계약은 승인되지 않은 MKTCAP ≥ 1조 진입 게이트와 2026-09-21 current survivor 교집합을 historical P3-1 eligibility에 적용했어. 이전 결과는 `UNAUTHORIZED_MCAP1T_AND_CURRENT_SURVIVOR_FILTERED_RESULT`로 분류했어.
- 수정 후 계약은 `MARKET_CAP_FILTER=NONE`이야. Frozen historical PIT의 P3-1 COMMON 2,626 identity key에서 current permanent exclusion registry의 exact (ticker, ISU) 181쌍만 적용해 2,467 key를 만들었어.
- 기존 runner의 P3-1 universe는 2,336개였어. 수정 후 historical COMMON 2,626개에서 영구 제외만 적용해 2,467개를 사용했고, 기존 survivor 교집합 때문에 빠졌던 131개 identity는 다시 포함됐어. 수정 run의 survivor 기반 제외는 0개야.
- 공통 universe는 identity key 2,467개, COMMON segment 2,467개, ticker 2,460개야. 제외 키에 market과 ticker-only matching을 사용하지 않았어.
- CONTROL, MA60 fail-closed, Bullish Alignment는 같은 corrected historical universe, PIT, calendar, lifecycle, cutoff, Repository V2 가격 및 비용 계약을 사용했어.
- 매수/매도 수수료 각 0.015%, 매수/매도 슬리피지 각 0.10%, 거래세 제외. 수익률은 net 기준이야.

## 전략별 핵심 지표

| 전략 | 거래 | 실현 | cutoff 미종료 | 미종료율 % | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 보유 평균 일 | 보유 중앙 일 | 최대 수익 % | 최대 손실 % | Loss Guard 건수/율 | PROGRESSED 건수/율 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 1097 | 894 | 203 | 18.51 | 17.45 | 28.81 | 0.34 | -15.50 | -3.70 | -15.90 | 96.68 | 51.00 | 434.05 | -65.10 | 713 (65.00%) | 229 (20.88%) |
| MA60 | 870 | 716 | 154 | 17.70 | 18.58 | 28.62 | 0.32 | -15.49 | -3.61 | -15.85 | 96.22 | 50.00 | 434.05 | -65.10 | 560 (64.37%) | 198 (22.76%) |
| ALIGNMENT | 482 | 416 | 66 | 13.69 | 21.15 | 29.25 | 1.19 | -15.50 | -1.28 | -15.73 | 99.73 | 57.50 | 434.05 | -65.10 | 312 (64.73%) | 125 (25.93%) |

## 대형 승리·손실 분포

| 전략 | 구간 | 건수 | 전체 거래 대비 % |
|---|---|---:|---:|
| CONTROL | >=+20% | 199 | 18.14 |
| CONTROL | >=+50% | 99 | 9.02 |
| CONTROL | >=+100% | 25 | 2.28 |
| CONTROL | <=-10% | 751 | 68.46 |
| CONTROL | <=-15% | 651 | 59.34 |
| CONTROL | <=-20% | 80 | 7.29 |
| CONTROL | <=-30% | 20 | 1.82 |
| MA60 | >=+20% | 162 | 18.62 |
| MA60 | >=+50% | 76 | 8.74 |
| MA60 | >=+100% | 21 | 2.41 |
| MA60 | <=-10% | 593 | 68.16 |
| MA60 | <=-15% | 516 | 59.31 |
| MA60 | <=-20% | 65 | 7.47 |
| MA60 | <=-30% | 16 | 1.84 |
| ALIGNMENT | >=+20% | 96 | 19.92 |
| ALIGNMENT | >=+50% | 45 | 9.34 |
| ALIGNMENT | >=+100% | 14 | 2.90 |
| ALIGNMENT | <=-10% | 331 | 68.67 |
| ALIGNMENT | <=-15% | 288 | 59.75 |
| ALIGNMENT | <=-20% | 38 | 7.88 |
| ALIGNMENT | <=-30% | 8 | 1.66 |

## CONTROL 대비 변화

| 후보 | 거래수 Δ | 거래 감소 % | 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 보유 평균/중앙 Δ 일 | +20/+50/+100% 비율 Δ %p | -10/-15/-20/-30% 비율 Δ %p | Loss Guard 건수/율 Δ | PROGRESSED 건수/율 Δ | cutoff-open 건수/율 Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MA60 | -227 | 20.69 | 1.13 | -0.19 | -0.03/0.01 | 0.08/0.06 | -0.47/-1.00 | 0.48/-0.29/0.13 | -0.30/-0.03/0.18/0.02 | -153 / -0.63%p | -31 / 1.88%p | -49 / -0.80%p |
| ALIGNMENT | -615 | 56.06 | 3.70 | 0.45 | 0.85/0.00 | 2.42/0.17 | 3.04/6.50 | 1.78/0.31/0.63 | 0.21/0.41/0.59/-0.16 | -401 / -0.27%p | -104 / 5.06%p | -137 / -4.81%p |

## 이전 오염 결과와 비교

이전 성과 파일은 replay 입력에 사용하지 않았어. 아래 비교표만 만들기 위해 읽었고, 이전 결과는 official simple baseline으로 쓰지 않아.

| 전략 | 이전 거래 | 수정 거래 | 거래 Δ | 이전 terminal 평균 % | 수정 terminal 평균 % | 평균 Δ %p | 이전 terminal 중앙 % | 수정 terminal 중앙 % | 중앙 Δ %p | 승률 Δ %p | 평균 보유기간 Δ 일 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 247 | 1097 | 850 | 5.66 | 0.34 | -5.32 | -15.03 | -15.50 | -0.47 | -6.11 | -38.17 |
| MA60 | 207 | 870 | 663 | 6.01 | 0.32 | -5.70 | -14.93 | -15.49 | -0.56 | -6.27 | -31.25 |
| ALIGNMENT | 119 | 482 | 363 | 9.15 | 1.19 | -7.96 | -14.31 | -15.50 | -1.19 | -10.03 | -32.53 |

## Exit reason 분포

| 전략 | exit reason | 건수 |
|---|---|---:|
| CONTROL | LOSS_GUARD_CLOSE_LE_NEG_15 | 713 |
| CONTROL | EXIT4_SCORE_DRAWDOWN_GE_15 | 157 |
| CONTROL | NO_PROGRESSED_BEFORE_CUTOFF | 155 |
| CONTROL | NO_EXIT_BEFORE_CUTOFF | 48 |
| CONTROL | EXIT3_PROGRESSED_TO_TRANSITION | 13 |
| CONTROL | EXIT3_PROGRESSED_TO_WEAK | 10 |
| CONTROL | EXIT3_PROGRESSED_TO_EARLY_TREND | 1 |
| MA60 | LOSS_GUARD_CLOSE_LE_NEG_15 | 560 |
| MA60 | EXIT4_SCORE_DRAWDOWN_GE_15 | 133 |
| MA60 | NO_PROGRESSED_BEFORE_CUTOFF | 112 |
| MA60 | NO_EXIT_BEFORE_CUTOFF | 42 |
| MA60 | EXIT3_PROGRESSED_TO_TRANSITION | 12 |
| MA60 | EXIT3_PROGRESSED_TO_WEAK | 10 |
| MA60 | EXIT3_PROGRESSED_TO_EARLY_TREND | 1 |
| ALIGNMENT | LOSS_GUARD_CLOSE_LE_NEG_15 | 312 |
| ALIGNMENT | EXIT4_SCORE_DRAWDOWN_GE_15 | 86 |
| ALIGNMENT | NO_PROGRESSED_BEFORE_CUTOFF | 45 |
| ALIGNMENT | NO_EXIT_BEFORE_CUTOFF | 21 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_TRANSITION | 10 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_WEAK | 8 |

## PROGRESSED 판정

PROGRESSED는 raw 날짜 존재만으로 세지 않았어. 실현 거래는 entry execution부터 exit signal까지, cutoff 미종료 거래는 entry execution부터 cutoff까지, lifecycle 정산은 settlement date까지 대조했어. Trade별 근거는 p3_1_progressed_reconciliation_audit.csv에 있어.

## 실행·무결성·provenance

- 전략별 worker는 10개, worker 오류 합계 0건, 네트워크 호출 0회.
- 전략별 처리 ticker 2,460개; 공통 PIT identity key 2,467개.
- Accepted signal↔trade parity True; duplicate trade key 0; cutoff 이후 신규 진입 0.
- 시총 진입 필터 적용 False; 시총 기반 reject 0; current survivor 기반 제외 0.
- Permanent exclusion leakage: trade 0, signal audit 0. 등록 exact pair 181, 중복 pair 0, residue 0.
- MA60 공식·fail-closed True; Alignment signal_day_close > MA20 > MA60·fail-closed True; net terminal 재계산 불일치 0.
- MA60/Alignment 공식과 lifecycle causal fix source hash가 이전 결과와 같아: True (core_strategy_runner, canonical_strategy, ma60_helper, alignment_helper).
- Frozen PIT SHA-256 6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1; calendar cf9560da17674c866c57906b4b8e21ce956a0e7a0a9a3ccd1779d1a83a7111c2; exclusion registry 858ec93e656bea5aa9ad036f7bd8e129253b4f682d062e7fb9350ad5eea1cffa.
- Current survivor 비교 전용 SHA-256 313bca3d5dbc28672cb505c18b61af40a9b4b827c11af56b30f45160cdba1506; 이전 metrics 비교 전용 SHA-256 278d3e4e441e594bb028f281d2f840c3a01ddf550c83015790e0d60c8726618d.
- 이 문서는 P3-1 단일 기간 simple trade-level 결과야. P2-1/P2-2/P3-2/P1/5-window synthesis는 실행하지 않았어. 포트폴리오 MDD와 공식 채택 판정은 포함하지 않아.

## 산출물

- artifacts/strategies/a_fast_core_v2/research/fast_core_v2_simple_backtest_universe_mcap_contract_fix_v01/p3_1/에 preflight, identity authority audit, 세 trade ledger, signal/no-cap contract/price audit, execution audit, PROGRESSED reconciliation, metrics, CONTROL delta, previous-result comparison, provenance, artifact manifest가 있어.
- 결과 토큰: FAST_CORE_V2_SIMPLE_BACKTEST_UNIVERSE_MCAP_CONTRACT_FIX_V01_P3_1_PASS
