opendart_fundamentals_v01_assessment_fix03.md

======================================================================
OpenDART Fundamentals Assessment V01 FIX03
======================================================================

목적
----------------------------------------------------------------------
FIX02의 Closure 전 결함 세 가지를 수정한다.

1. MIXED DirectionComponent를 directional abstention으로 취급한다.
2. Direction selector와 DirectionComponent의 Evidence axis를 일치시킨다.
3. 과거 reversal이 아닌 최신 delta regime만 REVERSING으로 분류한다.

변경 경계
----------------------------------------------------------------------
OpenDART Core, Corp Code semantics, FilingRegistry, PITResolver, XBRL
Repository, Periodization, canonical duplicate collapse, Derived Metrics,
5Y default, same-period series, LEVEL/DIRECTION separation,
DirectionComponent model, PIT provenance, CURRENT_AS_OF/EXPLICIT_RANGE는
변경하지 않았다. 새 accounting metric이나 Score/Valuation/Pattern A/RS도
추가하지 않았다.

MIXED aggregation contract
----------------------------------------------------------------------
I=IMPROVING, D=DETERIORATING, M=MIXED, S=STABLE, U=UNAVAILABLE component
count를 사용한다.

I>0이고 D=0이면 M과 무관하게 IMPROVING이다.
D>0이고 I=0이면 M과 무관하게 DETERIORATING이다.
I>0이고 D>0이면 MIXED다.
I=D=0이고 M>0이면 MIXED다.
I=D=M=0이고 S>0이면 STABLE, 모두 없으면 UNAVAILABLE이다.

axis별 component count와 direction_aggregation_rule_id를 diagnostics에
보존하고 mixed_component_unconditional_veto_count를 실제로 계산한다.

Evidence / Component axis
----------------------------------------------------------------------
Growth Direction authority는 revenue, operating_income, net_income의
short-term acceleration/transition만 사용한다.

Cash Flow Direction authority는 operating_cash_flow의 short-term
acceleration, short-term trend, margin direction, multi-year trend를
사용한다. 따라서 OCF YOY_GROWTH_ACCELERATION의 Evidence와 Component는
모두 CASH_FLOW axis다.

evidence_component_axis_mismatch_count는 실제 Evidence/Component 연결을
비교해 계산하며 0이어야 한다.

Latest-regime reversal
----------------------------------------------------------------------
stable delta를 제외하고 최신 delta의 same-sign run을 뒤로 센다.

최신 run이 2개 이상이면 양수는 ACCELERATING, 음수는 DECELERATING이다.
최신 run이 1개이고 직전 반대 방향 run이 2개 이상이면 REVERSING_UP 또는
REVERSING_DOWN이다. 그 외에는 MIXED다. 3 READY point 미만은 기존대로
INSUFFICIENT_DATA다.

검증 산출물
----------------------------------------------------------------------
artifacts/fundamentals/opendart/validation/assessment_v01_fix03/
  assessment_fix03_summary.json
  assessment_fix03_manifest.json
  direction_aggregation_validation.json
  mixed_component_veto_validation.json
  evidence_axis_alignment_validation.json
  latest_regime_reversal_validation.json
  direction_order_invariance_validation.json
  production_current_assessment_validation.json
  production_current_assessment_table.csv
  production_fix02_fix03_comparison.csv
  historical_pit_regression.json
  assessment_provenance_validation.json
  network_audit.json
  financial_not_applicable_validation.json

네트워크와 provenance
----------------------------------------------------------------------
1. FIX03은 CACHE_ONLY로 실행하며 OpenDART 신규 hydration은 하지 않는다.
2. hydration_run_request_count와 final_replay_request_count를 분리해
   기록한다. 이번 실행 값은 각각 0이다.
3. PyKRX/KRX 신규 요청은 0이다.
4. summary/manifest에는 start_head, implementation_head,
   validation_source_head를 기록한다. implementation_head와
   validation_source_head는 Commit A SHA다.
5. Commit B가 artifact를 저장하며 END HEAD는 Commit B SHA다.

완료 상태
----------------------------------------------------------------------
READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ASSESSMENT_V01_FIX03_REVIEW는
MIXED veto, Evidence axis mismatch, stale reversal, contamination,
overwrite/order, PIT/provenance, rule, dependency, test, cache-only
network gate가 모두 0/PASS일 때만 사용한다.

Developer는 ASSESSMENT_V01 = CLOSED를 선언하지 않는다.
