# A FAST Core V2 개선 연구 종료 기록

작성일: 2026-09-27 KST

상태: `A_FAST_CORE_V2_IMPROVEMENT_RESEARCH_CLOSED`

## 공식 상태

| 대상 | 최종 상태 | 결정 |
|---|---|---|
| Production — A FAST Core V2 | `PRODUCTION / KEEP` — `PATTERN_A_FAST_FINAL_STRATEGY_V02` | 현재 공식 전략과 파라미터를 유지한다. 전략 코드 및 운영 파라미터는 변경하지 않았다. |
| V2.1 Candidate — `PATTERN_A_FAST_CORE_V2_NEG40_WEAK_PROTECT_SOFT_EXIT_V01` | `V2_1_PROMOTION_REJECTED_RESEARCH_CLOSED` | 승격하지 않으며, V2.1 공식 명칭을 부여하지 않는다. 기존 Candidate 이름과 산출물은 연구 이력으로 보존한다. |
| Exit4 threshold research | `EXIT4_T15_KEEP_RESEARCH_CLOSED` | 현재 Exit4 15pt를 유지하고 threshold sweep을 종료한다. |
| Exit3 Coverage Extension | `EXIT3_COVERAGE_EXTENSION_NOT_PROMOTED_RESEARCH_CLOSED` | Production에 반영하지 않는다. |
| EARLY_TREND-only | `NOT_RUN_BY_DECISION` | 사용자 결정으로 수행하지 않고 종료했다. 실패·데이터 부족·미완료 항목이 아니다. |
| V2 개선 연구 전체 | `A_FAST_CORE_V2_IMPROVEMENT_RESEARCH_CLOSED` | 같은 정보셋을 사용한 V2 미세조정을 종료한다. |

## V2.1 Candidate 최종 근거

5-window simple 비교에서는 가장 깊은 손실 꼬리의 감소가 일부 반복됐지만, 평균 수익과 중간 손실 구간의 개선은 일관되지 않았다. 독립적인 승격 근거가 부족하다. 후속 realistic portfolio 결과도 다음과 같이 일관된 계좌 개선을 보이지 않았다.

- P2-1: 실질적 동률
- P2-2: Candidate가 명확히 악화
- P3-2: 실질적 동률

1조 원 이상 PIT 시가총액과 survivor-only 현실 유니버스에서는 V2.1이 겨냥한 extreme deep-loss 문제가 simple 분석보다 크게 줄었다. Candidate의 tail-control 장점이 계좌 성과로 연결되지 않아 `V2_1_PROMOTION_NOT_SUPPORTED_BY_REALISTIC_PORTFOLIO_EVIDENCE`로 판정한다. 추가 V2.1 검증 백테스트는 수행하지 않는다.

## Exit4 연구 종료

현재 규칙인 Pattern A Score의 PROGRESSED high-watermark 대비 `15pt` 하락 청산을 유지한다. 기존 분석에서 Exit4 제거 또는 지연은 profit preservation을 악화시켰고, T10/T15/T20/T25 sensitivity에서 T15가 가장 견고했다. T10 realistic portfolio 비교는 P2-1/P2-2에서 악화되고 P3-2에서 개선되어 계좌 성과 방향이 혼합됐으며, 승률의 일관된 개선이나 자본 회전의 일관된 계좌 성과 연결도 확인되지 않았다.

최종 판정은 `MIXED_NO_CLEAR_PORTFOLIO_WINNER`다. Exit4 15pt는 유지하고 threshold sweep 및 추가 T10/T20/T25 재시험은 종료한다.

## Exit3 Coverage Extension 연구 종료

실험은 Exit4 15pt, 기존 진입과 Loss Guard를 유지한 채 holding-lifecycle C1의 첫 PROGRESSED departure에 Exit3를 확대했다. realistic portfolio 최종자산은 P2-1과 P3-2에서 개선되고 P2-2에서 악화됐다. deep-loss tail rescue는 있었지만 C1 subset의 median return, realized return, win rate는 전반적으로 악화됐으며 winner damage와 deep-loss rescue가 상쇄되는 구조였다.

