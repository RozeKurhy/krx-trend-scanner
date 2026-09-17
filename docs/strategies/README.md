# 전략 문서

이 영역은 패턴과 매매 전략의 규칙, 연구 기록, 공통 검증 절차를 구분하여
관리하는 문서 공간이다.

- **패턴**: 시장·가격 구조를 탐지하는 독립 신호 모델이다.
- **전략**: 하나 이상의 패턴, 필터, 체결 규칙을 이용해 진입·보유·청산·재진입
  정책을 정의하는 매매 정책이다.

패턴과 전략은 개념적으로 분리한다. 현재 기본 전략은 `A FAST Core V2`
(`PATTERN_A_FAST_FINAL_STRATEGY_V02`)이며, 패턴과 강하게 결합되어 있어
관련 문서는 [A FAST 전략 문서](../patterns/pattern_a_fast/strategy/)에 둔다.

`Julia Strategy`는 V2의 변형을 연구한 전략이다. 최종 V2와 Julia의 현실적
포트폴리오 비교 결과 Julia는 일반 종목 공식 전략으로 채택하지 않으며, 현재
일반 종목 기본 전략은 A FAST Core V2다. Julia의 ETF 전용 가능성은 별도
검토 대상으로 보존하고 현재 상태는 보류(`DEFERRED`)로 둔다.

공식 전략의 검증·채택 절차는 [전략 생애주기와 채택 절차](strategy_lifecycle.md)를
따른다. Julia 관련 현재 상태와 과거 기록은 [Julia 문서](julia/)에서 관리하며,
최신 ETF 비교 결과는 공식 전략이 아닌 [V3와 Julia 통합 비교 기록](../../artifacts/research/etf_v3_julia_integrated_comparison_v01/final_comparison.md)에서 확인한다.

이 문서 영역의 사람이 읽는 설명은 한글을 기본으로 작성한다. 전략 ID, 파일명,
코드 심볼, KRX·OpenDART, MDD·MAE와 같은 고유 식별자나 널리 쓰이는 약어만
필요한 범위에서 영문을 유지한다. 전략별 규칙·연구 기록과 프로젝트 공통
생애주기 절차 문서는 서로 복사하지 않고 역할을 나누어 보존한다.
