# Julia V1 — ETF 전용 공식 전략

## 현재 공식 상태

- 공식 표시명: **Julia V1**
- 공식 전략 ID: **JULIA_ETF_STRATEGY_V01**
- 공식 상태: **OFFICIAL_STRATEGY_ADOPTED**
- 적용 범위: **OFFICIAL ETF 36 ONLY**
- 일반 종목 적용: **금지**. JULIA_STRATEGY_V00의 일반 종목 상태는 NOT ADOPTED / RETIRED AS GENERAL-STOCK OFFICIAL STRATEGY로 유지한다.
- 기본 전략/CONTROL: A FAST Core V2가 계속 담당한다. Julia V1은 기본 전략이나 CONTROL이 아니다.
- 자동 주문: 승인하지 않는다.
- 현재 연결 상태: Stock Report, Phase 4 전략 모니터, ETF 리포트, 운용 UI 및 자동 주문에 연결되지 않았다.

## V00에서 V1로의 공식 계보

JULIA_STRATEGY_V00은 ETF 공식 채택 심사의 실제 검증 후보 ID다. 해당 후보는 다섯 표준 window에서 공통 A~E gate를 모두 통과해 총 25/25 PASS를 기록했고 ETF 전용 공식 전략으로 채택되었다. 이번 문서는 그 공식 승격 이름과 ID를 Julia V1 / JULIA_ETF_STRATEGY_V01로 기록한다.

### Lifecycle 규칙

Julia V1은 검증 후보 `JULIA_STRATEGY_V00`의 진입·보유·청산 lifecycle 규칙을 변경 없이 계승한다. A FAST Core V2와 비교한 기존 단일 전략 차이인 `Pre-PROGRESSED -15% Loss Guard = disabled`도 그대로 유지한다. 새 threshold나 진입·보유·청산 조건을 추가하지 않았다.

### ETF eligibility 계약

ETF 자산 적격성은 일반 종목용 investability 계약을 사용하지 않는다. 공식 ETF 검증에서 사용한 ETF 전용 계약 `ETF_PIT_LISTED_2Y_CLOSE_1000_VOL20_10000_V01`을 적용한다. JULIA_STRATEGY_V00의 lifecycle 계승과 ETF eligibility는 별도 규칙이다.

- Universe는 frozen **OFFICIAL ETF 36**이다.
- 각 signal date는 해당 ETF의 상장일로부터 2년 이상 지난 날짜여야 한다.
- 해당 signal date의 실제 KRX 원시 종가가 1,000원 이상이어야 한다.
- 해당 signal date를 포함한 직전 20개 실제 KRX 거래일의 평균 거래량이 10,000주 이상이어야 한다.
- 위 조건은 signal date별 point-in-time ETF eligibility로 판정하며, 그 날짜의 eligibility가 PASS여야 한다.
- 신호는 장 마감 후 판정하고, 진입은 다음 실제 KRX 거래일의 해당 ETF 원시 시가가 존재할 때만 가능하다. 평가 window의 종료 뒤에 체결되는 신규 진입은 포함하지 않는다.
- 각 ticker/window의 평가 span은 `max(window_start, strategy_ready_date, clean_ready_date)`부터 시작한다. strategy-ready가 window 시작보다 늦으면 그 실제 날짜를 effective start로 사용해 partial window로 평가하고, effective start가 window 종료 뒤면 해당 span은 평가 불가로 둔다.
- clean-ready는 신호 입력에 필요한 일간·주간·월간 lookback에서 zero-OHLC sentinel 영향이 제거된 첫 유효 주간 기준일이다.
- 상장 전 또는 strategy-ready/clean-ready 이전 날짜를 채워 넣지 않는다. nearest-date 대체, proxy 또는 synthetic eligibility/가격 데이터도 사용하지 않는다.

구현 근거는 [ETF eligibility 및 Julia 실행 경로](../../../scripts/run_etf_current_survivors_raw_price_three_strategy_simple_backtest_v03.py), [5-window effective span 검증 경로](../../../scripts/run_etf_36_afast_v2_vs_julia_5window_simple_v01.py), [clean-ready span closure 결과](../../../artifacts/research/etf_36_zero_ohlc_sentinel_clean_eligibility_closure_v01/summary.md)에 있다.

기존 V00 evaluator, 코드 심볼, ledger 및 연구 산출물은 실제 검증 이력을 보존하기 위해 JULIA_STRATEGY_V00 이름으로 유지한다. 별도의 Julia V1 evaluator 구현이나 코드 migration은 이 문서 승격 범위에 포함하지 않는다. 현재 ID는 공식 문서상의 전략 식별자이며 실행기 연결을 의미하지 않는다.

## 검증 근거

- 심사 보고서: [Julia V00 ETF 전용 공식 채택 심사 V01](../../../artifacts/strategies/julia/etf_official_adoption_v01/report.md)
- A~E gate 및 수치: [validation.json](../../../artifacts/strategies/julia/etf_official_adoption_v01/validation.json)
- 입력 해시: [source_hashes.json](../../../artifacts/strategies/julia/etf_official_adoption_v01/source_hashes.json)
- 검증 당시 후보 계약: [V00 contract](../../../artifacts/strategies/julia/v00/contract.json)
- 공식 ETF 36 기준: [frozen universe](../../../artifacts/research/etf_36_afast_v2_vs_julia_5window_simple_v01/official_etf_universe_36.csv)

채택 심사는 초기 자본 250,000,000원, 종목당 15,000,000원 한도를 공식 포트폴리오 시나리오로 사용했다. 수수료와 슬리피지를 반영하고 거래세는 공식 손익에서 제외했다. 25,000,000원 시나리오는 민감도 진단이며 공식 gate가 아니다. V2 상대 MDD 기준은 독립 ETF 전략의 첫 채택 심사에 적용하지 않았다.

## 운용 특성과 한계

심사 결과에서 장기 보유와 낮은 회전, 일부 window의 높은 ETF 손익 집중도가 확인됐다. window별 평균 보유기간은 약 536~751 거래일이고, turnover는 초기 자본 대비 약 1.33~5.45회였다. 상위 5개 ETF의 순손익 기여율은 window에 따라 약 50%에서 242%까지 달랐다. 100% 초과는 손실 포지션의 상쇄로 순손익 분모가 줄어든 경우를 포함한다. 이 특성들은 사전 고정 심사 진단이며 새 채택 threshold는 아니다.

공식 채택은 자동 주문 승인, 기본 전략 승격, 일반 종목 적용 또는 Phase 4·Stock Report 연결을 뜻하지 않는다. 운영 연결이 승인되는 별도 작업이 있기 전까지 Julia V1은 ETF 전용 공식 전략 문서 상태로 관리한다.

## 과거 기록

V00 당시의 규칙 계획, 검증 결과와 archive 문서는 과거 기록으로 유지한다. 해당 문서와 artifacts의 JULIA_STRATEGY_V00 표기는 실제 검증에 사용된 ID이므로 V1로 일괄 치환하지 않는다. 현재 공식 ETF ID는 JULIA_ETF_STRATEGY_V01이다.
