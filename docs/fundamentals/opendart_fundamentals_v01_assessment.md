opendart_fundamentals_v01_assessment.md
==================================================
OpenDART Fundamentals Assessment V01
==================================================

목적
--------------------------------------------------
DerivedMetricsResult 또는 DerivedMetricsBuild를 사람이 검토할 수 있는
상태와 explanation code로 변환한다. Assessment는 Pattern A, RS, 수급,
주가와 독립이며 Fundamentals Score나 랭킹을 생성하지 않는다.

입력 경계
--------------------------------------------------
- 입력 authority: DerivedMetricsResult 또는 DerivedMetricsBuild
- Raw XBRL, PeriodizationFact, OpenDART API 직접 접근 금지
- requested_as_of는 provider build와 정확히 일치해야 한다
- READY evidence의 pit_available_from 및 source receipt date는 cutoff 이내여야 한다
- 최신 period의 metric이 unavailable이면 이전 period로 대체하지 않는다

축
--------------------------------------------------
- GROWTH: revenue/operating income/net income/OCF YoY 및 earnings transition
- PROFITABILITY: operating/net margin, TTM margin, margin expansion
- CASH_FLOW: OCF YoY, OCF margin, TTM OCF, OCF trend
- MOMENTUM: YoY acceleration, positive streak, margin expansion, transition, OCF trend

축 상태
--------------------------------------------------
GROWTH / PROFITABILITY / CASH_FLOW:
STRONG, POSITIVE, MIXED, NEGATIVE, WEAK, UNAVAILABLE

MOMENTUM:
ACCELERATING, IMPROVING, STABLE, DECELERATING, DETERIORATING, UNAVAILABLE

Overall rule precedence
--------------------------------------------------
1. INSUFFICIENT_DATA: 평가 가능한 축이 2개 미만
2. NOT_APPLICABLE: FINANCIAL company family
3. TURNAROUND: LOSS_TO_PROFIT + supporting positive evidence
4. WEAK: 3개 핵심 축의 광범위한 악화 또는 critical loss 전환
5. WEAKENING: 2개 이상 독립 축의 악화
6. STRONG: Growth/Profitability/Cash Flow positive이고 critical risk 없음
7. IMPROVING: 2개 이상 축의 개선, cash deterioration 없음
8. MIXED: 위 조건에 해당하지 않는 충돌 상태

Sign transition
--------------------------------------------------
- LOSS_TO_PROFIT: positive evidence, TURNAROUND 후보
- PROFIT_TO_LOSS: risk evidence
- LOSS_NARROWING: improving evidence
- LOSS_WIDENING: risk evidence
- ZERO_BASE: percentage growth evidence를 만들지 않음

결과와 provenance
--------------------------------------------------
FundamentalsAssessmentResult는 ticker, company family, current fiscal period,
overall/axis state, strengths, risks, evidence, coverage, status,
matched_rule_id, pit_available_from을 보존한다.

각 AssessmentEvidence는 원 Derived Metric의 metric, metric_type, 값,
classification, direction, explanation code, 요청 cutoff, PIT availability,
receipt 번호/일자/hash를 그대로 보존한다.

상태
--------------------------------------------------
- READY: 결정 규칙과 PIT/provenance가 모두 유효
- INPUT_NOT_READY: cutoff 불일치 또는 future/missing PIT provenance
- INSUFFICIENT_DATA: 축 coverage가 최소 기준 미만
- NOT_APPLICABLE: FINANCIAL_PROFILE_NOT_IMPLEMENTED

검증 및 범위
--------------------------------------------------
Assessment V01은 deterministic 상태/evidence만 제공한다. Architect Review 전에는
FUNDAMENTALS_ASSESSMENT_V01 = CLOSED를 선언하지 않는다. Full Repo Suite는
작업 범위에서 실행하지 않으며, cache-only OpenDART validation과 synthetic
scenario를 acceptance authority로 사용한다.
