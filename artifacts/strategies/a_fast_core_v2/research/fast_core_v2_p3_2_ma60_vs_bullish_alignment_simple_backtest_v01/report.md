# FAST Core V2 P3-2 MA60 vs Bullish Alignment 단순 백테스트

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 필수 무결성 검증 불일치 없이 집계 완료 |
| MAJOR | 0 | 미해결 exact-date MKTCAP 신호 없음 |
| MINOR | 1 | 거래 단위 분석이며 포트폴리오 MDD는 범위 밖 |

## 1. 최종 판정

- 판정: `FAST_CORE_V2_P3_2_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01_PASS`
- 기간: 2022-01-03~2026-08-31; 실행 지원일: 2026-09-01. 기간 종료 뒤 신규 진입은 0건이야.
- P3-2 한 기간의 CONTROL, MA60, Bullish Alignment 거래 단위 비교야. 다른 기간 결과 비교나 전략 승격 판단은 하지 않았어.

## 2. Authority / universe

- 영구 제외 정책: 181개 exact `(ticker, ISU)` pair, 중복 0개.
- Frozen survivor: 2,539; 현재 제외와 교집합 115; replay 전 필터된 공통 eligible universe 2,424.
- P3-2 PIT overlap: identity 2,424, segment 2,424, ticker 2,424.
- 제외 적용은 exact `(ticker, ISU)` pair 기준이고 ticker-only 매칭은 사용하지 않았어.
- 세 전략은 같은 survivor roster, PIT interval, 거래 캘린더, 가격 authority, lifecycle, cutoff와 비용 조건을 공유했어.

## 3. PIT / lifecycle 무결성

- Permanent-exclusion leakage: trades 0, signal audits 0, MKTCAP audit 0.
- Exact-date MKTCAP unresolved 0건; reason 분포 {}; gate를 통과한 CONTROL 진입의 MKTCAP 확인 True. UNRESOLVED 신호는 진입시키지 않았어.
- Worker 10개/전략, worker 오류 0, 네트워크 호출 0; 처리 ticker 수 일치 True.
- Signal↔trade accepted parity True; MA60 fail-closed/formula True; Alignment fail-closed/formula True.
- Duplicate trade key 0; post-cutoff entry 0; terminal return 재계산 불일치 0.
- PIT SHA-256 `6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1`; calendar `cf9560da17674c866c57906b4b8e21ce956a0e7a0a9a3ccd1779d1a83a7111c2`; survivor roster `313bca3d5dbc28672cb505c18b61af40a9b4b827c11af56b30f45160cdba1506`; exclusion registry `858ec93e656bea5aa9ad036f7bd8e129253b4f682d062e7fb9350ad5eea1cffa`.
- Net 수익률은 매수/매도 수수료 각 0.015%, 슬리피지 각 0.10%를 반영했고 거래세는 제외했어.

## 4. 전략별 핵심 결과

| 전략 | 거래 | 실현 | 생애주기 정산 | cutoff 미종료 | terminal 결과 | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 평균 보유일 | 중앙 보유일 | Loss Guard 건수/율 | PROGRESSED 건수/율 | 최대 수익 % | 최대 손실 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 370 | 336 | 0 | 34 (9.19%) | 370 | 33.93 | 37.57 | 17.72 | -14.65 | 16.05 | -15.06 | 151.82 | 89.50 | 206 (55.68%) | 150 (40.54%) | 584.70 | -45.77 |
| MA60 | 308 | 278 | 0 | 30 (9.74%) | 308 | 37.05 | 40.91 | 18.55 | -14.34 | 17.41 | -14.81 | 145.31 | 86.00 | 163 (52.92%) | 134 (43.51%) | 584.70 | -52.58 |
| ALIGNMENT | 166 | 152 | 0 | 14 (8.43%) | 166 | 46.05 | 49.40 | 23.45 | -5.75 | 22.54 | -12.27 | 157.18 | 100.00 | 78 (46.99%) | 82 (49.40%) | 190.41 | -33.62 |

