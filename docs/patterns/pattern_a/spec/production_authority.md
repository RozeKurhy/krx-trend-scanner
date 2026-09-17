# Pattern A: 장기 베이스 수렴형 (Long Term Base Convergence)

> 이 문서는 현재 Pattern A 공식 규격이다. 현재 계약과 구현 위치를 먼저
> 설명하고, 아래 접힌 영역에는 역사적 연구·검증 근거를 보존한다.

## 1. 현재 상태

| 항목 | 현재 기준 |
|---|---|
| 패턴 | Pattern A: 장기 베이스 수렴형 |
| Score | v0.2, 현재 구현 및 운영 기준 |
| Stage | v0.1, 현재 구현된 단계 분류 기준 |
| 운영 상태 | `FROZEN` / `KEEP_CURRENT_PRODUCTION` |
| 현재 역할 | 장기 베이스와 상승 전환 초기 후보를 판단하는 공식 패턴 |
| 자동매매 | 승인하지 않음. 분석·의사결정 지원 범위에서 사용 |
| 추가 연구 | 현재 진행하지 않음. 새 임계값·새 Feature·OOS 재튜닝을 이 문서에서 만들지 않음 |

Score v0.2와 Stage v0.1은 현재 공식 계약이다. 역사적 검증 문서의 당시 상태
표현은 현재 작업 상태가 아니다. 추가 검증이나 규칙 변경이 필요하면 별도
연구와 승인 절차로 다룬다.

## 2. 현재 공식 위치

| 역할 | 위치 |
|---|---|
| Feature 분류 | `src/trend_scanner/patterns/pattern_a_feature_set.py` |
| Score 계산 | `src/trend_scanner/patterns/pattern_a_score.py`의 `score_pattern_a` |
| 결과 객체 | `PatternAResult` |
| 안내 문서 | [`docs/patterns/pattern_a/README.md`](../README.md) |
| 과거 검증·연구 분류 | [`PATTERNS_DOC_REORGANIZATION_REVIEW_V01.md`](../../PATTERNS_DOC_REORGANIZATION_REVIEW_V01.md) |

## 3. 현재 패턴 정의

Pattern A는 장기 베이스 또는 장기 정체 구간을 거친 뒤 장기 추세가 상승
방향으로 전환되기 시작하는 종목을 판단한다. 다음 두 축을 함께 본다.

```text
Base / Long-Term Structure
+
Trend Transition
```

MA24 기울기 하나만 양수인 상태나 이미 크게 확장된 상태만으로 Pattern A가
되는 것은 아니다. Stage / Breakout Context는 현재 생애주기를 해석하는
참고 축이며 Score와 독립적으로 유지한다.

### 3.1 Feature 역할과 축

| 역할 | 축 | Feature |
|---|---|---|
| Core | Transition | `ma24_slope` |
| Supporting | Transition | `weekly_ma12_slope`, `ma24_slope_acceleration` |
| Context | Base | `range_36m`, `avg_price_change_12m`, `ma_spread` |
| Context | Stage | `range_position`, `range_position_52w`, `distance_to_resistance` |
| Diagnostic | 없음 | `compression_ratio`, `atr_ratio`, `ma_spread_ratio`, `range_24m`, `range_12m` |
| Drop | 없음 | `pivot_low_slope` |

`range_24m`, `range_12m`, `compression_ratio`는 현재 Score에 직접 사용하지
않는다. Context와 Diagnostic을 Hard Filter로 임의 해석하지 않는다.

## 4. 현재 Score 계약

### 4.1 Base Score

Base Score는 장기적으로 과도하게 확장되지 않았는지를 본다. 결측이 아닌
Feature의 가중치를 재정규화한다.

| Feature | 가중치 | 구간별 점수 |
|---|---:|---|
| `range_36m` | 0.55 | `(0.6,100) → (1.2,60) → (2.0,0)` |
| `avg_price_change_12m` | 0.30 | `(0.10,100) → (0.30,50) → (0.60,0)` |
| `ma_spread` | 0.15 | `(0.10,100) → (0.25,50) → (0.40,0)` |

### 4.2 Transition Score

`ma24_slope`만 Core이며, 두 Supporting Feature는 Core를 확인하는 용도로만
사용한다.

| Feature | 역할 | 구간별 점수 |
|---|---|---|
| `ma24_slope` | Core | `(-0.05,0) → (0.00,50) → (0.05,90) → (0.15,100)` |
| `weekly_ma12_slope` | Supporting | `(0.00,20) → (0.15,100)` |
| `ma24_slope_acceleration` | Supporting | `(0.00,30) → (0.05,100)` |

```text
support_score = 0.5 * weekly_score + 0.5 * acceleration_score
confirmation_gate = piecewise(core_score, (0,0), (50,0), (80,1), (100,1))
confirmation_bonus = 20.0 * (support_score / 100.0) * confirmation_gate
transition_score = min(100.0, core_score + confirmation_bonus)
```

### 4.3 Alignment Bonus

다음 세 조건을 모두 만족할 때만 정렬로 본다.

```text
weekly_ma12_slope > 0
AND ma24_slope > 0
AND ma24_slope_acceleration > 0
```

`core_score >= 60.0`이면 `+8.0`, 그보다 낮으면 `+3.0`을 적용한다. 결측이
있어 정렬을 확인할 수 없으면 보너스를 적용하지 않는다.

### 4.4 Already Progressed Penalty

여러 확장 신호가 동시에 나타나는 경우에만 추가 감점을 적용한다. 결측은
증거로 세지 않는다.

