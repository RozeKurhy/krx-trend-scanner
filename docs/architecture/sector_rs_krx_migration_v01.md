docs/architecture/sector_rs_krx_migration_v01.md

# Sector RS용 KRX 전환 (SECTOR_RS_KRX_MIGRATION_V01)

목적
----------------------------------------------------------------------
Sector Relative Strength가 사용하는 native 46개 업종지수 가격 원천을
PyKRX에서 KRX Open API로 교체했다. Sector 구성 종목 정보는 KRX Data Marketplace
공식 지수구성종목 CSV를 수동 로그인 브라우저로 내려받아 approved
effective-date SectorMembershipStore 스냅샷으로 관리한다. Naver 구성 종목 fallback과 live
PyKRX 구성 종목 정보는 금지한다.

운영 계약
----------------------------------------------------------------------
- `trend_scanner.data.krx_sector_index.KRX_NATIVE_SECTOR_INDEX_MAP`
  - 변경 불가 46-entry mapping
  - KOSPI 24 / KOSDAQ 22
  - 원천이 포함된 `(source_api, idx_class, idx_name)` identity
- 검증 산출물은 contract의 실행 시점 의존성이 아니다.

캐시 흐름
----------------------------------------------------------------------
KRX `/idx/kospi_dd_trd` + `/idx/kosdaq_dd_trd`
        ↓ (최대 2 snapshot calls / date)
normalized 46-sector Parquet cache
        ↓
`IndexPriceDataProvider.load_sector_index_history()`
        ↓
`compute_relative_strength_features()`

현재 구성 종목 정보 흐름
----------------------------------------------------------------------
KRX Data Marketplace 공식 지수 구성 종목 CSV
        ↓ (수동 로그인 → 지수 → 주가지수 → 지수구성종목 → 기준일)
46개 업종 검증 (KOSPI 24 + KOSDAQ 22)
        ↓ MOST_SPECIFIC_NATIVE_SECTOR_V01 resolution
`SectorMembershipStore` approved effective-date snapshots
        ↓
`2026-08-14` (2528 COMMON, 2496 resolved, 32 explicit UNMAPPED)
`2026-09-04` (2562 COMMON, 2528 resolved, 34 explicit UNMAPPED)
`2026-09-17` (2559 COMMON, 2438 resolved, 33 explicit UNMAPPED)
        ↓
`resolve_sector_membership_snapshot_for_target()`
        ↓
`compute_relative_strength_features(require_exact_sector_snapshot=False)`

Market RS는 기존 market index cache/원천을 계속 사용한다.
KRX `/idx/krx_dd_trd` branded taxonomy는 native Sector RS에 사용하지 않는다.

캐시 불변식
----------------------------------------------------------------------
- 표준 컬럼은 date/index_code/index_name/open/high/low/close/volume/trading_value.
- 정상 거래일은 KOSPI 24 + KOSDAQ 22 rows를 갖는다.
- `(date, index_code)`는 unique하다.
- OHLC는 numeric/non-null/positive다.
- `BAS_DD`, `IDX_CLSS`, `IDX_NM`은 요청일·contract와 exact match여야 한다.
- API 200 + 빈 OutBlock은 양 시장 모두 빈 경우에만 non-trading date로 취급한다.
- 한 시장만 성공하면 운영 cache를 갱신하지 않는다.
- 초기 cache는 최소 270 complete trading sessions를 요구한다.

구성 종목 불변식
----------------------------------------------------------------------
- 승인된 snapshot pair(parquet + `_meta.json`)만 사용한다. 현재 보유 승인
  스냅샷은 `2026-08-14`, `2026-09-04`, `2026-09-17`이며,
  `2026-09-17`이 현재 최신 승인 스냅샷이다.
- 일일 target에는 `effective_date <= target_as_of`인 최신 승인 snapshot을
  사용한다. 정확히 일치하는 snapshot이 없어도 이 규칙에 따라 과거 승인
  snapshot을 사용할 수 있다.
- target보다 미래인 snapshot은 사용하지 않는다. 최신 eligible 후보가
  부분 발행·무효이면 fail closed하고 더 오래된 snapshot으로 fallback하지
  않는다.
- unmapped COMMON은 삭제하지 않고 `DATA_UNAVAILABLE` /
  `SECTOR_MEMBERSHIP_UNMAPPED`로 보존한다. (`2026-08-14`: 32개,
  `2026-09-04`: 34개, `2026-09-17`: 33개)
- Sector RS cross-section은 전체 COMMON valid 값만으로 계산하며 candidate subset을
  분모로 사용하지 않는다.

Sector index cache 증분 갱신
----------------------------------------------------------------------
기존 cache가 있으면 target date의 KOSPI/KOSDAQ snapshot만 가져온다.
두 snapshot 검증이 모두 끝난 뒤 임시 Parquet와 metadata를 atomic replace한다.
동일 날짜 재실행은 해당 날짜를 deterministic replace하며 duplicate를 만들지 않는다.

현재 구성 종목 취득 및 계보
----------------------------------------------------------------------
- 원천: `KRX Data Marketplace 공식 지수 구성 종목`
- UI 경로: 수동 로그인 → 지수 → 주가지수 → 지수구성종목 → 기준일 선택
- 운영 취득: 직접 scripted HTTP 없이 공식 CSV 다운로드
- 운영 게시 게이트: KOSPI 24 + KOSDAQ 22 = 46 / 46 required
- CSV는 로컬 원천으로 보존한 뒤 effective-date `SectorMembershipStore` 스냅샷을 생성한다.
- Sector index cache metadata에는 source_name, fetch_mode, source_apis, mapping
  contract version/hash, date range, index/row counts, Parquet SHA-256을 기록한다.
- 검증 결과는 `artifacts/data/krx_openapi/sector_rs_migration/v01/`에 저장하고,
  운영 cache 자체는 `.cache/` 아래에 둔다.

과거 검증 근거 (현재 운영 취득 경로 아님)
----------------------------------------------------------------------
과거 일치성/전송 검증에서 PyKRX 구성 종목 정보 probe를 사용했다는 기록은
과거 검증 근거로 보존한다. 해당 probe와 replay는 현재 운영 구성 종목 수집 또는
  대체 경로가 아니다.

FIX01 검증 계약
----------------------------------------------------------------------
- RS parity 검증은 운영과 동일한
  `(sector_code, sector_name, effective_date)` PIT tuple을 사용한다.
- `effective_date > as_of` 또는 2-tuple mapping은 fail-closed이며,
  old/new 결과가 모두 `READY`인 표본만 parity를 통과시킨다.
- KOSDAQ validation-only membership은 native sector code별 bounded
  `get_index_portfolio_deposit_file()` probe로 확보할 수 있다. 이 증적은
  운영 구성 종목 cache나 `build_sector_mapping()`을 변경하지 않는다.
- cache parity는 `LOCAL_PYKRX_SECTOR_CACHE` 또는 committed
  `LOCAL_PYKRX_SECTOR_CACHE_RECONSTRUCTED` replay만 사용하며, 암묵적인
  live PyKRX 가격 fallback은 수행하지 않는다.
- daily quota authority는 `LocalKrxOpenApiQuota()`의 canonical DB다.
  validation은 `quota_before`/`quota_after` run delta와 현재 run audit만
  비교하며, 과거 cache build의 640회 요청과 legacy task-local 800회 기록은
  현재 audit에 섞지 않는다.
- 실제 호출 간단 검증은 2026-08-14/20/21의 3 dates × 2 endpoints로 제한하고,
  46 sectors × 4 OHLC = 552 fields를 운영 cache와 정확히 비교한다.
