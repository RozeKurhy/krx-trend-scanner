krx_instrument_metadata_authority.md

# KRX Instrument Metadata Authority — Lineage & Trust Rule (Fix Round 06)

이 문서는 `InstrumentMetadataResolver`가 Production Asset Type Authority로 사용하는
frozen local artifact의 실제 lineage를 기록한다. 확인 불가능한 부분은 "확인 불가"로
명시하며, 근거 없이 정당화 문구를 채우지 않는다 (w.md Fix Round 04 §4.4, Fix Round
05 §4.4).

Fix Round 04까지는 이 artifact 전체(72,786 row)가 실제로는 어디서 왔는지 저장소
안에서 재현할 수 없는 상태였다(§3 "Fix Round 04 이전 상태" 참고). Fix Round 05는
처음으로 실제 verified upstream formal source에 연결된 build workflow를 만들었으나,
verified snapshot의 `effective_date`를 CLI 인자(`--as-of-date`)로 임의 과거 날짜에
지정할 수 있어 실제 관측일(빌드 시점)보다 과거 시점을 formal-verified라고 잘못
주장하는 PIT lookahead corruption을 냈다(실제 사례: 2026-08-20/21 관측 데이터를
`effective_date=2026-08-14`에 기록). Fix Round 06은 이 backdating 경로를
구조적으로 제거하고, SPAC identity가 section 상태 전이에 취약했던 문제(Critical 2),
manifest checksum 필드가 산출물 해시를 source 해시로 잘못 라벨링했던 문제(Major 2)를
함께 고친다.


## 1. Artifact

- `data/reference/krx_instrument_metadata.parquet` (1차 read 대상)
- `data/reference/krx_instrument_metadata.csv` (parquet 없을 때 fallback, 동일 스키마)
- `data/reference/krx_instrument_metadata_manifest.json` (매 build 실행마다 갱신되는
  generation manifest)
- `data/reference/source/krx_instrument_metadata_source_snapshot_<date>.json` (신규,
  Fix Round 06 — 실제 upstream 응답을 canonical 직렬화해 보존한 snapshot. manifest의
  `source_snapshot_sha256`을 재계산으로 검증할 수 있는 근거 파일)

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
   ([12005] 전종목 기본정보 페이지의 이면 데이터 API). Fix Round 06에서
   `ISU_ENG_NM`(공식 영문 종목명) 필드를 추가로 사용(§6).
2. pykrx `get_etf_ticker_list()` / `get_etn_ticker_list()`
3. 상폐종목검색 (delisted finder, `bld=dbms/comm/finder/finder_listdelisu`) —
   현재 미상장(delisted) ticker의 존재 자체를 확인하는 reference 용도로만 사용,
   security type 필드는 제공하지 않음

**SOURCE_LOCATION** = `https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd`
(POST, `bld` 파라미터로 구분)

**ACQUISITION_METHOD** = 인증된 HTTPS 세션(KRX_ID/KRX_PW, `.env`)으로 build-time에만
접근. `dbms/comm/finder/finder_stkisu`(단순 ticker 검색) 같은 공개 endpoint와
달리, `MDCSTAT01901`은 익명 요청 시 본문이 문자 그대로 `"LOGOUT"`인 400 응답을
반환한다 — 즉 이 특정 bld는 실제로 로그인 세션을 요구한다. `KRX_ID`/`KRX_PW`가
없으면 이 build script는 `RuntimeError`로 즉시 실패한다(추측성 fallback 없음).

**SOURCE_OBSERVATION_DATE(Fix Round 06 Critical 1)** = `pd.Timestamp.now(tz="Asia/Seoul")`에서만
파생되는 값으로, CLI로 다른 값을 주입할 방법이 코드에 없다. 새로 검증되는 row의
`effective_date`는 항상 이 값과 동일하며, 이전 실행 결과(baseline)를 그대로
새 effective_date로 clone한 뒤 재분류한다. 이전 build가 backdate한 row가
있었다면(예: Fix Round 05가 `2026-08-14`에 써넣은 row), 이번 build는 그 row를
재검증하지 않았으므로 `classification_authority=LEGACY_UNVERIFIED`로 자동
재정정한다(§9).

**CHECKSUM 3분리 (Fix Round 06 Major 2)** — Fix Round 05는 `source_checksum_sha256`이라는
이름으로 실제로는 산출물(CSV) 해시를 기록하는 오류를 냈다. 이제 manifest는 세 값을
분리한다:
- `source_snapshot_sha256`: `data/reference/source/`에 저장된 canonical(정렬,
  고정 구분자) source snapshot bytes의 SHA-256 — 실제 upstream 응답의 fingerprint.
