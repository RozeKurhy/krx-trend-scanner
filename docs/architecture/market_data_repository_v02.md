# 수정주가·원천 시장데이터 저장소 (MARKET_DATA_REPOSITORY_V02)

목적
----
[현재 수정주가 저장소 계약](adjusted_price_store_v02.md)의 수정주가 OHLC와
`KrxRawStockStore`의 원천 일별 사실을 읽기 전용 결합 계층에서 결합한다.
Repository V2는 권위 기준이 아니며 가격 조정, 원천 보정, 기업행위 처리, 네트워크
조회를 수행하지 않는다.

현재 데이터 기준
--------------
* open/high/low/close: `AdjustedPriceStore`, `NAVER_DIRECT_DATE_RANGE_ADJUSTED`, `ADJUSTED` (수정주가)
* volume/trading_value: `KrxRawStockStore`, `KRX_OPEN_API_STOCK_DAILY`, `RAW` (원천)
* market_cap/listed_shares: `KrxRawStockStore`의 원천 부가 데이터만 제공

현재 구현 경계
--------------
이 문서의 FIX01/FIX02 단계 설명은 당시 검증 범위를 보존한다. 현재
수정주가 원천은 Naver direct date-range 수정주가 V02이며, 운영 Stock Report와
Pattern A 스캐너는 `build_production_repository_v2`를 통해 현재 기준을 계속 적용하는
경계를 적용한다. 고정된 과거 평가·검증 진입점은
`build_repository_v2`를 계속 사용하므로, 두 생성 함수의 과거 고정 모드와
운영 순차 갱신 모드를 혼동하지 않는다.

공식 지원 종목 계약
---------------------------------
Repository V2는 공식 분류된 `COMMON`과 `ETF`를 동일한 결합
인터페이스로 지원한다. ETF 여부는 `InstrumentMetadataResolver`의 PIT 공식
상품 마스터 분류로만 결정하며 ticker 모양·이름·17종 허용 목록을
사용하지 않는다.

* COMMON 수정주가 기준 원천: `AdjustedPriceStore` (`ADJUSTED_PRICE_STORE_V02`) / Naver direct date-range 수정주가 V02
* COMMON 원천 기준: `KrxRawStockStore` / KRX Open API stock daily
* ETF 수정주가 기준 원천: `AdjustedPriceStore` (`ADJUSTED_PRICE_STORE_V02`) / Naver direct date-range 수정주가 V02
* ETF 원천 기준: `KrxRawStockStore` / KRX Open API ETF daily (`/etp/etf_bydd_trd`)
* ETF volume/trading_value는 ETF 원천 필드를 그대로 보존한다. 수정주가
  OHLC로 재구성하거나 trading_value를 계산하지 않는다.
* 두 종목 유형 모두 정확히 일치하는 원천 날짜 범위, 명시적 세션 투영,
  PIT 생명주기 의미를 사용한다. forward-fill/backfill과 사용 주체별
  우회는 금지한다.

ETF 원천 접근이 인증/활용 승인되지 않은 경우 Repository V2는 성공을
가장하지 않고 `DATA_UNAVAILABLE: RAW_MISSING`으로 fail-closed한다. 레거시
`data/raw/stocks` ETF 캐시는 이 계약의 원천 기준이 아니다.

종목 코드 범위
-------------
* 수정주가 API: 기존 `SIX_DIGIT_TICKER` 숫자 영역 유지
* 원천 API: `KRX_SHORT_CODE` 정규식 `^[0-9A-Z]{6}$`를 원천 보존 방식으로 지원
* 원천 suffix 제거, 대문자 변환, 숫자 강제 변환, 복구·보정은 하지 않는다.

API 스키마
---------
공식 필드 의미 토큰은 다음과 같이 고정한다.

```text
price_semantics = "ADJUSTED"
volume_semantics = "RAW"
trading_value_semantics = "RAW"
```

`get_daily(ticker, start, end)`
  index: 시간대 없음, 오름차순, unique DatetimeIndex
  columns: open, high, low, close, volume, trading_value
  OHLC는 `ADJUSTED` (수정주가), volume/trading_value는 `RAW` (원천).

`get_raw_daily(ticker, start, end)`
  columns: open, high, low, close, volume, trading_value, market_cap, listed_shares
  모든 값은 `RAW`이며 원천 KRX 종목코드 영역을 사용한다.

`get_daily_ancillary(ticker, start, end)`
  columns: volume, trading_value, market_cap, listed_shares
  OHLC를 포함하지 않는다.

`get_stock_snapshot(ticker, date)`
  해당 날짜의 정확히 1개 원천 행을 반환한다. 없으면 `DATA_UNAVAILABLE`이다.

