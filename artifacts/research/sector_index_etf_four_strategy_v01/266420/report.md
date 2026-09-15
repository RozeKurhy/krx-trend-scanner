# 266420 KODEX 헬스케어 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/266420.parquet`
- period: `2017-03-28 ~ 2026-08-21` / `2300` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `21`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 21, 'mean_delta_pct': 17.326667, 'median_delta_pct': 10.84, 'improved_count': 18, 'worsened_count': 3, 'same_count': 0}, 'V4': {'paired_count': 21, 'mean_delta_pct': 10.404286, 'median_delta_pct': 5.57, 'improved_count': 12, 'worsened_count': 9, 'same_count': 0}, 'Julia': {'paired_count': 21, 'mean_delta_pct': 3.288571, 'median_delta_pct': 0.0, 'improved_count': 8, 'worsened_count': 0, 'same_count': 13}}`
- V3 vs Julia: `{'paired_count': 21, 'mean_delta_pct_julia_minus_v3': -14.038095, 'median_delta_pct_julia_minus_v3': -10.84, 'julia_better_count': 3, 'v3_better_count': 18, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 16.256667, 'Julia': 2.218571, 'winner': 'V3'}, 'median_return_pct': {'V3': 14.13, 'Julia': 3.75, 'winner': 'V3'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 57.142857, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -6.858571, 'Julia': -13.07619, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 20.975753 | 2.046612 | -35.838264 | 31.304348 | 3 |
| V3 | 42.115657 | 3.810231 | -19.188256 | 13.826087 | 3 |
| V4 | 55.890671 | 4.837069 | -28.031485 | 26.956522 | 3 |
| Julia | 30.496132 | 2.872401 | -40.473373 | 32.565217 | 3 |
| Buy & Hold | 73.283951 | 6.023567 | -56.649793 | 100.0 | None |

## same_window

- common eligible entries: `12`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 12, 'mean_delta_pct': 24.524167, 'median_delta_pct': 27.155, 'improved_count': 11, 'worsened_count': 1, 'same_count': 0}, 'V4': {'paired_count': 12, 'mean_delta_pct': 19.523333, 'median_delta_pct': 21.13, 'improved_count': 12, 'worsened_count': 0, 'same_count': 0}, 'Julia': {'paired_count': 12, 'mean_delta_pct': 5.755, 'median_delta_pct': 7.285, 'improved_count': 8, 'worsened_count': 0, 'same_count': 4}}`
- V3 vs Julia: `{'paired_count': 12, 'mean_delta_pct_julia_minus_v3': -18.769167, 'median_delta_pct_julia_minus_v3': -19.005, 'julia_better_count': 1, 'v3_better_count': 11, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 16.4, 'Julia': -2.369167, 'winner': 'V3'}, 'median_return_pct': {'V3': 10.97, 'Julia': -5.79, 'winner': 'V3'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 33.333333, 'winner': 'V3'}, 'mean_mae_pct': {'V3': -7.4125, 'Julia': -18.293333, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | -6.034654 | -1.14857 | -35.838264 | 40.499621 | 2 |
| V3 | 12.305312 | 2.177205 | -19.188256 | 17.713853 | 2 |
| V4 | 22.74475 | 3.876774 | -20.098619 | 32.248297 | 2 |
| Julia | 1.360098 | 0.25104 | -40.473373 | 42.694928 | 2 |
| Buy & Hold | -11.231976 | -2.186973 | -48.881485 | 100.0 | None |
