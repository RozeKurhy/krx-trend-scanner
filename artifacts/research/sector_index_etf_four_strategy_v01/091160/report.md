# 091160 KODEX 반도체 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/091160.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `56`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 56, 'mean_delta_pct': 4.348929, 'median_delta_pct': 19.315, 'improved_count': 33, 'worsened_count': 23, 'same_count': 0}, 'V4': {'paired_count': 56, 'mean_delta_pct': -10.293571, 'median_delta_pct': 8.01, 'improved_count': 31, 'worsened_count': 25, 'same_count': 0}, 'Julia': {'paired_count': 56, 'mean_delta_pct': 15.467321, 'median_delta_pct': 0.0, 'improved_count': 14, 'worsened_count': 0, 'same_count': 42}}`
- V3 vs Julia: `{'paired_count': 56, 'mean_delta_pct_julia_minus_v3': 11.118393, 'median_delta_pct_julia_minus_v3': 8.145, 'julia_better_count': 36, 'v3_better_count': 20, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 60.136607, 'Julia': 71.255, 'winner': 'Julia'}, 'median_return_pct': {'V3': 28.675, 'Julia': 42.45, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 75.0, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -15.5625, 'Julia': -17.296964, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 588.784558 | 16.504776 | -50.264143 | 52.918413 | 3 |
| V3 | 547.01258 | 15.929207 | -44.511252 | 52.563689 | 4 |
| V4 | 283.760947 | 11.233341 | -43.067244 | 42.566914 | 5 |
| Julia | 588.784558 | 16.504776 | -50.264143 | 52.918413 | 3 |
| Buy & Hold | 635.542692 | 17.112098 | -50.264143 | 100.0 | None |

## same_window

- common entries: `30`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 30, 'mean_delta_pct': -1.777333, 'median_delta_pct': 19.615, 'improved_count': 18, 'worsened_count': 12, 'same_count': 0}, 'V4': {'paired_count': 30, 'mean_delta_pct': -9.131667, 'median_delta_pct': 8.115, 'improved_count': 18, 'worsened_count': 12, 'same_count': 0}, 'Julia': {'paired_count': 30, 'mean_delta_pct': 0.195333, 'median_delta_pct': 0.0, 'improved_count': 1, 'worsened_count': 0, 'same_count': 29}}`
- V3 vs Julia: `{'paired_count': 30, 'mean_delta_pct_julia_minus_v3': 1.972667, 'median_delta_pct_julia_minus_v3': -19.37, 'julia_better_count': 12, 'v3_better_count': 18, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 88.075333, 'Julia': 90.048, 'winner': 'Julia'}, 'median_return_pct': {'V3': 23.49, 'Julia': 1.67, 'winner': 'V3'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 53.333333, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -5.624, 'Julia': -7.399667, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 265.515005 | 27.195609 | -50.264143 | 46.934141 | 2 |
| V3 | 279.952286 | 28.113393 | -43.067244 | 40.953823 | 2 |
| V4 | 225.840829 | 24.511942 | -43.067244 | 41.408024 | 2 |
| Julia | 265.515005 | 27.195609 | -50.264143 | 46.934141 | 2 |
| Buy & Hold | 244.30294 | 25.792067 | -50.264143 | 100.0 | None |
