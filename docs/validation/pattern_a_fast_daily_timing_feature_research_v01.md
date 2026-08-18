pattern_a_fast_daily_timing_feature_research_v01.md

==================================================
0. Status / Base SHA
==================================================

Phase: 13F Daily Timing Feature Research

Base Commit: 415583ab97835d6d98c945476de45aafdd6371b7 (Phase 13E Final)

Status:

DAILY TIMING FEATURE RESEARCH COMPLETE
ADVISOR REVIEW PENDING

Phase 13F은 아직 CLOSED로 선언되지 않는다. advisor가 실제 GitHub commit /
artifacts / feature distribution / PIT leakage / daily breakout horizon /
incremental value를 검토한 뒤 PASS하면 CLOSED로 전환한다.

Phase 13F 종료 시점에도 "최적 매수일"은 정의되지 않는다. 13D + 13E + 13F가
모두 CLOSED되면 다음 단계는 세 timeframe의 Research Evidence를 합쳐 Feature
Selection / Role Assignment(Gate/Score/Diagnostic 배정)로 진행한다 — 이
Phase에서 결정하지 않는다.

==================================================
1. Research Purpose
==================================================

Pattern A Fast는 세 timeframe의 역할을 분리한다.

Monthly grants permission. Weekly pulls the trigger. Daily times entry.

Phase 13D는 Monthly Regime Feature Research, Phase 13E는 Weekly Trigger
Feature Research를 각각 CLOSED했다. Phase 13F는 동일한 40-sample Human
Calibration Set(Phase 13C-2 CLOSED/FROZEN)을 사용해 "Monthly가 허용하고
Weekly가 유효한 구조를 만들었을 때, reference_date 시점의 Daily 구조가
실제 신규 진입 위치로 얼마나 건강했는가"를 연구한다.

핵심 질문(w.md 목적):

- 너무 급등한 날인가?
- 눌림이 건강한가?
- 단기 저점이 유지되는가?
- 직전 일봉 고점에 너무 붙어 있는가?
- 돌파 직후인가, 돌파 후 과열됐는가?
- 단기 이평선과 너무 멀어진 상태인가?
- 변동성이 지나치게 커졌는가?
- 거래량을 동반한 건강한 전환인가?

를 PIT-safe Feature로 정량화한다. Daily Production Entry Rule, Threshold,
Score, Classifier, Optimal Entry Date는 이 Phase의 범위가 아니다(§21, §37).

==================================================
2. Daily Ground Truth Limitation
==================================================

40개 Human Calibration Set에는 Human Weekly Stage / Human Outcome Label은
있지만, 별도의 Human Daily Entry Label / Human Ideal Entry Date / Human
Daily Trigger Date는 존재하지 않는다.

따라서 이 Phase에서 절대 하지 않은 해석:

- "이 날이 최적 매수일이다"
- "GOOD_TRIGGER이므로 reference_date가 좋은 Daily Entry였다"
- "TOO_EARLY이면 며칠 뒤가 진짜 Entry였다"
- 미래 차트에서 가장 좋은 저점을 찾아 ideal_entry_date로 만드는 것

이 문서 전체는 "DAILY TIMING FEATURE RESEARCH"이지 "DAILY ENTRY GROUND
TRUTH LABELING"이 아니다 — reference_date 당시 Daily 상태가 기존 7종
Human Outcome Label과 어떤 관계를 보였는지만 기술한다.

==================================================
3. Human Calibration Set
==================================================

사용: artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv

조건: weekly_stage_at_reference != UNLABELED AND human_label != UNLABELED

정확히 40 samples(script의 `assert len(labeled) == 40`으로 machine-check).

PIT Stage: WATCH=24, SETUP=10, TRIGGER=1, TREND=2, EXTENDED=3

Human Outcome: GOOD_TRIGGER=9, BORDERLINE_TRIGGER=6, FALSE_TRIGGER=4,
TOO_EARLY=8, TOO_LATE=1, TOO_EXTENDED=3, NO_SETUP=9

Remaining 20 UNLABELED은 사용하지 않았다.

==================================================
4. PIT Leakage Contract
==================================================

모든 Daily Feature는 `daily[daily.index <= reference_date]`로 슬라이스된
프레임만 입력받는다(`compute_daily_timing_features(daily)` 시그니처가
`daily` 하나뿐임을 §24 item 1로 machine-check).

Feature 계산에 절대 사용하지 않은 것: reference_date 이후 daily bars,
outcome_review_end, future return/drawdown/breakout/pullback/support/
gap/volume, human_label, weekly_stage_at_reference, human_notes,
human_confidence, human Trigger Event, source_reason의 forward 정보.

`compute_daily_timing_features`는 human_label / weekly_stage_at_reference /
trigger_event_date / outcome_review_end 인자를 받지 않는다(§24 item 2-4,
inspect.signature로 machine-check).

leakage 회귀 테스트: `test_future_daily_row_append_does_not_change_reference_day_features`
— 원본 daily에 미래 60일 row를 추가한 뒤 PIT slice를 재실행해도 55개
feature 값이 전부 불변임을 확인.

==================================================
5. Daily Reference Semantics
==================================================

reference_date는 기존 Human Review의 weekly completed reference date다.
Daily Feature는 `daily[daily.index <= reference_date]`의 마지막 행을
"current bar"로 사용한다.

실증 확인(이 모듈 작성 전에 40개 샘플 전수 확인): 40개 샘플 전부
`daily[daily.index <= reference_date].index[-1] == reference_date`
(gap=0). 즉 reference_date는 모든 샘플에서 실제 거래일이었다.

이 모듈이 실제로 의존하는 계약은 이보다 약하다 — "current bar" = PIT
슬라이스의 마지막 행(`daily.iloc[-1]`)이며, reference_date가 비거래일인
경우 그 이전 가장 가까운 거래일이 된다(historical_snapshot.py의
`effective_as_of`와 동일 철학). Feature Matrix는 이 값을
`effective_daily_as_of` 컬럼으로 별도 기록해, 어떤 row의 "현재 상태"가
정확히 reference_date였는지(전부 YES) 나중에도 검증 가능하게 했다.

prior-window 계산(prior high, prior volume benchmark 등)은 current bar를
반드시 제외한다. 예: `prior_20d_high = max(high[-21:-1])`(current high
제외). §24 item 6/7이 이를 machine-check한다.

