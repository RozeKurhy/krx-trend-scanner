# FIX02 external sanity evidence

- requested_as_of: `2026-09-04`
- network calls: `0` (committed local OpenDART/XBRL cache only)
- population: the 26 FIX01 `NAVER_BASIS_OR_STALENESS` rows only; no new random selection
- authority rule: same metric, fiscal period, account meaning, statement scope, CFS/OFS basis, and currency; latest eligible PIT receipt wins; same-day conflicting candidates fail closed

## Result counts

- status counts: `{'EXTERNAL_SOURCE_STALE': 15, 'PRODUCTION_CORRECTED': 11}`
- affected tickers: `4`; corrected cells: `11` (annual `7`, quarterly `4`)
- Stock Report JSON/MD changed: `4/4`; Web payloads changed by UI/data contract: `553/553`
- unexplained MISMATCH: `0`; WRONG_SIGN: `0`

## Concrete candidate evidence

Each CSV row records every eligible cached official candidate as `rcept=value` in `reason`; external stale rows retain production only when the latest eligible candidate equals the production value and the Naver value is absent from that candidate set.

## Regressions

- Yusu 000700 2023 FY operating income: `21985188591`
- CJ 000120 2025 Q1 operating income: `85366748157`
- V07 Fundamentals chart assets were not modified by this script.
