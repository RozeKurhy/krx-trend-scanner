# Pattern A Stage Label Audit Freeze

## 목적

`PatternAStage`(base/transition/early_trend/progressed/weak)는 지금까지
Score 계산 결과에서 파생된 provisional 값이었고, 자동 분류 threshold는
구현된 적이 없다(`pattern_a_feature_set.py`의 `PatternAStage` docstring:
"자동 분류 threshold는 미구현"). OOS2 Validation의 Manual Stage Audit에서
이 provisional 값이 신뢰할 수 없다는 게 드러났다(`pattern_a_oos2.md` —
pre_breakout 1/5, early_trend 3/5 agreement).

이번 Phase의 목표는 Stage를 Score와 독립된, 가격 구조 기반 classifier로
재설계하는 것이다. 이 문서는 그 첫 단계(Commit A)로, classifier가 맞춰야
할 manual ground-truth label 46건을 freeze한다. **classifier 구현(threshold/
rule)은 이번 commit에 포함하지 않는다.**

## Score와 Stage의 관계

* Score: 이 Pattern A 후보가 얼마나 매력적인가.
* Stage: 이 종목이 가격 구조 생애주기의 어느 지점에 있는가.

두 질문은 독립적이어야 한다. 의존 방향은 단방향이다 — Score가 (나중에)
Stage classifier를 호출하는 것은 허용되지만, Stage classifier가
`score_pattern_a()`/`base_score`/`transition_score`/`balanced_core_score`/
`alignment_bonus`/`confirmation_bonus`/`progressed_penalty`를 참조하는 것은
금지한다. 이 manifest의 `audited_stage`/`stage_reason`도 예외 없이 이
원칙을 따른다 — 전부 raw Feature 값만 근거로 판정했다.

## Stage 정의

Feature 3축(item 8):

* **Base Context**: `range_36m`, `avg_price_change_12m`, `ma_spread`
* **Trend Transition**: `ma24_slope`, `ma24_slope_acceleration`,
  `weekly_ma12_slope`
* **Price Progression**: `range_position`, `range_position_52w`,
  `distance_to_resistance`

Stage 판정에서는 Score보다 Price Progression 축의 비중을 더 크게 본다
(price가 구조적으로 어디 있는지가 생애주기 판단에 더 직접적인 증거이기
때문).

### BASE

장기 박스권 안에 머무는 상태. `range_position`이 중간대(대략
0.3~0.6)이고, `ma24_slope`가 평탄하거나 약한 음수이며, `weekly_ma12_slope`도
아직 뚜렷한 전환 신호가 없다. 아직 core(`ma24_slope`)가 돌지 않았다.

### TRANSITION

`ma24_slope` 또는 `weekly_ma12_slope` 중 하나가 막 전환 조짐을 보이는
상태 — 대표적으로 weekly가 먼저 양전환했는데 ma24가 아직 안 돌았거나
(price leads, trend lags), 반대로 ma24는 막 돌았는데 weekly가 아직
확인되지 않은 경우. `range_position`은 BASE보다 높을 수도, 비슷할 수도
있다 — 핵심 판별은 두 slope 축의 불일치/막 전환 여부다.

### EARLY_TREND

`ma24_slope`와 `weekly_ma12_slope`가 둘 다 뚜렷한 양수로 전환했고,
`range_position`이 높아지고 `distance_to_resistance`가 좁혀지는 상태 —
아직 `avg_price_change_12m`/`ma_spread`(추세 확장 폭)는 크지 않다. "막
돌파를 시도/확인하는" 단계.

### PROGRESSED

추세가 상당히 진행된 상태 — `avg_price_change_12m`이 크고(대체로
+0.3 이상), `ma_spread`가 벌어져 있고, `range_position`이 매우 높다(대체로
0.8 이상). Core 확인은 이미 끝났고 확장 국면에 있다.

### WEAK

Pattern A 구조가 성립하지 않는 상태. 여기에는 두 가지 하위 유형이
섞여 있다:

* (a) 활성 하락 추세 — `range_position`이 매우 낮고(대략 0.25 이하,
  다년 저점권) `ma24_slope`가 뚜렷한 음수. 아직 안정된 박스조차
  형성되지 않았다.
