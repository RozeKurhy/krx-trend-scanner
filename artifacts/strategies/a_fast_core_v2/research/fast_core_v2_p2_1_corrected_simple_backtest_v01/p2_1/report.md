# FAST Core V2 P2-1 corrected simple backtest V01

## 이슈 레벨별 요약

| 레벨 | 개수 | 판정 |
|---|---|---|
| CRITICAL | 0 | 필수 gate 모두 통과 |
| MAJOR | 0 | 구조적 결과 훼손 확인 없음 |
| MINOR | 0 | 미해결 또는 범위 밖 항목은 상세 이슈에 표기 |

## 상세 이슈

필수 통과 조건을 위반한 이슈는 확인되지 않았어.

## 계약 검증

| 항목 | 결과 |
|---|---|
| 실행 구간 / support | 2021-01-04 ~ 2025-05-30 / 2025-06-02 |
| 공통 historical COMMON identity / segment / ticker | 2,657 / 2,657 / 2,482 |
| 영구 제외 후 identity / segment | 2,491 / 2,491 |
| MARKET_CAP_FILTER / cap rejects / hidden gate | NONE / 0 / 0 |
| current/future survivor 기반 제외 | 0 |
| exact permanent exclusion registry / duplicates / leakage | 181 / 0 / 0 |
| worker / worker errors / network | 10 per strategy / 0 / 0 |
| cutoff 이후 신호 / 체결 / duplicate trade | 0 / 0 / 0 |
| CONTROL emitted rows / ledger parity; MA60·Alignment accepted-signal parity | 1705 / 1705 / True |
| sample runtime estimate | 2.46 h + 20% buffer = 2.96 h |

- 세 전략 모두 같은 frozen historical PIT, exact 181쌍 제외, Repository V2 가격 원천, worker 10, 비용 조건을 사용했어.
- 비용은 매수·매도 수수료 각 0.015%, 매수·매도 슬리피지 각 0.10%, 거래세 제외야.
- current/future survivor roster 및 시총·거래대금·거래량·펀더멘털 필터는 eligibility에 사용하지 않았어.
- 신호와 체결이 당시 COMMON 구간 안이고 신규 진입 체결이 2025-05-30 이내인지 거래별로 검사했어. 이후 COMMON 종료만으로 보유를 강제 청산하지 않았어.
- 달력 기간은 2021-01-01~2025-05-31이고 frozen KRX 기준 실제 구간은 2021-01-04~2025-05-30, 체결 지원은 2025-06-02야. 지표 예열용 선행 가격은 평가 밖에서 읽고, 지원일은 cutoff까지 확정된 청산 신호의 후속 체결에만 사용했어.

## 성과 비교

아래 수익률은 trade-level net 결과야. 포트폴리오 자금·MDD·현금 부족률이나 공식 채택 판정은 이번 simple replay에서 계산하지 않았어.

| 전략 | 전체 거래 | 실현 | cutoff OPEN | 미종료율 | 실현 승률 | terminal 양수율 | terminal 평균 | terminal 중앙 | realized 평균 | realized 중앙 | 보유 평균 일 | 보유 중앙 일 | 최대 수익 | 최대 손실 | Loss Guard 수/율 | PROGRESSED 수/율 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONTROL | 1705 | 1482 | 223 | 13.08% | 25.78% | 31.85% | 3.14% | -15.39% | 0.99% | -15.57% | 122.92 | 74.00 | 752.98% | -72.56% | 991 / 58.12% | 565 / 33.14% |
| MA60 | 1344 | 1176 | 168 | 12.50% | 25.77% | 31.32% | 2.96% | -15.35% | 0.54% | -15.53% | 115.89 | 70.00 | 752.98% | -65.10% | 772 / 57.44% | 463 / 34.45% |
| ALIGNMENT | 591 | 522 | 69 | 11.68% | 22.99% | 29.27% | 2.46% | -15.49% | 0.73% | -15.70% | 105.08 | 60.00 | 434.05% | -65.10% | 378 / 63.96% | 167 / 28.26% |

### 대형 승리와 손실 꼬리

| 전략 | +20% | +50% | +100% | ≤−10% | ≤−15% | ≤−20% | ≤−30% |
|---|---|---|---|---|---|---|---|
| CONTROL | 357 (20.94%) | 173 (10.15%) | 54 (3.17%) | 1099 (64.46%) | 943 (55.31%) | 121 (7.10%) | 34 (1.99%) |
| MA60 | 283 (21.06%) | 133 (9.90%) | 43 (3.20%) | 858 (63.84%) | 735 (54.69%) | 92 (6.85%) | 28 (2.08%) |
| ALIGNMENT | 124 (20.98%) | 62 (10.49%) | 21 (3.55%) | 402 (68.02%) | 349 (59.05%) | 42 (7.11%) | 9 (1.52%) |

### CONTROL 대비 후보 변화

| 후보 | 거래수 변화 | 승률 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 보유 평균/중앙 Δ 일 | Loss Guard Δ %p | PROGRESSED Δ %p | +20/+50/+100 비율 Δ %p | −10/−15/−20/−30 비율 Δ %p |
|---|---|---|---|---|---|---|---|---|---|
| MA60 | -361 (21.17% 감소) | -0.01 | -0.18 / 0.04 | -0.46 / 0.04 | -7.04 / -4.00 | -0.68 | 1.31 | 0.12/-0.25/0.03 | -0.62/-0.62/-0.25/0.09 |
| ALIGNMENT | -1114 (65.34% 감소) | -2.79 | -0.68 / -0.11 | -0.26 / -0.13 | -17.84 / -14.00 | 5.84 | -4.88 | 0.04/0.34/0.39 | 3.56/3.74/0.01/-0.47 |

