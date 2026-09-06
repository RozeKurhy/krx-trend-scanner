krx_instrument_metadata_authority.md

# KRX Instrument Metadata Authority — Lineage & Trust Rule (Fix Round 07)

이 문서는 `InstrumentMetadataResolver`가 Production Asset Type Authority로 사용하는
frozen local artifact의 실제 lineage를 기록한다. 확인 불가능한 부분은 "확인 불가"로
명시하며, 근거 없이 정당화 문구를 채우지 않는다 (w.md Fix Round 04 §4.4, Fix Round
05 §4.4).

Fix Round 04까지는 이 artifact 전체(72,786 row)가 실제로는 어디서 왔는지 저장소
안에서 재현할 수 없는 상태였다(§3 "Fix Round 04 이전 상태" 참고). Fix Round 05는
처음으로 실제 verified upstream formal source에 연결된 build workflow를 만들었으나
verified snapshot의 `effective_date`를 CLI 인자로 임의 과거 날짜에 지정할 수 있어
PIT lookahead corruption을 냈다. Fix Round 06은 이 backdating 경로를 구조적으로
제거하고, checksum 필드 라벨링을 바로잡고, SPAC identity를 SECT_TP_NM 외에
ISU_ENG_NM/ISU_NM 문자열로도 확인하도록 확장했다. Fix Round 07은 세 가지를 다시
고친다: (1) HISTORICAL_LEGACY_RESEARCH eligibility가 미래 시점 정보를 사용하던
survivorship bias, (2) verified snapshot이 이전 baseline ticker 집합의 재분류에
불과해 신규 상장을 누락하던 문제, (3) Round 06의 ISU_ENG_NM/ISU_NM 기반 SPAC
판정이 formal 필드 출처였음에도 방식 자체는 여전히 이름 substring matching이었던
문제.


## 1. Artifact

- `data/reference/krx_instrument_metadata.parquet` (1차 read 대상)
- `data/reference/krx_instrument_metadata.csv` (parquet 없을 때 fallback, 동일 스키마)
- `data/reference/krx_instrument_metadata_manifest.json` (매 build 실행마다 갱신되는
  generation manifest)
- `data/reference/source/krx_instrument_metadata_source_snapshot_<date>.json` — 실제
  upstream 응답을 canonical 직렬화해 보존한 snapshot. manifest의
  `source_snapshot_sha256`을 재계산으로 검증할 수 있는 근거 파일

네 파일은 매 갱신마다 (ticker, effective_date) 기준으로 row-aligned 동일 내용을
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
파일 전체 상수였음이 드러났다.


## 4. Upstream Authority

**UPSTREAM_AUTHORITY** = KRX Market Data Center (data.krx.co.kr), 인증 세션 필요

**UPSTREAM_SOURCE_NAME**:
1. 전종목기본정보 — `bld=dbms/MDC/STAT/standard/MDCSTAT01901`
   ([12005] 전종목 기본정보 페이지의 이면 데이터 API). equity ticker/name/market/
   SECT_TP_NM/KIND_STKCERT_TP_NM/ISU_NM/ISU_ENG_NM 전부 이 source에서 나온다.
2. ETF_전종목기본종목 — `bld=dbms/MDC/STAT/standard/MDCSTAT04601` ([13104] 전종목
   기본정보). ETF ticker + 공식 name(`ISU_ABBRV`) 확보 (Fix Round 07 Major 2).
3. ETN_전종목기본종목 — `bld=dbms/MDC/STAT/standard/MDCSTAT06701` ([13202] 전종목
   등락률). ETN ticker + 공식 name(`ISU_ABBRV`) 확보 (Fix Round 07 Major 2).
4. 상폐종목검색 (delisted finder, `bld=dbms/comm/finder/finder_listdelisu`) —
   현재 미상장(delisted) ticker의 존재 자체를 확인하는 reference 용도로만 사용,
   security type 필드는 제공하지 않음

**SOURCE_LOCATION** = `https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd`
(POST, `bld` 파라미터로 구분)

**ACQUISITION_METHOD** = 인증된 HTTPS 세션(KRX_ID/KRX_PW, `.env`)으로 build-time에만
접근. `dbms/comm/finder/finder_stkisu`(단순 ticker 검색) 같은 공개 endpoint와
달리, `MDCSTAT01901`은 익명 요청 시 본문이 문자 그대로 `"LOGOUT"`인 400 응답을
반환한다 — 즉 이 특정 bld는 실제로 로그인 세션을 요구한다. `KRX_ID`/`KRX_PW`가
없으면 이 build script는 `RuntimeError`로 즉시 실패한다(추측성 fallback 없음).

**SOURCE_OBSERVATION_DATE** = `pd.Timestamp.now(tz="Asia/Seoul")`에서만
파생되는 값으로, CLI로 다른 값을 주입할 방법이 코드에 없다. 새로 검증되는 row의
`effective_date`는 항상 이 값과 동일하다. `effective_date`가 SOURCE_OBSERVATION_DATE가
아닌 모든 row는 매 실행마다 provenance가 `LEGACY_UNVERIFIED`로 낮춰진다(§9).

**CHECKSUM 3분리** — manifest는 세 값을 분리한다:
- `source_snapshot_sha256`: `data/reference/source/`에 저장된 canonical(정렬,
  고정 구분자) source snapshot bytes의 SHA-256 — 실제 upstream 응답(equity+ETF+ETN+
  delisted)의 fingerprint.
- `artifact_csv_sha256` / `artifact_parquet_sha256`: 생성된 산출물 파일 자체의 SHA-256.


## 5. Raw Source Fields

