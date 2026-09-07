opendart_fundamentals_v1_roe_debt_ratio.md
======================================================================

OpenDART Fundamentals V1 — ROE & Debt Ratio Derived Metrics
======================================================================

목적
----------------------------------------------------------------------

이 문서는 F2 MultiPeriodFundamentalsResult 또는 동일한 canonical
PeriodizedFinancialObservation 집합에서 계산하는 일반회사(NON_FINANCIAL)
자본효율성 파생지표의 계약을 정의한다. 원천 API/XBRL을 직접 호출하지 않으며
기존 DerivedMetricsEngine의 PIT와 provenance 경계를 재사용한다.

지표 정의
----------------------------------------------------------------------

- Annual ROE (`ANNUAL_ROE`)
  `annual net income / ((previous FY-end equity + current FY-end equity) / 2) * 100`
  가장 오래된 비교 연도에 prior FY-end equity가 없으면 `DATA_UNAVAILABLE`이다.
- TTM ROE (`TTM_ROE`)
  기존 DerivedMetricsEngine의 latest four contiguous standalone-quarter
  `TTM` net-income 결과를 사용한다. TTM 시작 직전 quarter-end equity와
  endpoint quarter-end equity의 평균을 분모로 사용한다. 분기별 annualized
  ROE는 만들지 않는다.
- Debt Ratio (`DEBT_RATIO`)
  `liabilities / equity * 100`. balance-sheet instant metric이며 TTM으로
  계산하거나 `TTM Debt Ratio`로 이름 붙이지 않는다. `Q1_END`, `H1_END`,
  `Q3_END`, `FY_END` snapshot에서만 생성한다.

입력 및 안전성
----------------------------------------------------------------------

- 입력은 F2 `canonical_observations`를 직접 소비할 수 있으며, 기존
  PeriodizationResult/iterable 입력도 계속 지원한다.
- 모든 source observation은 `pit_available_from <= requested_as_of`여야 한다.
  미래·미확인·ambiguous 입력은 READY로 승격하지 않는다.
- Annual ROE의 net income/prior equity/current equity, TTM ROE의 네 분기
  net income/beginning equity/ending equity, Debt Ratio의 liabilities/equity는
  basis(`fs_div_used`)와 currency가 일치해야 한다. 불일치하면 각각
  `BASIS_MISMATCH` 또는 `CURRENCY_MISMATCH`로 fail-closed한다.
- ROE 평균 equity가 0 이하이면 `UNDEFINED_BASE`/
  `NON_POSITIVE_AVERAGE_EQUITY_BASE`이다.
- Debt Ratio equity가 0 이하이면 `UNDEFINED_BASE`/
  `NON_POSITIVE_EQUITY_BASE`이다.
- 같은 instant identity에 PIT-usable candidate가 여러 개면 임의 winner를
  선택하지 않고 `PERIOD_AMBIGUOUS`로 남긴다.

Provenance
----------------------------------------------------------------------

새 관측도 기존 `DerivedMetricObservation`을 사용한다. source receipt 번호·일자·
SHA, `requested_as_of`, `pit_available_from`을 기존 `_period_context()` 경로로
보존하며, metadata에는 계산에 필요한 최소 period 정보만 기록한다.

FINANCIAL 회사
----------------------------------------------------------------------

`company_family == FINANCIAL`이면 이번 V1 일반회사 프로파일에서
`ANNUAL_ROE`, `TTM_ROE`, `DEBT_RATIO`를 `NOT_APPLICABLE`로 처리한다. 금융업
전용 ROE/부채비율 profile이나 별도 score는 이 단계에서 만들지 않는다.

범위 제외
----------------------------------------------------------------------

Fundamentals Filter, Stock Report/Markdown/JSON, production hydration,
strategy/backtest, ROA/ROIC/ROCE, valuation, DuPont, 금융업 전용 profile은
후속 단계다. PyKRX, KRX Open API, OpenDART live API, scraping, 외부 시세
데이터 요청은 이 지표 계산에서 사용하지 않는다.
