# Pattern A Fast Weekly Lifecycle Contract v0.1

================================================================================
0. 문서 상태
================================================================================
Phase: 13B — Pattern A Fast Weekly Lifecycle Contract
Status: **CLOSED / Weekly Lifecycle Semantics v0.1 Frozen** (사용자 리뷰
승인 완료. Classifier Rules: NOT FROZEN — Feature / Threshold / Score:
NOT FROZEN)
Base: `dd0dec386d1382f9176ec8a876b17fd4bcdeb51e`
선행 문서: [docs/patterns/pattern_a_fast/spec/definition_v01.md](definition_v01.md) (Phase 13A, CLOSED)

이 문서는 WATCH / SETUP / TRIGGER / TREND / EXTENDED 5개 Weekly
Lifecycle Stage의 의미와 전이 원칙을 고정하는 계약이다. Feature 공식,
숫자 Threshold, Classifier 구현은 포함하지 않으며 이 셋은 여전히
NOT FROZEN이다. Stage 이름 5개와 의미는 사용자 승인을 거쳐 공식
Freeze되었다.

--------------------------------------------------------------------------------
1. Purpose (목적)
--------------------------------------------------------------------------------
Phase 13A에서 인간 언어 수준으로 정의한 Pattern A Fast의 목적을 바탕으로,
Pattern A Fast의 공식 Weekly Lifecycle Stage 의미와 전이 원칙을 정의한다.

핵심 계약 대상:
* WATCH / SETUP / TRIGGER / TREND / EXTENDED 각 상태가 정확히 무엇을
  의미하는지
* 서로 어떻게 구분되는지
* 어떤 전이가 정상적인지, 어떤 후퇴가 허용되는지
* Trigger Event를 어떻게 해석하는지
* Ground Truth Label과 Lifecycle Stage를 어떻게 분리하는지

이번 단계에서는 아직 Feature 공식이나 숫자 Threshold를 만들지 않는다.
Stage의 "의미"를 먼저 고정한다.

--------------------------------------------------------------------------------
2. Authority and Relationship to 13A
--------------------------------------------------------------------------------
기준 문서는 `docs/patterns/pattern_a_fast/spec/definition_v01.md`이다. Phase 13B는
Phase 13A의 철학을 변경하지 않는다.

고정 원칙 (13A 승계):
* Pattern A Fast는 Pattern A와 독립.
* Pattern A는 `DONE / FROZEN`.
* Monthly = Regime / Environment, Weekly = Core Setup / Trigger /
  Lifecycle, Daily = Timing Support.
* Pattern A는 Ground Truth가 아니라 Lead Time Benchmark.
* RS / Flow / Investability는 Pattern Detection과 분리.
* PIT 원칙 유지.

--------------------------------------------------------------------------------
3. Orthogonal Timeframe Architecture
--------------------------------------------------------------------------------
Pattern A Fast Lifecycle Stage의 핵심 시간축은 **WEEKLY**다. 공식적으로
Stage를 **Weekly Lifecycle Stage**로 정의한다. 즉 WATCH / SETUP /
TRIGGER / TREND / EXTENDED는 기본적으로 주봉 구조의 현재 상태를
표현한다.

Pattern A Fast는 최소 다음 3개 축을 분리한다:
* `monthly_regime`
* `weekly_lifecycle_stage`
* `daily_timing`

이번 13B에서 Freeze하는 것은 `weekly_lifecycle_stage` semantics
뿐이다. Monthly Regime taxonomy 및 계산은 Phase 13D, Daily Timing
taxonomy 및 계산은 Phase 13F에서 다룬다.

최종적으로 Monthly Regime + Weekly Lifecycle Stage + Daily Timing을
함께 해석할 수 있지만, Weekly Stage 자체에 Monthly / Daily 조건을
섞지 않는다. 따라서 예를 들어 향후 `Monthly: BAD, Weekly: TRIGGER,
Daily: READY` 같은 조합도 기술적으로 가능하며 이것은 오류가 아니다.
최종 Candidate 여부는 향후 별도 Production Contract에서 결정한다.

