# 091170 KODEX 은행 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/091170.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `36`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 36, 'mean_delta_pct': -40.345, 'median_delta_pct': -20.675, 'improved_count': 12, 'worsened_count': 24, 'same_count': 0}, 'V4': {'paired_count': 36, 'mean_delta_pct': -43.119722, 'median_delta_pct': -1.08, 'improved_count': 5, 'worsened_count': 19, 'same_count': 12}, 'Julia': {'paired_count': 36, 'mean_delta_pct': 25.524167, 'median_delta_pct': 0.0, 'improved_count': 7, 'worsened_count': 0, 'same_count': 29}}`
- V3 vs Julia: `{'paired_count': 36, 'mean_delta_pct_julia_minus_v3': 65.869167, 'median_delta_pct_julia_minus_v3': 92.22, 'julia_better_count': 31, 'v3_better_count': 5, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 23.980278, 'Julia': 89.849444, 'winner': 'Julia'}, 'median_return_pct': {'V3': 9.06, 'Julia': 97.09, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -13.324167, 'Julia': -13.387222, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 148.713652 | 7.479114 | -38.500278 | 53.66011 | 2 |
| V3 | 122.817397 | 6.547701 | -35.255255 | 46.501129 | 3 |
| V4 | 8.03589 | 0.613739 | -44.819237 | 28.926153 | 4 |
| Julia | 148.713652 | 7.479114 | -38.500278 | 53.66011 | 2 |
| Buy & Hold | 81.384526 | 4.826508 | -59.8316 | 100.0 | None |

## same_window

- common entries: `30`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 30, 'mean_delta_pct': -45.5, 'median_delta_pct': -34.225, 'improved_count': 7, 'worsened_count': 23, 'same_count': 0}, 'V4': {'paired_count': 30, 'mean_delta_pct': -48.394333, 'median_delta_pct': -23.92, 'improved_count': 0, 'worsened_count': 18, 'same_count': 12}, 'Julia': {'paired_count': 30, 'mean_delta_pct': 30.629, 'median_delta_pct': 0.0, 'improved_count': 7, 'worsened_count': 0, 'same_count': 23}}`
- V3 vs Julia: `{'paired_count': 30, 'mean_delta_pct_julia_minus_v3': 76.129, 'median_delta_pct_julia_minus_v3': 93.32, 'julia_better_count': 30, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 26.85, 'Julia': 102.979, 'winner': 'Julia'}, 'median_return_pct': {'V3': 11.725, 'Julia': 99.425, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -14.903667, 'Julia': -14.979333, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 120.042343 | 15.762336 | -35.255255 | 99.8486 | 1 |
| V3 | 88.024128 | 12.432673 | -35.255255 | 96.214989 | 2 |
| V4 | -10.354382 | -2.008218 | -44.819237 | 52.233157 | 3 |
| Julia | 120.042343 | 15.762336 | -35.255255 | 99.8486 | 1 |
| Buy & Hold | 114.590502 | 15.224568 | -35.255255 | 100.0 | None |
