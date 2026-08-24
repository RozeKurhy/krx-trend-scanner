krx_production_data_architecture_v01.md

======================================================================
KRX Production Data Architecture v01
======================================================================

상태
----------------------------------------------------------------------

이 문서는 production data authority, logical store, Repository V2 target,
PIT/provenance, data health 계약을 고정한다. 이번 단계의 최종 상태는
`READY_FOR_ARCHITECT_KRX_PRODUCTION_DATA_ARCHITECTURE_V01_REVIEW`이며,
Architect 승인 전에는 `CLOSED`로 선언하지 않는다.

이번 단계의 범위
----------------------------------------------------------------------

- authority와 source semantics를 machine-readable contract로 고정한다.
- raw/adjusted/master/index/membership/fundamentals/dirty-state store 역할을 분리한다.
- 기존 `data/raw/stocks/<ticker>.parquet`는 `LEGACY_COMPOSITE_STOCK_CACHE`로 분류한다.
- Repository V2의 adjusted OHLC + raw ancillary join semantics를 고정한다.
- 모든 time-aware layer의 PIT/as_of 및 provenance 필드를 정의한다.
- Operations Dashboard가 소비할 health/status contract를 정의한다.
- 오프라인 static validator와 contract tests로 계약을 검증한다.

이번 단계에서 하지 않는 것
----------------------------------------------------------------------

- KRX Open API, PyKRX, OpenDART 네트워크 호출
- production fetch provider 전환
- historical backfill 또는 대량 parquet 생성
- 기존 stock cache rewrite/move/delete/bulk rename
- custom corporate-action adjustment engine
- market index source 전환
- ticker→sector membership source 전환
- Pattern A, FastCore, Julia, RS formula 변경
- HTML/dashboard UI 구현

1. Authority matrix
----------------------------------------------------------------------

Machine-readable 원본은
`src/trend_scanner/data/source_contracts.py`의 `AUTHORITY_FIELDS`다.

---------------------------------------------------------------------
| 데이터 의미                  | 현재/목표 authority                         |
---------------------------------------------------------------------
| raw OHLC                    | KRX Open API `/sto/stk_bydd_trd`,        |
|                             | `/sto/ksq_bydd_trd`                       |
| volume/trading_value        | KRX Open API raw                         |
| market_cap/listed_shares    | KRX Open API raw daily                   |
| adjusted OHLC               | PyKRX `adjusted=True`                   |
| adjusted volume              | NONE; 제공한다고 선언하지 않음           |
| stock master                | KRX Open API Basic Info                 |
| native sector index         | KRX Open API; 46 native sectors         |
| market index                | 현재 PyKRX legacy, 목표 KRX Open API    |
| ticker→sector membership    | 현재 PyKRX PDF, 향후 별도 PIT phase     |
| fundamentals                | OpenDART                               |
| foreign/institution flow    | 기존 production source                  |
---------------------------------------------------------------------

raw와 adjusted의 의미는 절대 합쳐서 하나의 authority로 표현하지 않는다.
AdjustedPriceStore는 OHLC만 소유하고 volume, trading_value, market_cap,
listed_shares를 저장하지 않는다.

2. Endpoint identifier semantics
----------------------------------------------------------------------

`ISU_CD`는 endpoint-qualified field다.

- Daily trading: `ISU_CD -> ticker` (6자리 종목코드)
- Basic info: `ISU_CD -> standard_code`
- Basic info: `ISU_SRT_CD -> ticker`
- `SECT_TP_NM`은 상장부/관리 분류인 `security_group`이며 sector membership이 아니다.

따라서 generic `ISU_CD = ticker` mapping과 `SECT_TP_NM -> sector_code` mapping은
금지한다. 구체 계약은 `ENDPOINT_IDENTIFIER_CONTRACT`로 직렬화한다.

3. Logical stores
----------------------------------------------------------------------

`source_contracts.py`의 `STORE_CONTRACTS`가 다음 7개 store와 schema version을
정의한다.

---------------------------------------------------------------------
| Store                         | 핵심 소유권                           |
---------------------------------------------------------------------
| KRXRawStockStore              | unadjusted OHLC + raw ancillary       |
| AdjustedPriceStore            | adjusted OHLC only                   |
| StockMasterStore              | as_of 포함 PIT master                |
| IndexStore                    | market/native-sector/taxonomy family |
| SectorMembershipStore         | effective_date 기반 PIT membership   |
| FundamentalsStore             | OpenDART reported facts              |
| CorporateActionStateStore     | adjusted cache dirty/refresh state   |
---------------------------------------------------------------------

이번 phase에서는 protocol/dataclass 수준의 계약만 정의한다. 실제 모든 store의
구현과 대량 데이터 이동은 후속 phase다.

4. Legacy composite cache
----------------------------------------------------------------------

현재 `data/raw/stocks/<ticker>.parquet`는 PyKRX adjusted OHLC와 raw volume,
raw trading_value가 결합된 기존 소비자 호환 캐시다. 이 파일을
`KRXRawStockStore`라고 부르지 않는다.

이번 phase에서 해당 경로의 파일을 rewrite, move, delete, bulk rename하지 않는다.
Pattern A, FastCore, Julia 등 기존 소비자는 당분간 legacy cache를 그대로 사용한다.

5. Repository V2
----------------------------------------------------------------------

개념 target은 `MarketDataRepositoryV2(adjusted_price_store, raw_stock_store, ...)`다.