```
전종목기본정보 (equity):
  ISU_SRT_CD           - 6자리(또는 영숫자) 종목코드
  ISU_NM                - 정식 한글 종목명
  ISU_ABBRV             - 공식 약식 종목명 (이 project의 canonical name 표기와 일치)
  ISU_ENG_NM            - 정식 영문 종목명
  MKT_TP_NM              - 시장 (KOSPI / KOSDAQ / KOSDAQ GLOBAL / KONEX)
  SECUGRP_NM             - 증권그룹명: 주권 / 부동산투자회사 / 외국주권 / 주식예탁증권 /
                            사회간접자본투융자회사 / 투자회사
  SECT_TP_NM             - 소속부명: 우량기업부/중견기업부/벤처기업부/기술성장기업부/
                            일반기업부/관리종목(소속부없음)/SPAC(소속부없음)/
                            투자주의환기종목(소속부없음)/외국기업(소속부없음)/공란
  KIND_STKCERT_TP_NM      - 주권종류구분명: 보통주 / 구형우선주 / 신형우선주 / 종류주권

ETF_전종목기본종목 / ETN_전종목기본종목:
  ISU_SRT_CD, ISU_ABBRV  - ticker/name (market 필드 없음 — §11 참고)
```

이 원본 필드들은 canonical artifact에 `source_security_type` 컬럼으로 압축
보존된다 (형식: `SECUGRP_NM=...|SECT_TP_NM=...|KIND_STKCERT_TP_NM=...|ISU_NM=...|ISU_ENG_NM=...`)
— 단 Verified rows(§8)에 한해서만 채워지며, 과거 legacy row는 빈 값이다 (§9).


## 6. Source Category → AssetType Deterministic Mapping (Fix Round 08 갱신)

`scripts/build_krx_instrument_metadata.py`의 `map_row_to_asset_type()` 실제 로직,
우선순위 순서(w.md Fix Round 08 §1/§2/§3):

```
[ETF/ETN — live product master membership, map_row_to_asset_type() 호출 이전]
ticker ∈ live ETF universe  → ETF
ticker ∈ live ETN universe  → ETN

[SPAC identity — SECT_TP_NM 단독, 이름 substring 완전 배제]
SECT_TP_NM에 "SPAC" 포함                              → SPAC

SECUGRP_NM == "부동산투자회사"                        → REIT
KIND_STKCERT_TP_NM == "보통주"
  AND SECT_TP_NM in {"관리종목(소속부없음)"}
  AND 이 ticker가 canonical 이력 어딘가에 SPAC으로 기록된 적 있음
                                                       → UNKNOWN (asset_type_source=INSUFFICIENT_FORMAL_IDENTITY)
KIND_STKCERT_TP_NM == "보통주" (그 외)                → COMMON
KIND_STKCERT_TP_NM in ("구형우선주", "신형우선주")     → PREFERRED
그 외 (외국주권 / 주식예탁증권 / 사회간접자본투융자회사 /
투자회사 / 종류주권 등)                                → UNKNOWN
                                                          (classification_authority=FORMAL_SECURITY_TYPE,
                                                           asset_type_source=UNMAPPED_FORMAL_CATEGORY)

formal source에서 ticker 자체를 못 찾음                → UNKNOWN
                                                          (classification_authority=UNKNOWN,
                                                           asset_type_source=UNKNOWN)
```

### 6.1 Production AssetType에서 이름 Substring Matching 완전 제거 (Fix Round 08 Major 1)

Fix Round 07에서 SPAC에 대해 종목명 substring matching을 제거한 것에 이어, Fix Round 08에서는
`종류주권` 판정(`if kind == "종류주권" and "우선주" in isu_nm:`)을 포함한 **모든 종목명 substring matching
휴리스틱을 production authority에서 완전히 제거했다 (`NAME_HEURISTIC_USED_FOR_PRODUCTION_ASSET_TYPE = NO`).**

- `KIND_STKCERT_TP_NM in ("구형우선주", "신형우선주")` (101건): KRX 공식 주권종류구분 코드 자체가
  우선주를 명시하므로 이름과 무관하게 `PREFERRED`로 정식 분류된다.
- `KIND_STKCERT_TP_NM == "종류주권"` (12건, e.g. 02826K 삼성물산우B, 03473K SK우 등):
  KRX 전종목기본정보에서 종목명(ISU_NM)과 독립적인 우선주 전용 formal code가 제공되지 않는다.
  이름에 "우선주"가 들어있다는 이유로 추측하거나 휴리스틱을 쓰지 않고, 규정에 따라
  `UNKNOWN` + `UNMAPPED_FORMAL_CATEGORY` (`is_trusted_for_production=False`)로 fail closed한다.

### 6.2 KRX Market Normalization: KOSDAQ GLOBAL → KOSDAQ (Fix Round 08 Major 2)

KRX raw 응답의 `MKT_TP_NM` 중 `"KOSDAQ GLOBAL"`은 독립된 시장이 아니라 코스닥 시장 내부의
세그먼트(우량기업 세그먼트)이다. 프로젝트 canonical `MarketType` enum은 `KOSPI`, `KOSDAQ`, `KONEX`, `UNKNOWN`으로
정의되어 있으므로, centralized canonical 함수 `normalize_krx_market()`를 통해 정규화한다:

- `KOSPI` → `KOSPI`
- `KOSDAQ` → `KOSDAQ`
- `KOSDAQ GLOBAL` → `KOSDAQ`
- `KONEX` → `KONEX`
- 그 외 / None → `UNKNOWN`

이 정규화는 `InstrumentMetadataResolver.resolve()`와 `scripts/build_krx_instrument_metadata.py` 모두에
적용되며, canonical CSV/parquet의 과거 및 현재 전체 77,193개 row에서 `KOSDAQ GLOBAL`이 0건으로 정규화되었다.

### 6.3 Former SPAC + 관리종목 Taxonomy 일치 (Fix Round 08 Minor 1)

KRX formal taxonomy 전수 검증 결과, 관리 관련 `SECT_TP_NM` 값은 오직 `"관리종목(소속부없음)"` 하나뿐이다
(`MANAGED_ISSUE_SECTIONS = {"관리종목(소속부없음)"}`).
- 과거 SPAC 이력이 있으면서 현재 `SECT_TP_NM="관리종목(소속부없음)"`인 종목(465320, 471050, 472220)은
  합병/전환 여부의 formal 근거 부족으로 `UNKNOWN` (`INSUFFICIENT_FORMAL_IDENTITY`) fail closed된다.
