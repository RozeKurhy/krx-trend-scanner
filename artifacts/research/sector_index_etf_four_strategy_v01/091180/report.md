# 091180 KODEX 자동차 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/091180.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `19`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 19, 'mean_delta_pct': 32.284737, 'median_delta_pct': 55.82, 'improved_count': 17, 'worsened_count': 2, 'same_count': 0}, 'V4': {'paired_count': 19, 'mean_delta_pct': 0.034737, 'median_delta_pct': -0.21, 'improved_count': 6, 'worsened_count': 13, 'same_count': 0}, 'Julia': {'paired_count': 19, 'mean_delta_pct': 82.057895, 'median_delta_pct': 107.56, 'improved_count': 14, 'worsened_count': 0, 'same_count': 5}}`
- V3 vs Julia: `{'paired_count': 19, 'mean_delta_pct_julia_minus_v3': 49.773158, 'median_delta_pct_julia_minus_v3': 51.41, 'julia_better_count': 16, 'v3_better_count': 3, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 40.735263, 'Julia': 90.508421, 'winner': 'Julia'}, 'median_return_pct': {'V3': 42.95, 'Julia': 93.96, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -17.384737, 'Julia': -17.384737, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 99.381581 | 5.614474 | -43.384228 | 14.737182 | 4 |
| V3 | 123.790432 | 6.58446 | -32.566453 | 23.573041 | 3 |
| V4 | 44.728363 | 2.969743 | -42.845301 | 14.35021 | 4 |
| Julia | 212.945383 | 9.451548 | -33.670162 | 34.698484 | 2 |
| Buy & Hold | 30.790129 | 2.147612 | -64.308682 | 100.0 | None |

## same_window

- common eligible entries: `16`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 16, 'mean_delta_pct': 37.88625, 'median_delta_pct': 56.275, 'improved_count': 14, 'worsened_count': 2, 'same_count': 0}, 'V4': {'paired_count': 16, 'mean_delta_pct': -0.410625, 'median_delta_pct': -1.225, 'improved_count': 3, 'worsened_count': 13, 'same_count': 0}, 'Julia': {'paired_count': 16, 'mean_delta_pct': 97.44375, 'median_delta_pct': 107.885, 'improved_count': 14, 'worsened_count': 0, 'same_count': 2}}`
- V3 vs Julia: `{'paired_count': 16, 'mean_delta_pct_julia_minus_v3': 59.5575, 'median_delta_pct_julia_minus_v3': 51.715, 'julia_better_count': 16, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 39.491875, 'Julia': 99.049375, 'winner': 'Julia'}, 'median_return_pct': {'V3': 42.48, 'Julia': 95.09, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -19.803125, 'Julia': -19.803125, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 39.018773 | 6.304989 | -30.927973 | 21.423164 | 3 |
| V3 | 53.483913 | 8.276011 | -25.884758 | 42.240727 | 2 |
| V4 | -0.739834 | -0.137725 | -31.411763 | 20.590462 | 3 |
| Julia | 118.201114 | 15.581944 | -27.108566 | 68.281605 | 1 |
| Buy & Hold | 24.129781 | 4.093322 | -39.339698 | 100.0 | None |
