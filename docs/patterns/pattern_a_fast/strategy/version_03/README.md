# A FAST Core V3 — 검증 대기 후보 전략

> 규칙은 동결됐지만 아직 공식 전략이나 기본 전략이 아니다. 현재 기본 전략은
> `A FAST Core V2`이며, V3는 동일 진입 코호트 비교 검증을 기다리고 있다.

## 후보 상태

- **전략 ID**: `PATTERN_A_FAST_FINAL_STRATEGY_V03`
- **전략 이름**: `A FAST Core V3` / `패스트 코어 V3`
- **청산 계약**: `WINNER_HWM_EXIT_V01`
- **상태**: 규칙 동결 후 비교 검증 대기 (`FROZEN_CANDIDATE_AWAITING_MATCHED_AB`)
- **기준 전략**: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- **현재 기본 전략**: `PATTERN_A_FAST_FINAL_STRATEGY_V02` / `A FAST Core V2`

이 문서는 후보 계약만 고정한다. V3를 공식 전략으로 승격하거나 실전 리포트를
바꾸지 않으며, V2 기본 전략을 대체하지도 않는다. 승격 여부를 판단하기 전에는
V2와 V3를 동일 진입 코호트에서 청산 규칙만 비교하는 A/B 검증이 필요하다.

## 진입 규칙

진입 계약은 V2와 정확히 같다 (`SAME_AS_V02`).

- Pattern A 허용 국면: `TRANSITION` 또는 `EARLY_TREND`
- FAST 상태: `TRIGGER` / `READY`
- 월간 국면 허용: `PERMITTED_REGIME`
- 일봉 위험 허용: `NORMAL` 또는 `ELEVATED`
- FAST 점수 상태: `READY` 또는 `PARTIAL`
- 진입 체결: `NEXT_LOCAL_TRADING_DAY_OPEN`

이 후보에서는 진입 규칙, 유니버스 필터, 캘린더 의미와 임계값을 재조정하지 않는다.

## Winner HWM 청산 규칙

Winner 모드 전에는 `running_raw_MFE < +20%`인 동안 항상 보유하며 V3 청산은
발생하지 않는다. `running_raw_MFE >= +20%`부터 Winner 모드가 시작된다.

`running_raw_MFE = running_highest_HIGH / entry_open - 1`이다. HWM은 진입 후
완료된 일봉 `HIGH` 중 가장 높은 값이다. 매일 완료된 EOD 판단에서 그날의
`HIGH`로 HWM을 갱신하고, 같은 날 완료된 `CLOSE`를 HWM과 비교한다. 장중 판단과
look-ahead는 없다.

| 누적 raw MFE 구간 | Soft 하락폭 | Hard 하락폭 |
| --- | ---: | ---: |
| `+20% <= MFE < +50%` | `-10%` | `-20%` |
| `+50% <= MFE < +100%` | `-15%` | `-25%` |
| `+100% <= MFE < +200%` | `-20%` | `-30%` |
| `+200% <= MFE < +400%` | `-25%` | `-35%` |
| `MFE >= +400%` | `-30%` | `-40%` |

정확한 경계값은 다음 구간에 속한다. 즉 `20/50/100/200/400`은 각 구간의
하한으로 적용된다.

- Soft 청산은 해당 HWM 하락폭을 충족하고 완료된 FAST 상태가 `WATCH` 또는
  `SETUP`일 때 발생한다. `SOFT EXIT SIGNAL`을 만들며 지속 확인이나 추가 확인
  단계는 없다.
- FAST 상태가 `WATCH`/`SETUP`이 아닌 상태에서 Soft 기준을 넘으면 결과는
  `HOLD`다.
- Hard 청산은 가격만으로 판단한다. 해당 HWM 하락폭을 충족하면 FAST 상태와
  관계없이 청산하고, Soft와 Hard가 동시에 발생하면 `HARD`가 우선하며 한
  번만 청산한다.
- 신호는 완료된 일봉 EOD에서 생성하고 다음 로컬 거래일 OPEN에 체결한다.
  지원되는 다음 거래일이 없으면 포지션은 `OPEN_AT_CUTOFF`로 남는다.

## 사용하지 않는 규칙

V3에는 다음 규칙을 사용하지 않는다.

- V2의 고정 `-15%` Pre-PROGRESSED Loss Guard
- V2 `EXIT3` 국면 전이 청산
- V2 `EXIT4` 15포인트 점수 HWM 청산
- `W25`, `W30`, `FAILURE_ARMED`
- persistence exit, Peak Profit Floor, Soft Confirm
- 그 밖의 Pre-Winner 손절 규칙

V3는 recovery, cooldown, re-entry를 생성하지 않는다. V2의 재진입 동작도 변경하지
않는다.

## 자본 운용상의 교환관계

Pre-Winner 구간에는 강제 청산이 없어서 자본이 장기간 묶이거나 큰 미실현 손실이
발생할 수 있다.

이 문서는 백테스트 결과가 아니다. 다음 작업은 V2의 동일 진입 지점을 사용한
청산 전용 matched-cohort A/B 비교이며, 평가자는 진입 필터를 다시 평가하거나
전략별 재진입을 생성해서는 안 된다.
