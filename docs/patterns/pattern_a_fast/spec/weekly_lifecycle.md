# Pattern A FAST 주봉 생애주기

> 이 문서는 Pattern A FAST의 주봉 구조가 현재 어떤 생애주기 위치에 있는지와
> 상태 전이 원칙을 정의한다. 주봉 Stage는 자동 매수 신호가 아니며, Feature·Threshold·
> Score를 계산하는 규칙은 이 문서의 범위에 포함하지 않는다.

## 문서 상태

- **계약 상태**: 주봉 생애주기 의미 동결 (`CLOSED / Weekly Lifecycle Semantics v0.1 Frozen`)
- **동결된 것**: `WATCH`, `SETUP`, `TRIGGER`, `TREND`, `EXTENDED`의 이름과 의미
- **동결하지 않은 것**: 분류기 규칙, Feature 공식, 숫자 Threshold, Score
- **기준 문서**: [Pattern A FAST 정의](README.md)
- **근거 커밋**: `dd0dec386d1382f9176ec8a876b17fd4bcdeb51e`

## 생애주기 개요

Pattern A FAST의 공식 주봉 Stage는 다음 다섯 가지다.

| Stage | 의미 |
|---|---|
| `WATCH` | 상승 전환 `SETUP`이 충분히 형성되지 않은 초기 관찰 상태 |
| `SETUP` | 상승 전환 가능성을 보여주는 구조 변화가 시작된 상태 |
| `TRIGGER` | 주봉 구조에서 유의미한 상승 전환 가능성이 처음 확인된 상태 |
| `TREND` | 초기 전환을 넘어 상승 구조가 지속·발전하는 상태 |
| `EXTENDED` | Fast 신규 진입의 초기 구간을 상당 부분 지난 상태 |

개념적 진행 순서는 `WATCH < SETUP < TRIGGER < TREND < EXTENDED`다. 하지만 이
표현은 좋음·나쁨이나 Score의 순위가 아니라 생애주기 위치를 뜻한다.

Stage는 현재 PIT 시점의 주봉 구조를 표현한다. 과거에 어느 Stage까지 갔는지나
이전 주의 Stage만으로 현재 Stage를 결정하지 않는다. 따라서 생애주기는 비가역적
상태 기계가 아니고, 후퇴와 직접 전이를 허용한다.

## 시간축 역할

Pattern A FAST는 서로 다른 시간축의 책임을 섞지 않는다.

- `monthly_regime`: 장기 환경과 국면
- `weekly_lifecycle_stage`: 현재 주봉 구조와 생애주기 위치
- `daily_timing`: 주봉 구조가 유효하다는 전제의 진입 타이밍 보조

이번 계약에서 동결하는 것은 `weekly_lifecycle_stage`의 의미뿐이다. 월봉과 일봉의
분류 체계·계산은 주봉 Stage의 의미에 섞지 않는다.

예를 들어 `Monthly: BAD`, `Weekly: TRIGGER`, `Daily: READY` 같은 조합은 기술적으로
가능하고 오류가 아니다. 최종 매매 후보인지 여부는 별도 전략 계약에서 판단한다.

## `WATCH`

핵심 질문은 “주봉 기준으로 아직 상승 전환 `SETUP`이 충분히 형성되지 않았는가?”이다.

주봉 구조에서 상승 전환을 연구할 이유는 있을 수 있지만, `SETUP`이라고 부를 만큼
구조적 개선 증거가 충분하지 않은 초기 관찰 상태를 뜻한다.

다음과 같은 의미는 아니다.

- 나쁜 종목
- 매도 대상
- 월봉 환경 `BAD`
- Pattern A의 실패

가능한 관찰 예시는 하락 둔화가 불명확함, 저점 개선 부족, 주봉 MA 구조 변화가
미약함, Range 안에서 의미 있는 구조 변화가 부족함이다. 구체 Feature는 별도
연구에서 정한다.

## `SETUP`

핵심 질문은 “상승 전환 가능성을 보여주는 주봉 구조 변화가 실제로 시작됐는가?”이다.

