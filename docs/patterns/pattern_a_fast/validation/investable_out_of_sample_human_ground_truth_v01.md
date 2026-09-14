pattern_a_fast_investable_oos_human_ground_truth_v01.md
==================================================
Phase 13J-3 Investable OOS-B Human PASS B Ground Truth Freeze
==================================================

1. Status
---------
HUMAN_OUTCOME_PASS_B_GROUND_TRUTH_FROZEN
READY_FOR_ADVISOR_REVIEW

Base commit: `f6b6448c280706e1e2d17d19809f369ac3feea95`

2. Scope and PASS A Preservation
--------------------------------
Phase 13J-2 PASS A Human Stage는 이미 frozen 상태다. PASS B에서는 사용자가 frozen `reference_date` 이후부터 frozen `outcome_review_end`까지의 outcome window를 의도적으로 검토한 Human outcome judgment만 기록한다. outcome을 보고 PASS A stage, confidence, trigger 또는 identity를 수정하지 않았다.

selection manifest, blind asset manifest, evaluation protocol, stage/outcome chart 및 hash, review mapping, PASS A freeze seal, Fast/Pattern A/Phase10, sampling 및 production scanner는 변경하지 않았다. resampling, retuning, machine score/stage 수정, OOS evaluation, Pattern A/Fast comparison 및 lead-time evaluation도 수행하지 않았다.

3. PASS B Exposure Boundary
---------------------------
Human reviewer는 frozen outcome window의 실제 가격 전개를 확인했다. 대부분의 종목은 익숙한 외부 주봉 차트 인터페이스를 사용했고, 필요한 경우 repository frozen outcome-blind asset을 사용할 수 있었다.

이는 PASS B의 의도된 Human ground-truth annotation 범위이므로 future outcome exposure는 `EXPECTED / AUTHORIZED`다. 오염으로 금지된 것은 machine Fast stage/score, machine prediction, sampling stratum/percentile, model evaluation, score separation, lead-time 및 confusion/result를 먼저 보고 Human outcome label을 맞추는 행위다. 그러한 machine output은 Human reviewer에게 노출되지 않았다.

