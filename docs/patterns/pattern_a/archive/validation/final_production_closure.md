# Pattern A 최종 운영 검증 및 확정 기록

> 이 문서는 Pattern A 운영 확정 시점의 역사 기록이다. `다음 프로젝트 단계`는 문서 작성 당시 계획이며 현재 작업 순서를 뜻하지 않는다.
>
> 현재 Pattern A의 규칙과 권위는 [현재 공식 규격](../../spec/production_authority.md)을 따른다. 아래 수치·판정·Stage 설명은 운영 확정 시점의 검증·해석 기록이며 현재 계약을 대체하지 않는다.
>
> 현재 프로젝트는 Score v0.2 / Stage v0.1을 유지하고 추가 연구는 진행하지 않는다. 향후 변경이 필요하면 별도 연구·검증·승인 절차로 다룬다. 이 문서의 당시 확정 결정은 미래 변경을 영구히 금지하는 현재 정책이 아니다.

## 1. 요약

* **문서명**: `pattern_a_final_production_closure.md`
* **운영 확정 시점 커밋**: `6b266fb5a8faa43c6daa7f1bef56315b03855f8e`
* **Pattern A Score 운영 버전**: **`v0.2 (운영 유지)`**
* **Pattern A Stage 운영 버전**: **`v0.1 (운영 유지)`**
* **Pattern A 스캐너 운영 경로**: **`Phase8 동결 경로 (운영 유지)`**
* **Stage v0.2 후보**: **`REJECT FOR PRODUCTION / HOLD AS RESEARCH HISTORY`**
* **Stage v0.3 기존 Feature 연구**: **`공식 종료 (CLOSED, NO_GENERALIZABLE_RULE_FOUND)`**
* **Stage v0.4 다년 구조 Feature 연구**: **`공식 종료 (CLOSED, NO_USEFUL_MULTI_YEAR_FEATURE_FOUND)`**
* **Pattern A Stage 연구 생애주기**: **`당시 결정: 추가 연구 종료 (CLOSED)`**
* **당시 다음 프로젝트 단계**: **`SCANNER_OPERATION_AND_CANDIDATE_QUALITY_WORKFLOW`**

---

## 2. 운영 기준 동결 기록

1. **Stage v0.1 동결 커밋**: `43ee01ca086c5d33bbf195bed67e161f5a315bf5`
2. **스캐너 Phase 8 동결 커밋**: `13ab6f416a0de77e89c7e0412467eb393e07c6dc`
3. **운영 소스 일치 확인**: 운영 확정 시점의 검증 당시 모든 프로덕션 로직(`pattern_a_stage.py`, `pattern_a_score.py`, `full_universe_scanner.py`, `historical_snapshot.py`)은 동결 커밋과 100% 동일하며 임의 변형이 0건입니다.

---

## 3. Score v0.2 최종 의미

* **수식**:
  ```text
  balanced_core = harmonic_mean(base_score, transition_score)

  pattern_a_score = clip(
      balanced_core + alignment_bonus - progressed_penalty,
      0,
      100
  )
  ```
* **Stage 독립성**: Score 계산은 Stage 출력값을 전혀 참조하지 않으며, Stage 또한 Score 파생값을 전혀 사용하지 않는 완전한 독립 계층입니다.

---

## 4. Stage v0.1 최종 의미

> 아래 생애주기 설명은 운영 확정 시점의 검증·해석 기록이다. 현재 공식 Stage는 `pattern_a_stage.py`의 독립 분류기를 따르며, `score_result.stage`는 legacy 휴리스틱이고 현재 평가기의 공식 Stage는 `stage_result.stage`이다.

