docs/architecture/sector_rs_krx_migration_v01.md

======================================================================
SECTOR_RS_KRX_MIGRATION_V01
======================================================================

목적
----------------------------------------------------------------------
Sector Relative Strength가 사용하는 native 46개 업종지수 가격 source를
PyKRX에서 KRX Open API로 교체했다. Sector Membership은 KRX Data Marketplace
공식 지수구성종목 CSV를 수동 로그인 브라우저로 내려받아 approved exact-date
SectorMembershipStore snapshot으로 관리한다. Naver membership fallback과 live
PyKRX membership은 금지한다.

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
KRX Data Marketplace official index constituents CSV
        ↓ (manual login → 지수 → 주가지수 → 지수구성종목 → effective date)
46-sector validation (KOSPI 24 + KOSDAQ 22)
        ↓ MOST_SPECIFIC_NATIVE_SECTOR_V01 resolution
`SectorMembershipStore` exact-date snapshots
        ↓
`2026-08-14` (2528 COMMON, 2496 resolved, 32 explicit UNMAPPED)
`2026-09-04` (2562 COMMON, 2528 resolved, 34 explicit UNMAPPED)
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
- approved exact-date snapshot만 사용한다.
- 현재 보유 snapshot은 `2026-08-14` historical approved snapshot과
  `2026-09-04` current latest approved snapshot이다.
- requested `as_of`와 exact match하는 snapshot이 없으면 fail closed하고
  Sector RS를 `NOT_EVALUATED`로 반환한다.
- 이전 snapshot을 자동 carry-forward하지 않고, 이후 snapshot을 backward apply하지 않는다.
- unmapped COMMON은 삭제하지 않고 `DATA_UNAVAILABLE` /
  `SECTOR_MEMBERSHIP_UNMAPPED`로 보존한다. (`2026-08-14`: 32개,
  `2026-09-04`: 34개)
- Sector RS cross-section은 전체 COMMON valid 값만으로 계산하며 candidate subset을
  분모로 사용하지 않는다.

Sector index cache incremental update
----------------------------------------------------------------------
기존 cache가 있으면 target date의 KOSPI/KOSDAQ snapshot만 가져온다.
두 snapshot 검증이 모두 끝난 뒤 임시 Parquet와 metadata를 atomic replace한다.
동일 날짜 재실행은 해당 날짜를 deterministic replace하며 duplicate를 만들지 않는다.

Current membership acquisition and provenance
----------------------------------------------------------------------
- Source: `KRX Data Marketplace official index constituents`
- UI path: 수동 로그인 → 지수 → 주가지수 → 지수구성종목 → 기준일 선택
- Production acquisition: direct scripted HTTP 없이 공식 CSV 다운로드
- Production publication gate: KOSPI 24 + KOSDAQ 22 = 46 / 46 required
- CSV는 local source로 보존한 뒤 exact-date `SectorMembershipStore` snapshot을 생성한다.
- Sector index cache metadata에는 source_name, fetch_mode, source_apis, mapping
  contract version/hash, date range, index/row counts, Parquet SHA-256을 기록한다.
- 검증 결과는 `artifacts/data/krx_openapi/sector_rs_migration/v01/`에 저장하고,
  production cache 자체는 `.cache/` 아래에 둔다.

Historical validation evidence (not current production acquisition)
----------------------------------------------------------------------
과거 parity/transport 검증에서 PyKRX membership probe를 사용했다는 기록은
historical evidence로 보존한다. 해당 probe와 replay는 현재 production
membership acquisition 또는 fallback 경로가 아니다.

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
