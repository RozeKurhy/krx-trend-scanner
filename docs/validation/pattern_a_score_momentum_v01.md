# Pattern A Score Momentum v0.1 설계 및 검증 보고서

## 1. 개요 및 목적

`Pattern A Score Momentum v0.1`은 Frozen 상태인 **Pattern A Score v0.2**를 완료된 월봉(Completed Monthly) 기준의 시간축으로 반복 평가하여, 최근 **1개월(1M), 3개월(3M), 6개월(6M)** 동안의 Score 변화량(Raw Delta) 및 세부 구성요소 변화량(Component Delta)을 산출하는 **순수 측정 계층(Pure Measurement Layer)**이다.

> [!IMPORTANT]
> **핵심 철학 및 분리 원칙**:
> * **Score**: "지금 이 종목의 Pattern A 구조가 얼마나 매력적인가?" (현재 시점의 매력도, 0~100점)
> * **Score Momentum**: "Pattern A Score가 최근 몇 개월 동안 어느 방향으로 얼마나 변화했는가?" (시간에 따른 Score 차분)
> * **Stage Classifier**: "현재 이 종목이 어떤 라이프사이클 국면(WEAK, BASE, TRANSITION, EARLY_TREND, PROGRESSED)에 있는가?" (구조적 위치)
> * **Candidate State**: 공식 Stage 기반의 해석 상태 (CANDIDATE, WATCH, LATE, BLOCKED, INSUFFICIENT_DATA)
>
> Score Momentum은 **새로운 alpha 모델이나 가중 점수(Unified Score)가 아니며**, 임의의 threshold(RISING, FALLING 등)나 good/bad 판단을 내리지 않고 순수한 시간축 관측값만을 제공한다.

---

## 2. 관측 주기 및 Anchor 기준 (Observation Cadence & Semantics)

1. **Completed Monthly Observation**:
   * 주봉/일봉이나 진행 중인 미완성 월봉을 사용하지 않고, 요청일(`req_ts`) 기준 완성된 월봉만을 anchor로 사용한다.
2. **Calendar Month End Semantics**:
   * `as_of = 2023-09-30`(토요일)처럼 월말이 비거래일인 경우에도 9월 월봉을 completed로 온전히 유지하며, `momentum_anchor = 2023-09-30`이 된다.
   * `as_of = 2023-11-15`처럼 월 중간인 경우 해당 11월 봉이 drop되어 `momentum_anchor = 2023-10-31`이 된다.
3. **Exact Calendar Horizons (No Silent Backfill)**:
   * 단순 봉 순서(ordinal distance)가 아닌 정확한 Calendar Month 이전 시점($T-1M, T-3M, T-6M$)과 비교한다.
   * 중간에 특정 calendar month 데이터가 결측된 경우, 더 오래된 월봉으로 silent backfill하지 않고 해당 horizon을 `ready=False` (`MISSING_MONTHLY_OBSERVATION_{m}M`)로 안전하게 반환한다.

---

## 3. Score Delta 및 Component Delta 산출 방식

### 3.1 Raw Score Delta
$$\Delta_{1M} = \text{Score}_T - \text{Score}_{T-1\_calendar\_month}$$
$$\Delta_{3M} = \text{Score}_T - \text{Score}_{T-3\_calendar\_months}$$
$$\Delta_{6M} = \text{Score}_T - \text{Score}_{T-6\_calendar\_months}$$

* Percent change 대신 **단순 차분(Simple Difference)**을 사용한다 (Score가 0~100 유계 척도이므로 0 근처에서 왜곡 방지).

### 3.2 Component Delta Decomposition & Caveat
Score 변화의 구체적인 동인을 파악하기 위해 기존 Frozen `PatternAResult`의 구성요소별 차분을 함께 제공한다:
* `base_score_delta`: 베이스 안정성 변화
* `transition_score_delta`: 전환 시그널 변화
* `core_score_delta`: 핵심 점수 변화
* `support_score_delta`: 보조 점수 변화
* `confirmation_bonus_delta`: 확인 보너스 변화
* `balanced_core_score_delta`: 균형 핵심 점수 변화
* `alignment_bonus_delta`: 정렬 보너스 변화 (이산적 변화 가능)
* `progressed_penalty_delta`: 진행 과열 페널티 변화 (이산적 변화 가능)
* `progressed_evidence_count_delta`: 과열 증거 개수 변화

> [!CAUTION]
> **Component Delta 단순 합 불일치 주의 (Diagnostic Decomposition Caveat)**:
> Component Delta는 Score 변화의 방향과 원인을 진단하기 위한 진단용 분해 관측값(Diagnostic Decomposition)이다.
> Pattern A Score v0.2는 조화평균(Harmonic Mean), 이산적 가산 보너스/페널티(Alignment Bonus, Progressed Penalty), 0~100 유계 클리핑(Bounded Clipping)을 포함하는 비선형 결합 구조를 가지므로, **각 Component Delta의 단순 합이 최종 Pattern A Score Delta와 항상 일치하지 않는다.**
> 따라서 Component Delta의 합으로 최종 Score Delta를 재구성하거나 회계적 항등식(Accounting Identity)으로 해석해서는 안 된다.

---

## 4. 최소 히스토리 요구사항 및 에러 Provenance 분리

| 평가 항목 | 최소 완성 월봉 요구조건 | 비고 |
|---|---|---|
| **Current Score only** | **36 completed monthly bars** | 36개월 미만 시 Current Score 산출 불가 |
| **1M Momentum** | **37 completed monthly bars** | $T$ 및 $T-1M$ 필요 |
| **3M Momentum** | **39 completed monthly bars** | $T$ 및 $T-3M$ 필요 |
| **6M Momentum** | **42 completed monthly bars** | $T$ 및 $T-6M$ 필요 |

