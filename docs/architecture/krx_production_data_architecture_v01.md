krx_production_data_architecture_v01.md

# KRX 운영 데이터 아키텍처 (KRX Production Data Architecture v01)

## 1. 문서 역할

이 문서는 현재 KRX Trend Scanner의 운영 데이터 아키텍처 전체 기준이다.
현재 운영 구조와 실제 사용 경로를 앞부분에 두고, 세부 저장소·원천·PIT
계약은 하위 문서로 연결한다. FIX03 당시의 설계·전환·검증 상태는 문서 뒤쪽
`FIX03 당시 설계·전환 역사 기록`에 보존하며 현재 상태로 해석하지 않는다.

## 2. 현재 운영 아키텍처 한눈에 보기

현재 데이터 흐름은 다음과 같다.

```text
Naver 직접 날짜 범위 조회 수정주가
    -> AdjustedPriceStore (ADJUSTED_PRICE_STORE_V02 계약)

KRX Open API 원천 일별 데이터
    -> KrxRawStockStore

AdjustedPriceStore (ADJUSTED_PRICE_STORE_V02 계약) + KrxRawStockStore
    -> MarketDataRepositoryV2
    -> 종목 보고서 / Pattern A 운영 사용 코드

시장·업종 지수
    -> data/market/index/v01의 IndexStore(MARKET_INDEX)

종목 메타데이터·자산 유형
    -> InstrumentMetadataResolver
    -> data/reference/krx_instrument_metadata.parquet

업종 구성 종목
    -> SectorMembershipStore

펀더멘털
    -> OpenDART
```

종목 보고서와 Pattern A 운영 스캐너는 `build_production_repository_v2`를
통해 현재 Repository V2 운영 연결을 사용한다. Pattern A의 시장 대표지수
기본 경로는 `IndexStore(MARKET_INDEX)`이며 과거 일치성 산출물은 비교 증적으로만
남는다. `InstrumentMetadataResolver`의 운영 실행 시점은 로컬 산출물만 읽고
네트워크를 호출하지 않는다.

## 3. 현재 데이터 기준

현재 운영에서 사용하는 원천과 저장·사용 경로는 다음과 같다. 과거 목표 상태는
이 표에 섞지 않는다.

| 데이터 의미 | 현재 실제 기준 원천 | 저장·사용 경로 |
|---|---|---|
| 수정주가 OHLC | Naver 직접 날짜 범위 조회 (`requestType=1`), `ADJUSTED` | `AdjustedPriceStore` (`ADJUSTED_PRICE_STORE_V02`) → `MarketDataRepositoryV2` |
| 원천 OHLC | KRX Open API `/sto/stk_bydd_trd`, `/sto/ksq_bydd_trd`, `RAW` | `KrxRawStockStore` → `MarketDataRepositoryV2` |
| 거래량·거래대금 | KRX Open API 원천 일별 데이터, `RAW` | `KrxRawStockStore`의 원천 부가 데이터 |
| 시가총액·상장주식수 | KRX Open API 원천 일별 데이터 | `KrxRawStockStore`의 원천 부가 데이터 및 스냅샷 계약 |
| 종목 메타데이터·자산 유형 | KRX MDC 공식 원천으로 생성된 로컬 PIT 산출물 | `InstrumentMetadataResolver` |
| 시장 대표지수 | `data/market/index/v01`의 현재 `IndexStore(MARKET_INDEX)` 경로 | Pattern A 운영 스캐너 |
| KRX 기본 업종지수 | KRX 기본 업종지수 원천 | `IndexStore`의 `NATIVE_SECTOR_INDEX` 계열 |
| 업종 구성 종목 | KRX Data Marketplace 공식 구성 종목 CSV의 승인된 정확한 기준일 스냅샷 | `SectorMembershipStore` |
| 펀더멘털 | OpenDART 보고 사실 | 펀더멘털 계층 |
| 외국인·기관 수급 | PyKRX Foreign Flow 원천을 사용하는 지표 계산 경로 | 스캐너·종목 보고서 지표 |

