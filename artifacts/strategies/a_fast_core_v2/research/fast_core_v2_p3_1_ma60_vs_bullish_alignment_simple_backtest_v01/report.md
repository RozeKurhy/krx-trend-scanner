# FAST Core V2 P3-1 MA60 vs Bullish Alignment 단순 백테스트

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 필수 무결성 검증 오류 없음 |
| MAJOR | 0 | 결과 범위 안에서 확인된 중대 이슈 없음 |
| MINOR | 1 | 거래 단위 결과이며 포트폴리오 MDD는 계산하지 않음 |

- 최종 판정: FAST_CORE_V2_P3_1_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01_PASS
- 실제 거래 기간: 2022-01-03~2025-05-30. Execution support: 2025-06-02. Cutoff 이후 신규 진입은 허용하지 않았어.
- Frozen survivor roster 2,539개에서 current permanent exclusion authority 181 exact pair를 적용했어. Roster와 겹친 115개를 전략 재생 전에 제외해 공통 eligible roster 2,424개를 만들었어.
- P3-1 PIT 범위는 identity key 2,336개, segment 2,336개, ticker 2,336개야. Exact (ticker, ISU) 매칭을 사용했고 ticker-only 매칭은 사용하지 않았어.
- CONTROL, MA60 fail-closed, Bullish Alignment는 같은 filtered roster, PIT, calendar, lifecycle, cutoff, Repository V2 가격 및 exact-date MKTCAP 계약을 사용했어.
- 매수/매도 수수료 각 0.015%, 매수/매도 슬리피지 각 0.10%, 거래세 제외. 수익률은 net 기준이야.

## 전략별 핵심 지표

| 전략 | 거래 | 실현 | cutoff 미종료 | 미종료율 % | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 보유 평균 일 | 보유 중앙 일 | 최대 수익 % | 최대 손실 % | Loss Guard 건수/율 | PROGRESSED 건수/율 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 247 | 191 | 56 | 22.67 | 23.56 | 38.87 | 5.66 | -15.03 | -1.07 | -15.63 | 134.86 | 79.00 | 190.41 | -33.62 | 140 (56.68%) | 67 (27.13%) |
| MA60 | 207 | 161 | 46 | 22.22 | 24.84 | 38.65 | 6.01 | -14.93 | -0.27 | -15.55 | 127.47 | 71.00 | 190.41 | -33.62 | 115 (55.56%) | 61 (29.47%) |
| ALIGNMENT | 119 | 93 | 26 | 21.85 | 31.18 | 45.38 | 9.15 | -14.31 | 3.97 | -15.09 | 132.25 | 81.00 | 190.41 | -33.62 | 61 (51.26%) | 39 (32.77%) |

## 대형 승리·손실 분포

| 전략 | 구간 | 건수 | 전체 거래 대비 % |
|---|---|---:|---:|
| CONTROL | >=+20% | 64 | 25.91 |
| CONTROL | >=+50% | 31 | 12.55 |
| CONTROL | >=+100% | 5 | 2.02 |
| CONTROL | <=-10% | 145 | 58.70 |
| CONTROL | <=-15% | 124 | 50.20 |
| CONTROL | <=-20% | 14 | 5.67 |
| CONTROL | <=-30% | 3 | 1.21 |
| MA60 | >=+20% | 59 | 28.50 |
| MA60 | >=+50% | 25 | 12.08 |
| MA60 | >=+100% | 5 | 2.42 |
| MA60 | <=-10% | 120 | 57.97 |
| MA60 | <=-15% | 101 | 48.79 |
| MA60 | <=-20% | 12 | 5.80 |
| MA60 | <=-30% | 3 | 1.45 |
| ALIGNMENT | >=+20% | 39 | 32.77 |
| ALIGNMENT | >=+50% | 15 | 12.61 |
| ALIGNMENT | >=+100% | 4 | 3.36 |
| ALIGNMENT | <=-10% | 64 | 53.78 |
| ALIGNMENT | <=-15% | 52 | 43.70 |
| ALIGNMENT | <=-20% | 8 | 6.72 |
| ALIGNMENT | <=-30% | 2 | 1.68 |

## CONTROL 대비 변화

