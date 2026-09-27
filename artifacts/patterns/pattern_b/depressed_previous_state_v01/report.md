# Pattern B DEPRESSED 진입 이전 상태 진단 V01

판정: **PATTERN_B_PREVIOUS_STATE_SIGNAL_MIXED**

## 범위와 방법

- 기존 raw Pattern B DEPRESSED 진입 20,076건과 기존 pure-strategy 신호·거래 원장을 연결했어. 새 진입 전략이나 전체 시장 재생은 하지 않았어.
- 직전 상태는 같은 PIT identity component에서 진입 신호일 전 마지막으로 관측한 non-DEPRESSED 상태야. 이후 경로는 월별 Pattern B 상태 관측 frontier 2026-08-31까지만 분류했고, cutoff 2026-09-21은 기존 미청산 평가를 그대로 연결했어.
- NORMAL_FIRST / DEEP_DEPRESSED_FIRST는 신호 후 둘 중 어느 상태가 먼저 관측됐는지를 뜻해. 둘 다 frontier까지 없으면 `NEITHER_BY_STATE_FRONTIER`로 분류했어. 두 도달 소요일은 각각 첫 상태 관측까지 merged KRX 거래일 차이야.
- 실현 수익·MFE·MAE·보유기간은 연결된 기존 실현 원장만, 평가수익은 exact cutoff close가 있는 기존 미청산만 사용했어.

## 핵심 전이 비교

| 이전 상태 → DEPRESSED | N | NORMAL 선도달 | DEEP 선도달 | 중앙수익 | 승률 | +50% | -30% | -50% | 미청산 비율 | 중앙 MAE |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NORMAL -> DEPRESSED | 12,618 | 65.99% | 30.57% | 7.48% | 72.65% | 4.53% | 5.01% | 1.65% | 8.96% | -10.94% |
| DEEP_DEPRESSED -> DEPRESSED | 7,163 | 41.83% | 50.83% | 8.16% | 67.97% | 9.46% | 8.95% | 5.17% | 22.71% | -17.64% |

## 모든 직전 상태

| 직전 상태 | 신호 | 전체 비중 | 체결 | 실현 | 미청산 | 미청산률 | NORMAL 선도달 | DEEP 선도달 | 둘 다 미도달 | NORMAL 중앙 거래일 | DEEP 중앙 거래일 | 중앙수익 | 승률 | +50% | -30% | -50% | 평가 미해결 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| NORMAL | 12,618 | 62.85% | 12,618 | 11,488 | 1,130 | 8.96% | 65.99% | 30.57% | 3.45% | 64.00 | 244.00 | 7.48% | 72.65% | 4.53% | 5.01% | 1.65% | 195 |
| DEEP_DEPRESSED | 7,163 | 35.68% | 1,026 | 793 | 233 | 22.71% | 41.83% | 50.83% | 7.34% | 126.00 | 82.00 | 8.16% | 67.97% | 9.46% | 8.95% | 5.17% | 47 |
| OVERHEATED | 244 | 1.22% | 218 | 141 | 77 | 35.32% | 55.74% | 17.21% | 27.05% | 41.00 | 266.50 | 15.04% | 89.36% | 6.38% | 4.26% | 1.42% | 7 |
| EXTREME_OVERHEATED | 51 | 0.25% | 48 | 32 | 16 | 33.33% | 43.14% | 27.45% | 29.41% | 145.00 | 244.00 | 7.62% | 62.50% | 12.50% | 12.50% | 3.12% | 2 |
| DEPRESSED | 0 | 0.00% | 0 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0 |
| UNAVAILABLE | 0 | 0.00% | 0 | 0 | 0 | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | n/a | 0 |

## 미청산 cutoff 평가

| 직전 상태 | 미청산 | cutoff exact 평가 | 평가 미해결 | 평균/중앙 평가수익 | -30% 이하 | -50% 이하 |
|---|---:|---:|---:|---:|---:|---:|
| NORMAL | 1,130 | 935 | 195 | -22.66% / -16.97% | 334 (35.72%) | 192 (20.53%) |
| DEEP_DEPRESSED | 233 | 186 | 47 | -14.92% / -3.00% | 54 (29.03%) | 33 (17.74%) |
| OVERHEATED | 77 | 70 | 7 | -3.09% / -1.92% | 7 (10.00%) | 5 (7.14%) |
| EXTREME_OVERHEATED | 16 | 14 | 2 | -12.29% / -8.02% | 2 (14.29%) | 1 (7.14%) |
| DEPRESSED | 0 | 0 | 0 | n/a / n/a | 0 (n/a) | 0 (n/a) |
| UNAVAILABLE | 0 | 0 | 0 | n/a / n/a | 0 (n/a) | 0 (n/a) |

