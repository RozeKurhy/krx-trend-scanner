pattern_a_fast_investable_oos_preregistration_v01.md
==================================================
Phase 13J-1 Investable OOS-B Preregistration + Blind Package
==================================================

1. Purpose
----------
Phase 13J-1은 reference-time에 투자 가능했던 KRX universe에서 frozen HIERARCHICAL_V01 Fast relevance만 사용해 새로운 OOS-B blind human review sample을 동결한다. 이 단계는 Human label 입력, OOS evaluation, score/lead validation, Fast/Pattern A tuning을 수행하지 않는다.

2. Why OOS-B
-------------
RESERVED_OOS_A의 frozen evaluation은 Human POSITIVE_STRUCTURE(GOOD_TRIGGER + BORDERLINE_TRIGGER)가 0건이라 primary score-direction test가 INCONCLUSIVE였다. OOS-B는 좋은 미래 결과를 찾기 위한 표본이 아니라, 새 blind ground truth에서 Fast semantics를 재평가하기 위한 independent historical sample이다.

3. Previous OOS-A Limitation
----------------------------
OOS-A의 zero Human POSITIVE_STRUCTURE limitation은 유지해 기록한다. anchor나 미래 outcome으로 positive sample을 보충하지 않았다.

4. Historical PIT Source
------------------------
Phase 13J-0 frozen KRX-only active source 22건을 사용했다. audit SHA-256은 `984a022e37305d4fe3e86051f10e8ac28a6104953b9efbe4717b605a2b184358`이고 status는 `HISTORICAL_MARKET_CAP_PIT_READY`다. reference grid/provenance SHA-256은 각각 `181f86abc4a84b1bd770a0864ed2e6946337c949364e7166a2c24e8bc8b0cc3f`, `bc9bf3361d21120b0fae1e1e7f26e2ec812009d3864627d6a284a4bfa6fa3764`다. SUPERSEDED_NON_REFERENCE_SOURCE는 사용하지 않았다.

5. Phase10 Investability Semantics
----------------------------------
KOSPI + KOSDAQ historical market만 사용했다. market_cap >= 100,000,000,000 KRW AND reference 이하 최근 valid 20 trading-day avg_trading_value >= 300,000,000 KRW를 적용했다. close-price hard filter는 NONE이며, 20개 미만 observation은 REFERENCE_DATA_INSUFFICIENT로 제외했다. current/future market cap, shares, listing state, interpolation은 사용하지 않았다.

6. Completed Weekly Reference Contract
--------------------------------------
각 22-row grid의 `completed_weekly_reference_date == effective_date`를 확인하고 같은 날짜 KRX snapshot의 ticker, market, canonical market_cap을 join했다. Fast input daily/monthly/weekly도 모두 reference date 이하로 잘랐다.

7. Prior Dataset Firewall
-------------------------
Phase13C-1 원본 60 row에서 ticker set을 코드로 추출해 ticker 전체를 제외했다. final overlap은 0이다.

8. Human Positive Anchor Firewall
---------------------------------
frozen human-positive anchor CSV에서 ticker set을 코드로 읽어 ticker 전체를 제외했다. final anchor overlap은 0이며 anchor similarity/nearest-neighbor는 사용하지 않았다.

9. Sampling Strata
------------------
ADVANCED_CANDIDATE(TRIGGER/TREND) 10, SETUP_CANDIDATE 10, WATCH_HIGH_SCORE 8, EXTENDED_CONTROL 4, WATCH_LOW_SCORE_CONTROL 4를 목표로 했다. WATCH percentile은 same-date investable WATCH + score READY/PARTIAL population에서만 계산했다.

10. Deterministic Selection
---------------------------
Seed는 `PATTERN_A_FAST_INVESTABLE_OOS_B_V01`이다. SHA256(seed|stratum|ticker|completed_weekly_reference_date) ascending을 사용하고 ticker별 최소 hash 하나만 유지했다. WATCH score tie는 score ascending 뒤 ticker ascending ordinal rank로 결정해 same-date percentile을 고정했다. Python built-in hash()는 사용하지 않았다.

