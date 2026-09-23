# Pattern B Feature 적합성 진단 V01

> 상태: 진단 완료. 봉인된 사람 판정 V01과 raw Feature V01의 관계를 진단만 했다.
> Feature 유지·수정·제외 여부, 임계값, 가중치, 점수, 자동 상태 판정은 정하지 않았다.

이 문서는 `scripts/analyze_pattern_b_feature_fitness_v01.py`가 생성한다.

## 1. 목적과 입력

[사람 판정 V01](human_ground_truth_labels_v01.csv)과 [raw Feature V01](feature_raw_values_v01.csv)을 `sample_id`로 처음 결합해, [Feature 계약 V01](../spec/feature_contract_v01.md)의 7개 Feature가 사람의 장기 가격 사이클 판정과 어떤 관계를 보이는지 진단한다.

- 두 입력은 각각 봉인된 공개 파일이며 이번 진단에서 수정하지 않았다.
- 비공개 대응표, ticker, 기준일, 미래 수익률은 사용하지 않았다.
- 판정 순서 값(`DEEP_DEPRESSED`=0 ~ `EXTREME_OVERHEATED`=4)은 순위 진단용 내부 표현이며 점수나 상태 규칙이 아니다. 7개 Feature 모두 값이 클수록 과열 방향을 기대한다.

## 2. 결합 검증

- 결합: 36/36, `PBHGT_001`~`PBHGT_036` 각 1회
- label: `DEEP_DEPRESSED` 2, `DEPRESSED` 4, `NORMAL` 12, `OVERHEATED` 8, `EXTREME_OVERHEATED` 10
- confidence: `HIGH` 22, `MEDIUM` 14, `LOW` 0
- raw Feature: 7개 × 36 = 252개 값 모두 `OK`
- HIGH-only label 수: `DEEP_DEPRESSED` 2, `DEPRESSED` 1, `NORMAL` 6, `OVERHEATED` 4, `EXTREME_OVERHEATED` 9

## 3. Feature별 label 분포

분위수는 선형 보간이다. `DEEP_DEPRESSED`는 n=2라 Q1·Q3가 두 값 사이의 보간값이다.

### `36M_RANGE_POSITION`

| label | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | 0.048 | 0.046 | 0.049 | 0.044 | 0.051 |
| `DEPRESSED` | 4 | 0.090 | 0.087 | 0.178 | 0.079 | 0.439 |
| `NORMAL` | 12 | 0.381 | 0.305 | 0.589 | 0.113 | 0.774 |
| `OVERHEATED` | 8 | 0.747 | 0.546 | 0.788 | 0.453 | 0.852 |
| `EXTREME_OVERHEATED` | 10 | 0.885 | 0.755 | 0.932 | 0.709 | 0.971 |

### `MONTHLY_MA24_DISTANCE`

| label | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | -0.382 | -0.402 | -0.363 | -0.421 | -0.343 |
| `DEPRESSED` | 4 | -0.228 | -0.318 | -0.101 | -0.338 | 0.031 |
| `NORMAL` | 12 | -0.021 | -0.070 | 0.132 | -0.559 | 0.335 |
| `OVERHEATED` | 8 | 0.359 | 0.128 | 0.489 | 0.082 | 1.470 |
| `EXTREME_OVERHEATED` | 10 | 0.713 | 0.536 | 1.848 | 0.316 | 2.841 |

### `12M_RETURN_HISTORICAL_PERCENTILE`

| label | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | 15.269 | 12.837 | 17.702 | 10.405 | 20.134 |
| `DEPRESSED` | 4 | 18.588 | 14.627 | 23.547 | 13.423 | 27.746 |
| `NORMAL` | 12 | 63.027 | 26.445 | 76.072 | 4.046 | 85.549 |
| `OVERHEATED` | 8 | 87.651 | 68.624 | 99.400 | 14.400 | 100.000 |
| `EXTREME_OVERHEATED` | 10 | 87.200 | 81.000 | 95.414 | 54.913 | 100.000 |

### `36M_HIGH_DRAWDOWN`

| label | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | -0.714 | -0.734 | -0.694 | -0.753 | -0.675 |
| `DEPRESSED` | 4 | -0.599 | -0.620 | -0.523 | -0.658 | -0.318 |
| `NORMAL` | 12 | -0.324 | -0.434 | -0.265 | -0.850 | -0.110 |
| `OVERHEATED` | 8 | -0.203 | -0.254 | -0.146 | -0.322 | -0.098 |
| `EXTREME_OVERHEATED` | 10 | -0.111 | -0.163 | -0.057 | -0.246 | -0.022 |

