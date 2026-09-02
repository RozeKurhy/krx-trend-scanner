docs/architecture/sector_rs_krx_migration_v01.md

======================================================================
SECTOR_RS_KRX_MIGRATION_V01
======================================================================

목적
----------------------------------------------------------------------
Sector Relative Strength가 사용하는 native 46개 업종지수 가격 source를
PyKRX에서 KRX Open API로 교체하고, current membership은 KRX frozen canonical
2026-08-14 exact snapshot으로 고정한다. Historical membership은 deferred이며,
Naver membership fallback과 live PyKRX membership은 금지한다.

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

Current membership flow
----------------------------------------------------------------------
KRX frozen canonical resolution policy
        ↓ (exact effective_date=2026-08-14)
`SectorMembershipStore` (2528 COMMON, 2496 mapped, 32 explicit UNMAPPED)
        ↓
`load_sector_mapping_exact_snapshot()`
        ↓
`compute_relative_strength_features(require_exact_sector_snapshot=True)`

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

Membership invariants
----------------------------------------------------------------------
- exact snapshot date는 `2026-08-14` 하나뿐이다.
- 2026-08-14 이외의 as_of에서는 Sector RS를 `NOT_EVALUATED`로 반환한다.
- 32개 unmapped COMMON은 삭제하지 않고 `DATA_UNAVAILABLE` /
  `SECTOR_MEMBERSHIP_UNMAPPED`로 보존한다.
- Sector RS cross-section은 전체 COMMON valid 값만으로 계산하며 candidate subset을
  분모로 사용하지 않는다.

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

FIX01 validation contract
----------------------------------------------------------------------
- RS parity validation은 production과 동일한
  `(sector_code, sector_name, effective_date)` PIT tuple을 사용한다.
- `effective_date > as_of` 또는 2-tuple mapping은 fail-closed이며,
  old/new 결과가 모두 `READY`인 표본만 parity를 통과시킨다.
- KOSDAQ validation-only membership은 native sector code별 bounded
  `get_index_portfolio_deposit_file()` probe로 확보할 수 있다. 이 증적은
  production membership cache나 `build_sector_mapping()`을 변경하지 않는다.
- cache parity는 `LOCAL_PYKRX_SECTOR_CACHE` 또는 committed
  `LOCAL_PYKRX_SECTOR_CACHE_RECONSTRUCTED` replay만 사용하며, 암묵적인
  live PyKRX 가격 fallback은 수행하지 않는다.
- daily quota authority는 `LocalKrxOpenApiQuota()`의 canonical DB다.
  validation은 `quota_before`/`quota_after` run delta와 현재 run audit만
  비교하며, 과거 cache build의 640회 요청과 legacy task-local 800회 기록은
  현재 audit에 섞지 않는다.
- live smoke는 2026-08-14/20/21의 3 dates × 2 endpoints로 제한하고,
  46 sectors × 4 OHLC = 552 fields를 production cache와 exact 비교한다.
