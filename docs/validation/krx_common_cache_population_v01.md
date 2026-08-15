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
* **Orphan Cache Count**: **2개** (`002270` KG피앤씨, `010620` 현대미포조선) (비공식 유니버스 캐시 100% 무손상 보존)

### 2.2 Execution Counts (2,528개 대상)
* **Run Target Count**: **2,528개**
* **Created (New)**: **978개**
* **Updated (Incremental)**: **230개**
* **Skipped (Fresh)**: **1,278개**
* **Failed (Isolated)**: **42개**
* **Identity 검증**: $978 + 230 + 1,278 + 42 = 2,528$ (100% 일치)

### 2.3 Failed Ticker Provenance (42건 전체 authoritative 검증)
* **Failure 원인**: 42건 모두 PyKRX/KRX 원천 일봉 데이터상 특정 일자에 `Low > High` 또는 `Open/Close` 가격 불일치 결함(`MarketDataError`)이 발견되어, Data Integrity Policy 및 Atomic Write 보호 정책에 따라 캐시 오염을 방지하기 위해 저장을 차단하고 FAILED 격리함.
* **KOSPI 보통주 (10개)**:
  * `000100` (유한양행), `001060` (JW중외제약), `001440` (대한전선), `002720` (국제약품), `005420` (코스모화학), `010780` (아이에스동서), `101140` (인바이오젠), `119650` (KC코트렐), `128940` (한미약품), `900140` (엘브이엠씨홀딩스)
* **KOSDAQ 보통주 (32개)**:
  * `019010` (베뉴지), `021650` (한국큐빅), `028300` (HLB), `030350` (드래곤플라이), `032750` (삼진), `049950` (미래컴퍼니), `050760` (에스폴리텍), `054180` (메디콕스), `056090` (시지메드텍), `069140` (누리플랜), `072950` (빛샘전자), `078890` (가온그룹), `086900` (메디톡스), `088800` (에이스테크), `089600` (KT나스미디어), `094860` (네오리진), `111710` (남화산업), `119610` (인터로조), `128540` (에코캡), `131090` (시큐브), `131400` (이브이첨단소재), `142210` (유니트론텍), `175250` (아이큐어), `179530` (애드바이오텍), `263020` (디케이앤디), `279600` (미디어젠), `284620` (카이노스메드), `317770` (엑스페릭스), `336570` (원텍), `347860` (알체라), `352770` (셀레스트라), `355150` (코스텍시스)
* **검증 결과**: 42개 실패 종목 모두 100% `AssetType.COMMON`이며, Artifact CSV(`population_20260814.csv`)와의 종목명/메타데이터 불일치 0건.

---

## 3. Data Quality & Readiness 실측 감사

### 3.1 Structural Integrity
* **Future Date Contamination**: **0건**
* **Duplicate Date Corruption**: **0건**
* **Unsorted Date Corruption**: **0건**
* **Missing Required Columns**: **0건**
* **Invalid OHLC Violations in Cache**: **0건** (Atomic Write 검증으로 원천 차단)
* **Atomic Temp Residue**: **0건**
* **Quality Audit Exceptions**: **0건**

### 3.2 Freshness Distribution (Official COMMON 2,486개 기준)
* **Fresh (0~1일 지연)**: **2,370개 (95.33%)**
* **Stale (2~5일 지연)**: **7개 (0.28%)**
* **Very Stale (6일+ 지연)**: **109개 (4.38%)** (장기 거래정지 종목 등 정상 사유)

### 3.3 History Readiness (Official COMMON 2,486개 기준)
* **36M History Ready (Minimum)**: **2,230개 (89.70%)**
* **42M History Ready (6M Momentum Contract)**: **2,172개 (87.37%)**
* **48M History Ready (Preferred Buffer Target)**: **2,112개 (84.96%)**
* **< 36M Short History**: **256개 (10.30%)** (신규 상장주 정상 사유)

### 3.4 Pattern A Score Momentum 실측 (Official COMMON 2,486개 대상)
* **Current Score Ready**: **2,221개 / 2,486 (89.34%)**
* **1M Momentum Ready**: **2,213개 / 2,486 (89.02%)**
* **3M Momentum Ready**: **2,193개 / 2,486 (88.21%)**
* **6M Momentum Ready**: **2,165개 / 2,486 (87.09%)**
* **Momentum Unavailable 원인 분석**:
  * `CURRENT_SCORE_UNAVAILABLE` / `INSUFFICIENT_HISTORY_CURRENT`: 263개 (신규상장 및 36m 미만)
  * `INSUFFICIENT_HISTORY_1M`: 8개 (37m 미만)
  * `INSUFFICIENT_HISTORY_3M`: 28개 (39m 미만)
  * `INSUFFICIENT_HISTORY_6M`: 56개 (42m 미만)
  * `NO_COMPLETED_MONTHLY_BARS`: 2개 (상장 1개월 미만 초신규 상장주)
  * **계산 오류 / 예외**: **0건 (100% 정상 산출)**

### 3.5 Layer Readiness Scope별 상세 집계
* **Official Universe Quality Audit Scope (전체 2,763개 대상)**:
  * Raw Data Ready: **2,487개**
  * Feature Ready: **2,222개**
  * Score Ready: **2,222개**
  * Stage Ready: **2,213개**
  * Evaluator Ready: **2,213개**