- SPAC 이력이 없는 일반 보통주 관리종목은 정상적으로 `COMMON` (`FORMAL_SECURITY_TYPE`)을 유지한다.
- 정상적으로 합병 전환된 369370(현재 SECT_TP_NM="벤처기업부")은 관리종목이 아니므로 깨끗한 COMMON 전환이 유지된다.


## 7. Builder Script

```
BUILDER_SCRIPT   = scripts/build_krx_instrument_metadata.py
MAPPING_VERSION  = v4
```

역할 (Fix Round 07/08 — live universe 전체에서 생성, 이름 휴리스틱 0건):

```
FETCH LIVE FORMAL SOURCES (equity + ETF + ETN)
        ↓
BUILD CURRENT LIVE SUPPORTED UNIVERSE (live 전체의 union, dedup, market 정규화)
        ↓
CLASSIFY EACH LIVE INSTRUMENT (code field 단독 판정, 이름 substring 완전 배제)
        ↓
CREATE NEW CURRENT SNAPSHOT (effective_date = SOURCE_OBSERVATION_DATE)
        ↓
COMPARE AGAINST PRIOR BASELINE (신규상장/상장폐지/asset_type 변경 diff만)
        ↓
APPEND CURRENT SNAPSHOT, PRESERVE ALL HISTORICAL ROWS (market 정규화)
        ↓
WRITE CSV + PARQUET + RAW SOURCE SNAPSHOT + MANIFEST
```

Fix Round 06까지는 "가장 최근 기존 snapshot(baseline)의 ticker 집합을 live
source에서 재분류"하는 구조였다 — baseline에 없는 신규 상장 종목은 verified
snapshot에 절대 들어갈 수 없었고, name/market도 baseline에서 그대로 복사해
왔다. 이제 baseline은 diff(신규상장/상장폐지 감지)와 §6.2 SPAC ambiguity 감지
용도로만 쓰이며, current snapshot membership의 authority가 아니다.

**`--as-of-date` 같은 날짜 주입 CLI 인자는 존재하지 않는다** (Fix Round 06
Critical 1, 유지). `--dry-run`으로 파일을 쓰지 않고 변경 미리보기 가능. 같은 날
재실행하면 기존 SOURCE_OBSERVATION_DATE row를 교체하는 idempotent upsert로
동작한다.


## 8. Verified Snapshot 범위

이번 build가 실제로 검증한 것은 **build 실행 시점(SOURCE_OBSERVATION_DATE)의 KRX
실시간 상장 상태** 하나뿐이다. 이제 이 snapshot은 이전 baseline ticker 집합이
아니라 live formal universe(equity + ETF + ETN) 전체를 포괄한다. 과거로 거슬러
올라가는 historical formal snapshot을 제공하는 API는 확인하지 못했다(§17).

이 값은 고정 상수가 아니라 매 build 실행마다 달라진다 — 최신 값은
`data/reference/krx_instrument_metadata_manifest.json`의
`verified_snapshot_effective_date`를 확인한다. 테스트 코드 역시 이 값을
manifest에서 동적으로 읽는다(하드코딩 날짜를 쓰지 않는다).


## 9. Historical Row 정책 (PIT History Rewrite 금지 및 Market Canonicalization)

**과거 effective_date row의 AssetType 값은 소급 재작성(history rewrite)하지 않고 그대로 보존한다 (`asset_type_history_rewrite = "NOT_PERFORMED"`).**
오늘 시점 조회 결과로 과거 snapshot의 asset_type을 소급 덮어쓰는 것은 절대 금지되어 있으며, historical row는 기존 asset_type 값을 유지한다.
단, 시장 구분의 canonical 정규화(`KOSDAQ GLOBAL` -> `KOSDAQ`, 696건)는 프로젝트 일관성을 위해 수행되었다 (`historical_market_normalization = "PERFORMED"`, `historical_market_normalized_row_count = 696`).

다만 provenance는 정직하게 낮춘다: SOURCE_OBSERVATION_DATE가 아닌 모든 row의
`classification_authority`/`asset_type_source`를 `"LEGACY_UNVERIFIED"`로
설정한다.

`InstrumentMetadata.is_trusted_for_production`은 이 값이 아니면
(`FORMAL_SECURITY_TYPE`이어야만) trusted로 인정하므로, historical row는 항상
자동으로 fail closed된다 — asset_type 자체(COMMON/SPAC 등)는 여전히 기존 PIT
로직으로 정확히 조회된다(§10).


## 9.1 HISTORICAL_LEGACY_RESEARCH 모드 (Fix Round 07 Major 1로 재정의)

Fix Round 06은 `InstrumentMetadata.is_eligible_for_historical_legacy_research`를
"이 ticker가 requested_as_of *이후*에 실제로 formal 재검증된 적이 있는가"
(`has_later_verified_snapshot`)로 판단했다. 이는 **survivorship bias**였다:
미래까지 살아남아 다시 검증된 ticker만 retrospective 분석이 가능해지고, 상장
폐지되어 다시 검증될 기회가 없었던 ticker(예: 380440)는 동일한 품질의
historical metadata를 가지고도 부당하게 배제됐다. 또한 이 판단 자체가 미래
시점의 정보를 과거 시점 조회의 eligibility 결정에 사용하는 것이라 Strict PIT
정신에도 어긋난다.

Fix Round 07부터 이 판단은 **오직 선택된(selected) PIT row 자체의 값**만 본다
— 미래의 다른 row는 전혀 조회하지 않는다:

```
selected requested_as_of PIT row가:
  is_identified == True
  AND classification_authority == "LEGACY_UNVERIFIED"
  AND asset_type_source == "LEGACY_UNVERIFIED"
  AND asset_type != "UNKNOWN"
→ metadata_provenance_mode = HISTORICAL_LEGACY_RESEARCH (전략 retrospective 계산 허용)

selected row가 FORMAL_SECURITY_TYPE
→ metadata_provenance_mode = CURRENT_VERIFIED

selected row가 UNKNOWN / LEGACY_HEURISTIC / NAME_BASED_HEURISTIC / asset_type UNKNOWN
→ metadata_provenance_mode = DATA_UNAVAILABLE
```

