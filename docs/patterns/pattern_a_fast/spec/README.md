# Pattern A FAST 정의

> Pattern A FAST는 Pattern A보다 빠른 상승 전환 구조를 탐지하는 **패턴**이다.
> `A FAST Core`는 이 패턴을 이용해 진입·보유·청산을 결정하는 **전략**이고,
> 둘은 같은 개념이 아니다.

## 핵심 요약

Pattern A FAST는 다음 질문에 답하기 위한 패턴이다.

> 장기 환경이 허용되는 종목에서, 상승 추세가 완전히 확인되기 전에 주봉 구조가
> 유효한 상승 전환으로 발전하기 시작했는가?

핵심 목적은 단순히 빨리 포착하는 것이 아니라 **빠르면서 구조적으로 유효한
(`EARLY + STRUCTURALLY VALID`) 전환**을 찾는 것이다. 가격이 잠깐 올랐다는
사실만으로 좋은 신호나 `TRIGGER`로 판단하지 않는다.

이 문서는 알고리즘, Feature 공식, Threshold, Score 산식을 정의하지 않는다.
Pattern A FAST가 무엇을 탐지하는 패턴인지와 각 시간축·상태의 의미를 설명하는
개념 기준 문서다. 주봉 생애주기의 상세 계약은
[weekly_lifecycle.md](weekly_lifecycle.md)에서 확인한다.

## Pattern A와의 관계

Pattern A FAST는 기존 Pattern A를 대체하거나 수정하지 않는 독립 패턴이다.
두 패턴은 시간축과 목적이 다르기 때문에 같은 종목에서 서로 다른 상태를 반환할
수 있다.

- **Pattern A**: 월봉과 주봉으로 충분히 확인된 장기 상승 초입을 보수적으로 탐지
  (`DONE`, `FROZEN`, `Conservative Structural Detector`)
- **Pattern A FAST**: 월봉에서 장기 환경을 확인한 뒤 주봉에서 더 빠른 전환
  `SETUP`과 `TRIGGER`를 탐지하는 독립 패턴 (`Independent Fast Detector`)

가능한 정상 조합은 다음과 같다.

| Pattern A | Pattern A FAST |
|---|---|
| `BASE` | `TRIGGER` |
| `TRANSITION` | `TREND` |
| `EARLY_TREND` | `EXTENDED` |

Pattern A를 정답 Label로 사용하지 않는다. Pattern A가 나중에 신호를 냈는지만으로
Pattern A FAST의 성공 여부를 정하지 않는다. Pattern A는 Fast Trigger Date와
Pattern A `TRANSITION`·`EARLY_TREND` Date의 **Lead Time 비교 기준**이다.
Pattern A가 잡지 못한 상승 종목을 자동으로 Pattern A FAST 실패로 처리하지 않는다.
실제 구조와 사후 Outcome은 별도로 검토한다.

## 시간축 구조

세 시간축의 책임을 분리한다.

```text
MONTHLY REGIME → WEEKLY STRUCTURE / TRIGGER → DAILY TIMING
```

### 월봉: 장기 환경과 국면

월봉은 “지금 빠른 상승 전환을 살펴볼 만한 장기 위치인가?”를 확인한다.
월봉은 `TRIGGER`를 만들지 않고 환경·국면 필터 역할만 한다.

확인하는 개념은 다음과 같다.

- 장기 하락 또는 장기 조정 여부
- 장기 바닥권 또는 회복 가능 위치 여부
- 장기 이동평균 구조
- 장기 가격 Range 내 위치
- 이미 지나치게 상승한 상태인지 여부
- 장기 구조적 위험이 여전히 큰지 여부

이 문서는 MA 기간, Range Threshold, 하락률 Threshold 같은 계산 수치를 정하지
않는다.

### 주봉: 핵심 구조와 전환

주봉이 Pattern A FAST의 핵심 시간축이다. 주봉은 “장기 하락 또는 정체 상태에서
실제 상승 전환 구조가 만들어지기 시작했는가?”를 확인한다.

