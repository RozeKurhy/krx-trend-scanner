README.md

# krx-trend-scanner

코스피와 코스닥 상장 보통주(`AssetType.COMMON`)를 대상으로 **대세 상승 초입 가능성이 있는 종목을 구조적으로 탐색하고, 투자 가능성·수급·시장 상대강도·전략 상태를 함께 평가하는 의사결정 지원 시스템**입니다.

단순히 이미 상승 중인 종목을 찾는 것이 아니라, 월봉과 주봉을 중심으로 장기 가격 구조와 추세 변화를 분석해 **상승 추세가 막 만들어지기 시작하는 후보**를 선별하고 체계적인 매매 전략 및 리포트를 제공하는 것을 목표로 합니다.

---

## 🌟 핵심 철학 및 개념 구조

```text
[가격 구조] ➔ [장기 추세] ➔ [투자 적합성 필터] ➔ [수급 확인] ➔ [상대강도] ➔ [전략 실행]
```

### Pattern vs Strategy 구분
* **Pattern (신호 모델)**: 시장의 가격 구조와 추세 상태를 독립적으로 탐지하는 관측 모델.
  * **Pattern A**: 장기 베이스 수렴 및 초기 추세 전환형 (**공식 Production 신호**, `FROZEN`)
  * **Pattern A FAST**: 주봉 중심의 조기 전환 탐지형 (**실험적 조기 신호**, `PRODUCTION_HOLD`)
* **Strategy (매매 정책)**: Pattern, Investability 필터, 손절 및 청산 규칙을 결합하여 진입/보유/청산/재진입을 규정하는 실행 정책.
  * **A FAST Core V2**: 현재 공식 기본 전략 (**`PRODUCTION_DECISION_SUPPORT`**)
  * **A FAST Core V1**: 과거 비교 기준선 (**`HISTORICAL_FROZEN_BASELINE`**)

---

## 📐 패턴 탐지 계층

### 1. Pattern A: 장기 베이스 수렴 및 초기 추세 전환형 (Frozen Production)
* **Score v0.2**: 24개월 이평선 기울기(`ma24_slope`) 중심의 조화평균(Harmonic Mean) 결합, Alignment Bonus 및 이격 과열에 대한 Progressed Penalty 적용 (0~100점).
* **Stage Classifier v0.1**: 주가 사이클 위치를 나타내는 5단계 라이프사이클 (`WEAK` ➔ `BASE` ➔ `TRANSITION` ➔ `EARLY_TREND` ➔ `PROGRESSED`).
* **Candidate State**: `CANDIDATE` (2026-09-04 기준 raw candidate 256개), `WATCH`, `LATE`, `BLOCKED`, `INSUFFICIENT_DATA`.
* **Score Momentum v0.1**: 정확한 Calendar 1M, 3M, 6M 시점 간의 Raw & Component Delta 측정.
* **공식 상태**: **`CLOSED / PRODUCTION / FROZEN`** (`KEEP_CURRENT_PRODUCTION`, [Final Closure: `05d03e1`](docs/patterns/pattern_a/validation/final_production_closure.md))

### 2. Pattern A FAST: 주봉 중심 조기 전환 탐지형 (Experimental / Early Signal)
* **시간축 구조**: `Monthly grants permission` ➔ `Weekly pulls trigger` ➔ `Daily times entry`.
* **Lifecycle**: `WATCH` ➔ `SETUP` ➔ `TRIGGER` ➔ `TREND` ➔ `EXTENDED`.
* **검증 결과 (Investable OOS-B)**: Score Separation `PASS` (diff +21.885), Lead Time `INCONCLUSIVE` (n=2).
* **공식 상태**: **`RESEARCH_CLOSED / PRODUCTION_HOLD / EXPERIMENTAL`** ([Phase 13 Synthesis](docs/patterns/pattern_a_fast/validation/phase_13_final_synthesis_v01.md))
* **사용 정책**: 공식 Candidate 판단이나 단독 랭킹에 사용하지 않으며, Stock Report 등에서 Pattern A의 보조 조기 신호로 병렬 표시됩니다.

---

## 🚦 필터 및 확인 지표

