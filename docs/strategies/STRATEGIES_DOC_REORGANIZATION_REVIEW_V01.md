# `strategies/` 문서 전수 분류 검토 V01

## 1. 작업 범위와 현재 기준

이번 단계에서는 `docs/strategies/` 아래 기존 Markdown을 전수 확인하고
`KEEP`, `ARCHIVE`, `DELETE_CANDIDATE`로만 분류한다. 기존 문서의 본문·링크·파일
위치는 이번 단계에서 변경하지 않는다.

현재 일반 종목의 공식 기본 전략은
`PATTERN_A_FAST_FINAL_STRATEGY_V02`다. Julia는 일반 종목 공식 전략으로 채택되지
않았고, ETF 전용 가능성만 `DEFERRED` 상태로 보존한다.

## 2. 요약

실제 조사 대상 Markdown은 6개다.

| 분류 | 건수 | 원칙 |
|---|---:|---|
| `KEEP` | 3 | 현재 전략 문서 탐색·공통 절차·현재 상태 확인에 필요한 문서 |
| `ARCHIVE` | 3 | 현재 권위는 아니지만 연구·검증·판단 근거를 보존할 가치가 있는 문서 |
| `DELETE_CANDIDATE` | 0 | 고유한 역사적 정보 손실 없이 삭제할 수 있다고 확인된 문서 없음 |

`KEEP + ARCHIVE + DELETE_CANDIDATE = 3 + 3 + 0 = 6`으로 조사 대상 수와
일치한다. 새로 작성한 이 통제 문서는 조사 대상 6개에 포함하지 않는다.

## 3. KEEP

| 파일 경로 | 현재 역할 | KEEP 근거 | 현재 권위와 관계 | 내용 정리 필요 여부 |
|---|---|---|---|---|
| `docs/strategies/README.md` | 전략 영역의 현재 진입점과 전략별 문서 위치 안내 | 현재 기본 전략 V2, Julia의 현재 미채택·ETF `DEFERRED` 상태, 공통 절차 위치를 안내한다. | 전략 영역 탐색의 상위 안내 문서이며 세부 규칙을 대체하지 않는다. | 후속 이동 이후 현재/역사 문서 경계를 다시 읽고 최소 정리할 수 있다. |
| `docs/strategies/strategy_lifecycle.md` | 프로젝트 공통 전략 생애주기·검증·채택 절차 | `docs/README.md`와 `docs/strategies/README.md`에서 공통 전략 절차로 참조하며, 공식 전략·기본 전략·검증·채택 단계를 현재 기준으로 정의한다. | 전략별 규칙이 아닌 프로젝트 공통 절차의 현재 기준 문서다. | 현재 절차와 실제 참조 관계를 유지하는 범위에서 후속 검토한다. |
| `docs/strategies/julia/README.md` | Julia 전략의 현재 상태와 과거 기록 인덱스 | Julia의 일반 종목 미채택, V2 유지, ETF `DEFERRED` 상태를 현재 관점에서 안내하고 과거 문서와 결과물의 역할을 구분한다. | Julia 영역의 현재 상태 진입점이며 과거 연구 원문 자체는 아니다. | archive 이동 후 역사 문서 링크와 현재/과거 경계를 다시 확인한다. |

## 4. ARCHIVE

