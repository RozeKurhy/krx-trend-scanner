opendart_fundamentals_v01_assessment_fix01.md

======================================================================
OpenDART Fundamentals Assessment V01 FIX01
======================================================================

목적
----------------------------------------------------------------------
Derived Metrics 결과만 입력으로 받아 종목의 펀더멘털 상태와 방향을
결정한다. 이 문서는 currentness, FY/Q4 anchor, level/direction 분리,
rule candidate 진단과 historical PIT 검증 기준을 고정한다.

입력 경계
----------------------------------------------------------------------
1. Assessment 엔진의 입력은 DerivedMetricsResult 또는 DerivedMetricsBuild다.
2. raw XBRL, filing registry, 가격, PyKRX/KRX, Pattern A와 직접 연결하지 않는다.
3. 명시적 fiscal-year range는 EXPLICIT_RANGE/RANGE_ONLY다.
4. 현재 평가 경로는 build_current()를 통해 요청 연도의 Y-2..Y를 입력하고
   CURRENT_AS_OF/VERIFIED를 확인한다.

Currentness와 period anchor
----------------------------------------------------------------------
1. requested_as_of=2026-08-20이면 current fiscal years는 2024, 2025, 2026이다.
2. current 입력에 요청 연도가 없으면 STALE_INPUT_RANGE와 INPUT_NOT_READY다.
3. fiscal period 순서는 Q1 < Q2 < Q3 < Q4 < FY다.
4. FY가 존재하면 Q4와 충돌하지 않고 FY를 current anchor로 선택한다.
5. 같은 입력을 순서만 바꿔 평가한 결과는 동일해야 한다.

Level와 Direction
----------------------------------------------------------------------
1. level은 GROWTH/PROFITABILITY/CASH_FLOW의 현재 상태다.
2. direction은 각 축의 IMPROVING/STABLE/DETERIORATING/UNAVAILABLE다.
3. 양(+)의 level 하나만으로 IMPROVING을 만들지 않는다.
4. growth acceleration/streak/transition, margin expansion,
   OCF trend/TTM OCF 변화만 방향 근거로 사용한다.

Overall rule
----------------------------------------------------------------------
1. TURNAROUND: LOSS_TO_PROFIT + 독립적인 improving direction 1개 이상이며
   severe cash deterioration이 없다.
2. WEAK: negative level 축 3개 이상 또는 PROFIT_TO_LOSS와 negative level
   2개 이상이다.
3. WEAKENING: deteriorating direction 축 2개 이상이며 WEAK가 아니다.
4. STRONG: 세 core level이 positive/strong이고 critical transition,
   broad deterioration, momentum 감속이 없다.
5. IMPROVING: improving direction 축 2개 이상, deteriorating 2개 미만,
   negative level 2개 미만이며 cash-flow level이 weak가 아니다.
6. TURNAROUND와 IMPROVING만 문서화된 candidate overlap이다. 그 밖의
   mutually-exclusive overlap은 conflict로 기록한다.

검증 산출물
----------------------------------------------------------------------
artifacts/fundamentals/opendart/validation/assessment_v01_fix01/
  assessment_fix01_summary.json
  assessment_fix01_manifest.json
  synthetic_directional_validation.json
  currentness_validation.json
  period_anchor_determinism_validation.json
  production_current_assessment_validation.json
  production_current_assessment_table.csv
  historical_pit_assessment_validation.json
  historical_pit_assessment_table.csv
  rule_candidate_validation.json
  rule_conflict_validation.json
  assessment_provenance_validation.json
  network_audit.json
  financial_not_applicable_validation.json

네트워크와 캐시 정책
----------------------------------------------------------------------
1. PyKRX/KRX 신규 요청은 금지하며 network_audit에서 0이어야 한다.
2. OpenDART는 --hydrate를 명시한 경우에만 cache-first로 누락 filing/XBRL을
   보충한다.
3. OpenDART 요청은 최대 60회다. 상한 도달 후 재시도하지 않는다.
4. API key, raw URL, raw XBRL/ZIP은 산출물과 Git 추적 대상에 쓰지 않는다.

완료 상태
----------------------------------------------------------------------
READY_FOR_ARCHITECT_OPENDART_FUNDAMENTALS_ASSESSMENT_V01_FIX01_REVIEW는
current ready/verified, historical ready, PIT/provenance 0, rule conflict 0,
targeted tests PASS, dependency 0, PyKRX/KRX 0, OpenDART request <=60을
모두 만족할 때만 사용한다. Developer가 CLOSED를 선언하지 않는다.
