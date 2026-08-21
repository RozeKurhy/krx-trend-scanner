# Pattern A Fast Monthly Regime Feature Research v0.1

================================================================================
0. 문서 상태
================================================================================
Phase: 13D — Monthly Regime Feature Research
Status: **MONTHLY REGIME FEATURE RESEARCH COMPLETE / ADVISOR REVIEW PENDING**
(advisor가 실제 commit/artifact/feature distribution을 검토해 PASS하기
전까지 CLOSED로 선언하지 않는다, w.md §30)
Base SHA: `2e5a87f8214fe91d6cd2dbfa2bdc03cc2453d696` (Phase 13C-2
CLOSED/FROZEN 시점)
Data cutoff (as_of): 2026-08-14
Network requests: 0 (전부 로컬 `data/raw/stocks/*.parquet` 캐시)

--------------------------------------------------------------------------------
1. Research Scope
--------------------------------------------------------------------------------
"Pattern A Fast에서 월봉이 어떤 장기 환경을 허용하고, 어떤 장기 환경을
차단해야 하는가"를 Phase 13C-2에서 CLOSED된 40-sample Human Calibration
Set으로 연구한다. Monthly는 13A 계약대로 Entry Signal이 아니라 **Regime/
Environment Layer**다 — "이 종목이 지금 빠른 상승 전환을 연구할 만한
장기 위치인가?"만 묻는다.

**이번 Phase가 하지 않는 것(§23 Explicit Non-Decision)**: Monthly PASS/
FAIL rule, Monthly numeric threshold, Production Feature Set, Pattern A
Fast Score, Pattern A Fast Classifier, Weekly Trigger rule, Daily Entry
rule — 이번 결과는 **RESEARCH EVIDENCE ONLY**다.

--------------------------------------------------------------------------------
2. 40 Human Calibration Summary
--------------------------------------------------------------------------------
`artifacts/pattern_a_fast/ground_truth/pattern_a_fast_human_review_v01.csv`
에서 `weekly_stage_at_reference != UNLABELED AND human_label !=
UNLABELED`인 40건만 사용했다(Total Dataset 60 중 나머지 20건은 자동
추론하지 않고 완전히 제외).

| Human Label | 건수 |
|---|---|
| GOOD_TRIGGER | 9 |
| BORDERLINE_TRIGGER | 6 |
| FALSE_TRIGGER | 4 |
| TOO_EARLY | 8 |
| TOO_LATE | 1 |
| TOO_EXTENDED | 3 |
| NO_SETUP | 9 |
| **합계** | **40** |

이 40개는 prevalence estimation dataset이 아니라 calibration/feature
discovery dataset이다 — label 비율을 시장 전체 성공률로 해석하지 않는다
(13C-2 계약 그대로 승계).

--------------------------------------------------------------------------------
3. Leakage Control
--------------------------------------------------------------------------------
모든 Monthly Feature는 `reference_date` 당시 PIT snapshot(
`build_historical_snapshot(..., include_incomplete_periods=False)`)의
`monthly` DataFrame만 입력으로 사용한다 — `reference_date` 이후 데이터,
`outcome_review_end`까지의 가격, `human_label`, `source_reason`의
forward 정보, Pattern A future stage, forward return/drawdown/breakout은
Feature 계산에 전혀 사용하지 않았다.

검증 방법(targeted test로 커버, §20):
* `test_no_future_daily_row_influence`: 원본 daily 뒤에 실제 미래 행을
  이어붙인 뒤 전체 파이프라인(`build_historical_snapshot` →
  `compute_monthly_regime_features`)을 다시 통과시켜도 feature 값이
  bit-identical함을 확인.
* `test_incomplete_future_monthly_period_does_not_affect_features`:
  `reference_date` 이후 아직 완료되지 않은 달의 daily row가 섞여도
  completed-period 계약 때문에 영향 없음을 확인.
* `test_insufficient_history_fails_safe_to_nan`: 이력 부족 시 짧은
  창으로 silent fallback하지 않고 `NaN`으로 fail-closed 처리됨을 확인.
