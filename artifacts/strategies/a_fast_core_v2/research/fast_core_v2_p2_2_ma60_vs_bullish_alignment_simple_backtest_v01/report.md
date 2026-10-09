# FAST Core V2 P2-2 단순 백테스트

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 검증 또는 실행 오류 없음 |
| MAJOR | 1 | 과거 P1/P2-1 ledger에 현재 permanent exclusion에 해당하는 거래가 있어 기간 간 비교는 방향성 참고로 제한 |
| MINOR | 1 | 포트폴리오 equity curve/MDD는 지시 범위 밖이므로 계산하지 않음 |

## 범위와 입력

- 공식 calendar 기간은 2021-01-01~2026-08-31이고 실제 거래일은 2021-01-04~2026-08-31; execution support는 2026-09-01야. cutoff 뒤 신규 진입은 없어.
- Frozen survivor roster 2,539개 중 최신 exact permanent exclusion authority 181개와 겹치는 115개를 `(ticker, ISU)`로 제거했어. 2026-10-05 승인 7개 중 roster와 겹친 수는 7개, 필터 후 roster는 2,424개, P2-2 window PIT identity key는 2,424개야.
- CONTROL, MA60 fail-closed, Bullish Alignment은 같은 필터된 survivor identity/PIT, lifecycle, Repository V2, cutoff 및 exact-date MKTCAP 계약을 공유했어. P2-2만 새 replay했어.
- P1/P2-1 결과는 백테스트 입력으로 재사용하지 않았고 반복성 비교에만 읽었어. 이전 ledger에 현재 제외 authority와 겹치는 거래가 있으므로 기간 간 수치는 완전한 동일 universe 비교가 아니야.
- 매수/매도 수수료 각 0.015%, 매수/매도 슬리피지 각 0.10%, 거래세 제외. 수익률은 비용 반영 net 기준이야.
- 단순 거래 단위 결과라 portfolio MDD와 자본/동시 보유 제약은 산출하지 않았어.

## 전략별 핵심 지표

| 전략 | 거래 | 실현 | 생애주기 정산 | cutoff 미종료 | 실현 승률 % | terminal 양수율 % | terminal 평균 % | terminal 중앙 % | realized 평균 % | realized 중앙 % | 보유 평균 일 | 보유 중앙 일 | PROGRESSED 건수/율 | Loss Guard 건수/율 | 최대 수익 % | 최대 손실 % |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| CONTROL | 440 | 403 | 0 | 37 (8.41%) | 34.24 | 37.27 | 15.19 | -14.72 | 13.85 | -15.04 | 185.54 | 100.50 | 188 (42.73%) | 238 (54.09%) | 584.70 | -61.02 |
| MA60 | 363 | 333 | 0 | 30 (8.26%) | 36.64 | 39.94 | 16.24 | -14.55 | 15.11 | -14.88 | 168.56 | 88.00 | 161 (44.35%) | 191 (52.62%) | 584.70 | -61.02 |
| ALIGNMENT | 177 | 162 | 0 | 15 (8.47%) | 43.83 | 46.89 | 20.76 | -11.32 | 20.17 | -14.06 | 160.96 | 100.00 | 84 (47.46%) | 87 (49.15%) | 190.41 | -61.02 |

## 대형 승리·손실

