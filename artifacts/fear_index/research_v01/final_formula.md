# Fear Index V01 — Final Formula (FIX01)

## INPUTS

- V-KOSPI 200
- KOSPI close
- KOSPI trading_value

All rolling windows are trailing and include today plus prior observations only. No future-return field is a formula input.

## FEATURES

- `v_level_pct_252`: percentile rank of today's V-KOSPI within the trailing 252 observations, with `min_periods=126`.
- `v_z_60`: `(v_kospi200_close - trailing_mean_60) / trailing_std_60`, with `min_periods=30`; zero standard deviation is unavailable.
- `v_spike`: `1 / (1 + exp(-clip(v_z_60, -8, 8)))`.
- `v_momentum`: `clip(0.5 + v_change_20 / 0.8, 0, 1)`.
- `kospi_return_5`: `KOSPI[t] / KOSPI[t-5] - 1`.
- `kospi_return_20`: `KOSPI[t] / KOSPI[t-20] - 1`.
- `kospi_return_60`: `KOSPI[t] / KOSPI[t-60] - 1`.
- `kospi_drawdown_60`: `KOSPI[t] / trailing_max_60 - 1`.
- `downside`: `clip(0.5 * (-kospi_return_20 / 0.15) + 0.5 * (-kospi_drawdown_60 / 0.25), 0, 1)`.
- `participation_pct_252`: trailing 252-observation percentile rank of trading value, `min_periods=126`.
- `participation_ratio_20`: `20D mean trading_value / trailing 252D median trading_value`.

## FEAR SCORE

Selected candidate: `downside_heavy_v01`

`fear_score = clip(100 * (0.40 * v_level_pct_252 + 0.10 * v_spike + 0.40 * downside + 0.10 * v_momentum), 0, 100)`

Participation is not a positive fear-score term. The candidate-comparison set was: (A) 0.50/0.15/0.25/0.10 level/spike/downside/momentum, (B) 0.45/0.10/0.30/0.10 plus 0.05 downside×high-participation confirmation, and (C, selected) 0.40/0.10/0.40/0.10.

`low participation raises fear_score`: **NO**.

## MARKET REGIME RULES

Derived booleans:

- `downside = kospi_return_20 <= -0.05 OR kospi_drawdown_60 <= -0.10`
- `sharp_downside = kospi_return_20 <= -0.07 OR kospi_return_5 <= -0.04`
- `severe_downside = kospi_return_20 <= -0.12 OR kospi_drawdown_60 <= -0.18 OR kospi_return_5 <= -0.06`
- `high_participation = participation_pct_252 >= 0.75 OR participation_ratio_20 >= 1.25`
- `bull_context = kospi_return_60 >= 0.25 AND kospi_return_20 > -0.05`
- `strong_up = kospi_return_20 >= 0.08 OR kospi_return_60 >= 0.12`
- `low_participation = participation_pct_252 <= 0.25 AND participation_ratio_20 <= 0.85`

Precedence is exactly: `PANIC → OVERHEATED → APATHY → ANXIOUS → NORMAL`.

1. `PANIC`: `(fear_score >= 70 AND downside AND high_participation AND NOT bull_context) OR (fear_score >= 88 AND severe_downside AND NOT bull_context)`.
2. `OVERHEATED`: `strong_up AND participation_pct_252 >= 0.55 AND NOT sharp_downside AND (NOT downside OR bull_context)`.
3. `APATHY`: `fear_score <= 50 AND low_participation AND kospi_return_60 <= 0.05 AND NOT sharp_downside`.
4. `ANXIOUS`: `fear_score >= 50 OR downside`.
5. `NORMAL`: remaining available observations.

## HYSTERESIS

Selected: `YES`. PANIC enters immediately. Any other raw regime change requires the new regime on two consecutive sessions. `UNAVAILABLE` remains unavailable.