--------------------------------------------------------------------------------
4. Weekly Lifecycle Stage Definition
--------------------------------------------------------------------------------
Phase 13A의 provisional lifecycle을 Phase 13B의 기본 Lifecycle
Contract v0.1 후보로 사용하며, 이번 검토에서 구체적인 semantic
contradiction이 발견되지 않아 다음 5개 명칭을 **Stage Contract v0.1로
고정**한다:

```
WATCH   SETUP   TRIGGER   TREND   EXTENDED
```

이것은 Stage 의미 Freeze이며 Classifier Rule Freeze가 아니다. Stage
이름과 의미는 고정하지만, 어떤 Feature / Threshold가 각 Stage를
만드는지는 아직 미정이다.

**Stage는 현재 상태를 표현한다.** Pattern A Fast Stage는 "이 종목이
과거에 어디까지 갔었는가"가 아니라 "현재 PIT 시점의 주봉 구조가 어떤
lifecycle 상태인가"를 표현한다. 따라서 Stage는 비가역적 State Machine이
아니다(전이 원칙은 §11~§12 참고).

**Stage는 이전 Stage에 의해 강제되지 않는다.** 각 historical weekly
snapshot은 해당 시점까지 이용 가능한 데이터만으로 독립 평가 가능해야
한다. Stage(t)는 기본적으로 현재 PIT weekly structure에서 결정되며,
Stage(t-1)가 Stage(t)를 강제로 제한하지 않는다("지난주 SETUP이었으니
이번주는 무조건 SETUP 또는 TRIGGER만 가능" 같은 artificial state
locking 금지). 향후 persistence / hysteresis가 정말 필요하다는 독립
evidence가 발견되면 별도 연구하며, 이번 13B에서는 도입하지 않는다.

**Stage Precedence**: 한 snapshot은 최종적으로 하나의 Weekly Lifecycle
Stage만 가진다. 여러 설명이 동시에 가능한 경우 "현재 구조가 어느
lifecycle 위치까지 진행되었는가"를 기준으로 가장 적절한 한 상태를
선택한다. 개념적 진행 순서는 `WATCH < SETUP < TRIGGER < TREND <
EXTENDED`이지만, 이 순서는 좋음/나쁨 순위나 Score 순위가 아니라 단순
lifecycle 진행 위치다. 실제 classifier precedence rule은 Feature
연구 후 확정한다.

--------------------------------------------------------------------------------
5. WATCH
--------------------------------------------------------------------------------
핵심 질문: "주봉 기준으로 아직 상승 전환 Setup이 충분히 형성되지
않았는가?"

인간 언어 정의: 주봉 구조에서 상승 전환을 연구할 이유는 존재할 수
있으나, SETUP이라고 부를 만큼 구조적 개선 증거가 아직 충분하지 않은
상태.

WATCH는 다음을 의미하지 않는다: 나쁜 종목 / 매도 대상 / 월봉 환경
BAD / Pattern A 실패. WATCH는 단순히 Weekly Fast Lifecycle의 초기
관찰 상태다.

가능한 개념 예(구체 Feature는 미확정): 하락 둔화가 아직 불명확 / 저점
개선이 부족 / 주봉 MA 구조 변화가 미약 / range 내 의미 있는 구조 변화가
부족.

--------------------------------------------------------------------------------
6. SETUP
--------------------------------------------------------------------------------
핵심 질문: "상승 전환 가능성을 보여주는 주봉 구조 변화가 실제로
시작됐는가?"

인간 언어 정의: 단순한 가격 반등을 넘어 주봉 구조에서 상승 전환
가능성을 설명할 수 있는 초기 변화가 여러 방향에서 나타나기 시작했지만,
아직 최초의 유의미한 전환 Trigger라고 부르기에는 결정적 증거가 부족한
상태.

SETUP은 관찰 우선순위 상승 / 초기 준비 상태이지 매수 신호가 아니다.

핵심 경계: `WATCH < SETUP < TRIGGER`

--------------------------------------------------------------------------------
7. TRIGGER
--------------------------------------------------------------------------------
TRIGGER는 Pattern A Fast의 핵심 Stage다.

핵심 질문: "주봉 구조가 단순 반등을 넘어 실제 상승 전환 가능성을
처음으로 의미 있게 보여주는가?"

인간 언어 정의: 주봉에서 상승 전환 Setup이 충분히 성숙하고, 단순
기술적 반등이라고 보기 어려운 의미 있는 구조적 확인이 최초로 나타난
상태.

