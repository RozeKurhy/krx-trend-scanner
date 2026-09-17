# A FAST Core V4 동일 진입 A/B 검증 계획

## 문서 목적과 상태

> 이 문서는 동결 후보 `A FAST Core V4` 검증을 위해 작성했던 과거 A/B 검증
> 계획을 보존하는 역사 기록이다. 현재 진행 중인 검증이나 현재 유효한 확정
> 계획을 의미하지 않는다.

당시에는 `A FAST Core V4`와 현재 기본 전략 `A FAST Core V2`를 동일한 진입
코호트에서 비교하기 위해 비교 대상, 고정 진입, 데이터 범위, 평가 지표, 실패
수리 기준, 공식 전략 채택 기준과 기본 전략 승격 기준을 사전 확정했다. 당시
문서는 전략 생애주기의 **4단계: 검증 계획 확정**에 해당했으며, 계획 작성
작업에서는 백테스트, 코드 구현, 테스트 실행, 결과 생성과 산출물 생성을
수행하지 않았다.

당시 계획에서는 결과를 확인한 뒤 합격 기준이나 비교 조건을 변경하지 않도록
했다. 규칙 변경이 필요하면 V4를 수정하지 않고 새 후보 전략으로 다시 정의·동결
한다는 원칙을 기록했다.

## 1. 기준 문서와 기존 결과물

다음 문서와 결과물을 기준으로 확인한다.

- `docs/strategies/strategy_lifecycle.md`
- `docs/patterns/pattern_a_fast/strategy/version_02/README.md`
- `docs/patterns/pattern_a_fast/strategy/version_03/README.md`
- `docs/patterns/pattern_a_fast/strategy/version_04/README.md`
- `docs/patterns/pattern_a_fast/validation_plan/version_03_matched_ab_validation.md`
- `docs/patterns/pattern_a_fast/validation/version_03_matched_ab_failure_review.md`
- `artifacts/backtests/fastcore_v3_matched_ab_official_v01/summary.json`
- `artifacts/backtests/fastcore_v3_failure_review_v01/summary.json`
- `artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv`
- `artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json`

기존 V3 결과는 V4의 합격 여부를 미리 판단하는 데 사용하지 않는다. 고정 비교 조건과 V3의 두 실패 모드 기준선을 정의하는 근거로만 사용한다.

## 2. 비교 대상

### 기준 전략: A FAST Core V2

- 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- 현재 기본 전략
- 비교 기준: 기존 V2 `CONTROL` 거래의 실제 진입 코호트
- 청산 계약: 기존 CONTROL의 Pre-PROGRESSED `-15%` Loss Guard, PROGRESSED Exit 3, Exit 4

### 후보 전략: A FAST Core V4

