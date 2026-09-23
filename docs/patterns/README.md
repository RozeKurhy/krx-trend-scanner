# 패턴 안내

`patterns/`는 종목이나 시장에서 어떤 가격 구조와 상태가 나타났는지 판단하는
패턴을 관리하는 영역이다. 패턴은 **무엇이 보이는지 판단**하고, 전략은 그
판단을 바탕으로 **무엇을 할지 결정**한다.

패턴과 강하게 결합된 전략은 해당 패턴 폴더에서 관리한다. 여러 패턴에
독립적인 전략은 [독립 전략 영역](../strategies/)에서 관리한다. 세부 산식,
계약, 검증 결과는 각 하위 권위 문서에 두고 이 문서는 현재 상태와 위치만
안내한다.

## 현재 패턴

| 패턴 | 역할 | 현재 상태 | 안내 |
|---|---|---|---|
| Pattern A | 장기 가격 구조와 상승 초기 후보 탐지 | 현재 공식 패턴 | [Pattern A 안내](pattern_a/README.md) |
| Pattern A FAST | Pattern A보다 빠른 전환 신호 탐지 | 보조 패턴 | [Pattern A FAST 안내](pattern_a_fast/README.md) |
| Pattern B | 자기 장기 가격 사이클 내 침체·과열 상태 탐지 | 초기 연구 후보 (미구현) | [Pattern B 안내](pattern_b/README.md) |

일반 종목의 현재 기본 전략은 A FAST Core V2이며, 공식 전략 ID는
`PATTERN_A_FAST_FINAL_STRATEGY_V02`다. V1은 공식 과거 비교 기준선이고,
V3와 V4는 종료된 후보 전략·연구 기록으로 보존한다.

전략 버전의 역할과 현재 상태는 [A FAST 전략 안내](pattern_a_fast/strategy/README.md)에서
확인한다.
