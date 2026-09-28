# 공식 전략 공통 채택 기준

작성일: 2026-09-28 KST

## 1. 목적과 적용 범위

이 문서는 A FAST Core V2를 포함해 프로젝트에서 공식 전략으로 검토하는 모든 전략과 후보에 적용하는 공통 최소 기준이다. 백테스트 실행·데이터·PIT·체결 원칙은 [`backtest_common_rules.md`](backtest_common_rules.md)를 따르고, 전략 생애주기와 기본 전략 분리 원칙은 [`strategy_lifecycle.md`](../strategies/strategy_lifecycle.md)를 따른다.

표준 기간은 `backtest_common_rules.md` §3.1의 P1, P2-1, P2-2, P3-1, P3-2다. 각 기간의 exact 거래일 해석, 데이터 authority 및 실행 계약은 해당 공통 원칙과 실행 계획에 따른다.

전략별 사전 계획은 실행 조건과 추가 진단을 정할 수 있다. 다만 공식 전략 재심사에서는 이 공통 Hard Gate를 완화하지 않는다. 결과를 확인한 뒤 이 기준을 변경하지 않으며, 변경이 필요하면 새 기준 revision과 새 검증 계획을 봉인한다.

## 2. 공통 Hard Gate

모든 Gate는 다섯 표준 window 각각에 적용한다. count, identity, status, date 및 범주형 integrity 값은 exact match를 사용한다.

### Gate A — Integrity

다음 구조적 오류가 없어야 한다.

- Point-in-Time universe·identity 위반
- lookahead 또는 cutoff 뒤 신규 진입
- 포지션 lifecycle 위반
- identity, duplicate 또는 overlap 오류
- 현금 보존·정산 오류
- 계약되지 않은 hidden position cap
- 결과에 영향을 줄 수 있는 미해결 구조적 데이터 문제

필수 원장과 계약의 count, identity, status, date는 exact하게 대조한다. 실행 계약에서 판정 가능한 검사는 모든 window에서 통과해야 한다.

### Gate B — 실행 비용

공식 채택용 핵심 성과에는 매수·매도 commission과 slippage를 100% 반영한다. 어느 한쪽이라도 누락된 체결이 있으면 통과하지 못한다.

거래세·매도세는 공식 채택 Gate와 공식 채택용 성과 산식에서 제외한다. 거래세 authority가 없다는 이유만으로 심사를 중단하거나 `CHECK_REQUIRED` 또는 `HOLD`로 판정하지 않는다. 거래세 자료가 있고 참고 민감도 분석이 필요하면 별도 진단으로 보고할 수 있지만, commission+slippage 기준 공식 수익률·CAGR·MDD, 현금 경로 및 Gate 판정을 대체하거나 바꾸지 않는다. 일부 window에만 거래세를 섞어 공식 지표를 계산하지 않는다.

### Gate C — 수익성

P1, P2-1, P2-2, P3-1, P3-2 각각에서 commission과 slippage를 반영하고 거래세를 제외한 기준으로 다음을 모두 충족한다.

```text
total return > 0
CAGR > 0
```

### Gate D — Portfolio MDD

다섯 window 각각에서 commission+slippage 기준 daily portfolio equity curve의 MDD가 다음을 충족한다.

```text
MDD >= -35%
```

개별 거래 MAE나 평균 손실로 대체하지 않는다.

### Gate E — 현금 부족

다섯 window 각각에서 다음 비율을 충족한다.

```text
cash_shortage_skip_rate < 55%
```

정확히 `55.00%`는 통과하지 못한다.

분모는 전략 규칙, PIT, lifecycle 및 체결 가격 조건을 모두 만족하여 현금만 충분하면 실제 진입할 수 있었던 entry attempt 수다. 분자는 그중 오직 현금 부족으로 `SKIPPED_CASH_UNAVAILABLE` 처리된 수다. 잘못된 identity·가격·lifecycle 등 현금 이외 사유의 실패는 분자나 분모에 섞지 않는다.

### Gate F — 결과 유효성

핵심 성과를 신뢰할 수 있어야 한다. 다음 문제가 material하면 통과하지 못한다.

- terminal valuation unresolved가 수익률 또는 MDD에 영향을 줄 수 있음
- daily equity의 평가 공백으로 핵심 지표를 계산할 수 없음
- nearest/proxy/forward-fill 등 임의 가격 대체
- 성과를 이유로 한 사후 종목 제거
- 결론을 바꿀 수 있는 미해결 구조·계산 오류

평가 불가 값은 임의 대체하지 말고 `CHECK_REQUIRED` 또는 `UNRESOLVED`로 남긴다.

## 3. 현금 부족률 진단 해석

Gate E는 최소 실행 가능성 기준이다. 통과가 좋은 자본 효율을 뜻하지 않는다. 현금 부족률은 반드시 별도 숫자로 보고하고, 설명이 유용하면 다음 참고 구간을 함께 쓸 수 있다.

| Skip rate | 참고 해석 |
|---|---|
| `<20%` | 양호 |
| `20% ≤ rate <35%` | 자본 제약 존재 |
| `35% ≤ rate <55%` | 자본 제약 큼 |
| `≥55%` | Gate E FAIL |

세 구간 라벨은 참고용이며 추가 Hard Gate가 아니다.

## 4. 필수 보고와 최종 판정

각 window에서 Gate별 상태와 근거를 남긴다. 최소한 다음을 보고한다.

- total return, CAGR, portfolio MDD
- 현금 부족률과 분자·분모, 현금 활용도
- commission·slippage 적용 여부
- 최대·평균 동시 보유, turnover, 미청산·unresolved 수
- 결과 해석에 필요한 거래·기간·종목 집중도 진단

필요한 핵심 값이 확정되지 않으면 해당 Gate를 `CHECK_REQUIRED`로 표시하고 어떤 자료가 왜 불완전한지 기록한다.

- `OFFICIAL_STRATEGY_ADOPTED`: A~F가 다섯 window 모두 PASS하고 material structural issue가 없음.
- `NOT_ADOPTED`: 필요한 증거가 완결됐으나 하나 이상의 Hard Gate가 FAIL.
- `HOLD`: 채택 판단에 필요한 핵심 증거가 unresolved 또는 불완전함. 거래세 authority 누락만으로는 HOLD 사유가 되지 않음.

## 5. V2 기준점과 기본 전략 분리

A FAST Core V2를 포함한 기존 공식 전략과 신규 후보에 동일 기준을 적용한다. 새 전략이 V2보다 모든 지표에서 우수해야 공통 Gate를 통과하는 것은 아니다. V2 대비 우위와 기본 전략 교체 여부는 별도 비교·승격 단계에서 판단한다.

공식 전략 채택은 프로젝트에서 사용할 수 있는 공식 전략으로 인정하는 결정이며, 기본 전략 승격이나 교체를 자동으로 뜻하지 않는다.

## 6. 역사적 검증 기록

이 기준은 적용 이후의 공식 전략 심사에 사용한다. 이전 실행 당시 별도 기준으로 봉인된 검증 계획과 산출물은 역사적 실행 기록으로 보존하며 이 문서에 맞춰 소급 수정하지 않는다. 과거 결과를 새 기준으로 심사할 필요가 있으면 기존 기록은 유지하고 재심사 범위와 새 기준 revision을 별도로 기록한다.