수정주가와 원천 데이터의 의미는 하나의 기준으로 합치지 않는다. `AdjustedPriceStore`
는 OHLC만 소유하고 volume, trading_value, market_cap, listed_shares를 저장하지
않는다. 공식 의미 토큰은 `ADJUSTED`와 `RAW`를 그대로 보존한다.

## 4. 현재 핵심 저장소와 역할

| 구성요소 | 현재 운영 역할 |
|---|---|
| `AdjustedPriceStore` (`ADJUSTED_PRICE_STORE_V02`) | Naver 직접 날짜 범위 조회 기반 수정주가 OHLC 저장소 |
| `KrxRawStockStore` | KRX 원천 OHLC와 거래량·거래대금·시가총액·상장주식수 보관 |
| `MarketDataRepositoryV2` | 두 저장소를 `(ticker, date)`로 결합하고 세션 불일치 시 fail-closed |
| `IndexStore` | 시장·기본 업종·분류 체계 지수를 논리 분류군과 표준 key로 제공 |
| `InstrumentMetadataResolver` | 종목 메타데이터와 PIT 자산 유형을 로컬 산출물에서 결정 |
| `SectorMembershipStore` | 기준일별 업종 구성 종목을 PIT 스냅샷으로 제공 |

`FundamentalsStore`와 `CorporateActionStateStore`의 세부 계약은 기존 권위
문서에 남기며, 이 문서에서는 현재 운영 흐름에 필요한 역할만 요약한다.

## 5. 현재 운영 데이터 흐름

1. 수정주가 원천은 `NaverDirectAdjustedPriceDataProvider`가
   `AdjustedPriceStore` (`ADJUSTED_PRICE_STORE_V02`)에 기록한다.
2. KRX 원천 일별 데이터는 `KrxRawStockStore`에서 원천 의미를 유지한다.
3. `build_production_repository_v2`가 두 저장소를 `MarketDataRepositoryV2`로
   연결하고 종목 보고서와 Pattern A 운영 사용 코드에 제공한다.
4. 과거 평가·검증용 `build_repository_v2`가 별도 동결 경계로 유지되는 경우에는
   운영용 factory와 혼동하지 않는다.
5. Pattern A 운영 스캐너는 `data/market/index/v01`의
   `IndexStore(MARKET_INDEX)`를 시장 대표지수 경로로 사용한다.
6. 업종 구성 종목은 승인된 정확한 기준일 `SectorMembershipStore` 스냅샷을
   사용하며 이전 스냅샷의 값 이월이나 이후 스냅샷의 소급 적용을 하지 않는다.
7. 종목 보고서의 메타데이터 판단은 `InstrumentMetadataResolver`의 로컬 PIT
   산출물을 사용하고, 펀더멘털은 OpenDART 계층에서 별도로 제공한다.

## 6. 현재 PIT·계보·fail-closed 핵심 규칙

- `as_of` 또는 `effective_date`보다 미래인 메타데이터·가격·보고 사실을 사용하지 않는다.
- 수정주가 OHLC는 `ADJUSTED`, 원천 부가 데이터는 `RAW`로 의미를 분리한다.
- Repository 결합은 `(ticker, date)`와 거래 세션 의미를 함께 확인하며, 세션 불일치·원천 누락·명시되지 않은 자리표시자는 fail-closed한다.
- `InstrumentMetadataResolver`는 요청 시점 이하의 가장 최신 PIT 행을 고르고, 신뢰 규칙을 충족하지 못하면 자산 유형을 fail-closed한다.
- 과거 종목 집합은 [생존편향 방지 분모 동결 계약](survivorship_safe_denominator_freeze_v01.md)의 Population Universe(전체 모집단)와 PIT Common Denominator(시점별 보통주 분모)를 구분해 사용한다.
- 운영 Store/Repository는 `artifacts/`를 실행 시점 원천으로 사용하지 않는다.
- 원천·요청 매개변수·정적 매핑·파생값·상태·계보 메타데이터를 계보 정보에서 구분한다.

