krx_production_data_architecture_v01.md

# KRX 운영 데이터 아키텍처 (KRX Production Data Architecture v01)

상태
----------------------------------------------------------------------

이 문서는 운영 데이터 기준, 논리 저장소, Repository V2 대상,
PIT/계보, 데이터 상태 계약을 고정한다. 이번 단계의 최종 상태는
`READY_FOR_ARCHITECT_KRX_PRODUCTION_DATA_ARCHITECTURE_V01_FIX03_REVIEW`이며,
Architect 승인 전에는 `CLOSED`로 선언하지 않는다.

현재 구현 경계
----------------------------------------------------------------------

위 상태와 아래 FIX03 범위·전환 표는 해당 architecture phase의 스냅샷이다.
현재 수정주가 OHLC 기준 원천은 Naver direct date-range (`requestType=1`)와
`AdjustedPriceStore V02`이며, 운영 Stock Report와 Pattern A scanner는
`build_production_repository_v2`를 통해 Repository V2 운영 연결을 사용한다.
Pattern A 운영 scanner의 market-index 기본 경로는
`data/market/index/v01`의 `IndexStore(MARKET_INDEX)`이며, 과거 parity artifact는
비교 증적으로만 유지된다. 따라서 아래의 “후속 phase”, “개념 target”, legacy
consumer 문구는 이 문서가 작성된 당시의 상태로 읽는다.

이번 단계의 범위
----------------------------------------------------------------------

- 기준과 원천 의미를 기계 판독 가능한 계약으로 고정한다.
- 원천/수정주가/master/index/구성 종목/fundamentals/dirty-state store 역할을 분리한다.
- 기존 `data/raw/stocks/<ticker>.parquet`는 `LEGACY_COMPOSITE_STOCK_CACHE`로 분류한다.
- Repository V2의 수정주가 OHLC + 원천 ancillary 결합 의미를 고정한다.
- 모든 time-aware layer의 PIT/as_of 및 provenance 필드를 정의한다.
- Operations Dashboard가 소비할 health/status contract를 정의한다.
- 오프라인 static validator와 contract tests로 계약을 검증한다.
- 실제 raw schema와 request/mapping-derived provenance를 구분한다.
- StockMaster raw fact, 표준 market, instrument classification의 경계를 구분한다.
- KRX `IDX_CLSS` source class와 logical index family를 분리한다.
- 현재 legacy 실행 시점의 `artifacts/` 소비를 debt registry로 추적한다.

이번 단계에서 하지 않는 것
----------------------------------------------------------------------

- KRX Open API, PyKRX, OpenDART 네트워크 호출
- 운영 fetch 데이터 제공자 전환
- 과거 데이터 백필 또는 대량 parquet 생성
- 기존 stock cache rewrite/move/delete/bulk rename
- custom corporate-action adjustment engine
- market index source 전환
- 이미 승인된 exact-date SectorMembershipStore snapshot 변경/재생성
- Pattern A, FastCore, Julia, RS formula 변경
- HTML/dashboard UI 구현

1. Authority 매트릭스
----------------------------------------------------------------------

Machine-readable 원본은
`src/trend_scanner/data/source_contracts.py`의 `AUTHORITY_FIELDS`다.

---------------------------------------------------------------------
| 데이터 의미                  | 현재/목표 기준                             |
---------------------------------------------------------------------
| raw OHLC                    | KRX Open API `/sto/stk_bydd_trd`,        |
|                             | `/sto/ksq_bydd_trd`                       |
| volume/trading_value        | KRX Open API raw                         |
| market_cap/listed_shares    | KRX Open API raw daily                   |
| 수정주가 OHLC (`ADJUSTED`)  | Naver direct date-range (`requestType=1`) |
| 수정주가 거래량              | NONE; 제공한다고 선언하지 않음           |
| stock master raw facts     | KRX Basic Info + request basDd          |
| stock master 표준 market | `normalize_krx_market(raw_market)`    |
| instrument asset type      | InstrumentMetadataResolver/공식 product-master classification |
| native sector index         | KRX Open API native sector index       |
| market index                | FIX03 snapshot: PyKRX legacy, 목표 KRX Open API |
| ticker→sector membership    | KRX Data Marketplace official index constituents CSV → exact-date SectorMembershipStore snapshots |
| fundamentals                | OpenDART                               |
| foreign/institution flow    | PyKRX Foreign Flow                      |
---------------------------------------------------------------------