- `artifact_csv_sha256` / `artifact_parquet_sha256`: 생성된 산출물 파일 자체의 SHA-256.


## 5. Raw Source Fields (전종목기본정보 API 원본 컬럼)

```
ISU_SRT_CD           - 6자리(또는 영숫자) 종목코드
ISU_NM                - 정식 한글 종목명
ISU_ENG_NM            - 정식 영문 종목명 (Fix Round 06에서 SPAC identity에 사용)
MKT_TP_NM              - 시장 (KOSPI / KOSDAQ / KOSDAQ GLOBAL / KONEX)
SECUGRP_NM             - 증권그룹명: 주권 / 부동산투자회사 / 외국주권 / 주식예탁증권 /
                          사회간접자본투융자회사 / 투자회사
SECT_TP_NM             - 소속부명: 우량기업부/중견기업부/벤처기업부/기술성장기업부/
                          일반기업부/관리종목(소속부없음)/SPAC(소속부없음)/
                          투자주의환기종목(소속부없음)/외국기업(소속부없음)/공란
KIND_STKCERT_TP_NM      - 주권종류구분명: 보통주 / 구형우선주 / 신형우선주 / 종류주권
```

이 원본 필드들은 canonical artifact에 `source_security_type` 컬럼으로 압축
보존된다 (형식: `SECUGRP_NM=...|SECT_TP_NM=...|KIND_STKCERT_TP_NM=...|ISU_NM=...|ISU_ENG_NM=...`)
— 단 Verified rows(§8)에 한해서만 채워지며, 과거 legacy row는 빈 값이다 (§9).


## 6. Source Category → AssetType Deterministic Mapping (Fix Round 06 갱신)

`scripts/build_krx_instrument_metadata.py`의 `map_row_to_asset_type()` 실제 로직,
우선순위 순서(w.md §3.4):

```
[SPAC identity — 최우선, section-independent, 두 개의 독립된 공식 필드로 교차 검증]
SECT_TP_NM에 "SPAC" 포함
OR ISU_ENG_NM에 "Special Purpose Acquisition" 포함
OR ISU_NM에 "기업인수목적" 포함
                                                       → SPAC

SECUGRP_NM == "부동산투자회사"                        → REIT
KIND_STKCERT_TP_NM == "보통주"                        → COMMON
KIND_STKCERT_TP_NM in ("구형우선주", "신형우선주")     → PREFERRED
KIND_STKCERT_TP_NM == "종류주권" AND ISU_NM에 "우선주" 포함
                                                       → PREFERRED
그 외 (외국주권 / 주식예탁증권 / 사회간접자본투융자회사 /
투자회사 / 종류주권(비우선주))                          → UNKNOWN
                                                          (classification_authority=FORMAL_SECURITY_TYPE,
                                                           asset_type_source=UNMAPPED_FORMAL_CATEGORY)

별도 product list 조회 (SPAC identity보다 먼저 적용):
  ticker ∈ get_etf_ticker_list()  → ETF
  ticker ∈ get_etn_ticker_list()  → ETN

formal source에서 ticker 자체를 못 찾음(상장/ETF/ETN 어디에도 없음)
                                                       → UNKNOWN
                                                          (classification_authority=UNKNOWN,
                                                           asset_type_source=UNKNOWN)
```

### 6.1 SPAC identity가 section-independent여야 하는 이유 (Fix Round 06 Critical 2)

`SECT_TP_NM`만으로 SPAC을 판정하면, SPAC이 상장폐지 검토 등으로
`관리종목(소속부없음)`으로 전환되는 순간 "SPAC" 문자열이 사라져 COMMON으로
오분류된다. 실측으로 확인된 사례 3건:

| ticker | 종목명 | SECT_TP_NM | ISU_ENG_NM |
|---|---|---|---|
| 465320 | 교보15호기업인수목적 | 관리종목(소속부없음) | Kyobo 15 Special Purpose Acquisition Company |
| 471050 | 대신밸런스제17호기업인수목적 | 관리종목(소속부없음) | Daishin Balance No.17 Special Purpose Acquisition Company |
| 472220 | 신영해피투모로우제10호기업인수목적 | 관리종목(소속부없음) | Shinyoung HappyTomorrow No.10 Special Purpose Acquisition Company |

