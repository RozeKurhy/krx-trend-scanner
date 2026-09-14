README.md

# Patterns

Patterns는 종목이나 시장에서 “어떤 상태가 나타났는지”를 판단하는 기준을
관리하는 영역이야. 패턴은 전략과 달라. 패턴이 **무엇이 보이는지 판단**한다면,
전략은 그 판단을 바탕으로 **무엇을 할지 결정**해.

각 패턴 폴더에는 필요한 범위에서 패턴 정의, 전략, 연구, 검증 계획, 검증 결과와
과거 기록을 함께 둔다. 특정 패턴과 강하게 결합된 전략은 해당 패턴 폴더에서
관리하고, 여러 패턴에 독립적인 전략은 [docs/strategies/](../strategies/)에서
관리한다.

## 현재 Pattern

| Pattern | 현재 상태 | 안내 |
|---|---|---|
| Pattern A | `FROZEN` / `KEEP_CURRENT_PRODUCTION` | [Pattern A 안내](pattern_a/README.md) |
| Pattern A FAST | `FINAL_STRATEGY_FROZEN` — A FAST Core V2가 현재 기본 전략 | [Pattern A FAST 안내](pattern_a_fast/README.md) |

Pattern A FAST의 V3는 규칙이 동결된 후보 전략이지만 아직 공식 전략이나 기본
전략이 아니며, V2와 동일 조건 비교 검증을 기다리고 있어.
