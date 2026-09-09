# Sector RS Within-Sector Ranking Contract V01

## Scope

This authority answers only:

> How strong is a security's Sector RS compared with other securities in the same canonical native sector?

The population is the exact `2026-09-04` SectorMembershipStore snapshot. It is independent of Stock Report publication, Pattern A candidates, or any market-wide cross-section.

## Group identity

Every ranking group is keyed by:

```text
(market, sector_code)
```

`sector_name` is descriptive only. Therefore `(KOSPI, 1009)` and `(KOSDAQ, 2066)` remain separate groups even when both names are `제약`.

This is within-sector ranking only. It is not a global ranking, KOSPI/KOSDAQ segment ranking, cross-sector ranking, candidate ranking, or published-report ranking.

## Population and membership

- Population authority: `data/market/sector_membership/v01/sector_membership_20260904.parquet`
- Total: `2,562`
- `MAPPED`: `2,440`
- `AGGREGATE_ONLY`: `88`
- `UNMAPPED`: `34`
- `MAPPED` and `AGGREGATE_ONLY` participate when canonical `market`, `sector_code`, and `sector_name` exist.
- `AGGREGATE_ONLY` is ranked in its existing canonical sector and is never reclassified.
- `UNMAPPED` rows remain in the authority with null group/rank/percentile fields and reason `SECTOR_MEMBERSHIP_UNMAPPED`.

## Inputs

```text
Sector Membership → exact 2026-09-04 SectorMembershipStore
Sector Index      → .cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet
Stock             → MarketDataRepositoryV2
Sector RS         → existing compute_relative_strength_features()
```

The sector benchmark must have an exact `2026-09-04` observation. No fallback is allowed. Sector RS formula and anchors are unchanged: 2W=`10`, 1M=`21`, 3M=`63`, 6M=`126`, 12M=`252` sessions.

## Metrics and eligibility

Only these values are ranked:

```text
sector_rs_2w
sector_rs_1m
sector_rs_3m
sector_rs_6m
sector_rs_12m
```

Higher values are stronger. Each horizon has an independent denominator. A `PARTIAL` row may rank for the horizons whose values are valid. A ranking value must be numeric and finite; null, NaN, positive infinity, and negative infinity are excluded without zero filling.

Ranks use descending order with average ties:

```text
rank = pandas rank(method="average", ascending=False)
```

For eligible population size `N`:

```text
percentile = (N - rank) / (N - 1) * 100
```

`N == 1` yields rank `1` and percentile `100`. `N == 0` yields null rank and percentile. Equal values receive equal rank and percentile.

## Authority artifact

The network-free builder is:

```text
scripts/build_sector_rs_ranking_v01.py
```

The core ranking implementation is:

```text
src/trend_scanner/relative_strength/sector_ranking.py
```

The `2026-09-04` artifact is stored outside `web/data`:

```text
data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904.parquet
data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904_meta.json
```

The core artifact is canonically stored by `market`, `sector_code`, and `ticker`. UI ordering is a later projection concern.

## Output fields

Each population row contains the exact-date identity, Sector RS provenance/status, the five Sector RS values, and:

```text
within_sector_rs_rank_2w/1m/3m/6m/12m
within_sector_rs_percentile_2w/1m/3m/6m/12m
sector_member_count
sector_eligible_count_2w/1m/3m/6m/12m
```

Existing `all_sector_rs_*` global fields are not used or changed by this authority.

## Out of scope

- Web payload/UI, sector selector, JavaScript, CSS, and GitHub Pages
- Stock Report regeneration
- Market RS, Foreign Flow, Trading Value, Fundamentals, Pattern A, or A FAST
- Full Universe Scanner
- Sector Membership or Sector Index downloads
- OpenDART, Naver, PyKRX, KRX Open API, and direct HTTP
