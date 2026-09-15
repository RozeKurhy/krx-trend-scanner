# 140700 KODEX 보험 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/140700.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `47`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 47, 'mean_delta_pct': -62.92383, 'median_delta_pct': -76.73, 'improved_count': 17, 'worsened_count': 30, 'same_count': 0}, 'V4': {'paired_count': 47, 'mean_delta_pct': -71.339149, 'median_delta_pct': -74.86, 'improved_count': 5, 'worsened_count': 32, 'same_count': 10}, 'Julia': {'paired_count': 47, 'mean_delta_pct': 47.241915, 'median_delta_pct': 0.0, 'improved_count': 17, 'worsened_count': 0, 'same_count': 30}}`
- V3 vs Julia: `{'paired_count': 47, 'mean_delta_pct_julia_minus_v3': 110.165745, 'median_delta_pct_julia_minus_v3': 116.67, 'julia_better_count': 47, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 17.891064, 'Julia': 128.056809, 'winner': 'Julia'}, 'median_return_pct': {'V3': 20.35, 'Julia': 126.55, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -22.50766, 'Julia': -26.325319, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 148.070352 | 7.457081 | -36.823858 | 59.077717 | 2 |
| V3 | 72.459624 | 4.408648 | -68.055098 | 71.009352 | 3 |
| V4 | 44.00201 | 2.928739 | -23.210832 | 39.72912 | 4 |
| Julia | 124.299065 | 6.603617 | -67.721823 | 74.846824 | 1 |
| Buy & Hold | 149.79351 | 7.515981 | -67.721823 | 100.0 | None |

## same_window

- common eligible entries: `32`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 32, 'mean_delta_pct': -109.213125, 'median_delta_pct': -132.795, 'improved_count': 2, 'worsened_count': 30, 'same_count': 0}, 'V4': {'paired_count': 32, 'mean_delta_pct': -106.723125, 'median_delta_pct': -125.665, 'improved_count': 2, 'worsened_count': 30, 'same_count': 0}, 'Julia': {'paired_count': 32, 'mean_delta_pct': 11.664688, 'median_delta_pct': 0.0, 'improved_count': 2, 'worsened_count': 0, 'same_count': 30}}`
- V3 vs Julia: `{'paired_count': 32, 'mean_delta_pct_julia_minus_v3': 120.877812, 'median_delta_pct_julia_minus_v3': 135.93, 'julia_better_count': 32, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 16.779688, 'Julia': 137.6575, 'winner': 'Julia'}, 'median_return_pct': {'V3': 18.82, 'Julia': 154.75, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -8.211562, 'Julia': -8.335938, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 190.688872 | 21.901702 | -23.210832 | 95.306586 | 1 |
| V3 | 86.049197 | 12.212552 | -23.210832 | 77.971234 | 4 |
| V4 | 35.680485 | 5.826516 | -23.210832 | 71.006813 | 3 |
| Julia | 190.688872 | 21.901702 | -23.210832 | 95.306586 | 1 |
| Buy & Hold | 235.499208 | 25.188794 | -23.210832 | 100.0 | None |