* 스크립트 자체에도 `assert snapshot.monthly.index.max() <=
  reference_date`를 추가로 넣어 이중으로 machine-check했다.

`human_label`은 Feature 계산 이후 분포 비교/그룹 분석에만 사용했다 —
Feature 계산 함수(`compute_monthly_regime_features`)는 `human_label`을
인자로 받지 않는다(함수 시그니처 자체가 이를 구조적으로 차단).

--------------------------------------------------------------------------------
4. Candidate Feature Definitions
--------------------------------------------------------------------------------
`src/trend_scanner/research/pattern_a_fast_monthly_features.py`의
`FEATURE_SPECS`에 37개 Feature 전부 `feature_name`/`formula`/
`required_history_bars`/`timeframe`/`pit_safe`/`missing_behavior`/
`human_interpretation`/`research_question`/`family`를 기계가 읽을 수
있는 형태로 문서화했다(§7 요구사항). 7개 Family(§6.1~§6.7) 전부 최소
2개 이상 구현했다:

| Family | 구현 Feature 수 |
|---|---|
| 6.1 Long-Term Return/Drawdown | 8 |
| 6.2 Monthly MA Structure | 9 (그중 3개는 진단용 raw MA, 분석 대상 6) |
| 6.3 MA Alignment/Compression | 6 |
| 6.4 Long-Term Range Position | 3 |
| 6.5 Recovery/Bottoming Proxy | 3 |
| 6.6 Trend Deceleration/Reversal | 5 |
| 6.7 Extended/Overheated Position | 3 |
| **분석 대상 합계** | **37 (진단용 3 제외 34)** |

모든 window는 **bar-count 기준**(`iloc[-n:]`)이며 달력 월 기준이
아니다 — 거래정지 등으로 gap이 생기면 "최근 12개월"이 실제로는 "최근
12개 completed monthly bar"를 의미한다(formula에 명시).

전체 정의는 `FEATURE_SPECS` 참고. 40개 샘플 전부 `completed_monthly_
bars_at_reference >= 37`(13C-1 Monthly Review Data Sufficiency Gate)
이므로 이번 40개에서는 **모든 Feature의 결측이 0건**이었다(§8 최소
이력 요구사항은 만족되지만, 다른 sample set에 재사용할 경우 결측이
발생할 수 있음을 유의 — fail-safe NaN 로직은 이미 구현/테스트됨).

--------------------------------------------------------------------------------
5. Feature Distribution Summary
--------------------------------------------------------------------------------
37개 Feature 전체 × count/missing_count/mean/median/std/min/max/p25/p75
+ human_label별 count/median/IQR + Research Group별 median/IQR + 주요
pair comparison(§12 요구사항 3종 전부: median 차이 `median_diff_*`,
pooled-IQR로 표준화한 effect size `standardized_effect_*`, 순위 기반
분리력 `cliffs_delta_*`, n 포함)은. **주의**: `standardized_effect_*`의
분모는 두 그룹을 합친 전체 표본의 IQR이다 — 두 그룹이 완벽히 분리될수록
합친 분포는 bimodal이 되어 IQR 자체가 커지므로, 이 지표는 분리가 가장
좋을 때 오히려 작게 나올 수 있다(분모 문제이지 분리력 모순이 아님).
`cliffs_delta_*`가 이번 문서의 1차 랭킹 근거이고 `standardized_effect_*`
는 보조 참고용인 이유다.
`artifacts/pattern_a_fast/research/monthly_regime_feature_summary_v01.csv`
에 전부 기록했다(37행 × 다수 컬럼 — 마크다운 표로 인라인하기엔
비현실적이라 CSV로만 제공, 이 문서는 랭킹/비교/사례만 요약).