중요: `LEGACY_HEURISTIC`/`NAME_BASED_HEURISTIC`은 `HISTORICAL_LEGACY_RESEARCH`로
승격되지 않는다 — canonical frozen PIT snapshot이 아니라 그보다 신뢰도가 낮은
별도 종류의 추정치이기 때문이다.

`HISTORICAL_LEGACY_RESEARCH`는 A FAST Core 전략 계산을 정상적으로 수행하되(가격/
계약 데이터는 실제 그대로), Stock Report의 `a_fast_core.metadata_provenance_mode`
필드로 이 판정이 production 신뢰가 아니라 retrospective 연구용임을 명시적으로
구분해 표시한다. w.md §4.5가 금지하는 것은 "오늘 시점" 판단에 legacy metadata를
trusted로 쓰는 것이지, 과거 조회 자체를 계산하는 것이 아니다.

380440(상장폐지, 재검증 기회 자체가 없음)은 이제 정상적으로
HISTORICAL_LEGACY_RESEARCH 자격을 얻는다 — future survival 여부와 무관하다.

이 모드는 `tests/test_a_fast_core_stock_report.py`의 PIT/execution-boundary
전략 테스트(`test_a_fast_core_uses_requested_as_of_only`,
`test_a_fast_core_pending_entry_next_open`, `test_a_fast_core_execution_boundary`)를
metadata trust를 강제로 override하는 테스트 헬퍼 없이 실제 production 경로
(`generate_stock_report`)로 직접 검증한다.


## 10. PIT Selection Rule (코드로 검증 가능, 선택 알고리즘 자체는 변경 없음)

`InstrumentMetadataResolver.resolve()` (src/trend_scanner/universe/instrument_metadata.py):

1. `ticker`로 후보 row 전체를 찾는다 (여러 effective_date 스냅샷 존재 가능).
2. `requested_as_of`가 주어지면, `effective_date <= requested_as_of`인 row만 남긴다.
3. 남은 것 중 `effective_date`가 가장 늦은 row 하나를 선택한다.
4. 후보가 없으면 `is_identified=False`, 전부 UNKNOWN으로 fail closed.

Fix Round 07은 이전에 있던 5번째 단계(`requested_as_of` 이후 FORMAL row 존재
여부를 조회해 `has_later_verified_snapshot`을 계산하던 로직)를 완전히
제거했다 — §9.1에 따라 더 이상 미래 row를 조회하지 않는다. 선택 알고리즘
1~4는 Fix Round 05/06/07 어느 라운드에서도 수정하지 않았다.


## 11. Trust Rule (변경 없음, Fix Round 04에서 구현)

```
is_identified == True
AND classification_authority == "FORMAL_SECURITY_TYPE"
AND asset_type_source == "FORMAL_SECURITY_TYPE"
AND asset_type != "UNKNOWN"
```

ETF/ETN의 market 필드에 대한 주석: `ETF_전종목기본종목`/`ETN_전종목기본종목`
응답에는 KOSPI/KOSDAQ을 구분하는 필드가 없다 — 이는 baseline 복사가 아니라
KRX 시장 구조 자체의 사실이다(ETF/ETN 상품은 전부 KOSPI 시장 구분 아래
상장된다). 이 project는 이를 상수 `ETX_MARKET = "KOSPI"`로 표현한다
(개별 종목 필드가 아니라 상품군 전체에 적용되는 일반 사실).


## 12. Fail Closed Rule

- `asset_type == UNKNOWN` → 항상 fail closed.
- `classification_authority`/`asset_type_source`가 `FORMAL_SECURITY_TYPE`이 아님
  (`UNKNOWN` / `LEGACY_HEURISTIC` / `LEGACY_UNVERIFIED`) → `asset_type`이 COMMON
  이라도 fail closed(§9.1의 selected-row-only 규칙에 따라 판정).
- formal source는 확인됐으나 mapping이 불가능한 category(`UNMAPPED_FORMAL_CATEGORY`)
  → fail closed.
- 관리종목 전환 + canonical 이력에 SPAC 기록이 있으나 현재 formal SPAC 증거가
  없는 경우(`INSUFFICIENT_FORMAL_IDENTITY`) → fail closed(§6.2).
- 이름 문자열 heuristic으로 UNKNOWN을 COMMON/SPAC 등으로 승격하지 않는다.
  `HEURISTIC_PROMOTION_COUNT = 0` — SPAC은 오직 `SECT_TP_NM` formal field로만
  확인된다(§6.1, ISU_ENG_NM/ISU_NM substring은 더 이상 사용하지 않음).


## 13. SPAC Ticker 재검증 결과

Fix Round 04에서 "asset_type=UNKNOWN, authority=FORMAL_SECURITY_TYPE"이라는
모순된 상태로 남아있던 13개 알파뉴메릭 ticker 전부, `SECT_TP_NM ==
"SPAC(소속부없음)"`으로 명확히 확인되어 `SPAC`으로 유지된다(Fix Round 05에서
최초 확인, 실측 재확인 결과 13개 모두 현재도 SECT_TP_NM=SPAC 유지).
465320/471050/472220은 Fix Round 06에서 ISU_ENG_NM/ISU_NM 근거로 SPAC 유지로
"수정"됐었으나, Fix Round 07에서 그 근거가 이름 substring matching이었음을
인정하고 UNKNOWN + INSUFFICIENT_FORMAL_IDENTITY로 fail closed 재정정했다(§6.2).


## 14. Manifest

