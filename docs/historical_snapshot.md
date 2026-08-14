# Historical Snapshot Validation v0.1

## 상태

과거 특정 날짜(`snapshot_date`)를 기준으로, 그 시점까지만 데이터가 존재했다고
가정하고 Feature Validation v0.1의 `build_feature_row()`를 다시 호출하는
최소 구현입니다. Pattern A 점수와는 무관합니다. 새 Feature 산식도 만들지
않습니다 — 기존 계산 경로(`build_feature_row`)를 그대로 재사용해서, 현재
시점과 과거 시점의 계산 방식이 갈라지는 일을 막습니다.

## 핵심 원칙: look-ahead 방지

`build_historical_snapshot()`은 daily를 받으면 가장 먼저

```python
sliced = daily[daily.index <= requested]
```

로 `snapshot_date` 이후 행을 제거하고, 이후 모든 계산(주봉/월봉 생성,
`build_feature_row`)은 이 `sliced`만 사용합니다. `daily`에 미래 데이터가
더 들어있어도 결과에 영향을 주지 않습니다(회귀 테스트
`test_future_data_does_not_change_past_snapshot` 참고).

`snapshot_date`가 비거래일(주말/공휴일/휴장일)이어도 실패시키지 않습니다.
별도의 "가장 가까운 거래일 조회" 로직이 필요 없는 이유는, `index <= requested`
필터 자체가 이미 그 결과와 동일하기 때문입니다 — 그 이하에서 가장 최근 거래일
까지의 행만 자연스럽게 남습니다. 실제로 남은 데이터의 마지막 날짜를
`effective_as_of`로 노출해서, 요청한 날짜(`requested_snapshot_date`)와
실제 사용된 날짜를 둘 다 확인할 수 있게 합니다.

`snapshot_date` 이전 데이터가 아예 없거나 lookback 기간(예: 36개월)에 못
미치면 예외를 던지지 않고 해당 Feature가 NaN이 됩니다(`build_feature_row`의
기존 동작을 그대로 물려받습니다).

## completed monthly 정책 (v0.1 한계)

`include_incomplete_periods` 옵션으로 진행 중인 월봉 포함 여부를 고를 수
있습니다.

* `True`(live, 기본값): `snapshot_date`까지의 daily로 만든 주봉/월봉을
  그대로 사용한다. `snapshot_date`가 월 중간이면 마지막 월봉은 미완성이다.
* `False`(completed): 마지막 월봉이 진행 중인 달이면 제거하고, 완성된
  월봉까지만 사용한다.

**한계**: "진행 중인 달인지"를 실제 거래소 캘린더가 아니라 단순 calendar
month 기준으로 판단합니다(`requested_snapshot_date < 해당 달의 calendar
month-end`이면 마지막 월봉을 제거). `snapshot_date`가 실제 마지막 거래일과
정확히 일치하는지는 확인하지 않습니다. weekly에는 이 정책을 적용하지
않습니다(월봉만 대상).

**사람이 보는 메인 비교표의 기본값은 completed monthly입니다**(Pattern A가
장기 구조를 보는 모델이라 진행 중인 달의 노이즈를 배제하는 쪽을 기본으로
한다). live monthly 결과는 참고용으로만 씁니다.

## Snapshot 날짜 선정

`scripts/historical_snapshot_validate.py`의 `SNAPSHOTS` 상수에 사람이 직접
적은 날짜 목록입니다. 자동 탐지 로직은 없습니다. 4종목 각각에 대해 캐시된
실제 월봉 close/MA24 slope/MA spread/compression ratio 등을 직접 조회해
보고 아래 4가지 상태에 해당하는 분기점을 골랐습니다.

* `pre_breakout`: 본격 상승 직전(장기 횡보/수렴 또는 하락 바닥 구간)
* `early_trend`: 이미 가격이 움직이기 시작했지만 장기 추세가 완전히
  확장되기 전
* `trend_progressed`: MA spread가 크게 벌어지고 장기 상승이 명확히 진행된
  시점
* `unfavorable`: 하락 추세 또는 고점 이후 하락 구간

선정 근거와 실제 수치는 완료 보고에 정리합니다. 이 라벨은 사람이 해석하기
위한 문자열일 뿐, Pattern A 점수나 다른 어떤 계산에도 사용되지 않습니다.

각 종목에는 추가로 `current` label의 snapshot이 하나씩 더 있습니다 —
snapshot_date를 캐시의 가장 최근 날짜(보통 월 중간)로 둬서, completed와
live가 실제로 다른 결과를 내는 걸 눈으로 확인할 수 있게 한 참고용
snapshot입니다.

## CSV / 비교표

`data/processed/historical_snapshots.csv`에 각 (ticker, label)마다
completed/live 두 행을 저장합니다(`include_incomplete_periods` 컬럼으로
구분). 사람이 보는 메인 비교표는 completed monthly만 사용합니다.

같은 종목의 snapshot을 날짜순으로 나열한 "시간 흐름 비교" 표에는
`delta_ma24_slope`, `delta_ma_spread`, `delta_atr_ratio`,
`delta_range_position` 같은 연속 snapshot 간 변화량을 참고용으로 같이
출력합니다. 이 값들은 새로운 Pattern Feature로 승격하지 않습니다 — 단순
분석용 컬럼입니다.
