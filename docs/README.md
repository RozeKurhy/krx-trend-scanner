# KRX Trend Scanner 문서 안내

이 문서는 `docs/` 아래 문서의 위치와 역할을 안내하고, 프로젝트 문서를
작성할 때 따를 기준을 정리한다. 각 영역의 README에서 세부 문서 위치를
확인할 수 있다.

## 어디부터 읽을지

1. 프로젝트 전체 이해 → [README.md](../README.md)
2. 프로젝트 확장 방향과 작업 선택 원칙 → [ROADMAP.md](../ROADMAP.md)
3. 세부 문서 위치와 작성 기준 → 이 문서
4. 세부 산식·계약·검증 결과 → 각 영역의 기준 문서

## 패턴과 전략의 차이

**패턴**은 종목이나 시장에서 어떤 가격 구조와 상태가 나타나는지 판단하는
기준이다. 즉, 무엇이 보이는지를 판단한다.

**전략**은 패턴과 다른 조건을 이용해 언제 진입하고, 보유하고, 청산할지
정하는 매매 규칙이다. 즉, 판단 결과를 바탕으로 무엇을 할지 결정한다.

패턴은 관찰·판단의 기준이고 전략은 행동의 규칙이므로 서로 다른 문서 역할을
가진다.

## docs 최상위 영역

| 영역 | 이곳에서 다루는 내용 |
|---|---|
| [architecture/](architecture/README.md) | 프로젝트 공통 구조, 데이터 처리 방식, 공용 기술 문서 |
| [fundamentals/](fundamentals/README.md) | OpenDART/XBRL 기반 기업 실적·재무 데이터와 검증 문서 |
| [patterns/](patterns/README.md) | 종목·시장 상태를 판단하는 패턴의 정의와 연구·검증 기록 |
| [relative_strength/](relative_strength/) | 시장·업종 상대강도 계산과 제공 계약 |
| [reporting/](reporting/README.md) | 패턴·전략·펀더멘털 결과를 모은 종목 보고서 문서 |
| [strategies/](strategies/README.md) | 패턴 결과를 매매 규칙으로 연결하는 전략과 독립 전략 |
| [validation/](validation/) | 이전 문서 경로 호환 안내와 영역 공통 현재 기준 문서 |
| [web/](web/) | 웹 화면에 제공하는 정적 데이터·전달 계약 |

`patterns/`에는 Pattern A, Pattern A FAST와 초기 연구 후보인 Pattern B가 있다.
A FAST Core 전략 문서는
Pattern A FAST와 강하게 결합되어 있으므로 해당 패턴 아래에서 관리한다.
여러 패턴을 조합하거나 특정 패턴과 독립적인 전략은 `strategies/`에 둔다.

## 핵심 기준 문서

- **Pattern A** — 공식 패턴 규격은 [공식 규격 문서](patterns/pattern_a/spec/production_authority.md)를 따른다.
- **Pattern A FAST** — 의미와 생애주기는 [FAST 명세](patterns/pattern_a_fast/spec/README.md)를 따른다.
- **A FAST Core V2** — 일반 종목 전략 규칙은 [V2 계약](patterns/pattern_a_fast/strategy/version_02/README.md)의 `PATTERN_A_FAST_FINAL_STRATEGY_V02`다.
- **Fundamentals V1** — 기준은 [Fundamentals 안내](fundamentals/README.md)와 해당 영역의 기준 문서에서 확인한다.
- **Stock Report v0.5** — 보고서 계약은 [Stock Report 안내](reporting/stock_report/README.md)와 [v0.5 계약](reporting/stock_report/contract_v05.md)을 따른다.
- **전략 채택 절차** — 기본 전략 변경과 후보 전략의 공식 채택은 [전략 생애주기와 채택 절차](strategies/strategy_lifecycle.md)를 따른다.

## 현재 문서와 역사 기록의 구분

문서는 다음 세 가지로 구분한다.

