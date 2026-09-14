# Pattern A FAST

Pattern A FAST는 Pattern A보다 상승 전환을 빠르게 탐지하기 위한 별도 패턴이야.
이 폴더는 패턴의 의미와 생애주기, 관련 전략, 연구, 검증 계획과 결과를 역할별로
정리해 둔 안내서야.

패턴은 “종목의 어떤 상태가 보이는가”를 판단하고, 전략은 “그 판단을 바탕으로
무엇을 할 것인가”를 결정해. 따라서 Pattern A FAST와 A FAST Core는 서로 관련되어
있지만 같은 개념은 아니야. Pattern A와의 관계는 [Pattern A 안내](../pattern_a/README.md)에서
확인할 수 있어.

## 현재 기준

| 항목 | 현재 내용 |
|---|---|
| 패턴 | Pattern A FAST |
| 목적 | Pattern A보다 빠른 상승 전환 탐지 |
| 현재 기본 전략 | [A FAST Core V2](strategy/version_02/README.md) |
| 기본 전략 ID | `PATTERN_A_FAST_FINAL_STRATEGY_V02` |
| 현재 상태 | 의사결정 지원 운영 (`PRODUCTION_DECISION_SUPPORT`) |
| 자동매매 | 승인하지 않음 (`NOT_APPROVED`) |
| V3 후보 | [A FAST Core V3 후보](strategy/version_03/README.md), V2와 동일 조건 비교 검증 대기 |

A FAST Core V2가 현재 기본 전략이야. A FAST Core V1은 역사적 동결 기준선이고,
A FAST Core V3는 규칙이 동결된 후보일 뿐 공식 전략이나 기본 전략이 아니야.

## 문서 구조

| 역할 | 위치 | 설명 |
|---|---|---|
| 패턴 정의·생애주기 | [specification/](specification/) | Pattern A FAST가 무엇을 의미하고 어떻게 상태가 바뀌는지 |
| 전략 | [strategy/](strategy/) | V1·V2·V3 후보를 버전별로 구분한 규칙과 이력 |
| 연구 | [research/](research/) | 기능, 시간 프레임, Pattern A 비교 등 연구 기록 |
| 검증 계획 | [validation_plan/](validation_plan/) | 검증 전에 등록한 질문·범위·판정 기준 |
| 검증 결과 | [validation/](validation/) | 실제 수행한 사람 검토와 평가 결과 |
| 과거 문서 | [archive/](archive/) | 현재 기준으로 재사용하지 않는 역사적 계획·아키텍처 |

## 기준 문서

- [Pattern A FAST 정의](specification/definition_v01.md)
- [Pattern A FAST 생애주기 계약](specification/lifecycle_contract.md)
- [전략 안내](strategy/README.md)
- [A FAST Core V1 — 역사적 기준선](strategy/version_01/README.md)
- [A FAST Core V2 — 현재 기본 전략](strategy/version_02/README.md)
- [A FAST Core V3 — 검증 대기 후보](strategy/version_03/README.md)

## 공통 전략 절차

후보 전략의 검증, 공식 전략 채택, 기본 전략 승격은 프로젝트 공통 [전략
생애주기와 채택 절차](../../strategies/strategy_lifecycle.md)를 따른다.

Pattern A FAST와 강하게 결합된 전략은 이 폴더의 `strategy/`에서 관리하고,
특정 패턴과 독립적인 전략은 [docs/strategies/](../../strategies/)에 둔다.
