# Pattern A Stage Label Audit Freeze

## 목적

`PatternAStage`(base/transition/early_trend/progressed/weak)는 지금까지
Score 계산 결과에서 파생된 provisional 값이었고, 자동 분류 threshold는
구현된 적이 없다(`pattern_a_feature_set.py`의 `PatternAStage` docstring:
"자동 분류 threshold는 미구현"). OOS2 Validation의 Manual Stage Audit에서
이 provisional 값이 신뢰할 수 없다는 게 드러났다(`pattern_a_oos2.md` —
pre_breakout 1/5, early_trend 3/5 agreement).

이번 Phase의 목표는 Stage를 Score와 독립된, 가격 구조 기반 classifier로
재설계하는 것이다. 이 문서는 그 첫 단계(Commit A)로 manual ground-truth
label 46건을 freeze했고(commit 3ceac21), 이 문서는 그 재리뷰 후속으로
(1) BASE/WEAK 경계 재감사, (2) Stage semantic 확정(current-state vs
lifecycle), (3) manifest provenance 검증 강화를 다룬다. **classifier
구현(threshold/rule)은 이번 commit에도 포함하지 않는다.**

## Score와 Stage의 관계

* Score: 이 Pattern A 후보가 얼마나 매력적인가.
* Stage: 이 종목이 가격 구조 생애주기의 어느 지점에 있는가.

두 질문은 독립적이어야 한다. 의존 방향은 단방향이다 — Score가 (나중에)
Stage classifier를 호출하는 것은 허용되지만, Stage classifier가
`score_pattern_a()`/`base_score`/`transition_score`/`balanced_core_score`/
`alignment_bonus`/`confirmation_bonus`/`progressed_penalty`를 참조하는 것은
금지한다. 이 manifest의 `audited_stage`/`stage_reason`도 예외 없이 이
원칙을 따른다 — 전부 raw Feature 값만 근거로 판정했다.

## Stage semantic: current-state가 아니라 lifecycle로 확정

이번 재리뷰에서 가장 중요한 설계 질문을 확정한다. Stage는 다음 둘 중
하나여야 한다.

* A. 현재 snapshot Feature만으로 표현되는 순간 상태
* B. Pattern A 가격 구조의 lifecycle 상태

**B(lifecycle)로 확정한다.** Stage는 BASE → TRANSITION → EARLY_TREND →
PROGRESSED로 이어지는 진행 과정을 표현하고, 한 번 큰 breakout과
expansion을 거쳐 PROGRESSED에 들어간 종목이 잠시 횡보하거나 조정을
받았다는 이유만으로 다시 EARLY_TREND로 쉽게 되돌아가지 않는다.

**근거(079550 LIG넥스원 2023-12-31 사례)**: 이 snapshot 자체의 Feature만
보면(`avg_price_change_12m=+0.029`, `ma_spread=0.072`, `range_position
=0.861`) EARLY_TREND와 구분이 어렵다. 하지만 이 종목은 snapshot 이전
(2021-12-31: `avg_price_change_12m=+0.585`/`ma_spread=0.216`)에 이미 큰
폭의 breakout+expansion을 통과했다. current-state로 정의했다면 이
snapshot은 재라벨링(EARLY_TREND 또는 별도 stage)이 필요했을 것이고,
lifecycle로 정의하면 과거 경로를 근거로 PROGRESSED를 유지할 수 있다.
이번 라운드에서 lifecycle로 명시적으로 확정해 이 모순을 남기지 않는다.
079550(2023-12-31)은 PROGRESSED로 유지한다(manifest `stage_reason`에도
이 근거를 명시).

### historical path 사용 정책 (lookahead 아님)

lifecycle 판단을 위해 snapshot 이전의 같은 종목 과거 이력(예: 과거에
breakout/expansion을 거쳤는지)을 참조하는 것은 **lookahead가 아니다**.
lookahead는 `snapshot_date` **이후**의 정보를 쓰는 것이고, lifecycle
path 참조는 `snapshot_date` **이전**의 정보를 쓰는 것이다 — 방향이
반대다.

