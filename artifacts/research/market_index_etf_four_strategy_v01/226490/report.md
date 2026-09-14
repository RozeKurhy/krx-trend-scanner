# 226490 KODEX 코스피 Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/226490.parquet`
- actual authority period: `2015-08-24 ~ 2026-09-04` / `2707` rows
- used through support end: `2015-08-24 ~ 2026-08-21` / `2697` rows
- evaluation/signal/support/final: `run-specific` / `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## Run summary

| run | strategy | total | cagr | mdd | exposure | trades |
| --- | --- | --- | --- | --- | --- | --- |
| long_range | V2 | 249.150717 | 12.046585 | -27.822145 | 29.106415 | 3 |
| long_range | V3 | 175.388167 | 9.65348 | -38.067272 | 40.044494 | 2 |
| long_range | V4 | 91.448334 | 6.086132 | -38.067272 | 31.664813 | 3 |
| long_range | Julia | 376.63667 | 15.264517 | -35.419814 | 34.853541 | 2 |
| long_range | Buy & Hold | 281.436642 | 12.951704 | -43.333333 | 100.0 |  |
| same_window | V2 | 215.75417 | 23.787403 | -19.674147 | 37.925814 | 1 |
| same_window | V3 | 110.297317 | 14.793202 | -38.067272 | 41.029523 | 1 |
| same_window | V4 | 110.297317 | 14.793202 | -38.067272 | 41.029523 | 1 |
| same_window | Julia | 215.75417 | 23.787403 | -19.674147 | 37.925814 | 1 |
| same_window | Buy & Hold | 125.405405 | 16.280862 | -38.649226 | 100.0 |  |

## long_range

- common entry: `22`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 22, 'mean_delta_pct': -72.599545, 'median_delta_pct': -104.36, 'improved_count': 1, 'worsened_count': 21, 'same_count': 0}, 'V4': {'paired_count': 22, 'mean_delta_pct': -75.731818, 'median_delta_pct': -104.36, 'improved_count': 0, 'worsened_count': 22, 'same_count': 0}, 'Julia': {'paired_count': 22, 'mean_delta_pct': 3.289091, 'median_delta_pct': 0.0, 'improved_count': 1, 'worsened_count': 0, 'same_count': 21}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 22 | 154.895455 | 212.47 | 95.454545 | 157.622727 | -8.450455 | 337.590909 |
| V3 | 22 | 82.295909 | 108.11 | 100.0 | 183.246818 | -8.874545 | 392.863636 |
| V4 | 22 | 79.163636 | 108.11 | 95.454545 | 181.091364 | -8.874545 | 372.727273 |
| Julia | 22 | 158.184545 | 212.47 | 100.0 | 159.778182 | -8.874545 | 354.090909 |

### Sequential exit reasons

- V2: `{'LOSS_GUARD_CLOSE_LE_NEG_15': 1, 'EXIT4_SCORE_DRAWDOWN_GE_15': 2}`
- V3: `{'SOFT_EXIT': 1, 'HARD_EXIT': 1}`
- V4: `{'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 1, 'WINNER_SOFT_WATCH_EXIT': 1, 'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 2}`

## same_window

- common entry: `16`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 16, 'mean_delta_pct': -100.451875, 'median_delta_pct': -105.38, 'improved_count': 0, 'worsened_count': 16, 'same_count': 0}, 'V4': {'paired_count': 16, 'mean_delta_pct': -100.451875, 'median_delta_pct': -105.38, 'improved_count': 0, 'worsened_count': 16, 'same_count': 0}, 'Julia': {'paired_count': 16, 'mean_delta_pct': 0.0, 'median_delta_pct': 0.0, 'improved_count': 0, 'worsened_count': 0, 'same_count': 16}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 16 | 205.13125 | 215.525 | 100.0 | 205.4825 | -10.12 | 397.1875 |
| V3 | 16 | 104.679375 | 110.145 | 100.0 | 237.751875 | -10.12 | 437.75 |
| V4 | 16 | 104.679375 | 110.145 | 100.0 | 237.751875 | -10.12 | 437.75 |
| Julia | 16 | 205.13125 | 215.525 | 100.0 | 205.4825 | -10.12 | 397.1875 |

### Sequential exit reasons

- V2: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`
- V4: `{'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