구조를 설명할 때 사용하는 개념은 다음과 같다.

- 하락 속도 둔화
- 주봉 저점 상승과 주봉 고점 상승
- 주봉 이동평균의 평탄화와 상승 전환
- 주요 주봉 이동평균 회복
- 중기 박스 상단 접근 또는 돌파
- 주봉 변동성 변화
- 주봉 거래량·거래대금 변화
- `higher low`와 `higher high`의 진행

구체적인 계산식과 Threshold는 이 개념 문서에서 확정하지 않는다. 현재 주봉 상태의
정의와 전이 원칙은 [주봉 생애주기 계약](weekly_lifecycle.md)이 담당한다.

### 일봉: 진입 타이밍 보조

일봉은 패턴 자체를 결정하지 않는다. 주봉 구조가 유효하다는 전제에서 현재 단기
진입 위치가 적절한지 보조한다.

살펴볼 수 있는 개념은 돌파 직후, 눌림, 재돌파, 단기 이동평균 이격, 단기 과열,
최근 저점 이탈, 거래대금 동반 여부다. 일봉은
`ENTRY TIMING SUPPORT LAYER`이고, 일봉 상태 때문에 주봉 Stage를 임의로
낮추거나 높이지 않는다.

## 목표 구간

Pattern A FAST가 찾고 싶은 구간은 다음과 같다.

- 장기 하락 또는 조정이 상당 부분 진행됨
- 월봉상 지나치게 위험하거나 이미 지나치게 진행된 위치가 아님
- 주봉에서 하락 구조가 둔화됨
- 저점·이동평균·가격 구조가 개선되기 시작함
- 실제 주봉 구조에서 상승 전환 가능성이 나타남

완전히 상승 추세가 확인된 뒤가 아니라, 상승 추세가 만들어지는 과정을 찾는
것이 핵심이다.

## 주요 상태와 해석

주봉의 공식 생애주기는 `WATCH`, `SETUP`, `TRIGGER`, `TREND`, `EXTENDED`다.
각 상태의 상세 의미와 전이 규칙은 [weekly_lifecycle.md](weekly_lifecycle.md)에
고정되어 있다.

### `TOO_EARLY`

아직 구조적 증거 없이 가격만 단기적으로 움직인 상태다.

예시는 다음과 같다.

- 월봉상 장기 하락 압력이 여전히 강함
- 주봉 하락 추세가 명확히 유지됨
- 단순 1~2주 반등만 존재함
- 주봉 저점 구조 개선이 없음
- 이동평균 구조 개선 없이 가격만 단기 급등함
- 장기 저항 바로 아래에서 일시적 반등만 발생함
- 거래 증가 없이 단기 기술적 반등만 발생함

가격이 올랐다는 사실만으로 `TRIGGER`가 되지 않는다.

### `SETUP`

`SETUP`은 아직 `TRIGGER`가 아니다. 상승 전환 가능성을 보여주는 주봉 구조
변화가 시작됐지만, 실제 전환을 확정할 정도의 구조가 완성되지 않은 상태다.

하락 기울기 둔화, 저점 방어, 주봉 MA 평탄화 시작, Range 상단 접근, 주봉 고점
구조 개선 시도 등이 예가 될 수 있다. `SETUP`은 관찰 대상이지 매수 신호가
아니다.

### `TRIGGER`

`TRIGGER`는 Pattern A FAST의 핵심 연구 대상이다. 월봉 환경이 허용 가능한
상태에서 주봉 가격 구조가 단순 반등을 넘어 상승 전환 가능성을 처음으로
의미 있게 보여주는 시점이다.

`TRIGGER`는 상승이 완전히 확인된 시점보다 빨라야 하지만 단순 반등보다 충분한
구조적 증거를 가져야 한다. 개념적 목표는 다음과 같다.

```text
TOO_EARLY < TRIGGER < Pattern A의 보수적 확인 시점
```