**중요(표본 크기 주의)**: `TOO_LATE`는 n=1, `TOO_EXTENDED`는 n=3,
`FALSE_TRIGGER`는 n=4다. 이 그룹이 낀 pair comparison(특히
`GOOD_TRIGGER vs TOO_EXTENDED`, `GOOD_TRIGGER vs FALSE_TRIGGER`)의
Cliff's Delta는 **참고용 서술(descriptive)일 뿐 랭킹 근거로 쓰지
않는다** — n=1/3/4 대 n=9의 비교는 통계적으로 신뢰할 수 있는 분리력
측정이 아니다. `GOOD_TRIGGER(9) vs NO_SETUP(9)`, `GOOD_TRIGGER(9) vs
TOO_EARLY(8)`, `SETUP→GOOD_TRIGGER(7) vs WATCH→TOO_EARLY/NO_SETUP(16)`
세 비교만 랭킹의 주 근거로 사용했다. 그 외에도 40개 전체가 여전히
"40개 calibration sample에서 통계적으로 유의하다/아니다를 최종 기준으로
삼지 않는다"는 w.md §12 원칙을 따른다 — 목적은 ranking/분포 관찰/후보
축소이지 가설검정이 아니다.

--------------------------------------------------------------------------------
6. Human Label Separation Summary (§11 Research View)
--------------------------------------------------------------------------------
원본 7개 label은 그대로 보존하고, 분석 편의를 위한 Research Group을
추가했다(label을 대체하지 않음):

* **A. POSITIVE_STRUCTURE** = GOOD_TRIGGER(9) + BORDERLINE_TRIGGER(6) = 15
* **B. FAILED_STRUCTURE** = FALSE_TRIGGER(4)
* **C. EARLY_OR_NONE** = TOO_EARLY(8) + NO_SETUP(9) = 17
* **D. LATE_OR_EXTENDED** = TOO_LATE(1) + TOO_EXTENDED(3) = 4

그룹별 median/IQR도 summary CSV에 포함했다.

--------------------------------------------------------------------------------
7. Correlation / Redundancy Summary
--------------------------------------------------------------------------------
Spearman correlation, `abs(corr) >= 0.85` 전부
`artifacts/pattern_a_fast/research/monthly_regime_feature_correlation_v01.csv`
에 기록(41쌍). **0.85는 production threshold가 아니라 research
redundancy 표시 기준일 뿐이다.**

주요 발견(중복성이 명확한 것들):
* `ma_spread_pct` == `max_ma_gap_pct` (corr **1.000**, 세 MA 중 2개가
  항상 최대/최소 쌍을 형성하는 이 표본 구성에서는 대수적으로 거의
  동일값) — 하나만 대표로 남기고 나머지는 MEDIUM/LOW로 강등.
* `close_above_ma_count` / `close_below_ma_count` (corr **-1.000**,
  정의상 합이 3으로 고정되므로 완전 역상관 — 당연한 결과, 하나만 채택).
* `return_12m` / `ma12_slope_1m` (corr **0.999**), `return_6m` /
  `ma6_slope_1m` (corr **0.999**), `return_24m` / `ma24_slope_1m`
  (corr **0.995**) — "수익률"과 "그 스케일의 이평 1개월 기울기"는
  이 40개에서 사실상 같은 정보.
* `monthly_down_month_ratio_6m` / `monthly_up_month_ratio_6m` (corr
  **-0.976**, 정의상 상보적) — 하나만 채택.
* `range_position_*` 3개 서로 0.88~0.94로 강하게 상관, `close_vs_ma*_pct`
  계열과도 0.85+ 다수 — "장기 고점/저점 대비 위치"라는 하나의
  잠재개념(latent construct)을 여러 창/방식으로 측정한 결과로 해석.

동일 정보를 표현하는 Feature 5개를 전부 다음 단계 핵심 후보로 추천하지
않았다(§12 Top Research Candidates에서 대표만 선정).

