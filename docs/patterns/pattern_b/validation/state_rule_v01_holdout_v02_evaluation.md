# Pattern B 상태 판정 규칙 V01 — 별도 검증 표본 V02 공식 평가

> 상태: 공식 1회 평가 완료. 별도 검증 표본 V02는 상태 판정 규칙 V01의 독립 검증에
> 사용되어 소진됐다. 이 결과를 보고 규칙을 고치면, 고친 규칙의 독립 검증에는 새
> 별도 검증 표본(V03)이 필요하다.

이 문서는 `scripts/evaluate_pattern_b_state_rule_v01_holdout_v02.py`가 계산과 함께 생성한다.

## 1. 목적과 입력

봉인된 [상태 판정 규칙 V01](state_rule_v01.md)(규칙안 C)을 봉인된 [별도 검증 표본 V02 원시 지표값](feature_raw_values_v02.md)에 그대로 적용하고, 봉인된 [사람 판정 V02](human_ground_truth_v02.md)와 한 번 비교한다.

- 세 봉인(규칙 코드, 원시 지표값, 사람 판정)의 SHA-256을 평가 전에 확인했다.
- 36개 자동 판정을 모두 만든 뒤에 사람 판정과 결합했다.
- 규칙, 임계값, 사람 판정, 지표값은 바꾸지 않았다.
- 순서 값: `DEEP_DEPRESSED`=−2, `DEPRESSED`=−1, `NORMAL`=0, `OVERHEATED`=+1, `EXTREME_OVERHEATED`=+2. 순서 오차 = 자동 − 사람.

## 2. 전체 36개

| 지표 | 값 |
|---|---|
| 정확 일치 | 12/36 (0.3333) |
| 1단계 이내 일치 | 29/36 (0.8056) |
| 순서 평균절대오차 | 0.9722 |
| 2단계 이상 오류 | 7 |
| 3단계 이상 오류 | 4 |

## 3. 높은 신뢰도(`HIGH`)만

| 지표 | 값 |
|---|---|
| 표본 수 | 22 |
| 정확 일치 | 7/22 (0.3182) |
| 순서 평균절대오차 | 0.8636 |
| 2단계 이상 오류 | 2 |

## 4. 혼동 행렬

행은 사람 판정, 열은 자동 판정이다.

| 사람 \ 자동 | DEEP | DEP | NORM | OVH | EXT |
|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | 4 | 2 | 0 | 0 |
| `DEPRESSED` | 0 | 4 | 2 | 0 | 0 |
| `NORMAL` | 1 | 1 | 4 | 2 | 0 |
| `OVERHEATED` | 0 | 0 | 5 | 2 | 0 |
| `EXTREME_OVERHEATED` | 0 | 4 | 0 | 3 | 0 |

## 5. 방향 편향

| 구분 | 표본 수 |
|---|---|
| 자동 판정이 더 침체 쪽 (오차 < 0) | 14 |
| 일치 (오차 = 0) | 12 |
| 자동 판정이 더 과열 쪽 (오차 > 0) | 10 |
| 평균 부호 오차 | -0.3056 |

## 6. 극단 상태 (사람 판정 기준)

| 사람 판정 | 표본 수 | 정확 일치 | 1단계 이내 | 2단계 이상 오류 |
|---|---|---|---|---|
| `DEEP_DEPRESSED` | 8 | 2 | 6 | 2 |
| `EXTREME_OVERHEATED` | 7 | 0 | 3 | 4 |
| 두 극단 합계 | 15 | 2 | 9 | 6 |

## 7. 2단계 이상 오류 표본

| sample_id | 사람 판정 | 자동 판정 | 신뢰도 | 순서 오차 |
|---|---|---|---|---|
| `PBHOLD_012` | `DEEP_DEPRESSED` | `NORMAL` | `MEDIUM` | +2 |
| `PBHOLD_017` | `NORMAL` | `DEEP_DEPRESSED` | `MEDIUM` | -2 |
| `PBHOLD_018` | `EXTREME_OVERHEATED` | `DEPRESSED` | `MEDIUM` | -3 |
| `PBHOLD_019` | `EXTREME_OVERHEATED` | `DEPRESSED` | `MEDIUM` | -3 |
| `PBHOLD_024` | `EXTREME_OVERHEATED` | `DEPRESSED` | `HIGH` | -3 |
| `PBHOLD_026` | `DEEP_DEPRESSED` | `NORMAL` | `MEDIUM` | +2 |
| `PBHOLD_028` | `EXTREME_OVERHEATED` | `DEPRESSED` | `HIGH` | -3 |

## 8. 3단계 이상 오류 표본

| sample_id | 사람 판정 | 자동 판정 | 신뢰도 | 순서 오차 |
|---|---|---|---|---|
| `PBHOLD_018` | `EXTREME_OVERHEATED` | `DEPRESSED` | `MEDIUM` | -3 |
| `PBHOLD_019` | `EXTREME_OVERHEATED` | `DEPRESSED` | `MEDIUM` | -3 |
| `PBHOLD_024` | `EXTREME_OVERHEATED` | `DEPRESSED` | `HIGH` | -3 |
| `PBHOLD_028` | `EXTREME_OVERHEATED` | `DEPRESSED` | `HIGH` | -3 |

## 9. 산출물과 이후 절차

- 표본별 결과: [state_rule_v01_holdout_v02_predictions.csv](state_rule_v01_holdout_v02_predictions.csv)
- 봉인: [state_rule_v01_holdout_v02_evaluation_seal.json](state_rule_v01_holdout_v02_evaluation_seal.json)
- 이 평가는 한 번만 수행했다. 채택 여부와 이후 연구 방향은 이 문서의 범위가 아니다.