* **생애주기 흐름**: `WEAK / BASE` $\rightarrow$ `TRANSITION` $\rightarrow$ `EARLY_TREND` $\rightarrow$ `PROGRESSED`
* **동일 에피소드 내 역행 없음**: 동일 에피소드 내에서 PROGRESSED 상태가 하위 단계(TRANSITION, EARLY_TREND)로 역행하지 않음.
* **진정한 구조 붕괴 시 새 에피소드 가능**: 장기 지지선 붕괴 및 MA24 하락(`ma24_slope < -0.045`, `range_position < 0.20`) 후 재구축 시 새로운 에피소드로 판정.
* **시점 일치 원칙**: `include_incomplete_periods=False` 및 완료된 캘린더 월봉/주봉만 사용하여 미래 데이터 참조를 철저히 차단.

---

## 5. 기준 데이터 재현 결과

운영 확정 시점의 검증 코드에서 운영 평가기를 실행한 실측 결과입니다.

| 데이터 묶음 | 전체 수 | 정확 일치 | 정확도 (%) | 인접 오차 (±1) | 큰 오류 (≥2) |
|---|---:|---:|---:|---:|---:|
| Calibration 46 | 46 | 38 / 46 | 82.6% | 5 / 46 (10.9%) | 3 / 46 (6.5%) |
| OOS 35 | 35 | 24 / 35 | 68.6% | 10 / 35 (28.6%) | 1 / 35 (2.9%) |
| 전체 | 81 | 62 / 81 | 76.5% | 15 / 81 (18.5%) | 4 / 81 (4.9%) |

* **결과**: Calibration 38/5/3 및 OOS 24/10/1이 100% 완벽하게 재현됨 (관문 PASS).

---

## 6. 생애주기 회귀 및 079550 알려진 한계 점검

* **079550 LIG넥스원 (2021-12-31)**:
  - `운영 분류기 결과`: **`PROGRESSED`**
  - `감사 기준 정답`: **`PROGRESSED`**
* **079550 LIG넥스원 (2023-12-31)**:
  - `운영 분류기 결과`: **`EARLY_TREND`**
  - `감사 기준 정답`: **`PROGRESSED`**
  - **알려진 한계 해석**: 이는 신규 에피소드가 정상 시작된 것이 아니라, **동결된 v0.1 설계 문서에 이미 기록된 알려진 인접 오분류**입니다. 운영 동작 재현성은 완벽히 PASS(`frozen_stage_behavior_reproduction_pass = true`)하며, 새로운 회귀가 아님을 확증하였습니다.

---

## 7. Phase 8 스캐너 재현 및 후보 동일성 비교

2026-08-14 단일 컷오프(`include_incomplete_periods=False`) 기준 실측 스캐너 실행 결과:
* **전체 보통주 유니버스**: **2,528개**
* **Pattern A 통과 후보**: **180개**
  - `TRANSITION`: **168개 (93.3%)**
  - `EARLY_TREND`: **12개 (6.7%)**
* **후보 동일성 1:1 비교**:
  - `누락 종목`: **`[] (0건)`**
  - `추가 종목`: **`[] (0건)`**
  - `Stage 변경 종목`: **`[] (0건)`**
  - `동일성 비교 통과`: **`TRUE`**

---

## 8. 42종목 사람 차트 검토 결과

* **EARLY_TREND (12종목)**:
  - `GOOD_FIT`: 7건, `BORDERLINE`: 3건, `NOT_FIT`: 2건 (적합률 **83.3%**)
  - Stage 적합성: `MATCH 4`, `TOO_EARLY 3`, `TOO_LATE 4`, `UNCLEAR 1`
* **TRANSITION (30종목 탐색 표본)**:
  - `GOOD_FIT`: 2건, `BORDERLINE`: 15건, `NOT_FIT`: 13건
  - Stage 적합성: `MATCH 13`, `TOO_EARLY 13`, `TOO_LATE 4`
  - *참고: TRANSITION 30종목은 무작위 표본이 아닌 탐색적 연구군이므로 모집단 전체 정확도로 일반화하지 않음.*

---

## 9. 알려진 한계 8가지

