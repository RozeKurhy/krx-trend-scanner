# 수정주가 저장소 (AdjustedPriceStore v01)

> 이 문서는 과거 V01 수정주가 저장소의 구현·검증 계약 기록이다.
> 현재 운영 계약은 [../adjusted_price_store_v02.md](../adjusted_price_store_v02.md)를 따른다.
> 아래의 V01 수치, 기술 토큰, 검증 결과와 역사적 실행 기록은 삭제하지 않는다.

상태
----------------------------------------------------------------------

이 문서는 동결된 운영 데이터 아키텍처 v01의 수정주가 OHLC 기준을
실제 데이터 제공자/저장소 기본 요소로 구현한 계약이다. 최종 상태는
`READY_FOR_ARCHITECT_ADJUSTED_PRICE_STORE_V01_FIX01_REVIEW`이며, Architect 승인 전에는
`ADJUSTED_PRICE_STORE_V01 = CLOSED`로 선언하지 않는다.

현재 기준 안내
----------------------------------------------------------------------

위 상태와 PyKRX `adjusted=True` 원천 표기는 V01 구현·검증 단계의 과거
기록이다. 현재 수정주가 OHLC 기준 원천과 저장소 계약은
`../adjusted_price_store_v02.md`에 정의된 패키지 소유
`NaverDirectAdjustedPriceDataProvider`의 Naver direct date-range
(`requestType=1`)과 `AdjustedPriceStore`의 V02 계약이다.
따라서 아래 V01 데이터 제공자/저장소 세부사항은 당시 기본 요소와 일치성(parity) 검증 근거를
설명하는 기록으로 읽고, 현재 운영 원천으로 해석하지 않는다.

이번 단계의 범위
----------------------------------------------------------------------

- `AdjustedPriceDataProvider`가 PyKRX `adjusted=True` OHLC만 조회한다.
- `AdjustedPriceStore`가 종목코드 단위 변경 가능한 전체 교체를 지원한다.
- Parquet 물리 스키마와 메타데이터 보조 파일, SHA-256 파일 쌍 무결성을 보존한다.
- 저장소 소유 메타데이터 계보와 호출자 요청 문맥을 분리한다.
- 새 데이터 제공자와 기존 레거시 수정주가 OHLC의 직접 일치성 검증 근거를 별도 기록한다.
- 기존 레거시 composite cache와 운영 사용 코드는 전환하지 않는다.
- 다음 dirty-refresh 단계가 사용할 fail-closed 저장 기본 요소를 고정한다.

이번 단계에서 하지 않는 것
----------------------------------------------------------------------

- `adjusted=False`, KRX Open API, OpenDART 호출
- `PyKrxDataProvider`, `MarketDataRepository`, `ParquetCache` 동작 변경
- `data/raw/stocks/` 전환 또는 덮어쓰기
- KRXRawStockStore, 기업행위 감지기, dirty 종목코드 자동 탐지
- 전체 종목 백필, Pattern A/FastCore/Julia/Stock Report 사용 코드 전환
- custom adjustment engine

1. 수정주가 데이터 제공자 계약 (AdjustedPriceDataProvider)
----------------------------------------------------------------------

기준 원천:

`pykrx.stock.get_market_ohlcv_by_date(start, end, ticker, adjusted=True)`

하나의 논리적 조회는 adjusted=True 호출 1회만 수행한다. adjusted=False 호출,
기존 `PyKrxDataProvider(adjusted=True)` 재사용, KRX 인증 정보 읽기와 `.env` 로드는
없다. 데이터 제공자 반환 스키마는 정확히 다음 4개 컬럼과 시간대 없는
`DatetimeIndex`다.

| 컬럼 | 의미 |
|---|---|
| `open`, `high`, `low`, `close` | 수정주가 OHLC, `float64` |

PyKRX 응답의 `거래량`은 휴장일 허위 행 판정을 위해 일시적으로만 사용한다.
`volume`, `trading_value`, `market_cap`, `listed_shares`는 제공자 반환 및 저장소
저장 모두 금지한다. `open=high=low=volume=0`, `close>0`인 row는 제거한다.

기존 수정주가 경로와 같은 1원 보정만 데이터 제공자 단계에서 수행한다.
`high < max(open, close)` 또는 `low > min(open, close)`의 위반 폭이 1원 이내일
때만 정상 관계값으로 보정한다. 2원 이상 위반은 자동 수리하지 않고 fail closed한다.

2. 전용 수정주가 검증
----------------------------------------------------------------------

`validate_adjusted_ohlc()`는 기존 `validate_ohlcv()`를 재사용하지 않는다.
정확한 OHLC 스키마, `DatetimeIndex`, 오름차순·고유 날짜, NaN/음수 부재와
high/low 가격 관계를 검사한다. 빈 데이터 프레임은 데이터 제공자에서 반환할 수 있지만,
저장소의 `save_full()`은 빈 데이터 덮어쓰기를 거부한다.

3. AdjustedPriceStore
----------------------------------------------------------------------

기본 경로:

`data/market/adjusted/stocks/<ticker>.parquet`

`data/raw/stocks/`는 `LEGACY_COMPOSITE_STOCK_CACHE`이므로 읽기 일치성 검증 대상일 뿐,
이번 단계에서 수정·덮어쓰기·이동·삭제하지 않는다.

공개 API:

`exists(ticker)`

`load_daily(ticker, start=None, end=None)`

`load_metadata(ticker)`

`save_full(ticker, frame, metadata_context=None)`

`latest_date(ticker)`

`list_cached_tickers()`

Parquet 물리 스키마는 순서까지 다음과 같다.

