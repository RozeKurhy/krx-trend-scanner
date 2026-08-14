# Pattern A Stage Classifier v0.1

## 목적

`docs/validation/pattern_a_stage.md`가 확정한 Stage 정의(BASE/TRANSITION/
EARLY_TREND/PROGRESSED/WEAK, "현재 Pattern A episode의 lifecycle 위치")와
`pattern_a_stage_manifest.py`의 46건 manual truth set(calibration truth set)을
근거로, Score와 독립적이고 rule-based로 설명 가능한 첫 production candidate
Stage classifier(`src/trend_scanner/patterns/pattern_a_stage.py`)를 구현했다.

**이번 라운드의 목표는 46건을 100% 맞추는 게 아니다.** v0.1이 구조적으로
어디까지 설명되는지 확인하고, 남는 실패는 v0.2 evidence로 남긴다. 특정
종목 하나를 맞추기 위해 global rule을 비틀지 않는다 — 이 원칙 때문에
실제로 포기한 override가 하나 있고(episode continuation 유지 로직), 그
경위를 "Episode / Cycle reset logic"과 "Known failure modes"에 그대로
기록한다.

**Calibration vs OOS 구분**: 이 46건은 Stage Classifier v0.1의 rule과
threshold를 설계하는 데 사용된 development/calibration truth set이다.
따라서 여기서 얻은 82.6%(38/46) 결과는 **calibration truth set exact
match rate**(reproduction rate)이며, 아직 독립된 external OOS accuracy가
아니다. 외부 OOS 검증은 다음 별도 단계(Stage v0.1 OOS Validation)에서
수행한다.

## Classifier architecture

```
classify_pattern_a_stage(snapshot: HistoricalSnapshot) -> StageClassificationResult
```

입력은 `HistoricalSnapshot`(raw `FeatureRow` + look-ahead 없는 monthly
OHLCV)이다. bare `FeatureRow`가 아니라 `HistoricalSnapshot`을 받는 이유는
episode/cycle reset 판정에 `snapshot.monthly`(과거 시점 series 재구성용)가
필요하기 때문이다.

```
StageEvidence          # 현재 snapshot 시점 evidence (8개 bool)
StageLifecycleContext  # snapshot 이전 과거 확장 프록시 및 cycle reset 상태
StageClassificationResult
    stage: PatternAStage | None
    reason_codes: tuple[str, ...]
    evidence: StageEvidence
    context: StageLifecycleContext
```

**Score와의 독립성**: `pattern_a_stage.py`는 `pattern_a_score` 모듈을
import하지 않고, `score_pattern_a()`/`base_score`/`transition_score`/
`balanced_core_score`/`alignment_bonus`/`confirmation_bonus`/
`progressed_penalty` 등 Score 파생값을 전혀 참조하지 않는다
(`tests/test_pattern_a_stage.py::test_module_does_not_import_pattern_a_score`,
`::test_module_source_does_not_reference_score_derived_names`로 검증).
`pattern_a_score.py`에는 이미 Score 파생값 기반 provisional stage
heuristic(`_classify_stage`)이 있지만 이번 커밋에서 건드리지 않는다 — 이
모듈은 그것과 독립된 별도 production candidate다.

## Stage evidence

`StageEvidence`(현재 snapshot 시점, raw `FeatureRow` 값에서만 파생):

| 필드 | 정의 |
|---|---|
| `active_decline` | 활발한 하락 국면(WEAK 후보) 여부 |
| `core_turning_positive` | `ma24_slope > 0` |
| `weekly_turning_positive` | `weekly_ma12_slope >= 0.03` |
| `breakout_like_structure` | core+weekly 양전환 + `range_position >= 0.60` |
| `near_resistance` | `distance_to_resistance <= 0.10` (진단용, 판정에 미사용) |
| `expansion_present` | `avg_price_change_12m >= 0.30` 또는 `ma_spread >= 0.20` |
| `price_extended` | `range_position >= 0.80` (진단용, 판정에 미사용 — 아래 참고) |
| `insufficient_data` | 필요한 7개 Feature 중 하나라도 NaN |

필요한 7개 Feature: `ma24_slope`, `weekly_ma12_slope`,
`ma24_slope_acceleration`, `avg_price_change_12m`, `ma_spread`,
`range_position`, `distance_to_resistance`. 하나라도 없으면
`stage=None`(새 enum 값을 추가하지 않고 기존 `insufficient_data` 패턴을
따른다).

