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

현재 공식 전략은 위 두 개다. 기본 전략과 CONTROL은 A FAST Core V2 하나로 유지한다.
B Select Core V1의 공식 채택은 기본 전략 변경이나 자동 주문 승인을 뜻하지 않는다.

## 다른 전략 연구

Julia Strategy는 A FAST Core V2와 다른 조건을 검토한 연구 전략이다. 일반 종목 공식 전략으로
채택하지 않았고 현재 기본 전략도 아니다. Julia의 ETF 전용 검토 상태는 `DEFERRED`이며,
현재 판정과 비교 산출물은 [Julia 문서](julia/) 및 [V3와 Julia 통합 비교 기록](../../artifacts/research/etf_v3_julia_integrated_comparison_v01/final_comparison.md)에
보존한다.

공식 전략의 검증·채택 절차는 [전략 생애주기와 채택 절차](strategy_lifecycle.md)를 따른다.
전략별 규칙과 연구 기록, 프로젝트 공통 생애주기 절차는 서로 복사하지 않고 각 권위 문서에서
관리한다. 사람이 읽는 설명은 한글을 기본으로 하며 전략 ID, 파일명, 코드 심볼과 고유 약어는
필요한 범위에서 영문으로 유지한다.
