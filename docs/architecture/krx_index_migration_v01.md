docs/architecture/krx_index_migration_v01.md
================================================================================
KRX_INDEX_MIGRATION_V01
================================================================================

목적
----
KOSPI 대표지수 1001과 KOSDAQ 대표지수 2001의 production source를 PyKRX에서
KRX Open API의 /idx/kospi_dd_trd, /idx/kosdaq_dd_trd로 전환한다.
이번 문서는 MARKET_INDEX만 다루며 native sector index, membership, RS 수식과
consumer 기본 wiring은 변경하지 않는다.

정적 mapping
------------
KRX_MARKET_INDEX_MAP_V01은 정확히 두 항목을 가진 immutable mapping이다.

  1001 | MARKET_INDEX | kospi_dd_trd | KOSPI | 코스피
  2001 | MARKET_INDEX | kosdaq_dd_trd | KOSDAQ | 코스닥

IDX_NM은 정확히 코스피/코스닥이어야 한다. 코스피 (외국주포함), 코스닥
(외국주포함), 첫 row, contains/startswith 선택은 허용하지 않는다.

IndexStore
----------
IndexStore는 network/PyKRX/artifact 의존성이 없는 INDEX_STORE_V01 local store다.
파일은 data/market/index/v01/market_index.parquet와
data/market/index/v01/market_index.meta.json이며, (date, family, index_code)를
유일 키로 사용한다. full replacement는 schema, family, code, 날짜, numeric,
OHLC, hash를 모두 검증한 뒤 temporary file과 atomic replace로 publish한다.

calendar / quota / resume
-------------------------
historical target은 CLOSED KRXRawStockStore manifest에서 양 시장 COMPLETE인
날짜만 파생한다. 양 시장 NO_DATA는 skip하고 asymmetric 상태는
BLOCKED_RAW_TRADING_CALENDAR_INCONSISTENT로 중단한다. quota authority는
.cache/krx_openapi/quota.sqlite3 하나이며 모든 HTTP attempt와 retry를 count한다.
한 날짜는 두 endpoint를 함께 처리하고, quota 부족 시 whole-date tranche만
staging에 저장한다. partial staging은 production IndexStore로 publish하지 않는다.

staging / publish
-----------------
staging은 .cache/krx_openapi/market_index_migration/v01에 둔다. 모든 target
날짜가 두 row(1001, 2001)로 검증되고 legacy OHLC parity, market RS parity,
quota audit, secret scan, integrity gate가 통과한 경우에만 production store를
한 번 publish한다. consumer는 END_TO_END_DATA_PARITY_V01에서 전환한다.

legacy parity / RS parity
-------------------------
PyKRX live parity fetch는 금지한다. 기존
artifacts/patterns/pattern_a/validation/relative_strength/source/
market_index_daily_20260814.parquet를 고정 SHA-256으로 검증하고 Decimal exact
OHLC 비교를 수행한다. RS 수식은 기존 relative_strength.py를 그대로 사용해
KOSPI/KOSDAQ old/new 결과를 비교한다.

known limitations
-----------------
CONSUMER_MARKET_INDEX_RUNTIME_SWITCH_NOT_PERFORMED
RELATIVE_STRENGTH_ARTIFACT_CACHE_NOT_YET_REMOVED
PRODUCTION_ADJUSTED_STORE_POPULATION_NOT_IMPLEMENTED
FULL_END_TO_END_PARITY_DEFERRED
