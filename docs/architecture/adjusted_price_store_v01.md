adjusted_price_store_v01.md

======================================================================
AdjustedPriceStore v01
======================================================================

상태
----------------------------------------------------------------------

이 문서는 frozen Production Data Architecture v01의 adjusted OHLC authority를
실제 provider/store primitive로 구현한 계약이다. 최종 상태는
`READY_FOR_ARCHITECT_ADJUSTED_PRICE_STORE_V01_FIX01_REVIEW`이며, Architect 승인 전에는
`ADJUSTED_PRICE_STORE_V01 = CLOSED`로 선언하지 않는다.

이번 단계의 범위
----------------------------------------------------------------------

- `AdjustedPriceDataProvider`가 PyKRX `adjusted=True` OHLC만 조회한다.
- `AdjustedPriceStore`가 ticker 단위 mutable full replacement를 지원한다.
- Parquet physical schema와 metadata sidecar, SHA-256 pair integrity를 보존한다.
- Store-owned metadata provenance와 caller request context를 분리한다.
- 새 provider와 기존 legacy adjusted OHLC의 직접 parity evidence를 별도 기록한다.
- 기존 legacy composite cache와 production consumer는 전환하지 않는다.
- 다음 dirty-refresh phase가 사용할 fail-closed storage primitive를 고정한다.

이번 단계에서 하지 않는 것
----------------------------------------------------------------------

- `adjusted=False`, KRX Open API, OpenDART 호출
- `PyKrxDataProvider`, `MarketDataRepository`, `ParquetCache` 동작 변경
- `data/raw/stocks/` migration 또는 overwrite
- KRXRawStockStore, corporate-action detector, dirty ticker 자동 탐지
- 전체 종목 backfill, Pattern A/FastCore/Julia/Stock Report consumer 전환
- custom adjustment engine

1. AdjustedPriceDataProvider
----------------------------------------------------------------------

source authority:

`pykrx.stock.get_market_ohlcv_by_date(start, end, ticker, adjusted=True)`

한 logical fetch는 adjusted=True 호출 1회만 수행한다. adjusted=False 호출,
기존 `PyKrxDataProvider(adjusted=True)` 재사용, KRX credential 읽기와 `.env` 로드는
없다. provider 반환 schema는 정확히 다음 4개 컬럼과 timezone-naive
`DatetimeIndex`다.

---------------------------------------------------------------------
| 컬럼                         | 의미                                  |
---------------------------------------------------------------------
| open, high, low, close       | adjusted OHLC, float64               |
---------------------------------------------------------------------

PyKRX 응답의 `거래량`은 phantom holiday 판정을 위해 transient하게만 사용한다.
`volume`, `trading_value`, `market_cap`, `listed_shares`는 provider 반환 및 store
저장 모두 금지한다. `open=high=low=volume=0`, `close>0`인 row는 제거한다.

기존 adjusted path와 같은 1원 correction만 provider 단계에서 수행한다.
`high < max(open, close)` 또는 `low > min(open, close)`의 위반 폭이 1원 이내일
때만 정상 관계값으로 보정한다. 2원 이상 위반은 자동 repair하지 않고 fail closed한다.

2. Dedicated adjusted validation
----------------------------------------------------------------------

`validate_adjusted_ohlc()`는 기존 `validate_ohlcv()`를 재사용하지 않는다.
정확한 OHLC schema, `DatetimeIndex`, 오름차순/unique date, NaN/음수 부재와
high/low 가격 관계를 검사한다. empty frame은 provider에서 반환할 수 있지만,
store의 `save_full()`은 empty overwrite를 거부한다.

3. AdjustedPriceStore
----------------------------------------------------------------------

기본 경로:

`data/market/adjusted/stocks/<ticker>.parquet`

`data/raw/stocks/`는 `LEGACY_COMPOSITE_STOCK_CACHE`이므로 읽기 parity 대상일 뿐,
이번 phase에서 수정·덮어쓰기·이동·삭제하지 않는다.

공개 API:

`exists(ticker)`

`load_daily(ticker, start=None, end=None)`

`load_metadata(ticker)`

`save_full(ticker, frame, metadata_context=None)`

`latest_date(ticker)`

`list_cached_tickers()`

Parquet physical schema는 순서까지 다음과 같다.

---------------------------------------------------------------------
| date | ticker | open | high | low | close                          |
---------------------------------------------------------------------

`date`와 `ticker`를 파일 안에 저장해 filename-only identity를 피한다. consumer가
읽는 frame은 `DatetimeIndex`와 `open/high/low/close`만 가진다. Store는 adjusted
OHLC만 소유하며 raw OHLC, ancillary, master, asset_type, membership, flow, RS는
소유하지 않는다.

4. Mutable history와 atomic replacement
----------------------------------------------------------------------

Adjusted history는 향후 corporate action에 의해 과거 값이 변할 수 있으므로
append-only가 아니다. `save_full()`은 ticker 전체 snapshot을 다음 순서로 처리한다.

1) 입력 schema/가격 관계/ticker/date 검증
2) 임시 Parquet 기록
3) 임시 Parquet read-back 및 physical schema 검증
4) 임시 파일의 최종 byte SHA-256 계산
5) 임시 metadata sidecar 기록 및 재검증
6) 최종 parquet/meta pair 교체