`ISU_ENG_NM`에 "Special Purpose Acquisition"이 포함되는 ticker(71개)와 `ISU_NM`에
"기업인수목적"이 포함되는 ticker(71개)를 실측 비교하면 **완전히 동일한 집합**이며,
`SECT_TP_NM`에 "SPAC"이 포함되는 ticker(68개)의 상위 집합이다(교집합=합집합 관계는
없음 — SECT 기반 68개는 항상 나머지 71개 집합 안에 포함되고, 위 3건만 SECT 신호를
잃었다). 즉 SPAC이 관리종목 상태가 되어도 공식 종목명 필드(한글/영문 모두)는
정체성을 계속 보존한다 — 이는 별도의 비공식 name-heuristic이 아니라, **동일
formal record 내부의 서로 다른 두 formal field로 교차 검증**하는 것이다(w.md §2.2가
금지하는 것은 종목명 문자열만으로 canonical asset_type을 만드는 것이지, formal
API 응답 내부의 다른 formal field로 재확인하는 것이 아니다).

`KIND_STKCERT_TP_NM == "종류주권"` 12건의 PREFERRED 판정도 동일한 원칙이다:
전수 확인 결과 전부 `ISU_NM`이 "...우선주"/"...우선주(신형)" 형태였다(예: `03473K
SK1우선주`).


## 7. Builder Script

```
BUILDER_SCRIPT   = scripts/build_krx_instrument_metadata.py
MAPPING_VERSION  = v2
```

역할: 인증 세션으로 KRX MDC에서 라이브 formal 분류를 가져와, 가장 최근 기존
snapshot(baseline_date)의 ticker 집합을 그대로 가져와 `effective_date =
SOURCE_OBSERVATION_DATE`(실행 시각의 실제 KST 날짜)인 새 row 블록으로 재분류해
append한다. **`--as-of-date` 같은 날짜 주입 CLI 인자는 존재하지 않는다** —
Fix Round 06 Critical 1: backdating 경로를 코드에서 원천 제거했다. `--dry-run`으로
파일을 쓰지 않고 변경 미리보기 가능. 같은 날 재실행하면 기존
SOURCE_OBSERVATION_DATE row를 교체하는 idempotent upsert로 동작한다.


## 8. Verified Snapshot 범위

이번 build가 실제로 검증한 것은 **build 실행 시점(SOURCE_OBSERVATION_DATE)의 KRX
실시간 상장 상태** 하나뿐이다. 과거로 거슬러 올라가는 historical formal snapshot을
제공하는 API는 확인하지 못했다(향후 과제, §17).

이 값은 고정 상수가 아니라 매 build 실행마다 달라진다 — 최신 값은
`data/reference/krx_instrument_metadata_manifest.json`의
`verified_snapshot_effective_date`를 확인한다. 테스트 코드 역시 이 값을
manifest에서 동적으로 읽는다(하드코딩 날짜를 쓰지 않는다).


## 9. Historical Row 정책 (PIT History Rewrite 금지, w.md §2.13/§2)

**SOURCE_OBSERVATION_DATE가 아닌 모든 row(직전 verified snapshot이었던
baseline_date row 포함)는 이번 build가 값(asset_type, name, market 등)을 전혀
건드리지 않는다.** 오늘 시점 조회 결과로 과거 snapshot을 소급 덮어쓰는 것(history
rewrite)은 절대 금지되어 있으므로, historical row는 기존 값을 그대로 유지한다.

다만 provenance는 정직하게 낮춘다: SOURCE_OBSERVATION_DATE가 아닌 모든 row의
`classification_authority`/`asset_type_source`를 `"LEGACY_UNVERIFIED"`로
설정한다. 이는 **직전까지 FORMAL_SECURITY_TYPE으로 표시되어 있던 baseline_date
row도 포함한다** — Fix Round 05가 그 시점을 formal-verified라고 backdate했던
주장을 이번 build가 실행될 때마다 다시 정직하게 되돌린다(Critical 1의 핵심
수정: 검증되지 않은 채로 남아있는 시점을 verified로 자칭하지 않는다).

`InstrumentMetadata.is_trusted_for_production`은 이 값이 아니면
(`FORMAL_SECURITY_TYPE`이어야만) trusted로 인정하므로, historical row는 항상
자동으로 fail closed된다 — asset_type 자체(COMMON/SPAC 등)는 여전히 기존 PIT
로직으로 정확히 조회된다(§10).


## 9.1 HISTORICAL_LEGACY_RESEARCH 모드 (신규, Fix Round 06 Major 1)

