ROADMAP.md

# KRX Trend Scanner Development Roadmap

이 문서는 향후 작업 순서의 기준 문서다. 새로운 아이디어가 생겨도 바로
구현하지 않고, 어느 Phase에 속하는지 먼저 이 문서에서 위치를 정한다.

## Current Status Summary (기준: 2026-09-04)

**COMPLETED**
- Repository V2 / production data migration (local rolling market-data authority, KRX Open API 기반)
- Market data refresh through 2026-09-04 (production certified boundary = 2026-09-04)
- Market-price validation
- Pattern A production regeneration (COMMON production universe 2,555 / scan rows 2,555 / scanner_error_count 0)
- Stock Report regeneration (54/54, report errors 0)
- Branch / main integration cleanup (Group B 정리 및 merged branch 정리 포함)

**CURRENT**
- Documentation / artifact consolidation (이 문서 및 `README.md`, `docs/**`, `artifacts/**` 정리)

**NEXT**
- FastCore realistic backtest (next-day execution, transaction cost, slippage, holding period, win rate, payoff ratio, MDD, trade count, market regime, benchmark comparison, parameter robustness 반영)
- Julia realistic backtest (동일 기준)
- Strategy robustness comparison — 목표는 "최대 backtest 수익률 parameter"가 아니라 **현실적 실행조건에서도 반복 가능한 robust strategy**를 찾는 것

**HOLD**
- New Pattern development (Pattern B~F 등)
- Deferred Group B work (`codex/deferred-group-b-v01` 브랜치에 보존된 consumer-migration / authority-adjudication 관련 미완료 작업)
- 추가적인 market-data hardening (새로운 concrete discrepancy가 없는 한 재검증하지 않음)
- OpenDART Fundamentals 신규 착수 (기존 설계/구현 문서는 `docs/fundamentals/`에 보존되어 있으나, 현재 최우선순위는 FastCore/Julia backtest)

**알려진 현재 한계 (2026-09-04 production scan 기준, 과장하지 않고 그대로 기록)**
- Foreign Flow: 대부분 `NOT_EVALUATED` — Phase 11 인프라 자체는 존재하나 매 스캔마다 전수 평가되지 않음
- Market RS: candidate 단위 production 통합이 아직 완전히 적용되지 않은 부분이 있음
- Repository 전체에 legacy/historical PyKRX 관련 코드가 남아 있음 — 다만 production scanner/report 경로의 silent PyKRX fallback은 제거된 상태

---

## 핵심 목표

이 프로젝트의 최종 목표는 단순히 **"이미 상승 중인 강한 종목"**을
찾는 것이 아니다.

최종 목표는:

> 대세 상승이 만들어지기 시작하는 종목을 여러 독립적인 패턴과
> 시장 신호를 이용해 조기에 탐지하고, 체계적인 매매 전략 및 리포트로 의사결정을 지원하는 것

기본 철학:

