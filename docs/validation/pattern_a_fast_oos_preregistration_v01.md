pattern_a_fast_oos_preregistration_v01.md
=================================================
Phase 13I-1 Reserved OOS Evaluation Preregistration
=================================================

상태: READY_FOR_BLIND_HUMAN_OOS_LABELING
OOS package base SHA: ddc7480bb24119ca3e8caca6d7b7f451f8eb097a
Contract seal base SHA: 311c235706bd07a67bfd3c658403f7d31da603c1
OOS set: RESERVED_OOS_A, 20건. 기존 사람이 주봉 단계와 결과 라벨을 모두 작성한 40건은 calibration으로 제외했다.

1. 모집단 동결
원본 60건 중 기존 review에서 weekly_stage_at_reference와 human_label이 모두 UNLABELED인 20건만 전량 사용한다. 선택, 제외, 대체는 허용하지 않는다. ticker+reference_date 기준으로 calibration과 겹치지 않으며, 같은 ticker의 다른 시점은 허용한다. reference_date와 outcome_review_end는 Phase 13C 원본 값 그대로이며 현재 데이터로 연장하지 않는다.

2. 블라인드 절차
PASS A에서 월/주/일 차트를 reference_date까지만 열어 단계·신뢰도·trigger 관찰값을 기록하고 저장한다. PASS B에서만 frozen outcome_review_end까지의 결과 차트를 열어 결과 라벨·신뢰도·메모를 기록한다. PASS B 이후 PASS A 기록을 수정하지 않는다. 사람용 자료에는 모델 점수·단계·후보·pairing·표본 분류를 노출하지 않는다.

3. 13I-2 사전등록 평가
Fast contract는 HIERARCHICAL_V01 (2da3fc36744b27ec13edae3f690df72c796906e5), Pattern A production closure는 05d03e16501adbca889488294aaaaa0bd84005de로 고정한다. Primary score comparison은 POSITIVE_STRUCTURE(GOOD_TRIGGER + BORDERLINE_TRIGGER) vs EARLY_OR_NONE(TOO_EARLY + NO_SETUP)다. Primary metrics는 n_positive, n_early_or_none, median_positive, median_early_or_none, median_difference, cliffs_delta다. Secondary descriptive comparisons는 GOOD_TRIGGER vs NO_SETUP, FALSE_TRIGGER, TOO_EARLY, TOO_EXTENDED이며 primary gate를 대체하지 않는다. sample 수가 부족한 primary/secondary 비교는 INCONCLUSIVE로 기록한다.

pairing precedence는 13H frozen conservative semantics와 동일하게 DATA_UNAVAILABLE → SAME_WEEK → PATTERN_A_ALREADY_ACTIVE → PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT → FAST_EARLIER_PATTERN_A_LATER → FAST_EVENT_NO_PATTERN_A_CATCHUP 순서다. 같은 completed week에 Fast trigger event와 Pattern A official candidate event가 observed되면 SAME_WEEK이며, 해당 주에 active라는 이유로 PATTERN_A_ALREADY_ACTIVE를 먼저 적용하지 않는다.

가용성은 Pattern A를 먼저 확인한다. Fast stage-ready coverage < 0.80 또는 Fast score unavailable > 0.20이면 OOS_DATA_COVERAGE_FAIL이며 부분 가용성은 별도 보고한다. n(POSITIVE_STRUCTURE) >= 3 및 n(EARLY_OR_NONE) >= 3일 때 median(POSITIVE_STRUCTURE) <= median(EARLY_OR_NONE)이면 OOS_SCORE_DIRECTION_FAIL이다. 둘 중 하나라도 표본이 부족하면 이 hard directional conclusion은 INCONCLUSIVE다. clean primary n >= 3이면 median lead weeks는 0보다 커야 하며 아니면 OOS_LEAD_DIRECTION_FAIL이다. clean primary n < 3이면 OOS_LEAD_INCONCLUSIVE이다. 라벨 동결 후 재튜닝·임계값 변경·샘플 교체는 금지한다.

4. 경계
13I-1에서는 OOS에 대한 Fast 또는 Pattern A 실행, 점수/단계/후보 산출, 비교 평가를 하지 않았다. production_frozen은 false이며 다음 단계는 사람 라벨 동결 뒤의 13I-2 평가다.