* (b) 어느 Stage로도 신뢰성 있게 분류되지 않는 잔여 케이스.

item 24 지침에 따라 이번 라운드에서는 별도 BOUNDARY stage를 만들지
않고 경계 사례는 WEAK로 흡수한다. 이번 46건 중 WEAK로 분류된 5건은
전부 (a) 유형이고 (b) 유형은 없다 — Stage classifier v0.1이 구현된
뒤 (a)/(b) 분리가 필요해지면 그건 별도 판단(v0.2-Stage 논의)으로
남긴다.

## Source Dataset (4개)

manifest는 이미 로컬 캐시에 있는 4개 기존 dataset에서 snapshot을
재사용한다 — 이번 라운드를 위한 신규 KRX fetch는 없다. Stage 라벨링은
Score 성능 검증(OOS2)과는 다른 작업이므로, development snapshot
(HOLDOUT_SNAPSHOTS)을 Stage 라벨 목적으로 재사용해도 OOS2 성능 검증을
오염시키지 않는다.

1. **OOS2_v0.2_manifest** (`oos_v02_manifest.py`, 22건) — positive_pre_breakout/
   positive_early_trend/positive_trend_progressed/downtrend_reversal_boundary
   4개 case_group에서 20건, 추가로 hard_negative_false_turn 1건과
   weak_core_strong_support 1건을 WEAK 라벨 보강용으로 가져왔다(아래
   "boundary/추가 사례 처리" 참고).
2. **OOS_v0.1_stage_audit** (`oos_v01_manifest.py`의 `OOS_V01_STAGE_AUDIT`,
   13건) — 기존 15건 중 애매한 경계 표기("/") 2건은 제외했다(아래 참고).
3. **negative_control_compare** (`score_v02_candidate_compare.py`의
   `NEGATIVE_CONTROL_SNAPSHOTS`, 8건) — 기존 `label`(failed_breakout 등)은
   전부 outcome 기반이라 Stage 판정 근거로 쓰지 않았다(아래 참고).
4. **holdout_early_trend_compare** (`score_v02_candidate_compare.py`의
   `HOLDOUT_SNAPSHOTS` 중 label이 `early_trend`인 5건 중 3건, EARLY_TREND
   보강용) — EARLY_TREND 표본이 원래 5건으로 너무 얇아서 추가로
   가져왔다.

## audited_stage 판단 기준

전부 `build_historical_snapshot(..., include_incomplete_periods=False)`로
계산한 실제 `FeatureRow` 값만 보고 판정했다(스크립트로 pull, `score_pattern_a()`는
호출하지 않음). 판정 근거는 각 manifest row의 `stage_reason`에 snapshot
시점 Feature 값으로만 기록했다 — "이후" 같은 forward-looking 표현은
`stage_reason`에 쓰지 않는다(그런 정보는 원 dataset의 `selection_reason`/
`audit_note`에 이미 있고, 그건 `notes`에 provenance로만 인용한다).

## as of snapshot 준수 방식

`build_historical_snapshot`은 `daily.index <= snapshot_date`만 사용하도록
이미 여러 라운드에 걸쳐 테스트로 검증된 함수다(look-ahead 없음). 이
manifest도 그 함수를 그대로 재사용했으므로 별도 구현 없이 as-of 원칙을
상속한다. row를 만들 때 Feature pull에 사용한 스크립트는 `score_pattern_a()`를
전혀 import하지 않는다.

## boundary/추가 사례 처리 방식

* **WEAK 재정의로 인한 재분류**: 초기 분석에서 011210/011170을
  `range_position`이 낮다는 이유로 WEAK 후보로 봤으나, 재검토 결과
  0.32~0.42로 WEAK 기준(0.25 이하)에 못 미치고 오히려 기존 BASE
  사례(009150 0.345, 032830 0.480)와 프로필이 같아 BASE로 재분류했다.
  대신 `range_position`이 실제로 0.25 이하이고 `ma24_slope`가 뚜렷한
  음수인 진짜 WEAK 사례 2건(023530 2023-12-31, 034220 2020-09-30)을
  OOS2 데이터에서 추가로 가져왔다.
