# Julia 전략 문서

이 디렉터리는 공식 ETF 전략 Julia V1과 일반 종목 비교 및 ETF 채택 심사에 사용된
Julia V00 과거 연구·검증 기록을 함께 관리한다.

## 현재 상태

- 공식 표시명: `Julia V1`
- 공식 전략 ID: `JULIA_ETF_STRATEGY_V01`
- ETF 공식 상태: `OFFICIAL_STRATEGY_ADOPTED`
- 적용 범위: OFFICIAL ETF 36 ONLY
- 일반 종목 적용: 금지. V00 일반주 미채택 결론 유지
- 기본 전략/CONTROL: `A FAST Core V2` / `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- Julia V00 계보: `JULIA_STRATEGY_V00`은 과거 연구 및 ETF 공식 채택 심사에 사용된 검증 후보 ID
- 규칙 관계: V1은 V00 규칙을 수정 없이 계승한다. 별도의 evaluator 또는 코드 ID migration은 이번 문서 승격에 포함하지 않는다.
- 자동 주문: 승인하지 않음
- 현재 연결: Stock Report, Phase 4 전략 모니터, ETF 리포트, 운용 UI 및 자동 주문에 미연결
- 과거 일반 종목 비교: V2 `58.8579%` vs Julia `38.5329%`; 이는 일반 종목 비교 기록이며 ETF 전용 채택 판정을 대체하지 않음
- 검증 유형: V00 심사는 `SAME_SAMPLE_RETROSPECTIVE`

Julia V1은 ETF 전용 공식 전략으로 채택되었다. 일반 종목의 Julia 상태는
NOT ADOPTED / RETIRED AS GENERAL-STOCK OFFICIAL STRATEGY로 유지한다.
V1은 문서상 공식 승격 이름과 ID이며, 실행기·리포트·UI에 아직 연결되지 않았다.

최근 문서 재배치에 따라 V2↔Julia execution contract의 문서 경로와 SHA만
archive 구조 기준으로 재동결했으며, 전략 규칙과 기존 백테스트 결과는 변경하지 않았다.

## 전략 생애주기 단계

| 단계 | 상태 | 근거와 범위 |
|---:|---|---|
| 1. 전략 아이디어 정의 | 완료 | Loss Guard 제거의 손실 방어·상승 기회 상충 관계가 연구 질문으로 기록됨 |
| 2. 전략 규칙 명세화 | 완료 | V2 공식 규칙 문서와 동일한 진입·보유·청산·재진입 경로를 사용하며 `enable_loss_guard=False`로 과거 V00 검증 후보에 단일 변경점만 적용함 |
| 3. 후보 전략 동결 | 완료 | 과거 V00 계약에 기준 전략, 단일 변경점, 전략 ID, `no_tuning: true`가 고정되어 결과에 따른 규칙 조정을 하지 않음 |
| 4. 검증 계획 확정 | 완료 / 동결 | [V00 일반 종목 과거 검증 계획 V01](archive/validation/validation_plan_v01.md)에 비교 조건과 판정 기준을 고정함 |
| 5. 동일 조건 비교 백테스트 | 완료 | V00 일반 종목 비교에서 `Matched-entry`, `Sequential`, 현실적 2억 포트폴리오를 동일 조건으로 1회 완료함 |
| 6. 핵심 성과 비교 | 완료 | V00 일반 종목 최종 포트폴리오 성과에서 V2 `58.8579%`, Julia `38.5329%`를 확인함 |
| 7. 실패 사례 및 부작용 검증 | 완료 | 미해결 상태(`unresolved`), 종료 시점 미해결(`terminal unresolved`), 현금 보존(`cash conservation`) 및 Loss Guard 하위 집합을 확인함 |
| 8. 강건성 검증 | 제한적 확인 | 과거 일반 종목 비교는 연도별·시장별·집중도 분석을 확정하지 않음; ETF 전용 검토의 진단 결과는 별도 심사 보고서에 기록함 |
| 9. 최종 전략 검토 | 완료 | 일반 종목 공식 전략은 V2로 유지함 |
| 10. 공식 전략 채택 여부 결정 | 완료 | 일반 종목 V00: 미채택 유지; ETF 36: 검증 후보 V00을 Julia V1으로 공식 채택 |
| 11. 기본 전략 승격 여부 결정 | 완료 | 일반 종목 기본 전략 승격 없음; V2 유지. ETF 공식 채택은 기본 전략 승격이 아님 |
| 12. 버전·문서·결과물 확정 | 완료 | V00 검증 기록은 유지하고 공식 ETF 이름·ID 및 현재 문서를 V1로 정리함 |
| 13. 운영 환경 반영 | 별도 적용 없음 | ETF 공식 자격만 기록; 종목 리포트·운용 UI·자동 주문은 연결하지 않음 |
| 14. 사후 성과 확인 | 대기 | ETF 전략은 공식 채택됐으나 리포트·운용 환경에는 연결하지 않아 운영 성과 확인 전 |

일반 종목 Julia 비교 결론은 종료 상태로 유지하며 ETF 36 전용 채택은 별도 결정으로 기록한다.
일반 종목 기본 전략과 ETF 리포트·운용 연결 범위는 변경하지 않는다.

## 문서 인덱스

- [Julia V1 공식 전략 문서](JULIA_ETF_STRATEGY_V01.md): ETF 36 전용 공식 상태와 V00에서 계승한 규칙 계약.

- [Julia V00 ETF 전용 공식 채택 심사 V01](../../../artifacts/strategies/julia/etf_official_adoption_v01/report.md): 다섯 표준 기간의 공통 A~E gate와 진단 결과.

- [V00 과거 연구 기록](archive/research/v00.md): 공식 PIT 117/215개 기준일에서 중단된 불완전
  PIT 백필 체크포인트. 성과 해석은 억제된 상태다.
- [proxy_market_cap_v01 과거 비공식 연구](archive/research/proxy_market_cap_v01.md): 98개
  결측 기준일에 예상 시가총액을 사용한 연구 기록이며 공식 검증 근거가 아니다.
- [V00 일반 종목 과거 검증 계획 V01](archive/validation/validation_plan_v01.md): Stage 4에서 동결한
  사전 비교 계획과 최종 비교 후 현재 결정을 함께 보존하는 문서이다.
- [최신 ETF V3·Julia 통합 비교](../../../artifacts/research/etf_v3_julia_integrated_comparison_v01/final_comparison.md):
  21개 ETF의 비교 증거를 정리한 별도 연구 문서이며 Julia 공식 검증 계획은 아니다.
- 관련 결과물: `artifacts/strategies/julia/v00/` 및
  `artifacts/strategies/julia/proxy_market_cap_v01/`

과거 문서는 삭제하지 않는다. 현재 상태·공식 절차와 과거 연구 기록을 서로
혼동하지 않도록 역할을 나누어 보존한다.