| 파일 경로 | 역사적 역할 | ARCHIVE 근거 | 고유 보존 가치 | 예상 archive 위치 |
|---|---|---|---|---|
| `docs/strategies/julia/v00.md` | 중단된 Julia V00 PIT 백필 체크포인트 | `NON_AUTHORITATIVE_INCOMPLETE_SOURCE_COVERAGE`이며 PIT 커버리지 117/215개로 불완전하다. 현재 공식 결과나 현재 실행 계획이 아니다. | 당시 수집 출처·무결성 상태·누락 기준일·재개 조건을 보존한다. 단순 중복 문서가 아니다. | `docs/strategies/julia/archive/research/v00.md` |
| `docs/strategies/julia/validation_plan_v01.md` | Julia 후보 전략의 과거 검증 계획과 최종 비교 결정 기록 | 문서 상태가 `STAGE_4_FROZEN / HISTORICAL_PLAN`이며 비교 조건과 판정 기준을 사전 고정한 역사 계획이다. 현재 추가 실행 지시나 Julia 채택 권위가 아니다. | Loss Guard 단일 변경점, 공식 기간·모집단·PIT·공통조건·판정 기준과 최종 비채택 결정을 함께 보존한다. | `docs/strategies/julia/archive/validation/validation_plan_v01.md` |
| `docs/strategies/julia/proxy_market_cap_v01.md` | 공식 KRX PIT 값이 없던 기준일의 예상 시가총액 proxy 연구 | `NON-AUTHORITATIVE_PROXY_PIT`이며 공식 검증·프로덕션 승인 근거가 아니다. 과거 실험의 결과와 한계를 기록한다. | 예상값 오차·경계 민감도·위험·수익 비교와 당시 결론을 보존한다. 후속 연구의 실패·위험 모드 참고 가치가 있다. | `docs/strategies/julia/archive/research/proxy_market_cap_v01.md` |

## 5. DELETE_CANDIDATE

없음.

세 문서 모두 현재 권위는 아니지만 서로 다른 수집 상태, 검증 계획, proxy
실험 결과를 보존한다. 현재 문서와 중복된다고 단정하거나 삭제할 경우 과거
연구의 재현·판단 맥락이 손실될 수 있으므로 ARCHIVE로 유지한다.

## 6. Julia 문서 특별 검토

| 문서 | 분류 | 판단 |
|---|---|---|
| `julia/README.md` | `KEEP` | Julia가 채택되지 않았다는 현재 상태 자체를 안내하고, 과거 문서와 ETF `DEFERRED` 상태를 구분하는 live 진입점이다. Julia라는 이유만으로 archive하지 않는다. |
| `julia/v00.md` | `ARCHIVE` | 54.42% PIT 커버리지의 중단 체크포인트다. 일반 종목 재검증의 현재 작업으로 해석하면 안 되지만, 수집 경로와 무결성 기록에 고유 가치가 있다. |
| `julia/validation_plan_v01.md` | `ARCHIVE` | 현재 결정 업데이트가 포함되어도 문서의 본질은 동결된 Stage 4 사전 검증 계획과 역사적 실행 조건이다. 현재 상태 안내는 `julia/README.md`가 담당하므로 archive한다. |
| `julia/proxy_market_cap_v01.md` | `ARCHIVE` | 공식 PIT가 아닌 예상 시가총액을 사용한 비공식 실험이다. 공식 결과로 유지하지 않되 proxy 오차·위험 분석의 고유 기록은 보존한다. |

## 7. 후속 작업 제안

다음 단계에서 이동을 수행한다면 파일명 수준의 제안은 다음과 같다.

1. `julia/v00.md`를 `julia/archive/research/v00.md`로 이동한다.
2. `julia/validation_plan_v01.md`를 `julia/archive/validation/validation_plan_v01.md`로 이동한다.
3. `julia/proxy_market_cap_v01.md`를 `julia/archive/research/proxy_market_cap_v01.md`로 이동한다.
4. 이동 후 KEEP 문서 3개(`strategies/README.md`, `strategy_lifecycle.md`,
   `julia/README.md`)를 다시 읽고 현재 링크와 현재/역사 경계를 최소 정리한다.
5. 삭제 후보는 현재 제안하지 않는다.

이번 단계에서는 위 이동·삭제·본문 수정·링크 수정·코드·테스트·백테스트·외부
API 호출을 수행하지 않는다.

## 8. 셀프 리뷰

- 모든 기존 `docs/strategies/` Markdown 6개를 읽었다: **YES**
- 현재 권위와 역사 기록을 구분했다: **YES**
- Julia 일반 종목 미채택과 ETF `DEFERRED` 상태를 반영했다: **YES**
- 과거 계획 문구를 현재 계획으로 오인하지 않았다: **YES**
- 삭제 후보를 과도하게 만들지 않았다: **YES**
- 기존 문서 본문을 수정하지 않았다: **YES**
- 실제 이동·삭제를 하지 않았다: **YES**