* **Official COMMON Scope (전체 2,528개 보통주 대상)**:
  * Cached: **2,486개 (98.34%)**
  * Raw Data Ready: **2,486개 (98.34%)**
  * Feature Ready: **2,221개 (87.86%)**
  * Score Ready: **2,221개 (87.86%)**
  * Stage Ready: **2,212개 (87.50%)**
  * Evaluator Ready: **2,212개 (87.50%)**
* **Cached COMMON Scope (캐시 보유 2,486개 보통주 대상)**:
  * Raw Data Ready: **2,486개 (100.00%)**
  * Feature Ready: **2,221개 (89.34%)**
  * Score Ready: **2,221개 (89.34%)**
  * Stage Ready: **2,212개 (88.98%)**
  * Evaluator Ready: **2,212개 (88.98%)**

---

## 4. 알려진 한계 (Known Limitations)

### 4.1 External Provider Dependency
* PyKRX / KRX backend 상태에 따라 일시적 오류, timeout, rate limiting 또는 빈 DataFrame 응답이 발생할 수 있다.
* 파이프라인은 retry & exponential backoff와 failure isolation을 통해 이를 격리하며, 실패 종목의 error provenance를 정확히 기록한다.

### 4.2 Trading Suspension & Repeated Fetch
* 장기 거래정지 종목은 정상적인 데이터임에도 최종 거래일(`cache_last_date`)이 `reference_market_date`에 도달하지 못할 수 있다.
* Population의 엄격한 Skip 조건(`cache_last_date == reference_market_date`)을 만족하지 못하므로, 재실행 시마다 overlap 구간 fetch가 재시도될 수 있다. 이는 정상 동작이며 임의로 Universe에서 제외하지 않는다.

### 4.3 Short History / New Listing
* 신규 상장주는 정상적으로 캐시가 수집(`CREATED`)되더라도 36개월 미만이면 Score/Stage가 `insufficient_data`로 평가되고, 42개월 미만이면 6M Momentum이 `ready=False`로 반환된다. 이는 데이터 결함이나 fetch 실패가 아닌 정상적인 short history이다.

### 4.4 Adjusted Price Caveat
* 수정주가(`adjusted=True`) 정책을 일관되게 사용하며, 대규모 무상증자/액면분할 등 corporate action 시 provider의 과거 가격 조정 방식에 영향을 받을 수 있다.

### 4.5 Freshness Semantics Difference (Population Fresh vs Audit Fresh)
* **Population Fresh (`SKIPPED_FRESH`)**:
  * **Strict Operational Condition**: `cache_last_date == reference_market_date` AND `completed_months >= 42`.
  * 네트워크 호출을 생략해도 되는지 판단하는 엄격한 운영 조건이다.
* **Audit Fresh (`FreshnessStatus.FRESH`)**:
  * **Quality Classification**: `reference_market_date` 대비 영업일 지연 `staleness_trading_days <= 1`.
  * 유니버스 품질 감사 시 1거래일 이내 데이터를 최신으로 분류하는 통계적 등급이다.
* 두 개념은 사용 목적이 상이하므로 동일한 의미로 혼용하지 않는다.

### 4.6 Fail Closed OHLC Cases (42건)
* 이번 Full Population에서 42개 종목이 FAILED로 격리된 것은 캐시 손상(Corruption)이 아니다.
* 원천 데이터의 OHLC 가격 모순(`Low > High` 등)을 validator가 사전에 감지하고 `ParquetCache.save`의 원자적 쓰기 단계에서 차단한 **Fail-Closed 보호의 결과**이다.
* 따라서 **"Accepted Cache의 Structural Corruption = 0"**과 **"Population Failed = 42"**는 동시에 완벽하게 성립한다.

---

## 5. 단위 및 통합 테스트 회귀 결과

* **Cache Population Tests**: **21 passed (100% Green)**
* **Full Test Suite**: **298 passed, 6 skipped, 1 deselected, 0 failed (100% Green)**

---

## 6. 최종 판정 (Final Judgment)

* **Official Common Stock Cache Population v0.1**: **`COMPLETED & FROZEN`**
* **Pipeline Implementation**: **`APPROVED`**
* **Atomic Cache Write**: **`VERIFIED (Residue 0)`**
* **Official COMMON Population Coverage**: **`98.34% (2,486 / 2,528)`**
* **Accepted Cache Structural Integrity**: **`100% PASSED (0 Violations)`**
* **Contract Critical Readiness**:
  * Current Score Ready: **89.34% (2,221 / 2,486)**
  * Momentum 1M Ready: **89.02% (2,213 / 2,486)**
  * Momentum 3M Ready: **88.21% (2,193 / 2,486)**
  * Momentum 6M Ready: **87.09% (2,165 / 2,486)**
* **History Readiness**:
  * 36M History Ready: **89.70% (2,230 / 2,486)**
  * 42M History Ready: **87.37% (2,172 / 2,486)**
  * 48M Preferred Buffer: **84.96% (2,112 / 2,486)**
* **Post Universe Quality Audit**: **`PASSED`**
* **Final Cache Population Judgment**: **`CACHE POPULATION READY`**
* **Full Population & Final Audit Evidence**: **`8983e65`**
* **Final Documentation & Provenance Evidence**: **`7ff45fe`**
* **Phase 7 Status**: **`DONE`**
* **Phase 8 (Full Universe Scanner Integration)**: **`NEXT (Scanner Integration GO)`**
