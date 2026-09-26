# Pattern B 상태 규칙 V01

> 상태: 설계·봉인 완료. Holdout 평가 전이며, Holdout을 열기 전에는 이 규칙과 임계값을
> 고치지 않는다. 전략·매매 규칙·백테스트는 없다.

## 1. 목적과 입력

봉인된 [사람 판정 V01](human_ground_truth_labels_v01.csv) 36개와
[raw Feature V01](feature_raw_values_v01.csv)을 `sample_id`로 결합하고,
[Feature 선택 V01](feature_selection_v01.md)의 KEEP Feature 3개만으로 5단계 자동 상태
규칙을 정한다.

- 월봉 핵심: `36M_RANGE_POSITION`, `MONTHLY_MA24_DISTANCE`
- 주봉 보조: `52W_RANGE_POSITION`
- 출력 상태: `DEEP_DEPRESSED`, `DEPRESSED`, `NORMAL`, `OVERHEATED`, `EXTREME_OVERHEATED`
  (`UNCERTAIN`은 출력하지 않는다)

순위 비교에는 `DEEP_DEPRESSED`=0 ~ `EXTREME_OVERHEATED`=4를 쓴다. 이 숫자는 비교용
내부 표현이며 점수가 아니다.

## 2. Holdout 미접근 선언

이 설계에서는 [Holdout V02](holdout_v02_protocol.md)의 비공개 대응표, 가린 차트,
Feature, 판정을 열거나 계산하지 않았다. 설계 스크립트와 규칙 코드는 Holdout 파일을
참조하지 않는다.

## 3. 임계값 근거

규칙은 평가 전에 고정했다.

- 인접 label 쌍마다 IQR 사이에 틈이 있으면 틈의 중점, 겹치면 median 중점을 쓴다.
- 계산값은 3개 Feature 모두 0.05 단위로 반올림한다(반올림 폭은 결과를 보기 전에 정했다).
- 각 임계값은 위쪽 상태의 하한이다. 값이 임계값과 같으면 위쪽 상태로 본다.

약어: DEEP=`DEEP_DEPRESSED`, DEP=`DEPRESSED`, NORM=`NORMAL`, OVH=`OVERHEATED`,
EXT=`EXTREME_OVERHEATED`.

### `36M_RANGE_POSITION`

| 경계 | 왼쪽 median | 오른쪽 median | 왼쪽 Q3 | 오른쪽 Q1 | IQR | 근거 | 계산값 | 임계값 |
|---|---|---|---|---|---|---|---|---|
| DEEP/DEP | 0.048 | 0.090 | 0.049 | 0.087 | 틈 | IQR 틈 중점 | 0.0680 | 0.05 |
| DEP/NORM | 0.090 | 0.381 | 0.178 | 0.305 | 틈 | IQR 틈 중점 | 0.2412 | 0.25 |
| NORM/OVH | 0.381 | 0.747 | 0.589 | 0.546 | 겹침 | median 중점 | 0.5636 | 0.55 |
| OVH/EXT | 0.747 | 0.885 | 0.788 | 0.755 | 겹침 | median 중점 | 0.8159 | 0.80 |

### `MONTHLY_MA24_DISTANCE`

| 경계 | 왼쪽 median | 오른쪽 median | 왼쪽 Q3 | 오른쪽 Q1 | IQR | 근거 | 계산값 | 임계값 |
|---|---|---|---|---|---|---|---|---|
| DEEP/DEP | -0.382 | -0.228 | -0.363 | -0.318 | 틈 | IQR 틈 중점 | -0.3404 | -0.35 |
| DEP/NORM | -0.228 | -0.021 | -0.101 | -0.070 | 틈 | IQR 틈 중점 | -0.0851 | -0.10 |
| NORM/OVH | -0.021 | 0.359 | 0.132 | 0.128 | 겹침 | median 중점 | 0.1690 | 0.15 |
| OVH/EXT | 0.359 | 0.713 | 0.489 | 0.536 | 틈 | IQR 틈 중점 | 0.5125 | 0.50 |

### `52W_RANGE_POSITION`

| 경계 | 왼쪽 median | 오른쪽 median | 왼쪽 Q3 | 오른쪽 Q1 | IQR | 근거 | 계산값 | 임계값 |
|---|---|---|---|---|---|---|---|---|
| DEEP/DEP | 0.151 | 0.206 | 0.154 | 0.184 | 틈 | IQR 틈 중점 | 0.1689 | 0.15 |
| DEP/NORM | 0.206 | 0.503 | 0.255 | 0.271 | 틈 | IQR 틈 중점 | 0.2632 | 0.25 |
| NORM/OVH | 0.503 | 0.773 | 0.700 | 0.743 | 틈 | IQR 틈 중점 | 0.7211 | 0.70 |
| OVH/EXT | 0.773 | 0.840 | 0.834 | 0.676 | 겹침 | median 중점 | 0.8064 | 0.80 |

