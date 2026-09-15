# 102960 KODEX 기계장비 Sector ETF Four Strategy Backtest

- status: `COMPLETE`
- authority: `data/raw/stocks/102960.parquet`
- period: `2014-01-02 ~ 2026-08-21` / `3101` rows
- liquidity filter: `OFF / threshold 0`
- price filter: `OFF / close threshold 0`
- signal cutoff / support / final valuation: `2026-08-14` / `2026-08-21` / `2026-08-21 CLOSE`
- cost model: `GROSS / NO_COST_MODEL`

## long_range

- common eligible entries: `48`
- sequential common-set enforcement: `True`
- matched identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
- paired vs V2: `{'V3': {'paired_count': 48, 'mean_delta_pct': -61.336042, 'median_delta_pct': -77.07, 'improved_count': 16, 'worsened_count': 32, 'same_count': 0}, 'V4': {'paired_count': 48, 'mean_delta_pct': -42.315833, 'median_delta_pct': -6.505, 'improved_count': 16, 'worsened_count': 32, 'same_count': 0}, 'Julia': {'paired_count': 48, 'mean_delta_pct': 23.274583, 'median_delta_pct': 0.0, 'improved_count': 8, 'worsened_count': 0, 'same_count': 40}}`
- V3 vs Julia: `{'paired_count': 48, 'mean_delta_pct_julia_minus_v3': 84.610625, 'median_delta_pct_julia_minus_v3': 78.025, 'julia_better_count': 40, 'v3_better_count': 8, 'same_count': 0, 'metric_comparison': {'mean_return_pct': {'V3': 23.060625, 'Julia': 107.67125, 'winner': 'Julia'}, 'median_return_pct': {'V3': 18.81, 'Julia': 114.485, 'winner': 'Julia'}, 'win_rate_pct': {'V3': 100.0, 'Julia': 100.0, 'winner': 'tie'}, 'mean_mae_pct': {'V3': -9.760417, 'Julia': -11.563125, 'winner': 'V3'}}}`

| strategy | total | cagr | mdd | exposure | trades |
| --- | ---: | ---: | ---: | ---: | ---: |
| V2 | 182.751537 | 8.575986 | -39.657143 | 32.021928 | 3 |
| V3 | 200.171018 | 9.091046 | -29.227273 | 26.34634 | 3 |
| V4 | 180.081993 | 8.494483 | -39.818182 | 30.312802 | 3 |
| Julia | 216.016424 | 9.536192 | -39.657143 | 32.82812 | 2 |
| Buy & Hold | -26.639931 | -2.422514 | -87.167001 | 100.0 | None |

## same_window

- common eligible entries: `40`
- sequential common-set enforcement: `True`
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
