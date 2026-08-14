# KRX Trend Scanner Development Roadmap

이 문서는 향후 작업 순서의 기준 문서다. 새로운 아이디어가 생겨도 바로
구현하지 않고, 어느 Phase에 속하는지 먼저 이 문서에서 위치를 정한다.

## 핵심 목표

이 프로젝트의 최종 목표는 단순히 **"이미 상승 중인 강한 종목"**을
찾는 것이 아니다.

최종 목표는:

> 대세 상승이 만들어지기 시작하는 종목을 여러 독립적인 패턴과
> 시장 신호를 이용해 조기에 탐지하는 것

기본 철학:

```text
가격 구조 -> 장기 추세 -> 상대강도 -> 거래대금 -> 수급 -> 펀더멘털
```

순으로 증거를 쌓고, 각 Pattern A~F는 먼저 독립적으로 검증한 뒤
마지막 단계에서 Market Leader Score로 통합한다.

## Status 표기 규칙

각 Phase는 다음 status 중 하나를 쓴다: `DONE` / `IN PROGRESS` / `NEXT` /
`PLANNED` / `BLOCKED`.

## Current Status

**Pattern A**

| 단계 | 상태 |
|---|---|
| Feature Validation | DONE |
| Historical Snapshot Validation | DONE |
| Holdout Validation | DONE |
| Negative Control | DONE |
| Outcome Audit | DONE |
| Base / Expansion Validation | DONE |
| Feature Set Freeze v0.1 | DONE |
| Score Design v0.1 (freeze `6e7cc95`) | DONE |
| Frozen Score External Case Validation (OOS Case Validation v0.1) | DONE |
| v0.2 diagnostic dataset 정리(OOS v0.1 29건 고정) | DONE |
| Score Design v0.2 (implementation freeze `fffce85`) | DONE |

**Pattern B~F**: 미착수(NOT STARTED)
**전체 시장 Scanner**: 미착수(NOT STARTED)
**Market Leader Score**: 미착수(NOT STARTED)

## Phase 1. Pattern A Score v0.2 — DONE

목표: Pattern A Score의 구조적 문제를 해결하고 최종 v0.2 Score를
freeze한다.

핵심 작업:

* Core / Supporting interaction 재설계
  * ma24_slope가 Core 역할을 유지하도록 구조화
  * weekly_ma12_slope와 ma24_slope_acceleration이 Core 없이 Transition
    Score를 과도하게 끌어올리지 못하게 개선
* alignment bonus 재검토
* Pattern A / Pattern B boundary용 장기 하락 구조 Feature 최소 후보 검증
* Already Progressed penalty는 기본 유지
* fast mover 사례는 diagnostic으로 관찰
* v0.2 development dataset으로 기존 29개 OOS Case 사용

완료 조건: **Pattern A Score v0.2 implementation freeze** — 커밋
`fffce85`로 완료됐다.

중요: OOS2는 이 단계에서 절대 보지 않았다(실제로 보지 않았음).

## Phase 2. Pattern A v0.2 OOS2 Validation — NEXT

v0.2를 완전히 freeze한 뒤 새로운 종목과 날짜를 사용한다.

기존 exploration / holdout / negative control / OOS Case v0.1
diagnostic에 사용된 종목/날짜와 독립적인 사례를 우선한다.

검증 대상:

* positive pre breakout
* clean early trend
* trend progressed
* false turn
* Pattern A / Pattern B boundary
* fast mover
* insufficient history

목표: v0.2가 새로운 사례에서도 의도한 방식으로 작동하는지 확인한다.

이 단계에서는 Score를 수정하지 않는다.

결과가 만족스러우면: **Pattern A Score v0.2 Final Freeze**.

## Phase 3. Pattern A Stage Classifier — PLANNED

Score와 별도로 Stage classifier를 재설계한다.

현재 자동 Stage heuristic은 progressed 사례를 early trend로 오판하는
문제가 확인됐다.

