# A FAST Core 다음 후보 전략 설계 방향

## 문서 성격

이 문서는 다음 후보 전략의 설계 방향을 결정하는 연구 문서이다. 전략 규칙
명세서가 아니며, 새로운 전략 버전·전략 ID·구체 Threshold를 생성하거나 동결하지
않는다. 현재 기본 전략은 계속 `A FAST Core V2`이다.

판단 근거는 다음 자료에 한정한다.

- `docs/patterns/pattern_a_fast/strategy/version_02/README.md`
- `docs/patterns/pattern_a_fast/strategy/version_03/README.md`
- `docs/patterns/pattern_a_fast/validation_plan/version_03_matched_ab_validation.md`
- `docs/patterns/pattern_a_fast/validation/version_03_matched_ab_failure_review.md`
- `artifacts/backtests/fastcore_v3_matched_ab_official_v01/summary.json`
- `artifacts/backtests/fastcore_v3_failure_review_v01/summary.json`
- `artifacts/backtests/fastcore_v3_failure_review_v01/pre_winner_threshold_diagnostics.csv`
- `artifacts/backtests/fastcore_v3_failure_review_v01/winner_side_effect_diagnostics.csv`

## 결론 요약

다음 후보의 기본 아키텍처는 `TWO_PHASE_EXIT_ARCHITECTURE`로 결정한다.

1. `Phase 1 — Pre-Winner failure protection`
   - 범위: `running_raw_MFE < +20%`
   - 목적: V3처럼 실패 거래를 cutoff까지 방치하지 않으면서, 단일 고정 손실률로
     미래 Winner를 과도하게 제거하지 않는 것
2. `Phase 2 — Winner HWM profit protection`
   - 범위: `running_raw_MFE >= +20%`
   - 목적: V3에서 확인된 중간 성과와 giveback 개선을 보존하되, 대형 Winner를
     너무 일찍 청산하는 tail cost를 줄이는 것

공식 failure review의 분류는 Pre-Winner `PRIMARY_FAILURE_SOURCE`, Winner HWM
`PROMISING_WITH_TAIL_COST`, 후속 연구 `NEW_CANDIDATE_JUSTIFIED`로 유지한다.
Pre-Winner 연구 방향은 `PRICE_PLUS_STRUCTURE`로 결정한다. Winner HWM 연구 방향은
`RETAIN_HWM_REDESIGN_SOFT`로 결정한다. 다음 작업 결정은
`DEFINE_NEW_CANDIDATE_RULES`이다. 다만 구체 규칙 정의는 이 문서가 아닌 별도 작업에서
수행한다.

## 공식 근거와 현재 상태

공식 matched A/B는 973건이며, V3는 공식 채택 및 기본 전략 승격 기준을 통과하지
못했다. 전체 mean return은 V2 `8.860421%`, V3 `8.666341%`로 V3가 우세하지 않았다.
반면 median return은 V2 `-15.14%`, V3 `9.20%`로 개선되었다. 따라서 V3를 전체적으로
채택하거나 전부 폐기하는 이분법은 데이터와 맞지 않는다.

현재 운영 기준은 다음과 같이 유지한다.

- 기본 전략: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- V2의 진입 계약과 재진입 의미: 변경하지 않음
- V3: 공식 전략이 아닌 실패 후보로 유지
- 새 후보: 아직 생성·명세·동결하지 않음

## Pre-Winner 보호 문제

V3의 가장 큰 구조적 문제는 +20% Winner activation 이전에 별도 청산이 없다는 점이다.
전체 973건 중 Pre-Winner는 236건이며, 이 236건은 모두 +20% activation에 도달하지
않았다. V3에서는 236건 전부가 `OPEN_AT_CUTOFF`로 남았고, mean/median return은
`-37.333559% / -34.4%`, median holding은 `468.5일`이었다. `<= -30%`는 138건,
`<= -40%`는 110건이었다.

