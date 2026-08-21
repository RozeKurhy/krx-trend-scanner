pattern_a_fast_weekly_trigger_feature_research_v01.md

--------------------------------------------------------------------------------
0. Status / Base SHA
--------------------------------------------------------------------------------

Status: **WEEKLY TRIGGER FEATURE RESEARCH COMPLETE / ADVISOR REVIEW PENDING**
(§37 Final Status Rule — 이번 커밋으로 Phase 13E를 자동 CLOSED하지 않는다)

Base Commit: `6917b1341553b58fa42390ba1507fc9b80551fee` (Phase 13D CLOSED 시점)

**[Correction 반영]** Base Commit `db9e09e3b48a0743b07ee2a60bfe589d6f02a2f5`
(최초 13E 연구 완료 시점)에서 advisor review로 발견된 breakout search
horizon 버그(`_find_breakout_event`가 search horizon 제한 없이 전체
이력을 backward scan해 최대 152주 전 stale breakout까지 breakout_level로
사용하던 문제)를 수정했다. `weeks_since_26w_close_breakout`은 이제
reference 기준 최근 26 completed weekly observation(offset 0..25)
안에서만 breakout을 검색하고, horizon 밖은 NOT_OBSERVED(NaN)로 처리한다.
이 문서의 §7/§8/§13/§15/§17이 이 correction을 반영해 갱신됐다 — 특히
기존 "U자형 sweet-spot" 해석은 **폐기**됐다(§7).

--------------------------------------------------------------------------------
1. Research Purpose
--------------------------------------------------------------------------------

Phase 13D는 Monthly Feature가 장기 환경(허용/차단)을 잘 구분할 수 있음을
확인했다(HIGH 후보 7개). Phase 13E는 그 다음 질문에 답한다: "월봉 환경이
허용된 종목 중, 어떤 주봉 구조가 실제 GOOD_TRIGGER로 이어졌는가?" Monthly가
permission을 주고 Weekly가 trigger를 당긴다는 Pattern A Fast 철학을 데이터로
검증한다. Production Rule/Threshold/Classifier/Score는 만들지 않는다 —
§19/§33 참고.

--------------------------------------------------------------------------------
2. Human Calibration Set
--------------------------------------------------------------------------------

`artifacts/patterns/pattern_a_fast/validation/ground_truth/pattern_a_fast_human_review_v01.csv`에서
`weekly_stage_at_reference != UNLABELED AND human_label != UNLABELED`인 정확히
40개(13C-2 CLOSED/FROZEN, 재사용 — 재라벨링 없음). 나머지 20개(UNLABELED)는
`load_labeled_samples()`의 필터 자체가 구조적으로 제외한다(§20 item 13,
`test_matrix_has_exactly_40_unique_labeled_samples`로 커밋된 matrix output을
직접 검증).

PIT Stage Distribution: WATCH=24, SETUP=10, TRIGGER=1, TREND=2, EXTENDED=3.

Human Outcome Distribution: GOOD_TRIGGER=9, BORDERLINE_TRIGGER=6,
FALSE_TRIGGER=4, TOO_EARLY=8, TOO_LATE=1, TOO_EXTENDED=3, NO_SETUP=9.
label 인원수 자체는 고정이며 40개 어느 sample도 분석에서 제외되지 않는다.
다만 feature마다 required_history_bars/missing_behavior가 달라(§8) pair
comparison에 쓰이는 유효 n은 feature별로 다르다 — 예: `weeks_since_26w_
close_breakout`은 Correction 후(§1) TOO_EARLY 8개 중 6개가 최근 26주
내 breakout event 없음(NOT_OBSERVED)이라 그 feature에 한해 유효 n=2다
(대부분의 다른 feature는 40개 전체가 유효). 이 유효 n은 summary CSV의
`missing_count`/그룹별 `n` 컬럼에 feature마다 기록돼 있다.

이 40개는 prevalence estimation dataset이 아니라 calibration / feature
discovery dataset이다. label 비율을 시장 실제 발생 확률로 해석하지 않는다.

--------------------------------------------------------------------------------
3. PIT Leakage Contract
--------------------------------------------------------------------------------

모든 Weekly Feature는 `weekly.index <= reference_date`만 사용한다.
`compute_weekly_trigger_features(weekly)`는 `weekly` DataFrame 하나만
받는다 — human_label / weekly_stage_at_reference / trigger_event_date는
함수 시그니처에 존재하지 않는다(§20 item 1-4로 시그니처 자체를 검증).

리크 방지 기계 검증:
- `test_feature_computation_is_deterministic`, `test_future_daily_row_
  append_does_not_change_reference_week_features`(§20 item 5 — raw daily에
  실제 미래 행을 append한 뒤 전체 파이프라인 재실행, feature 값 불변 확인),
  `test_incomplete_future_week_does_not_affect_features`(item 6).
- `build_feature_matrix()` 내부 assert:
  `snapshot.weekly.empty or snapshot.weekly.index.max() <= reference_date`
  로 매 샘플마다 기계 검증.
- `test_current_week_excluded_from_prior_high_family`(item 7, §24 CASE B와
  동일 취지를 §7.3 distance feature에도 적용) — reference 자신의 고가를
  prior high 분모 계산에서 반드시 제외한다.

--------------------------------------------------------------------------------
4. Completed Weekly Contract
--------------------------------------------------------------------------------