==================================================
6. Daily Feature Definitions
==================================================

전체 55개 Feature(50 analysis + 5 diagnostic raw MA값)를 12개 family로
구성했다. 정확한 formula/required_history_bars/missing_behavior는
`src/trend_scanner/research/pattern_a_fast_daily_features.py`의
`FEATURE_SPECS`가 단일 source-of-truth다(이 문서는 요약만 제공).

w.md §8 "Avoid Indicator Zoo" + advisor review에 따라, w.md가 후보로
제시한 여러 이름이 실제로는 동일한 값을 가리키는 경우(예: §7.2
`distance_from_dmaN_pct` == §7.1 `close_vs_dmaN_pct`, §7.7
`higher_daily_low_count_5d`/`rolling_low_5d_change`를 §7.8도 그대로
재사용) 한 번만 구현하고 문서에서만 두 family 모두에 연결했다. 또한
w.md가 제시한 다중 window grid(예: 10d/20d/60d prior-high 3종, ATR
5/14/20 3종) 중 대표 window 1~2개만 채택해 Weekly 모듈(52개)과 같은
자릿수로 유지했다(총 55개, Weekly 대비 1.06배).

Family 구성:

| family | feature 수 | 대표 feature |
|---|---|---|
| 7.1 daily_ma_structure | 15(diag 5 포함) | close_vs_dma200_pct |
| 7.2 short_term_extension | 6 | daily_return_20d, recent_5d_max_runup |
| 7.3 prior_high_proximity | 2 | distance_to_prior_20d_high_pct |
| 7.4 daily_breakout_state | 3 | close_above_prior_20d_high |
| 7.5 daily_breakout_age | 1 | days_since_20d_close_breakout |
| 7.6 daily_breakout_hold | 5 | post_breakout_close_hold_ratio_20d |
| 7.7 pullback_quality | 5 | pullback_from_20d_high_pct |
| 7.8 support_low_structure | 4 | higher_daily_low_count_10d |
| 7.9 range_position | 2 | range_position_10d, range_position_20d |
| 7.10 volatility_risk | 5 | atr_14_pct |
| 7.11 volume_participation | 3 | volume_vs_20d_avg |
| 7.12 daily_candle_location | 4 | close_location_in_daily_range |

==================================================
7. Daily MA / Extension Research
==================================================

**Hypothesis A**(GOOD_TRIGGER는 TOO_EARLY보다 daily MA20/60 구조가 더
안정적일 수 있다) — **약하게만 지지됨**. GOOD_TRIGGER vs TOO_EARLY
Cliff's Delta: `close_vs_dma20_pct` -0.111(거의 무관), `close_vs_dma60_pct`
0.083(거의 무관), `close_vs_dma120_pct` 0.306(약한 지지). 20일/60일처럼
짧은 창에서는 두 그룹이 사실상 구분되지 않고, 120일처럼 긴 창에서만
약한 신호가 보인다. 단기 이평 이격도만으로 GOOD과 TOO_EARLY를 가르기는
어렵다.

**Hypothesis B**(TOO_LATE/TOO_EXTENDED는 recent 5d/10d runup, MA20
distance, range position이 과도할 수 있다) — **지지됨(단, small n)**.
GOOD_TRIGGER vs TOO_EXTENDED Cliff's Delta: `recent_5d_max_runup` -1.000,
`recent_10d_max_runup` -0.630, `close_vs_dma120_pct` -0.778,
`range_position_20d` -0.556 — 전부 TOO_EXTENDED 쪽이 더 극단적. 실제
케이스(§16-F/G): 우리기술 TOO_LATE(032820_20260327)의
`close_vs_dma200_pct` = +250%, `atr_14_pct` = 14.3%, 천일고속
TOO_EXTENDED(000650_20251226)의 `close_vs_dma200_pct` = +401%, ATR14 =
23.7%. 같은 종목의 GOOD/SETUP 시점 대비 수십 배 확대된 수치다. 단
TOO_LATE n=1, TOO_EXTENDED n=3이므로 §32 Small-N Guard에 따라 개별 pair
Delta는 descriptive로만 취급한다.

**Hypothesis C**(GOOD_TRIGGER는 직전 20d high에 적당히 가까우면서도
지나치게 extended되지 않은 위치일 수 있다) — **부분 지지, 비선형
가능성**. `pullback_from_20d_high_pct`의 GOOD_TRIGGER vs TOO_EARLY Delta
-0.361(GOOD이 고점에 더 가까움)과 GOOD_TRIGGER vs TOO_EXTENDED Delta
+0.407(GOOD이 TOO_EXTENDED보다는 고점에서 더 떨어져 있음, 즉
TOO_EXTENDED가 이미 고점 위/근접)이 동시에 나타난다. §31 Non-Monotonic
Guard에 따라 U-shape 가능성을 바로 폐기하지 않고 §17에서 그대로
기록했다 — 다만 13E의 stale-breakout 경험을 반영해, 이 값이 이벤트
search-horizon 버그에서 비롯된 게 아님을 먼저 확인했다(§7.7은
event-conditioned가 아닌 순수 rolling-window 계산이라 해당 버그 클래스
자체가 없음).

==================================================
8. Prior High / Breakout Research
==================================================

`close_above_prior_20d_high`/`high_above_prior_20d_high`는 13E에서 확인한
대로 boolean이 희귀/상수에 가깝다: 40개 중 `close_above_prior_20d_high`=1
인 샘플은 6개뿐(대부분 WATCH/SETUP 단계 샘플은 아직 20일 고점을 못
넘긴 상태) — LOW로 분류한다(§18).

연속형 버전 `distance_to_prior_20d_high_pct`(=`close_breakout_strength_20d`,
spearman 1.0으로 완전 중복 — §15에서 근거 제시)는 GOOD_TRIGGER vs
TOO_EARLY Delta -0.20 내외로 약한 신호만 보인다.

`days_since_20d_close_breakout`(§7.5, 20일 search horizon, offset 0..19)은
event-conditioned라 40개 중 18개만 유효(missing 22개). label별 effective
n: GOOD_TRIGGER=6(median 8.5일), BORDERLINE=4(15.5일), FALSE_TRIGGER=2(9일),
TOO_EARLY=1, TOO_LATE=1, TOO_EXTENDED=3(11일), NO_SETUP=1. POSITIVE_STRUCTURE
(n=10) vs EARLY_OR_NONE(n=2) Cliff's Delta=0.700으로 표면적으로는 강하지만,
EARLY_OR_NONE 쪽 유효 표본이 2개뿐이라(§32 Small-N Guard) 이 숫자를 그대로
순위 근거로 쓰지 않는다 — §18에서 HIGH가 아닌 MEDIUM으로 분류한 이유다.

