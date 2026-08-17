# Pattern A Relative Strength Confirmation Infrastructure Validation Report v0.1

- **Requested As Of**: `2026-08-14`
- **Validation Verdict**: `HOLD_RELATIVE_STRENGTH_INFRA`
- **All Dynamic Hard Gates**: `HOLD / GATE_FAILURE`
- **Artifact File**: `pattern_a_relative_strength_features_20260814.csv`

## 1. 10대 Dynamic Hard Gates 평가 요약

| Gate # | Gate 명칭 | 판정 | 주요 세부 내역 |
| :--- | :--- | :--- | :--- |
| Gate 01 | `gate_01_frozen_identity_parity` | ✅ PASS | universe_common_count=2528, raw_candidate_count=180, investable_candidate_count=103 |
| Gate 02 | `gate_02_market_benchmark_source_identity` | ✅ PASS | parquet_exists=True, meta_exists=True, row_count=1276 |
| Gate 03 | `gate_03_pit_no_lookahead_contract` | ✅ PASS | market_index_future_rows=0, stock_future_observations=0, requested_as_of=2026-08-14 |
| Gate 04 | `gate_04_exact_freshness_anchor_contract` | ✅ PASS | market_last_date=2026-08-14, anchor_date_3m=2026-05-14, anchor_date_6m=2026-02-06 |
| Gate 05 | `gate_05_market_benchmark_selection_contract` | ✅ PASS | evaluated_candidates=180, benchmark_mapping_errors=0 |
| Gate 06 | `gate_06_market_rs_arithmetic_parity` | ✅ PASS | verified_investables=103, market_rs_3m_mismatches=0, market_rs_6m_mismatches=0 |
| Gate 07 | `gate_07_sector_mapping_contract` | ❌ FAIL | sector_mapping={...}, sector_index={...} |
| Gate 08 | `gate_08_sector_rs_arithmetic_parity` | ❌ FAIL | candidate_sector_rs_ready=0, candidate_sector_rs_partial=0, candidate_sector_rs_data_unavailable=180 |
| Gate 09 | `gate_09_fail_closed_schema_compatibility` | ✅ PASS | total_required_rs_columns=30, missing_columns_count=0, missing_columns=[] |
| Gate 10 | `gate_10_production_test_suite_pass` | ✅ PASS | exit_code=0, passed=464, failed=0 |

## 2. Universe 및 Candidate 계층 구조 요약

- **Official COMMON Universe Rows**: `2528`
- **Pattern A Raw Candidates (Stage Transition / Early Trend)**: `180`
- **Investable Candidates (Phase 10C Integration)**: `103`
- **Foreign Flow READY Candidates (Phase 11 Integration)**: `176`
- **Market RS READY Candidates (Phase 12 Integration)**: `176`
- **Investable Market RS READY Count**: `103` / 103 (100.0%)

## 3. 103개 Investable 후보군 상대강도(RS) 분포 통계

| Horizon | Count | Mean | Std | Min | Median | Max | Positive Ratio |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| 3M (63D) | 103 | +0.2544 | 0.3446 | -0.2397 | +0.1672 | +1.6782 | 85/103 (82.5%) |
| 6M (126D) | 103 | +0.0051 | 0.5646 | -0.4666 | -0.1838 | +4.1775 | 32/103 (31.1%) |
| 12M (252D) | 103 | -0.3283 | 0.3376 | -0.6686 | -0.4839 | +1.1064 | 17/103 (16.5%) |

## 4. 결론 및 향후 조치

- 본 검증은 `2026-08-14` 기준 KRX 대표 시장 지수(KOSPI 1001, KOSDAQ 2001) 상대강도 산출의 완결성을 입증함.
- Phase 10C Investability(103개) 및 Phase 11 Foreign Flow(103개 READY)의 Frozen Identity와 100% 일치함을 확인.
- **최종 판정**: `HOLD_RELATIVE_STRENGTH_INFRA`