세션 투영, placeholder 분류, 메타데이터 신뢰, 분모 동결의 세부 규칙은
[시장데이터 Repository 계약](market_data_repository_v02.md),
[종목 메타데이터 권위](instrument_metadata_authority.md),
[현재 수정주가 저장소 계약](adjusted_price_store_v02.md) 및
[생존편향 방지 분모 동결](survivorship_safe_denominator_freeze_v01.md)을 따른다.

## 7. 레거시 경계

- [data_layer.md](data_layer.md)는 과거 공용 Data Layer v0.1 기록이며 현재 운영 데이터 레이어가 아니다.
- `data/raw/stocks/<ticker>.parquet`는 PyKRX 수정주가와 원천 부가 데이터가 섞인 `LEGACY_COMPOSITE_STOCK_CACHE`다. 이를 `KRXRawStockStore`로 부르지 않는다.
- 과거 PyKRX 수정주가 경로와 `ADJUSTED_PRICE_V01` 캐시는 레거시 호환 또는 검증 비교기로만 읽을 수 있으며 현재 수정주가 기준이 아니다.
- 일부 기존 분석/보고서 흐름의 `artifacts/` 소비는 `LEGACY_RUNTIME_DEPENDENCIES`에 전환 기술 부채로 추적한다. 이는 현재 운영 Store/Repository의 권위가 아니다.

## 8. 세부 계약 문서 연결

- [시장데이터 Repository V2](market_data_repository_v02.md)
- [현재 수정주가 저장소 V02 계약](adjusted_price_store_v02.md)
- [종목 메타데이터 권위](instrument_metadata_authority.md)
- [생존편향 방지 분모 동결](survivorship_safe_denominator_freeze_v01.md)
- [KRX 지수 전환](krx_index_migration_v01.md)
- [Sector RS KRX 전환](sector_rs_krx_migration_v01.md)
- [과거 시점 스냅샷](historical_snapshot.md)

## 9. 현재 문서의 해석 경계

이 문서 앞부분의 1~8절만으로 현재 운영 데이터 흐름과 권위 경계를 파악할 수
있어야 한다. 아래 10절 이후는 FIX03 당시의 설계·전환·검증을 보존하기 위한
역사 기록이며, 현재 운영 상태·목표 상태·후속 작업 상태를 새로 선언하는
부분이 아니다.

## 10. FIX03 당시 설계·전환 역사 기록

이하의 번호와 표현은 FIX03 당시 원문을 보존한 역사 기록이다. 현재 구조와
섞어 읽지 않으며, 공식 token·수치·당시 판단은 변경하지 않는다.

### 10.1 FIX03 당시 상태
----------------------------------------------------------------------

이 문서는 운영 데이터 기준, 논리 저장소, Repository V2 대상,
PIT/계보, 데이터 상태 계약을 고정한다. 이번 단계의 최종 상태는
`READY_FOR_ARCHITECT_KRX_PRODUCTION_DATA_ARCHITECTURE_V01_FIX03_REVIEW`이며,
Architect 승인 전에는 `CLOSED`로 선언하지 않는다.

### 10.2 FIX03 당시 구현 경계 기록
----------------------------------------------------------------------

위 상태와 아래 FIX03 범위·전환 표는 해당 아키텍처 단계의 스냅샷이다.
현재 수정주가 OHLC 기준 원천은 Naver 직접 날짜 범위 조회 (`requestType=1`)와
`AdjustedPriceStore`의 V02 계약이며, 운영 종목 보고서와 Pattern A 스캐너는
`build_production_repository_v2`를 통해 Repository V2 운영 연결을 사용한다.
Pattern A 운영 스캐너의 시장 지수 기본 경로는
`data/market/index/v01`의 `IndexStore(MARKET_INDEX)`이며, 과거 일치성 산출물은
비교 증적으로만 유지된다. 따라서 아래의 “후속 단계”, “개념 대상”, 레거시
사용 코드 문구는 이 문서가 작성된 당시의 상태로 읽는다.