결합 및 누락 데이터 의미
-------------------------
수정주가/원천 양쪽의 비어 있지 않은 거래 세션 집합은 정확히 같아야 한다.
한쪽 날짜를 조용히 제거하거나 forward-fill/bfill/0-fill하지 않는다.
거래 세션 집합 불일치는 REPOSITORY_V2_TRADING_SESSION_MISMATCH로 fail-closed한다.
양쪽이 모두 빈 결과인 요청 범위는 형식이 지정된 빈 일봉 데이터 프레임을 반환할 수 있다.
한쪽만 빈 결과이거나 종목 저장소가 없으면 DATA_UNAVAILABLE로 종료한다.

읽기 전용 및 호환성
--------------------------
Repository V2는 저장소를 생성자 주입받고 쓰기·갱신을 호출하지 않는다.
기존 MarketDataRepository와 tests/test_repository.py는 변경하지 않는다.
FIX01 당시에는 사용 코드 자동 전환이 0건이었고 Pattern A, FastCore, Julia,
RS, Stock Report 등의 전환을 END_TO_END_DATA_PARITY_V01 이후 별도 결정하도록
기록했다. 현재 운영 진입점의 Repository V2 연결은 후속 사용 코드
전환 완료 이후 반영되었으며, 과거 평가 진입점은
여전히 동결된 생성 함수 경계를 사용한다.

성능 한계
----------------------
`KrxRawStockStore.load_ticker`의 market/date partition scan 비용은
운영 점검 계측 정보로 관찰한다. 전수 구체화, 대량 캐시 생성,
저장소 재설계는 이 단계 범위에 포함하지 않는다.

검증 근거
-------------------
* `tests/test_repository_v2.py`: 원천 기준, 엄격한 결합, 영역, 누락, 변형,
  시장 간, 중복 날짜 및 네트워크 격리 검증
* `tests/test_market_data_repository_v02_validation.py`: FIX01의 표본 수,
  메타데이터 파생 범위, 빈 결과 비교, 예외 구조화 및 diff-check gate 검증
* `scripts/validate_market_data_repository_v02.py`: FIX01 검증 게이트와 임시
  `AdjustedPriceStore` 기반 제한적 실제 기준 점검
* `artifacts/data/market_data_repository/v02/`: contract, 계보, 점검,
  호환성, 성능 및 회귀 검증 증적

FIX01 실행 경계
---------------
* 검증기 실행 전에 원천·테스트·문서 변경을 고정하고, 제한된 회귀 검증을
  통과한 커밋 이후에만 실제 기준 점검을 수행한다.
* 실제 기준 점검의 수정주가 표본은 005930(2018-04-01..2018-06-30),
  000660(2026-07-01..2026-08-21), 068270(2026-07-01..2026-08-21) 세 건으로
  제한한다. 실제 비교 범위는 임시 저장소 메타데이터의 actual_date_min/max에서
  파생하며 날짜를 하드코딩하지 않는다.
* PyKRX adjusted=True 호출만 허용하고 KRX Open API, OpenDART, 대체 경로 및
  재시도는 0건이어야 한다. 외부 실패 시 재시도하지 않고 차단 사유로 기록한다.
* 임시 `AdjustedPriceStore`에만 수정주가 데이터를 저장하고 실제 기준 점검 종료 후
  경로가 제거되는지 확인한다. 운영 원천/수정주가 저장소와 기업행위 상태에는 쓰지
  않으며 전후 스냅샷이 동일해야 한다.
* 세 표본 모두 수정주가 OHLC, 원천 volume/trading_value, 부가 데이터 및 날짜 집합이
  정확히 일치해야 하며, Samsung listed_shares 의미와 영숫자 원천 종목코드 점검도
  별도 게이트로 확인한다.
* FIX01 단계에서는 운영 수정주가 저장소 적재와 사용 코드 전환을
  구현하지 않았다. 둘은 후속 전환의 전제조건으로 문서화되었으며, 현재
  운영 연결은 이 문서 이후의 후속 단계에서 별도로 반영되었다.

FIX02 원천 기준 및 점검 근거
-------------------------------------
* Repository V2의 원천 OHLC 관계는 동결된 KRX 원천 기준과 동일하게
  모든 OHLC 값이 양수인 행에만 적용한다. 가격이 0인 행은 원천 유효성
  의미를 보존하며 repository가 새 유효성 규칙을 추가하지 않는다.
* 원천 숫자 변환 가능 여부, NaN/inf, 음수 부가 데이터 및 volume/trading_value
  범위는 계속 fail-closed로 검증한다. 원천 값의 수리, 채움, 상한·하한 고정,
  조정, 반올림 또는 의미 변환은 수행하지 않는다.
* FIX02 검증기는 수정주가 데이터 제공자 조회, 임시 저장소 쓰기·재읽기,
  운영 원천 로드, Repository 결합, Samsung 의미 및 영숫자 원천 점검을 별도
  단계와 기록으로 남긴다.
