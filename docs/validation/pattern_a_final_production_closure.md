# Pattern A Final Production Validation & Closure

## 1. Executive Summary

* **문서명**: `pattern_a_final_production_closure.md`
* **Closure Checkpoint Commit**: `5be5b4255a8045a626fa22a002a6012521e918ae`
* **Pattern A Score Production Version**: **`v0.2 (Production 유지)`**
* **Pattern A Stage Production Version**: **`v0.1 (Production 유지)`**
* **Pattern A Scanner Production Path**: **`Phase8 Frozen Path (Production 유지)`**
* **Stage v0.2 Candidate**: **`REJECT FOR PRODUCTION / HOLD AS RESEARCH HISTORY`**
* **Stage v0.3 Existing Feature Research**: **`공식 종료 (CLOSED, NO_GENERALIZABLE_RULE_FOUND)`**
* **Stage v0.4 Multi-Year Structural Feature Research**: **`공식 종료 (CLOSED, NO_USEFUL_MULTI_YEAR_FEATURE_FOUND)`**
* **Pattern A Stage Research Lifecycle**: **`공식 종료 (CLOSED)`**
* **Next Project Phase**: **`SCANNER_OPERATION_AND_CANDIDATE_QUALITY_WORKFLOW`**

---

## 2. Frozen Production Identity

1. **Stage v0.1 Frozen Commit**: `43ee01ca086c5d33bbf195bed67e161f5a315bf5`
2. **Scanner Phase8 Frozen Commit**: `13ab6f416a0de77e89c7e0412467eb393e07c6dc`
3. **Production Source Integrity**: 현재 HEAD의 모든 프로덕션 로직(`pattern_a_stage.py`, `pattern_a_score.py`, `pattern_a_scanner.py`)은 Frozen Commit과 100% 동일하며 임의 변형(Mutation)이 0건입니다.

---

## 3. Score v0.2 Final Semantic

* **수식**:
  $$\text{balanced\_core} = \text{harmonic\_mean}(\text{base\_score}, \text{transition\_score})$$
  $$\text{pattern\_a\_score} = \text{clip}(\text{balanced\_core} + \text{alignment\_bonus} - \text{progressed\_penalty}, 0, 100)$$
* **Stage 독립성**: Score 계산은 Stage 출력값을 전혀 참조하지 않으며, Stage 또한 Score 파생값을 전혀 사용하지 않는 완전한 독립 계층(Decoupled Layer)입니다.

---

## 4. Stage v0.1 Final Semantic

* **Lifecycle 흐름**: `WEAK / BASE` $\rightarrow$ `TRANSITION` $\rightarrow$ `EARLY_TREND` $\rightarrow$ `PROGRESSED`
* **동일 Episode Non-Regression**: 동일 에피소드 내에서 PROGRESSED 상태가 하위 단계(TRANSITION, EARLY_TREND)로 역행하지 않음.
* **진정한 구조 붕괴 시 새 Episode 가능**: 장기 지지선 붕괴 및 MA24 하락(`ma24_slope < -0.045`, `range_position < 0.20`) 후 재구축 시 새로운 에피소드로 판정.
* **Point-in-Time 원칙**: `include_incomplete_periods=False` 및 완료된 캘린더 월봉/주봉만 사용하여 Lookahead를 철저히 차단.

---

## 5. Benchmark Exact Reproduction

현재 HEAD 코드에서 Live Evaluator를 실행한 실측 결과입니다.

```text
+----------------+-------------+---------------+-----------------+----------------+--------------------+
| Dataset        | Total Count | Exact Matches | Exact Rate (%)  | Adjacent (±1)  | Severe Errors (≥2) |
+----------------+-------------+---------------+-----------------+----------------+--------------------+
| Calibration 46 | 46          | 38 / 46       | 82.6%           | 5 / 46 (10.9%) | 3 / 46 (6.5%)      |
| OOS 35         | 35          | 24 / 35       | 68.6%           | 10 / 35 (28.6%)| 1 / 35 (2.9%)      |
+----------------+-------------+---------------+-----------------+----------------+--------------------+
| Total          | 81          | 62 / 81       | 76.5%           | 15 / 81 (18.5%)| 4 / 81 (4.9%)      |
+----------------+-------------+---------------+-----------------+----------------+--------------------+
```
* **결과**: Calibration 38/5/3 및 OOS 24/10/1이 100% 완벽하게 재현됨 (Gate PASS).

---

## 6. Lifecycle Regression Audit

* **079550 LIG넥스원 2021-12-31**: `PROGRESSED` (2021 대규모 시세 분출 반영)
* **079550 LIG넥스원 2023-12-31**: `EARLY_TREND` (2022-2023 기간 조정 후 새 에피소드 정상 전이)
* **동일 에피소드 비역행(Non-regression) 및 요청 순서 독립성**: 기존 12개 lifecycle regression 테스트 전수 통과.

---

## 7. Phase8 Scanner Reproduction