TRIGGER의 목적은 Pattern A의 보수적 확인 시점보다 더 빠른 전환
가능성을 포착하는 것이다. 단 TRIGGER는 무조건적인 매수 신호가 아니다.
Monthly Regime, Daily Timing, Investability, Flow, RS 등은 별도
축이다(§17~§19).

--------------------------------------------------------------------------------
8. Trigger Stage vs Trigger Event
--------------------------------------------------------------------------------
**TRIGGER Stage**: 현재 weekly snapshot이 TRIGGER 상태임을 의미한다.

**Trigger Event**: Lifecycle이 비-TRIGGER 상태에서 TRIGGER 상태로
처음 진입한 사건이다.

예: Week 1 `SETUP` → Week 2 `TRIGGER` → Week 3 `TRIGGER` → Week 4
`TREND`인 경우, Trigger Event Date는 **Week 2**다. Week 3을 새로운
Trigger Event로 중복 기록하지 않는다.

향후 Lead Time 분석에서 사용하는 날짜는 Trigger Stage가 지속된 모든
주가 아니라 **Trigger Event 진입 시점**이다. Episode / Re-Trigger
개념은 §21에서 다룬다.

--------------------------------------------------------------------------------
9. TREND
--------------------------------------------------------------------------------
핵심 질문: "현재 PIT weekly structure가 TRIGGER 수준의 초기 전환
구간을 넘어, 상승 구조가 지속/발전하는 lifecycle 위치에 있는가?"

인간 언어 정의: 주봉 가격 구조가 초기 전환 구간(TRIGGER가 표현하는
수준)을 넘어 상승 방향으로 지속/발전하고 있다는 증거가 나타난 상태.

중요: TREND는 과거 snapshot에서 실제 `TRIGGER` Stage가 관측되었을
것을 필수 조건으로 요구하지 않는다. Stage(t-1)는 Stage(t)의 mandatory
input이 아니라는 §4의 원칙(Stage는 이전 Stage에 의해 강제되지
않는다)을 TREND에도 동일하게 적용한다. 따라서 `SETUP → TREND`나
`WATCH → TREND`처럼 TRIGGER Stage를 건너뛰고 TREND로 direct jump한
episode도 정상이다(§12 Direct Jump 참고). 이 경우 Trigger Event는
관측되지 않은 것으로 취급하며, 존재하지 않는 과거 TRIGGER Stage를
추정하거나 backfill하지 않는다(상세 규칙은 §21 참고).

TREND는 초기 Trigger 수준보다 진행된 lifecycle 위치이지만, Fast
관점에서 반드시 늦었다는 뜻은 아니다. Pattern A에서는 같은 시점에
`BASE` / `TRANSITION` / `EARLY_TREND` 등 다양한 상태가 가능하며, 두
Pattern의 Stage 일치는 요구하지 않는다.

--------------------------------------------------------------------------------
10. EXTENDED
--------------------------------------------------------------------------------
핵심 질문: "Fast Strategy의 초기 진입 관점에서 이미 움직임이 상당 부분
진행됐는가?"

인간 언어 정의: 주봉 상승 구조 자체는 강하거나 정상일 수 있으나,
Pattern A Fast가 목표로 하는 초기 전환/초기 진입 구간은 상당 부분
지나간 상태.

중요: `EXTENDED != BAD`, `EXTENDED != 하락 예상`, `EXTENDED != 매도
신호`. 의미는 Fast 신규 진입 관점에서 초기 Risk/Reward가 악화된
상태라는 것뿐이다.

**EXTENDED는 terminal state가 아니다.** 예: `EXTENDED → 건강한 조정 /
횡보 → TREND`가 가능하다. 충분히 구조가 reset된 뒤 `EXTENDED → WATCH /
SETUP` 형태도 이론적으로 가능하다. 다만 실제 Episode reset semantics는
후속 연구에서 확정한다.

--------------------------------------------------------------------------------
11. Primary Forward Path
--------------------------------------------------------------------------------
가장 전형적인 forward progression:

```
WATCH → SETUP → TRIGGER → TREND → EXTENDED
```

이 경로는 **PRIMARY PATH**이지 강제 State Machine이 아니다.