따라서 다음 후보는 Pre-Winner를 무기한 보유하는 구조를 그대로 유지하지 않는다.
이 구간의 목표는 수익률을 극대화하는 것이 아니라 다음 질문에 답하는 실패 탐지이다.

> 아직 Winner가 되지 못한 거래 중 실패 가능성이 충분히 높아진 거래를 어떻게
> 식별하고 종료할 것인가?

### 고정 손실률 단독 사용이 부적절한 이유

진단용으로 계산한 단순 가격 손실선은 Pre-Winner를 많이 포착하지만 미래 Winner도
상당수 포함한다. Winner-capable 737건의 +20% activation 이전 가격 경로에서 다음
손실선이 먼저 발생한 비율은 다음과 같다.

| 진단선 | Pre-Winner breach rate | Winner-capable pre-activation breach rate |
|---:|---:|---:|
| `-10%` | `95.338983%` | `51.83175%` |
| `-15%` | `93.220339%` | `39.077341%` |
| `-20%` | `88.559322%` | `28.222524%` |
| `-30%` | `75.847458%` | `15.87517%` |

이 값들은 새 손절선을 선택하기 위한 비교가 아니다. 각 후보선이 실패 거래와 미래
Winner를 동시에 포함한다는 구조적 사실을 보여주는 진단 결과이다. 추가로 V2 Loss
Guard로 청산됐지만 full-path 기준으로는 Winner-capable이었던 거래가 387건이었다.
그러므로 단일 가격 Threshold 하나를 Pre-Winner 최종 판정으로 되살리는 방향은
채택하지 않는다.

## Winner HWM의 부분적 유효성과 부작용

Winner-capable 737건에서 V3는 V2보다 다음 성과를 보였다.

- mean return: `16.595617%` → `23.396296%`
- median return: `-14.29%` → `13.95%`
- paired mean delta: `+6.800678%p`
- paired median delta: `+20.09%p`
- improved / worsened / same: `512 / 222 / 3`

이 결과는 +20% activation과 HWM 추적을 전부 폐기할 근거가 아니다. Winner phase를
분리하고 HWM을 사용해 이익을 추적하는 발상은 다음 후보에서도 유지할 연구 가치가
있다.

그러나 tail upside 훼손은 명확하다.

- V2 `>= +50%`였으나 V3 `< +50%`: `133건`
  - Soft Exit `105건`, Hard Exit `28건`
- V2 `>= +100%`였으나 V3 `< +100%`: `48건`
  - Soft Exit `34건`, Hard Exit `14건`

특히 Soft Exit에서 대형 Winner 훼손이 많이 발생했다. 따라서 Soft Exit는 현재
발동 방식과 FAST `WATCH/SETUP` 결합 방식을 재검토해야 한다. Hard Exit도 훼손 사례가
있으므로 검증 완료된 정답으로 동결하지 않는다. 다음 후보에서 Hard protection은
유지 후보일 뿐, 별도 검증 대상이다.

## 다음 후보의 기본 구조

### Phase 1: Pre-Winner failure protection

범위는 `running_raw_MFE < +20%`로 고정된 개념을 유지한다. 이 구간에서는 다음 두
종류의 정보를 최소 조합으로 검토한다.

- 가격 상태: entry 대비 손상, 회복 실패, 저점 갱신 또는 이와 동등한 가격 경로 정보
- 구조 상태: FAST weekly lifecycle 악화, TRIGGER 이후 `WATCH/SETUP` 회귀, Pattern A
  구조 약화 또는 기존 상태 계약의 실패 정보

핵심은 가격 상태와 구조 상태가 함께 실패를 가리킬 때를 연구하는 것이다. 가격이
흔들렸다는 사실만으로 종료하거나, 구조 상태가 회복될 때까지 가격 손상을 무제한
허용하는 방식은 모두 피한다.

이번 단계에서는 다음을 정하지 않는다.