| 후보 | 거래수 Δ | 거래 감소 % | 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 보유 평균/중앙 Δ 일 | +20/+50/+100% 비율 Δ %p | -10/-15/-20/-30% 비율 Δ %p | Loss Guard 건수/율 Δ | PROGRESSED 건수/율 Δ | cutoff-open 건수/율 Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MA60 | -40 | 16.19 | 1.28 | -0.22 | 0.35/0.10 | 0.79/0.09 | -7.39/-8.00 | 2.59/-0.47/0.39 | -0.73/-1.41/0.13/0.23 | -25 / -1.12%p | -6 / 2.34%p | -10 / -0.45%p |
| ALIGNMENT | -128 | 51.82 | 7.62 | 6.51 | 3.49/0.72 | 5.04/0.54 | -2.61/2.00 | 6.86/0.05/1.34 | -4.92/-6.50/1.05/0.47 | -79 / -5.42%p | -28 / 5.65%p | -30 / -0.82%p |

## Exit reason 분포

| 전략 | exit reason | 건수 |
|---|---|---:|
| CONTROL | LOSS_GUARD_CLOSE_LE_NEG_15 | 140 |
| CONTROL | EXIT4_SCORE_DRAWDOWN_GE_15 | 47 |
| CONTROL | NO_PROGRESSED_BEFORE_CUTOFF | 40 |
| CONTROL | NO_EXIT_BEFORE_CUTOFF | 16 |
| CONTROL | EXIT3_PROGRESSED_TO_TRANSITION | 3 |
| CONTROL | EXIT3_PROGRESSED_TO_WEAK | 1 |
| MA60 | LOSS_GUARD_CLOSE_LE_NEG_15 | 115 |
| MA60 | EXIT4_SCORE_DRAWDOWN_GE_15 | 43 |
| MA60 | NO_PROGRESSED_BEFORE_CUTOFF | 31 |
| MA60 | NO_EXIT_BEFORE_CUTOFF | 15 |
| MA60 | EXIT3_PROGRESSED_TO_TRANSITION | 2 |
| MA60 | EXIT3_PROGRESSED_TO_WEAK | 1 |
| ALIGNMENT | LOSS_GUARD_CLOSE_LE_NEG_15 | 61 |
| ALIGNMENT | EXIT4_SCORE_DRAWDOWN_GE_15 | 30 |
| ALIGNMENT | NO_PROGRESSED_BEFORE_CUTOFF | 19 |
| ALIGNMENT | NO_EXIT_BEFORE_CUTOFF | 7 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_TRANSITION | 1 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_WEAK | 1 |

## PROGRESSED 판정

PROGRESSED는 raw 날짜 존재만으로 세지 않았어. 실현 거래는 entry execution부터 exit signal까지, cutoff 미종료 거래는 entry execution부터 cutoff까지, lifecycle 정산은 settlement date까지 대조했어. Trade별 근거는 p3_1_progressed_reconciliation_audit.csv에 있어.

## 실행·무결성·provenance

- 전략별 worker는 10개, worker 오류 합계 0건, 네트워크 호출 0회.
- 전략별 처리 ticker 2,336개; 공통 PIT identity key 2,336개.
- Accepted signal↔trade parity True; duplicate trade key 0; cutoff 이후 신규 진입 0.
- 정확한 MKTCAP audit unresolved 0; CONTROL trade 진입 MKTCAP PASS True.
- Permanent exclusion leakage: trade 0, signal audit 0, MKTCAP audit 0.
- MA60 공식·fail-closed True; Alignment signal_day_close > MA20 > MA60·fail-closed True; net terminal 재계산 불일치 0.
- Frozen PIT SHA-256 6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1; calendar cf9560da17674c866c57906b4b8e21ce956a0e7a0a9a3ccd1779d1a83a7111c2; survivor roster 313bca3d5dbc28672cb505c18b61af40a9b4b827c11af56b30f45160cdba1506; exclusion registry 858ec93e656bea5aa9ad036f7bd8e129253b4f682d062e7fb9350ad5eea1cffa.
- 이 문서는 P3-1 한 기간 안의 세 전략 비교만 담아. 다른 기간 성과와 교차 기간 비교, 포트폴리오 MDD, 공식 채택 판정은 포함하지 않아.

## 산출물

- artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_1_ma60_vs_bullish_alignment_simple_backtest_v01/에 preflight, identity authority audit, 세 trade ledger, signal/MKTCAP/price audit, execution audit, PROGRESSED reconciliation, metrics, CONTROL delta, provenance, artifact manifest가 있어.
- 결과 토큰: FAST_CORE_V2_P3_1_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01_PASS
