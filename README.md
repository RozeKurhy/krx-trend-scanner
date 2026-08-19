# krx-trend-scanner

코스피와 코스닥 상장 보통주(AssetType.COMMON)를 대상으로 **대세 상승 초입에 진입하는 종목을 정량적으로 탐색하기 위한 스크리너 프로젝트**입니다.

단순히 이미 상승 중인 종목을 찾는 것이 아니라, 월봉과 주봉을 중심으로 장기 가격 구조와 추세 변화를 분석해 **상승 추세가 막 만들어지기 시작하는 후보**를 선별하는 것을 목표로 합니다.

---

## 🌟 주요 특징 및 핵심 철학

* **다차원 독립 측정 분리 (Orthogonal Architecture)**:
  * **Score v0.2 (Frozen Production)**: 장기 베이스 안정성과 전환 시그널의 조화평균 결합 (0~100점)
  * **Stage Classifier v0.1 (Frozen Production)**: `WEAK` ➔ `BASE` ➔ `TRANSITION` ➔ `EARLY_TREND` ➔ `PROGRESSED`
  * **Score Momentum v0.1**: 정확한 Calendar 1M, 3M, 6M 시점 간의 Raw Delta 및 Component Delta 측정
  * **Candidate State**: `CANDIDATE`, `WATCH`, `LATE`, `BLOCKED`, `INSUFFICIENT_DATA`
* **Lookahead 원천 차단 (Time-Travel Free)**:
  * 모든 스냅샷 및 피처는 `snapshot_date` 이전의 확정된 데이터만을 사용하여 과거 시점을 완벽하게 재현합니다.
* **Fail-Closed 데이터 품질 관리**:
  * 엄격한 OHLCV 검증, 36 Completed Months 계약, 불완전 월봉 오인 차단, 종목명 매핑 무결성 보장.
* **Investability Filtering 계층 분리**:
  * 시가총액, 주가 수준, 거래대금, 유동성 등 투자 적합성 필터는 Pattern A 알고리즘 자체에 섞지 않고 독립된 후속 필터링 계층으로 분리하여 운영합니다.

---

## 📐 패턴 기반 스크리닝 (Pattern A: Frozen Production)

### Pattern A: 장기 베이스 수렴 및 초기 추세 전환형

장기간 박스권 또는 횡보 구간을 형성하면서 저점이 점차 상승하고, 장기 이동평균선(MA24)이 평탄화/상승 전환하며 수렴하는 형태입니다.

* **Base Score**: 36개월 레인지(`range_36m`), 12개월 평균 주가 변화율(`avg_price_change_12m`), 이동평균 수렴도(`ma_spread`)
* **Transition Score**: 24개월 이평선 기울기(`ma24_slope`), 주봉 12주 이평선 기울기(`weekly_ma12_slope`), 24개월 이평선 가속도(`ma24_slope_acceleration`)
* **Core & Support 결합**: 핵심 지표(`ma24_slope`) 중심의 조화평균(Harmonic Mean) 결합으로 단기 왜곡 억제
* **Bonuses & Penalties**: Alignment Bonus 및 장기 이격 과열에 대한 Progressed Penalty 적용
* **공식 상태**: **`FROZEN`**, **`KEEP_CURRENT_PRODUCTION`** — Score v0.2와 Stage lifecycle은 동결 상태이며 현재 종목 탐색·리포트에서 공식 production 신호로 사용한다. Frozen semantics는 변경·재해석하지 않는다. (**`Score v0.2 KEEP`**, **`Stage v0.1 KEEP`**, **`Pattern A Stage Research CLOSED`**, [Final Closure Checkpoint: `05d03e1`](docs/validation/pattern_a_final_production_closure.md))

---

## 🧪 Pattern A FAST (Research Closed / Production Hold — Experimental)

### Pattern A FAST: Monthly Regime → Weekly Trigger → Daily Timing

Pattern A의 v2나 개선판이 아니라, 시간축과 투자 스타일이 다른 **독립 파생
전략**입니다. `Monthly grants permission` → `Weekly pulls trigger` →
`Daily times entry` 철학으로, Pattern A보다 상승 전환을 더 빠르게 포착하는
것을 목표로 연구했습니다.

* **Lifecycle**: `WATCH` ➔ `SETUP` ➔ `TRIGGER` ➔ `TREND` ➔ `EXTENDED`
* **독립성**: Pattern A Fast Score/Stage는 Pattern A Score/Stage와 완전히
  독립적으로 산출됩니다. Pattern A의 하위 stage나 확장판이 아닙니다.
