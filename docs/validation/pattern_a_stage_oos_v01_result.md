# Pattern A Stage Classifier v0.1: Frozen OOS Validation Run 결과

## 1. Validation Design

본 문서는 `Stage Classifier v0.1`(commit `43ee01c`)을 사전 봉인된 `Stage OOS Truth Set`(35 snapshots, commit `93f26a0`)에 **처음으로 실행한 공식 외부 검증(External Challenge OOS Validation Run) 결과 보고서**이다.

### 1.1 엄격한 Git Chronology 및 사후 봉인 검증
- **Classifier Frozen**: commit `43ee01c`
- **OOS Truth Freeze**: commit `e3506be`
- **Truth Integrity Followup**: commit `875afa7` (Overlap 0 & Provenance 테스트 강제화)
- **Minor Documentation Followup**: commit `93f26a0` (OOS v0.2 38건 표기 정정 및 로컬 링크 제거)
- **Classifier Prediction First Run**: commit `ae3508e` (Frozen 상태에서 최초 검증 실행)

---

## 2. Frozen Inputs & Dataset Caveat

### 2.1 Frozen Inputs
1. **Classifier**: `src/trend_scanner/patterns/pattern_a_stage.py` (`classify_pattern_a_stage()`)
2. **Truth Manifest**: `src/trend_scanner/validation/pattern_a_stage_oos_v01_manifest.py` (`PATTERN_A_STAGE_OOS_V01_LABELS`, 35 snapshots, 24 unique tickers)

### 2.2 Dataset Caveat
* **Stage-balanced & Failure-mode-enriched Challenge Set**: 본 35건은 시장 전체의 무작위 표본이 아니라, 5개 Stage가 각각 7건씩 완벽히 균등 배치되고 4대 known failure mode 및 cycle reset 구조가 집중된 **고난도 외부 도전 과제 세트(External Challenge Set)**이다.
* **해석 기준**: 따라서 본 결과의 EXACT match rate(68.6%)와 EXACT+ADJACENT 비율은 **`external challenge OOS reproduction rate`**로 해석하며, 시장 자연 분포가 반영된 `real-world market accuracy`나 `production hit rate`로 직접 환산하지 않는다.

---

## 3. Overall Results

| 지표 | 건수 (n=35) | 비율 (%) | 평가 |
|---|---|---|---|
| **EXACT Match** | **24** | **68.6%** | 외부 challenge OOS 기준 양호 |
| **ADJACENT Match** | **10** | **28.6%** | 사전 정의된 인접 bucket 내 위치 |
| **SEVERE Mismatch** | **1** | **2.9%** | 보수적 과소평가 1건 (위험한 과대승격 0건) |
| **NODATA** | **0** | **0.0%** | 35건 전수 정상 평가 완료 |
| **EXACT or ADJACENT Bucket** | **34** | **97.1%** | 35건 중 34건이 사전 정의된 인접 범위 내 포함 |

> [!NOTE]
> **Ordinal Caveat**: WEAK는 완전한 ordinal Stage가 아니므로(`WEAK <-> BASE`는 단순한 1단계 차이로만 볼 수 없음), EXACT + ADJACENT 비율(97.1%)을 일반적인 valid accuracy나 production hit rate로 해석하지 않는다.

---

## 4. Confusion Matrix (5x5)

```text
[Confusion Matrix (rows = Manual Ground Truth, cols = Classifier Prediction)]

Manual Truth \ Predicted |    WEAK |    BASE | TRANSITION | EARLY_TREND | PROGRESSED | Total
---------------------------------------------------------------------------------------------
WEAK                     |       7 |       0 |          0 |           0 |          0 |     7
BASE                     |       2 |       3 |          2 |           0 |          0 |     7
TRANSITION               |       1 |       2 |          4 |           0 |          0 |     7
EARLY_TREND              |       0 |       0 |          4 |           3 |          0 |     7
PROGRESSED               |       0 |       0 |          0 |           0 |          7 |     7
---------------------------------------------------------------------------------------------
Total Predicted          |      10 |       5 |         10 |           3 |          7 |    35
```

---

## 5. Per Stage Breakdown