==================================================
9. Breakout Hold / Retest Research
==================================================

이 family(§7.6) 전체가 §7.5 event 존재를 전제로 하는 event-conditioned
subset이다(40개 중 유효 16~18개). Phase 13E의 교훈(breakout family는
전체 40이 아니라 이 subset에서만 유효)을 그대로 적용해 아래 결과도 항상
subset 범위로 읽어야 한다.

`post_breakout_close_hold_ratio_20d`는 **예상과 반대 방향의 결과**를
보였다: GOOD_TRIGGER n=5, median=0.0 / FALSE_TRIGGER n=2, median=0.363 —
GOOD_TRIGGER 쪽이 오히려 돌파 후 종가 유지 비율이 더 낮다(Cliff's Delta
GOOD vs FALSE = -0.600). 원인 추정: GOOD_TRIGGER의 breakout event median
offset이 8.5일로 최근이라 post-event 관찰 구간 자체가 짧고(median 5~8일),
그 짧은 구간에 마침 조정이 섞이면 hold_ratio가 쉽게 0으로 떨어지는
반면, FALSE_TRIGGER의 관찰 구간이 상대적으로 길어(구간 길이 효과) hold
비율이 더 안정적으로 보일 수 있다. 이 해석은 검증되지 않은 가설이며,
n=5 vs n=2로 통계적 결론을 내릴 수 없다 — **§18에서 이 feature를 LOW/
REJECTED로 분류**한다(§31 Non-Monotonic Guard: 표면 delta만 보고 채택하지
않고 semantics/missingness/small-n을 먼저 검증).

`close_back_below_breakout_level_20d`(boolean)는 n=18, POSITIVE_STRUCTURE
vs EARLY_OR_NONE Delta=0.300으로 약한 신호. FALSE_TRIGGER 쪽 표본이
2개뿐이라 "돌파 후 레벨 아래로 복귀"가 FALSE_TRIGGER를 잡아내는지는
이번 40-sample로는 결론 내리기 어렵다.

==================================================
10. Pullback / Support Research
==================================================

**Hypothesis E**(건강한 눌림 = 20d high 대비 일부 조정 + daily low 상승
+ MA20/60 구조 유지) — **부분적으로만 지지, 저점 상승 방향은 반대**.

`pullback_from_20d_high_pct`: 전체 median -0.061 정도로 대부분 표본이
20일 고점에서 소폭 조정된 상태에서 관측됐다(§16 안국약품처럼 돌파 직후
0에 가까운 값도, 우리기술 TOO_LATE처럼 -22.5%까지 밀린 값도 공존).

`higher_daily_low_count_10d`는 **예상과 반대**: POSITIVE_STRUCTURE(n=15)
median 3.0 vs EARLY_OR_NONE(n=17) median 5.0 — "저점이 점점 높아지는
쪽"이 오히려 WATCH/basing 단계 표본에서 더 흔하다(Cliff's Delta
POSITIVE vs EARLY/NONE = -0.459). 추정 해석: 활성 돌파/추세 구간은
며칠 연속으로 큰 상승 캔들이 나오고 그 사이 저점이 들쭉날쭉한 반면,
basing 단계는 좁은 range 안에서 매일 조금씩 저점을 높이는 안정적
패턴을 만들기 쉽다. 이는 "저점 상승=항상 긍정적"이라는 naive 가정이
Daily 시간축에서는 성립하지 않을 수 있음을 보여주는 사례다 — §18에서
방향을 뒤집어 HIGH로 채택했다(부호 반대 방향의 유효 신호).

`rolling_low_5d_change`(최근 5일 최저 vs 그 이전 5일 최저)도 같은 방향
(POSITIVE vs EARLY/NONE Delta -0.267)으로 나타나 위 해석과 일관된다.

==================================================
11. Volatility Research
==================================================

**Hypothesis D**(FALSE_TRIGGER는 breakout 후 hold quality가 약하거나
daily volatility가 높을 수 있다) — **volatility 쪽만 부분 지지**.

`atr_14_pct`: GOOD_TRIGGER vs NO_SETUP Delta -0.753(GOOD이 더 낮은
변동성), GOOD_TRIGGER vs TOO_EXTENDED Delta -1.000(n=3, 완전분리이나
small-n). GOOD vs FALSE_TRIGGER Delta -0.333으로는 약함 — FALSE_TRIGGER
자체가 유독 변동성이 큰 것은 아니고, 오히려 극단적으로 확장된
TOO_EXTENDED 표본이 변동성 신호를 지배한다.

median atr_14_pct(전체 40) = 3.71%(p25 2.41% / p75 5.52%). 실제
TOO_EXTENDED(000650_20251226 천일고속)는 23.7%, TOO_LATE(032820_20260327
우리기술)는 14.3%로 median의 4~6배에 달한다 — §16 사례 참고.

`recent_5d_max_gap_abs_pct`는 GOOD_TRIGGER vs NO_SETUP Delta -0.901,
GOOD_TRIGGER vs FALSE_TRIGGER -0.833, GOOD_TRIGGER vs TOO_EXTENDED -0.852로
40개 feature 중 가장 일관되게 강한 분리력을 보였다 — GOOD_TRIGGER는
최근 5일 내 큰 갭이 거의 없는(median 1.6%) 반면, NO_SETUP/FALSE/
TOO_EXTENDED는 갭 변동성이 훨씬 크다. §18 HIGH 후보 중 가장 근거가
탄탄한 feature다.

==================================================
12. Volume Participation Research
==================================================

**Hypothesis F**(Daily volume participation은 GOOD과 EARLY/NONE 구분에
보조적으로 도움될 수 있다) — **혼재된 결과, 단독 채택 보류**.

