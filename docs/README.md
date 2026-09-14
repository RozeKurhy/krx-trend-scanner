README.md

# KRX Trend Scanner 문서 안내

이 문서는 `docs/` 아래 문서의 위치와 역할을 빠르게 확인하기 위한 안내다.
각 하위 폴더의 README에서 해당 영역의 상세 문서 위치를 확인할 수 있다.

## 패턴과 전략의 차이

**패턴**은 종목이나 시장에서 어떤 가격 구조나 상태가 나타나고 있는지
판단하는 기준이다.

쉽게 말하면, **무엇이 보이는지 판단한다.**

**전략**은 패턴이나 다른 조건을 이용하여 언제 진입하고, 보유하고, 청산할지
정하는 매매 규칙이다.

쉽게 말하면, **판단한 결과를 바탕으로 무엇을 할지 결정한다.**

패턴은 관찰과 판단의 기준이고 전략은 행동의 규칙이므로, 두 개념은 서로
다르다.

## 최상위 영역

| 영역 | 이곳에서 다루는 내용 |
|---|---|
| [architecture/](architecture/README.md) | 특정 패턴에 속하지 않는 프로젝트 공통 구조, 데이터 처리 방식, 공용 기술 문서 |
| [patterns/](patterns/README.md) | 종목과 시장의 상태를 판단하는 패턴의 정의, 연구, 검증 기록과 결합된 전략 문서 |
| [fundamentals/](fundamentals/README.md) | 기업 실적과 재무 정보를 분석하기 위한 OpenDART/XBRL 기반 데이터와 검증 문서 |
| [reporting/](reporting/README.md) | 패턴, 전략, 펀더멘털 결과를 모아 사용자가 확인하는 종목 보고서 |
| [strategies/](strategies/README.md) | 패턴의 판단 결과를 바탕으로 실제 매매 방법을 정하는 전략과 독립 전략 |

`patterns/`에는 Pattern A와 Pattern A FAST가 있다. `A FAST Core V1/V2/V3`는
Pattern A FAST와 강하게 결합되어 있으므로 현재 해당 패턴 아래에서 관리한다.
여러 패턴을 조합하거나 특정 패턴과 독립적인 파생 전략은 `strategies/`에 둔다.
예를 들어 Julia Strategy가 독립 전략으로 정리되면 이 영역에서 관리한다.

## 현재 사용 중인 패턴과 전략

- **Pattern A** — 현재 운영을 유지하는 패턴이다. 상세 내용은 [Pattern A 안내](patterns/pattern_a/README.md)에서 확인한다. (`FROZEN` / `KEEP_CURRENT_PRODUCTION`)
- **Pattern A FAST** — Pattern A보다 빠른 상승 전환을 탐지하는 패턴이다. 현재 기본 전략은 A FAST Core V2다. ([Pattern A FAST 안내](patterns/pattern_a_fast/README.md))
- **A FAST Core V3** — 규칙이 동결된 후보 전략이다. 아직 공식 전략이 아니며 기본 전략도 대체하지 않는다. 다음 단계는 V2와 동일 조건으로 비교하는 검증이다. ([V3 후보 규칙](patterns/pattern_a_fast/strategy/final_v03_candidate.md))

현재 기본 전략 변경과 후보 전략의 공식 채택 절차는 [전략 생애주기와 채택 절차](strategies/strategy_lifecycle.md)에서 확인한다.

## 현재 보고서

- **Fundamentals V1** — 일반 비금융 보통주와 비금융 지주회사를 지원하는 기업 실적 분석 영역이다. 금융회사 일반 V1은 적용 대상이 아니다. ([Fundamentals 안내](fundamentals/README.md))
- **Stock Report** — 펀더멘털과 시장·업종 상대강도 정보를 모아 제공하는 종목 보고서다. ([Stock Report 안내](reporting/stock_report/README.md))
- **Web Report Viewer** — 정적 종목 보고서를 조회하고 검색하는 읽기 전용 화면이다.

## 현재 전략 상태

A FAST Core V2는 현재 기본 전략이며 Pattern A FAST 내부에서 실제 의사결정
지원에 사용한다. 필요한 기술 상태값은 해당 전략 문서에서 확인한다.

A FAST Core V3는 `PATTERN_A_FAST_FINAL_STRATEGY_V03` 후보 전략이며,
`FROZEN_CANDIDATE_AWAITING_MATCHED_AB` 상태다. V2와 동일 조건 비교 검증이
끝나기 전에는 공식 전략 채택이나 기본 전략 승격을 하지 않는다.

## 향후 작업 계획

[ROADMAP.md](../ROADMAP.md)

## 문서 작성 원칙과 파일 이름 규칙

- 문서는 공통 영역, 패턴, 문서 역할, 구체적인 문서 순으로 찾을 수 있게 구성한다.
- 경로가 패턴과 역할을 설명하므로 파일명에서 같은 말을 불필요하게 반복하지 않는다.
- `prereg/` 안에서는 파일명에 `_prereg`나 `_preregistration`을 다시 붙이지 않는다.
- 문서에 명시되지 않은 버전 번호를 임의로 만들지 않는다.
- `archive/`에는 현재 기준이 아니고 대체된 문서만 보관한다. 공식 과거 기준선은 해당 역할 폴더에 유지한다.
- README는 산식이나 결론을 새로 만드는 곳이 아니라, 기준 문서로 안내하는 곳이다.

## 이전 경로 안내

기존 `docs/specs/`와 `docs/validation/`의 문서는 대부분 새 구조로 이동되어
있다. `docs/validation/`에 남아 있는 일부 파일은 이전 경로 호환을 위해
보존된 안내 파일이며, 현재 기준 문서는 각 실제 영역의 문서다.
