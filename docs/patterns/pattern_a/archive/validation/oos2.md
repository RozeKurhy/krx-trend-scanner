# Pattern A Score v0.2 OOS2 Validation

## 개요

Score Design v0.2는 commit `fffce85`에서 freeze됐고, 재현성 tooling
후속(`_score_v01_baseline()` 완전 독립 고정)도 commit `4501c3b`까지
끝났다. 이 문서는 v0.2 freeze **이후** 처음 보는 완전히 새로운 종목/
snapshot(OOS2)에서 Frozen Pattern A Score v0.2가 어떻게 동작하는지
검증한 결과다.

**핵심 원칙**: OOS2 결과를 보기 전에는 Score v0.2를 절대 수정하지
않는다. 결과가 좋지 않아도 이번 Validation 중간에 threshold나 weight를
수정하지 않는다 — 발견된 문제는 v0.3 development evidence로 넘긴다.

이 문서는 두 단계로 채워진다.

1. **Selection Methodology**(이 절, OOS2 manifest freeze commit에 포함) —
   Score를 계산하기 전에 먼저 작성하고 commit한다.
2. **Frozen v0.2 결과**(별도 절, selection freeze 이후의 별도 commit에서
   추가) — 아래 "Frozen v0.2 결과" 절 참고. 이 절이 비어 있다면 아직
   validation 실행 전이라는 뜻이다.

Git history로 다음 순서를 증명한다.

```
4501c3b (재현성 최종 마무리, Score v0.2 그대로)
  ↓
OOS2 Manifest Freeze — 이 문서의 Selection Methodology + manifest만 포함,
                        Score 계산 없음
  ↓
Frozen v0.2 실행 — 위에서 freeze한 manifest로 score_pattern_a() 호출
  ↓
OOS2 결과 Commit — 이 문서의 "Frozen v0.2 결과" 절 + validation script
                    + 테스트, Score 코드 변경 없음
```

## Selection Methodology

### 데이터 소스

- 후보 43종목의 raw 일봉을 `scripts/_oos2_fetch_and_inspect.py`로
  fetch했다(5종목은 `validate_ohlcv`가 거부하는 OHLC 이상치가 있어
  제외 — 097230 HJ중공업, 267260 HD현대일렉트릭, 128940 한미약품,
  032350 롯데관광개발, 000100 유한양행. 002270은 2022-06-24 이후
  거래 데이터가 없어 확인해보니 실제로는 2022년에 상장폐지된 종목이라
  애초에 후보 이름이 틀렸다 — 006650/240810 등 이미 확보한 대체
  종목으로 충분해 재조사하지 않았다).
- 조회 구간은 `OOS2_SELECTION_START`/`OOS2_SELECTION_END`
  (2011-01-01~2025-12-31)로 절대 고정했다 — 재실행 시점마다 구간이
  밀리는 걸 막기 위해서다(OOS v0.1과 동일 원칙).
- 월봉/주봉 close만 CSV로 저장했다
  (`data/processed/oos2_selection_monthly_close.csv`,
  `data/processed/oos2_selection_raw_summary.csv` — 둘 다 로컬 전용,
  `data/`는 전체 gitignore). Feature나 Score는 **전혀** 계산하지 않았다.

### raw 구조 보조 지표 (scouting 전용)

`_oos2_fetch_and_inspect.py`는 선정을 돕기 위해 pandas rolling으로 4개
raw 보조 지표를 직접 계산한다 — `trend_scanner.features`의 어떤 함수도
호출하지 않는다.

| 이름 | 계산 | 용도 |
|---|---|---|
| `range_36m_raw` | (36개월 최고 - 36개월 최저) / 36개월 최저 | 박스권 폭 |
| `position_36m_raw` | (종가 - 36개월 최저) / (36개월 최고 - 36개월 최저) | 박스권 내 위치 |
| `ma24_raw_slope_6m` | 24개월 단순이동평균의 6개월 전 대비 변화율 | "core" 대리 지표 |
| `ma12w_raw_slope_8w` | 주봉 12주 이동평균의 8주 전 대비 변화율 | "support" 대리 지표 |

**주의**: 이 4개는 production Feature(`range_36m`/`ma24_slope`/
`weekly_ma12_slope` 등)와 계산 방식·스케일이 다르다. manifest의
selection_reason에 적힌 숫자가 나중에 production Feature 계산 결과와
다르더라도 오류가 아니다 — 이 숫자들은 순전히 "어떤 시점을 볼지"
고르기 위한 참고 자료였을 뿐, Score 판단 기준으로 쓰지 않았다.

v0.1/v0.2 Score의 curve breakpoint(예: `ma24_slope` 0.05, 0.15 등)를
선정 cutoff로 쓰지 않았다 — Score 자체의 판단 기준을 선정 단계로
끌어오면 순환 논리가 되기 때문이다. Weak Core/Strong Support 같은
그룹도 "core가 거의 0이거나 음수인데 주봉은 뚜렷하게 양수"라는 구조적
서술로만 판단했다.

### Development Data와의 분리

다음은 이미 v0.2 설계에 영향을 준 데이터라 OOS2 후보에서 제외했다.

- exploration 12 + holdout 15 + negative_control 8
  (`scripts/score_v02_candidate_compare.py`의 EXPLORATION_SNAPSHOTS/
  HOLDOUT_SNAPSHOTS/NEGATIVE_CONTROL_SNAPSHOTS/FAST_MOVER_CASES)
- OOS v0.1 diagnostic 29건(`oos_v01_manifest.py`)

이 종목들의 ticker 집합과 OOS2 manifest의 ticker 집합이 교집합이
없다는 것을 `tests/test_oos_v02_manifest.py::
test_manifest_tickers_are_disjoint_from_development_tickers`가 두 집합을
코드로 직접 import해서 검증한다 — 사람이 눈으로 대조한 목록이 아니다.

OOS v0.1 선정 당시 후보로 검토했지만 최종 미사용한 종목
(011070/010950/000720/010060, `scripts/_oos_fetch_and_inspect.py`
참고)도 OOS2 후보에서 제외했다 — 이미 한 번 "선정 후보"로 본 종목이라
포함하면 ∩=0 주장이 흐려진다.

