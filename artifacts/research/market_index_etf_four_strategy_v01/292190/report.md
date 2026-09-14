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
| long_range | V4 | 107.719084 | 9.086603 | -36.256864 | 38.148328 | 2 |
| long_range | Julia | 115.730337 | 9.578849 | -35.513327 | 59.379544 | 1 |
| long_range | Buy & Hold | 235.970974 | 15.509099 | -41.275168 | 100.0 |  |
| same_window | V2 | 101.087958 | 13.84312 | -20.969891 | 24.148372 | 2 |
| same_window | V3 | 142.959359 | 17.910621 | -36.256864 | 40.953823 | 1 |
| same_window | V4 | 142.959359 | 17.910621 | -36.256864 | 40.953823 | 1 |
| same_window | Julia | 141.785919 | 17.80472 | -21.715961 | 33.3081 | 1 |
| same_window | Buy & Hold | 148.924731 | 18.442634 | -41.275168 | 100.0 |  |

## long_range

- common entry: `20`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 20, 'mean_delta_pct': 62.7195, 'median_delta_pct': 1.205, 'improved_count': 20, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 20, 'mean_delta_pct': 29.6765, 'median_delta_pct': 1.205, 'improved_count': 15, 'worsened_count': 5, 'same_count': 0}, 'Julia': {'paired_count': 20, 'mean_delta_pct': 61.584, 'median_delta_pct': 0.0, 'improved_count': 8, 'worsened_count': 0, 'same_count': 12}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 20 | 72.4935 | 117.005 | 60.0 | 84.7025 | -17.5545 | 462.85 |
| V3 | 20 | 135.213 | 140.62 | 100.0 | 270.954 | -18.0495 | 674.45 |
| V4 | 20 | 102.17 | 140.62 | 75.0 | 211.0135 | -13.7835 | 405.85 |
| Julia | 20 | 134.0775 | 139.46 | 100.0 | 142.251 | -18.0495 | 573.45 |

### Sequential exit reasons

- V2: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`
- V4: `{'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 1, 'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`

## same_window

- common entry: `15`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 15, 'mean_delta_pct': 83.274667, 'median_delta_pct': 152.1, 'improved_count': 15, 'worsened_count': 0, 'same_count': 0}, 'V4': {'paired_count': 15, 'mean_delta_pct': 83.274667, 'median_delta_pct': 152.1, 'improved_count': 15, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 15, 'mean_delta_pct': 82.112, 'median_delta_pct': 150.95, 'improved_count': 8, 'worsened_count': 0, 'same_count': 7}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 15 | 57.626 | -9.99 | 46.666667 | 71.377333 | -12.284 | 211.533333 |
| V3 | 15 | 140.900667 | 142.89 | 100.0 | 279.923333 | -12.944 | 460.0 |
| V4 | 15 | 140.900667 | 142.89 | 100.0 | 279.923333 | -12.944 | 460.0 |
| Julia | 15 | 139.738 | 141.72 | 100.0 | 148.108667 | -12.944 | 359.0 |

### Sequential exit reasons

- V2: `{'LOSS_GUARD_CLOSE_LE_NEG_15': 1, 'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`
- V4: `{'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