이것은 개념적 목표이지 모든 종목에서 반드시 Pattern A보다 먼저 발생해야 한다는
뜻은 아니다. `TRIGGER`가 자동 매수 신호라는 뜻도 아니다.

### `TREND`

`TREND`는 Fast Trigger 이후 주봉 상승 구조가 지속되고 있는 상태다. Pattern A의
`TRANSITION` 또는 `EARLY_TREND`와 겹칠 수 있지만, Fast 관점에서는 최초 진입
Trigger가 아니라 진행 중인 추세로 본다.

### `EXTENDED`

`EXTENDED`는 초기 진입 구간을 상당 부분 지난 상태다. 나쁜 종목, 하락 예상,
매도 신호를 뜻하지 않는다. Pattern A에서는 `EARLY_TREND`일 수도 있고 장기 투자
관점에서는 여전히 유효할 수 있다. 다만 Fast 신규 진입 관점에서는 Risk / Reward가
악화된 상태로 해석한다.

`EXTENDED`는 terminal state가 아니다. 건강한 조정이나 횡보 뒤
`EXTENDED → TREND`가 가능하고, 구조가 충분히 reset되면
`EXTENDED → WATCH` 또는 `SETUP`도 개념상 가능하다. 실제 Episode reset 규칙은
별도 계약에서 다룬다.

### `FALSE_TRIGGER`

`FALSE_TRIGGER`는 `TRIGGER` 직후 기존 하락 구조로 복귀하는 경우를 뜻하는
사후 평가 Label이다. 주봉 돌파 실패, 주봉 저점 구조 붕괴, 장기 Range 하단
회귀, 지속적인 상승 구조로 연결되지 못한 반등 등이 예다.

`FALSE_TRIGGER` 판정 기간은 이 정의에서 공식 Threshold로 고정하지 않는다.

### `TOO_LATE`

`TOO_LATE`는 주봉 전환이 이미 충분히 진행된 뒤 뒤늦게 Fast Trigger가 발생한
경우다. Fast의 가치가 낮아지는 사례를 표현하지만, 개별 사례 하나만으로 실패로
판정하지 않고 전체 코호트에서 평가한다.

## 성공 신호의 의미

`SUCCESSFUL FAST SIGNAL`은 다음 조건을 함께 만족하는 신호다.

- Trigger 이후 주봉 상승 구조가 의미 있게 유지되거나 발전함
- 기존 장기 하락·정체 구조로 즉시 복귀하지 않음
- Pattern A보다 유의미한 선행 탐지 가능성을 제공함

성공을 단순 수익률로 정의하지 않는다. 예를 들어 Trigger 후 `+10%` 같은 단일
수익률 Threshold를 이 정의에 넣지 않는다. 구조적 성공과 투자 성과는 별도로
검증한다.

## 사후 검증에서 보는 축

다음 축을 측정할 수 있다.

- Pattern A `TRANSITION`까지의 Lead Time
- Pattern A `EARLY_TREND`까지의 Lead Time
- False Trigger Rate
- Trigger 이후 실패 여부
- Trigger 이후 Stage progression
- Trigger 이후 최대 adverse excursion
- Trigger 이후 최대 favorable excursion

어떤 수치가 PASS 기준인지 이 문서에서 정하지 않는다. 먼저 실제 Ground Truth의
분포를 확인한 뒤 별도 검증에서 판단한다.

## Ground Truth Label

주봉 Lifecycle Stage와 사후 Ground Truth / Outcome Label은 분리한다.

- **Lifecycle Stage**: PIT 시점의 주봉 구조 상태
- **Ground Truth Label**: 이후 구조를 사람이 검토해 붙이는 사후 결과 Label

사람이 사용할 수 있는 Label의 의미는 다음과 같다.