### 현재 기준 문서

현재 구현·운영·전략·계약에서 실제 기준으로 사용하는 문서다.

### 역사 기록

과거 연구, 검증, 후보 전략, 대체된 계획과 결과를 보존하는 문서다. 역사
기록에 적힌 `NEXT`, `HOLD`, `IN_PROGRESS`, 검증 대기 등의 상태는 당시 상태를
기록한 것이며 현재 프로젝트 상태를 뜻하지 않을 수 있다.

공식 과거 기준선은 현재 기본 전략은 아니지만 비교·검증 기준으로 보존하는
문서다. 따라서 단순히 오래되었다는 이유로 일반적인 대체·폐기 문서와 같은
것으로 취급하지 않는다. 예를 들어 A FAST Core V1은 `HISTORICAL_FROZEN_BASELINE`
역할을 유지한다.

### 호환 안내

이전 경로나 이전 문서 구조에서 현재 기준 문서로 연결하기 위한 문서다. 호환
안내는 과거 경로 접근성을 제공하며, 현재 계약이나 구현의 권위를 대신하지
않는다.

## 문서 작성 원칙

- 문서는 공통 영역, 패턴, 문서 역할, 구체적인 기준 문서 순으로 찾을 수 있게 구성한다.
- README는 안내와 요약을 담당한다. 세부 산식, 임계값, 계약, 검증 결과는 해당 권위 문서에서 관리한다.
- README는 프로젝트 목적, 구조, 문서 위치를 짧게 안내하고 권위 문서로 연결한다. 상위 README가 하위 권위 문서를 대체하지 않도록 한다.
- 같은 사실을 여러 README에서 장문으로 반복하지 않는다. 기존 권위 문서가 있으면 링크하거나 참조한다.
- 경로가 패턴과 역할을 설명하므로 파일명에서 같은 말을 불필요하게 반복하지 않는다.
- `prereg/` 안에서는 파일명에 `_prereg`나 `_preregistration`을 다시 붙이지 않는다.
- 문서에 명시되지 않은 버전 번호를 임의로 만들지 않는다.
- `archive/`에는 현재 기준이 아니고 대체된 문서를 보관한다. 공식 과거 기준선은 해당 역할 폴더에 유지한다.
- 패턴의 현재 규격 문서는 각 패턴 폴더의 `spec/` 폴더에 둔다.
- 일반 설명은 한글을 우선한다. 제목, 소제목, 현재 상태, 전략 설명, 사용자에게 보여주는 문구도 한글로 작성한다.
- 코드 식별자, 파일명, 경로, 함수·클래스·필드명, JSON 키, 공식 전략 ID, 고정 상태 토큰, Git 식별자, API·KRX·OpenDART·XBRL 같은 고유명과 약어는 영어 표기를 유지할 수 있다.
- 영어 상태 토큰은 최초 등장 시 사람이 이해할 수 있는 한글 설명을 함께 쓴다. 예: 의사결정 지원 운영 상태 (`PRODUCTION_DECISION_SUPPORT`).
- 일반 설명에서는 `Current Default Strategy`보다 현재 기본 전략, `Historical Baseline`보다 과거 비교 기준선처럼 한글 표현을 우선한다.
- 과거 실험값이나 구현값을 별도 승인 없이 현재 공식 기준으로 승격하지 않는다. 검토 대기, 후보, 공식, 과거·대체됨 등의 상태를 분명히 표시한다.
- 문서 작성·수정은 이 문서의 기준을 따르고, 현재 작업 목적에 필요한 범위까지만 기록한다.

## 이전 경로 안내

기존 `docs/specs/`와 `docs/validation/`의 문서는 대부분 새 구조로 이동되어
있다. `docs/validation/`에는 이전 경로 호환 안내와 영역을 가로지르는 현재
기준 문서가 함께 있을 수 있으며, 각 문서의 역할과 권위 표기를 따른다.