```text
가격 구조 -> 장기 추세 -> 투자 적합성 필터 -> 수급 확인 -> 상대강도 -> 전략 실행
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
Phase만): `PRODUCTION` / `PRODUCTION_HOLD` / `EXPERIMENTAL` / `PRODUCTION_DECISION_SUPPORT`

예:

* Pattern A: `Lifecycle = CLOSED`, `Production = PRODUCTION`, `Qualifier = FROZEN`
* Pattern A FAST: `Lifecycle = CLOSED`, `Production = PRODUCTION_HOLD`, `Usage = EXPERIMENTAL`
* A FAST Core V2: `Lifecycle = CLOSED`, `Production = PRODUCTION_DECISION_SUPPORT`, `Qualifier = FROZEN`
* Phase 12 Market RS: `Lifecycle = CLOSED`, Sector RS: `DEFERRED / FUTURE_EXTENSION`

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

| 구분 | 단계 / 마일스톤 | 상태 | 상세 / 기준 커밋 |
|---|---|---|---|
| **Pattern A Core Engine** | Feature & Snapshot Validation | DONE | 17개 피처 및 Time-Travel Free 검증 완료 |
| | Score Design v0.2 | DONE | Core/Support 조화평균 결합 (`fffce85`) |
| | Stage Classifier v0.1 | DONE | 5단계 Rule-based Lifecycle 분류기 (`43ee01c`) |
| | Single Evaluator Integration v0.1 | DONE | Evaluator API 및 Candidate State (`51fc202`) |
| | Data Quality & Universe Preparation | DONE | Fail-Closed 종목명 조회, 36m 계약 (`0ce8012`) |
| | Pattern A Score Momentum v0.1 | DONE | Calendar 1M/3M/6M Delta 측정 계층 (`707c594`) |
| | Official Common Stock Cache Population | DONE | 2,528개 보통주 캐시 구축 (Coverage 98.34%, `8983e65`) |
| | Full Universe Scanner Integration | DONE | 2,528개 전종목 스캔 및 매트릭스 통합 (`13ab6f4`) |
| | Real Candidate Review & Human42 | DONE | 180개 Candidate 추출 및 Human42 차트 리뷰 완료 |
| | Stage Research (v0.2/v0.3/v0.4) | CLOSED | v0.2 HOLD(`d975f66`), v0.3 CLOSED(`6f3c061`), v0.4 CLOSED(`5be5b42`) |
| | **Pattern A Final Production Closure** | **DONE / FROZEN** | **KEEP_CURRENT_PRODUCTION 확정 (`05d03e1`)** |
| **Filters & Confirmation** | Phase 10 Investability Filter | CLOSED | 시총 $\ge \text{1,000억}$, 20D 유동성 $\ge \text{3억}$ (`75afa32`) |
| | Phase 11 Foreign Flow Infrastructure | CLOSED | Foreign Flow 독립 confirmation axis (`71237c0`) |
| | **Phase 12 Market Relative Strength** | **CLOSED** | 3M/6M/12M, delta, acceleration, all-market rank/percentile 및 Stock Report v0.3 통합 완료 (`5fdf977`) |
| **Pattern A FAST** | Phase 13 Signal Model Research | **RESEARCH_CLOSED / PRODUCTION_HOLD** | Score Separation `PASS`, Lead Time `INCONCLUSIVE` (`935f9be`) |
| **A FAST Core Strategy** | A FAST Core Strategy V1 | CLOSED / FROZEN | 단일 진입 모델 (**`HISTORICAL_FROZEN_BASELINE`**) |
| | **A FAST Core Strategy V2** | **CLOSED / FROZEN** | **Current Default Strategy (`PRODUCTION_DECISION_SUPPORT`)** |
| **Reporting & Viewer** | **Stock Report v0.3** | **CLOSED** | Phase 12 Market RS production integration 완료 (`0e54ad5`) |
| | Web Report Viewer | PLANNED / FUTURE | Fundamentals 및 핵심 데이터 계층 이후 |
| **Engineering Infrastructure** | Documentation IA Reorganization | CLOSED | Domain-first / Pattern-second 구조 확립 (`docs/README.md`) |
| | Artifacts IA Reorganization | CLOSED | Authority & Lifecycle 분리 완료 (`a81e3bb`) |
| | Test Suite Performance Audit | CLOSED | 실행 시간 단축 (~66분 ➔ ~11분44초) |
| **Project Management** | README & Roadmap Refresh | **CLOSED** | Refresh 및 Semantics 정합성 완료 |
| | **Production Regeneration through 2026-09-04** | **CLOSED** | Repository V2 / rolling market-data authority, universe 2,555, Pattern A + Stock Report 재생성, branch/main integration cleanup 완료 |
| | **Documentation / Artifact Consolidation** | **CURRENT** | README/ROADMAP/docs/artifacts 정리 (이 작업) |
| | **FastCore Realistic Backtest** | **NEXT** | 실행조건 반영 현실적 백테스트 (next-day execution, cost, slippage 등) |
| | **Julia Realistic Backtest** | **NEXT** | 동일 기준의 Julia 전략 백테스트 |
| | OpenDART Fundamentals | HOLD | 설계/구현 문서는 `docs/fundamentals/`에 보존, 신규 착수는 FastCore/Julia 이후 |
| | KRX Open API Validation | COMPLETE | 서비스 API 승인 완료, 현재 production data path (Repository V2) |
| | **Julia Strategy V00 Official PIT** | **INCOMPLETE / BLOCKED_BY_KRX_DATA** | 117/215 확보, 98개 기준일 누락 |
| | **Market Cap Threshold Research** | **AFTER_OFFICIAL_JULIA_PIT** | Official PIT 100% 이후 strategy path 재생성 연구 |
| **Longer-term** | Phase 14~18. Pattern B ~ F | PLANNED | 장기 파이프라인 |
| | Phase 19. Market Leader Score | PLANNED | 종합 스코어링 체계 |
| | Phase 20~21. Operational Dashboard | PLANNED | 최종 운영 시스템 |

---

## 공식 작업 우선순위 (Current Work Order)

```text
1. Documentation / Artifact Consolidation = CURRENT
       ↓
