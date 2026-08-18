pattern_a_fast_score_stage_contract_prototype_v01.md

==================================================
0. Status / Base SHA
==================================================

Phase: 13G-2 Threshold / Score / Stage Contract Prototype
Base Commit: 4fc5f9d11c23cd96703c5b066d5f60200fb41703

Status:
PHASE 13G-2
THRESHOLD / SCORE / STAGE CONTRACT PROTOTYPE COMPLETE
ADVISOR REVIEW PENDING

이 결과는 RESEARCH PROTOTYPE CONTRACT다. Production Freeze가 아니며 13H와
별도 13I OOS를 통과하기 전 Production Contract로 승격하지 않는다.

==================================================
1. Purpose
==================================================

13G-1의 동결된 21개 role registry와 selected 40-sample matrix를 READ ONLY로
사용해 bounded threshold/zone candidate, Monthly permission, Weekly core,
conditional breakout quality, Daily timing risk, aggregate opportunity score,
Weekly-only stage prototype을 만들었다.

Monthly grants permission.
Weekly pulls the trigger.
Daily times entry.

==================================================
2. Input Candidate Architecture
==================================================

입력은 13G-1 commit 4fc5f9d의 registry, selected matrix, architecture JSON,
그리고 Stage marker를 위한 frozen 13E weekly matrix다. 40 labeled sample만
사용했고 20 UNLABELED은 사용하지 않았다.

==================================================
3. No Optimization Guard
==================================================

Grid/random/Bayesian search, AUC/accuracy optimization, weight optimization,
새 feature mining은 하지 않았다. 모든 boundary는 rounded zone, structural zero,
critical-case semantic에서 수동으로 지정했고 provenance를 threshold registry에
기록했다.

==================================================
4. Threshold Candidate Method
==================================================

threshold candidates는 feature당 최대 3개다. exact calibration value를
복사하지 않았고 production_frozen은 모든 row에서 NO다.

- range_position_24m: EARLY / PERMITTED / LATE_OR_EXTENDED의 비선형 zone
- monthly_down_month_ratio_12m: IMPROVING / NEUTRAL / HEAVY_DOWNSIDE zone
- weekly proximity/structure: rounded readiness 또는 ordinal boundary
- daily max-gap/ATR: NORMAL / ELEVATED / EXTREME risk zone
- weekly secondary와 breakout hold: structural zero anchor

==================================================
5. Monthly Permission Prototype
==================================================

range_position_24m과 monthly_down_month_ratio_12m을 PRIMARY로 사용한다.
range position은 LOW=EARLY, MID=PERMITTED, VERY_HIGH=extended risk가 되도록
non-monotonic mapping을 보존한다. 결과 state는 EARLY_REGIME,
PERMITTED_REGIME, LATE_OR_EXTENDED_REGIME, UNAVAILABLE다.

drawdown/MA alignment/higher monthly low는 이번 selected aggregate에
직접 추가하지 않았다. Primary semantic을 먼저 검증하는 hierarchical variant다.

==================================================
6. Weekly Core Prototype
==================================================

Weekly core는 close_vs_wma200_pct, distance_to_prior_26w_high_pct,
higher_weekly_low_count_13w를 중심으로 하고, wma52 slope와 wma12-vs-wma26을
작은 secondary contribution으로 사용한다. 전체 aggregate에서 Weekly는 가장
큰 component다.

close_vs_wma200_pct가 INSUFFICIENT_HISTORY면 0점/FAIL로 채우지 않고,
남은 Weekly input으로 renormalize한다. score_status는 PARTIAL로 기록한다.

==================================================
7. Conditional Breakout Prototype
==================================================

post_breakout_min_low_vs_level_pct_26w는 event가 관측된 경우에만 quality
refinement다. EVENT_NOT_OBSERVED는 component NOT APPLICABLE이며 penalty나
Weekly fail을 만들지 않는다.

==================================================
8. Daily Timing Risk Prototype
==================================================

recent_5d_max_gap_abs_pct를 main shock-risk, atr_14_pct를 capped persistent
range confirmation으로 사용한다. Daily는 positive core가 아니라 risk penalty다.
risk가 높아질수록 final opportunity score가 좋아질 수 없고 Weekly stage는
변하지 않는다.

==================================================
9. Aggregate Score Prototype
==================================================

HIERARCHICAL_V01을 RECOMMENDED_FOR_13H 후보로 선택했다.

Weekly core를 중심으로 Monthly permission을 더하고, observed conditional
breakout만 작은 refinement로 반영한 뒤 Daily risk를 감산한다.
WEEKLY_DOMINANT_SOFT_V01은 개념으로만 검토했고 구현·calibration·diagnostics를
만들지 않았다.
선택은 in-sample 성능 최적화가 아니라 timeframe responsibility에 근거한다.

==================================================
10. Score Missing Semantics
==================================================

- close_vs_wma200_pct unavailable: INSUFFICIENT_HISTORY로만 허용한다.
  이 경우 available Weekly input을 renormalize하고 score_status=PARTIAL이다.
- post_breakout_min_low_vs_level_pct_26w unavailable: EVENT_NOT_OBSERVED다.
  conditional component는 NOT_APPLICABLE, refinement=0이며 score_status에 영향이 없다.
- 그 밖의 direct input(range position, downside ratio, prior-high distance,
  weekly higher-low, 두 Weekly secondary, max-gap, ATR) 중 하나라도 NaN이면
  UNEXPECTED_INPUT_MISSING으로 score_status=UNAVAILABLE, final score=NaN이다.
- NaN을 silent zero, silent renormalization, numeric risk로 변환하지 않는다.