단순한 가격 반등을 넘어 주봉 구조에서 상승 전환 가능성을 설명할 수 있는 초기
변화가 여러 방향에서 나타나기 시작했지만, 최초의 유의미한 전환 `TRIGGER`라고
부르기에는 결정적 증거가 부족한 상태다.

하락 기울기 둔화, 저점 방어, 주봉 MA 평탄화 시작, Range 상단 접근, 주봉 고점
구조 개선 시도 등이 예가 될 수 있다. `SETUP`은 관찰 우선순위가 높아진 초기
준비 상태이지 매수 신호가 아니다.

핵심 경계는 `WATCH < SETUP < TRIGGER`다.

## `TRIGGER`

`TRIGGER`는 Pattern A FAST의 핵심 Stage다.

핵심 질문은 “주봉 구조가 단순 반등을 넘어 실제 상승 전환 가능성을 처음으로
의미 있게 보여주는가?”이다.

주봉에서 상승 전환 `SETUP`이 충분히 성숙하고, 단순 기술적 반등이라고 보기 어려운
구조적 확인이 최초로 나타난 상태를 뜻한다. Pattern A의 보수적 확인 시점보다 빠른
전환 가능성을 포착하는 것이 목적이지만, `TRIGGER` 자체가 무조건적인 매수 신호는
아니다.

월봉 국면, 일봉 타이밍, Investability, Flow, RS는 별도 축이다.

## `TREND`

핵심 질문은 “현재 PIT 주봉 구조가 초기 전환 구간을 넘어 상승 구조를 지속·발전시키는
생애주기 위치에 있는가?”이다.

주봉 가격 구조가 `TRIGGER`가 표현하는 초기 전환 수준을 넘어 상승 방향으로 지속·
발전한다는 증거가 나타난 상태다. Pattern A의 `BASE`, `TRANSITION`, `EARLY_TREND`
등과 같은 시점에 나타날 수 있지만, 두 패턴의 Stage가 일치할 필요는 없다.

과거 snapshot에서 실제 `TRIGGER`를 관측한 것이 `TREND`의 필수 조건은 아니다.
`SETUP → TREND`나 `WATCH → TREND`처럼 `TRIGGER`를 건너뛴 직접 전이도 정상일 수
있다. 이 경우 존재하지 않는 과거 `TRIGGER`나 Trigger 사건을 추정하거나
과거 보완하지 않는다.

`TREND`는 초기 `TRIGGER`보다 진행된 위치지만, Pattern A FAST 관점에서 반드시
늦었다는 뜻은 아니다.

## `EXTENDED`

핵심 질문은 “Fast 신규 진입 관점에서 움직임이 이미 상당 부분 진행됐는가?”이다.

주봉 상승 구조 자체는 강하거나 정상일 수 있지만, Pattern A FAST가 목표로 하는
초기 전환·초기 진입 구간을 상당 부분 지난 상태를 뜻한다.

다음 의미는 아니다.

- `EXTENDED`가 곧 나쁜 종목이라는 뜻
- 하락을 예상한다는 뜻
- 매도 신호

Pattern A에서는 `EARLY_TREND`일 수도 있고 장기 투자 관점에서는 여전히 유효할 수
있다. 다만 Fast 신규 진입 관점의 초기 위험 대비 보상은 악화된 상태로 해석한다.

`EXTENDED`는 종결 상태가 아니다. 건강한 조정·횡보 뒤
`EXTENDED → TREND`가 가능하고, 구조가 충분히 초기화되면
`EXTENDED → WATCH` 또는 `SETUP`도 개념상 가능하다. 실제 Episode 초기화 의미는
별도 연구에서 다룬다.

## Trigger Stage와 Trigger 사건

둘은 서로 다른 개념이다.

- **`TRIGGER` Stage**: 현재 weekly snapshot이 `TRIGGER` 상태라는 뜻
- **Trigger 사건**: 생애주기가 비-`TRIGGER` 상태에서 `TRIGGER`로 처음 진입한 사건

예를 들어 `SETUP → TRIGGER → TRIGGER → TREND`라면 Trigger 사건 날짜는 첫
`TRIGGER` 주다. 이어지는 `TRIGGER` 주를 새 사건으로 중복 기록하지 않는다.