2. FastCore Realistic Backtest = NEXT
       ↓
3. Julia Realistic Backtest = NEXT
       ↓
4. Strategy Robustness Comparison = NEXT
       ↓
5. OpenDART Fundamentals = HOLD (신규 착수는 위 3개 이후)
       ↓
6. Julia Official PIT 100% = BLOCKED_BY_KRX_DATA
       ↓
7. Market Cap Threshold Research = AFTER_OFFICIAL_JULIA_PIT
       ↓
8. Sector RS = DEFERRED / FUTURE_EXTENSION
       ↓
9. Web Report Viewer = FUTURE
       ↓
10. Phase 14~18 Pattern B ~ F & Longer-term = LONGER-TERM
```

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

핵심 성과:
* Official COMMON Coverage 98.34% (2,486 / 2,528) 달성 (`8983e65`, `7ff45fe`)
* 구조적 오염 0건 (Future/Duplicate/Unsorted/Schema Violations 0, Temp Residue 0)
* Contract Critical Readiness 87.09% ~ 89.34% 확보 (6M Momentum 2,165개 계산 가능)

---

## Phase 8. Full Universe Scanner Integration — DONE (`13ab6f4`)

Official KRX KOSPI / KOSDAQ `AssetType.COMMON` universe를 대상으로 Pattern A Score, Official Stage, Candidate State, Score Momentum, Readiness 및 Quality Flags를 종목별 단일 row로 통합.

핵심 성과 및 계약:
* **평가 대상**: Official KRX 보통주 2,528개 전수 스캔 완료 (Row Emitted 2,528개 100% 일치)
* **제외 자산**: PREFERRED, SPAC, REIT, ETF, ETN, UNKNOWN, KONEX 엄격 배제
* **Fail-Closed 보존**: UNAVAILABLE 316개 row 유지 및 `INSUFFICIENT_DATA` 처리
* **산출물**: `artifacts/patterns/pattern_a/production/scanner/pattern_a_universe_scan_20260814.csv`

---

## Phase 9. Real Candidate Chart Review & Structural Audit — DONE

Scanner CANDIDATE 180종목을 수동 차트 검토하고 Stage 연구 사이클을 거쳐 최종 Production을 동결한 검증 단계.

구성 및 핵심 성과:
* **Phase 9A. Candidate Review Dataset Preparation — DONE**: 180개 공인 CANDIDATE 추출 및 무결성 검증 완료.
* **Phase 9B. Human Chart Review & Evidence — DONE**: EARLY_TREND 12건 전수 + TRANSITION 30건 표본 검토 (EARLY_TREND 적합률 83.3%).
* **후속 Stage 연구 및 Final Production Closure — DONE**:
  * Stage v0.2 Candidate (`d975f66`): PRESEAL 미달로 프로덕션 기각 (`HOLD`)
  * Stage v0.3 Existing Feature Research (`6f3c061`): 일반화 규칙 부재 확인 (`CLOSED`)
  * Stage v0.4 Multi-Year Feature Research (`5be5b42`): 5년 구조 피처 한계 확인 (`CLOSED`)
  * Pattern A Final Production Closure (`05d03e1`): **`KEEP_CURRENT_PRODUCTION`** 공식 확정 및 Stage Research 종료

---

## Phase 10. Investability & Tradability Filter — DONE / CLOSED (`75afa32`)

목적: Pattern A Candidate 중 비투자성 / 극저유동성 종목을 사전에 분리하는 독립 downstream filter.

핵심 성과 및 계약:
* **독립 필터링 계층**: 시가총액($\ge \text{1,000억원}$) 및 20일 평균 거래대금($\ge \text{3억원}$) 기준의 downstream filter 통합.
* **100% Frozen Pattern A 보존**: 180개 Raw Candidate (TRANSITION 168, EARLY_TREND 12) 전수 보존.
* **Investability 분류 결과**: Investable 103개, Filtered Market Cap 42개, Filtered Liquidity 31개, Data Unavailable 4개.
* **산출물**: `artifacts/patterns/pattern_a/production/investability/`

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

## Phase 12. Market Relative Strength — CLOSED

목적: KOSPI와 KOSDAQ 전체 공식 COMMON universe를 기준으로 종목별 시장 상대강도(Market RS)를 산출하고, 이를 Stock Report v0.3에서 소비하는 분석 축으로 통합.

### 최종 상태
* **Lifecycle**: **`CLOSED`**
* **Closure SHA**: `5fdf97793c1fd7683c33d5fe77ff4da97fc75a19`
* **범위**: KOSPI COMMON은 KOSPI, KOSDAQ COMMON은 KOSDAQ을 benchmark로 사용.
* **기간**: `3M` / `6M` / `12M`
* **계산 값**: Market RS level, `market_rs_delta_3m_vs_6m`, `market_rs_delta_6m_vs_12m`, `market_rs_acceleration_3_6_12m`, 전체 시장 rank/percentile.
* **Cross-sectional authority**: 후보 subset이 아닌 전체 공식 KOSPI/KOSDAQ COMMON universe를 기준으로 rank/percentile을 lookup.
* **제외 자산**: Preferred, SPAC, REIT, ETF, ETN, KONEX, UNKNOWN.
* **Fail-closed 원칙**: exact as-of snapshot만 사용하고 nearest/future fallback을 사용하지 않음.

### Stock Report 통합
* Stock Report v0.3이 Phase 12 snapshot을 consumer로 사용하며, report 생성마다 Full Universe Scanner를 호출하거나 RS를 재계산하지 않음.
* Market RS level은 Markdown에서 `%`, improvement delta와 acceleration은 `%p`, JSON 원본 값은 decimal로 보존.
* Phase 12 자체는 Pattern A Score나 Investability 필터에 합산되지 않는 독립 Context / Analysis feature.
* **Stock Report v0.3 closure**: `0e54ad5e93e0817d690b944c5356b49f85dac639`

### Sector RS 상태
* **`DEFERRED / FUTURE_EXTENSION`**
* 공인 업종 매핑과 PIT-compatible 업종 benchmark가 확정되기 전까지 Sector RS는 구현 완료로 간주하지 않음.

---

## Phase 13 (Historical Research Track). Pattern A Fast — RESEARCH_CLOSED / PRODUCTION_HOLD

설명: Monthly Regime $\rightarrow$ Weekly Trigger $\rightarrow$ Daily Timing

목적: 기존 Pattern A(월봉/주봉 기반, 대세 상승 초입을 보수적으로 탐지)의
v2/개선판/후속 버전이 아니라, 시간축과 투자 스타일이 다른 **독립 파생
신호 모델**이다. 별도 Stage / Score / Candidate / Validation을 가지며 연구
과정에서 기존 Pattern A Score/Stage semantics를 수정하지 않았다.

핵심 연구 결과 (Investable OOS-B, frozen n=36 sample):
* Primary Score Separation: `PASS` (diff +21.885, $p < 0.01$)
* Pattern A 대비 Clean Lead Time: `INCONCLUSIVE` (n=2, median 8.5주, range 1~16주, 최소 기준 n $\ge$ 3 미달)
* Hard Failure: 0건
* 종합 결정: **`HIERARCHICAL_V01_PRODUCTION_HOLD / EXPERIMENTAL`** ([Phase 13 Synthesis](docs/patterns/pattern_a_fast/validation/phase_13_final_synthesis_v01.md))
* 사용 정책: 단독 Candidate 판단이나 Production Ranking에 사용하지 않으며, Stock Report 등에서 Pattern A의 조기 보조 신호로 병렬 표시.

---

## Post-Phase 13. A FAST Core Strategy Finalization — CLOSED

Pattern A, Pattern A FAST, Investability 필터, 손절 및 청산 규칙을 결합한 실전 매매 정책 계층입니다.

### 전략 버전 체계
* **A FAST Core V2 (`PATTERN_A_FAST_FINAL_STRATEGY_V02`) — Current Default Strategy**:
  * **진입 (Entry)**: Pattern A가 TRANSITION 또는 EARLY_TREND이고, FAST가 TRIGGER/READY이며, Investability·Monthly Regime(PERMITTED_REGIME)·Daily Risk(NORMAL/ELEVATED)·FAST Score Status 조건이 모두 허용될 때 다음 로컬 거래일 시가 진입.
  * **손절 (Loss Guard)**: Pre-PROGRESSED 구간에서 entry_open 대비 일봉 종가 -15% 이하 도달 시 다음 로컬 거래일 시가 청산 (최초 PROGRESSED effective date 도달 이후 비활성화).
  * **청산 (Exit3 / Exit4)**: PROGRESSED에서 WEAK/BASE/TRANSITION/EARLY_TREND 등 다른 유효 Pattern A Stage로 이탈 시 Exit3 청산, PROGRESSED 이후 Score HWM 대비 현재 Score가 15pt 이상 하락 시 Exit4 청산 (특수 Coverage lifecycle에서는 Exit3 비활성 및 Exit4만 적용).
  * **재진입 (Reentry)**: 포지션 청산(FLAT) 후 새로운 진입 조건 충족 시 동일 종목 독립 재진입 허용 (V1 대비 유일한 전략 변경점, No Cooldown / No Max Reentries, 피라미딩 및 중복 포지션 금지).
  * **공식 상태**: **`FINAL_STRATEGY_FROZEN / PRODUCTION_DECISION_SUPPORT`** ([V2 Contract](docs/patterns/pattern_a_fast/strategy/final_v02.md), [Strategy Versions](docs/patterns/pattern_a_fast/strategy/versions.md))
  * **회고적 검증 증거**: 783 trades / 551 tickers (Same Sample Retrospective, Fresh OOS 미실행).
  * **기준 커밋**: Architecture (`89df82a`), Calendar (`88d54d8`), Evidence (`36273d9`), Trade Gen (`b9ba613`)
* **A FAST Core V1 (`PATTERN_A_FAST_FINAL_STRATEGY_V01`) — Historical Baseline**:
  * 재진입이 금지된 단일 진입 기준 모델 (**`HISTORICAL_FROZEN_BASELINE`**, [V1 Contract](docs/patterns/pattern_a_fast/strategy/final_v01.md)).
* **운용 정책**: 본 전략은 리포트를 통한 **투자 의사결정 지원(Decision Support)** 목적으로 사용되며, 자동 주문 실행(Automated Trading)용으로 승인되지 않았습니다.

## OpenDART Fundamentals — HOLD (설계/구현 문서 보존, 신규 착수는 FastCore/Julia 이후)

Pattern A, Investability, Foreign Flow, Market RS와 독립된 실적 분석 축을 추가하는 다음 개발 단계.

### 초기 목표
* OpenDART corp code mapping
* 연결재무제표 우선 조회
* 매출, 영업이익, 당기순이익
* 자산, 부채, 자본
* 수익성, YoY growth, earnings trend
* 공시일 기준 Point-in-Time(PIT) 처리

### PIT 원칙
Historical as-of report에서는 `disclosure / filing availability date <= as_of`인 실제 공시 데이터만 사용한다. 미래 공시 데이터가 과거 리포트에 유입되는 future filing leakage를 금지한다.

### 아직 확정하지 않는 항목
Fundamentals Score, Pattern A Score와의 합산, 매매 signal, PER/PBR, valuation score 및 fundamental cutoff는 OpenDART Fundamentals 설계 단계에서 확정한다. 현재는 `NEXT / PLANNED`이며 OpenDART가 production 통합 완료된 상태가 아니다.

---

## Stock Report v0.3 Integration — CLOSED

단일 종목의 Pattern A, Investability, Foreign Flow, Market RS, 전략 상태 및 데이터 품질을 종합 진단하는 JSON/Markdown 리포트 엔진.

* **공식 상태**: **`v0.3 CLOSED / PRODUCTION_DECISION_SUPPORT`** ([Stock Report v0.3 Contract](docs/reporting/stock_report/contract_v03.md))
* **Stock Report v0.2**: `artifacts/reporting/stock_reports/archive/v0.2/`에 historical archive로 보존.
* **Stock Report v0.3**: `artifacts/reporting/stock_reports/<YYYYMMDD>/`에 current production contract으로 제공.
* **리포트 구성 (9대 축)**:
  1. Pattern A 진단 (Score v0.2, Stage Classifier, Candidate State, Score Momentum)
  2. Phase 10 Investability 판정 (시총 $\ge \text{1,000억}$, 20D 거래대금 $\ge \text{3억}$)
  3. A FAST Core V2 Canonical Strategy Position 및 Action
  4. Pattern A FAST Early Signal Stage & Fast Score
  5. Pattern A 월별 히스토리 추이 (Monthly History / Score Trend / Stage Transitions)
  6. Phase 11 Foreign Flow 수급 지표 및 Flow Intensity
  7. Phase 12 Market RS (3M/6M/12M, delta, acceleration, rank/percentile)
  8. 거래대금 추이 (Trading Value Trend, 5D/20D/60D 평균 및 단·중기 상태)
  9. 데이터 품질 및 PIT 무결성 감사 (Zero Network Requests)
* **생성 원칙**: Local Parquet Cache와 canonical artifact만 사용하며 exact as-of lookup, Full Universe Scanner 미호출, 네트워크 요청 0건.
* **Authority chain**: Initial v0.3 `6695f994`, FIX01 `2c96d69e`, FIX01 evidence `813309e`, final closure `0e54ad5`.
* **Final Full Suite evidence**: `1078 passed`, `0 failed`, `0 errors`, `6 skipped`, `5 deselected`, `1267.16 sec`, exit code `0`.

---

## Cross-Cutting Engineering Infrastructure Milestones — CLOSED

1. **Documentation IA Reorganization — CLOSED**:
   - Domain-first / Pattern-second 정보 구조 확립 (`docs/README.md`, `docs/patterns/`, `docs/reporting/`, `docs/strategies/`).
2. **Artifacts IA Reorganization — CLOSED** (`a81e3bba5fdf9c49931b0531b6d74d5a8543b173`):
   - Authority & Lifecycle 기반 단일 기준(Canonical) 아티팩트 트리 확립 (`artifacts/README.md`, `production/`, `validation/`, `research/`, `archive/`, `reporting/`, `shared/`).
   - 910개 아티팩트 파일 전수 무결성 검증 완료 ($913 - 4 + 1 = 910$).
3. **Test Suite Performance Audit — CLOSED**:
   - 전체 테스트 스위트 병목 구간 최적화 완료 (~66분 ➔ ~11분44초).

---

## Julia Strategy V00 — INCOMPLETE / BLOCKED_BY_KRX_DATA

목적: A FAST Core V2의 핵심 보호 규칙인 pre-PROGRESSED $-15\%$ Loss Guard가 회고적 수익률 분포와 대규모 손실 프로필에 미치는 영향을 독립적으로 비교 검증.

현재 Official PIT는 `117 / 215 = 54.42%`이며 98개 reference date가 누락되어 있다. 따라서 현재 결과는 `INCOMPLETE`이고, KRX historical market-cap data availability 확인 전까지 `BLOCKED_BY_KRX_DATA`다.

### 검증 규격 (Strict No Tuning Contract)
* **Base Strategy**: A FAST Core V2
* **ONLY DELTA**:
  $$\text{Pre-PROGRESSED Loss Guard: } \mathbf{ON (-15\%)} \longrightarrow \mathbf{OFF}$$
* **동일 유지**: Entry, Exit3, Exit4, Coverage, PIT, Calendar, Execution, Reentry, Sample Scope.
* **절대 금지**: 임계치 튜닝, 진입/청산 규칙 수정, 스코어 튜닝, 샘플 임의 선정.
* **증거 분류**: `EXPLORATORY / SAME_SAMPLE_RETROSPECTIVE` (Production 미승인).
* **Proxy research**: `CLOSED / NON_AUTHORITATIVE_PROXY_PIT` (공식 production 근거로 사용하지 않음).
* **Official production approval**: `NOT_APPROVED`.
* **다음 Julia 작업**: KRX historical market-cap data가 확보된 뒤 98개 누락 기준일을 official PIT로 채우고, 100% completeness를 확인한 후에만 이 비교 연구를 실행한다.

## KRX Open API Validation — COMPLETE (2026-09-04 기준 업데이트)

> **현재 상태 업데이트**: 서비스 API 승인이 완료되어 KRX Open API 기반 데이터 계층(Repository V2 / local rolling market-data authority)이 현재 production data path다. 아래는 승인 전 작성된 원본 검증 계획으로, 역사적 기록을 위해 그대로 남긴다.

KRX Open API 기반 데이터 계층 전환은 서비스 API 승인 대기 상태였다. 승인 후 다음 순서로 검증했다.

1. HTTP 200 및 인증 성공 확인
2. Response schema freeze
3. Stock daily data field parity
4. Index daily data parity
5. Historical market-cap availability
6. Corporate-action adjusted-price semantics 검증
7. `KRX_ONLY` vs `KRX_PLUS_KIS` architecture 결정

현재는 migration 완료나 production 전환으로 표시하지 않는다. OpenDART Fundamentals의 작은 작업 단위가 진행 중 승인되면, 해당 단위를 마친 뒤 KRX validation을 우선 재개할 수 있다.

## Market Cap Threshold Research — AFTER_OFFICIAL_JULIA_PIT

Julia Official PIT가 100% 완료된 뒤 A FAST Core V2와 Julia를 대상으로 각 threshold에서 strategy path를 다시 생성하는 연구.

예정 threshold: `100B KRW`(1000억원), `300B KRW`(3000억원), `500B KRW`(5000억원), `1T KRW`(1조원).

기존 1000억원 결과에 사후 필터만 적용하지 않고, 각 threshold에서 진입·보유·청산 경로를 재생성한다.

---

## Web Report Viewer — PLANNED / FUTURE

목적: Stock Report v0.3 산출물을 웹 브라우저에서 편리하게 조회/검색할 수 있는 뷰어 인터페이스 구축.

* **실행 의존성**: OpenDART Fundamentals $\rightarrow$ 핵심 데이터 계층 정리 $\rightarrow$ Web Report Viewer.
* **현재 상태**: 즉시 구현 대상이 아니며, OpenDART Fundamentals 및 핵심 데이터 계층 이후의 미래 단계.
* **설계 방향**: 실시간 대규모 연산 대신 사전에 생성된 정적/공식 아티팩트(Static/Canonical JSON)를 우선 소비하는 구조로 설계.

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

1. Pattern A Score Design v0.2 — DONE (`fffce85`)
2. Pattern A Stage Classifier v0.1 — DONE (`43ee01c`)
3. Pattern A Evaluator Integration v0.1 — DONE (`51fc202`)
4. Official Common Stock Cache Population — DONE (`8983e65`, `7ff45fe`)
5. Full Universe Scanner Integration — DONE (`13ab6f4`)
6. Pattern A Final Production Closure — DONE (`05d03e1`)
7. Phase 10 Investability & Tradability Filter — DONE (`75afa32`)
8. Phase 11 Flow Confirmation Infrastructure — DONE (`71237c0`)
9. Phase 13 Pattern A Fast Research — DONE (`RESEARCH_CLOSED / PRODUCTION_HOLD`, `935f9be`)
10. Post-Phase 13 A FAST Core Strategy V1/V2 Finalization — CLOSED
11. Phase 12 Market Relative Strength — CLOSED (`5fdf977`)
12. Stock Report v0.3 Integration — CLOSED (`0e54ad5`)
13. Documentation & Artifacts IA Reorganization — CLOSED (`a81e3bb`)
14. Production Regeneration through 2026-09-04 (Repository V2, universe 2,555) — **CLOSED**
15. Documentation / Artifact Consolidation — **CURRENT**
16. FastCore Realistic Backtest — **NEXT**
17. Julia Realistic Backtest — **NEXT**
18. OpenDART Fundamentals — **HOLD**
19. KRX Open API Validation — **COMPLETE**
20. Julia Strategy V00 Official PIT — **INCOMPLETE / BLOCKED_BY_KRX_DATA**
21. Market Cap Threshold Research — **AFTER_OFFICIAL_JULIA_PIT**
22. Sector RS — **DEFERRED / FUTURE_EXTENSION**
23. Web Report Viewer — **PLANNED / FUTURE**

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
