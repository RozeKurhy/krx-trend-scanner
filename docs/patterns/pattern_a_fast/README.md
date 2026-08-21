README.md

# Pattern A FAST

- **Pattern**: Pattern A FAST
- **Purpose**: Pattern A보다 빠른 상승 전환 탐지
- **Current Strategy**: A FAST Core V2
- **Formal Strategy ID**: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- **Strategy Status**: `FINAL_STRATEGY_FROZEN`
- **Production Status**: `PRODUCTION_DECISION_SUPPORT`
- **Automated Trading**: `NOT_APPROVED`
- **Fresh OOS**: `NOT_EXECUTED`
- **다른 Pattern과 관계**: Pattern A(`../pattern_a/README.md`)와 관련은 있으나 독립적인 validation history와 authority를 가진 별도 Pattern이다.

## Current Authority

이 README 자체에 전략 산식을 새로 작성하지 않는다. 아래 원본 문서가 authority다.

| 항목 | 위치 |
|---|---|
| Definition | [spec/definition_v01.md](spec/definition_v01.md) |
| Lifecycle | [spec/lifecycle_contract.md](spec/lifecycle_contract.md) |
| Current Strategy | [strategy/final_v02.md](strategy/final_v02.md) |
| Historical Strategy | [strategy/final_v01.md](strategy/final_v01.md) |
| Strategy Versions | [strategy/versions.md](strategy/versions.md) |
| Research | [research/](research/) |
| Validation | [validation/](validation/) |
| Preregistration | [prereg/](prereg/) |

A FAST Core V2는 Pattern A FAST와 강하게 결합된 frozen production strategy이므로 당분간 `strategy/` 아래 유지한다(향후 Julia 같은 독립 파생 전략은 `docs/strategies/`에 배치).
