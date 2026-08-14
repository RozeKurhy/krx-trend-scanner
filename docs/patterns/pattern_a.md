# Pattern A: 장기 베이스 수렴형 (Long Term Base Convergence)

## 상태

**Feature Set Freeze v0.1 완료.** Feature Validation → Historical Snapshot →
Holdout → Negative Control → Outcome Audit → Base/Expansion Validation까지
검증한 결과를 바탕으로, Pattern A가 실제로 사용할 Feature와 그 역할/축을
이 문서에서 확정한다.

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
**Base/Expansion Validation(아래 절)으로 재검증한 최종 결과**, 이 축의
Context Role은 `range_36m` / `avg_price_change_12m` / `ma_spread` 셋만
남는다 — `range_24m`/`range_12m`은 검증 결과에 따라 Diagnostic으로
내려갔다(사유는 아래 Base/Expansion Validation 절 참고).

```text
range_36m               -> 장기(36개월) 가격 변동폭 자체 (Base Context)
avg_price_change_12m    -> 최근 12개월 가격 중심 이동량 (Base Context)
ma_spread                -> 이동평균선 간격(확장 정도)  (Base Context)

range_24m / range_12m    -> range_36m과 중복이거나 분리력이 약함 (Diagnostic으로 하향)
```

**핵심 질문에 대한 답**: SK하이닉스처럼 이미 크게 상승한 종목을 Base로
오인하지 않으려면, compression_ratio(12M/36M range 비율) 같은 "압축 정도"
보다 range_36m·avg_price_change_12m·ma_spread 같은 **"확장 정도" 자체를
직접 보는 게 더 유용하다** — compression_ratio는 비율이라 "36개월 range
자체가 이미 매우 컸던" 경우를 걸러내지 못하지만, range_36m은 그 확장을
직접 드러낸다. Base/Expansion Validation에서 range_36m은 holdout
trend_progressed 최솟값(1.2614)이 pre_breakout/early_trend/
confirmed_negative 세 그룹의 최댓값(1.1767)보다 커서 **trend_progressed
그룹을 나머지 세 그룹에서 완전히 분리했다**(pre/early/confirmed_negative
세 그룹끼리는 겹친다 — "4그룹을 전부 서로 분류할 수 있다"는 뜻은 아니다)
— 지금까지 검증한 Feature 중 가장 깨끗한 Already Progressed 판별 신호다.
다만 이번 단계에서 threshold는 정하지 않는다.

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

## Feature Role / Axis

`src/trend_scanner/patterns/pattern_a_feature_set.py`에 상수로 고정돼
있다. Score 계산과는 아직 연결하지 않는다.

**재리뷰 후속으로 Role과 Axis를 분리했다.** Role은 "Score Design에서 이
Feature를 어떻게 쓸 것인가"(핵심/보조/참고/진단용/미사용), Axis는
"Pattern A의 어느 축 개념에 속하는가"(Base/Transition/Stage)를 답한다.
예를 들어 `ma_spread`는 Core는 아니지만(Role=Context) Base Axis에
속한다 — 이전의 5분류(Role만 있던 구조)로는 이 관계를 표현할 수 없었다.
Diagnostic/Drop Feature에는 Axis를 부여하지 않는다(Score Design에 실제
쓰이는 축 구조에만 매핑, 과도한 프레임워크 방지).

| Role | 정의 | Axis | Feature |
|---|---|---|---|
| **Core** | Pattern A 판단의 중심 | Transition | `ma24_slope` |
| **Supporting** | Core 신호를 보강하지만 단독으로 결정하지 않음(transition confirmation 포함) | Transition | `weekly_ma12_slope`, `ma24_slope_acceleration` |
| **Context** | 좋고 나쁨이 아니라 "이미 얼마나 진행됐는가"(폭/변화율) 판별용 | Base | `range_36m`, `avg_price_change_12m`, `ma_spread` |
| **Context** | 좋고 나쁨이 아니라 "지금 어느 단계인가"(range 내 위치) 판별용 | Stage | `range_position`, `range_position_52w`, `distance_to_resistance` |
| **Diagnostic only** | 리포트엔 남기지만 Score에 직접 넣지 않음 | — | `ma_spread_ratio`, `atr_ratio`, `compression_ratio`, `range_24m`, `range_12m` |
| **Drop** | v0.1에서 사용하지 않음 | — | `pivot_low_slope` |

