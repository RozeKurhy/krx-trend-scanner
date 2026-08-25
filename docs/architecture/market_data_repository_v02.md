market_data_repository_v02.md

================================================================================
MARKET_DATA_REPOSITORY_V02
================================================================================

목적
----
AdjustedPriceStore의 조정 OHLC와 KrxRawStockStore의 원천 일별 사실을
read-only composition layer에서 결합한다. Repository V2는 authority가 아니며
가격 조정, 원천 보정, corporate action 처리, 네트워크 조회를 수행하지 않는다.

소스 authority
--------------
* open/high/low/close: AdjustedPriceStore, PYKRX_ADJUSTED_PRICE, ADJUSTED
* volume/trading_value: KrxRawStockStore, KRX_OPEN_API_STOCK_DAILY, RAW
* market_cap/listed_shares: KrxRawStockStore의 raw ancillary만 제공

Ticker domain
-------------
* adjusted API: 기존 SIX_DIGIT_TICKER numeric domain 유지
* raw API: KRX_SHORT_CODE 정규식 ^[0-9A-Z]{6}$를 source-preserving 지원
* raw suffix 제거, upper 변환, 숫자 coercion, 복구/보정은 하지 않는다.

API schema
---------
get_daily(ticker, start, end)
  index: timezone-naive, ascending, unique DatetimeIndex
  columns: open, high, low, close, volume, trading_value
  OHLC는 adjusted, volume/trading_value는 raw.

get_raw_daily(ticker, start, end)
  columns: open, high, low, close, volume, trading_value, market_cap, listed_shares
  모든 값은 raw이며 raw KRX ticker domain을 사용한다.

get_daily_ancillary(ticker, start, end)
  columns: volume, trading_value, market_cap, listed_shares
  OHLC를 포함하지 않는다.

get_stock_snapshot(ticker, date)
  해당 날짜의 정확히 1개 raw row를 반환한다. 없으면 DATA_UNAVAILABLE이다.

Join 및 missing semantics
-------------------------
adjusted/raw 양쪽의 non-empty trading session set은 정확히 같아야 한다.
한쪽 날짜를 조용히 drop하거나 forward-fill/bfill/0-fill하지 않는다.
session set mismatch는 REPOSITORY_V2_TRADING_SESSION_MISMATCH로 fail-closed한다.
양쪽이 모두 empty인 요청 범위는 typed empty daily frame을 반환할 수 있다.
한쪽만 empty이거나 ticker store가 없으면 DATA_UNAVAILABLE로 종료한다.

Read-only 및 compatibility
--------------------------
Repository V2는 store를 생성자 주입받고 write/refresh를 호출하지 않는다.
기존 MarketDataRepository와 tests/test_repository.py는 변경하지 않는다.
consumer 자동 migration은 0건이며 Pattern A, FastCore, Julia, RS, Stock Report
등의 전환은 END_TO_END_DATA_PARITY_V01 이후 별도 결정한다.

Performance limitation
----------------------
KrxRawStockStore.load_ticker의 market/date partition scan 비용은
production probe telemetry로 관찰한다. 전수 materialization, bulk cache 생성,
storage redesign은 이 phase 범위에 포함하지 않는다.

Validation evidence
-------------------
* tests/test_repository_v2.py: source authority, strict join, domain, missing,
  mutation, cross-market, duplicate-date 및 network isolation 관련 검증
* tests/test_market_data_repository_v02_validation.py: FIX01의 샘플 수,
  metadata-derived 범위, empty comparison, 예외 구조화 및 diff-check gate 검증
* scripts/validate_market_data_repository_v02.py: FIX01 검증 gate와 임시
  AdjustedPriceStore 기반의 제한된 live authority probe
* artifacts/data/market_data_repository/v02/: contract, provenance, probe,
  compatibility, performance 및 regression 증적

FIX01 실행 경계
---------------
* validator 실행 전에 source/test/doc 변경을 고정하고, bounded regression을
  통과한 커밋 이후에만 live probe를 수행한다.
* live probe의 adjusted 샘플은 005930(2018-04-01..2018-06-30),
  000660(2026-07-01..2026-08-21), 068270(2026-07-01..2026-08-21) 세 건으로
  제한한다. 실제 비교 범위는 임시 store metadata의 actual_date_min/max에서
  파생하며 날짜를 하드코딩하지 않는다.
* PyKRX adjusted=True 호출만 허용하고 KRX Open API, OpenDART, fallback 및
  retry는 0건이어야 한다. 외부 실패 시 재시도하지 않고 blocker로 기록한다.
* 임시 AdjustedPriceStore에만 adjusted 데이터를 저장하고 live probe 종료 후
  경로가 제거되는지 확인한다. production raw/adjusted store와 corporate-action
  state에는 쓰지 않으며 before/after snapshot이 동일해야 한다.
* 세 샘플 모두 adjusted OHLC, raw volume/trading_value, ancillary 및 날짜 집합이
  exact match여야 하며, Samsung listed_shares 의미론과 alphanumeric raw ticker
  probe도 별도 gate로 확인한다.
* production adjusted store population과 consumer migration은 이 단계에서
  구현하지 않는다. 둘은 후속 migration 전제조건으로 문서화한다.

FIX02 raw authority 및 probe evidence
-------------------------------------
* Repository V2의 raw OHLC relation은 frozen KRX raw authority와 동일하게
  모든 OHLC 값이 양수인 row에만 적용한다. zero-price row는 source-valid
  semantics를 보존하며 repository가 새 validity rule을 추가하지 않는다.
* raw numeric parseability, NaN/inf, 음수 ancillary 및 volume/trading_value
  범위는 계속 fail-closed로 검증한다. source 값의 repair, fill, clamp, adjust,
  round 또는 대체 의미론 변환은 수행하지 않는다.
* FIX02 validator는 adjusted provider fetch, temporary store write/readback,
  production raw load, repository composition, Samsung semantic 및
  alphanumeric raw probe를 별도 stage와 record로 남긴다.
* successful_provider_fetch_count, successful_temp_store_integrity_count,
  successful_composition_probe_count 및 usable_composition_sample_count는
  서로 독립적으로 계산한다. logical_fetch_count가 3보다 작다는 사실만으로
  PyKRX 외부 장애를 추론하지 않는다.
* 외부 PyKRX blocker는 ADJUSTED_PROVIDER_FETCH stage의 실제 exception 또는
  empty/invalid provider output이 증적에 존재할 때만 부여한다. composition,
  temporary store, raw load 실패는 각각 전용 blocker로 기록한다.
* Network 0 offline raw probe는 005930, 000660, 068270의 raw parity와
  zero-price row count를 확인하고, Samsung listed_shares와 alphanumeric
  raw domain probe는 adjusted live 샘플과 독립적으로 수행한다.