* **공식 상태**: **`Phase 13 Research CLOSED`**, **`HIERARCHICAL_V01
  Production HOLD`** ([Final Synthesis](docs/validation/pattern_a_fast_phase_13_final_synthesis_v01.md))

검증 결과 요약 (Investable OOS-B, frozen n=36):
* Primary Score Separation(`GOOD_TRIGGER+BORDERLINE_TRIGGER` median 73.82 vs
  `TOO_EARLY+NO_SETUP` median 51.935, diff +21.885): **`PASS`**
* Pattern A 대비 Clean Lead Time(n=2, median 8.5주, 프로토콜 최소 n>=3):
  **`INCONCLUSIVE`**
* Hard Failure 0건 → 종합 결정: **`PRODUCTION HOLD`**(Production 승격 아직
  없음, 폐기도 아님)

사용 정책: Pattern A FAST는 현재 **`Experimental / Early Signal`**입니다.
공식 Candidate 판단이나 Production Ranking에는 사용하지 않으며, Pattern A
Score/Stage를 대체하지 않습니다. Stock Report 등에서 Pattern A와 병렬 보조
신호로 표시될 수 있습니다(예: `Pattern A: Not Active` + `Pattern A FAST:
SETUP / Score 81`). FAST를 "더 정확한 모델"이나 "차세대 production
모델"로 서술하지 않습니다 — 현재 evidence가 이를 뒷받침하지 않습니다.

---

## 📂 프로젝트 구조

```text
krx-trend-scanner/
├── src/
│   └── trend_scanner/
│       ├── data/                   # 데이터 수집, 검증, 캐싱 및 리샘플링
│       │   ├── provider.py         # MarketDataProvider Protocol
│       │   ├── pykrx_provider.py   # PyKRX 구현체
│       │   ├── repository.py       # 증분 캐시 리포지토리
│       │   ├── cache.py            # Parquet 로컬 캐시
│       │   ├── validator.py        # OHLCV 데이터 검증
│       │   ├── resampler.py        # 주봉/월봉 리샘플링
│       │   └── errors.py           # MarketDataError
│       │
│       ├── features/               # 정량적 기술적 피처 계산
│       │   ├── moving_average.py   # 이평선 및 기울기, 가속도, 수렴도
│       │   ├── pivot.py            # 피벗 저점 탐지
│       │   ├── volatility.py       # ATR, HL Range
│       │   └── resistance.py       # 레인지 및 저항선 거리
│       │
│       ├── patterns/               # 패턴 평가, 스코어링, 스테이지, 모멘텀
│       │   ├── pattern_a_score.py          # Frozen Score v0.2
│       │   ├── pattern_a_stage.py          # Frozen Stage Classifier v0.1
│       │   ├── pattern_a_evaluator.py      # 종단간 단일 종목 Evaluator v0.1
│       │   └── pattern_a_score_momentum.py # Calendar Score Momentum v0.1
│       │
│       ├── scanner/                # 전체 유니버스 스캔 및 다차원 통합
│       │   └── full_universe_scanner.py # Pattern A Full Universe Scanner v0.1
│       │
│       ├── review/                 # 후보 종목 추출 및 수동 차트 검토 데이터셋
│       │   └── candidate_review.py # Candidate Review Dataset & Workflow
│       │
│       ├── universe/               # 유니버스 준비도 및 데이터 품질 감사
│       │   └── quality_auditor.py  # Universe Data Quality Auditor
│       │
│       └── validation/             # 스냅샷 생성, 피처 리포트 및 최종 클로저
│           ├── historical_snapshot.py
│           ├── feature_report.py
│           ├── stage_v03_research.py
│           ├── stage_v04_multi_year_research.py
│           └── pattern_a_final_closure.py
│
├── tests/                          # Pattern A + Pattern A Fast(Phase 13) 전체 검증 스위트
└── docs/                           # 상세 설계 및 검증 보고서
    ├── roadmap.md                  # 전체 개발 로드맵
    ├── data_layer.md               # 데이터 레이어 설계 문서
    └── validation/                 # 각 컴포넌트별 검증 및 클로저 보고서
        ├── pattern_a_score_v02.md
        ├── pattern_a_stage_classifier_v01.md
        ├── pattern_a_evaluator_v01.md
        ├── data_quality_universe_v01.md
        ├── pattern_a_score_momentum_v01.md
        ├── krx_common_cache_population_v01.md
        ├── pattern_a_full_universe_scanner_v01.md
        ├── pattern_a_real_candidate_chart_review_v01.md
        ├── stage_v03_existing_feature_research.md
        ├── stage_v04_multi_year_research.md
        └── pattern_a_final_production_closure.md
```

