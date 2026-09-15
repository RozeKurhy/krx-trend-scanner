# 117680 KODEX 철강 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/117680.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `34`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 34, 'mean_delta_pct': 8.399118, 'median_delta_pct': 18.97, 'improved_count': 19, 'worsened_count': 15, 'same_count': 0}, 'V4': {'paired_count': 34, 'mean_delta_pct': -4.291765, 'median_delta_pct': -4.24, 'improved_count': 9, 'worsened_count': 24, 'same_count': 1}, 'Julia': {'paired_count': 34, 'mean_delta_pct': 43.153529, 'median_delta_pct': 21.675, 'improved_count': 19, 'worsened_count': 0, 'same_count': 15}}`
- V3 vs Julia: `{'paired_count': 34, 'mean_delta_pct_julia_minus_v3': 34.754412, 'median_delta_pct_julia_minus_v3': 5.19, 'julia_better_count': 33, 'v3_better_count': 1, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 16.887353, 'Julia': 51.641765, 'winner': 'Julia'}, 'median_return_pct': {'V3': 12.785, 'Julia': 44.37, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -20.350588, 'Julia': -23.455588, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 21.030011 | 1.52241 | -50.994673 | 38.019994 | 6 |
| V3 | 49.680476 | 3.24435 | -67.154255 | 48.69397 | 4 |
| V4 | 41.439583 | 2.782549 | -39.344413 | 35.31119 | 4 |
| Julia | 124.880962 | 6.625484 | -67.154255 | 61.270558 | 2 |
| Buy & Hold | 16.966068 | 1.248292 | -67.154255 | 100.0 | None |

## same_window

- common eligible entries: `16`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 16, 'mean_delta_pct': 10.096875, 'median_delta_pct': 19.505, 'improved_count': 12, 'worsened_count': 4, 'same_count': 0}, 'V4': {'paired_count': 16, 'mean_delta_pct': 4.585625, 'median_delta_pct': 6.215, 'improved_count': 8, 'worsened_count': 7, 'same_count': 1}, 'Julia': {'paired_count': 16, 'mean_delta_pct': 81.4825, 'median_delta_pct': 102.855, 'improved_count': 12, 'worsened_count': 0, 'same_count': 4}}`
- V3 vs Julia: `{'paired_count': 16, 'mean_delta_pct_julia_minus_v3': 71.385625, 'median_delta_pct_julia_minus_v3': 76.36, 'julia_better_count': 16, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 9.615625, 'Julia': 81.00125, 'winner': 'Julia'}, 'median_return_pct': {'V3': 7.35, 'Julia': 87.22, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -12.600625, 'Julia': -19.19875, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | -2.253498 | -0.422128 | -50.994673 | 49.96215 | 4 |
| V3 | 34.641824 | 5.675691 | -27.714924 | 33.2324 | 3 |
| V4 | 33.582885 | 5.520943 | -32.777995 | 42.316427 | 2 |
| Julia | 100.677583 | 13.799965 | -33.205925 | 58.970477 | 1 |
| Buy & Hold | 33.257533 | 5.473196 | -45.603329 | 100.0 | None |
