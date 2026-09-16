# Pattern A FAST

Pattern A FAST는 Pattern A보다 상승 전환을 빠르게 탐지하기 위한 별도 패턴이다.
이 폴더는 패턴의 의미와 생애주기, 관련 전략, 연구, 검증 계획과 결과를 역할별로
정리한 안내서다.

패턴은 “종목의 어떤 상태가 보이는가”를 판단하고, 전략은 “그 판단을 바탕으로
무엇을 할 것인가”를 결정한다. 따라서 Pattern A FAST와 A FAST Core는 서로 관련되어
있지만 같은 개념은 아니다. Pattern A와의 관계는 [Pattern A 안내](../pattern_a/README.md)에서
확인할 수 있다.

## 현재 기준

| 항목 | 현재 내용 |
|---|---|
| 패턴 | Pattern A FAST |
| 역할 | Pattern A보다 빠른 전환 신호 탐지 |
| 현재 기본 전략 | [A FAST Core V2](strategy/version_02/README.md) |
| 전략 ID | `PATTERN_A_FAST_FINAL_STRATEGY_V02` |
| 사용 목적 | 투자 의사결정 지원 |
| 현재 운영 상태 | 의사결정 지원 운영 (`PRODUCTION_DECISION_SUPPORT`) |
| 자동매매 | 승인하지 않음 (`NOT_APPROVED`) |
| V1 | 공식 과거 비교 기준선 |
| V2 | 현재 공식 기본 전략 |
| V3 | 종료된 후보 전략 기록 |
| V4 | 종료된 후보 전략 기록 |

현실적 비교 검증과 V2·Julia 공식 비교는 완료되었으며, 일반 종목의 현재
기본 전략은 V2를 유지한다. Julia는 일반 종목 공식 전략으로 채택하지 않는다.

## 문서 구조

| 역할 | 위치 | 설명 |
|---|---|---|
| 패턴 정의·생애주기 | [specification/](specification/) | Pattern A FAST가 무엇을 의미하고 어떻게 상태가 바뀌는지 |
| 전략 | [strategy/](strategy/) | V1~V4의 규칙과 현재·과거 역할 안내 |
| 연구 | [research/](research/) | 기능, 시간 프레임, Pattern A 비교 등 연구 기록 |
| 검증 계획 | [validation_plan/](validation_plan/) | 검증 전에 작성한 계획과 종료된 비교 계획 기록 |
| 검증 결과 | [validation/](validation/) | 실제 수행한 사람 검토와 평가 결과 |
| 과거 문서 | [archive/](archive/) | 현재 기준으로 재사용하지 않는 역사적 계획·아키텍처 |

## 기준 문서

- [Pattern A FAST 정의](specification/README.md)
- [Pattern A FAST 생애주기 계약](specification/weekly_lifecycle.md)
- [전략 안내](strategy/README.md)
- [A FAST Core V1 — 역사적 기준선](strategy/version_01/README.md)
- [A FAST Core V2 — 현재 기본 전략](strategy/version_02/README.md)
- [A FAST Core V3 — 종료된 후보 기록](strategy/version_03/README.md)
- [A FAST Core V4 — 종료된 후보 기록](strategy/version_04/README.md)

## 공통 전략 절차

후보 전략의 검증, 공식 전략 채택, 기본 전략 승격은 프로젝트 공통 [전략
생애주기와 채택 절차](../../strategies/strategy_lifecycle.md)를 따른다.

Pattern A FAST와 강하게 결합된 전략은 이 폴더의 `strategy/`에서 관리하고,
특정 패턴과 독립적인 전략은 [docs/strategies/](../../strategies/)에 둔다.