--------------------------------------------------------------------------------
8. Human Observation → Feature Mapping (§15)
--------------------------------------------------------------------------------
| Human Observation | Candidate Feature | Monthly에서 설명 가능? |
|---|---|---|
| 역배열 + 장기 하락 | `ma_alignment_score`, `close_below_ma_count`, `close_vs_ma24_pct`, `return_12m` | YES |
| 바닥이 아직 없다 | `months_since_12m_low`, `higher_monthly_low_count_12m`, `drawdown_from_12m_high` | YES(근사) — 정확한 "저점 확정" 판단은 Weekly에서 더 명확할 수 있음(§6 Q6) |
| 이미 너무 많이 올랐다 | `range_position_12m/24m`, `close_vs_ma12_pct`, `recent_3m_return`, `recent_6m_max_runup` | YES |
| 주봉 200 이평이 위에 있다 | **NONE** | NO — Weekly 책임. `close_vs_ma24_pct`가 월봉 스케일에서 부분적으로 유사한 정보를 주지만(§4/§12 근거), 정확히 같은 개념은 아니다. Next Research: **Phase 13E Weekly Feature** |
| 이평선 엉킴 | `ma_spread_pct`(≈`max_ma_gap_pct`, §7 중복), `min_ma_gap_pct` | YES(근사) — 세 이평이 어느 정도 벌어져야 "엉킴이 아니다"인지의 정확한 경계는 이번 Phase에서 정하지 않음(§23) |
| 장기 하락 압력이 둔화 중인가 | `ma12_slope_change_3m`, `recent_3m_return_vs_prior_9m`, `monthly_down_month_ratio_12m` | YES(근사) — deceleration 신호가 존재하지만 효과크기는 크지 않음(§12 참고) |

억지로 Monthly에 모든 Human Observation을 설명시키지 않았다 — "주봉 200
이평 저항"은 명시적으로 Weekly 책임으로 남겨뒀다(§6 Q7 그대로).

--------------------------------------------------------------------------------
9. Special Sample Case Studies (§16)
--------------------------------------------------------------------------------
**A. 안국약품 `001540_20260213`** (PIT=TRIGGER → GOOD_TRIGGER, 유일한
explicit Trigger Positive Anchor): `range_position_24m=0.74`,
`drawdown_from_12m_high=-0.08`(고점에 근접), `ma_alignment_score=+1`
(정배열), `monthly_down_month_ratio_12m=0.33`. 세 HIGH 후보 모두 "이미
장기 하락에서 벗어나 고점권에 근접한" 방향을 가리켜, PIT 당시 사람이
TRIGGER로 본 판단과 정합적이다.

**B. 우리기술 Pair** — `032820_20251226`(SETUP→GOOD_TRIGGER)
`range_position_24m=0.60`, `drawdown_from_12m_high=-0.31`,
`recent_3m_return=0.00` vs `032820_20260327`(TREND→TOO_LATE)
`range_position_24m=0.91`, `drawdown_from_12m_high=-0.08`,
`recent_3m_return=3.42`(최근 3개월간 342% — 극단적 단기 급등).
`ma_alignment_score`는 두 시점 모두 +1(정배열 유지)로 **동일** —
즉 MA 정배열만으로는 이 pair를 구분하지 못하고, `range_position_24m`과
특히 `recent_3m_return`(Extended/Overheated family)이 "좋은 진입
window"와 "이미 늦은 window"를 명확히 갈랐다. Weekly Entry Window
연구(13E)에 중요한 근거.

**C. 천일고속 Pair** — `000650_20250926`(WATCH→TOO_EARLY)
`range_position_24m=0.21`, `ma_alignment_score=0` vs
`000650_20251226`(EXTENDED→TOO_EXTENDED, 3개월 뒤) `range_position_24m=
1.00`(창의 최상단), `recent_3m_return=4.70`(470%). 같은 종목이 단
3개월 만에 "장기 range 최하단 근처"에서 "장기 range 최상단"으로
이동했다 — Monthly Feature가 이 이동을 명확히 포착하며, "너무 이름 →
너무 늦음"이 얼마나 빠르게 일어날 수 있는지를 정량적으로 보여준다.

