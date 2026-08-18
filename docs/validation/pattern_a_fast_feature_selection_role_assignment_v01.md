pattern_a_fast_feature_selection_role_assignment_v01.md

==================================================
0. Status / Base SHA
==================================================

Phase: 13G-1 Feature Selection / Role Assignment
Base Commit: 505c412f504dbb1a5a475e2562a0a1749eaa6508

Status:

PHASE 13G-1
FEATURE SELECTION / ROLE ASSIGNMENT COMPLETE
ADVISOR REVIEW PENDING

이 문서는 Production Score / Stage Contract가 아니다. 13D, 13E, 13F에서
HIGH로 남은 21개 Research Candidate를 동결된 40-sample Human Calibration
evidence로 정리한 Candidate Architecture v0.1이다.

==================================================
1. Purpose
==================================================

목적은 더 많은 feature를 찾는 것이 아니라 Monthly permission, Weekly core,
Daily timing/risk의 책임을 겹치지 않게 남기는 것이다.

Monthly grants permission.
Weekly pulls the trigger.
Daily times entry.

Daily는 Weekly 구조를 뒤집지 않고, Monthly는 trigger event를 만들지 않으며,
machine event는 유일한 Human Trigger Anchor(안국약품 001540_20260213)를
변경하거나 backfill하지 않는다.

==================================================
2. Input Research Phases
==================================================

| phase | final SHA | input | treatment |
| --- | --- | --- | --- |
| 13C-2 | 2e5a87f | Human Calibration 40 | READ ONLY |
| 13D | 6917b13 | Monthly HIGH 7 | READ ONLY |
| 13E | 415583a | Weekly HIGH 7 | READ ONLY |
| 13F | 505c412 | Daily HIGH 7 | READ ONLY |

남은 20개 UNLABELED sample은 사용하지 않았다. 기존 feature calculator,
matrix, summary, correlation, Human label, Human weekly stage, Human Trigger
Event는 수정하지 않았다.

==================================================
3. Candidate 21 Inventory
==================================================

정식 source-of-truth는 다음 registry다.

artifacts/pattern_a_fast/research/pattern_a_fast_feature_role_registry_v01.csv

| TF | FEATURE | ROLE | STATUS | WHY / LIMITATION |
| --- | --- | --- | --- | --- |
| M | range_position_24m | MONTHLY_PERMISSION | PRIMARY | 장기 위치; NON_MONOTONIC |
| M | drawdown_from_12m_high | MONTHLY_PERMISSION | SECONDARY | 최근 고점 대비 회복 |
| M | close_vs_ma24_pct | DROP_REDUNDANT | DROP | range position과 0.935 중복 |
| M | ma_alignment_score | MONTHLY_PERMISSION | SECONDARY | MA order 구조 |
| M | monthly_down_month_ratio_12m | MONTHLY_PERMISSION | PRIMARY | 하락 persistence |
| M | higher_monthly_low_count_12m | MONTHLY_PERMISSION | SECONDARY | 월봉 bottoming |
| M | recent_3m_return | DIAGNOSTIC | DIAGNOSTIC | 진행/과열 설명 |
| W | post_breakout_min_low_vs_level_pct_26w | CONDITIONAL_STRUCTURE | CONDITIONAL | event hold quality |
| W | close_vs_wma200_pct | WEEKLY_CORE | PRIMARY | 주봉 장기 저항 |
| W | distance_to_prior_26w_high_pct | WEEKLY_CORE | PRIMARY | prior-high readiness |
| W | higher_weekly_low_count_13w | WEEKLY_CORE | PRIMARY | weekly higher-low |
| W | wma52_slope_1w | WEEKLY_CORE | SECONDARY | long weekly trend |
| W | wma12_vs_wma26_pct | WEEKLY_CORE | SECONDARY | weekly alignment |
| W | rolling_low_4w_change | DIAGNOSTIC | DIAGNOSTIC | short progression |
| D | close_vs_dma200_pct | DIAGNOSTIC | DIAGNOSTIC | weekly trend shadow |
| D | dma20_vs_dma60_pct | DIAGNOSTIC | DIAGNOSTIC | weekly progression shadow |
| D | recent_5d_max_gap_abs_pct | DAILY_TIMING_RISK | PRIMARY | recent shock risk |
| D | higher_daily_low_count_10d | HOLD_RESEARCH | HOLD | direction unresolved |
| D | gap_from_prev_close_pct | DIAGNOSTIC | DIAGNOSTIC | one-day noise |
| D | lower_wick_pct | DIAGNOSTIC | DIAGNOSTIC | candle morphology |
| D | atr_14_pct | DAILY_TIMING_RISK | SECONDARY | persistent range risk |

