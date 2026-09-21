opendart_fundamentals_v1_scope_freeze.md

======================================================================
OpenDART Fundamentals V1 — 적용 범위와 경계
======================================================================

목적
----------------------------------------------------------------------

이 문서는 Fundamentals V1이 다루는 회사 범위, 데이터 권위, PIT 원칙, 지원
지표, 금융회사 경계와 명시적 범위 제외를 정의하는 영속적인 범위 계약이다.
세부 산식과 임계값은 각 기준 문서(Multi-period, Filter, ROE/부채비율)에서
관리한다.

데이터 권위와 PIT 원칙
----------------------------------------------------------------------

OpenDART/XBRL이 Fundamentals V1의 유일한 production 데이터 권위 원천이다.
filing availability date가 as_of 이전인 공시 데이터만 사용하며, 미래 공시가
과거 시점 결과에 섞이는 것을 금지한다. Naver Finance 등 외부 데이터는 sanity
validation 참고 역할만 하며 production 권위를 대신하지 않는다.

지원 회사 범위
----------------------------------------------------------------------

- 일반 비금융 보통주와 비금융 지주회사(NON_FINANCIAL)를 지원한다.
- BANK/SECURITIES/INSURANCE/FINANCIAL_HOLDING 등 금융회사(FINANCIAL)의 일반
  V1 fundamentals는 `NOT_APPLICABLE`이다. 금융업 전용 매출·영업이익 해석이나
  NIM, CET1, 충당금 지표를 일반회사 지표로 변환하지 않으며, 금융회사에 대한
  별도 제품 범위는 이 V1에 포함하지 않는다.

지원 지표 범위
----------------------------------------------------------------------

- 분기·연간 매출, 영업이익, 당기순이익, 영업현금흐름(OCF)
- 분기·연간 YoY
- TTM 매출/영업이익/순이익/OCF와 TTM 마진
- Annual ROE, TTM ROE, 부채비율

산식, fail-closed 조건, basis/currency 일관성 규칙은
[ROE/부채비율 기준 문서](opendart_fundamentals_v1_roe_debt_ratio.md)에서
관리한다.

Stock Report 표시 범위
----------------------------------------------------------------------

- Quarterly: 최근 12개 confirmed standalone quarter.
- Annual: 최근 5개 confirmed fiscal year.
- Summary candidates: latest FY revenue, latest 4Q 평균 매출, TTM 지표.
- 확인되지 않은 기간, basis/currency 불일치, 모호한 context, 미래 filing은
  값을 0으로 대체하지 않고 그대로 미확인 상태로 남긴다.
- 표시 가능한 값이 없다는 이유로 필터 조건을 우회하거나 다른 원천으로
  대체하지 않는다.

표시 기간, coverage, readiness 계약의 세부 사항은
[Multi-period 기준 문서](opendart_fundamentals_v1_multi_period.md)에서
관리한다.

Fundamentals Filter 경계
----------------------------------------------------------------------

Fundamentals Filter는 독립된 필터 계약이며 조건, 임계값, 상태 우선순위는
[필터 기준 문서](opendart_fundamentals_v1_filter.md)에서 관리한다. cutoff와
threshold, Fundamentals Score, Pattern A Score와의 합산, valuation score,
매매 signal은 이 범위 문서가 확정하지 않는다.

명시적 범위 제외
----------------------------------------------------------------------

- PER, PBR, PSR, EV, EBITDA, PEG 및 모든 valuation
- composite score, Pattern A + Fundamentals 합산 점수
- automated signal/recommendation
- 금융회사 특화 fundamentals (NIM, CET1 등)
- dividend analytics
- DCF, fair value, target price
- PyKRX, KRX HTML/web scraping, Naver raw fallback을 canonical 원천으로 사용
- legacy ETF/parquet를 OpenDART canonical raw로 승격
- manual data injection 및 API 결과 대체

다른 기준 문서와의 관계
----------------------------------------------------------------------

- [Multi-period fundamentals](opendart_fundamentals_v1_multi_period.md) —
  표시 기간, coverage, readiness 계약
- [Fundamentals filter](opendart_fundamentals_v1_filter.md) — 필터 조건,
  임계값, 상태 우선순위
- [ROE / 부채비율](opendart_fundamentals_v1_roe_debt_ratio.md) — 파생 지표
  산식과 fail-closed 조건
- [Stock Report v0.5 계약](../reporting/stock_report/contract_v05.md) —
  Fundamentals 산출물을 Stock Report에 통합하는 계약
