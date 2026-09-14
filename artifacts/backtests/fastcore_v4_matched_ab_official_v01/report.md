# FastCore V4 공식 동일 진입 matched A/B 결과

## 실행 상태

- 상태: `COMPLETE`
- 기간: `2021-04-01` ~ `2026-08-21` 지원, signal cutoff `2026-08-14`, 최종 평가 `2026-08-21 CLOSE`
- matched 거래: `973` / 고유 종목: `542`
- entry signal / execution / open 일치: `973` / `973` / `973`
- 네트워크 요청: `0`
- adjusted analytic authority에 없는 raw-only 행 명시적 제외: `1`

## V2 / V4 핵심 지표

| 지표 | V2 | V4 |
|---|---:|---:|
| mean terminal return | 8.860421 | 7.210051 |
| median terminal return | -15.14 | -2.23 |
| positive rate | 30.524152% | 44.912641% |
| mean MAE | -16.049856 | -15.836074 |
| median MAE | -16.48 | -16.18 |
| median holding | 85.0 | 80.0 |
| P90 holding | 322.6 | 243.8 |
| OPEN_AT_CUTOFF | 89 (9.146968%) | 29 (2.980473%) |
| <= -30% | 16 (1.644399%) | 40 (4.110997%) |
| <= -40% | 7 (0.719424%) | 12 (1.233299%) |
| >= +50% | 160 | 75 |
| >= +100% | 57 | 30 |
| mean giveback | 36.471418 | 37.688962 |
| median giveback | 25.05 | 28.67 |

## Paired 결과

- mean V4 - V2 delta: `-1.65037`
- median V4 - V2 delta: `0.0`
- improved / worsened / same: `387 / 471 / 115`

## Repair Gate

- Pre-Winner: `PRE_WINNER_REPAIR_PASS`; checks={'tail_le_30_rate_lt_v3': True, 'tail_le_40_rate_lt_v3': True, 'median_holding_lt_v3': True, 'open_at_cutoff_rate_lt_v3': True}
- Winner Tail: `WINNER_TAIL_REPAIR_PASS`; checks={'v2_ge_50_v4_lt_50_lt_133': True, 'v2_ge_100_v4_lt_100_lt_48': True}

## 사전등록 판정

- Path A / B / C: `False` / `False` / `False`
- large-loss worsened: `True`
- capital-lock worsened: `False`
- Risk Block: `False`
- OFFICIAL_ADOPTION_ELIGIBLE: `False`
- default promotion eligibility: `False`

## 청산 이유

| strategy | exit_reason | count | rate_pct | mean_terminal_return | median_terminal_return | mean_mfe | median_mfe | mean_mae | median_mae | mean_holding_days | median_holding_days | mean_giveback | median_giveback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | LOSS_GUARD | 590 | 60.637205 | -16.279949 | -15.875 | 12.318237 | 7.45 | -17.761864 | -17.06 | 71.023729 | 40.0 | 28.598186 | 23.46 |
| V2 | EXIT3 | 39 | 4.008222 | 9.951795 | -6.01 | 106.99 | 50.97 | -22.141282 | -17.92 | 311.051282 | 224.0 | 97.038205 | 60.41 |
| V2 | EXIT4 | 255 | 26.207605 | 60.794078 | 53.82 | 93.902902 | 79.5 | -10.719882 | -9.18 | 221.494118 | 150.0 | 33.108824 | 24.8 |
| V2 | OPEN_AT_CUTOFF | 89 | 9.146968 | 26.244382 | 9.28 | 98.003034 | 57.74 | -17.302584 | -13.91 | 381.168539 | 271.0 | 71.758652 | 44.52 |
| V4 | PRE_WINNER_PRICE_STRUCTURE_FAILURE | 414 | 42.548818 | -20.798986 | -18.325 | 7.630145 | 6.745 | -23.878213 | -21.785 | 95.782609 | 71.0 | 28.42913 | 27.255 |
| V4 | WINNER_SOFT_WATCH_EXIT | 68 | 6.988695 | 32.325441 | 18.785 | 61.445882 | 36.995 | -8.795735 | -7.945 | 239.426471 | 190.0 | 29.120441 | 22.575 |
| V4 | WINNER_HARD_EXIT | 462 | 47.482014 | 29.064113 | 10.575 | 77.858268 | 42.245 | -9.791732 | -8.29 | 110.898268 | 80.0 | 48.794156 | 30.425 |
| V4 | OPEN_AT_CUTOFF | 29 | 2.980473 | 0.014138 | -2.71 | 13.069655 | 8.29 | -13.828621 | -13.01 | 93.724138 | 82.0 | 13.055517 | 11.18 |

## MDD와 한계

- MDD: `NOT_EVALUATED` — 고정 trade replay에 확정된 공통 포트폴리오 구성 규칙이 없어 새 모델을 만들지 않음
- V3는 기존 공식 결과를 Repair 기준선과 대표 사례 비교용으로만 읽었으며 재실행하지 않음
- 이 결과는 V4의 기계적 자격 판정이며, 공식 채택·기본 전략 승격 결정이 아님
