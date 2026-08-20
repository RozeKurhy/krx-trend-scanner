krx_instrument_metadata_authority.md

# KRX Instrument Metadata Authority — Lineage & Trust Rule (Fix Round 05, Major 1)

이 문서는 `InstrumentMetadataResolver`가 Production Asset Type Authority로 사용하는
frozen local artifact의 실제 lineage를 기록한다. 확인 불가능한 부분은 "확인 불가"로
명시하며, 근거 없이 정당화 문구를 채우지 않는다 (w.md Fix Round 04 §4.4, Fix Round
05 §4.4).

Fix Round 04까지는 이 artifact 전체(72,786 row)가 실제로는 어디서 왔는지 저장소
안에서 재현할 수 없는 상태였다(§3 "Fix Round 04 이전 상태" 참고). Fix Round 05에서
처음으로 실제 verified upstream formal source에 연결된 build workflow를 만들었다 —
단, **이번 라운드가 검증할 수 있는 것은 build 실행 시점의 KRX 실시간 상장 상태
하나의 snapshot뿐**이라는 근본적인 한계가 있다. 이 한계와 그로 인한 PIT 범위
제한은 §8~9에 그대로 기록한다.


## 1. Artifact

- `data/reference/krx_instrument_metadata.parquet` (1차 read 대상)
- `data/reference/krx_instrument_metadata.csv` (parquet 없을 때 fallback, 동일 스키마)
- `data/reference/krx_instrument_metadata_manifest.json` (신규, Fix Round 05 — 매
  build 실행마다 갱신되는 generation manifest)

세 파일은 매 갱신마다 (ticker, effective_date) 기준으로 row-aligned 동일 내용을
유지해야 한다.


## 2. Purpose

Production Instrument Metadata Authority.
Strict PIT(Point-In-Time) local frozen snapshot — 여러 `effective_date` 시점의
스냅샷을 누적 보관하고, 조회 시점(`requested_as_of`)보다 미래인 스냅샷은
사용하지 않는다.


## 3. Fix Round 04 이전 상태 (역사적 기록)

Fix Round 04 완료 시점까지 확인된 사실: 이 artifact를 생성하는 스크립트가
저장소 안에 없었고, 최초 도입 커밋(`5baa44b`, 2026-08-20)에 2781행 CSV가 완성된
형태로 한 번에 추가됐으며, 실제 upstream 조회 방식은 커밋 메시지에도 남아있지
않았다. `classification_authority`/`asset_type_source`는 전 row 100%
"FORMAL_SECURITY_TYPE"으로 균일하게 찍혀 있었으나, `asset_type=UNKNOWN`인 36개
row조차 동일한 라벨을 갖고 있어 이 라벨이 row별 실제 검증을 반영하지 않는
파일 전체 상수였음이 드러났다. 이 문제를 실제로 해소하는 것이 이번 Fix Round 05의
목표였다.


## 4. Upstream Authority (Fix Round 05에서 실제 확인됨)

**UPSTREAM_AUTHORITY** = KRX Market Data Center (data.krx.co.kr), 인증 세션 필요

**UPSTREAM_SOURCE_NAME**:
1. 전종목기본정보 — `bld=dbms/MDC/STAT/standard/MDCSTAT01901`
   ([12005] 전종목 기본정보 페이지의 이면 데이터 API)
2. pykrx `get_etf_ticker_list()` / `get_etn_ticker_list()`
3. 상폐종목검색 (delisted finder, `bld=dbms/comm/finder/finder_listdelisu`) —
   현재 미상장(delisted) ticker의 존재 자체를 확인하는 reference 용도로만 사용,
   security type 필드는 제공하지 않음

**SOURCE_LOCATION** = `https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd`
(POST, `bld` 파라미터로 구분)

**ACQUISITION_METHOD** = 인증된 HTTPS 세션(KRX_ID/KRX_PW, `.env`)으로 build-time에만
접근. `dbms/comm/finder/finder_stkisu`(단순 ticker 검색) 같은 공개 endpoint와
달리, `MDCSTAT01901`은 익명 요청 시 본문이 문자 그대로 `"LOGOUT"`인 400 응답을
반환한다 — 즉 이 특정 bld는 실제로 로그인 세션을 요구하며, 익명 접근으로는
얻을 수 없다는 것을 직접 확인했다. `KRX_ID`/`KRX_PW`가 없으면 이 build script는
`RuntimeError`로 즉시 실패한다(추측성 fallback 없음).

