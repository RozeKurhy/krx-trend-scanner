# 현재 수정주가 저장소 계약 (AdjustedPriceStore V02)

## 1. 문서 역할과 버전 의미

이 문서는 현재 운영 수정주가 저장소 계약의 대표 문서다. `AdjustedPriceStore V02`는
별도의 `AdjustedPriceStoreV02` 클래스명이 아니다. 현재
`AdjustedPriceStore` 클래스가 다음 V02 저장소·스키마 계약을 따른다는 뜻이다.

| 항목 | 현재 계약값 |
|---|---|
| 저장소 클래스 | `AdjustedPriceStore` |
| 스키마 | `ADJUSTED_PRICE_V02` |
| 저장소 계약 | `ADJUSTED_PRICE_STORE_V02` |
| 기본 저장 경로 | `data/market/adjusted/stocks/` |

## 2. 현재 수정주가 기준 원천

현재 기준 원천은 패키지가 소유하는 `AdjustedPriceSourceDescriptor`와
`CURRENT_SOURCE_DESCRIPTOR`에 고정되어 있다.

| 항목 | 현재 계약값 |
|---|---|
| 기준 식별자 | `NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1` |
| 원천 이름 | `NAVER_DIRECT_DATE_RANGE_ADJUSTED` |
| 원천 endpoint | `https://fchart.stock.naver.com/sise.nhn` |
| 요청 방식 | `requestType=1` |
| 시간 단위 | `day` |
| 조회 개수 | `5000` |
| 원천 의미 | `ADJUSTED_OHLC_ONLY` |
| 기준 유형 | `AUTHORITATIVE` |

`NaverDirectAdjustedPriceDataProvider`가 이 기준에 맞는 수정주가 OHLC를
제공한다. 과거 PyKRX `adjusted=True`는 V01 검증·레거시 비교 원천이며 현재
운영 기준 원천이 아니다. 실행 시점의 기준 객체는 파일이나 산출물에서 읽지
않고 패키지 계약에서 제공된다.

## 3. 저장 범위와 책임

종목별로 다음 두 파일을 하나의 저장 쌍으로 관리한다.

```text
data/market/adjusted/stocks/<ticker>.parquet
data/market/adjusted/stocks/<ticker>.meta.json
```

Parquet의 물리 컬럼 순서는 `date`, `ticker`, `open`, `high`, `low`, `close`다.
사용 코드가 읽는 결과는 시간대 없는 `DatetimeIndex`와 수정주가
`open/high/low/close`만 가진다.

`AdjustedPriceStore`가 저장하는 것은 수정주가 OHLC뿐이다. 다음 값은 저장하지
않는다.

- `volume`
- `trading_value`
- `market_cap`
- `listed_shares`

원천 일별 부가 데이터와 원천 OHLC는 `KrxRawStockStore`의 책임이다. 두 저장소는
`MarketDataRepositoryV2`에서 `(ticker, date)`와 거래 세션 의미를 확인한 뒤
결합한다.

## 4. 메타데이터 계약

각 `.meta.json`에는 저장소가 소유하는 계보·범위·무결성 정보가 들어간다.
V02에서 검증되는 핵심 필드는 다음과 같다.

```text
schema_version
store_version
ticker
source_authority_id
source_name
source_endpoint
source_request_type
source_semantics
authority_type
authority_closure_version
authority_closure_artifact_head
authority_closure_artifact_tree
authority_decision_sha256
requested_start
requested_end
actual_date_min
actual_date_max
row_count
ticker_count
generated_at
last_success_at
content_sha256
```

`schema_version`과 `store_version`은 각각
`ADJUSTED_PRICE_V02`와 `ADJUSTED_PRICE_STORE_V02`여야 한다.
`source_authority_id`부터 `authority_decision_sha256`까지는 현재
`CURRENT_SOURCE_DESCRIPTOR`와 정확히 일치해야 한다. `generated_at`과
`last_success_at`은 시간대가 있는 시각이어야 하며, `content_sha256`은 실제
Parquet 파일 바이트의 SHA-256이다.