Base Context와 Stage Context를 같은 축에 두지 않은 이유: 둘 다 "참고
정보"라는 점은 같지만 단위가 다르다 — Base Context는 폭/변화율(스칼라
크기), Stage Context는 range 내 위치(0~1 정규화)다. 코드에서도
`BASE_CONTEXT_FEATURES`/`STAGE_CONTEXT_FEATURES`로 분리했다.

`PATTERN_A_FEATURE_SCOPE`(15개)가 Pattern A 후보로 명시적으로 검토한
Feature 전체를 나열한 ground truth다. `FeatureRow`의 나머지 필드(ma6/
ma12/ma24 원시 레벨, volume/trading_value 참고 지표, pivot 상세 등)는
애초에 Pattern A 후보로 논의된 적이 없어 여기 포함하지 않는다.

## Validation Evidence

| Feature | 원래 가설 | 관찰 결과 | v0.1 역할 | 확신도 |
|---|---|---|---|---|
| `ma24_slope` | 장기 추세 전환 포착 | early_trend에서 양전환이 가장 일관적(holdout 5/5, 100%). negative_control에서 양수 비율 낮음(confirmed 40%, ambiguous 0%, 합쳐서 25%) | Core | High |
| `weekly_ma12_slope` | 월봉보다 먼저 도는 선행 신호 | winner에서 monthly보다 먼저 양전환하는 사례 확인(9종목 중 6종목). 하지만 negative_control에서도 단독 양수가 흔함(confirmed 80%, ambiguous 66.7%) | Supporting(ma24와 결합 시에만 유의미) | Medium |
| `ma24_slope_acceleration` | 추세 전환 가속 신호 | early_trend에서 양수 많음(80%)이나 negative_control도 비슷하게 흔함(confirmed 80%, ambiguous 66.7%) — 단독 구분력 거의 없음. ma24_slope와 결합(Combination D/E)했을 때만 구분력 확인 | Supporting | Medium |
| Combination E(`weekly>0 & ma24>0 & accel>0`) | 세 신호의 동시 정렬이 강한 신호 | early_trend 80% vs confirmed_negative 20%, ambiguous_negative 0% — 지금까지 중 최고 구분력. 표본 작음(각 3~5개) | 개념만 정의(`transition_alignment`), Hard Filter/threshold 미확정 | Medium(표본 작음) |
| `range_position` | 장기 Range 내 위치로 돌파 임박 판단 | pre_breakout 단계 구분엔 약함(unbiased 중앙값이 negative와 사실상 동일: 0.4154 vs 0.4124). early_trend 확인에는 유용(중앙값 0.885) | Context(Stage) | Medium(stage 확인용으로 한정) |
| `range_position_52w` | 주봉 기준 range_position | range_position과 같은 패턴(단계 확인용, pre_breakout 판별력 약함) | Context(Stage) | Medium |
| `distance_to_resistance` | 저항까지 거리 | range_position과 상보적인 값, 별도 독립 검증은 약함 | Context(Stage) | Low |
| `compression_ratio` | 장기 Base 압축(12M/36M range 비율 낮음) | pre_breakout의 공통 특성으로 재현 안 됨(holdout 5종목 중 0.6 미만 없는 라운드도 있었음). negative_control 중앙값(0.60)이 오히려 positive pre(0.86)보다 낮음 — 방향이 반대로 나타난 사례도 있음 | Diagnostic | Low |
| `atr_ratio` | 돌파 전 변동성 축소 | holdout pre_breakout 최소값이 1.03(압축된 사례가 사실상 없음). negative_control과 분포가 크게 겹침 | Diagnostic | Low |
| `pivot_low_slope` | 저점 상승 구조 | exploration/holdout/negative_control 전부 값이 ±0.001 내외로 미미, 상태 구분력 없음 | Drop | Low |
| `ma_spread` | MA 수렴 정도("좁을수록 Base") | "수렴" 방향으로는 약함(pre_breakout 중앙값 0.0774이 early_trend 0.0627보다 오히려 높아 비단조). "확장" 방향은 중앙값이 progressed(0.2777)에서 가장 높아 방향성은 있으나, confirmed_negative 1건(롯데케미칼 0.2626)이 progressed 최솟값(0.1828)보다 커서 노이즈가 큼 | Context(Base, Already Progressed 판별에 참고, Score에는 직접 안 넣음) | Low-Medium |
| `ma_spread_ratio` | 과거 대비 수렴 진행도 | 편차가 극단적으로 큼(pre_breakout 0.62~6.57), 방향 불안정 | Diagnostic | Low |
| `range_36m` | Base/Expansion 판별(장기 변동폭) | Base/Expansion Validation(아래 절)에서 trend_progressed 그룹을 나머지 세 그룹(holdout pre/early, confirmed_negative)에서 완전히 분리(progressed 최솟값 1.2614 > 나머지 최댓값 1.1767). pre/early/confirmed_negative 세 그룹끼리는 겹친다 — 지금까지 가장 깨끗한 Already Progressed 신호 | Context(Base) | High |
| `avg_price_change_12m` | Base/Expansion 판별(12개월 가격 이동량) | 중앙값 차이는 매우 큼(progressed 0.7251 vs 나머지 -0.12~0.05)이나 confirmed_negative 1건(고려아연 0.3117)이 progressed 최솟값(0.2220)보다 커서 완전히 깨끗하진 않음 | Context(Base) | Medium |
| `range_24m` | (신규 후보) Base/Expansion 판별 | range_36m과 순위가 사실상 동일(인접 종목 1쌍만 뒤바뀜)하고 분리력도 비슷함 — range_36m과 정보 중복 | Diagnostic(range_36m과 중복) | Low |
| `range_12m` | (신규 후보) Base/Expansion 판별 | range 계열 중 유일하게 4그룹 분리 실패(progressed 최솟값 0.9097 < confirmed_negative 최댓값 1.0693) | Diagnostic(분리력 부족) | Low |

