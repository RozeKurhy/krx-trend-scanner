pattern_a_fast_investable_oos_evaluation_v01.md
==================================================
Phase 13J-4 Frozen Investable OOS-B Evaluation
==================================================

1. Scope and integrity
Base commit: 753f7601078aad46e3f3329887e3a9c60203bea7
Population: 36 frozen Investable OOS-B samples. HIERARCHICAL_V01 and frozen Pattern A were evaluated with local cached OHLCV only; network market requests=0 and retuning=false.
Human review SHA-256: c90db38860fc15cfe81eeb4f35e5e7ce0af8bd3c6de1eb1195e9603198d60585
Ground-truth seal SHA-256: c626759b046e4a1bc223685c41c3e9744e5fb989c28dbccdf91f8f3794852689
The evaluator hard-gates the human review, PASS A seal, selection manifest, blind asset manifest, protocol, and review-order mapping before it computes an output. No label, sample, chart, model, or frozen seal was changed.

2. Point-in-time method
At every weekly point, the source daily bars are explicitly truncated at that weekly date before historical snapshot construction. `effective_as_of` must not exceed that date. Fast trigger events are observed only from the frozen reference date; the preceding 104 weeks are used solely to determine prior Pattern A activity. Pairing follows the frozen precedence without new rules.

3. Availability
Stage READY: 36/36 (100.0%). Score UNAVAILABLE: 7/36 (19.4%). Preregistered availability status: PASS.

4. Human outcome and primary score comparison
Outcome distribution: {'GOOD_TRIGGER': 5, 'BORDERLINE_TRIGGER': 7, 'FALSE_TRIGGER': 5, 'TOO_EARLY': 8, 'TOO_LATE': 2, 'TOO_EXTENDED': 3, 'NO_SETUP': 6}.
POSITIVE_STRUCTURE (GOOD_TRIGGER+BORDERLINE_TRIGGER): score n=9, median=73.82. EARLY_OR_NONE (TOO_EARLY+NO_SETUP): score n=12, median=51.935. Minimum group n=5. Primary status: PASS (PREREGISTERED_DIRECTION_GATE). Other outcome groups and GOOD-vs-BORDERLINE are descriptive only in the JSON artifact.

5. Stage comparison
Exact match: 14; rate: 0.3888888888888889; over-call: 15; under-call: 7. Human and model stages are descriptive, using WATCH < SETUP < TRIGGER < TREND < EXTENDED. Human TRIGGER n=0 is preserved and is not treated as an error.

6. Events and lead time
Observed Fast trigger events: 41. Pair-status distribution: {'DATA_UNAVAILABLE': 18, 'SAME_WEEK': 0, 'PATTERN_A_ALREADY_ACTIVE': 13, 'PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT': 4, 'FAST_EARLIER_PATTERN_A_LATER': 2, 'FAST_EVENT_NO_PATTERN_A_CATCHUP': 4}. Clean lead population (FAST_EARLIER_PATTERN_A_LATER): n=2, median weeks=8.5, status=INCONCLUSIVE. A clean-lead n below the preregistered 3 is INCONCLUSIVE, not evidence of no lead.

7. TOO_EARLY diagnostic
TOO_EARLY n=8. Frozen monthly, weekly, and daily component distributions are retained as descriptive diagnostics in the JSON artifact; no threshold/model adjustment was made after ground-truth exposure.

8. Failure and limitation
Hard failures: [] (count=0). Overall OOS-B status: INCONCLUSIVE.
Historical coverage limitation: Local cache is approximately 20 trading years; early 2020 through 2021-H1 history can be insufficient. The frozen 36-sample OOS-B population was not replaced.
