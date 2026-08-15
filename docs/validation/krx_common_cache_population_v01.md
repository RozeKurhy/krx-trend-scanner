# KRX Official Common Stock Cache Population v0.1 설계 및 검증 보고서 (Followup)

## 1. 개요 및 목적

`KRX Official Common Stock Cache Population v0.1`은 KRX 공인 Universe에서 **AssetType.COMMON (KOSPI / KOSDAQ 보통주)**으로 분류된 전 종목을 대상으로, Pattern A Full Universe Scanner를 신뢰할 수 있게 실행하기 위한 최신 일봉 OHLCV 및 Trading Value 캐시를 안전하고 결정론적으로 구축/갱신하는 Production Data Pipeline이다.

> [!IMPORTANT]
> **핵심 원칙 및 안전성 보장**:
> * **Atomic Cache Write & Verification**: `ParquetCache.save`는 임시 파일(`.{ticker}.parquet.tmp_{uuid}`)에 먼저 기록한 뒤, Read-Back Validation(`validate_ohlcv`, unique/sorted index, row count 검증)을 통과한 경우에만 `os.replace`로 원자적 교체한다. 오류 발생 시 임시 파일은 삭제되며 기존 캐시는 100% 보존된다.
> * **Metric & Scope Provenance 분리**: Local Cache Total, Official Universe Intersection, Official COMMON Cache Present, Orphan Cache를 엄격히 분리하여 보고한다.
> * **Incremental Update & Resumability**: 최신 거래일(`reference_market_date`)과 42개월 이상 히스토리를 보유한 종목은 자동 생략(`SKIPPED_FRESH`)하고, 누락/stale 종목만 증분 fetch한다.
> * **Failure Isolation**: 특정 종목의 API 오류/빈 데이터가 전체 파이프라인을 중단시키지 않으며, 종목별 failure reason을 기록한다.

---

## 2. 수집 정책 및 데이터 계약

### 2.1 대상 유니버스 (Universe Scope)
* **KOSPI / KOSDAQ 상장 보통주 (AssetType.COMMON)**
* **제외 자산**: PREFERRED, SPAC, REIT, ETF, ETN, UNKNOWN, KONEX
* **Reference Market Date**: `get_latest_market_trading_date()`를 통한 KRX 공식 최신 거래일 (`2026-08-14`)

### 2.2 히스토리 계약 (History Contract)
* **Contract Minimum**: **42 completed monthly bars** (Pattern A 6M Score Momentum 계산 최소 계약)
* **Preferred Target**: **48 completed monthly bars** (약 5개년 backfill)
* **Short History (신규 상장주)**: 상장 42개월 미만인 종목은 수집 성공(`CREATED`) 처리하되, 6M Momentum만 `ready=False`로 안전하게 격리.

### 2.3 캐시 병합 및 안전성 (Safe & Deterministic Merge)
* **Safe Merge**: 기존 캐시와 신규 수집 데이터 concat ➔ `~combined.index.duplicated(keep="last")` ➔ `sort_index()`
* **Future Date Protection**: `df.index > reference_market_date` 데이터 발견 시 validation failure 처리 및 저장 차단.
* **Orphan Cache Preservation**: 공인 Universe 밖의 기존 로컬 캐시(예: 002270, 010620 등)는 자동 삭제하지 않고 보존.

---

## 3. 원자적 캐시 저장 (Atomic Write Implementation)

```text
[Data Input] (merged DataFrame)
     │
     ▼
1. 임시 파일 생성: data/raw/stocks/.{ticker}.parquet.tmp_{uuid}
     │
     ▼
2. 임시 파일 쓰기: df.to_parquet(temp_path)
     │
     ▼
3. Read-Back 검증:
   - pd.read_parquet(temp_path)
   - validate_ohlcv(read_back)
   - read_back.index.is_monotonic_increasing
   - read_back.index.is_unique
   - len(read_back) == len(df)
     │
     ├── [검증 통과] ──▶ 4. os.replace(temp_path, final_path) (Atomic Replace 완료)
     └── [검증 실패] ──▶ 5. temp_path.unlink() (임시 파일 삭제, 기존 final_path 100% 보존)
```

---

## 4. Coverage & Provenance 공식 정의

* **Official COMMON Population Coverage %**:
  $$\text{COMMON Coverage} = \frac{\text{Official COMMON Cache Present}}{\text{Official COMMON Total}} \times 100\%$$
  (분모는 전체 Universe 2,763이 아닌 **Official COMMON 2,528개**)
* **Run Target Coverage %**:
  $$\text{Target Coverage} = \frac{\text{Run Target Success Count}}{\text{Run Population Target Count}} \times 100\%$$
* **Orphan Cache Count**: 로컬 캐시 파일 중 현재 Official Universe(KOSPI+KOSDAQ)에 속하지 않는 파일 개수.

---

## 5. 단위 및 통합 테스트 검증

20개 단위 테스트를 통해 모든 핵심 기능 및 엣지 케이스 검증 완료:
1. `test_missing_cache_create`
2. `test_existing_cache_incremental_update`
3. `test_fresh_cache_skip`
4. `test_idempotency`
5. `test_provider_failure_isolation`
6. `test_empty_response`
7. `test_invalid_schema`
8. `test_future_date`
9. `test_duplicate_merge`
10. `test_sorted_output`
11. `test_resume`
12. `test_short_history_new_listing`
13. `test_orphan_cache_preservation`
14. `test_dry_run`
15. `test_atomic_write_success`
16. `test_atomic_write_failure_preserves_existing_cache`
17. `test_temp_cleanup_on_failure`
18. `test_common_coverage_denominator`
19. `test_local_official_common_provenance_scope`
20. `test_subset_target_coverage_vs_global_coverage`

* **Unit Tests**: **20 passed (100% Green)**
* **Full Test Suite**: **293 passed, 10 skipped, 1 deselected, 0 failed (100% Green)**

---

## 6. Current Status & Next Step

### 6.1 확정 상태
```text
Pattern A Score v0.2: FROZEN
Pattern A Stage Classifier v0.1: FROZEN (43ee01c)
Pattern A Evaluator Integration v0.1: COMPLETED (51fc202)
Data Quality & Universe Preparation v0.1: COMPLETED (0ce8012)
Pattern A Score Momentum v0.1: FROZEN MEASUREMENT CONTRACT (707c594)
Official Common Stock Cache Population Pipeline: COMPLETED & VERIFIED (293 tests passed)
Atomic Cache Write: VERIFIED
COMMON Population Coverage Scope: VERIFIED
Full 2,528 Universe Population: IN PROGRESS (Background)
Scanner Integration: PENDING FULL AUDIT
```
