pattern_a_fast_phase_13_final_synthesis_v01.md
==================================================
Phase 13 Final Research Closure
==================================================

1. Final status
Research status: PHASE_13_RESEARCH_CLOSED.
HIERARCHICAL_V01 production status: HIERARCHICAL_V01_PRODUCTION_HOLD.

The HOLD is not a post-hoc rejection or a model change. Frozen Investable OOS-B passes the preregistered score-direction and availability gates, with no hard failure, but the frozen clean lead-time population is n=2 while the protocol requires n>=3. In addition, the earlier Reserved OOS-A primary score comparison was INCONCLUSIVE because it contained Human POSITIVE_STRUCTURE n=0. The available frozen evidence is therefore not sufficient for Production GO.

2. Phase 13 trace
13A established the Pattern A Fast research scope and point-in-time research boundary.
13B through 13G defined and compared the monthly regime, weekly trigger, daily risk, score, and staged-contract research components.
13H froze lead-time event pairing semantics: DATA_UNAVAILABLE, SAME_WEEK, PATTERN_A_ALREADY_ACTIVE, PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT, FAST_EARLIER_PATTERN_A_LATER, FAST_EVENT_NO_PATTERN_A_CATCHUP.
13I evaluated the frozen contract on Reserved OOS-A without tuning.
13J-1 froze Investable OOS-B selection, identity, blinded assets, and evaluation protocol.
13J-2 completed and sealed PASS A human stage review before model-output exposure.
13J-3 completed and sealed PASS B outcome ground truth before OOS evaluation.
13J-4 executed the frozen HIERARCHICAL_V01 and frozen Pattern A evaluation, then closed Phase 13 research.

3. Frozen contracts and integrity
Fast contract: HIERARCHICAL_V01 / 2da3fc36744b27ec13edae3f690df72c796906e5.
Frozen Pattern A: 05d03e16501adbca889488294aaaaa0bd84005de.
OOS-B evaluation protocol SHA-256: ffd271881d2b6ce9aa536431b7747395bf29dc3244df6316b241d60a1bdf138d.
Selection manifest SHA-256: 6fb59b9ffce5d8076a18faa00327c62e4edc5cff6ef93bcaf5095c50532ef825.
Blind asset manifest SHA-256: 9d8b03bf597c4520c279d2fdfe02c59df22669e27135adc1b9efa56b611b5ebe.
PASS A seal SHA-256: 4c908daa5ab803ccbf20f355027391aaa3f2d63c31e3f60ac60df6e34b9201ea.
PASS B human review SHA-256: c90db38860fc15cfe81eeb4f35e5e7ce0af8bd3c6de1eb1195e9603198d60585.

No model threshold, label, sample, review order, blinded asset, protocol, chart, PASS A seal, or PASS B seal was changed by 13J-4. All market data came from the local cache; network market requests=0. The evaluator explicitly truncates bars at each weekly point before building a historical snapshot.

4. Reserved OOS-A context (kept separate)
Population: 20. Human POSITIVE_STRUCTURE=0 and EARLY_OR_NONE=8, so the preregistered primary score test was INCONCLUSIVE. Fast trigger events=10. Clean lead population was n=1 with lead=3 weeks, therefore lead was INCONCLUSIVE. Human-vs-machine stage exact match was 10/20 (50%). Hard failures=0. The OOS-A production conclusion remains HOLD, not GO.

5. Investable OOS-B results
Population: 36 frozen samples. Human outcome distribution: GOOD_TRIGGER=5, BORDERLINE_TRIGGER=7, FALSE_TRIGGER=5, TOO_EARLY=8, TOO_LATE=2, TOO_EXTENDED=3, NO_SETUP=6.

Availability: stage READY=36/36 (100.0%); score UNAVAILABLE=7/36 (19.4%). Both satisfy the frozen availability thresholds (stage coverage >=80%, score unavailable <=20%).

Primary score comparison: POSITIVE_STRUCTURE (GOOD_TRIGGER+BORDERLINE_TRIGGER) score n=9, median=73.82; EARLY_OR_NONE (TOO_EARLY+NO_SETUP) score n=12, median=51.935; median difference=21.885. The frozen minimum group size is 5 and the preregistered direction gate PASSed.

Stage comparison is descriptive only: exact=14/36 (38.9%), over-call=15, under-call=7. Human TRIGGER count is frozen at zero and is not treated as an evaluation defect. The model distribution is WATCH=12, SETUP=10, TRIGGER=5, TREND=5, EXTENDED=4.

Fast trigger events=41. Pairing distribution: DATA_UNAVAILABLE=18, SAME_WEEK=0, PATTERN_A_ALREADY_ACTIVE=13, PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT=4, FAST_EARLIER_PATTERN_A_LATER=2, FAST_EVENT_NO_PATTERN_A_CATCHUP=4. Clean lead is defined only by FAST_EARLIER_PATTERN_A_LATER: n=2, median=8.5 weeks, range=1 to 16 weeks. The frozen lead minimum is 3, so lead-time status is INCONCLUSIVE rather than PASS or FAIL.

TOO_EARLY is a descriptive diagnostic: n=8; monthly states are PERMITTED_REGIME=4, EARLY_REGIME=3, UNAVAILABLE=1; daily risk is NORMAL=7 and EXTREME=1; weekly component status is PARTIAL=6, READY=1, UNAVAILABLE=1. These observations do not authorize retuning.

6. Strengths and weaknesses
Strengths: blinded two-pass human ground truth was completed before evaluation; all 36 OOS-B stage outputs were available; score availability passed the preregistered ceiling; OOS-B primary score direction passed with a material median separation; and all hard-failure audits are zero.

Weaknesses: OOS-A had no positive-structure outcome population, so it cannot establish score-direction evidence; OOS-B clean lead evidence is only two events; 18 of 41 Fast events encounter Pattern A data unavailability at the event; stage exact match is descriptive and modest; and TOO_EARLY remains a material diagnostic subgroup.

7. Historical coverage limitation
The local cache covers approximately 20 trading years, but early 2020 through 2021-H1 can have insufficient history for some component outputs. This is recorded as a limitation. The frozen OOS-B sample population was not replaced, filtered, or resampled to remove affected observations.

8. Decision and permitted next work
The correct final decision is HIERARCHICAL_V01_PRODUCTION_HOLD. No production promotion, threshold retuning, or retrospective label correction is justified by Phase 13. Future work must use a newly designed and independently frozen validation population or prospective monitoring; it must not revise the closed Phase 13 evidence set.
