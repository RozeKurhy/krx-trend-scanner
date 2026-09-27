# Pattern A FAST 전략 안내

`Pattern A FAST Core`는 Pattern A FAST 패턴을 이용해 진입·보유·청산을 결정하는
전략이다. 이 문서는 전략 폴더의 입구로, 네 버전의 역할과 현재 상태만 안내한다.
상세 규칙은 각 버전의 README에서 확인할 수 있다.

## 현재 기준

- **현재 기본 전략**: V2 — `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- **V2 운영 상태**: 의사결정 지원 운영 — `PRODUCTION_DECISION_SUPPORT`
- **V2 개선 연구 상태**: 종료 — `A_FAST_CORE_V2_IMPROVEMENT_RESEARCH_CLOSED`
- **V1 역할**: 공식 과거 비교 기준선
- **V3 역할**: 종료된 후보 전략 기록
- **V4 역할**: 종료된 후보 전략 기록

현재 추가 V2 미세조정 연구는 진행하지 않는다. V2.1 Candidate는 비채택·종료,
Exit4 15pt는 유지·종료, Exit3 Coverage Extension은 비승격·종료했다. V3와 V4의
상세 규칙과 당시 판단은 각 버전 문서에 역사 기록으로 보존한다. [V2 개선 연구
종료 기록](../research/v2_improvement_research_closure_20260927.md)에 최종 근거와
보존 산출물 색인이 있다.

## 버전 한눈에 보기

| 버전 | 역할 | 상태 | 문서 |
|---|---|---|---|
| V1 | 공식 과거 비교 기준선 | 역사 기록 | [V1 README](../archive/strategy/version_01/README.md) |
| V2 | 현재 기본 전략 | 의사결정 지원 운영 | [V2 README](./version_02/README.md) |
| V3 | 종료된 후보 전략 | 역사 기록 | [V3 README](../archive/strategy/version_03/README.md) |
| V4 | 종료된 후보 전략 | 역사 기록 | [V4 README](../archive/strategy/version_04/README.md) |

## 버전별 안내

- [A FAST Core V1](../archive/strategy/version_01/README.md): 최초 1회 진입 기준의 역사적 전략
- [A FAST Core V2](./version_02/README.md): V1의 진입·보유·청산 규칙을 유지하면서 독립 재진입을 허용한 현재 기본 전략
- [A FAST Core V3](../archive/strategy/version_03/README.md): 종료된 후보 전략의 규칙과 판단을 보존하는 기록
- [A FAST Core V4](../archive/strategy/version_04/README.md): 종료된 후보 전략의 규칙과 판단을 보존하는 기록

## 후보 검증 기록

- [A FAST Core V2 + NEG40 / WEAK Protect 5-window synthesis V01](./FAST_CORE_V2_NEG40_WEAK_PROTECT_5_WINDOW_SYNTHESIS_V01.md): P1/P2-1/P2-2/P3-1/P3-2의 당시 비교 기록이다. 후속 realistic portfolio 검증을 포함한 최종 상태는 [V2 개선 연구 종료 기록](../research/v2_improvement_research_closure_20260927.md)을 따른다.
- [A FAST Core V2 개선 연구 종료 기록](../research/v2_improvement_research_closure_20260927.md): V2.1 Candidate, Exit4 threshold, Exit3 Coverage Extension, EARLY_TREND-only의 최종 결정을 정리한다.

## 공통 절차

후보 전략의 검증, 공식 전략 채택과 기본 전략 승격은 프로젝트 공통 [전략
생애주기와 채택 절차](../../../strategies/strategy_lifecycle.md)를 따른다.