- 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V04`
- 청산 계약: `TWO_PHASE_PRICE_STRUCTURE_HWM_EXIT_V01`
- 동결 규칙: `docs/patterns/pattern_a_fast/strategy/version_04/README.md`
- 당시 계획상 상태: 규칙 동결 후 동일 조건 비교 백테스트를 계획한 상태
- 현재 상태: 종료된 후보 전략·역사 기록
- 현재 공식 전략이 아니며 기본 전략도 아님

### 보조 진단 기준: A FAST Core V3

- V3는 공식 채택 비교 대상이 아니다.
- V3는 V4가 수리하려는 두 실패 모드의 진단 기준선으로만 사용한다.
- 공식 전략 채택과 기본 전략 승격의 최종 비교 대상은 V2이다.

이번 비교에서 달라지는 요소는 청산 규칙뿐이라는 조건을 당시 고정했다. 진입
규칙, 진입 시점, 진입 가격, 데이터 범위, 캘린더 의미와 기준일은 V2와 V4에서
동일하게 유지하도록 기록했다.

## 3. 고정 CONTROL 진입 코호트

### 기준 파일

- `artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv`
- `artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json`

### 고정 값

| 항목 | 고정 값 |
| --- | ---: |
| 평가 시작일 | `2021-04-01` |
| 신호 기준일 | `2026-08-14` |
| 체결 지원 종료일 | `2026-08-21` |
| CONTROL 거래 수 | `973건` |
| 고유 종목 수 | `542개` |
| 최종 평가일 | `2026-08-21 CLOSE` |

V2와 V4는 CONTROL의 동일한 `973개` 진입을 사용한다. V4 전용 진입 재스캔, 추가 필터, overlap 제거, 진입 코호트 재선정, 전략별 독립 재진입 생성은 금지한다.

## 4. 비교 무결성

공식 성과 비교에 앞서 다음 조건을 모두 확인한다.

- 동일 진입 거래 수 = `973`
- 고유 종목 수 = `542`
- 진입 신호일 일치율 = `100%`
- 진입 체결일 일치율 = `100%`
- 진입 시가 일치율 = `100%`
- 누락 = `0`
- 중복 identity = `0`
- 임의 제외 = `0`
- 공통 기준일 동일
- 미래 데이터 / 미래 참조(look-ahead) 없음
- 외부 네트워크 요청 = `0`

하나라도 실패하면 성과 비교를 공식 결과로 채택하지 않고 검증을 중단하여 무결성 실패 사유를 기록한다.

각 CONTROL 거래의 다음 항목은 V2와 V4 재현 과정 사이에 동일해야 한다.

- `ticker` 및 identity
- 진입 신호일
- 진입 체결일
- 진입 시가
- 진입 당시 데이터 범위
- 캘린더 의미
- 공통 기준일

## 5. 데이터와 체결 의미

- 동일 저장소의 V2 로컬 가격 데이터를 사용한다.
- 외부 API, 네트워크 요청, 캐시 갱신, 누락 데이터 자동 다운로드를 사용하지 않는다.
- 식별자 생애주기와 Point-in-Time(PIT) 원칙을 유지한다.
- 완료된 정보만 사용한다.
- 미래 주가, 미래 거래량, 미래 Stage, 미래 성공 여부를 현재 판단에 사용하지 않는다.
- 데이터 누락·손상·식별자 불일치는 실패 시 종료(`fail-closed`)로 처리한다.

공통 기간은 다음과 같다.

- 평가 시작일: `2021-04-01`
- 신호 기준일: `2026-08-14`
- 체결 지원 종료일: `2026-08-21`
- 최종 평가일: `2026-08-21 CLOSE`

V2 CONTROL은 기존 진입·청산·체결 의미를 그대로 사용한다. V4는 동결된 V4 README의 규칙을 그대로 적용한다.

- 청산 신호: 완료된 일봉 EOD에서 판단
- 청산 체결: 다음 로컬 거래일 `OPEN`
- 지원되는 다음 거래일이 없으면 `OPEN_AT_CUTOFF`
- 장중 판단과 미래 참조 금지

## 6. V4 계약 식별

검증 계획에서 V4 규칙을 다시 정의하거나 수정하지 않는다. 검증 실행 시 다음 식별만 확인한다.

- Entry: `SAME_AS_V02`
- Pre-Winner: `running_raw_MFE < +20%`
- Pre-Winner Exit: 완료 일봉 종가 수익률 `<= -15%`이고 최신 완료 Weekly FAST가 `WATCH / READY`인 경우의 동시 조건
- Pre-Winner signal: `PRE_WINNER_PRICE_STRUCTURE_FAILURE`
- Winner: `running_raw_MFE >= +20%`
- Winner Soft: V3 Soft HWM band 유지, `WATCH / READY`만 허용, `SETUP` 제외
- Winner Soft signal: `WINNER_SOFT_WATCH_EXIT`
- Winner Hard: V3 Hard HWM band 유지, 가격 단독
- Winner Hard signal: `WINNER_HARD_EXIT`
- Soft + Hard 동시 충족: Hard 우선
- Execution: `NEXT_LOCAL_TRADING_DAY_OPEN`
- 지원 범위 종료: `OPEN_AT_CUTOFF`

V4 규칙은 결과를 보고 수정하지 않는다.

## 7. 평가 지표

모든 성과 수치는 동일한 `973` 동일 진입 거래를 기준으로 V2와 V4를 각각 산출한다. 동일 거래 비교를 우선한다.

### A. 전체 수익 특성

- 평균 최종 수익률
- 중앙값 최종 수익률
- 양수 거래 수 / 비율
- V4 - V2 동일 거래 수익률 차이의 평균
- V4 - V2 동일 거래 수익률 차이의 중앙값
- 개선 / 악화 / 동일

### B. 손실 위험

- 평균 / 중앙값 MAE
- 최종 수익률 `<= -15%`
- `<= -20%`
- `<= -30%`
- `<= -40%`
- 데이터에 이미 존재하면 `<= -50%`, `<= -60%`

### C. Winner 보존

최종 수익률 기준으로 다음 구간의 거래 수와 비율을 기록한다.

- `>= +20%`
- `>= +30%`
- `>= +50%`
- `>= +100%`
- `>= +200%`
- `>= +400%`

### D. 수익 되돌림

```text
giveback = strategy_path_MFE - terminal_return
```

V2와 V4 각각의 평균과 중앙값을 기록한다. 기존 공식 A/B 결과와 같은 의미를 사용한다.

### E. 보유 기간과 자본 묶임

- 평균 보유 기간
- 중앙값 보유 기간
- P90 보유 기간
- `OPEN_AT_CUTOFF` 건수 / 비율

### F. 청산 이유

V2:

- Loss Guard
- Exit3
- Exit4
- OPEN_AT_CUTOFF

V4:

- `PRE_WINNER_PRICE_STRUCTURE_FAILURE`
- `WINNER_SOFT_WATCH_EXIT`
- `WINNER_HARD_EXIT`
- `OPEN_AT_CUTOFF`

각 청산 이유별로 다음을 기록한다.

- 거래 수 / 비율
- 평균 / 중앙값 최종 수익률
- MAE
- MFE
- 보유 기간

## 8. 공통 전체 경로 MFE 코호트

전략별 청산과 독립된 공통 진단값을 다음과 같이 정의한다.

```text
full_path_raw_MFE =
max(daily HIGH from entry through common cutoff) / entry_open - 1
```

다음 두 코호트를 고정한다.

### Pre-Winner 코호트

```text
full_path_raw_MFE < +20%
```

기존 공식 기준으로 `236건`이다.

### Winner 활성화 가능 코호트

```text
full_path_raw_MFE >= +20%
```

기존 공식 기준으로 `737건`이다.

`973 = 236 + 737`이 성립해야 한다. 이 값은 청산 신호가 아니며 진단 분류에만 사용한다.

## 9. V4 설계 목적 검증: 수리 관문

V4는 V3의 두 실패 모드를 수리하기 위해 만든 후보이다. 따라서 일반 성과와 별도로 다음 두 수리 관문을 사전등록한다.

### 관문 1 — Pre-Winner 수리

Pre-Winner `236건`에서 V4가 V3보다 다음 네 항목을 모두 개선해야 한다.

1. 최종 수익률 `<= -30%` 비율 `< V3`
2. 최종 수익률 `<= -40%` 비율 `< V3`
3. 중앙값 보유 기간 `< V3`
4. `OPEN_AT_CUTOFF` 비율 `< V3`

기존 V3 기준선:

- `<= -30%`: `138 / 236`
- `<= -40%`: `110 / 236`
- 중앙값 보유 기간: `468.5`
- `OPEN_AT_CUTOFF`: `236 / 236`

네 항목을 모두 만족하면 `PRE_WINNER_REPAIR_PASS`로 판정한다. 새 최소 개선폭은 추가하지 않으며, V3보다 실제로 개선됐는지만 본다.

### 관문 2 — Winner 꼬리 수리

Winner 활성화 가능 코호트 `737건`에서 V3의 대형 Winner 훼손을 줄였는지 확인한다.

기존 V3 기준선:

- V2 `>= +50%`였으나 V3 `< +50%`: `133건`
- V2 `>= +100%`였으나 V3 `< +100%`: `48건`

V4는 다음 두 조건을 모두 만족해야 한다.

1. V2 `>= +50%` → V4 `< +50%` 훼손 건수 `< 133`
2. V2 `>= +100%` → V4 `< +100%` 훼손 건수 `< 48`

두 조건을 모두 만족하면 `WINNER_TAIL_REPAIR_PASS`로 판정한다. Soft/Hard별 훼손 건수도 기록하되 별도 합격 임계값은 추가하지 않는다.

## 10. 일반 성과 개선 경로

비교 무결성 PASS를 전제로, V2 대비 다음 A/B/C 중 하나 이상 PASS가 필요하다. 별도 통계적 유의성 임계값이나 임의 최소 개선폭은 만들지 않는다.

### Path A — 수익 개선

다음을 모두 만족한다.

- 평균(V4 - V2 동일 거래 최종 수익률 차이) `> 0`
- 중앙값(V4 - V2 동일 거래 최종 수익률 차이) `>= 0`

### Path B — 대형 Winner 보존

다음을 모두 만족한다.

- V4 최종 수익률 `>= +50%` 거래 수 `> V2`
- V4 최종 수익률 `>= +100%` 거래 수 `>= V2`

### Path C — 수익 되돌림 개선

다음을 모두 만족한다.

- V4 중앙값 되돌림(giveback) `< V2`
- V4 평균 되돌림(giveback) `<= V2`

## 11. 위험 악화 판정

### 대형 손실 영역 악화

다음 두 조건을 모두 만족하면 `large_loss_area_worsened = true`로 기록한다.

- V4 `<= -30%` 비율 `> V2`
- V4 `<= -40%` 비율 `> V2`

### 자본 묶임 영역 악화

다음 두 조건을 모두 만족하면 `capital_lock_area_worsened = true`로 기록한다.

- V4 중앙값 보유 기간 `> V2`
- V4 `OPEN_AT_CUTOFF` 비율 `> V2`

### 위험 차단

다음 두 값이 모두 true이면 다음을 true로 기록한다.

```text
official_adoption_risk_block = true
```

- `large_loss_area_worsened`
- `capital_lock_area_worsened`

## 12. 공식 전략 채택 자격

다음을 모두 만족해야 한다.

1. 비교 무결성 PASS
2. `PRE_WINNER_REPAIR_PASS`
3. `WINNER_TAIL_REPAIR_PASS`
4. Path A / B / C 중 하나 이상 PASS
5. `official_adoption_risk_block == false`

모두 만족하면 다음을 기록한다.

```text
OFFICIAL_ADOPTION_ELIGIBLE = YES
```

하나라도 만족하지 않으면 자동 공식 채택 자격 없음으로 기록한다. 당시 계획에서
최종 채택 결정 자체는 생애주기 후속 단계에서 수행하도록 했다. 현재 V4는 종료된
후보 전략·역사 기록이다.

## 13. 기본 전략 승격 자격

V4가 공식 전략 채택 자격을 만족한 뒤에만 기본 전략 승격을 평가한다. 다음을 모두 만족해야 한다.

1. 평균 최종 수익률 `>= V2`
2. 중앙값 최종 수익률 `>= V2`
3. `<= -30%` 비율 `<= V2`
4. `<= -40%` 비율 `<= V2`
5. Path B 또는 Path C PASS
6. 중앙값 보유 기간 `<= V2`
7. `OPEN_AT_CUTOFF` 비율 `<= V2`
8. `PRE_WINNER_REPAIR_PASS`
9. `WINNER_TAIL_REPAIR_PASS`
10. 제한적 강건성 조건 PASS

### 제한적 강건성 조건

다음 분해에서 모두 평균 동일 거래 수익률 차이 `>= 0`이어야 한다.

- KOSPI
- KOSDAQ
- FIRST_ENTRY
- REENTRY

또한 거래가 존재하는 진입 연도의 절반 이상에서 평균 동일 거래 수익률 차이 `>= 0`이어야 한다.

위 조건을 모두 만족하지 않으면 V2를 기본 전략으로 유지한다. 일부 지표 하나의 개선만으로 기본 전략을 교체하지 않는다.

## 14. 실패 사례 및 부작용 검토

평균값만으로 판정하지 않고 다음 대표 사례를 확인한다.

1. V4 Pre-Winner Exit가 큰 손실을 줄인 사례
2. V4 Pre-Winner Exit 후 실제 전체 경로에서 Winner 활성화가 가능했던 사례
3. V4에서도 큰 손실로 남은 Pre-Winner
4. V4 Soft가 V3보다 대형 Winner를 더 오래 보존한 사례
5. V4 Soft가 여전히 대형 Winner를 훼손한 사례
6. V4 Hard가 대형 Winner를 훼손한 사례
7. V4가 V2보다 크게 악화된 동일 거래 비교 사례
8. V4가 V2보다 크게 개선된 동일 거래 비교 사례

유리한 사례만 선택하지 않는다. 전 종목 수작업 전수 리뷰는 하지 않는다.

## 15. 제한적 강건성 범위

다음만 분해한다.

- KOSPI / KOSDAQ
- FIRST_ENTRY / REENTRY
- 진입 연도별

파라미터 탐색은 하지 않는다.

- `-15%` 변경 금지
- `+20%` 변경 금지
- Soft/Hard band 변경 금지
- WATCH/SETUP 조합 변경 금지

결과가 좋지 않더라도 V4를 수정하지 않는다.

## 16. MDD 처리

고정 973개 동일 진입 거래를 재현하는 과정에 동일 포지션 투자금액과 확정 포트폴리오 구성 규칙이 없다면 새 MDD 모델을 만들지 않는다.

이 경우 다음과 같이 기록한다.

```text
MDD = NOT_EVALUATED
```

MDD를 평가하지 않는 경우 거래 단위 MAE, 최종 손실 구간, 보유 기간, 기준일을 하방 위험 평가에 사용한다.

## 17. 당시 공식 실행 원칙

당시에는 검증 계획 승인 후 별도 작업에서 실행하도록 기록했다. 현재 실행
지시나 대기 상태를 의미하지 않는다.

- V2 CONTROL 기준 자료 재사용
- V4만 동결 규칙으로 재현
- V3는 기존 공식 결과를 진단 비교용으로 재사용 가능
- 기존 973 CONTROL을 변경하지 않음
- 새 진입 생성하지 않음
- 외부 API 없음
- 네트워크 없음
- 데이터 갱신 없음
- 규칙 수정 없음

## 18. 이번 작업의 금지 사항

- 백테스트 실행
- 코드 구현
- 테스트 작성 또는 실행
- 산출물 생성
- V4 규칙 수정
- V2/V3 규칙 수정
- 새 임계값 설정
- 파라미터 탐색
- 기존 V3 결과 재실행
- 운영 반영
- README/ROADMAP 광범위 정리
- 다른 유사 문제 조사

## 19. 셀프 리뷰 기준

문서 작성 후 다음 항목만 확인한다.

1. 결과 보기 전에 합격 기준이 완전히 정해졌는가
2. V4 규칙을 변경하지 않았는가
3. 공식 비교 기준은 V2로 유지되는가
4. V3는 수리 진단 기준으로만 사용되는가
5. CONTROL 973건이 고정됐는가
6. Pre-Winner 236 / Winner-capable 737 의미가 기존 공식 결과와 같은가
7. 두 수리 관문이 V4 설계 목적과 직접 연결되는가
8. 기본 전략 승격 기준이 공식 전략 채택보다 엄격한가
9. 불필요한 파라미터 탐색이 추가되지 않았는가
10. 이번 작업에서 결과를 생성하지 않았는가

## 20. 당시 계획된 다음 단계

문서 작성 당시에는 리뷰 통과 후 전략 생애주기 5단계인 **동일 조건 비교
백테스트**를 다음 단계로 기록했다. 결과를 보기 전에 고정한 규칙과 기준을
변경하지 않는다는 원칙도 당시 계획에 포함했다. 현재 실행 계획은 아니다.