### 4.1 Reason Code Contract 최종 목록

* **Insufficient History (히스토리 부족)**:
  * `INSUFFICIENT_HISTORY_CURRENT`
  * `INSUFFICIENT_HISTORY_1M`
  * `INSUFFICIENT_HISTORY_3M`
  * `INSUFFICIENT_HISTORY_6M`
* **Missing Monthly Observation (중간 월봉 결측)**:
  * `MISSING_MONTHLY_OBSERVATION_1M`
  * `MISSING_MONTHLY_OBSERVATION_3M`
  * `MISSING_MONTHLY_OBSERVATION_6M`
* **Observation Error (계산 예외 / 에러)**:
  * `OBSERVATION_ERROR_CURRENT`
  * `OBSERVATION_ERROR_1M`
  * `OBSERVATION_ERROR_3M`
  * `OBSERVATION_ERROR_6M`
* **Current Horizon Wrapper**:
  * `CURRENT_SCORE_UNAVAILABLE`

---

## 5. 대표 사례 실측 관찰 결과 (Descriptive Historical Analysis)

> 아래 결과는 Score Momentum이 과거 시점에서 어떻게 산출되는지 관찰하기 위한 실측 데이터이며, 모델의 적중률이나 성과를 주장하는 것이 아닙니다.

### 5.1 SK하이닉스 (`000660`)
* **2023-05-31 (requested_as_of: 2023-05-31, momentum_anchor: 2023-05-31)**:
  * Score at Anchor: `18.96`
  * 1M Delta: `+18.96` (0.00 ➔ 18.96)
  * 3M Delta: `+15.57` (Base: `+8.99`, Transition: `+8.82`, Core: `+8.82`)
  * 6M Delta: `-40.43` (59.38 ➔ 18.96)
* **2023-11-30 (requested_as_of: 2023-11-30, momentum_anchor: 2023-11-30)**:
  * Score at Anchor: `87.74`
  * 1M Delta: `+1.41` (86.33 ➔ 87.74)
  * 3M Delta: `+13.65` (Transition: `+12.02`, Core: `+10.02`)
  * 6M Delta: `+68.78` (18.96 ➔ 87.74)
* **2024-06-28 (requested_as_of: 2024-06-28, momentum_anchor: 2024-05-31)**:
  * Score at Anchor: `56.89`
  * 3M Delta: `-24.67` (Base: `-32.38`, Transition: `+26.99`, Core: `+24.82`, Progressed Penalty: `+10.00`)
  * 6M Delta: `-30.85` (87.74 ➔ 56.89)

### 5.2 LS (`006260`)
* **2022-10-31 (requested_as_of: 2022-10-31, momentum_anchor: 2022-10-31)**: Score at Anchor: `81.12`, 3M Delta: `-9.01`
* **2023-07-31 (requested_as_of: 2023-07-31, momentum_anchor: 2023-07-31)**: Score at Anchor: `51.40`, 3M Delta: `-28.59` (Base: `-40.45`, Penalty: `+10.00`)

### 5.3 삼양식품 (`003230`)
* **2022-04-29 (requested_as_of: 2022-04-29, momentum_anchor: 2022-03-31)**: Score at Anchor: `58.55`, 3M Delta: `-0.75`
* **2022-11-30 (requested_as_of: 2022-11-30, momentum_anchor: 2022-11-30)**: Score at Anchor: `75.79`, 3M Delta: `+25.51` (Transition: `+30.31`, Core: `+26.90`)

---

## 6. 알려진 한계 (Known Limitations)

1. **Monthly Cadence 시차**: Score Momentum은 완성 월봉 주기이므로, 월중에 발생하는 급격한 주간(weekly) 돌파나 단기 변동성을 실시간으로 반영하지 않는다.
2. **Stage와의 반응 시차**: 공식 Stage Classifier는 52주 고가 및 주봉 MA12 기울기 등 주간 Context를 포함하므로, Stage 전이 시점과 Monthly Score Momentum의 반응 시점에 차이가 발생할 수 있다.
3. **0~100 유계 클리핑 효과**: Score가 상한(100) 또는 하한(0)에 도달한 극단 구간에서는 추가적인 구조 변화가 Delta 수치에 온전히 반영되지 않고 압축될 수 있다.
4. **이산적 보너스/페널티의 계단식 변동**: Alignment bonus(0, 3, 8) 및 Progressed penalty(10, 20 등)의 발동/해제 시 Delta가 불연속적인 계단식으로 변동할 수 있다.
5. **No Silent Backfill**: 특정 calendar month 결측 시 오래된 월봉으로 대체하지 않으므로 데이터 갭이 있는 경우 해당 horizon이 unavailable로 처리된다.
6. **예측성/수익률 검증 미포함**: 본 v0.1은 순수 측정 계층으로, 미래 수익률과의 상관관계나 매매 시그널로서의 유효성을 검증하거나 보장하지 않는다.

---

## 7. Current Status & Next Step

### 7.1 확정 상태
```text
Pattern A Score v0.2: FROZEN
Pattern A Stage Classifier v0.1: FROZEN (43ee01c)
Pattern A Evaluator Integration v0.1: COMPLETED (51fc202)
Data Quality & Universe Preparation v0.1: COMPLETED (0ce8012)
Pattern A Score Momentum v0.1: FROZEN MEASUREMENT CONTRACT (CLEANUP COMPLETED)
Unit & Integration Tests: 273 passed (100% Green)
Next: Official Common Stock Cache Population -> Full Universe Scanner Integration
```
