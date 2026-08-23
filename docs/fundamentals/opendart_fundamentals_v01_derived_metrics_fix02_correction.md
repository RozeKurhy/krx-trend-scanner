opendart_fundamentals_v01_derived_metrics_fix02_correction.md

==================================================
OPENDART Fundamentals V01 - FIX02 Validation Correction
==================================================

목적
--------------------------------------------------

FIX02의 계산·Periodization·PIT semantics는 변경하지 않고 validation
authority와 production evidence만 보완한다.

수정 범위
--------------------------------------------------

- basis/currency adversarial target의 실제 status/value를 측정한다.
- target이 없으면 PASS가 아니라 MISSING_TARGET/FAIL이다.
- final gate는 basis_status/currency_status와 violation count를 모두 요구한다.
- summary와 measured/artifact count를 비교하고 불일치를 gate에서 차단한다.
- historical materialization은 method 문자열이 아니라 current anchor,
  fact identity, historical-only identity와 canonical anchor의 교집합으로
  측정한다. historical prior가 derived source에 포함되는 것은 허용한다.
- 실제 production provider path만 TTM margin evidence로 인정한다.

Production TTM margin evidence
--------------------------------------------------

기존 005930, 237690, 086790 cohort는 그대로 유지한다. 추가 후보는
005380, 000660, 035420, 068270, 012330으로 고정하고 최대 5개까지만
cache-first로 시도한다. 후보는 NON_FINANCIAL, Q1~Q4 revenue와 numerator가
모두 READY이고 basis/currency가 일치하며 revenue 합계가 양수인 경우에만
선정한다.

선정된 READY TTM margin은 canonical Q1~Q4 값으로 별도 재계산한다.

sum(numerator Q1:Q4) / sum(revenue Q1:Q4) * 100

derived 값과의 차이가 1e-9 초과이면 evidence로 인정하지 않는다. source
receipt/date/hash 배열과 8개 numerator/revenue quarter provenance도 함께
검증한다.

Production blocker 정책
--------------------------------------------------

same-EOD/context ambiguity를 완화하거나 winner를 임의로 고르지 않는다.
후보군에서도 실제 TTM margin evidence가 없으면
BLOCKED_PRODUCTION_TTM_EVIDENCE를 유지한다.

산출물
--------------------------------------------------

artifacts/fundamentals/opendart/validation/derived_metrics_fix02_correction/

- derived_metrics_fix02_correction_summary.json
- derived_metrics_fix02_correction_manifest.json
- measured_invariants_validation.json
- coherence_validation.json
- summary_consistency_validation.json
- historical_materialized_exclusion_validation.json
- production_derived_provider_validation.json
- production_ttm_validation.json
- production_ttm_margin_validation.json
- production_ttm_margin_diagnostics.json
- production_future_leakage_validation.json
- pit_metadata_validation.json
- derived_provenance_validation.json
- live_derived_metrics.csv

네트워크·보안
--------------------------------------------------

PyKRX/KRX 요청은 0이다. OpenDART는 cache-first이며 후보군 때문에 필요한
경우에만 bounded 요청을 한다. API key, env 파일, raw ZIP/XML은 커밋하지
않고 secret_leak_count와 raw_source_committed를 실제 검사한다.

동시성 상태
--------------------------------------------------

DerivedMetricsEngine의 기존 KNOWN_MINOR_CONCURRENCY_STATE는 이번 correction
범위 밖 maintenance backlog로 유지한다.
