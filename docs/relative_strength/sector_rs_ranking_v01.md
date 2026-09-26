# 업종 내 상대강도 순위 계약 V01

## 목적

이 계약은 다음 질문에만 답한다.

> 같은 업종 안에서 이 종목의 업종 RS는 다른 종목보다 얼마나 강한가?

순위 모집단은 기준일(`as_of`)의 PIT COMMON(해당 시점 KOSPI/KOSDAQ 보통주)
전체 종목이다. Stock Report 발행 여부, Pattern A 후보 여부, 시장 전체 교차
비교와는 관계가 없다.

## 그룹 기준

모든 순위 그룹은 다음 키로 구분한다.

```text
(market, sector_code)
```

`sector_name`은 설명용이다. 따라서 이름이 둘 다 `제약`이더라도
`(KOSPI, 1009)`와 `(KOSDAQ, 2066)`은 서로 다른 그룹이다.

이 계약의 순위는 업종 내 순위만 뜻한다. 전체 순위, KOSPI/KOSDAQ 시장별 순위,
업종 간 순위, 후보 종목 순위, 발행 리포트 기준 순위가 아니다.

## 모집단과 섹터 구성

모집단과 섹터 구성 정보 선택의 상세 계약은
[분석 입력 갱신 기준 V01](../architecture/daily_update_phase3_analysis_inputs_contract_v01.md)
§4.4·§4.5를 따른다. 이 문서는 순위 계산에 필요한 규칙만 요약한다.

- **모집단**: `data/market/rolling_authority/merged_pit_intervals.json`에서
  기준일에 유효한 `COMMON` 구간의 KOSPI/KOSDAQ 종목이다. 결과는 이 모집단의
  종목 집합과 시장을 빠짐없이 그대로 보존한다.
- **섹터 구성 정보**: `data/market/sector_membership/v01/`의 승인 스냅샷 중
  효력일이 기준일과 같거나 이전인 가장 최신 스냅샷을 사용한다. 그 스냅샷이
  불완전하거나 무효이면 더 오래된 스냅샷으로 대체하지 않고 중단한다.
- 모집단 종목과 섹터 구성 정보의 시장이 서로 다르면 중단한다.

모집단 종목의 섹터 구성 상태는 다음과 같이 처리한다.

| 상태 | 뜻 | 순위 처리 |
|---|---|---|
| 업종 배정 (`MAPPED`) | 세부 업종 하나에 배정됨 | 해당 업종 그룹에서 순위를 매긴다 |
| 집계 업종만 배정 (`AGGREGATE_ONLY`) | 세부 업종 없이 집계 업종 지수에만 포함됨 | 배정된 집계 업종 그룹에서 순위를 매기며 다른 업종으로 재분류하지 않는다 |
| 업종 미배정 (`UNMAPPED`) | 배정된 업종이 없거나, 섹터 구성 정보에 없는 모집단 종목 | 행은 남기고 그룹·순위·백분위 필드는 비운다. 사유는 `SECTOR_MEMBERSHIP_UNMAPPED` |

## 입력

```text
모집단      → 기준일 PIT COMMON (merged_pit_intervals.json)
섹터 구성   → 기준일 이전 최신 승인 스냅샷 (sector_membership_YYYYMMDD.parquet + _meta.json)
업종 지수   → .cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet
종목 가격   → MarketDataRepositoryV2
업종 RS     → 기존 compute_relative_strength_features()
```

업종 지수는 기준일에 46개 업종 지수가 중복 없이 모두 있어야 하고, 업종 지수
파일 전체의 종가가 양의 유한값이어야 한다. 가까운 날짜로 대체하지 않는다.

업종 RS 산식은 기존 계산 엔진을 그대로 쓴다. 기준점은 업종 지수 거래일
기준으로 2W=`10`, 1M=`21`, 3M=`63`, 6M=`126`, 12M=`252` 거래일 전이며,
종목도 같은 기준점 날짜의 종가가 있어야 한다.

```text
stock_return_H     = 종목 기준일 종가 / 종목 기준점 종가 - 1
benchmark_return_H = 업종 지수 기준일 종가 / 업종 지수 기준점 종가 - 1
sector_rs_H        = (1 + stock_return_H) / (1 + benchmark_return_H) - 1
```

업종 RS 상태(`sector_rs_data_status`)는 다음과 같다.

- 정상 산출 (`READY`): 3M·6M·12M이 모두 산출됨
- 일부 산출 (`PARTIAL`): 3M은 산출됐지만 6M 또는 12M 기준점이 부족함
- 산출 불가 (`DATA_UNAVAILABLE`): 기준일 업종 지수 관측값 없음, 3M 기준점 부족,
  업종 미배정 등

## 순위 대상 값과 참여 조건

다음 값만 순위를 매긴다.

```text
sector_rs_2w
sector_rs_1m
sector_rs_3m
sector_rs_6m
sector_rs_12m
```

