# Pattern A: 장기 베이스 수렴형 (Long Term Base Convergence)

## 상태

**Feature Set Freeze v0.1 완료 + Score Design v0.1 완료 + OOS Case
Validation v0.1 완료 + v0.2 설계 준비 완료.** Feature Validation →
Historical Snapshot → Holdout → Negative Control → Outcome Audit →
Base/Expansion Validation까지 검증한 결과로 Feature Set을
확정했고(Freeze), 그 위에 `pattern_a_score.py`(`score_pattern_a`,
`PatternAResult`)로 실제 Score 산식을 구현하고 기존 validation snapshot에
적용해 분포를 검증했다(Score Design). 자세한 산식/근거/검증 결과는 아래
"Score Design v0.1" 절 참고.

**Score는 커밋 `6e7cc95`(range_36m required anchor 반영)에서 freeze됐다.**
그 이후 "OOS Case Validation v0.1"(아래 절, 정식 명칭 — 시장 전체의
unbiased 성능 검증이 아니다, 아래 caveat 참고)은 완전히 새로운 종목/
날짜에 그 Score를 그대로 적용만 했다 — weight/threshold/bonus/penalty를
전혀 수정하지 않았다. holdout/negative_control은 Score 설계에 이미
쓰여서 더 이상 out-of-sample이 아니다. **Score v0.1의 최종 결론은
"architecture는 baseline으로 유지, performance validation은 미완료"다**
(자세한 근거는 "Score v0.1 상태: architecture 유지 vs performance
validation" 절 참고) — 아직 최종 Score로 freeze 완료된 상태는 아니다.

`pattern_a.py`의 `evaluate_pattern_a`(raw daily OHLCV 입력)는 여전히
구현되지 않았다 — `score_pattern_a`는 FeatureRow를 입력받는 순수 함수이고,
daily OHLCV -> 월봉/주봉 -> FeatureRow 조립 경로는 실제 스캐너 진입점을
만드는 작업이라 스코프 밖이다(전체 시장 스캔 금지와 맞물린 경계). **미래
수익률 기반 최적화, grid search, 그룹 분리 최대화, 전체 KOSPI/KOSDAQ
스캔, 백테스트는 이번 Score Design에서도 하지 않았다.**

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
| `ma_spread` | MA 수렴 정도("좁을수록 Base") | "수렴" 방향으로는 약함(pre_breakout 중앙값 0.0774이 early_trend 0.0627보다 오히려 높아 비단조). "확장" 방향은 중앙값이 progressed(0.2777)에서 가장 높아 방향성은 있으나, confirmed_negative 1건(롯데케미칼 0.2626)이 progressed 최솟값(0.1828)보다 커서 노이즈가 큼 | Context(Base). Score Design v0.1에서 Base Score의 15%로 실제 반영됨(단독 분리력이 약해 세 Base Feature 중 가장 작은 비중) | Low-Medium |
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

## Stage 개념 (enum, 초안 분류 구현됨)

```text
BASE          장기 횡보/정체, Transition 신호 아직 없음
TRANSITION    Trend Transition 신호가 막 나타나기 시작(pre_breakout에 대응)
EARLY_TREND   장기 추세 전환이 확인됨, 아직 크게 확장되지 않음
PROGRESSED    MA 확장, 장기 상승이 명확히 진행됨(Already Progressed 포함)
WEAK          하락 추세 또는 실패한 전환(negative_control에 대응)
```

`src/trend_scanner/patterns/pattern_a_feature_set.py`의 `PatternAStage`
enum. **Score Design v0.1에서 자동 분류 threshold를 초안으로 구현했다**
(`pattern_a_score._classify_stage`, 아래 "Score Design v0.1" 절의 "Stage
분류 초안" 참고 — 알려진 오분류 사례 1건 포함). 지금까지의 검증 라벨
(pre_breakout/early_trend/trend_progressed/unfavorable, failed_*)과
대략 대응하지만 1:1은 아니다.

## Pattern A v0.1 출력 구조 (구현됨)

Score Design v0.1로 실제 구현했다. `src/trend_scanner/patterns/
pattern_a_score.py`의 `PatternAResult`(기존 5영역 구조를 완전히 대체 —
`pattern_a.py`에 있던 구 `PatternAResult`/`PATTERN_A_WEIGHTS`는 삭제)와
`score_pattern_a(features)`가 실제 코드다. 아래는 실제 필드와 값이 일치한다.

```text
PatternAResult (실제 구조, src/trend_scanner/patterns/pattern_a_score.py)
  base_score: float | None
  base_valid_features: tuple[str, ...]
  base_missing_features: tuple[str, ...]

  transition_score: float | None
  transition_valid_features: tuple[str, ...]
  transition_missing_features: tuple[str, ...]

  balanced_core_score: float | None   # harmonic_mean(base_score, transition_score)
  alignment_bonus: float              # 0.0 또는 ALIGNMENT_BONUS(8.0)
  progressed_penalty: float           # progressed_evidence_count에 따른 penalty
  progressed_evidence_count: int      # 0~5

  pattern_a_score: float | None       # clip(balanced_core + bonus - penalty, 0, 100)
                                       # insufficient_data=True면 항상 None

  stage: PatternAStage | None         # insufficient_data=True면 항상 None(초안 heuristic)

  flags: dict[str, bool]              # transition_alignment / already_progressed / insufficient_data

  feature_snapshot: FeatureRow | None
```

산식/근거는 아래 "Score Design v0.1" 절 참고.

## Score Design v0.1 입력 Feature (Feature Set Freeze 확정 목록)

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

실제 가중치·soft threshold는 Score Design v0.1(아래 절)에서 확정했다.
Hard Filter는 이번에도 최소화했다(`insufficient_data` 상태만 별도로 둠,
아래 "Already Progressed Penalty" 절 참고).

## 폐기된 기존 가설

* **5영역 100점 배점(Base Quality 25 / Low Structure 20 / MA Transition
  25 / Volatility Compression 15 / Breakout Position 15)**: 초기
  가설이었을 뿐 검증되지 않았다. `pattern_a.py`에 있던 `PATTERN_A_WEIGHTS`와
  구 `PatternAResult`는 Score Design v0.1로 완전히 **삭제**했다 —
  `pattern_a_score.py`의 새 3축 구조(Base Context/Trend Transition/Stage
  Context)로 대체됐다.
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

## Score Design v0.1

### 철학

Pattern A는 단순 "MA 상승 종목 점수"가 아니다. 정의(위 "Pattern A 정의"
절)대로 **Base / Long-Term Structure**와 **Trend Transition**이 둘 다
있어야 높은 점수를 받아야 하고, 이미 상승이 너무 많이 진행된 종목은
**Already Progressed Penalty**를 받아야 한다. 기본 구조:

```text
pattern_a_score = clip(
    harmonic_mean(base_score, transition_score)
    + transition_alignment_bonus
    - already_progressed_penalty,
    0, 100
)
```

Stage/Breakout Context(`range_position` 등)는 Score와 분리해 해석 정보로만
반환한다(아래 "Stage 분류" 절).

### 후보 Design 비교 (A / B / C)

Base 40% + Transition 60% 같은 **단순 가산식만 쓰면 안 된다** — Base가
거의 없어도 Transition만 강하면 고득점할 수 있어서, SK하이닉스처럼 이미
진행된 종목을 다시 높게 평가하는 문제가 재발한다. 이걸 실제 데이터로
확인하려고 세 안을 같은 component score(base_score/transition_score)에
적용해 비교했다(`scripts/score_design_validate.py`).

```text
Design A: 0.4 * base_score + 0.6 * transition_score               (단순 가산식)
Design B: harmonic_mean(base_score, transition_score)              (균형만, bonus/penalty 없음)
Design C: harmonic_mean(...) + alignment_bonus - progressed_penalty (채택안)
```

holdout_trend_progressed 그룹(5종목) 최종 점수 min/median/max:

| Design | min | median | max |
|---|---|---|---|
| A (가산식) | 47.73 | 62.45 | 77.50 |
| B (harmonic만) | 11.53 | 24.34 | 67.01 |
| C (채택안) | 0.00 | 0.00 | 56.07 |

Design A는 문제를 재현한다 — 006400(삼성SDI) trend_progressed는
base_score=6.11(거의 0)인데 transition_score=100이라 Design A 점수가
62.45로 나온다. 같은 종목의 holdout_early_trend Design A 점수(83.93)와
큰 차이가 안 난다 — "Base가 거의 없어도 Transition만 강하면 고득점"이
그대로 재현됐다.

Design B(harmonic mean만)는 이 문제를 크게 완화한다(median 24.34로 급락)
하지만 min~max 범위(11.53~67.01)가 early_trend 최저점(70.07)과 거의
붙는다 — 가장 나쁜 progressed 사례(67.01, 012330 현대모비스)가 여전히
early_trend 최저점 근처까지 올라온다.

Design C(harmonic + bonus - penalty)가 가장 깨끗하게 분리한다 —
trend_progressed 최댓값(56.07)이 early_trend 최솟값(70.07)보다 낮다.
그래서 **Design C를 채택**한다.

Base Feature 비중 후보도 하나 더 비교했다(item 5) — `range_36m` 비중을
55%/60%로 바꿔봤다(`avg_price_change_12m` 30%/25%, `ma_spread` 15% 고정).
holdout+confirmed_negative 20개 스냅샷 기준 두 후보 간 차이는 평균
0.81점, 최대 2.11점으로 미미했다 — Feature 방향성이 이미 강하게 일치해서
비중 조정의 영향이 작다. 검증 근거 강도 순서(range_36m High >
avg_price_change_12m Medium > ma_spread Low-Medium)를 그대로 반영한
**55% / 30% / 15%를 채택**한다(추가 튜닝 불필요).

### Base Score 산식

`BASE_WEIGHTS`(`pattern_a_score.py`): `range_36m` 55%, `avg_price_change_12m`
30%, `ma_spread` 15%. 각 Feature를 0~100 soft piecewise linear로 먼저
정규화한 뒤 가중합한다(결측 Feature는 가중치를 재정규화 — 아래 "Missing
Feature 정책" 참고).

Base Score의 의미는 "얼마나 압축돼 있는가"가 아니라 **"아직 장기적으로
과도하게 확장되지 않았는가"**다. 그래서 세 Feature 모두 값이 작거나
중간이면 높은 점수, 매우 크면 낮은 점수(단조 감소)로 설계했다.

| Feature | breakpoint(x, y) | 근거 |
|---|---|---|
| `range_36m` | (0.6, 100) → (1.2, 60) → (2.0, 0) | Base/Expansion Validation에서 trend_progressed 최솟값(1.2614)이 나머지 세 그룹 최댓값(1.1767)보다 컸다. 1.2는 그 관찰된 gap을 정밀 조준한 값이 아니라 근처의 **라운드 넘버**다 — 이 하나만으로 progressed를 가르지 않는다(Already Progressed Penalty는 이 값 포함 5개 신호가 동시에 나타나야 붙는다, 아래 참고). |
| `avg_price_change_12m` | (0.10, 100) → (0.30, 50) → (0.60, 0) | 낮거나 완만한 상승은 Base로 허용한다(early trend에서도 가격 중심이 오르는 건 정상). 절대 양수라는 이유만으로 감점하지 않는다 — 0.10까지는 만점. |
| `ma_spread` | (0.10, 100) → (0.25, 50) → (0.40, 0) | 단독 분리력이 약하고(Low-Medium 확신도) 노이즈가 크므로 완만한 보조 지표로만 쓴다. 좁다고 무조건 좋은 Base로 보지 않고, 매우 넓을 때만 확장 가능성을 보조 반영한다. |

### Transition Score 산식

`TRANSITION_WEIGHTS`: `ma24_slope` 60%, `weekly_ma12_slope` 20%,
`ma24_slope_acceleration` 20% — Core가 가장 큰 비중을 갖는다.

| Feature | breakpoint(x, y) | 근거 |
|---|---|---|
| `ma24_slope` | (-0.05, 0) → (0.00, 50) → (0.05, 90) → (0.15, 100) | Hard binary(양수=만점/음수=0점)로 만들지 않는다 — Pattern A는 "전환 중"도 찾고 싶다. 0에서 50을 준 이유: negative_control도 0 근처에 몰려 있어(003550 LG +0.0102, 032830 삼성생명 −0.0207) 0 근처는 "가능성은 있으나 미확인" 정도로만 취급한다. 완만한 양수(0.05)부터 90으로 빠르게 올라간다. **지나치게 큰 양수를 여기서 다시 깎지 않는다** — 과도한 상승은 Already Progressed Penalty가 별도로 담당한다(이중 역할 금지, item 11). |
| `weekly_ma12_slope` | (0.00, 20) → (0.15, 100) | 단독 양수가 negative_control에서도 흔했으므로(confirmed 80%, ambiguous 66.7%, Feature Set Freeze 참고) 큰 독립 점수를 주지 않는다 — 완만한 형태 + 작은 비중(20%)으로 이중 안전장치. |
| `ma24_slope_acceleration` | (0.00, 30) → (0.05, 100) | 단독 positive가 false positive에서도 많았으므로(negative_control confirmed 80%) Supporting만 담당한다. |

### harmonic mean / balance 구조

```python
balanced_core_score = harmonic_mean(base_score, transition_score)
# = 2 * base * transition / (base + transition), base+transition<=0이면 0.0
```

한쪽이 낮으면 전체가 크게 낮아진다(단순 평균이 아님) — 예:
`harmonic_mean(90, 90) = 90`, `harmonic_mean(90, 30) = 45`,
`harmonic_mean(30, 90) = 45`. 0 division은 `a+b<=0`일 때 0.0을 직접
반환해서 처리한다(base/transition은 설계상 음수가 나오지 않으므로 사실상
"둘 다 0"인 경우만 해당).

### transition_alignment 정의 및 bonus

```text
transition_alignment:
    weekly_ma12_slope > 0
    AND ma24_slope > 0
    AND ma24_slope_acceleration > 0
```

검증에서 가장 의미 있었던 interaction(Combination E, Feature Set
Freeze). Hard Filter가 아니라 **완전 충족 시에만** 소규모 bonus
(`ALIGNMENT_BONUS = 8.0`)를 준다 — 부분 충족은 bonus 없음. 결측 Feature가
하나라도 있으면 정렬 여부를 확인할 수 없으므로 False로 취급한다(미확인
== 정렬 안 됨).

### Already Progressed 판별 구조 / progressed penalty 산식

후보 Feature 5개 중 몇 개가 "이미 진행됨" 기준을 넘는지 세는 composite
evidence count로 설계했다(단일 Feature가 아니라 여러 신호 동시 발생만
반영 — 아래 "Double Penalty 방지" 참고).

| Feature | threshold | 비고 |
|---|---|---|
| `range_36m` | >= 1.2 | Base Score 곡선의 breakpoint를 재사용(관찰된 gap을 정밀 조준한 게 아니라 그 곡선을 "확장 신호로 셀 만큼 큰 값" 기준으로 재사용) |
| `avg_price_change_12m` | >= 0.30 | Base Score 곡선의 breakpoint 재사용 |
| `ma_spread` | >= 0.20 | Base Score 곡선의 breakpoint 재사용 |
| `ma24_slope` | >= 0.10 | Transition Score가 90~100에 도달하는 구간과 겹침 |
| `range_position` | >= 0.85 | Feature Set Freeze에서 early_trend 중앙값(0.885)과 근접한 라운드 넘버 |

```text
progressed_penalty by evidence_count:
    0개 -> 0
    1개 -> 0    (거의 없음)
    2개 -> 10   (작은 penalty)
    3개 -> 20   (의미 있는 penalty)
    4개 -> 28
    5개 -> 35   (최대, 0~40 권장 범위 안)
```

결측 Feature는 evidence로 세지 않는다(불확실 == 진행 증거 아님).

### Double Penalty 방지

`range_36m`/`avg_price_change_12m`/`ma_spread`는 이미 Base Score에
반영된다. 같은 값으로 Base Score를 낮추고 Progressed Penalty도 또
붙이면 double counting이다. 그래서 Progressed Penalty는:

* Base Score처럼 연속값을 다시 감점 계산에 쓰지 않고, **threshold를
  넘었는지 여부(boolean)만** 본다.
* **1개 신호만으로는 penalty가 붙지 않는다**(evidence_count=1 → 0). 여러
  신호(range_36m/avg_price_change_12m/ma_spread/ma24_slope/range_position)가
  **동시에** 강하게 나타날 때만 추가로 붙는다 — Base Score의 "장기 구조
  적합도" 하락과는 별개로, "여러 축이 한꺼번에 진행됨을 가리키는가"라는
  다른 질문에 답하는 것이다.

실제 데이터에서도 검증된다: holdout_pre_breakout/early_trend 15건은
evidence_count가 0~1(현대차 early_trend, 기아 early_trend 등은 range_position
만 0.85를 넘어 count=1 → penalty 0), confirmed_negative 5건은 0~1
(penalty 전부 0). trend_progressed만 2~5(penalty 10~35)로 몰려 있다.

### Missing Feature 정책

Feature가 NaN이어도 0점 처리하지 않는다("Base가 나쁘다"가 아니라 "Base
판정 불충분"). `ComponentScore`가 axis별로 `valid_features`/
`missing_features`를 추적한다 — 결측 Feature는 가중치에서 빼고 남은
Feature로 재정규화한다(예: `ma_spread`만 결측이면 `range_36m`/
`avg_price_change_12m` 비중을 55:30 → 64.7:35.3으로 재정규화).

Base Feature가 **전부** 결측이면 `base_score=None`.

**재리뷰 후속(Required Base Anchor)**: `range_36m`(Base/Expansion
Validation에서 가장 강한 High 확신도 Base Feature)과 `ma24_slope`(Core
Transition Feature)는 required anchor다 — 둘 중 **하나라도** 결측이면
무조건 `insufficient_data=True`다. 나머지 Feature가 전부 있어도
재정규화로 대신하지 않는다: `range_36m` 없이 `avg_price_change_12m`/
`ma_spread`만으로 Base를 판정하거나, `ma24_slope` 없이 `weekly_ma12_slope`/
`ma24_slope_acceleration`만으로 Transition을 판정하는 건 Pattern A의
전제(장기 Base 구조 + Core Transition 신호) 자체를 건너뛰는 것이기
때문이다. `avg_price_change_12m`/`ma_spread`/`weekly_ma12_slope`/
`ma24_slope_acceleration`은 결측이어도 기존 재정규화 정책을 그대로
쓴다. `insufficient_data=True`면 `pattern_a_score`/`stage`는 항상
`None`이다(Hard Reject가 아니라 "판정 보류" 상태).

### PatternAResult 새 구조

위 "Pattern A v0.1 출력 구조 (구현됨)" 절 참고. 기존 5영역 구조
(`base_score`/`low_score`/`ma_score`/`volatility_score`/`breakout_score`,
`rejected`/`rejection_reasons`)는 완전히 삭제하고 새 3축 구조로 교체했다.

### Stage 분류 초안

`_classify_stage(base_score, transition_score, progressed_evidence_count)`
(`pattern_a_score.py`). Feature/component score → Stage 방향으로만
흐른다(Stage가 Score를 역으로 결정하지 않는다). threshold는 모두 잠정치다.

```text
base_score/transition_score 중 하나라도 None       -> None(insufficient_data)
progressed_evidence_count >= 3                      -> PROGRESSED
transition_score < 40  AND base_score >= 60          -> BASE
transition_score < 40  AND base_score < 60           -> WEAK
transition_score >= 70                               -> EARLY_TREND
그 외(40 <= transition_score < 70)                    -> TRANSITION
```

**알려진 한계**: holdout_trend_progressed의 005380(현대차)은
evidence_count=2(3 미만이라 PROGRESSED 조건 불충족)이면서
transition_score=85.12(>=70)라서 **EARLY_TREND로 분류된다** — 실제로는
trend_progressed 라벨이다. Score Validation에서 이렇게 확인된 오분류를
이번 라운드에서 threshold를 조정해 없애지 않는다(item 19: "정확한 stage
threshold는 Score Validation을 보고 조정" — 그 조정은 다음 라운드
과제로 남긴다). pattern_a_score 자체는 이 경우도 56.07로 낮게 나와서
Score만 보면 문제가 크지 않다 — Stage 초안의 한계일 뿐이다.

### Score Design Validation

`scripts/score_design_validate.py`로 필수 5개 그룹(holdout_pre_breakout/
early_trend/trend_progressed, confirmed_negative, ambiguous_negative) +
exploration(참고용)에 Design C를 적용했다. 새 KRX fetch 없음, 기존 캐시만
재사용. CSV는 `data/processed/score_design_validation.csv`(관찰용,
`data/` 전체가 gitignore라 로컬 전용).

**그룹별 final score(Design C) min / median / max**

| group | n | min | median | max |
|---|---|---|---|---|
| holdout_pre_breakout | 5 | 34.27 | 65.69 | 88.52 |
| holdout_early_trend | 5 | 70.07 | 90.25 | 95.58 |
| holdout_trend_progressed | 5 | 0.00 | 0.00 | 56.07 |
| confirmed_negative | 5 | 30.97 | 48.66 | 71.25 |
| ambiguous_negative | 3 | 23.26 | 45.99 | 54.21 |

**snapshot별 component score(holdout + negative_control)**

| group | ticker | name | base | transition | balanced_core | bonus | penalty | final | stage |
|---|---|---|---|---|---|---|---|---|---|
| holdout_pre_breakout | 005380 현대차 | | 89.52 | 21.19 | 34.27 | 0 | 0 | 34.27 | base |
| holdout_pre_breakout | 051910 LG화학 | | 99.31 | 31.63 | 47.98 | 0 | 0 | 47.98 | base |
| holdout_pre_breakout | 000270 기아 | | 92.72 | 50.86 | 65.69 | 0 | 0 | 65.69 | transition |
| holdout_pre_breakout | 006400 삼성SDI | | 85.01 | 76.48 | 80.52 | 8 | 0 | 88.52 | early_trend |
| holdout_pre_breakout | 012330 현대모비스 | | 100.00 | 54.01 | 70.14 | 8 | 0 | 78.14 | transition |
| holdout_early_trend | 005380 현대차 | | 89.15 | 73.42 | 80.53 | 8 | 0 | 88.53 | early_trend |
| holdout_early_trend | 051910 LG화학 | | 92.65 | 83.04 | 87.58 | 8 | 0 | 95.58 | early_trend |
| holdout_early_trend | 000270 기아 | | 93.26 | 76.31 | 83.93 | 8 | 0 | 91.93 | early_trend |
| holdout_early_trend | 006400 삼성SDI | | 76.58 | 88.83 | 82.25 | 8 | 0 | 90.25 | early_trend |
| holdout_early_trend | 012330 현대모비스 | | 100.00 | 53.92 | 70.07 | 0 | 0 | 70.07 | transition |
| holdout_trend_progressed | 005380 현대차 | | 44.07 | 85.12 | 58.07 | 8 | 10 | 56.07 | early_trend* |
| holdout_trend_progressed | 051910 LG화학 | | 7.31 | 98.12 | 13.60 | 8 | 28 | 0.00 | progressed |
| holdout_trend_progressed | 000270 기아 | | 14.75 | 69.72 | 24.34 | 0 | 28 | 0.00 | progressed |
| holdout_trend_progressed | 006400 삼성SDI | | 6.11 | 100.00 | 11.53 | 8 | 35 | 0.00 | progressed |
| holdout_trend_progressed | 012330 현대모비스 | | 51.88 | 94.59 | 67.01 | 8 | 28 | 47.01 | progressed |
| confirmed_negative | 003550 LG | | 95.50 | 47.28 | 63.25 | 8 | 0 | 71.25 | transition |
| confirmed_negative | 010130 고려아연 | | 71.96 | 65.22 | 68.42 | 0 | 0 | 68.42 | transition |
| confirmed_negative | 011170 롯데케미칼 | | 76.15 | 19.43 | 30.97 | 0 | 0 | 30.97 | base |
| confirmed_negative | 032830 삼성생명 | | 76.69 | 35.64 | 48.66 | 0 | 0 | 48.66 | base |
| confirmed_negative | 034730 SK | | 87.77 | 29.79 | 44.48 | 0 | 0 | 44.48 | base |
| ambiguous_negative | 009150 삼성전기 | | 80.70 | 32.16 | 45.99 | 0 | 0 | 45.99 | base |
| ambiguous_negative | 018260 삼성에스디에스 | | 93.54 | 13.28 | 23.26 | 0 | 0 | 23.26 | base |
| ambiguous_negative | 011200 HMM | | 79.23 | 41.20 | 54.21 | 0 | 0 | 54.21 | transition |

(\* Stage 초안의 알려진 오분류 — 위 "Stage 분류 초안" 절 참고. Score
자체는 56.07로 낮게 나와 있다.)

**pre_breakout 결과 해석**: median 65.69로 중상위권 — 아직 Transition이
완전히 확인되지 않은 경우가 많아(현대차 21.19, LG화학 31.63) 최고점은
아니다. Base Score는 5종목 모두 85 이상으로 매우 높다(장기 구조가 아직
Base 안에 있다는 신호가 강하게 잡힘). **item 26 C 확인**: `range_position`
은 Base Score/Transition Score 어디에도 직접 들어가지 않는다(Already
Progressed evidence에서 0.85 이상일 때만 참고). pre_breakout 5종목의
range_position은 0.32~0.56로 낮지만 evidence threshold(0.85)에 전혀
안 걸려 점수에 영향이 없다 — 낮은 점수는 전부 Transition Score 자체가
아직 낮기 때문이지, range_position 때문이 아니다.

**early_trend 결과 해석**: median 90.25로 **5개 그룹 중 가장 높다**
(item 26 D 확인). Base Score도 여전히 76~100으로 높게 유지되면서
Transition Score가 53~89로 올라온 상태 — "Base 유지 + Transition 막
시작"이라는 정의가 그대로 점수에 반영됐다.

**trend_progressed 결과 해석**: median 0.00 — Base Score가 6~52로
급락하고(evidence_count 2~5로 Progressed Penalty 10~35까지 붙어) 강한
Transition(69~100)에도 불구하고 낮게 눌린다(item 26 A 확인: "Transition이
강하다는 이유로 최고점이 되는가?" → 아니오). 유일하게 높은 사례
(012330 현대모비스, 47.01)는 evidence_count=4로 penalty 28을 맞고도
balanced_core 자체가 67.01로 높았던 경우 — base_score(51.88)가 다른
4종목보다 훨씬 덜 무너졌기 때문이다(장기 range가 상대적으로 작음).

**confirmed_negative 결과 해석**: median 48.66. 대부분 base_score는
높지만(72~96) transition_score가 낮아서(19~65) 걸러진다. **알려진
false positive 2건**(item 26 B 관련, 아래 "발견된 실패 사례" 참고):
003550(LG) 71.25, 010130(고려아연) 68.42 — 둘 다 ma24_slope가 약하지만
양수(+0.0102, +0.0520)라서 발생한다. weekly/acceleration 단독 양수만으로
점수가 오른 건 아니다(item 26 B는 이 의미에서는 통과 — 아래 참고).

**ambiguous_negative 결과 해석**: median 45.99. confirmed_negative와
비슷한 수준. 009150/018260은 base 통과, transition 탈락으로 낮음(46,
23). 011200(HMM)만 54.21로 약간 높다 — 정확히는 `ma24_slope_acceleration`
만 양수(+0.0388)고 `weekly_ma12_slope`(−0.0102)와 `ma24_slope`(−0.0161)는
둘 다 음수다(weekly/accel이 둘 다 양수인 게 아니다). ma24_slope도
약한 음수라 50점 근처를 받고(33.9) accel이 84.3으로 끌어올려 transition이
41.20까지 오른다. alignment는 ma24_slope(음수)라 당연히 불충족 —
bonus 없음).

### 발견된 실패 사례

* **confirmed_negative 003550(LG) 71.25**: `ma24_slope=+0.0102`,
  `weekly_ma12_slope=+0.0129`, `ma24_slope_acceleration=+0.0036` 셋 다
  양수라 `transition_alignment`가 충족돼 +8 bonus까지 붙는다. Feature Set
  Freeze의 Combination E 검증에서 이미 확인된 confirmed_negative
  false positive 1/5(20%)가 그대로 재현된 것 — Score Design에서 새로
  발생한 문제가 아니라 Feature 자체의 한계다. 이 샘플 하나 때문에 curve를
  다시 조정하지 않는다(item 27: 표본 하나짜리 separation 튜닝 금지).
* **confirmed_negative 010130(고려아연) 68.42**: `ma24_slope=+0.0520`로
  Transition Score의 Core 요소가 90.2까지 올라간다. `weekly_ma12_slope`는
  음수(−0.0239)라 alignment는 불충족(bonus 없음) — weekly/acceleration이
  아니라 **ma24_slope 자체의 약한 양전환**이 원인이다. item 26 B("weekly/
  acceleration 양수만으로 점수가 높아지는가")는 이 사례에서는 아니오 —
  대신 "ma24_slope의 약한 양전환은 negative_control에서도 발생할 수
  있다"는 Feature Set Freeze 결과의 재확인이다.
* **Stage 초안 오분류(005380 trend_progressed → EARLY_TREND)**: 위
  "Stage 분류 초안" 절 참고. Score(56.07)는 낮게 나와 심각하지 않지만
  Stage 라벨 자체는 부정확하다.

### 최종 Pattern A v0.1 Score 정의

```python
base_score = weighted_piecewise(range_36m=0.55, avg_price_change_12m=0.30, ma_spread=0.15)
transition_score = weighted_piecewise(ma24_slope=0.60, weekly_ma12_slope=0.20, ma24_slope_acceleration=0.20)

balanced_core_score = harmonic_mean(base_score, transition_score)
alignment_bonus = 8.0 if (weekly>0 and ma24>0 and accel>0) else 0.0
progressed_penalty = {0:0, 1:0, 2:10, 3:20, 4:28, 5:35}[progressed_evidence_count]

pattern_a_score = clip(balanced_core_score + alignment_bonus - progressed_penalty, 0, 100)
# range_36m/ma24_slope(required anchor) 결측 또는 base_score/transition_score 계산 불가 -> insufficient_data=True, pattern_a_score=None
```

구현: `src/trend_scanner/patterns/pattern_a_score.py`
(`score_pattern_a(features) -> PatternAResult`).

## OOS Case Validation v0.1 (Frozen Score External Case Validation)

Score Design v0.1(harmonic mean + alignment bonus - progressed penalty,
range_36m required anchor)을 **완전히 새로운 종목/날짜**에 그대로
적용했다. holdout/negative_control은 Score 설계(weight/threshold/penalty
확정)에 이미 쓰여서 더 이상 out-of-sample이 아니다.

**이번 라운드에서 하지 않은 것**: weight/threshold/bonus/penalty 수정,
grid search, 미래 수익률 최적화, 전체 시장 스캔, Stage threshold 조정.
아래 발견된 문제는 전부 **다음 라운드 과제로만 기록**한다.

### 성격 caveat: 이것은 시장 전체의 unbiased OOS 성능 검증이 아니다

Score parameter(weight/threshold/bonus/penalty) 관점에서는 정상적인
external validation이다 — 이 종목/날짜들은 Score 설계에 전혀 쓰이지
않았다. **하지만 종목·날짜 자체를 "이후 상승했는지/다시 하락했는지"라는
미래 outcome 정보를 이용해 선정했다**(positive는 이후 상승 지속,
hard_negative는 이후 재하락, boundary는 아직 base가 없는 하락 도중의
반등). 이건 outcome conditioned case selection이다.

Score/Feature 값을 보지 않고 날짜를 고른 것(아래 "선정 방법" 참고)은
사실이지만, **그룹 라벨 자체가 미래를 알고 붙인 것**이기 때문에 이
결과의 비율을 실제 시장에서의 false positive rate나 precision으로
해석하면 안 된다. 예를 들어 "hard_negative 8개 중 2개가 70점 이상"은
"실제 시장에서 FP rate가 25%"라는 뜻이 아니다 — **의도적으로 고른 실패
사례에 frozen score를 적용했을 때의 stress test 결과**일 뿐이다. 이
문서와 스크립트에서는 앞으로 "OOS Case Validation" 또는 "Frozen Score
External Case Validation"이라는 명칭만 쓴다(정확도가 필요 없는 문맥에서만
"OOS"로 줄여 쓴다).

### 데이터 경계: Development history / v0.2 diagnostic / 미래 OOS2

이번 재리뷰로 세 그룹을 명확히 구분한다.

```text
Development history (Score v0.1 설계에 쓰임, 재사용 가능)
    exploration, 원본 holdout(5종목), negative_control(8종목),
    Base/Expansion Validation

v0.2 diagnostic / development set (이번 라운드로 경계 고정)
    OOS Case Validation v0.1의 29건(positive 15 + hard_negative 8 +
    boundary 5 + insufficient_data_check 1). 이미 결과를 봤으므로
    v0.2 설계·분석에는 재사용할 수 있지만(예: 이번 라운드의 Stage
    audit), v0.2의 성능 검증에는 다시 쓰지 않는다.

미래 OOS2 (아직 선정하지 않음)
    v0.2 Score를 freeze하기 전까지는 OOS2 종목/날짜를 고르거나
    Feature/Score를 계산하지 않는다.
```

`src/trend_scanner/validation/oos_v01_manifest.py`가 29건의 유일한
출처다(`OOS_V01_DATASET_VERSION = "oos_v0.1"`로 태그돼 있다). `scripts/
oos_validate.py`는 이 manifest를 그대로 가져다 쓴다 — 스크립트가 별도
목록을 들고 있다가 조용히 어긋나는 걸 방지한다.

### 선정 방법(look-ahead 방지 원칙 재사용)

negative_control 선정 때와 같은 원칙: **Feature/Score 값을 먼저 보고
고르지 않는다.** `scripts/_oos_fetch_and_inspect.py`로 후보 종목들의
raw monthly close(월봉 종가)만 먼저 조회해서 그 모양(박스권/돌파/하락/
반등)만 보고 종목·날짜를 고정했다. Pattern A Score, base_score,
transition_score, range_36m, ma24_slope 등은 그 이후
`scripts/oos_validate.py`에서 처음 계산했다.

**데이터 품질 스크리닝**: 2013-01-01~2026-08-14(절대 날짜로 고정,
`OOS_V01_SELECTION_START`/`OOS_V01_SELECTION_END`) 구간의 일봉을
조회하면서 `validate_ohlcv`가
거부한 6종목(010140 삼성중공업, 009540 HD한국조선해양, 034020
두산에너빌리티, 004990 롯데지주, 047810 한국항공우주, 042670 HD현대
인프라코어 — 전부 OHLC 관계 위반)은 후보에서 제외했다(카카오 1원 위반
제외 선례와 같은 원칙, provider 보정 정책을 확장하지 않는다). 010060
OCI홀딩스는 `validate_ohlcv`는 통과했지만 2023-04-27~05-29 거래정지
(인적분할 재상장) 구간이 껴 있어 별도로 제외했다 — 36개월 range가
분할 전후 가격을 그대로 이어붙인 값이라 경제적으로 불연속하기
때문이다. 042660(한화오션)의 2016-2017 장기 거래정지(대우조선해양
분식회계 사태)는 이번에 쓴 스냅샷(2024-10 이후)과 36개월 트레일링
구간이 겹치지 않아 문제없다.

**선정 투명성**: 011070(LG이노텍), 010950(S-Oil), 000720(현대건설)도
raw close를 조회했지만 최종 스냅샷에는 쓰지 않았다(가격 흐름이 어느
그룹에도 깔끔하게 들어맞지 않아서 제외 — Feature/Score를 본 뒤 뺀 게
아니다). 전체 후보 목록과 raw monthly close는 `scripts/
_oos_fetch_and_inspect.py` 실행 결과인
`data/processed/oos_selection_monthly_close.csv`(로컬 전용, close만
포함)로 재현 가능하다.

### 그룹 구성

```text
positive_pre_breakout / positive_early_trend / positive_trend_progressed
    5종목 x 3시점(holdout 구성 방식 그대로 재사용)

hard_negative_false_turn
    박스/기저 이후 반등처럼 보였지만 이후 다시 꺾인 8종목

downtrend_reversal_boundary
    아직 base로 정착하기 전, 장기 하락 도중의 반등 시점 5종목
    (Pattern B와의 경계 검증용)

insufficient_data_check
    상장 이력이 짧아 range_36m 36개월 창을 못 채우는 시점 1건
    (required anchor 정책 검증용)
```

### 종목/날짜 선정 근거(raw close만 근거)

| 그룹 | 종목 | 날짜 | 선정 근거(raw monthly close만 근거) |
|---|---|---|---|
| positive_pre/early/progressed | 010620 HD현대미포 | 2023-12 / 2024-06 / 2024-12 | 2019~2023 대체로 4만~9만원대 박스, 2024년 중반부터 뚜렷한 신고가 돌파 시작 |
| positive_pre/early/progressed | 012450 한화에어로스페이스 | 2021-12 / 2022-12 / 2024-06 | 2018~2021 2만~5만원대 박스, 2022년부터 신고가 경신 지속 |
| positive_pre/early/progressed | 079550 LIG넥스원 | 2020-12 / 2021-12 / 2023-12 | 2018~2020 코로나 저점 포함 2만~4만원대 박스, 2021년부터 지속 상승 |
| positive_pre/early/progressed | 005490 POSCO홀딩스 | 2022-12 / 2023-03 / 2023-07 | 2018~2022 23만~29만원대 박스, 2023년 급등(7월 64만원대 고점) |
| positive_pre/early/progressed | 042660 한화오션 | 2024-10 / 2025-01 / 2025-07 | 2018~2024 1.2만~4.2만원대 박스(여러 실패한 반등 포함), 2025년부터 뚜렷한 신고가 경신 |
| hard_negative_false_turn | 036570 엔씨소프트 | 2023-11 | 2023-09 저점(222,500)에서 반등(262,000) 중이던 시점, 이후 2024년 내내 재하락(183,100까지) |
| hard_negative_false_turn | 251270 넷마블 | 2023-11 | 2023-10 저점(38,600)에서 급반등(59,400, +54%) 중이던 시점, 이후 반등분 대부분 반납하며 하향 지속 |
| hard_negative_false_turn | 090430 아모레퍼시픽 | 2024-05 | 2024-03 저점(121,400)에서 반등(194,200, +60%) 중이던 시점, 이후 재하락(104,800까지) |
| hard_negative_false_turn | 011790 SKC | 2024-06 | 2024-01 저점(72,187)에서 급반등(158,473, +120%) 중이던 시점, 이후 급락(92,959까지) |
| hard_negative_false_turn | 004020 현대제철 | 2023-09 | 2022 저점(28,100)대비 반등(38,050) 중이던 시점, 이후 지속 하락(20,950까지) |
| hard_negative_false_turn | 161390 한국타이어 | 2024-04 | 박스권 상단 부근에서 반등(59,100) 중이던 시점, 이후 재하락(35,300까지) |
| hard_negative_false_turn | 069960 현대백화점 | 2021-05 | 코로나 저점(53,700)대비 반등(93,100) 중이던 시점, 이후 다년간 추가 하락(46,350까지) |
| hard_negative_false_turn | 000990 DB하이텍 | 2023-11 | 2023-10 저점(48,400)에서 반등(61,900) 중이던 시점, 이후 재하락(33,150까지) |
| downtrend_reversal_boundary | 090430 아모레퍼시픽 | 2018-12 | 2015년 고점(414,500) 이후 지속 하락 중 2018-10 저점(153,000)에서 소폭 반등(209,500), base 형성 전 |
| downtrend_reversal_boundary | 251270 넷마블 | 2020-08 | 2017년 상장 이후 지속 하락 중 2020-02 저점(88,600) 이후 반등(166,500), base 형성 전 |
| downtrend_reversal_boundary | 069960 현대백화점 | 2019-04 | 2016년부터 지속 하락 중 소폭 개선(101,500), base 형성 전 |
| downtrend_reversal_boundary | 097950 CJ제일제당 | 2019-12 | 2018년부터 지속 하락 중 2019-08 저점(228,500) 이후 소폭 반등(252,500), base 형성 전 |
| downtrend_reversal_boundary | 006800 미래에셋증권 | 2022-10 | 2015년 이후 장기 박스 하단권에서 추가 하락 중이던 시점(다년 저점권, 진짜 base 여부 불확실) |
| insufficient_data_check | 247540 에코프로비엠 | 2021-06 | 2019-03 상장, 이 시점 상장 후 약 27개월치 데이터만 존재(36개월 미만) |

### 그룹별 pattern_a_score min / median / max

| group | n | min | median | max |
|---|---|---|---|---|
| positive_pre_breakout | 5 | 35.97 | 59.35 | 80.75 |
| positive_early_trend | 5 | 18.49 | 54.88 | 76.46 |
| positive_trend_progressed | 5 | 0.00 | 59.80 | 78.60 |
| hard_negative_false_turn | 8 | 10.89 | 53.67 | 75.36 |
| downtrend_reversal_boundary | 5 | 17.71 | 31.01 | 74.67 |
| insufficient_data_check | 0 | — | — | — (전부 `pattern_a_score=None`, 의도대로) |

**그룹별 base_score / transition_score 중앙값**: positive_pre_breakout
(77.80 / 52.97), positive_early_trend(50.88 / 68.02), positive_trend_
progressed(38.13 / 82.39), hard_negative_false_turn(76.50 / 38.73),
downtrend_reversal_boundary(86.43 / 19.33).

### Stage Label Rubric v0.1

v0.2 curve를 손보기 전에, positive 라벨 정의부터 Score/Feature와
**독립적으로** 고정한다. raw monthly/weekly close 구조만 쓰고, "pre
이후 몇 개월 지났는가" 같은 고정 기간은 쓰지 않는다(fast mover는 2~3
개월 만에도 PROGRESSED가 될 수 있다).

```text
PRE_BREAKOUT
    장기 Base 구조 안에 있다. 명확한 장기 돌파가 아직 발생하지
    않았거나, 돌파 시도가 초기 단계다(예: 이전 국지적 고점을 아직
    못 넘었거나 방금 넘은 시점).

EARLY_TREND
    Base 상단을 의미 있게 벗어나기 시작했으나, 장기 구조 대비 가격
    확장이 아직 초기다. 돌파 직후 또는 첫 상승 leg에 가깝다.

TREND_PROGRESSED
    돌파 이후 의미 있는 상승 leg가 이미 진행됐다. Base 대비 가격
    레벨이 크게 이동했고, "이제 막 시작"이라고 보기 어렵다.
```

### 기존 positive 15건 Stage Label Audit

새 rubric으로 positive_pre_breakout/early_trend/trend_progressed
15건을 감사했다(Score/Feature 값 사용 안 함, raw monthly close만
사용). **원본 라벨(`original_group`)은 바꾸지 않는다** — 아래는 별도
병렬 기록이다(`src/trend_scanner/validation/oos_v01_manifest.py`의
`OOS_V01_STAGE_AUDIT`).

| ticker | snapshot_date | original_group | audited_stage_label | audit_note |
|---|---|---|---|---|
| 010620 | 2023-12-31 | pre_breakout | PRE_BREAKOUT | 박스 상단 근접, 2022-08 스파이크 고점(107,000) 미돌파 — 일치 |
| 010620 | 2024-06-30 | early_trend | **PRE_BREAKOUT/EARLY_TREND 경계** | 종가(93,000)가 스파이크 고점(107,000) 아래이자 통상 박스 상단과 거의 겹침 — "돌파 시도 초기"에 더 가까움. 원본보다 보수적으로 판단 |
| 010620 | 2024-12-31 | trend_progressed | TREND_PROGRESSED | 7월 돌파 이후 추가 +44% — 일치 |
| 012450 | 2021-12-31 | pre_breakout | PRE_BREAKOUT | 2016년 고점 미회복, 다년 박스 상단 부근 — 일치 |
| 012450 | 2022-12-31 | early_trend | **TREND_PROGRESSED** | 12개월 +53%, 전 구간 신고가 돌파 완료 + spike-pullback 패턴 — **불일치** |
| 012450 | 2024-06-30 | trend_progressed | TREND_PROGRESSED | 추가 3배 이상 상승 — 일치 |
| 079550 | 2020-12-31 | pre_breakout | PRE_BREAKOUT | 상대적으로 좁은 박스 내부 — 일치 |
| 079550 | 2021-12-31 | early_trend | **TREND_PROGRESSED** | 12개월 +125% — "막 시작"으로 보기 어려움 — **불일치** |
| 079550 | 2023-12-31 | trend_progressed | TREND_PROGRESSED | 추가 상승 지속 — 일치 |
| 005490 | 2022-12-31 | pre_breakout | PRE_BREAKOUT | 박스 상단 부근, 돌파 전 — 일치 |
| 005490 | 2023-03-31 | early_trend | EARLY_TREND | 3개월 만에 박스 상단 확실히 돌파(+33%) — 일치(5건 중 가장 깨끗한 사례) |
| 005490 | 2023-07-31 | trend_progressed | TREND_PROGRESSED | 추가 +74%, 이 구간 전체 고점 — 일치 |
| 042660 | 2024-10-31 | pre_breakout | PRE_BREAKOUT | 다년 박스(2023 실패한 반등 포함) 내부 — 일치 |
| 042660 | 2025-01-31 | early_trend | **EARLY_TREND/TREND_PROGRESSED 경계** | 3개월 +114%로 단기 변동은 크지만, 절대 가격이 2014~2015 고점에 크게 못 미침 — 판단 어려움 |
| 042660 | 2025-07-31 | trend_progressed | TREND_PROGRESSED | 추가 상승, 2014~2015 고점권 근접 — 일치 |

**early_trend 5건 최종 판정**: 1건 깨끗이 일치(005490), 2건 TREND_
PROGRESSED로 불일치(012450, 079550), 1건 PRE/EARLY 경계(010620), 1건
EARLY/PROGRESSED 경계(042660).

**item 23 G에 대한 답(fast mover 문제가 Score 문제인지 label 문제인지)**:
**주로 label 문제였다.** 012450/079550은 raw price 구조로도 이미
TREND_PROGRESSED였는데 달력 기준(pre 이후 약 12개월)으로 "early"라고
잘못 붙였다 — Score의 progressed 판정(evidence_count=4)이 오히려 맞았다.
042660만 진짜로 애매한 fast-mover 구조 사례로 남는다(절대 가격은 여전히
낮은데 단기 변동률만 매우 큼 — 이건 다음 라운드에서 Score 문제로
검토할 여지가 있다). 010620은 라벨이 살짝 관대했던 경계 사례다. 이
결과가 "### A. early_trend가 여전히 높은 Score 영역인가?" 절의 median
54.88이 왜 낮게 나왔는지 대부분 설명한다.

### A. early_trend가 여전히 높은 Score 영역인가? — **OOS Case Validation에서는 재현되지 않았다**

positive_early_trend median 54.88로 pre_breakout(59.35)/trend_progressed
(59.80)보다 **오히려 낮다**. Score Design v0.1이 목표로 했던 "early_trend가
가장 좋은 구간"이라는 패턴이 이번 새 사례 5건에서는 안정적으로
재현되지 않았다 — 이건 그대로 기록한다(단순히 "확인됨"으로 넘기지
않는다).

위 Stage Label Audit이 원인을 대부분 설명한다: early_trend 5건 중
2건(012450, 079550)은 raw price 구조로도 이미 TREND_PROGRESSED였다 —
**주로 label 문제**였고, 그 두 종목에서 Score의 progressed 판정
(evidence_count=4)은 오히려 맞았다. 010620은 라벨이 살짝 관대했던
PRE/EARLY 경계, 042660은 절대 가격은 낮은데 단기 변동률만 큰 진짜
fast-mover 애매 사례로 남는다. 깨끗하게 label과 Score가 둘 다 "early"로
일치한 건 005490 하나뿐이다(76.46, 5건 중 최고점).

**날짜를 다시 고르지 않았다** — Score를 이미 본 뒤에 라벨을 바꾸면
freeze 원칙이 무너진다. **"6개월 이상 지속했을 때만 evidence로 센다"
같은 관찰기간 조건은 이번 라운드에서 넣지 않는다** — Pattern A는 달력
시간이 아니라 가격 구조를 찾는 패턴이므로, fast mover라고 penalty를
늦춰주는 게 반드시 옳지는 않다(item 15). 042660처럼 audit으로도 판단이
안 서는 사례가 남아있는 한, 이건 라벨/observation-period 문제와 진짜
Score 문제가 섞여 있는 채로 다음 라운드 과제로 넘긴다.

### B. progressed가 Transition이 강하다는 이유로 최고점으로 올라오는가? — **아니오**

positive_trend_progressed median(59.80)은 pre_breakout(59.35)과
거의 같고, 5건 중 2건(012450, 042660)은 evidence_count=5로 최대
penalty(35)를 맞아 **0점**까지 떨어졌다. Design C의 구조(harmonic +
penalty)가 OOS에서도 의도대로 작동한다.

### C/D. hard_negative가 70점대 이상으로 침투하는가? LG형 alignment FP가 반복되는가?

8건 중 2건이 70점대 이상으로 침투했다(161390 한국타이어 75.36, 011790
SKC 70.66) — **두 가지 서로 다른 메커니즘**이다.

* **161390(75.36) = LG형 alignment FP의 반복**: ma24_slope(+0.0719)/
  weekly_ma12_slope(+0.0614)/ma24_slope_acceleration(+0.0366) 전부
  양수라 `transition_alignment`가 실제로 충족돼 +8 bonus가 붙는다.
  evidence_count=2로 penalty 10이 붙었는데도 75.36까지 올라갔다 —
  Feature Set Freeze 때 확인한 confirmed_negative의 20%(1/5) FP(LG,
  71.25)와 같은 유형이 OOS에서, 더 높은 값으로 재현됐다.
* **011790(70.66) = 새로운 메커니즘(alignment 아님)**: ma24_slope가
  약한 음수(-0.0109)라 `transition_alignment`는 **불충족**(bonus=0)이다.
  대신 weekly_ma12_slope(+0.1504→100점)와 ma24_slope_acceleration
  (+0.0498→99.8점)가 Supporting 가중치(20%+20%=40%)만으로 transition_
  score(63.37) 중 40점을 만들어냈다 — Core(ma24_slope)가 사실상 약한
  음수인데도 Supporting 둘의 합이 점수를 밀어올린 것이다. 이건 item 12
  ("weekly 하나만 강하다고 전체 Transition Score가 높아지면 안 된다")가
  경고한 위험이 **weekly 하나가 아니라 weekly+accel 조합**으로 실제
  발생한 사례다.

### E. downtrend reversal이 Pattern A 고득점으로 들어오는가? — **예, 사례 있음(item 6 질문에 대한 답)**

5건 중 4건은 낮게 유지됐다(아모레 17.71, CJ제일제당 22.24, 미래에셋
31.01 — ma24_slope 자체가 뚜렷한 음수라 transition_score가 낮게
눌렸다). **하지만 251270(넷마블) 2020-08-31은 74.67까지 올라간다.**

메커니즘: `avg_price_change_12m=-0.1030`(큰 음수)가 Base Score curve에서
무차별적으로 100점을 받는다("낮거나 완만한 상승은 허용"이라는 설계가
"큰 음수"까지 전부 만점으로 취급함). `ma24_slope`는 아직 약한 음수
(-0.0071)라 alignment는 불충족(bonus=0)이지만, weekly(+0.1714)/
accel(+0.0565)가 다시 transition_score를 65.73까지 끌어올린다.
harmonic_mean(86.43, 65.73)=74.67 — **아직 진짜 base가 아니라 다년간
하락 중이던 종목이, "안 오른 게 아니라 계속 빠지고 있었다"는 신호를
Base Score가 구분하지 못해서 높은 점수를 받은 사례**다.

**item 6 결론**: 있다. `avg_price_change_12m`의 "음수는 전부 허용" curve와
weekly/accel Supporting 조합이 겹치면 Pattern A/B 경계 사례가 고득점으로
들어올 수 있다. 다만 4/5는 안전했다 — ma24_slope가 뚜렷한 음수로
유지되는 한 transition_score가 낮게 눌려 보호된다. 위험은 "ma24_slope는
아직 약한 음수인데 avg_price_change_12m은 이미 음수이고 weekly/accel이
동시에 양수인" 특정 조합에서만 나타난다.

### avg_price_change_12m 음수 방향 분석(development set)

item 6/9의 hump-shape(양방향) curve 가설을 뒷받침하는 근거를 development
set 값으로 확인했다(future return 최적화는 하지 않았다, 관찰만).

| 그룹 | 종목 | avg_price_change_12m |
|---|---|---|
| holdout pre_breakout(5종목) | 현대차/LG화학/기아/삼성SDI/현대모비스 | -0.089 ~ +0.098 (전부 완만) |
| holdout early_trend(5종목) | 〃 | -0.058 ~ +0.176 |
| OOS positive_pre_breakout(5종목) | 010620/012450/079550/005490/042660 | -0.157 ~ +0.723(★) |
| confirmed_negative(5종목) | LG/고려아연/롯데케미칼/삼성생명/SK | **-0.276, -0.204**, -0.121, -0.034, +0.312 |
| downtrend_reversal_boundary(5종목) | 아모레/넷마블/현대백화점/CJ제일제당/미래에셋 | -0.184 ~ -0.014(전부 음수) |

(★ 012450 pre_breakout=+0.7233은 이 Feature의 정의(최근 12개월 평균
종가 vs 그 이전 12개월 평균 종가) 때문에, 절대 고점을 아직 안 넘었어도
그 해 안에서 이미 크게 올랐으면 양수로 크게 나올 수 있다 — Base Score
곡선과는 별개 이슈이자 이번 분석의 핵심은 아니다.)

**재검토(당초 분석 오류 수정)**: 처음엔 "큰 음수는 positive Base 사례에
전혀 없다"고 결론 내렸는데, OOS positive_pre_breakout을 다시 보니 틀린
결론이었다 — 079550(-0.144)과 005490(-0.157)이 **-0.14~-0.16 구간에서
진짜 pre_breakout 사례**로 존재한다. 이 구간은 boundary(4/5가
-0.10~-0.18)와 완전히 겹친다. **-0.20보다 깊은 구간(롯데케미칼 -0.276,
삼성생명 -0.204)만 confirmed_negative 전용**이고, 표본이 2개뿐이라
근거가 얇다.

**item 9 결론(수정)**: hump-shape curve 가설은 **후보로 유지하되
단독으로는 Pattern A/B 경계를 못 가른다.** 넷마블 boundary 사례
(-0.103)를 잡을 만큼 얕은 left shoulder를 만들면, 079550(-0.144)/
005490(-0.157) 같은 진짜 pre_breakout 사례까지 함께 감점된다. 넷마블형
누출은 avg_price_change_12m 하나의 curve 모양 문제가 아니라, "하락
구조 자체"(예: 장기간 신저가 경신 여부, 또는 다른 Base 축 Feature와의
조합)를 보는 별도 신호가 필요할 가능성이 있다 — 이번 라운드에서는
breakpoint도 새 Feature도 확정하지 않고 **개념만** 남긴다.

### F. range_36m required 정책이 실제로 적절한가? — **예**

247540(에코프로비엠) 2021-06-30: `range_36m=NaN`(상장 27개월차, 36개월
창 미충족)로 즉시 `insufficient_data=True`, `pattern_a_score=None`,
`stage=None`이 됐다. `avg_price_change_12m`/`ma_spread`/`ma24_slope`는
전부 유효했고 base_score(11.15)/transition_score(88.27)도 개별적으로는
계산됐지만, required anchor 정책이 이를 무시하고 판정을 보류시켰다 —
의도대로 동작한다.

### Stage 오분류(재발, 빈도 증가) — Stage classifier는 별도 후속 작업

positive_trend_progressed 5건 중 **3건**(010620, 079550, 005490)이
evidence_count<3(2, 2, 1)인데 transition_score>=70이라 `PROGRESSED`가
아니라 `EARLY_TREND`로 분류됐다 — Feature Set Freeze 재리뷰 때 holdout
1건에서 확인한 것과 같은 한계인데, OOS에서는 5건 중 3건(60%)으로 빈도가
훨씬 높다. 지금 수준(60% 오분류)은 실사용하기 어렵다.

**Stage threshold는 이번에도 손대지 않는다.** `Stage classifier v0.2는
Score Design v0.2와 별도 후속 작업`으로 명시한다 — Score curve/weight
설계와 Stage 자동 분류 threshold 설계는 서로 다른 문제이고, 섞어서
동시에 손대지 않는다.

**향후 노출 시 주의(구현은 이번에 하지 않음)**: 지금은 Stage가 Scanner
UI나 출력에 연결되기 전이라 문제없다. 나중에 실제 Scanner에 연결할
때는 지금 수준의 heuristic Stage를 확정 label처럼 노출하지 않는다 —
필요하면 `stage_confidence` 또는 `stage_experimental=True` 같은 형태를
그때 검토한다.

### Score v0.1 상태: architecture 유지 vs performance validation

**"현재 Score를 유지할 수 있다"는 표현을 엄밀하게 나눈다.**

```text
Score architecture(harmonic mean + alignment bonus + composite penalty) 유지
    YES — progressed가 최고점이 되지 않는다(2/5는 0점까지 하락),
    hard_negative/boundary 대부분이 낮게 유지된다. 구조 자체는 OOS에서도
    의도대로 작동한다.

Score performance validation 완료
    NO — early_trend가 가장 높은 점수 구간을 형성한다는 Score Design
    초기 목표가 이번 OOS Case Validation에서 재현되지 않았다(median
    54.88이 pre_breakout/trend_progressed보다 낮음, 다만 원인의 상당
    부분은 label 문제로 확인됨). alignment FP(한국타이어), 새로운
    Supporting 우위 메커니즘(SKC), avg_price_change_12m 음수 방향
    사각지대(넷마블 boundary)까지 서로 다른 3가지 실패 메커니즘이
    새 사례에서 발견됐다.
```

**결론: v0.1은 baseline / reference implementation으로 유지한다.**
최종 Score로 freeze 완료된 상태는 아니다. 위 caveat(outcome conditioned
case selection)을 감안하면 "hard_negative 8개 중 2개가 70점대"라는
숫자를 실제 시장 FP rate로 해석해서도 안 된다 — 이번 라운드가 답할 수
있는 건 "이 구조가 그럴듯한 방향으로 작동하는가"까지다, "정확히 얼마나
잘 작동하는가"는 아니다.

### v0.2 검토 후보 1: avg_price_change_12m 양방향(hump-shape) curve

위 "avg_price_change_12m 음수 방향 분석" 절 근거. 개념만 기록한다
(breakpoint 미정):

```text
큰 음수      -> Base 적합도 낮음(가설, 단독으로는 불충분 — 위 분석 참고)
완만한 음수/0 근처 -> 높음
완만한 양수   -> 높음
매우 큰 양수  -> Already Progressed 쪽으로 낮음
```

### v0.2 검토 후보 2: Core / Supporting interaction

SKC 사례(ma24_slope 약한 음수, weekly/accel 강한 양수, alignment
false인데도 transition_score 63점대)가 근거다. 현재 역할 정의(ma24_slope
= Core, weekly/acceleration = Supporting)와 "가중합이면 Supporting
둘의 합(40%)이 Core가 약해도 점수를 밀어올릴 수 있다"는 사실이
충돌할 가능성이 있다. **바로 가중치를 줄이지 않는다**(예: 60/20/20 →
80/10/10 같은 즉흥 조정 금지) — 대신 비교할 구조 후보만 기록한다.

```text
Candidate A: 현재 weighted sum 유지(baseline)

Candidate B: Core gating
    ma24_slope가 약할수록 weekly/acceleration의 기여도를 일부 축소.
    ma24_slope가 충분히 개선됐을 때만 Supporting이 full contribution.

Candidate C: Core + support interaction
    core_score를 먼저 계산하고, Supporting은 core_score에 곱해지는
    confirmation term으로 사용.
    transition_score = core_score + support_factor(core_state) * support_score
```

정확한 식/threshold는 이번 라운드에서 확정하지 않는다.

### v0.2 검토 후보 3: alignment bonus 재검토

LG(Feature Set Freeze)와 한국타이어(OOS)에서 같은 alignment false
positive가 반복됐다. `weekly>0 AND ma24>0 AND accel>0`가 strong
confirmation인 건 맞지만 실패 종목에서도 나온다. **+8 bonus를 바로
없애지 않는다** — 비교 후보만 기록한다: 현재 bonus 유지 / bonus 축소 /
Core strength 조건부 bonus(ma24_slope가 일정 수준 이상 개선됐을 때만
full bonus). 특히 "ma24가 겨우 +0.01인데 나머지 둘도 소폭 양수라는
이유만으로 +8 full bonus"가 적절한지는 v0.2에서 검토한다.

### progressed evidence / fast mover 판단 기준

Stage Label Audit 결과를 기준으로 구분한다: **audit 결과 실제로
TREND_PROGRESSED였다면(012450, 079550) 현재 penalty가 맞게 작동한
것**이고, **audit 결과에서도 여전히 애매하거나 early라면(042660,
경계 사례) progressed evidence가 fast mover를 너무 일찍 처벌하는
문제**로 본다. 이번 감사에서는 후자(진짜 Score 문제)보다 전자(label
문제)가 더 많았다 — 그렇다고 fast mover 문제가 전혀 없다는 뜻은
아니다(042660이 남아있다).

## Score Momentum (다음 단계 계획, 이번 라운드에서는 구현하지 않음)

매주 또는 매일 Pattern Score를 저장한다(`models/score.py`). 목표는
이미 완성된 강한 상승주보다 점수가 빠르게 개선되고 있는 초기 후보를
찾는 것이다. `pattern_a_score`가 이제 실제 점수를 계산하지만, 이번
Score Design v0.1 라운드에서는 `score_momentum()`을 새 Score와 연결하지
않는다(이번 라운드 금지 목록에 명시) — 다음 라운드에서 그대로 적용한다.

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