선행 기간 분석에서 사용하는 날짜도 Stage가 지속된 모든 주가 아니라 Trigger 사건
진입 시점이다.

## 단계 전이 원칙

### 전형적인 경로

```text
WATCH → SETUP → TRIGGER → TREND → EXTENDED
```

이 경로는 주 경로이지 강제 상태 기계가 아니다.

### 후퇴 허용

Fast 구조는 실패하거나 약화될 수 있으므로 후퇴 전이를 정상적인 현상으로
인정한다.

예시는 다음과 같다.

- `SETUP → WATCH`
- `TRIGGER → SETUP`
- `TRIGGER → WATCH`
- `TREND → TRIGGER`
- `TREND → SETUP`
- `EXTENDED → TREND`

Stage regression 자체를 분류기 오류로 간주하지 않는다.

### 직접 전이 허용

Stage는 이전 Stage에 의해 강제되지 않으므로 다음과 같은 직접 전이도 실제 PIT
구조로 정당화될 수 있다.

- `WATCH → TRIGGER`
- `SETUP → TREND`
- `WATCH → TREND`
- `TREND → WATCH`

직접 전이가 빈번하면 Stage 의미나 분류기가 너무 거친지 별도로 감사할 수 있지만,
직접 전이 자체를 금지하지 않는다.

### 직접 전이와 Trigger 사건의 분리

`SETUP → TRIGGER → TREND`처럼 실제로 `TRIGGER` Stage를 거친 경우에만 Trigger
사건이 있다. `SETUP → TREND`처럼 `TRIGGER`를 건너뛴 에피소드에는 과거 Stage를
추정한 합성·추정 Trigger 사건 날짜를 만들지 않는다.

## PIT와 완료된 주봉 원칙

### 완료된 주봉만 사용

Weekly Lifecycle Stage는 기본적으로 완료된 주봉 데이터만 사용한다. 특정 `as_of`
시점에 진행 중인 미완성 주봉을 완료된 주봉처럼 사용하지 않는다. 주중 급등·급락으로
Stage가 일시적으로 왜곡되는 것을 막기 위해서다.

즉 다음과 같이 책임을 나눈다.

- `Weekly Stage = 완료된 주봉 구조`
- `Daily Timing = as_of까지 완료된 일봉 데이터`

### 완료된 월봉 참고

Monthly Regime은 별도 분류 축이지만 기본적으로 완료된 월봉을 사용한다. 미완성 월봉을
확정된 Monthly Regime처럼 취급하지 않는다. Current Month 정보를 사용해야 한다면
완료 월봉 기반 Regime과 섞지 않고 `현재 월 보조 관측`으로
분리한다.

### Point-in-Time 계약

Stage(t)는 t 시점까지 확정된 데이터만 사용한다.

현재 Stage 판단에 다음을 사용해서는 안 된다.

- 미래 주봉과 미래 일봉
- 미래 Pattern A Stage
- 미래 수익률과 미래 거래량
- 미래 Trigger 성공 여부

미래 데이터는 사후 정답, 결과 검증, 실패 분석에서만 사용한다.

## Stage와 다른 축의 독립성

### Score와의 분리

향후 Pattern A FAST Score가 생기더라도 Weekly Lifecycle Stage와 Score는 독립 축으로
유지한다. `Fast Score >= 80 => TRIGGER`, `Fast Score >= 90 => TREND` 같은 구조는
허용하지 않는다.

Stage는 주봉 생애주기의 구조적 의미를 표현하고, Score는 별도의 연속 측정값이다.

### 사후 정답 / 결과 라벨과의 분리

다음 두 종류를 구분한다.

- **Lifecycle Stage**: PIT 시점의 구조적 상태 — `WATCH` / `SETUP` / `TRIGGER` /
  `TREND` / `EXTENDED`
- **사후 정답 / 결과 라벨**: 사후 리뷰 결과 — `GOOD_TRIGGER` /
  `BORDERLINE_TRIGGER` / `FALSE_TRIGGER` / `TOO_EARLY` / `TOO_LATE` /
  `TOO_EXTENDED`

