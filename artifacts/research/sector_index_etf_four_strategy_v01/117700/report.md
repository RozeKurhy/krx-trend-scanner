# 117700 KODEX 건설 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/117700.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `0`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}}`
- V3 vs Julia: `{'paired_count': 0, 'mean_delta_pct_julia_minus_v3': None, 'median_delta_pct_julia_minus_v3': None, 'julia_better_count': 0, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}, 'median_return_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}, 'win_rate_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| V3 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| V4 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| Julia | 213.881284 | 9.477424 | -64.036223 | 51.370526 | 2 |
| Buy & Hold | 73.67688 | 4.466796 | -65.508685 | 100.0 | None |

## same_window

- common entries: `0`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}}`
- V3 vs Julia: `{'paired_count': 0, 'mean_delta_pct_julia_minus_v3': None, 'median_delta_pct_julia_minus_v3': None, 'julia_better_count': 0, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}, 'median_return_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}, 'win_rate_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| V3 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| V4 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| Julia | 163.776224 | 19.723395 | -35.582822 | 53.595761 | 1 |
| Buy & Hold | 83.382353 | 11.912272 | -47.482014 | 100.0 | None |
