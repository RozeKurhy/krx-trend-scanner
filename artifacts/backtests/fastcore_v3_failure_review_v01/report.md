# FastCore V3 공식 A/B 실패 사례 검토

## 결론 요약

- V3 전체: `OFFICIAL_ADOPTION_FAILED`
- Pre-Winner: `PRIMARY_FAILURE_SOURCE`
- Winner HWM: `PROMISING_WITH_TAIL_COST`
- 후속 연구 가치: `NEW_CANDIDATE_JUSTIFIED`

공식 matched A/B 973건은 재실행하거나 수정하지 않고 불변 입력으로 사용했다. 이번 문서는 V3 규칙이나 새 후보를 설계하지 않는 실패 원인 진단이다.

## 공식 A/B 결과 요약

- Pre-Winner: `236`건
- Winner-capable: `737`건
- V2/V3 mean return: `8.860421% / 8.666341%`
- V2/V3 median return: `-15.14% / 9.2%`
- V2/V3 <= -30%: `16 / 139`
- V2/V3 >= +50%: `160 / 50`

## Pre-Winner 문제

V3 Pre-Winner 236건은 모두 +20% activation에 도달하지 않았고, V3에서는 `236/236`건이 OPEN_AT_CUTOFF로 남았다.

| threshold | cohort | breach rate | median days | P25 | P75 | no breach |
|---:|---|---:|---:|---:|---:|---:|
| -30.0% | PRE_WINNER_LT_20 | 75.847458% | 112.0 | 65.5 | 230.0 | 57 |
| -20.0% | PRE_WINNER_LT_20 | 88.559322% | 64.0 | 30.0 | 117.0 | 27 |
| -15.0% | PRE_WINNER_LT_20 | 93.220339% | 35.0 | 18.0 | 76.25 | 16 |
| -10.0% | PRE_WINNER_LT_20 | 95.338983% | 19.0 | 8.0 | 44.0 | 11 |
| -30.0% | WINNER_CAPABLE_GE_20_BEFORE_ACTIVATION | 15.87517% | 104.0 | 52.0 | 205.0 | 620 |
| -20.0% | WINNER_CAPABLE_GE_20_BEFORE_ACTIVATION | 28.222524% | 47.5 | 25.0 | 112.25 | 529 |
| -15.0% | WINNER_CAPABLE_GE_20_BEFORE_ACTIVATION | 39.077341% | 29.0 | 15.0 | 67.0 | 449 |
| -10.0% | WINNER_CAPABLE_GE_20_BEFORE_ACTIVATION | 51.83175% | 19.0 | 9.0 | 41.0 | 355 |

Trading days are zero-based from the entry execution day. Winner-capable rows are measured strictly before their first +20% activation date.

## 미래 Winner와의 구분 가능성

진단용 손실선은 규칙 선택이나 threshold optimization에 사용하지 않았다. 같은 표의 Winner-capable pre-activation 행은 최종적으로 +20% activation에 도달한 737건의 activation 이전 경로만 나타낸다.

## Winner HWM 성과

- Winner-capable mean return V2/V3: `16.595617% / 23.396296%`
- Winner-capable median return V2/V3: `-14.29% / 13.95%`
- paired mean/median delta: `6.800678% / 20.09%`
- V2/V3 >= +50%: `160 / 50`
- V2/V3 >= +100%: `57 / 24`
- improved/worsened/same: `512 / 222 / 3`

| V3 exit reason | count | V3 mean return | V3 median return | paired mean delta | V2 >= +50 | V2 >= +100 | V3 >= +50 | V3 >= +100 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| SOFT_EXIT | 498 | 17.599759 | 13.39 | 1.853233 | 110 | 35 | 14 | 5 |
| HARD_EXIT | 236 | 35.424661 | 15.125 | 17.221398 | 49 | 22 | 35 | 19 |
| OPEN_AT_CUTOFF | 3 | 39.39 | 22.3 | 8.313333 | 1 | 0 | 1 | 0 |

## 대형 Winner 훼손

- `V2_GE_50_V3_LT_50`: `133`건, paired mean/median delta `-80.592857% / -62.69%`, V3 exit reason `{'HARD_EXIT': 28, 'SOFT_EXIT': 105}`
- `V2_GE_100_V3_LT_100`: `48`건, paired mean/median delta `-143.10875% / -116.6%`, V3 exit reason `{'HARD_EXIT': 14, 'SOFT_EXIT': 34}`

대표 최악 사례와 전체 deterministic 목록은 `winner_side_effect_diagnostics.csv`에 기록했다.

## V2 청산 사유와 full-path 결과

`pre_winner_threshold_diagnostics.csv`와 함께 공식 matched 입력의 V2 청산 사유 교차표는 summary.json의 `v2_exit_cross_tab`에 보존했다. 특히 V2 Loss Guard로 종료된 Winner-capable 거래 수는 `387`건이다.

## 종합 판단

- Pre-Winner 분류: `PRIMARY_FAILURE_SOURCE` — 236건 전부 activation 없이 V3 OPEN_AT_CUTOFF에 남았고, V3 terminal loss와 holding이 V2보다 크게 악화됐다.
- Winner HWM 분류: `PROMISING_WITH_TAIL_COST` — Winner-capable 평균·중앙값과 giveback 일부는 개선됐지만 +50%/+100% 대형 Winner가 줄고 큰 훼손 집합이 확인됐다.
- 후속 연구: `NEW_CANDIDATE_JUSTIFIED` — Pre-Winner 보호와 Winner 보존을 분리한 다음 후보 연구의 근거는 있으나, 이번 작업에서는 새 규칙을 설계하지 않는다.

이번 작업에서는 구체적인 stop threshold, FAST state 조합, V4/V3.1 규칙을 확정하지 않았고 기존 V3도 수정하지 않았다.

## 실행 제한 및 무결성

- network requests: `0`
- 공식 A/B rerun: `NO`
- V3 rule change: `NO`
- new candidate design: `NO`
- official artifact modified: `False`