--------------------------------------------------------------------------------
12. Regression and Direct Jump Semantics
--------------------------------------------------------------------------------
**Regression (후퇴) 허용**: Fast 구조는 실패하거나 약화될 수 있으므로
backward transition을 정상적인 현상으로 인정한다.

예: `SETUP → WATCH` / `TRIGGER → SETUP` / `TRIGGER → WATCH` / `TREND →
TRIGGER` / `TREND → SETUP` / `EXTENDED → TREND` 등. 정확한 Feature
조건은 향후 결정한다. 핵심은 Stage regression 자체를 Classifier
Error로 간주하지 않는다는 것이다.

**Direct Jump 허용**: Stage는 이전 Stage에 의해 강제되지 않으므로
direct jump도 원칙적으로 가능하다. 예: `WATCH → TRIGGER` / `SETUP →
TREND` / `WATCH → TREND` / `TREND → WATCH` 같은 이동이 실제 PIT
구조에 의해 정당화될 수 있다. 다만 이러한 direct jump가 빈번하게
발생하면 Stage semantics 또는 classifier가 너무 거칠다는 evidence가
될 수 있으며, 향후 validation에서 별도 감사한다. 13B에서 direct
jump 자체를 금지하지 않는다.

**Direct Jump와 Trigger Event는 별개 계약이다**: `SETUP → TRIGGER →
TREND`처럼 `TRIGGER` Stage를 실제로 거친 경우에만 Trigger Event가
존재한다. `SETUP → TREND`처럼 `TRIGGER` Stage 없이 TREND로 direct
jump한 episode는 historical TRIGGER Stage가 관측되지 않았으므로
synthetic/inferred Trigger Event Date를 만들지 않는다. 상세 규칙과
Lead Time 처리는 §21 참고.

--------------------------------------------------------------------------------
13. PIT / Completed Weekly Rule
--------------------------------------------------------------------------------
**Completed Weekly Bar 원칙**: Weekly Lifecycle Stage는 기본적으로
완료된 주봉 데이터만 사용한다. 특정 as_of 시점에서 현재 진행 중인
미완성 주봉을 완료된 주봉처럼 Stage 판단에 사용하지 않는다. 이유는
주중 가격 급등/급락으로 Stage가 일시적으로 왜곡되는 것을 방지하기
위함이다. 즉 `Weekly Stage = Completed Weekly Structure`, `Daily
Timing = as_of까지 완료된 Daily Data`로 책임을 분리한다.

**Monthly Completed Period 참고**: Monthly Regime은 향후 13D에서
공식화하지만, 기본 원칙은 완료된 월봉을 사용하는 것이다. 미완성
월봉을 확정 Monthly Regime처럼 취급하지 않는다. 향후 current month
정보를 활용할 필요가 있다면 별도의 Current Month Supporting
Observation으로 분리하고 완료 월봉 기반 Regime과 혼합하지 않는다.

**Point-In-Time Contract**: Stage(t)는 t 시점까지 확정된 데이터만
사용한다. 금지: 미래 주봉, 미래 일봉, 미래 Pattern A Stage, 미래
수익률, 미래 거래량, 미래 Trigger 성공 여부. 미래 데이터를 이용하여
현재 Stage를 결정하면 Lookahead 위반이다. 미래 데이터는 Ground Truth
/ Outcome Audit / Failure Analysis에서만 사용한다.

--------------------------------------------------------------------------------
14. Stage vs Score Independence
--------------------------------------------------------------------------------
향후 Pattern A Fast Score가 만들어지더라도 Weekly Lifecycle Stage와
Score는 독립 축으로 유지한다.

금지 예: `Fast Score >= 80 => TRIGGER`, `Fast Score >= 90 => TREND`
같은 구조.

Stage는 주봉 lifecycle의 구조적 의미를 표현하고, Score는 별도의
연속적 측정값이다. Pattern A에서 유지한 `Score != Stage` 원칙을
Pattern A Fast에도 동일하게 적용한다.

--------------------------------------------------------------------------------
15. Stage vs Ground Truth Label
--------------------------------------------------------------------------------
매우 중요한 분리다.

**Lifecycle Stage** (PIT 시점의 구조적 상태): `WATCH` / `SETUP` /
`TRIGGER` / `TREND` / `EXTENDED`

