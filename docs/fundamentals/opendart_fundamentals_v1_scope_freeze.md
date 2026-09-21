# OpenDART Fundamentals V1 - 적용 범위와 경계

## 목적

이 문서는 Fundamentals V1이 다루는 적용 대상, 데이터 권위, PIT 원칙, 지원
지표, 금융회사 경계와 제외 범위를 정의하는 영속적인 범위 계약이다. 세부
산식과 임계값은 각 기준 문서(Multi-period, Filter, ROE/부채비율)에서
관리한다.

## 데이터 권위와 PIT 원칙

OpenDART/XBRL이 Fundamentals V1의 유일한 운영 데이터 권위 원천이다. PIT는
`DAILY_EOD_KST` 기준이며, `as_of` 당일을 포함해 그 시점까지 이용 가능해진
공시 데이터만 사용한다(filing availability date `<= as_of`). 미래 공시가
과거 시점 결과에 섞이는 것을 금지한다. Naver Finance 등 외부 데이터는
검증 참고 자료 역할만 하며 운영 데이터 권위를 대신하지 않는다.

## 적용 대상

- 일반 비금융 보통주와 비금융 지주회사(NON_FINANCIAL)를 지원한다.
- BANK/SECURITIES/INSURANCE/FINANCIAL_HOLDING 등 금융회사(FINANCIAL)의
  일반 Fundamentals V1 지표는 `NOT_APPLICABLE`이다. 금융업 전용 매출·영업
  이익 해석이나 NIM, CET1, 충당금 지표를 일반회사 지표로 변환하지 않으며,
  금융회사에 대한 별도 제품 범위는 이 V1에 포함하지 않는다.

## 지원 지표

- 분기·연간 매출, 영업이익, 당기순이익, 영업현금흐름(OCF)
- 분기·연간 YoY
- TTM 매출/영업이익/순이익/OCF와 TTM 마진
- 연간 ROE, TTM ROE, 부채비율

## 핵심 산식

- TTM = 최신 4개 연속 독립 분기(standalone quarter)의 합
- Quarterly YoY = 현재 분기와 4분기 전 동일 분기 비교
- Annual YoY = 현재 FY와 직전 FY 비교
- Operating margin = operating income / revenue * 100
- Net margin = net income / revenue * 100
- OCF margin = operating cash flow / revenue * 100

ROE와 부채비율 산식, 실패 시 차단 조건, 재무제표 기준/통화 일관성 규칙은
[ROE/부채비율 기준 문서](opendart_fundamentals_v1_roe_debt_ratio.md)에서
관리한다.

## Stock Report 표시 범위

- 분기: 최근 12개 확정된 독립 분기(confirmed standalone quarter)
- 연간: 최근 5개 확정된 회계연도(confirmed fiscal year)
- 요약 지표: 최신 FY 매출, 최신 4개 분기 평균 매출, TTM 지표
- 확인되지 않은 기간, 재무제표 기준/통화 불일치, 모호한 context, 미래
  공시는 값을 0으로 대체하지 않고 그대로 미확인 상태로 남긴다.
- 표시 가능한 값이 없다는 이유로 필터 조건을 우회하거나 다른 원천으로
  대체하지 않는다.

표시 기간, 데이터 충족 범위와 사용 가능 여부 계약의 세부 사항은
[Multi-period 기준 문서](opendart_fundamentals_v1_multi_period.md)에서
관리한다.

## Fundamentals Filter 경계

Fundamentals Filter는 독립된 필터 계약이며 조건, 임계값, 상태 우선순위는
[필터 기준 문서](opendart_fundamentals_v1_filter.md)에서 관리한다. 필터의
구체적인 기준값과 임계값, Fundamentals Score, Pattern A Score와의 합산,
가치평가 점수, 매매 신호는 이 범위 문서가 확정하지 않는다.

## 제외 범위

- PER, PBR, PSR, EV, EBITDA, PEG 등 모든 가치평가
- composite score, Pattern A + Fundamentals 합산 점수
- 자동 매매 신호/추천
- 금융회사 특화 fundamentals (NIM, CET1 등)
- 배당 분석
- DCF, 적정가치, 목표가
- PyKRX, KRX HTML/웹 수집, Naver 원천 데이터 대체 경로를 정본(canonical)
  원천으로 사용
- 기존 ETF/parquet 데이터를 OpenDART 정본(canonical) raw로 승격
- 수동 데이터 주입 및 API 결과 대체

## 관련 기준 문서

- [Multi-period fundamentals](opendart_fundamentals_v1_multi_period.md) —
  표시 기간, 데이터 충족 범위, 사용 가능 여부 계약
- [Fundamentals filter](opendart_fundamentals_v1_filter.md) — 필터 조건,
  임계값, 상태 우선순위
- [ROE / 부채비율](opendart_fundamentals_v1_roe_debt_ratio.md) — 파생 지표
  산식과 실패 시 차단 조건
- [Stock Report v0.5 계약](../reporting/stock_report/contract_v05.md) —
  Fundamentals 산출물을 Stock Report에 통합하는 계약