### 1. Phase 10 Investability & Tradability Filter (Closed)
* **목적**: 비투자성·극저유동성 종목을 사전에 분리하는 독립 downstream filter.
* **기준**: 시가총액 $\ge \text{1,000억원}$ & 20일 평균 거래대금 $\ge \text{3억원}$ (별도 종가 하드 필터 미도입).
* **분류**: `INVESTABLE`, `FILTERED_MARKET_CAP`, `FILTERED_LIQUIDITY`, `DATA_UNAVAILABLE` (2026-09-04 기준 `INVESTABLE` 133개 — 세부 분포는 production summary 산출물 참고).

### 2. Phase 11 Foreign Flow Confirmation Infrastructure (Closed)
* **목적**: 외국인 수급 데이터를 독립된 확인 축(Confirmation Axis)으로 제공.
* **지표**: Foreign Net Buy (1D, 5D, 20D, 60D) 및 거래대금 대비 Flow Intensity (5D, 20D, 60D).
* **정책**: 하드 필터나 스코어 합산에 사용하지 않는 순수 정보성 지표 (기관 수급 및 OBV는 현재 미구현).

### 3. Phase 12 Market Relative Strength (Closed)
* **공식 상태**: **`CLOSED`**
* **정의**: 종목 수익률을 해당 종목의 상장 시장 벤치마크와 비교하는 상대강도입니다. KOSPI 종목은 KOSPI, KOSDAQ 종목은 KOSDAQ을 비교 기준으로 사용하며 RSI와는 다른 개념입니다.
* **기간**: `3M` / `6M` / `12M`
* **제공 값**: Market RS level, 기간별 improvement delta, acceleration, 전체 COMMON 시장 기준 rank/percentile.
* **범위**: KOSPI/KOSDAQ 전체 공식 COMMON universe를 권위 데이터로 사용하며, ETF·ETN·우선주·SPAC·REIT·KONEX 등은 제외합니다. Percentile은 `100 = strongest`, `0 = weakest`입니다.
* **운영 원칙**: 후보 subset 재계산 없이 전체 시장 snapshot을 exact as-of로 lookup합니다. nearest/future fallback, 리포트별 Full Universe Scan, 네트워크 요청은 사용하지 않습니다.
* **분석 위치**: RS는 현재 Pattern A Score나 필터에 합산되지 않는 독립 Context / Analysis feature입니다.
* **Sector RS**: **`DEFERRED / FUTURE_EXTENSION`** (Market RS와 별도 범위).

### 4. KRX Open API Validation (Complete)
* **현재 상태**: **`COMPLETE`**
* 서비스 API 승인이 완료되어 KRX Open API 기반 데이터 계층(Repository V2 / local rolling market-data authority)이 현재 production data path입니다.

### 5. OpenDART Fundamentals (Hold)
* **다음 개발 영역**: OpenDART 기반 매출, 영업이익, 당기순이익, 수익성, 성장률, 실적 추세 및 공시일 기준 PIT 처리.
* **현재 상태**: **`HOLD`**. 설계/구현 문서는 [`docs/fundamentals/`](docs/fundamentals/README.md)에 보존되어 있으나, 현재 최우선순위는 FastCore/Julia realistic backtest입니다. Fundamentals Score, Pattern A Score와의 합산, valuation score 및 매매 signal은 아직 확정하지 않았습니다.

---

## 🎯 A FAST Core Strategy (의사결정 지원 전략)

Pattern A의 장기 베이스와 Pattern A FAST의 주봉 타이밍, Investability 필터, 손절 및 청산 규칙을 결합한 통합 매매 전략입니다.