따라서 PROGRESSED departure는 위험 신호지만 즉시 전량청산 신호로는 충분하지 않다고 판단한다. 최종 판정은 `MIXED_NO_CLEAR_WINNER`, 상태는 `EXIT3_COVERAGE_EXTENSION_NOT_PROMOTED_RESEARCH_CLOSED`다. Production 반영은 없다.

세 구간의 계좌 비교와 검증 자료는 [Exit3 Coverage Extension realistic portfolio report](../../../../artifacts/patterns/pattern_a_fast/research/exit3_coverage_extension_realistic_v01/run_20260927_exit3_coverage_extension_realistic_v01/final_report.md)에 보존되어 있다.

## Lifecycle 연구의 최종 해석

1. 현재 V2 진입 조건을 별도로 수정할 근거는 확인하지 못했다.
2. 보유 중 직접 `EARLY_TREND → PROGRESSED` 경로는 강한 사후 품질 신호다.
3. 이 경로는 진입 뒤에야 알 수 있는 미래 정보이므로 직접적인 진입 규칙으로 사용할 수 없다.
4. 진입 시 Pattern A / FAST score는 strict PASS를 유의미하게 예측하지 못했다.
5. `PROGRESSED` departure는 tail risk 증가 신호지만 단독 전량청산 신호로는 과도하다.
6. 현재 정보셋에서 추가 V2 미세조정은 기대 수익 개선보다 과최적화 위험이 커졌다.

## EARLY_TREND-only 결정

`NOT_RUN_BY_DECISION` 상태로 종료한다. 오류나 데이터 부족으로 중단한 것이 아니며, 같은 정보셋에서 추가 미세조정의 기대값이 낮다는 판단에 따라 실행하지 않았다. 미완료 연구 항목으로 남기지 않는다.

## 종료 범위와 이후 방향

- A FAST Core V2를 유지하고 V2.1 Candidate는 채택하지 않는다.
- Exit4 15pt를 유지하고 Exit3 Coverage Extension은 채택하지 않는다.
- 동일한 정보셋을 활용한 feature, lifecycle, threshold 기반 V2 미세조정 연구를 종료한다.
- 기존 결과와 산출물은 삭제·이동·재생성하지 않고 연구 이력으로 보존한다.
- 차후 개선은 새로운 정보 또는 새로운 전략 틀에서 시작한다. 본 종료 기록은 새 백테스트나 전략 변경을 승인하지 않는다.

## 보존된 연구·검증 산출물

아래 원본 기록과 산출물은 그대로 보존한다. 이 종료 문서는 상태와 최종 해석만 색인한다.

| 연구 묶음 | 보존 위치 |
|---|---|
| V2.1 simple / 5-window | [5-window synthesis](../strategy/FAST_CORE_V2_NEG40_WEAK_PROTECT_5_WINDOW_SYNTHESIS_V01.md), `artifacts/backtests/p1_neg40_weak_protect_v01/`, `artifacts/backtests/p2_1_neg40_weak_protect_v01/`, `artifacts/backtests/p2_2_neg40_weak_protect_v01/`, `artifacts/backtests/p3_1_neg40_weak_protect_v01/`, `artifacts/backtests/p3_2_neg40_weak_protect_v01/` |
| V2.1 realistic portfolio | `artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/`, `artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/`, `artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/` |
| Lifecycle / A vs C1 / counterfactual | `artifacts/patterns/pattern_a_fast/research/lifecycle_refinement_strict_handoff_v01/`, `a_vs_c1_divergence_v01/`, `departure_cf_weak_scale_v01/` |
| Exit4 effectiveness / threshold sensitivity / T10 realistic | `artifacts/patterns/pattern_a_fast/research/exit4_effectiveness_v01/`, `exit4_threshold_sensitivity_v01/`, `exit4_t10_realistic_portfolio_v02/` |
| Exit3 Coverage Extension realistic | `artifacts/patterns/pattern_a_fast/research/exit3_coverage_extension_realistic_v01/run_20260927_exit3_coverage_extension_realistic_v01/` |
