# 229200 KODEX 코스닥150 Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/229200.parquet`
- actual authority period: `2015-10-01 ~ 2026-08-21` / `2671` rows
- used through support end: `2015-10-01 ~ 2026-08-21` / `2671` rows
- evaluation/signal/support/final: `run-specific` / `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## Run summary

| run | strategy | total | cagr | mdd | exposure | trades |
| --- | --- | --- | --- | --- | --- | --- |
| long_range | V2 | 58.753709 | 4.3361 | -40.115905 | 54.137027 | 1 |
| long_range | V3 | 42.776419 | 3.324602 | -41.783735 | 48.296518 | 2 |
| long_range | V4 | 8.413575 | 0.744676 | -34.916637 | 30.662673 | 4 |
| long_range | Julia | 58.753709 | 4.3361 | -40.115905 | 54.137027 | 1 |
| long_range | Buy & Hold | 27.516159 | 2.2575 | -57.925408 | 100.0 |  |
| same_window | V2 | -2.37616 | -0.445332 | -36.581401 | 49.96215 | 3 |
| same_window | V3 | 30.842716 | 5.115818 | -39.669153 | 77.365632 | 1 |
| same_window | V4 | -13.330439 | -2.620311 | -34.916637 | 35.579107 | 4 |
| same_window | Julia | 27.772091 | 4.653544 | -39.669153 | 82.891749 | 1 |
| same_window | Buy & Hold | -3.695955 | -0.69651 | -49.739336 | 100.0 |  |

## long_range

- common entry: `49`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 49, 'mean_delta_pct': 8.901837, 'median_delta_pct': 3.1, 'improved_count': 31, 'worsened_count': 18, 'same_count': 0}, 'V4': {'paired_count': 49, 'mean_delta_pct': -14.114286, 'median_delta_pct': -1.17, 'improved_count': 14, 'worsened_count': 29, 'same_count': 6}, 'Julia': {'paired_count': 49, 'mean_delta_pct': 22.03551, 'median_delta_pct': 0.0, 'improved_count': 21, 'worsened_count': 0, 'same_count': 28}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 49 | 13.723673 | 17.99 | 57.142857 | 39.745102 | -17.393265 | 522.714286 |
| V3 | 49 | 22.62551 | 25.78 | 100.0 | 39.479796 | -14.846735 | 367.204082 |
| V4 | 49 | -0.390612 | -0.45 | 46.938776 | 26.820408 | -10.014898 | 172.510204 |
| Julia | 49 | 35.759184 | 37.13 | 100.0 | 57.510612 | -20.557755 | 757.44898 |

### Sequential exit reasons

- V2: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'SOFT_EXIT': 2}`
- V4: `{'WINNER_HARD_EXIT': 3, 'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`

## same_window

- common entry: `35`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 35, 'mean_delta_pct': 21.400286, 'median_delta_pct': 28.97, 'improved_count': 26, 'worsened_count': 9, 'same_count': 0}, 'V4': {'paired_count': 35, 'mean_delta_pct': -0.322, 'median_delta_pct': 0.0, 'improved_count': 14, 'worsened_count': 15, 'same_count': 6}, 'Julia': {'paired_count': 35, 'mean_delta_pct': 30.849714, 'median_delta_pct': 44.92, 'improved_count': 21, 'worsened_count': 0, 'same_count': 14}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 35 | 2.875429 | -14.7 | 40.0 | 30.278571 | -12.301714 | 180.857143 |
| V3 | 35 | 24.275714 | 27.3 | 100.0 | 42.062571 | -12.053143 | 255.371429 |
| V4 | 35 | 2.553429 | 1.69 | 54.285714 | 30.278571 | -8.904571 | 105.028571 |
| Julia | 35 | 33.725143 | 35.79 | 100.0 | 55.150286 | -16.732 | 509.485714 |

### Sequential exit reasons

- V2: `{'LOSS_GUARD_CLOSE_LE_NEG_15': 2, 'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'SOFT_EXIT': 1}`
- V4: `{'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 2, 'WINNER_HARD_EXIT': 2}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
