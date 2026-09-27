# Pattern B PROGRESSED 이전 Pattern A Stage 진단 V01

판정: `PATTERN_B_PROGRESSED_PREVIOUS_STAGE_PROMISING`

## 계약과 방법

- 기존 Pattern B `DEPRESSED + Pattern A PROGRESSED` raw 진입 835건을 그대로 분석했어. 기존 독립 PROGRESSED 전략 체결 832건, 실현 746건, cutoff 미청산 86건을 연결했고 새 전략 상태머신은 실행하지 않았어.
- 같은 PIT identity에서 공식 Pattern A classifier로 각 completed KRX 월말 Stage를 과거 방향으로 계산했어. 현재 PROGRESSED와 연속된 월말 묶음의 첫 관측일을 segment 시작으로 두고, 그 직전의 다른 authoritative classifier 결과를 이전 Stage로 기록했어. `UNAVAILABLE` 또는 PIT 활성 월 공백은 segment 경계로 취급했고 이전 Stage는 `UNAVAILABLE`로 표시했어.
- PROGRESSED 체류기간은 구간 시작 월말부터 신호 월말까지 경과한 KRX 거래 세션 수(시작일 당일 0)야. 체류기간 threshold/bin 탐색은 하지 않았어.
- PIT 검증은 요청일로 잘린 실제 일봉 as-of와 주봉 label을 기준으로 했어. 월봉 label은 달력 월말로 표시되어 해당 월의 마지막 KRX 거래일보다 며칠 뒤일 수 있지만, 월봉 원자료는 요청일 이전 일봉에서만 만들고 완성된 KRX 월만 포함했어.
- Pattern B 신호 2013-01-31~2026-08-31, 평가 cutoff 2026-09-21, 월별 상태 frontier 2026-08-31; 기존 PIT universe·exclusion·거래 계약을 유지했어.
- 동일한 Pattern B candidate key, 독립 PROGRESSED 거래 원장, Pattern B 상태 경로 원장을 연결했어. Pattern B state path 표의 분모는 raw 835건, 수익·MFE·MAE·보유·미청산은 independent fill 기준이야.
- 이전 Stage별 raw 표본이 20건 미만이면 주의 표시만 했어. 상태를 임의 병합하지 않았고 체류기간 threshold/bin은 탐색하지 않았어.

## 이전 Pattern A Stage별 비교

| 이전 Stage → PROGRESSED | raw N | 체결/실현/미청산 | NORMAL 첫 도달 | DEEP 첫 도달 | 중앙수익 | 승률 | +50% | -30% | -50% | 미청산률 | 중앙 MAE | 주의 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| WEAK → PROGRESSED | 118 | 115/103/12 | 58.47% (69) | 35.59% (42) | 9.92% | 63.11% | 4.85% (5) | 11.65% (12) | 4.85% (5) | 10.43% | -22.43% |  |
| BASE → PROGRESSED | 43 | 43/39/4 | 67.44% (29) | 16.28% (7) | 10.51% | 71.79% | 0.00% (0) | 5.13% (2) | 2.56% (1) | 9.30% | -10.46% |  |
| TRANSITION → PROGRESSED | 306 | 306/277/29 | 75.16% (230) | 16.34% (50) | 12.60% | 80.87% | 6.14% (17) | 5.78% (16) | 2.53% (7) | 9.48% | -9.94% |  |
| EARLY_TREND → PROGRESSED | 287 | 287/253/34 | 72.47% (208) | 17.07% (49) | 12.50% | 78.66% | 6.32% (16) | 5.53% (14) | 1.58% (4) | 11.85% | -9.86% |  |
| PROGRESSED → PROGRESSED | 0 | 0/0/0 | — (0) | — (0) | — | — | — (0) | — (0) | — (0) | — | — | 표본 작음 |
| UNAVAILABLE → PROGRESSED | 81 | 81/74/7 | 69.14% (56) | 22.22% (18) | 9.55% | 72.97% | 9.46% (7) | 12.16% (9) | 5.41% (4) | 8.64% | -15.58% |  |

경로의 `NORMAL 첫 도달`·`DEEP 첫 도달`은 raw 후보의 첫 target-state 결과야. 중앙 도달 세션 수와 전체 수익 분포는 `previous_stage_summary.csv`에 있고, 모든 실현 threshold 건수/비율·MFE·MAE·보유기간은 같은 표에 포함했어.

