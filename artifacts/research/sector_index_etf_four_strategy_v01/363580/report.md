# 363580 KODEX 200IT TR Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/363580.parquet`
- period: `2020-09-25 ~ 2026-08-21` / `1445` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `21`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 21, 'mean_delta_pct': 151.060476, 'median_delta_pct': 88.52, 'improved_count': 21, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 21, 'mean_delta_pct': 51.199524, 'median_delta_pct': 75.02, 'improved_count': 15, 'worsened_count': 5, 'same_count': 1}, 'Julia': {'paired_count': 21, 'mean_delta_pct': 68.082857, 'median_delta_pct': 0.0, 'improved_count': 8, 'worsened_count': 0, 'same_count': 13}}`
- V3 vs Julia: `{'paired_count': 21, 'mean_delta_pct_julia_minus_v3': -82.977619, 'median_delta_pct_julia_minus_v3': -84.08, 'julia_better_count': 0, 'v3_better_count': 21, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 252.083333, 'Julia': 169.105714, 'winner': 'V3'}, 'median_return_pct': {'V3': 256.76, 'Julia': 172.68, 'winner': 'V3'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -14.441429, 'Julia': -14.441429, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 147.189599 | 16.569147 | -24.296424 | 15.640138 | 2 |
| V3 | 253.539157 | 23.854366 | -45.150342 | 37.439446 | 1 |
| V4 | 200.190402 | 20.46926 | -45.150342 | 26.989619 | 2 |
| Julia | 170.218373 | 18.341542 | -39.663866 | 30.449827 | 1 |
| Buy & Hold | 472.817048 | 34.405239 | -51.509378 | 100.0 | None |

## same_window

- common eligible entries: `21`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 21, 'mean_delta_pct': 151.060476, 'median_delta_pct': 88.52, 'improved_count': 21, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 21, 'mean_delta_pct': 51.199524, 'median_delta_pct': 75.02, 'improved_count': 15, 'worsened_count': 5, 'same_count': 1}, 'Julia': {'paired_count': 21, 'mean_delta_pct': 68.082857, 'median_delta_pct': 0.0, 'improved_count': 8, 'worsened_count': 0, 'same_count': 13}}`
- V3 vs Julia: `{'paired_count': 21, 'mean_delta_pct_julia_minus_v3': -82.977619, 'median_delta_pct_julia_minus_v3': -84.08, 'julia_better_count': 0, 'v3_better_count': 21, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 252.083333, 'Julia': 169.105714, 'winner': 'V3'}, 'median_return_pct': {'V3': 256.76, 'Julia': 172.68, 'winner': 'V3'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -14.441429, 'Julia': -14.441429, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 147.189599 | 18.288969 | -24.296424 | 17.108251 | 2 |
| V3 | 253.539157 | 26.411619 | -45.150342 | 40.953823 | 1 |
| V4 | 200.190402 | 22.631553 | -45.150342 | 29.523089 | 2 |
| Julia | 170.218373 | 20.260751 | -39.663866 | 33.3081 | 1 |
| Buy & Hold | 277.560809 | 27.963351 | -51.509378 | 100.0 | None |
