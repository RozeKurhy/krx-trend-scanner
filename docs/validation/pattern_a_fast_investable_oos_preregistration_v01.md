pattern_a_fast_investable_oos_preregistration_v01.md
==================================================
Phase 13J-1 Investable OOS-B Historical PIT Feasibility Block
==================================================

1. Purpose
Phase 13J는 RESERVED_OOS_A의 재시험이 아니다. reference-time investable universe 안에서 frozen HIERARCHICAL_V01의 Fast relevance를 독립 표본으로 blind human review 하기 위한 단계다. 이 문서는 샘플링 이전 first hard gate의 결과를 기록한다.

2. Why 13J is Needed
RESERVED_OOS_A contained zero Human POSITIVE_STRUCTURE samples and therefore could not evaluate the preregistered score direction.

Investable OOS-B is a new independently frozen sample designed from reference-time investable and Fast-relevant strata without using any future outcome information.

The four Human Positive Anchors are excluded from both sampling and evaluation metrics.

3. Historical Investability PIT Audit
Status: HISTORICAL_INVESTABILITY_PIT_BLOCKED.

Phase10 definition requires market_cap_at_reference >= 100,000,000,000 KRW and avg_trading_value_20d_at_reference >= 300,000,000 KRW. Local raw cache has daily OHLCV and trading_value, so a 20-trading-day value can be calculated where daily history exists. It has neither historical market_cap nor shares_outstanding.

The only local market-cap snapshots are 2025-01-31 and 2026-08-14. Neither is a common 2020 Q1 through 2025 Q2 reference-grid date, and they cannot be substituted for historical reference dates. Current market cap, future shares outstanding, current listing state, and close multiplied by future shares were not used.

4. Reference Date Grid
The 22 calendar-quarter W-FRI candidates are 2020-03-27, 2020-06-26, 2020-09-25, 2020-12-25, 2021-03-26, 2021-06-25, 2021-09-24, 2021-12-31, 2022-03-25, 2022-06-24, 2022-09-30, 2022-12-30, 2023-03-31, 2023-06-30, 2023-09-22, 2023-12-29, 2024-03-29, 2024-06-28, 2024-09-27, 2024-12-27, 2025-03-28, 2025-06-27. The exact label must be the last completed weekly point accepted by build_historical_snapshot, including any holiday fallback.

The full exact grid cannot be derived locally because the inspected raw daily cache begins at 2021-08-17. All 22 calendar candidates also lack a matching local canonical historical market-cap snapshot. This is a second strict-PIT block, not a reason to infer dates or values.

5. Prior Dataset Exclusion, Sampling Strata, and Diversity Constraints
Not executed. No substitute investability proxy, outcome-based selection, hash selection, or quota fill was attempted. Therefore there is no OOS-B sample manifest and no selected ticker to compare with the prior 60-sample dataset or the four positive anchors.

6. Blindness Rules and Human Review Protocol
Not started. No human review sheet, stage chart, outcome chart, machine output exposure, human stage, human outcome, or trigger event was created.

7. Evaluation Preregistration
Not created because no sample can be frozen legally. Frozen HIERARCHICAL_V01, frozen Pattern A, Phase10 thresholds, RESERVED_OOS_A, Phase 13I-2 results, and docs/roadmap.md remain unchanged.

8. Positive Anchor Firewall and No Outcome-Based Sampling
No anchor similarity, human label, future return, forward runup/drawdown, future high/low, or other future-dependent field was used. No OOS evaluation was run.

9. Required Additional Data
Before Phase 13J-1 can continue, the repository must contain a frozen local dataset with, for every common reference-grid date: (1) historical KRX market cap or reference-date shares outstanding, (2) reference-date ticker and market identity, and (3) provenance sufficient to prove the snapshot was available as of that reference date. The missing data must not be fetched during this phase.

10. Limitations
This is not a retrospective historical OOS evaluation because sample selection did not start. A fully prospective claim is not applicable. Historical market-cap PIT feasibility is the blocking dependency.

11. Final Decision
Sample generated: 0. OOS evaluation run: false. Network market request count: 0.

Final status: HISTORICAL_INVESTABILITY_PIT_BLOCKED.

12. Next Step
STOP. Do not create an arbitrary market-cap proxy or begin Phase 13J-2. Resume Phase 13J-1 only after the required frozen historical inputs are supplied locally.
