# 종목 리포트 계약 v0.7 — COMMON Pattern B 정보 분석

## 목적과 버전 경계

v0.7은 [v0.5 계약](contract_v05.md)의 공통 리포트 및 펀더멘털 계약을 유지하고,
COMMON 종목의 Pattern B 정보 분석을 공식 출력으로 추가한다. v0.5는 이전 COMMON
계약 기록으로 유지하며, ETF36의 Julia V1은 독립적인 v0.6 계약을 따른다.

v0.7의 JSON 구조는 [schema_v07.json](schema_v07.json)을 따른다. 이 스키마는
`report_version="0.7"`, `asset_type="COMMON"`, 필수 `fundamentals`와
`pattern_b`를 검증한다.

## Pattern B 정보 분석

- `pattern_b`는 모든 COMMON v0.7 리포트에 포함한다. 공식 데이터를 평가할 수 없는
  경우에도 섹션을 생략하지 않고 `evaluation_status=UNAVAILABLE` 및 사유 코드를
  기록한다.
- `pattern_b_state`는 기존 권위의 `DEEP_DEPRESSED`, `DEPRESSED`, `NORMAL`,
  `OVERHEATED`, `EXTREME_OVERHEATED` 중 하나이며, 값이 없으면 `null`이다.
- 현재 상태, 36개월 범위 위치, 24개월선 이격률, 52주 범위 위치, 월별 이력,
  마지막 월봉·주봉 및 freshness는 기존 `evaluate_pattern_b`와
  `pattern_b_operational` 계약에서 가져온다. 임계값·계산식을 새로 정의하지 않는다.
- `as_of`는 `reference_market_date`와 같고 가격 이력에 이 날짜 이후 행을 포함하지
  않는다. 월별 이력은 동일 evaluator를 날짜별로 적용한다.
- `provenance`는 MarketDataRepositoryV2, PIT identity authority, feature/state 및
  운영 계약 버전, 유효 이력 구간과 시장 이전 연결 여부를 기록한다.

## 전략 및 기존 필드 의미

- Pattern B는 종목의 장기 위치와 상태를 보여주는 정보성 분석이다.
  `B Select Core V1` 매매 전략 실행이나 매수·매도 신호가 아니다.
- `pattern_b`를 `a_fast_core` 또는 A FAST Core V2 라우팅에 연결하지 않는다.
- Pattern A, fundamentals, foreign flow, market/sector RS 및 기존 전략 필드의
  의미와 산식은 변경하지 않는다.
- v0.7은 COMMON 전용이다. ETF36 / Julia V1 v0.6의 스키마·생성·산출물에는 적용하지
  않는다.

## Web 투영

- Web exporter는 v0.7의 `pattern_b`를 report JSON에서 그대로 전달한다.
- exporter에서 Pattern B 계산, 네트워크 조회, proxy 또는 결측 대체를 하지 않는다.
- UI의 카드·그래프·상세 표시는 정보 제공이며 매매 전략 실행을 뜻하지 않는다.

## Markdown 위치

Markdown 리포트는 현재 스냅샷 다음에 기존 `1.5. 펀더멘털`을 유지하고,
`1.6. Pattern B 정보 분석`을 추가한다. 나머지 절의 순서와 의미는 v0.5 계약을
그대로 따른다.