원천과 수정주가의 의미는 절대 합쳐서 하나의 기준으로 표현하지 않는다.
AdjustedPriceStore는 OHLC만 소유하고 volume, trading_value, market_cap,
listed_shares를 저장하지 않는다.

2. Endpoint 식별자 의미
----------------------------------------------------------------------

`ISU_CD`는 endpoint-qualified field다.

- Daily trading: `ISU_CD -> ticker` (6자리 종목코드)
- Basic info: `ISU_CD -> standard_code`
- Basic info: `ISU_SRT_CD -> ticker`
- Basic info: `SECUGRP_NM -> security_group`
- Basic info: `SECT_TP_NM -> listing_section`
- Basic info: `MKT_TP_NM -> raw_market`
- Basic info: `KIND_STKCERT_TP_NM -> security_kind`
- `SECUGRP_NM`과 `SECT_TP_NM`은 모두 `NOT_SECTOR_MEMBERSHIP` namespace이며,
  어느 필드도 `sector_code` 또는 ticker->sector membership을 의미하지 않는다.

따라서 generic `ISU_CD = ticker` mapping, `SECUGRP_NM -> listing_section`
mapping, `SECT_TP_NM -> security_group` mapping 및 두 필드를
`sector_code`로 재사용하는 것은 금지한다. 구체 계약은
`ENDPOINT_IDENTIFIER_CONTRACT`로 직렬화한다.

Basic Info response에는 `BAS_DD`가 없다. `StockMasterStore.as_of`는
`REQUEST_PARAMETER.basDd`에서 파생된 `REQUESTED_SNAPSHOT_DATE`다.

`StockMasterStore.raw_market`는 `MKT_TP_NM` 원문이다. `StockMasterStore.market`는
`normalize_krx_market(raw_market)`로 얻는 프로젝트 표준 value이며, 두 필드를
같은 의미의 중복 authority로 취급하지 않는다. `StockMasterStore`는
`security_group`, `listing_section`, `security_kind` 같은 raw/master fact를 보유하지만
최종 `asset_type` authority가 아니다.

Native sector index response의 raw identity는
`(source_api, IDX_CLSS, IDX_NM)`다. `IndexStore.index_code`는 raw response field가
아니라 frozen `KRX_NATIVE_SECTOR_INDEX_MAP`에서 파생된 표준 code이며,
`IndexStore.family`는 `MARKET_INDEX`, `NATIVE_SECTOR_INDEX`,
`KRX_BRANDED_TAXONOMY` 중 logical family다. `IDX_CLSS`는 `source_index_class`로
보존하며 logical family로 사용하지 않는다. 표준 key는 `(family, index_code)`다.

3. 논리 저장소
----------------------------------------------------------------------

`source_contracts.py`의 `STORE_CONTRACTS`가 다음 8개 store와 schema version을
정의한다. 각 required field의 provenance는 전역 필드명이 아니라
`(owner_store, target_field)` 키로 `STORE_FIELD_PROVENANCE`에서 관리한다.

---------------------------------------------------------------------
| Store                         | 핵심 소유권                           |
---------------------------------------------------------------------
| KRXRawStockStore              | 미수정 OHLC + 원천 ancillary              |
| AdjustedPriceStore            | 수정주가 OHLC (`ADJUSTED`) only; schema `ADJUSTED_PRICE_V02` / store `ADJUSTED_PRICE_STORE_V02` |
| StockMasterStore              | as_of 포함 PIT raw/표준 master; final asset_type 제외 |
| InstrumentClassificationStore| PIT asset_type/applicability + provenance |
| IndexStore                    | market/native-sector/taxonomy family; key=(family,index_code) |
| SectorMembershipStore         | effective_date 기반 PIT membership   |
| FundamentalsStore             | OpenDART reported facts              |
| CorporateActionStateStore     | 수정주가 cache dirty/refresh state      |
---------------------------------------------------------------------

FIX03 당시에는 protocol/dataclass 수준의 계약만 정의했다. 실제 모든 store의
구현과 대량 데이터 이동은 당시 후속 phase로 남겨 두었다.

InstrumentClassificationStore
----------------------------------------------------------------------