### `52W_RANGE_POSITION`

| label | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | 0.151 | 0.148 | 0.154 | 0.145 | 0.157 |
| `DEPRESSED` | 4 | 0.206 | 0.184 | 0.255 | 0.161 | 0.360 |
| `NORMAL` | 12 | 0.503 | 0.271 | 0.700 | 0.106 | 0.918 |
| `OVERHEATED` | 8 | 0.773 | 0.743 | 0.834 | 0.217 | 0.944 |
| `EXTREME_OVERHEATED` | 10 | 0.840 | 0.676 | 0.899 | 0.624 | 0.913 |

### `WEEKLY_MA40_DISTANCE`

| label | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | -0.193 | -0.204 | -0.183 | -0.215 | -0.172 |
| `DEPRESSED` | 4 | -0.066 | -0.076 | -0.020 | -0.078 | 0.091 |
| `NORMAL` | 12 | 0.080 | -0.024 | 0.137 | -0.262 | 0.291 |
| `OVERHEATED` | 8 | 0.180 | 0.129 | 0.234 | -0.107 | 0.710 |
| `EXTREME_OVERHEATED` | 10 | 0.327 | 0.108 | 0.831 | 0.009 | 1.420 |

### `26W_RETURN_HISTORICAL_PERCENTILE`

| label | n | median | Q1 | Q3 | min | max |
|---|---|---|---|---|---|---|
| `DEEP_DEPRESSED` | 2 | 19.124 | 14.006 | 24.241 | 8.889 | 29.359 |
| `DEPRESSED` | 4 | 54.423 | 40.106 | 70.186 | 34.273 | 80.359 |
| `NORMAL` | 12 | 65.192 | 44.178 | 84.310 | 24.098 | 94.083 |
| `OVERHEATED` | 8 | 91.172 | 79.049 | 95.155 | 4.745 | 96.147 |
| `EXTREME_OVERHEATED` | 10 | 91.844 | 57.641 | 97.557 | 45.359 | 100.000 |

## 4. median 순서

인접 label의 median 차이(오른쪽 − 왼쪽)다. 양수면 기대 방향이다. 약어: DEEP=`DEEP_DEPRESSED`, DEP=`DEPRESSED`, NORM=`NORMAL`, OVH=`OVERHEATED`, EXT=`EXTREME_OVERHEATED`.

| Feature | DEEP→DEP | DEP→NORM | NORM→OVH | OVH→EXT |
|---|---|---|---|---|
| `36M_RANGE_POSITION` | 0.043 ✓ | 0.291 ✓ | 0.366 ✓ | 0.139 ✓ |
| `MONTHLY_MA24_DISTANCE` | 0.154 ✓ | 0.207 ✓ | 0.380 ✓ | 0.354 ✓ |
| `12M_RETURN_HISTORICAL_PERCENTILE` | 3.319 ✓ | 44.439 ✓ | 24.624 ✓ | -0.451 ✗ |
| `36M_HIGH_DRAWDOWN` | 0.115 ✓ | 0.276 ✓ | 0.121 ✓ | 0.092 ✓ |
| `52W_RANGE_POSITION` | 0.055 ✓ | 0.297 ✓ | 0.270 ✓ | 0.066 ✓ |
| `WEEKLY_MA40_DISTANCE` | 0.127 ✓ | 0.147 ✓ | 0.099 ✓ | 0.147 ✓ |
| `26W_RETURN_HISTORICAL_PERCENTILE` | 35.299 ✓ | 10.770 ✓ | 25.980 ✓ | 0.672 ✓ |

## 5. Spearman 순위 상관 (전체 / HIGH-only)

고정 연구 표본이므로 유의성 판단 없이 진단 지표로만 본다. HIGH-only의 median 순서는 표본이 적은 label이 있어 참고용이다.

| Feature | 전체 (n=36) | HIGH-only (n=22) | 차이 | HIGH-only median 역전·동률 |
|---|---|---|---|---|
| `36M_RANGE_POSITION` | 0.845 | 0.875 | 0.029 | 없음 |
| `MONTHLY_MA24_DISTANCE` | 0.847 | 0.863 | 0.016 | 없음 |
| `12M_RETURN_HISTORICAL_PERCENTILE` | 0.676 | 0.679 | 0.002 | DEEP→DEP, OVH→EXT |
| `36M_HIGH_DRAWDOWN` | 0.788 | 0.855 | 0.067 | 없음 |
| `52W_RANGE_POSITION` | 0.684 | 0.778 | 0.094 | 없음 |
| `WEEKLY_MA40_DISTANCE` | 0.649 | 0.758 | 0.109 | 없음 |
| `26W_RETURN_HISTORICAL_PERCENTILE` | 0.546 | 0.668 | 0.122 | DEP→NORM |

