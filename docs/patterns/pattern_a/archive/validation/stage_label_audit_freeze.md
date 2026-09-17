# Pattern A Stage Label Audit Freeze

## 목적

`PatternAStage`(base/transition/early_trend/progressed/weak)는 지금까지
Score 계산 결과에서 파생된 provisional 값이었고, 자동 분류 threshold는
구현된 적이 없다(`pattern_a_feature_set.py`의 `PatternAStage` docstring:
"자동 분류 threshold는 미구현"). OOS2 Validation의 Manual Stage Audit에서
이 provisional 값이 신뢰할 수 없다는 게 드러났다(`pattern_a_oos2.md` —
pre_breakout 1/5, early_trend 3/5 agreement).

이번 Phase의 목표는 Stage를 Score와 독립된, 가격 구조 기반 classifier로
재설계하는 것이다. manual ground-truth label 46건은 Commit A(3ceac21)에서
freeze했고, 첫 재리뷰 후속(3752f40)에서 BASE/WEAK 4건을 재분류하고
Stage semantic을 lifecycle로 확정했다. 이 문서는 그 두 번째 재리뷰
후속으로 (1) BASE/WEAK 재감사에 쓴 4-gate가 global rule처럼 읽히는
문제를 diagnostic checklist 수준으로 명확히 낮추고, (2) lifecycle
Stage에 "현재 Pattern A episode"와 "cycle reset" 개념을 추가한다.
**classifier 구현(threshold/rule)은 이번 commit에도 포함하지 않는다.**

핵심 두 문장(이번 라운드에서 고정하는 것):

1. BASE/WEAK는 몇 개 숫자 gate의 결과가 아니라 가격 구조 lifecycle의
   질적 상태다.
2. Stage는 종목 전체 역사의 영구 라벨이 아니라 현재 Pattern A episode의
   lifecycle 위치다.

## Score와 Stage의 관계

* Score: 이 Pattern A 후보가 얼마나 매력적인가.
* Stage: 이 종목이 가격 구조 생애주기의 어느 지점에 있는가.

두 질문은 독립적이어야 한다. 의존 방향은 단방향이다 — Score가 (나중에)
Stage classifier를 호출하는 것은 허용되지만, Stage classifier가
`score_pattern_a()`/`base_score`/`transition_score`/`balanced_core_score`/
`alignment_bonus`/`confirmation_bonus`/`progressed_penalty`를 참조하는 것은
금지한다. 이 manifest의 `audited_stage`/`stage_reason`도 예외 없이 이
원칙을 따른다 — 전부 raw Feature 값만 근거로 판정했다.

## Stage semantic: current Pattern A episode의 lifecycle

Stage는 다음 둘 중 하나다.

* A. 현재 snapshot Feature만으로 표현되는 순간 상태
* B. Pattern A 가격 구조의 lifecycle 상태

**B(lifecycle)로 확정한다.** 다만 이번 라운드에서 B의 의미를 한 단계
더 명확히 한다: **Stage는 종목 전체 역사에서 단 한 번만 존재하는
lifecycle이 아니라, 현재 Pattern A episode의 lifecycle 위치다.**

### Pattern A episode 개념

한 종목은 역사에서 Pattern A 구조를 여러 번 반복할 수 있다. 하나의
episode는 개념적으로

```
WEAK/BASE -> TRANSITION -> EARLY_TREND -> PROGRESSED
```

로 진행한다. 이 진행 안에서는 PROGRESSED가 일시적으로 조정받아도
EARLY_TREND로 단순 회귀하지 않는다(079550 사례, 아래 참고). 하지만
장기 추세가 완전히 붕괴하고 기존 상승 구조(breakout/base)가 소멸한
뒤 새로운 장기 안정화 구조가 만들어지면, **기존 episode는 종료된다**
— 그 뒤에 만들어지는 새 BASE 후보는 이전 episode의 연장이 아니라
새로운 Pattern A episode의 시작이다.