목표 Stage: `PRE_BREAKOUT` / `EARLY_TREND` / `TREND_PROGRESSED`. 필요하면
`WEAK` / `UNKNOWN` 등을 유지할 수 있다.

기준은 달력 시간이 아니라 가격 구조다 — "3개월 지났기 때문에 early" 같은
규칙을 쓰지 않는다. fast mover는 몇 달 만에도 TREND_PROGRESSED가 될 수
있다.

Manual Stage Rubric을 기준으로 자동 classifier를 별도 검증한다. Score
threshold와 Stage threshold를 동시에 튜닝하지 않는다.

## Phase 4. Pattern A Evaluator Integration — PLANNED

현재 `FeatureRow -> score_pattern_a()` 중심인 구조를 다음 경로로
연결한다:

```text
daily OHLCV -> weekly/monthly resampling -> FeatureRow
            -> Pattern A Score -> Stage -> Result
```

목표: 종목 하나와 날짜를 입력하면 Pattern A 분석 결과 하나를 반환할 수
있는 완전한 API.

결과 예: `ticker`, `name`, `pattern_a_score`, `base_score`,
`transition_score`, `progressed_penalty`, `stage`, `flags`,
`feature_snapshot`, `insufficient_data`.

## Phase 5. Market Data Quality / Corporate Action Handling — PLANNED

전체 시장 Scanner 전에 데이터 품질 정책을 정리한다.

현재 확인된 문제:

* 일부 종목 OHLC validation 실패
* 액면분할
* 인적분할
* 재상장
* 장기 거래정지
* 과거 adjusted price 불연속
* 36개월 range 왜곡 가능성

필요한 작업:

* Corporate Action 처리 정책
* 분할 전후 가격 연결 정책
* 거래정지 구간 정책
* adjusted OHLC validation 정책
* 경제적으로 불연속인 장기 데이터 처리 방법
* invalid ticker / snapshot 처리 정책

목표: 전체 시장을 돌렸을 때 데이터 오류 때문에 의미 있는 종목이 대량
누락되거나 가짜 Pattern A가 생성되지 않도록 한다.

## Phase 6. Score Momentum — PLANNED

Pattern A Score의 변화 속도를 측정한다.

핵심 개념: `score_momentum_4w = current_pattern_a_score - pattern_a_score_4_weeks_ago`

추가 후보: `score_momentum_8w`, base_score 변화, transition_score 변화.

목표: 절대 Score가 이미 높은 종목보다 "점수가 빠르게 좋아지고 있는
종목"을 찾는다. 이 프로젝트의 "이미 오른 종목이 아니라 추세가 만들어지는
종목"이라는 철학과 직접 연결되는 신호다.

## Phase 7. KOSPI / KOSDAQ Universe Scanner v0.1 — PLANNED

처음으로 전체 Universe를 실제로 스캔한다.

초기 단계에서는 "70점 이상 매수 후보" 같은 Hard Threshold를 만들지
않는다. 먼저 전체 Score distribution을 본다.

종목별 저장 항목: `ticker`, `name`, `pattern_a_score`, `base_score`,
`transition_score`, `balanced_core_score`, `progressed_penalty`,
`score_momentum`, `stage`, `flags`, 주요 raw feature.

목표: 실제 수천 종목 Universe에서 Pattern A가 어떤 후보를 만들어내는지
관찰한다.

## Phase 8. Real Candidate Chart Review — PLANNED

Scanner 상위 후보를 사람이 직접 검토한다.

기본 차트 순서: 월봉 -> 주봉 -> 일봉. 월봉/주봉은 대세 구조 검증, 일봉은
단기 추세와 진입 timing 확인용이다.

초기에는 상위 20~50개 정도를 직접 검토한다.

목적: Score가 높은데 실제 차트상 이상한 종목, Corporate Action 왜곡,
하락 추세 반등, 이미 너무 진행된 종목, 유동성 부족 종목 등을 발견하는 것.

이 단계에서 나온 실패 사례는 Pattern A v0.3 후보로 기록할 수 있지만
즉시 Score를 튜닝하지 않는다.

