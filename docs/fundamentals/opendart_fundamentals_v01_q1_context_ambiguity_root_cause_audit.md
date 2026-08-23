opendart_fundamentals_v01_q1_context_ambiguity_root_cause_audit.md

==================================================
Q1 CONTEXT AMBIGUITY ROOT CAUSE AUDIT
==================================================

목적
--------------------------------------------------

Q1 revenue PERIOD_AMBIGUOUS의 원인을 실제 OpenDART XBRL context와
production PeriodizationProvider 경계에서 확인한다.

검증 범위
--------------------------------------------------

- 기존 005930, 237690
- 추가 NON_FINANCIAL 005380, 000660, 035420, 068270, 012330
- 2024년/2025년
- revenue, operating_income, net_income, operating_cash_flow
- Q1 원문 inventory와 Q1/Q2/Q3 구조 비교

결론
--------------------------------------------------

Q1 ambiguity 42건 중 41건은 동일 semantic fingerprint와 동일 값의
중복 context였다. 단 현대자동차 2025 Q1 operating_income 1건은
동일 값이지만 OperatingIncomeLoss와 ProfitLossFromOperatingActivities라는
서로 다른 concept QName을 사용한다.

따라서 전체 cohort를 exact duplicate로 단정하거나 concept alias를 임의로
dedupe할 수 없다. 이번 작업에서는 Periodization production code를 수정하지
않았고 PERIOD_AMBIGUOUS fail-closed 정책을 유지했다.

검증 원칙
--------------------------------------------------

- context_id는 authority로 사용하지 않는다.
- period, basis, currency, entity, dimensions, scenario/segment,
  period semantics와 concept를 fingerprint에 포함한다.
- 값이 같다는 이유만으로 semantic difference를 제거하지 않는다.
- raw XML/ZIP는 ignored cache에만 두고 artifact에는 metadata와 SHA-256만 쓴다.

historical detector
--------------------------------------------------

PeriodizationResult와 DerivedMetricsProvider canonical input 양쪽을 검사한다.
이전 receipt의 historical vintage는 PIT 보존으로 허용하고, current selection이
AMBIGUOUS/MISSING인데 historical filing이 READY current authority로 노출되거나
same-EOD/non-selected filing이 current authority로 쓰이는 경우를 violation으로
판정한다.

positive control violation = 0
negative control detected = 2
production violation = 0

수정 여부
--------------------------------------------------

periodization_change_required = false
production code correction = NOT IMPLEMENTED

Q1 context root cause가 cohort 전체에서 단일 exact duplicate로 증명되지 않았고,
concept QName이 다른 case가 남아 있으므로 winner 선택이나 dedupe는 안전하지 않다.
Architect가 production input limitation과 후속 concept-level 정책을 별도 검토해야 한다.

관련 artifact
--------------------------------------------------

artifacts/fundamentals/opendart/validation/q1_context_ambiguity_audit/

최종 상태
--------------------------------------------------

READY_FOR_ARCHITECT_Q1_CONTEXT_LIMITATION_REVIEW