`volume_vs_20d_avg`: GOOD_TRIGGER vs FALSE_TRIGGER Delta 0.722(GOOD이 더
높은 거래 참여)로 방향은 가설과 일치하지만, GOOD_TRIGGER vs TOO_EARLY
Delta -0.222로 부호가 뒤집힌다(TOO_EARLY 쪽이 오히려 거래량이 살짝
높음 — 초기 관심 유입과 실제 돌파 참여가 다른 신호일 수 있음).
POSITIVE_STRUCTURE vs EARLY_OR_NONE Delta 0.114로 전체적으로는 약함.

`up_day_volume_ratio_10d`(상승일 거래량 비중)는 GOOD_TRIGGER vs
TOO_EXTENDED Delta -0.556로 나타났으나 부호가 가설과 반대(TOO_EXTENDED가
상승일 거래 비중이 더 높음 — 과열 국면 자체가 상승일에 거래가 몰리는
경향과 겹쳐서 나타난 것으로 추정). 전체적으로 Volume family는 이번
40-sample에서 뚜렷한 단독 신호를 주지 못했다 — §18에서 HIGH 채택하지
않는다.

==================================================
13. Human Label Separation
==================================================

전체 요약은 커밋된
`artifacts/pattern_a_fast/research/daily_timing_feature_summary_v01.csv`
(50개 feature × count/mean/median/std/min/max/p25/p75 + 7개 human_label별
effective n/median/iqr + 5개 weekly_stage별 + 4개 Research Group별 + 4개
pair comparison(Cliff's Delta/median diff/standardized effect) + SETUP_GOOD
vs WATCH_EARLY_NONE pair)가 단일 source-of-truth다.

effective n 원칙: 모든 label_n/stage_n/group_n은 dropna 이후 실제 분석
표본 수다(Phase 13E Correction의 실수를 처음부터 재발시키지 않도록
`build_summary()`를 처음부터 `group[feature].dropna()` 기준으로 작성).
`test_summary_csv_effective_n_sum_matches_count_for_every_feature`가 커밋된
CSV 전체(50개 feature)에 대해 `sum(label effective n) == count`를 직접
검증한다.

각 label의 raw n과 event-conditioned feature의 effective n이 다를 수
있음에 유의: 예를 들어 GOOD_TRIGGER는 raw 9명이지만
`days_since_20d_close_breakout`에서는 effective n=6(3명은 최근 20일
내 breakout이 없어 NaN)이다.

==================================================
14. Weekly Stage Conditioned Analysis
==================================================

**SETUP(n=10) 내부 분해**: GOOD_TRIGGER 7 / BORDERLINE_TRIGGER 2 /
TOO_EARLY 1. GOOD_TRIGGER 7개의 `atr_14_pct`는 1.87%~3.91% 범위로 좁게
모여 있고(median 2.97%), `close_vs_dma200_pct`는 -7.8%~+16.7%로 넓게
퍼져 있다 — 즉 SETUP 단계 GOOD 진입은 "장기 이평과의 이격도"보다
"변동성이 안정적인가"가 더 일관된 신호로 보인다.

**TREND/EXTENDED(n=5) 신규 진입 관점**: TREND의 한화에어로스페이스(GOOD_
TRIGGER, 012450_20230630)는 `close_vs_dma200_pct`=+46.0%, `atr_14_pct`=
5.23%로 SETUP 그룹보다는 확장됐지만 극단적이지 않다. 반면 TREND의
우리기술(TOO_LATE, 032820_20260327)은 `close_vs_dma200_pct`=+250.3%,
`atr_14_pct`=14.3%로 같은 TREND 단계에서도 수치가 5배 이상 차이난다.
EXTENDED(n=3)는 전부 TOO_EXTENDED이며 `close_vs_dma200_pct`가
+17.6%~+400.7%까지 퍼져 있다 — "EXTENDED 단계는 늦은 daily 특징이
보이는가"에는 방향성으로는 YES이지만 크기 편차가 매우 커서 절대
threshold를 정할 근거는 없다(n=5, §32 Small-N Guard).

**SETUP → GOOD_TRIGGER vs WATCH → TOO_EARLY/NO_SETUP** (n_SETUP_GOOD /
n_WATCH_EARLY_NONE 컬럼): `close_vs_dma200_pct` Delta 0.661,
`dma60_vs_dma120_pct` Delta 0.554, `recent_5d_max_gap_abs_pct` Delta
-0.554로, POSITIVE_STRUCTURE vs EARLY_OR_NONE(전체 label 기준)과 방향/
크기가 유사하다 — Weekly Stage로 조건화해도 결론이 크게 달라지지
않는다는 뜻이며, 이는 Daily 신호가 Weekly Stage와 독립적으로도 일정한
분리력을 유지함을 시사한다.

==================================================
15. Correlation / Redundancy
==================================================

Spearman |corr| >= 0.85 pair 34개(전체 34쌍, `daily_timing_feature_correlation_v01.csv`).
설계 단계에서 미리 예상하고 회피한 완전 중복 1건을 실제로 확인:

`distance_to_prior_20d_high_pct` ↔ `close_breakout_strength_20d`:
spearman = 1.0(완전 동일값, §6에서 문서화한 대로 같은 수식). §18 HIGH
후보에는 `distance_to_prior_20d_high_pct` 하나만 남긴다(현재는 둘 다
HIGH가 아니므로 실질 영향 없음, 향후 라운드에서 주의).

그 외 강한 redundancy 예:

- `dma5_slope_1d` ↔ `daily_return_5d`(0.999), `dma20_slope_1d` ↔
  `daily_return_20d`(0.998) — MA slope와 단순 수익률이 사실상 동일값.
- `close_vs_dma60/120/200_pct` 삼각 클러스터(0.89~0.89) — 장기 MA
  이격도들은 서로 강하게 얽혀 있다. §18에서는 `close_vs_dma200_pct` 하나만
  대표로 채택했다.
- `post_breakout_close_hold_ratio_20d` ↔ `days_closed_above_breakout_level_20d`
  (0.977) — 비율/절대개수 쌍, Weekly 13E와 동일 패턴.
- `atr_14_pct` ↔ `realized_volatility_20d`(0.938) — §18에서 `atr_14_pct`
  하나만 대표로 채택.
- Breakout-hold family(`post_breakout_min_low_vs_level_pct_20d` 등) ↔
  `recent_10d_max_runup`(-0.944, -0.885) — event-conditioned subset
  feature가 event 유무와 무관한 momentum feature와도 강하게 얽혀 있다.

같은 latent concept을 HIGH에 중복 채택하지 않는다는 원칙(§16/§18)에
따라 위 클러스터마다 대표 1개만 선택했다.

==================================================
16. Critical Case Studies
==================================================

**A. 안국약품(001540_20260213, TRIGGER→GOOD_TRIGGER, 유일 explicit Human
Trigger)**: `days_since_20d_close_breakout`=0.0(reference 당일이 돌파
자체), `distance_to_prior_20d_high_pct`=+0.8%(직전 고점 바로 위),
`close_vs_dma200_pct`=+10.4%(과열 아님), `atr_14_pct`=2.66%(median
수준), `range_position_10d`=0.946(10일 range 최상단), `close_location_
in_daily_range`=0.826(종가가 당일 고가권). 요약: "직전 20일 고점을
방금 넘어선 날, 장기 이평과는 과열되지 않은 거리, 종가는 당일 고가권"
— 임계값 튜닝 없이도 이 사례 하나만으로 정성적 일관성을 확인했다.

**B. 현대해상(001450_20260116, SETUP→GOOD_TRIGGER)**: `days_since_20d_
close_breakout`=14.0(2주 전 돌파, 최근 새 돌파는 아님), `pullback_from_
20d_high_pct`=-15.3%(20일 고점 대비 상당히 조정됨), `range_position_
10d`=0.137(10일 range 하단권), `higher_daily_low_count_10d`=3.0. 요약:
SETUP 단계에서 이미 조정을 거친 뒤의 재진입 관점 — 안국약품(A)과 달리
"막 돌파" 신호가 아니라 "조정 후 하단권"에서 관측됐다.

**C. 오리온홀딩스(001800_20250321, SETUP→GOOD_TRIGGER)**: `days_since_
20d_close_breakout`=1.0(직전날 돌파), `range_position_10d`=0.556(중간),
`atr_14_pct`=1.87%(낮은 변동성). 건강한 구조 progression 사례로 A와
유사하게 "최근 돌파 + 안정적 변동성" 조합.

**D. 대한항공(003490_20250905, SETUP→GOOD_TRIGGER)**: `days_since_20d_
close_breakout`=9.0, `pullback_from_20d_high_pct`=-8.2%,
`recent_5d_max_gap_abs_pct`=0.64%(매우 낮음), `atr_14_pct`=2.27%. 과열
없이 안정적인 timing — 수익률 자체는 크지 않았지만 daily 변동성/갭이
낮게 유지된 사례.

**E. LG이노텍(011070_20200925, SETUP→GOOD_TRIGGER)**: `days_since_20d_
close_breakout`=11.0, `close_location_in_daily_range`=0.917(당일 고가권
마감), `lower_wick_pct`=2.0%(아랫꼬리 존재, 저점 지지 흔적). 정석
Positive progression.

**F. 우리기술 Pair(032820)**: SETUP→GOOD_TRIGGER(20251226) vs
TREND→TOO_LATE(20260327). `close_vs_dma200_pct` +8.8% → +250.3%(28배),
`atr_14_pct` 3.66% → 14.3%(3.9배), `daily_return_20d` -5.7% → +41.1%,
`pullback_from_20d_high_pct` -11.3% → -22.5%. **Phase 13F에서 가장
극명한 pair**: 같은 종목이 3개월 사이 "적당한 눌림, 낮은 변동성"에서
"장기 이평 대비 2.5배 확장, 20일 고점 대비 여전히 -22.5%(이미 훨씬 더
높은 고점에서 조정 중)"로 완전히 다른 daily 구조를 보였다.