**Ground Truth / Outcome Label** (사후 리뷰 라벨): `GOOD_TRIGGER` /
`BORDERLINE_TRIGGER` / `FALSE_TRIGGER` / `TOO_EARLY` / `TOO_LATE` /
`TOO_EXTENDED`

**Naming Collision 해결**: 13A에서 Lifecycle Stage `EXTENDED`와
Ground Truth Label `EXTENDED`가 동일 이름으로 존재해 dataset에서
혼동 가능성이 있었다. 검토 결과 Ground Truth 쪽 명칭을
`TOO_EXTENDED`로 변경한다(`TOO_EARLY`/`TOO_LATE`와 동일한 `TOO_*`
명명 규칙 통일, 의미 변경 없음). Lifecycle Stage 쪽 `EXTENDED` 이름은
그대로 유지한다. 상세 변경 기록은
`docs/patterns/pattern_a_fast/spec/definition_v01.md` §19 참고.

**FALSE_TRIGGER는 Stage가 아니다.** FALSE_TRIGGER는 미래 outcome을
본 뒤 붙이는 사후 Review Label이다. 현재 시점에서 `TRIGGER`였던
판단이 나중에 실패했다고 해서 historical Stage를 `FALSE_TRIGGER`로
rewrite하지 않는다. 예: 2025-03-07 PIT `TRIGGER`, 2025-05 Outcome
Review `FALSE_TRIGGER` → historical PIT Stage는 그대로 `TRIGGER`
유지. 정상이다.

**GOOD_TRIGGER도 Stage가 아니다.** PIT 당시에는 `TRIGGER`, 이후
구조가 성공적으로 발전하면 Ground Truth Label `GOOD_TRIGGER`로
평가한다. 미래 성공 여부를 Stage classifier 입력에 넣지 않는다.

**TOO_EARLY / TOO_LATE도 Stage와 분리된 Human Review / Validation
Label이다.** Lifecycle Stage와 동일 개념으로 사용하지 않는다. 예:
PIT Weekly Lifecycle `SETUP` + Human Review `TOO_EARLY` 가능. 또는
PIT Weekly Lifecycle `TREND` + Human Review `TOO_LATE` 가능.

--------------------------------------------------------------------------------
16. UNAVAILABLE / NOT_EVALUATED
--------------------------------------------------------------------------------
데이터 부족 / 손상 / PIT weekly snapshot 계산 불가 상태를 정상
Lifecycle Stage에 억지로 배정하지 않는다. **WATCH로 fallback
금지.**

권장: `weekly_lifecycle_stage = UNAVAILABLE`. 단 UNAVAILABLE은
`WATCH / SETUP / TRIGGER / TREND / EXTENDED`와 같은 lifecycle
state가 아니라 **Data / Evaluation Status**다. 이를 명확히 분리한다.

필요하다면 향후 `NOT_EVALUATED`를 사용할 수 있다(예: 사용자가 Fast
분석을 요청하지 않음, 필수 upstream 구조 자체가 아직 평가되지 않음).
단 Monthly Regime `BAD`라는 이유만으로 Weekly Stage를
`NOT_EVALUATED`로 숨기지는 않는 것을 기본 원칙으로 한다. Weekly
Lifecycle은 연구 및 진단을 위해 독립적으로 관측 가능해야 한다.

--------------------------------------------------------------------------------
17. Monthly Regime Independence
--------------------------------------------------------------------------------
예를 들어 향후 `Monthly: BAD`, `Weekly: TRIGGER`가 발생할 수 있다.
이 경우 Weekly TRIGGER를 억지로 WATCH로 rewrite하지 않는다. 대신
향후 final Pattern A Fast interpretation에서 Monthly Regime이 Fast
Candidate를 허용하는지 별도로 판단한다. 이 방식으로 Monthly Gate가
Weekly Stage 의미를 오염시키지 않도록 한다.

--------------------------------------------------------------------------------
18. Daily Timing Independence
--------------------------------------------------------------------------------
예: `Weekly: TRIGGER`, `Daily: EXTENDED / WAIT` 가능. Daily Timing이
좋지 않다고 해서 Weekly TRIGGER를 SETUP으로 낮추지 않는다. 반대로
`Weekly: WATCH`인데 Daily가 READY처럼 보이는 단기 급등이라도 Weekly
Stage를 TRIGGER로 올리지 않는다. Daily는 Timing Support Layer다.

