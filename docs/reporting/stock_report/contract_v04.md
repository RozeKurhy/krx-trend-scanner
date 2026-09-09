contract_v04.md

===============================================================================
Stock Report v0.4 계약 — Sector Relative Strength 통합
===============================================================================

목적
----
v0.4는 Stock Report v0.3의 모든 필드와 의미를 유지하면서 최상위
`sector_relative_strength` 섹션을 추가한다.

기계 계약
---------
- Draft 7 스키마: `docs/reporting/stock_report/schema_v04.json`
- `report_version`은 문자열 `0.4`이어야 한다.
- v0.3의 `docs/reporting/stock_report/contract_v03.md`와
  `schema_v03.json`은 historical contract로 수정하지 않는다.
- 기존 최상위 `relative_strength`는 Market RS 전용이며 v0.4에서도 유지한다.
- 신규 최상위 `sector_relative_strength`는 Sector RS 전용이다.

데이터 권위와 시점
------------------
- Stock 가격은 production 경로에서 `MarketDataRepositoryV2`를 사용한다.
- Sector membership은 `requested_as_of`와 정확히 일치하는
  approved SectorMembershipStore exact-date snapshot만 사용한다.
  예를 들어 `2026-08-14` 요청은
  `data/market/sector_membership/v01/sector_membership_20260814.parquet`,
  `2026-09-04` 요청은
  `data/market/sector_membership/v01/sector_membership_20260904.parquet`를
  사용한다.
- snapshot의 `effective_date == requested_as_of`가 반드시 성립해야 한다.
  이전 snapshot 재사용, 미래 snapshot의 소급 적용, nearest-date fallback은
  허용하지 않는다. exact snapshot이 없으면
  `SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE`로 fail closed하고 Sector RS를
  계산하지 않는다.
- Sector index는 다음 로컬 cache만 사용한다.
  `.cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet`
- Sector RS는 기존 `compute_relative_strength_features(...)`를 재사용하며
  stock return, sector return, RS ratio, anchor를 새로 구현하지 않는다.
- 이번 버전에는 Sector RS cross-sectional rank/percentile을 포함하지 않는다.

적용 범위와 상태
-----------------
- KOSPI/KOSDAQ `COMMON`은 `APPLICABLE`이며 candidate 여부와 관계없이 직접
  Sector RS 평가를 시도한다.
- `READY`: 3M/6M/12M 모두 산출 가능.
- `PARTIAL`: 일부 horizon의 history가 부족.
- `DATA_UNAVAILABLE`: membership, 기준일 stock, benchmark 또는 anchor 입력이
  부족한 fail-closed 상태.
- ETF·ETN·우선주 등 비대상 instrument는 `NOT_APPLICABLE`/
  `NOT_EVALUATED`이며 수치 필드는 모두 `null`이다.
- Sector RS 상태는 전체 report의 `header.report_status`를 낮추지 않는다.

표시 및 서술
------------
- Executive Summary에 `업종 상대강도` bullet/narrative를 additive하게 추가한다.
- Markdown에서는 Market RS `## 7.5. 시장 상대강도 (RS)` 뒤, 거래대금 앞에
  `## 7.6. 업종 상대강도 (Sector RS)`를 표시한다.
- Sector section은 적용 상태, 데이터 상태, 업종명/코드, benchmark 기준일,
  3M/6M/12M RS와 업종 수익률, 규칙 기반 해석 및 provenance를 표시한다.
- Sector RS는 context/confirmation only이며 매매 추천이나 새로운 scoring을
  제공하지 않는다.

Provenance
----------
Sector section 내부에 다음을 기록한다.

- `source_as_of`
- `membership_snapshot_date`는 실제 사용한 exact membership snapshot의
  `effective_date`와 같다.
- `membership_source`는 실제 사용한 exact snapshot 파일 경로를 기록한다.
  예: `data/market/sector_membership/v01/sector_membership_20260904.parquet`
- `sector_index_source`
- `input_reason` (fail-closed 사유가 있는 경우)

전략 및 기존 section 보호
--------------------------
- Pattern A formula/stage, Candidate, Investability, Foreign Flow, Market RS,
  Trading Value, Pattern A FAST, A FAST Core, Entry/Hold/Exit 및 report_status의
  semantics는 변경하지 않는다.
- `relative_strength`는 exact-date Market RS authority CSV를 계속 소비한다.
- Sector RS 때문에 Market RS를 재계산하거나 scanner를 호출하지 않는다.
- canonical `artifacts/reporting/stock_reports/20260904/`의 기존 158개 MD/JSON은
  이 단계에서 수정하지 않는다. smoke report만 gitignored temporary directory에
  생성한다.
- 전체 158개 report regeneration, Full Universe Scanner, Full pytest 및 외부
  네트워크 요청은 이 단계의 범위가 아니다.

호환성
------
v0.4 JSON은 v0.3의 모든 기존 top-level section을 보존하고
`sector_relative_strength`만 additive하게 추가한다. v0.3 contract/schema 및
historical artifact는 그대로 유지한다.