- `GOOD_TRIGGER`: 월봉 환경이 허용 가능하고 주봉 구조 전환이 이후 유지·발전한 이상적인 Trigger
- `BORDERLINE_TRIGGER`: Trigger 조건은 성립하지만 이후 진행이 약하거나 불확실한 사례
- `FALSE_TRIGGER`: Trigger 직후 기존 하락·횡보 구조로 복귀하거나 돌파가 실패한 사례
- `TOO_EARLY`: 구조적 증거 없이 가격만 움직여 아직 Trigger로 볼 수 없는 사례
- `TOO_LATE`: 주봉 전환이 충분히 진행된 뒤 포착되어 선행 가치가 낮은 사례
- `TOO_EXTENDED`: 초기 진입 구간을 지나 신규 진입 Risk / Reward가 악화된 사례
- `NO_SETUP`: 관찰 시점 기준 `SETUP`에 해당하는 구조 변화조차 없는 사례

Lifecycle Stage의 `EXTENDED`와 사후 Label의 이름이 충돌하지 않도록 사후 Label은
`TOO_EXTENDED`를 사용한다. Lifecycle Stage의 `EXTENDED` 이름은 유지한다.

## Point-in-Time 원칙

특정 historical week의 판단에는 그 주 시점까지 확정된 데이터만 사용한다.

Trigger 계산에 미래 주가, 미래 거래량, 미래 Stage, 미래 Pattern A 판정, 미래
수익률을 사용하지 않는다. 미래 데이터는 사후 Validation, Ground Truth, Outcome
Audit와 Failure Analysis에서만 사용한다.

## 다른 분석 축과의 분리

Pattern Detection은 다음 축과 섞지 않는다.

- Relative Strength (`RS`)
- Foreign Flow
- Investability
- Market Cap
- Trading Value hard filter
- Sector RS와 Market RS

Pattern A FAST는 `RS` 데이터가 없어도 계산 가능한 독립 패턴이어야 한다. 예를 들어
`Pattern A Fast TRIGGER`이면서 동시에 `FILTERED_MARKET_CAP`일 수 있고, 이것은
정상적인 결과다. `A FAST Core` 전략이 이 결과를 이용할지는 별도 전략 계약에서
결정한다.

## 이 문서의 범위 밖인 것

이 정의는 다음을 공식 규칙으로 만들지 않는다.

- MA12 > MA24 같은 확정 규칙
- 8주 Breakout Threshold
- 12주 Range Threshold
- Volume Ratio Threshold
- Fast Score 0~100과 TRIGGER 점수 Cutoff
- Daily READY 조건
- False Trigger 기간 숫자
- Backtest와 Optimization
- 전체 시장 스캔과 실제 Candidate 생성

## 개념 예시

실제 종목을 사용하지 않는 개념 예시다.

### 좋은 Fast Trigger 후보

- 월봉: 장기 바닥권이 허용됨
- 주봉: 하락 둔화 → `SETUP` → 구조 돌파
- 일봉: 과열 아님
- 결과: `GOOD_TRIGGER` 후보

### `TOO_EARLY`

- 월봉: 장기 하락 진행 중
- 주봉: 2주 급반등
- 일봉: 강한 양봉
- 결과: `TOO_EARLY`

### `EXTENDED` / `TOO_LATE`

- 월봉: 상승 추세가 상당 부분 진행됨
- 주봉: 장기 이격 확대
- 일봉: 신고가 급등
- 결과: `EXTENDED` / `TOO_LATE`

| 시점 | Pattern A | Pattern A FAST |
|---|---|---|
| Week 0 | `BASE` | `SETUP` |
| Week 4 | `BASE` | `TRIGGER` |
| Week 10 | `TRANSITION` | `TREND` |
| Week 18 | `EARLY_TREND` | `EXTENDED` |

## 참고: 정의의 이력

이 문서는 초기 개념 정의(Phase 13A, Base commit
`9a8013005a28af113fb10607cd493eba8ed32184`)에서 출발했어. 초기 문서가 이후
검토 단계를 현재의 진행 예정 작업처럼 보이게 하지 않도록, 현재 적용되는 주봉
Stage 의미와 전이 원칙은 [weekly_lifecycle.md](weekly_lifecycle.md)에서
관리한다.