§9의 결과로 SOURCE_OBSERVATION_DATE 이전 모든 시점(v0.2 Stock Report가 지금까지
써온 `2026-08-14` 포함)이 매 build마다 항상 production-untrusted가 된다. 이 시점을
요청하는 모든 조회를 무조건 `DATA_UNAVAILABLE`로 막으면, 실제로는 "과거를 묻는
retrospective 조회"까지 "메타데이터가 전혀 없는 조회"와 구분 없이 취급하게 되어
과도하다.

이를 구분하기 위해 `InstrumentMetadata.is_eligible_for_historical_legacy_research`
(및 그 근거인 `has_later_verified_snapshot`)를 도입했다: 이 ticker에 대해
**requested_as_of 이후 시점에 실제로 formal 재검증된 snapshot이 존재하는가**를
판단 근거로 쓴다.

```
requested_as_of 시점 row가 FORMAL_SECURITY_TYPE          → metadata_provenance_mode = CURRENT_VERIFIED
requested_as_of 시점 row가 LEGACY_UNVERIFIED
  AND 이 ticker의 더 나중 시점에 FORMAL_SECURITY_TYPE row가 존재  → metadata_provenance_mode = HISTORICAL_LEGACY_RESEARCH
requested_as_of 시점 row가 LEGACY_UNVERIFIED
  AND 더 나중에 재검증된 적이 전혀 없음                      → metadata_provenance_mode = DATA_UNAVAILABLE
```

`HISTORICAL_LEGACY_RESEARCH`는 A FAST Core 전략 계산을 정상적으로 수행하되(가격/
계약 데이터는 실제 그대로), Stock Report의 `a_fast_core.metadata_provenance_mode`
필드로 이 판정이 production 신뢰가 아니라 retrospective 연구용임을 명시적으로
구분해 표시한다. w.md §4.5가 금지하는 것은 "오늘 시점" 판단에 legacy metadata를
trusted로 쓰는 것이지, 과거 조회 자체를 계산하는 것이 아니다 — `requested_as_of`가
이미 과거를 명시하는 retrospective 질의이므로 이 구분은 안전하다. 반대로 이후
재검증된 적이 전혀 없는 시점(사실상의 "현재"인데 아직 검증되지 않은 경우)은
여전히 `DATA_UNAVAILABLE`로 fail closed 유지된다 — 이 조건이 바로 §4.5가 실제로
막고자 하는 경계다.

이 모드 도입으로 `tests/test_a_fast_core_stock_report.py`의 PIT/execution-boundary
전략 테스트(`test_a_fast_core_uses_requested_as_of_only`,
`test_a_fast_core_pending_entry_next_open`, `test_a_fast_core_execution_boundary`)는
metadata trust를 강제로 override하는 테스트 헬퍼 없이 실제 production 경로
(`generate_stock_report`)로 직접 검증한다.


## 10. PIT Selection Rule (코드로 검증 가능, 변경 없음)

`InstrumentMetadataResolver.resolve()` (src/trend_scanner/universe/instrument_metadata.py):

1. `ticker`로 후보 row 전체를 찾는다 (여러 effective_date 스냅샷 존재 가능).
2. `requested_as_of`가 주어지면, `effective_date <= requested_as_of`인 row만 남긴다.
3. 남은 것 중 `effective_date`가 가장 늦은 row 하나를 선택한다.
4. 후보가 없으면 `is_identified=False`, 전부 UNKNOWN으로 fail closed.
5. (Fix Round 06 신규) 이와 별도로, `requested_as_of` 이후에 이 ticker의
   FORMAL_SECURITY_TYPE row가 존재하는지도 계산해 `has_later_verified_snapshot`에
   싣는다(§9.1의 근거).

이 선택 알고리즘 자체(1~4)는 Fix Round 05/06 모두 수정하지 않았다 — 매 round의
변경은 순수하게 **데이터(provenance 컬럼 값)**만 바꿨을 뿐이다.


## 11. Trust Rule (변경 없음, Fix Round 04에서 구현)

```
is_identified == True
AND classification_authority == "FORMAL_SECURITY_TYPE"
AND asset_type_source == "FORMAL_SECURITY_TYPE"
AND asset_type != "UNKNOWN"
```

이 게이트는 이 artifact 안에서 실제로 row를 구분한다(Fix Round 04 시점의
"row마다 다르지 않은 상수" 문제가 verified rows에 한해 해소됨). Historical row는
§9에 따라 여전히 균일하게 untrusted다 — 이는 게이트가 못 구분하는 게 아니라,
검증 불가능한 데이터에 대해 게이트가 의도대로 정직하게 차단하는 것이다.


## 12. Fail Closed Rule

