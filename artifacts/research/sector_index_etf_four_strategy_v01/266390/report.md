# 266390 KODEX 경기소비재 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/266390.parquet`
- period: `2017-03-28 ~ 2026-08-21` / `2283` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `26`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 26, 'mean_delta_pct': -33.463846, 'median_delta_pct': -49.5, 'improved_count': 0, 'worsened_count': 26, 'same_count': 0}, 'V4': {'paired_count': 26, 'mean_delta_pct': -42.494615, 'median_delta_pct': -49.5, 'improved_count': 0, 'worsened_count': 26, 'same_count': 0}, 'Julia': {'paired_count': 26, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 26}}`
- V3 vs Julia: `{'paired_count': 26, 'mean_delta_pct_julia_minus_v3': 33.463846, 'median_delta_pct_julia_minus_v3': 49.5, 'julia_better_count': 26, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 11.312308, 'Julia': 44.776154, 'winner': 'Julia'}, 'median_return_pct': {'V3': 11.32, 'Julia': 54.525, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -17.122308, 'Julia': -18.508846, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 20.926316 | 2.042175 | -46.071044 | 60.271572 | 1 |
| V3 | 13.642105 | 1.369904 | -46.071044 | 57.468244 | 1 |
| V4 | 9.563058 | 0.976432 | -30.521345 | 23.872098 | 3 |
| Julia | 20.926316 | 2.042175 | -46.071044 | 60.271572 | 1 |
| Buy & Hold | 38.743961 | 3.545374 | -51.352381 | 100.0 | None |

## same_window

- common eligible entries: `16`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 16, 'mean_delta_pct': -49.334375, 'median_delta_pct': -53.605, 'improved_count': 0, 'worsened_count': 16, 'same_count': 0}, 'V4': {'paired_count': 16, 'mean_delta_pct': -49.334375, 'median_delta_pct': -53.605, 'improved_count': 0, 'worsened_count': 16, 'same_count': 0}, 'Julia': {'paired_count': 16, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 16}}`
- V3 vs Julia: `{'paired_count': 16, 'mean_delta_pct_julia_minus_v3': 49.334375, 'median_delta_pct_julia_minus_v3': 53.605, 'julia_better_count': 16, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 12.2675, 'Julia': 61.601875, 'winner': 'Julia'}, 'median_return_pct': {'V3': 13.725, 'Julia': 67.33, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -5.148125, 'Julia': -5.148125, 'winner': 'tie'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 74.7188 | 10.911584 | -20.766284 | 19.303558 | 1 |
| V3 | 33.373789 | 5.490268 | -19.233716 | 14.383043 | 2 |
| V4 | 33.373789 | 5.490268 | -19.233716 | 14.383043 | 2 |
| Julia | 74.7188 | 10.911584 | -20.766284 | 19.303558 | 1 |
| Buy & Hold | 16.558442 | 2.884547 | -46.071044 | 100.0 | None |
