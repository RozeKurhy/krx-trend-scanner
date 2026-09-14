# 140710 KODEX 운송 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/140710.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `23`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 23, 'mean_delta_pct': 1.449565, 'median_delta_pct': 4.14, 'improved_count': 12, 'worsened_count': 8, 'same_count': 3}, 'V4': {'paired_count': 23, 'mean_delta_pct': -5.981739, 'median_delta_pct': -7.25, 'improved_count': 2, 'worsened_count': 14, 'same_count': 7}, 'Julia': {'paired_count': 23, 'mean_delta_pct': 6.27, 'median_delta_pct': 0.0, 'improved_count': 6, 'worsened_count': 1, 'same_count': 16}}`
- V3 vs Julia: `{'paired_count': 23, 'mean_delta_pct_julia_minus_v3': 4.820435, 'median_delta_pct_julia_minus_v3': 0.0, 'julia_better_count': 10, 'v3_better_count': 7, 'same_count': 6, 'metric_comparison': {'mean_return_pct': {'V3': 5.135652, 'Julia': 9.956087, 'winner': 'Julia'}, 'median_return_pct': {'V3': 6.29, 'Julia': 15.33, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 73.913043, 'Julia': 69.565217, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -13.364348, 'Julia': -13.811739, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | -18.352044 | -1.592209 | -28.790469 | 11.99613 | 3 |
| V3 | 1.163511 | 0.091615 | -23.270847 | 18.413415 | 2 |
| V4 | -24.165585 | -2.165942 | -28.790469 | 10.287004 | 3 |
| Julia | 96.182327 | 5.47932 | -50.13369 | 50.20961 | 2 |
| Buy & Hold | 69.892473 | 4.284766 | -63.359528 | 100.0 | None |

## same_window

- common entries: `23`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 23, 'mean_delta_pct': 1.449565, 'median_delta_pct': 4.14, 'improved_count': 12, 'worsened_count': 8, 'same_count': 3}, 'V4': {'paired_count': 23, 'mean_delta_pct': -5.981739, 'median_delta_pct': -7.25, 'improved_count': 2, 'worsened_count': 14, 'same_count': 7}, 'Julia': {'paired_count': 23, 'mean_delta_pct': 6.27, 'median_delta_pct': 0.0, 'improved_count': 6, 'worsened_count': 1, 'same_count': 16}}`
- V3 vs Julia: `{'paired_count': 23, 'mean_delta_pct_julia_minus_v3': 4.820435, 'median_delta_pct_julia_minus_v3': 0.0, 'julia_better_count': 10, 'v3_better_count': 7, 'same_count': 6, 'metric_comparison': {'mean_return_pct': {'V3': 5.135652, 'Julia': 9.956087, 'winner': 'Julia'}, 'median_return_pct': {'V3': 6.29, 'Julia': 15.33, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 73.913043, 'Julia': 69.565217, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -13.364348, 'Julia': -13.811739, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | -18.352044 | -3.693071 | -28.790469 | 28.160484 | 3 |
| V3 | 1.163511 | 0.214925 | -23.270847 | 43.22483 | 2 |
| V4 | -24.165585 | -5.004321 | -28.790469 | 24.148372 | 3 |
| Julia | 20.380952 | 3.502557 | -23.270847 | 48.296745 | 1 |
| Buy & Hold | 3.69155 | 0.675057 | -47.909754 | 100.0 | None |
