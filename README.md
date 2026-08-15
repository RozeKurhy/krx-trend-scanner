# krx-trend-scanner

코스피와 코스닥 상장 보통주(AssetType.COMMON)를 대상으로 **대세 상승 초입에 진입하는 종목을 정량적으로 탐색하기 위한 스크리너 프로젝트**입니다.

단순히 이미 상승 중인 종목을 찾는 것이 아니라, 월봉과 주봉을 중심으로 장기 가격 구조와 추세 변화를 분석해 **상승 추세가 막 만들어지기 시작하는 후보**를 선별하는 것을 목표로 합니다.

---

## 🌟 주요 특징 및 핵심 철학

* **다차원 독립 측정 분리 (Orthogonal Architecture)**:
  * **Score** (현재 시점의 매력도, 0~100점): 장기 베이스 안정성과 전환 시그널의 조화평균 결합
  * **Stage** (현재 라이프사이클 국면): `WEAK` ➔ `BASE` ➔ `TRANSITION` ➔ `EARLY_TREND` ➔ `PROGRESSED`
  * **Score Momentum** (시간에 따른 Score 변화량): 정확한 Calendar 1M, 3M, 6M 시점 간의 Raw Delta 및 Component Delta
  * **Candidate State** (해석 상태): `CANDIDATE`, `WATCH`, `LATE`, `BLOCKED`, `INSUFFICIENT_DATA`
* **Lookahead 원천 차단 (Time-Travel Free)**:
  * 모든 스냅샷 및 피처는 `snapshot_date` 이전의 확정된 데이터만을 사용하여 과거 시점을 완벽하게 재현합니다.
* **Fail-Closed 데이터 품질 관리**:
  * 엄격한 OHLCV 검증, 36 Completed Months 계약, 불완전 월봉 오인 차단, 종목명 매핑 무결성 보장.

---

## 📐 패턴 기반 스크리닝 (Pattern A)

### Pattern A: 장기 베이스 수렴 및 초기 추세 전환형

장기간 박스권 또는 횡보 구간을 형성하면서 저점이 점차 상승하고, 장기 이동평균선(MA24)이 평탄화/상승 전환하며 수렴하는 형태입니다.

* **Base Score**: 36개월 레인지(`range_36m`), 12개월 평균 주가 변화율(`avg_price_change_12m`), 이동평균 수렴도(`ma_spread`)
* **Transition Score**: 24개월 이평선 기울기(`ma24_slope`), 주봉 12주 이평선 기울기(`weekly_ma12_slope`), 24개월 이평선 가속도(`ma24_slope_acceleration`)
* **Core & Support 결합**: 핵심 지표(`ma24_slope`) 중심의 조화평균(Harmonic Mean) 결합으로 단기 왜곡 억제
* **Bonuses & Penalties**: Alignment Bonus 및 장기 이격 과열에 대한 Progressed Penalty 적용

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
│       ├── universe/               # 유니버스 준비도 및 데이터 품질 감사
│       │   └── quality_auditor.py  # Universe Data Quality Auditor
│       │
│       └── validation/             # 스냅샷 생성 및 피처 리포트
│           ├── historical_snapshot.py
│           └── feature_report.py
│
├── tests/                          # 273개 유닛 및 통합 테스트 (100% Green)
└── docs/                           # 상세 설계 및 검증 보고서
    ├── roadmap.md                  # 전체 개발 로드맵
    ├── data_layer.md               # 데이터 레이어 설계 문서
    └── validation/                 # 각 컴포넌트별 검증 보고서
        ├── pattern_a_score_v02.md
        ├── pattern_a_stage_classifier_v01.md
        ├── pattern_a_evaluator_v01.md
        ├── data_quality_universe_v01.md
        └── pattern_a_score_momentum_v01.md
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

cache = ParquetCache()
daily = cache.load("000660")

# 1. 단일 시점 종합 평가 (Score + Stage + Candidate State)
eval_res = evaluate_pattern_a("000660", "SK하이닉스", daily, as_of="2023-11-30")
print(f"Score: {eval_res.score.pattern_a_score:.2f}")
print(f"Stage: {eval_res.stage.stage.name}")
print(f"Candidate State: {eval_res.candidate_state.name}")

# 2. 시간축 Score Momentum 측정 (1M, 3M, 6M Raw & Component Delta)
momentum_res = compute_pattern_a_score_momentum("000660", "SK하이닉스", daily, as_of="2023-11-30")
print(f"3M Score Delta: {momentum_res.horizon_3m.score_delta:+.2f}")
print(f"6M Score Delta: {momentum_res.horizon_6m.score_delta:+.2f}")
```

---

## 🗺️ 개발 로드맵 요약

* [x] **Phase 1~2**: Pattern A Feature Set & Score v0.2 Frozen
* [x] **Phase 3**: Pattern A Stage Classifier v0.1 Frozen
* [x] **Phase 4**: Pattern A Evaluator Integration v0.1 Completed
* [x] **Phase 5**: Data Quality & Universe Preparation v0.1 Completed
* [x] **Phase 6**: Pattern A Score Momentum v0.1 Completed
* [x] **Phase 7**: Official Common Stock Cache Population Completed (Coverage 98.34%)
* [ ] **Phase 8**: Full Universe Scanner Integration (NEXT)
* [ ] **Phase 9**: Real Candidate Chart Review
* [ ] **Phase 10~17**: Liquidity Filter, RS, Flow, Pattern B~F
* [ ] **Phase 18~20**: Market Leader Score & Production Scanner

자세한 로드맵은 [docs/roadmap.md](docs/roadmap.md)를 참고하세요.
