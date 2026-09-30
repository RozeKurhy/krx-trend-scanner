# 전략 문서

이 영역은 패턴과 매매 전략의 규칙, 연구 기록, 공통 검증 절차를 구분하여
관리한다.

- **패턴**은 시장·가격 구조를 탐지하는 독립 신호 모델이다.
- **전략**은 하나 이상의 패턴과 필터, 체결 규칙을 이용해 진입·보유·청산 정책을 정한다.

패턴과 전략은 개념적으로 분리한다. 패턴과 강하게 결합된 전략은 해당 패턴 폴더에서
관리하고, 특정 패턴과 독립적인 전략은 이 영역에서 관리한다.

## 현재 공식 전략

| 공식 표시명 | 전략 ID | 역할 | 규칙 문서 |
|---|---|---|---|
| A FAST Core V2 | `PATTERN_A_FAST_FINAL_STRATEGY_V02` | 기본 전략·CONTROL, 투자 의사결정 지원 | [A FAST Core V2](../patterns/pattern_a_fast/strategy/version_02/README.md) |
| B Select Core V1 | `PATTERN_B_SELECT_CORE_V01` | Pattern B와 Pattern A Stage를 결합한 별도 공식 전략. 기본 전략은 아님 | [B Select Core V1](../patterns/pattern_b/strategy/PATTERN_B_SELECT_CORE_V01.md) |
| Julia V1 | `JULIA_ETF_STRATEGY_V01` | ETF 36 전용 공식 전략; 일반 종목에는 적용하지 않음 | [Julia V1](julia/JULIA_ETF_STRATEGY_V01.md) |

현재 공식 전략은 위 세 개다. 일반 종목 공식 전략은 A FAST Core V2와 B Select Core V1이고, ETF 전용 공식 전략은 Julia V1이다.
A FAST Core V2가 기본 전략·CONTROL로 유지된다. B Select Core V1과 Julia V1은 기본 전략이 아니며, 어느 전략도 이 등록만으로 자동 주문 승인을 얻지 않는다.

## 연구 및 적용 범위

Julia V1은 ETF 36 전용 공식 전략이며, 일반 종목 공식 전략 상태는
NOT ADOPTED / RETIRED AS GENERAL-STOCK OFFICIAL STRATEGY로 유지한다.
JULIA_STRATEGY_V00은 ETF 공식 채택 심사에 사용된 과거 검증 후보 ID로 보존한다.
현재 기본 전략은 A FAST Core V2다. 심사 결과와 과거 연구는 [Julia 문서](julia/)에서 확인한다.

공식 전략의 검증·채택 절차는 [전략 생애주기와 채택 절차](strategy_lifecycle.md)를 따른다.
전략별 규칙과 연구 기록, 프로젝트 공통 생애주기 절차는 서로 복사하지 않고 각 권위 문서에서
관리한다. 사람이 읽는 설명은 한글을 기본으로 하며 전략 ID, 파일명, 코드 심볼과 고유 약어는
필요한 범위에서 영문으로 유지한다.
