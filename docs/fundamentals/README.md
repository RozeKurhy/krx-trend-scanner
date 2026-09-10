README.md

# Fundamentals (OpenDART)

OpenDART/XBRL 기반 재무 기초 데이터의 current authority index와 구현·검증 이력이다.

## Current Status

- **Fundamentals V1**: `FINAL_CLOSED / PRODUCTION`
- **기준일**: 2026-09-04 production certified boundary
- **범위**: 분기·연간 매출, 영업이익, 당기순이익, 영업현금흐름, ROE, 부채비율, YoY 및 TTM
- **PIT**: 기준일에 허용되는 최신 비교기간과 `filing availability date <= as_of`인 공시 데이터만 사용하며 future filing leakage를 금지한다.
- **회사 범위**: 일반 비금융 보통주와 비금융 지주회사를 지원한다. BANK/SECURITIES/INSURANCE/FINANCIAL_HOLDING 등 금융회사의 일반 V1 fundamentals는 `NOT_APPLICABLE`이며 전용 확장은 미래 범위다.
- **필터**: Fundamentals Filter는 production filter status를 제공한다. cutoff/threshold, Fundamentals Score, Pattern A Score와의 합산, valuation score 및 매매 signal은 임의로 확정하지 않는다.
- **외부 검증 역할**: Naver Finance는 sanity validation reference이고, production authority는 OpenDART/XBRL이다.

## Current Authority Documents

- [Scope freeze](opendart_fundamentals_v1_scope_freeze.md)
- [Multi-period fundamentals](opendart_fundamentals_v1_multi_period.md)
- [Fundamentals filter](opendart_fundamentals_v1_filter.md)
- [ROE / debt ratio](opendart_fundamentals_v1_roe_debt_ratio.md)
- [Stock Report v0.5 contract](../reporting/stock_report/contract_v05.md)
- [Stock Report v0.5 schema](../reporting/stock_report/schema_v05.json)

## Validation Closure

- [Independent validation v0.6](../../artifacts/fundamentals/validation/fundamentals_v1_independent_validation_v06/validation_summary.json)
- [FIX01 closure](../../artifacts/fundamentals/validation/fundamentals_v1_edge_case_closure_v08_fix01/validation_summary.json)
- [FIX02 closure](../../artifacts/fundamentals/validation/fundamentals_v1_edge_case_closure_v08_fix02/validation_summary.json)

## Implementation History

The earlier v0.1 architecture, assessment, core, derived-metrics, periodization, and Q1 audit documents remain as implementation history. Current status is governed by the V1 documents above; historical fix generations are not current authority.