예를 들어 snapshot_date가 2023-12-31이면 2021~2023-12-31까지의 가격
이력은 전부 사용 가능하고, 2024년 이후 데이터는 여전히 금지다. 이
manifest는 `build_historical_snapshot(..., include_incomplete_periods=
False)`가 보장하는 `daily.index <= snapshot_date` 범위 안에서만 과거
경로를 참조했다(079550 사례에서 실제로 참조한 2021-12-31 snapshot도
2023-12-31보다 이전이다).

## BASE/WEAK 경계 재감사

기존 raw feature 값(Commit A와 동일한 계산 경로로 재확인, 재계산 없음)을
9건에서 직접 비교한다.

| ticker | name | snapshot_date | range_36m | range_position | range_position_52w | distance_to_resistance | ma24_slope | ma24_slope_acceleration | weekly_ma12_slope | avg_price_change_12m | ma_spread | 최종 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 011210 | 현대위아 | 2019-12-31 | 0.9645 | 0.4205 | 0.6420 | 0.3717 | -0.0370 | +0.0178 | +0.0101 | +0.0121 | 0.0500 | BASE |
| 032830 | 삼성생명 | 2021-02-28 | 1.1767 | 0.4795 | 0.7774 | 0.3852 | -0.0207 | +0.0260 | +0.0071 | -0.2037 | 0.1433 | BASE |
| 015760 | 한국전력 | 2023-12-31 | 0.5624 | 0.2408 | 0.4018 | 0.3238 | -0.0219 | +0.0122 | +0.0186 | -0.1322 | 0.0952 | BASE(재분류) |
| 023530 | 롯데쇼핑 | 2023-12-31 | 0.7554 | 0.1429 | 0.3730 | 0.4444 | -0.0250 | +0.0230 | +0.0205 | -0.1603 | 0.1597 | BASE(재분류, 경계) |
| 011170 | 롯데케미칼 | 2023-01-31 | 1.0287 | 0.3182 | 0.5599 | 0.4508 | -0.0475 | -0.0207 | +0.0744 | -0.2761 | 0.2626 | WEAK(재분류) |
| 009150 | 삼성전기 | 2022-12-31 | 0.9217 | 0.3454 | 0.2818 | 0.4148 | -0.0187 | -0.0164 | +0.0318 | -0.2003 | 0.2502 | WEAK(재분류) |
| 034220 | LG디스플레이 | 2020-09-30 | 1.3294 | 0.2616 | 0.7350 | 0.5445 | -0.0491 | +0.0257 | +0.1065 | -0.2361 | 0.1859 | WEAK |
| 018260 | 삼성에스디에스 | 2023-07-31 | 0.7754 | 0.1313 | 0.4217 | 0.4410 | -0.0507 | +0.0077 | +0.0104 | -0.1640 | 0.1006 | WEAK |
| 011200 | HMM | 2024-10-31 | 1.1664 | 0.1457 | 0.2851 | 0.5453 | -0.0161 | +0.0388 | -0.0102 | -0.0693 | 0.0385 | WEAK |

### 재감사 전 문제

재감사 전 라벨(011210/032830/011170/009150=BASE, 015760/023530/034220/
018260/011200=WEAK)을 `range_position` 순으로 정렬하면 0.131~0.262는
전부 WEAK, 0.318~0.480은 전부 BASE — **사실상 `range_position<=0.25`
cutoff와 동일했다**. 이번 재감사가 확인하려는 게 바로 이 문제였다.

### 재감사 기준(4-gate, label 설명용 — production threshold 아님)

`range_position` 자체는 게이트에서 뺐다. 다음 중 하나라도 해당하면
WEAK, 넷 다 해당 없으면 BASE로 재분류했다.

1. `ma24_slope`가 뚜렷하게 가파른 하락(대략 -0.045 이하) — 장기 하락이
   아직 강한 속도로 진행 중인가(질문 A).