**G. 천일고속 Pair(000650)**: WATCH→TOO_EARLY(20250926) vs
EXTENDED→TOO_EXTENDED(20251226). `close_vs_dma200_pct` +1.4% → +400.7%
(286배), `atr_14_pct` 1.99% → 23.7%(11.9배), `daily_return_20d` -3.1% →
+233.6%. 아무 Trigger 없는 상태에서 초대형 과열까지의 이동을 daily
extension feature가 극단적으로 세밀하게 포착했다 — 13F 가설 B의 가장
강력한 실증 사례.

**H. 삼성전기(009150_20260327, EXTENDED→TOO_EXTENDED)**: `close_vs_
dma200_pct`=+85.7%, `atr_14_pct`=6.67%, `recent_5d_max_gap_abs_pct`=5.7%
(median의 3.6배). reference 이후 더 크게 상승했지만 PIT 신규 진입
위치는 이미 확장 상태였음을 daily feature가 보여준다.

**I. 선광(003100_20250822, WATCH→FALSE_TRIGGER)**: `days_since_20d_
close_breakout`=NaN(최근 20일 내 돌파 이벤트 없음 — "약한 돌파"가
아니라 애초에 이벤트 자체가 이 window에서 관측 안 됨), `close_location_
in_daily_range`=0.722(고가권 마감), `lower_wick_pct`=0.69%(아랫꼬리
거의 없음). "윗꼬리 실패/거래량 실패"의 명시적 daily 단서는 이번
window에서 뚜렷하지 않았다 — reference 이후 실패 데이터는 사용하지
않았으므로 이 사례는 결론을 내리기보다 한계로 기록한다(§19).

**J. 서흥(008490_20250328, WATCH→FALSE_TRIGGER)**: `close_vs_dma200_
pct`=-13.9%(오히려 장기 이평 아래), `pullback_from_20d_high_pct`=
-13.5%. reference 시점 자체가 이미 구조적으로 약한 위치였음을 daily
feature가 보여준다.

**K. 삼화전기(009470_20250627, WATCH→FALSE_TRIGGER)**: `close_vs_dma200_
pct`=-16.9%, `days_since_20d_close_breakout`=8.0(약한 돌파는 있었으나
장기 이평 아래에서 발생).

**L. LG디스플레이(034220_20200925, WATCH→FALSE_TRIGGER)**: `days_since_
20d_close_breakout`=10.0, `dma20_vs_dma60_pct`=+13.1%(단기 정배열은
확인되나), `range_position_10d`=0.023(10일 range 최하단 — 돌파 흔적과
현재 위치가 모순). FALSE_TRIGGER 4개는 개별 evidence 기준으로만
해석했다(small n).