## Base / Expansion Validation

Feature Set Freeze v0.1 재리뷰 후속. compression_ratio를 대체한
range_36m/range_24m/range_12m/avg_price_change_12m/ma_spread가 "아직
Base/Transition 상태인 종목"과 "이미 상승이 상당히 진행된 종목"을 실제로
구분하는지 검증한다. 성공/실패 예측이 목적이 아니다 — 새 데이터 인프라나
KRX fetch 없이 기존 historical_snapshot 캐시(holdout 5종목, negative_control
8종목)를 재사용했다(`scripts/base_expansion_validate.py`).

**비교 그룹(4개)**: `holdout_pre_breakout`, `holdout_early_trend`,
`holdout_trend_progressed`(전부 completed monthly+weekly 기준), `confirmed_negative`
(negative_control 8종목 중 12개월 outcome이 "실패"와 잘 맞는 5종목 —
negative_control.md의 `NEGATIVE_SUBGROUP` 그대로 재사용, ambiguous_negative
3종목은 outcome이 견실하게 양수라 이번 비교에서 제외).

### 종목별 raw value

| ticker | name | group | range_36m | range_24m | range_12m | avg_price_change_12m | ma_spread |
|---|---|---|---|---|---|---|---|
| 005380 | 현대차 | holdout_pre_breakout | 0.7878 | 0.6553 | 0.6786 | -0.0891 | 0.1719 |
| 051910 | LG화학 | holdout_pre_breakout | 0.6188 | 0.5593 | 0.5836 | -0.0801 | 0.0673 |
| 000270 | 기아 | holdout_pre_breakout | 0.7078 | 0.6845 | 0.6594 | 0.0793 | 0.1665 |
| 006400 | 삼성SDI | holdout_pre_breakout | 1.0087 | 0.7596 | 0.7030 | 0.0982 | 0.0774 |
| 012330 | 현대모비스 | holdout_pre_breakout | 0.3958 | 0.3203 | 0.3104 | 0.0506 | 0.0263 |
| 005380 | 현대차 | holdout_early_trend | 0.8959 | 0.9605 | 0.9898 | -0.0575 | 0.0471 |
| 051910 | LG화학 | holdout_early_trend | 0.8004 | 0.8202 | 0.8351 | -0.0352 | 0.0627 |
| 000270 | 기아 | holdout_early_trend | 0.7839 | 0.7475 | 0.7504 | -0.0077 | 0.0166 |
| 006400 | 삼성SDI | holdout_early_trend | 1.0175 | 0.8778 | 0.8121 | 0.1761 | 0.1482 |
| 012330 | 현대모비스 | holdout_early_trend | 0.4872 | 0.4349 | 0.4118 | 0.0636 | 0.0826 |
| 005380 | 현대차 | holdout_trend_progressed | 1.6362 | 1.5865 | 1.4424 | 0.2220 | 0.2358 |
| 051910 | LG화학 | holdout_trend_progressed | 1.9168 | 1.7752 | 1.3968 | 0.7430 | 0.3225 |
| 000270 | 기아 | holdout_trend_progressed | 1.7168 | 1.5337 | 1.0549 | 0.7251 | 0.3387 |
| 006400 | 삼성SDI | holdout_trend_progressed | 2.2071 | 1.9080 | 1.4778 | 0.8214 | 0.2777 |
| 012330 | 현대모비스 | holdout_trend_progressed | 1.2614 | 1.1693 | 0.9097 | 0.3890 | 0.1828 |
| 003550 | LG | confirmed_negative | 0.7227 | 0.7369 | 0.7498 | -0.0338 | 0.0606 |
| 010130 | 고려아연 | confirmed_negative | 0.8563 | 0.6866 | 0.4444 | 0.3117 | 0.1611 |
| 011170 | 롯데케미칼 | confirmed_negative | 1.0287 | 0.8982 | 0.4886 | -0.2761 | 0.2626 |
| 032830 | 삼성생명 | confirmed_negative | 1.1767 | 0.8628 | 0.9395 | -0.2037 | 0.1433 |
| 034730 | SK | confirmed_negative | 0.9335 | 1.0005 | 1.0693 | -0.1208 | 0.0747 |

