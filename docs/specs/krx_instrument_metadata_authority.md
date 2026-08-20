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


## 6. Source Category → AssetType Deterministic Mapping (Fix Round 07 갱신)

`scripts/build_krx_instrument_metadata.py`의 `map_row_to_asset_type()` 실제 로직,
우선순위 순서(w.md §3.4/§4.6):

```
[ETF/ETN — live product master membership, map_row_to_asset_type() 호출 이전]
ticker ∈ live ETF universe  → ETF
ticker ∈ live ETN universe  → ETN

[SPAC identity — SECT_TP_NM 단독, 이름 substring 완전 배제 (Fix Round 07 Major 3)]
SECT_TP_NM에 "SPAC" 포함                              → SPAC

SECUGRP_NM == "부동산투자회사"                        → REIT
KIND_STKCERT_TP_NM == "보통주"
  AND SECT_TP_NM == "관리종목(소속부없음)"
  AND 이 ticker가 canonical 이력 어딘가에 SPAC으로 기록된 적 있음
                                                       → UNKNOWN (asset_type_source=INSUFFICIENT_FORMAL_IDENTITY)
KIND_STKCERT_TP_NM == "보통주" (그 외)                → COMMON
KIND_STKCERT_TP_NM in ("구형우선주", "신형우선주")     → PREFERRED
KIND_STKCERT_TP_NM == "종류주권" AND ISU_NM에 "우선주" 포함
                                                       → PREFERRED
그 외 (외국주권 / 주식예탁증권 / 사회간접자본투융자회사 /
투자회사 / 종류주권(비우선주))                          → UNKNOWN
                                                          (classification_authority=FORMAL_SECURITY_TYPE,
                                                           asset_type_source=UNMAPPED_FORMAL_CATEGORY)

formal source에서 ticker 자체를 못 찾음                → UNKNOWN
                                                          (classification_authority=UNKNOWN,
                                                           asset_type_source=UNKNOWN)
```

### 6.1 왜 Fix Round 06의 ISU_ENG_NM/ISU_NM 기반 SPAC 판정을 되돌렸는가 (Fix Round 07 Major 3)

Fix Round 06은 `SECT_TP_NM`이 SPAC을 나타내지 않아도 `ISU_ENG_NM`에 "Special
Purpose Acquisition"이나 `ISU_NM`에 "기업인수목적"이 포함되면 SPAC으로 판정했다.
이 필드들은 formal API 응답에서 나오지만, 판정 **방식** 자체는 종목명 문자열
검색이었다 — 즉 formal source 출처라는 사실이 "이름 substring matching이
아니다"를 보장하지 않는다.

이번 라운드에서 KRX formal source를 다시 조사했다(w.md §4.3):
- 전종목기본정보의 전체 12개 컬럼(ISU_CD, ISU_SRT_CD, ISU_NM, ISU_ABBRV,
  ISU_ENG_NM, LIST_DD, MKT_TP_NM, SECUGRP_NM, SECT_TP_NM, KIND_STKCERT_TP_NM,
  PARVAL, LIST_SHRS) — 종목명과 독립적인 SPAC 전용 필드 없음.
- 업종분류현황(`bld=MDCSTAT03901`, IDX_IND_NM) — SPAC들이 "금융" 카테고리에
  속하지만, 실측 결과 이 카테고리는 SPAC 아닌 증권사/투자회사/지주회사 등
  117개 ticker(LS증권, DSC인베스트먼트, APS 등)와 공유되어 식별력이 없음을
  직접 확인했다.
- pykrx 패키지 전체에 SPAC 전용 endpoint/wrapper 없음(소스 grep으로 확인).

종목명과 독립적인 formal SPAC identity source를 확보하지 못했으므로, w.md §4.7의
지시대로 **추측으로 SPAC이나 COMMON을 확정하지 않는다.** `SECT_TP_NM`이 명시적으로
SPAC을 나타내는 경우만 positive evidence로 인정하고, 그렇지 않으면서 이
ticker의 canonical 이력에 SPAC 기록이 있다면(§6.2) UNKNOWN + fail closed로
처리한다.

### 6.2 465320/471050/472220 — UNKNOWN Fail Closed (Fix Round 06→07 재정정)

세 종목 모두 `KIND_STKCERT_TP_NM=보통주`, `SECT_TP_NM=관리종목(소속부없음)`
상태다:

| ticker | 종목명 | SECT_TP_NM | canonical 이력에 SPAC 기록 있음 |
|---|---|---|---|
| 465320 | 교보15호기업인수목적 | 관리종목(소속부없음) | Yes (2023-12-22 ~ 2025-06-27 SPAC) |
| 471050 | 대신밸런스제17호기업인수목적 | 관리종목(소속부없음) | Yes |
| 472220 | 신영해피투모로우제10호기업인수목적 | 관리종목(소속부없음) | Yes |

"관리종목(소속부없음)"은 그 자체로 formal하고 이름과 무관한 신호다 — 정상
사업부(우량기업부/일반기업부/벤처기업부 등)가 아니라 관리/주의 상태임을
나타낸다. 이 상태이면서 canonical 이력에 SPAC 기록이 있는 ticker는 실제
합병/전환으로 COMMON이 됐는지, 여전히 SPAC인데 formal 근거만 일시적으로
사라졌는지 이름과 독립적으로 구분할 방법이 없어 fail closed한다.

**369370과의 대조가 핵심이다**: 369370(과거 SPAC → 블리츠웨이엔터테인먼트로
합병)은 실측 확인 결과 현재 `SECT_TP_NM="벤처기업부"`(정상 사업부, 관리종목
아님)다. 즉 정상적으로 전환이 완료된 종목은 관리종목 상태에서 벗어나
있으므로 이 규칙(§6 "관리종목 AND 과거 SPAC 기록" 조건)에 걸리지 않고 그대로
COMMON으로 유지된다 — "관리종목=SPAC 의심 전체"로 확대하지 않고, 관리종목이면서
동시에 SPAC 이력이 있는 교집합만 본다(실측상 관리종목+보통주 118개 중 3개만
해당, 나머지 115개는 SPAC 이력이 전혀 없는 일반 기업으로 영향받지 않음).

**"canonical 이력에 SPAC 기록이 있는가"는 immediate baseline이 아니라 전체
이력을 본다.** baseline(직전 build 결과) 하나만 비교하면, 한 번 UNKNOWN으로
fail closed된 ticker가 같은 날 재실행(idempotent rebuild)될 때 그 UNKNOWN
자체가 새 기준이 되어 다음 실행에서 COMMON으로 잘못 승격되는 non-deterministic
회귀가 실제로 발생함을 확인했다(§7 deterministic output 위반). SPAC 기록은
과거 row 값을 절대 재작성하지 않으므로(§9), 전체 이력에서 "이 ticker가 SPAC
으로 기록된 적 있는가"를 보는 방식은 재실행 횟수/순서와 무관하게 항상 안정적이다.

`KIND_STKCERT_TP_NM == "종류주권"` 12건의 PREFERRED 판정은 이 라운드의 대상이
아니다: 전수 확인 결과 전부 `ISU_NM`이 "...우선주"/"...우선주(신형)" 형태이며,
판정 키 자체가 `KIND_STKCERT_TP_NM`이라는 code field이지 이름이 판정을 단독으로
뒤집는 구조가 아니다(w.md 어느 라운드에서도 문제로 지적되지 않음).


## 7. Builder Script

```
BUILDER_SCRIPT   = scripts/build_krx_instrument_metadata.py
MAPPING_VERSION  = v3
```

역할 (Fix Round 07 Major 2 — live universe 전체에서 생성):

```
FETCH LIVE FORMAL SOURCES (equity + ETF + ETN)
        ↓
BUILD CURRENT LIVE SUPPORTED UNIVERSE (live 전체의 union, dedup)
        ↓
CLASSIFY EACH LIVE INSTRUMENT (name/market도 live source에서 직접, baseline 복사 없음)
        ↓
CREATE NEW CURRENT SNAPSHOT (effective_date = SOURCE_OBSERVATION_DATE)
        ↓
COMPARE AGAINST PRIOR BASELINE (신규상장/상장폐지/asset_type 변경 diff만)
        ↓
APPEND CURRENT SNAPSHOT, PRESERVE ALL HISTORICAL ROWS
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


## 9. Historical Row 정책 (PIT History Rewrite 금지)

**SOURCE_OBSERVATION_DATE가 아닌 모든 row는 이번 build가 값(asset_type, name,
market 등)을 전혀 건드리지 않는다.** 오늘 시점 조회 결과로 과거 snapshot을
소급 덮어쓰는 것(history rewrite)은 절대 금지되어 있으므로, historical row는
기존 값을 그대로 유지한다.

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
insufficient_formal_identity_tickers(신규),
changed_tickers_vs_baseline_committed_value, historical_rows_marked_legacy_unverified,
zero_network_runtime, backdating_prevention, pit_history_rewrite,
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
