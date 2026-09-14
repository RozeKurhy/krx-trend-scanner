# Pattern A FAST 전략 안내

`Pattern A FAST Core`는 Pattern A FAST 패턴을 이용해 진입·보유·청산을 결정하는
전략이야. 이 문서는 전략 폴더의 입구로, 세 버전의 역할과 현재 상태만 안내해.
상세 규칙은 각 버전의 README에서 확인하면 돼.

## 현재 기준

> V2는 현재 기본 전략이고, V3는 아직 공식 전략이 아닌 검증 대기 후보야.

- **현재 기본 전략**: V2 — `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- **V2 운영 상태**: 의사결정 지원 운영 — `PRODUCTION_DECISION_SUPPORT`
- **V1 역할**: 역사적 기준 전략
- **V3 역할**: 규칙 동결 완료 후보 전략 — `FROZEN_CANDIDATE_AWAITING_MATCHED_AB`
- **V3 다음 단계**: 동일한 진입 코호트에서 V2와 V3를 비교하는 검증

V3는 아직 공식 전략이나 기본 전략이 아니며, V2를 대체하지 않아.

## 버전 한눈에 보기

| 버전 | 역할 | 상태 | 문서 |
|---|---|---|---|
| V1 | 역사적 기준 전략 | 동결된 기준선 | [V1 README](./version_01/README.md) |
| V2 | 현재 기본 전략 | 의사결정 지원 운영 | [V2 README](./version_02/README.md) |
| V3 | 후보 전략 | 동일 조건 비교 검증 대기 | [V3 README](./version_03/README.md) |

## 버전별 안내

- [A FAST Core V1](./version_01/README.md): 최초 1회 진입 기준의 역사적 전략
- [A FAST Core V2](./version_02/README.md): V1의 진입·보유·청산 규칙을 유지하면서 독립 재진입을 허용한 현재 기본 전략
- [A FAST Core V3](./version_03/README.md): V2와 같은 진입 계약을 사용하고 후보 청산 규칙을 평가하는 전략

## 공통 절차

후보 전략의 검증, 공식 전략 채택과 기본 전략 승격은 프로젝트 공통 [전략
생애주기와 채택 절차](../../../strategies/strategy_lifecycle.md)를 따른다.