==================================================
4. Selection Principles
==================================================

각 배정은 PIT safety, semantic clarity, coverage/effective N, Human Label
separation, case-study consistency, same-timeframe redundancy,
cross-timeframe incremental value, interpretability를 함께 사용했다.
Cliff's Delta 하나만으로 Primary를 정하지 않았고 correlation도 자동 Drop
규칙이 아니다.

==================================================
5. Role Taxonomy
==================================================

MONTHLY_PERMISSION은 장기 환경/위치, WEEKLY_CORE는 구조/trigger readiness,
DAILY_TIMING_RISK는 entry risk 후보를 뜻한다. CONDITIONAL_STRUCTURE는
event가 관측됐을 때만 의미가 있다. DIAGNOSTIC/HOLD/DROP은 직접 계약
입력이 아니다.

==================================================
6. Cross-Timeframe Redundancy
==================================================

21개 HIGH 후보의 cross-timeframe Spearman 결과는
artifacts/pattern_a_fast/research/pattern_a_fast_cross_timeframe_redundancy_v01.csv
에 147개 pair로 남겼다.

| pair | evidence | decision |
| --- | --- | --- |
| range_position_24m / close_vs_ma24_pct | same-TF 0.935 | range position 유지, MA-distance DROP |
| wma52_slope_1w / close_vs_dma200_pct | cross-TF 0.905 | Weekly trend, Daily MA diagnostic |
| wma12_vs_wma26_pct / close_vs_dma200_pct | cross-TF 0.860 | Weekly alignment 우선 |
| rolling_low_4w_change / dma20_vs_dma60_pct | cross-TF 0.839 | Daily MA diagnostic |
| recent_5d_max_gap_abs_pct / atr_14_pct | same-TF 0.791 | max-gap primary, ATR secondary |

상관이 낮아도 같은 semantic일 수 있고, 상관이 높아도 시간축 책임이 다르면
둘 다 남을 수 있다. 위 결정은 numeric threshold나 weight가 아니다.

==================================================
7. Monthly Permission Selection
==================================================

range_position_24m과 monthly_down_month_ratio_12m은 PRIMARY다. 전자는
long-term position의 early/extended zone을, 후자는 price magnitude와 다른
downside persistence를 보존한다. range position은 GOOD/TOO_EARLY/TOO_EXTENDED
관계가 비선형이므로 one-sided hard gate로 축소하지 않는다.

drawdown_from_12m_high, ma_alignment_score, higher_monthly_low_count_12m은
각각 recovery, order, bottoming semantic이 있어 SECONDARY다. close_vs_ma24_pct는
range position과 가장 강하게 중복돼 DROP, recent_3m_return은 late/extended
case 설명에만 유용해 DIAGNOSTIC이다.

==================================================
8. Weekly Core Selection
==================================================

Weekly PRIMARY는 close_vs_wma200_pct, distance_to_prior_26w_high_pct,
higher_weekly_low_count_13w다. 각각 long-term resistance, prior-high
proximity, higher-low structure라는 다른 책임을 가진다.

wma52_slope_1w와 wma12_vs_wma26_pct는 trend/alignment evidence로 SECONDARY다.
rolling_low_4w_change는 retained higher-low/conditional hold와 겹쳐
DIAGNOSTIC이다.