### Exit reason

| 전략 | exit reason | 건수 |
|---|---|---|
| CONTROL | LOSS_GUARD_CLOSE_LE_NEG_15 | 991 |
| CONTROL | EXIT4_SCORE_DRAWDOWN_GE_15 | 432 |
| CONTROL | NO_PROGRESSED_BEFORE_CUTOFF | 149 |
| CONTROL | NO_EXIT_BEFORE_CUTOFF | 74 |
| CONTROL | EXIT3_PROGRESSED_TO_TRANSITION | 42 |
| CONTROL | EXIT3_PROGRESSED_TO_WEAK | 14 |
| CONTROL | EXIT3_PROGRESSED_TO_BASE | 2 |
| CONTROL | EXIT3_PROGRESSED_TO_EARLY_TREND | 1 |
| MA60 | LOSS_GUARD_CLOSE_LE_NEG_15 | 772 |
| MA60 | EXIT4_SCORE_DRAWDOWN_GE_15 | 352 |
| MA60 | NO_PROGRESSED_BEFORE_CUTOFF | 109 |
| MA60 | NO_EXIT_BEFORE_CUTOFF | 59 |
| MA60 | EXIT3_PROGRESSED_TO_TRANSITION | 37 |
| MA60 | EXIT3_PROGRESSED_TO_WEAK | 12 |
| MA60 | EXIT3_PROGRESSED_TO_BASE | 2 |
| MA60 | EXIT3_PROGRESSED_TO_EARLY_TREND | 1 |
| ALIGNMENT | LOSS_GUARD_CLOSE_LE_NEG_15 | 378 |
| ALIGNMENT | EXIT4_SCORE_DRAWDOWN_GE_15 | 121 |
| ALIGNMENT | NO_PROGRESSED_BEFORE_CUTOFF | 46 |
| ALIGNMENT | NO_EXIT_BEFORE_CUTOFF | 23 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_TRANSITION | 15 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_WEAK | 8 |

## 거래 빈도

연도는 진입 신호일 기준이야. 월평균 분모는 해당 연도 P2-1 구간 안에서 실제 frozen KRX 달력에 거래일이 있는 월 수야.

| 전략 | 연도 | 진입 수 | 관측 KRX 월 | 진입 발생 월 | 월평균 진입 |
|---|---|---|---|---|---|
| CONTROL | 2021 | 654 | 12 | 12 | 54.50 |
| CONTROL | 2022 | 232 | 12 | 12 | 19.33 |
| CONTROL | 2023 | 372 | 12 | 12 | 31.00 |
| CONTROL | 2024 | 296 | 12 | 12 | 24.67 |
| CONTROL | 2025 | 151 | 5 | 5 | 30.20 |
| MA60 | 2021 | 498 | 12 | 12 | 41.50 |
| MA60 | 2022 | 178 | 12 | 12 | 14.83 |
| MA60 | 2023 | 309 | 12 | 12 | 25.75 |
| MA60 | 2024 | 251 | 12 | 12 | 20.92 |
| MA60 | 2025 | 108 | 5 | 5 | 21.60 |
| ALIGNMENT | 2021 | 110 | 12 | 12 | 9.17 |
| ALIGNMENT | 2022 | 122 | 12 | 12 | 10.17 |
| ALIGNMENT | 2023 | 202 | 12 | 12 | 16.83 |
| ALIGNMENT | 2024 | 117 | 12 | 12 | 9.75 |
| ALIGNMENT | 2025 | 40 | 5 | 5 | 8.00 |

월별 거래 빈도는 `p2_1_trade_frequency_by_month.csv`에서 0건인 관측월까지 포함해 확인할 수 있어.

Prefix invariance는 이 단일 기간 실행 범위가 아니며, corrected P2-2 fresh replay 이후 P2-1 ↔ P2-2로 대조해.

## 실행·산출물·Git

- 50개 대표 ticker 샘플 합산 예상 실행시간: 2.46시간; 계획 여유 20% 포함 2.96시간.
- 전체 replay 처리시간: 2.49시간; network 호출 0회; worker 오류 0건.
- Git 시작 HEAD `b12ace3484be01c29c762942e0ffdd3e374bfc15`; 시작 시점 HEAD == origin/main, tracked worktree/index clean.
- 산출물 디렉터리: `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p2_1_corrected_simple_backtest_v01/p2_1/`; `artifact_manifest.json`의 모든 hash를 재검증했어.
- 시총 기반 필터는 실제 진입 경로에 없고 cap reject는 0이야. 포트폴리오 MDD·현금 부족률·official adoption은 simple trade-level 범위가 아니야.

## 범위 메모

이전 P2-1 결과물은 replay 입력, 기대 거래 수, 지표 기준값 또는 eligibility authority로 읽지 않았어. 이번 결과는 새 historical PIT 기반 replay야.

최종 상태 토큰: `FAST_CORE_V2_P2_1_CORRECTED_SIMPLE_BACKTEST_V01_PASS`