| 전략 | 구간 | 건수 | 전체 거래 대비 % |
|---|---|---:|---:|
| CONTROL | >=+20% | 128 | 29.09 |
| CONTROL | >=+50% | 93 | 21.14 |
| CONTROL | >=+100% | 36 | 8.18 |
| CONTROL | <=-10% | 257 | 58.41 |
| CONTROL | <=-15% | 207 | 47.05 |
| CONTROL | <=-20% | 27 | 6.14 |
| CONTROL | <=-30% | 8 | 1.82 |
| MA60 | >=+20% | 109 | 30.03 |
| MA60 | >=+50% | 79 | 21.76 |
| MA60 | >=+100% | 28 | 7.71 |
| MA60 | <=-10% | 204 | 56.20 |
| MA60 | <=-15% | 163 | 44.90 |
| MA60 | <=-20% | 21 | 5.79 |
| MA60 | <=-30% | 7 | 1.93 |
| ALIGNMENT | >=+20% | 63 | 35.59 |
| ALIGNMENT | >=+50% | 48 | 27.12 |
| ALIGNMENT | >=+100% | 16 | 9.04 |
| ALIGNMENT | <=-10% | 90 | 50.85 |
| ALIGNMENT | <=-15% | 70 | 39.55 |
| ALIGNMENT | <=-20% | 10 | 5.65 |
| ALIGNMENT | <=-30% | 3 | 1.69 |

## CONTROL 대비 변화

| 후보 | 거래수 Δ | 거래 감소 % | 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 평균/중앙 보유 Δ 일 | cutoff-open Δ %p | Loss Guard Δ %p | PROGRESSED Δ %p |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| MA60 | -77 | 17.50 | 2.39 | 2.67 | 1.06 / 0.17 | 1.26 / 0.16 | -16.98 / -12.50 | -0.14 | -1.47 | 1.63 |
| ALIGNMENT | -263 | 59.77 | 9.58 | 9.62 | 5.57 / 3.41 | 6.32 / 0.98 | -24.58 / -0.50 | 0.07 | -4.94 | 4.73 |

## P1 / P2-1 반복성 평가

P1/P2-1 delta는 각 기간의 CONTROL 대비 후보 delta야. P2-2는 최신 exact exclusion을 적용했어. 이전 결과에서 제외 목록 identity를 포함한 ledger row가 발견돼 cross-period 평가는 방향성 비교로만 해석해.

| 기간 | 후보 | 거래 감소 % | 승률 Δ %p | terminal 양수율 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 평균/중앙 보유 Δ 일 | cutoff-open Δ %p | Loss Guard Δ %p | PROGRESSED Δ %p |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | MA60 | 25.54 | 3.14 | 3.31 | 1.71 / 0.19 | 1.97 / 0.16 | -22.47 / -5.00 | 0.81 | -3.44 | 3.30 |
| P1 | ALIGNMENT | 58.35 | 3.86 | 4.08 | 2.10 / 0.23 | 2.19 / 0.21 | -34.76 / 1.00 | 0.03 | -1.52 | 1.30 |
| P2-1 | MA60 | 18.03 | 1.50 | 0.84 | 0.98 / 0.13 | 1.28 / 0.06 | -18.20 / -16.00 | -0.16 | -0.85 | 1.12 |
| P2-1 | ALIGNMENT | 58.87 | 2.33 | 4.48 | 2.44 / 0.37 | 2.69 / 0.08 | -32.37 / -13.50 | 2.52 | -0.70 | -3.10 |
| P2-2 | MA60 | 17.50 | 2.39 | 2.67 | 1.06 / 0.17 | 1.26 / 0.16 | -16.98 / -12.50 | -0.14 | -1.47 | 1.63 |
| P2-2 | ALIGNMENT | 59.77 | 9.58 | 9.62 | 5.57 / 3.41 | 6.32 / 0.98 | -24.58 / -0.50 | 0.07 | -4.94 | 4.73 |

### 반복성 해석