2026-08-14 단일 컷오프(`include_incomplete_periods=False`) 기준 실측 재현 결과:
* **전체 종목 Universe**: **2,528개**
* **Pattern A 통과 Candidates**: **180개**
  - `TRANSITION`: **168개 (93.3%)**
  - `EARLY_TREND`: **12개 (6.7%)**
* **Frozen CSV 일치율**: `artifacts/chart_review/pattern_a_candidate_manual_review_20260814.csv`와 180개 전 종목 identity 100% 일치.

---

## 8. Human 42 Chart Review Evidence

* **EARLY_TREND (12종목)**:
  - `GOOD_FIT`: 7건, `BORDERLINE`: 3건, `NOT_FIT`: 2건 (적합률 **83.3%**)
  - Stage Fit: `MATCH 4`, `TOO_EARLY 3`, `TOO_LATE 4`, `UNCLEAR 1`
* **TRANSITION (30종목 탐색 표본)**:
  - `GOOD_FIT`: 2건, `BORDERLINE`: 15건, `NOT_FIT`: 13건
  - Stage Fit: `MATCH 13`, `TOO_EARLY 13`, `TOO_LATE 4`
  - *참고: TRANSITION 30종목은 무작위 표본이 아닌 탐색적 연구군이므로 모집단 전체 정확도로 일반화하지 않음.*

---

## 9. 8대 Known Limitation Registry

```text
+----+---------------------------------------------------------------------------------------------------------+
| No | Known Limitation Description                                                                            |
+----+---------------------------------------------------------------------------------------------------------+
| 01 | TRANSITION 단계는 바닥권 극초기 반등(BASE 수준)의 Premature Candidate를 일부 포함함.                     |
| 02 | 026910(광진실업)과 같은 단기 급반등 사례가 36m 모멘텀으로 인해 TRANSITION으로 분류될 수 있음.            |
| 03 | 038390(레드캡투어)과 같은 과거 대규모 시세 분출 후 조정 국면의 Recycled 사례가 완전히 배제되지 않음.     |
| 04 | EARLY_TREND 단계는 빠른 시세 분출이나 성숙한 돌파 후 종목에서 일부 TOO_LATE 판정이 발생할 수 있음.      |
| 05 | Stage는 기계적 라이프사이클 휴리스틱이며, 인간 차트의 모든 미세 구조를 100% 표현하는 분류기가 아님.     |
| 06 | 36개월 Existing Feature 연구(Stage v0.3)에서 정상군을 훼손하지 않는 일반화 규칙을 발견하지 못함.         |
| 07 | 5년 다년 구조 Feature 연구(Stage v0.4)에서도 독립적으로 분리 가능한 유의미한 단일 피처를 발견하지 못함. |
| 08 | Known Limitation을 억지로 제거하기 위한 추가 임계값 튜닝은 정상군 및 벤치마크에 심각한 훼손을 유발함.    |
+----+---------------------------------------------------------------------------------------------------------+
```

---

## 10. Rejected Candidate Research History

1. **Stage v0.2 Candidate (ad4fd7f1...)**:
   - Checkpoint: `d975f66`
   - 결과: PRESEAL 57 PASS / 3 FAIL (Premature 3개 제거로 기준 4개 미달, 026910 미해결) ➔ **`HOLD / REJECT`**
2. **Stage v0.3 Existing Feature Research (Hypothesis A~G)**:
   - Checkpoint: `6f3c061`
   - 결과: 81개 벤치마크 및 정상 Transition MATCH 13군에 치명적 회귀 유발 ➔ **`CLOSED (NO_GENERALIZABLE_RULE_FOUND)`**
3. **Stage v0.4 Multi-Year Structural Feature Research (Family 1~3)**:
   - Checkpoint: `5be5b42`
   - 결과: 5년 피처 9종 전수 광범위한 IQR 중첩 확인 ➔ **`CLOSED (NO_USEFUL_MULTI_YEAR_FEATURE_FOUND)`**

---

## 11. Final Production Decision

```text
================================================================================
FINAL PRODUCTION DECISION: KEEP_CURRENT_PRODUCTION
================================================================================
- Pattern A Score v0.2: PRODUCTION KEEP
- Pattern A Stage v0.1: PRODUCTION KEEP
- Pattern A Scanner Phase8: PRODUCTION KEEP
- Pattern A Stage Research: PERMANENTLY CLOSED
================================================================================
```

---

## 12. Future Change Policy

* **기본 원칙**: Pattern A 알고리즘은 본 Closure 시점 이후 **영구 동결(Frozen Algorithm)**로 취급한다.
* **재오픈 불가 사유**:
  - 특정 1~2개 종목(026910, 038390 등)의 오분류 불만
  - 임의의 직관에 기반한 즉흥적 threshold 미세 조정
* **향후 프로젝트 방향**:
  - **NEXT_PHASE = `SCANNER_OPERATION_AND_CANDIDATE_QUALITY_WORKFLOW`**
  - 알고리즘 변경이 아닌, 스캐너 실운용 및 후보 종목 퀄리티 리뷰 워크플로우 개발로 전환한다.
