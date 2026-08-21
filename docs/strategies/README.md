README.md

# Strategies

- **Pattern** = 시장/가격 구조를 탐지하는 독립 신호 모델
- **Strategy** = 하나 이상의 Pattern/Filter/Execution rule을 이용하여 entry/hold/exit/reentry 정책을 정의하는 매매 정책

Pattern과 Strategy는 개념적으로 분리한다.

현재 A FAST Core V2는 Pattern A FAST와 강하게 결합된 frozen production strategy이므로 당분간 [`docs/patterns/pattern_a_fast/strategy/`](../patterns/pattern_a_fast/strategy/)에 유지한다.

향후 Julia Strategy처럼 여러 Pattern을 조합하거나 Pattern과 독립적인 전략은 `docs/strategies/<strategy_name>/`에 배치한다. (이 문서 작성 시점 기준 Julia 문서는 아직 존재하지 않는다.)
