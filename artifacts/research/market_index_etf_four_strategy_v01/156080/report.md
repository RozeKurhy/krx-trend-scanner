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
| long_range | V2 | 119.681947 | 12.596027 | -21.640625 | 20.828105 | 2 |
| long_range | V3 | 158.988924 | 15.424818 | -36.302047 | 33.751568 | 1 |
| long_range | V4 | 109.110613 | 11.762064 | -36.302047 | 24.46675 | 2 |
| long_range | Julia | 172.081795 | 16.286113 | -24.136098 | 30.112923 | 1 |
| long_range | Buy & Hold | 276.088508 | 22.101467 | -41.037403 | 100.0 |  |
| same_window | V2 | 119.681947 | 15.727124 | -21.640625 | 25.479662 | 2 |
| same_window | V3 | 158.988924 | 19.317109 | -36.302047 | 41.289332 | 1 |
| same_window | V4 | 109.110613 | 14.672701 | -36.302047 | 29.930929 | 2 |
| same_window | Julia | 172.081795 | 20.414237 | -24.136098 | 36.838066 | 1 |
| same_window | Buy & Hold | 159.876695 | 19.392911 | -41.037403 | 100.0 |  |

## long_range

- common entry: `13`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 13, 'mean_delta_pct': 147.526923, 'median_delta_pct': 175.43, 'improved_count': 11, 'worsened_count': 2, 'same_count': 0}, 'V4': {'paired_count': 13, 'mean_delta_pct': 39.557692, 'median_delta_pct': 0.0, 'improved_count': 3, 'worsened_count': 2, 'same_count': 8}, 'Julia': {'paired_count': 13, 'mean_delta_pct': 160.771538, 'median_delta_pct': 188.58, 'improved_count': 11, 'worsened_count': 0, 'same_count': 2}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 13 | 14.478462 | -14.4 | 15.384615 | 31.389231 | -14.259231 | 154.384615 |
| V3 | 13 | 162.005385 | 162.64 | 100.0 | 318.91 | -16.328462 | 486.076923 |
| V4 | 13 | 54.036154 | -14.4 | 38.461538 | 127.875385 | -14.496923 | 236.538462 |
| Julia | 13 | 175.25 | 175.92 | 100.0 | 175.25 | -16.328462 | 428.076923 |

### Sequential exit reasons

- V2: `{'LOSS_GUARD_CLOSE_LE_NEG_15': 1, 'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`
- V4: `{'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 1, 'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`

## same_window

- common entry: `13`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 13, 'mean_delta_pct': 147.526923, 'median_delta_pct': 175.43, 'improved_count': 11, 'worsened_count': 2, 'same_count': 0}, 'V4': {'paired_count': 13, 'mean_delta_pct': 39.557692, 'median_delta_pct': 0.0, 'improved_count': 3, 'worsened_count': 2, 'same_count': 8}, 'Julia': {'paired_count': 13, 'mean_delta_pct': 160.771538, 'median_delta_pct': 188.58, 'improved_count': 11, 'worsened_count': 0, 'same_count': 2}}`

### Matched

| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 13 | 14.478462 | -14.4 | 15.384615 | 31.389231 | -14.259231 | 154.384615 |
| V3 | 13 | 162.005385 | 162.64 | 100.0 | 318.91 | -16.328462 | 486.076923 |
| V4 | 13 | 54.036154 | -14.4 | 38.461538 | 127.875385 | -14.496923 | 236.538462 |
| Julia | 13 | 175.25 | 175.92 | 100.0 | 175.25 | -16.328462 | 428.076923 |

### Sequential exit reasons

- V2: `{'LOSS_GUARD_CLOSE_LE_NEG_15': 1, 'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`
- V4: `{'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 1, 'WINNER_HARD_EXIT': 1}`
- Julia: `{'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
