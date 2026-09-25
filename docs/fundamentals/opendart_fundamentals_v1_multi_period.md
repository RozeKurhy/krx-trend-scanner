# OpenDART Fundamentals V1 - 다기간 재무 데이터 계약

## 목적

`MultiPeriodFundamentalsResult`는 기존 `PeriodizationProvider`가 만든 정본
관측값을 소비해 Stock Report가 요구하는 비교 이력을 표현한다. 이 모듈은
OpenDART endpoint를 직접 호출하지 않으며 기간화, 누적 차분, TTM/YoY
산식을 다시 구현하지 않는다.

## 사용 방법

```python
from trend_scanner.fundamentals import MultiPeriodFundamentalsProvider

result = MultiPeriodFundamentalsProvider(periodization_provider).build(
    "005930", "YYYY-MM-DD", fiscal_years=fiscal_years
)
```

`fiscal_years`는 `"YYYY"` 형식 회계연도의 튜플이다. 생략하면 아래 기본 연도
범위를 사용한다.

기존 `DerivedMetricsProvider`와 같은 위치 인자 방식도 허용한다.

```python
result = provider.build("005930", fiscal_years, "YYYY-MM-DD")
```

## 기간 구성 규칙

- 기본 연도 범위는 `requested_as_of`의 연도부터 과거 5년까지 6개 회계연도
  (6FY)다.
- 초기 연도 범위에서 필수 지표가 모두 `READY`인 최신 V1 사용 가능 FY를
  찾은 뒤, 그 FY를 끝점으로 6FY를 다시 기준점으로 삼는다. 더 최신
  FY가 일부 지표만 갖거나 모호하면 창을 앞으로 이동하지 않는다. 필요한
  과거 FY만 추가로 생성하며 연도당 생성은 한 번이다.
- 분기 비교 슬롯은 16개(12분기 표시 + 전년 동기 비교 4분기)다.
- 연간 비교 슬롯은 6FY(5개 연도 표시 + 비교용 1개 연도)다.
- `quarters`/`annuals`는 슬롯에 포함된 평탄화된 정본 관측값이며,
  `quarter_slots`/`annual_slots`는 기간 식별자와 상태를 보존한다.
- 상태가 없는 분기는 `DATA_UNAVAILABLE`, 모호한 분기는 `PERIOD_AMBIGUOUS`로
  남는다. 중간 기간을 압축하지 않는다.
- `pit_available_from` 또는 기준 접수일이 `requested_as_of` 이후인
  원천은 제외되고 `diagnostics`에 기록된다.
  미래 공시를 정본 결과에 넣지 않는다.
- 분기 슬롯은 `revenue`, `operating_income`, `net_income`,
  `operating_cash_flow`가 모두 정본 `READY` 상태여야 한다. 연간 슬롯은
  `revenue`, `operating_income`, `net_income`, `equity`, `liabilities`가
  필요하며 연간 OCF는 선택 지표다. 필수 지표 누락은
  `DATA_UNAVAILABLE`/`REQUIRED_METRIC_MISSING`으로 남는다.
- 창 단위의 `fs_div_used`/통화 일관성은 각 창의 V1 필수 지표에만
  사용 가능 여부를 반영한다. 필수 지표가 섞이면
  `basis_consistent`/`currency_consistent`가 `false`가 되고 비교·표시 사용
  가능 여부가 `false`가 된다. 선택 지표의 불일치는 `diagnostics`에
  남기지만 완전한 필수 창을 무효화하지 않는다.
- `FINANCIAL` 회사 유형은 일반회사 계열을 `NOT_APPLICABLE`로 유지하며 금융
  전용 지표를 만들지 않는다.

## 주요 결과 필드

- `has_16q_comparison_window`, `has_12q_display_window`
- `has_6fy_comparison_window`, `has_5y_display_window`
- `quarter_coverage`: 요청/준비/누락/모호 건수, 슬롯, 재무제표 기준/통화
  일관성, 사용 가능 여부 플래그
- `annual_coverage`: 동일 구조의 FY 메타데이터
- `latest_quarter`, `latest_fy`, `diagnostics`

## 다루지 않는 범위

ROE/부채비율은 [ROE/부채비율 기준 문서](opendart_fundamentals_v1_roe_debt_ratio.md),
Fundamentals Filter는 [필터 기준 문서](opendart_fundamentals_v1_filter.md),
Stock Report schema·Markdown·JSON 통합은
[Stock Report v0.5 계약](../reporting/stock_report/contract_v05.md)이 각각
관리한다. 전체 KRX 데이터 갱신과 전략/백테스트는 별도 운영 스크립트와
전략 문서의 범위다. PyKRX, KRX 웹 수집, 실제 OpenDART API 호출, 외부 시세
데이터, 수동 데이터 주입은 이 모듈에서 사용하지 않는다.

## 검증 범위

`tests/test_opendart_fundamentals_multi_period_v1.py`에서 합성 정상 사례와
결측/모호/미래/재무제표 기준/통화/`FINANCIAL` 실패 사례를 검증한다. 기존
Periodization 및 DerivedMetrics 회귀
테스트와 함께 실행하며 전체 저장소 pytest 실행은 이 범위에서 수행하지
않는다.
