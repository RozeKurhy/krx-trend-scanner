krx_instrument_metadata_authority.md

# KRX Instrument Metadata Authority — Lineage & Trust Rule (Fix Round 04, Major 2)

이 문서는 `InstrumentMetadataResolver`가 Production Asset Type Authority로 사용하는
frozen local artifact의 실제 lineage를 기록한다. 확인 불가능한 부분은 "확인 불가"로
명시하며, 근거 없이 정당화 문구를 채우지 않는다 (w.md Fix Round 04 §4.4).


## 1. Artifact

- `data/reference/krx_instrument_metadata.parquet` (1차 read 대상)
- `data/reference/krx_instrument_metadata.csv` (parquet 없을 때 fallback, 동일 스키마)

두 파일은 매 갱신마다 (ticker, effective_date) 기준으로 row-aligned 동일 내용을
유지해야 한다 (Fix Round 03에서 6개 종목 오분류 복원 시 이 방식으로 검증함).


## 2. Purpose

Production Instrument Metadata Authority.
Strict PIT(Point-In-Time) local frozen snapshot — 여러 `effective_date` 시점의
스냅샷을 누적 보관하고, 조회 시점(`requested_as_of`)보다 미래인 스냅샷은
사용하지 않는다.


## 3. Upstream source — 확인 불가

**이 저장소 상태만으로는 실제 upstream formal source를 확인할 수 없다.**

- `scripts/` 및 `src/` 전체를 검색했을 때 이 두 파일을 생성/갱신하는 스크립트가
  저장소 안에 존재하지 않는다 (Fix Round 03에서 이미 확인, 이번 라운드에서 재확인).