요청 범위(`requested_start`, `requested_end`), 실제 데이터 범위
(`actual_date_min`, `actual_date_max`), 행 수(`row_count`), 종목 수
(`ticker_count`)도 저장 쌍과 일치해야 한다. 인증 정보나 인증 정보 표식은
메타데이터에 저장할 수 없다.

## 5. 읽기·쓰기 동작

현재 공개 동작은 다음과 같다.

| 메서드 | 의미 |
|---|---|
| `exists(ticker)` | Parquet와 메타데이터 저장 쌍이 모두 있는지 확인 |
| `load_metadata(ticker)` | 종목 메타데이터를 읽음 |
| `load_daily(ticker, start=None, end=None)` | 검증된 수정주가 OHLC를 범위로 읽음 |
| `load_daily_source(ticker, start=None, end=None)` | 원천 의미를 보존한 저장 행을 읽음 |
| `load_daily_analytic(ticker, start=None, end=None)` | 분석 가능한 OHLC 관계를 다시 확인해 읽음 |
| `is_current_authority_snapshot(ticker)` | 현재 V02 기준 저장 쌍인지 확인 |
| `save_full(ticker, frame, metadata_context=None, source_descriptor=None)` | 종목 전체 이력을 검증 후 교체 저장 |
| `latest_date(ticker)` | 저장된 최신 거래일을 반환 |
| `list_cached_tickers()` | 유효한 저장 쌍의 종목 목록을 반환 |

`save_full()`은 빈 데이터 프레임 저장을 거부하고, 입력 종목·날짜·OHLC 관계를 검증한다.
저장 전에 임시 Parquet를 기록하고 다시 읽어 물리 형식과 행 수를 확인한 뒤
메타데이터와 파일을 교체한다. 기존 유효 저장 쌍은 실패 시 복구할 수 있도록
백업하며, 임시 파일은 정리한다.

## 6. 검증과 fail-closed 원칙

읽을 때마다 다음을 확인한다.

- Parquet와 `.meta.json` 저장 쌍이 모두 존재하는가
- `schema_version`과 `store_version`이 서로 맞는가
- 현재 원천 descriptor와 기준 binding이 정확히 일치하는가
- 종목 코드, 요청 범위, 실제 범위, 행 수, 종목 수가 일치하는가
- `content_sha256`이 실제 Parquet 바이트와 일치하는가
- 날짜가 시간대 없는 오름차순·유일 인덱스인가
- OHLC가 숫자이고 허용된 가격 관계를 만족하는가
- 메타데이터 시각이 시간대 정보를 가지는가

Parquet 누락, 메타데이터 누락, 저장 쌍 불일치, 손상된 Parquet, 버전 불일치,
현재 기준 원천과의 불일치, 해시 불일치는 조용히 복구하거나 대체하지 않고
`MarketDataError`로 중단한다.

## 7. Repository V2와의 관계

```text
Naver 수정주가
    -> AdjustedPriceStore (ADJUSTED_PRICE_STORE_V02 계약)

KRX 원천 일별 데이터
    -> KrxRawStockStore

두 저장소
    -> MarketDataRepositoryV2
```

`AdjustedPriceStore`는 수정주가 OHLC만 제공하고, 거래량·거래대금·시가총액·
상장주식수는 `KrxRawStockStore`가 제공한다. `MarketDataRepositoryV2`는 두
저장소를 읽기 전용으로 주입받아 결합하며, 저장소에 쓰기나 갱신을 수행하지
않는다.

## 8. V01과의 관계

- [adjusted_price_store_v01.md](adjusted_price_store_v01.md)는 과거 V01 구현·검증 계약 기록이다.
- V01의 PyKRX `adjusted=True` 원천과 과거 검증 결과는 역사 기록으로 보존한다.
- 현재 운영 수정주가 저장소 계약의 기준 문서는 이 V02 문서다.
