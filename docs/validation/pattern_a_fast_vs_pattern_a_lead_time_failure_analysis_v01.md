pattern_a_fast_vs_pattern_a_lead_time_failure_analysis_v01.md

==================================================
0. Status / Base SHA
==================================================

Phase 13H / RESEARCH COMPLETE / ADVISOR REVIEW PENDING

Base SHA: 2da3fc36744b27ec13edae3f690df72c796906e5
Fast contract: HIERARCHICAL_V01 (13G-2, read-only)
Pattern A frozen production closure: 05d03e16501adbca889488294aaaaa0bd84005de
Human calibration SHA: 2e5a87f8214fe91d6cd2dbfa2bdc03cc2453d696
Production frozen: NO

==================================================
1. Purpose
==================================================

This is an in-sample measurement and failure analysis of frozen Pattern A
Fast against frozen Pattern A. It does not claim OOS performance,
generalization, or a production decision.

==================================================
2. Frozen Inputs / 3. No Optimization Contract
==================================================

Fast JSON inputs:
- artifacts/pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json
- artifacts/pattern_a_fast/research/pattern_a_fast_stage_prototype_v01.json

Pattern A official evaluator path:
- src/trend_scanner/validation/historical_snapshot.py: build_historical_snapshot
- src/trend_scanner/patterns/pattern_a_evaluator.py: evaluate_pattern_a
- src/trend_scanner/patterns/pattern_a_score.py: score_pattern_a
- src/trend_scanner/patterns/pattern_a_stage.py: classify_pattern_a_stage

No threshold, weight, score formula, stage threshold, precedence, missing
semantic, candidate rule, Human label, or Human stage was changed. Fast score
is a quality diagnostic, not a candidate gate.

==================================================
4. Historical PIT Timeline Method
==================================================

The analysis uses 37 unique tickers and 5,229 unique ticker + weekly_date
rows. Each sample window is reference_date minus 104 weeks through that
sample's frozen outcome_review_end. Duplicate ticker windows are evaluated
once then joined through sample_context_count.

At each point, daily data is sliced at or before t; HistoricalSnapshot then
constructs completed weekly and completed monthly bars only. W-FRI labels with
no actual Friday market close are excluded instead of being substituted with a
Thursday value. No network fetch is performed.

==================================================
5. Pattern A Benchmark Definition
==================================================

The primary benchmark is official PatternACandidateState.CANDIDATE returned by
the frozen production evaluator. TRANSITION/EARLY_TREND stage names are
secondary diagnostics only; no new candidate rule was inferred from stage.

==================================================
6. Fast Trigger Event Definition / 7. Censoring
==================================================

An observed Fast Trigger event requires previous READY stage != TRIGGER and
current READY stage == TRIGGER. TRIGGER -> TRIGGER is not a new event.
UNAVAILABLE -> TRIGGER and the first available TRIGGER timeline row are
LEFT_CENSORED, not synthetic trigger dates. SETUP/WATCH -> TREND direct jumps
are preserved as non-trigger transitions; they never receive a backfilled
trigger date.

UNAVAILABLE is a data/evaluation status, never WATCH or a sixth lifecycle
stage.

==================================================
8. Reference Anchored Comparison
==================================================

Exactly 40 labeled reference rows were compared; UNLABELED used = 0.
Reference catch-up delay is not called Fast trigger lead.

+----------------------+---+----------------------------------------------+------------------+--------------------------+
| Human group          | n | Fast stage distribution                      | Fast score median| Fast constructive + A inactive |
+----------------------+---+----------------------------------------------+------------------+--------------------------+
| POSITIVE_STRUCTURE   |15 | SETUP 8, TREND 3, TRIGGER 2, EXTENDED 2     | 70.35            | 11                       |
| FAILED               | 4 | WATCH 2, SETUP 2                             | 52.85            | 2                        |
| EARLY_OR_NONE        |17 | WATCH 10, SETUP 6, TRIGGER 1                 | 43.02            | 6                        |
| LATE_OR_EXTENDED     | 4 | EXTENDED 3, SETUP 1                          | 59.26            | 0                        |
+----------------------+---+----------------------------------------------+------------------+--------------------------+

For Fast-constructive/Pattern-A-inactive reference rows, catch-up-delay
medians were Positive 5w, Failed 14.5w, Early-or-none 10w. This is descriptive
only and is not an event lead metric.

==================================================
9. Observed Event Pair Analysis / 10. Lead Results
==================================================

Observed unique Fast Trigger events: 131
LEFT_CENSORED Fast trigger rows: 2
Direct jump without observed trigger: 118

+----------------------------------------+---+
| Pair status                            | n |
+----------------------------------------+---+
| PATTERN_A_ALREADY_ACTIVE               |70 |
| SAME_WEEK                              |13 |
| FAST_EARLIER_PATTERN_A_LATER           |33 |
| FAST_EVENT_NO_PATTERN_A_CATCHUP        |15 |
+----------------------------------------+---+

Only FAST_EARLIER_PATTERN_A_LATER is the primary lead population. Its n=33,
median=9.0 weeks, IQR=25.0 weeks, min=1.0, max=82.0. Pattern A already active,
same week, no catch-up, left-censored, and direct-jump cases are excluded from
this statistic. Therefore Fast is MIXED rather than universally earlier.