--------------------------------------------------------------------------------
19. Investability / Flow / RS Independence
--------------------------------------------------------------------------------
다음은 Weekly Stage에 영향을 주지 않는다: Market Cap, Investability
Status, Foreign Flow, Market RS, Sector RS, Liquidity Filter.

예: `Weekly: TRIGGER` + `Investability: FILTERED_MARKET_CAP`은
정상이다. Weekly Stage는 가격 구조 lifecycle만 표현한다.

--------------------------------------------------------------------------------
20. Transition History
--------------------------------------------------------------------------------
향후 Stock Report / Scanner에서 Weekly Stage Transition History를
만들 경우, 실제 Stage가 변경된 시점만 기록한다.

예: `SETUP, SETUP, TRIGGER, TRIGGER, TREND` → Transition: `SETUP →
TRIGGER`, `TRIGGER → TREND`. 동일 Stage 반복은 transition event가
아니다.

--------------------------------------------------------------------------------
21. Trigger Event / Episode Concept
--------------------------------------------------------------------------------
**Re-Trigger**: 한 종목에서 여러 차례 Trigger Event가 발생할 수 있다.
예: `SETUP → TRIGGER → WATCH` 이후 `WATCH → SETUP → TRIGGER`인 경우
두 번째 TRIGGER는 새로운 Trigger Event 후보가 될 수 있다. 다만 "새로운
Episode를 언제 인정할 것인가", "얼마나 reset되어야 새로운 Trigger인가"
에 대한 숫자 기준은 13B에서 Freeze하지 않는다. Episode / Reset
threshold는 Human Ground Truth와 실제 사례를 본 뒤 결정한다.

**Multiple Trigger Event 주의**: 한 종목에서 Trigger Event가 여러
번 발생하면 향후 분석에서 first trigger only / best trigger / latest
trigger를 임의 선택하지 않는다. 각 Trigger Event를 episode 단위로
관리할 가능성을 열어둔다. 이번 13B에서는 Event identity 필요성만
계약에 기록하며, Episode segmentation 공식은 아직 만들지 않는다.

**Trigger Lead Time 기준점**: 향후 Pattern A 비교에서 Lead Time
기준점은 Trigger Event Date를 사용한다. 비교 대상은 Pattern A
`TRANSITION` first date, Pattern A `EARLY_TREND` first date다. 단
Pattern A가 해당 Stage에 도달하지 않은 종목은 Fast 실패로 자동
처리하지 않는다 — Lead Time은 `NOT_APPLICABLE` 또는 별도 상태로
처리한다. 실제 schema는 13H에서 확정한다.

**Skipped Trigger (관측되지 않은 Trigger Event)**: TRIGGER Stage를
건너뛰어 TREND 이상으로 direct jump한 episode는 Trigger Event를
임의 생성하지 않는다. 이 상태를 개념적으로 `trigger_event =
NOT_OBSERVED`(또는 의미가 동일한 명칭)로 명시한다. 정확한 production
schema enum은 아직 Freeze하지 않아도 되며, Freeze하는 핵심 semantic은
다음 한 가지뿐이다: **관측되지 않은 Trigger Event Date를 추정하거나
backfill하지 않는다.**

**Lead Time 처리 (Trigger Event 미관측 시)**: Pattern A 대비 Lead
Time은 실제 관측된 Trigger Event Date가 있을 때만 계산한다. explicit
Trigger Event가 없는 direct jump episode는 Lead Time을
`NOT_EVALUATED` / `NOT_APPLICABLE` 계열 상태로 처리한다(정확한 schema
이름은 13H에서 확정). 다음은 금지한다:
* TREND 첫 날짜를 Trigger Date로 silently 사용
* SETUP과 TREND 사이 임의 날짜를 Trigger Date로 추정
* 미래 데이터를 보고 Trigger Date를 역추론