- 가격 손실 Threshold
- 관찰 기간 또는 보유일수 Threshold
- FAST state 조합과 우선순위
- 회복 확인 횟수
- 종료 체결 규칙의 세부 조건

### Phase 2: Winner HWM profit protection

`running_raw_MFE >= +20%`라는 phase separation은 유지 연구한다. Winner 구간에서는
다음 개념을 보존한다.

- 진입 이후 running HIGH 기반 HWM
- HWM 대비 하락을 이용한 이익 보호
- 큰 하락에서 작동하는 Hard protection 개념

다음 항목은 재설계 대상으로 분리한다.

- Soft Exit의 발동 방식
- Soft Exit에서 FAST `WATCH/SETUP`을 사용하는 방식
- Soft Exit가 대형 Winner의 장기 추세 중간 조정을 조기 종료로 해석하는 문제
- Hard Exit와 Soft Exit가 동시에 고려되는 경우의 역할 분리

다음 후보는 Winner를 빨리 실현하는 것이 아니라 큰 Winner를 오래 유지하면서 이미
확보한 수익의 과도한 반납을 제한하는 것을 목표로 한다. 다만 Hard protection의
정확한 경계와 우선순위도 후속 matched 검증 전에는 확정하지 않는다.

## 설계 원칙

1. **Pre-Winner와 Winner를 분리한다.**
   - 하나의 청산 규칙으로 전 구간을 처리하지 않는다.
2. **Pre-Winner에서는 실패를 탐지한다.**
   - 단기 흔들림을 모두 손실로 간주하지 않되, 실패 가능성이 높아진 상태를 무한히
     보유하지 않는다.
3. **Winner에서는 수익을 보존한다.**
   - phase activation 이후의 목적을 손실 회피가 아니라 추세 확장과 이익 보호로
     구분한다.
4. **고정 손절 단독 사용을 금지한다.**
   - 진단 결과에서 `-10%`부터 `-30%`까지 미래 Winner의 pre-activation breach가
     `15.87517%`~`51.83175%` 발생했다.
5. **변수를 최소화한다.**
   - 최초 연구는 가격 상태 1개와 구조/상태 정보 1개 수준에서 시작하고, 세 번째
     조건은 필요성이 확인될 때만 검토한다.
6. **기존 Pattern A FAST 체계를 우선 활용한다.**
   - 새 지표 체계를 먼저 만들지 않고 FAST weekly lifecycle, Pattern A stage,
     가격/HWM/MFE, 보유 기간을 우선 사용한다.
7. **V2의 진입 계약은 건드리지 않는다.**
   - 다음 후보 비교에서도 진입 신호와 진입 코호트가 청산 연구의 결과에 의해
     바뀌지 않도록 한다.

## 설계 대안 비교

### 대안 A: `PRICE_PLUS_STRUCTURE`

개념적으로 가격 손상과 FAST 구조 실패를 함께 검토한다.

- 장점: 단일 가격 손절보다 미래 Winner 보호 가능성이 있고, 이미 계산되는 FAST
  상태를 재사용할 수 있다.
- 위험: FAST 구조 악화가 늦게 나타나면 큰 손실 뒤에 종료될 수 있다.
- 판단: 가격 정보와 구조 정보를 최소 조합하는 이번 방향과 일치한다.

### 대안 B: `TIME_PLUS_STRUCTURE`

일정 기간 동안 Winner에 도달하지 못하고 FAST 구조도 회복하지 못하는 상황을
검토한다.

- 장점: 초기 변동성과 느린 Winner를 더 오래 허용할 수 있다.
- 위험: 가격 손상이 먼저 커질 수 있고, 시간 자체가 실패를 충분히 설명하지 못할
  수 있다.
- 판단: 보조 가설로는 유효하지만 최초 구조의 단독 축으로 선택하지 않는다.

### 대안 C: `MINIMAL_HYBRID`

가격·시간·구조를 모두 필수로 묶지 않고 최소 조합을 찾는 방향이다.

