# Pattern A: 장기 베이스 수렴형 (Long Term Base Convergence)

## 상태

**Feature Set Freeze v0.1 완료.** Feature Validation → Historical Snapshot →
Holdout → Negative Control → Outcome Audit까지 검증한 결과를 바탕으로,
Pattern A가 실제로 사용할 Feature와 그 역할을 이 문서에서 확정한다.

`evaluate_pattern_a`는 여전히 구현되지 않았다(`NotImplementedError`).
**점수, 가중치, threshold는 이 단계에서 정하지 않는다.** 아래 표에 남아있는
"초기 점수 후보"들은 전부 **검증 이전 가설**이며, 이번 Freeze로 유지/폐기
여부만 정리한다. 실제 배점은 다음 단계(Score Design)에서 결정한다.

## Pattern A 정의 (재확정)

Pattern A는 "MA가 상승 전환한 종목"을 찾는 패턴이 **아니다**. 정의는:

> 장기 베이스 또는 장기 정체 구간을 거친 뒤,
> 장기 추세가 상승 방향으로 전환되기 시작하는 종목

두 요소가 **모두** 필요하다.

```text
Base / Long-term structure   (장기 베이스가 있었는가)
+
Trend Transition             (그 베이스에서 상승 전환이 시작됐는가)
```

MA24 slope 하나가 양수라고 Pattern A가 아니다 — SK하이닉스처럼 이미 크게
상승한 종목의 MA24 slope도 상승 국면에서는 당연히 양수다. Base 요소 없이
Transition 요소만 보면 이미 많이 진행된 종목(Already Progressed)까지
잡아낸다. 이게 v0.1 검증에서 반복 확인된 핵심 실패 모드다(아래 참고).

기존 Base 정의(`compression_ratio < 0.6` 등)는 실제 데이터에서 재현되지
않았다. 이번 Freeze에서는 "장기 베이스"를 compression_ratio 하나로 정의
하지 않고, Base/Expansion Context 축(아래)에서 raw range/변화율 Feature
조합으로 다시 정의한다.

## 축 구조 (재설계)

기존 5개 영역(Base Quality/Low Structure/MA Transition/Volatility
Compression/Breakout Position, 각 25/20/25/15/15점)은 **초기 가설로
폐기**한다(아래 "폐기된 기존 가설" 참고). 대신 검증 결과를 반영해 최소
3개 축으로 재구성한다.

```text
Axis 1. Long-Term Structure / Base Context
        -> 이 종목이 아직 장기 구조 안에 있는가, 이미 너무 많이 갔는가

Axis 2. Trend Transition
        -> 장기 추세가 상승 쪽으로 전환되기 시작했는가

Axis 3. Stage / Breakout Context
        -> 지금 어느 단계인가(참고 정보, "좋고 나쁨" 점수가 아님)
```

세 축 사이의 가중치나 결합 방식은 이번 단계에서 정하지 않는다. Feature를
축에 배치하는 것까지만 한다.

### Axis 1: Long-Term Structure / Base Context

`compression_ratio` 하나로 Base를 정의하지 않는다. 검증 결과
compression_ratio는 실제 pre_breakout 사례들의 공통 특성으로 재현되지
않았고(holdout 5종목 중 낮은 값이 하나도 없었던 라운드도 있었음), 오히려
negative_control에서 더 낮게 나온 사례도 있었다.

대신 다음 raw Feature 조합으로 "아직 장기 구조 안에 있는가"를 판단한다.

```text
range_36m / range_24m / range_12m   -> 장기~중기 가격 변동폭 자체
avg_price_change_12m                -> 최근 12개월 가격 중심 이동량
ma_spread                           -> 이동평균선 간격(확장 정도)
```

