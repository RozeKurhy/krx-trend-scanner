# Pattern A FAST 전략

================================================================================
1. Overview & Strategy Identity
================================================================================
`Pattern A FAST Core`는 Pattern A FAST 패턴을 이용해 진입·보유·청산을 결정하는
전략이야. 이 문서는 전략 버전과 현재 상태를 안내하는 GitHub 폴더 입구야.

- **기본 통용 명칭**: `A FAST Core`, `패스트 코어`
- **현재 기본 전략**: **V2** — `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- **연구 상태**: 전략 연구 완료 (`STRATEGY_FINALIZATION_CLOSED`)
- **운영 상태**: 의사결정 지원 운영 (`PRODUCTION_DECISION_SUPPORT`)

V1은 역사적 기준 전략이고, V2는 현재 기본 전략이야. V3는 규칙 동결이 끝난
후보 전략이지만 아직 공식 전략이나 기본 전략이 아니며, V2와 동일 조건 비교
검증을 기다리고 있어.

================================================================================
2. Strategy Version Matrix
================================================================================

| 버전 | Formal Strategy ID | 한국어 공식 명칭 | 대표 Alias | 전략 성격 및 역할 | 동일 종목 재진입 (Re Entry) | 표본 거래 수 | 문서 및 계약 경로 |
|:---:|:---|:---|:---|:---|:---:|:---:|:---|
| **V1** | `PATTERN_A_FAST_FINAL_STRATEGY_V01` | 패턴A FAST 최종 전략 V01 | `A FAST Core V1`, `패스트 코어 V1` | 역사적 동결 기준선 (`HISTORICAL_FROZEN_BASELINE`) | `FIRST_QUALIFYING_ENTRY_PER_TICKER` (최초 1회 한정) | 551건 | [`V1 README`](./version_01/README.md)<br>[`V1 artifact`](../../../../artifacts/patterns/pattern_a_fast/production/strategy_v01/pattern_a_fast_final_strategy_v01.json) |
| **V2** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` | 패턴A FAST 최종 전략 V02 | `A FAST Core V2`, `패스트 코어 V2` | 현재 기본 전략 (`FINAL_STRATEGY_FROZEN`) | **`MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER`** (독립 재진입 허용) | 783건 | [`V2 README`](./version_02/README.md)<br>[`V2 artifact`](../../../../artifacts/patterns/pattern_a_fast/production/strategy_v02/pattern_a_fast_final_strategy_v02.json) |
| **V3** | `PATTERN_A_FAST_FINAL_STRATEGY_V03` | 패턴A FAST 최종 전략 V03 후보 | `A FAST Core V3` | 비교 검증 대기 후보 (`FROZEN_CANDIDATE_AWAITING_MATCHED_AB`) | V2와 동일한 진입 조건, 후보 청산 규칙 | 미실행 | [`V3 README`](./version_03/README.md) |

================================================================================
3. V1 vs V2 Core Delta
================================================================================
V2는 V1의 모든 진입 조건, 손실가드(-15%), 추세 보유, 청산 메커니즘(Exit 3, Exit 4, Coverage)을 100% 동일하게 계승하며, **동일 종목 재진입 규칙(`Re Entry`) 단 하나만 변경**한 버전입니다.

- **V1 (Historical Baseline)**: 종목당 최초 적격 신호 1회만 진입 (`FIRST_QUALIFYING_ENTRY_PER_TICKER`).
- **V2 (Current Strategy)**: 이전 포지션 청산 완료 후 신규 진입 조건이 다시 충족되면 횟수/쿨다운 제한 없이 독립 재진입 허용 (`MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER`).

================================================================================
4. Deferred Research (보류된 후속 연구)
================================================================================
- **연구명**: `PROGRESSED_DOWNSIDE_PROTECTION_RESEARCH` (Phase 1 진단 완료)
- **상태**: **`DEFERRED_RESEARCH` (전략 미반영, 향후 연구로 보류)**
- **진단 결론**: PROGRESSED 도달 후 대형 손실과 대형 승자 간에 가격 고점 대비 낙폭(HWM Drawdown)의 기술적 분리가 관측되었으나, 대형 승자의 18.29% 역시 -30% 이하의 조정을 견디고 상승한 우측 꼬리 중첩이 확인됨.
- **처리 방침**: 현재 V2 전략에는 추가 Trailing Stop이나 규칙을 일체 반영하지 않으며, 차후 독립 연구(`Phase 2`)로 보류함.
- **진단 증적 아티팩트**: [`artifacts/patterns/pattern_a_fast/research/progressed_downside_v01/`](../../../../artifacts/patterns/pattern_a_fast/research/progressed_downside_v01/)

================================================================================
5. Historical Preregistration Notice
================================================================================
- 과거 작성된 [`Fresh OOS V3 사전등록`](../archive/validation_plan/fresh_out_of_sample_v03.md) 문서는 **`SUPERSEDED_HISTORICAL_PREREGISTRATION`** 상태이며, 현재의 `A FAST Core V02` 전략 계약과 일치하지 않으므로 V02의 Forward Validation에 재사용할 수 없어.

## 공통 절차

후보 전략의 검증, 공식 전략 채택과 기본 전략 승격은 프로젝트 공통 [전략
생애주기와 채택 절차](../../../strategies/strategy_lifecycle.md)를 따른다.
