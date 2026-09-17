README.md

# 아키텍처 (Architecture)

특정 Pattern에 종속되지 않는 공용 infrastructure 문서.

| 문서 | 역할 |
|---|---|
| [data_layer.md](data_layer.md) | legacy 공용 데이터 레이어 v0.1 |
| [krx_production_data_architecture_v01.md](krx_production_data_architecture_v01.md) | 운영 데이터 권위·저장소·PIT 경계 |
| [adjusted_price_store_v01.md](adjusted_price_store_v01.md) | 수정주가 OHLC 저장소 계약 및 무결성 |
| [market_data_repository_v02.md](market_data_repository_v02.md) | 수정주가·원천 데이터 읽기 전용 Repository V2 결합 |
| [historical_snapshot.md](historical_snapshot.md) | 과거 시점 검증 및 엄격한 PIT 기반 |
| [instrument_metadata_authority.md](instrument_metadata_authority.md) | KRX 종목 메타데이터 권위·계보·신뢰 규칙 |
| [krx_dual_provider_contract_v01.md](krx_dual_provider_contract_v01.md) | 원천·수정주가 이중 데이터 제공자 경계와 과거 전환 계약 |
| [krx_historical_backfill_v01.md](krx_historical_backfill_v01.md) | KRX 원천 전체 시장 과거 백필 계약 |
| [corporate_action_dirty_refresh_v01.md](corporate_action_dirty_refresh_v01.md) | 기업행위 변경 감지·갱신 상태 계약 |
| [krx_index_migration_v01.md](krx_index_migration_v01.md) | KOSPI/KOSDAQ 시장 대표지수 원천 전환 경계 |
| [sector_rs_krx_migration_v01.md](sector_rs_krx_migration_v01.md) | native Sector RS 지수·기준일별 구성 종목 기준 |
| [survivorship_safe_denominator_freeze_v01.md](survivorship_safe_denominator_freeze_v01.md) | 생존편향 방지 PIT 분모 동결 계약 |
| [errata/krx_identifier_contract_errata_v01.md](errata/krx_identifier_contract_errata_v01.md) | KRX 식별자 계약 보정 overlay |
| [artifacts/artifacts_information_architecture_audit_v01.md](artifacts/artifacts_information_architecture_audit_v01.md) | artifact(산출물) 정보 구조 및 계보 감사 |
| [validation/](validation/) | 현재 사용하는 아키텍처 검증·테스트 기반 문서 |
| [archive/validation/](archive/validation/) | KRX 공용 데이터 소스의 과거 검증·조사 기록(cache population, market cap backfill, sector benchmark source investigation 등) |
