# ETF V06 A FAST vs Julia 실전 포트폴리오 배틀 V03

- Verdict: ETF_V06_AFAST_VS_JULIA_REALISTIC_PORTFOLIO_BATTLE_V03_COMPLETE
- 기간: 2014-01-02 ~ 2026-08-31 (체결 지원 2026-09-01)
- Universe: V06 CURRENT SURVIVING PLAIN LONG, 지정 영구 제외 2종목 유지
- 데이터: KRX raw OHLCV; RAW_PRICE_LIMITATION=TRUE; SURVIVORSHIP_BIAS=TRUE
- Select Core: readiness, common start, candidate ledger, portfolio 실행에 사용하지 않음
- 공통 시작: Group A 108 ETF; Group B 156 ETF
- Sample: SAMPLE_PASS (5 ETF); Full worker: 10; full-run attempt: 1
- 포트폴리오: 초기자본 200,000,000원, 매수 notional 5,000,000원 상한, 정수 수량, 무레버리지, cash shortage는 CASH_SKIP, 동시보유 상한 없음.
- 비용: 매수·매도 수수료 각 0.015%; 매수 슬리피지 +0.1%, 매도 -0.1%; 매도세 0%.
- 체결 순서: 해당 날짜 매도를 먼저 처리하고 매도 대금은 같은 세션의 다음 정렬 매수에 재사용. 신규 진입은 신호 다음 첫 exact KRX 세션 시가.
- Equity curve는 2014-01-02부터 2026-09-01까지 저장해. 2026-09-01은 cutoff 이전 exit 신호의 체결 지원일이며 신규 진입은 없어. TERMINAL 평가는 2026-08-31 raw close야.

## Portfolio 비교

| 전략 | Final equity | Return | CAGR | MDD | Avg cash ratio | Avg invested ratio | Avg positions | Max positions | CASH_SKIP | Fill rate | Median holding | Terminal # / value |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 400,075,798.85 | 100.04% | 5.63% | -29.72% | 39.11% | 60.89% | 24.52 | 56.00 | 174 | 51.12% | 196.00 | 40 / 281,437,645.00 |
| JULIA_STRATEGY_V00 | 451,686,151.19 | 125.84% | 6.65% | -36.59% | 35.99% | 64.01% | 30.65 | 68.00 | 135 | 46.43% | 770.00 | 52 / 327,193,815.00 |

## Parity

- Group A exact V06 parity mismatch: 0
- Group B: 156 ETF; 시작일 앞당김 14~788일; trade path 변경 ETF 24개.
- Group B divergence: PRE_V06_WINDOW_ONLY 2건; LIFECYCLE_CARRYOVER 46건; POST_V06_UNEXPLAINED_DIVERGENCE 0건.
- ETF·전략별 근거는 parity_report.json에 기록했어.

## Category realized contribution

| 전략 | Category | Filled | Positive rate | Median net return | Capital deployed | Realized P/L |
|---|---|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | MARKET_INDEX | 73 | 40.00% | -14.48% | 364,070,927.22 | 53,335,024.93 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | SECTOR_INDUSTRY | 90 | 39.19% | -15.16% | 449,444,760.76 | 39,051,867.54 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | COMMODITY_RESOURCE | 19 | 50.00% | -3.82% | 94,920,060.23 | 25,744,850.34 |
| JULIA_STRATEGY_V00 | MARKET_INDEX | 51 | 91.67% | 59.24% | 254,304,190.14 | 72,463,889.30 |
| JULIA_STRATEGY_V00 | SECTOR_INDUSTRY | 56 | 87.88% | 37.83% | 279,663,709.32 | 75,481,099.16 |
| JULIA_STRATEGY_V00 | COMMODITY_RESOURCE | 10 | 100.00% | 77.38% | 49,946,631.73 | 36,065,229.31 |

## Annual returns

| 전략 | Year | Return |
|---|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2014 | 0.00% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2015 | 0.00% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2016 | 0.00% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2017 | 11.52% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2018 | -15.59% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2019 | 10.03% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2020 | 8.75% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2021 | 5.54% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2022 | -14.05% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2023 | 9.36% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2024 | 6.97% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2025 | 35.94% |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 2026_YTD | 23.11% |
| JULIA_STRATEGY_V00 | 2014 | 0.00% |
| JULIA_STRATEGY_V00 | 2015 | 0.00% |
| JULIA_STRATEGY_V00 | 2016 | 0.00% |
| JULIA_STRATEGY_V00 | 2017 | 11.34% |
| JULIA_STRATEGY_V00 | 2018 | -16.04% |
| JULIA_STRATEGY_V00 | 2019 | 12.25% |
| JULIA_STRATEGY_V00 | 2020 | 18.89% |
| JULIA_STRATEGY_V00 | 2021 | 12.37% |
| JULIA_STRATEGY_V00 | 2022 | -9.83% |
| JULIA_STRATEGY_V00 | 2023 | 7.26% |
| JULIA_STRATEGY_V00 | 2024 | 8.77% |
| JULIA_STRATEGY_V00 | 2025 | 32.52% |
| JULIA_STRATEGY_V00 | 2026_YTD | 15.56% |

## Validation

- Verdict: ETF_V06_AFAST_VS_JULIA_REALISTIC_PORTFOLIO_BATTLE_V03_COMPLETE
- Passed: True
- Portfolio run attempts: 1
- Candidate ETFs requested / zero-candidate requested: 197 / 0
- Candidate-required price coverage missing: 0
- Negative cash / leverage / >5M notional: 0 / 0.0 / 0
- Post-cutoff entry / future fallback / nearest-date fallback: 0 / 0 / 0
- Unauthorized ETF / exclusion: 0 / 0
- Eligibility / execution timing / exact price / same-day ordering mismatches: 0 / 0 / 0 / 0
- Group A parity mismatches / Group B unexplained divergences: 0 / 0
- Revalidation replay counts (candidate / portfolio): 0 / 0
- Worker runtime: {"lifecycle_wall_seconds": 169.947, "portfolio_wall_seconds": 2.086, "total_wall_seconds": 173.925, "worker_count": 10}

## Artifacts

- candidate_trade_ledger.csv
- candidate_summary.json
- portfolio_trade_ledger.csv
- portfolio_metrics.csv
- execution_summary.csv
- equity_curve.csv
- annual_returns.csv
- category_contribution.csv
- parity_report.json
- validation.json
- preflight_sample.json