| Stage | 표본수 (Support) | EXACT (%) | ADJACENT (%) | SEVERE (%) | 판정 분석 및 한계점 |
|---|---|---|---|---|---|
| **WEAK** | 7 | **7 (100.0%)** | 0 (0.0%) | 0 (0.0%) | 이번 OOS 7건 모두 정확 분류 (하락 지속 및 false turn 식별) |
| **BASE** | 7 | **3 (42.9%)** | 4 (57.1%) | 0 (0.0%) | 경계 민감도 존재 (WEAK 2건, TRANSITION 2건) |
| **TRANSITION** | 7 | **4 (57.1%)** | 2 (28.6%) | 1 (14.3%) | SEVERE 1건(LS), 인접 BASE 2건 |
| **EARLY_TREND** | 7 | **3 (42.9%)** | 4 (57.1%) | 0 (0.0%) | **핵심 Limitation**: 4건이 TRANSITION으로 1단계 지연 인식 |
| **PROGRESSED** | 7 | **7 (100.0%)** | 0 (0.0%) | 0 (0.0%) | 이번 OOS 7건 모두 정확 분류 (과열 확장 및 episode continuation 식별) |

---

## 6. All Mismatches (11건 전수 목록)

| No | Ticker | 종목명 | Snapshot Date | Selection Group | Manual Truth | Predicted | Match Type | 주요 Reason Codes 및 메커니즘 |
|---|---|---|---|---|---|---|---|---|
| 1 | `030200` | KT | 2023-10-31 | `quiet_box_base` | BASE | **TRANSITION** | ADJACENT | `ma24_slope` 미세 양수로 `core_pos=True` 발동 |
| 2 | `024110` | 기업은행 | 2023-11-30 | `quiet_box_base` | BASE | **TRANSITION** | ADJACENT | `ma24_slope` 미세 양수로 `core_pos=True` 발동 |
| 3 | `271560` | 오리온 | 2024-08-31 | `quiet_box_base` | BASE | **WEAK** | ADJACENT | 24개월선 하향 기울기 잔존으로 `active_decline=True` 발동 |
| 4 | `068270` | 셀트리온 | 2023-09-30 | `cycle_reset_base` | BASE | **WEAK** | ADJACENT | Cycle Reset 정상 작동, 24개월선 음수로 `active_decline` 발동 |
| 5 | `000660` | SK하이닉스 | 2023-05-31 | `weekly_leading_transition` | TRANSITION | **BASE** | ADJACENT | 월봉 코어 미회복 및 주봉 기울기 0.03 미달로 fallback |
| 6 | `006260` | LS | 2022-10-31 | `box_breakout_prep_transition` | TRANSITION | **WEAK** | **SEVERE** | 24개월선 음수로 `active_decline` 발동 (False Negative 방향) |
| 7 | `028050` | 삼성E&A | 2021-03-31 | `weekly_leading_transition` | TRANSITION | **BASE** | ADJACENT | 월봉 코어 미회복 및 주봉 기울기 0.03 미달로 fallback |
| 8 | `005830` | DB손해보험 | 2023-12-31 | `clean_early_trend` | EARLY_TREND | **TRANSITION** | ADJACENT | `weekly_ma12_slope < 0.03`으로 breakout 미달 (지연) |
| 9 | `006260` | LS | 2023-02-28 | `clean_early_trend` | EARLY_TREND | **TRANSITION** | ADJACENT | `weekly_ma12_slope < 0.03`으로 breakout 미달 (지연) |
| 10 | `003230` | 삼양식품 | 2022-11-30 | `clean_early_trend` | EARLY_TREND | **TRANSITION** | ADJACENT | `weekly_ma12_slope < 0.03`으로 breakout 미달 (지연) |
| 11 | `272210` | 한화시스템 | 2024-03-31 | `clean_early_trend` | EARLY_TREND | **TRANSITION** | ADJACENT | `weekly_ma12_slope < 0.03`으로 breakout 미달 (지연) |

---

## 7. Severe Mismatch & Dangerous Promotion Audit