`data/reference/krx_instrument_metadata_manifest.json` — 매 build 실행마다 갱신.
포함 필드: artifact_version, generated_at, effective_date, upstream_authority,
upstream_source_name, upstream_source_location, retrieval_method,
source_snapshot_date, source_snapshot_path, source_snapshot_sha256,
artifact_csv_sha256, artifact_parquet_sha256, builder_script, mapping_version,
row_count, ticker_count, verified_snapshot_effective_date,
verified_snapshot_baseline_date, verified_row_count,
asset_type_distribution_verified_rows, unknown_count_verified_rows,
unmapped_formal_category_count_verified_rows,
insufficient_formal_identity_count_verified_rows(신규),
changed_tickers_vs_baseline_committed_value, historical_rows_marked_legacy_unverified,
zero_network_runtime, backdating_prevention,
asset_type_history_rewrite, historical_market_normalization,
historical_market_normalized_row_count, pit_history_rewrite,
current_live_universe(신규 — live_equity_count, live_etf_count, live_etn_count,
live_supported_unique_tickers, current_canonical_rows, baseline_ticker_count,
new_listing_count, new_listing_tickers, removed_from_live_count,
removed_from_live_tickers, common_ticker_count, current_coverage_missing_count,
baseline_name_copied_to_current=false, baseline_market_copied_to_current=false).


## 15. Runtime — Zero Network Rule

`ZERO_NETWORK_RUNTIME = YES` (Stock Report 생성 경로 기준, 변경 없음).
`scripts/build_krx_instrument_metadata.py`는 build-time 전용 스크립트이며
Stock Report runtime 경로(`InstrumentMetadataResolver`, `generate_stock_report`
등) 어디에서도 import/실행되지 않는다. `InstrumentMetadataResolver`는 여전히
로컬 parquet/csv만 읽는다 (`a_fast_core.provenance.network_requests == 0` schema
enum으로 강제).


## 16. Known UNKNOWN / Unsupported Category 정책

Verified rows 중 (Fix Round 07 live universe 전체 기준):
- formal source에서 ticker 자체를 못 찾음: 0건 (live universe 자체에서 verified
  row를 만들므로 이 category는 구조적으로 발생하지 않는다 — §3.11 coverage
  invariant, `CURRENT_COVERAGE_MISSING_COUNT = 0`으로 매 build마다 검증됨).
- formal source는 찾았으나 mapping 불가(UNMAPPED_FORMAL_CATEGORY): 실제 build
  결과는 manifest의 `unmapped_formal_category_count_verified_rows` 참고.
- 관리종목 전환 + SPAC 이력 있음(INSUFFICIENT_FORMAL_IDENTITY): 3건
  (465320/471050/472220, §6.2).
- 299900(위지윅스튜디오)는 live universe 자체에 없어(REMOVED_FROM_LIVE) verified
  row가 생성되지 않는다 — historical row는 그대로 보존된다(§3.7 delisted 정책).


## 17. Historical Metadata Provenance 정책

```
Historical effective_date row의 formal provenance가 실제 검증 가능한가?
→ NO (매 build 실행 시점의 SOURCE_OBSERVATION_DATE 제외 전부)
```

- **Verified 기간**: 매 build 실행 시점의 SOURCE_OBSERVATION_DATE 단일 snapshot만.
- **Legacy/Unverified 기간**: 그 이전 모든 effective_date — 값은 유지되나
  `classification_authority=asset_type_source=LEGACY_UNVERIFIED`로 production
  trust에서 배제됨. §9.1의 HISTORICAL_LEGACY_RESEARCH 모드(selected-row-only
  규칙)로 retrospective 연구 용도로는 future survival 여부와 무관하게 사용
  가능.
- 향후 과거 시점 formal snapshot을 실제로 확보할 방법을 찾으면, Option A(과거
  시점도 실제로 formal 재검증)로 이 정책 자체를 갱신할 수 있다 — 아직 그런
  API를 발견하지 못했다(Option B로 §9.1을 도입해 대응함).


## 18. Historical Universe Reconciliation — 별도 모듈, 별도 SECURITY_TYPE_MAPPING

**주의: 이 섹션은 `InstrumentMetadataResolver`(§1-17, live 현재 시점 전용)가 아니라
별도 모듈인 `trend_scanner.universe.historical_authority_reconciliation`
(`SECURITY_TYPE_MAPPING`)의 정책을 기록한다.** 두 모듈은 같은 KRX Basic Info
공식 필드(SECUGRP_NM/KIND_STKCERT_TP_NM/SECT_TP_NM)를 사용하지만 독립적으로
유지된다 — 이 섹션의 규칙 변경이 §6의 live mapping을 바꾸지 않으며 그 반대도
마찬가지다.

`HISTORICAL_UNIVERSE_AUTHORITY_UNRESOLVED_RESOLUTION_V01`에서 production
Basic Info 8190쌍 실데이터로 처음 발견된 4개 classification gap을 다음과 같이
해소했다 (frozen target 1,116 기준):

### 18.1 SPAC 이력 + 후속 관리종목 — chronological exception (122건 중 8건 해소)

기존 규칙(FIX01 Minor): 이 identity 이력 어딘가에 SPAC 관측이 있고 현재
`보통주+관리종목(소속부없음)`이면 UNKNOWN. 이 규칙이 실 데이터에서 122건에
발동했으나, 그중 114건은 SPAC 종료 후 단 한 번도 명확한 non-SPAC COMMON
구간이 관측되지 않은 채 바로 관리종목 상태로 전환된 사례였고, 8건만
SPAC → (수년~10년의) 명확한 COMMON 구간 → 관리종목의 구조였다.

개정 규칙(`_classify_observations`): SPAC 이력이 있어도, 그 이후 chronological
순서상 명확한 non-SPAC COMMON 관측이 한 번이라도 확인되면 그 identity는
"COMMON lineage 확정"으로 간주하고, 그 이후의 관리종목 관측은 더 이상
SPAC-이력 예외로 fail-close하지 않는다(정상 COMMON으로 해소). 반대로 SPAC 이후
COMMON 확정 전에 나타나는 관리종목 관측은 계속 fail-closed UNKNOWN이다.
임의 시간 임계값(N년 등)은 사용하지 않는다 — 오직 명시적 lifecycle 순서만
사용한다.