**`range_position`은 36개월 monthly 기준을 쓴다** (`FeatureRow.range_position`,
`resistance.range_position(close, low_36m, high_36m)`), `range_position_52w`
(주간 기준)가 아니다. 이유는 두 가지다.

1. `pattern_a_stage_manifest.py`의 46건 `stage_reason`이 대부분 이 값을
   근거로 판정을 남겼다(1건만 `range_position_52w`를 보조로 언급) —
   기존 manual 판정 근거와 판정 축을 맞추기 위함.
2. `HistoricalSnapshot`에는 monthly만 있고 weekly가 없어서, 과거 시점
   series 재구성(episode 판정)에 monthly `range_position`만 재사용할 수
   있다.

## Threshold / rule rationale

전부 46건 calibration truth set에 기록된 실제 Feature 값을 손으로 대조해
잡았다(ML fitting이 아니다). 세 가지는 처음 설계에서 실측으로 틀렸다는 게
확인돼 수정한 것이다.

* **`weekly_turning_positive`를 `>0`이 아니라 `>=0.03`으로 잡았다.** `>0`만
  요구하면 BASE 중에도 weekly가 소폭 양수인 사례(015760/023530/011210/
  032830 등, `+0.007~+0.02`)가 전부 TRANSITION 신호로 오분류된다.
* **`expansion_present`는 AND가 아니라 OR다**
  (`avg_price_change_12m>=0.30` 또는 `ma_spread>=0.20`). AND로 두면
  000810 삼성화재 2024-06-30(`avg_chg=0.387`, `ma_spread=0.185`, truth
  PROGRESSED)이 `ma_spread` 문턱을 근소하게 못 넘겨서 EARLY_TREND로
  밀린다.
* **PROGRESSED 직접 판정에 `weekly_turning_positive`도 `range_position`도
  쓰지 않는다.** 처음에는 "`breakout_like_structure` + `expansion_present`
  또는 `price_extended`"로 설계했는데, 46건 실측 결과 range_position은
  EARLY_TREND(0.83~0.96대 다수)와 PROGRESSED(0.82~0.97대) 분포가 크게
  겹쳐 분리력이 없었고, weekly_ma12_slope는 오히려 **PROGRESSED가 더
  낮았다**(모멘텀이 이미 성숙해서 단기 기울기가 둔화됨 — 042660
  2025-07-31 weekly=-0.004, 012450 2022-12-31 weekly=-0.015 등). 반대로
  weekly가 강하게 양전환 중인 건 EARLY_TREND(신선한 돌파)의 특징이었다
  (086790 2024-02-29 weekly=+0.121, 005380 2020-08-31 weekly=+0.195 등).
  그래서 최종 PROGRESSED 판정은 `core_turning_positive AND
  expansion_present`만 본다 — weekly/range_position은 evidence 필드로는
  남기되(진단용) 이 판정에는 안 쓴다.

## Precedence

blended `stage_score`와 cutoff 대신, 정해진 순서로 조건을 else-if로
검사해 가장 먼저 맞는 stage를 채택한다.

1. `insufficient_data` -> `stage=None`.
2. `active_decline` -> WEAK.
3. `core_turning_positive and expansion_present` -> PROGRESSED.
4. `breakout_like_structure` -> EARLY_TREND.
5. `core_turning_positive or weekly_turning_positive` -> TRANSITION.
6. 그 외 전부 BASE(fallback).

`active_decline`은 3-branch OR다(단일 신호 아님): `ma24_slope<=-0.045`
또는 (`ma24_slope_acceleration<0` and `avg_price_change_12m<=-0.15`) 또는
(`weekly_ma12_slope<=0` and `range_position<=0.20`).

## Episode / Cycle reset logic

`StageLifecycleContext`는 `snapshot.monthly`(현재 시점 제외, 과거 구간만)
로 계산한다.

* `prior_expansion_detected`: snapshot 이전에 strict historical expansion
  proxy(`ma24_slope > 0 AND avg_price_change_12m >= 0.30`)가 한 번이라도
  감지되었는가.
