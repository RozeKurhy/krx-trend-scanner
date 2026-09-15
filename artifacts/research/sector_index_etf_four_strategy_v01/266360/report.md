# 266360 KODEX K-콘텐츠 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/266360.parquet`
- period: `2017-03-28 ~ 2026-08-21` / `2304` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `5`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 5, 'mean_delta_pct': 15.842, 'median_delta_pct': -17.48, 'improved_count': 2, 'worsened_count': 3, 'same_count': 0}, 'V4': {'paired_count': 5, 'mean_delta_pct': 18.89, 'median_delta_pct': -6.21, 'improved_count': 2, 'worsened_count': 3, 'same_count': 0}, 'Julia': {'paired_count': 5, 'mean_delta_pct': 23.836, 'median_delta_pct': -17.48, 'improved_count': 2, 'worsened_count': 3, 'same_count': 0}}`
- V3 vs Julia: `{'paired_count': 5, 'mean_delta_pct_julia_minus_v3': 7.994, 'median_delta_pct_julia_minus_v3': 0.0, 'julia_better_count': 2, 'v3_better_count': 0, 'same_count': 3, 'metric_comparison': {'mean_return_pct': {'V3': 1.27, 'Julia': 9.264, 'winner': 'Julia'}, 'median_return_pct': {'V3': -29.87, 'Julia': -29.87, 'winner': 'tie'}, 'win_rate_pct': {'V3': 40.0, 'Julia': 40.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -30.894, 'Julia': -30.894, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | -30.233713 | -3.757952 | -34.15361 | 5.859375 | 2 |
| V3 | 0.345422 | 0.036694 | -46.641374 | 19.184028 | 2 |
| V4 | 9.619049 | 0.981921 | -42.528014 | 17.534722 | 2 |
| Julia | 13.688205 | 1.374278 | -40.329289 | 22.309028 | 2 |
| Buy & Hold | -0.100452 | -0.010692 | -66.618886 | 100.0 | None |

## same_window

- common eligible entries: `3`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 3, 'mean_delta_pct': -17.796667, 'median_delta_pct': -17.78, 'improved_count': 0, 'worsened_count': 3, 'same_count': 0}, 'V4': {'paired_count': 3, 'mean_delta_pct': -6.596667, 'median_delta_pct': -6.32, 'improved_count': 0, 'worsened_count': 3, 'same_count': 0}, 'Julia': {'paired_count': 3, 'mean_delta_pct': -17.796667, 'median_delta_pct': -17.78, 'improved_count': 0, 'worsened_count': 3, 'same_count': 0}}`
- V3 vs Julia: `{'paired_count': 3, 'mean_delta_pct_julia_minus_v3': 0.0, 'median_delta_pct_julia_minus_v3': 0.0, 'julia_better_count': 0, 'v3_better_count': 0, 'same_count': 3, 'metric_comparison': {'mean_return_pct': {'V3': -31.453333, 'Julia': -31.453333, 'winner': 'tie'}, 'median_return_pct': {'V3': -31.01, 'Julia': -31.01, 'winner': 'tie'}, 'win_rate_pct': {'V3': 0.0, 'Julia': 0.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -36.93, 'Julia': -36.93, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | -15.351171 | -3.045751 | -19.448895 | 9.159727 | 1 |
| V3 | -33.478261 | -7.286492 | -40.307594 | 21.650265 | 1 |
| V4 | -22.608696 | -4.64535 | -31.528356 | 18.016654 | 1 |
| Julia | -33.478261 | -7.286492 | -40.307594 | 21.650265 | 1 |
| Buy & Hold | -54.754322 | -13.686843 | -66.618886 | 100.0 | None |
