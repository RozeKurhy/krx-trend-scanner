# Fear Index Research & Market Regime Backtest V01 — FIX01

START_HEAD: `d48b1ebc7dcb842b615f39625b2ea94b8e1864f4`
FINAL_HEAD: repository HEAD after FIX01 commit
commit: research: refine fear index regime semantics
push: origin/main
HEAD == origin/main: verify after push
working tree: clean after push

## Data

- V-KOSPI source: KRX Data Marketplace official export
- Official files: 9 chunked CSVs
- Date range: `2010-01-04 ~ 2026-09-04`
- Rows: `4105`; duplicate `0`; null `0`
- KOSPI source: `data/market/index/v01/market_index.parquet`, index code `1001`
- Exact join: `4105` rows
- External financial network: `0`

## Fear Score FIX

- Previous participation problem: `1 - participation_pct_252` had a positive fear weight, so low participation increased fear and could create false PANIC.
- New participation role: excluded from the selected fear score; used for high-participation PANIC confirmation and low-participation APATHY classification.
- Candidate count: `3`
- Selected candidate: `downside_heavy_v01`
- Exact formula: `100 * clip(0.40*v_level_pct_252 + 0.10*v_spike + 0.40*downside + 0.10*v_momentum, 0, 100)`
- Does low participation raise fear? `NO`
- Candidate selection: historical mandatory gates, contextual contradictions, flicker, then simplicity. Forward Brier/correlation are diagnostic only.

## Market Regime Rules

- PANIC: `(fear_score >= 70 AND downside AND high_participation AND NOT bull_context) OR (fear_score >= 88 AND severe_downside AND NOT bull_context)`
- OVERHEATED: `strong_up AND participation_pct_252 >= 0.55 AND NOT sharp_downside AND (NOT downside OR bull_context)`
- APATHY: `fear_score <= 50 AND low_participation AND kospi_return_60 <= 0.05 AND NOT sharp_downside`
- ANXIOUS: `fear_score >= 50 OR downside`
- NORMAL: fallback for remaining available observations
- Precedence: `PANIC > OVERHEATED > APATHY > ANXIOUS > NORMAL`

## Period Validation

- 2011-08~09: `OVERHEATED=0, NORMAL=2, ANXIOUS=22, PANIC=18, APATHY=0`; verdict: anchor PANIC cluster present
- 2012~2016: `OVERHEATED=7, NORMAL=968, ANXIOUS=155, PANIC=11, APATHY=93`; APATHY longest run `46`; verdict: NORMAL/APATHY coexist
- 2017: `OVERHEATED=20, NORMAL=189, ANXIOUS=28, PANIC=0, APATHY=6`; PANIC `0`, APATHY `6`; verdict: not dominated
- 2018: `OVERHEATED=0, NORMAL=118, ANXIOUS=95, PANIC=11, APATHY=20`; verdict: ANXIOUS/PANIC downside explanation
- 2020-02-20~04-30: `OVERHEATED=0, NORMAL=0, ANXIOUS=17, PANIC=32, APATHY=0`; 2020-03-19 `PANIC`; verdict: COVID PANIC cluster
- 2021: `OVERHEATED=41, NORMAL=140, ANXIOUS=15, PANIC=0, APATHY=52`; verdict: NORMAL/OVERHEATED 중심
- 2022: `OVERHEATED=4, NORMAL=57, ANXIOUS=104, PANIC=2, APATHY=79`; PANIC `2`, ANXIOUS `104`; 2022-07-04 `ANXIOUS`; verdict: ANXIOUS 중심
- 2024-08-01~08-09: `OVERHEATED=0, NORMAL=1, ANXIOUS=1, PANIC=5, APATHY=0`; 2024-08-05 `PANIC`; verdict: PANIC anchor
- 2026-06: `OVERHEATED=12, NORMAL=0, ANXIOUS=9, PANIC=0, APATHY=0`; 2026-06-18 `OVERHEATED`, 2026-06-29 `ANXIOUS`; PANIC false positives `0`

## Current

- date: `2026-09-04`
- V-KOSPI: `39.33`
- KOSPI: `6687.21`
- trading_value: `17723233066259.0`
- fear_score: `30.180237`
- market_regime: `ANXIOUS`

## Flicker

- RAW: `{'valid_days': 3980, 'switch_count': 538, 'switch_rate': 0.13517587939698492, 'one_day_runs': 186, 'two_day_runs': 86, 'median_run_length': 2.0, 'mean_run_length': 7.38404452690167, 'max_run_length': 160}`
- STABILIZED: `{'valid_days': 3980, 'switch_count': 272, 'switch_rate': 0.06834170854271357, 'one_day_runs': 5, 'two_day_runs': 51, 'median_run_length': 6.0, 'mean_run_length': 14.578754578754578, 'max_run_length': 182}`
- Hysteresis selected: `YES`
- Exact rule: PANIC immediate; all other changes require two consecutive raw sessions.

## Forward Diagnostics

- Forward return metrics calculated: `YES`
- Used for formula: `NO`
- Used for candidate selection: `NO`
- Brier used as selection objective: `NO`

## False Regime Review

- PANIC during strong bull: 0 examples=[]
- APATHY during strong bull: 0 examples=[]
- OVERHEATED during sharp decline: 0 examples=[]
- NORMAL during obvious crash: 0 examples=[]
- PANIC without participation/downside confirmation: 0 examples=[]

## Artifacts

- `candidate_gate_comparison.csv`
- `regime_period_validation.csv`
- `regime_run_stats.json`
- `false_regime_review.csv`
- `final_formula.md` (exact numeric formula/thresholds)
- `final_daily_regimes.csv`

## Scope

No official source, KOSPI canonical, web, or production model/data was modified. 2008 remains `NOT IN COMMON SOURCE RANGE`.