## Phase 9. Liquidity / Trading Value Filter — PLANNED

실전 Scanner에서 잡주와 거래 빈약 종목을 걸러내기 위한 별도 축.

raw volume보다 trading_value를 우선한다.

후보: 20일 평균 거래대금, 60일 평균 거래대금, 돌파 구간 거래대금 증가,
거래대금 percentile, 시장 전체 대비 거래대금 rank.

초기에는 Pattern A Score에 섞지 않고 별도 eligibility / confirmation
신호로 사용한다.

## Phase 10. Relative Strength Infrastructure — PLANNED

Pattern D뿐 아니라 전체 Scanner에서 재사용할 공통 RS Feature를 만든다.

비교 대상: KOSPI, KOSDAQ, 업종, 시장 전체 Universe.

기간 후보: 3개월, 6개월, 12개월.

추가 중요 Feature: RS slope, RS acceleration, RS percentile, RS new
high, price breakout 이전 RS 개선.

목표: 시장보다 먼저 강해지는 종목을 찾는다.

## Phase 11. Flow Confirmation — PLANNED

외국인 / 기관 수급 축.

후보: 외국인 순매수, 기관 순매수, 최근 5일/20일/60일 누적, 시가총액
대비 순매수 비율, 거래대금 대비 순매수 비율, 가격 상승 + 기관/외국인
동시 유입.

초기에는 Pattern Score와 독립적으로 검증한다.

## Phase 12. Pattern B — PLANNED

**Pattern B: Long Downtrend Ending -> Stage 2 Transition**

장기 하락이 끝나고 새 상승 추세가 시작되는 유형.

Pattern A와의 차이:

* Pattern A: 장기 Base / 정체 후 상승 전환
* Pattern B: 장기 하락 추세 종료 후 상승 전환

Pattern A v0.2에서 검토한 downtrend structure Feature
(`long_term_high_slope_36m`, `prior_leg_drift_36m` — 검증됨, 단조
threshold로는 미채택)를 Pattern B에서 적극 재사용할 수 있다.

## Phase 13. Pattern C — PLANNED

**Pattern C: High / New High Compression -> Reacceleration**

이미 강한 종목이 고점 부근에서 무너지지 않고 압축된 뒤 다시 상승하는
구조.

Pattern A에서는 높은 range_position, 큰 MA expansion, 큰 range가
penalty가 될 수 있지만, Pattern C에서는 강한 주도주의 정상적인 특성이
될 수 있다.

따라서 Pattern별 Feature 의미가 다르다는 것을 명시한다.

## Phase 14. Pattern D — PLANNED

**Pattern D: Relative Strength Leads Price**

가격 돌파 전에 시장 / 업종 대비 상대강도가 먼저 좋아지는 유형.

Phase 10에서 만든 RS Infrastructure를 재사용한다.

핵심 질문: 가격은 아직 박스 안인데 RS는 이미 신고가 또는 상승 전환
중인가?

## Phase 15. Pattern E — PLANNED

**Pattern E: Volatility Contraction -> Expansion**

VCP와 유사한 유형.

여기서는 Pattern A에서 약했던 Feature들이 다시 주요 후보가 될 수 있다.
예: ATR, BB Width, range compression, volume contraction, trading
value contraction, breakout expansion.

중요: Pattern A에서 Drop 또는 Diagnostic이었던 Feature라고 해서
프로젝트 전체에서 쓸모없는 Feature는 아니다. Pattern별 검증을
독립적으로 한다.

## Phase 16. Pattern F — PLANNED

**Pattern F: Earnings Turnaround + Chart Leads Fundamentals**

OpenDART 기반 Fundamental Data Layer를 추가한다.

후보: 매출 성장, 영업이익 성장, 순이익 성장, YoY, QoQ, 적자 축소,
흑자 전환, 영업이익률 개선.

목표: 실적 개선이 공식 숫자로 완전히 확인되기 전에 차트가 먼저
개선되는 종목을 찾는다.

