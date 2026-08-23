opendart_fundamentals_v01_derived_metrics_fix01.md

==================================================
OPENDART Fundamentals V01 - Derived Metrics FIX01
==================================================

목적
--------------------------------------------------

Architect Review에서 확인된 Derived Metrics Major 6건과 Minor 2건을
수정한다. Core와 Periodization의 기존 의미는 변경하지 않는다.

발견사항과 수정 결과
--------------------------------------------------

+----+--------------------------------------+----------------------------------+
| ID | 발견사항                             | FIX01 결과                       |
+----+--------------------------------------+----------------------------------+
| 01 | sign transition에 percentage 생성    | UNDEFINED_BASE로 fail-closed    |
| 02 | production orchestration 부재        | DerivedMetricsProvider 추가     |
| 03 | matrix 재구성이 acceptance 경계      | Provider boundary 검증 추가     |
| 04 | CFS/OFS·currency cross-period 혼용   | BASIS/CURRENCY gate 추가        |
| 05 | TTM YoY provenance가 2개뿐            | current/prior 8분기 추적        |
| 06 | TTM margin 부재                       | 3개 TTM margin 추가              |
| M1 | revenue denominator 음수 허용         | NON_POSITIVE_REVENUE_BASE       |
| M2 | FINANCIAL margin 묵시적 누락          | 명시적 NOT_APPLICABLE           |
+----+--------------------------------------+----------------------------------+

Architecture
--------------------------------------------------

DerivedMetricsEngine은 계속 아래 canonical 경계만 사용한다.

PeriodizationProvider.build()
    |
PeriodizationBuild.result.observations
    |
DerivedMetricsProvider.build()
    |
DerivedMetricsEngine

Engine은 OpenDART API, XBRL parser, FilingRegistry, PITResolver, PyKRX,
KRX를 import하거나 호출하지 않는다. DerivedMetricsProvider도
PeriodizationBuild.facts를 현재 입력으로 사용하지 않고
result.observations만 전달한다.

DerivedMetricsProvider
--------------------------------------------------

- 여러 fiscal_year를 동일 requested_as_of로 PeriodizationProvider.build에
  전달한다.
- canonical_observations는 각 PeriodizationBuild.result.observations의
  합집합이다.
- 반환값 DerivedMetricsBuild에는 ticker, requested_as_of, fiscal_years,
  periodization_builds, canonical_observations, result가 포함된다.
- requested_as_of는 모든 DerivedMetricObservation에 전파된다.

성장률 및 transition 정책
--------------------------------------------------

percentage growth는 prior > 0이고 current >= 0인 경우만 계산한다.

- 100 -> 120: +20%
- 100 -> 50: -50%
- 100 -> 0: -100%
- -100 -> +50: percentage 없음, LOSS_TO_PROFIT
- +100 -> -50: percentage 없음, PROFIT_TO_LOSS
- -100 -> -30: percentage 없음, LOSS_NARROWING
- -30 -> -100: percentage 없음, LOSS_WIDENING
- prior == 0: ZERO_BASE
- current == 0: ZERO_CURRENT

분기 YoY와 Annual YoY는 동일 fiscal period, READY, basis/currency
coherence를 모두 요구한다. 양의 YoY만 streak와 acceleration에 사용한다.

Coherence gate
--------------------------------------------------

- cross-period fs_div_used 불일치: BASIS_MISMATCH
- cross-period currency 불일치: CURRENCY_MISMATCH
- READY가 아닌 canonical 입력: INPUT_NOT_READY
- prior 부재: DATA_UNAVAILABLE
- prior <= 0 또는 current < 0: UNDEFINED_BASE
- FX 변환은 구현하지 않는다.

TTM 정책
--------------------------------------------------

TTM은 연속된 Q1/Q2/Q3/Q4 standalone quarter 4개가 모두 READY이고
basis, currency, identity가 일치할 때만 계산한다.