## DEEP 도달 cohort

| 이전 Stage | 체결 | DEEP 도달 | 체결 대비 | DEEP 도달 실현 승률 | 평균/중앙 수익 | 평균/중앙 MAE | DEEP 도달 미청산 | 미청산/DEEP |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WEAK | 115 | 44 | 38.26% | 17.14% | -19.87%/-20.15% | -60.41%/-58.66% | 9 | 20.45% |
| BASE | 43 | 9 | 20.93% | 28.57% | -15.58%/-7.64% | -50.16%/-49.91% | 2 | 22.22% |
| TRANSITION | 306 | 55 | 17.97% | 20.93% | -22.87%/-21.29% | -59.49%/-60.41% | 12 | 21.82% |
| EARLY_TREND | 287 | 52 | 18.12% | 15.79% | -19.95%/-19.20% | -62.53%/-62.80% | 14 | 26.92% |
| PROGRESSED | 0 | 0 | — | — | —/— | —/— | 0 | — |
| UNAVAILABLE | 81 | 23 | 28.40% | 11.11% | -22.43%/-28.42% | -72.01%/-72.73% | 5 | 21.74% |

## 손실·winner의 이전 Stage 분포

아래 표는 cohort 내 stage 구성비와 해당 Stage의 적격 거래 중 cohort 비율을 함께 기록해. cutoff open tail은 exact cutoff 평가 가능한 미청산만 분모로 삼았어.

| Cohort | 이전 Stage | cohort 내 건수 | cohort 구성비 | stage 내 발생률 | 분모 |
|---|---|---:|---:|---:|---:|
| DEEP_REACHED | WEAK | 44 | 24.04% | 38.26% | 115 |
| DEEP_REACHED | BASE | 9 | 4.92% | 20.93% | 43 |
| DEEP_REACHED | TRANSITION | 55 | 30.05% | 17.97% | 306 |
| DEEP_REACHED | EARLY_TREND | 52 | 28.42% | 18.12% | 287 |
| DEEP_REACHED | PROGRESSED | 0 | 0.00% | — | 0 |
| DEEP_REACHED | UNAVAILABLE | 23 | 12.57% | 28.40% | 81 |
| REALIZED_LE_30 | WEAK | 12 | 22.64% | 11.65% | 103 |
| REALIZED_LE_30 | BASE | 2 | 3.77% | 5.13% | 39 |
| REALIZED_LE_30 | TRANSITION | 16 | 30.19% | 5.78% | 277 |
| REALIZED_LE_30 | EARLY_TREND | 14 | 26.42% | 5.53% | 253 |
| REALIZED_LE_30 | PROGRESSED | 0 | 0.00% | — | 0 |
| REALIZED_LE_30 | UNAVAILABLE | 9 | 16.98% | 12.16% | 74 |
| REALIZED_LE_50 | WEAK | 5 | 23.81% | 4.85% | 103 |
| REALIZED_LE_50 | BASE | 1 | 4.76% | 2.56% | 39 |
| REALIZED_LE_50 | TRANSITION | 7 | 33.33% | 2.53% | 277 |
| REALIZED_LE_50 | EARLY_TREND | 4 | 19.05% | 1.58% | 253 |
| REALIZED_LE_50 | PROGRESSED | 0 | 0.00% | — | 0 |
| REALIZED_LE_50 | UNAVAILABLE | 4 | 19.05% | 5.41% | 74 |
| OPEN_MARK_LE_30 | WEAK | 5 | 16.67% | 71.43% | 7 |
| OPEN_MARK_LE_30 | BASE | 2 | 6.67% | 50.00% | 4 |
| OPEN_MARK_LE_30 | TRANSITION | 8 | 26.67% | 33.33% | 24 |
| OPEN_MARK_LE_30 | EARLY_TREND | 12 | 40.00% | 40.00% | 30 |
| OPEN_MARK_LE_30 | PROGRESSED | 0 | 0.00% | — | 0 |
| OPEN_MARK_LE_30 | UNAVAILABLE | 3 | 10.00% | 75.00% | 4 |
| OPEN_MARK_LE_50 | WEAK | 4 | 16.00% | 57.14% | 7 |
| OPEN_MARK_LE_50 | BASE | 2 | 8.00% | 50.00% | 4 |
| OPEN_MARK_LE_50 | TRANSITION | 6 | 24.00% | 25.00% | 24 |
| OPEN_MARK_LE_50 | EARLY_TREND | 10 | 40.00% | 33.33% | 30 |
| OPEN_MARK_LE_50 | PROGRESSED | 0 | 0.00% | — | 0 |
| OPEN_MARK_LE_50 | UNAVAILABLE | 3 | 12.00% | 75.00% | 4 |
| REALIZED_GE_20 | WEAK | 27 | 12.00% | 26.21% | 103 |
| REALIZED_GE_20 | BASE | 8 | 3.56% | 20.51% | 39 |
| REALIZED_GE_20 | TRANSITION | 86 | 38.22% | 31.05% | 277 |
| REALIZED_GE_20 | EARLY_TREND | 82 | 36.44% | 32.41% | 253 |
| REALIZED_GE_20 | PROGRESSED | 0 | 0.00% | — | 0 |
| REALIZED_GE_20 | UNAVAILABLE | 22 | 9.78% | 29.73% | 74 |
| REALIZED_GE_50 | WEAK | 5 | 11.11% | 4.85% | 103 |
| REALIZED_GE_50 | BASE | 0 | 0.00% | 0.00% | 39 |
| REALIZED_GE_50 | TRANSITION | 17 | 37.78% | 6.14% | 277 |
| REALIZED_GE_50 | EARLY_TREND | 16 | 35.56% | 6.32% | 253 |
| REALIZED_GE_50 | PROGRESSED | 0 | 0.00% | — | 0 |
| REALIZED_GE_50 | UNAVAILABLE | 7 | 15.56% | 9.46% | 74 |
| REALIZED_GE_100 | WEAK | 1 | 14.29% | 0.97% | 103 |
| REALIZED_GE_100 | BASE | 0 | 0.00% | 0.00% | 39 |
| REALIZED_GE_100 | TRANSITION | 3 | 42.86% | 1.08% | 277 |
| REALIZED_GE_100 | EARLY_TREND | 3 | 42.86% | 1.19% | 253 |
| REALIZED_GE_100 | PROGRESSED | 0 | 0.00% | — | 0 |
| REALIZED_GE_100 | UNAVAILABLE | 0 | 0.00% | 0.00% | 74 |

