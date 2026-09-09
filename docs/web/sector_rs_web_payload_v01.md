# Sector RS Web Payload Export V01

## Purpose

`web/data/sector-rs-ranking.json` is a static web projection of the closed
Sector RS Within-Sector Ranking Contract V01 authority. The exporter does not
recalculate Sector RS, ranking, or percentile values.

## Sources

- Ranking authority: `data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904.parquet`
- Ranking metadata: `data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904_meta.json`
- Exact name authority: `data/reference/source/history/krx_instrument_master/v01/rolling/basic_info/2026/20260904/{KOSPI,KOSDAQ}.json`
- Report availability: existing `web/data/stocks/*.json` file set

The exact 2026-09-04 Basic Info join is fail-closed. `web/data/stock-index.json`
is not used as a population, name, or market authority because its universe
snapshot is 2026-08-21.

## Payload contract

- `items` preserves all 2,562 authority rows: MAPPED 2,440, AGGREGATE_ONLY 88,
  and UNMAPPED 34.
- `sectors` contains 45 canonical groups keyed by `market:sector_code`.
- `sector_key` is null for UNMAPPED rows; their ranking fields remain null.
- `report_available` is only a clickability/file-availability indicator. It
  never changes ranking denominators or eligibility counts.
- Raw `sector_rs_*`, `within_sector_rs_rank_*`, percentile, member-count, and
  eligible-count values are projected from the authority without rounding or
  reinterpretation.
- Items are stored in `market`, `sector_code`, `ticker` order; sectors are
  stored in `market`, `sector_code` order.
- JSON serialization is strict: NaN and +/-Infinity become null and are not
  emitted as invalid JSON numbers.

## Export

```text
scripts/export_sector_rs_ranking_web.py
```

The exporter is offline-only and has a network guard. It does not modify
`web/market.html`, JavaScript, CSS, the core ranking authority, Stock Reports,
or `stock-index.json`.