### Positive Trajectory

일부 positive 종목은 동일 종목에서 여러 snapshot을 둬서(PRE_BREAKOUT→
EARLY_TREND→TREND_PROGRESSED) Pattern A Score가 대세 상승 진행에 따라
어떻게 이동하는지 볼 수 있게 했다: 042700 한미반도체, 105560 KB금융,
086790 하나금융지주, 001040 CJ, 000880 한화. 이 trajectory 선정에서도
v0.2 Score는 전혀 보지 않았다 — 순수하게 raw 종가 흐름(박스 상단
돌파 시점, 이후 확장 여부)만 봤다.

KB금융/하나금융지주는 서로 다른 종목이지만 같은 거시 테마(은행주
밸류업 재평가, 2023년 저점 대비 2024~2025년 재상승)를 공유한다 —
development set에는 은행/보험 섹터가 전혀 없어서, 이 테마 하나로
두 개의 독립적인 trajectory 증거를 확보했다.

### Case Group 구성 (총 38건, 19개 신규 종목)

| case_group | 건수 | 목적 |
|---|---|---|
| positive_pre_breakout | 5 | 박스권 유지, 아직 돌파 전 |
| positive_early_trend | 5 | 돌파 확인 직후 |
| positive_trend_progressed | 6 | 이미 많이 진행된 상승 |
| hard_negative_false_turn | 4 | 일시 개선 후 실패 확인 |
| downtrend_reversal_boundary | 4 | Pattern A/B 경계(장기 하락 중 반등 시도) |
| strong_core_failure | 5 | core는 강했지만 이후 실패(한국타이어형) |
| weak_core_strong_support | 4 | core는 약한데 support만 강함(SKC형) |
| fast_mover | 3 | 짧은 기간에 급격한 전환 |
| insufficient_history | 2 | 36개월/24개월 history 부족 |

전체 manifest는 `src/trend_scanner/validation/oos_v02_manifest.py`의
`OOS_V02_VALIDATION_SNAPSHOTS`에 있다 — 종목/날짜/그룹/선정 근거/
expected_behavior가 전부 그 파일에 기록돼 있고, 이 문서는 그 요약이다.

### selection_reason과 Stage Audit 분리

`selection_reason`은 snapshot 이후 실제 가격 흐름(outcome)을 근거로 들
수 있다 — 예: "2024-12까지 지속 하락 확인". 이건 이 사례를 왜 검증
대상으로 뽑았는지 설명하는 것이라 outcome-conditioned 정보 사용이
허용된다.

반면 **Stage Audit**(snapshot 시점의 Pattern A Stage를 사람이 다시
판정하는 것)은 반드시 `close.index <= snapshot_date` 범위만 보고
판정해야 한다 — "다음 달 돌파", "이후 100% 상승" 같은 미래 정보를 쓰면
안 된다. Manual Stage Audit은 이 문서의 "Frozen v0.2 결과" 절에서 Score
계산과 함께 별도로 기록한다.

### 이번 라운드에서 하지 않은 것

- Score/Feature 계산(다음 commit에서 한다)
- Threshold classification(예: "70점 이상이면 성공") 설계
- 이 selection을 근거로 한 v0.2 산식 수정

## Frozen v0.2 결과

selection freeze commit(`b32f69d`) 이후 `scripts/oos2_validate.py`로
`build_historical_snapshot()` + production `score_pattern_a()`를 그대로
호출했다. Score/Feature 계산 로직은 새로 만들지 않았고,
`pattern_a_score.py`는 이 단계에서도 전혀 수정하지 않았다. v0.1
baseline은 `scripts/score_v02_candidate_compare.py`의
`_score_v01_baseline()`(재현성 최종 마무리에서 alignment까지 완전
독립 고정된 함수)을 그대로 import해서 같이 계산했다 — 재구현하지
않았다.

전체 38 snapshot 중 36건이 정상 계산됐고, 2건(insufficient_history
그룹)은 아래에서 따로 설명한다. CSV는 `data/processed/
oos_v02_validation.csv`(로컬 전용).

### case_group별 pattern_a_score(v0.2) min / median / max

| case_group | n | min | median | max |
|---|---|---|---|---|
| positive_pre_breakout | 5 | 0.00 | 64.64 | 74.54 |
| positive_early_trend | 5 | 66.67 | 84.79 | 99.77 |
| positive_trend_progressed | 6 | 0.00 | 41.76 | 76.52 |
| hard_negative_false_turn | 4 | 39.25 | 74.65 | 100.00 |
| downtrend_reversal_boundary | 4 | 22.59 | 44.81 | 49.41 |
| strong_core_failure | 5 | 30.44 | 64.89 | 98.17 |
| weak_core_strong_support | 4 | 0.00 | 21.94 | 73.40 |
| fast_mover | 3 | 0.00 | 89.33 | 91.79 |
| insufficient_history | 0 | — | — | — |

### v0.1 baseline vs v0.2 비교 (paired diff, case별 pattern_a_score(v0.2) − v0.1)

case_group별 median(v0.2) − median(v0.1)로 계산하면 표본이 작아
왜곡된다(unpaired). 아래는 **snapshot별로 짝을 지은** 차이의 중앙값이다.

| case_group | n | paired diff median | paired diff mean |
|---|---|---|---|
| weak_core_strong_support | 4 | **-24.52** | -21.26 |
| downtrend_reversal_boundary | 4 | -10.62 | -10.43 |
| positive_trend_progressed | 6 | +5.18 | +5.25 |
| positive_early_trend | 5 | +5.97 | +3.46 |
| positive_pre_breakout | 5 | +5.79 | -0.79 |
| strong_core_failure | 5 | +5.58 | +6.87 |
| hard_negative_false_turn | 4 | +2.86 | +2.72 |
| fast_mover | 3 | +2.61 | +1.76 |