11. Diversity Constraints
-------------------------
final sample은 ticker 36개 unique, reference quarter 15개, reference date별 최대 3개, KOSPI/KOSDAQ 18/18개다. market max floor(2/3*N)=24를 만족한다. historical PIT sector source가 없으므로 sector constraint는 만들지 않았다.

12. Blindness Contract
----------------------
machine-facing manifest는 human reviewer에게 제공하지 않는다. human review CSV에는 stage, score, stratum, percentile, selection hash, Pattern A, future model output column이 없다. PASS A는 stage_blind chart 108개만, PASS B는 stage freeze 뒤 outcome_blind chart 36개만 노출한다.

13. Human Stage Taxonomy
------------------------
WATCH, SETUP, TRIGGER, TREND, EXTENDED; confidence LOW/MEDIUM/HIGH; trigger YES/NO를 frozen taxonomy로 사용한다. sheet 초기값은 모두 UNLABELED/PENDING이다.

14. Human Outcome Taxonomy
--------------------------
GOOD_TRIGGER, BORDERLINE_TRIGGER, FALSE_TRIGGER, TOO_EARLY, TOO_LATE, TOO_EXTENDED, NO_SETUP의 정확히 7 labels다. DATA_UNAVAILABLE은 label이 아니라 후속 adjudication status다.

15. Evaluation Preregistration
------------------------------
evaluation protocol은 human label 전 생성·hash seal했다. claim boundary는 "retrospective historical OOS with preregistered blind human review"다. fully prospective/live/production-proven claim은 하지 않는다.

16. Score Protocol
-----------------
primary POSITIVE_STRUCTURE(GOOD_TRIGGER+BORDERLINE_TRIGGER) vs EARLY_OR_NONE(TOO_EARLY+NO_SETUP)는 group별 n>=5가 필요하다. 충분한 n에서 positive median <= negative median이면 direction fail, 아니면 pass다. Cliff's delta는 보고만 하고 hard threshold는 없다. secondary GOOD_TRIGGER comparisons는 descriptive다.

17. Stage Protocol
------------------
Human-vs-machine confusion matrix, exact/over-call/under-call을 후속 평가에서 보고한다. exact match hard threshold는 없다.

18. Lead Protocol
-----------------
Precedence는 DATA_UNAVAILABLE → SAME_WEEK → PATTERN_A_ALREADY_ACTIVE → PATTERN_A_PRIOR_ACTIVITY_BEFORE_FAST_EVENT → FAST_EARLIER_PATTERN_A_LATER → FAST_EVENT_NO_PATTERN_A_CATCHUP다. clean lead는 FAST_EARLIER_PATTERN_A_LATER만 사용하고 n>=3, median lead weeks > 0이 direction pass 조건이다.

19. Availability Gates
----------------------
frozen sample 기준 Stage READY coverage <80%면 failure, Fast Score UNAVAILABLE rate >20%면 failure다. PARTIAL은 unavailable이 아니다. outcome future data 부족은 sampling replacement 근거가 아니다.

20. No-Retuning Rule
--------------------
freeze 뒤 sample 교체/추가/제거, quota substitution, score/stage/feature/weight/threshold 변경은 금지한다. 이번 실행에서 human labels, OOS evaluation, retuning은 모두 false다.

21. Claim Boundary
------------------
이 패키지는 retrospective historical OOS with preregistered blind human review다. live validation과 paper validation은 Phase20 이후 별도 scope다.

22. Final Sample Distribution
-----------------------------
Target/actual = 36/36. strata actual = ADVANCED 10, SETUP 10, WATCH_HIGH 8, EXTENDED 4, WATCH_LOW 4. hard minimum 6/6/5/3/3을 전부 충족한다. deterministic post-firewall eligible pool은 1,609 rows다. stage blind chart 108개와 outcome blind chart 36개가 asset manifest SHA-256으로 봉인됐다.

23. Final Status
----------------
`READY_FOR_BLIND_HUMAN_INVESTABLE_OOS_LABELING`

Human Stage/Outcome을 입력하지 않는다. OOS evaluation도 실행하지 않는다. Network market request count는 0이다. 다음 행동은 advisor review 후 blind human PASS A stage labeling이며, 이 commit에서 Phase13J-2 이상으로 진행하지 않는다.
