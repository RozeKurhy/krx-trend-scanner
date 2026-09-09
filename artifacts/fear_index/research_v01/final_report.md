# Fear Index Research & Market Regime Backtest V01

- KRX menu path: `통계 > 기본 통계 > 지수 > 파생 및 기타지수 > 개별지수 시세 추이`
- Index: `V-KOSPI 200` / KRX displayed name `코스피 200 변동성지수`
- Login: `SUCCESS`
- Download: `chunked` (9 official CSV exports, each within the KRX two-year limit)
- Official date range: `2010-01-04 ~ 2026-09-04`
- Normalized row count: `4105`
- Duplicate dates: `0`
- Null values: `0`

## Research

- Exact-date join rows: `4105`
- Inputs: V-KOSPI 200, KOSPI, KOSPI trading_value
- Candidates evaluated: `balanced_v01, downside_sensitive_v01, participation_aware_v01`
- Final candidate: `downside_sensitive_v01`
- Validation cutoff: `2022-01-01`
- Validation Brier: `0.219875`
- Validation adverse-return Spearman: `0.058371`
- Regime counts: `{'OVERHEATED': 409, 'NORMAL': 1953, 'ANXIOUS': 776, 'PANIC': 157, 'APATHY': 685}`
- Flicker summary: `{'valid_days': 3980, 'regime_switches': 839, 'switch_rate': 0.2108040201005025, 'two_day_return_flickers': 269}`

## Scope

No web files or production payloads were changed. The 2008 financial-crisis check remains `NOT IN COMMON SOURCE RANGE` because the canonical KOSPI input begins on 2010-01-04.