### 7.1 Dangerous Promotion 정의 및 검증
* **정의**: 비추세 또는 초기 단계 종목을 성숙 확장 단계로 위험하게 과대 승격하는 오류
  - `WEAK -> EARLY_TREND`
  - `WEAK -> PROGRESSED`
  - `BASE -> PROGRESSED`
  - `TRANSITION -> PROGRESSED`
* **Calibration vs OOS 비교**:
  - Calibration: **2 / 46 (4.3%)** (`012450` 한화에어로스페이스 2021-12-31, `010130` 고려아연 2022-06-30에서 `TRANSITION -> PROGRESSED` 2건 존재)
  - OOS Validation: **0 / 35 (0.0%)**
* **해석 주의**: Calibration에서 2건 관찰되었던 dangerous promotion 문제가 완전히 해결되었다고 단정할 수 없으며, **"No dangerous promotion was observed in this 35 snapshot external challenge OOS set (이번 OOS challenge set에서는 dangerous promotion 0건이 관찰되었다)"**로 기술한다.

### 7.2 유일한 SEVERE 1건 상세 분석 (False Negative Cost)
* **사례**: `006260` LS (2022-10-31) | Truth: `TRANSITION` ➔ Predicted: `WEAK`
* **메커니즘**: 24개월선 장기 하향 잔존으로 `active_decline`이 먼저 발동하여 `WEAK`로 판정됨.
* **해석**: 위험한 과대 승격(dangerous promotion)은 아니지만, **초기 전환 후보를 누락시키는 False Negative 방향의 severe mismatch**이다. 스캐너 목적상 유망 전환 후보를 놓치는 False Negative 비용이 존재함을 명확히 인지해야 한다.

---

## 8. Known Failure Mode & Specific Structure Audit

### 8.1 Failure Mode 1: Episode Continuation
* **검증 케이스**: `086520` 에코프로 (2023-11-30, Truth: `PROGRESSED`)
* **결과**: `PROGRESSED` 일치 (`Episode continuation challenge: 1/1 passed`)
* **분석**: 피크 후 -40% 급락 조정기에도 `expansion_present`가 유지되어 `PROGRESSED`로 정확히 분류됨. 단, 단일 challenge 통과로 failure mechanism 자체가 일반적으로 해결되었다고 확대 해석하지 않는다.

### 8.2 Failure Mode 2: Surge Recovery vs Genuine Progression
* **검증 케이스**: `035900` JYP Ent. (2020-07-31, Truth: `TRANSITION`)
* **결과**: `TRANSITION` 일치 (`Surge recovery challenge: 1/1 passed`)
* **분석**: 가파른 V자 반등을 PROGRESSED로 과대평가하지 않고 `TRANSITION`으로 분류함.

### 8.3 Failure Mode 3: BASE 경계 민감도
* **검증 케이스**: `017670` SK텔레콤 (`BASE` EXACT), `030200` KT (`TRANSITION`), `024110` 기업은행 (`TRANSITION`), `271560` 오리온 (`WEAK`), `068270` 셀트리온 (`WEAK`)
* **분석**:
  - `BASE -> TRANSITION` (2건): 미세한 코어 양전환에 대한 민감도
  - `BASE -> WEAK` (2건): 24개월선 잔여 하향에 따른 active decline 발동. 이는 단순한 ordinal 1단계 차이로 축소할 수 없는 **BASE와 active decline WEAK 사이의 경계 오류**로서 별도 주의가 필요함.

### 8.4 Failure Mode 4: Active Decline & False Turn
* **검증 케이스**: `006360` GS건설 (2022-11-30, false turn, Truth: `WEAK`)
* **결과**: `WEAK` 일치 (`False turn challenge: 1/1 passed`)

### 8.5 핵심 Limitation: EARLY_TREND 탐지 지연 (4 / 7)
* **사례**: DB손해보험, LS, 삼양식품, 한화시스템 (4건 모두 `EARLY_TREND -> TRANSITION`)
* **분석**: 대세 상승 초입을 조기 포착하는 스캐너 목적에서 EARLY_TREND exact 42.9%(3/7)는 주요한 limitation이다. `weekly_ma12_slope`가 0.03 기준에 미세 미달하여 1단계 보수적으로 인식되었으며, 이는 향후 v0.2 설계의 핵심 개선 근거로 기록한다.