### cycle reset

```
PROGRESSED -> (장기 구조 붕괴) -> 이전 episode 종료
           -> (새로운 하락 안정화) -> 새 episode의 BASE 후보
```

구분해야 할 두 가지:

* **금지**: `PROGRESSED -> EARLY_TREND`로 같은 episode 안에서 단순
  회귀하는 것 (한 번 확장한 종목이 잠깐 쉬어간다고 EARLY_TREND로
  되돌아가지 않는다).
* **허용**: `기존 episode 종료 -> 새 episode BASE`로, episode 자체가
  끝나고 완전히 새로 시작하는 것.

**counter-example**: 2020년에 큰 상승으로 PROGRESSED에 도달한 종목이
2021~2023년에 장기 추세가 완전히 붕괴해 기존 base/breakout 구조가
소멸하고, 2024~2026년에 완전히 새로운 장기 안정화와 신규 base가
형성됐다고 하자. 이때 2026년 snapshot을 "2020년에 상승했었다"는
이유만으로 PROGRESSED로 유지하면 안 된다 — 이전 episode는 종료됐고,
2026년은 새로운 Pattern A episode의 BASE 또는 TRANSITION으로 다시
시작할 수 있다.

**이번 라운드에서 만들지 않는 것**: 몇 % 하락하면 reset인지, 몇 개월이
지나야 reset인지, `ma24_slope`가 얼마면 episode가 종료되는지 같은
수치 threshold는 이번에 만들지 않는다. 이번에는 semantic(개념)만
고정하고, 실제 episode 종료/reset 감지 rule은 Commit B 설계에서 별도로
만든다.

### historical path 사용 정책 (lookahead 아님)

lifecycle 판단을 위해 snapshot 이전의 같은 종목 과거 이력(예: 현재
episode 안에서 이미 breakout/expansion을 거쳤는지)을 참조하는 것은
**lookahead가 아니다**. lookahead는 `snapshot_date` **이후**의 정보를
쓰는 것이고, lifecycle path 참조는 `snapshot_date` **이전**의 정보를
쓰는 것이다 — 방향이 반대다. 이 manifest는
`build_historical_snapshot(..., include_incomplete_periods=False)`가
보장하는 `daily.index <= snapshot_date` 범위 안에서만 과거 경로를
참조했다.

### 079550 LIG넥스원 2023-12-31: episode 종료 사례가 아님

이 snapshot 자체의 Feature만 보면(`avg_price_change_12m=+0.029`,
`ma_spread=0.072`, `range_position=0.861`) EARLY_TREND와 구분이
어렵다. 하지만 이 종목은 2021-12-31(`avg_price_change_12m=+0.585`/
`ma_spread=0.216`)에 큰 폭의 breakout+expansion을 통과했고, 그 사이
장기 추세 붕괴나 기존 구조 소멸이 관찰되지 않는다 — 즉 **같은 episode
안에서의 일시 조정(consolidation)**이지 episode 종료가 아니다. 따라서
PROGRESSED를 유지한다. 이 사례는 "current state만 보면 EARLY와
비슷하지만 episode 이력을 보면 PROGRESSED"라는 lifecycle 근거 사례로
계속 사용한다 — episode 종료/cycle reset 개념을 추가해도 이 판단은
바뀌지 않는다.

## BASE/WEAK 재감사

### 재감사에 사용한 diagnostic checklist (global rule 아님)

첫 재리뷰(3752f40)에서 다음 4가지를 9건에 동일하게 적용해 재검토했다.

1. `ma24_slope`가 뚜렷하게 가파른 하락(대략 -0.045 이하)
2. `ma24_slope_acceleration`이 음수(하락이 가속 중)
3. `weekly_ma12_slope`가 0 이하(단기 방향 미전환)
4. `ma_spread`가 비교 대상 중 가장 넓은 축(비수렴)

이 4가지는 **9건 비교를 위한 diagnostic checklist**였다. 명확히
다음 수준으로 지위를 낮춘다.

