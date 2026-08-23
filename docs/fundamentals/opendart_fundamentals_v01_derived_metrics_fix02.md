opendart_fundamentals_v01_derived_metrics_fix02.md

==================================================
OPENDART Fundamentals V01 - Derived Metrics FIX02
==================================================

목적
--------------------------------------------------

FIX01의 derived metric 계산 의미는 유지하면서 검증 경계를 실제
PeriodizationProvider 생산 경계까지 닫는다. 검증기는 fixture의 결과와
실제 OpenDART 생산 결과에서 invariant count를 계산하며, PASS 또는 0을
미리 채워 acceptance를 통과시키지 않는다.

적용 범위와 불변 조건
--------------------------------------------------

+----+----------------------------------------+------------------------------------------+
| ID | 검증 대상                             | FIX02 기준                              |
+----+----------------------------------------+------------------------------------------+
| 01 | ambiguous/mismatch 입력                | READY 파생 결과에 사용된 입력 수 = 0    |
| 02 | basis/currency coherence                | CFS/OFS·통화 혼용 READY 수 = 0           |
| 03 | sign-aware percentage                   | undefined percentage 생성 수 = 0         |
| 04 | revenue margin denominator               | 0 이하 매출의 READY margin 수 = 0        |
| 05 | FINANCIAL margin                        | numeric margin 수 = 0, NOT_APPLICABLE   |
| 06 | TTM YoY provenance                      | READY 결과는 8분기 source triplet        |
| 07 | PIT availability                        | unknown/future PIT는 INPUT_NOT_READY     |
| 08 | production boundary                     | Provider.build -> Engine 실제 호출       |
+----+----------------------------------------+------------------------------------------+

DerivedMetricsEngine 변경
--------------------------------------------------

requested_as_of가 있으면 source의 pit_available_from 또는 anchor receipt가
반드시 존재하고 cutoff 이하여야 한다. 두 날짜가 모두 없으면 숫자가 있어도
PIT_AVAILABILITY_UNKNOWN / INPUT_NOT_READY로 닫는다. 이 규칙은 미래 correction
누출과 최신 snapshot의 역사 시점 오염을 방지한다.

FIX02 테스트
--------------------------------------------------

tests/test_opendart_fundamentals_derived_metrics_fix02.py는 아래 adversarial
cases를 실제 DerivedMetricsEngine 결과로 확인한다.

- sign transition 5종과 growth alias의 numeric percentage 차단
- PERIOD_AMBIGUOUS 및 DIRECT_DERIVED_MISMATCH 입력 차단
- quarterly/annual/TTM/margin basis와 currency mismatch 차단
- 0 또는 음수 revenue margin 차단
- FINANCIAL의 quarterly/TTM margin 명시적 NOT_APPLICABLE
- TTM YoY 8개 source provenance 및 배열 정렬
- PIT future 및 PIT availability unknown fail-closed
- DerivedMetricsProvider의 동일 cutoff·canonical result 경계

실제 생산 검증
--------------------------------------------------

scripts/validate_opendart_derived_metrics_fix02.py --live는 다음 cohort를
cache-first로 호출한다.

- ticker: 005930, 237690, 086790
- fiscal year: 2024, 2025
- requested_as_of: 2026-08-20
- production boundary: 실제 PeriodizationProvider.build 결과만 사용

OpenDART cache가 부족할 때만 bounded 요청을 허용한다. force refresh는
사용하지 않는다. PyKRX/KRX endpoint는 import·호출하지 않으며 full repo
suite는 이 작업 범위에서 실행하지 않고 NOT_RUN_BY_SCOPE로 기록한다.

생산 TTM evidence 정책
--------------------------------------------------

production_ttm_ready_count, production_ttm_yoy_ready_count,
production_ttm_margin_ready_count가 각각 1 이상이어야 production acceptance가
통과한다. 실제 canonical 입력이 ambiguous하면 synthetic fixture를 production
증거로 승격하지 않는다. 하나라도 충족하지 못하면 final_status는
BLOCKED_PRODUCTION_TTM_EVIDENCE로 기록한다.

FINANCIAL branch
--------------------------------------------------

086790 하나금융지주는 FINANCIAL로 분류하고 revenue 기반 quarterly/TTM margin을
value=null, resolution_status=NOT_APPLICABLE로 남긴다. 수치 margin으로 대체하지
않는다.

산출물
--------------------------------------------------

artifacts/fundamentals/opendart/validation/derived_metrics_fix02/ 아래에 다음
파일을 생성한다.

- derived_metrics_fix02_summary.json
- derived_metrics_fix02_manifest.json
- measured_invariants_validation.json
- growth_sign_policy_validation.json
- coherence_validation.json
- pit_metadata_validation.json
- historical_materialized_exclusion_validation.json
- production_derived_provider_validation.json
- production_ttm_validation.json
- production_ttm_margin_validation.json
- production_future_leakage_validation.json
- derived_provenance_validation.json
- live_derived_metrics.csv

manifest에는 각 파일 SHA-256, OpenDART 요청 회계, PyKRX/KRX 요청 수,
secret leak 및 raw source commit 여부를 기록한다. API key와 ZIP/XML 원문은
커밋하지 않는다.

알려진 제한
--------------------------------------------------

DerivedMetricsEngine은 현재 derive 호출 단위의 requested_as_of 상태를
인스턴스 필드에 보관한다. 결과 값과 PIT gate는 검증되지만 동일 engine
인스턴스를 여러 스레드가 동시에 호출하는 계약은 아직 보장하지 않으며,
summary에는 KNOWN_MINOR_CONCURRENCY_STATE로 기록한다.

완료 기준
--------------------------------------------------

- targeted test가 PASS이고 FIX02 테스트가 포함된다.
- critical invariant count가 모두 실제 scan 결과 0이다.
- production source future leakage와 provider cutoff mismatch가 0이다.
- TTM 세 evidence gate가 충족되거나, 불가능한 경우
  BLOCKED_PRODUCTION_TTM_EVIDENCE를 숨김없이 기록한다.
- r.md에는 같은 summary와 blocker, 실행한 검증을 기록한다.
