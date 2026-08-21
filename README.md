# krx-trend-scanner

코스피와 코스닥 상장 보통주(`AssetType.COMMON`)를 대상으로 **대세 상승 초입에 진입하는 종목을 정량적으로 탐색하기 위한 스크리너 및 의사결정 지원 시스템**입니다.

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
* **Candidate State**: `CANDIDATE` (180종목), `WATCH`, `LATE`, `BLOCKED`, `INSUFFICIENT_DATA`.
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
* **분류**: `INVESTABLE` (103개), `FILTERED_MARKET_CAP` (42개), `FILTERED_LIQUIDITY` (31개), `DATA_UNAVAILABLE` (4개).

### 2. Phase 11 Foreign Flow Confirmation Infrastructure (Closed)
* **목적**: 외국인 수급 데이터를 독립된 확인 축(Confirmation Axis)으로 제공.
* **지표**: Foreign Net Buy (1D, 5D, 20D, 60D) 및 거래대금 대비 Flow Intensity (5D, 20D, 60D).
* **정책**: 하드 필터나 스코어 합산에 사용하지 않는 순수 정보성 지표 (기관 수급 및 OBV는 현재 미구현).

### 3. Phase 12 Relative Strength Infrastructure (HOLD)
* **공식 상태**: **`HOLD_RELATIVE_STRENGTH_INFRA`**
* **현황**: KOSPI/KOSDAQ 시장 대비 RS 산출 인프라 및 Scanner 통합은 완료되었으나, 공인 종목-업종 매핑 및 Sector RS 산술 정합성 검증 부재로 HOLD 상태. Julia 전략 백테스트 완료 후 재개 예정.

---

## 🎯 A FAST Core Strategy (의사결정 지원 전략)

Pattern A의 장기 베이스와 Pattern A FAST의 주봉 타이밍, Investability 필터, 손절 및 청산 규칙을 결합한 통합 매매 전략입니다.

* **A FAST Core V2 (`PATTERN_A_FAST_FINAL_STRATEGY_V02`) — Current Default**:
  * **진입 (Entry)**: Investable + Pattern A FAST Setup/Trigger 조건 충족 시 익일 시가 진입.
  * **손절 (Loss Guard)**: PROGRESSED 도달 전 $\mathbf{-15\%}$ 손실 도달 시 즉시 익일 시가 손절.
  * **청산 (Exit3 / Exit4)**: PROGRESSED 도달 후 12주 이평선 이탈 또는 주봉 지지선 붕괴 시 청산.
  * **재진입 (Reentry)**: 포지션 청산(FLAT) 후 새로운 진입 조건 충족 시 독립 재진입 허용 (V1 대비 유일한 차이점).
  * **공식 상태**: **`FINAL_STRATEGY_FROZEN / PRODUCTION_DECISION_SUPPORT`** ([V2 Contract](docs/patterns/pattern_a_fast/strategy/final_v02.md))
* **A FAST Core V1 (`PATTERN_A_FAST_FINAL_STRATEGY_V01`) — Historical Baseline**:
  * 재진입이 금지된 단일 진입 모델로, 영구 보존되는 과거 기준선 (**`HISTORICAL_FROZEN_BASELINE`**).
* **운용 정책**: 본 전략은 **투자 의사결정 지원(Decision Support)** 목적으로 리포트에 제공되며, 자동 주문 실행(Automated Trading)용으로 승인된 상태가 아닙니다. 회고적 검증(Retrospective, 783 trades / 551 tickers) 기반이며 Fresh OOS 검증은 아직 수행되지 않았습니다.

---

## 📄 종목 분석 리포트 (Stock Report v0.2)

단일 종목의 장기 패턴, 투자 적합성, 전략 상태, 수급 현황을 종합 진단하는 Markdown 및 JSON 리포트 생성기입니다.

* **공식 상태**: **`CLOSED / PRODUCTION_DECISION_SUPPORT`** ([v0.2 Contract](docs/reporting/stock_report/contract_v02.md))
* **핵심 항목**:
  1. **Pattern A 진단**: Score v0.2, Stage Classifier, Candidate State, 1M/3M/6M Score Momentum
  2. **Investability 평가**: 시가총액, 20D 거래대금 적합성 판정
  3. **A FAST Core V2 전략 상태**: Canonical Strategy Position (`OPEN` / `FLAT`) 및 Action (`ENTER_NEXT_OPEN`, `HOLD`, `EXIT_NEXT_OPEN`, `WAIT`)
  4. **Pattern A FAST 조기 신호**: Early Signal Stage & Fast Score
  5. **수급 현황**: 외국인 기간별 순매수 및 Flow Intensity
  6. **데이터 품질**: 결측치 및 PIT 무결성 감사