v0.2가 6/8 그룹에서 v0.1보다 절대값이 높게 나오는 건 Core+Confirmation
구조 자체의 특성이다 — v0.2의 transition은 core_score를 하한으로 갖고
거기에 confirmation_bonus를 더하는 구조라, core가 강한 케이스는
거의 전부 v0.1의 가중합(0.6·core+0.2·weekly+0.2·accel)보다 높게
나온다. 그래서 **버전 간 절대 수준 비교보다 "같은 버전 안에서 그룹이
얼마나 잘 분리되는가"가 더 의미 있는 지표**다 — 아래 각 그룹 절에서
그 분리도를 본다.

## 12. Weak Core + Strong Support 결과 (핵심 질문 1)

**Core weak(<50) + Support strong(≥50) quadrant 전체(4개 case_group에
걸쳐 6건)를 보면 v0.2가 v0.1보다 6/6 전부 낮다** — case_group 딱지가
아니라 core/support 실제 값 기준으로 봤을 때 만장일치다.

| ticker | name | snapshot_date | case_group | core_score | support_score | v0.1 | v0.2 |
|---|---|---|---|---|---|---|---|
| 015760 | 한국전력 | 2024-02-29 | hard_negative_false_turn | 44.99 | 55.17 | 65.83 | 62.06 |
| 034220 | LG디스플레이 | 2020-12-31 | downtrend_reversal_boundary | 38.48 | 59.45 | 55.82 | 49.41 |
| 023530 | 롯데쇼핑 | 2025-05-31 | downtrend_reversal_boundary | 30.27 | 68.64 | 61.27 | 45.71 |
| 353200 | 대덕전자 | 2025-08-31 | weak_core_strong_support | 0.00 | 65.00 | 38.78 | **0.00** |
| 240810 | 원익IPS | 2019-10-31 | weak_core_strong_support | 27.47 | 51.08 | 52.32 | 42.07 |
| 034220 | LG디스플레이 | 2020-09-30 | weak_core_strong_support | 0.92 | 71.36 | 40.82 | **1.81** |

case_group으로 좁혀서 이름 그대로 라벨링한 4건만 봐도 3/4가 뚜렷하게
억제됐다(-38.78/-10.25/-39.00) — 나머지 1건(240810, 2020-07-31)은
scouting 단계에서는 "core flat(-0.007)"로 보였지만 실제 production
`ma24_slope`(+0.0231)이 curve breakpoint(0.00→50점, 0.05→90점) 근처라
`core_score=68.50`으로 계산돼 애초에 "weak core"가 아니었다 — 이건
scouting raw 지표와 production Feature 스케일이 다르다는 걸 보여주는
사례이지 v0.2의 문제가 아니다(이 case는 +3.01로 결과가 갈렸다).

**결론**: SKC/한국타이어형이 동기가 된 "core 약한데 support만 강해서
과대평가되는" 실패 메커니즘은 OOS2에서도 방향이 맞게 억제된다.

## 13. Clean Early Trend 결과

5건 전부 절대 수준으로 clean early trend 범위(66.67~99.77)에 있다.
자기 자신의 positive_pre_breakout 단계와 비교하면 4건은 명확히
더 높다(105560: 62.01→66.67, 086790: 64.64→80.81, 001040: 74.54→99.77,
000880: 72.41→89.02) — `clean_early_trend_should_score_meaningfully_
higher_than_pre_breakout`을 만족. 나머지 1건(042700)은 pre_breakout
쌍 자체가 0.00(20절의 core=0 붕괴)이라 "더 높다"는 비교가 산술적으로
항상 참이 되므로 상대 비교로는 무의미하다 — 절대 수준(84.79)만
근거로 쓴다. 000880(fast breakout, 2개월 만에 돌파)도 `fast_breakout_
should_still_score_as_clean_early_trend`를 만족(89.02).

## 14. Trend Progressed 결과

6건 median 41.76로 early_trend median(84.79)보다 뚜렷하게 낮다 —
Already Progressed Penalty가 방향대로 작동한다. 다만 이 그룹 1건
(042700 2023-12)은 penalty가 문제가 아니라 **base_score 자체가
0으로 붕괴**해서 최종 0이 됐다. 같은 메커니즘이 fast_mover 그룹
1건(000880 2025-06, 18절)에서도 나타난다 — 둘 다 v0.1도 동일하게
0.00이라(v01_pattern_a_score=0.00) v0.2가 새로 만든 문제가 아니다.
20절의 core=0 붕괴(transition_score가 정확히 0이 되는 v0.2 고유
메커니즘)와는 다른, Base Score 쪽의 별개 현상이다.

## 15. Pattern A / B Boundary 결과

4건 전부 max 49.41을 넘지 않는다 — "장기 하락 중 반등 시도"가
early_trend 수준(median 84.79)까지 과대평가되는 일은 없었다. v0.1
대비도 4건 전부 낮아졌다(paired diff median -10.62) — 경계 케이스를
v0.2가 v0.1보다 더 신중하게 본다.

## 16. Strong Core Failure 결과 (한국타이어형, 알려진 한계 재확인)

5건 median 64.89 — v0.1(56.99)보다 오히려 **더 높다**(paired diff
+5.58, 8개 그룹 중 두 번째로 큰 상승폭). v0.2의 Core+Confirmation
구조는 "snapshot 시점에 core가 강하면 반드시 높은 transition을 준다"는
점에서 v0.1과 다르지 않다 — 오히려 confirmation_bonus가 추가로
붙어서 더 높게 나온다. **이 실패 메커니즘(스냅샷 시점엔 강해 보이지만
이후 실패)은 v0.2가 해결하려던 문제가 아니었고(Core/Supporting
상호작용·alignment FP·Pattern A/B 경계가 목표였다), 실제로도 OOS2에서
개선되지 않았다** — 현재 Pattern A v0.2 Feature Set(range_36m/
avg_price_change_12m/ma_spread/ma24_slope/weekly_ma12_slope/
ma24_slope_acceleration/range_position)만으로는 snapshot 당시 강한
Core가 이후에도 지속될지를 구분하지 못한 상태로 **미해결**이다 —
"원리적으로 불가능"으로 단정하지 않는다. 상대강도(Relative
Strength)/거래대금/변동성 구조/수급/Score Momentum 같은 추가 정보가
Feature Set에 들어오면 이 실패 확률을 줄일 여지는 열어둔다(v0.3
candidate 방향, 이번 라운드에서 구현하지 않음).