### 그룹별 min / median / max

| feature | group | n | min | median | max |
|---|---|---|---|---|---|
| range_36m | holdout_pre_breakout | 5 | 0.3958 | 0.7078 | 1.0087 |
| range_36m | holdout_early_trend | 5 | 0.4872 | 0.8004 | 1.0175 |
| range_36m | holdout_trend_progressed | 5 | 1.2614 | 1.7168 | 2.2071 |
| range_36m | confirmed_negative | 5 | 0.7227 | 0.9335 | 1.1767 |
| range_24m | holdout_pre_breakout | 5 | 0.3203 | 0.6553 | 0.7596 |
| range_24m | holdout_early_trend | 5 | 0.4349 | 0.8202 | 0.9605 |
| range_24m | holdout_trend_progressed | 5 | 1.1693 | 1.5865 | 1.9080 |
| range_24m | confirmed_negative | 5 | 0.6866 | 0.8628 | 1.0005 |
| range_12m | holdout_pre_breakout | 5 | 0.3104 | 0.6594 | 0.7030 |
| range_12m | holdout_early_trend | 5 | 0.4118 | 0.8121 | 0.9898 |
| range_12m | holdout_trend_progressed | 5 | 0.9097 | 1.3968 | 1.4778 |
| range_12m | confirmed_negative | 5 | 0.4444 | 0.7498 | 1.0693 |
| avg_price_change_12m | holdout_pre_breakout | 5 | -0.0891 | 0.0506 | 0.0982 |
| avg_price_change_12m | holdout_early_trend | 5 | -0.0575 | -0.0077 | 0.1761 |
| avg_price_change_12m | holdout_trend_progressed | 5 | 0.2220 | 0.7251 | 0.8214 |
| avg_price_change_12m | confirmed_negative | 5 | -0.2761 | -0.1208 | 0.3117 |
| ma_spread | holdout_pre_breakout | 5 | 0.0263 | 0.0774 | 0.1719 |
| ma_spread | holdout_early_trend | 5 | 0.0166 | 0.0627 | 0.1482 |
| ma_spread | holdout_trend_progressed | 5 | 0.1828 | 0.2777 | 0.3387 |
| ma_spread | confirmed_negative | 5 | 0.0606 | 0.1433 | 0.2626 |

### Feature별 분석

**`range_36m`** — **trend_progressed 그룹을 나머지 세 그룹에서 완전히
분리**(progressed 최솟값 1.2614 > 나머지 세 그룹 최댓값 1.1767). 정확히는
"이미 진행된 종목만 골라낸다"는 뜻이지 pre/early/confirmed_negative
세 그룹까지 서로 분류한다는 뜻은 아니다 — 그 셋끼리는 값이 겹친다.
trend_progressed에서 일관되게 커지는가? **예, 가장 명확하다.**