### 10.3 FIX03 당시 작업 범위
----------------------------------------------------------------------

- 기준과 원천 의미를 기계 판독 가능한 계약으로 고정한다.
- 원천/수정주가/마스터/지수/구성 종목/펀더멘털/dirty-state 저장소 역할을 분리한다.
- 기존 `data/raw/stocks/<ticker>.parquet`는 `LEGACY_COMPOSITE_STOCK_CACHE`로 분류한다.
- Repository V2의 수정주가 OHLC + 원천 부가 데이터 결합 의미를 고정한다.
- 모든 시간 인식 계층의 PIT/as_of 및 계보 필드를 정의한다.
- Operations Dashboard가 소비할 상태 계약을 정의한다.
- 오프라인 정적 검증기와 계약 테스트로 계약을 검증한다.
- 실제 원천 스키마와 request/mapping-derived 계보를 구분한다.
- StockMaster 원천 사실, 표준 시장, 종목 분류의 경계를 구분한다.
- KRX `IDX_CLSS` 원천 분류와 논리적 지수 분류군을 분리한다.
- 현재 레거시 실행 시점의 `artifacts/` 소비를 기술 부채 목록으로 추적한다.

### 10.4 FIX03 당시 제외 범위
----------------------------------------------------------------------

- KRX Open API, PyKRX, OpenDART 네트워크 호출
- 운영 조회 데이터 제공자 전환
- 과거 데이터 백필 또는 대량 parquet 생성
- 기존 종목 캐시 재작성/이동/삭제/일괄 이름 변경
- 사용자 정의 기업행위 조정 엔진
- 시장 지수 원천 전환
- 이미 승인된 정확한 기준일 `SectorMembershipStore` 스냅샷 변경/재생성
- Pattern A, FastCore, Julia, RS formula 변경
- HTML/dashboard UI 구현

### 10.5 FIX03 당시 Authority 매트릭스
----------------------------------------------------------------------

Machine-readable 원본은
`src/trend_scanner/data/source_contracts.py`의 `AUTHORITY_FIELDS`다.

| 데이터 의미 | 당시 기준·목표 |
|---|---|
| 원천 OHLC | KRX Open API `/sto/stk_bydd_trd`, `/sto/ksq_bydd_trd` |
| 거래량·거래대금 | KRX Open API 원천 |
| 시가총액·상장주식수 | KRX Open API 일별 원천 |
| 수정주가 OHLC (`ADJUSTED`) | Naver 직접 날짜 범위 조회 (`requestType=1`) |
| 수정주가 거래량 | `NONE`; 제공한다고 선언하지 않음 |
| 종목 마스터 원천 사실 | KRX Basic Info + request `basDd` |
| 종목 마스터 표준 시장 | `normalize_krx_market(raw_market)` |
| instrument asset type | `InstrumentMetadataResolver` / 공식 상품 마스터 분류 |
| KRX 기본 업종지수 | KRX Open API 기본 업종지수 |
| 시장 대표지수 | FIX03 스냅샷: PyKRX 레거시, 목표 KRX Open API |
| ticker→sector membership | KRX Data Marketplace 공식 구성 종목 CSV → 정확한 기준일 `SectorMembershipStore` 스냅샷 |
| 펀더멘털 | OpenDART |
| 외국인·기관 수급 | PyKRX Foreign Flow |

원천과 수정주가의 의미는 절대 합쳐서 하나의 기준으로 표현하지 않는다.
AdjustedPriceStore는 OHLC만 소유하고 volume, trading_value, market_cap,
listed_shares를 저장하지 않는다.

### 10.6 FIX03 당시 Endpoint 식별자 의미
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
`normalize_krx_market(raw_market)`로 얻는 프로젝트 표준 값이며, 두 필드를
같은 의미의 중복 authority로 취급하지 않는다. `StockMasterStore`는
`security_group`, `listing_section`, `security_kind` 같은 원천/마스터 사실을 보유하지만
최종 `asset_type` authority가 아니다.

