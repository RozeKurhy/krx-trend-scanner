# Pattern B

Pattern B는 종목 자신의 장기 가격 사이클 안에서 가격이 침체 또는 과열 쪽 어디에 가까운지 분류한다. 기업가치 대비 저평가 여부를 판단하거나 바닥·천장을 예측하지 않는다. Pattern B 상태 자체는 매수·보유·매도 신호가 아니다.

## 패턴과 전략의 경계

Pattern A와 Pattern A FAST는 가격 구조와 상승 전환을 다루며, Pattern B는 장기 가격 사이클의 상태를 다룬다. 각 패턴의 정의와 입력은 별도 문서에서 관리한다.

B Select Core V2는 Pattern B 상태와 Pattern A Stage를 전략 규칙에 함께 사용한다. 패턴은 상태를 판단하고, 현재 진입·보유·청산 규칙은 [B Select Core V2 전략 문서](strategy/PATTERN_B_SELECT_CORE_V02.md)에서 확인한다. V1은 당시 월말 EXIT 규칙을 보존하는 역사적 버전이다.

## 문서 지도

| 역할 | 문서 |
|---|---|
| 공식 규격, 권위 경계와 구현 위치 | [Pattern B 공식 규격](spec/production_authority.md) |
| 개념, 상태 의미와 패턴의 경계 | [Pattern B 개념 기준](spec/README.md) |
| 지표 정의, 계산과 point-in-time 처리 | [지표 계약](spec/feature_contract_v01.md) |
| 상태 판정 규칙과 임계값 | [상태 판정 규칙](validation/state_rule_v02.md) |
| 입력 자료, 평가와 가격 신선도 계약 | [운영 계약](spec/production_contract_v02.md) |
| 패턴 채택 판단 근거 | [공식 패턴 채택 판단](validation/adoption_decision_v01.md) |
| 전체 종목 운영 계약 점검 기록 | [운영 감사 기록](validation/full_universe_operational_audit_v02.md) |
| 현재 공식 전략의 규칙과 근거 | [B Select Core V2 전략 문서](strategy/PATTERN_B_SELECT_CORE_V02.md) |
| 역사적 V1 규칙과 기록 | [B Select Core V1 전략 문서](strategy/PATTERN_B_SELECT_CORE_V01.md) |

## 연구 기록

사람 판정 기준, 지표 탐색, 규칙 검토, 차트 팩과 이전 후보의 검증 기록은 [validation 문서](validation/)에 보존한다. 현재 전략 채택 근거는 [B Select Core V2 전략 문서](strategy/PATTERN_B_SELECT_CORE_V02.md)에서, V1의 역사 규칙은 [B Select Core V1 문서](strategy/PATTERN_B_SELECT_CORE_V01.md)에서 확인한다. 연구 기록의 결과는 해당 연구 범위와 시점에 한정된다.

다른 패턴의 목적과 문서 위치는 [패턴 안내](../README.md)에서 확인한다.
