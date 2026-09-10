# V06 external sanity evidence

- Requested as-of: `2026-09-04`; validation run: `2026-09-10`.
- The production value is shown as ACTUAL; the raw/local XBRL value is shown as the independent check. No Naver value is substituted into production.

## Required spot checks

### Samsung Biologics (207940)
- FY2024 revenue ACTUAL `4547322176421` KRW; independent raw XBRL `4547322176421` KRW; status `MATCH`.
- The current Naver page shows FY2024 revenue `34,971억원`, while the official company release reports consolidated `45,473억원` and separate Logicus `34,971억원`; this confirms a basis distinction, so Naver is not treated as comparable to the consolidated DART value.
- References: [Naver Samsung Biologics](https://finance.naver.com/item/main.naver?code=207940), [Samsung Biologics FY2024 result](https://samsungbiologics.com/kr/media/company-news/samsung-biologics-reports-fourth-quarter-and-fiscal-year-2024-financial-results).

### Pearl Abyss (263750)
- 2025Q1 operating income ACTUAL `-5242125423` KRW; independent raw XBRL `-5242125423` KRW; status `MATCH`.
- The current Naver page has no 2025Q1 column, so the independently parsed DART fact's negative sign is checked against the prior external report context and is not overwritten by a stale/different display.
- References: [Naver Pearl Abyss](https://finance.naver.com/item/main.naver?code=263750), [EDaily Q1 report](https://www.edaily.co.kr/News/Read?mediaCodeNo=257&newsId=02587926642168920).

### Hyundai Construction (000720)
- 2025Q2 revenue ACTUAL `7720720000000` KRW; independent raw XBRL `7720720000000` KRW; status `MATCH`; semantics `CONSOLIDATED_PRIMARY_XBRL_FACT`.
- 2025Q2 operating_income ACTUAL `217001000000` KRW; independent raw XBRL `217001000000` KRW; status `MATCH`; semantics `CONSOLIDATED_PRIMARY_XBRL_FACT`.
- 2025Q2 net_income ACTUAL `158584000000` KRW; independent raw XBRL `158584000000` KRW; status `MATCH`; semantics `CONSOLIDATED_TOTAL_PROFIT_LOSS`.
- Net income is compared as `ifrs-full:ProfitLoss` (consolidated total profit/loss). If an external page uses attributable-owner net income, that is `NOT_COMPARABLE_METRIC_SEMANTICS`, not a production mismatch.
- Reference: [Naver Hyundai Construction](https://finance.naver.com/item/main.naver?code=000720).

## Interpretation

- This is an external sanity sample, not a second production collection. It uses already cached local filing/XBRL evidence and public reference links for semantic context.