## 17. Alignment core threshold 60 audit — 판정 불가

정렬 조건을 만족한 18건 중 `core_score<60` 그룹은 2건뿐이고(001040
2023-12, 086790 2024-02), 둘 다 positive(양의 결과)다 — `core_score
>=60` 쪽과 비교할 negative 표본이 없다. **OOS2로는 threshold 60이
잘 작동하는지 판정할 수 없다** — "60이 의미 있게 작동한다"고 결론
내리지 않는다. 표본 부족이 그대로 이번 라운드의 답이다.

## 18. Fast Mover 결과

3건 중 2건(353200 91.79, 015760 89.33)은 빠른 전환이 정상적으로 높게
평가됐다. 1건(000880 2025-06, 4개월 만에 2배)은 **0.00** — 20절의
Base Score 붕괴 메커니즘과 겹친다(avg_price_change_12m 등이 이미
극단값을 찍어 base_score=9.85로 떨어지고, progressed_evidence_count가
높아 penalty 35까지 붙는다). 즉 progressed penalty가 "적당히 빠른"
주도주는 죽이지 않지만, "극단적으로 빠른"(단기간 100%+ 상승) 주도주는
Base Score 붕괴와 맞물려 죽인다 — 정도의 문제이지 전면적인 문제는
아니다.

## 19. Insufficient History 결과

2건(353200 2021-06, 403870 2023-12) 모두 `build_historical_snapshot()`
이 예외 없이 정상 반환했고, `insufficient_data=True`, `pattern_a_score`/
`stage` 전부 None으로 나왔다 — pre-registered `expected_behavior`
(`insufficient_history_should_return_none`)와 정확히 일치. required
anchor 정책이 실제로 짧은 history에서 작동함을 확인했다.

## 20. 새롭게 발견된 failure mechanism: core=0 절대 붕괴

v0.1에는 없던, v0.2 Core+Confirmation 구조가 만드는 **새로운 절대
실패 지점**을 발견했다.

| ticker | case_group | snapshot | core_score | base_score | v0.1 | v0.2 |
|---|---|---|---|---|---|---|
| 042700 | positive_pre_breakout | 2019-12-31 | 0.00 | 78.11 | 23.74 | **0.00** |
| 353200 | weak_core_strong_support | 2025-08-31 | 0.00 | 76.28 | 38.78 | **0.00** |
| 034220 | weak_core_strong_support | 2020-09-30 | 0.92 | 68.36 | 40.82 | **1.81** |

메커니즘: v0.2의 `confirmation_gate`는 `core_score`의 piecewise
함수이고 `core_score=0`이면 `gate=0`, 그러면 `confirmation_bonus=0`,
`transition_score=core_score=0`이 된다. `balanced_core_score`는
`harmonic_mean(base_score, transition_score)`인데, 조화평균은 두 값
중 하나가 0이면 결과도 0이다 — **base_score가 아무리 높아도(78, 76)
transition_score가 정확히 0이면 최종 점수는 0으로 무너진다.**

v0.1은 이 문제가 없었다 — transition이 `0.6·core+0.2·weekly+
0.2·accel` 가중합이라 core가 0이어도 weekly/accel이 양수면 transition
자체는 0보다 컸다(그래서 042700이 23.74를 받았다). v0.2는 그 바닥을
없앤 대신(그게 SKC형 실패를 막는 핵심 장치였다) core=0인 순간
transition 전체가 0으로 떨어지는 새 절대 지점을 만들었다.

**이건 SKC형 FP를 막은 것과 같은 메커니즘이 만드는 부작용이다** — "core가
약하면 transition을 깎는다"는 장치가 core=0에서는 "transition을
완전히 지운다"로 극단화된다. 042700(2019-12)은 명백한 clean
pre_breakout(6년치 박스, 저점 상승 없음, Base 78점)인데도 이 시점에
ma24_slope가 curve floor(-0.05) 아래라 core=0이 되면서 전체 점수가
사라졌다 — `pre_breakout_should_preserve_base_identity` 기대를
위반한 유일한 케이스다.

**이번 라운드에서는 이 메커니즘을 수정하지 않는다** — v0.3
development evidence로 등록한다: `core_score=0`일 때
`balanced_core_score`가 harmonic mean 대신 다른 결합(예: base_score에
비례한 최소 바닥)을 갖게 하는 안, 또는 confirmation_gate 최저치를
0이 아니게 하는 안 등을 v0.3에서 검토할 후보로 남긴다.

(참고: 이건 Base가 **낮아서** 생기는 문제가 아니라 core=0이 harmonic
mean을 강제로 0으로 만드는 Transition 결합 방식의 문제다 — Base 축
자체의 별개 gap(하락 구조도 만점을 주는 negative clamp)은 "Hard
Negative Failure Audit" 절에서 evidence C로 별도 등록했다. 서로
다른 메커니즘이라 섞지 않는다.)

## 21. Manual Stage Audit 결과 (snapshot 시점 정보만 사용, diagnostic only)

positive trajectory 16건 + boundary 4건에 대해 raw 종가 구조
(`position_36m_raw`/`ma24_raw_slope_6m`, 전부 snapshot 시점까지의
rolling window만 사용 — 미래 정보 없음)만 보고 사람이 다시 판정한
Stage와, Score가 반환한 `stage` 필드를 비교했다.

| 구간 | 일치 | 대표 불일치 |
|---|---|---|
| pre_breakout(5건) | 1/5 | 4건에서 model은 "transition", 수동 판정은 "아직 박스 안"(105560/086790/001040/000880) — ma24_slope가 -0.03~+0.02 정도로 flat에 가까우면 Stage가 이미 transition으로 넘어간다 |
| early_trend(5건) | 3/5 | 086790(core=59.5)/105560(core=50.0)는 신고가 돌파(position=1.0) 시점인데도 model은 "transition"에 머문다 |
| trend_progressed(6건) | 5/6 | 000810(2024-06, core=93, 돌파 11개월 경과)을 model은 아직 "early_trend"로 분류 — progressed 승격이 늦다 |
| downtrend_reversal_boundary(4건) | 4/4(개념상) | model에 별도 "boundary" 라벨이 없어 전부 "base"로 나오지만, 수동 판정도 "아직 진짜 패턴 아님"이라 방향은 일치 |