**핵심 질문에 대한 답**: SK하이닉스처럼 이미 크게 상승한 종목을 Base로
오인하지 않으려면, compression_ratio(12M/36M range 비율) 같은 "압축 정도"
보다 range_36m·avg_price_change_12m·ma_spread 같은 **"확장 정도" 자체를
직접 보는 게 더 유용해 보인다** — compression_ratio는 비율이라 "36개월
range 자체가 이미 매우 컸던" 경우를 걸러내지 못하지만, range_36m은 그
확장을 직접 드러낸다. 다만 이번 단계에서 threshold는 정하지 않는다.

### Already Progressed / Expansion State

"좋은 상승 추세"라고 무조건 높게 평가하면 안 된다 — 이미 너무 진행된
종목은 Pattern A의 목표가 아니다. 다음 Feature들을 **Already Progressed
판별 후보**로 명시한다(threshold는 정하지 않음, 어떤 Feature를 쓸지만
확정).

```text
ma24_slope가 지나치게 큼
ma_spread가 큼
range_36m가 큼
avg_price_change_12m가 매우 큼
range_position이 매우 높음
```

Trend Transition 신호(ma24_slope 양전환 등)와 Base/Expansion Context
신호(range_36m, ma_spread 등)를 **함께** 봐야 이미 진행된 종목을 걸러낼
수 있다 — 이게 Proxy 테스트에서 확인된 원래 문제(아래 "Proxy 테스트에서
확인한 문제" 참고)의 정식 해결 방향이다.

### Axis 2: Trend Transition

현재 가장 근거가 강한 축이다. 세 Feature가 서로 다른 역할을 한다.

```text
ma24_slope                 -> 장기 추세 방향 (Core)
ma24_slope_acceleration    -> 장기 추세 개선 속도 / early trend 확인 (Supporting)
weekly_ma12_slope          -> 월봉보다 빠른 단기 확인 (Supporting)
```

**`ma24_slope`만 Core다.** `weekly_ma12_slope`와 `ma24_slope_acceleration`은
단독으로는 Pattern A를 결정하지 않는다 — 둘 다 negative_control에서도
단독 양수가 흔했다(아래 Validation Evidence 표). `ma24_slope`와 결합됐을
때만(Combination D/E) early_trend와 negative를 잘 구분했다.

세 값의 상호작용을 개념으로만 정의한다(점수/Hard Condition으로 아직
구현하지 않음).

```text
transition_alignment (개념, 미구현):
    weekly_ma12_slope > 0
    AND ma24_slope > 0
    AND ma24_slope_acceleration > 0
```

검증에서 이 조합(Combination E)이 holdout early_trend(80%)와
negative_control(confirmed 20%, ambiguous 0%)을 가장 잘 구분했다. 표본이
작아서(각 그룹 3~5개) threshold나 Hard Filter로 확정하지 않는다.

### Axis 3: Stage / Breakout Context

"좋고 나쁨"이 아니라 **지금 어느 단계인지** 해석하는 참고 축이다.

```text
range_position
range_position_52w
distance_to_resistance
```

```text
낮은 range_position       -> 아직 박스 하단 / 초기 가능성
중간 range_position       -> 구조 내부
높은 range_position       -> breakout 접근 또는 early trend
매우 높음 + MA 확장 강함  -> already progressed 가능성
```

검증 결과 range_position은 pre_breakout 성공/실패 구분에는 약했다(9종목
unbiased pre_breakout 중앙값 0.4154 vs negative_control 중앙값 0.4124 —
거의 동일). 반면 early_trend 단계에서는 뚜렷하게 높았다(중앙값 0.885).
**즉 "돌파 전 판별"이 아니라 "돌파 후 확인/단계 판별" 용도로 유용하다.**
이번 단계에서 threshold는 정하지 않는다.

## Feature Role (5분류)

`src/trend_scanner/patterns/pattern_a_feature_set.py`에 상수로 고정돼
있다. Score 계산과는 아직 연결하지 않는다.

| Role | 정의 | Feature |
|---|---|---|
| **Core** | Pattern A 판단의 중심 | `ma24_slope` |
| **Supporting** | Core 신호를 보강하지만 단독으로 결정하지 않음(transition confirmation 포함) | `weekly_ma12_slope`, `ma24_slope_acceleration` |
| **Stage / Context** | 좋고 나쁨이 아니라 현재 단계·Base/Expansion 판별용 | `range_position`, `range_position_52w`, `distance_to_resistance`, `range_36m`, `range_24m`, `range_12m`, `avg_price_change_12m`, `ma_spread` |
| **Diagnostic only** | 리포트엔 남기지만 Score에 직접 넣지 않음 | `ma_spread_ratio`, `atr_ratio`, `compression_ratio` |
| **Drop** | v0.1에서 사용하지 않음 | `pivot_low_slope` |

이 목록은 지금까지 명시적으로 검증한 Feature만 다룬다. `FeatureRow`의
나머지 필드(ma6/ma12/ma24 원시 레벨, volume/trading_value 참고 지표,
pivot 상세 등)는 애초에 Pattern A 후보로 논의된 적이 없어 role 분류
대상이 아니다.

## Validation Evidence

| Feature | 원래 가설 | 관찰 결과 | v0.1 역할 | 확신도 |
|---|---|---|---|---|
| `ma24_slope` | 장기 추세 전환 포착 | early_trend에서 양전환이 가장 일관적(holdout 5/5, 100%). negative_control에서 양수 비율 낮음(confirmed 40%, ambiguous 0%, 합쳐서 25%) | Core | High |
| `weekly_ma12_slope` | 월봉보다 먼저 도는 선행 신호 | winner에서 monthly보다 먼저 양전환하는 사례 확인(9종목 중 6종목). 하지만 negative_control에서도 단독 양수가 흔함(confirmed 80%, ambiguous 66.7%) | Supporting(ma24와 결합 시에만 유의미) | Medium |
| `ma24_slope_acceleration` | 추세 전환 가속 신호 | early_trend에서 양수 많음(80%)이나 negative_control도 비슷하게 흔함(confirmed 80%, ambiguous 66.7%) — 단독 구분력 거의 없음. ma24_slope와 결합(Combination D/E)했을 때만 구분력 확인 | Supporting | Medium |
| Combination E(`weekly>0 & ma24>0 & accel>0`) | 세 신호의 동시 정렬이 강한 신호 | early_trend 80% vs confirmed_negative 20%, ambiguous_negative 0% — 지금까지 중 최고 구분력. 표본 작음(각 3~5개) | 개념만 정의(`transition_alignment`), Hard Filter/threshold 미확정 | Medium(표본 작음) |
| `range_position` | 장기 Range 내 위치로 돌파 임박 판단 | pre_breakout 단계 구분엔 약함(unbiased 중앙값이 negative와 사실상 동일: 0.4154 vs 0.4124). early_trend 확인에는 유용(중앙값 0.885) | Stage/Context | Medium(stage 확인용으로 한정) |
| `range_position_52w` | 주봉 기준 range_position | range_position과 같은 패턴(단계 확인용, pre_breakout 판별력 약함) | Stage/Context | Medium |
| `distance_to_resistance` | 저항까지 거리 | range_position과 상보적인 값, 별도 독립 검증은 약함 | Stage/Context | Low |
| `compression_ratio` | 장기 Base 압축(12M/36M range 비율 낮음) | pre_breakout의 공통 특성으로 재현 안 됨(holdout 5종목 중 0.6 미만 없는 라운드도 있었음). negative_control 중앙값(0.60)이 오히려 positive pre(0.86)보다 낮음 — 방향이 반대로 나타난 사례도 있음 | Diagnostic | Low |
| `atr_ratio` | 돌파 전 변동성 축소 | holdout pre_breakout 최소값이 1.03(압축된 사례가 사실상 없음). negative_control과 분포가 크게 겹침 | Diagnostic | Low |
| `pivot_low_slope` | 저점 상승 구조 | exploration/holdout/negative_control 전부 값이 ±0.001 내외로 미미, 상태 구분력 없음 | Drop | Low |
| `ma_spread` | MA 수렴 정도("좁을수록 Base") | "수렴" 방향으로는 값 범위가 그룹 간 크게 겹쳐 약함(pre_breakout 4~9종목 기준 0.026~0.29로 편차 큼). 다만 "확장" 방향으로는 참고가 된다 — negative_control 중앙값(0.122)이 positive pre_breakout 중앙값(0.077)보다 넓고, trend_progressed 단계는 0.22~0.34로 더 넓다 | Stage/Context(Already Progressed 판별에 참고, Score에는 직접 안 넣음) | Low |
| `ma_spread_ratio` | 과거 대비 수렴 진행도 | 편차가 극단적으로 큼(pre_breakout 0.62~6.57), 방향 불안정 | Diagnostic | Low |
| `range_36m`, `avg_price_change_12m` | (신규 후보) Base/Expansion 판별 | 아직 독립적인 hypothesis test는 안 했지만, compression_ratio의 대안으로 이 Freeze에서 채택 | Stage/Context(Base/Expansion) | 미검증(다음 라운드 후보) |

## Hard Filter 재분류

이번 단계에서 Hard Filter를 실제로 적용하지 않는다. 기존 후보를
재검토만 한다.

| 후보 | 분류 |
|---|---|
| `range_position < 0.45` reject | **폐기**. unbiased holdout pre_breakout 5종목 중 4종목이 0.45 근처거나 미만이었다 — 실제 pre_breakout 사례 대부분을 걸러내는 조건이었다. |
| `ma24_slope_6m < -0.08` reject(강한 하락 중 제외) | **판단 유보**. 방향은 합리적이나(강하게 하락 중인 종목은 Transition이 아직 시작 안 됨) 정확한 임계값을 검증하지 않았다. 참고: 현재 `FeatureRow.ma24_slope`는 3개월 기준으로만 계산되고 6개월 변형은 존재하지 않는다 — 이 후보를 유지하려면 6m slope 산식부터 새로 정의해야 한다. |
| 최근 주요 저점 붕괴 | **판단 유보**. `pivot_low_slope` 자체는 Drop됐지만, "저점 붕괴 여부"라는 개념은 아직 다른 Feature 조합으로 재정의해볼 여지가 있다. |
| 유동성 부족 | **판단 유보**. 이번 검증 대상 전부 대형주라 검증하지 않았다.

## Stage 개념 (enum, 자동 분류 미구현)

```text
BASE          장기 횡보/정체, Transition 신호 아직 없음
TRANSITION    Trend Transition 신호가 막 나타나기 시작(pre_breakout에 대응)
EARLY_TREND   장기 추세 전환이 확인됨, 아직 크게 확장되지 않음
PROGRESSED    MA 확장, 장기 상승이 명확히 진행됨(Already Progressed 포함)
WEAK          하락 추세 또는 실패한 전환(negative_control에 대응)
```

`src/trend_scanner/patterns/pattern_a_feature_set.py`의 `PatternAStage`
enum으로 이름만 정의돼 있다. 자동 분류 threshold는 이번 단계에서
구현하지 않는다. 지금까지의 검증 라벨(pre_breakout/early_trend/
trend_progressed/unfavorable, failed_*)과 대략 대응하지만 1:1은 아니다.

## Pattern A v0.1 출력 구조 (초안, 미구현)

향후 `evaluate_pattern_a`가 반환할 정보의 초안이다. **이번 단계에서
`total_score` 계산은 구현하지 않는다** — 아래는 문서상 구조 정의일 뿐,
코드에 새 dataclass로 옮기지 않았다(기존 `PatternAResult`는 그대로 두되
5영역 가중치 구조가 폐기 대상임을 주석으로 표시했다).

```text
PatternAResult (v0.2 초안, 미구현)
  stage: PatternAStage

  rejected: bool
  rejection_reasons: tuple[str, ...]

  flags: dict[str, bool]         # 예: transition_alignment, already_progressed 후보 등
                                  # (threshold 미확정이라 실제 계산은 없음)

  total_score: float | None      # 이번 단계에서 미구현, 항상 None
  component_scores: dict | None  # 이번 단계에서 미구현, 항상 None

  feature_snapshot: FeatureRow   # 기존 Feature Validation의 FeatureRow 그대로 재사용
```

## 다음 Score Design 단계에서 사용할 Feature (최종 목록)

```text
Core candidate
    ma24_slope

Interaction candidate (Supporting, ma24와 결합 시 유의미)
    weekly_ma12_slope
    ma24_slope_acceleration

Base / Expansion Context (Stage/Context 축, compression_ratio 대체)
    range_36m
    range_24m
    range_12m
    avg_price_change_12m
    ma_spread                    # 절대값. "확장 정도" 서술에 참고

Stage Context (breakout 단계 판별)
    range_position
    range_position_52w
    distance_to_resistance

Diagnostic (Score에 직접 안 넣음, 리포트엔 유지)
    compression_ratio
    atr_ratio
    ma_spread_ratio

Drop
    pivot_low_slope
```

실제 가중치·threshold·Hard Filter는 다음 단계(Pattern A v0.1 Score
Design)에서 결정한다.

## 폐기된 기존 가설

* **5영역 100점 배점(Base Quality 25 / Low Structure 20 / MA Transition
  25 / Volatility Compression 15 / Breakout Position 15)**: 초기
  가설이었을 뿐 검증되지 않았다. `pattern_a.py`의 `PATTERN_A_WEIGHTS`는
  코드에 남아있지만(기존 테스트가 참조 중) **이 구조를 최종 배점으로
  쓰지 않는다** — 다음 Score Design 단계에서 위 축 구조를 기준으로
  다시 설계한다.
* **`compression_ratio < 0.6` 가산점**: pre_breakout 공통 특성으로
  재현되지 않았고, 방향이 반대로 나타난 사례도 있어 대폭 약화(Diagnostic
  으로 강등).
* **Volatility Compression 15점(ATR 감소 등)**: unbiased positive
  pre_breakout에서 변동성 압축이 관찰되지 않았다(atr_ratio 최소값
  1.03). 이 영역 구조를 유지할 근거가 약하다.
* **`range_position < 0.45` reject**: 위 Hard Filter 표 참고, 폐기.
* **Low Structure(저점 상승) 단독 평가**: Proxy 테스트에서 이미 확인된
  문제 — 이미 상승 중인 종목도 저점이 상승하므로, `pivot_low_slope`
  Drop과 별개로 "저점 상승"이라는 개념 자체를 단독 점수 요소로 쓰지
  않는다.

## Score Momentum (다음 단계 계획, 미변경)

매주 또는 매일 Pattern Score를 저장한다(`models/score.py`). 목표는
이미 완성된 강한 상승주보다 점수가 빠르게 개선되고 있는 초기 후보를
찾는 것이다. `total_score`가 아직 없으므로 이번 단계에서는 구현하지
않는다 — Score Design이 끝난 뒤 그대로 적용 가능한 개념으로 남겨둔다.

```python
score_momentum_4w = current_score - score_4w_ago
```

## Proxy 테스트에서 확인한 문제 (기존 기록, 유지)

임시 월별 종가 데이터로 셀트리온, NAVER, 삼성전자, SK하이닉스 등을
테스트했을 때, SK하이닉스처럼 이미 대세 상승이 상당히 진행된 종목도
"저점 상승 + MA 상승" 조건만 보면 높은 점수를 받을 수 있음을 확인했다.
이 문제는 이번 Freeze의 "Already Progressed / Expansion State" 절로
정식 반영됐다 — Trend Transition 신호와 Base/Expansion Context 신호를
함께 봐야 한다.