KRX 기본 업종지수 응답의 원천 정체성은
`(source_api, IDX_CLSS, IDX_NM)`다. `IndexStore.index_code`는 원천 응답 필드가
아니라 frozen `KRX_NATIVE_SECTOR_INDEX_MAP`에서 파생된 표준 code이며,
`IndexStore.family`는 `MARKET_INDEX`, `NATIVE_SECTOR_INDEX`,
`KRX_BRANDED_TAXONOMY` 중 논리 분류군이다. `IDX_CLSS`는 `source_index_class`로
보존하며 논리 분류군으로 사용하지 않는다. 표준 key는 `(family, index_code)`다.

### 10.7 FIX03 당시 논리 저장소
----------------------------------------------------------------------

`source_contracts.py`의 `STORE_CONTRACTS`가 다음 8개 저장소와 스키마 버전을
정의한다. 각 required field의 provenance는 전역 필드명이 아니라
`(owner_store, target_field)` 키로 `STORE_FIELD_PROVENANCE`에서 관리한다.

| 저장소 | 핵심 소유권 |
|---|---|
| `KrxRawStockStore` | 미수정 OHLC와 원천 부가 데이터 |
| `AdjustedPriceStore` | 수정주가 OHLC (`ADJUSTED`)만 보유; 스키마 `ADJUSTED_PRICE_V02`, 저장소 계약 `ADJUSTED_PRICE_STORE_V02` |
| `StockMasterStore` | `as_of`를 포함한 PIT 원천/표준 master; 최종 `asset_type`은 제외 |
| `InstrumentClassificationStore` | PIT `asset_type`·적용 가능성·계보 |
| `IndexStore` | 시장/기본 업종/분류 체계 논리 분류군; key=(family,index_code) |
| `SectorMembershipStore` | `effective_date` 기준 PIT membership |
| `FundamentalsStore` | OpenDART 보고 사실 |
| `CorporateActionStateStore` | 수정주가 캐시의 dirty/refresh 상태 |

FIX03 당시에는 protocol/dataclass 수준의 계약만 정의했다. 실제 모든 저장소의
구현과 대량 데이터 이동은 당시 후속 단계로 남겨 두었다.

InstrumentClassificationStore
----------------------------------------------------------------------

required field는 `effective_date`, `ticker`, `asset_type`,
`classification_authority`, `asset_type_source`다. `(effective_date, ticker)`를
표준 PIT key로 사용하고 requested `as_of` 이하의 최신 effective date를 조회한다.
`asset_type`은 `StockMasterStore.security_group/listing_section/security_kind`와
필요한 공식 상품 마스터 근거를 해석한 DERIVED 결과다. 현재 운영
authority인 `InstrumentMetadataResolver -> data/reference/krx_instrument_metadata.parquet`
와 공식 ETF/ETN 상품 마스터 기준은 이번 phase에서 교체하지 않는다.
KOSPI/KOSDAQ Basic Info만으로 ETF/ETN까지 분류한다고 선언하지 않는다.

Pattern A, FastCore, 종목 보고서 등 종목 적용 가능성 판단은 이 classification
layer를 사용해야 하며, consumer가 `KIND_STKCERT_TP_NM`, `SECUGRP_NM`, `SECT_TP_NM`을
각자 즉석 해석하는 중복 architecture는 금지한다.

### 10.8 FIX03 당시 Legacy composite cache
----------------------------------------------------------------------

현재 `data/raw/stocks/<ticker>.parquet`는 PyKRX 수정주가 OHLC와 원천 volume,
원천 trading_value가 결합된 기존 소비자 호환 캐시다. 이 파일을
`KRXRawStockStore`라고 부르지 않는다.

이번 단계에서 해당 경로의 파일을 다시 쓰기, 이동, 삭제, 일괄 이름 변경하지 않는다.
FIX03 당시 Pattern A, FastCore, Julia 등 기존 사용 코드는 당분간 레거시 캐시를
그대로 사용하도록 기록했다. 현재 운영 사용 코드 연결은 위의 현재 구현
경계에 적은 후속 Repository V2 경로를 따른다.