| 번호 | 알려진 한계 설명 |
|---:|---|
| 01 | TRANSITION 단계는 바닥권 극초기 반등(BASE 수준)의 조기 후보를 일부 포함함. |
| 02 | 026910(광진실업)과 같은 단기 급반등 사례가 36m 모멘텀으로 인해 TRANSITION으로 분류될 수 있음. |
| 03 | 038390(레드캡투어)과 같은 과거 대규모 시세 분출 후 조정 국면의 재등장 사례가 완전히 배제되지 않음. |
| 04 | EARLY_TREND 단계는 빠른 시세 분출이나 성숙한 돌파 후 종목에서 일부 TOO_LATE 판정이 발생할 수 있음. |
| 05 | 079550(LIG넥스원 2023-12)과 같이 긴 기간 조정 후 재반등 시 PROGRESSED 대신 EARLY_TREND로 인접 오분류됨. |
| 06 | 36개월 기존 Feature 연구(Stage v0.3)에서 정상군을 훼손하지 않는 일반화 규칙을 발견하지 못함. |
| 07 | 5년 다년 구조 Feature 연구(Stage v0.4)에서도 독립적으로 분리 가능한 유의미한 단일 피처를 발견하지 못함. |
| 08 | 알려진 한계를 억지로 제거하기 위한 추가 임계값 튜닝은 정상군 및 벤치마크에 심각한 훼손을 유발함. |

---

## 10. 채택하지 않은 후보 연구

1. **Stage v0.2 후보 (ad4fd7f1...)**:
   - 검증 시점: `d975f66`
   - 결과: PRESEAL 57 PASS / 3 FAIL (조기 후보 3개 제거로 기준 4개 미달, 026910 미해결) ➔ **`HOLD / REJECT`**
2. **Stage v0.3 기존 Feature 연구 (가설 A~G)**:
   - 검증 시점: `6f3c061`
   - 결과: 81개 벤치마크 및 정상 Transition MATCH 13군에 치명적 회귀 유발 ➔ **`CLOSED (NO_GENERALIZABLE_RULE_FOUND)`**
3. **Stage v0.4 다년 구조 Feature 연구 (그룹 1~3)**:
   - 검증 시점: `5be5b42`
   - 결과: 5년 피처 9종 전수 광범위한 IQR 중첩 확인 ➔ **`CLOSED (NO_USEFUL_MULTI_YEAR_FEATURE_FOUND)`**

---

## 11. 당시 최종 운영 결정

```text
================================================================================
당시 최종 운영 결정: KEEP_CURRENT_PRODUCTION
================================================================================
- Pattern A Score v0.2: 운영 유지 (PRODUCTION KEEP)
- Pattern A Stage v0.1: 운영 유지 (PRODUCTION KEEP)
- Pattern A Scanner Phase8: 운영 유지 (PRODUCTION KEEP)
- Pattern A Stage 연구: 당시 결정상 영구 종료 (PERMANENTLY CLOSED)
================================================================================
```

---

## 12. 향후 변경 원칙

* **운영 확정 시점의 기본 원칙**: Pattern A 알고리즘은 확정 이후 **당시 동결된 알고리즘(Frozen Algorithm)**으로 취급했다.
* **운영 확정 시점의 재오픈 제한 사유**:
  - 특정 1~2개 종목(026910, 038390 등)의 오분류 불만
  - 임의의 직관에 기반한 즉흥적 임계값 미세 조정
* **운영 확정 시점의 다음 프로젝트 방향**:
  - **NEXT_PHASE = `SCANNER_OPERATION_AND_CANDIDATE_QUALITY_WORKFLOW`**
  - 당시에는 알고리즘 변경이 아닌, 스캐너 실운용 및 후보 종목 퀄리티 리뷰 워크플로우 개발로 전환하는 방향이었다.
  - 위 `NEXT_PHASE`는 운영 확정 시점 당시의 다음 단계 기록이며 현재 작업 지시가 아니다.