==================================================
9. Conditional Weekly Features
==================================================

post_breakout_min_low_vs_level_pct_26w는 CONDITIONAL_STRUCTURE / CONDITIONAL이다.
최근 26주 machine breakout이 존재한 19개에서만 정의되고, 나머지 21개 NaN은
EVENT_NOT_OBSERVED다. 이는 0점, FAIL, BAD가 아니며 imputation도 하지 않는다.

이 feature는 universal Monthly/Weekly gate도 아니고 Human Trigger Event의
대체도 아니다. 관측된 machine event의 hold quality를 향후 별도로 검토할
후보일 뿐이다.

==================================================
10. Daily Timing Selection
==================================================

Daily의 직접 책임은 volatility/risk다. recent_5d_max_gap_abs_pct는 최근
discrete shock을 직접 설명하므로 PRIMARY, atr_14_pct는 지속 range breadth를
보완하므로 SECONDARY다. 둘은 같은 비중의 독립 PRIMARY가 아니다.

==================================================
11. Daily MA Shadow Decision
==================================================

close_vs_dma200_pct: DIAGNOSTIC.
dma20_vs_dma60_pct: DIAGNOSTIC.

Weekly wma52_slope_1w, wma12_vs_wma26_pct, rolling_low_4w_change와 높은
상관이 있어 Daily layer에 trend를 다시 쌓지 않았다. 에이치엠넥스
036170_20251226는 DMA200 아래에서도 GOOD_TRIGGER이므로 daily DMA200은
hard eligibility가 될 수 없다.

==================================================
12. Daily Volatility Consolidation Decision
==================================================

recent_5d_max_gap_abs_pct: DAILY_TIMING_RISK / PRIMARY.
atr_14_pct: DAILY_TIMING_RISK / SECONDARY.

max-gap은 recent shock sensitivity, ATR은 persistent range breadth를 보지만
Spearman 0.791의 moderate redundancy가 있다. max-gap이 Daily risk 대표를
맡고 ATR은 보조 확인으로만 남긴다.

==================================================
13. Counterintuitive / Unresolved Features
==================================================

higher_daily_low_count_10d는 HOLD_RESEARCH / HOLD다. GOOD_TRIGGER median이
NO_SETUP보다 낮은 방향의 separation은 active trigger pullback과 basing을
구분할 가능성을 만들지만, causal/structural direction을 고정할 근거는 아니다.
Interpretation Frozen은 NO이고 research debt는 보존한다.

==================================================
14. Missing Semantics
==================================================

| feature / class | semantic |
| --- | --- |
| post_breakout_min_low_vs_level_pct_26w | EVENT_NOT_OBSERVED; data error나 BAD가 아님 |
| close_vs_wma200_pct | INSUFFICIENT_HISTORY; data 부족은 negative observation이 아님 |
| selected full-coverage candidates | FULL_COVERAGE |

이번 Phase에는 imputation rule이 없다.

==================================================
15. Primary Candidate Architecture
==================================================

| layer | primary candidates |
| --- | --- |
| Monthly permission | range_position_24m, monthly_down_month_ratio_12m |
| Weekly core | close_vs_wma200_pct, distance_to_prior_26w_high_pct, higher_weekly_low_count_13w |
| Daily timing/risk | recent_5d_max_gap_abs_pct |

Primary는 다음 Phase에서 우선 검토할 후보라는 뜻이지 현재 구현된 rule이 아니다.

==================================================
16. Secondary / Conditional / Diagnostic
==================================================

SECONDARY 6개: drawdown_from_12m_high, ma_alignment_score,
higher_monthly_low_count_12m, wma52_slope_1w, wma12_vs_wma26_pct, atr_14_pct.

CONDITIONAL 1개: post_breakout_min_low_vs_level_pct_26w.