| 증거 Feature | 기준 |
|---|---:|
| `range_36m` | `>= 1.20` |
| `avg_price_change_12m` | `>= 0.30` |
| `ma_spread` | `>= 0.20` |
| `ma24_slope` | `>= 0.10` |
| `range_position` | `>= 0.85` |

| 증거 수 | Penalty |
|---:|---:|
| 0 | 0 |
| 1 | 0 |
| 2 | 10 |
| 3 | 20 |
| 4 | 28 |
| 5 | 35 |

### 4.5 최종 Score

```text
balanced_core_score = harmonic_mean(base_score, transition_score)
pattern_a_score = clip(
    balanced_core_score + alignment_bonus - progressed_penalty,
    0,
    100
)
```

## 5. 현재 Stage 계약

공식 lifecycle Stage는 Score 결과가 아니라 현재 Stage Classifier와 raw
Feature·lifecycle context로 독립 판정한다. 공식 구현은
`src/trend_scanner/patterns/pattern_a_stage.py`이며, Evaluator는
`src/trend_scanner/patterns/pattern_a_evaluator.py`의
`PatternAEvaluationResult.stage`와 `PatternAEvaluationResult.lifecycle_stage`에
`stage_result.stage`를 그대로 노출한다.

`score_result.stage`는 Score v0.2 내부의 legacy heuristic 필드다. 하위 호환을
위해 보존하지만 Scanner, 필터, 랭킹 또는 공식 lifecycle 판단에는 사용하지
않는다. Score와 Stage는 서로의 결과를 덮어쓰거나 변조하지 않는다.

현재 Stage Classifier는 다음 순서로 판정한다. 하나의 합성 점수나 Score cutoff를
사용하지 않는다.

필수 raw Feature는 `ma24_slope`, `weekly_ma12_slope`,
`ma24_slope_acceleration`, `avg_price_change_12m`, `ma_spread`,
`range_position`, `distance_to_resistance`다.

| 순서 | 조건 | Stage |
|---:|---|---|
| 1 | 필수 raw Feature 중 하나라도 결측 | `None` (`insufficient_data`) |
| 2 | `active_decline`: 가파른 하락, 하락 가속·과거 낙폭, 또는 낮은 위치의 미전환 조건 중 하나 | `WEAK` |
| 3 | `ma24_slope > 0` 및 (`avg_price_change_12m >= 0.30` 또는 `ma_spread >= 0.20`) | `PROGRESSED` |
| 4 | `ma24_slope > 0`, `weekly_ma12_slope >= 0.03`, `range_position >= 0.60` | `EARLY_TREND` |
| 5 | `ma24_slope > 0` 또는 `weekly_ma12_slope >= 0.03` | `TRANSITION` |
| 6 | 그 밖의 경우 | `BASE` |

`active_decline`의 세부 조건은 `ma24_slope <= -0.045`,
`ma24_slope_acceleration < 0` 및 `avg_price_change_12m <= -0.15`, 또는
`weekly_ma12_slope <= 0` 및 `range_position <= 0.20`이다. Stage Classifier는
과거 monthly context도 계산해 `StageLifecycleContext`로 반환하지만, 현재
최종 Stage를 Score나 별도 override로 다시 쓰지 않는다.

Stage 분류의 역사적 검증과 알려진 한계는 아래 역사 문서에서 확인한다. 현재
문서에서 Stage threshold를 임의로 조정하지 않는다.

## 6. 결측·PIT·출력 계약

- `range_36m`과 `ma24_slope`는 필수 기준 Feature다. 둘 중 하나라도 결측이면
  `insufficient_data=True`, `pattern_a_score=None`, `stage=None`이다.
- 그 밖의 Base·Supporting Feature 결측은 가능한 축 안에서 가중치를
  재정규화한다. 축 전체가 계산 불가능하면 해당 결과는 결측이다.
- 입력 Feature는 해당 기준일 이하의 완료된 관측값으로 계산한다. 미래 관측값,
  미완료 기간, 임의의 다른 날짜 대체값을 사용하지 않는다.
- 결과는 `base_score`, `transition_score`, `core_score`, `support_score`,
  `confirmation_bonus`, `balanced_core_score`, `alignment_bonus`,
  `progressed_penalty`, `progressed_evidence_count`, `pattern_a_score`,
  `stage`, `flags`를 포함하는 `PatternAResult`로 반환한다.
- 현재 공식 Score에는 위 계약 밖의 새 Filter·순위·수익률 최적화를 추가하지
  않는다.

## 7. 역사적 근거와 변경 경계

현재 계약의 근거는 다음 역사 기록에서 확인할 수 있다. 역사 문서는 현재
규칙이나 현재 작업 상태를 대체하지 않는다.

- [Pattern A 운영 확정 기록](../validation/final_production_closure.md)
- [Pattern A Score OOS 사례 기록](../validation/oos2.md)
- [Pattern A Stage OOS 결과](../validation/stage_oos_v01_result.md)
- [문서 재정리 분류표](../../PATTERNS_DOC_REORGANIZATION_REVIEW_V01.md)

Score 곡선·가중치·Penalty·Stage threshold·필수 Anchor를 바꾸려면 별도 연구
문서, 검증 범위, 승인과 함께 변경한다. 이 문서는 새 연구를 시작하는 문서가
아니다.

현행 권위 문서에는 과거 연구 원문을 통째로 포함하지 않는다. 상세한 Score·Stage
검증 근거는 위 링크된 역사 문서에서 확인한다. `oos2.md`는 완료된 역사적
검증 결과이며, 현재 추가 검증 대기 상태를 의미하지 않는다.
