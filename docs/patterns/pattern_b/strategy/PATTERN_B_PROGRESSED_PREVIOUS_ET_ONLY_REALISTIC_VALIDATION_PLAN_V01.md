# Pattern B E/T-only 현실 포트폴리오 최종 심사 계획 V01

작성일: 2026-09-28 KST
시작 HEAD: `90e3fdfe097233a1e05e85905e11317b10e27afd`

이 문서는 백테스트 결과를 산출하기 전에 실행 계약과 공식 채택 기준을 봉인한다. 결과 확인 뒤 기준을 수정하지 않는다. 기준 변경이 필요하면 별도 revision으로 새 심사를 시작한다.

## 1. 목적과 동결 규칙

심사 대상은 `PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01` 하나다. 기본 전략 선정, A FAST Core V2와의 우열 비교, 기본 전략 교체는 범위에 넣지 않는다.

진입은 Pattern B가 `DEPRESSED`이고, 현재 Pattern A Stage가 `PROGRESSED`이며, 직전 Pattern A Stage가 `{EARLY_TREND, TRANSITION}`일 때만 허용한다. 보유 중 Pattern B `NORMAL`을 관측하면 다음 exact KRX session open에 전량 청산한다. 손절, DEEP exit, Pattern A exit, stage 변경, threshold sweep, 결과 기반 튜닝, 시가총액·거래량 자격 필터를 추가하지 않는다.

## 2. 표준 기간과 데이터

Repository V2의 날짜별 PIT universe와 가격 자료, 기존 43개 exact permanent identity exclusion을 사용한다. 현재 종목 목록을 과거에 방송하거나 현재 상장폐지 여부로 과거 분모를 제거하지 않는다. 새 시가총액·거래량 필터를 두지 않는다.

| Window | Effective start | Effective end | Execution support |
|---|---|---|---|
| P1 | 2014-01-02 | 2026-08-31 | 2026-09-01 |
| P2-1 | 2021-01-04 | 2025-05-30 | 2025-06-02 |
| P2-2 | 2021-01-04 | 2026-08-31 | 2026-09-01 |
| P3-1 | 2022-01-03 | 2025-05-30 | 2025-06-02 |
| P3-2 | 2022-01-03 | 2026-08-31 | 2026-09-01 |

신호와 신규 진입은 effective end까지로 제한한다. execution support는 effective end 전에 발생한 청산 신호의 후속 체결에만 사용하고 신규 진입에는 사용하지 않는다. 신호/시장자료 worker 수는 10이며, 포트폴리오 현금 및 자산가치 replay는 결정론적 순차 처리다.

## 3. 포트폴리오와 주문 계약

- 초기 현금 `C0 = 200,000,000 KRW`.
- 신규 포지션별 최대 총 매수 현금예산 `5,000,000 KRW`; 매수 명목금액과 매수 수수료 합이 이 예산 이하인 최대 정수 수량을 산출한다.
- 매도 수익금은 재투자한다. 동시 보유 종목 수에 인위적 cap을 두지 않는다.
- 부분 체결은 금지한다. 정상 신호·가격·identity를 갖춘 주문에 가용 현금이 부족하면 전량 `SKIPPED_CASH_UNAVAILABLE`로 기록한다.
- 당일 이벤트는 거래일 오름차순, 기존 정산 가능 현금 반영, 매도, 매수 순서다. 매도 체결대금은 기존 certified realistic portfolio runner와 같이 다음 exact KRX session부터 사용 가능하다. 같은 시가 매도대금은 신규 주문 재원으로 쓰지 않는다.
- 같은 ISU 동시 중복 보유와 피라미딩을 금지한다. 동일 시가 청산 후 같은 ticker 재진입을 금지한다.
- 같은 시가 신규 주문 우선순위는 기존 runner의 PIT 신호일 시가총액 내림차순, ticker 오름차순, position ID 오름차순이다. 이는 현금 배분용 결정론적 동률 규칙이며, 자격 필터가 아니다. PIT 우선순위 값이 없으면 대체값을 만들지 않고 실행 계약의 unresolved 상태로 남긴다.
- 40개 등 숨은 보유 cap이 0인지 주문·일별 보유 원장으로 검증한다.
- 이벤트·정산 의미론의 구현 기준은 `scripts/run_p2_1_realistic_portfolio_v01.py::_portfolio_replay`다. 이 helper의 검증된 현금 정산과 이벤트 순서를 재사용하되, 이번 계획의 무제한 보유와 후보별 이벤트 원장을 입력으로 사용한다.

