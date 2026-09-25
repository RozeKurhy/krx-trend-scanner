# 종목 리포트

종목 리포트(Stock Report)는 패턴과 독립된 상위 계층이다. Pattern A, A FAST
Core V2, 외국인 수급, 시장·업종 RS, 펀더멘털 결과를 종목별 JSON과 Markdown으로
모은다. 의사결정 지원 운영 상태(`PRODUCTION_DECISION_SUPPORT`)의 리포트이며
매매 추천이나 자동 매매 신호가 아니다.

## 현재 버전

현재 운영 버전은 v0.5(`report_version="0.5"`)다. 일일 운영 경로의 생성
대상과 검증은 [분석·리포트·웹 반영 기준 V01](../architecture/daily_update_phase4_analysis_reporting_web_contract_v01.md)
4B를 따른다. 생성기에 펀더멘털 섹션(`fundamentals_section`)을 넘기지 않으면
v0.4 리포트가 만들어진다.

## 계약 구성과 읽는 순서

v0.5 계약은 한 문서가 아니다. 기반 계약 위에 버전별 추가분을 쌓은 구조이므로
아래 순서로 함께 읽는다. 각 추가분은 이전 계약의 필드와 의미를 바꾸지 않는다.

| 순서 | 계약 | 추가 내용 | 스키마 |
|---|---|---|---|
| 1 | [v0.2](contract_v02.md) | 헤더, 현재 스냅샷, A FAST Core V2, Pattern A FAST, 월별 이력, 외국인 수급, 거래대금, 데이터 품질 | [schema_v02.json](schema_v02.json) |
| 2 | [v0.3](contract_v03.md) | 시장 RS (`relative_strength`) | [schema_v03.json](schema_v03.json) |
| 3 | [v0.4](contract_v04.md) | 업종 RS (`sector_relative_strength`), 가격 원천 `MarketDataRepositoryV2` | [schema_v04.json](schema_v04.json) |
| 4 | [v0.5](contract_v05.md) | 펀더멘털 (`fundamentals`) | [schema_v05.json](schema_v05.json) |

버전별 스키마는 해당 버전 리포트의 검증과 기존 테스트에 쓰이므로 제자리에
유지한다. 현재 리포트 검증에는 `schema_v05.json`을 쓴다. 이 스키마는 최상위
필수 필드를 모두 나열하지만 세부 구조는 펀더멘털 섹션만 정의한다. 다른 섹션의
세부 구조는 이전 버전 계약과 스키마에서 확인한다.

## 현재 Markdown 목차

| 절 | 제목 | 추가 버전 |
|---|---|---|
| 0 | 핵심 요약 | v0.2 |
| 1 | 현재 기술적 국면·투자 적격성 스냅샷 | v0.2 |
| 1.5 | 펀더멘털 | v0.5 |
| 2 | A FAST Core V2 전략 상태 | v0.2 |
| 3 | Pattern A FAST 현재 신호 | v0.2 |
| 4 | Pattern A 최근 12개월 월별 추이 | v0.2 |
| 5 | Pattern A 국면 전환 이력 | v0.2 |
| 6 | Pattern A FAST 주별 이력 | v0.2 |
| 7 | 외국인 수급 확증 | v0.2 |
| 7.5 | 시장 상대강도 | v0.3 |
| 7.6 | 업종 상대강도 | v0.4 |
| 8 | 거래대금 추세 | v0.2 |
| 9 | Pattern A 전체 월별 이력 | v0.2 |
| 10 | 데이터 품질과 출처 | v0.2 |

생성 코드가 출력하는 정확한 절 제목은 각 버전 계약에서 확인한다.

## 산출물 위치

```text
Markdown: artifacts/reporting/stock_reports/<YYYYMMDD>/*.md
JSON:     artifacts/reporting/stock_reports/<YYYYMMDD>/json/*.json
```

버전별 폴더는 쓰지 않는다. 버전은 `report_version`, 스키마, 계약, Git 이력으로
관리한다. 대체된 과거 산출물은 `artifacts/reporting/stock_reports/archive/`에
보관한다.

## 역사 기록

[v0.1 계약](archive/contract_v01.md)은 v0.2 기반 계약으로 대체된 과거 기록이며
원문 그대로 보존한다. 현재 계약의 권위를 대신하지 않는다.