**M. HS화성(002460_20250509, WATCH→BORDERLINE_TRIGGER)**: `range_
position_10d`=0.789(range 상단권), `days_since_20d_close_breakout`=9.0,
`pullback_from_20d_high_pct`=-0.8%(거의 고점). Weekly higher-low는
좋았지만 major high breakout이 부족했던 샘플 — Daily 기준으로는 오히려
range 상단권에서 constructive하게 관측됐다.

**N. 한화솔루션(009830_20250328, WATCH→BORDERLINE_TRIGGER)**: `close_
vs_dma200_pct`=-14.5%(장기 이평 아래), `days_since_20d_close_breakout`=
NaN(최근 돌파 이벤트 없음). 13E correction에서 stale breakout 근거를
폐기한 샘플인데, Daily에서도 명확한 새 timing evidence는 나타나지
않았다 — 여전히 애매한 구조로 남는다(13E의 결론과 일관).

**O. 에이프로젠바이오로직스(003060_20260327, WATCH→NO_SETUP, 이후
초대형 급등)**: `close_vs_dma200_pct`=-45.3%, `recent_5d_max_gap_abs_
pct`=11.4%(median의 7배), `atr_14_pct`=11.4%. reference 시점 자체는
장기 이평 아래 + 변동성 급증 상태였다 — 미래 급등을 설명하려고 이
값을 억지로 Positive로 만들지 않았다(w.md 명시 지시 준수). 동전주
Investability observation은 이 Feature 계산과 무관하게 별도 축으로
남긴다(raw price filter 추가 없음).

**P. 에이치엠넥스(036170_20251226, SETUP→GOOD_TRIGGER)**: `close_vs_
dma200_pct`=-7.8%(장기 이평 아래에서도 GOOD 진입), `atr_14_pct`=1.97%
(median보다 낮음), `days_since_20d_close_breakout`=NaN. 구조적 Positive
사례지만 close_vs_dma200_pct가 음수인 채로 GOOD_TRIGGER가 나왔다는 점은
§18에서 이 feature 단독으로는 완벽한 분리자가 아님을 보여주는 반례로도
함께 기록한다.

==================================================
17. Monthly + Weekly + Daily Incremental Value
==================================================

`monthly_weekly_daily_research_join_v01.csv`(13D HIGH 7개 + 13E HIGH 7개
+ 13F 전체 feature)로 Daily HIGH 후보와 Monthly/Weekly HIGH 후보 간
Spearman 상관을 확인했다.

**핵심 발견 — Daily MA-구조 feature는 Weekly와 상당히 겹친다**:
`close_vs_dma200_pct`는 `WEEKLY_wma52_slope_1w`와 corr=0.91,
`WEEKLY_wma12_vs_wma26_pct`와 0.86, `MONTHLY_range_position_24m`과 0.73.
`dma20_vs_dma60_pct`는 `WEEKLY_rolling_low_4w_change`와 0.84. 즉 이 두
Daily MA-구조 feature는 Weekly가 이미 포착한 정보를 daily 해상도로
다시 보여주는 성격이 강하다 — "Weekly의 그림자"에 가깝다.

**나머지 5개 Daily HIGH 후보는 Monthly/Weekly와 거의 독립적**:
`recent_5d_max_gap_abs_pct`, `higher_daily_low_count_10d`,
`gap_from_prev_close_pct`, `lower_wick_pct`, `atr_14_pct` — 이 5개는
Monthly/Weekly HIGH 어느 것과도 |corr| >= 0.6인 쌍이 하나도 없었다.
이들이 이번 Phase에서 확인된 **genuine timing-specific incremental
value**다(§7.9 range_position family는 §18에서 HIGH 기준을 통과하지
못해 이 비교에서 제외).

Q1(Monthly/Weekly가 좋은데 Daily가 TOO_LATE/TOO_EXTENDED 위험을 추가로
보여준 사례)/§16-F,G,H가 정확히 이 사례다 — Weekly 13E HIGH 기준으로도
"좋은 구조"로 보일 수 있는 종목이 Daily 기준으로는 이미 극단적으로
확장돼 있음을 갭/변동성/장기이평 이격도가 별도로 보여줬다.

Q2(Weekly SETUP인데 Daily가 아직 이른 사례)는 §16-B(현대해상)처럼
SETUP 단계 자체 내에서도 daily 관점의 "막 돌파" vs "조정 후 재진입"
차이가 존재함을 보여줬다(둘 다 GOOD_TRIGGER로 발전했으므로 "이르다"의
반증이 아니라 daily 위치 자체가 다양할 수 있다는 확인).

Q3(SETUP + Daily 건강 = GOOD_TRIGGER와 일치하는가)은 §14의 SETUP
내부 분해로 일부 확인됐다 — ATR 안정성이 GOOD_TRIGGER 7개에서 일관되게
낮은 범위(1.9~3.9%)에 모여 있었다.

Q4(FALSE_TRIGGER가 reference 시점 이미 약한 daily 경고를 보였는가)는
혼재됐다 — §16-J/K는 장기 이평 아래(구조적 약점) 신호가 있었지만,
§16-I(선광)는 뚜렷한 daily 경고가 관측되지 않았다. 4개 표본으로는
결론을 내릴 수 없다(§32).

Q5(Daily가 Weekly의 단순 복제인지)는 위 "핵심 발견"으로 이미 답했다 —
일부(MA 구조)는 복제에 가깝고, 일부(갭/ATR/range/저점 카운트/윗꼬리)는
독립적이다.

Q6(Daily가 아무것도 추가하지 못하는 sample)는 §16-N(한화솔루션)이
해당한다 — Weekly/Daily 모두 명확한 timing evidence를 주지 못했다.

==================================================
18. HIGH / MEDIUM / LOW Candidates
==================================================

**HIGH(7개)** — 각각 서로 |corr|<0.85(§15), POSITIVE_STRUCTURE vs
EARLY_OR_NONE(n=40, 가장 안정적인 전체-표본 비교) 기준 |Cliff's Delta|
>= 0.34, 사례 연구와 일관. 최종 HIGH 선정 전 8개 후보(아래 7개 +
`range_position_10d`) 전수 쌍의 spearman 상관행렬을 계산해 family
집중도와 pairwise redundancy를 명시적으로 확인했다 — 그 결과
`range_position_10d`를 `higher_daily_low_count_10d`와의 0.745
redundancy를 근거로 HIGH에서 제외했다(아래 §18-후반부). 남은 7개
사이에는 |corr|>=0.85 쌍은 없지만, family 내부 상관이 0.6~0.8대로
존재하는 쌍이 있어 "완전히 독립적"이라고 주장하지 않는다:

1. `close_vs_dma200_pct` — Delta 0.569(전체). Weekly와 상관 0.7~0.9로
   높음(§17) — 독립적 신호로서의 가치는 제한적이나, 여전히 40-sample
   전체에서 가장 안정적인 분리력을 보였다. 같은 7.1 family인
   `dma20_vs_dma60_pct`와 spearman 0.666(<0.85지만 무시할 수 없는 수준).
2. `dma20_vs_dma60_pct` — Delta 0.600. Weekly(`rolling_low_4w_change`)와
   상관 0.84, 독립성은 제한적. 7.1 family가 HIGH 7개 중 2자리를 차지한다.
3. `recent_5d_max_gap_abs_pct` — Delta -0.475(GOOD vs NO_SETUP -0.901,
   vs FALSE -0.833, vs TOO_EXTENDED -0.852). Monthly/Weekly와 상관 낮음,
   가격대(reference-day 종가)와도 spearman -0.044로 사실상 무관(저가주
   변동성 착시 아님을 확인) — **가장 신뢰도 높은 genuine daily 신호**.
   단 같은 7.10 family인 `atr_14_pct`와 spearman 0.791로 상당히
   겹친다(아래 7.10 family 註 참고).
4. `higher_daily_low_count_10d` — Delta -0.459. **부호가 naive
   가정과 반대**(§10) — POSITIVE_STRUCTURE가 오히려 낮은 값을 가짐.
   해석은 아직 가설 단계이나 분리력 자체는 40-sample 전체에서 일관됨.
5. `gap_from_prev_close_pct` — Delta 0.396. `recent_5d_max_gap_abs_pct`/
   `atr_14_pct`와 |corr|<0.1로 사실상 독립적인 별도 신호(같은 7.10
   family이지만 방향성 있는 단일-갭 vs 크기 중심 지표라 실제로도 거의
   안 겹친다). 단 40개 중 정확히 0.0인 샘플이 7개(17.5%) — 갭 없이
   전일 종가로 그대로 시가가 형성된 경우가 드물지 않다는 한계를 §19에
   기록한다.
6. `lower_wick_pct` — Delta -0.396. candle-location family 유일 HIGH.
7. `atr_14_pct` — Delta -0.341(GOOD vs NO_SETUP -0.753). Monthly/
   Weekly와 상관 낮음, 가격대와도 spearman 0.111로 무관, Hyp D 부분
   지지.

**7.10 family 집중도에 대한 명시적 註**: `recent_5d_max_gap_abs_pct`,
`gap_from_prev_close_pct`, `atr_14_pct` 3개가 HIGH 7개 중 3자리(7.1
family 2개와 합쳐 5/7)를 차지한다. `recent_5d_max_gap_abs_pct` ↔
`atr_14_pct` spearman 0.791은 §15의 0.85 threshold는 넘지 않지만 "5일
최대 절대 갭"과 "14일 평균 변동성"이 상당 부분 같은 근본 개념(단기
변동성 크기)을 잰다는 뜻이다 — 둘 다 남겨둔 이유는 `gap_from_prev_
close_pct`가 이 둘과 거의 무관(<0.1)해 family 전체가 한 latent
concept로 붕괴하지는 않기 때문이지만, 향후 Feature Selection 단계에서
`atr_14_pct`와 `recent_5d_max_gap_abs_pct` 중 하나를 통합할 후보로
우선 검토해야 한다(§24에 반영).

`range_position_10d`(Delta -0.271)는 이번 라운드 HIGH 바를 넘지
못했다 — `higher_daily_low_count_10d`와 spearman 0.745로 이미 HIGH에
있는 low-structure 신호와 상당히 겹치고, Delta 자체도 8개 후보 중
가장 약했다. **§7.9 Range Position family는 이번 40-sample에서 HIGH
기준을 통과하는 대표 feature를 내지 못했다** — family 커버리지를
이유로 억지로 포함하지 않는다(HIGH는 최대 개수 제약이지 최소 채움
의무가 아니다). MEDIUM으로 남긴다.

`close_breakout_strength_20d`는 `distance_to_prior_20d_high_pct`와
spearman 정확히 1.0인데, 이는 표본에서 우연히 관측된 empirical
redundancy가 아니라 **두 feature가 항상 동일한 수식**
(`close[-1]/prior_20d_high - 1`)을 계산하도록 설계된 definitional
duplicate다(§6). 따라서 이 쌍은 "중복 발견"이 아니라 "의도적으로 한
번만 구현한 것을 두 family 이름으로 문서화"한 것에 가깝다.

**MEDIUM**: `range_position_10d`(위 사유), `days_since_20d_close_
breakout`(표면 Delta 0.700이지만 EARLY_OR_NONE 쪽 effective n=2로
fragile — §8), `daily_return_20d`/`dma20_slope_1d`(사실상 동일값, 서로
corr 0.998 — 대표 하나만도 HIGH엔 못 미치는 약한 Delta), `close_vs_
dma120_pct`(HIGH 후보들과 강한 redundancy), `daily_return_10d`,
`recent_10d_max_runup`, `pullback_from_20d_high_pct`, `close_vs_
recent_5d_high_pct`, `close_location_in_daily_range`, `range_
position_20d`, `volume_vs_20d_avg`.

**LOW / REJECTED**:
- `close_above_prior_20d_high`/`high_above_prior_20d_high`(boolean,
  희귀/상수에 가까움 — §8).
- `post_breakout_close_hold_ratio_20d`와 그 파생(`days_closed_above_
  breakout_level_20d`) — 부호가 가설과 반대이고 n=5 vs n=2로 신뢰
  불가(§9).
- `up_day_volume_ratio_10d`, `volume_5d_vs_prior_20d` — 부호 불안정,
  가설 미지지(§12).
- `dma5_slope_1d`(daily_return_5d와 완전 중복), `close_breakout_
  strength_20d`(distance_to_prior_20d_high_pct와 완전 중복, spearman
  1.0).
- 나머지 diagnostic-only raw MA값(`daily_ma5/20/60/120/200`) — 순위
  분석 대상 아님(설계부터 diagnostic으로 분류).

HIGH Priority Candidates는 Production Feature 확정이 아니다(§21).

