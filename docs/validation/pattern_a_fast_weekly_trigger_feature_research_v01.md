pattern_a_fast_weekly_trigger_feature_research_v01.md

--------------------------------------------------------------------------------
0. Status / Base SHA
--------------------------------------------------------------------------------

Status: **WEEKLY TRIGGER FEATURE RESEARCH COMPLETE / ADVISOR REVIEW PENDING**
(§37 Final Status Rule — 이번 커밋으로 Phase 13E를 자동 CLOSED하지 않는다)

Base Commit: `6917b1341553b58fa42390ba1507fc9b80551fee` (Phase 13D CLOSED 시점)

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

`artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv`에서
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
close_breakout`은 TOO_EARLY 8개 중 1개가 26주 내 breakout event 없음
(NOT_OBSERVED)이라 그 feature에 한해 유효 n=7이다. 이 유효 n은 summary
CSV의 `missing_count`/그룹별 `n` 컬럼에 feature마다 기록돼 있다.

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

**Breakout Age(§7.5)**: `weeks_since_26w_close_breakout`의 human_label별
median: GOOD_TRIGGER=12, FALSE_TRIGGER=6, TOO_EXTENDED=4, TOO_LATE=1,
BORDERLINE_TRIGGER=33, TOO_EARLY=56, NO_SETUP=61. **U자형 비선형 패턴**이다
— GOOD_TRIGGER는 "너무 최근도 너무 오래되지도 않은" 중간 지점(12주)에
몰려 있고, FALSE_TRIGGER/TOO_EXTENDED/TOO_LATE는 오히려 "매우 최근"
(1~6주, 방금 돌파해 검증 안 됐거나 이미 늦은 재돌파), TOO_EARLY/NO_SETUP은
"매우 오래전"(사실상 최근 구조와 무관)에 몰려 있다. 이 비선형성 때문에
단순 GOOD vs NO_SETUP Cliff's Delta는 **-0.309**로 약하게만 나온다(부호도
음수 — median 차이만 보면 GOOD이 더 작은 값이라는 오해를 줄 수 있음).
w.md §26 Hypothesis A("GOOD은 prior high에 더 가깝거나 이미 돌파")를
단조 관계가 아니라 **최적 구간(sweet spot) 가설**로 수정해서 봐야 한다는
것이 이번 연구의 핵심 발견 중 하나다. HIGH 후보로 유지하되 이 caveat을
반드시 §17 HIGH candidate 설명에 명시한다.

--------------------------------------------------------------------------------
8. Breakout Hold / False Breakout Research
--------------------------------------------------------------------------------

`post_breakout_min_low_vs_level_pct_26w`가 GOOD_TRIGGER vs NO_SETUP에서
**0.944**(전체 48개 feature 중 최상위), GOOD_TRIGGER vs TOO_EARLY **0.810**,
SETUP→GOOD vs WATCH→EARLY/NONE **0.857**로 이번 연구 전체에서 가장 강한
분리력을 보였다. `post_breakout_min_close_vs_level_pct_26w`는 거의 동일한
정보(spearman 0.986, 형제 — 종가/저가 버전 차이).

w.md §26 Hypothesis C("FALSE_TRIGGER는 breakout 발생보다 hold quality가
약할 것") 검증: FALSE_TRIGGER(n=3, 관찰 가능한 것 기준)의
`post_breakout_close_hold_ratio_26w` median은 매우 낮음(§9의 삼화전기/
선광/서흥 사례로 실증, `post_breakout_min_close_vs_level_pct_26w`가
-0.05~-0.51로 크게 마이너스) — Hypothesis C는 지지된다. 다만 n=3~4라
descriptive로만 취급한다(§28).

`weeks_closed_above_breakout_level_26w`(절대 카운트)는 GOOD vs NO_SETUP
**0.069**로 매우 약함 — post window 길이가 sample마다 다르기 때문에
절대 카운트는 오염되고, 비율(`hold_ratio`)이 훨씬 유효한 형태임을
실증했다. LOW로 분류.

`higher_low_after_breakout_count`는 `weeks_since_26w_close_breakout`과
spearman **0.980**으로 거의 완전 중복(breakout이 오래될수록 관찰 구간이
길어져 higher-low count도 자연히 커지는 구조적 상관) — LOW.

`close_back_below_breakout_level`(FALSE_TRIGGER의 가장 직접적인 machine
근사, §18/§19 Semantic Guard에 따라 "Human Trigger Event"가 아니라 machine
breakout candidate로만 명명)은 GOOD_TRIGGER vs NO_SETUP **-0.333**로 방향은
맞으나 중간 강도 — MEDIUM.

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
`artifacts/pattern_a_fast/research/weekly_trigger_feature_summary_v01.csv`
(48행)에 기록했다. `standardized_effect_*`의 분모는 두 그룹을 합친 전체
표본의 IQR이다(13D §5와 동일 caveat — 완벽 분리 시 오히려 작아질 수 있어
Cliff's Delta가 1차 근거).

**중요(표본 크기 주의)**: `TRIGGER` n=1, `TOO_LATE` n=1, `TOO_EXTENDED`
n=3, `FALSE_TRIGGER` n=4다. 이 그룹이 낀 pair comparison(`GOOD_TRIGGER vs
FALSE_TRIGGER`, `GOOD_TRIGGER vs TOO_EXTENDED`)은 descriptive로만
취급한다(§28). 주 근거는 `GOOD_TRIGGER(9) vs NO_SETUP(9)`,
`GOOD_TRIGGER(9) vs TOO_EARLY(8, feature에 따라 결측 1건 시 유효 n=7)`,
`SETUP→GOOD_TRIGGER(7) vs
WATCH→TOO_EARLY/NO_SETUP(16)`, `POSITIVE_STRUCTURE(15) vs
EARLY_OR_NONE(17)`.

--------------------------------------------------------------------------------
12. Weekly Stage Separation
--------------------------------------------------------------------------------

`artifacts/pattern_a_fast/research/weekly_trigger_stage_summary_v01.csv`에
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

|spearman| >= 0.85 쌍 42건(`weekly_trigger_feature_correlation_v01.csv`).
대표: `close_vs_wma200_pct`/`high_vs_wma200_pct`=0.992,
`post_breakout_min_close_vs_level_pct_26w`/`post_breakout_min_low_vs_
level_pct_26w`=0.986, `weeks_since_26w_close_breakout`/`higher_low_after_
breakout_count`=0.980, `close_vs_wma200_pct`/`wma200_slope_1w`=0.956,
`weekly_low_slope_13w`/`weekly_return_13w`=0.946(§17에서 다룬 것처럼
`weekly_low_slope_13w`가 사실상 momentum의 재표현임을 보여주는 쌍),
`distance_to_prior_26w_high_pct`/`distance_to_prior_52w_high_pct`=0.941,
`close_vs_wma52_pct`/`wma52_slope_1w`=0.936, `weekly_low_slope_8w`/
`weekly_return_8w`=0.924, `wma12_slope_1w`/`weekly_low_slope_8w`=0.908,
`range_position_26w`/`range_position_52w`=0.863. 0.85는 research
redundancy 표시 기준일 뿐 production threshold가 아니다(§14).

HIGH 후보 8개(§17) 상호간에는 |spearman|>=0.85 쌍이 하나도 없음을 별도
확인했다 — 서로 다른 latent concept을 대표하도록 선정했다는 근거다.

--------------------------------------------------------------------------------
14. Human Observation Mapping
--------------------------------------------------------------------------------

| Human Observation | Candidate Feature | 확인 |
|---|---|---|
| 직전 고점 돌파 전이라 조금 이름 | `distance_to_prior_26w_high_pct` | YES — GOOD vs NO_SETUP 0.753 |
| 고점 돌파 후 지지 성공 | `post_breakout_min_low_vs_level_pct_26w`, `post_breakout_close_hold_ratio_26w` | YES — 전체 최상위 분리력(0.944) |
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

**B. 현대해상 `001450_20260116`** (SETUP→GOOD_TRIGGER): `distance_to_prior_
26w_high_pct=-0.153`(안국약품보다 고점에서 더 멀다), `weeks_since_26w_
close_breakout=28.0`(오래된 돌파), `post_breakout_close_hold_ratio_26w=
0.786`(강한 지지). 안국약품(TRIGGER)과 비교해 "아직 고점 접근이 안 됐다"는
점이 SETUP에 머무른 이유로 읽힌다 — 지지 자체는 오히려 더 강했다.

**C. 오리온홀딩스 `001800_20250321`** (SETUP→GOOD_TRIGGER): `close_vs_
wma200_pct=NaN`(200주 이력 부족), `higher_weekly_low_count_13w=7.0`(최대치
근접), `weeks_since_26w_close_breakout=20.0`, `hold_ratio=0.0`(주의:
breakout이 있었지만 이후 hold는 실패 — 그럼에도 higher-low 구조 자체는
건강). Higher-low family가 breakout hold family와 반드시 같은 방향을
가리키지는 않음을 보여주는 사례.

**D. LG이노텍 `011070_20200925`** (SETUP→GOOD_TRIGGER, 정석적인 Positive):
`weeks_since_26w_close_breakout=12.0`(안국약품과 동일 sweet spot 대역),
`close_vs_wma200_pct=0.159`, `weeks_above_wma200_recent_12w=12.0`(12주
내내 200선 위), `range_position_26w=0.617`. HIGH 후보들이 일관되게
"건강한" 값을 보이는 대표 사례.

**E. 선광 `003100_20250822`** (WATCH→FALSE_TRIGGER): `close_vs_wma200_
pct=-0.615`(200선 아래 61.5%), `post_breakout_close_hold_ratio_26w=0.0`,
`post_breakout_min_close_vs_level_pct_26w=-0.132`. False Breakout Feature가
정확히 "실패"를 가리킨 사례.

**F. 서흥 `008490_20250328`** (WATCH→FALSE_TRIGGER): weekly feature
13개가 결측(200주 이력 부족 + breakout 계열 다수 NaN) — 단순 breakout
여부만으로 GOOD 판단하면 안 된다는 w.md 경고를 데이터 가용성 측면에서도
보여주는 사례(feature가 부족한 상태에서도 Human은 판단을 내렸다는 것,
Weekly Feature Research의 한계로 §18에 기록).

**G. 삼화전기 `009470_20250627`** (WATCH→FALSE_TRIGGER): `weeks_since_
26w_close_breakout=60.0`(오래됨), `post_breakout_close_hold_ratio_26w=
0.167`, `post_breakout_min_close_vs_level_pct_26w=-0.513`(51.3% 이탈,
40개 중 최악). 여러 breakout attempt 후 마지막 지지 실패라는 w.md 서술과
정확히 일치하는 수치.

**H. LG디스플레이 `034220_20200925`** (WATCH→FALSE_TRIGGER):
`weeks_since_26w_close_breakout=2.0`(매우 최근), `hold_ratio=0.5`(절반).
강한 저항 돌파 시도 후 support conversion 실패라는 서술과 일치 — breakout
자체는 최근이지만 hold가 불완전.

**I. 우리기술 Pair `032820`** — GOOD(`20251226`): `weeks_since_26w_close_
breakout=27.0`, `hold_ratio=1.00`(완벽 지지), `close_vs_wma200_pct=0.738`,
`range_position_26w=0.196`(26주 range 자체가 넓어 최근 위치는 낮게 관측),
`recent_8w_max_runup=0.174`. TOO_LATE(`20260327`): `weeks_since_26w_close_
breakout=1.0`(방금 재돌파), `hold_ratio=0.0`(관찰 구간 짧음), `close_vs_
wma200_pct=7.30`(200주선 대비 **730%** 위, 극단적), `weeks_above_wma200_
recent_12w=12.0`, `recent_8w_max_runup=5.61`(561%), `consecutive_positive_
weeks=0.0`(reference 주 자체는 종가 기준 하락 마감했다는 뜻 — 극단적으로
연장된 상승 뒤에도 최근 한 주는 눌림이 있을 수 있어, 연속상승 카운터
단독으로는 TOO_LATE를 못 잡는다는 것을 보여주는 사례). `close_vs_
wma200_pct`가 0.738→7.30으로 10배 가까이 뛴 것이
이번 연구에서 확인한 가장 극단적인 GOOD→TOO_LATE 이동 사례다.

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

**L. 한화솔루션 `009830_20250328`** (WATCH→BORDERLINE_TRIGGER):
`weeks_since_26w_close_breakout=135.0`(40개 중 최대치권, 매우 오래됨),
`hold_ratio=0.081`(매우 약함), `post_breakout_min_close_vs_level_pct_
26w=-0.748`(74.8% 이탈, 40개 중 최악에 가까움), `close_vs_wma200_pct=
-0.523`. 수치만 보면 FALSE_TRIGGER 그룹과 거의 구분이 안 될 정도로
나쁜데 Human은 BORDERLINE_TRIGGER로 판단 — GOOD/FALSE 사이의 애매한
구조라는 w.md 서술대로, "돌파 이후 구조 훼손 후 재지지/재돌파" 같은
질적 서사가 이 단순 window 기반 feature들로는 다 안 잡힌다는 것을
보여주는 중요한 반례다.

**M. 에이프로젠바이오로직스 `003060_20260327`** (WATCH→NO_SETUP, 이후
초대형 급등 — Negative Structural Anchor): `weeks_since_26w_close_
breakout=137.0`(최대치), `hold_ratio=0.022`(거의 0), `post_breakout_min_
close_vs_level_pct_26w=-0.916`(**91.6% 이탈**, 40개 중 최악),
`close_vs_wma200_pct=-0.840`, `range_position_26w=0.131`(하단). reference_
date 시점 Weekly 구조는 명백히 완전 붕괴 상태 — 향후 급등을 설명하기
위해 이 값들을 억지로 Positive로 해석하지 않았다.

**N. 에이치엠넥스 `036170_20251226`** (SETUP→GOOD_TRIGGER, Investability
observation 별도): `weeks_since_26w_close_breakout=71.0`(오래됨),
`hold_ratio=0.042`(매우 약함), `close_vs_wma200_pct=-0.144`(200선 아래).
구조적으로 다른 GOOD_TRIGGER 사례들만큼 강하지 않다 — 동전주 노이즈일
가능성과, Weekly Feature 자체의 한계일 가능성을 구분할 수 없다는 점을
투명하게 기록한다. Weekly Feature에 raw price hard filter는 추가하지
않았다(§2 item 14 금지 준수).

--------------------------------------------------------------------------------
16. Monthly vs Weekly Incremental Value
--------------------------------------------------------------------------------

`monthly_weekly_research_join_v01.csv`(13D matrix를 그대로 읽어 join,
재계산 없음)로 Weekly HIGH 8개와 Monthly HIGH 7개 간 실제 상관을 확인했다.

Q1(Monthly HIGH만으로 잘 설명된 sample): 에이프로젠(§15-M)은 Monthly
(`drawdown_from_12m_high` 등)와 Weekly(`post_breakout_min_close_vs_
level_pct_26w=-0.916`) 둘 다 극단적으로 나쁜 방향을 가리켜, 이 sample은
두 스케일이 일치해서 Monthly만으로도 상당 부분 설명된다.

Q2(Monthly는 애매했는데 Weekly가 추가 구분): 우리기술 TOO_LATE(§15-I)에서
Monthly `range_position_24m`은 극단값이지만 `close_vs_wma200_pct`가
0.738→7.30으로 이동한 것과 `recent_8w_max_runup`이 5.61에 달한 것은
Weekly만이 포착하는 정보다. 안국약품(§15-A)의 "10주 전 돌파 후 재접근"
서사도 Monthly 스케일에서는 아예 안 보이는 정보다.

Q3/Q4(Monthly+Weekly 둘 다 좋아 보였지만 FALSE_TRIGGER): 한화솔루션
(§15-L)이 대표 사례 — Monthly HIGH 값들은 §15에서 다루지 않았지만 이후
BORDERLINE으로 판정된 반면, Weekly hold quality(`hold_ratio=0.081`,
`min_close_vs_level=-0.748`)는 FALSE_TRIGGER 수준으로 나쁘다. 여기서
보이는 Weekly failure-risk feature는 `post_breakout_close_hold_ratio_
26w`와 `post_breakout_min_close_vs_level_pct_26w` 둘 다다.

Q5(우리기술 pair에서 Weekly가 Monthly보다 entry window를 더 정확히
표현했는가): YES — §15-I/§16-Q2 참고, `close_vs_wma200_pct`의 10배
가까운 변화와 `recent_8w_max_runup`의 급증이 Monthly 스케일보다 훨씬
세밀하게 시점을 짚어낸다.

Q6(안국약품 explicit TRIGGER의 Weekly feature space 위치): "이미 완전히
돌파해 안정적으로 안착한" 위치가 아니라 "1차 돌파 후 조정을 거쳐 재접근
중"인 위치다(§15-A) — `weeks_since_26w_close_breakout=10`이 GOOD_TRIGGER
median(12)과 거의 일치하는 것도 이 sweet-spot 가설(§7)을 뒷받침한다.

상관 수치로 본 정량적 결론: Weekly HIGH 8개 중 `distance_to_prior_26w_
high_pct`(Monthly HIGH와 상관 0.22~0.61, 대체로 낮음), `higher_weekly_
low_count_13w`(0.17~0.45), `rolling_low_4w_change`(0.22~0.45),
`weeks_since_26w_close_breakout`(-0.43~-0.66, 음의 방향이지만 중간 강도)
는 Monthly와 뚜렷이 구분되는 정보를 담고 있다. 반면 `close_vs_wma200_
pct`/`wma52_slope_1w`/`range_position_52w`/`post_breakout_min_low_vs_
level_pct_26w`는 Monthly HIGH(특히 `close_vs_ma24_pct`, `drawdown_from_
12m_high`)와 0.7~0.83대의 상당히 높은(0.85 미만이라 §14 기준상 "높은
상관"으로 flag되지는 않지만) 상관을 보인다 — 이는 "장기 구조가 좋으면
Weekly 구조도 대체로 좋다"는 자연스러운 결과이지, 두 스케일이 완전히
독립적이지는 않다는 것을 뜻한다. Monthly가 permission을 주고 Weekly가
trigger를 당긴다는 역할 분리는 데이터에서 대체로 유지되지만, 완전히
직교하지는 않는다는 것이 이번 연구의 정량적 결론이다.

--------------------------------------------------------------------------------
17. HIGH / MEDIUM / LOW Candidates
--------------------------------------------------------------------------------

**HIGH PRIORITY (8개)** — HIGH가 Production Feature 확정을 의미하지
않는다. 다음 단계(13F Daily, 그리고 13D와의 결합) 연구 가치가 높다는
뜻일 뿐이다.

1. **`post_breakout_min_low_vs_level_pct_26w`** — 왜: GOOD_TRIGGER vs
   NO_SETUP Cliff's Delta **0.944**(48개 feature 중 최상위), GOOD vs
   TOO_EARLY 0.810, SETUP→GOOD vs WATCH→EARLY/NONE 0.857. Human
   Observation: "고점 돌파 후 지지 성공/실패"의 가장 직접적인 대응
   (§8/§14). 약점: `post_breakout_min_close_vs_level_pct_26w`와 corr
   0.986(형제, 대표만 채택). event가 없는 3개 샘플은 구조적으로 NaN.
   Monthly 중복 가능성: 낮음(§16, corr 0.79~0.83으로 중간 수준).
2. **`close_vs_wma200_pct`** — 왜: GOOD vs NO_SETUP 0.792, GOOD vs
   FALSE_TRIGGER 0.750(n=3 descriptive). Human Observation: "주봉 200
   이평 저항"(Q7, 13D 이관)의 직접 대응. 약점: `high_vs_wma200_pct`와
   corr 0.992(중복), `wma200_slope_1w`와도 0.956. Monthly 중복: 있음
   (`MONTHLY_close_vs_ma24_pct`와 corr 0.80 — 장기 이평 이격 개념이
   스케일만 다를 뿐 유사).
3. **`distance_to_prior_26w_high_pct`** — 왜: GOOD vs NO_SETUP 0.753,
   SETUP→GOOD vs WATCH 0.571. Human Observation: "직전 고점 접근/돌파"의
   가장 단순한 연속형 표현, w.md 예시(26w)와 window 일치. 약점: 13w/52w
   형제와 0.89/0.94 상관. Monthly 중복: 낮음(corr 0.22~0.61) — Weekly
   고유 정보에 가장 가까운 후보 중 하나.
4. **`weeks_since_26w_close_breakout`** — 왜: 단조 관계가 아니라 **U자형
   sweet-spot 패턴**(§7)이라는 이번 연구의 핵심 발견. GOOD_TRIGGER median
   12, FALSE_TRIGGER 6, TOO_EXTENDED 4, TOO_LATE 1, NO_SETUP 61,
   TOO_EARLY 56. 단순 Cliff's Delta(-0.309)로는 이 신호가 저평가된다 —
   비선형 관계라는 것 자체가 finding. 약점: 39/40이 breakout state
   boolean과 달리 이 feature는 결측 2건(NOT_OBSERVED). Monthly 중복:
   중간(corr -0.43~-0.66).
5. **`higher_weekly_low_count_13w`** — 왜: GOOD vs NO_SETUP 0.765. Human
   Observation: "저점이 점점 높아짐"(가장 자주 언급된 관찰)의 가장 단순한
   연속형 근사. 약점: 8주 버전은 훨씬 약함(0.370) — 짧은 창은 노이즈에
   취약. Monthly 중복: 낮음(corr 0.17~0.45), Weekly 고유 정보.
6. **`wma52_slope_1w`** — 왜: GOOD vs TOO_EARLY **0.833**(최상위),
   GOOD vs NO_SETUP 0.506. Human Observation: "장기 하락 압력이 개선
   중인가"에 대응. 약점: `close_vs_wma52_pct`와 corr 0.936(형제).
   Monthly 중복: 있음(`MONTHLY_close_vs_ma24_pct`와 corr 0.83).
7. **`wma12_vs_wma26_pct`** — 왜: GOOD vs TOO_EARLY 0.722. Human
   Observation: "정배열/역배열"의 단기 축. 약점: `wma52_vs_wma200_pct`
   (장기 축)와는 상관이 낮아 서로 보완적이지만, 각각 단독으로는 중간
   강도. Monthly 중복: 낮음(corr 0.35~0.63).
8. **`rolling_low_4w_change`** — 왜: GOOD vs NO_SETUP 0.704. Human
   Observation: "저점 상승 속도"를 담는 유일한 HIGH 후보(higher-low
   count가 "얼마나 자주"라면 이건 "얼마나 빨리"). 약점: 8주 버전과는
   개념적으로 유사하나 실측 상관은 낮게 나와(<0.85) 형제로 강등하지
   않음. Monthly 중복: 낮음(corr 0.22~0.45).

**MEDIUM PRIORITY**: `range_position_52w`(GOOD vs TOO_EARLY 0.806, GOOD
vs NO_SETUP 0.728로 수치 자체는 HIGH급이지만 `range_position_26w`와 corr
0.863으로 0.85 임계를 넘어 §14 기준상 형제 대표성 문제가 있어 MEDIUM으로
분류 — HIGH 8개는 상호 |corr|<0.85 조건을 전부 만족하도록 유지),
`close_vs_wma52_pct`(wma52_slope_1w의 형제),
`wma200_slope_1w`/`weeks_above_wma200_recent_12w`/`high_vs_wma200_pct`
(close_vs_wma200_pct 계열의 형제 또는 약한 신호), `wma52_vs_wma200_pct`
(close_vs_wma200_pct와 corr 0.93), `distance_to_prior_13w/52w_high_pct`
(26w의 형제), `post_breakout_min_close_vs_level_pct_26w`/`post_breakout_
close_hold_ratio_26w`(min_low_vs_level의 형제 또는 보조),
`weekly_low_slope_13w`(higher_low_count의 보조로 기대했으나 실측 결과
`weekly_return_13w`와 corr 0.946 — 사실상 momentum 계열의 재표현), `rolling_
low_8w_change`, `weeks_since_26w_low`, `weekly_ma_spread_pct`/
`wma12_wma26_gap_pct`(FALSE_TRIGGER 방향에서는 강하나 n=3-4 descriptive),
`weekly_return_13w`/`weekly_positive_ratio_8w`, `distance_from_52w_low_
pct`, `range_position_26w`(52w의 형제), `close_back_below_breakout_
level`(방향은 맞으나 중간 강도).

**LOW / REJECTED**: `close_above_prior_26w_high`/`high_above_prior_26w_
high`(39-40/40 상수, 분리력 없음 — §7의 핵심 finding), `weeks_closed_
above_breakout_level_26w`(post window 길이 차이로 절대 카운트 오염,
GOOD vs NO_SETUP 0.069), `higher_low_after_breakout_count`(weeks_since_
breakout과 corr 0.980 완전 중복), `higher_weekly_low_count_8w`(8주 창이
13주 창보다 일관되게 약함), `weekly_low_slope_8w`(GOOD vs TOO_EARLY=
-0.028로 매우 약하고, `weekly_return_8w`/`wma12_slope_1w`/`close_vs_
wma12_pct`와 corr 0.90~0.92 — "저점 기울기"가 아니라 사실상 종가 momentum의
재표현일 뿐임이 실측으로 드러남), `distance_from_13w/26w_low_pct`(방향
반직관적, §9), `weekly_down_week_ratio_8w`, `recent_4w_return_vs_prior_
12w`(SETUP_GOOD vs WATCH=0.000), `weekly_return_4w/8w/26w`,
`distance_from_wma12_pct`(=close_vs_wma12_pct, GOOD vs TOO_EARLY=0.056로
매우 약함), `wma26_slope_1w`(GOOD vs FALSE=0.111), `recent_8w_max_
runup`(방향 반직관적, §10 — 그룹 통계보다 개별 사례에서만 신뢰 가능),
`consecutive_positive_weeks`(방향 애매).

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
- `post_breakout_*` 계열은 breakout event가 없는 샘플(3개)에서 전부
  NaN이다 — "돌파가 아예 없다"와 "돌파했지만 값을 못 구했다"를 구분하지
  못하면 안 되므로, 이 3개는 §7.4/§7.5 다른 feature(전부 NaN 또는 0)로
  교차 확인 가능하도록 뒀다.
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
않았다. 40개 calibration sample을 완벽히 분리하는 것이 목적이 아니었고
(§2 item 3), 실제로 어떤 단일 feature도 40개를 깔끔히 분리하지 못했다
(최고 Cliff's Delta도 0.944로 1.0 미만).

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
출발점으로 제안한다. 추가로, `post_breakout_*` 계열의 강한 분리력을
감안하면 Phase 13F에서 "돌파 이후 며칠 내 매수 타이밍"을 다루는 Daily
Feature가 이 Weekly hold-quality 신호와 어떻게 상호작용하는지가 유망한
연구 방향으로 보인다(단, 이 역시 이번 라운드에서 확정하지 않은 제안일
뿐이다).