### 10.9 FIX03 당시 Repository V2 개념 대상
----------------------------------------------------------------------

FIX03 당시 문서상 개념 대상은
`MarketDataRepositoryV2(adjusted_price_store, raw_stock_store, ...)`였다.

- `get_daily()`의 open/high/low/close는 `ADJUSTED` (수정주가)
- `get_daily()`의 volume/trading_value는 `RAW` (원천)
- 결합 키는 `(ticker, date)`
- 결합은 `INNER_CONSISTENT_TRADING_SESSION_JOIN`
- 한쪽 계층이 없으면 `DATA_UNAVAILABLE` 또는 명시적 오류
- 이전 값 이월과 묵시적 채움은 금지
- market_cap/listed_shares는 `get_raw_daily()`, `get_daily_ancillary()`,
  `get_stock_snapshot()` 같은 별도 접근 계약으로 노출

주봉/월봉은 권위 원천이 아니며, Repository 일별 출력에서 파생한다.
가격은 수정주가 OHLC, volume/trading_value는 원천 일별 합계를 사용한다.

### 10.10 FIX03 당시 Corporate action 및 PIT
----------------------------------------------------------------------

사용자 정의 조정 엔진은 이 단계에 없다. `LIST_SHRS` 변화를 1차 dirty
신호로 사용하고 `PARVAL` 변화는 강한 보강 근거, 원천 OHLC 불연속과
메타데이터 변화는 2차 근거로 정의한다. 감지기는 정답 판정기가 아니라
수정주가 캐시 갱신 필요성 신호다.

원천 이력은 변경 불가 기준으로 취급하고, 수정주가 이력은 기업행위 이후
과거 값이 변할 수 있으므로 변경 가능한 갱신 상태를 별도로 둔다.
dirty 범위는 종목별이며 전체 종목 집합 갱신을 기본값으로 하지 않는다.

모든 시간 인식 저장소는 `as_of`/effective date를 갖고, `effective_date > as_of`,
미래 가격, 허용 이용 가능 시점 이전의 보고서를 사용하지 않는다. 과거 종목 집합은
당시 마스터 스냅샷을 사용해 생존편향을 피한다.

### 10.11 FIX03 당시 계보와 상태
----------------------------------------------------------------------

저장된 데이터셋 메타데이터의 최소 필드:

`layer_id`, `schema_version`, `source_name`, `source_endpoint`,
`source_semantics`, `authority_type`, `requested_as_of`, `date_min`, `date_max`,
`row_count`, `ticker_count`, `generation_timestamp`, `last_success_at`,
`content_sha256`

네트워크 데이터셋은 `validation_run_id`, `quota_usage_date_kst`, `run_request_count`를
추가할 수 있다. AUTH_KEY, KRX_ID, KRX_PW 및 실제 인증 정보는 메타데이터/로그/산출물에
저장하지 않는다.

필드 계보 원천은 `RESPONSE_FIELD`, `REQUEST_PARAMETER`, `STATIC_MAPPING`,
`DERIVED`, `STATE`, `PROVENANCE_METADATA`, `DERIVED_SOURCE_TRACE`, `LEGACY_SOURCE`로
구분한다. `RESPONSE_FIELD`는 커밋된 원천 스키마에 존재해야 하며,
요청/매핑 파생 필드는 `source_field=null`과
`source_locator`를 사용한다. `STORE_FIELD_PROVENANCE`의 적용 범위 키는
`(owner_store, target_field)`다.

대상 아키텍처 규칙:
새 운영 Store/Repository는 `artifacts/`를 실행 시점 원천으로 사용하지 않는다.

현재 수정주가 실행 시점 기준 원천은 패키지 소유
`ADJUSTED_PRICE_AUTHORITY_CONTRACT`의 Naver 직접 날짜 범위 조회 수정주가 원천이다.
`NaverDirectAdjustedPriceDataProvider`가 `AdjustedPriceStore`
(`ADJUSTED_PRICE_STORE_V02` 계약)에 현재 기준 데이터를
기록하며, Closure V02 파일은 오프라인 감사 근거로만 사용한다. 기존
`ADJUSTED_PRICE_V01`/PyKRX 캐시는 레거시 호환 또는 검증 비교기로
읽을 수 있지만 현재 기준이 아니다.

