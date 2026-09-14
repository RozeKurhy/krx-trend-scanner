# 226980 KODEX 200중소형 Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/226980.parquet`
- actual authority period: `2020-01-02 ~ 2026-08-21` / `1628` rows
- used through support end: `2020-01-02 ~ 2026-08-21` / `1628` rows
- evaluation/signal/support/final: `run-specific` / `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## Run summary

| run | strategy | total | cagr | mdd | exposure | trades |
| --- | --- | --- | --- | --- | --- | --- |
| long_range | V2 | 82.63839 | 9.504796 | -13.048091 | 15.17199 | 1 |
| long_range | V3 | 74.442847 | 8.749556 | -19.935746 | 19.226044 | 1 |
| long_range | V4 | 58.878505 | 7.22823 | -28.982076 | 21.253071 | 1 |
| long_range | Julia | 82.63839 | 9.504796 | -13.048091 | 15.17199 | 1 |
| long_range | Buy & Hold | 144.86456 | 14.453167 | -41.365688 | 100.0 |  |
| same_window | V2 | 82.63839 | 11.82787 | -13.048091 | 18.712121 | 1 |
| same_window | V3 | 74.442847 | 10.879051 | -19.935746 | 23.712121 | 1 |
| same_window | V4 | 58.878505 | 8.972418 | -28.982076 | 26.212121 | 1 |
| same_window | Julia | 82.63839 | 11.82787 | -13.048091 | 18.712121 | 1 |
| same_window | Buy & Hold | 66.628264 | 9.9399 | -36.527912 | 100.0 |  |

## long_range

- common entry: `10`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 10, 'mean_delta_pct': -8.374, 'median_delta_pct': -8.31, 'improved_count': 0, 'worsened_count': 10, 'same_count': 0}, 'V4': {'paired_count': 10, 'mean_delta_pct': -24.275, 'median_delta_pct': -24.08, 'improved_count': 0, 'worsened_count': 10, 'same_count': 0}, 'Julia': {'paired_count': 10, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 10}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 10 | 86.602 | 85.105 | 100.0 | 91.338 | -7.389 | 226.3 |
| V3 | 10 | 78.228 | 76.795 | 100.0 | 120.315 | -7.389 | 292.3 |
| V4 | 10 | 62.327 | 61.025 | 100.0 | 120.315 | -7.389 | 325.3 |
| Julia | 10 | 86.602 | 85.105 | 100.0 | 91.338 | -7.389 | 226.3 |

### Sequential exit reasons

- V2: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'SOFT_EXIT': 1}`
- V4: `{'WINNER_SOFT_WATCH_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`

## same_window

- common entry: `10`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 10, 'mean_delta_pct': -8.374, 'median_delta_pct': -8.31, 'improved_count': 0, 'worsened_count': 10, 'same_count': 0}, 'V4': {'paired_count': 10, 'mean_delta_pct': -24.275, 'median_delta_pct': -24.08, 'improved_count': 0, 'worsened_count': 10, 'same_count': 0}, 'Julia': {'paired_count': 10, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 10}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 10 | 86.602 | 85.105 | 100.0 | 91.338 | -7.389 | 226.3 |
| V3 | 10 | 78.228 | 76.795 | 100.0 | 120.315 | -7.389 | 292.3 |
| V4 | 10 | 62.327 | 61.025 | 100.0 | 120.315 | -7.389 | 325.3 |
| Julia | 10 | 86.602 | 85.105 | 100.0 | 91.338 | -7.389 | 226.3 |

### Sequential exit reasons

- V2: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'SOFT_EXIT': 1}`
- V4: `{'WINNER_SOFT_WATCH_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