**SOURCE_SNAPSHOT_DATE** = build 실행 시각(UTC), `krx_instrument_metadata_manifest.json`의
`generated_at`/`source_snapshot_date`에 매 실행마다 기록됨.

**SOURCE_CHECKSUM** = build마다 `krx_instrument_metadata_manifest.json`의
`source_checksum_sha256`에 산출 CSV 전체의 SHA-256을 기록 (재현성/변경 추적용).


## 5. Raw Source Fields (전종목기본정보 API 원본 컬럼)

```
ISU_SRT_CD           - 6자리(또는 영숫자) 종목코드
ISU_NM                - 정식 종목명
MKT_TP_NM              - 시장 (KOSPI / KOSDAQ / KOSDAQ GLOBAL / KONEX)
SECUGRP_NM             - 증권그룹명: 주권 / 부동산투자회사 / 외국주권 / 주식예탁증권 /
                          사회간접자본투융자회사 / 투자회사
SECT_TP_NM             - 소속부명: 우량기업부/중견기업부/벤처기업부/기술성장기업부/
                          일반기업부/관리종목(소속부없음)/SPAC(소속부없음)/
                          투자주의환기종목(소속부없음)/외국기업(소속부없음)/공란
KIND_STKCERT_TP_NM      - 주권종류구분명: 보통주 / 구형우선주 / 신형우선주 / 종류주권
```

이 원본 필드들은 canonical artifact에 `source_security_type` 컬럼으로 압축
보존된다 (형식: `SECUGRP_NM=...|SECT_TP_NM=...|KIND_STKCERT_TP_NM=...`) — 단
Verified rows(§8)에 한해서만 채워지며, 과거 legacy row는 빈 값이다 (§9).


## 6. Source Category → AssetType Deterministic Mapping (실제 검증된 규칙)

`scripts/build_krx_instrument_metadata.py`의 `map_row_to_asset_type()` 실제 로직:

```
SECT_TP_NM에 "SPAC" 포함(예: "SPAC(소속부없음)")     → SPAC
SECUGRP_NM == "부동산투자회사"                        → REIT
KIND_STKCERT_TP_NM == "보통주"                        → COMMON
KIND_STKCERT_TP_NM in ("구형우선주", "신형우선주")     → PREFERRED
KIND_STKCERT_TP_NM == "종류주권" AND ISU_NM에 "우선주" 포함
                                                       → PREFERRED
그 외 (외국주권 / 주식예탁증권 / 사회간접자본투융자회사 /
투자회사 / 종류주권(비우선주))                          → UNKNOWN
                                                          (classification_authority=FORMAL_SECURITY_TYPE,
                                                           asset_type_source=UNMAPPED_FORMAL_CATEGORY)

별도 product list 조회:
  ticker ∈ get_etf_ticker_list()  → ETF
  ticker ∈ get_etn_ticker_list()  → ETN

formal source에서 ticker 자체를 못 찾음(상장/ETF/ETN 어디에도 없음)
                                                       → UNKNOWN
                                                          (classification_authority=UNKNOWN,
                                                           asset_type_source=UNKNOWN)
```

`KIND_STKCERT_TP_NM == "종류주권"` 12건 전수 확인 결과 전부 `ISU_NM`이
"...우선주"/"...우선주(신형)" 형태였다(예: `03473K SK1우선주`, `02826K
삼성물산1우선주(신형)`) — 이는 **같은 formal record 내부의 다른 formal field로
재확인**한 것이며, 별도의 비공식 name-heuristic이 아니다(w.md §2.2가 금지하는
"종목명 heuristic으로 canonical asset_type 생성"에 해당하지 않음 — 판정 키는
`KIND_STKCERT_TP_NM`이라는 formal field이고, `ISU_NM`은 같은 formal API 응답
안에서 그 판정을 뒷받침하는 보조 formal field일 뿐이다).


## 7. Builder Script

```
BUILDER_SCRIPT   = scripts/build_krx_instrument_metadata.py
MAPPING_VERSION  = v1
```

역할: 인증 세션으로 KRX MDC에서 라이브 formal 분류를 가져와, 이 project의
canonical metadata 중 `effective_date == --as-of-date`(기본 2026-08-14)인 row에만
반영. `--dry-run`으로 파일을 쓰지 않고 변경 미리보기 가능. 실행마다
`krx_instrument_metadata_manifest.json`을 새로 쓴다.


