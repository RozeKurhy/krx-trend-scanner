# KRX Official Common Stock Cache Population v0.1 설계 및 검증 보고서

## 1. 개요 및 목적

`KRX Official Common Stock Cache Population v0.1`은 KRX 공인 Universe에서 **AssetType.COMMON (KOSPI / KOSDAQ 보통주)**으로 분류된 전 종목을 대상으로, Pattern A Full Universe Scanner를 신뢰할 수 있게 실행하기 위한 최신 일봉 OHLCV 및 Trading Value 캐시를 안전하고 결정론적으로 구축/갱신하는 Production Data Pipeline이다.

> [!IMPORTANT]
> **핵심 철학 및 분리 원칙**:
> * **Data Preparation vs Trading Decision**: 이번 단계는 종목의 매력도나 랭킹을 매기는 것이 아니며, Score/Stage/State와 무관하게 모든 공인 보통주를 공평하게 수집한다.
> * **Authoritative Target**: KRX 공식 마스터의 KOSPI/KOSDAQ AssetType.COMMON만 수집 대상으로 삼으며, 우선주, ETF, ETN, SPAC, REIT는 제외한다.
> * **Incremental Update**: 이미 최신(`reference_market_date`)이고 충분한 히스토리가 있는 종목은 네트워크 호출을 생략(`SKIPPED_FRESH`)하고, stale 캐시만 overlap 증분 fetch한다.
> * **Failure Isolation**: 특정 종목의 API 오류/빈 데이터가 전체 파이프라인을 중단시키지 않으며, 종목별 실패 원인(Provenance)을 기록한다.

---

## 2. 수집 정책 및 데이터 계약

### 2.1 대상 유니버스 (Universe Scope)
* **KOSPI / KOSDAQ 상장 보통주 (AssetType.COMMON)**
* **제외 자산**: PREFERRED, SPAC, REIT, ETF, ETN, UNKNOWN, KONEX
* **Reference Market Date**: `get_latest_market_trading_date()`를 통한 KRX 공식 최신 거래일

### 2.2 히스토리 계약 (History Contract)
* **Contract Minimum**: **42 completed monthly bars** (Pattern A 6M Score Momentum 계산 최소 계약)
* **Preferred Target**: **48 completed monthly bars** (약 5개년 backfill)
* **Short History (신규 상장주)**: 상장 42개월 미만인 종목은 수집 성공(`CREATED`) 처리하되, 6M Momentum만 `ready=False`로 안전하게 격리.

### 2.3 캐시 병합 및 안전성 (Safe & Deterministic Merge)
* **Safe Merge**: 기존 캐시와 신규 수집 데이터 concat ➔ `~combined.index.duplicated(keep="last")` ➔ `sort_index()`
* **Future Date Protection**: `df.index > reference_market_date` 데이터 발견 시 validation failure 처리 및 저장 차단.
* **Orphan Cache Preservation**: 공인 Universe 밖의 기존 로컬 캐시(예: 상장폐지/합병 종목)는 자동 삭제하지 않고 보존.

---

## 3. 파이프라인 아키텍처

```text
Official KRX Universe (2,763개)
             ↓
AssetType.COMMON 필터링 (약 2,528개)
             ↓
     [Cache Population Service]
     ├── 1. 로컬 캐시 상태 및 Freshness 확인
     │       ├── 최신 & 42m+ 충족 ➔ SKIPPED_FRESH
     │       └── 부재 / Stale ➔ Fetch 범위 결정 (Backfill / Overlap)
     ├── 2. PyKRX Provider 호출 (Retry & Exponential Backoff)
     ├── 3. Future Date / Schema / OHLCV 무결성 검증
     └── 4. Deterministic Merge & Atomic Parquet Save
             ↓
     [Post-Population Quality Audit]
     ├── Universe Quality Auditor 실행
     └── Coverage, Freshness, Evaluator Readiness, Violations 검증
```

---

## 4. Reason & Status Code Contract

* `CachePopulationStatus`:
  * `SKIPPED_FRESH`: 이미 최신이고 42개월 이상 완성 월봉 보유
  * `UPDATED`: 기존 캐시에 최신 일봉 증분 병합 완료
  * `CREATED`: 신규 종목 5년치 일봉 캐시 생성 완료
  * `FAILED`: 수집/검증/저장 실패 (기존 캐시 보존)
  * `EXCLUDED_NOT_COMMON`: 보통주 아님 (사전 제외)

---

## 5. 단위 및 통합 테스트 검증

14개 단위 테스트를 통해 모든 엣지 케이스를 검증 완료:
1. `test_missing_cache_create`: 신규 캐시 생성 및 정렬/유니크 검증
2. `test_existing_cache_incremental_update`: 기존 캐시 증분 갱신 검증
3. `test_fresh_cache_skip`: 최신 캐시 스킵 및 API 호출 생략 검증
4. `test_idempotency`: 멱등성 검증 (중복 실행 시 불필요한 변경 없음)
5. `test_provider_failure_isolation`: 예외 격리 검증 (다른 종목 정상 진행)
6. `test_empty_response`: 빈 응답 시 FAILED 및 기존 캐시 보존 검증
7. `test_invalid_schema`: 스키마 결함 시 쓰기 금지 검증
8. `test_future_date`: 미래 날짜 오염 차단 검증
9. `test_duplicate_merge`: 중복 날짜 병합 및 신규 데이터 우선 검증
10. `test_sorted_output`: 일봉 오름차순 정렬 보장 검증
11. `test_resume`: 중단 후 재실행 시 완료 종목 스킵 및 실패 종목 재시도 검증
12. `test_short_history_new_listing`: 신규 상장주 단기 히스토리 처리 검증
13. `test_orphan_cache_preservation`: 고아 캐시 파일 보존 검증
14. `test_dry_run`: Dry-run 계획 수립 검증

* **Unit Tests**: **14 passed (100% Green)**
* **Full Test Suite**: **287 passed, 10 skipped, 1 deselected, 0 failed (100% Green)**

---

## 6. 알려진 한계 (Known Limitations)

1. **외부 Provider 가용성**: PyKRX 및 KRX 웹서버의 일시적 장애나 속도 제한에 영향을 받을 수 있다.
2. **거래정지 종목의 시차**: 장기 거래정지 종목은 reference date와 최종 거래일이 일치하지 않을 수 있으며, 이는 정상적인 Stale 데이터로 분류된다.
3. **신규 상장주의 히스토리 제약**: 상장 42개월 미만 종목은 정상적으로 캐시가 생성되더라도 6M Momentum 계산이 불가능하다.
4. **수정주가 왜곡 가능성**: 대규모 무상증자/액면분할 시 과거 데이터의 조정 가격 연결에 소폭 오차가 있을 수 있다.

---

## 7. Current Status & Next Step

### 7.1 확정 상태
```text
Pattern A Score v0.2: FROZEN
Pattern A Stage Classifier v0.1: FROZEN (43ee01c)
Pattern A Evaluator Integration v0.1: COMPLETED (51fc202)
Data Quality & Universe Preparation v0.1: COMPLETED (0ce8012)
Pattern A Score Momentum v0.1: FROZEN MEASUREMENT CONTRACT (707c594)
Official Common Stock Cache Population v0.1: COMPLETED (287 tests passed)
Next: Full Universe Scanner Integration v0.1
```