2. `ma24_slope_acceleration`이 음수 — 하락이 오히려 가속 중인가(질문 B의
   반대).
3. `weekly_ma12_slope`가 0 이하 — 단기 방향조차 아직 전환되지 않았는가
   (질문 E).
4. `ma_spread`가 비교 대상 중 가장 넓은 축(비수렴) — 월봉 구조가 아직
   베이스 형태로 안정되지 않았는가(질문 D).

**결과**: 4개 게이트를 전부 통과(넷 다 해당 없음)하면 BASE — 011210,
032830, 015760, 023530. 게이트 중 하나 이상 걸리면 WEAK — 011170(게이트
1+2), 009150(게이트 2), 034220(게이트 1), 018260(게이트 1), 011200(게이트
3). 9건 전체에 동일한 규칙을 기계적으로 적용한 결과이고, 케이스별로
다른 근거를 즉흥적으로 대는 방식은 쓰지 않았다.

### 011170 vs 034220 직접 비교(핵심 질문)

`ma24_slope`가 거의 동일한 쌍(011170=-0.0475, 034220=-0.0491)이 실제로
BASE/WEAK 게이트 기준으로도 같은 결론(둘 다 게이트 1에 걸림 → WEAK)에
도달하는지가 재감사의 핵심 질문이었다. **결론은 "034220을 BASE로
올린다"가 아니라 "011170을 WEAK로 내린다"였다** — 재감사 전 011170이
BASE였던 건 `range_position=0.318`이 0.25보다 높다는 이유뿐이었고,
가파름/가속/수렴 기준으로 보면 011170은 9건 중 `avg_price_change_12m`
(-27.6%, 최댓값), `ma_spread`(0.263, 최댓값), 유일하게 음수인
`ma24_slope_acceleration`(-0.021, 하락 가속)까지 갖춰 오히려 9건 중
가장 강한 WEAK 근거를 가진 사례였다.

### 재분류 결과

* 011170, 009150: BASE → WEAK
* 015760, 023530: WEAK → BASE
* 011210, 032830, 034220, 018260, 011200: 라벨 변경 없음(재확인)

4건이 서로 반대 방향으로 바뀌어 **BASE/WEAK 전체 건수는 10/5로
동일하다**(멤버십만 교체) — `docs/validation/pattern_a_stage.md`의
"결과 요약" 표와 `pattern_a_stage_manifest.py`의 소스별 건수는 변경
없음.

## Stage 정의(BASE/WEAK 재정의 반영)

Feature 3축(item 8):

* **Base Context**: `range_36m`, `avg_price_change_12m`, `ma_spread`
* **Trend Transition**: `ma24_slope`, `ma24_slope_acceleration`,
  `weekly_ma12_slope`
* **Price Progression**: `range_position`, `range_position_52w`,
  `distance_to_resistance`

### BASE (최종 정의)

장기 하락이 안정되거나 멈춘 상태 — 단순히 "저점에서 조금 올라왔다"가
아니라 **장기 하락 자체가 안정되고 가격 구조가 베이스 형태로 바뀌었다**
는 뜻이다. 판별은 하락의 속도/방향/수렴 여부로 한다: `ma24_slope`가
가파르지 않고(대략 -0.045보다 완만), `ma24_slope_acceleration`이
음수가 아니며(가속 중이 아님), `weekly_ma12_slope`가 0보다 크고(단기
방향 전환 확인), `ma_spread`가 비교군 대비 넓지 않다(이동평균 수렴).
절대적인 `range_position` 수준은 필요조건이 아니다 — 위 조건을 만족하면
`range_position`이 낮아도(예: 023530=0.143) BASE일 수 있다.

### WEAK (최종 정의)