required field는 `effective_date`, `ticker`, `asset_type`,
`classification_authority`, `asset_type_source`다. `(effective_date, ticker)`를
표준 PIT key로 사용하고 requested `as_of` 이하의 최신 effective date를 조회한다.
`asset_type`은 `StockMasterStore.security_group/listing_section/security_kind`와
필요한 공식 product-master 근거를 해석한 DERIVED 결과다. 현재 운영
authority인 `InstrumentMetadataResolver -> data/reference/krx_instrument_metadata.parquet`
와 공식 ETF/ETN product-master 기준은 이번 phase에서 교체하지 않는다.
KOSPI/KOSDAQ Basic Info만으로 ETF/ETN까지 분류한다고 선언하지 않는다.

Pattern A, FastCore, Stock Report 등 instrument applicability 판단은 이 classification
layer를 사용해야 하며, consumer가 `KIND_STKCERT_TP_NM`, `SECUGRP_NM`, `SECT_TP_NM`을
각자 즉석 해석하는 중복 architecture는 금지한다.

4. Legacy composite cache
----------------------------------------------------------------------

현재 `data/raw/stocks/<ticker>.parquet`는 PyKRX 수정주가 OHLC와 원천 volume,
raw trading_value가 결합된 기존 소비자 호환 캐시다. 이 파일을
`KRXRawStockStore`라고 부르지 않는다.

이번 단계에서 해당 경로의 파일을 다시 쓰기, 이동, 삭제, 일괄 이름 변경하지 않는다.
FIX03 당시 Pattern A, FastCore, Julia 등 기존 소비자는 당분간 legacy cache를
그대로 사용하도록 기록했다. 현재 운영 사용 코드 연결은 위의 현재 구현
경계에 적은 후속 Repository V2 경로를 따른다.

5. Repository V2
----------------------------------------------------------------------

FIX03 당시 문서상 개념 대상은
`MarketDataRepositoryV2(adjusted_price_store, raw_stock_store, ...)`였다.

- `get_daily()`의 open/high/low/close는 `ADJUSTED` (수정주가)
- `get_daily()`의 volume/trading_value는 `RAW` (원천)
- join key는 `(ticker, date)`
- join은 `INNER_CONSISTENT_TRADING_SESSION_JOIN`
- 한쪽 layer가 없으면 `DATA_UNAVAILABLE` 또는 명시적 오류
- forward-fill과 silent fill은 금지
- market_cap/listed_shares는 `get_raw_daily()`, `get_daily_ancillary()`,
  `get_stock_snapshot()` 같은 별도 access contract로 노출

주봉/월봉은 authoritative source가 아니며, Repository daily output에서 파생한다.
가격은 수정주가 OHLC, volume/trading_value는 원천 일별 합계를 사용한다.

6. Corporate action 및 PIT
----------------------------------------------------------------------

custom adjustment engine은 이 phase에 없다. `LIST_SHRS` 변화를 primary dirty
signal로 사용하고 `PARVAL` 변화는 강한 corroboration, raw OHLC discontinuity와
metadata 변화는 secondary evidence로 정의한다. detector는 oracle이 아니라
수정주가 cache refresh 필요성 신호다.

원천 이력은 immutable authority로 취급하고, 수정주가 이력은 corporate
action 이후 과거 값이 변할 수 있으므로 mutable refresh state를 별도로 둔다.
dirty scope는 ticker-specific이며 전체 universe refresh를 기본값으로 하지 않는다.

모든 time-aware store는 `as_of`/effective date를 갖고, `effective_date > as_of`,
future price, 허용 availability 이전의 report를 사용하지 않는다. 과거 universe는
당시 master snapshot을 사용해 survivorship bias를 피한다.

7. 계보와 health
----------------------------------------------------------------------

persisted dataset metadata 최소 필드:

`layer_id`, `schema_version`, `source_name`, `source_endpoint`,
`source_semantics`, `authority_type`, `requested_as_of`, `date_min`, `date_max`,
`row_count`, `ticker_count`, `generation_timestamp`, `last_success_at`,
`content_sha256`

network dataset은 `validation_run_id`, `quota_usage_date_kst`, `run_request_count`를
추가할 수 있다. AUTH_KEY, KRX_ID, KRX_PW 및 실제 인증 정보는 metadata/log/artifact에
저장하지 않는다.

