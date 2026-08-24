opendart_fundamentals_v01_assessment_fix02.md

======================================================================
OpenDART Fundamentals Assessment V01 FIX02
======================================================================

목적
----------------------------------------------------------------------
FIX01의 Assessment 판정 오류를 보정한다. 입력 경계는
DerivedMetricsBuild -> Assessment로 유지하고, upstream OpenDART Core,
FilingRegistry, PITResolver, XBRL Repository, Periodization,
canonical duplicate collapse, Derived Metrics semantics는 변경하지 않는다.

5년 current 입력
----------------------------------------------------------------------
1. build_current() 기본 lookback은 5년이다.
2. requested_as_of=2026-08-20의 current fiscal-year window는
   2022, 2023, 2024, 2025, 2026이다.
3. 호출자가 3 또는 7년 lookback을 명시하면 해당 범위를 사용한다.
4. currentness/PIT cutoff는 기존 규칙대로 요청일 이후 source를 금지한다.

동일 기간 YoY 시계열
----------------------------------------------------------------------
1. revenue, operating_income, net_income, operating_cash_flow를
   fiscal period별로 묶어 같은 기간 YoY point를 만든다.
2. Q1/Q2/Q3/Q4는 QUARTERLY_YOY, FY는 ANNUAL_YOY로 고정한다.
3. 입력 순서와 무관하게 fiscal year를 정렬하고, 누락 point는 숫자 0으로
   대체하지 않는다.
4. 최신 fiscal year부터 연속인 READY suffix만 trend 입력으로 사용한다.
5. 연속 READY point가 3개 미만이면 INSUFFICIENT_DATA다.
6. 결과와 point에는 resolution status, PIT available date, rcept_no,
   rcept_dt, source sha256 provenance를 보존한다.

Multi-year trend 상태
----------------------------------------------------------------------
1. ACCELERATING: 연속 delta가 모두 양수다.
2. DECELERATING: 연속 delta가 모두 음수다.
3. REVERSING_UP/DOWN: 같은 방향 delta가 2회 이상 누적된 뒤 최신 구간에서
   반대 방향으로 전환한다.
4. STABLE: 모든 delta가 허용 오차 안에 있다.
5. MIXED: 위의 단일 추세 또는 reversal 규칙으로 설명되지 않는다.
6. 데이터가 부족하면 INSUFFICIENT_DATA다.

LEVEL과 DIRECTION 분리
----------------------------------------------------------------------
1. LEVEL selector는 현재 YoY, 현재 margin, TTM level만 읽는다.
2. LEVEL selector는 acceleration, multi-year trend, streak, transition,
   margin trend, LOSS narrowing/widening을 읽지 않는다.
3. DIRECTION selector는 short-term acceleration/transition, margin
   expansion, OCF trend, multi-year trend를 component 단위로 읽는다.
4. current YoY sign, TTM YoY sign, positive streak만으로 direction을
   만들지 않는다.
5. growth/profitability/cash-flow별 DirectionComponent를 보존하고
   IMPROVING, STABLE, DETERIORATING, MIXED, UNAVAILABLE로 명시적으로
   aggregate한다. 마지막 입력이 판정을 덮어쓰지 않는다.

Assessment 결과와 회귀
----------------------------------------------------------------------
1. FundamentalsAssessmentResult는 same_period_yoy_series,
   direction_components, short_term_directions, multi_year_directions,
   multi_year_trends를 직렬화한다.
2. 현대모비스 회귀에서 현재 OCF YoY 음수와 OCF trend/margin contraction이
   TTM OCF YoY 양수만으로 IMPROVING으로 뒤집히지 않아야 한다.
3. 같은 데이터의 입력 순열은 결과와 component 순서에 영향을 주지 않는다.
4. 금융회사 086790은 기존 FINANCIAL_PROFILE_NOT_IMPLEMENTED 규칙에 따라
   NOT_APPLICABLE로 유지한다.

검증 산출물
----------------------------------------------------------------------
artifacts/fundamentals/opendart/validation/assessment_v01_fix02/
  assessment_fix02_summary.json
  assessment_fix02_manifest.json
  five_year_window_validation.json
  multi_year_yoy_trend_validation.json
  level_direction_separation_validation.json
  direction_component_validation.json
  direction_order_invariance_validation.json
  production_current_assessment_validation.json
  production_current_assessment_table.csv
  production_multi_year_yoy_table.csv
  historical_pit_regression.json
  assessment_provenance_validation.json
  network_audit.json
  financial_not_applicable_validation.json

네트워크와 테스트 정책
----------------------------------------------------------------------
1. PyKRX/KRX 신규 요청은 금지하며 network_audit에서 0이어야 한다.
2. OpenDART는 --hydrate를 명시한 경우에만 cache-first로 누락
   filing/XBRL을 보충한다.
3. FIX02 OpenDART hydration 상한은 80회이며, 상한 도달 후 재시도하지
   않는다. hydration 후 최종 client-less replay 요청은 0이어야 한다.
4. Full Repo Suite는 이 작업 범위에서 실행하지 않는다. 지정 targeted
   suite는 PASS여야 한다.
5. API key, raw URL, raw XBRL/ZIP은 산출물과 Git 추적 대상에 쓰지 않는다.

완료 상태
----------------------------------------------------------------------
READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ASSESSMENT_V01_FIX02_REVIEW는
5년 window, same-period series/trend, LEVEL/DIRECTION contamination,
component overwrite/order, PIT/provenance, dependency, targeted test,
OpenDART budget/replay, PyKRX/KRX 0 gate를 모두 만족할 때만 사용한다.
Developer는 ASSESSMENT_V01 = CLOSED를 선언하지 않는다.