Pattern A 구조가 성립하지 않는 상태. 위 BASE 조건 중 하나라도 실패하면
WEAK다 — 하락이 여전히 가파르거나, 가속 중이거나, 단기 방향이 아직
안 돌았거나, 이동평균이 수렴하지 않은 경우. 이번 46건의 WEAK 5건 중
034220/018260은 가파름 게이트, 011200은 단기 방향 게이트, 011170은
가파름+가속 게이트, 009150은 가속 게이트에 걸렸다 — 자세한 내용은
아래 "WEAK subtype 제한사항" 참고.

### TRANSITION

`ma24_slope` 또는 `weekly_ma12_slope` 중 하나가 막 전환 조짐을 보이는
상태 — 대표적으로 weekly가 먼저 양전환했는데 ma24가 아직 안 돌았거나
(price leads, trend lags), 반대로 ma24는 막 돌았는데 weekly가 아직
확인되지 않은 경우.

### EARLY_TREND

`ma24_slope`와 `weekly_ma12_slope`가 둘 다 뚜렷한 양수로 전환했고,
`range_position`이 높아지고 `distance_to_resistance`가 좁혀지는 상태 —
아직 `avg_price_change_12m`/`ma_spread`(추세 확장 폭)는 크지 않다.

### PROGRESSED (lifecycle 반영)

추세가 상당히 진행된 상태 — 보통 `avg_price_change_12m`이 크고(대체로
+0.3 이상), `ma_spread`가 벌어져 있고, `range_position`이 매우 높다
(대체로 0.8 이상). 다만 위 Stage semantic 절에서 확정했듯, **한 번
breakout+expansion을 통과한 종목이 일시적으로 조정받아 이 수치들이
낮아진 snapshot도 lifecycle 경로(과거 breakout/expansion 이력)를
근거로 PROGRESSED를 유지할 수 있다**(079550 2023-12-31 사례).

## Source Dataset (4개)

manifest는 이미 로컬 캐시에 있는 4개 기존 dataset에서 snapshot을
재사용한다 — 이번 라운드를 위한 신규 KRX fetch는 없다. Stage 라벨링은
Score 성능 검증(OOS2)과는 다른 작업이므로, development snapshot
(HOLDOUT_SNAPSHOTS)을 Stage 라벨 목적으로 재사용해도 OOS2 성능 검증을
오염시키지 않는다.

1. **OOS2_v0.2_manifest** (`oos_v02_manifest.py`, 22건) — positive_pre_breakout/
   positive_early_trend/positive_trend_progressed/downtrend_reversal_boundary
   4개 case_group에서 20건, 추가로 hard_negative_false_turn 1건과
   weak_core_strong_support 1건을 가져왔다.
2. **OOS_v0.1_stage_audit** (`oos_v01_manifest.py`의 `OOS_V01_STAGE_AUDIT`,
   13건) — 기존 15건 중 애매한 경계 표기("/") 2건은 제외했다(아래 참고).
3. **negative_control_compare** (`score_v02_candidate_compare.py`의
   `NEGATIVE_CONTROL_SNAPSHOTS`, 8건) — 기존 `label`(failed_breakout 등)은
   전부 outcome 기반이라 Stage 판정 근거로 쓰지 않았다.
4. **holdout_early_trend_compare** (`score_v02_candidate_compare.py`의
   `HOLDOUT_SNAPSHOTS` 중 label이 `early_trend`인 5건 중 3건) —
   EARLY_TREND 표본 보강용.

## audited_stage 판단 기준

전부 `build_historical_snapshot(..., include_incomplete_periods=False)`로
계산한 실제 `FeatureRow` 값만 보고 판정했다(스크립트로 pull,
`score_pattern_a()`는 호출하지 않음). 판정 근거는 각 manifest row의
`stage_reason`에 snapshot 시점까지의 Feature 값(lifecycle 판단 시
snapshot 이전의 동일 종목 과거 값 포함)만 근거로 기록했다 — 미래
시점 정보는 쓰지 않는다.

## as of snapshot 준수 방식