## 핵심 질문 답변

1. **성과가 다른가?** 이후 상태 경로와 체결 거래 지표가 모두 달라. NORMAL 선행은 NORMAL이 먼저 관측된 비율이 65.99%로 DEEP 선행 41.83%보다 높고, DEEP가 먼저 관측된 비율은 30.57% 대 50.83%야. 실현 수익 지표의 방향은 서로 엇갈려.
2. **NORMAL 회복 선도달률이 높은 쪽?** NORMAL 선행이 65.99%로 DEEP 선행 41.83%보다 높아. 중앙 도달 기간도 64.00 거래일 대 126.00 거래일이야.
3. **DEEP 재하락 선도달률이 낮은 쪽?** NORMAL 선행이 30.57%로 DEEP 선행 50.83%보다 낮아. 이 비율은 NORMAL보다 DEEP가 먼저 관측된 경우를 세며, 관측 frontier까지의 어느 시점이든 DEEP를 한 번이라도 본 비율과는 달라.
4. **실현 수익 지표가 좋은 쪽?** 중앙수익은 DEEP 선행 8.16% 대 NORMAL 선행 7.48%, 승률은 NORMAL 선행 72.65% 대 67.97%, +50% 비율은 DEEP 선행 9.46% 대 4.53%야.
5. **손실 위험이 낮은 쪽?** 실현 -30% / -50% 비율은 NORMAL 선행 5.01% / 1.65%, DEEP 선행 8.95% / 5.17%로 NORMAL 선행이 낮아. cutoff exact 평가가 가능한 미청산만 보면 -30% / -50% 꼬리는 NORMAL 선행 35.72% / 20.53%, DEEP 선행 29.03% / 17.74%로 DEEP 선행이 낮아. 각각 평가 미해결은 195건과 47건이야.
6. **이전 상태가 방향 정보를 더하나?** 회복/악화 경로는 구분하지만 수익·손실·미청산 지표가 한쪽으로 정렬되지 않아, 일관된 매매 방향 정보가 확인됐다고 보기는 어려워. 실현 통계는 기존 전략에서 실제 체결된 거래만 대상으로 하며, NORMAL 선행 신호는 12,618/12,618건 체결, DEEP 선행은 1,026/7,163건 체결됐어. DEEP 선행 raw 신호 6,137건은 기존 보유 중이라 억제됐으므로 실현 성과 비교에는 체결 선택 편향이 있어.
7. **특정 전이 단독 백테스트 근거가 충분한가?** 현재 판정은 `PATTERN_B_PREVIOUS_STATE_SIGNAL_MIXED`라서 충분하지 않아. 사후 기준을 추가하거나 자동 후속 백테스트를 실행하지 않았어.

## 해석 및 다음 단계

- 기준 상태 차이 요약: {"lower_deep_first_rate_better_group": "NORMAL_PRIOR", "median_return_better_group": "DEEP_PRIOR", "normal_first_rate_better_group": "NORMAL_PRIOR", "open_le_30_tail_better_group": "DEEP_PRIOR", "open_le_50_tail_better_group": "DEEP_PRIOR", "path_direction_group": "NORMAL_PRIOR", "plus_50_rate_better_group": "DEEP_PRIOR", "quality_direction_group": null, "realized_le_30_tail_better_group": "NORMAL_PRIOR", "realized_le_50_tail_better_group": "NORMAL_PRIOR", "risk_direction_group": null, "win_rate_better_group": "NORMAL_PRIOR"}
- MIXED 결과이므로 특정 전이를 확정 후보로 승격하지 않아.

## 검증

- raw 신호 원장 연결 누락 0; 중복 0; 이전 상태 미확인 0.
- 전체 신호에서 first NORMAL/DEEP 동일 날짜 충돌 0; 미래 이전 상태 입력 0; 기존 trade 연결 누락 0.
- 무작위 직접 검수 40/40 통과. 기존 원장 lineage는 metadata에 기록했어.

## 산출물

`state_group_summary.csv`, `core_transition_comparison.csv`, `signal_trade_path_linkage.csv`, `normal_deep_path_classification.csv`, `open_position_comparison.csv`, `signal_status_by_previous_state.csv`, `direct_review_sample.csv`, `summary.json`, `metadata.json`.
