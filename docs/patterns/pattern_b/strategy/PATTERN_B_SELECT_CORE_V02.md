# B Select Core V2

> 공식 표시명: **B Select Core V2**
> 전략 ID: `PATTERN_B_SELECT_CORE_V02`
> 공식 상태: `OFFICIAL_STRATEGY_ADOPTED`

## 버전 관계와 역할

B Select Core V2는 B Select Core V1의 공식 후속 버전이다. V1은 당시 규칙과 거래 기록을
그대로 보존하는 역사적 공식 버전이다. V2는 V1의 진입 규칙과 유니버스를 계승하고,
청산 신호 관측만 월말에서 매 완료 exact KRX 거래일로 바꾼다.

기본 전략·CONTROL은 계속 A FAST Core V2 (`PATTERN_A_FAST_FINAL_STRATEGY_V02`)다.
Julia V1 (`JULIA_ETF_STRATEGY_V01`)은 ETF 전용이다. 이 등록은 자동 주문을 승인하지 않는다.

## 유니버스와 제외

- 일반 COMMON 종목을 대상으로 한다.
- 정확 `(ticker, ISU_CD)` 영구 제외 권위 181쌍을 적용한다.
- 신규 신호·진입은 제외된 종목 식별자에 만들지 않는다.
- 승격 기준일에 V1에서 이미 OPEN인 포지션은 강제 청산하거나 재진입하지 않고, 기존 포지션의
  정확 종목 식별자와 진입 정보를 유지해 V2 청산 규칙으로 추적한다. 제외된 식별자는 기존
  포지션이 닫힌 뒤에도 신규 진입 대상이 되지 않는다.

## 진입 규칙

V1과 동일하게 매월 마지막 exact KRX 거래일 observation에서만 진입을 판단한다. 아래 조건을
모두 만족해야 한다.

1. Pattern B 상태가 `DEPRESSED`다.
2. 현재 Pattern A Stage가 `PROGRESSED`다.
3. 직전 Pattern A Stage가 `EARLY_TREND` 또는 `TRANSITION`이다.

신호일 다음 첫 exact KRX 거래일의 첫 유효 OPEN에 진입한다. 해당 세션이 없거나 유효 시가를
확인할 수 없으면 다른 날짜나 가격으로 대체하지 않는다.

## 청산 규칙

보유 중 매 완료 exact KRX 거래일마다 Pattern B 상태를 확인한다. `NORMAL`이면 그 날짜에
청산 신호를 만들고, 다음 exact KRX 거래일의 첫 유효 OPEN에 전량 청산한다.
`DEEP_DEPRESSED`, `DEPRESSED`, `OVERHEATED`, `EXTREME_OVERHEATED`는 청산 신호가 아니다.

당일 장이 끝나기 전에 신호를 반복 생성하지 않는다. 진행 중인 세션이나 이후 날짜의 상태·시가는
사용하지 않는다. 다음 exact 세션의 유효 OPEN이 아직 없으면 청산 이벤트를 pending으로 남긴다.

V1과 V2의 유일한 전략 규칙 차이는 보유 중 `NORMAL` 청산 observation cadence다. V1은 월말
관측만 청산 신호로 사용하고, V2는 매 완료 exact KRX 거래일의 `NORMAL`을 사용한다.

## V1 포지션과 거래 이력

승격 시점의 V1 OPEN 포지션은 진입일, 진입 실행일, 진입 시가, 회차와 현재 상태를 보존한다.
승격 전에 생성된 거래 행의 원래 `strategy_id`는 `PATTERN_B_SELECT_CORE_V01`로 유지한다.
승격 이후 새 진입·청산 신호는 `PATTERN_B_SELECT_CORE_V02`로 기록한다. 기존 V1 OPEN 포지션이
V2 `NORMAL` 신호로 청산되면 진입 전략 ID는 V1, 청산 전략 ID는 V2로 구분한다.

V1 production status의 current trade 형식은 보유 수량을 기록하지 않는다. 따라서 승계는 저장된
진입 식별·날짜·시가·회차를 그대로 사용하며, 없는 수량을 추정하거나 생성하지 않는다.

## 운영 status

현재 상태 파일은 다음 경로에 기준일별로 생성한다.

```text
artifacts/strategies/b_select_core_v2/production/{YYYYMMDD}/status.json
```

각 status는 완결된 exact KRX 거래일, 당일 공개 COMMON 리포트, Repository V2 시계열을 사용한다.
ENTRY는 월말에만 생성하며 EXIT는 일별 `NORMAL` 관측에서 생성한다. 모든 체결은 신호 다음
exact KRX session의 유효 OPEN만 인정한다. status 생성은 백테스트·성과 재계산·주문 실행을 하지 않는다.

## 공식 채택 근거

공식 승격은 완료된 `B_SELECT_7_IDENTITY_PERMANENT_EXCLUSION_PASS`와
`B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS` 결과를 근거로 한다. 영구 제외와 5-window
검증의 신호·체결 기록은 보존한다. 이후 valuation carry raw-partition cache의 조회 순서 문제를
확인해 봉인된 event/trade ledger를 그대로 둔 채 MDD와 coverage만 다시 계산했다. 이 valuation-only
정정에서 다섯 구간 CONTROL/TEST coverage는 모두 100%가 됐고, trade count, 승률, 총수익률, CAGR,
event/trade ledger hash는 바뀌지 않았다. A~E gate는 모두 PASS로 유지되어 공식 상태는
`OFFICIAL_STRATEGY_ADOPTED`다. 이전 연구 보고서의 MDD/coverage 숫자는 아래 정정 artifact에 의해
valuation 항목만 superseded됐다.

| Window | CONTROL MDD | TEST MDD | CONTROL − TEST | CONTROL/TEST coverage | D/E gate |
|---|---:|---:|---:|---:|---|
| P1 | -18.11% | -14.27% | -3.85pp | 100% / 100% | PASS / PASS |
| P2-1 | -20.62% | -17.59% | -3.03pp | 100% / 100% | PASS / PASS |
| P2-2 | -24.36% | -19.26% | -5.10pp | 100% / 100% | PASS / PASS |
| P3-1 | -18.52% | -17.58% | -0.94pp | 100% / 100% | PASS / PASS |
| P3-2 | -24.96% | -20.88% | -4.08pp | 100% / 100% | PASS / PASS |

- [영구 제외와 Daily NORMAL Exit 5-window 최종 보고서](../../../../artifacts/strategies/b_select_core_v1/research/daily_normal_exit_permanent_exclusion_v01/report.md)
- [Valuation cache 정정 및 frozen-ledger MDD 재산출](../../../../artifacts/strategies/b_select_core_v1/research/daily_normal_exit_mdd_valuation_v02/report.md)
- [B Select Core V1 역사적 공식 문서](PATTERN_B_SELECT_CORE_V01.md)
- [공식 전략 등록](../../../../docs/strategies/README.md)