---

## 9. Calibration vs OOS 비교 분석

| 지표 | Calibration (46 snapshots, 27 tickers) | OOS Validation (35 snapshots, 24 tickers) | 관찰된 특성 (Observational Notes) |
|---|---|---|---|
| **EXACT Match** | 38 / 46 (**82.6%**) | 24 / 35 (**68.6%**) | OOS challenge set에서 더 낮은 exact 비율 관찰 |
| **ADJACENT Match** | 5 / 46 (**10.9%**) | 10 / 35 (**28.6%**) | OOS challenge set에서 경계 bucket 비중이 더 높게 관찰 |
| **SEVERE Mismatch** | 3 / 46 (**6.5%**) | 1 / 35 (**2.9%**) | OOS challenge set에서 더 낮은 severe 비율 관찰 |
| **Dangerous Promotion** | **2 / 46 (4.3%)** | **0 / 35 (0.0%)** | 이번 OOS challenge set에서 dangerous promotion 미관찰 |
| **WEAK 정확도** | 5 / 5 (**100.0%**) | 7 / 7 (**100.0%**) | 두 dataset 모두 포함된 WEAK 사례 전수 exact |
| **BASE 정확도** | 7 / 10 (**70.0%**) | 3 / 7 (**42.9%**) | OOS challenge set에서 BASE 경계 민감도 관찰 |
| **TRANSITION 정확도**| 7 / 10 (**70.0%**) | 4 / 7 (**57.1%**) | OOS challenge set에서 일부 보수적 판정 관찰 |
| **EARLY_TREND 정확도**| 8 / 8 (**100.0%**) | 3 / 7 (**42.9%**) | OOS challenge set에서 TRANSITION으로 4건 지연 관찰 |
| **PROGRESSED 정확도** | **11 / 13 (84.6%)** | 7 / 7 (**100.0%**) | 이번 OOS challenge set의 PROGRESSED 7건 전수 exact |

---

## 10. Final Judgment

### **`Pattern A Stage Classifier v0.1: OOS CONDITIONALLY ACCEPTED`**

#### 종합 평가:
1. **긍정적 요인**:
   - 외부 challenge OOS에서 Dangerous Promotion 0건 관찰 (0/35).
   - WEAK(7/7) 및 PROGRESSED(7/7) 양극단에 대한 높은 식별력.
   - SEVERE mismatch가 1건(2.9%)에 불과.
   - 대표 challenge 케이스(에코프로, JYP, GS건설) 통과.
2. **한계점 (Known Limitations)**:
   - EARLY_TREND exact가 3/7(42.9%)로, 4건이 TRANSITION으로 1단계 지연 인식되는 보수적 bias 확인.
   - BASE의 경계 민감도(BASE ➔ TRANSITION 2건, BASE ➔ WEAK 2건).
   - LS(2022-10-31)에서 초기 전환 후보를 누락시키는 False Negative 방향의 SEVERE 1건 발생.
3. **결론**:
   - v0.1 baseline을 폐기하거나 즉시 v0.2 tuning을 진행할 필요는 없다.
   - 현재 OOS evidence를 frozen baseline으로 유지하고, 다음 architecture 단계에서 Stage를 독립 signal로 통합해 추가 관찰을 수행한다.

---

## 11. Current Status & Next Step

### 11.1 현재 상태
```text
Pattern A Stage Classifier v0.1: FROZEN (43ee01c)
Calibration Truth Set (46 snapshots): FROZEN
Stage OOS Truth Set (35 snapshots): FROZEN
OOS Validation Result: FROZEN (EXACT 68.6%, ADJACENT 28.6%, SEVERE 2.9%, Dangerous 0.0%)
Final Judgment: OOS CONDITIONALLY ACCEPTED
Stage v0.2: NOT STARTED (Known limitations documented for future development)
```

### 11.2 Next Step
Phase 3를 공식 완료하고, Stage Classifier v0.1을 Pattern A Score와 함께 독립 signal로 다루는 **`Pattern A Evaluator Integration`**으로 이동한다.
