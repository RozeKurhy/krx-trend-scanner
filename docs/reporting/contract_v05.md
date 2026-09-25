# 종목 리포트 계약 v0.5 — 펀더멘털 추가

## 목적

v0.5는 [v0.4 계약](contract_v04.md)의 기술·전략·수급 구조를 바꾸지 않고
`fundamentals` 섹션 하나를 추가한다. v0.4 계약과 기존 v0.4 산출물은 수정하지
않는다.

## 입력 경계

`fundamentals_report.build_fundamentals_section`은 이미 계산된 F2
MultiPeriod 결과, F3 DerivedMetrics 결과, F4 FundamentalsFilter 결과,
`requested_as_of`와 `asset_type`만 소비한다. OpenDART 제공자, 원본 공시,
네트워크 호출, 필터 재계산, 데이터 적재는 하지 않는다.

## 적용성과 상태

- 보통주(`COMMON`)에만 일반 기업 펀더멘털을 적용한다.
- ETF, ETN, PREFERRED, SPAC, REIT, OTHER, UNKNOWN은 숫자 필드를 모두
  `null`로 두고 `applicability=NOT_APPLICABLE`, `data_status=NOT_APPLICABLE`로
  처리한다.
- F4가 금융업(`FINANCIAL`) 또는 적용 제외(`NOT_APPLICABLE`)를 반환하면 F4
  상태와 사유를 그대로 보존하고 섹션은 적용 제외로 둔다.
- 보통주에 입력이 제공되지 않으면 생성에 실패하지 않고
  `APPLICABLE/DATA_UNAVAILABLE`, 사유 `FUNDAMENTALS_INPUT_NOT_PROVIDED`로
  기록한다.
- `data_status` 값은 정상 산출(`READY`), 일부 산출(`PARTIAL`), 산출 불가
  (`DATA_UNAVAILABLE`), 적용 제외(`NOT_APPLICABLE`)다. 이 값은 기존
  `header.report_status`를 바꾸지 않는다.

## 표시 기간과 결측

- F2 `quarter_slots[-12:]`의 분기 식별값을 그대로 유지한다.
- F2 `annual_slots[-5:]`의 회계연도 식별값을 그대로 유지한다.
- 값이 없거나 상태가 준비되지 않은 칸도 식별값은 유지하고 숫자만 `null`로
  둔다. 다른 분기 값으로 당겨 채우거나 대체하지 않는다.

## 필드 권위와 매핑

- 매출, 영업이익, 당기순이익, 영업현금흐름은 F2 관측값을 그대로 사용한다.
- 분기·연간 YoY, 영업이익률, 순이익률, 연간 ROE, TTM ROE, 부채비율과 TTM
  지표는 F3 파생 관측값을 식별값(종목, 회사군, 지표, 지표 유형, 연도, 기간)으로
  조회한다. 어댑터는 산식을 다시 계산하지 않는다.
- 부채비율 시점은 FY→`FY_END`, Q1→`Q1_END`, Q2→`H1_END`, Q3→`Q3_END`,
  Q4→`FY_END`로 매핑한다.
- TTM 요약은 F4가 선택한 `latest_quarter` 끝점을 기준으로 조회한다. 다른 종목
  또는 더 최신 끝점을 섞지 않는다.
- F4 `status`, `passed`, `reasons`는 다시 판정하지 않고 그대로 복사한다.

## JSON과 Markdown

- JSON 최상위에 `fundamentals`를 추가하며 구조는 `schema_v05.json`을 따른다.
- Markdown에서는 현재 스냅샷(1절) 다음, 기존 2절 앞에
  `## 1.5. 펀더멘털 (Fundamentals)`를 넣는다.
- 금액은 표시할 때만 억원 단위(KRW / 100,000,000, 소수 첫째 자리)로 바꾸고
  원본 JSON은 원 단위(KRW)를 유지한다. 비율은 `xx.xx%`, `null`은 `N/A`로
  표시한다.
- 핵심 요약에는 펀더멘털 상태와 핵심 수치를 요약 항목 하나로만 추가한다.
  Pattern A, A FAST Core, RS, 투자 적격성 산식은 바꾸지 않는다.

## 호출 호환성과 범위

- `generate_stock_report`에는 `fundamentals_section` 주입 지점 하나를 둔다.
  주입된 섹션은 그대로 사용하며 생성기가 F2/F3/F4를 다시 호출하지 않는다.
- `fundamentals_section`을 넘기지 않은 기존 호출은 v0.4 리포트를 만든다.
  v0.5 호출에서 명시적으로 `None`을 넘기면 안전한 산출 불가
  (`DATA_UNAVAILABLE`) 기본 섹션을 만든다.
- 리포트 생성은 새 API, PyKRX, 웹 수집, 수동 데이터 주입을 사용하지 않는다.
