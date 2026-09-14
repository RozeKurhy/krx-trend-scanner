# 292190 KODEX KRX300 Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/292190.parquet`
- actual authority period: `2018-03-26 ~ 2026-09-04` / `2073` rows
- used through support end: `2018-03-26 ~ 2026-08-21` / `2063` rows
- evaluation/signal/support/final: `run-specific` / `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## Run summary

| run | strategy | total | cagr | mdd | exposure | trades |
| --- | --- | --- | --- | --- | --- | --- |
| long_range | V2 | 115.730337 | 9.578849 | -35.513327 | 59.379544 | 1 |
| long_range | V3 | 116.777324 | 9.641986 | -36.256864 | 64.275327 | 1 |
| long_range | V4 | 100.267793 | 8.613513 | -36.256864 | 25.206011 | 2 |
| long_range | Julia | 115.730337 | 9.578849 | -35.513327 | 59.379544 | 1 |
| long_range | Buy & Hold | 235.970974 | 15.509099 | -41.275168 | 100.0 |  |
| same_window | V2 | 133.112583 | 17.008707 | -9.461164 | 13.096139 | 1 |
| same_window | V3 | 134.243929 | 17.113893 | -36.256864 | 20.741862 | 1 |
| same_window | V4 | 134.243929 | 17.113893 | -36.256864 | 20.741862 | 1 |
| same_window | Julia | 133.112583 | 17.008707 | -9.461164 | 13.096139 | 1 |
| same_window | Buy & Hold | 148.924731 | 18.442634 | -41.275168 | 100.0 |  |

## long_range

- common entry: `8`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 8, 'mean_delta_pct': 1.07, 'median_delta_pct': 1.06, 'improved_count': 8, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 8, 'mean_delta_pct': -81.5375, 'median_delta_pct': -130.555, 'improved_count': 3, 'worsened_count': 5, 'same_count': 0}, 'Julia': {'paired_count': 8, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 8}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 8 | 120.36625 | 117.87 | 100.0 | 128.0625 | -21.18 | 823.875 |
| V3 | 8 | 121.43625 | 118.93 | 100.0 | 249.23 | -21.18 | 924.875 |
| V4 | 8 | 38.82875 | -13.73 | 37.5 | 99.37875 | -10.515 | 253.375 |
| Julia | 8 | 120.36625 | 117.87 | 100.0 | 128.0625 | -21.18 | 823.875 |

### Sequential exit reasons

- V2: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`
- V4: `{'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 1, 'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`

## same_window

- common entry: `3`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 3, 'mean_delta_pct': 1.096667, 'median_delta_pct': 1.1, 'improved_count': 3, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 3, 'mean_delta_pct': 1.096667, 'median_delta_pct': 1.1, 'improved_count': 3, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 3, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 3}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 3 | 125.816667 | 125.88 | 100.0 | 133.703333 | -0.87 | 169.0 |
| V3 | 3 | 126.913333 | 126.98 | 100.0 | 257.87 | -0.87 | 270.0 |
| V4 | 3 | 126.913333 | 126.98 | 100.0 | 257.87 | -0.87 | 270.0 |
| Julia | 3 | 125.816667 | 125.88 | 100.0 | 133.703333 | -0.87 | 169.0 |

### Sequential exit reasons

- V2: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`
- V4: `{'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