## 4. 비용 계약과 세율 공백 처리

- 매수·매도 수수료율 각각 `0.00015`.
- 매수 슬리피지 `+0.001`, 매도 슬리피지 `-0.001`을 기준 체결 시가에 적용한다.
- 매도세는 실제 매도 체결일과 시장에 적용되는 Repository 내 검증된 역사 세율 authority만 사용한다.
- 현재 코드의 세율표 source는 `scripts/run_v2_julia_official_validation_v01.py::HISTORICAL_SELL_TAX_SCHEDULE`이며 첫 적용일은 2021-01-01이다. P1의 2014~2020을 덮는 Repository authority가 추가로 확인되지 않으면 아래 `CHECK_REQUIRED` 처리를 적용한다.
- P1의 2014~2020 매도세율 authority가 Repository 안에서 확인되지 않으면 해당 연도에 임의 세율을 적용하지 않는다. P1 비용 완결성을 `CHECK_REQUIRED`로 표시하고, 누락 세금으로 현금 경로가 바뀌는 P1 포트폴리오를 완결된 결과로 간주하지 않는다. 세금 누락 realized exit가 하나라도 있으면 Gate B는 통과하지 않는다.
- 열린 포지션의 종가 평가는 실제 매도가 아니므로 청산 수수료·세금·매도 슬리피지를 차감하지 않는다.

각 window의 `execution_contract.json`에는 수수료/슬리피지, 실제 적용된 세율표와 authority 출처, 날짜·세션 정산, 매도·매수 순서, 신규 매수 배분 순서, 부분체결 및 현금 부족, 동일 시가 재진입, 미청산 평가 조건을 기록한다.

## 5. 포트폴리오 lifecycle 및 현금 skip 감사

기존 trade ledger에 대한 현금만의 사후 replay를 자동으로 최종 결과로 인정하지 않는다. 현금 부족으로 진입을 건너뛴 뒤 해당 identity가 flat이 되면서 기존 unconstrained ledger에 억제된 후속 eligible signal이 있었는지 확인한다.

다음 중 하나를 충족해야 포트폴리오 결과를 Gate A에 사용할 수 있다.

1. 현금 승인/skip 상태를 lifecycle state에 반영하는 portfolio-aware lifecycle replay를 실행하고 이후 신호를 다시 평가한다.
2. 또는 모든 현금 skip 이후 해당 identity에 대해 effective end까지의 전체 eligible signal stream을 exact audit하여 ledger-only replay가 누락한 후속 진입이 0건임을 입증한다.

증명이 불완전하면 lifecycle 결과는 `CHECK_REQUIRED`이며 최종 채택 판단에 쓸 수 없다. 원천 전체 재수집이나 무관한 feature 재계산은 하지 않는다.

현금 부족률의 분모는 전략/PIT 조건 통과, identity 및 정확한 체결 가격 정상, 같은 시가 재진입 금지와 현재 포지션 상태를 반영해 현금만 충분하면 실제 진입할 수 있었던 attempt 수다. 분자는 그중 오직 현금 부족 때문에 skip된 건이다.

## 6. 일별 평가와 지표

각 exact 거래일에 현금, 미정산 매도대금, 미청산 포지션별 정확한 시장가치, 총 equity, 직전 고점, drawdown, 동시 보유 수를 기록한다. 포지션 평가는 각 거래일의 해당 identity exact close만 사용한다. nearest-day, proxy, 임의 forward-fill은 금지하며 exact daily close가 없으면 `UNRESOLVED`로 남긴다.

