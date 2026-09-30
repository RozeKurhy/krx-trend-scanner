# Stock Report v0.6 — Official ETF 36 / Julia V1

## 목적과 적용 범위

v0.6은 frozen Official ETF 36 종목 전용 리포트다. 공통 기술·월별 이력·수급·RS·
거래대금 섹션은 v0.5 생성기의 계산을 재사용하고, 공식 전략 상태와 거래 이력은
Julia V1 (`JULIA_ETF_STRATEGY_V01`)로 제공한다. 일반 종목 v0.5의 의미와 생성
경로는 바꾸지 않는다.

ETF v0.6은 `a_fast_core`를 포함하지 않는다. 해당 필드는 v0.5에서 A FAST Core V2
전략을 뜻하며 Julia V1을 담는 용도로 재사용할 수 없다. ETF 전략은 최상위
`official_strategy`에만 둔다. B Select Core V1은 기본 전략 라우팅에 넣지 않는다.

## 기준일과 데이터 권위

- `requested_as_of`는 요청 분석 기준일이다. `reference_market_date`는 실제 KRX
  시장 관측 기준일이다.
- 공통 리포트 계산과 Julia lifecycle은 모두 `MarketDataRepositoryV2`가 제공하는
  rolling local authority 경계 안의 로컬 데이터만 쓴다. ETF 조정/원시 가격 세션이
  일치하지 않는 경우 v0.6은 exact raw OHLCV를 공통 계산에도 명시 주입하고,
  nearest/proxy/inner-join 보정은 하지 않는다. JSON provenance에 이 source를 남긴다.
- Julia lifecycle은 `JULIA_STRATEGY_V00` evaluator를 변경 없이 사용한다.
  `Pre-PROGRESSED Loss Guard`는 비활성화한다.
- ETF PIT eligibility ID는
  `ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`이다. Official ETF 36,
  상장 2년, signal-date raw close 1,000원 이상, signal date를 포함한 직전 20개
  실제 KRX 세션의 평균 raw volume 10,000주 이상이 필요하다.
- strategy-ready 및 clean-ready 이전 신호는 제외한다. 진입 체결은 다음 실제 KRX
  거래일의 정확한 원시 시가만 허용한다. 결측을 채우거나 가장 가까운 날, proxy,
  synthetic 값을 쓰지 않는다.
- Phase10 시가총액·거래대금 조건은 Julia ETF eligibility가 아니다. v0.6은
  해당 필드를 `NOT_APPLICABLE`로 표시한다.
- 네트워크 요청은 0건이다.

## JSON 계약

JSON 구조는 [schema_v06.json](schema_v06.json)을 따른다. v0.5의 공통 섹션을
보존하고 아래를 추가한다.

- 최상위 `readiness_status`, `readiness_reason`
- `current_snapshot.etf_eligibility`: membership, 상장 연령, 정확한 raw close,
  20-session 평균 volume, eligibility, strategy/clean readiness
- 최상위 `official_strategy`: 전략 식별자, 상태/행동, 진입 checklist, 현재 포지션,
  protection/re-entry 상태, 거래 이력, eligibility 계약과 실행 provenance

`official_strategy.strategy_id`, `.strategy_name`, `.strategy_version`,
`.asset_scope`, `.eligibility_contract`는 각각 `JULIA_ETF_STRATEGY_V01`,
`Julia V1`, `V1`, `OFFICIAL_ETF_36`,
`ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`로 고정한다. `provenance`에는
실행 evaluator `JULIA_STRATEGY_V00`와 loss guard 비활성 상태를 기록한다.

Readiness는 다음과 같이 결정한다.

- `READY`: raw history가 60세션 이상이고, 기준일 exact raw close 및 20-session
  volume window가 있으며, Julia evaluator 오류가 없고 Pattern A/data quality,
  Pattern A FAST, 수급, 적용 가능한 RS, 거래대금 공통 섹션이 준비됐다. ETF에서
  적용 제외인 Phase10 Investability 상태는 readiness를 낮추지 않는다.
- `PARTIAL`: 생성은 가능하지만 기준일 가격/volume 창이나 공통 섹션 일부가
  준비되지 않았거나 Julia 보조 evaluator 오류가 있다. 사유는 `readiness_reason`에
  섹션별로 기록한다.
- `DATA_UNAVAILABLE`: raw history가 없거나 60세션 미만이라 Julia evaluator를
  판정할 수 없다.

기준일에 미래 거래일이 로컬 authority에 없으면 신규 ENTRY를 만들지 않는다.
청산 신호는 `EXIT_NEXT_OPEN`과 pending 상태로 남기며, 체결 시가를 만들지 않는다.

## Markdown

ETF v0.6의 전략 절 제목은 `Julia V1 전략 상태`다. 핵심 요약은 `Julia V1: WAIT`,
`Julia V1: ENTRY`, `Julia V1: HOLD_PRE_PROGRESSED`,
`Julia V1: HOLD_PROGRESSED`, `Julia V1: EXIT` 중 현재 상태를 먼저 표시한다.
진입 checklist는 ETF36 membership, 상장 기간, raw 가격/volume, readiness,
Pattern A / FAST 조건, no-open 조건, 다음 실제 KRX 시가 가능 여부를 보여준다.
전략 절은 `Pre-PROGRESSED Loss Guard: DISABLED`를 명시한다.

## 산출 위치

```text
artifacts/reporting/etf_stock_reports/<YYYYMMDD>/
  *.md
  json/*.json
  generation_summary.json
```

이 위치는 `artifacts/reporting/stock_reports/`의 일반 종목 v0.5 및 웹 exporter와
분리한다. 이 계약은 웹 UI, Phase 4 자동 실행, 전략 모니터 또는 주문 연결을
의미하지 않는다.