**`range_24m`** — range_36m과 같은 방식으로 **trend_progressed 그룹만
나머지 세 그룹에서 분리**한다(progressed 최솟값 1.1693 > 나머지 최댓값
confirmed_negative 1.0005). 종목별 순위도 range_36m과 사실상 동일하다
(trend_progressed 그룹에서 인접 종목 1쌍만 순서가 바뀜: 36m은
기아(1.7168)>현대차(1.6362), 24m은 현대차(1.5865)>기아(1.5337);
pre_breakout 그룹도 같은 패턴) — 사실상 같은 정보를 중복해서 담고 있다.

**`range_12m`** — range 계열 중 유일하게 분리에 실패한다.
trend_progressed 최솟값(0.9097)이 confirmed_negative 최댓값(1.0693)보다
낮다(034730 SK). 종목별 순위도 36m/24m와 다르게 흔들린다(trend_progressed
에서 기아·LG화학 순서가 뒤바뀜) — range_36m 대비 "추가 정보"가 아니라
노이즈가 늘어난 것에 가깝다.

**`avg_price_change_12m`** — 이미 상당히 상승한 종목에서 명확하게
커지는가? **대체로 예** — 중앙값 차이가 매우 크다(progressed 0.7251 vs
나머지 -0.12~0.05). 다만 완벽히 깨끗하진 않다: confirmed_negative
1건(고려아연 0.3117)이 progressed 최솟값(현대차 0.2220)보다 크다.

**`ma_spread`** — pre_breakout보다 progressed에서 실제로 넓어지는
패턴이 반복되는가? **방향은 있으나 노이즈가 크다.** 중앙값은
progressed(0.2777)에서 가장 높지만, pre_breakout(0.0774)이 early_trend
(0.0627)보다 오히려 높아 비단조적이고, confirmed_negative 1건(롯데케미칼
0.2626)이 progressed 최솟값(0.1828)보다 크다.

### range 계열 중복성 판단

`range_36m`/`range_24m`/`range_12m` 세 개를 모두 유지할 필요는 없다.
**대표 하나(range_36m)만 Base Context Role로 유지하고, range_24m/
range_12m은 Diagnostic으로 내린다.** 이유가 서로 다르다 — range_24m은
range_36m과 "중복"(순위가 사실상 동일)이라 내렸고, range_12m은
"분리력 부족"(range 계열 중 유일하게 4그룹 분리 실패)이라 내렸다. 둘 다
같은 Diagnostic Role이지만 신뢰도 함의는 다르다: range_24m은 range_36m을
쓰면 사실상 필요 없는 것이고, range_12m은 그 자체로 약한 신호다.

**참고**: 사용자가 예시로 제시한 "range_12m → Stage 해석용으로 이동"과는
다르게 판단했다. Stage Context Axis는 range_position류(0~1 정규화된
"위치") Feature로 구성되는데, range_12m은 위치가 아니라 폭(magnitude)
Feature라 Stage Axis에 넣으면 이번에 막 분리한 Axis 구분이 다시 흐려진다.
분리력이 약하다는 사실은 축을 바꿀 이유가 아니라 Role을 낮출 이유로
봤다. 다만 코드(`FEATURE_AXES`)는 Diagnostic/Drop Feature에 Axis를
부여하지 않으므로, 정확히는 "Base Axis를 유지"가 아니라 **"원래 Base
후보였지만 Diagnostic으로 강등되어 현재는 Axis가 없다"**가 코드와
일치하는 표현이다.

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
Core candidate (Axis=Transition)
    ma24_slope

Interaction candidate (Supporting, Axis=Transition, ma24와 결합 시 유의미)
    weekly_ma12_slope
    ma24_slope_acceleration

Base Context (Axis=Base, compression_ratio 대체, Base/Expansion Validation으로 확정)
    range_36m
    avg_price_change_12m
    ma_spread

Stage Context (Axis=Stage, breakout 단계 판별)
    range_position
    range_position_52w
    distance_to_resistance

Diagnostic (Score에 직접 안 넣음, 리포트엔 유지)
    compression_ratio
    atr_ratio
    ma_spread_ratio
    range_24m             # range_36m과 중복(Base/Expansion Validation)
    range_12m             # range 계열 중 분리력 부족(Base/Expansion Validation)

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
