contract_v05.md

Stock Report v0.5 Fundamentals Additive Contract
=================================================

목적
----
Stock Report v0.5는 기존 v0.4 기술/전략/수급 구조를 변경하지 않고
`fundamentals` 한 개의 additive section을 추가한다. 기존 v0.4 계약과
`artifacts/reporting/stock_reports/20260904/` 정본은 수정하지 않는다.

입력 경계
---------
`fundamentals_report.build_fundamentals_section`은 이미 계산된 F2
MultiPeriod 결과, F3 DerivedMetrics 결과, F4 FundamentalsFilter 결과,
requested_as_of와 asset_type만 소비한다. OpenDART provider, raw filing,
네트워크 호출, 필터 재계산 또는 데이터 hydration은 수행하지 않는다.

적용성 및 상태
--------------
- `COMMON`만 일반기업 펀더멘털을 적용한다.
- ETF, ETN, PREFERRED, SPAC, REIT, OTHER, UNKNOWN은 숫자 필드를 모두
  null로 두고 `applicability=NOT_APPLICABLE`, `data_status=NOT_APPLICABLE`로
  fail-closed 한다.
- F4가 `FINANCIAL` 또는 `NOT_APPLICABLE`을 반환하면 F4 상태/사유를 그대로
  보존하고 section은 NOT_APPLICABLE로 둔다.
- COMMON에 입력이 제공되지 않으면 생성에 실패하지 않고
  `APPLICABLE/DATA_UNAVAILABLE`, reason=`FUNDAMENTALS_INPUT_NOT_PROVIDED`로
  기록한다.
- `data_status` 값은 READY, PARTIAL, DATA_UNAVAILABLE, NOT_APPLICABLE이다.
  이는 기존 `header.report_status`를 변경하지 않는다.

표시 기간과 결측
----------------
- F2 `quarter_slots[-12:]`의 분기 identity를 정확히 유지한다.
- F2 `annual_slots[-5:]`의 FY identity를 정확히 유지한다.
- 값이 없거나 상태가 준비되지 않은 slot도 identity를 유지하고 숫자만 null로
  둔다. 다른 분기의 값을 당겨 채우거나 fallback하지 않는다.

필드 권위 및 매핑
-----------------
- 매출, 영업이익, 당기순이익, 영업현금흐름은 F2 관측값을 그대로 사용한다.
- 분기/연간 YoY, 영업이익률, 순이익률, 연간 ROE, TTM ROE, 부채비율과 TTM
  지표는 F3 derived observation을 identity(종목, 회사군, metric, metric_type,
  연도, 기간)로 조회한다. 어댑터가 산식을 재계산하지 않는다.
- 부채비율 snapshot은 FY→FY_END, Q1→Q1_END, Q2→H1_END,
  Q3→Q3_END, Q4→FY_END로 매핑한다.
- TTM summary는 F4가 선택한 `latest_quarter` endpoint를 기준으로 조회한다.
  다른 종목/더 최신 endpoint를 섞지 않는다.
- F4 `status`, `passed`, `reasons`는 재판정하지 않고 그대로 복사한다.

JSON 및 Markdown
----------------
- JSON 최상위에 `fundamentals`를 추가하며 구조는 `schema_v05.json`을 따른다.
- Markdown에서는 Current Snapshot 다음, 기존 Section 2 이전에
  `## 1.5. 펀더멘털 (Fundamentals)`를 삽입한다.
- 금액은 표시할 때만 KRW/100,000,000(억원)으로 변환하고 원본 JSON은 KRW를
  유지한다. 비율은 `xx.xx%`, null은 `N/A`로 표시한다.
- Executive Summary에는 펀더멘털 상태/핵심 수치를 한 개의 additive bullet로만
  추가한다. Pattern A, A FAST Core, RS, 투자 적격성 산식은 변경하지 않는다.

호출 호환성 및 범위
--------------------
`generate_stock_report`에는 `fundamentals_section` 단일 주입 지점을 둔다.
주입된 section은 그대로 사용하며 generator가 F2/F3/F4를 다시 호출하지 않는다.
기존 인자를 사용한 v0.4 호출과 아카이브 산출물은 보존하고, v0.5 호출에서
명시적으로 `None`을 전달하면 안전한 DATA_UNAVAILABLE 기본 section을 생성한다.
이번 단계에서는 전체 리포트를 재생성하지 않으며 신규 API, PyKRX, scraping,
수동 데이터 주입을 사용하지 않는다.
