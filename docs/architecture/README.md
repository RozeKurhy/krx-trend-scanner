README.md

# Architecture

특정 Pattern에 종속되지 않는 공용 infrastructure 문서.

| 문서 | 역할 |
|---|---|
| [data_layer.md](data_layer.md) | 공용 데이터 레이어 |
| [krx_production_data_architecture_v01.md](krx_production_data_architecture_v01.md) | production data authority·store·PIT 경계 |
| [adjusted_price_store_v01.md](adjusted_price_store_v01.md) | adjusted OHLC store 계약 및 무결성 |
| [market_data_repository_v02.md](market_data_repository_v02.md) | adjusted/raw read-only Repository V2 composition |
| [historical_snapshot.md](historical_snapshot.md) | Historical Snapshot Validation / Strict PIT infrastructure |
| [instrument_metadata_authority.md](instrument_metadata_authority.md) | KRX Instrument Metadata Authority — lineage & trust rule |
| [krx_dual_provider_contract_v01.md](krx_dual_provider_contract_v01.md) | raw·adjusted dual-provider 경계와 역사적 전환 계약 |
| [krx_historical_backfill_v01.md](krx_historical_backfill_v01.md) | KRX raw whole-market historical backfill 계약 |
| [corporate_action_dirty_refresh_v01.md](corporate_action_dirty_refresh_v01.md) | corporate-action dirty detection·refresh 상태 계약 |
| [krx_index_migration_v01.md](krx_index_migration_v01.md) | KOSPI/KOSDAQ market index source migration 경계 |
| [sector_rs_krx_migration_v01.md](sector_rs_krx_migration_v01.md) | native Sector RS index·exact-date membership authority |
| [survivorship_safe_denominator_freeze_v01.md](survivorship_safe_denominator_freeze_v01.md) | survivorship-safe PIT denominator freeze 계약 |
| [errata/krx_identifier_contract_errata_v01.md](errata/krx_identifier_contract_errata_v01.md) | KRX identifier contract correction overlay |
| [artifacts/artifacts_information_architecture_audit_v01.md](artifacts/artifacts_information_architecture_audit_v01.md) | artifact information architecture 및 lineage audit |
| [validation/](validation/) | 현재 사용 중인 architecture validation/test infrastructure 문서 |
| [archive/validation/](archive/validation/) | KRX 공용 데이터 소스에 대한 과거 validation/investigation 기록(cache population, market cap backfill, sector benchmark source investigation 등) |
