# Julia 전략 문서

이 디렉터리는 `A FAST Core V2` (`PATTERN_A_FAST_FINAL_STRATEGY_V02`)의 변형을
탐색한 Julia 전략의 현재 상태와 과거 연구 기록을 관리한다.

## 현재 상태

- 연구 분류: 과거 비교 기록 (`HISTORICAL_COMPARISON_RECORD`)
- 일반 종목 공식 전략 여부: `NOT ADOPTED / RETIRED AS GENERAL-STOCK OFFICIAL STRATEGY`
- 현재 기본 전략: `A FAST Core V2` (`PATTERN_A_FAST_FINAL_STRATEGY_V02`)
- V2와의 핵심 차이: 사전 진행 단계의 `-15% Loss Guard`를 끈 비교 후보이다.
- FastCore 전용 Fundamentals Filter와 전략 조건은 Julia V00에 자동 승계하지 않음
- 최종 비교: `2021-01-01 ~ 2026-08-14`, 동일 진입 비교 `Matched-entry` `8,533`건, 양쪽 현실적 2억 포트폴리오 `PASS`
- 최종 포트폴리오 성과: V2 `58.8579%` vs Julia `38.5329%`; Julia는 V2 대체 전략으로 채택하지 않음
- ETF 상태: Julia의 ETF 전용 가능성은 보류(`DEFERRED`); 공식 ETF 전략으로 확정하지 않음
- 과거 연구의 실증 방식: `SAME_SAMPLE_RETROSPECTIVE`

Julia 연구 기록과 최신 ETF 비교 결과는 삭제하지 않고 보존한다. 최종 V2와
Julia의 일반 종목 비교 및 채택 판단은 종료되었으며, Julia는 일반 종목 공식
전략으로 채택하지 않는다. ETF 관련 판단은 별도 전용 검증 전까지 보류
(`DEFERRED`)로 유지한다.

최근 문서 재배치에 따라 V2↔Julia execution contract의 문서 경로와 SHA만
archive 구조 기준으로 재동결했으며, 전략 규칙과 기존 백테스트 결과는 변경하지 않았다.

## 전략 생애주기 단계

| 단계 | 상태 | 근거와 범위 |
|---:|---|---|
| 1. 전략 아이디어 정의 | 완료 | Loss Guard 제거의 손실 방어·상승 기회 상충 관계가 연구 질문으로 기록됨 |
| 2. 전략 규칙 명세화 | 완료 | V2 공식 규칙 문서와 동일한 진입·보유·청산·재진입 경로를 사용하며 `enable_loss_guard=False`로 단일 변경점만 적용함 |
| 3. 후보 전략 동결 | 완료 | 현재 계약에 기준 전략, 단일 변경점, 전략 ID, `no_tuning: true`가 고정되어 결과에 따른 규칙 조정을 하지 않음 |
| 4. 검증 계획 확정 | 완료 / 동결 | [Julia 공식 전략 검증 계획 V01](archive/validation/validation_plan_v01.md)에 비교 조건과 판정 기준을 고정함 |
| 5. 동일 조건 비교 백테스트 | 완료 | `Matched-entry`, `Sequential`, 현실적 2억 포트폴리오를 동일 조건으로 1회 완료함 |
| 6. 핵심 성과 비교 | 완료 | 최종 포트폴리오 성과에서 V2 `58.8579%`, Julia `38.5329%`를 확인함 |
| 7. 실패 사례 및 부작용 검증 | 완료 | 미해결 상태(`unresolved`), 종료 시점 미해결(`terminal unresolved`), 현금 보존(`cash conservation`) 및 Loss Guard 하위 집합을 확인함 |
| 8. 강건성 검증 | 제한적 확인 | Loss Guard 발생 하위 집합과 핵심 운용 결과만 확인함; 연도별·시장별·집중도 분석은 이번 최종 비교에서 확정하지 않음 |
| 9. 최종 전략 검토 | 완료 | 일반 종목 공식 전략은 V2로 유지함 |
| 10. 공식 전략 채택 여부 결정 | 완료 | `NOT ADOPTED / RETIRED AS GENERAL-STOCK OFFICIAL STRATEGY` |
| 11. 기본 전략 승격 여부 결정 | 완료 | Julia 승격 없음; V2를 현재 기본 전략으로 유지함 |
| 12. 버전·문서·결과물 확정 | 완료 | 비교 결과와 현재 결론을 공식 문서에 반영함 |
| 13. 운영 환경 반영 | `NOT_APPLICABLE` | 일반 종목 공식 전략으로 채택되지 않았으므로 운영 반영 대상이 아님 |
| 14. 사후 성과 확인 | `NOT_APPLICABLE` | 운영 전략으로 승격되지 않았으므로 해당 단계에 진입하지 않음 |

일반 종목 Julia 비교와 채택 판단은 종료되었다. 문서 정리를 마친 뒤 최신
데이터 기반 종목 리포트와 스캐너 운영 흐름으로 복귀한다.

## 문서 인덱스

- [V00 과거 연구 기록](archive/research/v00.md): 공식 PIT 117/215개 기준일에서 중단된 불완전
  PIT 백필 체크포인트. 성과 해석은 억제된 상태다.
- [proxy_market_cap_v01 과거 비공식 연구](archive/research/proxy_market_cap_v01.md): 98개
  결측 기준일에 예상 시가총액을 사용한 연구 기록이며 공식 검증 근거가 아니다.
- [Julia 공식 전략 검증 계획 V01](archive/validation/validation_plan_v01.md): Stage 4에서 동결한
  사전 비교 계획과 최종 비교 후 현재 결정을 함께 보존하는 문서이다.
- [최신 ETF V3·Julia 통합 비교](../../../artifacts/research/etf_v3_julia_integrated_comparison_v01/final_comparison.md):
  21개 ETF의 비교 증거를 정리한 별도 연구 문서이며 Julia 공식 검증 계획은 아니다.
- 관련 결과물: `artifacts/strategies/julia/v00/` 및
  `artifacts/strategies/julia/proxy_market_cap_v01/`

과거 문서는 삭제하지 않는다. 현재 상태·공식 절차와 과거 연구 기록을 서로
혼동하지 않도록 역할을 나누어 보존한다.