실제 lookahead 방지 보장은 `build_historical_snapshot`의
`daily.index <= snapshot_date` 슬라이싱 경로에서 나온다(여러 라운드에
걸쳐 테스트로 검증됨) — 이 manifest도 그 함수를 그대로 재사용해서
별도 구현 없이 as-of 원칙을 상속한다. `stage_reason`에 "이후" 같은
표현이 없다는 문자열 검사(`tests/test_pattern_a_stage_manifest.py`)는
표현 스타일 회귀를 잡는 보조 장치일 뿐이고, 그 자체가 lookahead
방지를 증명하지는 않는다 — 실제 보장은 위 함수 경로에 있다.

## boundary/추가 사례 처리 방식

* **BASE/WEAK 경계**: 위 "BASE/WEAK 경계 재감사" 절 참고 — 011170/
  009150(BASE→WEAK), 015760/023530(WEAK→BASE) 4건 재분류.
* **105560(2024-02-29) vs 086790(2024-02-29) 경계**: 둘 다
  `positive_early_trend` snapshot이지만 105560은 `ma24_slope=0.0000`
  으로 core가 전혀 안 돌았고(weekly만 강한 양전환) TRANSITION으로,
  086790은 `ma24_slope=+0.012`로 core가 이미 돌고 `distance_to_resistance
  =0.057`로 저항선에 근접해 EARLY_TREND로 판정했다. `notes`에 경계
  사례로 명시.
* **negative_control 8건**: 기존 `label`(failed_breakout 등)은 outcome
  기반이므로 Stage 판정에 쓰지 않고 raw Feature로 독립 재분류했다.
* **079550(2023-12-31)**: Stage semantic을 lifecycle로 확정한 근거
  사례. 위 "Stage semantic" 절 참고.

## missing/ambiguous 사례 처리 방식

`OOS_V01_STAGE_AUDIT`의 2건 — 010620(2024-06-30, `"PRE_BREAKOUT/EARLY_TREND
경계"`), 042660(2025-01-31, `"EARLY_TREND/TREND_PROGRESSED 경계"`) —는
이번 truth set에도 포함하지 않는다. 원 audit 자체가 "판단이 어려운
사례로 남긴다"고 명시했고 5개 `PatternAStage` 값 중 하나로 깔끔히 안
맞는다. Classifier v0.1 구현 이후 이 2건은 정답 라벨이 아니라 **adjacent
boundary challenge set**(경계 근처에서 classifier가 얼마나 일관되게
행동하는지 보는 별도 평가용)으로 재사용할 수 있다 — 현재 truth set에는
포함하지 않는다.

## WEAK subtype 제한사항

WEAK 정의에는 두 가지 하위 유형이 있다.

* (a) 활성 하락 — 위 BASE 게이트 중 하나 이상이 명확히 실패하는 경우.
* (b) 어느 Stage로도 신뢰성 있게 분류되지 않는 residual 케이스.

이번 46건의 WEAK 5건은 전부 (a) 유형이다. 다만 (a) 안에서도 강도 차이가
있다는 점을 명시한다: 018260/011170은 여러 게이트가 동시에 걸리는
뚜렷한 활성 하락이고, 015760/023530은 재감사로 BASE로 넘어갔으며,
009150/011200은 게이트 하나만 걸리면서 다른 축(예: 011200의 강한 감속/
좁은 ma_spread, 009150의 완만한 slope)에서는 부분적 안정화 신호가
공존하는 상대적으로 얇은 근거의 WEAK다. **(b) residual 유형은 이번
46건에 하나도 없다** — Commit B에서 classifier를 만들 때 residual
WEAK까지 이 truth set이 검증했다고 착각하면 안 된다. residual WEAK에
대한 validation evidence는 아직 없다.

## Commit B Stage Classifier API 설계 방향(문서화만, 미구현)

