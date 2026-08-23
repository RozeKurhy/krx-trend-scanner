contract_v03.md

===============================================================================
Stock Report v0.3 계약 — Phase 12 Market Relative Strength 통합
===============================================================================

목적
----
v0.3은 기존 Stock Report v0.2의 모든 필드를 유지하면서 최상위
`relative_strength` 섹션을 추가한다. 이 섹션은 Phase 12에서 완료된 전체 시장
상대강도 snapshot을 소비하는 표시·해석 계층이며, RS를 재계산하거나 Full
Universe Scanner를 실행하지 않는다.

기계 계약
---------
- Draft 7 스키마: `docs/reporting/stock_report/schema_v03.json`
- `report_version`은 문자열 `0.3`이어야 한다.
- 기존 v0.2 스키마와 계약 파일은 변경하지 않는다.
- `relative_strength`의 숫자 필드는 원본 Phase 12 CSV의 정밀도를 보존하며,
  데이터가 없으면 모두 `null`이어야 한다.

데이터 권위와 시점
------------------
- 요청 기준일과 정확히 일치하는 다음 파일만 권위로 사용한다.
  `artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_universe_YYYYMMDD.csv`
- 최신 파일, 미래 파일, 다른 기준일 파일로 대체하지 않는다.
- `source_as_of`, repo-relative `source_artifact`, 파일 SHA-256,
  `phase12_closure_sha`를 기록한다.
- Phase 12 closure SHA는 `5fdf97793c1fd7683c33d5fe77ff4da97fc75a19`로 고정한다.
- 외부 네트워크 요청과 Full Universe Scanner 호출은 0회다.

적용 범위와 fail-closed
-----------------------
- KOSPI/KOSDAQ `COMMON`만 `APPLICABLE`이다.
- ETF, ETN, 우선주 등 비대상 종목은 `NOT_APPLICABLE`/`NOT_EVALUATED`이고,
  RS 숫자 필드는 모두 `null`이다.
- 정확한 snapshot이 없거나 ticker row가 없으면
  `DATA_UNAVAILABLE`/`DATA_UNAVAILABLE`이고, RS 숫자 필드는 모두 `null`이다.
- 이 상태가 전체 report의 기존 `header.report_status`를 바꾸지는 않는다.
- PARTIAL 원본 상태와 결측 기간은 그대로 보존하고, 존재하는 값만 표시한다.

표시 및 서술
------------
- Markdown에서 외국인 수급 다음, 거래대금 앞에 `## 7.5. 시장 상대강도 (RS)`를
  표시한다.
- 3개월·6개월·12개월 RS, delta, acceleration, 전체 시장 rank/percentile와
  benchmark를 보여준다. anchor 날짜는 JSON contract의 provenance/diagnostic
  field로 보존한다.
- Market RS level은 Markdown에서 `%`, improvement delta와 RS acceleration은
  percentage-point 단위인 `%p`로 표시한다. JSON raw 값은 decimal을 유지한다.
- 서술은 장기 약세 후 회복, 기간별 개선, 기간별 약화, 혼조/데이터 제한의
  규칙 기반 문장만 사용한다.
- acceleration은 숫자로만 표시하며 매매 신호·추천·전략 언어를 사용하지 않는다.
- 기존 headline 및 전략 headline은 변경하지 않으며, RS bullet/narrative만
  additive하게 추가한다.

아티팩트와 검증
----------------
- 기존 v0.2 JSON/Markdown 54건은
  `artifacts/reporting/stock_reports/archive/v0.2/20260814/`에 보존한다.
- canonical `artifacts/reporting/stock_reports/20260814/`에는 동일 ticker set의
  v0.3 JSON/Markdown 54건을 둔다.
- v0.2 → v0.3 parity 검증에서 header, current_snapshot, monthly_history,
  foreign_flow, trading_value_flow, data_quality, pattern_a_fast, a_fast_core와
  기존 provenance 필드는 동일해야 한다. 허용되는 변화는 report_version,
  relative_strength, additive summary, provenance additive뿐이다.
- 검증 결과는 `artifacts/reporting/stock_reports/validation/v0.3/` 아래 summary,
  regression parity, schema validation, manifest 파일로 기록한다.
- 본 단계 완료 상태는 `READY_FOR_ARCHITECT_STOCK_REPORT_V03_REVIEW`이며,
  Architect 검토 전에는 최종 close로 표시하지 않는다.
