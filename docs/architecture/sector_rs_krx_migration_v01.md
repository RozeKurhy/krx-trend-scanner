docs/architecture/sector_rs_krx_migration_v01.md

======================================================================
SECTOR_RS_KRX_MIGRATION_V01
======================================================================

목적
----------------------------------------------------------------------
Sector Relative Strength가 사용하는 native 46개 업종지수 가격 source를
PyKRX에서 KRX Open API로 교체한다. RS 공식, sector_code, ticker→sector
membership, RelativeStrengthFeatureResult와 Market RS source는 변경하지 않는다.

Production contract
----------------------------------------------------------------------
- `trend_scanner.data.krx_sector_index.KRX_NATIVE_SECTOR_INDEX_MAP`
  - immutable 46-entry mapping
  - KOSPI 24 / KOSDAQ 22
  - source-qualified `(source_api, idx_class, idx_name)` identity
- validation artifacts는 contract의 runtime dependency가 아니다.

Cache flow
----------------------------------------------------------------------
KRX `/idx/kospi_dd_trd` + `/idx/kosdaq_dd_trd`
        ↓ (최대 2 snapshot calls / date)
normalized 46-sector Parquet cache
        ↓
`IndexPriceDataProvider.load_sector_index_history()`
        ↓
`compute_relative_strength_features()`

Market RS는 기존 market index cache/source를 계속 사용한다.
KRX `/idx/krx_dd_trd` branded taxonomy는 native Sector RS에 사용하지 않는다.

Cache invariants
----------------------------------------------------------------------
- 표준 컬럼은 date/index_code/index_name/open/high/low/close/volume/trading_value.
- 정상 거래일은 KOSPI 24 + KOSDAQ 22 rows를 갖는다.
- `(date, index_code)`는 unique하다.
- OHLC는 numeric/non-null/positive다.
- `BAS_DD`, `IDX_CLSS`, `IDX_NM`은 요청일·contract와 exact match여야 한다.
- API 200 + 빈 OutBlock은 양 시장 모두 빈 경우에만 non-trading date로 취급한다.
- 한 시장만 성공하면 production cache를 갱신하지 않는다.
- 초기 cache는 최소 270 complete trading sessions를 요구한다.

Incremental update
----------------------------------------------------------------------
기존 cache가 있으면 target date의 KOSPI/KOSDAQ snapshot만 가져온다.
두 snapshot 검증이 모두 끝난 뒤 임시 Parquet와 metadata를 atomic replace한다.
동일 날짜 재실행은 해당 날짜를 deterministic replace하며 duplicate를 만들지 않는다.

Provenance
----------------------------------------------------------------------
cache metadata에는 source_name, fetch_mode, source_apis, mapping contract
version/hash, date range, index/row counts, Parquet SHA-256을 기록한다.
검증 결과는 `artifacts/data/krx_openapi/sector_rs_migration/v01/`에 저장하고,
production cache 자체는 `.cache/` 아래에 둔다.
