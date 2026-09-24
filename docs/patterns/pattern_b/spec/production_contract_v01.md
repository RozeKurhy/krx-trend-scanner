# Pattern B 운영 계약 V01

> 상태: 현재 기준. 운영 코드가 Pattern B를 호출할 때의 입력, 평가 상태, 오류, 결과 필드를
> 정한다. 새 산식·임계값·상태는 없으며, [지표 계약 V01](feature_contract_v01.md)과
> [상태 판정 규칙 V02](../validation/state_rule_v02.md)를 조합만 한다. 스캐너·일일 갱신·웹
> 연결은 이 계약의 범위가 아니다.

구현: `src/trend_scanner/patterns/pattern_b_evaluator.py`
(`evaluate_pattern_b(ticker, daily, as_of, name="")`)

## 1. 입력

| 입력 | 내용 |
|---|---|
| `ticker` | 종목코드 |
| `name` | 종목명 (선택, 기본값 빈 문자열) |
| `daily` | 조정 가격 일봉. `DatetimeIndex`, `high`·`low`·`close` 열 |
| `as_of` | 평가 기준일 |

데이터 출처와 호출자 책임:

- 운영 가격 출처는 `MarketDataRepositoryV2`의 조정 가격이다.
- 호출자는 기준일을 포함하는 PIT COMMON 종목 구간(identity segment) 안의 가격만 넘긴다.
  다른 종목 구간과 이어 붙이지 않는다.
- evaluator는 가격을 읽지 않는다. Repository 로더와 종목 구간 적용은 호출자가 맡는다.

기준일 이후 일봉 제거, 입력 검증, 완료 봉 집계는 [지표 계약 V01](feature_contract_v01.md)을
그대로 따른다.

## 2. 평가 상태

평가 상태(`evaluation_status`)와 Pattern B 상태(`pattern_b_state`)는 다른 값이다.

| 평가 상태 | 조건 | `pattern_b_state` |
|---|---|---|
| `READY` | 규칙 V02가 쓰는 유지 지표 3개가 모두 계산됨 | 5개 상태 중 하나 (규칙 V02 결과) |
| `UNAVAILABLE` | 유지 지표 3개 중 하나 이상이 계산 불가 | `null` |

- 유지 지표 3개: 36개월 범위 위치, 월봉 24개월 이동평균 이격, 52주 범위 위치.
- 준비 여부는 이 3개로만 판단한다. 규칙 V02가 쓰지 않는 나머지 지표 4개가 계산 불가여도
  `READY`가 될 수 있다.
- `UNAVAILABLE`은 여섯 번째 Pattern B 상태가 아니다. `NORMAL` 등 다른 상태로 대신 채우지 않는다.
- 계산 불가 사유는 지표 계약의 상태 코드를 그대로 쓴다. 예: `INSUFFICIENT_BARS`(완료 봉 부족),
  `FLAT_RANGE`(범위 창의 최고가와 최저가가 같음).

## 3. 오류

정상적인 이력 부족·계산 불가는 `UNAVAILABLE`이다. 잘못된 입력이나 데이터 계약 위반은
`UNAVAILABLE`로 숨기지 않고 예외로 낸다.

| 경우 | 처리 |
|---|---|
| 인덱스가 날짜가 아님, 열 누락, 날짜 중복 | `PatternBFeatureInputError` |
| 조정 가격에 결측·비유한값·0 이하 값 | `PatternBFeatureInputError` |
| `low <= close <= high` 위반 | `PatternBFeatureInputError` |
| 규칙 V02 입력이 유한한 숫자가 아님 | `ValueError` (규칙 V02의 기존 동작) |

## 4. 결과 필드

결과는 변경할 수 없는 객체(`PatternBEvaluationResult`)다.

| 필드 | 내용 |
|---|---|
| `ticker`, `name` | 입력값 |
| `as_of` | 평가 기준일 (`YYYY-MM-DD`) |
| `evaluation_status` | `READY` 또는 `UNAVAILABLE` |
| `pattern_b_state` | `READY`면 5개 상태 중 하나, `UNAVAILABLE`이면 `null` |
| `reason_codes` | 계산 불가 유지 지표별 `<지표>:<상태 코드>`. `READY`면 빈 값 |
| `reason_details` | 같은 순서의 지표 계약 사유 문장 |
| `range_36m` | 36개월 범위 위치 원시값. 계산 불가면 `null` |
| `monthly_ma24_distance` | 월봉 24개월 이동평균 이격 원시값. 계산 불가면 `null` |
| `range_52w` | 52주 범위 위치 원시값. 계산 불가면 `null` |
| `monthly_last_bar`, `weekly_last_bar` | 마지막 완료 월봉·주봉 날짜. 봉이 없으면 `null` |
| `feature_contract_version` | `"V01"` |
| `state_rule_version` | `"PATTERN_B_STATE_RULE_V02"` |

`UNAVAILABLE`이어도 계산된 유지 지표의 원시값은 그대로 보여 준다. Pattern B 자체의 버전
번호는 만들지 않는다.

## 5. 범위 밖

- 전체 종목 실행, 종목 구간 적용 로더, 일일 갱신·웹 연결
- 기준일에 거래정지 중인 종목의 별도 처리 (지표 계약대로 마지막 거래 봉으로 계산된다)
- 전략, 매매 신호, 백테스트