* `episode_broken_after_expansion`: 마지막 historical expansion 시점
  이후~현재 이전 구간에 `ma24_slope <= -0.045` 또는 `range_position <= 0.20`
  (장기 추세 붕괴)이 한 번이라도 발생했는가.
* `last_expansion_month`: 마지막 확장이 감지된 월.
* `months_since_expansion`: 마지막 확장 이후 경과 개월 수.
* `previously_expanded_in_current_episode`:
  `prior_expansion_detected AND NOT episode_broken_after_expansion`. 즉,
  과거에 확장이 있었고 그 확장이 아직 붕괴되지 않아 **현재 episode에
  속하는 확장**으로 볼 수 있는 상태인가를 나타낸다.

**Historical expansion proxy와 direct PROGRESSED의 차이**:
direct PROGRESSED 판정의 `expansion_present`는 `avg_price_change_12m >= 0.30`
또는 `ma_spread >= 0.20`(OR)이지만, historical lifecycle 탐색에서는
더 엄격한 **strict historical expansion proxy**(`ma24_slope > 0 AND
avg_price_change_12m >= 0.30`, AND)를 사용한다. 이유: historical 탐색에서
`range_position` 경로는 실측으로 false positive가 확인되었고(EARLY_TREND
구간도 걸려서 직전 달이 항상 마지막 확장으로 잡힘), `ma_spread` historical
경로는 v0.1에서 채택하지 않았으며 향후 trajectory 기반 검증 후보로 남겨두었다.
향후 Stage v0.2에서 필요시 historical `ma_spread` 궤적 등을 추가해 두 정의를
재통합할 수 있지만, v0.1에서는 이 엄격한 프록시를 유지한다.

재구성에 쓰는 series는 새 Feature가 아니라 기존 point formula
(`build_feature_row`/`_avg_price_change_12m`/`resistance.range_position`)의
vectorized 버전이다: `ma24_series=moving_average(close,24)`,
`ma24_slope_series=ma_slope_series(ma24_series, periods=3)`,
`range_position_series=(close-low_36m_rolling)/(high_36m_rolling-low_36m_rolling)`,
`avg_price_change_12m_series=(close.rolling(12).mean() - close.rolling(12).mean().shift(12)) / close.rolling(12).mean().shift(12)`.

처음에는 "확장이 있었다"의 기준을 `range_position>=0.60 or
avg_price_change_12m>=0.30`(OR)로 잡았는데, `range_position` 단독으로도
매달 걸리는 바람에(EARLY_TREND 구간도 range_position은 이미 높다)
`months_since_expansion`이 사실상 항상 1로 나왔다 — "직전 달"이 무조건
"마지막 확장"으로 잡히는 문제였다. 그래서 최종 기준은 strict historical
expansion proxy인 `ma24_slope>0 AND avg_price_change_12m>=0.30`(AND, 훨씬
엄격함)으로 좁혔다.

## `StageLifecycleContext`를 최종 stage 판정에 아직 쓰지 않는 이유

**이 부분이 이번 라운드의 가장 중요한 honest failure 기록이다.**

"이미 이 episode 안에서 확장했었고 아직 안 꺾였으면
(`previously_expanded_in_current_episode=True`) PROGRESSED로 유지한다"는
override를 넣어 46건에 실측 검증했다. 이 override는 LIG넥스원(079550)
2023-12-31 같은 사례(지금 이 순간의 evidence는 `breakout_like_structure`까지만
도달하지만, 실제로는 PROGRESSED가 맞는 lifecycle continuation)를 잡아주기
위해 설계했다.

실측 결과:

| 구성 | exact match | SEVERE mismatch |
|---|---|---|
| override 적용 | 37/46 (80.4%) | 4건 |
| override 미적용(최종) | 38/46 (82.6%) | 3건 |

override를 넣으면 079550 2023-12-31과 POSCO(005490) 2023-07-31은
정확히 맞지만, 대신 086790/010620/042660 같은 종목들 — "과거 어느
시점엔가 진짜 확장이 있었지만 이미 오래전에 새 국면으로 넘어간" 경우를
잘못 PROGRESSED로 밀어올리는 부작용이 더 컸다. `episode_broken_after_expansion`
판정(가파른 하락이나 낮은 range_position)이 "장기 횡보로 국면이 자연스럽게
끝난" 경우를 못 잡기 때문이다.