## 6. 인접 label IQR 겹침

`DEEP_DEPRESSED`(n=2)와 `DEPRESSED`(n=4)가 걸린 구간은 표본이 적어 과도하게 해석하지 않는다.

| Feature | 구간 | 왼쪽 IQR | 오른쪽 IQR | 겹침 |
|---|---|---|---|---|
| `36M_RANGE_POSITION` | DEEP→DEP | 0.046 ~ 0.049 | 0.087 ~ 0.178 | 아니오 |
| `36M_RANGE_POSITION` | DEP→NORM | 0.087 ~ 0.178 | 0.305 ~ 0.589 | 아니오 |
| `36M_RANGE_POSITION` | NORM→OVH | 0.305 ~ 0.589 | 0.546 ~ 0.788 | 예 |
| `36M_RANGE_POSITION` | OVH→EXT | 0.546 ~ 0.788 | 0.755 ~ 0.932 | 예 |
| `MONTHLY_MA24_DISTANCE` | DEEP→DEP | -0.402 ~ -0.363 | -0.318 ~ -0.101 | 아니오 |
| `MONTHLY_MA24_DISTANCE` | DEP→NORM | -0.318 ~ -0.101 | -0.070 ~ 0.132 | 아니오 |
| `MONTHLY_MA24_DISTANCE` | NORM→OVH | -0.070 ~ 0.132 | 0.128 ~ 0.489 | 예 |
| `MONTHLY_MA24_DISTANCE` | OVH→EXT | 0.128 ~ 0.489 | 0.536 ~ 1.848 | 아니오 |
| `12M_RETURN_HISTORICAL_PERCENTILE` | DEEP→DEP | 12.837 ~ 17.702 | 14.627 ~ 23.547 | 예 |
| `12M_RETURN_HISTORICAL_PERCENTILE` | DEP→NORM | 14.627 ~ 23.547 | 26.445 ~ 76.072 | 아니오 |
| `12M_RETURN_HISTORICAL_PERCENTILE` | NORM→OVH | 26.445 ~ 76.072 | 68.624 ~ 99.400 | 예 |
| `12M_RETURN_HISTORICAL_PERCENTILE` | OVH→EXT | 68.624 ~ 99.400 | 81.000 ~ 95.414 | 예 |
| `36M_HIGH_DRAWDOWN` | DEEP→DEP | -0.734 ~ -0.694 | -0.620 ~ -0.523 | 아니오 |
| `36M_HIGH_DRAWDOWN` | DEP→NORM | -0.620 ~ -0.523 | -0.434 ~ -0.265 | 아니오 |
| `36M_HIGH_DRAWDOWN` | NORM→OVH | -0.434 ~ -0.265 | -0.254 ~ -0.146 | 아니오 |
| `36M_HIGH_DRAWDOWN` | OVH→EXT | -0.254 ~ -0.146 | -0.163 ~ -0.057 | 예 |
| `52W_RANGE_POSITION` | DEEP→DEP | 0.148 ~ 0.154 | 0.184 ~ 0.255 | 아니오 |
| `52W_RANGE_POSITION` | DEP→NORM | 0.184 ~ 0.255 | 0.271 ~ 0.700 | 아니오 |
| `52W_RANGE_POSITION` | NORM→OVH | 0.271 ~ 0.700 | 0.743 ~ 0.834 | 아니오 |
| `52W_RANGE_POSITION` | OVH→EXT | 0.743 ~ 0.834 | 0.676 ~ 0.899 | 예 |
| `WEEKLY_MA40_DISTANCE` | DEEP→DEP | -0.204 ~ -0.183 | -0.076 ~ -0.020 | 아니오 |
| `WEEKLY_MA40_DISTANCE` | DEP→NORM | -0.076 ~ -0.020 | -0.024 ~ 0.137 | 예 |
| `WEEKLY_MA40_DISTANCE` | NORM→OVH | -0.024 ~ 0.137 | 0.129 ~ 0.234 | 예 |
| `WEEKLY_MA40_DISTANCE` | OVH→EXT | 0.129 ~ 0.234 | 0.108 ~ 0.831 | 예 |
| `26W_RETURN_HISTORICAL_PERCENTILE` | DEEP→DEP | 14.006 ~ 24.241 | 40.106 ~ 70.186 | 아니오 |
| `26W_RETURN_HISTORICAL_PERCENTILE` | DEP→NORM | 40.106 ~ 70.186 | 44.178 ~ 84.310 | 예 |
| `26W_RETURN_HISTORICAL_PERCENTILE` | NORM→OVH | 44.178 ~ 84.310 | 79.049 ~ 95.155 | 예 |
| `26W_RETURN_HISTORICAL_PERCENTILE` | OVH→EXT | 79.049 ~ 95.155 | 57.641 ~ 97.557 | 예 |

