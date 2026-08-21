# Pattern A Full Universe Scanner Integration v0.1 설계 및 검증 보고서 (Followup Revision)

## 1. 개요 및 목적

`Pattern A Full Universe Scanner Integration v0.1`은 KRX 공인 Universe에서 **AssetType.COMMON (KOSPI / KOSDAQ 보통주 2,528개)**으로 분류된 전 종목을 대상으로, Frozen Pattern A Score v0.2, Stage Classifier v0.1, Candidate State, Score Momentum v0.1, Layer Readiness 및 Data Quality Flags를 종목별 단일 Row로 통합하여 다차원 결과 매트릭스를 생성하고 데이터/스코어 분포를 관찰(Distribution Inspection)하는 Production Integration Layer이다.

> [!IMPORTANT]
> **핵심 설계 및 Temporal Semantics 원칙**:
> 1. **Completed Period Evaluation Contract**:
>    - Evaluator용 historical snapshot은 공식 계약에 따라 `include_incomplete_periods=False`로만 생성하여 진행 중인 미완성 월봉/주봉을 철저히 배제하고 완성된 봉(Completed Periods)만을 평가에 사용한다.
> 2. **Single Temporal Context (One Cache Load -> One daily_as_of Slice -> Shared Context)**:
>    - Ticker당 1회 parquet 캐시 로드 후 즉시 `daily_as_of = daily.loc[daily.index <= req_as_of]`를 생성하고, Quality Auditor, Historical Snapshot/Evaluator, Score Momentum 모두 동일한 `daily_as_of`를 컨텍스트로 소비하여 lookahead 및 `FUTURE_DATE` 오탐을 원천 차단한다.
> 3. **Anchor-based Current Momentum Readiness**:
>    - `momentum_current_ready`는 `momentum_res.observations` 중 `anchor_date == momentum_anchor`인 시점 $T$의 observation의 score 유무로 정확히 판정한다.
>    - Invariant: $N(\text{Current Ready}) \ge \max(N(\text{1M Ready}), N(\text{3M Ready}), N(\text{6M Ready}))$.
> 4. **Global Universe Count vs Subset Target Count Separation**:
>    - `official_common_total`: 전체 resolved Official COMMON 개수 (글로벌 2,528개)
>    - `scan_target_count`: subset 필터 적용 후 실제 scanner 대상 개수
>    - `rows_emitted`: 실제 출력 row 수
> 5. **Fail-Closed Universe & Row Count 보존**:
>    - 캐시 누락(42개)이나 히스토리 부족(36m 미만 274개) 종목도 Universe에서 drop하지 않고 단일 Row를 유지하며 `INSUFFICIENT_DATA` 및 명확한 reason provenance로 fail-closed 처리한다.
> 6. **No Ranking / No Cutoff Policy**:
>    - Ranking, Top N, Cutoff 필터링, Unified/Composite Score, BUY/SELL 해석을 일체 배제한다.
> 7. **Deterministic Ordering & Exception Isolation**:
>    - 결과는 `(MarketType, Ticker)` 순으로 결정론적으로 정렬되며, 예외 발생 시 `row_status=ERROR`로 격리된다.

---

## 2. Full Universe Scan 최종 실측 결과 (2026-08-14 기준)

### 2.1 Universe Snapshot & Row Count
* **Official COMMON Total (Global)**: **2,528개** (KOSPI 830, KOSDAQ 1,698)
* **Scan Target Count**: **2,528개**
* **Scanner Rows Emitted**: **2,528개** (100% 1 ticker = 1 row)
* **Duplicate Rows**: **0건**
* **Missing Output Rows**: **0건**
* **Cache Present Count**: **2,486개 (98.34%)**
* **Cache Missing Count**: **42개 (1.66%)** (PyKRX 원천 OHLC 모순으로 격리된 종목, Row 유지)
* **Scanner Calculation Errors**: **0건 (100% 무오류)**

### 2.2 Layer Readiness 실측 (Completed Periods Contract)
* **Raw Data Ready**: **2,486개 (98.34%)**
* **Feature Ready**: **2,221개 (87.86%)**
* **Score Ready**: **2,221개 (87.86%)**
* **Stage Ready**: **2,212개 (87.50%)**
* **Evaluator Ready**: **2,212개 (87.50%)**
* **Momentum Current Ready**: **2,221개 (87.86%)**
* **Momentum 1M Ready**: **2,213개 (87.54%)**
* **Momentum 3M Ready**: **2,193개 (86.75%)**
* **Momentum 6M Ready**: **2,165개 (85.64%)**

> [!NOTE]
> **Readiness 정합성 검증**:
> - $N(\text{Score Ready}) = N(\text{Score Distribution N}) = \mathbf{2,221}$ (100% 일치)
> - $N(\text{Stage Ready}) = N(\text{Evaluable Stages}) = 125 + 168 + 12 + 411 + 1496 = \mathbf{2,212}$ (100% 일치)
> - $N(\text{Evaluator Ready}) = N(\text{candidate\_state} \ne \text{INSUFFICIENT\_DATA}) = \mathbf{2,212}$ (100% 일치)
> - $N(\text{Momentum Current Ready: 2221}) \ge 2213 \ge 2193 \ge 2165$ (완벽한 단조 감소 Invariant 성립)

### 2.3 Row Status Distribution
* **OK (Evaluator 및 모든 Momentum Horizon 정상)**: **2,158개 (85.36%)**
* **PARTIAL (Evaluator 정상이나 일부 Momentum 미준비)**: **54개 (2.14%)**
* **UNAVAILABLE (캐시 부재 또는 36m 미만 정상 Fail-Closed)**: **316개 (12.50%)**
* **ERROR (예상치 못한 예외)**: **0개 (0.00%)**