* production classifier rule이 아니다.
* global Stage definition이 아니다.
* Stage truth를 생성하는 공식이 아니다.
* Commit B threshold가 아니다.

기존 range_position 편향(재감사 전 라벨이 사실상 `range_position<=0.25`
cutoff와 동일했던 문제)을 드러내기 위해 같은 분석 축을 9건에 일괄
적용한 heuristic checklist일 뿐이고, 이 결과 자체로 BASE/WEAK를
정의하지 않는다. 아래 "BASE 최종 정의"/"WEAK 최종 정의"는 이 checklist
결과를 참고하되 별도로 질적으로 다시 확정한다.

### 9건 비교표 (유지)

| ticker | name | snapshot_date | range_36m | range_position | range_position_52w | distance_to_resistance | ma24_slope | ma24_slope_acceleration | weekly_ma12_slope | avg_price_change_12m | ma_spread | 최종 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 011210 | 현대위아 | 2019-12-31 | 0.9645 | 0.4205 | 0.6420 | 0.3717 | -0.0370 | +0.0178 | +0.0101 | +0.0121 | 0.0500 | BASE |
| 032830 | 삼성생명 | 2021-02-28 | 1.1767 | 0.4795 | 0.7774 | 0.3852 | -0.0207 | +0.0260 | +0.0071 | -0.2037 | 0.1433 | BASE |
| 015760 | 한국전력 | 2023-12-31 | 0.5624 | 0.2408 | 0.4018 | 0.3238 | -0.0219 | +0.0122 | +0.0186 | -0.1322 | 0.0952 | BASE |
| 023530 | 롯데쇼핑 | 2023-12-31 | 0.7554 | 0.1429 | 0.3730 | 0.4444 | -0.0250 | +0.0230 | +0.0205 | -0.1603 | 0.1597 | BASE(경계) |
| 011170 | 롯데케미칼 | 2023-01-31 | 1.0287 | 0.3182 | 0.5599 | 0.4508 | -0.0475 | -0.0207 | +0.0744 | -0.2761 | 0.2626 | WEAK |
| 009150 | 삼성전기 | 2022-12-31 | 0.9217 | 0.3454 | 0.2818 | 0.4148 | -0.0187 | -0.0164 | +0.0318 | -0.2003 | 0.2502 | WEAK |
| 034220 | LG디스플레이 | 2020-09-30 | 1.3294 | 0.2616 | 0.7350 | 0.5445 | -0.0491 | +0.0257 | +0.1065 | -0.2361 | 0.1859 | WEAK |
| 018260 | 삼성에스디에스 | 2023-07-31 | 0.7754 | 0.1313 | 0.4217 | 0.4410 | -0.0507 | +0.0077 | +0.0104 | -0.1640 | 0.1006 | WEAK |
| 011200 | HMM | 2024-10-31 | 1.1664 | 0.1457 | 0.2851 | 0.5453 | -0.0161 | +0.0388 | -0.0102 | -0.0693 | 0.0385 | WEAK |

### 4건 재확인: checklist가 아니라 질적 lifecycle 판단으로

이번 라운드에서 011170/009150/015760/023530을 checklist 통과 여부가
아니라 다음 질문으로 다시 판단했다.

* A. snapshot 당시 활성 장기 하락이 여전히 구조를 지배하는가?
* B. 월봉 가격 구조가 안정화되기 시작했는가?
* C. 하락 속도와 이동평균 구조가 base 형성 쪽으로 수렴하고 있는가?
* D. 주봉 반등이 단순 일시 반등인지, 장기 구조 안정화의 일부인지?
* E. 현재 Pattern A episode에서 BASE라고 부르는 것이 자연스러운가?

