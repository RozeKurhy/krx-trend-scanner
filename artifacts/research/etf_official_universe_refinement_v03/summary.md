# KRX ETF current representative universe refinement V03

- Verdict: **ETF_OFFICIAL_UNIVERSE_REFINEMENT_V03_COMPLETE**
- V02 representatives: 39; V03 representatives: 37
- Authority unchanged: market reference 2026-09-23; 40D 2026-07-29 through 2026-09-23 (40 sessions)
- Market data refetches: 0; 40D metric recomputations: 0. All market figures were copied from the committed V02 selected/candidate rows.
- ACTIVE representatives excluded and replaced: 462900 KoAct 바이오헬스케어액티브 → 244580 KODEX 바이오
- Parent groups removed: FINANCIALS (139270 TIGER 200 금융); INFORMATION_TECHNOLOGY (139260 TIGER 200 IT)
- Retained child groups: `BANK, SECURITIES, INSURANCE, SEMICONDUCTOR, SOFTWARE`
- V02 input artifact SHA-256 hashes match before and after generation: `True`

## Validation

- `reference_date_unchanged`: `True`
- `40D_window_unchanged`: `True`
- `40D_session_count_unchanged`: `True`
- `market_data_refetch_count_zero`: `True`
- `40D_metric_recomputation_count_zero`: `True`
- `selected_active_etf_count_zero`: `True`
- `selected_hard_filter_violation_count_zero`: `True`
- `duplicate_representative_group_count_zero`: `True`
- `parent_child_overlap_violation_count_zero`: `True`
- `unknown_selected_classification_count_zero`: `True`
- `v02_source_raw_figures_unchanged`: `True`
- `v02_market_metrics_copied_exactly`: `True`
- `v03_count_matches_expected_scope`: `True`
- `selected_ticker_count_unique`: `True`

## Audit files

- `changes_from_v02.csv`: one row per V02 selected representative, including unchanged, replaced, and removed rows.
- `active_exclusion_audit.csv`: ACTIVE removals and passive replacements.
- `sector_overlap_audit.csv`: explicit finance/IT parent removals and other reviewed adjacent groups.
