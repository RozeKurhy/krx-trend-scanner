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
개선되지 않았다** — snapshot 하나만 보는 구조상 원리적으로 풀 수 없는
문제일 가능성이 높다(미래 정보 없이는 "지금 강한 core가 유지될지"를
알 수 없다).

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
   붕괴(20절)는 v0.2가 새로 만든 지점이다.
6. **v0.1 대비 v0.2 변경 방향이 OOS2에서도 재현되는가** — 그렇다.
   Weak Core+Strong Support 억제, boundary 억제 모두 development set에서
   봤던 방향 그대로 재현됐다. Strong Core Failure는 애초에 v0.2가
   풀려던 문제가 아니었고, 그대로 안 풀렸다(16절, 예상된 결과).

**종합**: Score 산식을 수정하지 않고 **Pattern A Score v0.2 Final
Freeze Confirmed**로 기록한다. v0.2가 설계 목표(Core/Supporting
상호작용, alignment FP, Pattern A/B 경계)에서 의도한 방향으로
개선됐다는 근거가 OOS2에서 재현됐다. 동시에 core=0 절대 붕괴라는
새 failure mechanism 1건을 v0.3 development evidence로 등록한다 —
이번 라운드에서는 수정하지 않는다.
