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

## 12개월 및 24개월 표시 이력

- `monthly_history.recent_12m_history`와 기존 Pattern B `monthly_history`는 기존 계약 그대로 유지한다. B Select 및 기존 소비자는 이 필드를 계속 사용한다.
- Pattern A에는 `monthly_history.recent_24m_history`를 추가한다. 기존 `full_monthly_history`의 tail projection이며 t-24M부터 현재 관측까지 최대 25개 월말 행을 담는다. 상장 이력이 짧으면 존재하는 행만 담는다.
- Pattern B에는 `monthly_history_24m`를 추가한다. 기존 `evaluate_pattern_b`와 동일 daily authority / PIT identity chain으로 t-24M 범위와 현재 `as_of`를 평가해 최대 25개 행을 담는다. lookback 부족은 기존 evaluator처럼 `UNAVAILABLE`로 남기며 추정하거나 nearest-date 대체를 하지 않는다.
- Web의 `pattern.history_24m`는 Pattern A source history의 projection이고, `pattern_b.monthly_history_24m`는 source report 값을 그대로 전달한다. 새 계산 권위나 전략 semantics를 추가하지 않는다.

## Markdown 위치

Markdown 리포트는 현재 스냅샷 다음에 기존 `1.5. 펀더멘털`을 유지하고,
`1.6. Pattern B 정보 분석`을 추가한다. 나머지 절의 순서와 의미는 v0.5 계약을
그대로 따른다.