## 미청산 cutoff tail

| 이전 Stage | 체결 | 미청산 | 미청산률 | exact 평가 | 미해결 | 평가 평균/중앙 | -30% 이하 | -50% 이하 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| WEAK | 115 | 12 | 10.43% | 7 | 5 | -42.27%/-51.31% | 5 (71.43%) | 4 (57.14%) |
| BASE | 43 | 4 | 9.30% | 4 | 0 | -32.21%/-38.29% | 2 (50.00%) | 2 (50.00%) |
| TRANSITION | 306 | 29 | 9.48% | 24 | 5 | -18.94%/-12.90% | 8 (33.33%) | 6 (25.00%) |
| EARLY_TREND | 287 | 34 | 11.85% | 30 | 4 | -31.28%/-22.45% | 12 (40.00%) | 10 (33.33%) |
| PROGRESSED | 0 | 0 | — | 0 | 0 | —/— | 0 (—) | 0 (—) |
| UNAVAILABLE | 81 | 7 | 8.64% | 4 | 3 | -22.73%/-78.80% | 3 (75.00%) | 3 (75.00%) |

## PROGRESSED 체류기간 분포

단위는 KRX 거래 세션이며, 분포 진단만 했어.

| cohort | n | mean | median | P25 | P75 | P90 | min–max |
|---|---:|---:|---:|---:|---:|---:|---:|
| ALL_RAW_SIGNALS | 835 | 126.3 | 83.0 | 21.0 | 188.5 | 308.0 | 0.0–922.0 |
| FILLED_TRADES | 832 | 126.7 | 83.0 | 21.0 | 191.8 | 308.0 | 0.0–922.0 |
| REALIZED_WINNER | 570 | 127.5 | 101.0 | 21.0 | 200.8 | 306.1 | 0.0–738.0 |
| REALIZED_LOSER | 175 | 137.0 | 83.0 | 18.5 | 224.0 | 341.4 | 0.0–922.0 |
| REALIZED_GE_50 | 45 | 113.0 | 83.0 | 0.0 | 203.0 | 265.2 | 0.0–452.0 |
| REALIZED_LE_30 | 53 | 152.3 | 101.0 | 18.0 | 267.0 | 365.0 | 0.0–596.0 |
| REALIZED_LE_50 | 21 | 160.7 | 83.0 | 39.0 | 247.0 | 388.0 | 0.0–596.0 |
| DEEP_REACHED | 183 | 125.7 | 60.0 | 0.0 | 204.0 | 329.8 | 0.0–922.0 |
| OPEN_AT_CUTOFF | 86 | 100.8 | 61.0 | 22.0 | 161.0 | 232.5 | 0.0–425.0 |

