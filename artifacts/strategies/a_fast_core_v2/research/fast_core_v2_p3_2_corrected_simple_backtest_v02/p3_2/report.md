# FAST Core V2 P3-2 corrected simple backtest V02

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
| 실행 구간 / support | 2022-01-03 ~ 2026-08-31 / 2026-09-01 |
| 공통 historical COMMON identity / segment / ticker | 2,717 / 2,717 / 2,551 |
| 영구 제외 후 identity / segment | 2,558 / 2,558 |
| MARKET_CAP_FILTER / cap rejects / hidden gate | NONE / 0 / 0 |
| current/future survivor 기반 제외 | 0 |
| exact permanent exclusion registry / duplicates / leakage | 181 / 0 / 0 |
| worker / worker errors / network | 10 per strategy / 0 / 0 |
| cutoff 이후 신규 진입 / duplicate trade | signal=0; execution=0 / 0 |
| P3-1 → P3-2 prefix mismatch | True |
| sample runtime estimate | 2.79 h + 20% buffer = 3.35 h |

- 세 전략 모두 같은 frozen historical PIT, exact 181쌍 제외, Repository V2 가격 원천, worker 10, 비용 조건을 사용했어.
- 비용은 매수·매도 수수료 각 0.015%, 매수·매도 슬리피지 각 0.10%, 거래세 제외야.
- current/future survivor roster 및 시총·거래대금·거래량·펀더멘털 필터는 eligibility에 사용하지 않았어.
- 신호와 체결이 당시 COMMON 구간 안이고 entry execution이 2026-08-31 이내인지 거래별로 검사했어. 이후 COMMON 종료만으로 보유를 강제 청산하지 않았어.
- 선행 지표 예열은 기간 밖 가격을 읽고, 평가는 2022-01-03부터 시작했어. 다음 거래일 support는 기존 cutoff 이후 청산 신호의 체결에만 사용했어.

## 성과 비교

아래 수익률은 trade-level net 결과야. 포트폴리오 자금·MDD·현금 부족률이나 공식 채택 판정은 이번 simple replay에서 계산하지 않았어.

| 전략 | 전체 거래 | 실현 | cutoff OPEN | 미종료율 | 실현 승률 | terminal 양수율 | terminal 평균 | terminal 중앙 | realized 평균 | realized 중앙 | 보유 평균 일 | 보유 중앙 일 | 최대 수익 | 최대 손실 | Loss Guard 수/율 | PROGRESSED 수/율 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| CONTROL | 1688 | 1518 | 170 | 10.07% | 23.45% | 27.90% | 6.08% | -15.46% | 3.76% | -15.63% | 119.48 | 69.00 | 741.71% | -82.06% | 1098 / 65.05% | 505 / 29.92% |
| MA60 | 1287 | 1163 | 124 | 9.63% | 26.05% | 30.23% | 7.69% | -15.40% | 5.19% | -15.56% | 118.68 | 69.00 | 741.71% | -78.21% | 811 / 63.01% | 421 / 32.71% |
| ALIGNMENT | 626 | 583 | 43 | 6.87% | 28.13% | 30.51% | 8.36% | -15.42% | 7.74% | -15.49% | 120.75 | 69.50 | 434.05% | -78.21% | 394 / 62.94% | 215 / 34.35% |

### 대형 승리와 손실 꼬리

| 전략 | +20% | +50% | +100% | ≤−10% | ≤−15% | ≤−20% | ≤−30% |
|---|---|---|---|---|---|---|---|
| CONTROL | 349 (20.68%) | 232 (13.74%) | 89 (5.27%) | 1154 (68.36%) | 971 (57.52%) | 112 (6.64%) | 31 (1.84%) |
| MA60 | 285 (22.14%) | 188 (14.61%) | 70 (5.44%) | 854 (66.36%) | 725 (56.33%) | 87 (6.76%) | 21 (1.63%) |
| ALIGNMENT | 146 (23.32%) | 101 (16.13%) | 37 (5.91%) | 418 (66.77%) | 354 (56.55%) | 44 (7.03%) | 13 (2.08%) |

### CONTROL 대비 후보 변화

| 후보 | 거래수 변화 | 승률 Δ %p | terminal 평균/중앙 Δ %p | realized 평균/중앙 Δ %p | 보유 평균/중앙 Δ 일 | Loss Guard Δ %p | PROGRESSED Δ %p | +20/+50/+100 비율 Δ %p | −10/−15/−20/−30 비율 Δ %p |
|---|---|---|---|---|---|---|---|---|---|
| MA60 | -401 (23.76% 감소) | 2.60 | 1.61 / 0.06 | 1.43 / 0.06 | -0.81 / 0.00 | -2.03 | 2.79 | 1.47/0.86/0.17 | -2.01/-1.19/0.12/-0.20 |
| ALIGNMENT | -1062 (62.91% 감소) | 4.68 | 2.28 / 0.04 | 3.98 / 0.14 | 1.26 / 0.50 | -2.11 | 4.43 | 2.65/2.39/0.64 | -1.59/-0.97/0.39/0.24 |

### Exit reason

