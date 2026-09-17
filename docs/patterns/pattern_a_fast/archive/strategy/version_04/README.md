# A FAST Core V4 — 종료된 후보 전략·역사 기록

> 이 문서는 종료된 V4 후보 전략의 규칙과 당시 판단을 보존하는 역사 기록이다.
> 현재 일반 종목 기본 전략은 `A FAST Core V2`이며, V4 연구는 재개하지 않는다.

## 문서 역할

- **전략 버전**: A FAST Core V4
- **현재 역할**: 종료된 후보 전략·역사 기록
- **현재 상태**: 검증 대기 상태가 아닌 종료된 기록
- **현재 사용 여부**: 공식 전략과 기본 전략으로 사용하지 않음
- **관련 기준 문서**: [A FAST 전략 안내](../README.md), [V2 현재 기본 전략](../version_02/README.md)

## 1. 전략 식별

- 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V04`
- 전략 이름: `A FAST Core V4`
- 한국어 통용명: `패스트 코어 V4`
- 청산 계약: `TWO_PHASE_PRICE_STRUCTURE_HWM_EXIT_V01`
- 상태: 종료된 후보 전략 기록
- 기준 전략: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- 현재 기본 전략: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- 당시 검증 계획 기록: [V4 동일 진입 matched A/B 검증 계획](../../validation_plan/version_04_matched_ab_validation.md)
- 생애주기 단계: 후보 전략 동결 후 종료된 역사 기록

V4는 검증 전에 동결된 후보 전략이다. 공식 전략이나 기본 전략으로 채택되지
않았으며, 현재 기본 전략은 계속 V2이다. 아래의 규칙과 검증 계획 표현은 당시
후보를 정의한 맥락을 보존하는 것이며 현재 진행 중인 작업을 뜻하지 않는다.

## 2. 목적과 동결 원칙

V2의 진입 계약을 유지하면서 청산을 두 단계로 구분한다.

1. `+20%` Winner 도달 전에는 가격 손실과 주간 FAST 구조의 동시 조건으로 조기 실패를 정의한다.
2. `+20%` Winner 도달 후에는 V3의 HWM 보호 밴드를 유지하고 Winner Soft의 구조 조건에서 `SETUP`을 제외한다.

이 문서에 정의된 규칙은 검증 전에 동결된다. 이후 검증 결과를 보고 V4의 규칙을 수정하지 않는다. 변경이 필요하면 V4를 수정하지 않고 새 후보를 다시 정의하고 동결한다.

## 3. 진입 계약

진입 의미는 `SAME_AS_V02`이다. `TRIGGER`와 `READY`는 서로 다른 필드이며 대체 가능한 상태가 아니다.

- Pattern A Stage: `TRANSITION` 또는 `EARLY_TREND`
- FAST Machine Stage: `TRIGGER`
- FAST Machine Stage Status: `READY`
- Monthly: `PERMITTED_REGIME`
- Daily Risk: `NORMAL` 또는 `ELEVATED`
- FAST Score Status: `READY` 또는 `PARTIAL`
- Entry execution: `NEXT_LOCAL_TRADING_DAY_OPEN`

진입 시점과 진입 가격은 V2와 동일하다. 당시 계획된 matched A/B 청산 검증에서도
CONTROL 진입 코호트는 고정하며, 후보별 독립 진입 차이를 만들지 않는 조건이었다.

## 4. 공통 정의

### 4.1 running raw MFE

```text
running_raw_MFE = running_highest_completed_daily_HIGH / entry_open - 1
```

- HWM은 진입 이후 완료된 일봉의 HIGH 중 최고값이다.
- `entry_open`은 V2와 동일한 진입 기준값이다.
- HWM은 완료 일봉의 HIGH로 갱신한다.
- 청산 판단 가격은 완료 일봉의 CLOSE를 사용한다.
- running raw MFE는 한 방향으로만 단계가 진행되는 기준이다.

### 4.2 Phase 구분

Pre-Winner:

```text
running_raw_MFE < +20%
```

Winner:

```text
running_raw_MFE >= +20%
```

정확히 `+20.0%`인 값은 Winner가 소유한다. Winner가 한 번 활성화되면 Pre-Winner로 돌아가지 않는다.

### 4.3 완료 EOD 처리 순서

각 완료 거래일에는 다음 순서로 처리한다.

1. 당일 HIGH로 HWM을 갱신한다.
2. 갱신한 HWM으로 running raw MFE를 계산한다.
3. Pre-Winner 또는 Winner를 판정한다.
4. 판정된 Phase의 청산 규칙만 평가한다.

같은 날 처음 `+20%`에 도달하면 그날부터 Winner 규칙만 평가한다. 해당 일의 Pre-Winner 규칙을 소급 적용하지 않는다.

### 4.4 주간 FAST 구조

구조 판정은 최신 완료 Weekly FAST의 다음 두 필드를 사용한다.

- `Stage`
- `Stage Status`

`WATCH/READY`는 `Stage == WATCH`와 `Stage Status == READY`의 조합이다. `UNAVAILABLE`을 `WATCH`로 매핑하거나 대체하지 않는다.

## 5. Pre-Winner 청산

Pre-Winner에서는 다음 가격 조건과 구조 조건을 동시에 만족할 때만 청산한다.

### 5.1 가격 조건

```text
daily_close / entry_open - 1 <= -15%
```

정확히 `-15.0%`인 값도 포함한다.

### 5.2 구조 조건

최신 완료 Weekly FAST가 다음을 모두 만족해야 한다.

```text
Stage == WATCH
AND
Stage Status == READY
```

### 5.3 신호와 체결

- 신호: `PRE_WINNER_PRICE_STRUCTURE_FAILURE`
- 체결: `NEXT_LOCAL_TRADING_DAY_OPEN`

두 조건 중 하나라도 충족하지 않으면 `HOLD`한다.

다음 조건은 Pre-Winner 청산으로 보지 않는다.

- 가격만 `-15%` 이하인 경우
- `SETUP / READY`
- `TRIGGER`
- `TREND`
- `EXTENDED`
- `UNAVAILABLE`
- Stage Status가 `READY`가 아닌 경우

시간 손절, persistence, `FAILURE_ARMED`, recovery counter, 추가 확인 규칙, 새로운 지표와 상태를 사용하지 않는다.

## 6. Winner HWM 밴드

V3의 기존 HWM 밴드와 수치를 그대로 동결한다.

| running raw MFE | Soft DD | Hard DD |
|---|---:|---:|
| `+20% <= MFE < +50%` | `-10%` | `-20%` |
| `+50% <= MFE < +100%` | `-15%` | `-25%` |
| `+100% <= MFE < +200%` | `-20%` | `-30%` |
| `+200% <= MFE < +400%` | `-25%` | `-35%` |
| `MFE >= +400%` | `-30%` | `-40%` |

정확히 `+50%`, `+100%`, `+200%`, `+400%`에 도달한 값은 각각 다음 밴드의 하한이 소유한다. 경계에 도달한 즉시 다음 밴드의 Soft/Hard 임계값을 적용한다.

HWM은 완료 일봉 HIGH 기준으로 갱신하고, 청산 판단 가격은 완료 일봉 CLOSE로 한다. HWM 밴드의 수치와 경계 처리는 V3에서 변경하지 않는다.

## 7. Winner Soft Exit

다음 세 조건을 모두 만족할 때 Winner Soft Exit를 발생시킨다.

```text
HWM drawdown >= active Soft threshold
AND
latest completed Weekly FAST Stage == WATCH
AND
Stage Status == READY
```

- 신호: `WINNER_SOFT_WATCH_EXIT`
- 체결: `NEXT_LOCAL_TRADING_DAY_OPEN`

`SETUP`은 Soft Exit 조건에 포함하지 않는다. 주간 구조가 `UNAVAILABLE`이거나 Stage Status가 `READY`가 아닌 경우에도 Soft Exit를 발생시키지 않는다.

## 8. Winner Hard Exit

```text
HWM drawdown >= active Hard threshold
```

- FAST 주간 구조와 무관하게 평가한다.
- 가격 조건만으로 판단한다.
- 신호: `WINNER_HARD_EXIT`
- 체결: `NEXT_LOCAL_TRADING_DAY_OPEN`

Soft와 Hard가 같은 날 모두 충족되면 Hard가 우선한다. Hard 규칙은 이 후보에서 새로 검증하거나 확정한 것이 아니라 V3 요소를 그대로 유지한 것이다.

## 9. Cutoff와 실행 시점

- 모든 청산 신호는 완료 EOD에 판정한다.
- 실제 청산 체결은 `NEXT_LOCAL_TRADING_DAY_OPEN`으로 한다.
- 지원 가능한 다음 로컬 거래일이 없으면 `OPEN_AT_CUTOFF`로 종료한다.
- same-day exit를 사용하지 않는다.
- look-ahead를 사용하지 않는다.
- 당일 종가 이후의 가격이나 다음 거래일 시가를 신호 판정에 사용하지 않는다.

## 10. 재진입

전략 의미는 `SAME_AS_V02`이다.

- 포지션 완전 종료 후 새 Entry Contract를 충족하면 독립 재진입을 허용한다.
- pyramiding은 금지한다.
- 동일 종목 동시 보유는 금지한다.
- 청산 후 상태는 완전히 리셋한다.
- 당시 후속 청산 규칙 matched A/B 검증 계획에서는 CONTROL 진입 코호트를 고정하며
  후보별 독립 재진입을 생성하지 않는 조건이었다.

## 11. V2 및 V3 대비 변경

### 11.1 V2 대비

- 진입 계약은 동일하다.
- 단독 `-15%` Loss Guard는 사용하지 않는다.
- Pre-Winner에 `-15% + WATCH/READY` 동시 실패 규칙을 사용한다.
- V2 Exit3와 Exit4는 사용하지 않는다.
- `+20%` Winner Phase를 도입한다.
- Winner에 HWM 청산을 적용한다.

### 11.2 V3 대비

- Pre-Winner 보호 규칙을 추가한다.
- Winner 활성화 기준 `+20%`를 유지한다.
- HWM 밴드와 임계값을 유지한다.
- Hard Exit를 유지한다.
- Soft 구조 조건을 `WATCH 또는 SETUP`에서 `WATCH` 및 Stage Status `READY`로 축소한다.
- 실행 시점과 재진입 의미는 변경하지 않는다.

## 12. 원본 규칙과의 일치

`docs/patterns/pattern_a_fast/research/next_candidate_rule_spec_v01.md`의 의미를 다음과 같이 1:1로 동결한다.

- `TRIGGER`와 `READY`를 같은 필드로 표현하지 않는다.
- 정확히 `+20%`인 날은 Winner를 우선한다.
- Pre-Winner는 `-15% + WATCH/READY`일 때만 청산한다.
- `SETUP`은 Pre-Winner 청산과 Winner Soft에서 제외한다.
- `UNAVAILABLE`은 fail-safe `HOLD`로 유지한다.
- HWM band는 변경하지 않는다.
- Hard 우선순위는 변경하지 않는다.
- 실행 시점은 변경하지 않는다.
- 재진입 의미는 변경하지 않는다.

## 13. 동결 선언

- 규칙은 검증 전에 동결되었다.
- 이후 결과를 보고 V4 규칙을 수정하지 않는다.
- 변경이 필요하면 새 후보로 다시 정의하고 동결한다.
- V4는 아직 공식 전략이 아니다.
- V2가 계속 현재 기본 전략이다.
- 문서 작성 당시에는 전략 생애주기 4단계인 검증 계획 확정을 후속 항목으로
  기록했다. 현재 진행 중인 작업이 아니다.