**011170 롯데케미칼(WEAK 유지)**: avg_price_change_12m=-27.6%(9건 중
최대 낙폭), ma_spread=0.263(9건 중 최대, 이동평균 가장 발산),
ma24_slope_acceleration=-0.021(9건 중 유일하게 하락 가속) — 세 개의
독립적인 신호가 함께 활성 하락이 여전히 구조를 지배함을 가리킨다.
weekly_ma12_slope=+0.074(D)의 반등은 있지만, 낙폭/발산/가속이 전부
악화 방향이라 이 반등은 장기 구조 안정화의 일부가 아니라 하락 중
일시 반등으로 판단했다. A=예, B=아니오, C=아니오, E=부자연스러움 →
WEAK.

**009150 삼성전기(WEAK 유지, acceleration 단일 신호 아님)**: 재검토
결과 acceleration(-0.016) 하나가 아니라 세 신호가 함께 근거가 된다 —
(1) ma_spread=0.250(9건 중 2번째로 넓음, 미수렴), (2)
range_position_52w=0.282가 range_position(0.345)보다 낮아(9건 중
유일한 역전) 최근 1년이 3년 구간 대비 오히려 개선되지 않았고, (3)
avg_price_change_12m=-20.0%로 낙폭 자체도 여전히 크다. ma24_slope
자체는 완만(-0.019)하지만, 이동평균 미수렴+52주 역전+큰 낙폭이 함께
나타나 A=예, B=아니오, C=애매(slope는 완만하나 구조는 미수렴) → WEAK로
판단.

**015760 한국전력(BASE 유지)**: ma_spread=0.095로 9건 중 좁은 편(수렴
진행), ma24_slope_acceleration=+0.012로 계속 감속, weekly_ma12_slope
=+0.019로 단기 방향도 양전환 — 세 신호가 함께 활성 하락이 더 이상
지배적이지 않고 베이스 형성 쪽으로 수렴 중임을 가리킨다.
range_position(0.241)이 낮은 건 절대 가격 수준일 뿐, 낮은 가격대에서도
베이스는 형성될 수 있다고 판단했다. A=아니오(더 이상 지배적이지
않음), B=예, C=예, D=구조적 안정화의 일부로 봄, E=자연스러움 → BASE.

**023530 롯데쇼핑(BASE 유지, 가장 얇은 근거)**: ma24_slope=-0.025(가파른
하락 아님), ma24_slope_acceleration=+0.023(감속), weekly_ma12_slope
=+0.021(양전환)은 BASE 쪽 신호이지만, range_position=0.143(9건 중
최저)과 ma_spread=0.160(완전히 좁혀지지 않음)이 걸린다. 이번 BASE
10건 중 근거가 가장 얇은 경계 사례라는 점을 명시하고, 그럼에도
활성 하락이 구조를 지배한다고 보기보다는 낮은 위치에서 새로운 베이스를
만들어가는 초기 단계(B=예, 다만 초기 단계)로 판단해 BASE를 유지한다.

**결론**: checklist 결과와 이번 질적 재검토의 결론이 4건 모두
일치했다(011170/009150=WEAK, 015760/023530=BASE) — 다만 이번 재검토는
checklist 통과/실패를 근거로 쓰지 않고, 매번 여러 구조 신호를 함께
검토해 독립적으로 확인했다. 라벨 자체는 변경 없음.

### 011170 vs 034220 직접 비교

`ma24_slope`가 거의 동일한 쌍(011170=-0.0475, 034220=-0.0491)이 같은
결론(WEAK)에 도달하는지가 핵심 질문이었다. **결론은 "034220을 BASE로
올린다"가 아니라 "011170을 WEAK로 내린다"였다** — 재감사 전 011170이
BASE였던 건 `range_position=0.318`이 상대적으로 높다는 이유뿐이었고,
낙폭/발산/가속을 함께 보면 011170은 9건 중 가장 강한 WEAK 근거를 가진
사례였다.

## Stage 정의(BASE/WEAK 재정의 반영)

Feature 3축(item 8):