DEEP(2개)과 DEP(4개)가 걸린 경계는 표본이 적다. 36M의 0.05는 DEEP 두 값(0.044,
0.051) 사이에, MA24의 −0.35는 DEEP 두 값(−0.421, −0.343) 사이에 놓인다. 이는 미리 정한
반올림 폭과 n=2의 결과이며, 결과를 본 뒤 폭을 바꾸지 않았다.

## 4. 비교한 규칙 family

각 Feature 값을 위 임계값으로 0~4 band로 바꾼 뒤(36M=`m36`, MA24=`ma24`, 52W=`w52`)
세 가지 결합 방식을 비교했다.

- **A. 월봉 합의 + 주봉 판정 보조**: `m36`과 `ma24`가 같으면 그 상태. 한 단계 차이면
  `w52`에 더 가까운 쪽. 두 단계 이상이면 NORMAL 반대편끼리는 NORMAL, 같은 쪽이면 덜
  극단인 쪽.
- **B. 월봉 전용 보수적 교집합**: 두 월봉이 NORMAL 반대편이면 NORMAL, 아니면 덜 극단인 쪽.
  주봉은 쓰지 않는다. 지시서 문구대로 "경계에서만 주봉 보조"를 넣으면 125개 band 조합
  전부에서 A와 같은 결과가 나오므로, B는 주봉의 기여를 따로 보는 월봉 전용 비교
  기준으로 두었다(테스트로 확인).
- **C. 36M 주축 + 확인**: `m36`을 주 상태로 둔다. 극단(0·4)은 `ma24`도 같은 극단이어야
  하고, 아니면 NORMAL 쪽으로 한 단계 물러난다. NORMAL이 아닌 상태는 `ma24` 또는 `w52`가
  같은 쪽(NORMAL 아래 또는 위)에 있어야 하며, 아니면 NORMAL이다.

## 5. family별 V01 성능 (36개)

| Family | 정확 일치 | 1단계 이내 | ordinal MAE | 2단계 이상 오분류 | 3단계 이상 | HIGH 정확 일치 | HIGH MAE |
|---|---|---|---|---|---|---|---|
| A | 0.583 | 0.972 | 0.444 | 1 | 0 | 0.727 | 0.273 |
| B | 0.639 | 1.000 | 0.361 | 0 | 0 | 0.773 | 0.227 |
| C | 0.639 | 1.000 | 0.361 | 0 | 0 | 0.773 | 0.227 |

A는 `PBHGT_033`(`NORMAL`)을 `DEEP_DEPRESSED`로 두 단계 틀린다. B와 C는 모든 지표가
같고, 두 표본에서만 결과가 갈린다.

| sample_id | 사람 판정 | B | C |
|---|---|---|---|
| `PBHGT_010` | `OVERHEATED` | `NORMAL` | `OVERHEATED` |
| `PBHGT_019` | `NORMAL` | `NORMAL` | `OVERHEATED` |

두 차이는 서로 상쇄된다. 즉 V01 36개에서 주봉은 집계 성능을 바꾸지 않았다.

## 6. 최종 규칙: Family C

선택 기준(큰 오분류 → MAE → 정확 일치 → HIGH 안정성 → 단순성)에서 B와 C가 같다.
단순성만 보면 B가 앞서지만, B는 KEEP한 주봉 `52W_RANGE_POSITION`에 역할을 주지 않아
"월봉 핵심·주봉 보조" 역할 고정 원칙을 지키지 못한다. 그래서 C를 최종 규칙으로 정했다.
이 판단은 검토에서 B로 바꿀 수 있다.

코드: `src/trend_scanner/patterns/pattern_b_state_v01.py`
(`classify_pattern_b_state_v01(range_36m, monthly_ma24_distance, range_52w)`)

1. 세 값을 각각 band 0~4로 바꾼다. 값이 유한한 숫자가 아니면 오류를 낸다.
2. `m36`을 주 상태로 둔다.
3. 주 상태가 `DEEP_DEPRESSED`나 `EXTREME_OVERHEATED`면 `ma24`도 같은 극단이어야 한다.
   아니면 NORMAL 쪽으로 한 단계 물러난다.
4. 주 상태가 NORMAL이 아니면 `ma24` 또는 `w52` 중 하나가 같은 쪽에 있어야 한다.
   아니면 NORMAL이다.

성질:

- 극단 상태는 두 월봉 Feature가 모두 같은 극단일 때만 나온다.
- `m36`이 NORMAL이면 다른 값과 관계없이 NORMAL이다.
- 두 월봉이 NORMAL 반대편으로 갈리면, 주봉이 `m36` 쪽을 확인할 때만 그쪽으로 한 단계
  (예: `OVERHEATED`) 나오고, 아니면 NORMAL이다.
- 주봉은 상태를 확인하거나 NORMAL로 되돌릴 뿐, 반대편으로 뒤집거나 두 단계 이상 움직이지
  않는다. 이 규칙에서 `w52`는 0.25 미만(침체 쪽)인지, 0.70 이상(과열 쪽)인지만 쓰인다.