- 8건: COMMON lineage 확정 → HISTORICAL_COMMON_REQUIRED로 해소.
- 114건: 명시적 COMMON 구간 없음 → 계속 HISTORICAL_AUTHORITY_UNRESOLVED.

### 18.2 선박투자회사 (Ship Investment Company) — NOT_COMMON (49건)

SECUGRP_NM="선박투자회사"는 §6의 live mapping 카탈로그(주권/부동산투자회사/
외국주권/주식예탁증권/사회간접자본투융자회사/투자회사)에 없는 값이다 — 현재
live universe에 선박투자회사 종목이 전혀 없어 한 번도 관측되지 못했을 뿐,
historical raw에는 2010~2023년 사이 49건이 존재한다(전부 단일 상태,
identity 충돌 없음).

`docs/patterns/pattern_a/validation/universe_quality_v01.md` §2.1이 이미
부동산투자회사(REIT)를 "배당 중심 구조로 일반 추세 스캐너 대상에서 제외"라는
명시적 원칙으로 배제한다. 선박투자회사법 역시 특정 자산(선박)을 보유하며
용선료 수익 대부분을 배당으로 분배하도록 강제하는 특별법 기반 pooled
investment vehicle로, REIT와 동일한 배당 중심 구조 원칙에 해당한다. 이름이나
ticker 추정이 아니라 이 기존 원칙의 직접 적용이다.

`_DIVIDEND_FOCUSED_INVESTMENT_VEHICLE_GROUPS = {부동산투자회사, 선박투자회사}`
→ HISTORICAL_NOT_COMMON.

### 18.3 종류주권 — 정책 유지, UNKNOWN 그대로 (14건, 미해소)

§6.1(Fix Round 08 Major 1)이 이미 정확히 이 값(KIND_STKCERT_TP_NM="종류주권")에
대해 이름 substring heuristic(`"우선주" in isu_nm`)을 의도적으로 제거하고
UNKNOWN + `UNMAPPED_FORMAL_CATEGORY`로 fail-close하기로 결정한 전례가 있다.
historical reconciliation에서도 동일한 근거(공식 필드만으로는 종류주권 내부의
실제 우선주/기타 클래스 구분이 불가능함)로 이 값을 매핑하지 않고 UNKNOWN으로
유지한다 — §6.1의 이미 검토된 정책과의 일관성이 이유이며, 새 heuristic이
아니다. 14건 전부 다른 구간에 COMMON 이력이 없어 lifecycle 규칙으로도
구제되지 않는다.

### 18.4 주식예탁증서 — 주식예탁증권의 구 명칭 (5건 전부 해소)

950010/950100/950110 세 종목 모두 SECUGRP_NM이 2014-03-03에 "주식예탁증서"에서
"주식예탁증권"으로 정확히 동일한 날짜에 전환되며(동일 ISU_CD, 동일 ISU_ABBRV),
2014-03-03 이전에 상장폐지된 나머지 2건(950030/950070)은 "주식예탁증서"만
관측된다. 이는 KRX 공식 용어 개정(2014-03-03 cutover)이지 별도 카테고리가
아니라는 명확한 증거다 — fuzzy 문자열 매칭이 아니라 exact value 추가.

`_COMMON_GROUPS`에 "주식예탁증서" 추가 → 5건 전부 HISTORICAL_COMMON_REQUIRED.

### 18.5 결과 요약

| gap | 건수 | 해소 | 근거 |
|---|---|---|---|
| SPAC 이력+관리종목 | 122 | 8 COMMON / 114 UNRESOLVED 유지 | chronological lifecycle (§8.1) |
| 선박투자회사 | 49 | 49 NOT_COMMON | REIT 배당중심구조 원칙 적용 (§18.2) |
| 종류주권 | 14 | 0 (UNRESOLVED 유지) | §6.1 기존 fail-closed 정책과 일관성 |
| 주식예탁증서 | 5 | 5 COMMON | KRX 용어 개정 확인 (§18.4) |

숫자를 0으로 맞추기 위한 조정은 없었다 — 종류주권 14건과 SPAC 114건은 근거
부족으로 계속 UNRESOLVED다.

## 19. Supplemental Authority Layer — KRX Basic Info 만으로 부족한 residual 해소

`HISTORICAL_UNIVERSE_RESIDUAL_AUTHORITY_RESOLUTION_V01`에서 §18의 잔여
128건(SPAC 114 + 종류주권 14)을 KRX Basic Info 외부의 공식 source(OpenDART
공시, KRX 공식 종목명 필드)로 개별 조사하여 해소했다.

**Primary authority(KRX PIT Basic Info)는 절대 수정하지 않는다.** 대신 별도
supplemental authority layer를 두어, 개별적으로 조사된 identity에 한해서만
분류를 override한다.

### 19.1 구조

- 위치: `data/reference/source/history/krx_instrument_master/v01/supplemental_authority/`
  - `spac_residual_resolution_v01.json` (114 records)
  - `preferred_class_residual_resolution_v01.json` (14 records)
- 각 record는 `(target_ticker, isu_cd)`로 identity를 특정하고, `authority_source`
  (OpenDART 등), `official_document_id`(DART rcept_no), `authority_date`,
  `evidence_summary`, `decision`(`COMMON`/`NOT_COMMON`/`INSUFFICIENT`),
  `decision_reason_code`를 기록한다.
- `load_supplemental_authority_records()`가 이 디렉터리를 `(ticker, isu_cd) ->
  record` lookup으로 로드한다. 디렉터리가 없거나 record가 없으면 빈 lookup —
  묵시적 해소는 절대 없다(fail-closed 기본값).
- `_classify_observations()`가 두 지점에서만 이 lookup을 참조한다:
  1. SPAC-이력 관리종목 예외(§18.1)가 발동한 관측 — `(ticker, isu_cd)` 일치하는
     record가 있으면 그 record의 `decision`으로 override.
  2. `UNKNOWN_SECURITY_TYPE_VALUE`로 남은 관측(종류주권 등) — 동일하게 override.