* **Base Context**: `range_36m`, `avg_price_change_12m`, `ma_spread`
* **Trend Transition**: `ma24_slope`, `ma24_slope_acceleration`,
  `weekly_ma12_slope`
* **Price Progression**: `range_position`, `range_position_52w`,
  `distance_to_resistance`

### BASE (최종 정의, 질적)

**현재 Pattern A episode에서, 활성 하락이 더 이상 가격 구조를
지배하지 않고, 장기 가격 구조가 안정화되기 시작해서 베이스 후보로 볼
수 있는 상태.**

명시적으로 다음은 BASE의 필수조건이 아니다.

* `weekly_ma12_slope > 0`은 필수조건이 아니다.
* `ma24_slope`가 특정 cutoff보다 높아야 하는 것도 아니다.
* `range_position`이 특정 cutoff 이상이어야 하는 것도 아니다.

BASE는 하나의 숫자 조건이 아니라, 하락 속도/방향/이동평균 수렴/과거
episode 맥락 등 여러 구조 증거를 종합해서 판단하는 lifecycle 상태다.
위 diagnostic checklist(4가지)는 그 증거 중 일부를 빠르게 훑어보는
도구일 뿐이다.

### WEAK (최종 정의, 질적)

**현재 Pattern A episode의 베이스가 아직 충분히 형성되지 않았거나,
활성 하락 구조가 여전히 지배적인 상태.**

"diagnostic checklist 4가지 중 하나라도 실패하면 자동 WEAK"라는 규칙은
쓰지 않는다 — 아래 "기존 BASE와의 정의 충돌 정리"가 그 이유를 보여준다.

### 기존 BASE와의 정의 충돌 정리

manifest에는 이미 다음과 같은 BASE 사례가 있다.

* 042700 한미반도체 2019-12-31: `ma24_slope`≈-0.057(가파름 기준보다
  더 가파름)
* 105560 KB금융 2023-12-31: `weekly_ma12_slope`≈-0.022(음수)
* 086790 하나금융지주 2023-12-31: `weekly_ma12_slope`≈-0.003(음수)
* 000880 한화 2024-12-31: `weekly_ma12_slope`≈-0.023(음수)

이 4건이 diagnostic checklist를 통과하지 못하는데도 BASE인 이유는,
이 4건이 011210/032830/015760/023530과 **다른 하위 상황**이기
때문이다.

* **하위 상황 1(042700/105560/086790/000880)**: 애초에 최근 활성
  하락이 존재하지 않는, 오랫동안 조용히 박스권을 유지해온 종목. 이
  경우 하락의 가속/감속이나 weekly 전환 여부는 판단 대상이 아니다 —
  질문 A("활성 장기 하락이 구조를 지배하는가")에 대한 답 자체가
  "애초에 지배할 활성 하락이 없다"이기 때문에 BASE다.
* **하위 상황 2(011210/032830/015760/023530, 그리고 WEAK로 남은
  011170/009150/034220/018260/011200)**: 비교적 최근까지 뚜렷한
  하락이 있었고, "그 하락이 끝나고 베이스로 전환됐는가"가 실제
  판단 대상인 경계 사례. diagnostic checklist는 바로 이 하위 상황을
  비교하기 위해 만들어졌다.

즉 diagnostic checklist는 하위 상황 2에만 적용되는 참고 도구이고,
하위 상황 1에는 애초에 적용 대상이 아니다 — 그래서 checklist를
global BASE definition으로 쓰면 042700류 사례와 충돌한다. 이번
라운드에서 BASE 최종 정의를 질적 문장으로 되돌린 이유가 바로 이
충돌을 없애기 위해서다.

### TRANSITION

`ma24_slope` 또는 `weekly_ma12_slope` 중 하나가 막 전환 조짐을 보이는
상태 — 대표적으로 weekly가 먼저 양전환했는데 ma24가 아직 안 돌았거나
(price leads, trend lags), 반대로 ma24는 막 돌았는데 weekly가 아직
확인되지 않은 경우.

