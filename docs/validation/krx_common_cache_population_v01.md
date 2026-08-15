# KRX Official Common Stock Cache Population v0.1 설계 및 검증 보고서

## 1. 개요 및 목적

`KRX Official Common Stock Cache Population v0.1`은 KRX 공인 Universe에서 **AssetType.COMMON (KOSPI / KOSDAQ 보통주 2,528개)**으로 분류된 전 종목을 대상으로, Pattern A Full Universe Scanner를 신뢰할 수 있게 실행하기 위한 최신 일봉 OHLCV 및 Trading Value 캐시를 안전하고 결정론적으로 구축/갱신하는 Production Data Pipeline이다.

> [!IMPORTANT]
> **핵심 원칙 및 안전성 보장**:
> * **Atomic Cache Write & Verification**: `ParquetCache.save`는 임시 파일(`.{ticker}.parquet.tmp_{uuid}`)에 먼저 기록한 뒤, Read-Back Validation(`validate_ohlcv`, unique/sorted index, row count 검증)을 통과한 경우에만 `os.replace`로 원자적 교체한다. 오류 발생 시 임시 파일은 삭제되며 기존 캐시는 100% 보존된다.
> * **Metric & Scope Provenance 분리**: Local Cache Total, Official Universe Intersection, Official COMMON Cache Present, Orphan Cache를 엄격히 분리하여 보고한다.
> * **Incremental Update & Resumability**: 최신 거래일(`reference_market_date`)과 42개월 이상 히스토리를 보유한 종목은 자동 생략(`SKIPPED_FRESH`)하고, 누락/stale 종목만 증분 fetch한다.
> * **Failure Isolation**: 특정 종목의 API 오류/빈 데이터/OHLC 가격 불일치가 전체 파이프라인을 중단시키지 않으며, 종목별 failure reason을 기록한다.

---

## 2. Full Population 최종 실측 결과 (2026-08-14 기준)

### 2.1 Universe Snapshot & Provenance
* **Official Universe Total**: **2,763개** (KOSPI 942, KOSDAQ 1,821, KONEX 0)
* **Official COMMON Total**: **2,528개** (KOSPI 830, KOSDAQ 1,698)
* **Local Cache Files Total**: **2,489개**
* **Official Universe Intersection**: **2,487개 (89.97%)**
* **Official COMMON Cache Present**: **2,486개 (98.34%)**
* **Official COMMON Missing**: **42개 (1.66%)**
* **Orphan Cache Count**: **2개** (`002270`, `010620`)

### 2.2 Execution Counts (2,528개 대상)
* **Run Target Count**: **2,528개**
* **Created (New)**: **978개**
* **Updated (Incremental)**: **230개**
* **Skipped (Fresh)**: **1,278개**
* **Failed (Isolated)**: **42개**
* **Identity 검증**: $978 + 230 + 1,278 + 42 = 2,528$ (100% 일치)

### 2.3 Failed Ticker Provenance (42건)
* **Failure 원인**: KRX/PyKRX 원천 데이터상 특정 일자에 `Low > High` 또는 `Open/Close` 가격 불일치 결함이 발견되어, Data Integrity Policy 및 Atomic Write 보호 정책에 따라 오염 방지를 위해 저장을 차단하고 FAILED 격리함.
* **대표 종목**:
  * `019010` (베뉴지): 2024-07-18 OHLC 불일치
  * `021650` (한국큐빅): 2025-07-15 OHLC 불일치
  * `028300` (HLB): 2021-09-09 외 3일 OHLC 불일치
  * `030350` (드래곤플라이): 2021-08-23 외 4일 OHLC 불일치
  * `086900` (메디톡스): 2021-10-08 OHLC 불일치
  * `119610` (인터로조): 2023-05-10 OHLC 불일치
  * `900140` (엘브이엠씨홀딩스): 2021-12-01 외 2일 OHLC 불일치 등 42건.

---

## 3. Data Quality & Readiness 감사 실측

### 3.1 Structural Integrity
* **Future Date Contamination**: **0건**
* **Duplicate Date Corruption**: **0건**
* **Unsorted Date Corruption**: **0건**
* **Missing Required Columns**: **0건**
* **Invalid OHLC in Cache**: **0건** (Atomic Write 검증으로 원천 차단)
* **Atomic Temp Residue**: **0건**
* **Quality Audit Exceptions**: **0건**

### 3.2 Freshness Distribution (Official COMMON 2,486개 기준)
* **Fresh (0~1일 지연)**: **2,370개 (95.33%)**
* **Stale (2~5일 지연)**: **7개 (0.28%)**
* **Very Stale (6일+ 지연)**: **109개 (4.38%)** (장기 거래정지 종목 등 정상 사유)

### 3.3 History Readiness Distribution
* **36M History Ready (Minimum)**: **2,230개 (89.70%)**
* **42M History Ready (6M Momentum Contract)**: **2,172개 (87.37%)**
* **48M History Ready (Preferred Target)**: **2,112개 (84.96%)**
* **< 36M Short History**: **256개 (10.30%)** (신규 상장주 정상 사유)

### 3.4 Pattern A Score Momentum 실측 (Official COMMON 2,486개 대상)
* **Current Score Ready**: **2,221개 / 2,486 (89.34%)**
* **1M Momentum Ready**: **2,213개 / 2,486 (89.02%)**
* **3M Momentum Ready**: **2,193개 / 2,486 (88.21%)**
* **6M Momentum Ready**: **2,165개 / 2,486 (87.09%)**
* **Momentum Unavailable 원인**:
  * `CURRENT_SCORE_UNAVAILABLE` / `INSUFFICIENT_HISTORY_CURRENT`: 263개 (신규상장 및 36m 미만)
  * `INSUFFICIENT_HISTORY_1M`: 8개 (37m 미만)
  * `INSUFFICIENT_HISTORY_3M`: 28개 (39m 미만)
  * `INSUFFICIENT_HISTORY_6M`: 56개 (42m 미만)
  * `NO_COMPLETED_MONTHLY_BARS`: 2개 (상장 1개월 미만 초신규 상장주)
  * **계산 오류 / 예외**: **0건 (100% 정상 산출)**

### 3.5 Layer Readiness (Universe Quality Audit 기준)
* **Raw Data Ready**: **2,487개**
* **Feature Ready**: **2,222개**
* **Score Ready**: **2,222개**
* **Stage Ready**: **2,213개**
* **Evaluator Ready**: **2,213개**

---

## 4. 단위 및 통합 테스트 회귀 결과

* **Cache Population Tests**: **21 passed (100% Green)**
* **Full Test Suite**: **298 passed, 6 skipped, 1 deselected, 0 failed (100% Green)**

---

## 5. 최종 판정 (Final Judgment)

* **Official Common Stock Cache Population v0.1**: **`COMPLETED & VERIFIED`**
* **Pipeline Implementation**: **`APPROVED`**
* **Atomic Cache Write**: **`VERIFIED (Residue 0)`**
* **Official COMMON Population Coverage**: **`98.34% (2,486 / 2,528)`**
* **Failure Provenance**: **`DOCUMENTED (42건 PyKRX OHLC 결함 차단)`**
* **Structural Integrity**: **`100% PASSED (0 Violations)`**
* **History & Momentum Readiness**: **`VERIFIED (87.09% ~ 89.34%)`**
* **Post Universe Quality Audit**: **`PASSED`**
* **Final Cache Population Judgment**: **`CACHE POPULATION READY`**
* **Phase 7 Status**: **`DONE`**
* **Phase 8 (Full Universe Scanner Integration)**: **`NEXT (Scanner Integration GO)`**