## Phase 17. Pattern Score Matrix — PLANNED

각 종목을 A~F 독립 Score로 표현한다.

```text
Pattern A 82
Pattern B 15
Pattern C 41
Pattern D 76
Pattern E 64
Pattern F 70
```

중요: A~F는 서로 대체 관계가 아니다. 한 종목이 A+D+F 또는 C+D+E처럼
여러 Pattern을 동시에 만족할 수 있다. 오히려 여러 독립 Pattern이 동시에
강한 경우 시장 주도주 후보로 의미가 커질 수 있다.

## Phase 18. Market Leader Score — PLANNED

A~F 독립 검증이 끝난 뒤 최종 종합 Score를 설계한다.

후보 구성: Pattern Scores, Relative Strength, Liquidity / Trading
Value, Foreign / Institutional Flow, Fundamentals, Score Momentum.

중요: Pattern A~F 단순 평균으로 시작하지 않는다. 각 신호의 역할과
중복성을 검토하고 독립 evidence가 겹칠수록 신뢰도가 높아지는 구조를
설계한다.

## Phase 19. Walk Forward / Paper Validation — PLANNED

실제 운영 시점에서 매주 또는 매일 당시 Score, 당시 Feature, 당시 선정
종목을 저장한다. 그 이후 실제 결과를 추적한다.

중요: 나중에 과거 차트를 보고 "여기가 좋은 진입점이었다"라고 고르는
retrospective validation과 구분한다.

이 단계부터 쌓이는 데이터가 장기적으로 가장 중요한 validation
dataset이 된다.

## Phase 20. Production Scanner — PLANNED

최종 운영 형태.

예시 출력: `ticker`, `name`, Pattern A~F Score, Market Leader Score,
Score Momentum, Relative Strength, Trading Value, Foreign Flow,
Institution Flow, Fundamental Trend, `stage`, `flags`, Candidate
Reasons.

최종 사용 흐름:

```text
Quant Scanner -> 후보 압축 -> 월봉 검토 -> 주봉 검토 -> 일봉 진입 timing 검토
```

## Near Term Milestones

1. Pattern A Score Design v0.2 — DONE
2. Pattern A OOS2
3. Pattern A Score Final Freeze
4. Pattern A Stage Classifier
5. Pattern A Evaluator Integration
6. Data Quality / Corporate Action
7. Score Momentum
8. Full Universe Scanner
9. Manual Chart Review

여기까지 완료되면: **Pattern A 기반 실사용 가능한 대세 상승 초입
Scanner v1**로 본다.

## Mid Term Milestones

* Liquidity
* Relative Strength
* Flow
* Pattern B
* Pattern C
* Pattern D
* Pattern E
* Pattern F

## Long Term Milestones

* Pattern Score Matrix
* Market Leader Score
* Walk Forward Validation
* Production Scanner

## Development Principles

**Principle 1**
Pattern별 Feature를 먼저 독립 검증한다.

**Principle 2**
한 Pattern에서 실패한 Feature를 다른 Pattern에서도 자동 폐기하지 않는다.

**Principle 3**
미래 수익률을 이용해 threshold를 최적화하지 않는다.

**Principle 4**
OOS 데이터를 본 순간 그 데이터는 다음 버전의 development data가 된다.

**Principle 5**
Score와 Stage를 분리한다.

**Principle 6**
가능하면 Hard Filter보다 해석 가능한 soft scoring을 우선한다.

**Principle 7**
전체 Score가 높은 이유를 사람이 설명할 수 있어야 한다.

**Principle 8**
월봉 / 주봉이 장기 추세 판단의 기본이고 일봉은 단기 추세와 진입
timing 확인에 사용한다.

**Principle 9**
실제 전체 시장 Scanner를 돌린 뒤 나오는 예상하지 못한 false positive를
중요한 검증 데이터로 취급한다.

**Principle 10**
Pattern A~F가 충분히 검증되기 전에는 Market Leader Score를 성급하게
만들지 않는다.