기존 `build_historical_snapshot(..., include_incomplete_periods=False)`를
그대로 재사용한다. **신규 공통 helper 변경 1건**을 별도 보고한다(§30 Frozen
Files 취지 준수, "정말 공통 helper가 필요하면 최소 변경만 허용하고 반드시
별도 보고"):

`src/trend_scanner/validation/historical_snapshot.py`의 `HistoricalSnapshot`
dataclass에 `weekly: pd.DataFrame` 필드를 추가했다. 기존 `monthly` 필드(Phase
13D가 동일한 이유로 이미 추가했던 것)와 완전히 대칭인 최소 변경이며:
- `build_historical_snapshot()` 내부에서 이미 지역변수로 계산되던 `weekly`를
  그대로 반환값에 노출시켰을 뿐, 계산 로직/값은 전혀 바뀌지 않았다.
- 새 필드는 `default_factory`로 빈 DataFrame을 기본값으로 둬서, 기존
  keyword-construction 호출부(`tests/test_pattern_a_stage.py`의
  `_make_snapshot`)를 깨지 않는다.
- 변경 후 기존 테스트 58개(`test_pattern_a_stage.py` +
  `test_pattern_a_fast_ground_truth*.py` + 13D 테스트) 전부 재통과 확인.
- **"기존 결과 불변" 증명**: Phase 13D 스크립트를 재실행해 3개 output CSV
  (`monthly_regime_feature_{matrix,summary,correlation}_v01.csv`)를 `diff`
  했고 바이트 단위로 완전히 동일함을 확인(exit 0) — 13D 산출물은 이번
  변경으로 전혀 바뀌지 않았다.

인덱싱 규칙(코드 작성 전 40개 샘플 전수로 경험적으로 확인 — 실제
`reference_date`가 완료된 금요일인지, 아니면 그 이전 마지막 완료 주인지가
모든 breakout feature의 인덱싱을 결정하는 문제였음):

```
weekly.index[-1] == reference_date  (40/40, 예외 없음)
```

따라서 `weekly.iloc[-1]`이 곧 reference week 자체다. 이를 바탕으로 두 가지
윈도우 규칙을 구분해서 적용한다:
- "현재 위치" 계열(MA, return, range position, momentum, higher-low count
  등): reference week을 포함(`iloc[-k:]`).
- "직전 구조" 계열(prior high, breakout state/age/hold): reference week을
  반드시 제외(`iloc[-(k+1):-1]`) — §24 CASE B가 정확히 이 혼동을 막기 위한
  테스트다.

--------------------------------------------------------------------------------
5. Weekly Feature Definitions
--------------------------------------------------------------------------------

`src/trend_scanner/research/pattern_a_fast_weekly_features.py`의
`FEATURE_SPECS`에 52개 Feature 전부(진단용 raw MA 4개 + 분석 대상 48개)
`feature_name`/`family`/`formula`/`required_history_bars`/`timeframe`/
`pit_safe`/`missing_behavior`/`human_interpretation`/`research_question`을
기계가 읽을 수 있는 형태로 문서화했다(§9 요구사항). 12개 Family(§7.1~§7.12)
전부 최소 1개 이상 구현했다.

w.md §7이 제안한 원시 후보는 훨씬 많았다(예: MA window 6종, breakout window
3종을 모든 하위 feature에 반복 적용 등). §14 correlation 경고("동일한
latent concept의 Feature 여러 개를 HIGH에 중복 추천하지 말 것")와 13D에서
드러난 교훈(37개 중 41쌍이 |corr|>=0.85)을 반영해, family는 12개 전부
유지하되 family 내부의 명백히 중복될 변형만 사전에 정리했다:

| Family | 구현 Feature 수(분석 대상) |
|---|---|
| 7.1 Weekly MA Structure | 10 (+진단용 raw MA 4: ma12/26/52/200) |
| 7.2 200-Week MA Resistance | 2 |
| 7.3 Prior High Proximity | 3 |
| 7.4 Breakout State | 2 |
| 7.5 Breakout Age | 1 |
| 7.6 Breakout Hold / Support | 4 |
| 7.7 Higher-Low Structure | 6 |
| 7.8 Support / Bottom Stabilization | 5 |
| 7.9 MA Compression / Expansion | 2 |
| 7.10 Momentum / Acceleration | 6 |
| 7.11 Extension / Late Entry | 5 |
| 7.12 False Breakout Risk | 2 |
| **분석 대상 합계** | **48 (+진단용 4 = 총 52)** |

사전에 스킵한 대표 사례(전부 코드 주석/이 문서에 이유 기록, w.md §14
"5개 유사 feature를 다 추천하지 말 것" 취지):
- `weekly_ma4`/`weekly_ma100`: ma4는 momentum family(7.10)의 4주 수익률과
  중복, ma100은 ma52/ma200 사이 정보로 두 형제와 강한 상관이 예상돼 스킵.
- `wmaN_slope_change_4w` 계열 4개 전부: `wmaN_slope_1w`가 이미 있고, 방향
  전환 정보는 momentum family의 `recent_4w_return_vs_prior_12w`가 유사한
  개념을 담당.
- `close_above/below_prior_13w/52w_high`(boolean): 26주만 대표로 남기고,
  13w/52w는 §7.3의 연속형 `distance_to_prior_Nw_high_pct`로 이미 커버.
- `recent_breakout_level_26w`(raw 가격): 종목마다 스케일이 달라 cross-
  sectional 비교가 무의미해 diagnostic으로도 노출하지 않음.
- `wma200_distance_crossing_state`(categorical BELOW/NEAR/ABOVE): "NEAR = 몇
  %"를 정하는 순간 threshold freeze가 되므로 이번 라운드에 생성하지 않음 —
  `close_vs_wma200_pct` 연속형 값이 primary evidence(§7.2 요구사항 그대로).
- `weekly_ma_dispersion_pct`: `weekly_ma_spread_pct`와 대수적으로 거의
  동일 정의가 되기 쉬워(13D의 `ma_spread_pct`/`max_ma_gap_pct` corr=1.000
  전례) 스킵.
- `recent_breakout_exists`(boolean 파생): `weeks_since_26w_close_breakout`이
  NaN인지로 대수적으로 완전히 유도 가능해 별도 feature로 만들지 않음.

--------------------------------------------------------------------------------
6. 200-Week MA Research
--------------------------------------------------------------------------------

`close_vs_wma200_pct`, `high_vs_wma200_pct`, `weeks_above_wma200_recent_12w`
3개를 구현. `weekly_ma200`은 진단용 raw. `weeks_above_wma200_recent_12w`는
매주 rolling 200주선을 다시 계산하지 않고 **reference 시점 고정값 근사**를
쓴다(§8 Pivot/Breakout Complexity Guard 취지 — 완전한 rolling 재계산은
과도한 복잡성). 이 근사를 formula/missing_behavior에 명시했다.

40개 중 10개는 200주(약 4년) 이력이 부족해 이 family 전체가 NaN이다
(fail-safe, §7.2 "200주 history가 없는 sample은 NaN, MA100/MA52로 silent
fallback 금지"를 그대로 준수). `test_insufficient_history_fails_safe_to_nan`
으로 검증.

Finding: `close_vs_wma200_pct`는 GOOD_TRIGGER vs NO_SETUP Cliff's Delta
**0.792**, GOOD_TRIGGER vs FALSE_TRIGGER **0.750**(n=3 descriptive)으로
상위권 — Q7(13D에서 이관된 질문, "주봉 200 이평 저항")이 Weekly에서 실제로
설명 가능함을 확인했다. `high_vs_wma200_pct`는 `close_vs_wma200_pct`와
spearman 0.992로 거의 완전 중복(고가/종가 버전 차이일 뿐) — MEDIUM으로
강등.

--------------------------------------------------------------------------------
7. Prior High / Breakout Research
--------------------------------------------------------------------------------

**Prior High Proximity(§7.3)**: `distance_to_prior_26w_high_pct`가
GOOD_TRIGGER vs NO_SETUP **0.753**로 강함. 13w/52w 버전과 각각 0.89/0.94
상관(형제, MEDIUM).

**Breakout State(§7.4) — 중요한 반직관적 발견**: `close_above_prior_26w_
high`, `high_above_prior_26w_high` 두 boolean feature가 **40개 중 39개가
항상 0**(유일한 1은 NO_SETUP/WATCH 샘플)이다. 즉 "reference 주 자체가
정확히 새 26주 고점을 찍는 순간"이라는 사건은 GOOD_TRIGGER를 포함해
거의 발생하지 않는다 — 이는 단순 통계적 사실(계단식 신고점 갱신이
아닌 이상 "이번 주가 정확히 그 순간"일 확률 자체가 낮음)이지 버그가
아니다(§24 CASE A/B 유닛 테스트로 로직 자체는 검증됨). 이 두 feature는
사실상 상수라 분리력이 없어 **LOW/REJECTED**로 분류했다 — 연속형인
`weeks_since_26w_close_breakout`(§7.5)이 이 정보를 훨씬 유용하게 담고
있다.

**Breakout Age(§7.5) — Correction 반영, U자형 해석 폐기**: 최초 구현은
`_find_breakout_event`가 backward scan에 search horizon 제한을 두지 않아
전체 이력을 뒤졌고, 그 결과 max offset=152(약 3년 전)인 stale event까지
breakout_level로 사용하는 버그가 있었다(advisor review로 발견,
`db9e09e` 시점). "weeks_since_**26w**_close_breakout"이라는 이름 자체가
최근 26주 이내여야 한다는 계약을 위반한 것이다. 이번 correction으로
`_find_breakout_event(close, high, k, search_horizon)`에 `search_horizon`
파라미터를 추가해 offset 0..25(최근 26 completed weekly observation)로
검색을 제한했다 — CASE 신규 regression test A~E(§24)로 boundary(offset
25=허용, offset 26=NOT_OBSERVED)까지 고정했다.

Correction 후 `weeks_since_26w_close_breakout`의 non-NaN 개수는
**40개 중 20개로 절반**까지 줄었다(최근 26주 내 breakout이 아예 없는
sample이 절반). human_label별 유효 n/median: GOOD_TRIGGER n=6 median=8.5,
NO_SETUP n=4 median=7.0, TOO_EARLY n=2 median=17.0, FALSE_TRIGGER n=2
median=4.0, TOO_EXTENDED n=3 median=4.0, TOO_LATE n=1 median=1.0,
BORDERLINE_TRIGGER n=2 median=11.5. Cliff's Delta는 GOOD vs NO_SETUP
**0.167**, GOOD vs TOO_EARLY **-0.583**로 correction 전(-0.309)과 방향도
강도도 다르게 나온다.

**기존 "U자형 sweet-spot" 해석은 폐기한다.** 원래 해석의 근거였던
"NO_SETUP median=61, TOO_EARLY median=56"이라는 큰 median 자체가 대부분
horizon 밖(NaN이어야 했을) stale event를 평균에 끌어들인 결과였다.
correction 후에는 애초에 그 그룹 대부분이 NaN(최근 26주 내 breakout
없음)이라 U자형을 그릴 만한 표본 자체가 남지 않는다. 대신 확인된 새
사실은: **최근 26주 내 breakout 존재 여부 자체가 이미 강한 정보**라는
것이다 — GOOD_TRIGGER(9개 중 6개, 67%)와 NO_SETUP(9개 중 4개, 44%)은
breakout이 있는 편이지만, TOO_EARLY는 8개 중 2개(25%)만 있다("아직
돌파가 없다"는 것이 TOO_EARLY 정의와 부합). 이 "존재 여부" 자체는 이번
correction 범위에서 별도 boolean feature로 새로 만들지 않았다(w.md §2가
기존 7개 feature의 semantics 수정만 요구했지 신규 feature 추가는 요구하지
않음) — Phase 13F 이후 연구 후보로만 기록한다(§22).

n=20/40(그리고 pair 비교에서는 6~9로 더 작아짐)이므로 `weeks_since_26w_
close_breakout`은 더 이상 HIGH 근거가 되지 못한다 — **MEDIUM으로 강등**
한다(§17).

--------------------------------------------------------------------------------
8. Breakout Hold / False Breakout Research
--------------------------------------------------------------------------------

**Correction 후에도 `post_breakout_min_low_vs_level_pct_26w`는 살아남았고
오히려 GOOD vs NO_SETUP에서 완전 분리(Cliff's Delta 1.000)로 강화됐다**
— n이 19(breakout이 최근 26주 내 있는 sample만)로 줄었지만, 그 19개
안에서는 GOOD_TRIGGER 6개 전원이 NO_SETUP 3개보다 값이 크다는 뜻이다.
GOOD vs TOO_EARLY **0.667**(correction 전 0.810보다 약해짐), SETUP→GOOD
vs WATCH→EARLY/NONE **0.800**, POSITIVE_STRUCTURE vs EARLY_OR_NONE
**0.900**. `post_breakout_min_close_vs_level_pct_26w`는 여전히 거의 동일한
정보(spearman **0.960**, 형제).

**중요(표본 크기 급감 caveat)**: 이 family 전체(§7.6)는 이제 "최근 26주
내 breakout이 있는 19개 sample"이라는 **더 좁은 subset**에서만 계산된다
— 40개 전체가 아니다. GOOD_TRIGGER는 9개 중 6개, NO_SETUP은 9개 중 3개만
이 subset에 포함된다(§7의 "존재 여부 자체가 신호"라는 관찰과 같은 맥락).
이 subset 안에서의 분리력이 강하다는 것과, 이 feature가 40개 전체를
설명한다는 것은 다른 주장이다 — 후자로 과장하지 않는다.

w.md §26 Hypothesis C("FALSE_TRIGGER는 breakout 발생보다 hold quality가
약할 것") 검증: FALSE_TRIGGER 중 breakout이 있는 2개(선광 `weeks_since=
6`, LG디스플레이 `weeks_since=2`, §15-E/H)의 `post_breakout_close_hold_
ratio_26w`는 각각 0.0/0.5로 낮고, `min_close_vs_level_pct`는 -0.13/-0.05로
마이너스 — Hypothesis C는 이 2개 사례에서는 지지되나 n=2로 descriptive
수준이다(§28). 서흥/삼화전기(§15-F/G)는 correction 후 breakout event
자체가 horizon 밖(또는 없음)이 돼 이 family에서 관찰 불가(NaN)가 됐다
— 이 두 sample은 더 이상 hold-failure 근거로 인용하지 않는다.

`weeks_closed_above_breakout_level_26w`(절대 카운트)는 GOOD vs NO_SETUP
**0.278**로 여전히 약함 — post window 길이가 sample마다 다르기 때문에
절대 카운트는 오염되고, 비율(`hold_ratio`)이 더 유효한 형태라는 결론은
correction 후에도 유지된다. LOW로 분류.

`higher_low_after_breakout_count`는 n=19로 줄었고, GOOD vs NO_SETUP
**0.167**, GOOD vs TOO_EARLY **-0.333**로 약함(FALSE_TRIGGER와의 비교는
n=2라 descriptive조차 어려움) — correction 전 "weeks_since와 corr 0.980
완전 중복"이라는 이유는 이제 두 feature 모두 값이 달라져 재확인이
필요하지만, 분리력 자체가 약해 여전히 LOW로 분류한다.

`close_back_below_breakout_level`(FALSE_TRIGGER의 가장 직접적인 machine
근사, §18/§19 Semantic Guard에 따라 "Human Trigger Event"가 아니라 machine
breakout candidate로만 명명)은 n=20, GOOD_TRIGGER vs NO_SETUP **-0.250**,
GOOD vs TOO_EARLY **-0.500**로 방향은 유지되나 약해짐 — MEDIUM에서
LOW/MEDIUM 경계로 조정.

--------------------------------------------------------------------------------
9. Higher-Low / Support Research
--------------------------------------------------------------------------------

`higher_weekly_low_count_13w`(GOOD vs NO_SETUP **0.765**)와
`rolling_low_4w_change`(GOOD vs NO_SETUP **0.704**)가 상위권. 8주 버전
(`higher_weekly_low_count_8w`, `weekly_low_slope_8w`)은 창이 짧아 노이즈가
많은지 상대적으로 약함(각각 0.370, 0.358) — 13주 이상 창이 이 family에서는
더 안정적이라는 것을 실증했다.

`distance_from_13w_low_pct`/`distance_from_26w_low_pct`는 방향이 **반직관적**
(GOOD vs NO_SETUP이 각각 -0.284/-0.086 — 저점에 더 가까운 쪽이 오히려
NO_SETUP 방향)이다. 원인 추정: SETUP 초입 sample(저점 근처, 아직 검증
안 됨)과 NO_SETUP 중 저점 회복 시도조차 없는 sample이 섞여 이 feature
단독으로는 방향성이 흐려진다 — LOW로 분류하되 이 caveat을 기록한다
(threshold tuning으로 "고치려" 하지 않음, §2 금지 사항 준수).

--------------------------------------------------------------------------------
10. Extension / Late Entry Research
--------------------------------------------------------------------------------

`range_position_52w`가 GOOD vs TOO_EARLY **0.806**, GOOD vs NO_SETUP
**0.728**로 강함. `range_position_26w`와 spearman 0.863(형제, MEDIUM).

`recent_8w_max_runup`은 **방향이 반직관적**이다: GOOD_TRIGGER vs NO_SETUP
**-0.901**(전체 중 절대값 최상위권인데 부호가 예상과 반대), GOOD vs
TOO_EXTENDED도 **-0.630**으로 음수다. 원래 가설(§7.11: "값이 클수록 이미
많이 상승")과 달리, 표본 안에서는 오히려 NO_SETUP 그룹에 최근 8주 내
극단적 변동(급등 또는 급락 재료성 노이즈)을 가진 종목이 섞여 있어
이런 부호가 나온 것으로 추정한다. §9-J(천일고속 EXTENDED→TOO_EXTENDED,
recent_8w_max_runup=10.13=1013%)에서는 가설대로 정방향으로 작동하는 것도
확인되므로, 이 feature는 그룹 전체 통계보다 개별 케이스에서 더 신뢰할
만하다 — **LOW/특이 findings**로 분류하고 원인을 확정하지 않은 채
투명하게 기록한다(threshold로 "고치지" 않음).

--------------------------------------------------------------------------------
11. Human Label Separation
--------------------------------------------------------------------------------

48개 feature 전체 × count/missing_count/mean/median/std/min/max/p25/p75 +
human_label별 n/median/IQR + Research Group별(13D와 동일:
POSITIVE_STRUCTURE/FAILED_STRUCTURE/EARLY_OR_NONE/LATE_OR_EXTENDED) +
weekly_stage별(§12 아래) + 주요 pair comparison(§13 요구사항 3종 전부:
`median_diff_*`, `standardized_effect_*`, `cliffs_delta_*` — 처음부터
포함, 13D에서 advisor가 지적한 실수를 이번엔 1회차부터 반영) +
POSITIVE_STRUCTURE vs EARLY_OR_NONE Research Group 비교까지 전부
`artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_feature_summary_v01.csv`
(48행)에 기록했다. `standardized_effect_*`의 분모는 두 그룹을 합친 전체
표본의 IQR이다(13D §5와 동일 caveat — 완벽 분리 시 오히려 작아질 수 있어
Cliff's Delta가 1차 근거).

**중요(표본 크기 주의)**: `TRIGGER` n=1, `TOO_LATE` n=1, `TOO_EXTENDED`
n=3, `FALSE_TRIGGER` n=4다. 이 그룹이 낀 pair comparison(`GOOD_TRIGGER vs
FALSE_TRIGGER`, `GOOD_TRIGGER vs TOO_EXTENDED`)은 descriptive로만
취급한다(§28). 주 근거는 `GOOD_TRIGGER(9) vs NO_SETUP(9)`,
`GOOD_TRIGGER(9) vs TOO_EARLY(8, breakout family에서는 결측이 많아
유효 n=2까지 줄어드는 feature도 있음)`,
`SETUP→GOOD_TRIGGER(7) vs
WATCH→TOO_EARLY/NO_SETUP(16)`, `POSITIVE_STRUCTURE(15) vs
EARLY_OR_NONE(17)`. 위 n은 breakout family 이외 대부분의 feature(40개
전체 계산됨)에 적용되는 label count다.

**Correction 이후 effective n 수정(Phase 13E Correction §5)**: 원래
`build_summary()`는 `{label}_n`/`STAGE_{stage}_n`/`GROUP_{group}_n`을
`len(group[feature])`(dropna 이전, 결측 포함 raw count)로 기록했다 —
n이 항상 label의 전체 인원수(예: GOOD_TRIGGER=9)로 고정 표시돼, breakout
family처럼 결측이 많은 feature에서도 마치 9명 전원이 유효한 것처럼
보이는 문제가 있었다. `len(g)`(dropna 이후)로 수정해 이제 `{label}_n`은
실제 그 feature에서 유효한 표본 수를 정확히 반영한다 — 예: breakout
family에서 `GOOD_TRIGGER_n=6`(9명 중 6명만 유효)으로 표시된다.
`n_SETUP_GOOD`/`n_WATCH_EARLY_NONE`도 동일하게 non-NaN count로 수정했다.
검증: 각 feature에서 `sum(label별 effective n) == count`(전체 non-NaN
개수)가 성립함을 synthetic matrix로 회귀 테스트했다
(`test_effective_n_sum_matches_feature_count`,
`test_setup_good_watch_early_none_n_matches_non_missing_count`, §24).

--------------------------------------------------------------------------------
12. Weekly Stage Separation
--------------------------------------------------------------------------------

`artifacts/patterns/pattern_a_fast/research/feature_role/weekly_trigger_stage_summary_v01.csv`에
PIT Weekly Stage별(WATCH/SETUP/TRIGGER/TREND/EXTENDED) n과 각 stage가
어떤 human_label로 발전했는지의 분포를 기록했다:

| Stage | n | 발전 Outcome |
|---|---|---|
| WATCH | 24 | NO_SETUP 9, TOO_EARLY 7, FALSE_TRIGGER 4, BORDERLINE_TRIGGER 4 |
| SETUP | 10 | GOOD_TRIGGER 7, BORDERLINE_TRIGGER 2, TOO_EARLY 1 |
| TRIGGER | 1 | GOOD_TRIGGER 1(안국약품, 유일) |
| TREND | 2 | GOOD_TRIGGER 1, TOO_LATE 1 |
| EXTENDED | 3 | TOO_EXTENDED 3 |

SETUP stage 10개 중 7개(70%)가 GOOD_TRIGGER로 발전 — 다만 이 40개는
13C 샘플링 단계에서 구조적으로 흥미로운 reference_date를 의도적으로
골라 구성한 것이지 시장에서 무작위로 뽑은 표본이 아니다(§2, §21 OOS
Separation). 따라서 이 70%를 "SETUP이 실제로 GOOD_TRIGGER가 될
확률(hit rate)"로 해석하지 않는다 — in-sample, non-random reference-date
selection 위에서 관찰된 descriptive 패턴일 뿐이다(n=10). EXTENDED 3개는
전부 TOO_EXTENDED로 귀결 — Human PIT 판단과
Outcome 라벨이 이 stage에서는 완전히 일치했다(n=3, 참고용).
TRIGGER/TOO_LATE는 각 n=1이므로 Production 근거가 아니다(§28).

--------------------------------------------------------------------------------
13. Correlation / Redundancy
--------------------------------------------------------------------------------

Correction 후 |spearman| >= 0.85 쌍 **49건**(`weekly_trigger_feature_
correlation_v01.csv`, correction 전 42건에서 증가). `weeks_since_26w_
close_breakout`/`higher_low_after_breakout_count` 쌍은 correction 후에도
여전히 **0.910**으로 강하게 남아 있다(19개 subset 안에서 "오래된
breakout일수록 post-breakout 관찰 구간이 길어져 higher-low count도
커진다"는 구조적 상관이 그대로 유지됨) — §17에서 `higher_low_after_
breakout_count`를 LOW로 분류한 근거에 이 중복성도 함께 추가한다(약한
분리력 + weeks_since와의 구조적 중복).

대표: `close_vs_wma200_pct`/`high_vs_wma200_pct`=0.992, `post_breakout_
min_close_vs_level_pct_26w`/`post_breakout_min_low_vs_level_pct_26w`=
0.960, `close_vs_wma200_pct`/`wma200_slope_1w`=0.956, `weekly_low_slope_
13w`/`weekly_return_13w`=0.946, `distance_to_prior_26w_high_pct`/
`distance_to_prior_52w_high_pct`=0.941, `close_vs_wma52_pct`/`wma52_
slope_1w`=0.936, `weekly_low_slope_8w`/`weekly_return_8w`=0.924,
`wma12_slope_1w`/`weekly_low_slope_8w`=0.908.

**신규 발견(§7.6 subset 효과)**: `post_breakout_min_close_vs_level_pct_
26w`가 이제 `weekly_return_13w`(0.889), `close_vs_wma12_pct`(0.882),
`close_vs_wma26_pct`(0.877), `weekly_return_8w`(0.872), `wma12_slope_
1w`(0.858), `distance_from_13w_low_pct`(0.853)와 새로 0.85 이상 상관을
보인다. 이는 breakout family가 이제 19개(breakout이 있는 subset)에서만
계산되면서, 그 subset 자체가 이미 momentum/MA 계열이 강한 종목 위주로
편향돼(breakout이 있으려면 이미 어느 정도 상승 구조가 필요하므로)
자연히 생긴 **표본 선택 효과(sample selection effect)**로 해석한다 —
`post_breakout_min_close_vs_level_pct_26w`가 momentum과 독립적인 새로운
정보를 담고 있는지는 이번 40개만으로는 확정할 수 없다(§18 Known
Limitations에 caveat으로 기록).

`range_position_26w`/`range_position_52w`=0.863은 correction과 무관하게
유지(§17에서 다룸). 0.85는 research redundancy 표시 기준일 뿐 production
threshold가 아니다(§14).

HIGH 후보 7개(§17, Correction 후 재계산) 상호간에는 |spearman|>=0.85
쌍이 하나도 없음을 별도 확인했다 — 서로 다른 latent concept을
대표하도록 선정했다는 근거다.

--------------------------------------------------------------------------------
14. Human Observation Mapping
--------------------------------------------------------------------------------

| Human Observation | Candidate Feature | 확인 |
|---|---|---|
| 직전 고점 돌파 전이라 조금 이름 | `distance_to_prior_26w_high_pct` | YES — GOOD vs NO_SETUP 0.753 |
| 고점 돌파 후 지지 성공 | `post_breakout_min_low_vs_level_pct_26w`, `post_breakout_close_hold_ratio_26w` | YES(단, 최근 26주 내 breakout이 있는 19개 subset에서만) — GOOD vs NO_SETUP Cliff's Delta 1.000(Correction 후) |
| 고점 돌파 후 지지 실패 | `close_back_below_breakout_level`, `post_breakout_min_close_vs_level_pct_26w` | YES(중간) — FALSE_TRIGGER 사례로 실증(§8) |
| 저점이 점점 높아짐 | `higher_weekly_low_count_13w`, `rolling_low_4w_change` | YES — GOOD vs NO_SETUP 0.765/0.704 |
| 저점이 계속 낮아짐 | `weeks_since_recent_low`(=`weeks_since_13w/26w_low`), `weekly_down_week_ratio_8w` | 약함(§9) — 방향 반직관적, LOW |
| 주봉 200 이평이 위에 있음 | `close_vs_wma200_pct`, `weeks_above_wma200_recent_12w` | YES — Q7(13D 이관) 확인됨(§6) |
| 이미 상승이 너무 진행됨 | `range_position_52w`, `distance_from_wma12/26`(=`close_vs_wmaN_pct`), `recent_8w_max_runup` | 부분 YES — range_position 강함, runup은 방향 반직관적(§10) |

--------------------------------------------------------------------------------
15. Critical Case Studies
--------------------------------------------------------------------------------

**A. 안국약품 `001540_20260213`** (PIT=TRIGGER→GOOD_TRIGGER, 유일한 explicit
Trigger Event): `close_above_prior_26w_high=0.0`, `weeks_since_26w_close_
breakout=10.0`, `post_breakout_close_hold_ratio_26w=0.40`,
`post_breakout_min_close_vs_level_pct_26w=-0.075`, `distance_to_prior_26w_
high_pct=-0.045`(고점 4.5% 아래, 매우 근접), `higher_weekly_low_count_
13w=6.0`, `range_position_26w=0.763`. 해석: 10주 전 1차 돌파가 있었으나
hold_ratio 40%로 불완전 지지(-7.5%까지 이탈한 적 있음) — 즉 "1차 돌파 후
조정을 받고 직전 고점(4.5% 아래)에 재접근하는" 국면. Human이 TRIGGER로
판단한 근거가 완전한 최초 돌파가 아니라 **재접근/2차 시도 구조**였을
가능성을 시사한다. 이 sample을 맞추기 위한 threshold tuning은 하지
않았다.

**B. 현대해상 `001450_20260116`** (SETUP→GOOD_TRIGGER, **Correction 반영**):
`distance_to_prior_26w_high_pct=-0.153`(안국약품보다 고점에서 더 멀다).
원래 `weeks_since_26w_close_breakout=28.0`(28주 전 돌파)을 근거로 "지지
자체는 더 강했다"고 서술했으나, correction 후 이 breakout은 search
horizon(26주) 밖이라 NOT_OBSERVED(NaN)로 처리된다 — breakout hold family
전체가 NaN이다. 안국약품(TRIGGER, 최근 10주 내 breakout 존재)과 비교해
"최근 26주 내 뚜렷한 breakout이 없고, 아직 고점 접근도 덜 됐다"는 점이
SETUP에 머무른 이유로 다시 읽힌다 — 이 sample은 오히려 breakout
"부재"가 SETUP 판정과 부합하는 사례가 됐다.

**C. 오리온홀딩스 `001800_20250321`** (SETUP→GOOD_TRIGGER): `close_vs_
wma200_pct=NaN`(200주 이력 부족), `higher_weekly_low_count_13w=7.0`(최대치
근접), `weeks_since_26w_close_breakout=20.0`, `hold_ratio=0.0`(주의:
breakout이 있었지만 이후 hold는 실패 — 그럼에도 higher-low 구조 자체는
건강). Higher-low family가 breakout hold family와 반드시 같은 방향을
가리키지는 않음을 보여주는 사례.

**D. LG이노텍 `011070_20200925`** (SETUP→GOOD_TRIGGER, 정석적인 Positive):
`weeks_since_26w_close_breakout=12.0`(search horizon 26주 내, 안국약품의
10주와 비슷한 범위), `close_vs_wma200_pct=0.159`, `weeks_above_wma200_
recent_12w=12.0`(12주 내내 200선 위), `range_position_26w=0.617`. HIGH
후보들이 일관되게 "건강한" 값을 보이는 대표 사례.

**E. 선광 `003100_20250822`** (WATCH→FALSE_TRIGGER): `close_vs_wma200_
pct=-0.615`(200선 아래 61.5%), `post_breakout_close_hold_ratio_26w=0.0`,
`post_breakout_min_close_vs_level_pct_26w=-0.132`. False Breakout Feature가
정확히 "실패"를 가리킨 사례.

**F. 서흥 `008490_20250328`** (WATCH→FALSE_TRIGGER): weekly feature
13개가 결측(200주 이력 부족 + breakout 계열 다수 NaN) — 단순 breakout
여부만으로 GOOD 판단하면 안 된다는 w.md 경고를 데이터 가용성 측면에서도
보여주는 사례(feature가 부족한 상태에서도 Human은 판단을 내렸다는 것,
Weekly Feature Research의 한계로 §18에 기록).

**G. 삼화전기 `009470_20250627`** (WATCH→FALSE_TRIGGER, **Correction
반영**): 원래 `weeks_since_26w_close_breakout=60.0`(60주 전)을 근거로
"여러 breakout attempt 후 마지막 지지 실패"를 설명했으나, 이 breakout은
search horizon(26주) 밖의 stale event였다 — correction 후
`weeks_since_26w_close_breakout`과 breakout hold family 전체가
NaN(NOT_OBSERVED)이다. 즉 이 sample은 애초에 "최근 26주 내 뚜렷한
breakout이 없는" 상태에서 FALSE_TRIGGER로 판정됐다는 것이 정확한 설명이다
— `distance_to_prior_26w_high_pct=-0.372`(고점에서 여전히 37% 이상 먼
상태)만 유효 정보로 남는다. 이 sample은 더 이상 breakout hold-failure
사례로 인용하지 않는다.

**H. LG디스플레이 `034220_20200925`** (WATCH→FALSE_TRIGGER):
`weeks_since_26w_close_breakout=2.0`(매우 최근), `hold_ratio=0.5`(절반).
강한 저항 돌파 시도 후 support conversion 실패라는 서술과 일치 — breakout
자체는 최근이지만 hold가 불완전.

**I. 우리기술 Pair `032820`** (**Correction 반영**) — GOOD(`20251226`):
원래 `weeks_since_26w_close_breakout=27.0`, `hold_ratio=1.00`(완벽 지지)을
이 sample의 핵심 근거로 인용했으나, offset=27은 search horizon(26주,
offset 0..25) 밖이다 — correction 후 breakout age/hold family 전체가
NaN(NOT_OBSERVED)이다. 이 sample은 이제 breakout 근거 없이 다음 값들로만
설명된다: `close_vs_wma200_pct=0.738`, `distance_to_prior_26w_high_pct=
-0.351`(아직 고점 접근 전), `range_position_26w=0.196`(26주 range 자체가
넓어 최근 위치는 낮게 관측), `higher_weekly_low_count_13w=6.0`,
`recent_8w_max_runup=0.174`(TOO_LATE 시점 대비 미미). TOO_LATE
(`20260327`): `weeks_since_26w_close_breakout=1.0`(방금 재돌파, 이건
offset=1<26이라 correction 영향 없음), `hold_ratio=0.0`(관찰 구간 짧음),
`close_vs_wma200_pct=7.30`(200주선 대비 **730%** 위, 극단적), `weeks_
above_wma200_recent_12w=12.0`, `recent_8w_max_runup=5.61`(561%),
`consecutive_positive_weeks=0.0`(reference 주 자체는 종가 기준 하락
마감했다는 뜻 — 극단적으로 연장된 상승 뒤에도 최근 한 주는 눌림이 있을
수 있어, 연속상승 카운터 단독으로는 TOO_LATE를 못 잡는다는 것을 보여주는
사례). `close_vs_wma200_pct`가 0.738→7.30으로 10배 가까이 뛴 것이 이번
연구에서 확인한 가장 극단적인 GOOD→TOO_LATE 이동 사례다 — breakout
근거가 사라진 뒤에도 이 결론은 유효하다(breakout 계열이 아닌 다른
feature로 뒷받침되는 발견).

**J. 천일고속 Pair `000650`** — TOO_EARLY(`20250926`): breakout 계열
전부 NaN(직전 26주 내 event 없음, NOT_OBSERVED — "아직 돌파 자체가 없다"는
것이 TOO_EARLY의 정의와 정확히 부합), `distance_to_prior_26w_high_pct=
-0.145`. TOO_EXTENDED(`20251226`): `weeks_since_26w_close_breakout=3.0`,
`hold_ratio=1.0`, `close_vs_wma200_pct=5.27`(527%), `recent_8w_max_
runup=10.13`(**1013%**, 40개 중 최댓값), `consecutive_positive_weeks=
1.0`. Weekly Feature가 Monthly보다 이 이동을 훨씬 세밀하게 포착한다
(§16 Q5 참고) — 특히 `recent_8w_max_runup`이 3개월 만에 0(관측불가)에서
1013%로 뛴 것은 Monthly 스케일(월 단위)에서는 절대 못 보는 정보다.

**K. HS화성 `002460_20250509`** (WATCH→BORDERLINE_TRIGGER): `close_vs_
wma200_pct=NaN`, `range_position_26w=0.912`(26주 range 최상단),
`weeks_since_26w_close_breakout=20.0`, `hold_ratio=0.20`(약함). "좋은 지지
구조"와 "Trigger 완성"의 차이 — 여기서는 오히려 range position은 높은데
hold quality가 약해 BORDERLINE에 머문 것으로 읽힌다.

**L. 한화솔루션 `009830_20250328`** (WATCH→BORDERLINE_TRIGGER,
**Correction 반영**): 원래 `weeks_since_26w_close_breakout=135.0`(40개
중 최대치권)과 `post_breakout_min_close_vs_level_pct_26w=-0.748`(74.8%
이탈)을 근거로 "FALSE_TRIGGER 그룹과 거의 구분이 안 될 정도로 나쁜데
BORDERLINE으로 판단됐다"는 반례로 인용했으나, 135주 전 breakout은 search
horizon 밖의 stale event였다 — correction 후 breakout family 전체가
NaN이다. 즉 이 sample은 애초에 "최근 26주 내 breakout 자체가 없는" 상태로
재해석해야 한다: `distance_to_prior_26w_high_pct=-0.294`(고점에서 29%
먼 상태), `close_vs_wma200_pct=-0.523`(200선 아래 52%). breakout이
전혀 없는데도 BORDERLINE(FALSE가 아닌)으로 판단됐다는 것은 오히려 Human이
breakout 여부만으로 판단하지 않았다는 것을 보여주는 사례로 다시 읽어야
한다 — 원래 서술("GOOD/FALSE 사이의 애매한 구조")의 근거였던 수치
자체가 stale event 버그의 산물이었으므로, 이 결론은 폐기한다.

**M. 에이프로젠바이오로직스 `003060_20260327`** (WATCH→NO_SETUP, 이후
초대형 급등 — Negative Structural Anchor, **Correction 반영**): 원래
`weeks_since_26w_close_breakout=137.0`, `post_breakout_min_close_vs_
level_pct_26w=-0.916`(91.6% 이탈)을 "구조 붕괴"의 핵심 근거로 인용했으나,
137주 전 breakout은 명백히 search horizon 밖의 stale event다 —
correction 후 breakout family 전체가 NaN이다. 다행히 이 sample의 "구조
붕괴" 결론 자체는 breakout family에 의존하지 않는 다른 feature로도
동일하게 뒷받침된다: `close_vs_wma200_pct=-0.840`(200선 아래 84%),
`distance_to_prior_26w_high_pct=-0.540`(고점에서 54% 먼 상태),
`higher_weekly_low_count_13w=3.0`(13주 중 3주만 higher-low, 매우 약함),
`range_position_26w=0.131`(26주 range 하단). reference_date 시점 Weekly
구조는 이 4개 feature만으로도 명백히 나쁜 상태 — 향후 급등을 설명하기
위해 이 값들을 억지로 Positive로 해석하지 않았다.

**N. 에이치엠넥스 `036170_20251226`** (SETUP→GOOD_TRIGGER, Investability
observation 별도, **Correction 반영**): 원래 `weeks_since_26w_close_
breakout=71.0`을 근거로 들었으나, 이 breakout도 search horizon 밖이라
correction 후 NaN이다. `distance_to_prior_26w_high_pct=-0.149`,
`close_vs_wma200_pct=-0.144`(200선 아래)만 유효 정보로 남는다 — 최근
26주 내 뚜렷한 breakout 없이 SETUP→GOOD_TRIGGER로 판정된 사례로
재해석된다. 구조적으로 다른 GOOD_TRIGGER 사례들만큼 강하지 않다는
결론은 유지된다(오히려 breakout 근거가 사라지면서 더 약해짐) — 동전주
노이즈일 가능성과, Weekly Feature 자체의 한계일 가능성을 구분할 수 없다는
점을 투명하게 기록한다. Weekly Feature에 raw price hard filter는 추가하지
않았다(§2 item 14 금지 준수).

--------------------------------------------------------------------------------
16. Monthly vs Weekly Incremental Value
--------------------------------------------------------------------------------

`monthly_weekly_research_join_v01.csv`(13D matrix를 그대로 읽어 join,
재계산 없음)로 Weekly HIGH 7개(**Correction 후 재계산**, §17)와 Monthly
HIGH 7개 간 실제 상관을 확인했다.

Q1(Monthly HIGH만으로 잘 설명된 sample, **Correction 반영**): 에이프로젠
(§15-M)은 correction 전 breakout family(`post_breakout_min_close_vs_
level_pct_26w=-0.916`)를 근거로 들었으나 이제 그 값은 NaN이다. 대신
Monthly(`drawdown_from_12m_high` 등)와 Weekly(`close_vs_wma200_pct=
-0.840`, `distance_to_prior_26w_high_pct=-0.540`, breakout family가
아닌 feature) 둘 다 여전히 극단적으로 나쁜 방향을 가리켜, 이 sample은
두 스케일이 일치해서 Monthly만으로도 상당 부분 설명된다는 결론 자체는
유지된다 — 다만 그 Weekly 근거가 breakout 계열에서 non-breakout 계열로
바뀌었다.

Q2(Monthly는 애매했는데 Weekly가 추가 구분): 우리기술 TOO_LATE(§15-I)에서
Monthly `range_position_24m`은 극단값이지만 `close_vs_wma200_pct`가
0.738→7.30으로 이동한 것과 `recent_8w_max_runup`이 5.61에 달한 것은
Weekly만이 포착하는 정보다(breakout family와 무관해 correction 영향
없음). 안국약품(§15-A)의 "10주 전 돌파 후 재접근" 서사도 offset=10<26
이라 correction 영향 없이 Monthly 스케일에서는 아예 안 보이는 정보로
남는다.

Q3/Q4(Monthly+Weekly 둘 다 좋아 보였지만 FALSE_TRIGGER, **Correction
반영**): 한화솔루션(§15-L)을 원래 대표 사례로 들었으나 근거였던
breakout hold 수치가 stale event였음이 드러나 폐기했다. 대신 FALSE_
TRIGGER 중 breakout이 search horizon 안에 있는 2개 사례(선광
`weeks_since=6`, LG디스플레이 `weeks_since=2`, §15-E/H, n=2라
descriptive)에서 `post_breakout_close_hold_ratio_26w`가 각각 0.0/0.5로
낮고 `min_close_vs_level_pct_26w`가 -0.13/-0.05로 마이너스라는 것이
Weekly failure-risk feature(`post_breakout_close_hold_ratio_26w`,
`post_breakout_min_close_vs_level_pct_26w`)가 실제로 작동하는 유일하게
남은 실증 사례다 — n=2이므로 결론의 강도는 correction 전보다 약해졌음을
투명하게 인정한다.

Q5(우리기술 pair에서 Weekly가 Monthly보다 entry window를 더 정확히
표현했는가): YES — §15-I/§16-Q2 참고, `close_vs_wma200_pct`의 10배
가까운 변화와 `recent_8w_max_runup`의 급증이 Monthly 스케일보다 훨씬
세밀하게 시점을 짚어낸다(둘 다 breakout family와 무관해 correction
영향 없음).

Q6(안국약품 explicit TRIGGER의 Weekly feature space 위치, **Correction
반영**): "이미 완전히 돌파해 안정적으로 안착한" 위치가 아니라 "1차
돌파(10주 전, search horizon 내) 후 조정을 거쳐 재접근 중"인 위치다
(§15-A, `post_breakout_close_hold_ratio_26w=0.40`으로 불완전 지지).
원래 이 median(10) vs GOOD_TRIGGER median(12)의 근접성을 "sweet-spot
가설"의 근거로 들었으나, §7에서 U자형 해석 자체를 폐기했으므로 이
median 비교는 더 이상 인용하지 않는다 — 안국약품이 GOOD_TRIGGER
median과 가깝다는 사실 자체는 유효하지만 (n=6로 작아진) 그룹 median과의
근접성에 특별한 의미를 부여하지 않는다.

상관 수치로 본 정량적 결론(**Correction 후 재계산**): Weekly HIGH 7개
중 `distance_to_prior_26w_high_pct`(Monthly HIGH와 상관 0.22~0.61,
대체로 낮음), `higher_weekly_low_count_13w`(0.17~0.45), `rolling_low_
4w_change`(0.22~0.45)는 Monthly와 뚜렷이 구분되는 정보를 담고 있다.
`post_breakout_min_low_vs_level_pct_26w`는 19개 subset 기준으로 Monthly
`drawdown_from_12m_high`와 0.75, 나머지 Monthly HIGH와는 0.05~0.56로
correction 전(0.79~0.83)보다 오히려 Monthly와의 상관이 낮아졌다 — 다만
이는 §13에서 지적한 표본 선택 효과와 얽혀 있어 해석에 주의가 필요하다.
`close_vs_wma200_pct`/`wma52_slope_1w`/`wma12_vs_wma26_pct`는 Monthly
HIGH(특히 `close_vs_ma24_pct`, `drawdown_from_12m_high`, `recent_3m_
return`)와 0.6~0.83대의 상당히 높은(0.85 미만이라 §14 기준상 "높은
상관"으로 flag되지는 않지만) 상관을 보인다 — 이는 "장기 구조가 좋으면
Weekly 구조도 대체로 좋다"는 자연스러운 결과이지, 두 스케일이 완전히
독립적이지는 않다는 것을 뜻한다. Monthly가 permission을 주고 Weekly가
trigger를 당긴다는 역할 분리는 데이터에서 대체로 유지되지만, 완전히
직교하지는 않는다는 것이 이번 연구의 정량적 결론이다.

--------------------------------------------------------------------------------
17. HIGH / MEDIUM / LOW Candidates
--------------------------------------------------------------------------------

**HIGH PRIORITY (7개, Correction 후 재계산)** — HIGH가 Production
Feature 확정을 의미하지 않는다. 다음 단계(13F Daily, 그리고 13D와의
결합) 연구 가치가 높다는 뜻일 뿐이다. §3 지시대로 correction 전 랭킹을
보존하려 하지 않았다 — `weeks_since_26w_close_breakout`이 HIGH에서
빠지고 8개가 아니라 7개가 됐다.

1. **`post_breakout_min_low_vs_level_pct_26w`** — 왜: Correction 후에도
   GOOD_TRIGGER vs NO_SETUP Cliff's Delta **1.000**(완전 분리, n=6 vs 3),
   POSITIVE_STRUCTURE vs EARLY_OR_NONE 0.900, SETUP→GOOD vs WATCH→
   EARLY/NONE 0.800. GOOD vs TOO_EARLY는 0.667로 correction 전(0.810)
   보다 약해짐. Human Observation: "고점 돌파 후 지지 성공/실패"의 가장
   직접적인 대응(§8/§14). **약점(중요)**: 이 family는 이제 40개 전체가
   아니라 **"최근 26주 내 breakout이 있는 19개 sample"이라는 좁은
   subset**에서만 계산된다(GOOD_TRIGGER 9개 중 6개, NO_SETUP 9개 중
   3개만 포함) — 나머지 21개 sample에 대해서는 이 feature가 아무것도
   말해주지 않는다. `post_breakout_min_close_vs_level_pct_26w`와 corr
   0.960(형제, 대표만 채택). §13에서 지적한 표본 선택 효과로 momentum/MA
   계열과도 새로 0.85+ 상관을 보임. Monthly 중복 가능성: 낮음(§16, corr
   0.05~0.75).
2. **`close_vs_wma200_pct`** — 왜: GOOD vs NO_SETUP 0.792, GOOD vs
   FALSE_TRIGGER 0.750(n=3 descriptive). breakout family와 무관해
   correction 영향 없음. Human Observation: "주봉 200 이평 저항"(Q7, 13D
   이관)의 직접 대응. 약점: `high_vs_wma200_pct`와 corr 0.992(중복),
   `wma200_slope_1w`와도 0.956. Monthly 중복: 있음(`MONTHLY_close_vs_
   ma24_pct`와 corr 0.80 — 장기 이평 이격 개념이 스케일만 다를 뿐 유사).
3. **`distance_to_prior_26w_high_pct`** — 왜: GOOD vs NO_SETUP 0.753,
   SETUP→GOOD vs WATCH 0.571. breakout family와 무관해 correction 영향
   없음(prior high 자체는 항상 계산 가능, breakout event 존재 여부와
   무관). Human Observation: "직전 고점 접근/돌파"의 가장 단순한 연속형
   표현, w.md 예시(26w)와 window 일치. 약점: 13w/52w 형제와 0.89/0.94
   상관. Monthly 중복: 낮음(corr 0.22~0.61) — Weekly 고유 정보에 가장
   가까운 후보 중 하나.
4. **`higher_weekly_low_count_13w`** — 왜: GOOD vs NO_SETUP 0.765.
   breakout family와 무관해 correction 영향 없음. Human Observation:
   "저점이 점점 높아짐"(가장 자주 언급된 관찰)의 가장 단순한 연속형
   근사. 약점: 8주 버전은 훨씬 약함(0.370) — 짧은 창은 노이즈에 취약.
   Monthly 중복: 낮음(corr 0.17~0.45), Weekly 고유 정보.
5. **`wma52_slope_1w`** — 왜: GOOD vs TOO_EARLY **0.833**(최상위),
   GOOD vs NO_SETUP 0.506. breakout family와 무관해 correction 영향
   없음. Human Observation: "장기 하락 압력이 개선 중인가"에 대응.
   약점: `close_vs_wma52_pct`와 corr 0.936(형제). Monthly 중복: 있음
   (`MONTHLY_close_vs_ma24_pct`와 corr 0.83).
6. **`wma12_vs_wma26_pct`** — 왜: GOOD vs TOO_EARLY 0.722. breakout
   family와 무관해 correction 영향 없음. Human Observation: "정배열/
   역배열"의 단기 축. 약점: `wma52_vs_wma200_pct`(장기 축)와는 상관이
   낮아 서로 보완적이지만, 각각 단독으로는 중간 강도. Monthly 중복:
   낮음(corr 0.35~0.79).
7. **`rolling_low_4w_change`** — 왜: GOOD vs NO_SETUP 0.704. breakout
   family와 무관해 correction 영향 없음. Human Observation: "저점 상승
   속도"를 담는 유일한 HIGH 후보(higher-low count가 "얼마나 자주"라면
   이건 "얼마나 빨리"). 약점: 8주 버전과는 개념적으로 유사하나 실측
   상관은 낮게 나와(<0.85) 형제로 강등하지 않음. Monthly 중복: 낮음
   (corr 0.22~0.45).

**MEDIUM PRIORITY**: `weeks_since_26w_close_breakout`(**Correction 후
HIGH에서 강등** — GOOD_TRIGGER vs NO_SETUP Cliff's Delta가 0.167로
급감, GOOD vs TOO_EARLY는 -0.583으로 방향이 바뀌었고, non-NaN 개수가
40개 중 20개로 절반까지 줄었다. §7의 핵심 finding: "breakout이 최근
26주 내 존재하는지 자체"가 흥미로운 신호일 수 있으나 age의 절대값 자체는
더 이상 강한 분리력을 갖지 못한다 — 13F 이후 boolean 파생형으로
재검토할 후보), `range_position_52w`(GOOD vs TOO_EARLY 0.806, GOOD vs
NO_SETUP 0.728로 수치 자체는 HIGH급이지만 `range_position_26w`와 corr
0.863으로 0.85 임계를 넘어 §14 기준상 형제 대표성 문제가 있어 MEDIUM으로
분류), `close_vs_wma52_pct`(wma52_slope_1w의 형제), `wma200_slope_1w`/
`weeks_above_wma200_recent_12w`/`high_vs_wma200_pct`(close_vs_wma200_pct
계열의 형제 또는 약한 신호), `wma52_vs_wma200_pct`(close_vs_wma200_pct와
corr 0.93), `distance_to_prior_13w/52w_high_pct`(26w의 형제),
`post_breakout_min_close_vs_level_pct_26w`/`post_breakout_close_hold_
ratio_26w`(min_low_vs_level의 형제 또는 보조, 동일한 n=19 subset
caveat 적용), `weekly_low_slope_13w`(higher_low_count의 보조로
기대했으나 실측 결과 `weekly_return_13w`와 corr 0.946 — 사실상 momentum
계열의 재표현), `rolling_low_8w_change`, `weeks_since_26w_low`,
`weekly_ma_spread_pct`/`wma12_wma26_gap_pct`(FALSE_TRIGGER 방향에서는
강하나 n=3-4 descriptive), `weekly_return_13w`/`weekly_positive_ratio_
8w`, `distance_from_52w_low_pct`, `range_position_26w`(52w의 형제),
`close_back_below_breakout_level`(n=20로 줄었고 방향은 유지되나 약해짐,
GOOD vs NO_SETUP -0.250).

**LOW / REJECTED**: `close_above_prior_26w_high`/`high_above_prior_26w_
high`(39-40/40 상수, 분리력 없음 — §7의 핵심 finding, breakout family와
무관해 correction 영향 없음), `weeks_closed_above_breakout_level_26w`
(post window 길이 차이로 절대 카운트 오염, GOOD vs NO_SETUP 0.278로
correction 후에도 여전히 약함), `higher_low_after_breakout_count`(n=19, GOOD vs NO_SETUP 0.167·GOOD vs
TOO_EARLY -0.333로 약함, 게다가 `weeks_since_26w_close_breakout`와
spearman 0.910으로 여전히 강하게 중복 — §13), `higher_
weekly_low_count_8w`(8주 창이 13주 창보다 일관되게 약함), `weekly_low_
slope_8w`(GOOD vs TOO_EARLY=-0.028로 매우 약하고, `weekly_return_8w`/
`wma12_slope_1w`/`close_vs_wma12_pct`와 corr 0.90~0.92 — "저점 기울기"가
아니라 사실상 종가 momentum의 재표현일 뿐임이 실측으로 드러남),
`distance_from_13w/26w_low_pct`(방향 반직관적, §9), `weekly_down_week_
ratio_8w`, `recent_4w_return_vs_prior_12w`(SETUP_GOOD vs WATCH=0.000),
`weekly_return_4w/8w/26w`, `distance_from_wma12_pct`(=close_vs_wma12_
pct, GOOD vs TOO_EARLY=0.056로 매우 약함), `wma26_slope_1w`(GOOD vs
FALSE=0.111), `recent_8w_max_runup`(방향 반직관적, §10 — 그룹 통계보다
개별 사례에서만 신뢰 가능), `consecutive_positive_weeks`(방향 애매).

w.md §7이 이름만 제안하고 이번에 명시적으로 계산하지 않은 항목(이유
기록, §5 참고): `weekly_ma4`/`weekly_ma100`, `wmaN_slope_change_4w`
4종, `close_above/below_prior_13w/52w_high` boolean 4종, `recent_
breakout_level_26w`(raw 가격), `wma200_distance_crossing_state`
(categorical), `weekly_ma_dispersion_pct`, `recent_breakout_exists`
(대수적으로 유도 가능).

--------------------------------------------------------------------------------
18. Known Limitations
--------------------------------------------------------------------------------

- `weeks_above_wma200_recent_12w`는 매주 rolling 200주선을 재계산하지
  않는 근사다(§6) — 완전한 PIT rolling은 계산 복잡도가 커서(§8 Guard)
  이번 라운드에 구현하지 않았다.
- 200주 이력이 부족한 10개 샘플은 §7.1/§7.2/§7.9 전체가 NaN이다(신규
  상장주 특성상 구조적 한계, fail-safe로 처리했을 뿐 보완하지 않음).
- `post_breakout_*` 계열은 breakout event가 없는 샘플에서 전부 NaN이다
  — "돌파가 아예 없다"와 "돌파했지만 값을 못 구했다"를 구분하지 못하면
  안 되므로, §7.4/§7.5 다른 feature(전부 NaN 또는 0)로 교차 확인 가능
  하도록 뒀다.
- **[Correction 반영] breakout search horizon 버그**: 최초 구현의
  `_find_breakout_event`는 backward scan에 search horizon 제한이 없어
  전체 이력을 뒤졌고, 그 결과 최대 152주 전(3년 가까이 된) stale event를
  breakout_level로 사용하는 버그가 있었다 — advisor review로 발견,
  `search_horizon=26`으로 수정했다(§1, §24 CASE 신규 테스트 A~E).
  Correction 후 `weeks_since_26w_close_breakout`의 non-NaN 개수는
  40개 중 20개로 절반까지 줄었고, breakout hold family(§7.6)는 이제
  19개(GOOD_TRIGGER 6, NO_SETUP 3 등)라는 좁은 subset에서만 계산된다.
  기존 "U자형 sweet-spot" 해석(§7)은 이 버그의 산물이었으므로 폐기했다.
  §15의 6개 case study(B/G/I-GOOD/L/M/N)가 원래 stale breakout 수치를
  근거로 서술됐다가 이번에 재작성됐다 — 이 자체가 "잘못된 breakout
  semantics가 case study 서사에 얼마나 쉽게 스며들 수 있는지"를 보여주는
  사례다.
- **[Correction 반영] 표본 선택 효과**: breakout family가 이제 19-20개
  subset에서만 계산되면서, `post_breakout_min_close_vs_level_pct_26w`가
  momentum/MA 계열(weekly_return_8w/13w, close_vs_wma12/26_pct 등)과
  새로 0.85+ 상관을 보인다(§13) — breakout이 있는 종목 자체가 이미
  momentum이 강한 경향이 있어 생긴 자연스러운 결과로 해석하지만, 40개
  전체가 아닌 subset에서의 상관이라는 점을 감안해 해석해야 한다.
- `distance_from_Nw_low_pct`, `recent_8w_max_runup`처럼 방향이
  반직관적으로 나온 feature가 있다(§9/§10) — 원인을 추정만 했고
  확정하지 않았다. threshold tuning으로 "고치지" 않았다(§2 item 3
  금지).
- Machine breakout candidate(`weeks_since_26w_close_breakout` 등)와
  Human observed Trigger Event(001540 단 1건)는 서로 다른 개념이다
  (§18 Semantic Guard). 이 문서 어디에서도 machine feature를 "Human
  Trigger Event"라고 지칭하지 않았다.
- FALSE_TRIGGER(n=4, 실제 유효 n=3), TOO_EXTENDED(n=3), TOO_LATE(n=1),
  TRIGGER stage(n=1)에 대한 모든 통계는 descriptive일 뿐 Production
  decision 근거가 아니다(§28).
- 서흥(§15-F)처럼 결측이 많은 샘플에서는 Weekly Feature Research 자체의
  적용 한계가 있다 — Human은 그 상태로도 판단을 내렸다.

--------------------------------------------------------------------------------
19. No Threshold Frozen
--------------------------------------------------------------------------------

이 문서와 산출물 어디에도 `distance_to_prior_26w_high_pct > X` 같은
PASS/FAIL 수치, "%면 Trigger"류의 production threshold는 확정하지
않았다. 40개 calibration sample을 완벽히 분리하는 것이 목적이 아니었다
(§2 item 3). `post_breakout_min_low_vs_level_pct_26w`가 GOOD_TRIGGER vs
NO_SETUP에서 Cliff's Delta **1.000**(완전 분리)을 기록했지만, 이는
**19개 subset**(최근 26주 내 breakout이 있는 sample만)에서의 완전
분리이지 40개 전체를 분리한 것이 아니다(§17) — 나머지 6개 feature를
포함해 40개 전체를 깔끔히 분리하는 단일 feature는 없다. 이 구분을
근거로도, 어떤 feature 하나로 production threshold를 확정하지 않는다.

Phase 13E does NOT decide(§33 Explicit Non-Decision): Weekly Trigger
numeric threshold, Weekly Stage automatic classifier, Weekly Production
Feature Set, Pattern A Fast Score, Monthly + Weekly combined score, Daily
entry condition, Production scanner integration, Trigger Event backfill.
이번 결과는 RESEARCH EVIDENCE ONLY다.

--------------------------------------------------------------------------------
20. No Production Change
--------------------------------------------------------------------------------

Pattern A production 코드(`src/trend_scanner/patterns/`), scanner
pipeline, Phase 10 Investability, Phase 11 Flow, Phase 12 Relative
Strength는 전혀 수정하지 않았다. `pattern_a_fast_weekly_features.py`는
production evaluator나 scanner pipeline 어디에서도 import되지 않는다
(`test_research_module_does_not_import_production_pattern_a`,
`test_research_module_has_no_phase12_dependency`로 검증). Classifier,
Score도 생성하지 않았다.

--------------------------------------------------------------------------------
21. OOS Separation
--------------------------------------------------------------------------------

13D와 동일. 이번 40개는 IN-SAMPLE HUMAN CALIBRATION SET이다. 13E에서
Feature를 보고 후보 선정까지 했으므로, 향후 OOS 성능평가(Phase 13I 또는
별도 OOS validation)에서 이 40개를 unseen data처럼 재사용하지 않는다.
별도 unseen sample을 사용해야 한다.

--------------------------------------------------------------------------------
22. Next Phase Recommendation
--------------------------------------------------------------------------------

Phase 13F Daily Timing Feature Research로 진행하기 전에, w.md §37이
요구하는 대로 13D Monthly + 13E Weekly 결과를 함께 검토해 "Monthly가
permission을 주고 Weekly가 trigger를 당긴다"는 역할 분리가 실제
데이터에서 유지되는지 advisor review에서 확인이 필요하다. §16의 정량적
결론(대체로 유지되나 완전히 직교하지는 않음, 특히 `close_vs_wma200_pct`
계열은 Monthly `close_vs_ma24_pct`와 0.8 안팎의 상관)을 그 검토의
출발점으로 제안한다. 추가로, `post_breakout_*` 계열의 강한 분리력(단,
19개 subset 한정)을 감안하면 Phase 13F에서 "돌파 이후 며칠 내 매수
타이밍"을 다루는 Daily Feature가 이 Weekly hold-quality 신호와 어떻게
상호작용하는지가 유망한 연구 방향으로 보인다(단, 이 역시 이번 라운드에서
확정하지 않은 제안일 뿐이다).

**Correction으로 새로 드러난 연구 후보**: "최근 26주 내 breakout이
존재하는지 자체"(boolean, `weeks_since_26w_close_breakout`이 NaN이
아닌지)가 GOOD_TRIGGER(67%)와 TOO_EARLY(25%) 사이에 뚜렷한 차이를
보였다(§7) — 이번 correction에서는 신규 feature를 추가하지 않았지만
(범위 밖), 이 boolean 자체를 다음 Weekly Feature Research 라운드의
후보로 명시적으로 남긴다.