| 전략 | exit reason | 건수 |
|---|---|---|
| CONTROL | LOSS_GUARD_CLOSE_LE_NEG_15 | 1098 |
| CONTROL | EXIT4_SCORE_DRAWDOWN_GE_15 | 365 |
| CONTROL | NO_PROGRESSED_BEFORE_CUTOFF | 85 |
| CONTROL | NO_EXIT_BEFORE_CUTOFF | 85 |
| CONTROL | EXIT3_PROGRESSED_TO_WEAK | 27 |
| CONTROL | EXIT3_PROGRESSED_TO_TRANSITION | 23 |
| CONTROL | EXIT3_PROGRESSED_TO_EARLY_TREND | 3 |
| CONTROL | EXIT3_PROGRESSED_TO_BASE | 2 |
| MA60 | LOSS_GUARD_CLOSE_LE_NEG_15 | 811 |
| MA60 | EXIT4_SCORE_DRAWDOWN_GE_15 | 304 |
| MA60 | NO_EXIT_BEFORE_CUTOFF | 69 |
| MA60 | NO_PROGRESSED_BEFORE_CUTOFF | 55 |
| MA60 | EXIT3_PROGRESSED_TO_TRANSITION | 22 |
| MA60 | EXIT3_PROGRESSED_TO_WEAK | 21 |
| MA60 | EXIT3_PROGRESSED_TO_EARLY_TREND | 3 |
| MA60 | EXIT3_PROGRESSED_TO_BASE | 2 |
| ALIGNMENT | LOSS_GUARD_CLOSE_LE_NEG_15 | 394 |
| ALIGNMENT | EXIT4_SCORE_DRAWDOWN_GE_15 | 159 |
| ALIGNMENT | NO_EXIT_BEFORE_CUTOFF | 26 |
| ALIGNMENT | NO_PROGRESSED_BEFORE_CUTOFF | 17 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_TRANSITION | 15 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_WEAK | 12 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_EARLY_TREND | 2 |
| ALIGNMENT | EXIT3_PROGRESSED_TO_BASE | 1 |

## 거래 빈도

연도는 진입 신호일 기준이야. 월평균 분모는 해당 연도 P3-2 구간 안에서 실제 frozen KRX 달력에 거래일이 있는 월 수야.

| 전략 | 연도 | 진입 수 | 관측 KRX 월 | 진입 발생 월 | 월평균 진입 |
|---|---|---|---|---|---|
| CONTROL | 2022 | 248 | 12 | 12 | 20.67 |
| CONTROL | 2023 | 387 | 12 | 12 | 32.25 |
| CONTROL | 2024 | 305 | 12 | 12 | 25.42 |
| CONTROL | 2025 | 506 | 12 | 12 | 42.17 |
| CONTROL | 2026 | 242 | 8 | 8 | 30.25 |
| MA60 | 2022 | 185 | 12 | 12 | 15.42 |
| MA60 | 2023 | 316 | 12 | 12 | 26.33 |
| MA60 | 2024 | 258 | 12 | 12 | 21.50 |
| MA60 | 2025 | 366 | 12 | 12 | 30.50 |
| MA60 | 2026 | 162 | 8 | 8 | 20.25 |
| ALIGNMENT | 2022 | 124 | 12 | 12 | 10.33 |
| ALIGNMENT | 2023 | 201 | 12 | 12 | 16.75 |
| ALIGNMENT | 2024 | 117 | 12 | 12 | 9.75 |
| ALIGNMENT | 2025 | 136 | 12 | 12 | 11.33 |
| ALIGNMENT | 2026 | 48 | 8 | 8 | 6.00 |

월별 거래 빈도는 `p3_2_trade_frequency_by_month.csv`에서 0건인 관측월까지 포함해 확인할 수 있어.

## P3-1 공통 기간과 prefix invariance

| 전략 | P3-1 REALIZED 대상 | missing | duplicate key | entry mismatch | exit mismatch | net return mismatch | exit reason mismatch | lifecycle mismatch | status mismatch |
|---|---|---|---|---|---|---|---|---|---|
| ALIGNMENT | 416 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| CONTROL | 894 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| MA60 | 716 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |

P3-1에서 cutoff에 이미 REALIZED였던 거래만 안정 거래 키로 대조했어. P3-1 cutoff OPEN 거래가 P3-2에서 뒤에 청산되는 건 prefix mismatch로 보지 않았어. 상세 행 단위 결과는 `p3_2_p3_1_prefix_invariance_audit.csv`야.

## 실행·산출물·Git

- 50개 대표 ticker 샘플 합산 예상 실행시간: 2.79시간; 계획 여유 20% 포함 3.35시간.
- 전체 replay 처리시간: 2.78시간; network 호출 0회; worker 오류 0건.
- Git 시작 HEAD `20f123797545c57524fb6d91aedf7d749825db34`; 시작 시점 HEAD == origin/main, tracked worktree/index clean.
- 산출물 디렉터리: `artifacts/strategies/a_fast_core_v2/research/fast_core_v2_p3_2_corrected_simple_backtest_v02/p3_2/`; `artifact_manifest.json`의 모든 hash를 재검증했어.
- 시총 기반 필터는 실제 진입 경로에 없고 cap reject는 0이야. 포트폴리오 MDD·현금 부족률·official adoption은 simple trade-level 범위가 아니야.

## 부록: 기존 오염 P3-2 자료 분류

기존 1조 시총 및 current survivor roster 기반 P3-2 파일은 `INVALID / 비공식 비교자료`야. 이 replay의 universe, 계산, metrics, prefix 판정에는 사용하지 않았어.

최종 상태 토큰: `FAST_CORE_V2_P3_2_CORRECTED_SIMPLE_BACKTEST_V02_PASS`


## 보고서 생성 복구

- 세 전략 replay와 무결성 검사는 완료됐고 모든 필수 gate는 PASS야.
- 최초 보고서 작성은 템플릿의 누락된 `post_cutoff_entry_count` 참조로 중단됐어.
- 이 보고서·provenance는 저장된 거래 원장과 감사 산출물에서 재생성했으며, 백테스트 replay는 다시 실행하지 않았어.