==================================================
11. Pattern A Catch Up Horizons
==================================================

Among the 33 valid Fast-earlier pairs, Pattern A caught up within 4w: 16,
8w: 16, 13w: 20, 26w: 24, and 52w: 30. The remaining no-catch-up events remain
NaN/right-censored; they are never converted to 52 weeks.

==================================================
12. Positive Structure / 13. False Trigger Cost
==================================================

Positive structure has a higher reference score median (70.35) but includes
two EXTENDED rows, so score alone is not a timing gate. Of four Human
FALSE_TRIGGER references, Fast is constructive in two (SETUP) and Pattern A is
inactive in those two contexts. This is failure evidence, not a basis for
retuning Fast sensitivity.

==================================================
14. Too Early / 15. Too Late-Extended Analysis
==================================================

Five TOO_EARLY references are Fast-constructive and are retained as
FAST_TOO_EARLY_CONTEXT evidence. Late/extended references are mostly Fast
EXTENDED (3/4); 000650_20251226 and 009150_20260327 also show EXTREME/ELEVATED
daily risk respectively. Daily risk is explanatory only and does not move a
trigger date.

==================================================
16. Score Failure / 17. Stage Mismatch
==================================================

Upper-quartile score bad-outcome evidence: 3. Lower-quartile good-outcome
evidence: 1. Quartiles are descriptive slices, never production thresholds.

+-------------+------------------------------------------+
| Human stage | Machine Fast stage counts                |
+-------------+------------------------------------------+
| WATCH       | WATCH 12, SETUP 9, TREND 2, TRIGGER 1    |
| SETUP       | SETUP 7, EXTENDED 1, TREND 1, TRIGGER 1  |
| TRIGGER     | TRIGGER 1                                |
| TREND       | EXTENDED 2                               |
| EXTENDED    | EXTENDED 2, SETUP 1                      |
+-------------+------------------------------------------+

This is a lifecycle-position comparison, not an accuracy score or a rule
change request.

==================================================
18. Critical Pair Cases
==================================================

- 001540 안국약품: reference Fast TRIGGER/82.05; Pattern A base/inactive;
  reference-to-Pattern-A catch-up 12w. The Human trigger was not backfilled.
- 032820 우리기술 pair: both references Fast EXTENDED; first GOOD_TRIGGER is
  NORMAL daily risk, later TOO_LATE is EXTREME. Pattern A remains progressed
  and inactive throughout the available reference comparison window.
- 000650 천일고속 pair: TOO_EARLY is Fast SETUP with Pattern A catch-up 10w;
  later TOO_EXTENDED is Fast EXTENDED, Pattern A already active, daily EXTREME.
- 006260 LS pair: 2020 reference Fast SETUP with 6w catch-up; 2022 GOOD_TRIGGER
  has Fast TRIGGER while Pattern A is already active.
- 012450 한화에어로스페이스: Human TREND/GOOD_TRIGGER but Fast EXTENDED;
  Pattern A progressed/inactive and no candidate catch-up inside window.
- 009150 삼성전기: Fast EXTENDED, daily ELEVATED, Pattern A progressed/inactive,
  no observed catch-up in window.
- FALSE_TRIGGER four: 선광 WATCH, 서흥 SETUP, 삼화전기 WATCH, LG디스플레이
  SETUP. Constructive Fast evidence exists for 서흥/LG디스플레이 only.
- 003060 에이프로젠바이오로직스: Fast WATCH / Pattern A WEAK / no catch-up;
  later price movement was not used to reinterpret the reference timeline.
- 036170 에이치엠넥스: Fast SETUP/54.62, Pattern A WEAK/inactive, catch-up 2w.

==================================================
19. Fast Advantages / 20. Weaknesses
==================================================

Advantage: 33 observed event pairs show Fast before a later Pattern A official
candidate, with a 9w median lead in that restricted population.

Weakness: 70 events already had Pattern A active, 15 never had Pattern A
catch-up, 118 direct-jump diagnostics have no observable Fast trigger, and
constructive states occur in both TOO_EARLY and FALSE_TRIGGER contexts.

==================================================
21. Pattern A Earlier / 22. Never Caught Up
==================================================

Pattern A was already active at 70 Fast event dates; no Fast-earlier claim is
made for them. Fifteen Fast events have no Pattern A candidate event before
their frozen analysis end; these are divergence/failure cases with NaN lead,
not evidence of lead beyond 52 weeks.

==================================================
23. Known Limitations / 24. In-Sample Declaration
==================================================

This uses the same 40 Human calibration samples used in 13D-13G. Multiple raw
TRIGGER entries can exist per ticker because episode-reset semantics are not
production-frozen. This report is in-sample hypothesis and failure evidence
only; it has no generalization claim.

==================================================
25. No Contract Modification / 26. 13I Recommendation
==================================================

No production integration and no contract modification occurred. Proceed to
13I only with unseen reference dates/samples that exclude these 40 calibration
records, with HIERARCHICAL_V01, thresholds, weights, and stage rules unchanged.