* **A FAST Core V2 (`PATTERN_A_FAST_FINAL_STRATEGY_V02`) — Current Default**:
  * **진입 (Entry)**: Pattern A가 TRANSITION 또는 EARLY_TREND이고, FAST가 TRIGGER/READY이며, Investability·Monthly Regime·Daily Risk·FAST Score Status 조건이 모두 허용될 때 다음 로컬 거래일 시가 진입.
  * **손절 (Loss Guard)**: Pre-PROGRESSED 구간에서 entry_open 대비 일봉 종가 -15% 이하 도달 시 다음 로컬 거래일 시가 청산 (최초 PROGRESSED effective date 도달 이후 비활성화).
  * **청산 (Exit3 / Exit4)**: PROGRESSED에서 다른 유효 Pattern A Stage(WEAK/BASE/TRANSITION/EARLY_TREND)로 이탈 시 Exit3 청산, PROGRESSED 이후 Score HWM 대비 현재 Score가 15pt 이상 하락 시 Exit4 청산 (특수 Coverage lifecycle에서는 Exit3 비활성 및 Exit4만 적용).
  * **재진입 (Reentry)**: 포지션 청산(FLAT) 후 새로운 진입 조건 충족 시 동일 종목 독립 재진입 허용 (V1 대비 유일한 전략 변경점, No Cooldown / No Max Reentries, 피라미딩 및 중복 포지션 금지).
  * **공식 상태**: **`FINAL_STRATEGY_FROZEN / PRODUCTION_DECISION_SUPPORT`** ([V2 Contract](docs/patterns/pattern_a_fast/strategy/final_v02.md))
* **A FAST Core V1 (`PATTERN_A_FAST_FINAL_STRATEGY_V01`) — Historical Baseline**:
  * 재진입이 금지된 단일 진입 모델로, 영구 보존되는 과거 기준선 (**`HISTORICAL_FROZEN_BASELINE`**).
* **운용 정책**: 본 전략은 **투자 의사결정 지원(Decision Support)** 목적으로 리포트에 제공되며, 자동 주문 실행(Automated Trading)용으로 승인된 상태가 아닙니다. 회고적 검증(Retrospective, 783 trades / 551 tickers) 기반이며 Fresh OOS 검증은 아직 수행되지 않았습니다.

---

## 📄 종목 분석 리포트 (Stock Report v0.3)

단일 종목의 장기 패턴, 투자 적합성, 전략 상태, 수급, 시장 상대강도 및 히스토리 추이를 종합 진단하는 Markdown 및 JSON 리포트 생성기입니다.

* **공식 상태**: **`v0.3 CLOSED / PRODUCTION_DECISION_SUPPORT`** ([v0.3 Contract](docs/reporting/stock_report/contract_v03.md))
* **핵심 항목 (9대 축)**:
  1. **Pattern A 진단**: Score v0.2, Stage Classifier, Candidate State, 1M/3M/6M Score Momentum
  2. **Investability 평가**: 시가총액($\ge \text{1,000억}$), 20D 거래대금($\ge \text{3억}$) 적합성 판정
  3. **A FAST Core V2 전략 상태**: Canonical Strategy Position (`OPEN` / `FLAT`) 및 Action (`ENTER_NEXT_OPEN`, `HOLD`, `EXIT_NEXT_OPEN`, `WAIT`)
  4. **Pattern A FAST 조기 신호**: Early Signal Stage & Fast Score
  5. **월별 히스토리 추이 (Monthly History)**: 과거 월별 Pattern A Score Trend, Stage Transitions, Recent 12M History
  6. **수급 현황 (Foreign Flow)**: 외국인 기간별(1D/5D/20D/60D) 순매수 및 Flow Intensity
  7. **시장 상대강도 (Market RS)**: 3M/6M/12M level, improvement delta, acceleration, 전체 시장 rank/percentile
  8. **거래대금 추이 (Trading Value Trend)**: 5D/20D/60D 평균 거래대금 및 단·중기 확장 상태/비율
  9. **데이터 품질 & Provenance**: 결측치 감사, exact as-of, Zero Network Requests, PIT 무결성 검증
* **산출물 경로**: `artifacts/reporting/stock_reports/<YYYYMMDD>/`
* **생성 원칙**: local cache와 canonical artifact를 소비하며, report 생성 시 외부 네트워크 요청과 Full Universe Scanner 호출은 0회입니다.

> **주의**: 리포트의 포지션 정보는 사용자의 실제 계좌 보유 내역이 아닌 **A FAST Core 전략의 공인 가상 포지션(Canonical Strategy Position)**입니다.

---

## 📂 프로젝트 구조

정보 구조(Docs IA & Artifacts IA) 원칙에 따라 체계적으로 분리되어 있습니다.

