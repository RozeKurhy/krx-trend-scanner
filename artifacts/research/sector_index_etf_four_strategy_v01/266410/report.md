# 266410 KODEX 필수소비재 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/266410.parquet`
- period: `2017-03-28 ~ 2026-08-21` / `2304` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `25`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 25, 'mean_delta_pct': 4.7516, 'median_delta_pct': 5.57, 'improved_count': 18, 'worsened_count': 7, 'same_count': 0}, 'V4': {'paired_count': 25, 'mean_delta_pct': -2.9456, 'median_delta_pct': -5.38, 'improved_count': 3, 'worsened_count': 16, 'same_count': 6}, 'Julia': {'paired_count': 25, 'mean_delta_pct': 2.232, 'median_delta_pct': 0.0, 'improved_count': 7, 'worsened_count': 0, 'same_count': 18}}`
- V3 vs Julia: `{'paired_count': 25, 'mean_delta_pct_julia_minus_v3': -2.5196, 'median_delta_pct_julia_minus_v3': -5.57, 'julia_better_count': 7, 'v3_better_count': 18, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 5.968, 'Julia': 3.4484, 'winner': 'V3'}, 'median_return_pct': {'V3': 7.22, 'Julia': 3.7, 'winner': 'V3'}, 'win_rate_pct': {'V3': 76.0, 'Julia': 56.0, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -17.7088, 'Julia': -17.7088, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 1.930686 | 0.203662 | -34.207202 | 30.989583 | 2 |
| V3 | 0.204918 | 0.021782 | -43.691149 | 59.722222 | 1 |
| V4 | -3.353346 | -0.362237 | -34.207202 | 30.902778 | 2 |
| Julia | -8.094262 | -0.894015 | -43.691149 | 58.159722 | 1 |
| Buy & Hold | -4.724793 | -0.513629 | -50.0 | 100.0 | None |

## same_window

- common entries: `20`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 20, 'mean_delta_pct': 2.0185, 'median_delta_pct': 5.495, 'improved_count': 13, 'worsened_count': 7, 'same_count': 0}, 'V4': {'paired_count': 20, 'mean_delta_pct': -3.6865, 'median_delta_pct': -5.54, 'improved_count': 2, 'worsened_count': 16, 'same_count': 2}, 'Julia': {'paired_count': 20, 'mean_delta_pct': 0.9275, 'median_delta_pct': 0.0, 'improved_count': 2, 'worsened_count': 0, 'same_count': 18}}`
- V3 vs Julia: `{'paired_count': 20, 'mean_delta_pct_julia_minus_v3': -1.091, 'median_delta_pct_julia_minus_v3': -5.495, 'julia_better_count': 7, 'v3_better_count': 13, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 7.5945, 'Julia': 6.5035, 'winner': 'V3'}, 'median_return_pct': {'V3': 9.64, 'Julia': 6.79, 'winner': 'V3'}, 'win_rate_pct': {'V3': 85.0, 'Julia': 70.0, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -12.137, 'Julia': -12.137, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 1.618335 | 0.298394 | -29.422271 | 43.45193 | 2 |
| V3 | -0.102145 | -0.018965 | -39.59596 | 93.565481 | 1 |
| V4 | -3.649505 | -0.687622 | -29.422271 | 43.30053 | 2 |
| Julia | -8.375894 | -1.610395 | -39.59596 | 90.840273 | 1 |
| Buy & Hold | -3.834808 | -0.723098 | -43.691149 | 100.0 | None |