중간 실패 시 임시 파일을 정리하고 기존 valid pair를 가능한 한 보존한다.
Parquet와 metadata는 단일 filesystem transaction이 아니므로 load 때마다
`metadata.content_sha256`과 실제 parquet byte hash를 비교한다. hash mismatch,
metadata 누락, schema/version mismatch, ticker mismatch, corrupt parquet는
조용히 복구하지 않고 fail closed한다.

5. Metadata contract
----------------------------------------------------------------------

sidecar:

`data/market/adjusted/stocks/<ticker>.meta.json`

최소 필드:

`schema_version`, `store_version`, `ticker`, `source_name`, `source_endpoint`,
`source_semantics`, `authority_type`, `requested_start`, `requested_end`,
`actual_date_min`, `actual_date_max`, `row_count`, `ticker_count`, `generated_at`,
`last_success_at`, `content_sha256`

고정 값:

- `schema_version = ADJUSTED_PRICE_V01`
- `store_version = ADJUSTED_PRICE_STORE_V01`
- `source_name = PYKRX_ADJUSTED_PRICE`
- `source_endpoint = pykrx.stock.get_market_ohlcv_by_date(adjusted=True)`
- `source_semantics = ADJUSTED_OHLC_ONLY`
- `authority_type = AUTHORITATIVE`
- `ticker_count = 1`
- `content_sha256 = 최종 parquet byte의 SHA-256`

`generated_at`, `last_success_at`은 timezone-aware ISO-8601이어야 한다. KRX key,
KRX_ID, KRX_PW 등 credential은 metadata에 저장하지 않는다. `metadata_context`는
allowlist이며 caller가 지정할 수 있는 필드는 `requested_start`, `requested_end`뿐이다.
schema/store version, ticker, source provenance, actual bounds, row/ticker count,
timestamps, content hash는 Store-owned reserved field라 override 시 fail closed한다.
`source_endpoint`도 `pykrx.stock.get_market_ohlcv_by_date(adjusted=True)`와 완전
일치해야 한다. filename ticker, metadata ticker, parquet ticker column은 모두 동일해야 한다.

6. Legacy parity와 validation
----------------------------------------------------------------------

offline validator는 기존 `data/raw/stocks/`에서 OHLC만 추출해 임시 Store에
round-trip하고 date/row/OHLC parity를 비교한다. 이는 `STORE_ROUND_TRIP` evidence다.
별도로 live smoke에서 새 `AdjustedPriceDataProvider` output과 동일 요청 범위의
legacy adjusted OHLC를 직접 비교한다. 값과 날짜는 공통 거래일 intersection에서
검증하고, frozen legacy cache에만 없는 provider-only 날짜와 legacy-only 날짜는
coverage evidence로 별도 기록한다. volume/trading_value는 parity 비교 대상이 아니다.
validation parquet는 artifacts나 git에 commit하지 않는다.

live smoke 모드에서만 다음 3개 logical fetch를 수행한다.

---------------------------------------------------------------------
| ticker | window                                      |
---------------------------------------------------------------------
| 005930 | 2018 split 전후를 포함하는 2018-04-01~06-30 |
| 000660 | 2026-07-01~08-21                            |
| 068270 | 2026-07-01~08-21                            |
---------------------------------------------------------------------

live smoke도 adjusted=True만 허용하며, 결과는 target production path가 아닌
temporary directory에 저장한다. 외부 PyKRX 장애나 empty/error는 성공으로
위장하지 않고 `BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE`로 기록한다.

provider parity artifact는 `provider_legacy_parity.csv`이며 ticker, requested bounds,
provider/legacy/common row 수, provider-only/legacy-only coverage, date mismatch,
open/high/low/close mismatch를 분리한다. Store round-trip artifact
`offline_parity.csv`와 의미를 혼동하지 않는다.

7. Production boundary
----------------------------------------------------------------------

이번 phase에서 MarketDataRepository는 AdjustedPriceStore를 자동 사용하지 않는다.
기존 PyKrxDataProvider, ParquetCache, repository 및 분석/report consumer의
behavioral diff는 0이어야 한다. 향후 `MarketDataRepositoryV2`가
`AdjustedPriceStore + KRXRawStockStore`를 `(ticker, date)`로 join한다.

8. Evidence artifacts
----------------------------------------------------------------------

`artifacts/data/adjusted_price_store/v01/`에 metrics/provenance만 기록한다.

- `adjusted_price_store_v01_summary.json`
- `adjusted_price_store_v01_manifest.json`
- `provider_contract.json`
- `store_contract.json`
- `offline_parity.csv`
- `provider_legacy_parity.csv`
- `live_smoke_summary.json`
- `write_integrity_summary.json`
- `adjusted_price_store_recommendation.md`

validation parquet, sample stock cache, large historical price file는 commit하지
않는다. artifact 내부 `end_head`는 null로 유지하고 실제 END SHA는 completion
report에만 기록한다.

9. Next phase
----------------------------------------------------------------------

이번 phase의 recommendation이 통과하면 다음 단계는
`CORPORATE_ACTION_DIRTY_REFRESH_V01`이다. dirty ticker를 언제 선택할지는 다음
phase의 책임이며, 이 Store는 ticker full-replacement primitive만 제공한다.