## 5. CONTROL 대비 delta

| 후보 | 거래 수 Δ | 거래 감소율 % | 실현 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 평균 보유일 Δ | +20/+50/+100% 건수 Δ | +20/+50/+100% 비율 Δ %p | -10/-15/-20/-30% 건수 Δ | 손실 비율 Δ %p | Loss Guard 건수/율 Δ | PROGRESSED 건수/율 Δ | cutoff 미종료 건수/율 Δ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MA60 | -62 | 16.76 | 3.12 | 3.34 | 0.84/0.31 | 1.37/0.24 | -6.51 | -16/-14/-8 | 1.01/0.35/-0.75 | -44/-36/-3/0 | -2.59/-2.33/0.11/0.22 | -43/-2.75%p | -16/2.97%p | -4/0.55%p |
| ALIGNMENT | -204 | 55.14 | 12.12 | 11.83 | 5.74/8.90 | 6.49/2.79 | 5.36 | -51/-42/-18 | 7.14/4.59/0.45 | -135/-111/-13/-3 | -9.92/-9.74/-1.19/-0.48 | -128/-8.69%p | -68/8.86%p | -20/-0.76%p |

## 6. 수익 / 손실 구간

| 전략 | 구간 | 건수 | 전체 거래 대비 % |
|---|---|---:|---:|
| CONTROL | >=+20% | 114 | 30.81 |
| CONTROL | >=+50% | 90 | 24.32 |
| CONTROL | >=+100% | 34 | 9.19 |
| CONTROL | <=-10% | 215 | 58.11 |
| CONTROL | <=-15% | 172 | 46.49 |
| CONTROL | <=-20% | 20 | 5.41 |
| CONTROL | <=-30% | 4 | 1.08 |
| MA60 | >=+20% | 98 | 31.82 |
| MA60 | >=+50% | 76 | 24.68 |
| MA60 | >=+100% | 26 | 8.44 |
| MA60 | <=-10% | 171 | 55.52 |
| MA60 | <=-15% | 136 | 44.16 |
| MA60 | <=-20% | 17 | 5.52 |
| MA60 | <=-30% | 4 | 1.30 |
| ALIGNMENT | >=+20% | 63 | 37.95 |
| ALIGNMENT | >=+50% | 48 | 28.92 |
| ALIGNMENT | >=+100% | 16 | 9.64 |
| ALIGNMENT | <=-10% | 80 | 48.19 |
| ALIGNMENT | <=-15% | 61 | 36.75 |
| ALIGNMENT | <=-20% | 7 | 4.22 |
| ALIGNMENT | <=-30% | 1 | 0.60 |

## 7. 거래 빈도

진입 신호일 기준 연도별 거래 수야. 2026년은 8월 31일까지의 부분 연도야.

| 전략 | 연도 | 진입 건수 |
|---|---:|---:|
| CONTROL | 2022 | 52 |
| CONTROL | 2023 | 85 |
| CONTROL | 2024 | 77 |
| CONTROL | 2025 | 101 |
| CONTROL | 2026 | 55 |
| MA60 | 2022 | 37 |
| MA60 | 2023 | 73 |
| MA60 | 2024 | 71 |
| MA60 | 2025 | 80 |
| MA60 | 2026 | 47 |
| ALIGNMENT | 2022 | 24 |
| ALIGNMENT | 2023 | 42 |
| ALIGNMENT | 2024 | 40 |
| ALIGNMENT | 2025 | 43 |
| ALIGNMENT | 2026 | 17 |

## 8. 주요 관찰점

### Exit reason 분포