Stage를 lifecycle로 정의했으므로, Commit B classifier는 `FeatureRow`
하나만 받는 `classify_pattern_a_stage(features)` 같은 signature로
충분하다고 가정하지 않는다 — 079550 사례처럼 단일 snapshot Feature만
으로는 lifecycle 위치(특히 PROGRESSED 유지 여부)를 판단할 수 없는
경우가 있기 때문이다. 권장 방향은 `HistoricalSnapshot`(또는 Stage
전용 historical evidence 묶음)을 받을 수 있는 구조다. 이번 라운드에서는
실제 signature나 함수를 구현하지 않는다 — Commit B 설계 시 참고용
방향만 남긴다.

## Stage 전용 historical evidence 후보(미구현, 문서화만)

Commit B 설계를 위해 후보만 정리한다. **이것들은 Pattern A Score
Feature가 아니다** — Stage classifier 전용 lifecycle evidence 후보이고,
Score(`pattern_a_score.py`)에는 절대 연결하지 않는다.

* 최근 N개월 내 장기 resistance 돌파 이력
* 최근 N개월 최대 `range_position`
* 과거 `ma_spread` 확장 여부
* 과거 `avg_price_change_12m` 최대값
* 확장 이후 경과 개월 수
* 최근 장기 고점 이후 pullback 정도
* 과거 `ma24_slope` peak
* breakout 이후 가격 유지 여부

## manifest 검증 테스트(이번 라운드에서 추가)

기존 테스트(중복 키/날짜 파싱/enum 유효성/source_dataset 기록/Stage별
최소 건수/Score import 없음)에 다음을 추가했다.

* **provenance test**: 각 `StageLabelSpec`의 (ticker, snapshot_date,
  source_dataset) 조합이 실제로 해당 원본 dataset에 존재하는지
  assert한다 — `OOS2_v0.2_manifest`→`OOS_V02_VALIDATION_SNAPSHOTS`,
  `OOS_v0.1_stage_audit`→`OOS_V01_STAGE_AUDIT`, `negative_control_compare`
  →`NEGATIVE_CONTROL_SNAPSHOTS`, `holdout_early_trend_compare`→
  `HOLDOUT_SNAPSHOTS`(label이 `early_trend`인 항목만). source_dataset
  문자열 오타나 잘못된 provenance 연결을 코드로 잡는다.
* **Feature reconstruction test**(KRX 캐시 있는 환경에서만 실행,
  skipif): 46건 전부 `build_historical_snapshot(ticker, name, daily,
  snapshot_date, include_incomplete_periods=False)`가 예외 없이
  생성되는지 확인한다. try/except로 감추지 않고 예외가 나면 테스트가
  그대로 실패한다(OOS2 라운드와 동일 원칙) — manifest에 존재하지 않는
  snapshot, 잘못된 날짜, cache와 안 맞는 ticker/date를 조기에 잡는
  목적이다.

## 결과 요약

| Stage | 건수 |
|---|---|
| BASE | 10 |
| TRANSITION | 10 |
| EARLY_TREND | 8 |
| PROGRESSED | 13 |
| WEAK | 5 |
| **합계** | **46** |

건수 자체는 Commit A와 동일하다 — 이번 재리뷰는 46건 구성이 아니라
BASE/WEAK 4건의 멤버십과 판정 기준을 바꿨다.

## 이번 라운드에서 하지 않은 것

* Stage classifier(threshold/rule) 구현, `pattern_a_stage.py` 신규
  파일 — 하지 않았다.
* `pattern_a_score.py` 및 Base curve/Transition/confirmation/alignment/
  progressed penalty 수정 — 하지 않았다.
* v0.3 evidence(core=0 collapse / strong core persistence / Base negative
  clamp) 수정 — 하지 않았다.
* `OOS_V02_VALIDATION_SNAPSHOTS`/`OOS_V01_STAGE_AUDIT`/
  `NEGATIVE_CONTROL_SNAPSHOTS`/`HOLDOUT_SNAPSHOTS` 자체 수정 — 이번
  manifest는 이 dataset들에서 값을 "읽기만" 했다.
* 이번 재감사에서 쓴 -0.045/게이트 숫자를 production classifier
  threshold로 확정 — 하지 않았다. label 설명용이고, Commit B threshold는
  별도로 설계한다.
