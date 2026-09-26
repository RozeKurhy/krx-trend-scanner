# OpenDART Fundamentals V1 - Fundamentals Filter

## 목적

`MultiPeriodFundamentalsResult`와 `DerivedMetricsResult`의 정본 관측값만
사용해 일반 기업(`NON_FINANCIAL`)의 Fundamentals Filter V1을 평가한다. 이
계층은 OpenDART, 네트워크, 스캐너, 리포트 생성기를 직접 호출하지 않는다.

## 적용 대상

`FINANCIAL` 기업은 항상 `NOT_APPLICABLE`이며 `passed=false`다. 금융업에 같은
매출/이익 기준을 적용하지 않는다. ROE, 부채비율, OCF, 전략 임계값은 이
필터의 조건이 아니다.

## 필터 조건

`NON_FINANCIAL` 기업은 아래 네 조건을 모두 만족해야 `PASS`다.

| 조건 | 기준 |
|---|---|
| 연간 매출 | `MultiPeriodFundamentalsResult`의 `latest_fy`가 가리키는 최신 V1 사용 가능 FY 매출 >= 50,000,000,000 KRW |
| 최근 분기 평균 매출 | `latest_quarter`가 끝점인 최신 4개 연속 독립 분기 매출 평균 >= 10,000,000,000 KRW |
| TTM 영업이익 | `DerivedMetricsResult`가 이미 계산한 최신 TTM `operating_income` > 0 |
| TTM 순이익 | `DerivedMetricsResult`가 이미 계산한 최신 TTM `net_income` > 0 |

매출 두 기준은 경계값을 포함하고(값이 정확히 같아도 통과), 영업이익/순이익은
0을 통과시키지 않는다. 최신 분기가 누락되면 이전 분기 네 개를 당겨 쓰지
않고 `DATA_UNAVAILABLE`이다. 분기 중간의 빈 식별자도 압축하지 않는다.

## 정본 및 일관성 규칙

- FY와 분기 매출은 `MultiPeriodFundamentalsResult`의 `latest_fy`/
  `latest_quarter` 및 슬롯 상태를 따른다.
- 임계값이 KRW 기준이므로 연간 매출은 KRW만 허용한다. 자동 환율
  변환(FX 환산)은 하지 않는다.
- 최신 네 분기 매출도 모두 KRW여야 하며, 네 관측값의 `fs_div_used`가
  동일해야 평균을 계산한다. KRW가 아니거나 재무제표 기준이 불일치하면
  `DATA_UNAVAILABLE`이다.
- TTM 영업이익/순이익은 `DerivedMetricsResult`의 `metric_type=TTM`
  관측값만 읽는다. 이 필터에서 분기 합산이나 재계산을 하지 않는다.
- 매출과 TTM 이익의 최신 기준 기간이 다르면 `DATA_UNAVAILABLE`이다.
- `MultiPeriodFundamentalsResult`와 `DerivedMetricsResult`는 동일
  `ticker`를 가져야 한다. `corp_code`가 양쪽에 있으면 일치해야 하고,
  `company_family`도 일치해야 한다. 다른 종목의 더 최신 TTM을 사용하지
  않는다.
- 두 결과의 `requested_as_of`가 다르거나 필수 관측값이 `READY`가
  아니거나, 기간/재무제표 기준/통화/PIT 판정이 모호하면
  `DATA_UNAVAILABLE`이다. 원본 상태와 사유는 `diagnostics`에 보존한다.
- 더 오래된 FY/분기 또는 다른 데이터 제공자로의 조용한 대체 경로는 없다.

## 상태와 판정 순서

주 상태 우선순위는 다음과 같다.

```text
DATA_UNAVAILABLE > NOT_APPLICABLE > FILTERED_ANNUAL_REVENUE >
FILTERED_QUARTERLY_REVENUE > FILTERED_OPERATING_LOSS > FILTERED_NET_LOSS > PASS
```

여러 조건이 동시에 실패하면 `reasons`에 모든 필터 사유를 보존하고
`status`에는 위 우선순위의 첫 상태를 기록한다. `DATA_UNAVAILABLE`이면
`passed=false`다.

## 기본 설정

```text
annual_revenue_min = 50,000,000,000
quarterly_avg_revenue_min = 10,000,000,000
require_positive_ttm_operating_income = true
require_positive_ttm_net_income = true
```

## 검증 범위

테스트는 `PASS`, 각 임계값의 미만/동일/초과, 양의 이익의 엄격한 경계,
연속 분기 누락/최신 분기 누락, 기준 기간 불일치, 기준일 불일치, 비
`READY` 상태 보존, 금융업 `NOT_APPLICABLE`, 사용자 설정 및 JSON
직렬화를 고정한다.