- `asset_type == UNKNOWN` → 항상 fail closed.
- `classification_authority`/`asset_type_source`가 `FORMAL_SECURITY_TYPE`이 아님
  (`UNKNOWN` / `LEGACY_HEURISTIC` / `LEGACY_UNVERIFIED`) → `asset_type`이 COMMON
  이라도, `has_later_verified_snapshot`이 없다면 fail closed.
- formal source는 확인됐으나 mapping이 불가능한 category(`UNMAPPED_FORMAL_CATEGORY`)
  → fail closed.
- 이름 문자열 heuristic으로 UNKNOWN을 COMMON/SPAC 등으로 승격하지 않는다.
  `HEURISTIC_PROMOTION_COUNT = 0` (SPAC은 이름이 아니라 formal `SECT_TP_NM`/
  `ISU_ENG_NM`/`ISU_NM` 필드로 확인됨 — §6.1, §13 참고).


## 13. SPAC Ticker 재검증 결과

Fix Round 04에서 "asset_type=UNKNOWN, authority=FORMAL_SECURITY_TYPE"이라는
모순된 상태로 남아있던 13개 알파뉴메릭 ticker 전부, Fix Round 05의 verified live
formal source에서 `SECT_TP_NM == "SPAC(소속부없음)"`으로 명확히 확인되어
`SPAC`으로 갱신됐다. Fix Round 06에서는 추가로 `관리종목(소속부없음)`으로 전환돼
`SECT_TP_NM` 신호를 잃은 3개 ticker(465320/471050/472220, §6.1)를
`ISU_ENG_NM`/`ISU_NM` 신호로 SPAC 유지되도록 수정했다. 두 경우 모두 이름에
"스팩"이 포함된다는 이유의 승격이 아니라, KRX 공식 필드를 그대로 읽은 결과다
(`FORMAL_SPAC_CONFIRMED`).


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
changed_tickers_vs_baseline_committed_value, historical_rows_marked_legacy_unverified,
zero_network_runtime, backdating_prevention(신규, Fix Round 06), pit_history_rewrite.


## 15. Runtime — Zero Network Rule

`ZERO_NETWORK_RUNTIME = YES` (Stock Report 생성 경로 기준, 변경 없음).
`scripts/build_krx_instrument_metadata.py`는 build-time 전용 스크립트이며
Stock Report runtime 경로(`InstrumentMetadataResolver`, `generate_stock_report`
등) 어디에서도 import/실행되지 않는다. `InstrumentMetadataResolver`는 여전히
로컬 parquet/csv만 읽는다 (`a_fast_core.provenance.network_requests == 0` schema
enum으로 강제).


## 16. Known UNKNOWN / Unsupported Category 정책

Verified rows 중:
- formal source에서 ticker 자체를 못 찾음: 1건 (299900 위지윅스튜디오 — 현재
  상장/ETF/ETN 어디에도 없음. `상폐종목검색`으로 실제 delisted 상태임을 별도
  확인함, 임의 추정 아님).
- formal source는 찾았으나 mapping 불가(UNMAPPED_FORMAL_CATEGORY): 0건 (외국주권/
  주식예탁증권/사회간접자본투융자회사/투자회사 카테고리에 해당하는 verified
  ticker가 이번 스냅샷에는 없었음. 향후 build에서 이런 카테고리가 나타나면
  자동으로 이 정책이 적용된다).


## 17. Historical Metadata Provenance 정책

```
Historical effective_date row의 formal provenance가 실제 검증 가능한가?
→ NO (매 build 실행 시점의 SOURCE_OBSERVATION_DATE 제외 전부)
```

- **Verified 기간**: 매 build 실행 시점의 SOURCE_OBSERVATION_DATE 단일 snapshot만.
- **Legacy/Unverified 기간**: 그 이전 모든 effective_date — 값은 유지되나
  `classification_authority=asset_type_source=LEGACY_UNVERIFIED`로 production
  trust에서 배제됨. §9.1의 HISTORICAL_LEGACY_RESEARCH 모드로 retrospective
  연구 용도로는 여전히 사용 가능.
- 향후 과거 시점 formal snapshot을 실제로 확보할 방법(예: KRX가 과거 시점
  기준 조회를 지원하는 별도 API가 있는지)을 찾으면, Option A(과거 시점도
  실제로 formal 재검증)로 이 정책 자체를 갱신할 수 있다 — 이번 라운드에서도
  그런 API를 조사하지 않았고 발견하지 못했다(Option B로 §9.1을 도입해 대응함).
