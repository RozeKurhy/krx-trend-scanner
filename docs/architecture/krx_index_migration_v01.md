# KRX 시장 대표지수 전환 (KRX_INDEX_MIGRATION_V01)

목적
----
KOSPI 대표지수 1001과 KOSDAQ 대표지수 2001의 운영 원천을 PyKRX에서
KRX Open API의 /idx/kospi_dd_trd, /idx/kosdaq_dd_trd로 전환한다.
이번 문서는 MARKET_INDEX만 다루며 native sector index, 구성 종목 정보, RS 수식과
사용 코드 기본 연결은 변경하지 않는다.

현재 상태 경계
----------------

이 문서의 전환 계약과 아래 known-limitations token은 당시 단계 기록이다.
현재 Pattern A 운영 scanner는 기본 market-index 입력으로
`data/market/index/v01`의 `IndexStore(MARKET_INDEX)`를 읽고, 기존 relative-strength
artifact(산출물)는 parity/comparison 검증 근거로만 유지한다. 현재 수정주가 원천 기준은
Naver direct date-range와 `AdjustedPriceStore V02`이며, V02 운영 적재
구현도 후속 단계에서 반영되었다. 다만 full end-to-end parity 전체 상태는 이 문서에서
새로 해소되었다고 확정하지 않는다.

정적 매핑
------------
KRX_MARKET_INDEX_MAP_V01은 정확히 두 항목을 가진 immutable mapping이다.

  1001 | MARKET_INDEX | kospi_dd_trd | KOSPI | 코스피
  2001 | MARKET_INDEX | kosdaq_dd_trd | KOSDAQ | 코스닥

IDX_NM은 정확히 코스피/코스닥이어야 한다. 코스피 (외국주포함), 코스닥
(외국주포함), 첫 row, contains/startswith 선택은 허용하지 않는다.

IndexStore 저장소
-----------------
IndexStore는 network/PyKRX/artifact 의존성이 없는 INDEX_STORE_V01 로컬 저장소다.
파일은 data/market/index/v01/market_index.parquet와
data/market/index/v01/market_index.meta.json이며, (date, family, index_code)를
유일 키로 사용한다. full replacement는 schema, family, code, 날짜, numeric,
OHLC, hash를 모두 검증한 뒤 temporary file과 atomic replace로 publish한다.

거래일 달력·quota·재개
----------------------
과거 대상은 CLOSED KRXRawStockStore manifest에서 양 시장 COMPLETE인
날짜만 파생한다. 양 시장 NO_DATA는 skip하고 asymmetric 상태는
BLOCKED_RAW_TRADING_CALENDAR_INCONSISTENT로 중단한다. quota authority는
.cache/krx_openapi/quota.sqlite3 하나이며 모든 HTTP attempt와 retry를 count한다.
한 날짜는 두 endpoint를 함께 처리하고, quota 부족 시 whole-date tranche만
staging에 저장한다. partial staging은 운영 IndexStore로 publish하지 않는다.

staging·publish
--------------
staging은 .cache/krx_openapi/market_index_migration/v01에 둔다. 모든 대상
날짜가 두 행(1001, 2001)으로 검증되고 legacy OHLC 일치성, market RS 일치성,
quota audit, secret scan, integrity gate가 통과한 경우에만 운영 store를
한 번 publish한다. 사용 코드는 END_TO_END_DATA_PARITY_V01에서 전환한다.

legacy 일치성·RS 일치성
-----------------------
PyKRX 실시간 parity fetch는 금지한다. 기존
artifacts/patterns/pattern_a/validation/relative_strength/source/
market_index_daily_20260814.parquet를 고정 SHA-256으로 검증하고 Decimal exact
OHLC 비교를 수행한다. RS 수식은 기존 relative_strength.py를 그대로 사용해
KOSPI/KOSDAQ old/new 결과를 비교한다.

FIX01 당시 known limitations
-----------------
CONSUMER_MARKET_INDEX_RUNTIME_SWITCH_NOT_PERFORMED
RELATIVE_STRENGTH_ARTIFACT_CACHE_NOT_YET_REMOVED
PRODUCTION_ADJUSTED_STORE_POPULATION_NOT_IMPLEMENTED
FULL_END_TO_END_PARITY_DEFERRED