- 장점: 가격만 보거나 구조만 기다리는 양극단을 피할 수 있다.
- 위험: 조건이 빠르게 늘어나면 해석 가능성과 사전등록 가능성이 떨어진다.
- 판단: 장기적인 설계 원칙으로는 유효하지만, 최초 다음 후보의 명시적 방향은
  `PRICE_PLUS_STRUCTURE`로 제한한다.

## 이번 작업의 결정

### A. 다음 후보 아키텍처

`TWO_PHASE_EXIT_ARCHITECTURE`

- Phase 1: Pre-Winner failure protection
- Phase 2: Winner HWM profit protection

V3에서 확인된 +20% phase separation과 HWM 개념은 연구 대상으로 유지하고,
Pre-Winner 보호는 독립 모듈로 분리한다.

### B. Pre-Winner 연구 방향

`PRICE_PLUS_STRUCTURE`

근거는 다음과 같다.

- Pre-Winner 236건은 V3에서 모두 cutoff까지 남았고 terminal loss가 크게 악화됐다.
- 단순 가격선은 Pre-Winner breach rate가 높지만 Winner-capable pre-activation
  breach도 `15.87517%`~`51.83175%`로 높다.
- 따라서 가격 상태만으로는 부족하고, 기존 FAST 구조 정보를 함께 사용해 오탐을
  줄이는 방향이 필요하다.

### C. Winner 연구 방향

`RETAIN_HWM_REDESIGN_SOFT`

근거는 다음과 같다.

- Winner-capable mean/median return과 paired delta는 개선되었다.
- 동시에 V2 `>=+50%` 중 133건, `>=+100%` 중 48건이 V3에서 해당 tail을 잃었다.
- 대형 Winner 훼손은 Soft Exit에서 각각 105건과 34건으로 더 많이 발생했다.
- Hard Exit도 각각 28건과 14건의 훼손이 있어 Hard-only를 정답으로 확정하지 않는다.

### D. 다음 작업

`DEFINE_NEW_CANDIDATE_RULES`

다음 별도 작업에서만 위 두 모듈의 구체 규칙을 정의한다. 그 작업에서도 먼저
사전등록 가능한 최소 변수와 matched 평가 계약을 정하고, V2 진입 코호트를 유지한
상태에서 검증한다. 이번 문서에서는 새 전략 버전이나 규칙을 만들지 않는다.

## 후속 작업에서 구체화할 항목

다음 단계는 아래 항목의 정의만 다룬다.

- Pre-Winner 가격 상태의 관측 의미
- FAST 구조 실패의 관측 의미와 완료 시점
- 두 정보의 결합 논리와 fail-closed 처리
- +20% activation 시점의 phase 전환 의미
- Winner HWM 추적과 Soft/Hard 역할 분리
- 다음 로컬 거래일 OPEN 체결 의미
- 동일 진입 matched 평가의 지표와 실패 기준
- 대형 Winner 보존과 대형 손실 억제의 우선순위

다음 항목은 구체화 대상에서 제외한다.

- 이번 문서에서 새로운 stop Threshold 선택
- 특정 보유일수 선택
- 특정 FAST state 조합 확정
- HWM Soft/Hard 수치 변경
- V4/V3.1 생성
- production 반영 또는 자동매매 승인

## 상태 및 제한

- V2 기본 전략: 유지
- V3 공식 채택: 실패 유지
- 새 후보 전략 버전: 생성하지 않음
- 새 전략 ID: 생성하지 않음
- 코드 수정: 없음
- 백테스트: 실행하지 않음
- 테스트: 실행하지 않음
- 외부 API 및 데이터 갱신: 없음
- 기존 공식 A/B artifact: 수정하지 않음
- 새 artifact: 생성하지 않음

이 문서는 다음 후보의 설계 방향만 결정한다. `DEFINE_NEW_CANDIDATE_RULES`는 별도
승인·지시가 있는 후속 단계에서 수행한다.