- MA60: P1/P2-1/P2-2의 거래 감소율은 +25.54, +18.03, +17.50% (거래 유지율 +74.46, +81.97, +82.50%)야. 승률 우위 3/3기간, 평균 terminal 수익 우위 3/3기간, 평균 보유기간 단축 3/3기간으로 평가해. PROGRESSED 비율 delta는 +3.30, +1.12, +1.63%p (같은 방향)이야.
- Bullish Alignment: 거래 감소율 +58.35, +58.87, +59.77% 중 55~60% 범위는 3/3기간이야. 승률 우위 3/3기간, 평균 terminal 수익 우위 3/3기간, 평균 보유기간 단축 3/3기간이고, +20/+50/+100% winner 비율이 모두 상승한 기간은 3/3기간이야. PROGRESSED 비율 delta는 +1.30, -3.10, +4.73%p (기간별 방향 변동)이야.
- 공통 위험 MA60: -10/-15% 손실 비율 delta는 -3.42, -1.46, -2.21/-4.02, -2.06, -2.14%p, -20/-30% tail delta는 +0.33, -0.01, -0.35/+0.50, +0.15, +0.11%p야. 음수는 CONTROL 대비 발생률 감소, 양수는 증가야. P1/P2-1/P2-2 median terminal은 -15.18, -14.97, -14.55%야.
- 공통 위험 Bullish Alignment: -10/-15% 손실 비율 delta는 -3.26, -3.03, -7.56/-4.21, -3.60, -7.50%p, -20/-30% tail delta는 +1.38, +1.34, -0.49/+0.00, +0.49, -0.12%p야. 음수는 CONTROL 대비 발생률 감소, 양수는 증가야. P1/P2-1/P2-2 median terminal은 -15.14, -14.72, -11.32%야.

### 대형 승리·손실 rate delta 반복성 (%p)

| 기간 | 후보 | +20% | +50% | +100% | -10% 이하 | -15% 이하 | -20% 이하 | -30% 이하 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | MA60 | 1.72 | 0.73 | -0.12 | -3.42 | -4.02 | 0.33 | 0.50 |
| P1 | ALIGNMENT | 2.00 | 2.07 | 0.10 | -3.26 | -4.21 | 1.38 | 0.00 |
| P2-1 | MA60 | 2.39 | -0.05 | 0.68 | -1.46 | -2.06 | -0.01 | 0.15 |
| P2-1 | ALIGNMENT | 4.70 | 0.94 | 1.01 | -3.03 | -3.60 | 1.34 | 0.49 |
| P2-2 | MA60 | 0.94 | 0.63 | -0.47 | -2.21 | -2.14 | -0.35 | 0.11 |
| P2-2 | ALIGNMENT | 6.50 | 5.98 | 0.86 | -7.56 | -7.50 | -0.49 | -0.12 |

### 대형 승리·손실 비율 변화

| 후보 | 구간 | 건수 Δ | 전체 거래 대비 비율 Δ %p |
|---|---|---:|---:|
| MA60 | >=+20% | -19 | 0.94 |
| MA60 | >=+50% | -14 | 0.63 |
| MA60 | >=+100% | -8 | -0.47 |
| MA60 | <=-10% | -53 | -2.21 |
| MA60 | <=-15% | -44 | -2.14 |
| MA60 | <=-20% | -6 | -0.35 |
| MA60 | <=-30% | -1 | 0.11 |
| ALIGNMENT | >=+20% | -65 | 6.50 |
| ALIGNMENT | >=+50% | -45 | 5.98 |
| ALIGNMENT | >=+100% | -20 | 0.86 |
| ALIGNMENT | <=-10% | -167 | -7.56 |
| ALIGNMENT | <=-15% | -137 | -7.50 |
| ALIGNMENT | <=-20% | -17 | -0.49 |
| ALIGNMENT | <=-30% | -5 | -0.12 |

## Exit reason 분포