TTM YoY는 current TTM 4개와 prior-year TTM 4개를 모두 authority로
사용한다. READY 결과의 provenance는 최대 8개 quarter source triplet을
포함한다. TTM margin은 분기 margin 평균이 아니라 다음 방식이다.

sum(numerator 4 quarters) / sum(revenue 4 quarters) * 100

추가 metric type:

- TTM_OPERATING_MARGIN
- TTM_NET_MARGIN
- TTM_OPERATING_CASH_FLOW_MARGIN

Margin 정책
--------------------------------------------------

revenue <= 0이면 margin을 계산하지 않고 UNDEFINED_BASE /
NON_POSITIVE_REVENUE_BASE를 기록한다.

FINANCIAL company의 revenue 기반 margin 및 TTM margin은 observation을
생성하되 value=null, resolution_status=NOT_APPLICABLE,
reason=FINANCIAL_COMPANY_REVENUE_MARGIN_NOT_APPLICABLE로 명시한다.

PIT metadata
--------------------------------------------------

DerivedMetricObservation에는 requested_as_of와 pit_available_from을
추가했다. pit_available_from은 source observations의
pit_available_from 우선, 없으면 anchor_rcept_dt를 사용한 최댓값이다.
READY 결과의 availability가 requested_as_of를 넘으면
FUTURE_DATA_AFTER_REQUESTED_AS_OF로 fail-closed한다.

FIX05 historical source exclusion
--------------------------------------------------

PeriodizationBuild.facts에 historical prior가 materialized되어 있어도
DerivedMetricsProvider는 이를 current canonical input으로 승격하지 않는다.
current 입력은 result.observations에만 한정한다.

검증
--------------------------------------------------

검증 스크립트:

scripts/validate_opendart_derived_metrics_fix01.py

- 대상 테스트: 138 passed
- Engine synthetic: sign policy, transition, TTM, TTM YoY 8-source,
  TTM margin, FINANCIAL NOT_APPLICABLE PASS
- Provider boundary: 3개 종목 x 2024/2025, 동일 requested_as_of PASS
- historical_materialized_as_current_count: 0
- future_correction_leakage: NO
- ambiguous/mismatch/basis/currency input used: 0
- undefined percentage emitted: 0
- financial margin wrongly computed: 0
- TTM YoY incomplete provenance: 0
- source provenance alignment: PASS
- OpenDART/registry/XBRL 신규 요청: 0
- PyKRX/KRX 요청: 0
- Full Repo Suite: NOT_RUN_BY_SCOPE

live cohort 검증은 기존 FIX05 local matrix를 fixture adapter로 사용해
DerivedMetricsProvider.build 경계를 검증했다. 이 CSV 재구성은 raw-source
acceptance authority가 아니며, acceptance authority는 Provider boundary
및 canonical result 경계다.

산출물
--------------------------------------------------

artifacts/fundamentals/opendart/validation/derived_metrics_fix01/

- derived_metrics_fix01_summary.json
- derived_metrics_fix01_manifest.json
- growth_sign_policy_validation.json
- derived_provider_validation.json
- historical_materialized_exclusion_validation.json
- coherence_validation.json
- ttm_provenance_validation.json
- ttm_margin_validation.json
- pit_snapshot_validation.json
- live_company_derived_summary.json
- live_derived_metrics.csv
- derived_provenance_validation.json

제외 범위 및 한계
--------------------------------------------------

- Early Earnings / Preliminary Earnings는 후속 layer다.
- QoQ, Fundamentals Score, composite grade, Pattern A/A FAST,
  Investability, Foreign Flow, RS, Stock Report, valuation, PER/PBR/
  EV/EBITDA/PEG/ROE/ROA/debt ratio는 구현하지 않는다.
- 실제 OpenDART live refresh는 이번 검증에서 수행하지 않았다. 기존
  local fixture와 stub PeriodizationProvider로 네트워크 없는 acceptance를
  수행했다.