- `equity_t = cash_t + pending_settlement_t + Σ(open shares × exact close_t)`.
- 총수익률 `ending_equity / C0 - 1`.
- CAGR은 effective start일부터 effective end일까지 실제 calendar duration을 사용한다.
- 고점은 누적 equity 최고값, `drawdown_t = equity_t / running_peak_equity_t - 1`; MDD는 일별 drawdown 최솟값이다.
- 회전율은 `Σ(actual buy notional + actual sell notional) / C0`. 비용·세금 차감 전 실제 체결 명목금액으로 계산하며 미체결/skip 및 terminal open 평가액은 제외한다.
- effective end의 terminal open position은 그 날짜 exact close로 표시한다. 이를 실제 매도로 보지 않고 세금/매도비용/회전율에 넣지 않으며 현금화 또는 재투자하지 않는다. 정확한 종가가 없으면 임의 대체 없이 unresolved다.
- 보유기간은 진입 체결일부터 실제 청산 체결일까지다. terminal open은 종료 거래와 분리하고 검열 상태로 집계한다.
- 현금 보존, 미정산자금 흐름, 포지션 수량 및 일별 equity 연속성을 원장으로 재검산한다.

## 7. Hard Gate 및 판정

### Gate A — Integrity

5개 window 모두 PIT/identity PASS, lookahead 0, post-cutoff 신규 진입 0, lifecycle/duplicate/overlap violation 0, 현금 보존 PASS, 숨은 position cap 0, 일별 equity 연속성 PASS, exact valuation/settlement contract PASS여야 한다.

### Gate B — 비용 완결성

5개 window 모두 매수·매도 수수료 적용 100%, 슬리피지 적용 100%, realized sell tax의 authoritative schedule 적용 100%, 누락 비용 realized trade 0이어야 한다. P1 역사 세율 authority가 불완전하면 `CHECK_REQUIRED`; 임의 확장하지 않는다.

### Gate C — 순수익

각 window의 net total return과 CAGR가 모두 0 초과여야 한다.

### Gate D — Portfolio MDD

각 window의 equity curve MDD가 `-35%` 이상이어야 한다. 개별 거래 MAE로 대체하지 않는다.

### Gate E — 현금 부족

각 window의 cash shortage skip rate가 위 분모 정의 기준으로 `10% 미만`이어야 한다.

### Gate F — 결과 신뢰성

terminal unresolved가 return/MDD를 왜곡하거나 일별 평가 공백이 material한 경우 통과하지 못한다. 성과를 근거로 특정 종목을 사후 제거하지 않는다. 희귀 lifecycle 예외는 기존 영구 제외 정책과 필요한 사용자 승인 절차를 따른다.

### 필수 진단

각 window와 통합 보고서에 positive trade rate, median net trade return, +30/+50/+100 및 -30/-40/-50/-60 수익률 꼬리, 평균/중앙/P90 보유기간, 최대/평균 동시 보유, 현금 활용도, turnover, 연도별 성과, ticker 손익 집중도와 상위 5개 승자·패자 기여, DEEP arrival, unresolved/open 수를 보고한다. 단일 진단 수치만으로 자동 탈락시키지 않는다.

### 최종 판정

- `OFFICIAL_STRATEGY_ADOPTED`: A~F 전부 통과하고 material structural issue가 없다.
- `NOT_ADOPTED`: 증거가 완결됐으나 사전 Hard Gate 중 하나 이상 실패했다.
- `HOLD`: 세율 authority, lifecycle replay, terminal valuation, equity curve 등 필요한 증거가 불완전하다. 후보 규칙은 그대로 유지한다.

## 8. 사전 실행 성능 점검 및 산출물

이 계획을 먼저 commit/push한 뒤에만 대표 preflight를 실행한다. 실제 동일 실행 경로로 wall time, CPU, RSS와 처리 대상을 측정하고 5개 window 전체 예상시간을 기록한다. 과도한 실행시간이 확인되면 병목과 효과를 제시한 최소 수정만 검토한다. 자동 재실행하지 않는다.

결과는 `artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_realistic_portfolio_v01/` 아래에 기록한다. 최소 산출물은 `execution_contract.json`, `preflight.json`, window별 portfolio event/equity 원장, skipped entry, cost/cash/valuation audit, portfolio metrics, 5-window summary, official adoption gates, `report.md`, `summary.json`, `metadata.json`이다. 기존 대형 ledger는 복사하지 않고 source path와 SHA-256으로 참조한다.

구조적 문제 발견 시 문제와 영향 범위를 먼저 보고한다. 결과에 따른 규칙 변경, 임의 세율 생성, 자동 retry는 하지 않는다.
