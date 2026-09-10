# Fundamentals V1 full authority audit V02

- requested_as_of: `2026-09-04`
- universe: `4415`; applicable common/non-financial: `2399`
- selected filings: `47887`; selected XBRL cache miss: `488`
- hypothetical remaining-miss projection: `18458 + 488 = 18946` / `39000` (no further fetch requested)
- registry cache missing: `0`; future filing rejected: `0`
- local audit network requests: `0`

## Source completion

- scope: selected filing XBRL cache misses only
- current manifest attempts/fetched/failures/remaining: `492`/`4`/`488`/`488`
- unresolved classification: `DART_SOURCE_UNAVAILABLE_STATUS_014`; status counts: `{'014': 488}`
- historical targeted attempts: `5033`; actual estimated daily total: `23491` / `39000`
- unresolved source failures were retained in the audit manifest and were not retried beyond the quota-controlled retry.

## F7 invariants

```json
{
  "completed": 4415,
  "duplicate": 0,
  "invalid": 0,
  "outside_universe": 0,
  "remaining": 0,
  "total": 4415
}
```

## Representative checks

```json
{
  "021240": {
    "annual_count": 5,
    "data_status": "READY",
    "f4_status": "PASS",
    "optional_debt_ratio_missing": true,
    "optional_roe_missing": true,
    "quarter_count": 12
  },
  "181710": {
    "annual_count": 5,
    "data_status": "READY",
    "f4_status": "PASS",
    "optional_debt_ratio_missing": true,
    "optional_roe_missing": true,
    "quarter_count": 12
  }
}
```

## External sample validation

- samples/pass/fail: `12`/`12`/`0`
- artifact: `artifacts/fundamentals/validation/fundamentals_v1_full_authority_audit_v02/external_sample_validation.csv`

## Final local state

```json
{
  "data_status": {
    "DATA_UNAVAILABLE": 918,
    "NOT_APPLICABLE": 2012,
    "PARTIAL": 519,
    "READY": 966
  },
  "f3_status": {
    "DATA_UNAVAILABLE": 918,
    "NOT_APPLICABLE": 2012,
    "PARTIAL": 519,
    "READY": 966
  },
  "f4_status": {
    "DATA_UNAVAILABLE": 918,
    "FILTERED_ANNUAL_REVENUE": 374,
    "FILTERED_NET_LOSS": 104,
    "FILTERED_OPERATING_LOSS": 230,
    "FILTERED_QUARTERLY_REVENUE": 7,
    "NOT_APPLICABLE": 2012,
    "PASS": 770
  }
}
```
