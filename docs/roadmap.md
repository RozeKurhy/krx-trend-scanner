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
가격 구조 -> 장기 추세 -> 투자 적합성 필터 -> 수급 확인 -> 상대강도 -> 펀더멘털
```

순으로 증거를 쌓고, Pattern A, Pattern A Fast, Pattern B~F는 먼저 독립적으로 검증한 뒤
마지막 단계에서 Market Leader Score로 통합한다.

## Status 표기 규칙

각 Phase의 상태는 세 개의 독립적인 축으로 구성된다. "연구는 끝났지만
Production 승격은 아직"처럼 하나의 축만으로는 실제 상태를 다 표현하지
못하는 경우가 있으므로, 필요한 축만 골라 조합해서 표기한다.

**Phase lifecycle**(연구/구현 진행 상태): `PLANNED` / `IN_PROGRESS` /
`CLOSED` / `BLOCKED`

**Operational qualifier**(실행 우선순위/재개 상태, 필요한 Phase만):
`NEXT` / `RESUME_READY` / `FROZEN`

**Production / Usage qualifier**(실전 사용 가능 여부, Production 관련
Phase만): `PRODUCTION` / `PRODUCTION_HOLD` / `EXPERIMENTAL`

예:

* Pattern A: `Lifecycle = CLOSED`, `Production = PRODUCTION`, `Qualifier = FROZEN`
* Pattern A FAST: `Lifecycle = CLOSED`, `Production = PRODUCTION_HOLD`, `Usage = EXPERIMENTAL`
* Phase 12: `Lifecycle = PLANNED`, `Qualifier = RESUME_READY`

문서 전반에서 초기 Pattern A 트랙(Phase 1~11)이 사용해온 `DONE`은 이
문서 내에서 `CLOSED`와 동일한 의미(Phase lifecycle 완료)로 취급한다 —
과거 커밋 이력과의 연속성을 위해 기존 `DONE` 표기는 그대로 유지하되,
Phase 13 이후 신규 섹션은 `CLOSED`를 우선 사용한다. `IN PROGRESS`는
`IN_PROGRESS`와 동일하게 취급한다. Phase 13의 `RESEARCH_CLOSED`는
`Lifecycle = CLOSED`의 Phase-13 전용 합성 표기다 — "연구(13A~13J-4)만
CLOSED고 Production 승격 여부는 별도"임을 한 토큰으로 강조하기 위해
`CLOSED` 대신 유지하며, `Production = PRODUCTION_HOLD`와 항상 함께
쓴다.

## Current Status

**Pattern A Core Engine**: **`DONE / FROZEN`**

| 단계 | 상태 | 상세/커밋 |
|---|---|---|
| Feature Validation | DONE | 17개 기본 Feature 검증 완료 |
| Historical Snapshot Validation | DONE | Lookahead 없는 과거 시점 재현 |
| Holdout Validation | DONE | OOS Case 29건 고정 |
| Negative Control | DONE | False turn & Non-pattern 종목 검증 |
| Outcome Audit | DONE | 사후 성과 독립 감사 |
| Base / Expansion Validation | DONE | 베이스 및 확장 구조 검증 |
| Feature Set Freeze v0.1 | DONE | Feature 계약 확정 |
| Score Design v0.1 (freeze `6e7cc95`) | DONE | 1세대 스코어 설계 |
| Score Design v0.2 (implementation freeze `fffce85`) | DONE | Core/Support 조화평균, 페널티 구조 |
| Pattern A v0.2 OOS2 Validation | DONE | 38건 OOS2 검증 완료 |
| Pattern A Stage Truth Set Freeze (46건) | DONE | Manual Stage 라벨링 확정 |
| Pattern A Stage Classifier v0.1 (`43ee01c`) | DONE | Rule-based Lifecycle 분류기 (Calibration 38/5/3, OOS 24/10/1) |
| Pattern A Evaluator Integration v0.1 (`51fc202`) | DONE | Single-stock 종단간 통합 API 및 Candidate State |
| Data Quality & Universe Preparation v0.1 (`0ce8012`) | DONE | Fail-Closed 종목명 조회, 36m 계약, 품질 감사 |
| Pattern A Score Momentum v0.1 (`707c594`) | DONE | Calendar 1M/3M/6M Raw & Component Delta 측정 계층 |
| Official Common Stock Cache Population | DONE | Full Population & Audit `8983e65`, final docs `7ff45fe` |
| Full Universe Scanner Integration | DONE | Official COMMON 2,528개 스캔 및 매트릭스 통합 완료 (`13ab6f4`) |
| Real Candidate Chart Review (Phase 9A/9B) | DONE | Phase 9A (Dataset Prep) & Phase 9B (Human42 Review) 완료 |
| Stage v0.2 Candidate Research | HOLD | PRESEAL 미달 및 026910 미해결로 프로덕션 미채택 (`d975f66`) |
| Stage v0.3 Existing Feature Research | CLOSED | 가설 A~G 벤치마크 훼손 확인 (`NO_GENERALIZABLE_RULE_FOUND`, `6f3c061`) |
| Stage v0.4 Multi-Year Feature Research | CLOSED | 5년 구조 피처 9종 분리 한계 확인 (`NO_USEFUL_MULTI_YEAR_FEATURE_FOUND`, `5be5b42`) |
| Pattern A Final Production Closure | DONE | Final Closure PASS, KEEP_CURRENT_PRODUCTION 확정 (`05d03e1`) |
| Pattern A Stage Research Lifecycle | CLOSED | 알고리즘 연구 종료 (`KEEP_CURRENT_PRODUCTION`) |
| Phase 10 Investability & Tradability Filter | CLOSED | 시총 >= 1,000억, 20D 유동성 >= 3억 downstream filter 통합 (Investable 103개, `75afa32`) |
| Phase 11 Flow Confirmation Infrastructure | CLOSED | Foreign Flow 독립 confirmation axis 및 10대 hard gates 통과 (FLOW_INFRA_READY, `71237c0`) |

**Pattern A Fast**: **`RESEARCH_CLOSED / PRODUCTION_HOLD`** — Experimental / Early Signal 사용 가능(공식 Candidate·Ranking 미편입). 상세: [pattern_a_fast_phase_13_final_synthesis_v01.md](validation/pattern_a_fast_phase_13_final_synthesis_v01.md)  
**Pattern B~F**: 미착수(PLANNED)  
**전체 시장 Scanner**: 완료(DONE - Phase 8 Integration 및 Phase 9B Review 완료)  
**현재 작업 순서**: `README/Roadmap Sync = DONE (5e7c748)` → `Stock Report Pattern A Monthly + Pattern A FAST Weekly = CLOSED (4a20358)` → `Phase 12 Relative Strength Infrastructure = NEXT / RESUME_READY` → `Phase 14 Pattern B = PLANNED`  
**Market Leader Score**: 미착수(PLANNED - Phase 19)  

---

## Phase 1. Pattern A Score v0.2 — DONE (`fffce85`)

목표: Pattern A Score의 구조적 문제를 해결하고 최종 v0.2 Score를 freeze한다.

핵심 작업:
* Core / Supporting interaction 재설계 (ma24_slope 중심 조화평균 결합)
* weekly_ma12_slope와 ma24_slope_acceleration의 보조 확인 구조화
* alignment bonus 및 Already Progressed penalty 적용
* 0~100 유계 클리핑 및 해석 가능한 세부 점수 분해

---

## Phase 2. Pattern A v0.2 OOS2 Validation — DONE

v0.2를 완전히 freeze한 뒤, 독립적인 새로운 종목/날짜 38건(OOS2)에 적용해 검증했다.

핵심 결과:
* Frozen Pattern A Score v0.2 적용 및 OOS2 전 과정에서 Score 무수정 원칙 준수
* Weak Core + Strong Support 억제 개선 확인
* Hard Negative False Turn 4건 개별 component 분해 완료
* v0.3 improvement evidence 기록

---

## Phase 3. Pattern A Stage Classifier v0.1 — DONE (`43ee01c`)

Score와 완전히 독립적인 주가 사이클 상의 lifecycle 위치 분류기.

목표 Stage:
* `WEAK`: 장기 하락 또는 베이스 미형성 국면
* `BASE`: 장기 횡보 및 지지선 구축 국면
* `TRANSITION`: 단기/중기 이평선 정렬 및 턴어라운드 시도 국면
* `EARLY_TREND`: 장기 베이스 돌파 및 초기 추세 확장 국면
* `PROGRESSED`: 장기 추세 과열 및 이격 과다 국면

핵심 결과:
* Manual Stage Truth Set 46건(Exact 38, Adj 5, Sev 3 / 82.6%) 및 OOS 35건(Exact 24, Adj 10, Sev 1 / 68.6%) 검증 통과
* Stage는 Score를 참조하지 않고 오직 주가/이평선 구조적 위치만 평가하는 완전 독립 계층

---

## Phase 4. Pattern A Evaluator Integration v0.1 — DONE (`51fc202`)

종목코드, 종목명, 일봉 데이터, 기준일(`as_of`)을 입력받아 Pattern A 분석 결과를 일관되게 반환하는 Public API.

핵심 구조:
* Public API: `evaluate_pattern_a(ticker, name, daily, as_of)`
* 통합 결과: `PatternAEvaluationResult` (Score, Stage, Candidate State, Feature Snapshot, Flags 등)
* 해석 상태(Candidate State): `CANDIDATE`, `WATCH`, `LATE`, `BLOCKED`, `INSUFFICIENT_DATA`

---

## Phase 5. Data Quality & Universe Preparation v0.1 — DONE (`0ce8012`)

전체 시장 스캐너 실행 전 데이터 무결성을 보장하기 위한 감사 계층.

핵심 결과:
* Name Lookup Fail-Closed 정책 (조회 실패 시 ticker fallback 대신 `MarketDataError` 발생)
* 36 Completed Monthly Bars 계약 일치 (`_drop_incomplete_current_month` 적용)
* UNSORTED_DATE 감지 시 `raw_data_ready = False` 처리
* QualityAuditor를 통한 캐시 무결성 검증

---

## Phase 6. Pattern A Score Momentum v0.1 — DONE (`707c594`)

Frozen Pattern A Score v0.2를 완료된 월봉(Completed Monthly) 시간축으로 반복 평가하여 Score 변화량을 산출하는 순수 측정 계층(Pure Measurement Layer).

핵심 설계:
* Public API: `compute_pattern_a_score_momentum(ticker, name, daily, as_of)`
* Exact Calendar Horizons: 정확한 1M($T-1$), 3M($T-3$), 6M($T-6$) Calendar Month 말일 시점 비교 (No Silent Backfill)
* Raw Score Delta & Component Delta 분해 (진단용 분해 관측값 제공)
* 히스토리 요구조건 및 Partial Readiness: Current(36m), 1M(37m), 3M(39m), 6M(42m)
* Error Provenance 분리: `INSUFFICIENT_HISTORY_*`, `MISSING_MONTHLY_OBSERVATION_*`, `OBSERVATION_ERROR_*`

---

## Phase 7. Official Common Stock Cache Population — DONE

KOSPI / KOSDAQ 보통주 2,528개 대상 원자적 캐시(Atomic Write) 구축 및 데이터 무결성 검증 완료.

핵심 증거:
* Full Population & Final Audit: `8983e65`
* Final Documentation & Provenance Cleanup: `7ff45fe`

핵심 성과:
* Official COMMON Coverage 98.34% (2,486 / 2,528) 달성
* 구조적 오염 0건 (Future/Duplicate/Unsorted/Schema Violations 0, Temp Residue 0)
* Contract Critical Readiness 87.09% ~ 89.34% 확보 (6M Momentum 2,165개 계산 가능)

---

## Phase 8. Full Universe Scanner Integration — DONE (`13ab6f4`)

Official KRX KOSPI / KOSDAQ `AssetType.COMMON` universe를 대상으로 Pattern A Score, Official Stage, Candidate State, Score Momentum, Readiness 및 Quality Flags를 종목별 단일 row로 통합.

핵심 성과 및 계약:
* **평가 대상 (Evaluation Scope)**: Official KRX KOSPI / KOSDAQ 보통주 (`AssetType.COMMON`) 2,528개 전수 스캔 완료 (Row Emitted 2,528개 100% 일치)
* **제외 자산 (Excluded Assets)**: PREFERRED, SPAC, REIT, ETF, ETN, UNKNOWN, KONEX 엄격 배제
* **Fail-Closed 보존**: Cache Missing 42개 + Score/Stage Unavailable 265개 + Stage-only Unavailable 9개 = 총 UNAVAILABLE 316개 row 유지 및 `INSUFFICIENT_DATA` 처리
* **예외 격리**: Scanner Calculation Errors 0건 달성
* **매트릭스 아티팩트 생성**: `artifacts/scanner/pattern_a_universe_scan_20260814.csv` 및 `summary.json`

---

## Phase 9. Real Candidate Chart Review & Structural Audit — DONE

Scanner CANDIDATE 종목을 사람이 직접 검토(월봉 ➔ 주봉 ➔ 일봉)하여 실제 품질과 구조적 한계를 확인하고, Stage 연구 사이클을 거쳐 최종 Production을 동결한 검증 단계.

구성 및 핵심 성과:
* **Phase 9A. Candidate Review Dataset Preparation — DONE**:
  * 180개 공인 CANDIDATE 종목 (TRANSITION 168개, EARLY_TREND 12개) 추출 및 무결성 검증 완료
  * Review Dataset 아티팩트(`pattern_a_candidate_source_20260814.csv`, `pattern_a_candidate_manual_review_20260814.csv`, `summary.json`) 생성 및 Overwrite Protection / Source Lock 적용
* **Phase 9B. Human Chart Review & Evidence — DONE**:
  * **Human42 Evidence**: EARLY_TREND 12건 전수 + Exploratory TRANSITION 30건 표본에 대한 상세 수동 차트 검토 수행
  * EARLY_TREND 적합률 83.3% (Good Fit 7, Borderline 3, Not Fit 2)
  * Human42가 직접 확인한 구조적 Failure Pattern: Premature(바닥권 극초기 반등), Recycled(과거 시세 분출 후 조정), Too Early / Too Late 등
  * 최종 8대 Known Limitation은 Human42 + 후속 Stage v0.2 / v0.3 / v0.4 연구를 종합하여 확정
* **후속 Stage 연구 및 Final Production Closure — DONE**:
  * Stage v0.2 Candidate (`d975f66`): PRESEAL 미달로 프로덕션 기각 (`HOLD`)
  * Stage v0.3 Existing Feature Research (`6f3c061`): 일반화 규칙 부재 확인 (`CLOSED`)
  * Stage v0.4 Multi-Year Feature Research (`5be5b42`): 5년 구조 피처 한계 확인 (`CLOSED`)
  * Pattern A Final Production Closure (`05d03e1`): **`KEEP_CURRENT_PRODUCTION`** 공식 확정 및 Stage Research 종료

---

## Phase 10. Investability & Tradability Filter — DONE / CLOSED (`75afa32`)

목적: Pattern A Candidate 중 실제로 사람이 검토하거나 실전 투자 대상으로 고려할 가치가 낮은 비투자성 / 극저유동성 종목을 사전에 분리한다.

핵심 성과 및 계약:
* **독립 필터링 계층**: 시가총액(Market Cap >= 1,000억원) 및 20D 평균 거래대금(TV20 >= 3억원) 기준의 downstream filter 통합.
* **100% Frozen Pattern A 보존**: 180개 Raw Candidate (TRANSITION 168, EARLY_TREND 12) 전수 보존.
* **Investability 분류 결과**: Investable 103개, Filtered Market Cap 42개, Filtered Liquidity 31개, Data Unavailable 4개.

---

## Phase 11. Flow Confirmation Infrastructure — DONE / CLOSED (`71237c0`)

목적: 외국인 수급 데이터를 Pattern A 및 Investability와 독립된 confirmation axis로 구축.

현재 feature(외국인 수급 한정 — 기관 순매수는 코드/데이터 파이프라인에
존재하지 않으며 아직 구현되지 않았다):
* Foreign Net Buy: `1D` / `5D` / `20D` / `60D` (signed KRW)
* `5D` / `20D` / `60D` normalized Flow Intensity(거래대금 대비 강도)
* Positive flow day 수 및 비율

현재 정책:
* Pattern A Score에 합산하지 않는다.
* Production Ranking에 사용하지 않는다.
* Hard Filter에 사용하지 않는다.
* Candidate 판단에 사용하지 않는다.
* 현재는 정보성 / confirmation feature다.

핵심 성과 및 계약:
* **독립 Confirmation Axis**: Foreign Investor Flow를 하드 필터나 스코어 합산이 아닌 독립 확인 피처 계층으로 구축 완료. (Foreign Flow threshold, ranking, BUY/SELL, Candidate filtering 미도입)
* **데이터 무결성 & Fail-Closed**: exact `as_of` freshness, strict PIT 계약, source identity 검증, stale / missing / future data fail-closed.
* **Canonical 보존**: Official COMMON 2,528개, Raw Candidate 180개, Investable 103개 (Flow READY 103개, 100.0%) 전수 보존.
* **최종 Checkpoint**: `71237c0ec185b5cdc677c149b2d3e941f41d1b52` (Status: `FLOW_INFRA_READY`, 10대 Dynamic Hard Gates 전수 통과).

향후 확장 가능성(roadmap 수준 아이디어일 뿐, 이번 작업 범위 아님): 기관
순매수, OBV 등 거래량 기반 flow 보조 지표 추가.

---

## Phase 12. Relative Strength Infrastructure — PLANNED / RESUME_READY

목적: KOSPI, KOSDAQ 지수 및 업종 대비 상대강도(RS) 산출 인프라 구축.

과거 KRX IP block으로 Operational HOLD 상태였으나 현재 block 문제가 해소되어
재개 가능하다. 단 즉시 착수하는 다음 작업은 아니다 — README/Roadmap Sync와
Stock Report Pattern A + Pattern A Fast 병렬 표시를 먼저 완료한 뒤 착수한다.
Phase 13 Pattern A Fast가 먼저 수행된 것은 실행 순서 변경일 뿐 Phase 12와의
production dependency 변경은 아니다(두 트랙은 서로 독립적으로 수행 가능).

핵심 방향:
* KOSPI / KOSDAQ / 섹터 대비 RS (3M, 6M, 12M Horizon)
* Pattern A Score에 단순 합산하지 않고 독립적인 시장 선도력 확인 축으로 검증.

---

## Phase 13. Pattern A Fast — RESEARCH_CLOSED / PRODUCTION_HOLD

설명: Monthly Regime + Weekly Trigger + Daily Timing

목적: 기존 Pattern A(월봉/주봉 기반, 대세 상승 초입을 보수적으로 탐지)의
v2/개선판/후속 버전이 아니라, 시간축과 투자 스타일이 다른 **독립 파생
전략**이다. 별도 Stage / Score / Candidate / Validation을 가지며 연구
과정에서 기존 Pattern A Score/Stage semantics를 수정하지 않았다.

핵심 연구 질문:
* Pattern A가 결국 탐지할 유효한 상승 구조를, Pattern A Fast가 몇 주
  또는 몇 달 더 빠르게 탐지할 수 있는가?
* 그 빠른 탐지의 대가로 False Trigger가 얼마나 증가하는가?

시간축 철학 (Monthly Regime → Weekly Trigger → Daily Timing):
* **Monthly**: 장기 시장 위치와 큰 흐름을 확인하는 환경 필터(permission). 실제
  Trigger를 월봉이 결정하지 않는다.
* **Weekly**: Pattern A Fast의 핵심 판단 시간축(trigger). Setup / Trigger / Trend
  progression을 주봉에서 판단한다.
* **Daily**: 진입 타이밍 보조(timing). 장기 구조나 Pattern 자체를 일봉이
  결정하지 않는다.

목표: Pattern A보다 빠른 상승 전환 탐지 / Pattern A 대비 선행 기간 측정 /
False Trigger 측정 / 주봉 중심 전환 구조 정의 / 일봉 timing layer 정의

비목표: Pattern A 대체 / Pattern A Score·Stage 수정 / 단기 매매 수익률
최대화 / 무조건적인 매수 신호 생성 / Backtest 수익률에 맞춘 과최적화

Sub-stage (전체 CLOSED):
* 13A. Pattern A Fast Definition — CLOSED (`docs/specs/pattern_a_fast_definition.md`)
* 13B. Stage / Lifecycle Contract — CLOSED (`docs/specs/pattern_a_fast_lifecycle_contract.md`)
* 13C. Human Ground Truth Dataset(13C-1 준비 / 13C-2 40-sample Calibration) — CLOSED / FROZEN
* 13D. Monthly Regime Feature Research — CLOSED (HIGH 후보 7개)
* 13E. Weekly Trigger Feature Research — CLOSED (HIGH 후보 7개)
* 13F. Daily Timing Feature Research — CLOSED (HIGH 후보 7개)
* 13G-1. Feature Selection / Role Assignment — CLOSED (Monthly/Weekly/Daily HIGH 21개 역할 정리)
* 13G. Score & Stage Production Contract(`HIERARCHICAL_V01`) — CLOSED
* 13H. Pattern A vs Pattern A Fast Lead Time / Failure Analysis — CLOSED (event pairing semantics 동결)
* 13I. Reserved OOS-A Evaluation — CLOSED (Human POSITIVE_STRUCTURE=0으로 primary score test `INCONCLUSIVE`)
* 13J-1~4. Investable OOS-B Freeze / Blind Human Review(PASS A/B) / Evaluation / Closure — CLOSED

최종 결과 (Investable OOS-B, frozen n=36 sample):
* Primary Score Separation: `PASS` — POSITIVE_STRUCTURE(GOOD_TRIGGER+BORDERLINE_TRIGGER)
  score median=73.82 vs EARLY_OR_NONE(TOO_EARLY+NO_SETUP) score median=51.935,
  difference=+21.885
* Pattern A 대비 Clean Lead Time: `INCONCLUSIVE` — n=2(median 8.5주, range 1~16주),
  프로토콜 최소 기준 n>=3 미달
* Hard Failure: 0건
* 최종 결정: **`HIERARCHICAL_V01_PRODUCTION_HOLD`** — Production 승격, threshold
  retuning, label 재수정 없음. FAST는 폐기된 모델이 아니라 `Experimental /
  Early Signal`로 사용 가능한 상태.

Frozen contract:
* Fast contract: `HIERARCHICAL_V01` / `2da3fc36744b27ec13edae3f690df72c796906e5`
* Frozen Pattern A(비교 기준): `05d03e16501adbca889488294aaaaa0bd84005de`
* Phase 13 최종 closure commit: `935f9be7c0e790b7b4efedc04ea4149a90ad78a8`

상세 결과 및 향후 작업 제약: [pattern_a_fast_phase_13_final_synthesis_v01.md](validation/pattern_a_fast_phase_13_final_synthesis_v01.md)
— 향후 작업은 새로 독립적으로 frozen한 검증 population 또는 prospective
monitoring을 사용해야 하며, 이미 닫힌 Phase 13 evidence set은 재수정하지
않는다.

### Pattern A FAST 사용 정책

| | Pattern A | Pattern A Fast |
|---|---|---|
| 상태 | Official Production Signal | Experimental / Early Signal |
| Candidate 판단 | 사용 | 미사용 |
| 공식 Production Ranking | 사용 | 미사용 |
| Stage / Score | 공식 제공, Frozen | 독립 제공(Pattern A Stage/Score를 대체하지 않음) |

Pattern A와 Pattern A Fast는 서로 독립 모델이다 — Pattern A Fast는 Pattern A의
하위 stage나 확장판이 아니며, Pattern A Fast Score/Stage는 Pattern A
Score/Stage와 독립적으로 산출된다. Stock Report 등에서는 두 신호를 병렬
표시할 수 있다:

* `Pattern A: Not Active` + `Pattern A FAST: SETUP / Score 81`
  → Pattern A confirmation 이전에 초기 구조를 FAST가 탐지.
* `Pattern A: TRANSITION / Score 72` + `Pattern A FAST: TREND / Score 78`
  → 공식 Pattern A는 전환 단계이며 FAST는 초기 추세 구조가 더 진행된 것으로 판단.

FAST를 "더 정확한 모델", "상위 모델", "차세대 production 모델"처럼 표현하지
않는다 — 현재 evidence가 이를 뒷받침하지 않는다. 향후 prospective / shadow
monitoring을 통해 실전 lead evidence를 추가 축적한다.

Phase 12 Relative Strength Infrastructure와 Phase 13 Pattern A Fast는 독립 연구
트랙이며 상호 production dependency가 없다 — Phase 13이 먼저 완료된 것은
실행 순서 변경일 뿐 dependency 변경은 아니다.

---

## Phase 14 ~ 18. Pattern B ~ F — PLANNED

* **Phase 14. Pattern B**: 장기 하락 추세 종료 및 Stage 2 전환형
* **Phase 15. Pattern C**: 신고가 직전 고점 압축형
* **Phase 16. Pattern D**: 상대강도 선행형
* **Phase 17. Pattern E**: 장기 변동성 수축형 (VCP)
* **Phase 18. Pattern F**: 실적 턴어라운드 + 차트 선행형

---

## Phase 19. Pattern Score Matrix & Market Leader Score — PLANNED

독립적인 Pattern A, Pattern A Fast, Pattern B~F 점수와 Investability 결과, RS, 수급(Flow), 모멘텀, 실적 증거를 종합한 시장 주도주 종합 점수 체계 구축.

---

## Phase 20. Walk Forward / Paper Validation — PLANNED

과거 시점 시뮬레이션 및 실시간 전진 추적 검증.

---

## Phase 21. Production Scanner & Operational Dashboard — PLANNED

CLI / Web 대시보드, 관심종목 워크플로우, 실시간 알림 등 최종 운영 시스템 구축.

---

## Near Term Milestones

1. Pattern A Score Design v0.2 — DONE
2. Pattern A v0.2 OOS2 Validation — DONE
3. Pattern A Stage Classifier v0.1 — DONE (`43ee01c`)
4. Pattern A Evaluator Integration v0.1 — DONE (`51fc202`)
5. Data Quality / Universe Preparation v0.1 — DONE (`0ce8012`)
6. Pattern A Score Momentum v0.1 — DONE (`707c594`)
7. Official Common Stock Cache Population — DONE (`8983e65`, `7ff45fe`)
8. Full Universe Scanner Integration — DONE (`13ab6f4`)
9. Real Candidate Chart Review (Phase 9A Dataset Prep & 9B Human42 Review) — DONE
10. Pattern A Final Production Closure (`05d03e1`) — DONE
11. Phase 10 Investability & Tradability Filter — DONE
12. Phase 11 Flow Confirmation Infrastructure (`71237c0`) — DONE
13. Phase 13 Pattern A Fast Research (`935f9be`) — DONE (`RESEARCH_CLOSED / PRODUCTION_HOLD`)
14. README / Roadmap Sync (`5e7c748`) — DONE
15. Stock Report Pattern A Monthly + Pattern A FAST Weekly 병렬 표시 (`4a20358`) — CLOSED
16. Phase 12 Relative Strength Infrastructure — NEXT / RESUME_READY
17. Phase 14 Pattern B — PLANNED

---

## Development Principles

* **Principle 1**: Pattern별 Feature를 먼저 독립 검증한다.
* **Principle 2**: 한 Pattern에서 실패한 Feature를 다른 Pattern에서도 자동 폐기하지 않는다.
* **Principle 3**: 미래 수익률을 이용해 threshold를 최적화하지 않는다.
* **Principle 4**: OOS 데이터를 본 순간 그 데이터는 다음 버전의 development data가 된다.
* **Principle 5**: Score, Stage, Score Momentum을 독립된 축으로 분리한다.
* **Principle 6**: 가능하면 Hard Filter보다 해석 가능한 soft scoring을 우선한다.
* **Principle 7**: 전체 Score가 높은 이유를 사람이 설명할 수 있어야 한다.
* **Principle 8**: 월봉 / 주봉이 장기 추세 판단의 기본이고 일봉은 단기 추세와 진입 timing 확인에 사용한다.
* **Principle 9**: 실제 전체 시장 Scanner를 돌린 뒤 나오는 예상하지 못한 false positive를 중요한 검증 데이터로 취급한다.
* **Principle 10**: Pattern A, Pattern A Fast, Pattern B~F가 충분히 검증되기 전에는 Market Leader Score를 성급하게 만들지 않는다.
* **Principle 11**: Pattern detection과 Investability filtering은 철저히 분리한다 (시총, 주가, 거래대금은 Pattern A Score/Stage에 섞지 않음).
* **Principle 12**: Flow 및 Relative Strength는 독립 Confirmation Axis로 시작하며 초기에는 절대적 Hard Filter로 사용하지 않는다.
* **Principle 13**: Pattern A는 Final Closure 이후 기본적으로 Frozen Algorithm으로 취급한다. 개별 ticker 오분류나 임의 threshold 조정 아이디어만으로는 재오픈하지 않으며, 오직 (1) 충분한 신규 independent validation cohort 확보, (2) 실전 운용에서 반복적인 systematic production failure 확인, (3) 시장 구조 변화로 frozen production semantic의 유효성이 명백히 훼손된 경우에만 제한적으로 재오픈을 검토한다.
