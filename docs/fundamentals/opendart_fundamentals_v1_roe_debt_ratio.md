# OpenDART Fundamentals V1 - ROE와 부채비율

## 목적

이 문서는 `MultiPeriodFundamentalsResult` 또는 동일한 정본
`PeriodizedFinancialObservation` 집합에서 계산하는 일반회사(NON_FINANCIAL)
자본효율성 파생지표의 계약을 정의한다. 원천 API/XBRL을 직접 호출하지
않으며 기존 DerivedMetricsEngine의 PIT와 출처 추적(provenance) 경계를
재사용한다.

## 지표 정의

### 연간 ROE

`ANNUAL_ROE`

```text
연간 순이익 / ((직전 FY 기말 자기자본 + 당기 FY 기말 자기자본) / 2) * 100
```

```text
annual net income / ((previous FY-end equity + current FY-end equity) / 2) * 100
```

가장 오래된 비교 연도에 직전 FY 기말 자기자본이 없으면
`DATA_UNAVAILABLE`이다.

### TTM ROE

`TTM_ROE`

기존 DerivedMetricsEngine의 최신 4개 연속 독립 분기(standalone quarter)
`TTM` 순이익 결과를 사용한다. TTM 시작 직전 분기말 자기자본과 종료 시점
분기말 자기자본의 평균을 분모로 사용한다. 분기별 연환산(annualized) ROE는
만들지 않는다.

### 부채비율

`DEBT_RATIO`

```text
부채 / 자기자본 * 100
```

```text
liabilities / equity * 100
```

대차대조표 시점 지표(balance-sheet instant metric)이며 TTM으로 계산하거나
`TTM Debt Ratio`로 이름 붙이지 않는다. `Q1_END`, `H1_END`, `Q3_END`,
`FY_END` 시점에서만 생성한다.

## 입력과 안전성 규칙

- 입력은 `MultiPeriodFundamentalsResult`의 `canonical_observations`를
  직접 소비할 수 있으며, 기존 PeriodizationResult/iterable 입력도 계속
  지원한다.
- 모든 원천 관측값은 `pit_available_from <= requested_as_of`여야 한다.
  미래·미확인·모호한 입력은 `READY`로 승격하지 않는다.
- 연간 ROE의 순이익/직전 자기자본/당기 자기자본, TTM ROE의 네 분기
  순이익/기초 자기자본/기말 자기자본, 부채비율의 부채/자기자본은
  재무제표 기준(`fs_div_used`)과 통화가 일치해야 한다. 불일치하면 각각
  `BASIS_MISMATCH` 또는 `CURRENCY_MISMATCH`로 fail-closed한다.
- ROE 평균 자기자본이 0 이하이면 `UNDEFINED_BASE`/
  `NON_POSITIVE_AVERAGE_EQUITY_BASE`이다.
- 부채비율 자기자본이 0 이하이면 `UNDEFINED_BASE`/
  `NON_POSITIVE_EQUITY_BASE`이다.
- 같은 시점 식별자에 PIT 사용 가능 후보가 여러 개면 임의로 하나를
  선택하지 않고 `PERIOD_AMBIGUOUS`로 남긴다.

## 출처 추적 정보

새 관측값도 기존 `DerivedMetricObservation`을 사용한다. 원천 접수
번호·일자·SHA, `requested_as_of`, `pit_available_from`을 기존
`_period_context()` 경로로 보존하며, 메타데이터에는 계산에 필요한
최소한의 기간 정보만 기록한다.

## 금융회사 처리

`company_family == FINANCIAL`이면 이번 V1 일반회사 프로파일에서
`ANNUAL_ROE`, `TTM_ROE`, `DEBT_RATIO`를 `NOT_APPLICABLE`로 처리한다.
금융업 전용 ROE/부채비율 프로파일이나 별도 점수는 이 단계에서 만들지
않는다.

## 제외 범위

이 문서는 ROE/부채비율 산식만 다룬다. Fundamentals Filter는
[필터 기준 문서](opendart_fundamentals_v1_filter.md), Stock Report/Markdown/
JSON 통합은 [Stock Report v0.5 계약](../reporting/stock_report/contract_v05.md),
운영 데이터 갱신은 별도 운영 스크립트가 각각 관리한다. ROA/ROIC/ROCE,
가치평가, DuPont 분해, 금융업 전용 프로파일은 V1 범위에서 제외한다.
PyKRX, KRX Open API, OpenDART live API, 웹 수집, 외부 시세 데이터 요청은
이 지표 계산에서 사용하지 않는다.