- 다른 모든 관측(다른 identity, 다른 gap)은 이 layer의 영향을 전혀 받지 않는다
  — record가 없는 identity는 기존 §18 규칙 그대로 통과한다.
- `decision`이 `INSUFFICIENT`이거나 인식되지 않는 값이면 classification은
  바뀌지 않고 `classification_reason`만 `SUPPLEMENTAL_AUTHORITY_STILL_INSUFFICIENT`
  (또는 record의 값)로 갱신된다 — "조사했지만 근거 불충분"이라는 사실 자체를
  추적 가능하게 남긴다.

### 19.2 SPAC 114건 결과 (OpenDART 공시 기반)

DART corpCode 레지스트리로 114개 ticker 전부 corp_code를 식별(stock_code exact
match, 100% 매칭)한 뒤 각 corp의 공시 목록을 조회했다.

| 결과 | 건수 | 근거 |
|---|---|---|
| NOT_COMMON (해산 확정) | 110 | DART "주요사항보고서(해산사유발생)" 등 공식 해산 공시 — SPAC이 법정 기한 내 합병을 완료하지 못하고 해산 |
| NOT_COMMON (합병 소멸) | 1 | 거래정지 사유 "SPAC 소멸합병" + 이후 공시 완전 중단 + DART corp_name 미변경 — 이 identity 자체는 합병으로 소멸되어 독립적 common lineage로 이어지지 않음 |
| INSUFFICIENT (UNRESOLVED 유지) | 3 | 465320(합병 결정 후 철회, 기업 존속 중), 471050/472220(합병/해산 관련 공시 자체가 없음, 존속 중) — 확정적 결론을 내릴 공식 근거 없음 |

114건 전부 최소 1건 이상의 공식 DART 공시를 확인했다(공시가 전혀 없는 경우도
"공시 없음"이라는 사실 자체가 조회 결과다). 합병 완료(Q1=YES) + 공식 common
lineage 확정(Q2=YES) 사례는 0건이었다 — 114건 중 어느 것도 COMMON으로
승격되지 않았다. "SPAC은 대부분 합병했을 것"이라는 추정이 아니라 실제 조회
결과가 반대(대부분 해산)임을 보여준다.

### 19.3 종류주권 14건 결과 (KRX 공식 종목명 + DART 사업보고서)

14건 전부 KRX Basic Info의 `ISU_NM`(공식 전체 종목명, ticker suffix가 아닌
KRX가 직접 부여하는 정식 명칭)이 "OOO우선주" 형태임을 확인했다. 이는 §20에서
금지하는 ticker suffix(K/5/7/우/우B/신형) 추정이 아니라 KRX가 공식적으로
발행하는 종목명 필드 자체다.

12건은 발행사의 DART 사업보고서 "주식의 총수 현황"이 `보통주`/`우선주`를 별도
항목으로 명시했다(예: 삼성물산 FY2025 — 보통주 169,976,544주 / 우선주
1,467,590주). SK/DL이앤씨 2건은 이 보고서의 항목명이 다르게 표기되어(의결권
있는/없는 주식, 보통주식/기타주식) 추가로 DART 배당사항(alotMatter)의
`stock_knd`별 배당 라인을 확인해 우선주 계열로 재확인했다(예: SK 보통주
8,000원/우선주 8,050원).

14건 전부 → HISTORICAL_NOT_COMMON.

### 19.4 결과 요약

| gap | 건수 | 해소 | 근거 |
|---|---|---|---|
| SPAC 잔여 114 | 114 | 111 NOT_COMMON / 3 UNRESOLVED 유지 | DART 해산/합병소멸 공시 (§19.2) |
| 종류주권 14 | 14 | 14 NOT_COMMON | KRX ISU_NM + DART 사업보고서/배당사항 (§19.3) |

재실행 후 `HISTORICAL_AUTHORITY_UNRESOLVED = 3`(465320/471050/472220) —
공식 근거가 존재하지 않는 case만 UNRESOLVED로 남았고, 숫자를 0으로 맞추기
위한 조정은 없었다.

### 19.5 Interval 병합과 reason 보존

`_intervalize()`의 구간 병합 키에 `classification_reason`을 추가했다(기존에는
`classification` 값만 비교). 이유: supplemental override로 인해 같은
`classification`(예: NOT_COMMON)이지만 reason이 다른(예: 원래 SPAC 구간의
`TIER_A_NON_COMMON_SECURITY_TYPE` vs override된 관리종목 구간의
`SUPPLEMENTAL_AUTHORITY_SPAC_DISSOLUTION_CONFIRMED`) 두 관측이 달력상
인접하면, reason을 구간 병합 키에서 빼는 기존 로직은 이 둘을 하나의 구간으로
합쳐 supplemental 근거를 결과물에서 지워버렸다(§33 traceability 위반). 이
수정은 순수 표현/추적성 수정이며 어떤 ticker의 최종 classification도 바꾸지
않는다.

## 20. AS-OF-Cutoff SPAC Semantics — "아직 해산 안 됨" ≠ "근거 부족"

`HISTORICAL_UNIVERSE_FINAL_RESIDUAL_SPAC_RESOLUTION_V01`에서 §19의 잔여
3건(465320/471050/472220)이 계속 UNRESOLVED로 남아있던 원인은 evidence
부족이 아니라 **잘못 설정된 판정 기준**이었다 — "공식 해산/합병완료 확정
evidence가 있어야만 결론을 낼 수 있다"는 암묵적 전제 자체가 project
denominator semantics와 맞지 않았다.

### 20.1 핵심 원칙: ACTIVE SPAC은 POSITIVE NOT_COMMON EVIDENCE다

`HISTORICAL_NOT_COMMON`은 "결국 그 종목이 사라졌다/해산됐다"는 terminal
label이 아니다. 의미는: **해당 historical interval에서 일반 common-stock
strategy denominator 대상이 아니다**. 이 project의 기존 policy상 SPAC은
common-stock denominator에서 제외된다(§18.1 참조 — SPAC 자체 관측은 이미
row-level에서 `TIER_A_NON_COMMON_SECURITY_TYPE`로 NOT_COMMON). 따라서:

- "이 identity가 frozen cutoff(2026-08-21)까지 공식적으로 SPAC 상태를
  유지했다"는 사실 자체가 NOT_COMMON의 **적극적 근거**다.
- "아직 해산/합병완료 공시가 없다"는 이 판정을 막는 장애물이 아니다 —
  오히려 "아직 common-equity로 전환되지 않았다"는 것을 보강한다.
- 반대로 COMMON으로 승격하려면 반드시 explicit한 공식 merger-completion +
  common-equity lineage 확인이 필요하다(§18.1 원칙 그대로 유지, 완화 없음).
- 미래(cutoff 이후) event는 과거 cutoff 판정에 소급 적용하지 않는다 — 판정은
  항상 "AS-OF 2026-08-21 기준 이 identity가 무엇이었는가"에 대한 답이다.

### 20.2 3건 최종 판정

| ticker | 상태(cutoff 기준) | 핵심 근거 | 최종 |
|---|---|---|---|
| 465320 (교보15호스팩) | 합병 결정 → 공식 철회(2026-07-31), SPAC 정체성 유지 | 반기보고서(2026.06, 2026-08-14 제출) 등 cutoff 이전 문서 전부 SPAC corp_name 유지, COMMON 전환 없음 | `SUPPLEMENTAL_AUTHORITY_MERGER_WITHDRAWN_SPAC_IDENTITY_PRESERVED` → NOT_COMMON |
| 471050 (대신밸런스제17호스팩) | 상장폐지 사유발생 거래정지(2026-08-19) + 청산 관련 안내(2026-08-21), 정식 해산보고서는 cutoff까지 미제출 | 법인 청산 절차 완료 여부와 security denominator 판정은 별개 질문(§10) — 절차 개시 + SPAC 정체성 유지 + COMMON 전환 없음으로 충분 | `SUPPLEMENTAL_AUTHORITY_SPAC_TERMINATION_IN_PROGRESS_NO_COMMON_TRANSITION` → NOT_COMMON |
| 472220 (신영스팩10호) | 합병/해산 이벤트 자체 없음, cutoff까지 활동 중인 평범한 SPAC | 반기보고서(2026.06, 2026-08-10 제출)까지 SPAC corp_name 유지, COMMON 전환 없음 | `SUPPLEMENTAL_AUTHORITY_ACTIVE_SPAC_AT_HISTORICAL_CUTOFF` → NOT_COMMON |

3건 모두 cutoff(2026-08-21) **이전** 날짜의 공식 DART 문서만 근거로 사용했다
— cutoff 이후 발간된 문서(예: 471050/472220의 2026-08-22 이후 "상장폐지
우려 예고")는 미래 정보 소급 적용을 막기 위해 evidence에서 명시적으로
제외했다.

**주의 (interval 경계 vs authority_date는 서로 다른 것을 가리킨다):**
재실행된 `preflight_summary.json`에서 이 3건의 interval 경계일(예: 471050의
2026-07-20, 472220의 2026-07-30)은 supplemental record의 `authority_date`/
`event_effective_date`(예: 471050 2026-08-19, 472220 2026-08-10)와 다르다.
이는 모순이 아니다 — interval 경계는 primary KRX Basic Info의
`SECT_TP_NM`이 SPAC 소속부에서 관리종목(소속부없음)으로 실제 전환된 날짜(1차
authority가 결정)이고, `authority_date`는 그 관리종목 상태를 NOT_COMMON으로
판정하는 데 사용한 supplemental 문서의 발간일(2차 authority가 결정)이다. 두
날짜는 서로 다른 질문에 답하며 일치할 필요가 없다.

### 20.3 Future Event Leakage 방지

이 semantic 수정은 코드 로직 변경이 아니라 **판정 기준(record 작성 원칙)의
수정**이다 — `_classify_observations`/`_apply_supplemental_authority`는
그대로이며, supplemental record의 `decision` 값 해석 방식도 동일하다.
resolver 자체는 날짜 기반 cutoff 로직을 갖고 있지 않다 — 각 record는 그것이
attach된 특정 관측(observation)만 override하며, 그 관측 자체의
`effective_date`가 이미 raw archive의 frozen 범위(≤2026-08-21) 안에
있다. 만약 향후 raw archive가 확장되어 2026-08-21 이후 관측이 추가되고 그
관측이 실제로 genuine COMMON shape(관리종목이 아닌 정상 보통주)라면, 그
관측은 row-level `classify_security_type()`에서 직접 COMMON으로 판정되며
이번 supplemental record의 영향을 받지 않는다 — 즉 과거의 NOT_COMMON
판정이 미래의 진짜 COMMON 관측을 막지 않는다(regression test로 고정,
`test_future_merger_completion_after_cutoff_does_not_leak_backward`).

### 20.4 Population Universe vs Point-In-Time Denominator (다음 단계 계약)

다음 단계(`SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01`)를 위해 명시적으로
구분해야 하는 두 개념:

- **A. Population universe**: historical 기간 중 COMMON interval이 한 번이라도
  존재한 identity 전체 (예: AdjustedPriceStore population target에 사용).
- **B. Point-In-Time denominator**: 특정 date에 실제 COMMON 상태인 identity
  집합만(survivorship-safe backtest denominator에 사용).

예: 어떤 ticker가 2013~2015년 COMMON, 2016~2018년 NOT_COMMON이라면, population
universe에는 포함되지만 2016~2018 기간의 PIT denominator에는 포함되면 안
된다. 이번 라운드는 freeze 자체를 실행하지 않지만, 이 원칙을 다음 단계
설계에 명시적으로 전달한다 — 단순 ticker-level 목록만으로 freeze하면
lifecycle transition이 있는 identity(§18.1의 8건 COMMON-lineage SPAC 포함)의
PIT semantics가 깨진다.
