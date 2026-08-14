# Pattern A Universe & Data Quality Audit v0.1 보고서

## 1. 개요 및 목적

`Pattern A Data Quality / Universe Preparation v0.1`은 Full Universe Scanner로 넘어가기 전에, 현재 KRX 데이터 캐시 및 종목 universe가 **Pattern A Score v0.2, Stage Classifier v0.1, Evaluator v0.1**을 안정적으로 실행할 수 있는지 검증하고 평가 가능한 종목의 경계를 정의하는 인프라 단계이다.

> [!NOTE]
> **핵심 철학**: Universe 선정은 투자 판단이 아니다. "이 종목을 Pattern A 시스템이 신뢰할 수 있는 데이터로 평가할 수 있는가?"만을 판단하며, Score가 낮거나 Stage가 WEAK여도 데이터가 정상이면 Universe에 포함된다.

---

## 2. Universe 정의 및 자산 적격성 정책 (Asset Eligibility Policy)

### 2.1 대상 시장 및 자산
* **기본 Universe 대상**: **KOSPI 보통주**, **KOSDAQ 보통주**
* **제외 대상 자산 (Unsupported Asset Types)**:
  * **우선주 (PREFERRED)**: 거래량 및 호가 구조 차이로 제외 (`UNSUPPORTED_ASSET_PREFERRED`).
  * **기업인수목적회사 (SPAC)**: 일반 기업 성장/추세 사이클과 상이하여 제외 (`UNSUPPORTED_ASSET_SPAC`).
  * **부동산투자회사 (REIT)**: 배당 중심 구조로 일반 추세 스캐너 대상에서 제외 (`UNSUPPORTED_ASSET_REIT`).
  * **ETF / ETN / 파생상품**: 지수/파생 상품으로 기업 주가 패턴 분석 대상에서 제외 (`UNSUPPORTED_ASSET_ETF`, `UNSUPPORTED_ASSET_ETN`).
  * **KONEX 시장**: 유동성 및 상장 규정 차이로 제외 (`EXCLUDED_MARKET_KONEX`).

---

## 3. 데이터 원천 및 수정주가 정책 (Data Source & Adjusted Price)

1. **데이터 소스**: `PyKrxDataProvider(adjusted=True)` (Naver 및 KRX 백엔드).
2. **수정주가 OHLC**:
   * 액면분할, 무상증자 등 권리락이 소급 반영된 수정주가 OHLCV를 사용.
   * 소급 계산 과정에서 발생하는 1원 이내 반올림 오차는 `_correct_minor_rounding_violations()`로 정규화.
3. **거래량(Volume) 특성 (Corporate Action Caveat)**:
   * PyKRX의 `adjusted=True` 경로의 거래량은 분할 조정되지 않은 원본 거래량임.
   * 장기 거래량 직접 비교 시 인위적 단차가 발생할 수 있으나, Pattern A Score 및 Stage Classifier의 핵심 Feature(`range_36m`, `ma24_slope`, `weekly_ma12_slope`, `avg_price_change_12m` 등)는 **가격 기반 Feature**이므로 평가 왜곡 위험이 차단되어 있음.
4. **거래대금(Trading Value)**:
   * 당일 실제 체결 금액 기준이므로 액면분할의 영향을 받지 않음 (NaN 안전 처리 적용).

---

## 4. 최소 히스토리 요구사항 (Minimum History: 36 Months)

Pattern A Feature Set 및 Stage Classifier의 모든 필수 앵커를 결측 없이 완전하게 산출하기 위한 최소 히스토리 기준을 실측 검증하여 확정함.

* **최소 완성 월봉 수 (`MIN_HISTORY_MONTHS`)**: **36개월 (3년, 약 750 trading days)**
* **산정 근거**:
  * `range_36m`: 36개월 월봉 필요
  * `ma24_slope_acceleration`: 24개월 MA + periods=3 + lag=3 ➔ 최소 30개월
  * `ma_spread_12m_ago`: 13개월 전의 24개월 MA ➔ 24 + 12 = 36개월
  * `avg_price_change_12m`: 최근 12개월 종가 평균 vs 직전 12개월 종가 평균 ➔ 최소 24개월
  * `high_52w`: 52주 (약 12개월)