Stage 자동 분류기는 "자동 분류 threshold는 미구현"이라는 코드 주석
그대로 아직 정식 threshold가 없는 상태다(로드맵 Phase — Stage
Classifier redesign 별도 예정). 이 불일치는 **diagnostic으로만
기록**하고, 이번 라운드에서 Stage 로직을 수정하지 않는다(item 23).

## 22. v0.2에 대한 최종 판단

단일 aggregate metric 하나로 PASS/FAIL을 정하지 않고, 순서대로
판단한다.

1. **Feature role consistency** — Core(ma24_slope)/Supporting(weekly,
   acceleration) 역할 구분은 OOS2에서도 유지됐다. 위반 없음.
2. **Weak Core + Strong Support 실패가 구조적으로 억제되는가** — 그렇다.
   core_weak+support_strong quadrant 6/6 전부 v0.1보다 낮다(12절).
3. **Clean Early positive를 심하게 훼손하지 않는가** — 대체로 아니다.
   단, core=0 근처의 clean pre_breakout 1건(042700)이 완전히
   훼손됐다(20절) — "심하게"의 기준에 따라 이 항목은 조건부 통과다.
4. **Progressed와 boundary에서 예상 못한 높은 Score가 반복되는가** —
   아니다. boundary max 49.41, progressed median 41.76로 과대평가
   없음.
5. **새로운 failure mechanism이 등장하는가** — 그렇다. core=0 절대
   붕괴(20절)는 v0.2가 새로 만든 지점이고, Hard Negative Audit
   과정에서 Base `avg_price_change_12m` negative clamp(Base가 하락
   구조도 만점 처리하는 gap)도 추가로 확인됐다 — 둘 다 v0.3
   development evidence로 등록했다.
6. **v0.1 대비 v0.2 변경 방향이 OOS2에서도 재현되는가** — 그렇다.
   Weak Core+Strong Support 억제, boundary 억제 모두 development set에서
   봤던 방향 그대로 재현됐다. Strong Core Failure는 애초에 v0.2가
   풀려던 문제가 아니었고, 현재 Feature Set으로는 미해결로 남았다
   (16절 — "원리적으로 불가능"이 아니라 상대강도/거래대금/수급 같은
   추가 정보가 들어오면 개선될 여지가 있는 상태다).

**종합(재리뷰 후속으로 잠정 하향)**: Score 산식은 수정하지 않는다.
다만 hard_negative_false_turn 4건(median 74.65, max 100.00)이
positive_pre_breakout median(64.64)보다 높게 나온 원인을 개별
분해하지 않은 채 아래 문구로 확정했던 것은 성급했다 — 판정을
"Hard Negative Failure Audit" 절(아래)의 결과가 나올 때까지
한 단계 낮춘다.

> **Pattern A Score v0.2 — Frozen after OOS2. Final confirmation
> pending hard-negative audit.** (잠정. 아래 "## Hard Negative
> Failure Audit" 절의 "v0.2 최종 판단"과 "문서 최종 상태 블록"이
> 최종본이다 — 이 문서의 현재 상태 판정은 그 절을 따른다. hard
> negative 4건의 직접 원인은 Strong Core Failure 반복으로 확인됐지만,
> audit 과정에서 Base negative clamp라는 새 v0.3 evidence가 나와서
> "Final Freeze Confirmed"가 아니라 **"v0.2 Frozen · OOS2 Validation
> Completed · v0.3 Development Required"**로 정리됐다. 여기 문구는
> 판단 과정을 남겨두기 위한 이력이다.)

## Hard Negative Failure Audit

`scripts/oos2_hard_negative_audit.py`로 manifest의 hard_negative_
false_turn 4건(추가/삭제 없음, 그대로)을 다시 계산했다 — production
`score_pattern_a()`/`_score_v01_baseline()`을 identity로 재사용하고,
결과 필드에서 counterfactual만 사후에 유도했다. Feature/Score 자체는
전부 snapshot_date 당시 데이터만 쓴다 — selection_reason의 미래
outcome은 분류(왜 이 사례가 "false turn"인지)에만 쓰고 계산에는
쓰지 않았다.

### 4건 개별 component

| ticker | name | snapshot_date | ma24_slope | weekly_ma12_slope | ma24_slope_accel | range_position | base_score | core_score | support_score | confirmation_bonus | transition_score | balanced_core_score | alignment_bonus | progressed_evidence_count | progressed_penalty | pattern_a_score | v0.1 | stage |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 015760 | 한국전력 | 2024-02-29 | -0.0050 | 0.0572 | 0.0213 | 0.768 | 100.00 | 44.99 | 55.17 | 0.00 | 44.99 | 62.06 | 0 | 0 | 0 | 62.06 | 65.83 | transition |
| 023530 | 롯데쇼핑 | 2023-12-31 | -0.0250 | 0.0205 | 0.0230 | 0.143 | 91.32 | 25.00 | 46.54 | 0.00 | 25.00 | 39.25 | 0 | 0 | 0 | 39.25 | 49.14 | base |
| 001450 | 현대해상 | 2017-08-31 | 0.0530 | 0.0820 | 0.0158 | 0.865 | 88.41 | 90.30 | 57.93 | 11.59 | 100.00 | 93.85 | 8 | 1 | 0 | **100.00** | 90.51 | early_trend |
| 007070 | GS리테일 | 2017-04-30 | 0.0485 | 0.0181 | -0.0133 | 0.665 | 80.81 | 88.80 | 29.83 | 5.97 | 94.77 | 87.24 | 0 | 0 | 0 | 87.24 | 72.18 | early_trend |

selection_reason 요약(전체는 manifest 참고): 015760은 일시 반등 후
되돌림, 023530은 지속 하락 확인, 001450은 2017년 돌파 후 2019년까지
2015년 수준으로 되돌림, 007070은 2017년 강세 후 2024년까지도 미회복.

