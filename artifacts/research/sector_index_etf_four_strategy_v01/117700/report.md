# 117700 KODEX 건설 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/117700.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `27`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 27, 'mean_delta_pct': -7.995926, 'median_delta_pct': -10.0, 'improved_count': 13, 'worsened_count': 14, 'same_count': 0}, 'V4': {'paired_count': 27, 'mean_delta_pct': -16.164444, 'median_delta_pct': -7.27, 'improved_count': 8, 'worsened_count': 17, 'same_count': 2}, 'Julia': {'paired_count': 27, 'mean_delta_pct': 47.331111, 'median_delta_pct': 0.0, 'improved_count': 13, 'worsened_count': 0, 'same_count': 14}}`
- V3 vs Julia: `{'paired_count': 27, 'mean_delta_pct_julia_minus_v3': 55.327037, 'median_delta_pct_julia_minus_v3': 12.93, 'julia_better_count': 27, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 19.104815, 'Julia': 74.431852, 'winner': 'Julia'}, 'median_return_pct': {'V3': 13.07, 'Julia': 31.37, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -13.683704, 'Julia': -23.798148, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 140.844965 | 7.205933 | -34.401968 | 34.34376 | 4 |
| V3 | 139.764134 | 7.16777 | -36.166848 | 31.247985 | 4 |
| V4 | 31.674486 | 2.202119 | -30.920245 | 24.475975 | 5 |
| Julia | 213.881284 | 9.477424 | -64.036223 | 51.370526 | 2 |
| Buy & Hold | 73.67688 | 4.466796 | -65.508685 | 100.0 | None |

## same_window

- common eligible entries: `12`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 12, 'mean_delta_pct': -26.443333, 'median_delta_pct': -18.135, 'improved_count': 6, 'worsened_count': 6, 'same_count': 0}, 'V4': {'paired_count': 12, 'mean_delta_pct': -38.966667, 'median_delta_pct': -33.37, 'improved_count': 2, 'worsened_count': 8, 'same_count': 2}, 'Julia': {'paired_count': 12, 'mean_delta_pct': 84.675833, 'median_delta_pct': 63.61, 'improved_count': 6, 'worsened_count': 0, 'same_count': 6}}`
- V3 vs Julia: `{'paired_count': 12, 'mean_delta_pct_julia_minus_v3': 111.119167, 'median_delta_pct_julia_minus_v3': 140.465, 'julia_better_count': 12, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 29.038333, 'Julia': 140.1575, 'winner': 'Julia'}, 'median_return_pct': {'V3': 16.12, 'Julia': 151.345, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -14.570833, 'Julia': -16.614167, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 119.932338 | 15.751593 | -26.380368 | 39.137017 | 2 |
| V3 | 87.277005 | 12.349623 | -35.582822 | 53.44436 | 2 |
| V4 | 8.542266 | 1.532939 | -30.920245 | 34.519304 | 3 |
| Julia | 163.776224 | 19.723395 | -35.582822 | 53.595761 | 1 |
| Buy & Hold | 83.382353 | 11.912272 | -47.482014 | 100.0 | None |