## 8. Verified Snapshot 범위 (2026-08-14 한정)

이번 build가 실제로 검증한 것은 **build 실행 시점의 KRX 실시간 상장 상태**
하나뿐이다. 과거로 거슬러 올라가는 historical formal snapshot을 제공하는
API는 확인하지 못했다(그런 것이 존재하는지 자체를 이번 라운드에서 조사하지
않았다 — 향후 과제).

이 project의 canonical metadata는 `effective_date == 2026-08-14`를 "현재" 기준일로
쓰므로, 이번 build는 정확히 그 날짜의 row만 이 verified snapshot으로 갱신한다.

```
VERIFIED_ROWS = 2,780 (전체 72,786 row 중 2026-08-14 시점 row)
```


## 9. Historical Row 정책 (PIT History Rewrite 금지, w.md §2.13)

**2026-08-14 이전의 26개 effective_date, 70,006개 row는 이번 build가 값(asset_type,
name, market 등)을 전혀 건드리지 않았다.** 오늘 시점 조회 결과로 과거 snapshot을
소급 덮어쓰는 것(history rewrite)은 절대 금지되어 있으므로, historical row는
기존 값을 그대로 유지한다.

다만 provenance는 정직하게 낮춘다: historical row 전체의
`classification_authority`/`asset_type_source`를 새 값 `"LEGACY_UNVERIFIED"`로
설정했다. `InstrumentMetadata.is_trusted_for_production`은 이 값이 아니면
(`FORMAL_SECURITY_TYPE`이어야만) trusted로 인정하므로, **historical row는 이제
자동으로 fail closed된다** — asset_type 자체(COMMON/SPAC 등)는 여전히 기존 PIT
로직으로 정확히 조회되지만(§10), production trust는 더 이상 주어지지 않는다.

이것이 369370의 §5 representative regression과 만드는 긴장에 대한 명시적 답:
369370의 2021-06-25(합병 전, SPAC)/2022-06-24(합병 후, COMMON) 두 row 모두
`effective_date < 2026-08-14`인 historical row다. 이번 규칙에 따라 두 row 모두
`classification_authority = LEGACY_UNVERIFIED`이며, **`asset_type`(SPAC/COMMON)
값 자체는 여전히 정확하게 조회되지만 `is_trusted_for_production`은 두 시점 모두
`False`다.** w.md §5 스스로 "증명 불가능한 과거 row를 억지로 trusted로 유지하지
말 것"이라고 명시하므로, 이는 스펙 위반이 아니라 그 지시를 문자 그대로 따른
결과다. 369370의 오직 최신 row(2026-08-14, `블리츠웨이엔터테인먼트`, COMMON)만
이번 build로 실제 verified되어 trusted다.


## 10. PIT Selection Rule (코드로 검증 가능, 변경 없음)

`InstrumentMetadataResolver.resolve()` (src/trend_scanner/universe/instrument_metadata.py):

1. `ticker`로 후보 row 전체를 찾는다 (여러 effective_date 스냅샷 존재 가능).
2. `requested_as_of`가 주어지면, `effective_date <= requested_as_of`인 row만 남긴다.
3. 남은 것 중 `effective_date`가 가장 늦은 row 하나를 선택한다.
4. 후보가 없으면 `is_identified=False`, 전부 UNKNOWN으로 fail closed.

Fix Round 05에서 이 로직 자체는 수정하지 않았다 — 위 policy(§9)는 순수하게
**데이터(provenance 컬럼 값)**만 바꿨을 뿐, 선택 알고리즘은 그대로다.


## 11. Trust Rule (변경 없음, Fix Round 04에서 구현)

```
is_identified == True
AND classification_authority == "FORMAL_SECURITY_TYPE"
AND asset_type_source == "FORMAL_SECURITY_TYPE"
AND asset_type != "UNKNOWN"
```

이제 이 게이트는 이 artifact 안에서 실제로 row를 구분한다(Fix Round 04 시점의
"row마다 다르지 않은 상수" 문제가 verified rows(2026-08-14, 2,780개)에 한해
해소됨). Historical row는 §9에 따라 여전히 균일하게 untrusted다 — 이는 게이트가
못 구분하는 게 아니라, 검증 불가능한 데이터에 대해 게이트가 의도대로 정직하게
차단하는 것이다.


## 12. Fail Closed Rule