- 최초 도입 커밋은 `5baa44b` ("Establish canonical local KRX instrument metadata
  authority", 2026-08-20)이며, 이 커밋에서 2781행 CSV와 parquet가 완성된 형태로
  한 번에 추가됐다. 커밋 메시지에도 실제 조회 API/도구/원본 파일명이 명시되어
  있지 않다.
- 이후 `605b77a`(Fix Round 02, 138040/369370 보정), `1bb6665`(Fix Round 03, 6개
  종목 오분류 복원)에서 값이 수정됐지만 두 커밋 모두 upstream 재조회가 아니라
  기존 커밋된 값 대비 row 단위 수동 보정이었다.

따라서 "KRX 공식 종목정보를 실제로 어떤 방식(웹 조회 / 파일 다운로드 / 유료 API 등)
으로 가져왔는지"는 이 문서에 단정적으로 기록하지 않는다. §7의 Trust Rule은
이 저장소 안에서 실제로 검증 가능한 **row-level provenance 값**을 근거로 하며,
**artifact 전체가 진짜 KRX 공식 소스에서 왔다는 사실 자체**를 이 문서가
증명하지는 못한다는 것을 명시한다.


## 4. Acquisition method — 확인 불가

위와 동일한 이유로 재현 가능한 생성 스크립트나 process가 저장소 안에 없다.
필요시 향후 별도 작업으로 `scripts/`에 재현 가능한 generation script를 추가하고
이 문서를 갱신하는 것을 권장한다 (이번 라운드 범위 밖, w.md §4.5).


## 5. Source fields (파일에 실제로 존재하는 컬럼)

```
ticker                    - 6자리 숫자 또는 영숫자 혼합 ticker (예: 0115D0)
name                      - 종목명 (PIT, effective_date 시점 기준 표기)
market                    - KOSPI / KOSDAQ / KONEX
asset_type                - COMMON / PREFERRED / SPAC / REIT / ETF / ETN / UNKNOWN
is_common_stock           - asset_type == COMMON 의 boolean 미러 (redundant, 편의 컬럼)
metadata_source           - 전 row 100% "KRX_LOCAL_FROZEN_MASTER" (아래 §8 참고)
effective_date            - 이 레코드가 유효한 snapshot 날짜
classification_authority  - 전 row 100% "FORMAL_SECURITY_TYPE" (아래 §8 참고)
asset_type_source         - 전 row 100% "FORMAL_SECURITY_TYPE" (아래 §8 참고)
```

"원본 formal category 원문 필드"(예: 실제 KRX가 쓰는 "보통주"/"기업인수목적회사"
같은 원문 텍스트)는 이 파일에 보존되어 있지 않다 — `asset_type` 컬럼은 이미
AssetType enum으로 매핑 완료된 최종 값만 담고 있다. 따라서 원본 → AssetType
매핑 규칙 자체도 재현할 수 없다 (§6).


## 6. Mapping (원본 formal category → AssetType)

파일에 원본 카테고리 원문이 없으므로 실제 매핑 규칙(예: "보통주" → COMMON이
정확히 어떤 문자열 비교로 이뤄졌는지)은 확인 불가다.

확인 가능한 것은 **결과값으로 실제 사용되는 enum**뿐이다:

```
COMMON     - 보통주로 추정 (66,623 rows)
PREFERRED  - 우선주로 추정 (3,287 rows)
SPAC       - 기업인수목적회사로 추정 (1,874 rows)
REIT       - 부동산투자회사로 추정 (507 rows)
ETF        - ETF로 추정 (459 rows)
UNKNOWN    - 분류 불가 / 미확인 (36 rows, §8 참고)
```

("추정"이라고 표기한 이유: enum 이름 자체는 자명하지만, 실제 원본 소스가 이
정확한 한국어 공식 명칭을 사용했는지, 아니면 다른 taxonomy를 이 enum으로
재매핑한 것인지 재현 불가.)


## 7. PIT rule (코드로 검증 가능, 실제 동작)

`InstrumentMetadataResolver.resolve()` (src/trend_scanner/universe/instrument_metadata.py)
기준 실제 구현:

1. `ticker`로 후보 row 전체를 찾는다 (여러 effective_date 스냅샷 존재 가능).
2. `requested_as_of`가 주어지면, `effective_date <= requested_as_of`인 row만 남긴다
   (미래 스냅샷 엄격 배제).
3. 남은 row 중 `effective_date`가 가장 늦은(가장 최근) row 하나를 선택한다.
4. 해당 row가 아예 없으면(과거 스냅샷 자체가 없음) `is_identified=False`,
   `asset_type=UNKNOWN`, `classification_authority=UNKNOWN`,
   `asset_type_source=UNKNOWN`으로 fail closed 반환한다.

이 로직 자체는 이번 저장소의 소스코드로 직접 검증 가능하며, Fix Round 02/03에서
정의한 Strict PIT 계약과 동일하게 유지되고 있다 (regression test:
`test_instrument_metadata_selects_latest_snapshot_not_after_as_of`,
`test_stock_report_pit_does_not_use_future_instrument_metadata`).


## 8. Trust rule (Fix Round 04 Critical 1, 코드로 검증 가능)

Production A FAST Core applicability에 asset_type을 신뢰하려면 (row-level):

```
is_identified == True
AND classification_authority == "FORMAL_SECURITY_TYPE"
AND asset_type_source == "FORMAL_SECURITY_TYPE"
AND asset_type != "UNKNOWN"
```

(`InstrumentMetadata.is_trusted_for_production`, `is_common_stock_for_production`)

**중요 caveat — 이번 라운드에서 실제로 발견한 내용:**

`data/reference/krx_instrument_metadata.csv` 전체 72,786 row를 집계한 결과:

```
metadata_source == "KRX_LOCAL_FROZEN_MASTER"        : 72,786 / 72,786 (100%)
classification_authority == "FORMAL_SECURITY_TYPE"  : 72,786 / 72,786 (100%)
asset_type_source == "FORMAL_SECURITY_TYPE"          : 72,786 / 72,786 (100%)
```

즉 이 세 provenance 컬럼은 현재 이 artifact 안에서 **row마다 다르게 나타나는
값이 아니라 파일 전체에 걸친 상수**다. `LEGACY_HEURISTIC`이나 다른 값이 이
artifact 자체에는 전혀 존재하지 않는다(그런 값은 `pattern_a_universe_quality.csv`
fallback 경로에서만 코드가 인위적으로 부여한다).

더 구체적으로, `asset_type == "UNKNOWN"`인 36개 row조차 `classification_authority`
는 여전히 "FORMAL_SECURITY_TYPE"로 찍혀 있다 (§9의 13개 SPAC ticker 사례).
즉 "formal source를 조회했다"는 라벨이 "그 조회 결과가 깨끗하게 매핑됐다"는
것을 보장하지 않는다.

**결론:** 이번 Fix Round 04의 trust gate(§7~8, Critical 1 구현)는 코드 레벨에서
정확히 명세대로 동작한다 — `classification_authority`/`asset_type_source`가
`FORMAL_SECURITY_TYPE`이 아닌 row(예: `pattern_a_universe_quality.csv` fallback
경로로만 조회된 종목)는 정확히 fail closed된다. 다만 이 artifact **내부에서는**
현재 이 게이트가 row를 구분하지 못한다 — 전 row가 동일한 라벨을 갖고 있기
때문이다. 따라서 "이 파일의 FORMAL_SECURITY_TYPE 라벨이 실제로 row마다 정당한
근거를 갖고 부여됐는지"는 §3~4의 upstream lineage 확인 불가 문제와 직결된
**미해결 residual risk**이며, 이번 라운드가 자체적으로 해소한 것이 아니다.


## 9. Fail closed rule

- `asset_type == UNKNOWN` (row는 존재하나 분류 불가) → `is_trusted_for_production
  = False` → A FAST Core `applicability = DATA_UNAVAILABLE`,
  `action_reason = INSUFFICIENT_METADATA`.
- ticker 자체를 찾을 수 없음(`is_identified = False`) → 동일하게 fail closed.
- `classification_authority` 또는 `asset_type_source`가 `FORMAL_SECURITY_TYPE`이
  아님(`UNKNOWN` 또는 `LEGACY_HEURISTIC`) → `asset_type`이 설령 `COMMON`이라도
  fail closed (Critical 1의 핵심).
- 이름 문자열 heuristic(`asset_classifier.classify_asset_type`)으로 UNKNOWN을
  COMMON/SPAC 등으로 승격하지 않는다 (§6.1 원칙, `HEURISTIC_PROMOTION_COUNT = 0`
  유지).


## 10. Runtime

`ZERO_NETWORK_RUNTIME = YES`. `InstrumentMetadataResolver`는 로컬 parquet/csv만
읽으며 Stock Report 생성 경로에서 네트워크 요청을 하지 않는다
(`a_fast_core.provenance.network_requests == 0` schema enum으로 강제).