4. Authoritative Human Outcome Result
-------------------------------------
+-----+---------------+--------------------+---------------------+------------+
| Ord | Sample ID     | Outcome            | Confidence          | Status     |
+-----+---------------+--------------------+---------------------+------------+
| 001 | INV_OOS_B_002 | GOOD_TRIGGER       | HIGH                | COMPLETE   |
| 002 | INV_OOS_B_004 | BORDERLINE_TRIGGER | MEDIUM              | COMPLETE   |
| 003 | INV_OOS_B_030 | BORDERLINE_TRIGGER | MEDIUM              | COMPLETE   |
| 004 | INV_OOS_B_024 | TOO_EARLY          | HIGH                | COMPLETE   |
| 005 | INV_OOS_B_031 | NO_SETUP           | HIGH                | COMPLETE   |
| 006 | INV_OOS_B_007 | FALSE_TRIGGER      | HIGH                | COMPLETE   |
| 007 | INV_OOS_B_005 | TOO_LATE           | HIGH                | COMPLETE   |
| 008 | INV_OOS_B_008 | NO_SETUP           | HIGH                | COMPLETE   |
| 009 | INV_OOS_B_023 | FALSE_TRIGGER      | HIGH                | COMPLETE   |
| 010 | INV_OOS_B_010 | TOO_EARLY          | HIGH                | COMPLETE   |
| 011 | INV_OOS_B_009 | FALSE_TRIGGER      | HIGH                | COMPLETE   |
| 012 | INV_OOS_B_018 | GOOD_TRIGGER       | HIGH                | COMPLETE   |
| 013 | INV_OOS_B_006 | TOO_LATE           | HIGH                | COMPLETE   |
| 014 | INV_OOS_B_034 | TOO_EXTENDED       | HIGH                | COMPLETE   |
| 015 | INV_OOS_B_028 | FALSE_TRIGGER      | HIGH                | COMPLETE   |
| 016 | INV_OOS_B_016 | BORDERLINE_TRIGGER | MEDIUM              | COMPLETE   |
| 017 | INV_OOS_B_022 | GOOD_TRIGGER       | HIGH                | COMPLETE   |
| 018 | INV_OOS_B_027 | TOO_EARLY          | HIGH                | COMPLETE   |
| 019 | INV_OOS_B_033 | NO_SETUP           | HIGH                | COMPLETE   |
| 020 | INV_OOS_B_035 | TOO_EARLY          | HIGH                | COMPLETE   |
| 021 | INV_OOS_B_011 | NO_SETUP           | HIGH                | COMPLETE   |
| 022 | INV_OOS_B_012 | FALSE_TRIGGER      | HIGH                | COMPLETE   |
| 023 | INV_OOS_B_003 | NO_SETUP           | HIGH                | COMPLETE   |
| 024 | INV_OOS_B_029 | TOO_EARLY          | HIGH                | COMPLETE   |
| 025 | INV_OOS_B_013 | TOO_EARLY          | HIGH                | COMPLETE   |
| 026 | INV_OOS_B_020 | TOO_EARLY          | HIGH                | COMPLETE   |
| 027 | INV_OOS_B_021 | BORDERLINE_TRIGGER | MEDIUM              | COMPLETE   |
| 028 | INV_OOS_B_001 | TOO_EARLY          | HIGH                | COMPLETE   |
| 029 | INV_OOS_B_026 | BORDERLINE_TRIGGER | MEDIUM              | COMPLETE   |
| 030 | INV_OOS_B_015 | GOOD_TRIGGER       | HIGH                | COMPLETE   |
| 031 | INV_OOS_B_025 | BORDERLINE_TRIGGER | MEDIUM              | COMPLETE   |
| 032 | INV_OOS_B_019 | NO_SETUP           | HIGH                | COMPLETE   |
| 033 | INV_OOS_B_036 | GOOD_TRIGGER       | HIGH                | COMPLETE   |
| 034 | INV_OOS_B_032 | TOO_EXTENDED       | HIGH                | COMPLETE   |
| 035 | INV_OOS_B_017 | BORDERLINE_TRIGGER | MEDIUM              | COMPLETE   |
| 036 | INV_OOS_B_014 | TOO_EXTENDED       | HIGH                | COMPLETE   |
+-----+---------------+--------------------+---------------------+------------+

5. Outcome Distribution
-----------------------
+--------------------+-------+    +------------+-------+
| Outcome            | Count |    | Confidence | Count |
+--------------------+-------+    +------------+-------+
| GOOD_TRIGGER       |     5 |    | LOW        |     0 |
| BORDERLINE_TRIGGER |     7 |    | MEDIUM     |     7 |
| FALSE_TRIGGER      |     5 |    | HIGH       |    29 |
| TOO_EARLY          |     8 |    +------------+-------+
| TOO_LATE           |     2 |
| TOO_EXTENDED       |     3 |
| NO_SETUP           |     6 |
+--------------------+-------+
| TOTAL              |    36 |
+--------------------+-------+

이 분포는 사용자 authoritative row에서 계산한 결과이며 목표 분포에 맞추어 조정하지 않았다.

6. Frozen Integrity and Ground Truth Seal
------------------------------------------
PASS B helper는 시작 전에 pre-PASS-B Human review SHA-256, immutable PASS A seal SHA-256, selection/asset/protocol/mapping hash 및 36-row frozen identity를 hard gate로 검증한다. identity는 `review_order`, `sample_id`, `ticker`, `name`, `historical_market`, `reference_date`, `outcome_review_end`이며 current data 재계산이나 network 조회는 하지 않는다.

새 ground-truth seal은 PASS B 전/후 Human review hash, PASS A seal hash, selection/asset/protocol/mapping hash, PASS A stage/trigger 보존, outcome distribution/confidence 및 non-evaluation flags를 봉인한다.

7. Next Gate
------------
이 commit은 Phase 13J-4 frozen HIERARCHICAL_V01 evaluation을 수행하지 않는다. advisor가 이 ground truth freeze를 PASS/CLOSED/FROZEN으로 검토한 뒤에만 별도 지시로 evaluation을 시작한다.
