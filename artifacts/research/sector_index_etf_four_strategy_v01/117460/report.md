# 117460 KODEX 에너지화학 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/117460.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `42`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 42, 'mean_delta_pct': 14.007381, 'median_delta_pct': 18.89, 'improved_count': 26, 'worsened_count': 16, 'same_count': 0}, 'V4': {'paired_count': 42, 'mean_delta_pct': 5.476667, 'median_delta_pct': 0.79, 'improved_count': 21, 'worsened_count': 16, 'same_count': 5}, 'Julia': {'paired_count': 42, 'mean_delta_pct': 35.299524, 'median_delta_pct': 0.0, 'improved_count': 20, 'worsened_count': 2, 'same_count': 20}}`
- V3 vs Julia: `{'paired_count': 42, 'mean_delta_pct_julia_minus_v3': 21.292143, 'median_delta_pct_julia_minus_v3': 10.345, 'julia_better_count': 36, 'v3_better_count': 6, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 17.981905, 'Julia': 39.274048, 'winner': 'Julia'}, 'median_return_pct': {'V3': 21.86, 'Julia': 38.4, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 92.857143, 'Julia': 83.333333, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -16.163095, 'Julia': -30.98619, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 17.967063 | 1.316615 | -39.52016 | 39.116414 | 4 |
| V3 | 46.690524 | 3.079569 | -62.844437 | 40.212835 | 5 |
| V4 | 33.345419 | 2.30419 | -45.604076 | 30.151564 | 5 |
| Julia | 28.414651 | 1.999505 | -60.846385 | 58.20703 | 2 |
| Buy & Hold | 24.600939 | 1.756365 | -60.846385 | 100.0 | None |

## same_window

- common entries: `9`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 9, 'mean_delta_pct': 8.741111, 'median_delta_pct': 14.31, 'improved_count': 6, 'worsened_count': 3, 'same_count': 0}, 'V4': {'paired_count': 9, 'mean_delta_pct': 5.208889, 'median_delta_pct': 14.14, 'improved_count': 6, 'worsened_count': 3, 'same_count': 0}, 'Julia': {'paired_count': 9, 'mean_delta_pct': -2.83, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 2, 'same_count': 7}}`
- V3 vs Julia: `{'paired_count': 9, 'mean_delta_pct_julia_minus_v3': -11.571111, 'median_delta_pct_julia_minus_v3': -14.31, 'julia_better_count': 3, 'v3_better_count': 6, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 0.063333, 'Julia': -11.507778, 'winner': 'V3'}, 'median_return_pct': {'V3': 8.75, 'Julia': -6.08, 'winner': 'V3'}, 'win_rate_pct': {'V3': 66.666667, 'Julia': 22.222222, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -18.924444, 'Julia': -22.827778, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | -18.178255 | -3.655059 | -35.08316 | 20.287661 | 2 |
| V3 | -6.873094 | -1.312869 | -40.462578 | 17.486752 | 3 |
| V4 | -23.903927 | -4.943573 | -40.462578 | 16.956851 | 3 |
| Julia | -25.891388 | -5.409321 | -59.914611 | 58.213475 | 1 |
| Buy & Hold | -30.632514 | -6.562886 | -60.541676 | 100.0 | None |