| 전략 | Exit reason | 건수 |
|---|---|---:|
| CONTROL | LOSS_GUARD_CLOSE_LE_NEG_15 | 206 |
| CONTROL | EXIT4_SCORE_DRAWDOWN_GE_15 | 118 |
| CONTROL | NO_EXIT_BEFORE_CUTOFF | 20 |
| CONTROL | NO_PROGRESSED_BEFORE_CUTOFF | 14 |
| CONTROL | EXIT3_PROGRESSED_TO_TRANSITION | 6 |
| CONTROL | EXIT3_PROGRESSED_TO_WEAK | 4 |
| CONTROL | EXIT3_PROGRESSED_TO_EARLY_TREND | 2 |
| MA60 | LOSS_GUARD_CLOSE_LE_NEG_15 | 163 |
| MA60 | EXIT4_SCORE_DRAWDOWN_GE_15 | 106 |
| MA60 | NO_EXIT_BEFORE_CUTOFF | 19 |
| MA60 | NO_PROGRESSED_BEFORE_CUTOFF | 11 |
| MA60 | EXIT3_PROGRESSED_TO_TRANSITION | 5 |
| MA60 | EXIT3_PROGRESSED_TO_EARLY_TREND | 2 |
| MA60 | EXIT3_PROGRESSED_TO_WEAK | 2 |
| ALIGNMENT | LOSS_GUARD_CLOSE_LE_NEG_15 | 78 |
| ALIGNMENT | EXIT4_SCORE_DRAWDOWN_GE_15 | 67 |
| ALIGNMENT | NO_EXIT_BEFORE_CUTOFF | 8 |
| ALIGNMENT | NO_PROGRESSED_BEFORE_CUTOFF | 6 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_TRANSITION | 4 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_EARLY_TREND | 2 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_WEAK | 1 |

- 이 세 전략 중 terminal 평균 수익률이 가장 높은 전략은 ALIGNMENT (23.45%)이야.
- terminal 중앙값이 가장 높은 전략은 ALIGNMENT (-5.75%)이야.
- MA60는 CONTROL보다 거래가 -62건 변했고, 거래 수 변화율은 16.76%야. terminal 평균/중앙 변화는 0.84/0.31%p야.
- ALIGNMENT는 CONTROL보다 거래가 -204건 변했고, 거래 수 변화율은 55.14%야. terminal 평균/중앙 변화는 5.74/8.90%p야.

## 9. 제한사항

- 결과는 단일 기간의 동일 가중 거래 단위 집계야. 동시 보유, 자본 제약, 포트폴리오 equity curve/MDD는 계산하지 않았어.
- 이번 결과만으로 다기간 반복성, 공식 전략 승격, FAST Core V2 교체 또는 포트폴리오 우위를 결론 내리지 않아.
- PROGRESSED는 authoritative lifecycle event와 realized/cutoff/settlement boundary를 대조한 거래별 audit 기준이야. Exit reason 분포는 아래 산출물과 `p3_2_exit_reason_distribution.csv`에 있어.

## 10. 실행시간

전체 사전점검·재생·무결성 검증·보고서 생성 시간: 160.1분 (9608.3초).

## 11. 생성 artifact 목록

전용 폴더: `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_ma60_vs_bullish_alignment_simple_backtest_v01/`
- `run_p3_2_simple_backtest.py`, `preflight.json`, `identity_authority_audit.csv`
- CONTROL/MA60/Alignment 거래 원장, 후보 signal audit, CONTROL exact-date MKTCAP audit, 가격 파티션 audit
- `p3_2_strategy_metrics.csv`, `p3_2_strategy_metrics_reconciled.csv`, `p3_2_deltas_vs_control.csv`, `p3_2_large_outcomes.csv`, `p3_2_trade_frequency_by_year.csv`
- `p3_2_progressed_reconciliation_audit.csv`, `p3_2_exit_reason_distribution.csv`, `p3_2_execution_audit.json`, `p3_2_provenance.json`, `artifact_manifest.json`, `report.md`
- 결과 토큰: `FAST_CORE_V2_P3_2_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01_PASS`
