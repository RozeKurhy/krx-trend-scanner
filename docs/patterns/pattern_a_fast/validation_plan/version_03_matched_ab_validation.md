# A FAST Core V3 동일 진입 A/B 검증 계획

## 문서 목적과 상태

이 문서는 `A FAST Core V3` 후보 전략과 현재 기본 전략 `A FAST Core V2`를
동일한 진입 코호트에서 비교하기 위한 공식 A/B 검증 계획이다. 비교 전에 청산
규칙, 데이터 범위, 평가 지표, 실패 사례, 공식 전략 채택 기준과 기본 전략 승격
기준을 고정한다.

이번 문서는 전략 생애주기의 **4단계: 검증 계획 확정**에 해당한다. 이 문서가
커밋된 이후 동일 조건으로 공식 검증 결과를 생성한다. 본 작업에서는 백테스트,
A/B 결과 생성, 코드 수정, 테스트 실행, 아티팩트 생성을 수행하지 않는다.

### 핵심 질문

> 동일한 진입을 사용했을 때 V3의 `WINNER_HWM_EXIT_V01` 청산 규칙이 현재 기본
> 전략 V2의 청산 규칙보다 더 나은 결과와 교환관계를 제공하는가?

## 1. 비교 대상

### 기준 전략: A FAST Core V2

- 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- 현재 기본 전략
- 비교 기준: 기존 V2 `CONTROL` 거래의 실제 진입 코호트
- 청산 계약: Pre-PROGRESSED `-15%` Loss Guard, PROGRESSED Exit 3, Exit 4

### 후보 전략: A FAST Core V3

- 전략 ID: `PATTERN_A_FAST_FINAL_STRATEGY_V03`
- 후보 청산 계약: `WINNER_HWM_EXIT_V01`
- 규칙 동결 완료
- 아직 공식 전략 또는 기본 전략이 아님
- V3 전용 진입 스캔을 수행하지 않음

이번 비교에서 변경되는 요소는 청산 규칙뿐이다. 진입 규칙, 진입 시점, 진입
가격, 데이터 범위, 캘린더 의미와 cutoff는 V2와 V3에서 동일하게 유지한다.

## 2. 고정 CONTROL 진입 코호트

### 권위 파일

- `artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_trades.csv`
- `artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json`

CONTROL 요약과 거래 파일을 대조한 고정 값은 다음과 같다.

| 항목 | 고정 값 |
|---|---:|
| Evaluation start | `2021-04-01` |
| Signal cutoff | `2026-08-14` |
| Execution support end | `2026-08-21` |
| CONTROL 거래 수 | `973건` |
| 고유 종목 수 | `542개` |
| 최종 평가 기준 | `2026-08-21 CLOSE` |

`control_trades.csv`는 헤더를 제외한 거래 행이 973건이며, `ticker` 기준 고유
종목 수가 542개이다. 향후 실행 시 실제 파일과 값이 다르면 성과 비교를 진행하지
않고 검증을 중단하여 보고한다.

### 동일 진입 보장

CONTROL의 **973개 진입을 모두 그대로 사용**한다. 각 거래에서 다음 항목은 V2와
V3 replay 사이에 완전히 동일해야 한다.

- `ticker` 및 identity
- 진입 신호일
- 진입 체결일
- 진입 시가
- 진입 당시 데이터 범위
- 캘린더 의미
- 공통 cutoff

진입 날짜와 진입 시가가 100% 일치하지 않으면 성과 비교는 무효이다. 비교 무결성
검사에서 다음 조건을 모두 확인한다.

- matched 거래 수 `= 973`
- 진입 날짜 일치율 `= 100%`
- 진입 시가 일치율 `= 100%`
- 누락 거래 `= 0`
- 중복 거래 `= 0`
- 임의 제외 거래 `= 0`

### 금지되는 코호트 변경

- V3용 진입 재스캔
- V3용 추가 진입 필터
- 시가총액·유동성·펀더멘털 조건 변경
- V3 결과에 따른 진입 제외
- overlap 제거
- 진입 코호트 재선정
- 전략별 독립 re-entry 생성

각 CONTROL 진입을 V2 청산 규칙과 V3 청산 규칙 아래 독립적으로 재생한다. 한
CONTROL 거래의 replay가 다른 CONTROL 진입을 삭제하거나 이동해서는 안 된다.

## 3. 데이터와 체결 의미

### 데이터 원칙

- 동일 Repository V2 로컬 가격 데이터를 사용한다.
- 외부 API, 네트워크 요청, 캐시 refresh와 누락 데이터 자동 다운로드를 사용하지
  않는다.