## 판정 및 필수 질문

- 판정은 `PATTERN_B_PROGRESSED_PREVIOUS_STAGE_PROMISING`야. `WEAK → PROGRESSED`는 raw 118건, 체결 115건·실현 103건으로 충분한 표본에서 TRANSITION/EARLY_TREND보다 중앙수익·승률·NORMAL 첫 도달률이 낮고 DEEP 첫 도달과 -30%/-50% 실현손실률은 높았어. +20%와 +50% winner 발생률도 더 낮아 방향이 대체로 일치해.
- 다만 `UNAVAILABLE → PROGRESSED`도 손실 위험이 높았고 +50% 실현률도 가장 높아 양쪽 tail이 함께 보여. 이를 다른 Stage와 합치지 않았으며, `WEAK` 후보의 cutoff open exact mark는 7건뿐(미해결 5건)이므로 미청산 통계는 주의해서 봐야 해.
- 큰 실현 손실(-30/-50)과 cutoff open loss의 집중 여부는 위 stage 구성비뿐 아니라 각 Stage 내부 발생률을 같이 봐야 해. 작은 group은 과해석하지 않아.
- 체류기간은 winner·loser·tail·DEEP·open 분포를 서술적으로 비교했을 뿐, threshold·bin·최적 구간은 만들지 않았어.
- `PROMISING`인 경우에만 한 개의 exact 전이를 후속 후보로 제안할 수 있어. `MIXED`/`WEAK`이면 이전 Stage 조합 연구를 중단하고 이번 작업에서는 후속 백테스트를 실행하지 않아.
- 단일 후속 후보: `WEAK -> PROGRESSED`를 위험 필터 후보로 평가해. 개선 여부와 winner 손실은 별도 단순 백테스트에서 확인해야 하며 이번 작업에서는 실행하지 않았어.

> `DEPRESSED + PROGRESSED`의 성과와 tail risk를 현재 PROGRESSED 이전의 Pattern A Stage가 실제로 구분하는가?
> 판정: `PATTERN_B_PROGRESSED_PREVIOUS_STAGE_PROMISING`. 이전 Stage별 exact 표와 tail/winner cohort 발생률을 기준으로 답했어.

> 단 하나의 `이전 Stage -> PROGRESSED` 전이를 다음 백테스트 후보로 넘길 근거가 충분한가?
> 있어: `WEAK -> PROGRESSED`. 위험 필터 후보로만 넘기며 이번 작업에서 후속 백테스트는 실행하지 않았어.

## 검증

- raw candidate key/linkage: 835, mismatch 0; independent trade link 832/832.
- Entry-date Stage 재계산 mismatch 0; 미래 Pattern A 입력 0; 음수 체류기간 0; NORMAL/DEEP first collision 0.
- 이전 Stage UNAVAILABLE 81; randomized direct review 30/30; same-ISU trade key duplicates 0.
- Repository V2 tickers 633, OHLC rows 2,216,612, silent inner drops 0; workers 10.
- 관련 `py_compile`, focused tests, `git diff --check` 실행. 전체 pytest는 실행하지 않았어.

## 산출물

`previous_stage_summary.csv`, `candidate_signal_stage_history.csv`, `pattern_a_stage_history_snapshots.csv`, `deep_arrival_by_previous_stage.csv`, `failure_cohort_previous_stage.csv`, `winner_cohort_previous_stage.csv`, `open_position_by_previous_stage.csv`, `progressed_duration_distribution.csv`, `random_review_30.csv`, `summary.json`, `metadata.json`.
