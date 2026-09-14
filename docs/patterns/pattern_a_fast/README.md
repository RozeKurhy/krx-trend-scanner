README.md

# Pattern A FAST

Pattern A FAST는 Pattern A보다 상승 전환을 더 빠르게 탐지하기 위한 별도
패턴이다. Pattern A FAST 자체는 종목의 상태를 판단하는 패턴이고,
A FAST Core는 그 판단 결과를 이용해 실제 진입·보유·청산을 결정하는 전략이다.
따라서 패턴과 전략은 같은 것이 아니다.

Pattern A와 관련되어 있지만, 별도의 패턴 정의와 연구·검증 기록을 가진다.
Pattern A와의 관계는 [Pattern A 안내](../pattern_a/README.md)에서 함께 확인할
수 있다.

## 현재 상태

| 항목 | 현재 내용 |
|---|---|
| 패턴 이름 | Pattern A FAST |
| 목적 | Pattern A보다 빠른 상승 전환 탐지 |
| 현재 기본 전략 | A FAST Core V2 |
| 기본 전략 ID | `PATTERN_A_FAST_FINAL_STRATEGY_V02` |
| 현재 운영 상태 | 의사결정 지원 운영 (`PRODUCTION_DECISION_SUPPORT`) |
| 자동매매 승인 여부 | 승인하지 않음 (`NOT_APPROVED`) |
| Pattern A와의 관계 | 관련은 있으나 독립적인 패턴 정의와 연구·검증 기록을 가진 별도 패턴 |

A FAST Core V2는 Pattern A FAST와 강하게 결합된 현재 기본 전략이다.
V2의 상세 규칙은 아래 기본 전략 문서에서 확인한다.

## 현재 후보 전략

- 이름: A FAST Core V3
- 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V03`
- 상태: 규칙 동결 완료, V2와 동일 조건 비교 검증 대기 (`FROZEN_CANDIDATE_AWAITING_MATCHED_AB`)
- 현재 위치: 아직 공식 전략이 아니며 기본 전략도 아니다.
- 다음 단계: V2와 동일한 진입 지점을 사용한 비교 검증

V3의 상세 규칙은 [후보 전략 V3](strategy/final_v03_candidate.md)에서 확인한다.

## 기준 문서

이 README는 산식이나 전략 규칙을 새로 작성하지 않는다. 세부 내용은 아래
기준 문서와 결과 기록에서 확인한다.

| 항목 | 위치 |
|---|---|
| 패턴 정의 | [spec/definition_v01.md](spec/definition_v01.md) |
| 패턴 생애주기 | [spec/lifecycle_contract.md](spec/lifecycle_contract.md) |
| 현재 기본 전략 | [strategy/final_v02.md](strategy/final_v02.md) |
| 이전 공식 전략 | [strategy/final_v01.md](strategy/final_v01.md) |
| 후보 전략 V3 | [strategy/final_v03_candidate.md](strategy/final_v03_candidate.md) |
| 전략 버전 기록 | [strategy/versions.md](strategy/versions.md) |
| 연구 | [research/](research/) |
| 검증 | [validation/](validation/) |
| 검증 계획 | [prereg/](prereg/) |

## 공통 전략 절차

후보 전략의 검증, 공식 전략 채택, 기본 전략 승격은 프로젝트 공통 [전략
생애주기와 채택 절차](../../strategies/strategy_lifecycle.md)를 따른다.

A FAST Core V2와 V3는 Pattern A FAST와 강하게 결합되어 있으므로 `strategy/`
아래에서 관리한다. 특정 패턴과 독립적인 파생 전략은 `docs/strategies/`에
배치한다.