079550 하나(또는 005490 하나)를 맞추기 위해 override를 유지하면 다른
종목에서 더 많은 오분류가 생긴다 — "특정 종목 하나를 맞추기 위해 global
rule을 비틀지 않는다"는 원칙에 따라, **v0.1은 이 override 없이
출시한다.** `StageLifecycleContext` 계산 자체(episode/cycle reset 판정)는
`classify_pattern_a_stage()`가 항상 수행해서 `StageClassificationResult.
context`로 반환하고, WEAK 판정의 `episode_broken_cycle_reset` reason_code
(`prior_expansion_detected AND episode_broken_after_expansion AND active_decline`)
에는 실제로 쓰인다 — 구조는 v0.1에 존재하고, v0.2가 이 데이터를 이어받아
recency 조건(예: 확장 이후 몇 개월까지만 "같은 episode"로 볼지) 등을
추가할 수 있다.

## Calibration truth set validation 결과

`scripts/pattern_a_stage_validate.py` 실행 결과(46건, `data/processed/
pattern_a_stage_v01_validation.csv`).

* n = 46 (calibration truth set)
* EXACT match: 38건 (82.6%)
* ADJACENT mismatch: 5건 (10.9%)
* SEVERE mismatch: 3건 (6.5%)
* NODATA/NO_CACHE: 0건

Stage별 support / exact:

| audited_stage | support | exact | exact_rate |
|---|---|---|---|
| weak | 5 | 5 | 100% |
| base | 10 | 7 | 70% |
| transition | 10 | 7 | 70% |
| early_trend | 8 | 8 | 100% |
| progressed | 13 | 11 | 85% |

**Calibration vs OOS 성격 명시**: 82.6%(38/46)는 Stage Classifier v0.1
설계에 사용된 46건 **calibration truth set exact match rate**(reproduction
rate)이며, external OOS accuracy가 아니다. 외부 OOS 검증은 다음 별도
마일스톤에서 진행한다.

**match 판정 caveat**: `docs/validation/pattern_a_stage.md`가 명시하듯
WEAK는 완전히 서열적이지 않다(다른 stage와 별개 축의 "실패" 상태에
가깝다). 그래도 ADJACENT/SEVERE 판정을 위해 하나의 순서
(`WEAK=0, BASE=1, TRANSITION=2, EARLY_TREND=3, PROGRESSED=4`)를 정해서
썼다 — WEAK<->BASE 거리만 1(ADJACENT)로 잡히고, WEAK<->TRANSITION 이상은
그대로 SEVERE로 잡힌다. 이 순서는 편의상 정의이지 WEAK가 실제로 BASE보다
"한 단계 낮다"는 의미는 아니다.

## Confusion matrix

row = audited_stage, col = predicted_stage:

| audited \ predicted | weak | base | transition | early_trend | progressed |
|---|---|---|---|---|---|
| weak | 5 | 0 | 0 | 0 | 0 |
| base | 1 | 7 | 2 | 0 | 0 |
| transition | 1 | 0 | 7 | 0 | 2 |
| early_trend | 0 | 0 | 0 | 8 | 0 |
| progressed | 0 | 0 | 0 | 2 | 11 |

## Major error type audit

지정된 6가지 오류 유형(audited_stage -> predicted_stage 방향)을
`scripts/pattern_a_stage_validate.py`가 46건 실제 결과에 대조한다. 이
6개는 사전에 정의된 유형이지 사후에 관찰해서 만든 분류가 아니다 — 그래서
6개 중 실제로 발생한 것도 있고, 전혀 발생하지 않은 것도 있다.

* **A. BASE -> TRANSITION 과다**: 2건 — 000880 2024-12-31, 010620
  2023-12-31. 둘 다 `core_or_weekly_turning_positive`(약한 양전환
  신호)에 규칙이 민감하게 반응한 경우다.
* **B. EARLY_TREND -> TRANSITION**: 0건.
* **C. PROGRESSED -> EARLY_TREND**: 2건 — 079550 2023-12-31, 005490
  2023-07-31. 위 "`StageLifecycleContext`를 최종 판정에 아직 쓰지 않는
  이유" 절에서 설명한, v0.1이 의도적으로 감수한 실패다.