**13C Annotation Schema Concept**: 13C Human Ground Truth Dataset에서는
최소 다음 두 종류를 분리해서 기록할 수 있도록 schema concept만
제안한다(아직 실제 dataset은 만들지 않는다):
* PIT STRUCTURE: `weekly_stage_at_reference` (예: `TRIGGER`)
* OUTCOME LABEL: `human_label` (예: `GOOD_TRIGGER` 또는
  `FALSE_TRIGGER`)

--------------------------------------------------------------------------------
22. Synthetic Examples
--------------------------------------------------------------------------------
**Example 1 — 정상 Forward**
`WATCH → SETUP → TRIGGER → TREND → EXTENDED`

**Example 2 — Setup Failure**
`WATCH → SETUP → WATCH`

**Example 3 — False Trigger**
`SETUP → TRIGGER → WATCH`
PIT Stage: `TRIGGER` / Outcome Label: `FALSE_TRIGGER`

**Example 4 — Successful Trigger**
`SETUP → TRIGGER → TREND`
Trigger Event: TRIGGER 진입 주 / Outcome Label: `GOOD_TRIGGER`

**Example 5 — Monthly Conflict**
Monthly: `BAD`, Weekly: `TRIGGER`
결론: Weekly Stage는 `TRIGGER` 유지. Final Candidate 판단은 향후 별도.

**Example 6 — Daily Conflict**
Weekly: `TRIGGER`, Daily: `WAIT`
결론: Weekly Stage는 `TRIGGER` 유지.

**Example 7 — De-extension**
`EXTENDED → TREND` (건강한 조정 후 de-extension 사례)

**Example 8 — Direct Jump to TREND (Skipped Trigger)**
Week 1: `SETUP` / Week 2: `TREND`
Weekly Stage: `TREND` / Observed Trigger Event: `NO` / Trigger Event
Date: 없음 / Lead Time from Trigger: `NOT_EVALUATED`
이 direct jump 자체는 Stage 오류가 아니며, 향후 실제 발생 빈도를
validation에서 감사한다.

--------------------------------------------------------------------------------
23. Non Goals
--------------------------------------------------------------------------------
이번 단계에서 만들지 않는 것: Weekly MA 기간 / Monthly MA 기간 /
Range 기간 / Slope threshold / Breakout threshold / Volume threshold
/ Trading Value threshold / Volatility threshold / Fast Score / Stage
Score Cutoff / Candidate Cutoff / Daily READY threshold / Monthly
GOOD·BAD 공식 / False Trigger 주수 / Episode Reset 기간 / Return
threshold / MDD threshold / Success Rate PASS 기준.

--------------------------------------------------------------------------------
24. Open Questions for 13C / 13D / 13E
--------------------------------------------------------------------------------
13B에서 억지로 답을 만들지 않고 다음 단계로 넘기는 질문:

* Episode / Re-Trigger reset 기준은 몇 주 또는 어떤 구조 조건인가?
* Trigger Stage precedence rule의 실제 Feature 기반 구현은
  어떻게 되는가?
* Direct jump가 실제 데이터에서 얼마나 자주 발생하며, 그 빈도가
  Stage semantics 재검토를 요구하는 수준인가?
* Weekly Lifecycle과 Monthly Regime을 최종적으로 어떻게 결합해
  Candidate를 만들 것인가(13G Production Contract 대상)?
* `NOT_EVALUATED`를 실제로 언제 도입할 것인가?
* Ground Truth Label 수집 시 `weekly_stage_at_reference`와
  `human_label`을 어떤 UI/스키마로 기록할 것인가?

답은 13B에서 확정하지 않는다. 13B 승인 후 다음 단계는 Phase 13C
Human Ground Truth Dataset이며, 실제 차트를 기준으로 `GOOD_TRIGGER` /
`BORDERLINE_TRIGGER` / `FALSE_TRIGGER` / `TOO_EARLY` / `TOO_LATE` /
`TOO_EXTENDED` / `NO_SETUP` 사례를 수집하고 각 사례의 reference date,
weekly lifecycle interpretation, trigger event, 사후 outcome label,
Pattern A 당시 Stage, Pattern A 이후 전환 시점을 분리 기록한다. 13C
에서도 아직 Feature Threshold 최적화는 시작하지 않으며, 정답 사례를
충분히 확보한 뒤 13D Monthly Regime Research, 13E Weekly Trigger
Feature Research로 넘어간다.
