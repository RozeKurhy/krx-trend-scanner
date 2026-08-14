# Pattern A Universe & Data Quality Audit v0.1 보고서

## 1. 개요 및 목적

`Pattern A Data Quality / Universe Preparation v0.1`은 Full Universe Scanner로 넘어가기 전에, 실제 공인 KRX 종목 마스터(KOSPI / KOSDAQ)를 authoritative source로 연결하고, 로컬 캐시의 커버리지와 데이터 무결성, 절대 시장 신선도(Absolute Market Freshness), 그리고 **Pattern A Score v0.2, Stage Classifier v0.1, Evaluator v0.1**의 실행 준비도를 엄격히 검증하는 인프라 단계이다.

> [!NOTE]
> **핵심 원칙**:
> 1. Universe 선정은 투자 판단이 아니다. "이 종목을 Pattern A 시스템이 신뢰할 수 있는 데이터로 평가할 수 있는가?"만을 판단하며, Score가 낮거나 Stage가 WEAK여도 데이터가 정상이면 Universe에 포함된다.
> 2. **Official Universe Scope 분리**: 전체 KRX 종목 마스터(`Official Universe`)와 현재 로컬에 저장된 캐시(`Cached Dataset`)의 통계를 엄격히 분리하여 보고한다.

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
  * **식별 불가 자산 (UNKNOWN)**: 자산 유형이 불명확한 종목은 보통주로 자동 간주하지 않고 제외 (`UNKNOWN_ASSET_TYPE`).

---

## 3. 데이터 원천 및 수정주가 정책 (Data Source & Adjusted Price)

1. **데이터 소스**: `PyKrxDataProvider(adjusted=True)` (Naver 및 KRX 백엔드).
2. **수정주가 OHLC**:
   * 액면분할, 무상증자 등 권리락이 소급 반영된 수정주가 OHLCV를 사용.
   * 소급 계산 과정에서 발생하는 1원 이내 반올림 오차는 `_correct_minor_rounding_violations()`로 정규화.
3. **거래량(Volume) 특성 (Corporate Action Caveat)**:
   * PyKRX의 `adjusted=True` 경로의 거래량은 분할 조정되지 않은 원본 거래량임.
   * 현재 Score / Stage 핵심 구조는 **가격 기반 Feature(`range_36m`, `ma24_slope`, `weekly_ma12_slope`, `avg_price_change_12m` 등) 중심**이라 비수정 거래량 불연속성의 직접 영향은 제한적이다.
   * 향후 거래량 기반 Pattern E 또는 Volume Feature 확장 시 corporate action caveat를 재검토해야 한다.
4. **거래대금(Trading Value)**:
   * 당일 실제 체결 금액 기준이므로 액면분할의 영향을 받지 않음 (NaN 안전 처리 적용).

---

## 4. 최소 히스토리 요구사항 (Minimum History: 36 Completed Monthly Bars)

Pattern A Feature Set 및 Stage Classifier의 모든 필수 앵커를 결측 없이 완전하게 산출하기 위한 최소 히스토리 기준을 실측 검증하여 확정함.

* **최소 완성 월봉 수 (`MIN_HISTORY_MONTHS`)**: **36 completed monthly bars (3년, 약 750 trading days)**
* **산정 근거**:
  * `range_36m`: 36 completed monthly bars 필요
  * `ma24_slope_acceleration`: 24개월 MA + periods=3 + lag=3 ➔ 최소 30개월
  * `ma_spread_12m_ago`: 13개월 전의 24개월 MA ➔ 24 + 12 = 36개월
  * `avg_price_change_12m`: 최근 12개월 종가 평균 vs 직전 12개월 종가 평균 ➔ 최소 24개월
  * 진행 중인 마지막 미완성 월봉(`include_incomplete_periods=False`)은 제외되므로, 실질적으로 36개의 완성된 월봉이 요구됨.

---

## 5. Official KRX Universe & Data Quality Audit 실측 결과

### 5.1 Official KRX Universe 마스터 현황 (`reference_market_date = 2026-08-14`)

