# Pattern B 사람 판정 표본 Feature raw 값 V01

> 상태: 36개 표본의 raw Feature 값 계산·봉인 완료. 사람 판정과 Feature의 적합성
> 분석은 아직 하지 않았다. 임계값, 점수, 자동 상태 판정도 없다.

## 목적

[사람 판정 V01](human_ground_truth_v01.md) 표본 36개에 대해
[Feature 계약 V01](../spec/feature_contract_v01.md)의 7개 Feature raw 값을 계산해
`sample_id` 기준으로 고정한다. 다음 단계의 적합성 분석은 이 값을 그대로 쓴다.

- 사람 판정 결과는 Feature 계산 전에 이미 봉인했다.
- Feature 산식과 PIT 계약은 이 계산을 위해 바꾸지 않았다.
- 비공개 대응표는 `sample_id`를 ticker·기준일에 연결하는 데만 썼다. 대응표와
  ticker·종목명·기준일은 Git에 올리지 않았다.

## 계산 조건

- 가격: Repository V2 조정 가격 일봉, 기준일까지만 요청
- 이력 시작일: `requested_history_start = 1900-01-01` (확보된 전체 이력)
- 계산: `compute_pattern_b_features_v01(daily, as_of)`
- 실행 스크립트: `scripts/compute_pattern_b_hgt_feature_raw_v01.py`
- 36개 모두 기준일 이후 1년 치 데이터를 함께 읽어 다시 계산했을 때 값이 같았다.

## 결과

결과 파일: [feature_raw_values_v01.csv](feature_raw_values_v01.csv)
(36행, Feature별 값과 상태, 이력 범위와 봉 개수)

| Feature | `OK` | 계산 불가 |
|---|---|---|
| `36M_RANGE_POSITION` | 36 | 0 |
| `MONTHLY_MA24_DISTANCE` | 36 | 0 |
| `12M_RETURN_HISTORICAL_PERCENTILE` | 36 | 0 |
| `36M_HIGH_DRAWDOWN` | 36 | 0 |
| `52W_RANGE_POSITION` | 36 | 0 |
| `WEEKLY_MA40_DISTANCE` | 36 | 0 |
| `26W_RETURN_HISTORICAL_PERCENTILE` | 36 | 0 |

실제 이력 시작일은 모든 표본이 2010-01-04 또는 2010-01-06이며, 완료 봉은 월봉
138~186개, 주봉 595~807개다.