JSON 공통 zone contract는 ordered upper-bound mapping이다. equality는 `<=`로
처리하고, 마지막 upper bound보다 큰 값만 fallback/final zone으로 보낸다.
따라서 0.25, 0.85, -0.10, -0.02, 0.03, 0.07도 script와 같은 zone에 속한다.

==================================================
11. Weekly Stage Prototype
==================================================

Stage output은 WATCH, SETUP, TRIGGER, TREND, EXTENDED다. 입력은 Weekly
retained feature만 사용한다. Monthly, Daily, score, human label, human stage,
previous stage를 읽지 않는다.

EXTENDED는 주봉 MA distance/alignment가 이미 상당히 진행된 snapshot,
TRIGGER는 최근 machine breakout marker와 ready weekly structure,
TREND/SETUP/WATCH는 현재 weekly structure의 진행도로만 구분한다.

==================================================
12. Stage-only Semantic Markers
==================================================

weeks_since_26w_close_breakout만 STAGE_SEMANTIC_MARKER로 READ ONLY 참조했다.
이는 score input이 아니며 Human Trigger Event를 대체하지 않는다.
Human Trigger Event는 입력으로 사용하지 않았고 backfill하지 않았다.

==================================================
13. Score / Stage Independence
==================================================

Daily risk만 달라져도 score는 달라질 수 있지만 weekly inputs가 같으면
stage는 같다. 반대로 score numeric value를 stage rule이 읽지 않는다.
Monthly는 TRIGGER를 만들지 않고 Daily는 Weekly stage를 만들지 않는다.

==================================================
14. Calibration Score Distribution
==================================================

HIERARCHICAL_V01 median:
GOOD_TRIGGER 71.61, NO_SETUP 34.31, TOO_EARLY 49.55, FALSE_TRIGGER 52.85,
TOO_EXTENDED 59.91.

GOOD vs NO_SETUP Cliff's Delta는 0.901이다. 이는 in-sample descriptive
separation일 뿐 generalization proof가 아니다.

==================================================
15. Human Stage Comparison
==================================================

Machine distribution: WATCH 12, SETUP 17, TRIGGER 3, TREND 3, EXTENDED 5.
Human distribution: WATCH 24, SETUP 10, TRIGGER 1, TREND 2, EXTENDED 3.

confusion/evaluation artifact는 descriptive mismatch list이며 accuracy를
최적화 기준으로 사용하지 않았다.

==================================================
16. Critical Pair Case Studies
==================================================

- 우리기술 pair: GOOD SETUP과 TOO_LATE TREND의 Monthly progression, Weekly
  progression, Daily risk를 분리해 기록한다. 모든 높은 feature를 보상하지 않는다.
- 천일고속 pair: WATCH/TOO_EARLY와 EXTENDED/TOO_EXTENDED 양끝을 Monthly zone,
  Weekly stage, Daily risk로 분리한다.
- LS pair: weekly higher-low/prior-high semantic을 위치 하나로 환원하지 않는다.
- 안국약품: 유일한 Human Trigger Anchor지만 이를 맞추기 위한 tuning은 하지 않았다.
- 에이치엠넥스: DMA200 아래 GOOD을 daily hard fail로 만들지 않았다.
- 에이프로젠: 이후 급등을 prototype 조정 근거로 쓰지 않았다.

==================================================
17. False Trigger Review
==================================================

선광, 서흥, 삼화전기, LG디스플레이의 FALSE_TRIGGER가 모두 낮은 score일 것을
강제하지 않았다. 어떤 component가 warning을 주는지와 놓치는 failure를 13H
failure analysis로 남긴다.

==================================================
18. Prototype Comparison
==================================================

실행 가능한 aggregate prototype은 HIERARCHICAL_V01 하나뿐이다. 두 번째
soft-score concept는 불필요한 in-sample variant 증식을 막기 위해 의도적으로
구현하지 않았다. HIERARCHICAL_V01은 Monthly permission → Weekly dominant
core → Daily risk adjustment → conditional refinement 순서를 보존한다.
weight는 SEMANTIC_ARCHITECTURE provenance 후보이지 production weight가 아니다.

==================================================
19. Recommended Candidate for 13H
==================================================

HIERARCHICAL_V01: RECOMMENDED_FOR_13H.
Recommended는 13H lead-time/failure analysis에서 써 볼 연구 후보이며
Production Winner를 뜻하지 않는다.

==================================================
20. Known Failures
==================================================

Human stage와 machine stage의 mismatch, GOOD의 낮은 score, NO_SETUP의 높은
score 가능성을 숨기지 않는다. 특히 small sample, optional WMA200 history,
machine breakout marker의 human-event 비동일성은 핵심 failure evidence다.

==================================================
21. Known Limitations
==================================================

40개는 feature discovery, selection, boundary design에 모두 사용된
in-sample calibration이다. label별 N과 event-observed N이 작고 stage
classifier는 current snapshot heuristic이다. Investability/Flow/RS는 별도 axis다.

==================================================
22. No Production Freeze
==================================================

Production score, production stage, BUY/SELL logic, optimal entry, scanner
integration은 없다. numeric candidate boundary와 candidate weight는 production
frozen이 아니다.

==================================================
23. OOS Separation
==================================================

이 40개는 13I unseen OOS로 사용할 수 없다. 13H도 OOS가 아니며 failure/lead
time research다.

==================================================
24. Next Phase Recommendation
==================================================

advisor가 PIT safety, bounded threshold design, missing semantics, Weekly-only
stage, score/stage independence, critical-pair behaviour, frozen artifact
integrity를 검토한 뒤 PASS하면 13G-2 CLOSED와 HIERARCHICAL_V01
RECOMMENDED_FOR_13H를 확정할 수 있다.
