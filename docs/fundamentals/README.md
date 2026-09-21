README.md

# Fundamentals (OpenDART)

## 목적

Fundamentals 영역은 OpenDART/XBRL 공시를 기반으로 기업의 분기·연간 실적과
재무 지표를 계산해 Fundamentals Filter와 Stock Report에 제공한다.

## 데이터 권위

OpenDART/XBRL이 Fundamentals의 유일한 production 데이터 권위 원천이다.
Naver Finance 등 외부 데이터는 sanity validation 참고 역할만 하며 production
권위를 대신하지 않는다.

## PIT 원칙

기준일(as_of)에 filing availability date가 이미 지난 공시 데이터만
사용하며, 미래 공시가 과거 시점 결과에 섞이는 것(future filing leakage)을
금지한다.

## 지원 범위

- 일반 비금융 보통주와 비금융 지주회사(NON_FINANCIAL)를 지원한다.
- BANK/SECURITIES/INSURANCE/FINANCIAL_HOLDING 등 금융회사(FINANCIAL)는 일반
  Fundamentals V1 적용 대상이 아니며 `NOT_APPLICABLE`로 처리한다. 금융회사
  전용 지표와 계약은 이 범위에 포함하지 않는다.

## 핵심 지표

분기·연간 매출, 영업이익, 당기순이익, 영업현금흐름(OCF), 분기·연간 YoY,
TTM 지표, Annual/TTM ROE, 부채비율을 제공한다. 세부 산식과 fail-closed
조건은 [ROE/부채비율 기준 문서](opendart_fundamentals_v1_roe_debt_ratio.md)와
[Multi-period 기준 문서](opendart_fundamentals_v1_multi_period.md)에서
관리한다.

## 필터 역할

Fundamentals Filter는 매출·이익 조건으로 종목의 적격성을 판단하는 독립된
필터 계약이다. cutoff/threshold, Fundamentals Score, Pattern A Score와의
합산, valuation score, 매매 signal은 이 필터가 확정하지 않는다. 세부 조건과
임계값은 [필터 기준 문서](opendart_fundamentals_v1_filter.md)에서 관리한다.

## Stock Report와의 관계

Stock Report는 Fundamentals 산출물(Multi-period/파생지표/필터 결과)을 추가
계산 없이 그대로 소비한다. 통합 계약은
[Stock Report v0.5 계약](../reporting/stock_report/contract_v05.md)과
[schema](../reporting/stock_report/schema_v05.json)에서 관리한다.

## 현재 기준 문서

- [적용 범위와 경계](opendart_fundamentals_v1_scope_freeze.md)
- [Multi-period fundamentals](opendart_fundamentals_v1_multi_period.md)
- [Fundamentals filter](opendart_fundamentals_v1_filter.md)
- [ROE / 부채비율](opendart_fundamentals_v1_roe_debt_ratio.md)

## 역사 기록

`archive/`에는 초기 구현·FIX·감사 기록이 원문 그대로 보존되어 있다. 현재
기준은 위 문서를 따르며 archive 문서는 현재 계약의 권위를 대신하지 않는다.
