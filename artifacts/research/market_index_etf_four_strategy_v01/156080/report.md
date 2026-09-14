# 156080 KODEX MSCI KOREA Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/156080.parquet`
- actual authority period: `2020-01-02 ~ 2026-08-21` / `1594` rows
- used through support end: `2020-01-02 ~ 2026-08-21` / `1594` rows
- evaluation/signal/support/final: `run-specific` / `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## Run summary

| run | strategy | total | cagr | mdd | exposure | trades |
| --- | --- | --- | --- | --- | --- | --- |
| long_range | V2 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| long_range | V3 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| long_range | V4 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| long_range | Julia | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| long_range | Buy & Hold | 276.088508 | 22.101467 | -41.037403 | 100.0 |  |
| same_window | V2 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| same_window | V3 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| same_window | V4 | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| same_window | Julia | 0.0 | 0.0 | 0.0 | 0.0 | 0 |
| same_window | Buy & Hold | 159.876695 | 19.392911 | -41.037403 | 100.0 |  |

## long_range

- common entry: `0`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| V3 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| V4 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Julia | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### Sequential exit reasons

- V2: `{}`
- V3: `{}`
- V4: `{}`
- Julia: `{}`

## same_window

- common entry: `0`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 0, 'mean_delta_pct': None, 'median_delta_pct': None, 'improved_count': 0, 'worsened_count': 0, 'same_count': 0}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| V3 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| V4 | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |
| Julia | 0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

### Sequential exit reasons

- V2: `{}`
- V3: `{}`
- V4: `{}`
- Julia: `{}`
