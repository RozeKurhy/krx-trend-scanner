# 업종 RS 웹 전달 데이터 생성 V01

## 목적

`web/data/sector-rs-ranking.json`은 [업종 내 상대강도 순위 계약 V01](../relative_strength/sector_rs_ranking_v01.md)의
산출물을 웹 표시용 정적 JSON으로 옮긴 결과다. 생성 스크립트는 업종 RS, 순위,
백분위 값을 다시 계산하지 않는다.

## 입력 데이터

| 입력 | 경로 | 용도 |
|---|---|---|
| 순위 산출물 | `data/analytics/sector_rs_ranking/v01/sector_rs_ranking_YYYYMMDD.parquet` | 전달할 값의 원천 |
| 순위 메타데이터 | `data/analytics/sector_rs_ranking/v01/sector_rs_ranking_YYYYMMDD_meta.json` | 모집단·그룹·참여 종목 수 대조 |
| KRX Basic Info | `data/reference/source/history/krx_instrument_master/v01/rolling/basic_info/YYYY/YYYYMMDD/KOSPI.json`, `KOSDAQ.json` | 종목명과 시장 표시 |
| 종목 리포트 웹 JSON | `web/data/stocks/*.json` | 리포트 제공 여부 확인 |

4단계 운영 경로(4C)에서는 입력을 다음과 같이 고른다.
세부 절차는 [분석·리포트·웹 반영 기준 V01](../architecture/daily_update_phase4_analysis_reporting_web_contract_v01.md)을
따른다.

- 순위 산출물과 메타데이터는 `target_as_of` 날짜의 파일을 쓰고, 메타데이터의
  `as_of`는 `reference_market_date`와 같아야 한다.
- KRX Basic Info는 `target_as_of`와 같거나 이전인 가장 최신 스냅샷을 쓴다.
  이전 스냅샷이 없으면 미래 스냅샷으로 대체하지 않고 중단한다. 이 정보는
  종목명과 시장 표시에만 쓰며 종목 집합 판단에는 쓰지 않는다.
- 리포트 제공 여부는 발행 전 준비 폴더에 만든 종목 리포트 웹 JSON 집합으로
  확인한다.

생성 스크립트를 명령줄에서 직접 실행하면 입력 경로는 인자(`--ranking`,
`--meta`, `--basic-info-dir`, `--stocks-dir`, `--output`)로 바꿀 수 있지만,
순위 산출물의 기준일 검증값은 인자로 받지 않는다. 따라서 직접 실행은 코드에
고정된 기본 기준일의 순위 산출물만 처리할 수 있다. 다른 기준일은 4단계 운영
경로에서 `build_sector_rs_web_payload()`에 `requested_as_of`와
`reference_market_date`를 넘겨 만든다.

생성 스크립트는 `web/data/stock-index.json`을 읽지 않는다. 따라서 이 파일을
종목 집합, 종목명, 시장의 기준으로 쓰지 않는다.

## 전달 데이터 계약

- `items`는 순위 산출물의 모든 행을 보존한다. 행 수와 섹터 구성 상태별 건수
  (`MAPPED`, `AGGREGATE_ONLY`, `UNMAPPED`)는 순위 메타데이터와 같아야 한다.
- 집계 업종만 배정(`AGGREGATE_ONLY`)된 종목도 배정된 업종 그룹에서 순위를 매긴
  순위 산출물 값을 그대로 쓴다.
- `sectors`는 `market:sector_code`를 키로 하는 업종 그룹 목록이다. 그룹 수는
  순위 메타데이터의 `sector_group_count`와 같아야 하고, 그룹마다 업종명은 하나여야
  한다.
- 업종 미배정(`UNMAPPED`) 행의 `sector_key`, `sector_code`, `sector_name`, 순위·
  백분위 값은 `null`이다. 나머지 행의 `sector_key`는 `market:sector_code`다.
- 모든 종목은 KRX Basic Info에서 종목명을 찾을 수 있어야 하고, 시장도 순위
  산출물과 같아야 한다. 하나라도 어긋나면 중단한다.
- `report_available`은 해당 종목의 리포트 웹 JSON 파일이 있는지를 나타내는
  클릭·파일 제공 여부다. 업종 구성, 순위 분모, 참여 종목 수에는 영향을 주지
  않는다.
- 지원 기간은 `2w`, `1m`, `3m`, `6m`, `12m`이다. 다섯 기간의 업종 RS, 업종 내
  순위와 백분위, 업종 구성원 수와 참여 종목 수를 순위 산출물에서 그대로 전달한다.
- `sector_anchor_date_*`, `sector_stock_return_*`, `latest_close` 같은 화면 표시
  값도 순위 산출물에서 전달하며, 반올림하거나 의미를 바꾸지 않는다.
- `items`는 `market`, `sector_code`, `ticker` 순으로, `sectors`는 `market`,
  `sector_code` 순으로 정렬한다.
- 엄격한 JSON 직렬화를 사용한다. `NaN`과 `+/-Infinity`는 `null`로 바꾸며,
  유효하지 않은 JSON 숫자로 출력하지 않는다.

## JSON 최상위 구조

| 필드 | 내용 |
|---|---|
| `schema_version` | `1` |
| `as_of` | 순위 산출물의 기준일 |
| `requested_as_of`, `reference_market_date` | 4단계 운영에서 호출할 때만 기록 |
| `scope` | 모집단 유형과 행 수, 섹터 구성 상태별 건수, 업종 그룹 수. `scope.type`은 코드에 `EXACT_SECTOR_MEMBERSHIP_POPULATION`으로 고정되어 있어, 순위 산출물 메타데이터의 범위 유형(`TARGET_PIT_COMMON_POPULATION`)과 다를 수 있다 |
| `metric_scope` | 업종 내 비교(`WITHIN_SECTOR`)와 그룹 키 |
| `horizons`, `eligible_counts` | 지원 기간과 기간별 참여 종목 수 |
| `source` | 순위 스키마 버전, 순위 기준일, 종목명 원천 날짜 |
| `sectors`, `items` | 업종 그룹 목록과 종목 행 |

## 생성 스크립트

```text
scripts/export_sector_rs_ranking_web.py
```

생성 스크립트는 실행 중 네트워크 연결을 차단하므로 로컬 입력만 사용한다.
순위 산출물을 다시 계산하지 않고, `sector-rs-ranking.json`을 만드는 웹 표시용
변환만 수행한다.

## 전체 웹 구조 문서와의 관계

웹 전체의 원천 데이터·변환 스크립트·정적 JSON·화면 연결은
[웹 영역 안내](README.md)에서 설명한다. 이 문서는 그중 업종 RS 전달 데이터의
입력, 보존 규칙, 정렬과 직렬화 경계만 다루는 세부 계약 문서다.