* **D. WEAK -> BASE**: 0건.
* **E. WEAK -> EARLY_TREND**: 0건.
* **F. 새 episode인데 과거 expansion 때문에 PROGRESSED 유지**: 0건 —
  **의도된 0건이다.** 바로 이 실패 유형을 막기 위해 episode continuation
  override를 v0.1에서 채택하지 않기로 결정했다(위 절 참고). override를
  넣었다면 이 유형이 실제로 발생했을 것이다(086790/010620/042660류가
  여기 해당했을 사례).

A-F 6개 유형에 안 들어가는 나머지 mismatch 4건도 투명성을 위해 별도로
기록한다: 042700 2019-12-31(BASE->WEAK, active_decline threshold 경계),
012450 2021-12-31(TRANSITION->PROGRESSED, `avg_chg=+0.723`), 010130
2022-06-30(TRANSITION->PROGRESSED, `avg_chg=+0.312`), 005490 2022-12-31
(TRANSITION->WEAK, active_decline 발동). 012450/010130 둘 다
`avg_price_change_12m`이 PROGRESSED threshold(0.30)를 넘는데도 사람은
TRANSITION으로 판정했다 — 급등성 12개월 변화율과 진짜 "이미 진행된
확장"을 `avg_price_change_12m` 단독으로 구분하지 못하는 게 원인으로
보인다(예: 변동성 큰 회복 구간 vs 꾸준한 상승).

## Challenge cases

Challenge case는 **2건의 external adjacent boundary challenge snapshot**과
**1건의 in-sample thin WEAK audit case**로 구성된다.

### 1. 2 External Adjacent Boundary Challenge Snapshots (010620 / 042660)

truth set 46건에는 없는 별도 (ticker, snapshot_date)다. 같은 종목의
앞뒤 snapshot이 이미 development set에 존재하므로, 이 관찰은 독립된
통계적 external evidence가 아니라 **temporal interpolation / adjacent
boundary sanity check**다. 공식 `audited_stage`가 없어 match_type을
계산하지 않고 예측값이 인접 시점 사이에서 자연스러운지 관찰한다.

| ticker | name | snapshot_date | predicted_stage | 관찰 (Adjacent Boundary Sanity Check) |
|---|---|---|---|---|
| 010620 | HD현대미포 | 2024-06-30 | transition | manifest 2023-12-31(BASE)~2024-12-31(PROGRESSED) 중간 지점. TRANSITION은 이 둘 사이 자연스러운 경유 단계로 보임. |
| 042660 | 한화오션 | 2025-01-31 | early_trend | manifest 2024-10-31(TRANSITION)~2025-07-31(PROGRESSED) 중간 지점. EARLY_TREND도 자연스러운 경유 단계로 보임. |

두 사례 모두 truth set 경계 사이에서 직관적으로 말이 되는 중간 상태를
예측했다 — 다만 앞뒤 시점 데이터가 이미 calibration 맥락에 포함되어
있으므로 이를 일반화 성능의 증거로 확대 해석하지 않는다.

### 2. 1 In-Sample Thin WEAK Audit Case (011200 HMM 2024-10-31)

이건 truth set 46건에 이미 포함된 WEAK 행(WEAK support=5 중 1건)이다.
새 snapshot이 아니라 "thin WEAK 사례"로서 과적합 여부를 별도로 들여다보는
audit case다. 결과는 EXACT match (predicted WEAK). `active_decline`의
3-branch OR 중 어느 것이 발동했는지 확인한 결과:

* branch1(`ma24_slope<=-0.045`): `ma24_slope=-0.0161` -> 불발.
* branch2(`ma24_slope_acceleration<0 and avg_price_change_12m<=-0.15`):
  `acceleration=+0.0388`(양수) -> 불발.
* branch3(`weekly_ma12_slope<=0 and range_position<=0.20`):
  `weekly=-0.0102<=0`(참), `range_position=0.1457<=0.20`(참) -> **발동**.

