README.md

# Stock Report

- **Current Version**: 0.5 (`report_version="0.5"`, Fundamentals + Market/Sector RS additive context)
- **Production Integration**: `CLOSED / PRODUCTION_DECISION_SUPPORT`
- **Current Production Artifact**: 2026-09-04 canonical 553 reports (COMMON 525 / ETF 26 / PREFERRED 2)
- **JSON Contract**: [contract_v05.md](contract_v05.md)
- **Machine Schema**: [schema_v05.json](schema_v05.json)
- **Fundamentals**: 분기·연간, TTM/YoY, filter status 및 Web trend chart를 제공하며 PIT-aware OpenDART/XBRL authority를 사용한다.
- **Web Report Viewer**: `CLOSED / READ_ONLY`; 검색, 리포트 조회, Fundamentals 표/차트, Flow, Market/Sector RS, A FAST Core 및 외부 링크를 제공한다.
- **Historical v0.4**: 이전 current production predecessor이며 v0.5에 의해 superseded 됐다.
- **Historical v0.3 Contract/Schema**: [contract_v03.md](contract_v03.md) / [schema_v03.json](schema_v03.json)
- **Historical v0.2**: [contract_v02.md](contract_v02.md) / [schema_v02.json](schema_v02.json)
- **Legacy v0.1**: [archive/contract_v01.md](archive/contract_v01.md)

Production artifact 경로:
- Markdown: `artifacts/reporting/stock_reports/<YYYYMMDD>/*.md`
- JSON: `artifacts/reporting/stock_reports/<YYYYMMDD>/json/*.json`

버전 디렉터리는 사용하지 않으며, 버전은 `report_version`/schema/contract/Git provenance에서 관리한다.
