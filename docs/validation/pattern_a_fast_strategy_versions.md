# Pattern A FAST Core Strategy Version Index & Provenance

================================================================================
1. Overview & Strategy Identity
================================================================================
본 문서는 `Pattern A FAST Core` (패스트 코어) 전략의 버전 체계, 공식 식별자 및 연구 상태를 안내하는 네비게이션 인덱스입니다.

- **기본 통용 명칭 (`Default Alias`)**: `A FAST Core`, `패스트 코어`
- **기본 참조 전략 (`Current Default Strategy`)**: **`PATTERN_A_FAST_FINAL_STRATEGY_V02` (V2)**
- **연구 종료 상태 (`Research Status`)**: **`STRATEGY_FINALIZATION_CLOSED` (패스트 코어 전략 연구 완료)**
- **운영 상태 (`Production Status`)**: **`PRODUCTION_HOLD` (운영 불변, 연구 전용)**

================================================================================
2. Strategy Version Matrix
================================================================================

| 버전 | Formal Strategy ID | 한국어 공식 명칭 | 대표 Alias | 전략 성격 및 역할 | 동일 종목 재진입 (Re Entry) | 표본 거래 수 | 문서 및 계약 경로 |
|:---:|:---|:---|:---|:---|:---:|:---:|:---|
| **V1** | `PATTERN_A_FAST_FINAL_STRATEGY_V01` | 패턴A FAST 최종 전략 V01 | `A FAST Core V1`, `패스트 코어 V1` | **`HISTORICAL_FROZEN_BASELINE`** (역사적 동결 기준선) | `FIRST_QUALIFYING_ENTRY_PER_TICKER` (최초 1회 한정) | 551건 | [`pattern_a_fast_final_strategy_v01.md`](./pattern_a_fast_final_strategy_v01.md)<br>[`pattern_a_fast_final_strategy_v01.json`](../../artifacts/pattern_a_fast/final_strategy_v01/pattern_a_fast_final_strategy_v01.json) |
| **V2** | `PATTERN_A_FAST_FINAL_STRATEGY_V02` | 패턴A FAST 최종 전략 V02 | `A FAST Core V2`, `패스트 코어 V2` | **`FINAL_STRATEGY_FROZEN`** (현재 공식 사용 전략) | **`MULTIPLE_INDEPENDENT_ENTRIES_PER_TICKER`** (독립 재진입 허용) | 783건 | [`pattern_a_fast_final_strategy_v02.md`](./pattern_a_fast_final_strategy_v02.md)<br>[`pattern_a_fast_final_strategy_v02.json`](../../artifacts/pattern_a_fast/final_strategy_v02/pattern_a_fast_final_strategy_v02.json) |

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
- **진단 증적 아티팩트**: [`artifacts/pattern_a_fast/progressed_downside_v01/`](../../artifacts/pattern_a_fast/progressed_downside_v01/)

================================================================================
5. Historical Preregistration Notice
================================================================================
- 과거 작성된 [`docs/validation/pattern_a_fast_fresh_oos_v03_prereg.md`](./pattern_a_fast_fresh_oos_v03_prereg.md) 문서는 **`SUPERSEDED_HISTORICAL_PREREGISTRATION`** 상태이며, 현재의 `A FAST Core V02` 전략 계약과 일치하지 않으므로 V02의 Forward Validation에 재사용할 수 없습니다.