Field provenance origin은 `RESPONSE_FIELD`, `REQUEST_PARAMETER`, `STATIC_MAPPING`,
`DERIVED`, `STATE`, `PROVENANCE_METADATA`, `DERIVED_SOURCE_TRACE`, `LEGACY_SOURCE`로
구분한다. `RESPONSE_FIELD`는 committed raw
schema에 존재해야 하며, request/mapping-derived field는 `source_field=null`과
`source_locator`를 사용한다. `STORE_FIELD_PROVENANCE`의 coverage key는
`(owner_store, target_field)`다.

TARGET ARCHITECTURE RULE:
새 운영 Store/Repository는 `artifacts/`를 실행 시점 원천으로 사용하지 않는다.

현재 수정주가 실행 시점 기준 원천은 패키지 소유
`ADJUSTED_PRICE_AUTHORITY_CONTRACT`의 Naver direct date-range 수정주가 원천이다.
`NaverDirectAdjustedPriceDataProvider`가 `AdjustedPriceStore V02`에 현재 기준 데이터를
기록하며, Closure V02 파일은 오프라인 감사 근거로만 사용한다. 기존
`ADJUSTED_PRICE_V01`/PyKRX cache는 레거시 호환 또는 검증 비교기로
읽을 수 있지만 현재 기준이 아니다.

CURRENT LEGACY REALITY:
일부 기존 analytics/report 흐름은 `artifacts/` 기반 data cache를 실행 시점에
사용하며 `LEGACY_RUNTIME_DEPENDENCIES`에 migration debt로 등록한다. Dashboard는
향후 이 registry를 Architecture Debt로 표시할 수 있다.

Health status는 `READY`, `STALE`, `PARTIAL`, `MISSING`, `ERROR`, `NOT_MIGRATED`,
`DIRTY`다. LayerRegistry는 정적 `operational_status`와 `migration_status`를
분리해 보유하고, `DataHealthSnapshot`은 별도 런타임 `HealthStatus`를 보유한다.
대시보드는 `layer_id`로 두 상태를 join한다. Snapshot은
layer/source/date/행/ticker/missing/stale/error와
last success/attempt/message를 공통으로 노출한다. quota observability는
`usage_date_kst`, `used`, `limit`, `remaining`, `percentage`, `endpoint_usage`다.

8. 전환 상태(Migration state) — FIX03 당시 snapshot
----------------------------------------------------------------------

---------------------------------------------------------------------
| Layer                      | 현재 상태                              |
---------------------------------------------------------------------
| SECTOR_INDEX_KRX           | MIGRATED                              |
| MARKET_INDEX               | LEGACY_SOURCE                         |
| STOCK_RAW_KRX              | VALIDATED_NOT_PRODUCTION_MIGRATED    |
| STOCK_ADJUSTED             | PARTIALLY_MIGRATED                    |
| STOCK_MASTER_KRX           | VALIDATED_NOT_PRODUCTION_MIGRATED    |
| INSTRUMENT_CLASSIFICATION  | LEGACY_SOURCE                         |
| FUNDAMENTALS_OPENDART      | CLOSED / AVAILABLE                   |
---------------------------------------------------------------------

아래 표는 FIX03 당시의 migration snapshot이며, token/value는 역사 기록으로
보존한다. API 검증 완료만으로 운영 전환/READY라고 표시하지 않는다.
이번 FIX03에서 `STOCK_RAW_KRX`는 실제 production source가 아니라
`LEGACY_COMPOSITE_STOCK_CACHE`를 현재 원천으로 명시하고, 검증 원천과
target store를 별도 기록한다. `STOCK_MASTER_KRX`의 current source는 현재
레포의 `InstrumentMetadataResolver -> data/reference/krx_instrument_metadata.parquet`
동결 artifact authority이며, KRX Basic Info는 validated/target 계약이다.
`STOCK_MASTER_KRX`는 raw/표준 master 경계만 담당하고, asset type 기준은
`INSTRUMENT_CLASSIFICATION` layer로 분리한다.