* **산출물 경로**: `artifacts/reporting/stock_reports/<YYYYMMDD>/`

> **주의**: 리포트의 포지션 정보는 사용자의 실제 계좌 보유 내역이 아닌 **A FAST Core 전략의 공인 가상 포지션(Canonical Strategy Position)**입니다.

---

## 📂 프로젝트 구조

정보 구조(Docs IA & Artifacts IA) 원칙에 따라 체계적으로 분리되어 있습니다.

```text
krx-trend-scanner/
├── src/trend_scanner/              # 핵심 엔진 소스코드
│   ├── data/                       # 데이터 수집, Parquet 캐시, PIT 스냅샷 검증
│   ├── features/                   # 이평선, 피벗, 변동성, 레인지 등 정량 피처
│   ├── patterns/                   # Pattern A 스코어링, 스테이지, 모멘텀, Evaluator
│   ├── filters/                    # Phase 10 Investability 필터
│   ├── flow/                       # Phase 11 Foreign Flow 수급 지표
│   ├── relative_strength/          # Phase 12 상대강도 인프라 (HOLD)
│   ├── reporting/                  # Stock Report v0.2 생성기
│   ├── scanner/                    # 2,528개 전종목 Full Universe Scanner
│   ├── universe/                   # 유니버스 데이터 품질 감사
│   └── validation/                 # 각 단계별 검증 파이프라인 및 클로저 감사
│
├── docs/                           # 설계 및 검증 문서 (Single Source of Truth)
│   ├── README.md                   # Documentation Authority Index
│   ├── roadmap.md                  # 전체 프로젝트 개발 로드맵
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
report = generate_stock_report(
    ticker="000660",
    name="SK하이닉스",
    as_of="2026-08-14",
    repo_root=repo_root,
)
print(f"Pattern A Score: {report['pattern_a']['score']}")
print(f"A FAST Core V2 Action: {report['fast_core_v2']['action']}")
```

---

## 🗺️ 개발 로드맵 및 현재 작업 순서

```text
[README/Roadmap Refresh] (CURRENT / CLOSING)
       ↓
[Julia Strategy V00 Backtest] (NEXT / EXPLORATORY)
       ↓
[Phase 12 Relative Strength Resume] (THEN)
       ↓
[Phase 12 Final Closure] (THEN)
       ↓
[Web Report Viewer / Production Expansion] (THEN)
       ↓
[Pattern B ~ F 장기 파이프라인] (LONGER-TERM)
```

1. **Phase 1~9: Pattern A Core Engine** — **`CLOSED / FROZEN`** (`05d03e1`)
2. **Phase 10: Investability Filter** — **`CLOSED`** (시총 $\ge \text{1,000억}$, 20D 거래대금 $\ge \text{3억}$)
3. **Phase 11: Foreign Flow Infrastructure** — **`CLOSED`** (`71237c0`, 독립 확인 축)
4. **Phase 13: Pattern A FAST Research** — **`RESEARCH_CLOSED / PRODUCTION_HOLD`** (조기 신호)
5. **Post-Phase 13: A FAST Core Strategy V1/V2 Finalization** — **`CLOSED / DECISION_SUPPORT`**
6. **Stock Report v0.2 Integration** — **`CLOSED / DECISION_SUPPORT`**
7. **Engineering IA Reorganization (Docs & Artifacts)** — **`CLOSED`**
8. **README & Roadmap Refresh** — **`CURRENT TASK`**
9. **Julia Strategy V00 Backtest** — **`NEXT / EXPLORATORY_CANDIDATE`** (A FAST Core V2에서 Loss Guard OFF 비교 가설 검증)
10. **Phase 12: Relative Strength Infrastructure** — **`HOLD_RELATIVE_STRENGTH_INFRA`** (Julia 완료 후 재개)
11. **Web Report Viewer** — **`PLANNED`** (Phase 12 Closure 이후 착수)
12. **Phase 14~18: Pattern B ~ F** — **`PLANNED`**
13. **Phase 19~21: Market Leader Score & Operational Dashboard** — **`PLANNED`**

자세한 로드맵과 세부 실행 계획은 [docs/roadmap.md](docs/roadmap.md)를 참고하세요.

