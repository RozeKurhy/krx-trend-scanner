# 102960 KODEX 기계장비 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/102960.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common entries: `43`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 43, 'mean_delta_pct': -69.882558, 'median_delta_pct': -77.51, 'improved_count': 11, 'worsened_count': 32, 'same_count': 0}, 'V4': {'paired_count': 43, 'mean_delta_pct': -48.711395, 'median_delta_pct': -6.67, 'improved_count': 11, 'worsened_count': 32, 'same_count': 0}, 'Julia': {'paired_count': 43, 'mean_delta_pct': 25.98093, 'median_delta_pct': 0.0, 'improved_count': 8, 'worsened_count': 0, 'same_count': 35}}`
- V3 vs Julia: `{'paired_count': 43, 'mean_delta_pct_julia_minus_v3': 95.863488, 'median_delta_pct_julia_minus_v3': 113.71, 'julia_better_count': 40, 'v3_better_count': 3, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 23.020465, 'Julia': 118.883953, 'winner': 'Julia'}, 'median_return_pct': {'V3': 18.3, 'Julia': 121.68, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -10.280465, 'Julia': -12.292791, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 148.961918 | 7.487603 | -39.657143 | 31.31248 | 3 |
| V3 | 164.299721 | 7.9975 | -29.227273 | 25.636891 | 3 |
| V4 | 146.611391 | 7.406917 | -39.818182 | 29.603354 | 3 |
| Julia | 216.016424 | 9.536192 | -39.657143 | 32.82812 | 2 |
| Buy & Hold | -26.639931 | -2.422514 | -87.167001 | 100.0 | None |

## same_window

- common entries: `40`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 40, 'mean_delta_pct': -75.985, 'median_delta_pct': -78.025, 'improved_count': 8, 'worsened_count': 32, 'same_count': 0}, 'V4': {'paired_count': 40, 'mean_delta_pct': -53.26275, 'median_delta_pct': -31.975, 'improved_count': 8, 'worsened_count': 32, 'same_count': 0}, 'Julia': {'paired_count': 40, 'mean_delta_pct': 27.9295, 'median_delta_pct': 0.0, 'improved_count': 8, 'worsened_count': 0, 'same_count': 32}}`
- V3 vs Julia: `{'paired_count': 40, 'mean_delta_pct_julia_minus_v3': 103.9145, 'median_delta_pct_julia_minus_v3': 117.68, 'julia_better_count': 40, 'v3_better_count': 0, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 23.51, 'Julia': 127.4245, 'winner': 'Julia'}, 'median_return_pct': {'V3': 18.335, 'Julia': 123.5, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -10.23475, 'Julia': -12.398, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 143.377725 | 17.948277 | -39.657143 | 56.77517 | 2 |
| V3 | 132.904388 | 16.989305 | -29.227273 | 48.826646 | 2 |
| V4 | 116.405634 | 15.404835 | -39.818182 | 56.69947 | 2 |
| Julia | 172.010399 | 20.408372 | -39.657143 | 58.667676 | 1 |
| Buy & Hold | 139.345794 | 17.583155 | -49.295455 | 100.0 | None |
