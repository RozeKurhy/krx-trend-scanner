# 종목 리포트

종목 리포트(Stock Report)는 패턴과 독립된 상위 계층이다. Pattern A, Pattern B
정보 분석, A FAST Core V2, 외국인 수급, 시장·업종 RS, 펀더멘털 결과를 종목별
JSON과 Markdown으로 모은다. 의사결정 지원 운영 상태(`PRODUCTION_DECISION_SUPPORT`)의 리포트이며
매매 추천이나 자동 매매 신호가 아니다.

## 현재 버전

일반 보통주(COMMON)의 운영 버전은 v0.7(`report_version="0.7"`)이다. 일일 운영
경로의 생성 대상과 검증은
[분석·리포트·웹 반영 기준 V01](../architecture/daily_update_phase4_analysis_reporting_web_contract_v01.md)
4B를 따른다. Official ETF 36에는 별도 산출 경로의 v0.6
(`report_version="0.6"`)을 사용한다. v0.5는 Pattern B를 공식 보장하기 전의
COMMON 계약 기록이다. 생성기에 펀더멘털 섹션(`fundamentals_section`)을 넘기지
않은 기존 호출은 v0.4 리포트를 만든다.

## 계약 구성과 읽는 순서

v0.5 계약은 한 문서가 아니다. 기반 계약 위에 버전별 추가분을 쌓은 구조이므로
아래 순서로 함께 읽는다. 각 추가분은 이전 계약의 필드와 의미를 바꾸지 않는다.

| 순서 | 계약 | 추가 내용 | 스키마 |
|---|---|---|---|
| 1 | [v0.2](contract_v02.md) | 헤더, 현재 스냅샷, A FAST Core V2, Pattern A FAST, 월별 이력, 외국인 수급, 거래대금, 데이터 품질 | [schema_v02.json](schema_v02.json) |
| 2 | [v0.3](contract_v03.md) | 시장 RS (`relative_strength`) | [schema_v03.json](schema_v03.json) |
| 3 | [v0.4](contract_v04.md) | 업종 RS (`sector_relative_strength`), 가격 원천 `MarketDataRepositoryV2` | [schema_v04.json](schema_v04.json) |
| 4 | [v0.5](contract_v05.md) | COMMON 펀더멘털 (`fundamentals`) | [schema_v05.json](schema_v05.json) |
| 5 | [ETF v0.6](contract_v06.md) | Official ETF 36의 Julia V1 전략 및 ETF PIT 적격성 | [schema_v06.json](schema_v06.json) |
| 6 | [COMMON v0.7](contract_v07.md) | COMMON Pattern B 정보 분석 (`pattern_b`) | [schema_v07.json](schema_v07.json) |

버전별 스키마는 해당 버전 리포트의 검증과 기존 테스트에 쓰이므로 제자리에
유지한다. 현재 COMMON 리포트 검증에는 `schema_v07.json`을 쓴다. 기반 공통 섹션의
세부 의미는 v0.2~v0.5 계약과 함께 확인하고, v0.7 스키마는 Pattern B 추가 필수
조건을 검증한다.

## 현재 Markdown 목차

| 절 | 제목 | 추가 버전 |
|---|---|---|
| 0 | 핵심 요약 | v0.2 |
| 1 | 현재 기술적 국면·투자 적격성 스냅샷 | v0.2 |
| 1.5 | 펀더멘털 | v0.5 |
| 1.6 | Pattern B 정보 분석 | v0.7 |
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

v0.6은 ETF36 전용 병렬 계약이며 COMMON v0.7의 Pattern B를 포함하지 않는다.
ETF 보고서의 공식 전략은 `official_strategy`이며 `a_fast_core`를 Julia V1 용도로
재사용하지 않는다.

## 산출물 위치

```text
Markdown: artifacts/reporting/stock_reports/<YYYYMMDD>/*.md
JSON:     artifacts/reporting/stock_reports/<YYYYMMDD>/json/*.json
```

버전별 폴더는 쓰지 않는다. 버전은 `report_version`, 스키마, 계약, Git 이력으로
관리한다. 대체된 과거 산출물은 `artifacts/reporting/stock_reports/archive/`에
보관한다.

Official ETF 36의 v0.6 산출물은 기존 일반 종목 및 웹 exporter 결과와 섞이지 않게
별도 경로에 둔다.

```text
Markdown: artifacts/reporting/etf_stock_reports/<YYYYMMDD>/*.md
JSON:     artifacts/reporting/etf_stock_reports/<YYYYMMDD>/json/*.json
Summary:  artifacts/reporting/etf_stock_reports/<YYYYMMDD>/generation_summary.json
```

## 역사 기록

[v0.1 계약](archive/contract_v01.md)은 v0.2 기반 계약으로 대체된 과거 기록이며
원문 그대로 보존한다. 현재 계약의 권위를 대신하지 않는다.