==================================================
19. Known Limitations
==================================================

1. Human Daily Entry Label이 없어(§2) 모든 결론이 기존 Weekly Outcome
   Label에 대한 간접 근거일 뿐이다 — Daily 자체의 ground truth는
   존재하지 않는다.
2. TRIGGER=1, TOO_LATE=1, TOO_EXTENDED=3, FALSE_TRIGGER=4로 small-n
   그룹이 많다(§32) — 이 그룹이 관련된 모든 pair delta는 descriptive로
   해석해야 한다.
3. Breakout-family(§7.5/§7.6) 전체가 event-conditioned subset(유효
   16~18/40)이라 이 family 기반 결론은 "40개 전체"가 아니라 해당
   subset으로 범위를 제한해야 한다(13E와 동일 교훈, §9).
4. `post_breakout_close_hold_ratio_20d`가 가설과 반대 방향으로
   나타난 원인(관찰 구간 길이 효과 가능성)은 검증되지 않은 가설이며,
   추가 조사 없이는 결론 내릴 수 없다(§9).
5. `higher_daily_low_count_10d`의 반직관적 부호(§10)도 마찬가지로
   해석 가설일 뿐 확정 결론이 아니다.
6. Daily MA-구조 HIGH 후보 2개(`close_vs_dma200_pct`,
   `dma20_vs_dma60_pct`)는 Weekly HIGH 후보와 상관이 높아(0.6~0.9)
   독립적 신호로서의 가치가 제한적이다(§17) — 향후 Feature Selection
   단계에서 중복 제거 대상으로 우선 검토할 후보다.
7. 이 40-sample은 Monthly(13D)/Weekly(13E) feature 발견에도 이미
   사용된 in-sample 집합이다(§23) — 세 timeframe의 결론이 서로
   일관되게 보이는 것 자체가 OOS 확인은 아니다.
8. HIGH 7개 중 5개(7.1 family 2개 + 7.10 family 3개)가 두 family에
   집중돼 있다(§18). `recent_5d_max_gap_abs_pct`와 `atr_14_pct`는
   |corr|<0.85 threshold는 넘지 않지만 spearman 0.791로 상당 부분
   같은 개념(단기 변동성 크기)을 재는 것으로 보인다 — 다음 Feature
   Selection 라운드에서 통합 검토 대상이다.
9. `recent_5d_max_gap_abs_pct`/`atr_14_pct`/`gap_from_prev_close_pct`가
   실제로는 저가주 변동성 착시(가격대가 낮을수록 %변동이 커 보이는
   효과)를 재는 것은 아닌지 reference-day 종가와의 spearman 상관으로
   확인했다: 각각 -0.044 / 0.111 / 0.09로 사실상 무관 — 가격대 효과가
   아님을 검증했다.
10. `gap_from_prev_close_pct`는 40개 중 7개(17.5%)가 정확히 0.0이다 —
    시가가 전일 종가와 완전히 동일하게 형성된 경우가 드물지 않다는
    뜻이며, 이는 feature 자체의 결함이라기보다 종목별 유동성/호가
    단위 차이를 반영할 수 있다(별도 조사 없이는 원인 미확정).

==================================================
20. No Daily Ground Truth Declaration
==================================================

Phase 13F는 Daily Entry Ground Truth를 만들지 않았다. 어떤 sample_id에
대해서도 "이 날이 최적 진입일이다"라는 라벨을 생성하지 않았고,
reference_date 전후로 더 나은 진입일을 미래 데이터에서 찾아 역산하지
않았다. 이 문서의 모든 Daily Feature 값은 reference_date 당시
PIT-sliced daily 데이터만으로 계산됐다.

==================================================
21. No Threshold Frozen
==================================================

이 Phase에서 결정하지 않은 것: Daily 숫자 threshold, Daily Score,
Classifier, Optimal Entry Date, Production Daily Feature Set. §18의
HIGH/MEDIUM/LOW는 연구 우선순위 분류일 뿐 production threshold가
아니며, 어떤 feature도 특정 값 이상/이하를 "합격"으로 규정하지 않는다.

==================================================
22. No Production Change
==================================================

`src/trend_scanner/patterns/`(Pattern A production evaluator)는 이번
Phase에서 전혀 수정되지 않았다. `pattern_a_fast_daily_features.py`는
production evaluator를 import하지 않으며(§24 item 31로 machine-check),
scanner pipeline에서도 import되지 않는다. Phase 10/11/12도 수정하지
않았다(§24 item 32, git diff --stat으로 재확인).

==================================================
23. OOS Separation
==================================================

현재 40 sample은 IN-SAMPLE HUMAN CALIBRATION SET이다. 13D, 13E, 13F
Feature를 전부 이 40개를 보고 발견했으므로, 향후 OOS 단계(Phase 13I
또는 별도 단계)에서 이 40개를 unseen 성능평가에 재사용하지 않는다.
unseen reference dates가 필요하다.

==================================================
24. Next Phase Recommendation
==================================================

1. §18 HIGH 7개 중 Weekly와 상관 높은 2개(`close_vs_dma200_pct`,
   `dma20_vs_dma60_pct`)의 중복 제거 여부, 그리고 서로 spearman
   0.791인 `recent_5d_max_gap_abs_pct`/`atr_14_pct`의 통합 여부를
   Feature Selection 단계에서 결정.
2. `higher_daily_low_count_10d`의 반직관적 부호와
   `post_breakout_close_hold_ratio_20d`의 관찰-구간-길이 가설을
   검증할 별도 synthetic/실증 조사(둘 다 §19에서 미해결로 남김).
3. `days_since_20d_close_breakout`처럼 event-conditioned subset이 큰
   표면 Delta를 보이는 경우, 향후 라운드에서는 effective n이 각
   비교 그룹에서 최소 4 이상일 때만 순위에 반영하는 명시적 gate를
   Research Script 자체에 추가하는 것을 고려(이번엔 문서 §8/§18에서
   수동으로 처리).
4. 13D + 13E + 13F가 모두 CLOSED되면, 세 timeframe Research Evidence를
   합쳐 Monthly + Weekly + Daily Feature Selection / Role Assignment
   (Gate/Score/Diagnostic 배정) 단계로 진행 — 이는 새 Feature를
   추가하는 단계가 아니라 기존 발견을 선별/구조화하는 단계다.