**중요한 관찰**: 4건이 균질하지 않다. 023530(39.25)과 015760(62.06)은
positive_pre_breakout median(64.64)과 비슷하거나 낮다 — 이 둘은
애초에 "높은 Score" 문제가 아니다. 그룹 median(74.65)과 max(100.00)를
끌어올리는 건 001450과 007070 2건뿐이다.

### Failure mechanism 분류

| ticker | 분류 | 근거 |
|---|---|---|
| 015760 | F(Mixed, 최종 결과는 문제 아님) — 단 Base=100 자체는 아래 B로 별도 등록 | core_score 44.99로 약함, confirmation_bonus=0(gate 미작동, 정상), core가 낮아 harmonic mean이 Base=100을 충분히 눌러 최종 62.06(pre_breakout median 이하)으로 억제됐다. 다만 Base=100이라는 값 자체는 "장기 하락 후 일시 반등" 종목에 나온 것이라 **B(Base False Positive) 구조 결함**의 증거로는 별도로 쓴다 |
| 023530 | 해당 없음(정상 억제) — 단 Base=91.32 자체는 아래 B로 별도 등록 | 39.25로 낮게 나옴 — 애초에 최종 Score의 "false positive"가 아니라 v0.2가 의도대로 억제한 케이스. 다만 Base=91.32는 "2014~2024 지속 하락 확인" 종목에 나온 값이라 마찬가지로 **B**의 증거 |
| 001450 | **A. Strong Core Failure**(주), C는 부차적 | core_score=90.30(매우 강함), transition_score=100(정당한 core+confirmation), balanced_core=93.85 — alignment 없이도 이미 93.85로 매우 높음. alignment는 93.85→100(clip) 구간만 밀어올림 |
| 007070 | **A. Strong Core Failure** | core_score=88.80, transition=94.77, alignment_bonus=0(acceleration이 음수라 정렬 조건 미충족) — alignment 관여 전혀 없이 balanced_core_score=87.24 자체가 최종값 |

**001450/007070의 고득점 "직접 원인"으로는 B(Base False Positive)/
D(Progressed Penalty Failure)/E(Core+Confirmation Failure) 전부
해당하지 않는다** — 아래에서 각각 확인. 다만 B는 이 두 사례에서만
"해당 없음"이다: **015760/023530에서는 실제로 별도의 Base False
Positive 구조 결함이 확인됐다**(아래 "Base False Positive 분석"
절). 이 Base 문제는 hard negative 4건의 고득점을 만든 직접 원인은
아니지만(015760/023530 자체는 최종 점수가 낮게 나와 core가 결과를
억제했다), v0.3 development evidence로는 별도로 유지한다.

### strong_core_failure 그룹과 비교

| case_group | n | min | median | max |
|---|---|---|---|
| hard_negative_false_turn | 4 | 39.25 | 74.65 | 100.00 |
| strong_core_failure | 5 | 30.44 | 64.89 | 98.17 |

component median 비교:

| | hard_negative_false_turn | strong_core_failure |
|---|---|---|
| base_score | **89.87** | 51.80 |
| core_score | 66.90 | **92.87** |
| support_score | 50.85 | 37.53 |
| transition_score | 69.88 | 99.80 |

core_score만 보면 hard_negative 그룹의 median(66.90)이 strong_core_
failure(92.87)보다 낮아 보이지만, 이건 015760/023530(core 25~45)이
median을 끌어내린 것이고, **001450/007070만 떼어 놓으면 core_score
90.30/88.80으로 strong_core_failure 그룹의 median(92.87)과 사실상
같은 구간**이다. 오히려 base_score는 001450/007070(88.41/80.81)이
strong_core_failure 그룹 median(51.80)보다 훨씬 높다 — 즉 이 두
건은 "strong_core_failure의 반복"일 뿐 아니라, **strong_core_failure
그룹보다 Base까지 더 깨끗해 보이는 케이스였다**. Base+Core가 둘 다
좋아 보였는데도 이후 실패했다는 뜻이라 A(Strong Core Failure) 분류를
더 강하게 뒷받침한다 — snapshot 하나만 보는 구조로는 원리적으로
가려낼 수 없는 persistence 문제라는 결론과 일치한다.

### Base False Positive 분석 (item 7)