현재 레거시 실행 현실:
일부 기존 분석/보고서 흐름은 `artifacts/` 기반 데이터 캐시를 실행 시점에
사용하며 `LEGACY_RUNTIME_DEPENDENCIES`에 전환 기술 부채로 등록한다. 대시보드는
향후 이 레지스트리를 아키텍처 기술 부채로 표시할 수 있다.

상태 값은 `READY`, `STALE`, `PARTIAL`, `MISSING`, `ERROR`, `NOT_MIGRATED`,
`DIRTY`다. LayerRegistry는 정적 `operational_status`와 `migration_status`를
분리해 보유하고, `DataHealthSnapshot`은 별도 실행 시점 `HealthStatus`를 보유한다.
대시보드는 `layer_id`로 두 상태를 결합한다. 스냅샷은
layer/source/date/행/ticker/missing/stale/error와
last success/attempt/message를 공통으로 노출한다. quota observability는
`usage_date_kst`, `used`, `limit`, `remaining`, `percentage`, `endpoint_usage`다.

### 10.12 FIX03 당시 전환 상태 스냅샷
----------------------------------------------------------------------

| 계층 | 당시 상태 |
|---|---|
| `SECTOR_INDEX_KRX` | `MIGRATED` |
| `MARKET_INDEX` | `LEGACY_SOURCE` |
| `STOCK_RAW_KRX` | `VALIDATED_NOT_PRODUCTION_MIGRATED` |
| `STOCK_ADJUSTED` | `PARTIALLY_MIGRATED` |
| `STOCK_MASTER_KRX` | `VALIDATED_NOT_PRODUCTION_MIGRATED` |
| `INSTRUMENT_CLASSIFICATION` | `LEGACY_SOURCE` |
| `FUNDAMENTALS_OPENDART` | `CLOSED / AVAILABLE` |

아래 표는 FIX03 당시의 전환 상태 스냅샷이며, 기술 토큰/값은 역사 기록으로
보존한다. API 검증 완료만으로 운영 전환/READY라고 표시하지 않는다.
이번 FIX03에서 `STOCK_RAW_KRX`는 실제 운영 원천이 아니라
`LEGACY_COMPOSITE_STOCK_CACHE`를 현재 원천으로 명시하고, 검증 원천과
대상 저장소를 별도 기록한다. `STOCK_MASTER_KRX`의 현재 원천은 현재
레포의 `InstrumentMetadataResolver -> data/reference/krx_instrument_metadata.parquet`
동결 산출물 기준이며, KRX Basic Info는 검증/대상 계약이다.
`STOCK_MASTER_KRX`는 원천/표준 마스터 경계만 담당하고, 자산 유형 기준은
`INSTRUMENT_CLASSIFICATION` 계층으로 분리한다.

### 10.13 FIX03 당시 Sector RS 구성 종목 기준
----------------------------------------------------------------------
현재 Sector RS 운영 경로의 구성 종목은
KRX Data Marketplace 공식 지수구성종목 CSV를 수동 로그인 브라우저로 내려받아
46개 업종 검증을 통과시킨 뒤 `SectorMembershipStore`에 정확한 기준일 스냅샷으로
구체화한 것이다. 현재 승인 스냅샷은
`data/market/sector_membership/v01/sector_membership_20260814.parquet`와
`data/market/sector_membership/v01/sector_membership_20260904.parquet`다.
요청 `as_of`는 스냅샷의 `effective_date`와 정확히 일치해야 하며, 이전 스냅샷을
유지하거나 이후 스냅샷을 소급 적용하지 않는다. Marketplace 실패 시
PyKRX 구성 종목 대체 경로도 수행하지 않는다. Naver 분류 체계와 현재 PyKRX 구성 종목은
현재 구성 종목 기준이 아니다.

