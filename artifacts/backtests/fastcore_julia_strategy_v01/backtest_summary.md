# FastCore vs Julia STEP 1 Strategy Comparison Backtest

## Contract
- Backtest end: 2026-09-04
- COMMON universe: 2555 tickers
- Entry filter: market cap >= 300,000,000,000 KRW, 20D avg trading value >= 300,000,000 KRW, close >= 5,000 KRW (entry-only, re-evaluated on re-entry)
- Strategy difference: loss_guard_enabled boolean only (FastCore=True, Julia=False)
- OTHER_STRATEGY_DIFFERENCE_COUNT: 0
- First actual entry date: 2013-01-02
- Last signal date: 2026-08-21
- Last execution date: 2026-08-24
- Transaction cost: NOT_APPLIED / Slippage: NOT_APPLIED
- Network requests: 0

## Headline comparison

| Metric | FastCore (Loss Guard ON) | Julia (Loss Guard OFF) |
|---|---:|---:|
| Total trades | 1850 | 1039 |
| Unique tickers | 662 | 662 |
| Loss cut count | 1171 | 0 |
| Mean terminal return | 7.56% | 24.1% |
| Median terminal return | -15.27% | 12.25% |
| Return <= -20% rate | 6.92% | 29.16% |
| Return >= +50% rate | 15.08% | 29.36% |

## Comparison buckets
- SHARED_ENTRY: 662
- FASTCORE_ONLY_REENTRY: 811
- JULIA_ONLY_ENTRY: 0
- SHARED_REENTRY: 377
- UNPAIRED_AFTER_STRATEGY_DIVERGENCE: 0
- Loss-cut counterfactual rows: 439