- identity lifecycle과 Point-in-Time(PIT) 원칙을 유지한다.
- 완료된 정보만 사용한다.
- 미래 주가, 미래 거래량, 미래 Stage, 미래 성공 여부를 현재 판단에 사용하지
  않는다.
- 데이터 누락·손상·identity 불일치는 fail-closed로 처리하고 검증 실패 사유를
  기록한다.

### 공통 기간과 평가

- Evaluation start: `2021-04-01`
- Signal cutoff: `2026-08-14`
- Execution support end: `2026-08-21`
- Final valuation: `2026-08-21 CLOSE`

최종 평가 기준일과 지원 범위는 기존 CONTROL과 동일하게 유지한다.

### 체결 규칙

V2는 권위 CONTROL 거래의 기존 진입·청산·체결 의미를 그대로 사용한다.

V3는 다음 계약을 적용한다.

- 청산 신호: 완료된 일봉 EOD에서 판단
- 청산 체결: 다음 로컬 거래일 `OPEN`
- 지원되는 다음 거래일이 없으면 `OPEN_AT_CUTOFF`
- 장중 판단과 look-ahead 금지

## 4. V2와 V3 청산 계약

### V2 기준 청산

V2는 기존 CONTROL에서 사용된 청산 규칙을 기준으로 한다.

- Pre-PROGRESSED `-15%` Loss Guard
- PROGRESSED `Exit 3`
- PROGRESSED `Exit 4`
- 청산 신호가 지원 범위 안에서 체결되지 않으면 `OPEN_AT_CUTOFF`

### V3 후보 청산

V3의 `WINNER_HWM_EXIT_V01` 계약은 다음과 같이 고정한다.

1. Pre-Winner 구간에는 V3 청산을 발생시키지 않는다.
2. `running_raw_MFE >= +20%`부터 Winner 모드를 활성화한다.
3. `running_raw_MFE`는 진입 후 완료된 일봉 `HIGH` 중 최고값을 진입 시가와
   비교해 계산한다.
4. 매일 완료된 EOD 판단에서 HWM을 갱신하고, 같은 날 완료된 `CLOSE`를 HWM과
   비교한다.
5. Soft 청산은 HWM 하락폭을 충족하면서 완료된 FAST 상태가 `WATCH` 또는
   `SETUP`인 경우 발생한다.
6. Hard 청산은 가격 기준으로 판단하며 FAST 상태와 관계없이 발생한다.
7. Soft와 Hard가 동시에 충족되면 `HARD`가 우선한다.
8. 청산은 거래당 한 번만 발생한다.
9. 청산 신호는 다음 로컬 거래일 `OPEN`에 체결한다.
10. 지원되는 다음 거래일이 없으면 `OPEN_AT_CUTOFF`로 남긴다.

| 누적 raw MFE 구간 | Soft 하락폭 | Hard 하락폭 |
|---|---:|---:|
| `+20% <= MFE < +50%` | `-10%` | `-20%` |
| `+50% <= MFE < +100%` | `-15%` | `-25%` |
| `+100% <= MFE < +200%` | `-20%` | `-30%` |
| `+200% <= MFE < +400%` | `-25%` | `-35%` |
| `MFE >= +400%` | `-30%` | `-40%` |

V3 검증 중에는 위 규칙을 변경하지 않는다. 결과가 좋지 않더라도 새로운
Pre-Winner 손절, `W25`, `W30`, `FAILURE_ARMED`, persistence exit, 새로운
MFE/HWM Threshold, 임의의 Soft/Hard 보정을 추가하거나 조정하지 않는다.

규칙 변경이 필요하면 기존 V3를 수정하지 않고 새 후보 전략으로 다시 동결한다.

## 5. 평가 지표

### A. 비교 무결성

성과보다 먼저 다음을 평가한다.

- matched 거래 수
- 진입 신호일과 진입 체결일 일치율
- 진입 시가 일치율
- 누락·중복·임의 제외 건수
- identity lifecycle 일치 여부

무결성 조건 하나라도 실패하면 해당 검증 결과는 `FAIL`이며, 수익성 비교를
공식 결과로 채택하지 않는다.

### B. 전체 수익 특성

V2와 V3 각각에 대해 평균·중앙값 terminal return과 승률을 계산한다. 또한
다음 paired 지표를 계산한다.

- V3 - V2 paired return delta의 평균
- V3 - V2 paired return delta의 중앙값
- `improved` 거래 수
- `worsened` 거래 수
- `same` 거래 수

paired 결과를 단순 총합 수익률보다 우선한다.

```text
paired_return_delta = V3 terminal return - V2 terminal return
```

### C. 손실 위험

V2와 V3 각각에 대해 평균·중앙값 MAE와 다음 terminal return tail을 비교한다.

