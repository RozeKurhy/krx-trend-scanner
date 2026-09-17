# Sector RS 웹 전달 데이터 생성 V01

## 목적

`web/data/sector-rs-ranking.json`은 현재 기준인 `Sector RS Within-Sector
Ranking Contract V01`의 값을 웹 표시용 정적 JSON으로 옮긴 결과다. 생성
스크립트는 Sector RS, 순위, 백분위 값을 다시 계산하지 않는다.

## 입력 데이터

- 순위 기준 데이터: `data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904.parquet`
- 순위 메타데이터: `data/analytics/sector_rs_ranking/v01/sector_rs_ranking_20260904_meta.json`
- 기준일별 종목명·시장: `data/reference/source/history/krx_instrument_master/v01/rolling/basic_info/2026/20260904/KOSPI.json` 및 `KOSDAQ.json`
- 리포트 제공 여부: 현재 존재하는 `web/data/stocks/*.json` 파일 집합

2026-09-04 Basic Info 결합은 하나라도 확인되지 않으면 중단하는 방식으로
처리한다. 이 생성 스크립트는 `web/data/stock-index.json`을 읽지 않으므로 이를
종목 집합·종목명·시장 기준으로 사용하지 않는다. 대신 `web/data/stocks/*.json`을
읽어 리포트 파일 존재 여부만 확인한다. 현재 `stock-index.json`의 종목 집합 기준일은
2026-09-04이지만, 이 값은 Sector RS 전달 데이터의 종목 집합에 영향을 주지 않는다.

## 전달 데이터 계약

- `items`는 기준 데이터의 2,562개 행을 모두 보존한다. 구성은 `MAPPED` 2,440개,
  `AGGREGATE_ONLY` 88개, `UNMAPPED` 34개다. `AGGREGATE_ONLY`도 지정된 정식
  섹터에 포함해 순위를 계산한 기준 데이터를 그대로 사용한다.
- `sectors`는 `market:sector_code`를 키로 하는 45개 정식 섹터 그룹이다.
- `UNMAPPED` 행의 `sector_key`, `sector_code`, `sector_name`, 순위·백분위 값은
  `null`이다. 나머지 행의 `sector_key`는 `market:sector_code`로 만든다.
- `report_available`은 해당 종목의 `web/data/stocks/*.json` 파일이 있는지를
  나타내는 클릭·파일 제공 여부다. 섹터 구성, 순위 분모, `eligible_count`에는
  영향을 주지 않는다.
- 지원 기간은 `2w`, `1m`, `3m`, `6m`, `12m`이다. 다섯 기간의 원시 Sector RS,
  섹터 내 순위와 백분위, 섹터 구성원 수와 유효 종목 수를 기준 데이터에서
  그대로 전달한다.
- `sector_anchor_date_*`, `sector_stock_return_*`, `latest_close` 같은 화면 표시
  값도 기준 데이터에서 전달하며, 기존 값을 반올림하거나 의미를 바꾸지 않는다.
- `items`는 `market`, `sector_code`, `ticker` 순으로 정렬하고 `sectors`는
  `market`, `sector_code` 순으로 정렬한다.
- 엄격한 JSON 직렬화를 사용한다. `NaN`과 `+/-Infinity`는 `null`로 바꾸며,
  유효하지 않은 JSON 숫자로 출력하지 않는다.

## 생성 스크립트

```text
scripts/export_sector_rs_ranking_web.py
```

생성 스크립트는 네트워크 차단 장치를 설치하므로 로컬 입력만 사용한다. 핵심
Sector RS 기준 데이터를 다시 계산하지 않고, `sector-rs-ranking.json`을 생성하는
웹 표시용 변환만 수행한다.

## 전체 웹 구조 문서와의 관계

웹 전체의 원천 데이터·변환 스크립트·정적 JSON·화면 연결은
[`docs/web/README.md`](README.md)에서 설명한다. 이 문서는 그중 Sector RS
전달 데이터의 입력, 보존 규칙, 정렬과 직렬화 경계만 다루는 세부 계약 문서다.