- `asset_type == UNKNOWN` → 항상 fail closed.
- `classification_authority`/`asset_type_source`가 `FORMAL_SECURITY_TYPE`이 아님
  (`UNKNOWN` / `LEGACY_HEURISTIC` / `LEGACY_UNVERIFIED`) → `asset_type`이 COMMON
  이라도 fail closed.
- formal source는 확인됐으나 mapping이 불가능한 category(`UNMAPPED_FORMAL_CATEGORY`)
  → fail closed (§6, 이번 build 결과 실제 0건 — 모든 verified row가 깨끗하게
  매핑됨).
- 이름 문자열 heuristic으로 UNKNOWN을 COMMON/SPAC 등으로 승격하지 않는다.
  `HEURISTIC_PROMOTION_COUNT = 0` (13개 SPAC ticker는 이름이 아니라 formal
  `SECT_TP_NM` 필드로 확인됨 — §13 참고).


## 13. 13개 SPAC Ticker 재검증 결과

w.md Fix Round 04에서 "asset_type=UNKNOWN, authority=FORMAL_SECURITY_TYPE"이라는
모순된 상태로 남아있던 13개 알파뉴메릭 ticker 전부, 이번 build의 verified live
formal source에서 `SECT_TP_NM == "SPAC(소속부없음)"`으로 명확히 확인되어
`SPAC`으로 갱신됐다. 이는 이름에 "스팩"이 포함된다는 이유의 승격이 아니라,
KRX 공식 소속부 분류 필드를 그대로 읽은 결과다 (`FORMAL_SPAC_CONFIRMED`, 자세한
수치는 완료 보고서 r.md §11.7 참고).


## 14. Manifest

`data/reference/krx_instrument_metadata_manifest.json` — 매 build 실행마다 갱신.
포함 필드: artifact_version, generated_at, effective_date, upstream_authority,
upstream_source_name, upstream_source_location, retrieval_method,
source_snapshot_date, source_checksum_sha256, builder_script, mapping_version,
row_count, ticker_count, verified_snapshot_effective_date, verified_row_count,
asset_type_distribution_verified_rows, unknown_count_verified_rows,
unmapped_formal_category_count_verified_rows,
changed_tickers_vs_prior_committed_value, historical_rows_marked_legacy_unverified,
zero_network_runtime, pit_history_rewrite(수행 안 함, 이유 명시).


## 15. Runtime — Zero Network Rule

`ZERO_NETWORK_RUNTIME = YES` (Stock Report 생성 경로 기준, 변경 없음).
`scripts/build_krx_instrument_metadata.py`는 build-time 전용 스크립트이며
Stock Report runtime 경로(`InstrumentMetadataResolver`, `generate_stock_report`
등) 어디에서도 import/실행되지 않는다. `InstrumentMetadataResolver`는 여전히
로컬 parquet/csv만 읽는다 (`a_fast_core.provenance.network_requests == 0` schema
enum으로 강제).


## 16. Known UNKNOWN / Unsupported Category 정책

Verified rows(2,780개) 중:
- formal source에서 ticker 자체를 못 찾음: 1건 (299900 위지윅스튜디오 — 현재
  상장/ETF/ETN 어디에도 없음. `상폐종목검색`으로 실제 delisted 상태임을 별도
  확인함, 임의 추정 아님).
- formal source는 찾았으나 mapping 불가(UNMAPPED_FORMAL_CATEGORY): 0건 (외국주권/
  주식예탁증권/사회간접자본투융자회사/투자회사 카테고리에 해당하는 verified
  ticker가 이번 스냅샷에는 없었음. 향후 build에서 이런 카테고리가 나타나면
  자동으로 이 정책이 적용된다).


## 17. Historical Metadata Provenance 정책 (신규, w.md §2.13/§11.8)

```
Historical effective_date row의 formal provenance가 실제 검증 가능한가?
→ NO (2026-08-14 제외 전부)
```

- **Verified 기간**: 2026-08-14 단일 snapshot만.
- **Legacy/Unverified 기간**: 2020-03-27 ~ 2025-06-27 (26개 effective_date,
  70,006개 row) — 값은 유지되나 `classification_authority=asset_type_source=
  LEGACY_UNVERIFIED`로 production trust에서 배제됨.
- 향후 과거 시점 formal snapshot을 실제로 확보할 방법(예: KRX가 과거 시점
  기준 조회를 지원하는 별도 API가 있는지)을 찾으면 이 정책을 갱신할 수 있다 —
  이번 라운드에서는 조사하지 않았다.