| 구분 | 컬럼 순서 |
|---|---|
| 물리 컬럼 | `date`, `ticker`, `open`, `high`, `low`, `close` |

`date`와 `ticker`를 파일 안에 저장해 파일명만으로 정체성을 판단하는 방식을 피한다. 사용 코드가
읽는 frame은 `DatetimeIndex`와 `open/high/low/close`만 가진다. 저장소는 수정주가
OHLC만 소유하며 원천 OHLC, 부가 데이터, master, asset_type, membership, flow, RS는
소유하지 않는다.

4. 변경 가능한 이력과 원자적 교체
----------------------------------------------------------------------

수정주가 이력은 향후 기업행위(corporate action)에 의해 과거 값이 변할 수 있으므로
append-only가 아니다. `save_full()`은 종목 전체 스냅샷을 다음 순서로 처리한다.

1) 입력 스키마/가격 관계/종목코드/날짜 검증
2) 임시 Parquet 기록
3) 임시 Parquet 재읽기 및 물리 스키마 검증
4) 임시 파일의 최종 byte SHA-256 계산
5) 임시 메타데이터 보조 파일 기록 및 재검증
6) 최종 Parquet/메타데이터 쌍 교체

중간 실패 시 임시 파일을 정리하고 기존 유효 pair를 가능한 한 보존한다.
Parquet와 메타데이터는 단일 파일 시스템 트랜잭션이 아니므로 읽을 때마다
`metadata.content_sha256`과 실제 Parquet 바이트 해시를 비교한다. 해시 불일치,
메타데이터 누락, 스키마/버전 불일치, 종목코드 불일치, 손상된 Parquet는
조용히 복구하지 않고 fail closed한다.

5. 메타데이터 계약
----------------------------------------------------------------------

메타데이터 보조 파일(sidecar):

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

`generated_at`, `last_success_at`은 시간대가 포함된 ISO-8601이어야 한다. KRX key,
KRX_ID, KRX_PW 등 인증 정보는 메타데이터에 저장하지 않는다. `metadata_context`는
허용 목록이며 호출자가 지정할 수 있는 필드는 `requested_start`, `requested_end`뿐이다.
스키마/저장소 버전, 종목코드, 원천 계보, 실제 범위, 행/종목 수, 시각,
콘텐츠 해시는 저장소 소유 예약 필드이므로 덮어쓰기를 시도하면 fail closed한다.
`source_endpoint`도 `pykrx.stock.get_market_ohlcv_by_date(adjusted=True)`와 완전
일치해야 한다. filename ticker, metadata ticker, parquet ticker column은 모두 동일해야 한다.

6. 레거시 일치성 검증과 검증 근거
----------------------------------------------------------------------

오프라인 검증기는 기존 `data/raw/stocks/`에서 OHLC만 추출해 임시 저장소에
왕복 저장하고 날짜/행/OHLC 일치성을 비교한다. 이는 `STORE_ROUND_TRIP` 근거다.
별도로 실제 호출 간단 검증에서 새 `AdjustedPriceDataProvider` 결과와 동일 요청 범위의
레거시 수정주가 OHLC를 직접 비교한다. 값과 날짜는 공통 거래일 교집합에서
검증하고, 동결된 레거시 캐시에만 없는 제공자 전용 날짜와 레거시 전용 날짜는
범위 근거로 별도 기록한다. volume/trading_value는 일치성 비교 대상이 아니다.
검증용 Parquet는 산출물이나 git에 커밋하지 않는다.

실제 호출 간단 검증 모드에서만 다음 3개 논리적 조회를 수행한다.

| 종목 | 조회 구간 |
|---|---|
| `005930` | 2018 split 전후를 포함하는 2018-04-01~06-30 |
| `000660` | 2026-07-01~08-21 |
| `068270` | 2026-07-01~08-21 |

실제 호출 간단 검증도 adjusted=True만 허용하며, 결과는 운영 대상 경로가 아닌
임시 디렉터리에 저장한다. 외부 PyKRX 장애나 빈 결과/오류는 성공으로
위장하지 않고 `BLOCKED_EXTERNAL_PYKRX_UNAVAILABLE`로 기록한다.

제공자 일치성 산출물은 `provider_legacy_parity.csv`이며 종목코드, 요청 범위,
제공자/레거시/공통 행 수, 제공자 전용·레거시 전용 범위, 날짜 불일치,
open/high/low/close 불일치를 분리한다. 저장소 왕복 산출물
`offline_parity.csv`와 의미를 혼동하지 않는다.

7. 운영 경계
----------------------------------------------------------------------

이번 단계에서 MarketDataRepository는 AdjustedPriceStore를 자동 사용하지 않는다.
기존 PyKrxDataProvider, ParquetCache, repository 및 분석/리포트 사용 코드의
동작 차이는 0이어야 한다. 향후 `MarketDataRepositoryV2`가
`AdjustedPriceStore + KRXRawStockStore`를 `(ticker, date)`로 결합한다.

8. 검증 산출물
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

검증용 Parquet, 표본 종목 캐시, 대용량 과거 가격 파일은 커밋하지
않는다. 산출물 내부 `end_head`는 null로 유지하고 실제 END SHA는 완료
보고서에만 기록한다.

9. 다음 단계
----------------------------------------------------------------------

이번 단계의 권고가 통과하면 다음 단계는
`CORPORATE_ACTION_DIRTY_REFRESH_V01`이다. dirty ticker를 언제 선택할지는 다음
단계의 책임이며, 이 저장소는 종목 전체 교체 기본 기능만 제공한다.