**D. LS Pair** — `006260_20200925`(WATCH→BORDERLINE_TRIGGER)
`ma_alignment_score=-1`(역배열) vs `006260_20221223`(SETUP→
GOOD_TRIGGER) `ma_alignment_score=0`(엉킴, 역배열 탈출 중),
`drawdown_from_12m_high`가 -0.13→-0.02로 고점에 훨씬 근접,
`higher_monthly_low_count_12m` 6→7. 구조 완성도(역배열 탈출 + 고점
근접 + higher-low 누적)가 실제로 Outcome 품질 차이(BORDERLINE →
GOOD)로 이어진 사례라는 Human 관찰과 Feature 방향이 일치한다.

**E. 에이프로젠바이오로직스 `003060_20260327`** (WATCH→NO_SETUP,
이후 초대형 급등한 negative structural anchor): `ma_alignment_score=
-1`(역배열), `drawdown_from_12m_high=-0.61`(고점에서 크게 이탈),
`range_position_24m=0.03`(창의 최하단 근처), `recent_3m_return=
-0.44`(하락 중), `higher_monthly_low_count_12m=2`(12개 중 2개월만
higher low). **모든 HIGH 후보가 일관되게 "구조적으로 나쁜 위치"를
가리켰다** — 이후 실제로 급등했다는 사실이 이 Feature들의 방향성을
무효화하지 않는다(§16 원문 그대로: "향후 급등 예측"과 "구조적으로
유효한 Fast Setup"은 다른 축). Feature Research가 이런 사례를 억지로
Positive로 만들려고 최적화되면 안 된다는 원칙을 이 문서도 그대로
따른다 — 이 sample을 설명하기 위해 사후적으로 threshold를 조정하지
않았다.

**F. 에이치엠넥스 `036170_20251226`** (SETUP→GOOD_TRIGGER,
Investability observation 대상): `ma_alignment_score=0`(엉킴),
`range_position_24m=0.36`, `drawdown_from_12m_high=-0.19`. 구조적으로는
중간 정도의 Positive 신호이며, Monthly Feature 값 자체는 동전주 여부와
무관하게 계산됐다 — 가격 수준(주가가 몇 원인지)은 이번 Feature
어디에도 입력되지 않는다(전부 %/ratio/count 기반). Investability
Universe 여부는 Monthly Feature Research와 완전히 분리된 축이라는
w.md §16-F 원칙을 그대로 유지했다.

--------------------------------------------------------------------------------
10. Top Research Candidates (§13, §22)
--------------------------------------------------------------------------------
7개 Family를 모두 대표하도록, 그리고 §7의 중복성 발견을 반영해 상관된
형제 Feature 중 하나만 대표로 선정했다. **HIGH PRIORITY라고 해서 이번
Phase에서 Feature를 Freeze한다는 뜻이 아니다** — 다음 단계(13E와의
결합) 연구 가치가 높다는 뜻일 뿐이다.

**HIGH PRIORITY (7개)**

1. **`range_position_24m`** — 왜: `GOOD_TRIGGER vs TOO_EARLY`에서
   Cliff's Delta **1.00**(완전 분리, n=9 vs 8), `SETUP→GOOD vs
   WATCH→EARLY/NONE`에서도 0.89로 최상위. Human Observation: "이미 너무
   많이 올랐다"/"바닥권 여부". 약점: `range_position_12m/36m`,
   `close_vs_ma24_pct`와 0.85+ 상관(§7) — 같은 잠재개념의 대표일 뿐,
   독립 신호로 과대평가하면 안 됨. Weekly와 중복 가능성: 낮음(월봉
   스케일 고유 정보).
2. **`drawdown_from_12m_high`** — 왜: `GOOD_TRIGGER vs NO_SETUP`에서
   Delta **0.95**(최상위), `SETUP→GOOD vs WATCH→EARLY/NONE`에서도 0.82.
   Human Observation: "장기 고점 대비 낙폭"/"바닥권". 약점: 24m/36m
   버전과 0.85+ 상관, 사실상 3개 창이 유사 정보. Weekly 중복: 낮음.
3. **`close_vs_ma24_pct`** — 왜: `GOOD_TRIGGER vs TOO_EARLY`에서 0.92.
   Human Observation: "주봉 200 이평 저항"의 월봉 근사(Q7, §8 mapping).
   약점: `return_12m`/`ma12_slope_1m`과 0.94+로 강하게 상관 — 독립
   신호라기보다 "장기 상승/하락 정도"의 또 다른 표현일 가능성. Weekly
   중복: 있음(진짜 200주 이평 저항은 Weekly에서 다뤄야 함, §8).
4. **`ma_alignment_score`** — 왜: LS pair(§9-D)와 에이프로젠(§9-E)
   사례에서 방향이 명확했고, `GOOD_TRIGGER vs TOO_EARLY`에서 0.78.
   Human Observation: "정배열/역배열"을 -1/0/+1로 직접 표현 — 이번
   HIGH 후보 중 유일하게 **연속형 magnitude가 아니라 순서형(ordinal)**
   이라 다른 후보들과 상관이 낮고 보완적. 약점: 우리기술 pair(§9-B)를
   전혀 구분하지 못함(둘 다 +1) — 정배열 여부만으로는 진입 시점의
   이르고 늦음을 못 가른다는 명확한 한계.
5. **`monthly_down_month_ratio_12m`** — 왜: `GOOD_TRIGGER vs NO_SETUP`
   에서 -0.78, `GOOD_TRIGGER vs FALSE_TRIGGER`에서 -0.97(단, n=4
   descriptive). Human Observation: 하락의 "빈도"(magnitude가 아니라
   persistence) — 다른 HIGH 후보 대부분이 magnitude 계열이라 낮은
   상관의 보완적 정보. 약점: 절대적 하락폭은 반영 못함.
6. **`higher_monthly_low_count_12m`** — 왜: `SETUP→GOOD vs
   WATCH→EARLY/NONE`에서 0.67, `GOOD_TRIGGER vs NO_SETUP`에서 0.74.
   Human Observation: "higher low"의 가장 단순한 연속형 근사(§6.5
   경고대로 pivot threshold 없이). LS pair(§9-D)에서 6→7로 실제
   변화를 포착. 약점: 단순 카운트라 "얼마나 확실한 higher low인지"의
   정도는 표현 못함.
7. **`recent_3m_return`** — 왜: 세 주요 비교 전부에서 중간 이상
   (0.58/0.61/0.46)이며 `GOOD_TRIGGER vs TOO_EXTENDED`에서도 -0.93
   (descriptive, n=3)로 우리기술/천일고속 case study의 핵심 근거였음.
   Human Observation: "단기 과열". 약점: `close_vs_ma6_pct`와 0.92
   상관 — 짧은 창 계열의 대표.

**MEDIUM PRIORITY**: `return_12m`(HIGH 후보들과 상관 높아 보조적),
`ma12_slope_1m`(return_12m과 사실상 동일 정보, §7), `months_since_
12m_low`(higher_monthly_low_count_12m보다 효과 약함), `ma12_slope_
change_3m`(TOO_EXTENDED에서 -1.00이지만 n=3 descriptive, 주요 3개
비교에서는 0.32~0.56로 약함), `range_position_12m`/`36m`(24m의
상관된 형제), `drawdown_from_24m_high`/`36m_high`(12m의 상관된
형제), `close_above_ma_count`/`close_below_ma_count`(둘 중 하나면
충분, 완전 역상관), `recent_6m_max_runup`(약함, -0.56/0.28/-0.21로
방향 일관성 부족), `return_6m`/`ma6_slope_1m`/`close_vs_ma6_pct`
(짧은 창 계열, recent_3m_return과 겹침).

**LOW / REJECTED**: `ma_spread_pct`/`max_ma_gap_pct`(corr=1.000, 완전
중복 — 대표 없이 둘 다 강등, min_ma_gap_pct가 개념적으로는 더
독립적), `monthly_up_month_ratio_6m`(down_ratio와 corr=-0.976, 완전
중복), `recent_3m_return_vs_prior_9m`(세 주요 비교에서
0.41/0.11/0.18로 약함 — deceleration 개념 자체는 유효할 수 있으나 이
정의로는 신호가 약함), `months_since_24m_low`(12m 버전보다 전반적으로
약함), `monthly_ma6`/`monthly_ma12`/`monthly_ma24`(진단용 raw 값,
파생 feature로만 의미 있음 — 애초에 순위분석 대상 아님).

**명시적으로 계산하지 않은 w.md §6 후보(이유와 함께 기록, 재현성
목적)**:
* `drawdown_recovery_pct` — `distance_from_Nm_low`와 대수적으로 동일
  정의가 되어 중복이라 스킵.
* MA slope의 **3개월 regression 변형** — 1개월 diff 버전만 구현,
  회귀 기반 변형은 다음 연구로 보류(§6.2 "어떤 방식이 정답인지 확정
  하지 말 것"에 따라 하나만 우선 구현).
* `ma24_slope_change` — `ma12_slope_change_3m` 하나만 대표로 구현,
  다른 스케일은 보류(feature 폭발 방지).
* `rolling_low_change` — 정의가 모호해(어떤 rolling window/step인지)
  이번 Phase에서 임의로 확정하지 않고 스킵.
* `negative_return_decay` — 명확한 단순 정의가 없어 §6.5의 "임의
  pivot/decay 공식을 과도하게 만들지 말 것" 경고에 따라 스킵.
* `monthly_close_recovery_from_low` — `distance_from_Nm_low`와 사실상
  동일한 공식이 되어 중복이라 스킵.
* `close_vs_ma12_pct`/`close_vs_ma24_pct`를 이용한 **"200주 이평
  저항"의 직접 구현** — 의도적으로 하지 않음(§8, Weekly 책임으로
  명시적 보류).

--------------------------------------------------------------------------------
11. Known Limitations
--------------------------------------------------------------------------------
* **표본 크기**: 40개 전체가 작고, `TOO_LATE`(1)/`TOO_EXTENDED`(3)/
  `FALSE_TRIGGER`(4)는 특히 작다. 이 그룹이 낀 효과크기는 전부
  descriptive로만 취급했다(§5). ~34개 분석 대상 feature × 5개 pair
  비교에서 n≈9 수준이면, 상위 효과크기 랭킹 안에 우연에 의한 잡음이
  섞여 있을 가능성이 구조적으로 있다 — 그래서 §10 HIGH 후보 선정에는
  효과크기 랭킹뿐 아니라 §9 case study의 구체적 사례 일치 여부도 함께
  반영했다.
* 이 40개는 in-sample calibration data다(§24 참고) — 다음 OOS
  단계에서 재사용 금지.
* Monthly Feature만으로는 "주봉 200 이평 저항"을 설명하지 못한다(§8).
* `ma_alignment_score`처럼 정배열 여부만 보는 Feature는 우리기술
  pair(§9-B)의 시점 차이를 구분하지 못했다 — Monthly만으로 Entry
  Window(진입 타이밍)를 좁히는 데는 명확한 한계가 있으며, 이는 Q4가
  묻는 "Monthly로 차단 vs Weekly confirmation 대기" 질문에 대한 근거
  자료이기도 하다: 이번 40개 결과는 Weekly confirmation이 필요하다는
  쪽에 가깝다.
* 높은 상관(§7)이 많다 — 37개 feature가 사실상 훨씬 적은 수의 잠재
  개념(magnitude 계열, position 계열, alignment 계열, frequency 계열)
  을 여러 창/방식으로 표현한 것에 가깝다.
* 동전주(Investability) 관찰(§9-F, §12)은 가격 수준과 무관하게
  계산되는 이 Feature들과 독립된 축이며, 이번 Phase에서 threshold를
  만들지 않았다(아래 §13).

--------------------------------------------------------------------------------
12. Penny Stock / Investability Observation (research note only)
--------------------------------------------------------------------------------
> User investability observation: very-low-price / penny-stock names may
> be outside the intended real trading universe. This is independent
> from structural Fast outcome quality. No price threshold is frozen in
> Phase 13C-2.

`036170`(에이치엠넥스) 관련 이 관찰은 13C-2에서 이미 기록됐고, 이번
Phase에서도 **가격 hard filter를 추가하지 않았다** — Phase 10
Investability Contract는 전혀 건드리지 않았다(§25 Frozen Artifacts).

--------------------------------------------------------------------------------
13. No Threshold Frozen / No Production Change Declaration
--------------------------------------------------------------------------------
**No Threshold Frozen.** `range_position_24m > X` 같은 어떤 PASS/FAIL
숫자도 확정하지 않았다. §10의 HIGH/MEDIUM/LOW는 다음 연구의 우선순위일
뿐 production rule이 아니다.

**No Production Change.** Pattern A production 코드(
`src/trend_scanner/patterns/`), Phase 10 Investability, Phase 11 Flow,
Phase 12 Relative Strength 전부 이번 commit에서 diff 없음(git diff로
확인). `src/trend_scanner/research/pattern_a_fast_monthly_features.py`
는 production evaluator나 scanner pipeline 어디에도 import되지 않는다
(targeted test `test_research_module_does_not_import_production_
pattern_a`로 커버).

--------------------------------------------------------------------------------
14. OOS / Calibration Separation
--------------------------------------------------------------------------------
이번 40개는 Human Calibration Set이다. 이 40개를 보고 Feature 후보를
발견하고 Threshold를 연구하고 Rule을 설계하게 되므로, **이 40개는 이미
in-sample calibration data다.** 향후 Phase 13I 또는 OOS Validation
단계에서는 이 40개를 그대로 OOS 성능 측정 대상으로 재사용하지 않고,
별도 unseen sample을 사용해야 한다.

--------------------------------------------------------------------------------
15. Artifacts
--------------------------------------------------------------------------------
* Feature matrix: `artifacts/pattern_a_fast/research/monthly_regime_feature_matrix_v01.csv` (40행 × 37 feature 컬럼 + identity/metadata 컬럼)
* Feature summary: `artifacts/pattern_a_fast/research/monthly_regime_feature_summary_v01.csv` (37행, feature별 분포/label별/그룹별/pair 비교 통계)
* Correlation findings: `artifacts/pattern_a_fast/research/monthly_regime_feature_correlation_v01.csv` (41쌍, `abs(spearman)>=0.85`)
* Research script: `scripts/research_pattern_a_fast_monthly_regime.py`
* Research helper: `src/trend_scanner/research/pattern_a_fast_monthly_features.py`
* Targeted tests: `tests/test_pattern_a_fast_monthly_feature_research.py` (8개, 전부 PASS)

--------------------------------------------------------------------------------
16. Next Research Recommendation
--------------------------------------------------------------------------------
1. **Phase 13E Weekly Trigger Feature Research**: 이번 Phase가 명시적으로
   Monthly 책임 밖으로 남긴 "주봉 200 이평 저항"(§8), 그리고 우리기술
   pair(§9-B)가 보여준 "Monthly만으로 Entry Window를 좁히지 못한다"는
   한계를 이어받아 Weekly 스케일 연구를 진행한다.
2. 13D와 13E 결과를 **결합하기 전까지는** 이번 Monthly 후보를 최종
   Pattern A Fast Rule로 확정하지 않는다(w.md §30 그대로).
3. HIGH 후보들(§10) 간 상관(§7)을 고려해, 다음 Phase에서 Feature Set을
   확정할 때는 중복 제거(예: `range_position_24m`과 `close_vs_ma24_pct`
   중 하나 선택)를 함께 고려해야 한다.

--------------------------------------------------------------------------------
17. Status
--------------------------------------------------------------------------------
**MONTHLY REGIME FEATURE RESEARCH COMPLETE / ADVISOR REVIEW PENDING.**
이 commit이 완료되어도 Phase 13D 결과를 자동으로 Production Contract로
Freeze하지 않는다. advisor가 실제 commit/artifact/feature distribution을
검토한 뒤 PASS하면 Phase 13D Research를 CLOSED하고 Phase 13E Weekly
Trigger Feature Research로 진행한다.
