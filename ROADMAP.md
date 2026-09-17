# KRX Trend Scanner 개발 로드맵

이 문서는 프로젝트가 현재 어디까지 왔고, 무엇을 진행하며, 다음에 무엇을 할지
빠르게 확인하기 위한 기준 문서다.

세부 산식·계약·검증 결과와 과거 연구 내용은 각 영역의 권위 문서에서 관리한다.
이 문서는 현재 상태와 작업 순서를 요약하며, 과거 작업일지 전체를 대신하지 않는다.

## 핵심 목표

가격 구조, 투자 적합성, 수급, 상대강도, 기업 실적을 독립적으로 확인해 상승 추세
초기 후보를 탐색하고, 종목 리포트와 전략 상태를 통해 투자 의사결정을 지원한다.

자동 주문을 실행하는 시스템이 아니며, 새 전략이나 기능은 독립적인 검토와 검증을
거친 뒤 현재 운영 범위에 포함한다.

## 1. 현재 상태

- Repository V2 기반 시장 데이터 운영 경로가 완료되었다.
- 시장가격 데이터 검증이 완료되었고, Pattern A 운영 기준이 확정되었다.
- Pattern A FAST 연구가 완료되었으며, 보조 신호로 관리한다.
- 일반 종목의 공식 기본 전략은 `PATTERN_A_FAST_FINAL_STRATEGY_V02`다.
- Julia는 일반 종목 공식 전략으로 채택하지 않는다.
- OpenDART Fundamentals V1 운영이 완료되었다.
- 외국인 수급, Market RS, Sector RS 분석과 Stock Report v0.5가 운영 가능하다.
- 웹 조회 기능은 생성된 리포트를 조회하는 읽기 전용 기능으로 운영한다.
- 일반 종목 전략 백테스트 연구 사이클은 종료되었다.
- 원격 브랜치는 `main`만 유지한다.
- 현재 문서 전수 재정리를 진행 중이다.

## 2. 다음 작업

### 1단계. 문서 정리

현재 진행 중인 문서 재정리를 다음 순서로 마무리한다.

- `docs/README.md` 정리 완료
- 루트 `README.md` 정리 완료
- `ROADMAP.md` 정리 완료
- 이후 하위 문서 정리 순서:

  `patterns/`
  → `strategies/`
  → `architecture/`
  → `fundamentals/`
  → `relative_strength/`
  → `reporting/`
  → `web/`
  → `validation/`

하위 문서는 현재 기준, 역사 기록, 호환 안내의 역할을 구분하며 세부 규칙은
각 권위 문서에 남긴다.

### 2단계. 최신 데이터 기반 운영 복귀

문서 정리가 끝나면 다음 운영 흐름으로 복귀한다.

- 최신 데이터 기준 Stock Report 재생성
- 최신 데이터 기준 scanner 운영 흐름 점검
- scanner → 종목 리포트 → 웹 조회 연결 확인

이 단계에서는 기존 운영 계약과 로컬 데이터 기준을 따르며, 별도 지시 없이
새 전략이나 새 데이터 기준을 만들지 않는다.

### 3단계. 이후 전략 연구

필요성이 확인된 경우에만 다음 연구를 별도 작업으로 시작한다.

- 기존 전략 개선
- 새로운 전략 후보 연구
- 새로운 백테스트

현재는 추가 전략 연구를 진행 중인 것으로 보지 않는다.

## 3. 보류

현재 실제로 보류 중인 항목은 다음과 같다.

- Pattern B~F 신규 패턴 개발
- V3/V4 및 추가 청산 규칙 연구
- Julia ETF 전용 전략 검증
- 금융회사 전용 Fundamentals 확장
- Sector RS 전체 COMMON 순위 체계 등 추가 확장
- 구체적인 오류가 없는 상태에서의 추가 market-data hardening

위 항목은 현재 작업 순서에 포함하지 않는다. 과거 작업 브랜치나 삭제된 브랜치는
현재 상태로 다시 기록하지 않는다.

## 4. 알려진 한계

- 일부 scanner 분석은 후보 종목 중심으로 수행되는 범위가 남아 있다.
- 금융회사는 Fundamentals V1의 일반 적용 대상이 아니며 전용 확장은 미래 범위다.
- Sector RS의 전체 COMMON 순위·백분위 기준은 아직 없다.
- legacy PyKRX 관련 코드는 저장소에 남아 있지만 현재 production scanner와
  report 경로의 fallback에는 사용하지 않는다.

## 5. 완료 이력 요약

| 영역 | 완료 결과 |
|---|---|
| Pattern A | 운영 기준 확정 |
| 투자 적합성 | 시가총액·유동성 필터 완료 |
| 외국인 수급 | 독립 분석 축 구축 |
| Market RS | 시장 상대강도 분석 완료 |
| Sector RS | 종목 리포트 통합 완료 |
| Pattern A FAST | 연구 종료 |
| A FAST Core V2 | 일반 종목 기본 전략 확정 |
| Fundamentals V1 | OpenDART 기반 운영 완료 |
| Stock Report v0.5 | 통합 리포트 운영 완료 |
| 웹 조회 | 읽기 전용 조회 기능 완료 |
| V2 ↔ Julia | 비교 완료, 일반 종목 V2 유지 |
| Repository V2 | 시장 데이터 운영 경로 전환 완료 |
| 시장가격 검증 | 운영 데이터 검증 완료 |
| 브랜치 정리 | 원격 `main` 단일 브랜치 정리 완료 |

## 상세 문서 안내

- 문서 구조와 작성 기준은 [docs/README.md](docs/README.md)에서 확인한다.
- Pattern A의 세부 규격은 [공식 규격 문서](docs/patterns/pattern_a/spec/production_authority.md)에서 확인한다.
- Pattern A FAST의 의미와 생애주기는 [FAST 명세](docs/patterns/pattern_a_fast/spec/README.md)에서 확인한다.
- A FAST Core V2의 세부 계약은 [V2 계약](docs/patterns/pattern_a_fast/strategy/version_02/README.md)에서 확인한다.
- Fundamentals V1의 기준은 [Fundamentals 안내](docs/fundamentals/README.md)에서 확인한다.
- Stock Report v0.5의 역할과 계약은 [Stock Report 안내](docs/reporting/stock_report/README.md)에서 확인한다.

문서를 추가하거나 수정할 때는 현재 기준과 역사 기록을 구분하고, 이미 권위 문서에
있는 사실을 이 문서에 장문으로 반복하지 않는다.
