# FAST Core 다음 후보 구체 규칙 정의서

## 1. 문서 상태

- 문서 상태: 검토용 규칙 정의
- 임시 후보명: `TWO_PHASE_PRICE_STRUCTURE_HWM_CANDIDATE_V01`
- 공식 전략 ID: 부여하지 않음
- 후보 동결: 하지 않음
- 운영 반영: 하지 않음

이 문서는 다음 후보의 규칙을 구체적으로 정의하는 단계의 산출물이다. 이 문서만으로 후보를 동결하거나 구현·검증·백테스트를 시작하지 않는다.

## 2. 근거 문서

다음 문서를 규칙의 기준으로 사용한다.

- `docs/strategies/strategy_lifecycle.md`
- `docs/patterns/pattern_a_fast/strategy/version_02/README.md`
- `docs/patterns/pattern_a_fast/strategy/version_03/README.md`
- `docs/patterns/pattern_a_fast/research/next_candidate_design_direction_v01.md`
- `docs/patterns/pattern_a_fast/validation/version_03_matched_ab_failure_review.md`
- `artifacts/backtests/fastcore_v3_failure_review_v01/summary.json`

새 분석을 수행하지 않으며, 기존 공식 결과의 관찰을 규칙 정의의 배경으로만 사용한다.

## 3. 목표와 비목표

### 3.1 목표

V2 진입을 유지하면서 다음 두 구간을 분리한다.

1. `+20%` Winner 도달 전에는 가격 손실과 주간 FAST 구조를 함께 사용하여 명시적인 조기 실패를 정의한다.
2. `+20%` Winner 도달 후에는 V3의 HWM 보호 구조를 유지하되, Soft exit의 구조 조건에서 `SETUP`을 제외한다.

### 3.2 비목표

- V4 또는 V3.1을 생성하지 않는다.
- 공식 전략 ID를 만들거나 후보를 동결하지 않는다.
- 진입 규칙, 지표, 상태 머신, 재진입 정책을 새로 만들지 않는다.
- 임계값 튜닝, 파라미터 스윕, 추가 분석, 구현, 테스트, 백테스트를 수행하지 않는다.
- 예상 백테스트 결과를 근거로 규칙을 추가하지 않는다.

## 4. 진입 규칙

진입은 `SAME_AS_V02`로 고정한다. 후보의 진입 조건과 실행 시점은 V2와 동일하다.

- Pattern A 상태: `TRANSITION` 또는 `EARLY_TREND`
- FAST 상태: `TRIGGER` 또는 `READY`
- 월간 레짐: `PERMITTED_REGIME`
- 일간 위험 상태: `NORMAL` 또는 `ELEVATED`
- FAST Score: `READY` 또는 `PARTIAL`
- 실행: `NEXT_LOCAL_TRADING_DAY_OPEN`
- 진입 가격: 기존 V2 진입 가격 규칙과 동일

후속 matched A/B 비교를 수행하는 경우에도 CONTROL의 진입 시점과 진입 가격은 고정하며, 후보별 진입 차이를 허용하지 않는다.

## 5. 공통 정의

### 5.1 평가 시점

- 신호에 사용하는 일간 가격은 완료된 일간 봉의 종가를 사용한다.
- 신호가 발생한 완료 일의 청산 실행은 `NEXT_LOCAL_TRADING_DAY_OPEN`으로 한다.
- 당일 고가로 HWM을 갱신하되, 당일 종가 신호를 당일 시가 또는 당일 고가에 소급하여 실행하지 않는다.
- 다음 현지 거래일이 없으면 `OPEN_AT_CUTOFF`로 종료한다.

### 5.2 HWM과 running raw MFE

- HWM은 진입 이후 완료된 일간 고가의 최고값이다.
- `running raw MFE = HWM / entry_open - 1`로 계산한다.
- `entry_open`은 V2와 동일한 진입 기준값이다.
- `running raw MFE`는 단방향으로 증가한다. 한 번 Winner로 분류되면 이후 Pre-Winner로 되돌리지 않는다.

### 5.3 주간 FAST 구조

- 구조 판정에는 최신 완료 주간의 FAST Machine Stage와 Stage Status만 사용한다.
- 구조 조건의 `WATCH/READY`는 Stage가 `WATCH`이고 Stage Status가 `READY`인 조합을 의미한다.
- `SETUP`은 구조 실패 조건에 포함하지 않는다.
- `TRIGGER`, `TREND`, `EXTENDED`는 구조 실패로 매핑하지 않는다.
- `UNAVAILABLE`은 `WATCH`로 간주하거나 대체 매핑하지 않는다.
- Stage Status가 `READY`가 아니면 구조 실패 조건을 충족하지 않는다.

## 6. 단계 분류와 당일 처리 순서

각 완료 일은 다음 순서로 처리한다.

1. 해당 일의 고가를 반영하여 HWM을 갱신한다.
2. 갱신된 HWM으로 `running raw MFE`를 계산한다.
3. `running raw MFE < +20%`이면 Pre-Winner, `running raw MFE >= +20%`이면 Winner로 분류한다.
4. 분류된 단계의 규칙만 평가한다.