Sector RS 구성 종목 기준
----------------------------------------------------------------------
현재 Sector RS 운영 경로의 구성 종목은
KRX Data Marketplace 공식 지수구성종목 CSV를 수동 로그인 브라우저로 내려받아
46-sector validation을 통과시킨 뒤 `SectorMembershipStore`에 exact-date snapshot으로
구체화한 것이다. 현재 승인 snapshot은
`data/market/sector_membership/v01/sector_membership_20260814.parquet`와
`data/market/sector_membership/v01/sector_membership_20260904.parquet`다.
요청 `as_of`는 snapshot의 `effective_date`와 정확히 일치해야 하며, 이전 snapshot을
carry-forward하거나 이후 snapshot을 backward apply하지 않는다. Marketplace 실패 시
PyKRX 구성 종목 대체 경로도 수행하지 않는다. Naver taxonomy와 live PyKRX 구성 종목은
현재 구성 종목 기준이 아니다.

10. Foreign Flow 계보와 production diff guard
----------------------------------------------------------------------

`src/trend_scanner/flow/foreign_flow.py`는 foreign flow 상위 원천 기준이
아니라 feature 계산 엔진이다. 현재 계보는
`ForeignFlowDataProvider.fetch_date_batch -> build_historical_cache`와
`scripts/fetch_foreign_flow_20260814.py`가 PyKRX
`get_market_net_purchases_of_equities_by_ticker(date, date, "ALL", "외국인")`를
호출해 `foreign_flow_daily_<as_of>.parquet`를 만들고, scanner/stock report가
`compute_foreign_flow_features`를 소비하는 흐름으로 고정한다.

FIX03 validator는 고정된 start head
`bba23053b806b3775159acf89cb6a0b143937ebd`부터 implementation head까지의
`git diff --name-only`를 검사한다. 허용 경로는 contracts, validator, 이 문서,
architecture contract tests 및 `artifacts/data/architecture/krx_production_data/v01/`
뿐이며, 그 밖의 운영 동작 경로 변경은 blocker다. `network_request_count`는
실행 중 네트워크 요청 횟수이고 `static_forbidden_network_import_count`는
계약/validator의 금지 import 정적 검사 횟수로 서로 다른 지표다. 이 작업에서는
KRX/PyKRX/OpenDART 네트워크 요청을 수행하지 않는다.

11. 의존성 graph
----------------------------------------------------------------------

`KRX_PRODUCTION_DATA_ARCHITECTURE_V01`
→ `ADJUSTED_PRICE_STORE_V02`
→ `CORPORATE_ACTION_DIRTY_REFRESH_V01`
→ `KRX_HISTORICAL_BACKFILL_V01`
→ `MARKET_DATA_REPOSITORY_V02`
→ `KRX_INDEX_MIGRATION_V01`
→ `END_TO_END_DATA_PARITY_V01`

그래프는 static validator에서 cycle을 검사한다. Repository V2와 AdjustedPriceStore
사이의 역방향 dependency는 만들지 않는다.

12. ADR 목록
----------------------------------------------------------------------

- ADR-01 KRX raw authority
- ADR-02 과거 PyKRX 수정주가 OHLC 기준 원천 (legacy/comparator)
- ADR-03 raw ancillary ownership
- ADR-04 legacy composite cache classification
- ADR-05 Repository join semantics
- ADR-06 수정주가 과거 이력 변경 가능성
- ADR-07 corporate-action dirty policy
- ADR-08 endpoint-specific identifier semantics
- ADR-09 KRX `SECT_TP_NM` non-sector rule
- ADR-10 sector vs market index migration state
- ADR-11 PIT universe requirement
- ADR-12 runtime artifact dependency prohibition
- ADR-13 canonical quota authority
- ADR-14 data health observability contract
- ADR-15 FIX01 store-qualified field provenance and state separation
- ADR-16 FIX02 raw schema truth and request/mapping provenance
- ADR-17 legacy runtime artifact dependency debt
- ADR-18 FIX03 StockMaster raw/canonical market와 instrument classification boundary
- ADR-19 FIX03 logical index family와 `IDX_CLSS` source class 분리
- ADR-20 FIX03 PIT classification compatibility와 ETF/ETN authority 보존

검증 및 산출물
----------------------------------------------------------------------

오프라인 validator:
`scripts/validate_krx_production_data_architecture_v01.py`

contract tests:
`tests/test_krx_production_data_architecture_v01.py`

산출물:
`artifacts/data/architecture/krx_production_data/v01/`

이번 단계의 완료 목표는 새 과거 데이터를 만든 것이 아니라 기준,
schema, PIT, provenance, 상태 의미를 혼동 없이 고정하는 것이다.