* **105560(2024-02-29) vs 086790(2024-02-29) 경계**: 둘 다 `positive_early_trend`
  snapshot이지만 105560은 `ma24_slope=0.0000`으로 core가 전혀 안
  돌았고(weekly만 강한 양전환, price leads/trend lags) TRANSITION으로,
  086790은 `ma24_slope=+0.012`로 core가 이미 돌았고 `distance_to_resistance
  =0.057`로 저항선에 근접해 EARLY_TREND로 판정했다. 두 stage 사이 실제
  경계 사례라서 `notes`에 명시했다 — classifier의 adjacent-error 평가 시
  참고.
* **034220(2020-09-30)의 weekly 이상치**: WEAK로 분류했지만
  `weekly_ma12_slope=+0.1065`로 다른 WEAK 사례보다 훨씬 높다. `range_position
  =0.2616`(저점권)과 `ma24_slope=-0.0491`(뚜렷한 하락)이 주 판별 축이라
  WEAK로 판정했지만, weekly 축만 보면 TRANSITION 신호로도 읽힐 수 있어
  `notes`에 이 divergence를 남겼다.
* **negative_control 8건**: 기존 `label`(failed_breakout/failed_higher_low/
  failed_momentum/failed_ma24_turn/failed_weekly_turn)은 outcome 기반이므로
  Stage 판정에 쓰지 않고, 각 row의 실제 Feature 값만 보고 독립적으로
  재분류했다. 그 결과 `label`이 "failed_*"라고 해서 자동으로 WEAK가 되지
  않았다(예: 003550/010130/034730은 실제로는 BASE→TRANSITION 진입
  구조가 확인돼 TRANSITION으로 분류).
* **079550(2023-12-31)**: 원 OOS v0.1 audit이 `TREND_PROGRESSED`로 판정한
  근거(avg_price_change_12m=+0.029로 낮지만 ma_spread=0.072 유지 —
  "선행 종목이 잠시 쉬어가는" 맥락 판단)를 존중해 PROGRESSED를 유지했다.
  Feature 값만으로는 EARLY_TREND와도 경계에 있어 `notes`에 남겼다.

## missing/ambiguous 사례 처리 방식

`OOS_V01_STAGE_AUDIT`의 2건 — 010620(2024-06-30, `"PRE_BREAKOUT/EARLY_TREND
경계"`), 042660(2025-01-31, `"EARLY_TREND/TREND_PROGRESSED 경계"`) —는
원 audit 자체가 "판단이 어려운 사례로 남긴다"고 명시했고, 현재 5개
`PatternAStage` 값 중 하나로 깔끔하게 매핑되지 않아 이번 manifest에서
제외했다. 필요하면 classifier v0.1 구현 이후 별도 경계 사례로 재검토한다.

## 결과 요약

| Stage | 건수 |
|---|---|
| BASE | 10 |
| TRANSITION | 10 |
| EARLY_TREND | 8 |
| PROGRESSED | 13 |
| WEAK | 5 |
| **합계** | **46** |

전 category가 최소 5건 기준을 충족한다(EARLY_TREND/WEAK가 8/5로 가장
얇다).

## 이번 라운드에서 하지 않은 것

* Stage classifier(threshold/rule) 구현 — Commit B에서 진행.
* `pattern_a_score.py` 수정 — 하지 않았다.
* v0.3 evidence(core=0 collapse / strong core persistence / Base negative
  clamp) 수정 — 하지 않았다. Stage classifier가 이 문제들을 우연히
  가려준다고 해도 Score 문제가 해결된 것으로 간주하지 않는다.
* `OOS_V02_VALIDATION_SNAPSHOTS`/`OOS_V01_STAGE_AUDIT`/`NEGATIVE_CONTROL_SNAPSHOTS`/
  `HOLDOUT_SNAPSHOTS` 자체 수정 — 이번 manifest는 이 dataset들에서 값을
  "읽기만" 했고 원본은 건드리지 않았다.