## 7. Feature 간 상관

36개 전체의 Spearman 상관이다. 약어: M36_RP=`36M_RANGE_POSITION`, M_MA24=`MONTHLY_MA24_DISTANCE`, M_R12P=`12M_RETURN_HISTORICAL_PERCENTILE`, M36_DD=`36M_HIGH_DRAWDOWN`, W52_RP=`52W_RANGE_POSITION`, W_MA40=`WEEKLY_MA40_DISTANCE`, W_R26P=`26W_RETURN_HISTORICAL_PERCENTILE`.

| | M36_RP | M_MA24 | M_R12P | M36_DD | W52_RP | W_MA40 | W_R26P |
|---|---|---|---|---|---|---|---|
| M36_RP | 1.00 | 0.93 | 0.80 | 0.96 | 0.81 | 0.82 | 0.73 |
| M_MA24 | 0.93 | 1.00 | 0.86 | 0.88 | 0.77 | 0.85 | 0.73 |
| M_R12P | 0.80 | 0.86 | 1.00 | 0.73 | 0.69 | 0.76 | 0.68 |
| M36_DD | 0.96 | 0.88 | 0.73 | 1.00 | 0.82 | 0.82 | 0.69 |
| W52_RP | 0.81 | 0.77 | 0.69 | 0.82 | 1.00 | 0.88 | 0.84 |
| W_MA40 | 0.82 | 0.85 | 0.76 | 0.82 | 0.88 | 1.00 | 0.93 |
| W_R26P | 0.73 | 0.73 | 0.68 | 0.69 | 0.84 | 0.93 | 1.00 |

절대 상관이 큰 순서 상위 5쌍:

1. `36M_RANGE_POSITION` – `36M_HIGH_DRAWDOWN`: 0.957
2. `WEEKLY_MA40_DISTANCE` – `26W_RETURN_HISTORICAL_PERCENTILE`: 0.929
3. `36M_RANGE_POSITION` – `MONTHLY_MA24_DISTANCE`: 0.928
4. `52W_RANGE_POSITION` – `WEEKLY_MA40_DISTANCE`: 0.879
5. `MONTHLY_MA24_DISTANCE` – `36M_HIGH_DRAWDOWN`: 0.876

## 8. MEDIUM confidence 표본 14개

다음 단계에서 경계 사례를 사람이 직접 검토하기 위한 표다. 자동 분류는 붙이지 않았다.

| sample_id | label | M36_RP | M_MA24 | M_R12P | M36_DD | W52_RP | W_MA40 | W_R26P |
|---|---|---|---|---|---|---|---|---|
| `PBHGT_002` | `OVERHEATED` | 0.766 | 0.475 | 100.000 | -0.158 | 0.743 | 0.225 | 92.995 |
| `PBHGT_005` | `EXTREME_OVERHEATED` | 0.755 | 0.316 | 79.200 | -0.153 | 0.722 | 0.085 | 48.862 |
| `PBHGT_006` | `NORMAL` | 0.774 | 0.335 | 85.549 | -0.110 | 0.739 | 0.291 | 88.417 |
| `PBHGT_007` | `DEPRESSED` | 0.079 | -0.144 | 22.148 | -0.592 | 0.161 | -0.076 | 34.273 |
| `PBHGT_009` | `DEPRESSED` | 0.439 | 0.031 | 27.746 | -0.318 | 0.360 | 0.091 | 80.359 |
| `PBHGT_010` | `OVERHEATED` | 0.554 | 0.132 | 65.101 | -0.235 | 0.877 | 0.263 | 94.970 |
| `PBHGT_012` | `OVERHEATED` | 0.522 | 0.115 | 14.400 | -0.322 | 0.217 | -0.107 | 4.745 |
| `PBHGT_014` | `DEPRESSED` | 0.090 | -0.338 | 13.423 | -0.607 | 0.221 | -0.057 | 42.051 |
| `PBHGT_016` | `OVERHEATED` | 0.453 | 0.082 | 69.799 | -0.254 | 0.944 | 0.150 | 89.349 |
| `PBHGT_019` | `NORMAL` | 0.568 | 0.094 | 74.497 | -0.285 | 0.918 | 0.152 | 94.083 |
| `PBHGT_024` | `NORMAL` | 0.254 | -0.107 | 4.046 | -0.327 | 0.280 | 0.079 | 68.846 |
| `PBHGT_026` | `NORMAL` | 0.703 | 0.246 | 82.659 | -0.143 | 0.698 | 0.162 | 87.387 |
| `PBHGT_032` | `NORMAL` | 0.306 | -0.254 | 51.678 | -0.631 | 0.200 | -0.073 | 60.327 |
| `PBHGT_033` | `NORMAL` | 0.113 | -0.559 | 6.936 | -0.850 | 0.106 | -0.262 | 24.098 |