| 전략 | exit_type | 건수 |
|---|---|---:|
| CONTROL | LOSS_GUARD_CLOSE_LE_NEG_15 | 238 |
| CONTROL | EXIT4_SCORE_DRAWDOWN_GE_15 | 150 |
| CONTROL | NO_EXIT_BEFORE_CUTOFF | 23 |
| CONTROL | NO_PROGRESSED_BEFORE_CUTOFF | 14 |
| CONTROL | EXIT3_PROGRESSED_TO_TRANSITION | 9 |
| CONTROL | EXIT3_PROGRESSED_TO_WEAK | 4 |
| CONTROL | EXIT3_PROGRESSED_TO_EARLY_TREND | 2 |
| MA60 | LOSS_GUARD_CLOSE_LE_NEG_15 | 191 |
| MA60 | EXIT4_SCORE_DRAWDOWN_GE_15 | 130 |
| MA60 | NO_EXIT_BEFORE_CUTOFF | 19 |
| MA60 | NO_PROGRESSED_BEFORE_CUTOFF | 11 |
| MA60 | EXIT3_PROGRESSED_TO_TRANSITION | 8 |
| MA60 | EXIT3_PROGRESSED_TO_EARLY_TREND | 2 |
| MA60 | EXIT3_PROGRESSED_TO_WEAK | 2 |
| ALIGNMENT | LOSS_GUARD_CLOSE_LE_NEG_15 | 87 |
| ALIGNMENT | EXIT4_SCORE_DRAWDOWN_GE_15 | 68 |
| ALIGNMENT | NO_EXIT_BEFORE_CUTOFF | 9 |
| ALIGNMENT | NO_PROGRESSED_BEFORE_CUTOFF | 6 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_TRANSITION | 4 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_EARLY_TREND | 2 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_WEAK | 1 |

## PROGRESSED 집계

| 전략 | 원본 날짜 non-null (비권위) | 보유 중 PROGRESSED (권위) | 전체 거래 대비 % |
|---|---:|---:|---:|
| CONTROL | 332 | 188 | 42.73 |
| MA60 | 287 | 161 | 44.35 |
| ALIGNMENT | 140 | 84 | 47.46 |

실현 거래는 `entry_execution_date ≤ event ≤ exit_signal_date`, cutoff 미종료는 `entry_execution_date ≤ event ≤ 2026-08-31`, lifecycle 정산 거래는 공식 settlement date까지로 경계를 적용했어. entry 이전과 허용 상한 이후 event는 집계에서 제외했고 per-trade 근거는 `p2_2_progressed_reconciliation_audit.csv`에 있어.

## Authority / worker / provenance 검증

- CONTROL/MA60/Alignment worker는 각 10개, 오류는 각각 0건. 전체 처리 ticker 2,424, P2-2 identity key 2,424, PIT segment 2,424.
- 현재 permanent exclusion leakage: 0 trade. 정확한 `(ticker, ISU)` 필터와 authority 상세는 `identity_authority_audit.csv`에 있어.
- Trade key 중복 0; accepted signal↔trade parity True; terminal 수익 재계산 불일치 0; cutoff 뒤 진입 0.
- MA60 공식·fail-closed True; Alignment `signal_day_close > MA20 > MA60`·fail-closed True; MKTCAP unresolved 0; network calls 0.
- Frozen PIT SHA-256 `6747f26368369bc2ff5d20d695daed702c577bab34dd79640d41fbc862950bd1`; calendar `cf9560da17674c866c57906b4b8e21ce956a0e7a0a9a3ccd1779d1a83a7111c2`; survivor roster `313bca3d5dbc28672cb505c18b61af40a9b4b827c11af56b30f45160cdba1506`; permanent exclusion source `858ec93e656bea5aa9ad036f7bd8e129253b4f682d062e7fb9350ad5eea1cffa`.
- P1/P2-1 saved metrics와 trade ledger artifact hash 검증: PASS. 현재 authority와 겹치는 이전 ledger 거래 row는 P1 185, P2-1 71건이야. 이전 결과에는 백테스트 재실행 없이 검증된 결과만 사용했어.
- 이 작업은 trade-level 비교만 수행했고 portfolio MDD, realistic portfolio, P3-1/P3-2, 5-window 종합 및 공식 채택 판정은 실행하지 않았어.

## 산출물

- `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p2_2_ma60_vs_bullish_alignment_simple_backtest_v01/` 아래 metrics, trade ledger, signal/MKTCAP/price audit, execution audit, provenance가 있어.
- 결과 토큰: `FAST_CORE_V2_P2_2_MA60_VS_BULLISH_ALIGNMENT_SIMPLE_BACKTEST_V01_PASS`