**100점을 만든 001450/007070만 보면 안 된다** — item 7이 요구하는
질문("Base가 매우 높은데 실제로는 장기 Base라고 보기 어려운 사례가
있는가")에 대한 답은 오히려 **015760과 023530**에 있다.

| ticker | base_score | range_36m | avg_price_change_12m | ma_spread | 실제 구조 |
|---|---|---|---|---|---|
| 015760 | **100.00** | 0.540 | -0.085 | 0.036 | 장기 하락 후 일시 반등, 되돌림(hard negative) |
| 023530 | **91.32** | 0.755 | -0.160 | 0.160 | 2014~2024 지속 하락 확인(23절 selection_reason) |
| 001450 | 88.41 | 0.803 | +0.143 | 0.119 | 실제 박스형 구조, 이후 실패(core 문제) |
| 007070 | 80.81 | 1.123 | -0.064 | 0.033 | 실제 박스형 구조, 이후 실패(core 문제) |

메커니즘: `avg_price_change_12m` 곡선의 왼쪽 끝이 `(0.10, 100.0)`이다
— 0.10 미만이면 전부 100점이고, **음수(가격이 실제로 하락)도 예외
없이 100점**이다. 015760(range_36m=0.540도 첫 breakpoint 0.6 미만이라
100점, ma_spread=0.036도 첫 breakpoint 0.10 미만이라 100점)은 세
Feature 전부가 각자의 clamp 구간에 걸려 base_score가 정확히 100.00이
됐다 — "장기 박스"가 아니라 "장기 하락 중 반등 실패" 종목인데도 Base
축 하나만 보면 만점이다. 023530도 직접 계산하면 재현된다: `0.55×
89.64(range_36m) + 0.30×100(avg_price_change_12m, 음수 clamp) +
0.15×80.10(ma_spread) = 91.32`.

**001450/007070의 100점/87.24점은 Base 문제가 아니다** — 001450의
avg_price_change_12m은 +0.143로 clamp 구간이 아니라 정상적인 완만한
상승이고, 두 종목 다 실제로 타이트한 박스 구조였다(A. Strong Core
Failure 결론 유지). 다만 **Base 축 자체는 "횡보"와 "하락"을 구분하지
못한다**는 게 015760/023530에서 확인됐다 — 이번 4건의 높은 Score
원인은 아니지만(core_score가 낮아 015760=62.06/023530=39.25로 최종
결과는 억제됐다), Base 곡선 설계의 별도 gap으로 v0.3 evidence에
등록한다(아래 "새롭게 확인된 failure mechanism" 참고).

### Alignment counterfactual (item 8)

| ticker | balanced_core_score | alignment_bonus | pattern_a_score | final_without_alignment | alignment_lift | raw_final_before_clip |
|---|---|---|---|---|---|---|
| 015760 | 62.06 | 0 | 62.06 | 62.06 | 0.00 | 62.06 |
| 023530 | 39.25 | 0 | 39.25 | 39.25 | 0.00 | 39.25 |
| 001450 | 93.85 | 8 | 100.00 | 93.85 | **6.15** | 101.85 |
| 007070 | 87.24 | 0 | 87.24 | 87.24 | 0.00 | 87.24 |

alignment가 관여한 건 001450 1건뿐이고, 그 1건도 **alignment 없이
이미 93.85로 충분히 높다** — alignment_lift(6.15)는 93.85를 100
clip까지 밀어올린 "추가 효과"이지 100점의 원인이 아니다. `raw_final_
before_clip=101.85`로 clip 폭 자체도 1.85점(alignment 미포함 시
93.85, alignment 포함 시 101.85 중 100을 넘는 부분만 1.85)이라 크지
않다. **alignment는 보조적 기여이지 주된 원인이 아니다** — Alignment
Amplification(C)을 독립적인 구조적 문제로 등록하지 않는다.

### Progressed penalty 분석 (item 9)

| ticker | range_position | avg_price_change_12m | progressed_evidence_count | progressed_penalty |
|---|---|---|---|---|
| 001450 | 0.865 | 0.143 | 1 (range_position만 threshold 0.85 초과) | 0 |
| 007070 | 0.665 | -0.064 | 0 | 0 |

001450은 range_position 하나만 threshold를 살짝 넘었고 나머지 4개
evidence(range_36m/avg_price_change_12m/ma_spread/ma24_slope)는 전부
threshold 미달이다 — "이미 많이 진행된 상태"라기보다 "막 신고가를
찍은 신선한 돌파"에 더 가까운 프로필이라, evidence_count=1/penalty=0은
설계 의도상 합리적이다. 007070은 avg_price_change_12m이 오히려
음수라 evidence 0건이 당연하다. **Progressed Penalty Failure(D)로
등록하지 않는다** — 두 사례 다 "아직 진행되지 않은 신선한 돌파처럼
보였다"는 게 핵심이고, 그게 바로 Strong Core Failure의 정의 그
자체다(진행되지 않았으니 페널티가 없는 게 당연하고, 그런데도 나중에
실패했다).

### Core + Confirmation 분석 (item 10)

| ticker | core_score | support_score | confirmation_bonus | confirmation_share |
|---|---|---|---|---|
| 001450 | 90.30 | 57.93 | 11.59 | 0.116 |
| 007070 | 88.80 | 29.83 | 5.97 | 0.063 |

두 사례 다 core_score가 88~90으로 이미 매우 강해서 confirmation_
share가 6~12%에 불과하다 — transition_score는 core_score가 거의
전부를 설명하고 confirmation_bonus는 미미한 보정치다. **Weak Core +
Strong Support 문제(E)가 재발한 게 아니다** — core가 이미 80~100
구간이면 이 분류에 넣지 않는다는 기준에 따라 명확히 제외한다.

### 100점 사례 완전 분해 (001450 현대해상, 2017-08-31)

```
Base       = 88.41                     (range_36m/avg_price_change_12m/ma_spread 가중합)
Core       = 90.30  (ma24_slope=0.0530)
Support    = 57.93  (weekly=0.0820, accel=0.0158 평균)
Confirmation gate(core=90.30) ≈ 1.0 → confirmation_bonus = 20.0 * (57.93/100) * gate ≈ 11.59
Transition = min(100, 90.30 + 11.59) = 100.00   (min() clip 발동)
Balanced   = harmonic_mean(88.41, 100.00) = 93.85
Alignment  = weekly>0 and ma24>0 and accel>0 → 전부 충족, core>=60 → +8.0
Penalty    = evidence_count=1 → 0.0
raw_final_before_clip = 93.85 + 8.0 - 0.0 = 101.85
pattern_a_score = clip(101.85, 0, 100) = 100.00   (여기서도 clip 발동)
```

**clip이 두 번 발동한다**: transition_score 단계에서 한 번(90.30+11.59
=101.89→100, 이건 core+confirmation이 이미 100을 넘어서인데 이 자체는
core가 워낙 강해서 생긴 것), 최종 pattern_a_score 단계에서 한 번
(101.85→100). raw_final_before_clip=101.85는 120처럼 극단적으로 큰
값이 아니라 100을 살짝(1.85점) 넘는 수준이라 — "정책이 완전히
고장났다"기보다 "core+alignment가 둘 다 만점 근처로 겹쳤을 때 자연스럽게
생기는 ceiling 근접"으로 해석한다. 근본 원인은 alignment가 아니라
**core_score=90.30 자체가 진짜로 강했다**는 것이다.

### v0.1 vs v0.2 비교

| ticker | v0.1 | v0.2 | diff | 분류 |
|---|---|---|---|---|
| 015760 | 65.83 | 62.06 | -3.77 | 거의 동일(소폭 개선) |
| 023530 | 49.14 | 39.25 | -9.89 | 개선(억제) |
| 001450 | 90.51 | 100.00 | **+9.49** | 악화 |
| 007070 | 72.18 | 87.24 | **+15.06** | 악화 |

001450/007070 둘 다 v0.2에서 v0.1보다 더 높아졌다 — core_score가
강한 케이스에서 v0.2의 Core+Confirmation 구조(transition이 core를
하한으로 갖고 confirmation_bonus가 추가됨)가 v0.1의 가중합(0.6·core+
0.2·weekly+0.2·accel)보다 항상 크거나 같기 때문이다. **이건 새로운
버그가 아니라 Core+Confirmation 구조의 known tradeoff**로 기록한다 —
Weak Core+Strong Support를 억제하려고 만든 구조가, Core가 이미 강한
케이스에서는 v0.1보다 더 관대해지는 것도 같은 설계의 반대쪽 효과다.

### 새롭게 확인된 failure mechanism

**001450/007070의 고득점을 설명하는 새 *메커니즘*은 없다** — 둘 다
A(Strong Core Failure)로 설명되고, 이 둘의 고득점 "직접 원인"으로는
B(Base False Positive)/D(Progressed Penalty Failure)/E(Core+
Confirmation Failure)가 해당하지 않으며 C(alignment)는 부차적 기여로만
확인됐다. 나머지 2건(015760/023530)은 애초에 문제가 아니었다
(pre_breakout median 이하) — **하지만 이 2건에서 B(Base False
Positive) 자체는 별도로 실제 확인됐다**(위 "Base False Positive
분석" 절). B가 "4건 전부 해당 없음"이 아니라 "001450/007070의 고득점
직접 원인은 아니지만 015760/023530에서 독립적으로 존재한다"는 게
정확한 결론이다.

다만 이 audit 과정에서 확인된 **새 *정보* 2건**은 있다 — "4건의 높은
Score를 설명하지는 않지만" v0.3에 남겨야 하는 것들이다: (1) Base
`avg_price_change_12m` 음수 clamp가 하락 종목에 만점을 준다는 것
(바로 위 절), (2) 001450/007070이 v0.1보다 v0.2에서 각각 +9.49/
+15.06 더 높아진 것(아래 "v0.1 vs v0.2 비교" 절 — 이건 이미 위에서
다뤘고, known tradeoff로 기록했다).

### 기존 core=0 failure와의 관계

이번 audit과 무관하다 — 완전히 분리된 별개의 v0.3 evidence다. 이번
4건 중 core_score=0인 케이스는 없다(015760이 가장 낮아도 44.99).
v0.3 development evidence를 3건으로 분리해서 기록한다.

- **A. core=0 collapse**(20절): `confirmation_gate(core=0)=0` →
  `transition_score=0` → harmonic mean이 `base_score`를 무시하고
  강제로 0. v0.2가 새로 만든 절대 붕괴 지점.
- **B. hard negative / strong core failure persistence 문제**(이번
  절): snapshot 하나만 보는 구조상, "지금 core가 강하다"와 "이 core가
  유지될 것이다"를 구분할 신호가 Pattern A Score 안에 없다. v0.1에도
  있던 한계이고 v0.2에서 core+confirmation 구조 때문에 오히려 살짝
  더 두드러진다(001450: +9.49, 007070: +15.06). 두 evidence는
  메커니즘이 다르므로 v0.3에서 서로 다른 해법이 필요할 수 있다(A는
  transition의 하한 설계 문제, B는 애초에 단일 snapshot으로는 풀기
  어려운 forward-looking 정보 부재 문제).
- **C. Base `avg_price_change_12m` 음수 clamp**("Base False Positive
  분석" 절): 곡선 좌단이 `(0.10, 100.0)`이라 음수(실제 가격 하락)도
  전부 100점을 받는다 — 015760(base=100.00, 세 Feature 전부 clamp),
  023530(base=91.32)에서 확인. 이번 4건의 높은 Score 원인은 아니지만
  (core_score가 낮아 최종 결과는 억제됨), Base 축이 "횡보"와 "하락"을
  구분 못한다는 건 A/B와 별개인 v0.3 candidate다.

### v0.2 최종 판단 (재리뷰 후속으로 수정)

hard negative 4건 중 그룹 median/max를 견인하는 2건(001450/007070)은
기존 Strong Core Failure 메커니즘의 반복이었다 — alignment, progressed
penalty, weak core+strong support 재발이 주 원인은 아니었다. 다만 이
audit 과정에서 **Base `avg_price_change_12m` negative clamp**라는
별도의 구조적 gap을 새로 확인했다(015760/023530). 이건 hard negative
4건의 고득점 원인은 아니지만, OOS2 전체를 통틀어 새로 확인된 v0.3
development evidence이기 때문에, "이 설계가 최종 버전"이라는 의미의
Final Freeze Confirmed는 더 이상 쓰지 않는다 — v0.2는 그대로 frozen
baseline으로 유지하되, 상태를 아래처럼 정리한다.

> **Pattern A Score v0.2 — Frozen. OOS2 Validation — Completed.
> v0.2 production code — No further tuning. v0.3 Development —
> Required.**

v0.2가 "실패했다"는 뜻이 아니다 — 설계 방향(Weak Core+Strong Support
억제, Pattern A/B boundary 개선, Clean Early Trend 보존, Progressed
억제, Core/Supporting 역할 분리)은 OOS2에서 그대로 재현됐고 이 결론은
그대로 유지한다(12절, 15절). 다만 OOS2 이후 구조적 improvement
후보(A/B/C, 아래 최종 상태 블록)가 실제로 확인된 상태에서 "더 이상
손댈 곳이 없다"는 의미의 문구를 쓰는 건 정확하지 않아서 내린다.
`pattern_a_score.py`는 이번 audit에서도 전혀 수정하지 않았다.

### 문서 최종 상태 블록

| 항목 | 상태 |
|---|---|
| Pattern A Score v0.2 | Frozen |
| OOS2 Validation | Completed |
| Core + Confirmation redesign | Validated |
| Weak Core + Strong Support | Improved |
| Pattern A / B boundary | Improved |
| Strong Core Failure | Unresolved (현재 Feature Set 한계, 원리적 불가능 아님) |
| Alignment core threshold 60 | Inconclusive (표본 부족, 17절) |
| Core Zero Collapse | v0.3 Evidence |
| Base Negative Clamp | v0.3 Evidence |
| v0.3 Development | Required |
