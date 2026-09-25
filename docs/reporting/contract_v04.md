# 종목 리포트 계약 v0.4 — 업종 상대강도 추가

## 목적

v0.4는 [v0.3 계약](contract_v03.md)의 모든 필드와 의미를 유지하고 최상위
`sector_relative_strength` 섹션을 추가한다.

## 기계 계약

- Draft 7 스키마: `docs/reporting/schema_v04.json`
- `report_version`은 문자열 `0.4`다.
- v0.3 계약과 스키마는 변경하지 않는다.
- 기존 최상위 `relative_strength`는 시장 RS 전용이며 v0.4에서도 유지한다.
- 새 최상위 `sector_relative_strength`는 업종 RS 전용이다.

## 데이터 권위와 시점

- 종목 가격은 운영 경로에서 `MarketDataRepositoryV2`를 사용한다.
- 섹터 구성 정보는 요청 기준일(`requested_as_of`)과 날짜가 정확히 같은 승인
  스냅샷만 사용한다.
  `data/market/sector_membership/v01/sector_membership_YYYYMMDD.parquet`
- 스냅샷의 효력일(`effective_date`)은 요청 기준일과 같아야 한다. 이전
  스냅샷 재사용, 미래 스냅샷의 소급 적용, 가까운 날짜 대체는 허용하지 않는다.
  정확한 날짜의 스냅샷이 없으면 업종 RS를 계산하지 않고, 섹션을 산출 불가
  (`DATA_UNAVAILABLE`)로 두며 사유 `SECTOR_MEMBERSHIP_SNAPSHOT_UNAVAILABLE`을
  기록한다. 리포트 생성은 계속한다.
- 업종 지수는 다음 로컬 캐시만 사용한다.
  `.cache/krx_openapi/sector_rs_migration/v01/sector_index_daily.parquet`
- 업종 RS는 기존 `compute_relative_strength_features(...)`를 재사용하며 종목
  수익률, 업종 수익률, RS 비율, 기준점을 새로 구현하지 않는다.
- 업종 RS 순위·백분위는 이 섹션에 포함하지 않는다. 업종 내 순위는
  [업종 내 상대강도 순위 계약](../relative_strength/sector_rs_ranking_v01.md)에서
  별도로 관리한다.

## 적용 범위와 상태

- KOSPI/KOSDAQ 보통주(`COMMON`)는 적용 대상(`APPLICABLE`)이며, 후보 여부와
  관계없이 업종 RS 평가를 시도한다.
- 정상 산출 (`READY`): 3개월·6개월·12개월 기준 기간이 모두 산출됨
- 일부 산출 (`PARTIAL`): 기준 기간 일부의 이력이 부족함. 2주·1개월은 짧은
  기간 추가 항목이며 기간별로 따로 `null`일 수 있다.
- 산출 불가 (`DATA_UNAVAILABLE`): 섹터 구성, 기준일 종목 가격, 업종 지수 또는
  기준점 입력이 부족함
- ETF·ETN·우선주 등 비대상 종목은 적용 제외(`NOT_APPLICABLE`)·미평가
  (`NOT_EVALUATED`)이며 숫자 필드는 모두 `null`이다.
- 업종 RS 상태는 리포트 전체의 `header.report_status`를 낮추지 않는다.

## 표시와 서술

- 핵심 요약에 `업종 상대강도` 요약 항목과 서술을 추가한다.
- Markdown에서는 시장 RS 절 `## 7.5. 시장 상대강도 (RS)` 뒤, 거래대금 앞에
  `## 7.6. 업종 상대강도 (Sector RS)`를 표시한다.
- 업종 절은 적용 상태, 데이터 상태, 업종명과 코드, 업종 지수 기준일,
  2주·1개월·3개월·6개월·12개월 업종 대비 RS와 업종 수익률, 규칙 기반 해석,
  출처를 표시한다.
- 업종 RS는 참고·확인용 정보이며 매매 추천이나 새로운 점수를 제공하지 않는다.

## 출처 기록

업종 섹션 안에 다음을 기록한다.

- `source_as_of`
- `membership_snapshot_date`: 실제 사용한 섹터 구성 스냅샷의 효력일
- `membership_source`: 실제 사용한 섹터 구성 스냅샷 파일 경로
- `sector_index_source`
- `input_reason`: 산출하지 못한 사유가 있는 경우

## 전략과 기존 섹션 보호

- Pattern A 산식·단계, 후보 판정, 투자 적격성, 외국인 수급, 시장 RS, 거래대금,
  Pattern A FAST, A FAST Core, 진입·보유·청산, `report_status`의 의미는
  바꾸지 않는다.
- `relative_strength`는 기준일과 날짜가 정확히 같은 시장 RS 권위 CSV를 계속
  소비한다.
- 업종 RS 때문에 시장 RS를 다시 계산하거나 스캐너를 호출하지 않는다.

## 호환성

v0.4 JSON은 v0.3의 모든 최상위 섹션을 보존하고 `sector_relative_strength`만
추가한다.
