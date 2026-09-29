# KRX ETF official representative universe refinement V04

- Verdict: **ETF_OFFICIAL_UNIVERSE_REFINEMENT_V04_COMPLETE**
- V03 selected: 37; V04 selected: 37.
- Healthcare: 244580 KODEX 바이오 → 143860 TIGER 헬스케어.
- Broad healthcare PASSIVE candidates reviewed: 4; selection: Highest V02 40D average trading value among broad healthcare PASSIVE candidates; AUM and listing age break ties.
- Group correction: `GLOBAL_BROAD` → `DEVELOPED_MARKETS`; ticker remains `251350`.
- All other non-HEALTHCARE tickers and stored market figures match V03 exactly.
- Authority unchanged: 2026-09-23; 40D 2026-07-29 through 2026-09-23 (40 sessions). Refetches: 0; metric recomputations: 0.
- V02/V03 input files unchanged by generation: `True`.

## Validation

- `v03_selected_count_37`: `True`
- `v04_selected_count_37`: `True`
- `healthcare_representative_is_broad_passive`: `True`
- `selected_active_etf_count_zero`: `True`
- `healthcare_biotech_only_representative_count_zero`: `True`
- `global_broad_group_count_zero`: `True`
- `developed_markets_group_count_one`: `True`
- `developed_markets_ticker_251350`: `True`
- `all_non_healthcare_tickers_unchanged`: `True`
- `market_reference_date_unchanged`: `True`
- `40D_window_unchanged`: `True`
- `40D_session_count_unchanged`: `True`
- `market_refetch_count_zero`: `True`
- `40D_metric_recomputation_count_zero`: `True`
- `market_metric_source_mismatch_count_zero`: `True`
- `hard_filter_violation_count_zero`: `True`
- `duplicate_representative_group_count_zero`: `True`
- `parent_child_overlap_violation_count_zero`: `True`
- `unknown_selected_classification_count_zero`: `True`
- `v02_v03_input_artifacts_unchanged`: `True`

## Artifacts

- `official_representative_etf_universe_v04.csv`
- `healthcare_candidate_audit.csv`
- `changes_from_v03.csv`
- `validation.json`
