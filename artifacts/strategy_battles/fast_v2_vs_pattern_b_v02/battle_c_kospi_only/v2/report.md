# battle_c_kospi_only — A FAST Core V2

전략 신호·청산 원장은 frozen 공식 CONTROL 원장을 사용했고, chronological cash-aware portfolio replay를 새로 수행했어.
- 공통 진입 순서: `ticker, exact ISU_CD, entry_signal_date, entry_execution_date`.
- worker: 10.
- Battle C는 entry identity의 exact entry-date PIT market이 KOSPI인 후보만 포함했고 시총 필터는 적용하지 않았어.

| Window | Return | CAGR | MDD / type | Coverage | Eligible | Executed / closed | Cash skip % | Median | +50 / +100 | Turnover |
|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|
| P1 | None | None | -46.272240475777295 / OBSERVED_BELOW_90_COVERAGE | 63.340843257161254 | 2046 | 553 / 511 | 72.97165200391007 | -15.607859203443914 | 63 / 26 | 5379157350.891998 |
| P2-1 | None | None | -27.02127083057977 / OBSERVED_BELOW_90_COVERAGE | 45.4713493530499 | 794 | 279 / 241 | 64.86146095717883 | -15.579007189496394 | 20 / 5 | 2572528478.079999 |
| P2-2 | None | None | -26.955139310104816 / OBSERVED_BELOW_90_COVERAGE | 35.47224224945926 | 1033 | 323 / 291 | 68.73184898354307 | -15.514942331721118 | 34 / 14 | 3096986259.5079994 |
| P3-1 | None | None | -24.620166897782948 / OBSERVED_BELOW_90_COVERAGE | 29.136690647482016 | 485 | 178 / 151 | 63.298969072164944 | -15.982935384761953 | 8 / 1 | 1570931886.349 |
| P3-2 | None | None | -24.620166897782948 / OBSERVED_BELOW_90_COVERAGE | 21.334503950834065 | 746 | 210 / 183 | 71.84986595174263 | -15.742604439741875 | 17 / 7 | 1929905283.115 |

이 문서는 양 전략 정면 비교용 포트폴리오 결과이며, 단독 채택 판정 문서가 아니야.