따라서 해당 일에 처음으로 `+20%`에 도달하면 그 일은 Winner이다. 같은 일의 Pre-Winner `-15%` 가격 조건과 `WATCH/READY` 구조 조건은 적용하지 않고 Winner 규칙을 평가한다. 정확히 `+20%`인 값은 Winner가 소유한다.

## 7. Phase 1: Pre-Winner 조기 실패 규칙

### 7.1 단계 조건

다음 조건을 모두 만족하는 경우에만 Pre-Winner 조기 실패 신호를 발생시킨다.

- 단계: `running raw MFE < +20%`
- 가격 조건: `daily_close / entry_open - 1 <= -15%`
- 구조 조건: 최신 완료 주간 FAST Machine Stage = `WATCH`이고 Stage Status = `READY`

정확히 `-15%`인 값은 가격 조건을 만족한다. `-15%`보다 작은 손실도 동일하게 조건을 만족한다.

### 7.2 신호와 실행

- 신호: `PRE_WINNER_PRICE_STRUCTURE_FAILURE`
- 실행: `NEXT_LOCAL_TRADING_DAY_OPEN`
- 두 조건 중 하나라도 충족하지 않으면 보유한다.

### 7.3 적용하지 않는 조건

- 가격만 `-15%` 이하인 경우에는 청산하지 않는다.
- `SETUP`과 Stage Status `READY` 조합은 구조 실패로 보지 않는다.
- `TRIGGER`, `TREND`, `EXTENDED`는 구조 실패로 보지 않는다.
- 주간 구조가 `UNAVAILABLE`인 경우에는 조기 실패로 보지 않는다.
- Stage Status가 `READY`가 아닌 경우에는 조기 실패로 보지 않는다.
- 지속성 조건, 시간 청산, `FAILURE_ARMED`, 회복 카운터, 추가 확인 조건을 도입하지 않는다.
- 새로운 지표나 상태를 추가하지 않는다.

## 8. Phase 2: Winner HWM 보호 규칙

### 8.1 Winner 활성화

`running raw MFE >= +20%`인 즉시 Winner 규칙을 활성화한다. 정확히 `+20%`인 값은 Winner의 하한이며, 이후 단계는 Pre-Winner로 회귀하지 않는다.

### 8.2 HWM 하락폭 밴드

다음 V3 밴드와 임계값을 그대로 유지한다. HWM 하락폭은 HWM 대비 현재 가격의 하락폭으로 계산하며, Winner 단계의 가격 보호 조건은 진입가 대비 손실률이 아니라 HWM 기준으로 평가한다.

| running raw MFE 구간 | Soft 하락폭 | Hard 하락폭 |
| --- | ---: | ---: |
| `+20% <= MFE < +50%` | `-10%` | `-20%` |
| `+50% <= MFE < +100%` | `-15%` | `-25%` |
| `+100% <= MFE < +200%` | `-20%` | `-30%` |
| `+200% <= MFE < +400%` | `-25%` | `-35%` |
| `MFE >= +400%` | `-30%` | `-40%` |

정확히 `+50%`, `+100%`, `+200%`, `+400%`에 도달한 값은 각각 다음 밴드의 하한으로 판정한다. 즉 경계 도달 즉시 다음 밴드의 Soft/Hard 임계값을 적용한다. 밴드의 수치 자체는 변경하지 않는다.

### 8.3 Winner Soft exit

Winner Soft 조건은 다음과 같다.

- 현재 HWM 하락폭이 해당 밴드의 Soft 임계값 이상이다.
- 최신 완료 주간 FAST Machine Stage = `WATCH`이고 Stage Status = `READY`이다.

두 조건을 모두 만족하면 다음 신호를 발생시킨다.

- 신호: `WINNER_SOFT_WATCH_EXIT`
- 실행: `NEXT_LOCAL_TRADING_DAY_OPEN`

V3의 `WATCH 또는 SETUP` 구조 조건에서 `SETUP`을 제거하고 `WATCH/READY`만 유지한다. `SETUP`은 Soft 구조 조건을 충족하지 않으므로 보유한다. 주간 구조가 `UNAVAILABLE`이거나 Stage Status가 `READY`가 아닌 경우에도 Soft exit를 발생시키지 않는다.

### 8.4 Winner Hard exit

Winner Hard 규칙은 V3와 동일하게 유지한다.

- 현재 HWM 하락폭이 해당 밴드의 Hard 임계값 이상이면 가격 조건만으로 청산한다.
- FAST 주간 구조 상태와 독립적으로 평가한다.
- 신호: `WINNER_HARD_EXIT`
- 실행: `NEXT_LOCAL_TRADING_DAY_OPEN`

Hard 규칙은 이 후보에서 새로 검증되거나 확정된 규칙이 아니다. 비교 가능성을 위해 V3 요소를 그대로 유지하는 것이다.

### 8.5 Soft와 Hard가 같은 날 충족되는 경우