`FALSE_TRIGGER`는 Stage가 아니다. 미래 결과를 본 뒤 붙이는 사후 검토 라벨이며,
당시 PIT Stage를 `FALSE_TRIGGER`로 다시 쓰지 않는다. 같은 이유로
`GOOD_TRIGGER`, `TOO_EARLY`, `TOO_LATE`도 Stage가 아니다.

Lifecycle Stage `EXTENDED`와 사후 Label 이름이 충돌하지 않도록 사후 Label은
`TOO_EXTENDED`를 사용한다. Lifecycle Stage의 `EXTENDED` 이름은 유지한다.

예를 들어 PIT 주봉이 `SETUP`이고 사후 리뷰가 `TOO_EARLY`일 수 있으며, PIT 주봉이
`TREND`이고 사후 리뷰가 `TOO_LATE`일 수도 있다.

### `UNAVAILABLE`과 `NOT_EVALUATED`

데이터 부족·손상·PIT weekly snapshot 계산 불가를 정상 Stage에 억지로 배정하지 않는다.
특히 `WATCH`로 대체 처리하지 않는다.

권장 상태는 `weekly_lifecycle_stage = UNAVAILABLE`이다. 다만 `UNAVAILABLE`은
`WATCH`·`SETUP`·`TRIGGER`·`TREND`·`EXTENDED`와 같은 생애주기 상태가 아니라
Data / Evaluation Status다.

`NOT_EVALUATED`는 사용자가 분석을 요청하지 않았거나 필수 upstream 구조를 평가하지
않은 경우에 별도로 사용할 수 있다. Monthly Regime이 `BAD`라는 이유만으로 Weekly
Stage를 `NOT_EVALUATED`로 숨기지는 않는다.

### 월봉·일봉과의 독립성

`Monthly: BAD`, `Weekly: TRIGGER`가 발생해도 Weekly Stage를 `WATCH`로 다시 쓰지
않는다. 월봉이 Fast Candidate를 허용하는지는 별도 해석 축이다.

`Weekly: TRIGGER`, `Daily: EXTENDED / WAIT`도 가능하다. 일봉 타이밍이 좋지 않다고
주봉을 `SETUP`으로 낮추지 않는다. 반대로 `Weekly: WATCH`에서 일봉이 READY처럼
보이는 단기 급등만으로 주봉을 `TRIGGER`로 올리지 않는다.

### Investability·Flow·RS와의 독립성

다음은 Weekly Stage에 영향을 주지 않는다.

- Market Cap
- Investability Status
- Foreign Flow
- Market RS와 Sector RS
- Liquidity Filter

예를 들어 `Weekly: TRIGGER`와 `Investability: FILTERED_MARKET_CAP`은 정상적인
조합이다. Weekly Stage는 가격 구조의 생애주기만 표현한다.

## Stage 이력과 Episode

### 전이 이력

향후 Stock Report나 Scanner에서 Stage 전이 이력을 만들 경우 실제 Stage가
변경된 시점만 기록한다.

`SETUP, SETUP, TRIGGER, TRIGGER, TREND`라면 전이는
`SETUP → TRIGGER`, `TRIGGER → TREND`다. 같은 Stage 반복은 전이 사건이
아니다.

### Re-Trigger와 Episode

한 종목에서 여러 Trigger 사건이 발생할 수 있다.

예를 들어 `SETUP → TRIGGER → WATCH` 이후 `WATCH → SETUP → TRIGGER`가 되면
두 번째 `TRIGGER`는 새로운 Trigger 사건 후보가 될 수 있다. 다만 새 Episode를
인정하는 조건이나 초기화에 필요한 기간은 이 계약에서 수치로 정하지 않는다.

여러 사건이 있을 때 first trigger only, best trigger, latest trigger 중 하나를
임의로 고르지 않는다. 각 Trigger 사건을 episode 단위로 관리할 가능성을 열어둔다.

### 선행 기간 처리

Pattern A 비교의 기준점은 Trigger 사건 날짜다. 비교 대상은 Pattern A
`TRANSITION` first date와 `EARLY_TREND` first date다.

Pattern A가 해당 Stage에 도달하지 않은 종목은 Fast 실패로 자동 처리하지 않는다.
실제 Trigger 사건이 없는 직접 전이 에피소드의 선행 기간은
`NOT_EVALUATED` 또는 `NOT_APPLICABLE` 계열 상태로 처리한다.