```text
krx-trend-scanner/
├── src/trend_scanner/              # 핵심 엔진 소스코드
│   ├── data/                       # Repository V2, rolling market-data authority, Parquet 캐시, PIT 스냅샷 검증
│   ├── features/                   # 이평선, 피벗, 변동성, 레인지 등 정량 피처
│   ├── patterns/                   # Pattern A 스코어링, 스테이지, 모멘텀, Evaluator
│   ├── filters/                    # Phase 10 Investability 필터
│   ├── flow/                       # Phase 11 Foreign Flow 수급 지표
│   ├── relative_strength/          # Phase 12 Market RS (CLOSED)
│   ├── reporting/                  # Stock Report v0.3 생성기
│   ├── scanner/                    # COMMON production universe(2026-09-04 기준 2,555개) Full Universe Scanner
│   ├── universe/                   # 유니버스 데이터 품질 감사
│   └── validation/                 # 각 단계별 검증 파이프라인 및 클로저 감사
│
├── ROADMAP.md                      # 전체 프로젝트 개발 로드맵 (COMPLETED/CURRENT/NEXT/HOLD)
├── docs/                           # 설계 및 검증 문서 (Single Source of Truth)
│   ├── README.md                   # Documentation Authority Index
│   ├── architecture/               # 시스템 아키텍처 및 공용 데이터 설계
│   ├── patterns/
│   │   ├── pattern_a/              # Pattern A 공식 규격 및 검증 보고서
│   │   └── pattern_a_fast/         # Pattern A FAST 연구 및 A FAST Core 전략 문서
│   ├── reporting/                  # Stock Report 계약 및 명세서
│   └── strategies/                 # 크로스 패턴 전략 아키텍처
│
├── artifacts/                      # 검증 및 운영 산출물 (Authority & Lifecycle 분리)
│   ├── README.md                   # Artifacts Authority Index
│   ├── patterns/
│   │   ├── pattern_a/              # Pattern A (production/, validation/, research/)
│   │   └── pattern_a_fast/         # Pattern A Fast (production/, validation/, research/, archive/)
│   ├── reporting/                  # 생성된 종목별 리포트 (stock_reports/)
│   └── shared/                     # 공용 캐시 품질 감사 데이터 (cache_population/)
│
└── tests/                          # 단위, 통합, 회귀 검증 테스트 스위트
```

---

## 🚀 빠른 시작

### 1. 환경 설정 및 설치

```bash
# uv 사용 시 (권장)
uv sync

# 또는 pip 사용 시
pip install -e ".[dev]"
```

### 2. 테스트 실행

```bash
# 빠른 검증 테스트 스위트
uv run pytest -m "not slow and not integration"
```

### 3. Stock Report 생성 예시

```python
from pathlib import Path
from trend_scanner.reporting.stock_report import generate_stock_report

repo_root = Path(".")
report, json_path, md_path = generate_stock_report(
    ticker="000660",
    as_of="2026-08-14",
    repo_root=repo_root,
)
print(f"Pattern A Score: {report.current_snapshot.pattern_a_score}")
print(f"Pattern A Stage: {report.current_snapshot.official_stage}")
print(f"A FAST Core V2 State: {report.a_fast_core.strategy_state}")
print(f"A FAST Core V2 Action: {report.a_fast_core.action}")
print(f"JSON: {json_path}")
print(f"Markdown: {md_path}")
```

---

## 🗺️ 현재 상태 및 다음 단계

**Production 기준일**: 2026-09-04 (`production certified boundary`)

* **COMPLETED**: Repository V2 / production data migration, market data refresh & price validation through 2026-09-04, Pattern A production regeneration (COMMON universe 2,555), Stock Report regeneration (54/54), branch/main integration cleanup
* **CURRENT**: Documentation / artifact consolidation (이 문서 포함)
* **NEXT**: FastCore realistic backtest → Julia realistic backtest → strategy robustness comparison (현실적 실행조건에서 반복 가능한 robust strategy 탐색이 목표)
* **HOLD**: 신규 Pattern 개발, OpenDART Fundamentals 신규 착수, deferred Group B 작업, 불필요한 추가 market-data hardening

**알려진 현재 한계** (2026-09-04 production scan 기준): Foreign Flow는 대부분 `NOT_EVALUATED`이며, Market RS의 candidate 단위 production 통합은 아직 완전히 적용되지 않은 부분이 있습니다.

전체 Phase 이력과 세부 실행 계획은 [ROADMAP.md](ROADMAP.md)를 참고하세요.
