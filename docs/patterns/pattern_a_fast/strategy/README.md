# Pattern A FAST 전략 안내

`Pattern A FAST Core`는 Pattern A FAST 패턴을 이용해 진입·보유·청산을 결정하는
전략이다. 이 문서는 전략 폴더의 입구로, 네 버전의 역할과 현재 상태만 안내한다.
상세 규칙은 각 버전의 README에서 확인할 수 있다.

## 현재 기준

- **현재 기본 전략**: V2 — `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- **V2 운영 상태**: 의사결정 지원 운영 — `PRODUCTION_DECISION_SUPPORT`
- **V1 역할**: 공식 과거 비교 기준선
- **V3 역할**: 종료된 후보 전략 기록
- **V4 역할**: 종료된 후보 전략 기록

현재 추가 전략 연구는 진행하지 않는다. V3와 V4의 상세 규칙과 당시 판단은
각 버전 문서에 역사 기록으로 보존한다.

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

## 공통 절차

후보 전략의 검증, 공식 전략 채택과 기본 전략 승격은 프로젝트 공통 [전략
생애주기와 채택 절차](../../../strategies/strategy_lifecycle.md)를 따른다.