값이 클수록 강하다. 기간마다 참여 종목 수(분모)를 따로 센다. 순위 참여는
업종 RS 상태가 아니라 기간별 값으로 판단하므로, 예를 들어 일부 산출
(`PARTIAL`) 종목도 값이 있는 기간에는 순위에 참여한다. 순위 값은 유한한
숫자여야 하며 null, NaN, 양의 무한대, 음의 무한대는 0으로 채우지 않고
제외한다.

순위는 내림차순이며, 같은 값은 평균 순위를 받는다.

```text
rank = pandas rank(method="average", ascending=False)
```

기간별 참여 종목 수가 `N`일 때 백분위는 다음과 같다.

```text
percentile = (N - rank) / (N - 1) * 100
```

`N == 1`이면 순위 `1`, 백분위 `100`이다. `N == 0`이면 순위와 백분위를
비운다. 같은 값은 같은 순위와 백분위를 받는다.

## 산출물

네트워크 없이 실행하는 빌더는 다음과 같다. 빌더는 실행 중 네트워크 연결을
차단한다.

```text
scripts/build_sector_rs_ranking_v01.py --as-of YYYY-MM-DD
```

운영 조율에서는 빌더의 기본값을 쓰지 않고 기준일을 명시해 전달한다.

순위 계산의 핵심 구현은 다음과 같다.

```text
src/trend_scanner/relative_strength/sector_ranking.py
```

산출물은 `web/data` 밖에 기준일별로 저장한다.

```text
data/analytics/sector_rs_ranking/v01/sector_rs_ranking_YYYYMMDD.parquet
data/analytics/sector_rs_ranking/v01/sector_rs_ranking_YYYYMMDD_meta.json
```

Parquet은 `market`, `sector_code`, `ticker` 순으로 정렬해 저장한다. 화면
정렬은 이후 웹 전달 단계에서 정한다.

메타데이터에는 `schema_version`(`SECTOR_RS_RANKING_V01`), 범위 유형
`scope.type`(`TARGET_PIT_COMMON_POPULATION`), 선택한 섹터 구성 효력일
(`membership_effective_date`), 모집단과 섹터 구성 정보의 대조 건수, 입력
파일 SHA-256, 검증 결과, Parquet SHA-256을 기록한다. `scope.type`이 다른
기존 산출물은 이 계약 이전 방식(섹터 구성 스냅샷을 모집단으로 사용)으로 만든
것이다.

## 출력 필드

각 행에는 기준일 식별값(`as_of`, `ticker`, `market`), 섹터 구성
(`membership_status`, `sector_code`, `sector_name`), 업종 RS 출처·상태
(`sector_rs_data_status`, `sector_rs_input_reason`,
`sector_benchmark_last_observation_date`), 다섯 기간의 `sector_rs_*` 값과
다음 순위 필드가 들어간다.

```text
within_sector_rs_rank_2w/1m/3m/6m/12m
within_sector_rs_percentile_2w/1m/3m/6m/12m
sector_member_count
sector_eligible_count_2w/1m/3m/6m/12m
```

다음 필드는 화면 표시용이며 순위 계산에 쓰지 않는다.

```text
latest_close
latest_close_as_of
sector_anchor_date_2w/1m/3m/6m/12m
sector_stock_return_2w/1m/3m/6m/12m
```

- `latest_close`는 기준일 당일의 양수 종가만 쓴다. 가까운 날짜나 미래 날짜로
  대체하지 않는다.
- `sector_stock_return_H`는 `latest_close / 업종 기준점 날짜의 종목 종가 - 1`이다.
  기준점 날짜는 기준일보다 늦을 수 없다.

기존 전체 업종 RS 순위 필드(`all_sector_rs_*`)는 이 계약에서 쓰거나 바꾸지
않는다.

## 검증

빌더는 산출물을 쓰기 전에 다음을 검증하고, 하나라도 어긋나면 중단한다.

- 결과의 종목 집합과 시장이 기준일 PIT COMMON과 정확히 같고 중복 종목이 없다.
- `MAPPED`·`AGGREGATE_ONLY` 행은 `sector_code`와 `sector_name`이 있다.
- `READY` 행의 업종 지수 마지막 관측일은 기준일과 같다.
- 순위는 `1` 이상 기간별 참여 종목 수 이하, 백분위는 `0` 이상 `100` 이하다.
- `latest_close`가 있으면 양의 유한값이고 `latest_close_as_of`는 기준일과
  같다. `latest_close`가 없으면 `latest_close_as_of`도 비어 있다.
- `sector_stock_return_*`는 값이 있을 때 유한값이며 기준점 날짜가 있어야 한다.
- 기준점 날짜가 있으면 기준일보다 늦지 않다.

## 범위 밖

- 웹 전달 데이터와 화면(섹터 선택기, JavaScript, CSS, GitHub Pages):
  [업종 RS 웹 전달 계약](../web/sector_rs_web_payload_v01.md)에서 관리한다.
- Stock Report 재생성
- 시장 RS, 외국인 수급, 거래대금, Fundamentals, Pattern A, A FAST
- 전체 종목 스캐너
- 섹터 구성 정보와 업종 지수의 수집·갱신: 분석 입력 갱신 기준 §4.4·§4.5에서
  관리한다.
- OpenDART, Naver, PyKRX, KRX Open API, 직접 HTTP 호출
