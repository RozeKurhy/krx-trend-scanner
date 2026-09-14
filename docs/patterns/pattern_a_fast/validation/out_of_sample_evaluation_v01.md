pattern_a_fast_oos_evaluation_v01.md
==================================================
Phase 13I-2 Frozen OOS Evaluation
==================================================

1. Purpose
RESERVED_OOS_A 20건에 HIERARCHICAL_V01과 frozen Pattern A를 최초 실행했다. raw cached OHLCV만 사용했고 network request는 0이다. 재튜닝은 하지 않았다.

2. Frozen Contracts
Base: 94bc7edf2ea959f27d847b5cd9f23cd0cf3521c1
Fast: HIERARCHICAL_V01 / 2da3fc36744b27ec13edae3f690df72c796906e5
Pattern A: 05d03e16501adbca889488294aaaaa0bd84005de
Ground truth seal SHA-256: 1207be9e6f0b350a88d2a63d13588923c28b48154eaacefe782920fbe93d615b

3. OOS Population and Human Ground Truth
OOS population은 20건 그대로다. Human outcome labeled는 19건이며 OOS_A_012는 거래정지로 DATA_UNAVAILABLE다. Stage 및 availability에는 포함하고 outcome label group에는 제외했다.

4. Machine Availability
Stage READY: 20/20 (100.0%); UNAVAILABLE: 0.
Score READY/PARTIAL/UNAVAILABLE: 16/4/0.
Data coverage status: PASS.

5. Stage Results
Human-vs-machine exact/over-call/under-call: 10/8/2. Exact match rate는 READY machine stage 기준 0.5. 이는 descriptive metric이며 hard gate가 아니다.

| OOS ID | Human stage | Machine stage | Stage status | Score status | Score | Call |
|---|---|---|---|---|---:|---|
| OOS_A_001 | EXTENDED | EXTENDED | READY | READY | 53.45 | EXACT |
| OOS_A_002 | EXTENDED | EXTENDED | READY | READY | 54.25 | EXACT |
| OOS_A_003 | WATCH | WATCH | READY | READY | 31.26 | EXACT |
| OOS_A_004 | SETUP | WATCH | READY | READY | 65.86 | UNDER_CALL |
| OOS_A_005 | WATCH | SETUP | READY | PARTIAL | 52.32 | OVER_CALL |
| OOS_A_006 | WATCH | SETUP | READY | READY | 45.17 | OVER_CALL |
| OOS_A_007 | EXTENDED | EXTENDED | READY | READY | 59.11 | EXACT |
| OOS_A_008 | WATCH | WATCH | READY | READY | 33.21 | EXACT |
| OOS_A_009 | WATCH | EXTENDED | READY | READY | 50.95 | OVER_CALL |
| OOS_A_010 | TREND | EXTENDED | READY | READY | 64.97 | OVER_CALL |
| OOS_A_011 | WATCH | SETUP | READY | READY | 41.88 | OVER_CALL |
| OOS_A_012 | WATCH | WATCH | READY | PARTIAL | 36.25 | EXACT |
| OOS_A_013 | WATCH | SETUP | READY | READY | 70.67 | OVER_CALL |
| OOS_A_014 | EXTENDED | EXTENDED | READY | READY | 70.56 | EXACT |
| OOS_A_015 | WATCH | SETUP | READY | READY | 68.36 | OVER_CALL |
| OOS_A_016 | WATCH | WATCH | READY | PARTIAL | 35.31 | EXACT |
| OOS_A_017 | WATCH | WATCH | READY | READY | 36.71 | EXACT |
| OOS_A_018 | EXTENDED | SETUP | READY | PARTIAL | 49.25 | UNDER_CALL |
| OOS_A_019 | WATCH | TRIGGER | READY | READY | 47.3 | OVER_CALL |
| OOS_A_020 | EXTENDED | EXTENDED | READY | READY | 74.42 | EXACT |

6. Score Results
Primary comparison: POSITIVE_STRUCTURE vs EARLY_OR_NONE. Human n_positive=0, n_early_or_none=8; score-available n=0/8.
RESERVED_OOS_A has zero Human POSITIVE_STRUCTURE samples. Therefore the preregistered primary score-direction test is sample-size INCONCLUSIVE. The four Human Positive Anchors were NOT used in OOS metrics. Primary status: INCONCLUSIVE (INSUFFICIENT_POSITIVE_STRUCTURE_SAMPLE_SIZE). All preregistered GOOD_TRIGGER secondary comparisons are INCONCLUSIVE when GOOD_TRIGGER n=0.

7. Trigger, Pairing, and Lead Time
Observed Fast trigger events: 10. Pair distribution: {'DATA_UNAVAILABLE': 0, 'SAME_WEEK': 0, 'PATTERN_A_ALREADY_ACTIVE': 3, 'PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT': 6, 'FAST_EARLIER_PATTERN_A_LATER': 1, 'FAST_EVENT_NO_PATTERN_A_CATCHUP': 0}. Primary lead population is FAST_EARLIER_PATTERN_A_LATER only: n=1, median=3.0, IQR=0.0, min=3.0, max=3.0. Lead direction status: OOS_LEAD_INCONCLUSIVE.

8. Failure / Diagnostic Summary
Direct-jump is not a hard production criterion. Only preregistered data coverage, score direction, and lead direction can create hard failures.

9. Hard Gate Decision
Hard failures: []. Overall OOS status: NO_HARD_OOS_FAILURE_BUT_PRIMARY_SCORE_INCONCLUSIVE. HIERARCHICAL_V01 production_frozen remains false. This result does not claim fully OOS validated, and follow-up Investable OOS validation remains necessary.

10. Interpretation
RESERVED_OOS_A의 사람 positive structure 표본은 0건이다. 따라서 primary score direction은 PASS도 FAIL도 아닌 표본 부족 INCONCLUSIVE다. anchor 4건은 모든 OOS metric에서 제외했다.

11. Limitations
OOS_A_012 outcome-label interpretation requires advisor review. Stage/availability에는 포함했지만 human outcome label group과 secondary comparison에서는 제외했다.

12. Production Decision
이번 OOS 결과만으로 PRODUCTION_GO나 fully OOS validated를 선언하지 않는다. production_frozen은 false다.

13. Next Step
OOS_A_012 outcome-label interpretation requires advisor review. No tuning occurred after OOS labels were revealed. Next step is advisor review; no new OOS set is designed in this phase.