다음은 금지한다.

- TREND 첫 날짜를 Trigger Date로 조용히 사용
- SETUP과 TREND 사이의 임의 날짜를 Trigger Date로 추정
- 미래 데이터를 보고 Trigger Date를 역추론

### 관측되지 않은 Trigger 사건

`TRIGGER`를 건너뛰어 `TREND` 이상으로 직접 전이한 에피소드는 Trigger 사건을
임의 생성하지 않는다. 개념적으로 `trigger_event = NOT_OBSERVED`로 기록할 수 있지만,
정확한 production schema enum은 별도 Schema 계약에서 정한다.

핵심 원칙은 하나다. **관측되지 않은 Trigger 사건 날짜를 추정하거나 과거 보완하지
않는다.**

사후 정답을 기록할 때도 PIT 구조 상태와 사후 결과 라벨을 분리한다.

- PIT 구조: `weekly_stage_at_reference` (예: `TRIGGER`)
- 사후 결과: `human_label` (예: `GOOD_TRIGGER`, `FALSE_TRIGGER`)

## 개념 예시

### 정상적인 진행

`WATCH → SETUP → TRIGGER → TREND → EXTENDED`

### Setup 실패

`WATCH → SETUP → WATCH`

### False Trigger

`SETUP → TRIGGER → WATCH`
PIT Stage: `TRIGGER` / 결과 라벨: `FALSE_TRIGGER`

### 성공적인 Trigger

`SETUP → TRIGGER → TREND`
Trigger 사건: `TRIGGER` 진입 주 / 결과 라벨: `GOOD_TRIGGER`

### 월봉 충돌

Monthly: `BAD`, Weekly: `TRIGGER`
결론: Weekly Stage는 `TRIGGER`로 유지하고, 최종 후보 여부는 별도로 판단한다.

### 일봉 충돌

Weekly: `TRIGGER`, Daily: `WAIT`
결론: Weekly Stage는 `TRIGGER`로 유지한다.

### 확장 상태에서의 후퇴

`EXTENDED → TREND`
건강한 조정 뒤 다시 진행되는 개념적 사례다.

### Trigger를 건너뛴 TREND

Week 1: `SETUP` / Week 2: `TREND`
Weekly Stage: `TREND` / 관측된 Trigger 사건: `NO` / Trigger 사건 날짜: 없음 /
Trigger 기준 선행 기간: `NOT_EVALUATED`

이 직접 전이 자체는 Stage 오류가 아니다. 실제 발생 빈도는 별도 검증에서 감사한다.

## 이 계약에서 정하지 않는 것

다음은 이 문서에서 새로 확정하지 않는다.

- Weekly MA 기간과 Monthly MA 기간
- Range 기간과 Slope Threshold
- Breakout·Volume·Trading Value·Volatility Threshold
- Fast Score와 Stage Score Cutoff
- Candidate Cutoff와 Daily READY Threshold
- Monthly GOOD·BAD 공식
- False Trigger 주수
- Episode 초기화 기간
- Return·MDD Threshold
- Success Rate PASS 기준

## 참고: 문서 이력과 열린 질문

이 계약은 초기 Pattern A FAST 개념 정의(Phase 13A)를 바탕으로 주봉 생애주기
의미를 동결한 기록이다. 다음 질문들은 이 문서에서 임의로 답하지 않은 역사적
연구 질문이며, 현재 적용 중인 Stage 의미를 뒤집지 않는다.

- Episode / Re-Trigger 초기화 기준은 어떤 구조 조건인가?
- Trigger Stage 우선순위 규칙을 실제 Feature로 어떻게 구현할 것인가?
- 직접 전이의 실제 발생 빈도가 Stage 의미 재검토를 요구하는 수준인가?
- Weekly Lifecycle과 Monthly Regime을 최종적으로 어떻게 함께 해석할 것인가?
- `NOT_EVALUATED`를 실제로 언제 사용할 것인가?
- `weekly_stage_at_reference`와 `human_label`을 어떤 UI·스키마로 기록할 것인가?