- `get_daily()`의 open/high/low/close는 ADJUSTED
- `get_daily()`의 volume/trading_value는 RAW
- join key는 `(ticker, date)`
- join은 `INNER_CONSISTENT_TRADING_SESSION_JOIN`
- 한쪽 layer가 없으면 `DATA_UNAVAILABLE` 또는 명시적 오류
- forward-fill과 silent fill은 금지
- market_cap/listed_shares는 `get_raw_daily()`, `get_daily_ancillary()`,
  `get_stock_snapshot()` 같은 별도 access contract로 노출

주봉/월봉은 authoritative source가 아니며, Repository daily output에서 파생한다.
가격은 adjusted OHLC, volume/trading_value는 raw daily sum을 사용한다.

6. Corporate action 및 PIT
----------------------------------------------------------------------

custom adjustment engine은 이 phase에 없다. `LIST_SHRS` 변화를 primary dirty
signal로 사용하고 `PARVAL` 변화는 강한 corroboration, raw OHLC discontinuity와
metadata 변화는 secondary evidence로 정의한다. detector는 oracle이 아니라
adjusted cache refresh 필요성 신호다.

raw history는 immutable authority로 취급하고, adjusted history는 corporate
action 이후 과거 값이 변할 수 있으므로 mutable refresh state를 별도로 둔다.
dirty scope는 ticker-specific이며 전체 universe refresh를 기본값으로 하지 않는다.

모든 time-aware store는 `as_of`/effective date를 갖고, `effective_date > as_of`,
future price, 허용 availability 이전의 report를 사용하지 않는다. 과거 universe는
당시 master snapshot을 사용해 survivorship bias를 피한다.

7. Provenance와 health
----------------------------------------------------------------------

persisted dataset metadata 최소 필드:

`layer_id`, `schema_version`, `source_name`, `source_endpoint`,
`source_semantics`, `authority_type`, `requested_as_of`, `date_min`, `date_max`,
`row_count`, `ticker_count`, `generation_timestamp`, `last_success_at`,
`content_sha256`

network dataset은 `validation_run_id`, `quota_usage_date_kst`, `run_request_count`를
추가할 수 있다. AUTH_KEY, KRX_ID, KRX_PW 및 실제 credential은 metadata/log/artifact에
저장하지 않는다. `artifacts/`는 evidence 전용이며 production runtime source가 아니다.

Health status는 `READY`, `STALE`, `PARTIAL`, `MISSING`, `ERROR`, `NOT_MIGRATED`,
`DIRTY`다. `DataHealthSnapshot`은 layer/source/date/row/ticker/missing/stale/error와
last success/attempt/message를 공통으로 노출한다. quota observability는
`usage_date_kst`, `used`, `limit`, `remaining`, `percentage`, `endpoint_usage`다.

8. Migration state
----------------------------------------------------------------------

---------------------------------------------------------------------
| Layer                      | 현재 상태                              |
---------------------------------------------------------------------
| SECTOR_INDEX_KRX           | MIGRATED                              |
| MARKET_INDEX               | LEGACY_SOURCE                         |
| STOCK_RAW_KRX              | VALIDATED_NOT_PRODUCTION_MIGRATED    |
| STOCK_ADJUSTED_PYKRX       | LEGACY_COMPOSITE_NOT_SPLIT           |
| STOCK_MASTER_KRX           | VALIDATED_NOT_PRODUCTION_MIGRATED    |
| FUNDAMENTALS_OPENDART      | CLOSED / AVAILABLE                   |
---------------------------------------------------------------------

API validation 완료만으로 production migrated/READY라고 표시하지 않는다.

9. Dependency graph
----------------------------------------------------------------------

`KRX_PRODUCTION_DATA_ARCHITECTURE_V01`
→ `ADJUSTED_PRICE_STORE_V01`
→ `CORPORATE_ACTION_DIRTY_REFRESH_V01`
→ `KRX_HISTORICAL_BACKFILL_V01`
→ `MARKET_DATA_REPOSITORY_V02`
→ `KRX_INDEX_MIGRATION_V01`
→ `END_TO_END_DATA_PARITY_V01`

그래프는 static validator에서 cycle을 검사한다. Repository V2와 AdjustedPriceStore
사이의 역방향 dependency는 만들지 않는다.

10. ADR 목록
----------------------------------------------------------------------

- ADR-01 KRX raw authority
- ADR-02 PyKRX adjusted OHLC authority
- ADR-03 raw ancillary ownership
- ADR-04 legacy composite cache classification
- ADR-05 Repository join semantics
- ADR-06 adjusted historical mutability
- ADR-07 corporate-action dirty policy
- ADR-08 endpoint-specific identifier semantics
- ADR-09 KRX `SECT_TP_NM` non-sector rule
- ADR-10 sector vs market index migration state
- ADR-11 PIT universe requirement
- ADR-12 runtime artifact dependency prohibition
- ADR-13 canonical quota authority
- ADR-14 data health observability contract

검증 및 산출물
----------------------------------------------------------------------

오프라인 validator:
`scripts/validate_krx_production_data_architecture_v01.py`

contract tests:
`tests/test_krx_production_data_architecture_v01.py`

산출물:
`artifacts/data/architecture/krx_production_data/v01/`

이번 phase의 완료 목표는 새 historical data를 만든 것이 아니라 authority,
schema, PIT, provenance, health semantics를 혼동 없이 고정하는 것이다.
