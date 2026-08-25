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
* scripts/validate_market_data_repository_v02.py: local store-only production probe
* artifacts/data/market_data_repository/v02/: contract, provenance, probe,
  compatibility, performance 및 regression 증적

