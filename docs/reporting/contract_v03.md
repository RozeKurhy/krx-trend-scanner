# 종목 리포트 계약 v0.3 — 시장 상대강도 추가

## 목적

v0.3은 [v0.2 기반 계약](contract_v02.md)의 모든 필드를 유지하고 최상위
`relative_strength` 섹션을 추가한다. 이 섹션은 시장 RS 권위 스냅샷을 소비해
보여주고 해석하는 계층이며, RS를 다시 계산하거나 전체 종목 스캐너를 실행하지
않는다.

## 기계 계약

- Draft 7 스키마: `docs/reporting/schema_v03.json`
- `report_version`은 문자열 `0.3`이다.
- v0.2 스키마와 계약 파일은 변경하지 않는다.
- `relative_strength`의 숫자 필드는 원본 권위 CSV의 정밀도를 보존하며,
  데이터가 없으면 모두 `null`이다.

## 데이터 권위와 시점

- 요청 기준일과 날짜가 정확히 같은 다음 파일만 권위로 사용한다.
  `artifacts/patterns/pattern_a/validation/relative_strength/market_completion_v01/market_rs_universe_YYYYMMDD.csv`
- 최신 파일, 미래 파일, 다른 기준일 파일로 대체하지 않는다.
- `source_as_of`, 저장소 기준 상대 경로 `source_artifact`, 파일 SHA-256,
  `phase12_closure_sha`를 기록한다. `phase12_closure_sha`에는 코드 상수
  `PHASE12_CLOSURE_SHA`(`src/trend_scanner/reporting/relative_strength_report.py`)를
  그대로 기록한다.
- 외부 네트워크 요청과 전체 종목 스캐너 호출은 하지 않는다.

## 적용 범위와 결측 처리

- KOSPI/KOSDAQ 보통주(`COMMON`)만 적용 대상(`APPLICABLE`)이다.
- ETF, ETN, 우선주 등 비대상 종목은 적용 제외(`NOT_APPLICABLE`)·미평가
  (`NOT_EVALUATED`)이고 RS 숫자 필드는 모두 `null`이다.
- 기준일 스냅샷이 없거나 종목 행이 없으면 적용성과 데이터 상태가 모두 산출
  불가(`DATA_UNAVAILABLE`)이고 RS 숫자 필드는 모두 `null`이다.
- 이 상태는 리포트 전체의 `header.report_status`를 바꾸지 않는다.
- 원본의 일부 산출(`PARTIAL`) 상태와 결측 기간은 그대로 보존하고, 있는 값만
  표시한다.

## 표시와 서술

- Markdown에서 외국인 수급 다음, 거래대금 앞에 `## 7.5. 시장 상대강도 (RS)`를
  표시한다.
- 2주·1개월·3개월·6개월·12개월 기간별로 종목 수익률, 시장 RS, 전체 시장
  백분위와 상위 위치를 보여주고, 기간 간 개선폭과 가속도, 비교 기준 지수를
  함께 보여준다.
  2주·1개월은 짧은 기간 추가 항목이며 기간별로 따로 `null`일 수 있다.
- anchor 날짜는 JSON contract의 provenance/diagnostic 항목으로 보존하며 Markdown에는 표시하지 않는다.
- Market RS level은 Markdown에서 `%`로, 개선폭(improvement delta)과 가속도(RS acceleration)는 percentage-point 단위인 `%p`로 표시한다.
- JSON 원값은 소수를 유지한다.
- 서술은 장기 약세 후 회복, 기간별 개선, 기간별 약화, 혼조·데이터 제한을
  나타내는 규칙 기반 문장만 쓴다.
- 가속도는 숫자로만 표시하며 매매 신호·추천·전략 표현을 쓰지 않는다.
- 기존 요약 제목과 전략 요약 제목은 바꾸지 않고, RS 요약 항목과 서술만
  추가한다.

## 호환성

v0.3은 v0.2의 `header`, `current_snapshot`, `monthly_history`, `foreign_flow`,
`trading_value_flow`, `data_quality`, `pattern_a_fast`, `a_fast_core`와 기존
출처 필드를 바꾸지 않는다. 허용되는 변화는 `report_version`,
`relative_strength`, 요약 추가 항목, 출처 추가 항목뿐이다.
