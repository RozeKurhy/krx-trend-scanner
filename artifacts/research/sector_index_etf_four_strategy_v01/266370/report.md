# 266370 KODEX IT Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/266370.parquet`
- period: `2017-03-28 ~ 2026-08-21` / `2300` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `33`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 33, 'mean_delta_pct': 3.053333, 'median_delta_pct': -3.11, 'improved_count': 13, 'worsened_count': 20, 'same_count': 0}, 'V4': {'paired_count': 33, 'mean_delta_pct': -3.279697, 'median_delta_pct': -4.9, 'improved_count': 6, 'worsened_count': 25, 'same_count': 2}, 'Julia': {'paired_count': 33, 'mean_delta_pct': 82.998182, 'median_delta_pct': 0.0, 'improved_count': 13, 'worsened_count': 0, 'same_count': 20}}`
- V3 vs Julia: `{'paired_count': 33, 'mean_delta_pct_julia_minus_v3': 79.944848, 'median_delta_pct_julia_minus_v3': 20.21, 'julia_better_count': 33, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 87.18303, 'Julia': 167.127879, 'winner': 'Julia'}, 'median_return_pct': {'V3': 30.63, 'Julia': 197.64, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -12.891515, 'Julia': -14.731212, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 196.732733 | 12.268202 | -37.024754 | 24.695652 | 5 |
| V3 | 392.008135 | 18.473598 | -43.283055 | 36.086957 | 3 |
| V4 | 220.760054 | 13.202093 | -43.283055 | 31.913043 | 4 |
| Julia | 402.456512 | 18.738771 | -41.470911 | 44.782609 | 2 |
| Buy & Hold | 574.622357 | 22.519987 | -50.063058 | 100.0 | None |

## same_window

- common entries: `24`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 24, 'mean_delta_pct': 3.64625, 'median_delta_pct': 0.0, 'improved_count': 12, 'worsened_count': 12, 'same_count': 0}, 'V4': {'paired_count': 24, 'mean_delta_pct': -5.267083, 'median_delta_pct': -4.935, 'improved_count': 5, 'worsened_count': 17, 'same_count': 2}, 'Julia': {'paired_count': 24, 'mean_delta_pct': 111.097083, 'median_delta_pct': 101.035, 'improved_count': 12, 'worsened_count': 0, 'same_count': 12}}`
- V3 vs Julia: `{'paired_count': 24, 'mean_delta_pct_julia_minus_v3': 107.450833, 'median_delta_pct_julia_minus_v3': 159.165, 'julia_better_count': 24, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 108.3175, 'Julia': 215.768333, 'winner': 'Julia'}, 'median_return_pct': {'V3': 29.965, 'Julia': 220.54, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -15.371667, 'Julia': -17.90125, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 150.108776 | 18.546994 | -32.239688 | 27.252082 | 3 |
| V3 | 239.845865 | 25.488238 | -43.283055 | 40.651022 | 2 |
| V4 | 121.5593 | 15.910037 | -43.283055 | 33.3838 | 3 |
| Julia | 220.706806 | 24.145477 | -41.470911 | 53.29296 | 1 |
| Buy & Hold | 213.697026 | 23.637327 | -50.063058 | 100.0 | None |
