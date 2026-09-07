opendart_fundamentals_v1_multi_period.md

======================================================================
OpenDART Fundamentals V1 — F2 Multi-period Production Boundary
======================================================================

목적
----------------------------------------------------------------------

F2는 기존 PeriodizationProvider가 만든 canonical observation을 소비해
Stock Report가 요구하는 비교 이력을 표현한다. 이 모듈은 OpenDART endpoint를
직접 호출하지 않으며 기간화, 누적 차분, TTM/YoY 산식을 다시 구현하지 않는다.

사용 경계
----------------------------------------------------------------------

```python
from trend_scanner.fundamentals import MultiPeriodFundamentalsProvider

result = MultiPeriodFundamentalsProvider(periodization_provider).build(
    "005930", "2026-08-20", fiscal_years=("2021", "2022", "2023", "2024", "2025", "2026")
)
```

기존 DerivedMetricsProvider와 같은 positional 형태도 허용한다.

```python
result = provider.build("005930", ("2021", "2022", "2023"), "2026-08-20")
```

Boundary 계약
----------------------------------------------------------------------

- 기본 연도 범위는 requested_as_of의 연도부터 과거 5년까지 6FY다.
- 초기 연도 범위에서 최신 PIT-usable FY를 찾은 뒤, 그 FY를 끝점으로 6FY를
  다시 anchor한다. 필요한 과거 FY만 추가 build하며 year당 build는 한 번이다.
- 분기 비교 슬롯은 16개(12Q 표시 + 전년 동기 비교 4Q)다.
- 연간 비교 슬롯은 6FY(5Y 표시 + 비교 1FY)다.
- `quarters`/`annuals`는 슬롯에 포함된 flat canonical observations이며,
  `quarter_slots`/`annual_slots`는 기간 identity와 상태를 보존한다.
- 상태가 없는 분기는 `DATA_UNAVAILABLE`, 모호한 분기는
  `PERIOD_AMBIGUOUS`로 남는다. 중간 기간을 압축하지 않는다.
- `pit_available_from` 또는 anchor receipt가 requested_as_of 이후인 source는
  제외되고 diagnostics에 기록된다. 미래 filing을 canonical 결과에 넣지 않는다.
- 동일 window 내 metric의 `fs_div_used` 또는 currency가 섞이면
  `basis_consistent`/`currency_consistent`가 false가 되고 comparison/display
  readiness가 false가 된다.
- 분기 slot은 `revenue`, `operating_income`, `net_income`,
  `operating_cash_flow`가 모두 canonical READY여야 한다. 연간 slot은
  `revenue`, `operating_income`, `net_income`, `equity`, `liabilities`가
  필요하며 annual OCF는 optional이다. required metric 누락은
  `DATA_UNAVAILABLE`/`REQUIRED_METRIC_MISSING`으로 남는다.
- FINANCIAL company family는 general-company series를
  `NOT_APPLICABLE`로 유지하며 금융 전용 metric을 만들지 않는다.

주요 필드
----------------------------------------------------------------------

- `has_16q_comparison_window`, `has_12q_display_window`
- `has_6fy_comparison_window`, `has_5y_display_window`
- `quarter_coverage`: requested/ready/missing/ambiguous count, slots,
  basis/currency consistency, readiness flags
- `annual_coverage`: 동일 구조의 FY metadata
- `latest_quarter`, `latest_fy`, `diagnostics`

F2에서 하지 않는 것
----------------------------------------------------------------------

ROE/부채비율, Fundamentals Filter, Stock Report schema·Markdown·JSON 통합,
전체 KRX hydration, strategy/backtest 변경은 후속 단계다. PyKRX, KRX scraping,
OpenDART live 호출, 외부 시세 데이터, manual injection은 사용하지 않는다.

검증
----------------------------------------------------------------------

`tests/test_opendart_fundamentals_multi_period_v1.py`에서 synthetic positive와
missing/ambiguous/future/basis/currency/FINANCIAL negative를 검증한다. 기존
Periodization 및 DerivedMetrics 회귀 테스트와 함께 실행하며 Full Repository
Pytest는 F2 범위에서 실행하지 않는다.