같은 완료 일에 Soft와 Hard가 모두 충족되면 `WINNER_HARD_EXIT`를 우선한다. Hard는 구조 조건을 요구하지 않으며, Soft보다 강한 보호 규칙으로 처리한다.

## 9. 결정표

| 단계 및 조건 | FAST 주간 구조 | 결과 |
| --- | --- | --- |
| Pre-Winner, 손실이 `-15%`보다 큼 | 무관 | `HOLD` |
| Pre-Winner, 손실이 `-15%` 이하 | `WATCH/READY` | `PRE_WINNER_PRICE_STRUCTURE_FAILURE` |
| Pre-Winner, 손실이 `-15%` 이하 | `SETUP/READY` | `HOLD` |
| Pre-Winner, 손실이 `-15%` 이하 | `UNAVAILABLE` | `HOLD` |
| Winner, Soft 미충족 | 무관 | `HOLD` |
| Winner, Soft 충족·Hard 미충족 | `WATCH/READY` | `WINNER_SOFT_WATCH_EXIT` |
| Winner, Soft 충족·Hard 미충족 | `SETUP/READY` | `HOLD` |
| Winner, Hard 충족 | 무관 | `WINNER_HARD_EXIT` |
| Winner, Soft와 Hard 동시 충족 | `WATCH/READY` 또는 그 외 | `WINNER_HARD_EXIT` |

결정표의 단계 분류가 먼저이며, Winner Hard가 Winner Soft보다 우선한다.

## 10. 재진입과 실행 의미

- 재진입 의미: `SAME_AS_V02`
- 후보별 전략 특화 재진입 규칙: 추가하지 않음
- 후속 matched A/B 비교의 CONTROL 진입: 고정
- 신호일 완료봉 이후 다음 현지 거래일 시가 실행: 모든 exit에 공통 적용
- 미래 데이터, 당일 종가 이후의 가격, 다음 거래일 시가를 신호 판정에 사용하지 않음

## 11. 기존 규칙과의 차이

### 11.1 V2 대비

- 진입 규칙: 변경하지 않음
- Pre-Winner exit: V2의 기존 Loss Guard를 그대로 복제하지 않고, `-15%` 가격 조건과 `WATCH/READY` 주간 구조의 동시 조건으로 구체화함
- Winner HWM 보호: V2에 없던 단계 분류와 V3 HWM 구조를 후보에 포함함

### 11.2 V3 대비

- Pre-Winner: `+20%` 이전의 명시적 `PRICE + STRUCTURE` 실패 규칙을 추가함
- Winner Soft: `WATCH 또는 SETUP`에서 `WATCH/READY`만 사용함
- Winner HWM 밴드: 수치와 경계 처리를 변경하지 않음
- Winner Hard: V3 규칙을 변경하지 않음
- 진입, 실행 시점, 재진입: V2 의미를 유지함

## 12. 규칙 정의의 배경

기존 공식 matched A/B failure review에서 확인된 관찰은 다음과 같다. 이는 후보의 수치와 구조를 임의로 조정하기 위한 새 분석 결과가 아니다.

- V3의 Pre-Winner 구간은 모두 `OPEN_AT_CUTOFF`로 종료되었으며, 해당 구간을 별도 규칙으로 정의할 필요가 있었다.
- `-15%`는 기존 공식 진단에서 Pre-Winner 미래 Winner breach 비율을 확인한 경계 중 하나이다.
- V2 `>=+50%`에서 V3 `<+50%`로 낮아진 사례는 133건이며, 그중 Soft 105건, Hard 28건이었다.
- V2 `>=+100%`에서 V3 `<+100%`로 낮아진 사례는 48건이며, 그중 Soft 34건, Hard 14건이었다.

이에 따라 이 후보에서는 HWM 밴드 자체를 조정하지 않고, Soft의 `SETUP` 적용만 제거하며, Pre-Winner 조기 실패를 가격과 주간 구조의 동시 조건으로 제한한다.

## 13. 자체 검토 체크리스트

- [x] 각 완료 일의 처리 순서와 결과가 결정적이다.
- [x] Pre-Winner와 Winner의 단계 조건이 겹치지 않는다.
- [x] 정확히 `+20%`일 때 Winner로 처리하는 규칙이 명확하다.
- [x] `WATCH`와 `SETUP`의 역할을 혼동하지 않는다.
- [x] `UNAVAILABLE`을 `WATCH`로 매핑하지 않는다.
- [x] Soft와 Hard의 동시 충족 시 Hard 우선이 명확하다.
- [x] V2 진입 규칙을 변경하지 않는다.
- [x] 새 지표나 별도 상태 머신을 추가하지 않는다.
- [x] 예측 백테스트 결과를 근거로 규칙을 추가하지 않는다.

## 14. 다음 단계 경계

현재 산출물은 구체 규칙 정의에 한정한다. 리뷰가 완료되기 전에는 후보 동결, 구현, 테스트, 백테스트, artifact 생성, promotion을 수행하지 않는다. 다음 단계는 별도 승인 후 후보 동결 여부를 검토하는 것이다.