### EARLY_TREND

`ma24_slope`와 `weekly_ma12_slope`가 둘 다 뚜렷한 양수로 전환했고,
`range_position`이 높아지고 `distance_to_resistance`가 좁혀지는 상태 —
아직 `avg_price_change_12m`/`ma_spread`(추세 확장 폭)는 크지 않다.

### PROGRESSED (episode/cycle reset 반영)

추세가 상당히 진행된 상태 — 보통 `avg_price_change_12m`이 크고(대체로
+0.3 이상), `ma_spread`가 벌어져 있고, `range_position`이 매우 높다
(대체로 0.8 이상). 같은 episode 안에서 일시적으로 조정받아 이 수치들이
낮아진 snapshot도 episode 이력(과거 breakout/expansion)을 근거로
PROGRESSED를 유지할 수 있다(079550 사례). 다만 **영구 상태는 아니다**
— 장기 구조가 완전히 붕괴해 기존 episode가 종료되면, 그 이후 snapshot은
과거 PROGRESSED 이력과 무관하게 새 episode의 BASE/TRANSITION으로
판단한다(위 "cycle reset" 절 참고).

## Source Dataset (4개)

manifest는 이미 로컬 캐시에 있는 4개 기존 dataset에서 snapshot을
재사용한다 — 이번 라운드를 위한 신규 KRX fetch는 없다.

1. **OOS2_v0.2_manifest** (`oos_v02_manifest.py`, 22건)
2. **OOS_v0.1_stage_audit** (`oos_v01_manifest.py`의 `OOS_V01_STAGE_AUDIT`,
   13건) — 기존 15건 중 애매한 경계 표기("/") 2건 제외
3. **negative_control_compare** (`score_v02_candidate_compare.py`의
   `NEGATIVE_CONTROL_SNAPSHOTS`, 8건) — outcome 기반 `label`은 Stage
   판정에 미사용
4. **holdout_early_trend_compare** (`score_v02_candidate_compare.py`의
   `HOLDOUT_SNAPSHOTS` 중 label=`early_trend` 3건)

## audited_stage 판단 기준

전부 `build_historical_snapshot(..., include_incomplete_periods=False)`로
계산한 실제 `FeatureRow` 값만 보고 판정했다(`score_pattern_a()`는
호출하지 않음). `stage_reason`은 snapshot 시점까지의 Feature 값(episode
lifecycle 판단 시 snapshot 이전의 동일 종목 과거 값 포함)만 근거로
기록했다.

## as of snapshot 준수 방식

실제 lookahead 방지 보장은 `build_historical_snapshot`의
`daily.index <= snapshot_date` 슬라이싱 경로에서 나온다 — 이 manifest도
그 함수를 재사용해 별도 구현 없이 상속한다. `stage_reason`에 "이후"
표현이 없다는 문자열 검사는 표현 스타일 회귀를 잡는 보조 장치일 뿐,
그 자체가 lookahead 방지를 증명하지는 않는다.

## missing/ambiguous 사례 처리 방식

`OOS_V01_STAGE_AUDIT`의 2건(010620 2024-06-30, 042660 2025-01-31)은
이번 truth set에도 포함하지 않는다. Classifier v0.1 이후 **adjacent
boundary challenge set**으로 재사용할 수 있다.

## WEAK subtype 제한사항

WEAK에는 두 하위 유형이 있다: (a) 활성 하락(베이스가 아직 형성되지
않았거나 하락이 여전히 지배적), (b) 어느 Stage로도 신뢰성 있게
분류되지 않는 residual 케이스. 이번 46건의 WEAK 5건(011170/009150/
034220/018260/011200)은 전부 (a) 유형이다. **(b) residual 유형은
이번 46건에 하나도 없다** — Commit B에서 residual WEAK까지 이 truth
set이 검증했다고 착각하면 안 된다.

## Commit B Stage Classifier API 설계 방향(문서화만, 미구현)