---

## 3. 다차원 결과 매트릭스 분포 관찰 (Distribution Inspection)

### 3.1 Lifecycle Stage Distribution (Completed Periods Only)
| Official Stage | 종목 수 (개) | 비율 (%) | 비고 |
| :--- | :--- | :--- | :--- |
| **WEAK** | 1,496 | 59.18% | 장기 하락 또는 횡보 미흡 |
| **PROGRESSED** | 411 | 16.26% | 이미 장기 상승이 상당히 진행된 국면 |
| **TRANSITION** | 168 | 6.65% | 장기 이평 상방 전환 초기 국면 (CANDIDATE) |
| **BASE** | 125 | 4.94% | 장기 박스권/수렴 형성 국면 |
| **EARLY_TREND** | 12 | 0.47% | 초기 상승 추세 확립 국면 (CANDIDATE) |
| **UNAVAILABLE** | 316 | 12.50% | 캐시 누락(42) 및 단기 상장주(274) |
| **합계** | **2,528** | **100.00%** | |

### 3.2 Candidate State Distribution
| Candidate State | 종목 수 (개) | 비율 (%) | 대응 Stage |
| :--- | :--- | :--- | :--- |
| **BLOCKED** | 1,496 | 59.18% | WEAK |
| **LATE** | 411 | 16.26% | PROGRESSED |
| **CANDIDATE** | **180** | **7.12%** | **TRANSITION (168) + EARLY_TREND (12)** |
| **WATCH** | 125 | 4.94% | BASE |
| **INSUFFICIENT_DATA** | 316 | 12.50% | UNAVAILABLE |
| **합계** | **2,528** | **100.00%** | |

### 3.3 Numeric Distributions (Score & Score Momentum)
| Metric | Valid N | Mean | Std | Min | Q25 (25%) | Median | Q75 (75%) | Max |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Pattern A Score** | 2,221 | 20.48 | 26.16 | 0.00 | 0.00 | 2.75 | 39.96 | 100.00 |
| **Momentum 1M ($\Delta$)** | 2,213 | -4.48 | 9.98 | -63.86 | -8.84 | 0.00 | 0.00 | +56.86 |
| **Momentum 3M ($\Delta$)** | 2,193 | -12.57 | 21.22 | -100.00 | -24.60 | -5.94 | 0.00 | +64.51 |
| **Momentum 6M ($\Delta$)** | 2,165 | -12.94 | 27.33 | -100.00 | -29.85 | -3.82 | 0.00 | +80.63 |

---

## 4. Phase 7 Baseline과의 비교 분석

* **Official COMMON Total**: 2,528 (일치)
* **Cache Present / Missing**: 2,486 / 42 (일치)
* **Score Ready**: 2,221 (일치)
* **Stage Ready / Evaluator Ready**: 2,212 (일치)
* **Momentum Current Ready**: 2,221 (신규 정확한 시점 T Observation 반영)
* **Momentum 1M / 3M / 6M Ready**: 2,213 / 2,193 / 2,165 (일치)
* **결론**: Phase 7 Baseline과 Scanner 집계 수치가 **100% 완벽하게 일치**하며, temporal snapshot 계약(`include_incomplete_periods=False`)이 온전히 반영됨.

---

## 5. 알려진 한계 (Known Limitations)

1. **Current Official Universe 기준 Scanner**:
   - 현재 시점의 authoritative universe를 기준으로 스캔을 수행하며, 과거 특정 시점의 상장 폐지/신규 상장 멤버십 역추적은 지원하지 않는다.
2. **Missing Cache COMMON Fail-Closed**:
   - 캐시가 누락된 42개 보통주는 row 단위로 유지되되, `raw_data_ready=False` 및 `INSUFFICIENT_DATA`로 fail-closed 처리된다.
3. **Short History 종목의 부분 가용성**:
   - 36m 미만 신규 상장주는 Evaluator가 `INSUFFICIENT_DATA`로 반환되며, 37m/39m/42m에 따라 1M/3M/6M Momentum이 독립적으로 가용/불가 처리된다.
4. **No Ranking / No Predictive Claim**:
   - 본 Scanner의 출력은 특정 종목의 매수/매도 추천이나 미래 수익률 예측이 아니며, 오직 측정 지표의 통합과 분포 관찰 목적이다.

---

## 6. 단위 및 통합 테스트 결과

* **Scanner Tests (`tests/test_full_universe_scanner.py`)**: **12 passed (100% Green)**
* **Full Test Suite**: **310 passed, 6 skipped, 1 deselected, 0 failed (100% Green)**

---

## 7. 아티팩트 (Artifacts)

* **Scan Matrix CSV**: `artifacts/scanner/pattern_a_universe_scan_20260814.csv` (2,528 rows)
* **Scan Summary JSON**: `artifacts/scanner/pattern_a_universe_scan_20260814_summary.json`

---

## 8. 최종 판정 (Final Judgment)

* **Full Universe Scanner Integration v0.1**: **`COMPLETED & VERIFIED`**
* **Temporal Semantics & Completed Periods**: **`100% ALIGNED`**
* **Readiness Provenance & Invariants**: **`100% CONSISTENT`**
* **Phase 8 Status**: **`DONE`**
* **Phase 9 (Real Candidate Chart Review)**: **`NEXT (Candidate: 180 Stocks)`**