- 극단 상태를 두 월봉 합의로만 허용한 대가로, `EXTREME_OVERHEATED` 10개 중 4개가
  `OVERHEATED`로 나온다.

## 7. 혼동 행렬 (최종 규칙, 36개)

| 사람 판정 \ 자동 판정 | DEEP | DEP | NORM | OVH | EXT |
|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 1 | 1 | 0 | 0 | 0 |
| `DEPRESSED` | 0 | 3 | 1 | 0 | 0 |
| `NORMAL` | 0 | 1 | 7 | 4 | 0 |
| `OVERHEATED` | 0 | 0 | 2 | 6 | 0 |
| `EXTREME_OVERHEATED` | 0 | 0 | 0 | 4 | 6 |

정확 일치 0.639(23/36), 1단계 이내 1.000, ordinal MAE 0.361, 2단계 이상 오분류 0개.
HIGH만 보면 정확 일치 0.773(17/22), MAE 0.227이다. 표본별 결과는
[state_rule_v01_predictions.csv](state_rule_v01_predictions.csv)에 있다.

## 8. 오분류 사례

13개 모두 1단계 차이다. 사람 판정은 고치지 않았다.

| sample_id | 사람 판정 | confidence | 36M | MA24 | 52W | 자동 판정 |
|---|---|---|---|---|---|---|
| `PBHGT_004` | `EXTREME_OVERHEATED` | HIGH | 0.756 | 0.509 | 0.624 | `OVERHEATED` |
| `PBHGT_005` | `EXTREME_OVERHEATED` | MEDIUM | 0.755 | 0.316 | 0.722 | `OVERHEATED` |
| `PBHGT_011` | `EXTREME_OVERHEATED` | HIGH | 0.731 | 0.318 | 0.661 | `OVERHEATED` |
| `PBHGT_022` | `EXTREME_OVERHEATED` | HIGH | 0.709 | 0.734 | 0.640 | `OVERHEATED` |
| `PBHGT_006` | `NORMAL` | MEDIUM | 0.774 | 0.335 | 0.739 | `OVERHEATED` |
| `PBHGT_015` | `NORMAL` | HIGH | 0.652 | 0.320 | 0.704 | `OVERHEATED` |
| `PBHGT_019` | `NORMAL` | MEDIUM | 0.568 | 0.094 | 0.918 | `OVERHEATED` |
| `PBHGT_026` | `NORMAL` | MEDIUM | 0.703 | 0.246 | 0.698 | `OVERHEATED` |
| `PBHGT_033` | `NORMAL` | MEDIUM | 0.113 | -0.559 | 0.106 | `DEPRESSED` |
| `PBHGT_012` | `OVERHEATED` | MEDIUM | 0.522 | 0.115 | 0.217 | `NORMAL` |
| `PBHGT_016` | `OVERHEATED` | MEDIUM | 0.453 | 0.082 | 0.944 | `NORMAL` |
| `PBHGT_009` | `DEPRESSED` | MEDIUM | 0.439 | 0.031 | 0.360 | `NORMAL` |
| `PBHGT_018` | `DEEP_DEPRESSED` | HIGH | 0.051 | -0.343 | 0.157 | `DEPRESSED` |

- `EXTREME_OVERHEATED` → `OVERHEATED` 4개: 36M이 0.80 미만이라 극단 조건에 못 미친다.
- `NORMAL` → `OVERHEATED` 4개: 36M이 과열 쪽 band이고, 3개는 MA24가, `PBHGT_019`는
  52W가 과열 쪽을 확인했다. 4개 중 3개가 MEDIUM이다.
- 나머지는 MEDIUM 경계 표본과 DEEP(n=2) 경계에서 나왔다.

## 9. 표본 한계와 과적합 위험

- 임계값과 규칙은 같은 36개로 정했으므로 이 성능은 낙관적인 추정이다. 실제 성능은
  Holdout V02로만 판단한다.
- 36개는 12종목 × 기준일 3개라 같은 종목 표본끼리 독립이 아니다.
- DEEP 2개, DEP 4개(HIGH 1개)라 하단 경계는 불안정하다.
- 규칙 family는 3개로 제한했고, 원자료 전체를 정렬하는 임계값 탐색, 표본별 예외,
  0.05 미만 단위 조정은 하지 않았다.

## 10. Holdout 평가 전 봉인

이 문서, `src/trend_scanner/patterns/pattern_b_state_v01.py`,
[state_rule_v01_predictions.csv](state_rule_v01_predictions.csv)를
[state_rule_v01_seal.json](state_rule_v01_seal.json)의 SHA-256으로 봉인한다. 이후 순서는
[Holdout V02 프로토콜](holdout_v02_protocol.md)을 따른다. Holdout 결과를 본 뒤 이 규칙을
고치면 Holdout V02는 더 이상 검증 표본이 아니며, 고친 규칙은 새 검증 표본이 필요하다.

설계 스크립트: `scripts/design_pattern_b_state_rule_v01.py`