## 9. 관찰 사항

표의 수치를 옮긴 사실만 적는다.

**`36M_RANGE_POSITION`**

- 인접 4구간 중 4구간에서 median이 기대 방향으로 증가했다.
- 인접 IQR이 겹치는 구간: NORM→OVH, OVH→EXT.
- Spearman은 전체 0.845, HIGH-only 0.875로 HIGH-only가 0.029 높다.

**`MONTHLY_MA24_DISTANCE`**

- 인접 4구간 중 4구간에서 median이 기대 방향으로 증가했다.
- 인접 IQR이 겹치는 구간: NORM→OVH.
- Spearman은 전체 0.847, HIGH-only 0.863로 HIGH-only가 0.016 높다.

**`12M_RETURN_HISTORICAL_PERCENTILE`**

- 인접 4구간 중 3구간에서 median이 기대 방향으로 증가했다 (역전·동률: OVH→EXT).
- 인접 IQR이 겹치는 구간: DEEP→DEP, NORM→OVH, OVH→EXT.
- Spearman은 전체 0.676, HIGH-only 0.679로 HIGH-only가 0.002 높다.
- HIGH-only median 역전·동률 구간: DEEP→DEP, OVH→EXT (HIGH에서 표본 1개 이하인 label이 걸린 구간 포함).

**`36M_HIGH_DRAWDOWN`**

- 인접 4구간 중 4구간에서 median이 기대 방향으로 증가했다.
- 인접 IQR이 겹치는 구간: OVH→EXT.
- Spearman은 전체 0.788, HIGH-only 0.855로 HIGH-only가 0.067 높다.

**`52W_RANGE_POSITION`**

- 인접 4구간 중 4구간에서 median이 기대 방향으로 증가했다.
- 인접 IQR이 겹치는 구간: OVH→EXT.
- Spearman은 전체 0.684, HIGH-only 0.778로 HIGH-only가 0.094 높다.

**`WEEKLY_MA40_DISTANCE`**

- 인접 4구간 중 4구간에서 median이 기대 방향으로 증가했다.
- 인접 IQR이 겹치는 구간: DEP→NORM, NORM→OVH, OVH→EXT.
- Spearman은 전체 0.649, HIGH-only 0.758로 HIGH-only가 0.109 높다.

**`26W_RETURN_HISTORICAL_PERCENTILE`**

- 인접 4구간 중 4구간에서 median이 기대 방향으로 증가했다.
- 인접 IQR이 겹치는 구간: DEP→NORM, NORM→OVH, OVH→EXT.
- Spearman은 전체 0.546, HIGH-only 0.668로 HIGH-only가 0.122 높다.
- HIGH-only median 역전·동률 구간: DEP→NORM (HIGH에서 표본 1개 이하인 label이 걸린 구간 포함).

**Feature 간 상관**

- `36M_RANGE_POSITION`와 `36M_HIGH_DRAWDOWN`의 Spearman 상관은 0.957다.
- `WEEKLY_MA40_DISTANCE`와 `26W_RETURN_HISTORICAL_PERCENTILE`의 Spearman 상관은 0.929다.
- `36M_RANGE_POSITION`와 `MONTHLY_MA24_DISTANCE`의 Spearman 상관은 0.928다.
- `52W_RANGE_POSITION`와 `WEEKLY_MA40_DISTANCE`의 Spearman 상관은 0.879다.
- `MONTHLY_MA24_DISTANCE`와 `36M_HIGH_DRAWDOWN`의 Spearman 상관은 0.876다.

**한계**

- 36개는 12종목 × 기준일 3개라 같은 종목의 표본끼리 독립이 아니다. 상관은 독립 표본 36개보다 과장될 수 있다.
- `DEEP_DEPRESSED`는 2개, `DEPRESSED`는 4개(HIGH-only 1개)라 하단 구간의 순서·겹침은 불안정하다.

## 10. 다음 단계

이 진단을 근거로 Feature별 검토를 거쳐 유지·수정·제외 여부를 정한다. 그 전에는 임계값, 가중치, 상태 규칙을 만들지 않는다.