* successful_provider_fetch_count, successful_temp_store_integrity_count,
  successful_composition_probe_count 및 usable_composition_sample_count는
  서로 독립적으로 계산한다. logical_fetch_count가 3보다 작다는 사실만으로
  PyKRX 외부 장애를 추론하지 않는다.
* 외부 PyKRX 차단 사유는 ADJUSTED_PROVIDER_FETCH 단계의 실제 exception 또는
  빈 결과·잘못된 제공자 출력이 증적에 존재할 때만 부여한다. 결합, 임시 저장소,
  원천 로드 실패는 각각 전용 차단 사유로 기록한다.
* 네트워크 0 오프라인 원천 점검은 005930, 000660, 068270의 원천 일치성과
  가격 0 행 수를 확인하고, Samsung listed_shares와 영숫자 원천 영역 점검은
  수정주가 실제 표본과 독립적으로 수행한다.

FIX03 거래 세션 투영
--------------------------------
* `KrxRawStockStore`의 모든 행은 `PHYSICAL_RAW_OBSERVATION`이다. 이 물리 관측치와
  수정주가 데이터 제공자가 반환하는 TRADING_SESSION 집합은 동일하다고
  가정하지 않는다.
* `get_raw_daily`, `get_daily_ancillary`, `get_stock_snapshot`은 물리 원천 행을
  전부 보존한다. 이 API들은 자리표시자를 제거하거나 거래일 집합을 투영하지
  않는다.
* `get_daily`에 한해서만 원천 전용 날짜를 명시적으로 투영한다. 투영 허용 조건식은
  NON_TRADING_PLACEHOLDER_V01이며 다음 여섯 조건을 모두 만족해야 한다.
  open == 0, high == 0, low == 0, close > 0, volume == 0,
  trading_value == 0.
* 위 predicate는
  ADJUSTED_PRICE_PROVIDER_PHANTOM_COMPATIBILITY 근거로만 사용한다.
  volume == 0 단독 조건, OHLC 전체 0 조건, trading_value 조건 일부, 또는
  임의의 inner join은 허용하지 않는다.
* 수정주가 전용 날짜는 BLOCKED_ADJUSTED_SESSION_WITHOUT_RAW_FACTS로,
  조건식을 만족하지 않는 원천 전용 날짜는
  BLOCKED_UNCLASSIFIED_RAW_ONLY_SESSION으로 fail-closed한다. 외부 관측치의
  불일치를 조용히 숨기지 않는다.
* 투영 결과의 날짜 집합은 수정주가 집합과 정확히 일치해야 하며, 제거된
  자리표시자 개수와 실제 날짜·필드·분류를 증적에 남긴다. 묵시적 inner 제거는
  항상 0이어야 한다.
* FIX03 오프라인 게이트는 네트워크 없이 세 표본의 후보를 검사한다. 005930의
  2018-04-01..2018-06-30 물리 원천 범위에서 후보가 정확히 3개가 아니면
  BLOCKED_PLACEHOLDER_SEMANTICS_UNPROVEN으로 실제 기준 점검을 실행하지 않는다.
  후보 날짜와 실제 원천 필드는 하드코딩하지 않고 저장소에서 산출한다.
* 실제 결합의 volume/trading_value 비교 대상은 투영된 원천이고,
  부가 데이터 비교 대상은 물리 원천이다. 성능 증적에는 원천 로드, 수정주가 로드,
  투영, 결합, 전체 경과 시간을 종목별로 기록하며 60초 이상은 warning이다.

FIX04 공통 날짜 의미 충돌
-----------------------------------
* 수정주가와 원천 양쪽에 같은 날짜가 있어도 원천 행이
  NON_TRADING_PLACEHOLDER_V01이면 두 authority의 session 의미가 충돌한다.
  이 상태는 정상 daily row로 합성하지 않고
  REPOSITORY_V2_SESSION_SEMANTIC_CONFLICT로 fail-closed한다.
* 동일 날짜의 자리표시자는 투영·제거 대상이 아니다. 근거에는
  shared_dates, shared_placeholder_conflict_dates,
  shared_placeholder_conflict_count 및 실제 행 세부 내용을 별도로 기록한다.
* 원천 전용 strict placeholder만 명시적 투영 대상이며,
  동일 날짜의 strict placeholder는 BLOCKED_SHARED_DATE_PLACEHOLDER_CONFLICT로
  분류한다. 동일 날짜의 정상 원천 행(volume=0 포함)은 자리표시자 조건식과
  일치하지 않으면 정상적으로 PASS한다.
* closure 근거의 accepted_placeholder_projection_count,
  rejected_raw_only_count, shared_placeholder_conflict_count는 composition
  레코드에서 검증기가 직접 집계하고 항상 숫자여야 한다.
  null 또는 집계 불일치는 BLOCKED_EVIDENCE_INCONSISTENCY다.