- `<= -15%`
- `<= -20%`
- `<= -30%`
- `<= -40%`
- 기존 데이터가 제공하는 경우 더 깊은 tail

특히 `<= -30%`와 `<= -40%`는 V3 Pre-Winner 무청산의 핵심 위험으로 별도
강조한다.

### D. Winner 보존과 giveback

V2와 V3 각각에 대해 terminal return `>= +20%`, `+30%`, `+50%`, `+100%`,
`+200%`, `+400%` 구간을 비교한다. MFE 대비 terminal return giveback도
계산하며, V2가 조기 종료한 대형 잠재 승자를 V3가 얼마나 보존하는지 확인한다.

### E. V3 Pre-Winner 위험

각 고정 진입에 대해 전략 청산과 무관한 공통 full-path raw MFE를 사후 진단용으로
계산한다.

```text
full_path_raw_MFE =
max(daily HIGH from entry through common cutoff) / entry_open - 1
```

이 값은 V3 청산 신호가 아니다. 다음 두 코호트를 분리한다.

- `full_path_raw_MFE < +20%`: 끝까지 Winner 활성화 가능성이 없었던 Pre-Winner
  코호트
- `full_path_raw_MFE >= +20%`: Winner 활성화 가능 코호트

Pre-Winner 코호트에서 terminal return, MAE, 보유 기간,
`OPEN_AT_CUTOFF` 건수·비율, 대형 손실 사례와 장기 자본 묶임 사례를 별도로
확인한다.

### F. 자본 묶임

V2와 V3 각각에 대해 평균 보유 거래일, 중앙값 보유 거래일, 가능하면 P90 보유
거래일, `OPEN_AT_CUTOFF` 건수·비율을 비교한다. V3 Pre-Winner 코호트의 장기
보유와 `OPEN_AT_CUTOFF`도 별도로 표시한다.

### G. 청산 이유

청산 이유별 건수와 결과를 다음과 같이 분리 집계한다.

| 전략 | 청산 이유 |
|---|---|
| V2 | Loss Guard |
| V2 | Exit 3 |
| V2 | Exit 4 |
| V2 | `OPEN_AT_CUTOFF` |
| V3 | Soft Exit |
| V3 | Hard Exit |
| V3 | `OPEN_AT_CUTOFF` |

각 이유에 대해 거래 수, 비율, terminal return, MAE, MFE, 보유 기간과 대표
실패 사례를 기록한다.

## 6. MDD 처리

이번 검증은 973개 고정 진입을 각각 독립 재생하는 청산 규칙 matched A/B이다.
동일한 포지션 사이징과 포트폴리오 구성 규칙이 기존에 확정되어 있지 않다면
새로운 포트폴리오 가정을 만들지 않는다.

기본 downside 평가는 trade-level MAE, terminal loss tail, 보유 기간과
`OPEN_AT_CUTOFF`를 우선한다. V2와 V3에 동일하게 적용 가능한 확정 포트폴리오
equity curve가 이미 존재하는 경우에만 MDD를 보조 지표로 사용할 수 있다.
새 포트폴리오 모델 설계는 이번 범위에 포함하지 않는다.

## 7. 실패 사례 검토

다음 유형의 대표 사례를 추출한다.

1. V3가 `+20%` Winner에 도달하지 못하고 큰 손실로 남은 거래
2. V3에서 장기간 `OPEN_AT_CUTOFF`로 남은 거래
3. V3가 V2보다 크게 악화된 paired 거래
4. V2가 먼저 청산했지만 V3가 대형 승자로 발전한 거래
5. Winner 활성화 후 V3가 고점 수익을 과도하게 반납한 거래
6. Soft 또는 Hard 청산이 계약 의도와 다르게 작동한 대표 거래

각 유형에서 상위 대표 사례만 확인한다. 전체 종목을 수작업으로 전수 리뷰하지
않는다. 대표 사례는 결과에 유리한 사례만 선택하지 않는다.

## 8. 제한적 강건성 확인

파라미터 탐색을 수행하지 않는다. 공식 A/B 이후 필요한 최소 분해만 수행한다.

- 진입 연도별
- KOSPI / KOSDAQ
- 최초 진입 / 재진입

목적은 특정 시기나 한 집단에 결과가 과도하게 몰렸는지 확인하는 것이다.
Soft/Hard Threshold의 여러 조합을 돌리는 민감도 탐색은 수행하지 않는다.

## 9. 공식 전략 채택 기준

V3의 결과를 보기 전에 다음 최소 조건을 고정한다.

1. 비교 무결성 `PASS`
2. V3가 전체 paired return 특성, 대형 Winner 보존 또는 MFE 대비 giveback 중
   하나 이상에서 명확한 개선을 보임