---

## 5. Universe Quality Audit 실측 결과 (Summary)

로컬 캐시(`data/raw/stocks`) 내 69개 종목에 대한 전체 감사 결과:

| 감사 항목 | 수치 (건수) | 비율 (%) | 비고 |
|---|---|---|---|
| **총 감사 종목 (Total Tickers)** | **69** | **100.0%** | 로컬 캐시 전체 대상 |
| ├ KOSPI | 64 | 92.8% | |
| ├ KOSDAQ | 5 | 7.2% | |
| └ KONEX | 0 | 0.0% | |
| **Pattern A Universe 포함 (Included)** | **26** | **37.7%** | 최신 데이터 기준 평가 준비 완료 |
| **Pattern A Universe 제외 (Excluded)** | **43** | **62.3%** | 과거 검증용 캐시(STALE) 및 REIT 1건 |
| ├ VERY_STALE_DATA (과거 시점 캐시) | 43 | 62.3% | 2024년 고정 검증용 데이터 |
| └ UNSUPPORTED_ASSET (REIT) | 1 | 1.4% | `293940` 신한알파리츠 |

### 5.1 계층별 준비도 (Readiness Hierarchy)
* **Raw Data Ready**: **69 / 69 (100.0%)**
* **Feature Ready**: **69 / 69 (100.0%)**
* **Score Ready**: **69 / 69 (100.0%)**
* **Stage Ready**: **69 / 69 (100.0%)**
* **Evaluator Ready**: **69 / 69 (100.0%)**
* **Exception 발생**: **0건 (0.0%)**

### 5.2 데이터 무결성 검증 (Data Integrity)
* **Missing Columns (필수 컬럼 누락)**: **0건**
* **Duplicate Dates (중복 거래일)**: **0건**
* **Unsorted Dates (비정렬 거래일)**: **0건**
* **Invalid OHLC (가격 관계 위반 / 음수)**: **0건**
* **Future Dates (미래 날짜 오염)**: **0건**
* **Diagnostic Extreme Returns**: **0건**

### 5.3 히스토리 및 신선도 분포
* **히스토리 길이**: 69건 전수 **48개월 이상 (48m+, 100%)** 보유.
* **신선도 (`reference_market_date = 2026-02-27`)**:
  * `FRESH (0~1 days)`: 26건
  * `VERY_STALE (6+ days)`: 43건 (과거 validation frozen 캐시)

---

## 6. Final Judgment

### **`Pattern A Universe & Data Quality: UNIVERSE CONDITIONALLY READY`**

#### 종합 판정 사유:
1. **완벽한 데이터 무결성**: 69개 종목 전수에서 OHLC 관계 위반, 중복/비정렬/미래 날짜, 결측치, 예외 발생이 0건으로 데이터 무결성이 매우 우수함.
2. **100% Evaluator Readiness**: 69개 전 종목에서 Feature, Score v0.2, Stage v0.1, Evaluator v0.1 실행이 단 한 번의 예외 없이 100% 정상 작동함.
3. **조건부 사유 (Conditional Note)**: 현재 로컬 캐시의 43개 종목은 과거 OOS 검증을 위해 특정 시점으로 고정된 캐시(`VERY_STALE`)이므로, 향후 Full Universe Scanner 실행 시 최신 시장 데이터 업데이트(증분 갱신)가 전제되어야 함.

---

## 7. Next Step
Universe 및 데이터 품질 인프라가 확보되었으므로, 다음 단계인 **`Score Momentum`** 모델링 및 **`Full Universe Scanner`** 파이프라인으로 안전하게 진입합니다.
