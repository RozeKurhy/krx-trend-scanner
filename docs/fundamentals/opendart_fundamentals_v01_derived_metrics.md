opendart_fundamentals_v01_derived_metrics.md

==================================================
OPENDART Fundamentals V01 - Derived Metrics
==================================================

목적
--------------------------------------------------
PeriodizationResult가 제공하는 canonical financial observations만 사용해
분기/연간 성장률, TTM, 마진과 추세 지표를 계산한다.

이번 단계의 범위
--------------------------------------------------

+------------------------------+------------------------------------------+
| 영역                         | 구현 결과                               |
+------------------------------+------------------------------------------+
| Quarterly YoY / Annual YoY   | 전년 동일 분기 또는 FY 대비 %           |
| 성장 alias                   | revenue, operating income, net income,  |
|                              | operating cash flow                     |
| TTM / TTM YoY                | 인접한 4개 standalone quarter 합계/비교 |
| 마진                         | operating, net income, OCF / revenue   |
| 이익 상태                    | 적자/흑자 전환, 축소·확대, 성장·감소    |
| OCF 추세                     | YoY 성장률의 개선/악화/보합             |
| 연속 성장                    | 양의 YoY 성장 연속 횟수                 |
| YoY 가속                     | 직전 분기 YoY 대비 percentage-point 차 |
| Margin expansion trend       | 전년 동일 기간 margin 변화와 분류       |
+------------------------------+------------------------------------------+

입력 및 아키텍처 경계
--------------------------------------------------

허용된 입력은 아래 두 가지뿐이다.

- PeriodizationResult
- PeriodizedFinancialObservation iterable

구현 모듈은 OpenDART API, XBRL parser, FilingRegistry, PITResolver를
import하거나 호출하지 않는다.

허용 흐름:

OpenDART
    |
FilingRegistry
    |
PITResolver
    |
XBRL
    |
PeriodizationProvider
    |
PeriodizationResult / PeriodizationBuild
    |
DerivedMetricsEngine

DerivedMetricsEngine은 위 흐름의 마지막 경계에서만 동작한다. Score,
Pattern A Score 결합, valuation, Stock Report 연결은 구현하지 않았다.

정합성 및 fail-closed 정책
--------------------------------------------------

01. periodization status가 READY가 아니거나 값이 없으면 0으로 대체하지
    않고 DATA_UNAVAILABLE을 반환한다.
02. prior 값이 0이면 성장률/TTM YoY를 계산하지 않고 DATA_UNAVAILABLE을
    반환한다.
03. 동일 EOD에 서로 다른 anchor가 남으면 해당 기간을 모호한 상태로 둔다.
04. TTM은 4개의 인접한 standalone quarter가 모두 READY인 경우에만
    계산한다.
05. 모든 파생 관측값은 원본 rcept_no, rcept_dt, sha256 provenance를
    함께 전달한다.
06. margin expansion은 전년 동일 fiscal period와 비교하며 값은
    percentage points, metadata.classification은 EXPANDING/CONTRACTING/FLAT
    중 하나다.

주요 API
--------------------------------------------------

- DerivedMetricsEngine.derive(source)
- DerivedMetricsEngine.calculate(source)
- DerivedMetricsEngine.compute(source)
- derive_metrics(source)
- calculate_derived_metrics(source)
- DerivedMetricsResult.get(metric, metric_type, fiscal_year, fiscal_period)
- DerivedMetricsResult.filter(...)

검증
--------------------------------------------------

검증 스크립트:

scripts/validate_opendart_derived_metrics.py

검증 방식은 외부 네트워크 없이 synthetic fixture와 기존 FIX05 local
period context matrix를 DerivedMetricsEngine에 입력하는 것이다.

- 지정 테스트: 117 passed
- synthetic: Quarterly/Annual YoY, TTM, transition, acceleration,
  provenance, zero-prior fail-closed PASS
- local cohort: 3 ticker, 83 canonical observations, 404 derived observations
- network_request_count: 0
- pykrx_krx_network_request_count: 0
- full repo suite: 이번 작업 범위에서 실행하지 않음

산출물
--------------------------------------------------

- artifacts/fundamentals/opendart/validation/derived_metrics/
  - derived_metrics_summary.json
  - derived_metrics_manifest.json
  - synthetic_derived_metrics_validation.json
  - live_derived_metrics_validation.json

다음 단계
--------------------------------------------------

Architect review 후에만 Fundamentals Score 또는 Pattern A 연계를 별도
작업으로 검토한다. 해당 작업은 이 단계 산출물의 책임 범위가 아니다.