Stage를 lifecycle로 정의했으므로, Commit B classifier는 `FeatureRow`
하나만 받는 `classify_pattern_a_stage(features)` 같은 signature로
충분하다고 가정하지 않는다. 권장 방향은 `HistoricalSnapshot` 또는
`StageEvidence`/`StageLifecycleContext` 같은, episode 이력을 담을 수
있는 historical context를 받는 구조다. 이번 라운드에서는 실제
signature나 함수를 구현하지 않는다.

## Stage 전용 historical evidence 후보(미구현, 문서화만)

**이것들은 Pattern A Score Feature가 아니다** — Stage classifier 전용
lifecycle evidence 후보이고, Score(`pattern_a_score.py`)에는 절대
연결하지 않는다.

* 최근 N개월 내 장기 resistance 돌파 이력
* 최근 N개월 최대 `range_position`
* 과거 `ma_spread` 확장 여부
* 과거 `avg_price_change_12m` 최대값
* 확장 이후 경과 개월 수
* 최근 장기 고점 이후 pullback 정도
* 과거 `ma24_slope` peak
* breakout 이후 가격 유지 여부

**이번 라운드에서 추가하는 원칙**: 가능하면 종목 전체 역사의 무제한
최댓값이 아니라 **현재 Pattern A episode와 관련된** historical path를
본다. 오래된 이전 cycle의 expansion(예: 이미 종료된 과거 episode의
PROGRESSED 이력)이 현재 Stage를 영구적으로 PROGRESSED에 고정하면
안 된다 — 위 "cycle reset" 개념과 직접 연결된다. episode 경계를 어떻게
감지할지(threshold)는 Commit B에서 설계한다.

## manifest 검증 테스트

기존 테스트(중복 키/날짜 파싱/enum 유효성/source_dataset 기록/Stage별
최소 건수/Score import 없음/provenance/Feature reconstruction, 총 10건)를
그대로 유지한다 — 이번 semantic 수정으로 제거하거나 약화한 테스트는
없다.

* **provenance test**: 각 `StageLabelSpec`의 (ticker, snapshot_date,
  source_dataset) 조합이 실제 원본 dataset에 존재하는지 assert.
* **Feature reconstruction test**(KRX 캐시 있는 환경에서만 skipif):
  46건 전부 `build_historical_snapshot`이 예외 없이 생성되는지 확인
  (try/except로 감추지 않음).

## 결과 요약

| Stage | 건수 |
|---|---|
| BASE | 10 |
| TRANSITION | 10 |
| EARLY_TREND | 8 |
| PROGRESSED | 13 |
| WEAK | 5 |
| **합계** | **46** |

이번 라운드에서 manifest 라벨은 변경하지 않았다 — 4건(011170/009150/
015760/023530)을 checklist가 아니라 질적 lifecycle 판단으로 재확인한
결과 첫 재리뷰(3752f40)의 결론과 동일했다.

## 이번 라운드에서 하지 않은 것

* Stage classifier(threshold/rule) 구현, `pattern_a_stage.py` 신규
  파일 — 하지 않았다.
* cycle reset threshold(몇 % 하락/몇 개월/`ma24_slope` 몇 이하) 구현 —
  하지 않았다. semantic만 고정했다.
* `pattern_a_score.py` 및 Base curve/Transition/confirmation/alignment/
  progressed penalty 수정 — 하지 않았다.
* v0.3 evidence(core=0 collapse / strong core persistence / Base negative
  clamp) 수정 — 하지 않았다.
* `OOS_V02_VALIDATION_SNAPSHOTS`/`OOS_V01_STAGE_AUDIT`/
  `NEGATIVE_CONTROL_SNAPSHOTS`/`HOLDOUT_SNAPSHOTS` 자체 수정 — 이번
  manifest는 이 dataset들에서 값을 "읽기만" 했다.
* provenance/reconstruction test 제거 또는 약화 — 하지 않았다, 그대로
  유지했다.