---

## 🚀 빠른 시작

### 1. 환경 설정 및 설치

```bash
# 가상환경 생성 및 의존성 설치
uv sync

# 또는 pip 사용 시:
pip install -e ".[dev]"
```

### 2. 테스트 실행

```bash
uv run pytest
```

### 3. Pattern A 평가 예시

```python
from trend_scanner.data.cache import ParquetCache
from trend_scanner.patterns import evaluate_pattern_a, compute_pattern_a_score_momentum
from trend_scanner.validation.historical_snapshot import build_historical_snapshot

cache = ParquetCache()
daily = cache.load("000660")

# 1. 단일 시점 종합 평가 (Score + Stage + Candidate State, Completed Periods Only)
snapshot = build_historical_snapshot(
    ticker="000660",
    name="SK하이닉스",
    daily=daily,
    snapshot_date="2023-11-30",
    include_incomplete_periods=False,
)
eval_res = evaluate_pattern_a(snapshot)
print(f"Score: {eval_res.score:.2f}")
print(f"Stage: {eval_res.lifecycle_stage.value}")
print(f"Candidate State: {eval_res.candidate_state.value}")

# 2. 시간축 Score Momentum 측정 (1M, 3M, 6M Raw & Component Delta)
momentum_res = compute_pattern_a_score_momentum("000660", "SK하이닉스", daily, as_of="2023-11-30")
print(f"3M Score Delta: {momentum_res.horizon_3m.score_delta:+.2f}")
print(f"6M Score Delta: {momentum_res.horizon_6m.score_delta:+.2f}")
```

---

## 🗺️ 개발 로드맵 요약

**현재 작업 순서**: `README/Roadmap Sync = DONE` → `Stock Report Pattern A + Pattern A FAST 병렬 표시 = NEXT` → `Phase 12 Relative Strength = PLANNED / RESUME_READY` → `Phase 14 Pattern B = PLANNED`

* [x] **Phase 1~2**: Pattern A Feature Set & Score v0.2 Frozen
* [x] **Phase 3**: Pattern A Stage Classifier v0.1 Frozen
* [x] **Phase 4**: Pattern A Evaluator Integration v0.1 Completed
* [x] **Phase 5**: Data Quality & Universe Preparation v0.1 Completed
* [x] **Phase 6**: Pattern A Score Momentum v0.1 Completed
* [x] **Phase 7**: Official Common Stock Cache Population Completed (Coverage 98.34%)
* [x] **Phase 8**: Full Universe Scanner Integration Completed (2,528 Stocks)
* [x] **Phase 9A**: Candidate Review Dataset Preparation Completed (180 Candidates)
* [x] **Phase 9B**: Human Chart Review & Structural Audit Completed (Human42 Evidence)
* [x] **Pattern A Final Production Closure**: Official Closure Completed (`05d03e1`, Score v0.2 / Stage v0.1 KEEP, Stage Research CLOSED)
* [x] **Phase 10**: **`CLOSED`** Investability & Tradability Filter Completed (Market Cap >= 1,000억, 20D Liquidity >= 3억, 종가 hard filter 없음)
* [x] **Phase 11**: **`CLOSED`** Flow Confirmation Infrastructure Completed (`71237c0`, Point-In-Time 외국인 순매수 1D/5D/20D/60D + Flow intensity, 별도 Score/Rank/Hard Filter 미연결 — 정보성 feature, 기관 순매수는 미구현)
* [ ] **Phase 12**: **`PLANNED / RESUME_READY`** Relative Strength Infrastructure (Index & Sector RS) — KRX IP Block 해소, Stock Report 통합 이후 착수
* [x] **Phase 13**: **`RESEARCH_CLOSED / PRODUCTION_HOLD`** Pattern A Fast (Monthly Regime + Weekly Trigger + Daily Timing, Pattern A와 독립된 파생 전략) — Score Separation `PASS`, Lead Time `INCONCLUSIVE`, Experimental/Early Signal 사용 가능
* [ ] **Phase 14~18**: **`PLANNED`** Pattern B ~ F (Stage 2 Transition, High Base, RS Leading, VCP, Turnaround)
* [ ] **Phase 19**: **`PLANNED`** Pattern Score Matrix & Market Leader Score
* [ ] **Phase 20**: **`PLANNED`** Walk Forward / Paper Validation
* [ ] **Phase 21**: **`PLANNED`** Production Scanner & Operational Dashboard

자세한 로드맵은 [docs/roadmap.md](docs/roadmap.md)를 참고하세요.