3. 다음 두 위험 영역이 동시에 모두 악화되지 않음
   - 대형 손실: `<= -30%` 비율 증가 및 `<= -40%` 비율 증가
   - 자본 묶임: 중앙값 보유 기간 증가 및 `OPEN_AT_CUTOFF` 비율 증가

V3가 수익 또는 Winner 보존 개선 없이 위험만 증가시키면 공식 전략으로 채택하지
않는다. 수익 개선이 있더라도 대형 손실 영역과 자본 묶임 영역이 동시에 명확히
악화되면 공식 전략으로 채택하지 않는다.

혼합 결과는 실패 사례 검토 후 `보류` 또는 `수정 후 새 후보 재검증`으로 처리할
수 있다. V3 규칙을 현재 후보 문서에서 직접 수정하지 않는다.

## 10. 기본 전략 승격 기준

V3가 공식 전략으로 인정되는 것과 V2를 대체하는 것은 별도 판단이다. V3를
기본 전략으로 승격하려면 다음 조건을 모두 만족해야 한다.

1. 평균 terminal return이 V2 이상
2. 중앙값 terminal return이 V2 이상
3. `<= -30%` 손실 비율이 V2 이하
4. `<= -40%` 손실 비율이 V2 이하
5. 대형 Winner 보존 또는 MFE 대비 giveback이 V2보다 개선
6. 중앙값 보유 기간이 V2 이하
7. `OPEN_AT_CUTOFF` 비율이 V2 이하
8. 연도·시장·진입 유형 분해에서 특정 한 구간의 우연한 성과만으로 결과가
   설명되지 않음

위 조건을 모두 만족하지 않으면 V3를 자동으로 기본 전략으로 승격하지 않는다.
공식 전략으로는 의미가 있으나 V2보다 전체적으로 명확한 우위가 없다면 V2를
기본 전략으로 유지한다.

## 11. 결과 처리

공식 검증 결과는 다음 중 하나로 귀결한다.

- **V3 공식 전략 채택 + 기본 전략 승격 검토**
- **V3 공식 전략 채택, V2 기본 전략 유지**
- **보류**
- **폐기**
- **규칙 수정 필요 → V3 수정 금지, 새 후보 동결 후 재검증**

결과를 확인한 뒤 이번 계획의 평가 지표와 합격 기준을 변경하지 않는다.

## 12. 기존 탐색 결과와의 관계

저장소의 기존 V3 탐색·진단 결과와 A/B 관련 스크립트는 데이터 경로, CONTROL
코호트, 실행 의미와 동일 진입 replay의 데이터 구조 확인에만 사용한다.

확인 대상은 다음과 같다.

- `docs/strategies/strategy_lifecycle.md`
- `docs/patterns/pattern_a_fast/strategy/version_02/README.md`
- `docs/patterns/pattern_a_fast/strategy/version_03/README.md`
- `artifacts/backtests/fastcore_fundamentals_simple_v01/control/control_summary.json`
- `scripts/analyze_fastcore_v3_exit_ab_v00.py`

기존 결과 수치는 이번 공식 검증 결과로 승격하지 않는다. 기존 결과에 맞춘 합격
기준 변경, 탐색 결과를 matched A/B 결과로 간주하는 행위, 기존 V3 독립 진입
백테스트를 동일 진입 결과로 간주하는 행위를 금지한다.

공식 검증 결과는 이 계획이 커밋된 이후 동일 조건으로 새로 생성한다.

## 13. 불변 원칙과 실행 전 체크리스트

- 외부 API와 네트워크 데이터 호출을 수행하지 않는다.
- V2 또는 V3 production 전략 코드와 운영 파이프라인을 수정하지 않는다.
- Stock Report, Candidate, Ranking을 수정하지 않는다.
- 계획 확정 작업에서 아티팩트를 생성하거나 수정하지 않는다.
- 계획 문서가 결과 생성 전에 커밋되어 있어야 한다.
- CONTROL 거래 수가 973건이고 고유 종목 수가 542개여야 한다.
- 기간은 `2021-04-01`부터 `2026-08-21 CLOSE`까지, signal cutoff는
  `2026-08-14`로 고정한다.
- V2와 V3가 동일 CONTROL 진입을 사용하고 진입 날짜·시가 100% 일치 검사를
  수행해야 한다.
- Pre-Winner `+20%` 미도달 코호트, 손실 tail, Winner 보존·giveback, 보유 기간과
  `OPEN_AT_CUTOFF`를 집계해야 한다.
- 파라미터 탐색과 Threshold 민감도 탐색을 수행하지 않는다.

이 체크리스트는 공식 검증 실행 준비 확인용이며, 이번 계획 확정 작업에서
백테스트를 수행했다는 의미가 아니다.