3개 branch 중 1개만 발동했고, 그 branch 안에서는 두 조건이 서로 다른
Feature(weekly slope, range_position)에서 독립적으로 근거를 대므로
단일 숫자 하나가 threshold를 겨우 넘겨서 우연히 맞은 경우는 아니다.
다만 branch1/branch2가 전혀 근접하지 않았다는 점(다른 WEAK 진성
사례들처럼 여러 branch가 동시에 발동하지 않음)은, 이 사례가 WEAK
스펙트럼에서 상대적으로 "얇은" 쪽에 있다는 우려와 일치한다 —
과적합으로 단정할 수는 없지만, WEAK support가 5건뿐이라는 sample
크기 문제와 함께 v0.2에서 계속 지켜볼 대상으로 남긴다.

## Known failure modes (v0.2로 넘기는 것)

1. **Episode continuation override 부재**: 위에서 설명한 대로, "같은
   episode 안에서 확장이 계속되는데 이번 달 evidence만 약한" 경우를
   구분 못 한다(079550/005490 2건). recency 조건이나 더 정교한
   episode_broken 판정(장기 횡보도 "종료"로 인식)이 필요하다.
2. **`avg_price_change_12m` 단독 급등과 진짜 progression의 구분 실패**:
   012450/010130 2건. 변동성이 큰 회복성 반등과 꾸준한 확장을
   `avg_price_change_12m` 하나로는 못 가른다 — ma_spread 궤적(계속
   벌어지는 중인지 이미 좁아지는 중인지) 같은 추가 신호가 필요해 보인다.
3. **약한 신호에 대한 BASE의 민감도**: 000880/010620 2건. `core_or_
   weekly_turning_positive`만으로 TRANSITION을 주는 게 너무 느슨할 수
   있다 — 신호 강도(threshold를 얼마나 넘었는지)를 보는 게 필요할 수
   있다.
4. **`active_decline`의 과다 반응 가능성**: 005490 1건. weekly_ma12_slope가
   순간적으로 낮아지는 노이즈에 반응하는지, smoothing이나 지속 기간
   조건이 필요한지 확인이 필요하다.

## Score와의 관계 (이번 커밋에서 하지 않은 것)

* `pattern_a_score.py`의 Score 공식/curve/gate/alignment/progressed
  penalty는 전혀 수정하지 않았다.
* `pattern_a_score.py`의 기존 provisional stage heuristic(`_classify_stage`,
  Score 파생값 기반)도 삭제하지 않았다 — 이 새 classifier와 별개로
  존재한다.
* 이 classifier를 `score_pattern_a()`에 아직 연결하지 않았다.

## Stage manifest / 다른 파일 변경 확인

* `pattern_a_stage_manifest.py`의 `audited_stage` 라벨은 전혀 수정하지
  않았다 — classifier 결과에 맞춰 truth set을 조정하지 않았다.
* 이번 커밋에서 새로 만든/수정한 파일: `src/trend_scanner/patterns/
  pattern_a_stage.py`, `tests/test_pattern_a_stage.py`,
  `scripts/pattern_a_stage_validate.py`,
  `docs/validation/pattern_a_stage_classifier_v01.md`(이 문서).

## Final judgement

**Pattern A Stage Classifier v0.1 — Accepted as calibrated v0.1 baseline.**

* **Calibration truth set**: 46 snapshots
* **Exact reproduction**: 38 / 46 (82.6%)
* **External Stage OOS Validation**: **Not yet performed (NEXT)**
* **Known failure modes**: Documented (4 categories)
* **Next Step**: Stage Classifier v0.1 OOS Validation Selection Freeze

Score와 독립적이고, 8개 evidence + episode/cycle reset context 전부를
사람이 reason_codes로 그대로 따라 읽을 수 있는 rule-based classifier를
구현했다. 46건 calibration truth set에서 exact match 82.6%(38/46), SEVERE
mismatch 3건(6.5%)이며, 2건의 adjacent boundary challenge snapshot에서도
직관적인 중간 예측을 냈다. 알려진 실패 모드 4가지(episode continuation,
avg_price_change_12m 단독 급등, BASE 민감도, active_decline 과다 반응)를
전부 문서화했고, 46/46을 맞추기 위해 truth set이나 global rule을 비틀지
않았다(079550 사례가 대표적 — 맞추는 override를 실제로 만들어 검증까지
했지만, 전체 정확도가 떨어져서 최종적으로 폐기했다).

이로써 Phase 3의 Stage Classifier v0.1 calibration baseline이 고정되었으며,
다음 작업으로 **Stage Classifier v0.1 OOS Validation**을 진행한다.