| 항목 | 수치 (건수) | 비율 (%) | 비고 |
|---|---|---|---|
| **공인 Universe 총 종목 수** | **2,763** | **100.0%** | KRX 공식 종목 마스터 (KOSPI + KOSDAQ) |
| ├ KOSPI | 942 | 34.1% | |
| └ KOSDAQ | 1,821 | 65.9% | |
| **자산 유형 분포 (Asset Types)** | | | |
| ├ 보통주 (COMMON) | 2,528 | 91.5% | Pattern A 기본 대상 |
| ├ 우선주 (PREFERRED) | 116 | 4.2% | 제외 대상 |
| ├ SPAC | 71 | 2.6% | 제외 대상 |
| ├ REIT | 25 | 0.9% | 제외 대상 |
| └ UNKNOWN | 23 | 0.8% | 보수적 제외 |

### 5.2 로컬 캐시 커버리지 (Cache Coverage)

| 항목 | 수치 (건수) | 비율 (%) |
|---|---|---|
| **Official Universe Total** | **2,763** | 100.0% |
| ├ 로컬 캐시 보유 (Cache Present) | **67** | **2.42%** |
| └ 로컬 캐시 부재 (Missing Cache) | **2,696** | **97.58%** |

### 5.3 보유 캐시 데이터 품질 감사 (Cached Dataset Quality: 67종목)

* **Raw Data Ready**: **67 / 67 (100.0%)**
* **Feature Ready**: **67 / 67 (100.0%)**
* **Score Ready**: **67 / 67 (100.0%)**
* **Stage Ready**: **67 / 67 (100.0%)**
* **Evaluator Ready**: **67 / 67 (100.0%)**
* **구조적 데이터 오염 (Missing Columns, Duplicates, Invalid OHLC, Future Dates)**: **0건 (0.0%)**
* **예외 발생 (Exceptions)**: **0건 (0.0%)**
* **히스토리 길이**: 67건 전수 **48개월 이상 (48m+, 100%)** 보유.
* **절대 시장 신선도 (vs 2026-08-14)**:
  * `VERY_STALE (6+ days)`: 67건 (과거 validation 및 OOS 테스트를 위해 고정된 시점의 캐시)

---

## 6. Final Judgment

### **`Pattern A Universe & Data Quality: UNIVERSE CONDITIONALLY READY`**

#### 종합 평가:
1. **Cached Dataset Quality Audit: PASSED**
   - 로컬에 보유한 67개 캐시 파일 전수에서 데이터 무결성 100%, Feature/Score/Stage/Evaluator 실행 100% 정상 작동이 검증됨.
2. **Official KRX Universe Source: ESTABLISHED**
   - PyKRX 기반의 공인 종목 마스터(2,763개) 연동 및 자산 분류(보통주 2,528개, 우선주 116개, SPAC 71개, REIT 25개) 체계 확립.
3. **Full Universe Scanner 전제 조건 (Condition)**:
   - 현재 로컬 캐시 커버리지는 2.42%(67개)이며, 데이터 시점이 과거 시점이므로, 향후 Full Universe Scanner 파이프라인 가동 전 2,528개 보통주에 대한 최신 일봉 캐시 수집(Cache Population)이 선행되어야 함.

---

## 7. Current Status & Next Step

### 7.1 확정 상태
```text
Pattern A Score v0.2: FROZEN
Pattern A Stage Classifier v0.1: FROZEN (43ee01c)
Pattern A Evaluator Integration v0.1: COMPLETED (51fc202)
Data Quality & Universe Preparation v0.1: COMPLETED (Authoritative Universe Source Established)
Cached Dataset Quality: 67 / 67 (100.0% Clean & Evaluator Ready)
Official KRX Universe: 2,763 Tickers (Common 2,528, Preferred 116, SPAC 71, REIT 25)
Unit & Integration Tests: 259 passed
Final Judgment: UNIVERSE CONDITIONALLY READY
Next: Score Momentum
```
