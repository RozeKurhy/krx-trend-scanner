# 102970 KODEX 증권 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/102970.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `35`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 35, 'mean_delta_pct': 29.03, 'median_delta_pct': 27.16, 'improved_count': 27, 'worsened_count': 8, 'same_count': 0}, 'V4': {'paired_count': 35, 'mean_delta_pct': -10.952857, 'median_delta_pct': -7.69, 'improved_count': 14, 'worsened_count': 20, 'same_count': 1}, 'Julia': {'paired_count': 35, 'mean_delta_pct': 58.697714, 'median_delta_pct': 87.23, 'improved_count': 19, 'worsened_count': 0, 'same_count': 16}}`
- V3 vs Julia: `{'paired_count': 35, 'mean_delta_pct_julia_minus_v3': 29.667714, 'median_delta_pct_julia_minus_v3': 77.99, 'julia_better_count': 23, 'v3_better_count': 12, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 65.543714, 'Julia': 95.211429, 'winner': 'Julia'}, 'median_return_pct': {'V3': 15.77, 'Julia': 91.71, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -24.489429, 'Julia': -38.179714, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 66.926408 | 4.139469 | -58.335274 | 63.785876 | 2 |
| V3 | 167.023346 | 8.085185 | -64.193441 | 69.300226 | 2 |
| V4 | 138.516086 | 7.123504 | -53.38386 | 40.922283 | 5 |
| Julia | 118.671875 | 6.389418 | -60.778936 | 67.236375 | 1 |
| Buy & Hold | 225.6479 | 9.796828 | -63.94352 | 100.0 | None |

## same_window

- common eligible entries: `5`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 5, 'mean_delta_pct': 94.372, 'median_delta_pct': 94.53, 'improved_count': 5, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 5, 'mean_delta_pct': 94.372, 'median_delta_pct': 94.53, 'improved_count': 5, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 5, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 5}}`
- V3 vs Julia: `{'paired_count': 5, 'mean_delta_pct_julia_minus_v3': -94.372, 'median_delta_pct_julia_minus_v3': -94.53, 'julia_better_count': 0, 'v3_better_count': 5, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 182.912, 'Julia': 88.54, 'winner': 'V3'}, 'median_return_pct': {'V3': 183.4, 'Julia': 88.87, 'winner': 'V3'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -9.806, 'Julia': -9.806, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 91.712329 | 12.838758 | -20.0195 | 30.507192 | 1 |
| V3 | 187.671233 | 21.66584 | -37.416182 | 43.679031 | 1 |
| V4 | 187.671233 | 21.66584 | -37.416182 | 43.679031 | 1 |
| Julia | 91.712329 | 12.838758 | -20.0195 | 30.507192 | 1 |
| Buy & Hold | 125.355597 | 16.276093 | -48.979288 | 100.0 | None |