### 10.14 FIX03 당시 Foreign Flow 계보와 운영 diff 보호
----------------------------------------------------------------------

`src/trend_scanner/flow/foreign_flow.py`는 Foreign Flow 상위 원천 기준이
아니라 지표 계산 엔진이다. 현재 계보는
`ForeignFlowDataProvider.fetch_date_batch -> build_historical_cache`와
`scripts/fetch_foreign_flow_20260814.py`가 PyKRX
`get_market_net_purchases_of_equities_by_ticker(date, date, "ALL", "외국인")`를
호출해 `foreign_flow_daily_<as_of>.parquet`를 만들고, 스캐너/종목 보고서가
`compute_foreign_flow_features`를 소비하는 흐름으로 고정한다.

FIX03 검증기는 고정된 시작 head
`bba23053b806b3775159acf89cb6a0b143937ebd`부터 implementation head까지의
`git diff --name-only`를 검사한다. 허용 경로는 계약, 검증기, 이 문서,
아키텍처 계약 테스트 및 `artifacts/data/architecture/krx_production_data/v01/`
뿐이며, 그 밖의 운영 동작 경로 변경은 차단 사유다. `network_request_count`는
실행 중 네트워크 요청 횟수이고 `static_forbidden_network_import_count`는
계약/validator의 금지 import 정적 검사 횟수로 서로 다른 지표다. 이 작업에서는
KRX/PyKRX/OpenDART 네트워크 요청을 수행하지 않는다.

### 10.15 FIX03 당시 의존성 그래프
----------------------------------------------------------------------

`KRX_PRODUCTION_DATA_ARCHITECTURE_V01`
→ `ADJUSTED_PRICE_STORE_V02`
→ `CORPORATE_ACTION_DIRTY_REFRESH_V01`
→ `KRX_HISTORICAL_BACKFILL_V01`
→ `MARKET_DATA_REPOSITORY_V02`
→ `KRX_INDEX_MIGRATION_V01`
→ `END_TO_END_DATA_PARITY_V01`

그래프는 정적 검증기에서 순환을 검사한다. Repository V2와 AdjustedPriceStore
사이의 역방향 의존성은 만들지 않는다.

### 10.16 FIX03 당시 ADR 목록
----------------------------------------------------------------------

- ADR-01 KRX 원천 기준
- ADR-02 과거 PyKRX 수정주가 OHLC 기준 원천 (레거시/비교기)
- ADR-03 원천 부가 데이터 소유권
- ADR-04 레거시 composite cache 분류
- ADR-05 Repository 결합 의미
- ADR-06 수정주가 과거 이력 변경 가능성
- ADR-07 기업행위 dirty 정책
- ADR-08 endpoint별 식별자 의미
- ADR-09 KRX `SECT_TP_NM` non-sector rule
- ADR-10 업종 지수와 시장 지수의 전환 상태
- ADR-11 PIT 종목 집합 요구사항
- ADR-12 실행 시점 산출물 의존 금지
- ADR-13 canonical quota authority
- ADR-14 데이터 상태 관측성 계약
- ADR-15 FIX01 store-qualified field provenance and state separation
- ADR-16 FIX02 raw schema truth and request/mapping provenance
- ADR-17 레거시 실행 시점 산출물 의존 기술 부채
- ADR-18 FIX03 StockMaster raw/canonical market와 instrument classification boundary
- ADR-19 FIX03 logical index family와 `IDX_CLSS` source class 분리
- ADR-20 FIX03 PIT classification compatibility와 ETF/ETN authority 보존

### 10.17 FIX03 당시 검증 및 산출물
----------------------------------------------------------------------

오프라인 검증기:
`scripts/validate_krx_production_data_architecture_v01.py`

계약 테스트:
`tests/test_krx_production_data_architecture_v01.py`

산출물:
`artifacts/data/architecture/krx_production_data/v01/`

이번 단계의 완료 목표는 새 과거 데이터를 만든 것이 아니라 기준,
스키마, PIT, 계보, 상태 의미를 혼동 없이 고정하는 것이다.