DIAGNOSTIC 6개: recent_3m_return, rolling_low_4w_change, close_vs_dma200_pct,
dma20_vs_dma60_pct, gap_from_prev_close_pct, lower_wick_pct.

==================================================
17. Drop / Hold Decisions
==================================================

DROP 1개: close_vs_ma24_pct. range_position_24m과의 0.935 중복이 근거다.
HOLD 1개: higher_daily_low_count_10d. separation이 아니라 해석되지 않은
방향이 문제다. PRIMARY + SECONDARY은 12개이며 21개 전체를 계약 후보로
올리지 않았다.

==================================================
18. Critical Pair Case Studies
==================================================

- 안국약품 001540_20260213: 유일한 explicit Human Trigger Anchor다.
  selection은 anchor를 바꾸지 않는다.
- 우리기술 032820 good/too-late pair: monthly progress와 daily extension을
  같은 방향의 단순 보상으로 만들지 않아야 한다.
- 천일고속 000650 early/extended pair: Monthly location과 Daily volatility의
  서로 다른 책임을 뒷받침한다.
- LS 006260 borderline/good pair: weekly higher-low와 prior-high proximity를
  가격 위치 하나로 환원하지 않아야 한다.

==================================================
19. False Trigger Review
==================================================

FALSE_TRIGGER 4개(선광, 서흥, 삼화전기, LG디스플레이)는 후보의 risk 설명이
항상 단일 방향으로 일치하지 않았다. 이 혼재 때문에 Daily 변동성은 risk
modifier 후보에 한정하고 Monthly/Weekly 구조도 현재 hard gate로 만들지
않았다. 에이프로젠바이오로직스의 이후 급등은 reference-date NO_SETUP
판정을 바꾸지 않는다.

==================================================
20. Architecture Invariants
==================================================

- Monthly permission은 trigger event를 생성하지 않는다.
- Weekly core가 trigger readiness/structure의 중심이다.
- Daily는 Weekly stage를 생성하지 않는다.
- Daily가 bad Weekly structure를 override하지 않는다.
- EVENT_NOT_OBSERVED와 INSUFFICIENT_HISTORY는 자동 fail이 아니다.
- Human Trigger Event backfill은 하지 않았다.

==================================================
21. Known Limitations
==================================================

분석은 labeled calibration 40개만 본 in-sample research다. label별 effective N이
작고 event-conditioned weekly feature는 19개만 관측된다. correlation은 small
sample에서 불안정할 수 있고 case study는 독립 validation이 아니다.
Investability와 시장/flow/relative-strength는 별도 axis다.

==================================================
22. No Threshold Frozen
==================================================

Numeric threshold, sweet-spot boundary, minimum gate, FAIL cutoff은 정하지
않았다. range_position_24m의 비선형성도 기록만 했고 boundary는 만들지 않았다.

==================================================
23. No Score Formula
==================================================

Feature weight, timeframe percentage, score formula, 점수 합산은 없다.
PRIMARY/SECONDARY은 evidence-review 우선순위일 뿐 score contribution이 아니다.

==================================================
24. No Production Stage Rule
==================================================

WATCH/SETUP/TRIGGER/TREND/EXTENDED를 feature 조합으로 자동 분류하지 않았다.
BUY/SELL logic, optimal entry, production scanner integration도 없다.

==================================================
25. OOS Separation
==================================================

40개 Human Calibration sample은 13I에서 unseen OOS로 재사용할 수 없다.
CV accuracy, precision, recall, AUC는 classifier가 없는 13G-1 범위 밖이다.

==================================================
26. Next Phase Recommendation
==================================================

advisor review가 candidate architecture와 frozen-input integrity를 PASS하면
13G-1을 CLOSED 처리할 수 있다. 그 뒤 13G-2에서만 direction, zone,
threshold candidate, score contribution candidate, risk-modifier candidate,
stage-inference candidate를 별도 prototype으로 검토한다. 그 단계도 곧바로
Production Freeze는 아니다.
