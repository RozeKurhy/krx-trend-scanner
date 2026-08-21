test_suite_performance_audit_v01.md

# Test Suite Performance Audit & Refactor v0.1

이 문서는 test infrastructure audit 문서이며, Pattern A / Pattern A FAST strategy
authority가 아니다. 검증 강도(coverage)나 production semantics를 바꾸지 않고,
테스트 실행 구조(중복 계산 제거, fixture 재사용, slow 격리)만 개선한 기록이다.

## 1. 문제 배경

Full Test Suite가 약 66분(3962.13초, 865 passed / 6 skipped / 3 deselected)
소요되는 것이 확인되었다. 근본 원인은 "테스트 개수가 많아서"가 아니라, 작은
invariant 하나를 확인하기 위해 대형 production computation(2,528종목 Full
Universe Scan, Stock Report 생성 등)을 반복 실행하는 구조였다.

대표 사례: `tests/test_pattern_a_relative_strength_infrastructure.py`의
negative test 다수가 "Gate 판정 하나 테스트" = "2,528종목 전체 production
scan 재실행" 구조였고, 일부 단일 테스트가 120초 이상, 파일 전체는 수십 분
이상 소요됐다.

## 2. Before baseline

공식 기록(재실행하지 않고 그대로 사용):

```
FULL_SUITE = 3962.13 sec (≈ 66분 02초), 865 passed, 6 skipped, 3 deselected, 0 failed
STOCK_REPORT_PAIR (test_stock_report.py + test_a_fast_core_stock_report.py)
  = 203.22 sec / 56 tests
RS (test_pattern_a_relative_strength_infrastructure.py)
  = 단일 테스트 >= 120초 관측, 파일 전체 실행 수십 분 이상 지속(비정상)
```

이번 사이클에서 직접 실측한 Before 값(정적 분석 후 대상 파일만 개별 실측,
Full Suite는 재실행하지 않음):

```
RS 파일 전체 실행 (수정 전 구조로 1회 실측)
  단일 slow full-universe 성격 테스트: 175.26초 (수정 후에도 동일하게 slow로 보존됨 — 6번 참고)
  negative test 각각이 별도로 2,528종목 재스캔 (13개 테스트 × 수십~백여 초 누적)

Foreign Flow 파일 전체 실행 (수정 전 구조로 1회 실측)
  = 364.25 sec (0:06:04), 13 passed
  base_scan_result fixture(module-scoped, 1회) setup = 179.54초
  test_live_validation_runner(별도 full scan) = 179.63초 — 완전 중복

Investability 파일 tests_scanner_candidate_summary_breakdown 단독
  = 무제한(limit=None) full scan 1회 (canonical summary와 100% 동일 값 중복 확인)
```

## 3. Test classification

- LEVEL 1 (UNIT/FAST): pure function, synthetic/소수 row, tmp_path, network 없음.
- LEVEL 2 (FAST INTEGRATION): 실제 production code path, 소수 ticker(예:
  `scan_pattern_a_universe(target_tickers=[...])`), network 없음, Full Universe
  없음.
- LEVEL 3 (FULL UNIVERSE / SLOW VALIDATION): 2,528 COMMON 전수, large
  historical replay — `@pytest.mark.slow` 필수, normal suite에서 제외.

## 4. 발견된 P0/P1/P2

```
TOTAL_TEST_FILES = 78
AUDITED_TEST_FILES = 78 (grep 기반 전수 조사: scan_pattern_a_universe,
  generate_stock_report, run_*validation, shutil.copytree 호출 패턴 검색)

P0_FOUND = 1
  - tests/test_pattern_a_relative_strength_infrastructure.py:
    negative test 13개가 각각 2,528종목 Full Universe Scan을 반복.

P1_FOUND = 3
  - tests/test_pattern_a_foreign_flow_infrastructure.py:
    test_live_validation_runner가 이미 재사용 중인 base_scan_result와 별개로
    추가 Full Universe Scan을 발생.
  - tests/test_pattern_a_investability_integration.py:
    test_scanner_candidate_summary_breakdown이 이미 canonical
    integration_summary에 존재하는 값을 얻기 위해 limit=None 전체 스캔을
    별도로 재실행.
  - tests/test_stock_report.py, test_a_fast_core_stock_report.py,
    test_pattern_a_fast_stock_report.py, test_pattern_a_fast_weekly_close.py:
    동일 (ticker, as_of, repo_root, save_artifacts=False) 조합으로
    generate_stock_report()를 여러 read-only test가 반복 호출.

P2_FOUND = 1
  - tests/test_pattern_a_foreign_flow_infrastructure.py: base_scan_result
    (module-scoped fixture)가 normal suite에서 실제 2,528종목 Full Universe
    Scan을 1회 수행해 약 178초 소요. 이미 5개 negative test가 재사용하는
    올바른 "1번 계산 → 여러 test 검증" 패턴이라 삭제/축소 대상은 아니지만,
    실행 시간 자체는 Remaining Performance Debt로 분류한다.
    ACTION = DEFERRED_AFTER_FULL_SUITE_MEASUREMENT (사용자가 Normal Full
    Suite를 실측한 뒤 우선순위 재검토).

P3_REPORTED = 1
  - tests/test_full_universe_scanner.py: scan_pattern_a_universe를 여러 번
    호출하지만 synthetic 4-COMMON universe(mock_scanner_env)만 사용해 실행
    시간이 이미 4초 수준(실측)이다. 심각한 문제가 아니라는 §17 사전 판단이
    실측으로 확인됨 — 수정하지 않음. (warning volume 등 다른 P3 항목은
    9번 Future recommendations 참고.)
```

## 5. 수정 내용

### 5.1 RS (P0) — Runner 구조 분리

`src/trend_scanner/validation/pattern_a_relative_strength_infrastructure.py`를
`prepare_relative_strength_validation_context()` + `evaluate_relative_strength_gates()`
+ `run_relative_strength_validation()` 3단계로 분리했다.

- `prepare_relative_strength_validation_context(as_of, repo_root, output_dir,
  doc_output_path, target_tickers=None, target_markets=None, limit=None)`:
  Oracle/Universe 로드 + Full Universe Scanner 실행까지 담당. `target_tickers`
  등은 `scan_pattern_a_universe()`로 그대로 전달되는 subset filter로,
  프로덕션 경로(운영 스크립트)에서는 전달하지 않아 기존 동작이 그대로
  유지된다. Foreign Flow oracle CSV(`df_flow_oracle`)도 이제 이 단계에서
  1회 로드되어 context에 담긴다(이전에는 Gate 1 평가 시점에 매번 파일을
  다시 읽었다 — evaluate가 PURE하도록 개선).
- `evaluate_relative_strength_gates(context)`: 이미 준비된 context만으로
  Gate 1~10을 판정하는 순수 함수. Full Universe Scanner를 호출하지 않는다.
- `run_relative_strength_validation(...)`: 기존 public API/behavior를 그대로
  유지한다 — 내부적으로 위 두 함수를 호출한 뒤 CSV/JSON/MD 산출물을 기록한다.
  Production/manual validation 스크립트는 변경 없이 계속 동작한다.

**정합성 검증(§38 Gate semantics parity)**: 분리 전/후 동일 실제 production
데이터(2026-08-14, 2,528종목 실제 scan)로 `evaluate_relative_strength_gates()`를
1회 실행해, 이미 frozen된
`artifacts/relative_strength/pattern_a_relative_strength_summary_20260814.json`의
`gates` dict(10개 Gate의 `passed` + 모든 `details` 카운터)와 완전히 diff했다 —
**TOTAL MISMATCHES: 0**. verdict도 `HOLD_RELATIVE_STRENGTH_INFRA`로 동일.

`tests/test_pattern_a_relative_strength_infrastructure.py`를 재작성했다:

- `rs_subset_context` (module-scoped fixture): 실제 production 코드 경로로
  종목 3개(`001540`, `003100`, `007390` — 실제 2026-08-14 oracle에서
  candidate_state=="candidate" AND investability_status=="INVESTABLE"인
  실제 종목)만 `target_tickers`로 스캔한 real context. 파일 전체에서
  Full Universe Scanner를 정확히 1회(사실상 subset이라 1초 미만)만 호출한다.
- `rs_clean_context` (function-scoped fixture): 위 context의 oracle
  DataFrame들을 동일 3종목으로만 필터링해 모든 mismatch counter가 0인
  깨끗한 기준선을 만든다. 매 test마다 새 DataFrame 복사본을 받으므로
  mutation이 다른 test로 새지 않는다(§9/§34).
  - **회귀 가드**: `test_clean_context_baseline_has_zero_mismatches`로
    이 기준선이 실제로 0인지 확인한다 — subset 크기 때문에
    `candidate_ticker_mismatches` 등이 애초부터 0이 아니면 아래 모든
    negative test의 discrimination이 무의미해지므로, 이 가드가 먼저
    깨져야 한다.
- 각 Gate negative test는 `rs_clean_context`를 `dataclasses.replace()` +
  DataFrame `.copy()` 후 특정 필드 하나만 mutate해서
  `evaluate_relative_strength_gates()`만 호출한다(`scan_pattern_a_universe()`
  재호출 없음). Gate 6(scan 출력 row 값 mutation)은 monkeypatch로 실제
  scanner를 다시 부르는 대신, 캐시된 `scan_res.rows`를
  `dataclasses.replace()`로 직접 mutate한다.
- Gate 7/8의 "sector source가 비어있어 fail-closed" negative test 2개는
  실제 production 상태(2026-08-14 시점 sector index source가 실제로 0-row)를
  그대로 재사용한다 — 별도 mutation이 필요 없는 이미 real한 negative case.
- **Full Universe 실제 검증은 삭제하지 않았다.** 기존
  `test_relative_strength_infrastructure_execution`을
  `test_relative_strength_full_universe_validation`으로 이름을 바꾸고
  `@pytest.mark.slow`를 부여해, 2,528종목 실제 scan + Gate 1~10 실제 평가를
  그대로 1회 수행한다(assertion 내용 동일).
- **Architecture Guard 추가(§48)**:
  `test_rs_gate_unit_tests_do_not_require_full_scan`이
  `scan_pattern_a_universe`를 monkeypatch로 "호출되면 AssertionError"로
  만든 뒤 `evaluate_relative_strength_gates()`를 호출해, 향후 누군가 Gate
  평가 로직 안에 다시 scanner 호출을 추가하는 회귀를 막는다.
- `test_mutation_tests_do_not_contaminate_canonical_artifacts`는
  `test_mutation_tests_do_not_touch_canonical_artifacts`로 이름을 바꿔,
  (이제는 시그니처가 바뀐) 두 gate6 negative test 함수를 직접 호출하는 대신
  공식 canonical CSV/JSON 파일 해시가 mutation 전후 불변임을 직접
  회귀 검증한다.

**Frozen hash**: 이번 사이클에서 `pattern_a_stage.py`/`pattern_a_score.py`
등 frozen 대상 production 파일은 전혀 수정하지 않았다 — `EXPECTED_FROZEN_HASHES`
갱신 없음 (`git diff --stat`에 `src/trend_scanner/patterns/` 관련 변경 없음).

**TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_01 (Major 1) 추가 수정**:
`test_relative_strength_full_universe_validation`(slow)이 애초에는
`prepare_relative_strength_validation_context()` + `evaluate_relative_strength_gates()`를
직접 호출해 "Full Universe Scan + Gate 평가"만 검증하고, public runner
`run_relative_strength_validation(...)`의 전체 orchestration(오라클 로드 ->
스캔 -> 평가 -> CSV/JSON/MD 산출물 기록까지)은 실제 production 데이터로
한 번도 실행되지 않는 coverage 축소가 있었다. 이 slow test를
`run_relative_strength_validation(...)`을 직접 호출하도록 수정해 복구했다
(`isolated_out_dir`/`isolated_doc_path`는 반드시 `tmp_path` 하위 — canonical
artifact 절대 미사용). 기존 Gate assertion에 더해 다음도 확인한다: result가
dict이고 `gates`/`verdict` 키 존재, `gates`가 정확히 10개, isolated output
artifact(CSV/분포 JSON/요약 JSON/MD) 실제 생성, canonical CSV/JSON 파일
해시가 실행 전후 불변. `prepare_relative_strength_validation_context()`와
`evaluate_relative_strength_gates()` 구조 자체(negative test들이 계속
`evaluate_relative_strength_gates()`만 호출하는 구조)는 그대로 유지했다 —
RS_NORMAL_FULL_UNIVERSE_SCAN_CALLS = 0은 변하지 않는다.

### 5.2 Foreign Flow (P1)

`tests/test_pattern_a_foreign_flow_infrastructure.py::test_live_validation_runner`에
`@pytest.mark.slow`를 부여했다. 이 test는 이미 5개 negative test가 재사용하는
`base_scan_result`(module-scoped, 1회 real full scan) fixture와 완전히
별개로 `run_foreign_flow_infrastructure_validation()`을 실제 repo_root로
호출해 추가 Full Universe Scan을 발생시키고 있었다. 이 test가 검증하는
Gate(1,2,5,6,7)는 이미 `flow_validation_summary`(canonical 요약 파일 기반)
test들이 커버하므로, "실제 live validator 경로가 isolated tmp 출력에서도
canonical artifact를 건드리지 않는다"는 이 test 고유의 나머지 가치만
slow로 격리해 보존했다. 삭제가 아니다 — `uv run pytest ... -m slow`로
계속 실행 가능하며 실제로 재실행해 PASS를 확인했다(179.27초).

`base_scan_result` fixture 자체(module scope, 5개 negative test가 재사용하는
1회 real full scan)는 그대로 두었다 — w.md §62의 "1번 계산 → 여러 test가
각각 invariant 검증"에 해당하는 이미 올바른 패턴이며, 이를 target_tickers
subset으로 추가 축소하려면 `run_foreign_flow_infrastructure_validation()`의
Gate 1 비교 로직(180행 전체 oracle과의 set-비교)이 subset과 안전하게
호환되는지 별도 검증이 필요해 이번 사이클 범위 밖으로 남겼다(§7 Remaining
Performance Debt 참고).

### 5.3 Investability (P1, FIX_01 Major 2)

`tests/test_pattern_a_investability_integration.py::test_scanner_candidate_summary_breakdown`가
`scan_pattern_a_universe(as_of=CANONICAL_AS_OF, limit=None)`로 2,528종목
전체를 재스캔해 `candidate_raw_count`(180)/`investable_count`(103) 등을
확인하고 있었다. 이 값은 이미 `integration_summary`(canonical JSON, 파일이
있으면 그대로 읽고 없으면 1회만 계산하는 module-scoped fixture)에 동일하게
존재함을 확인(`candidate_count=180`,
`investability_breakdown={investable_count:103, filtered_market_cap_count:42,
filtered_liquidity_count:31, data_unavailable_count:4}`)하고, 이 fixture를
재사용하도록 test를 다시 작성했다 — 별도 Full Universe Scan 없이 동일
invariant를 검증한다.

**후속 리뷰 지적(Major 2)**: 위 개선은 "canonical JSON에 이미 존재하는 값을
다시 assert"하는 구조가 되어, "실제 scanner가 candidate/investability
breakdown을 올바르게 집계하는가"라는 원래의 scanner aggregation coverage가
사라졌다는 지적이 있었다. 이를 두 단계로 복구했다.

1. `test_scanner_candidate_summary_breakdown`을
   `test_canonical_candidate_summary_breakdown`으로 이름을 바꿔, 이 test가
   canonical Phase 10 integration summary의 내용(180/103/42/31/4)을
   검증하는 것이며 scanner 자체의 집계 검증이 아님을 명확히 했다(assertion
   내용은 변경 없음).
2. `tests/test_full_universe_scanner.py`에
   `test_summary_candidate_investability_breakdown_aggregation`을 신규
   추가했다. 이미 이 파일이 쓰는 `mock_scanner_env`(synthetic 4-COMMON
   universe, 실제 production `scan_pattern_a_universe()` 코드 경로를 그대로
   통과)로 스캔한 뒤, expected count를 **hardcoded 숫자가 아니라 `res.rows`의
   실제 `candidate_state`/`investability_status` 값으로부터 계산**해서
   `summary.candidate_raw_count`/`candidate_investable_count`/
   `candidate_filtered_market_cap_count`/`candidate_filtered_liquidity_count`/
   `candidate_data_unavailable_count`와 비교한다("summary가 rows를 제대로
   aggregate하는가"를 검증 — summary hardcoded vs summary hardcoded 비교가
   되지 않도록 함). 2,528종목 Full Universe Scan은 이 test에서도 사용하지
   않는다(synthetic 4종목).

**TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_FIX_02 (Major 1) 추가 수정**: 위
`test_summary_candidate_investability_breakdown_aggregation`은 구조 자체는
맞았지만, 기존 `mock_scanner_env`(005930/000660만 CANDIDATE, 둘 다
INVESTABLE)에서는 `candidate_filtered_market_cap_count`/
`candidate_filtered_liquidity_count`/`candidate_data_unavailable_count` 세
필드가 실제로 항상 0이라 해당 assertion들이 사실상 `0 == 0`만 검증하고
있었다. 이를 전용 fixture `mock_scanner_investability_breakdown_env`로
복구했다:

- `005930`(canonical market cap snapshot 기준 시가총액 약 1,604조원, 충분한
  synthetic 거래대금) → `INVESTABLE`
- `014470`(canonical snapshot 기준 실제 시가총액 약 598.7억원 — 1,000억원
  미만) → `FILTERED_MARKET_CAP`
- `000660`(canonical snapshot 기준 시가총액 약 1,201조원이나, synthetic
  daily의 `trading_value`를 0.5억원으로 낮춤 — 3억원 미만) →
  `FILTERED_LIQUIDITY`
- `701001`(canonical market cap snapshot에 존재하지 않는 가상 종목 코드,
  단 Pattern A candidate 판정에 필요한 48개월+ 이력은 충분) →
  `DATA_UNAVAILABLE`

네 ticker 모두 scan 결과 row를 테스트 코드에서 직접 mutate하지 않고, scanner
입력(synthetic OHLCV + 실제 canonical market cap 값)만 조정해 production
classification 코드가 스스로 해당 status를 생성하도록 구성했다(실측 확인
완료). 신규 test
`test_summary_candidate_investability_breakdown_all_branches`가 4개 branch
모두 `>= 1`임을 먼저 assert한 뒤 summary aggregation을 검증하고, 대표
ticker별 `investability_status`도 직접 확인한다.

`SCANNER_SUMMARY_AGGREGATION_COVERAGE = FULLY_RESTORED`

기존 `test_summary_candidate_investability_breakdown_aggregation`(공유
`mock_scanner_env` 기반)과 `test_canonical_candidate_summary_breakdown`은
변경 없이 그대로 유지된다.

### 5.4 Stock Report 반복 생성 (P1)

4개 파일에서 동일 (ticker, as_of, repo_root=REPO_ROOT, save_artifacts=False)
조합으로 `generate_stock_report()`를 반복 호출하던 read-only test들을
module-scoped fixture로 통합했다. monkeypatch로 내부 동작을 바꾸거나
(`resolve_instrument_metadata` 등), `report` 객체를 직접 검증하는 게 아니라
"두 번 독립 호출한 결과가 동일한지"를 검증하는 결정론 테스트, tmp_path로
격리된 테스트는 fixture를 사용하지 않고 기존처럼 독립 호출을 유지했다(§15).

```
tests/test_stock_report.py
  report_001540_20260814 fixture 도입, 9개 read-only test가 재사용
  (test_stock_report_deterministic_output은 의도적으로 제외 — 독립 호출 자체가 검증 대상)

tests/test_a_fast_core_stock_report.py
  report_005930_20260814 fixture 도입, 5개 read-only test가 재사용
  (monkeypatch가 있는 3개 test는 fixture를 쓰지 않고 그대로 독립 호출 유지)

tests/test_pattern_a_fast_stock_report.py
  report_001540_20260814 fixture 도입, 8개 read-only test가 재사용

tests/test_pattern_a_fast_weekly_close.py
  report_420770_20260814 fixture 도입, 6개 read-only test가 재사용
```

## 6. slow marker 정책

`pyproject.toml`의 marker 설명을 특정 과거 테스트("대형주 40 전체 재실행 및
전수 PIT 가로채기 검증")에 국한되지 않도록 일반화했다.

```
integration: 실제 외부 API/network(예: PyKRX)를 호출한다. 기본 실행에서 제외되며 `-m integration`으로만 실행한다.
slow: 로컬 대용량 데이터, 2,528종목 Full Universe Scan, 장시간 historical replay 등 기본 개발 루프에서 제외하는 장시간 테스트. 기본 실행에서 제외되며 `-m slow`로만 실행한다.
```

`addopts = "-m 'not integration and not slow'"`는 기존 그대로 유지했다.

새로 `@pytest.mark.slow`가 부여된 test:

```
tests/test_pattern_a_relative_strength_infrastructure.py::test_relative_strength_full_universe_validation
  (기존 test_relative_strength_infrastructure_execution의 개명 + slow 부여, MOVED_TO_SLOW)
tests/test_pattern_a_foreign_flow_infrastructure.py::test_live_validation_runner
  (MOVED_TO_SLOW)
```

## 7. After timings (실측)

```
RS_NORMAL (test_pattern_a_relative_strength_infrastructure.py, -m "not slow and not integration")
  26 passed, 1 deselected, 2.46~2.51초
  (TARGET <= 30초, HARD CEILING <= 60초 — 통과. 이전: 단일 테스트조차 120초 이상)

  AFTER_NORMAL_RS_FULL_UNIVERSE_SCAN_CALLS = 0 (2,528종목 전수 scan 없음)
  AFTER_NORMAL_RS_SUBSET_SCAN_CALLS = 4 (정적 카운트 — 이전 완료 보고의
    "= 1"은 부정확했음, FIX_01 Minor 2로 정정):
    1) `rs_subset_context` module-scoped fixture — `target_tickers`로 3종목
       스캔, 파일 전체에서 1회만 실행되고 여러 test가 결과를 공유
    2) `test_future_sector_mapping_leakage_negative_test` — `target_tickers=["005930"]` 1종목 단독 스캔
    3) `test_missing_effective_date_column_rejected` — `target_tickers=["005930"]` 1종목 단독 스캔
    4) `test_mutation_tests_do_not_touch_canonical_artifacts` — 공유 fixture를
       쓰지 않고 `prepare_relative_strength_validation_context(target_tickers=[...3종목])`을
       직접 재호출(mutation 격리 목적)
    이 4개 모두 2,528종목이 아닌 1~3종목 subset이며, Full Universe Scan은
    0회로 유지된다.
  BEFORE_FULL_UNIVERSE_SCAN_CALLS_PER_RS_FILE = 13~15
    (§4 P0 대상 negative test 13개 각각 + 관련 회귀 test 호출 경로 포함,
    정적 감사 시점 counting)

RS_SLOW (test_relative_strength_full_universe_validation, -m slow, 단독 실행)
  1 passed, 175.26초(FIX_01 이전 구조) — FIX_01 이후 public runner
  `run_relative_strength_validation(...)` 직접 호출로 재실행한 결과는
  아래 "FIX_01 이후 실측"에 기록.
  (실제 2,528종목 Full Universe Scan + Gate 1~10 전부 real 실행 — 삭제되지 않았음)

FIX_01 이후 실측 (RS_SLOW, public runner 직접 호출로 수정된 뒤 재실행):
  1 passed, 175.91초 — public runner `run_relative_strength_validation()`이
  실제로 오라클 로드 -> Full Universe Scan -> Gate 1~10 평가 -> CSV/분포
  JSON/요약 JSON/MD를 `tmp_path`에 기록하는 전체 경로를 실행. isolated
  output artifact 4개 파일 존재 확인, canonical artifact(CSV/JSON) 해시
  실행 전후 불변 확인 — 모두 PASS.

  FIX_02: 위 test 안에서 Gate 7/8 False + verdict 검증 assertion 3줄이
  중복 작성되어 있던 것을 발견해 마지막 중복 블록만 제거했다(기능/semantics
  변경 없음). RS logic/path를 건드리지 않는 순수 정리라 slow test는
  재실행하지 않고 `--collect-only`로만 구문/import 확인했다.

Foreign_Flow_NORMAL (-m "not slow and not integration", V01 실측 — FIX_01에서
  이 파일은 수정도, 재실행도 하지 않았다(w.md §19). base_scan_result 잔존
  Full Universe Scan 1회는 P2 Remaining Performance Debt로 분류(8번 참고))
  12 passed, 1 deselected, 178.56초
  (이전 364.25초 — 51% 감소. base_scan_result의 1회 real full scan은 잔존, §5.2 근거)

Foreign_Flow_SLOW (test_live_validation_runner, -m slow, 단독 실행, V01 실측)
  1 passed, 179.27초 (정상 PASS 확인)

Investability_NORMAL (-m "not slow and not integration")
  13 passed, 0.66초 (V01 실측)
  (이전 test_scanner_candidate_summary_breakdown 단독으로 무제한 full scan 유발 — 사실상 즉시 실행 수준으로 개선)

FIX_01 이후: Investability + Full_Universe_Scanner 통합 재실행
  (uv run pytest tests/test_pattern_a_investability_integration.py
  tests/test_full_universe_scanner.py -m "not slow and not integration" --durations=20)
  26 passed, 4.51초 (Investability 13개 — `test_scanner_candidate_summary_breakdown`
  이 `test_canonical_candidate_summary_breakdown`으로 개명됨, assertion 동일
  + Full_Universe_Scanner 13개 — 신규 `test_summary_candidate_investability_breakdown_aggregation`
  1개 추가로 12->13). 2,528종목 Full Universe Scan = 0회, synthetic small
  universe만 사용.

FIX_02 이후: Investability + Full_Universe_Scanner 통합 재실행
  (동일 command, 신규 전용 fixture `mock_scanner_investability_breakdown_env` +
  신규 test `test_summary_candidate_investability_breakdown_all_branches`
  추가 후)
  27 passed, 4.72초 (Full_Universe_Scanner 13->14). 4개 candidate
  investability branch(INVESTABLE/FILTERED_MARKET_CAP/FILTERED_LIQUIDITY/
  DATA_UNAVAILABLE) 모두 실측 non-zero(각 1건)로 실제 production
  classification 경로에서 생성됨을 확인 — `SCANNER_SUMMARY_AGGREGATION_COVERAGE
  = FULLY_RESTORED`. 2,528종목 Full Universe Scan = 0회 유지.

Stock_Report_NORMAL (4개 파일 통합 실행, -m "not slow and not integration")
  77 passed, 171.63초

  개별 파일 단위 Before/After(각각 독립 실행, 동일 머신 비교 — 아래 수치는
  "4개 파일 통합 실행" 171.63초와는 별개의, 파일별 단독 실행 결과다):

  tests/test_stock_report.py: 68.06초 -> 42.48초 (18 tests, -37.6%)
  tests/test_pattern_a_fast_stock_report.py: 44.39초 -> 25.14초 (13 tests, -43.4%)
  tests/test_pattern_a_fast_weekly_close.py: 15.62초 -> 7.23초 (8 tests, -53.7%)
  tests/test_a_fast_core_stock_report.py: After = 100.33초 (38 tests).
    Before는 이번 사이클에서 재측정하지 않았다(2분 이상 소요되는 baseline
    재실행을 최소화하라는 지침에 따름) — 기존 공식 baseline
    "203.22초/56 tests"는 test_stock_report.py + test_a_fast_core_stock_report.py
    를 하나의 pytest 프로세스로 합쳐 실행한 결과이므로, 이번에 개별로 측정한
    수치(각 파일 단독 실행)와 단순 합산 비교는 apples-to-apples가 아니다.
    정확한 "페어를 하나의 명령으로 실행한" Before/After 재비교는 필요 시
    사용자 Full Suite 실행 시점에 확인 가능하다.

Full_Universe_Scanner (test_full_universe_scanner.py, 참고용 재확인, V01 실측)
  12 passed, 4.07초 (synthetic 4-COMMON universe, 원래도 문제 아니었음 —
  §4 P3). FIX_01에서 13개로 증가(위 "FIX_01 이후" 참고).
```

## 8. Remaining known expensive tests

```
PRIORITY: P2 (명확한 이득이 있으면 추후 고려)
FILE: tests/test_pattern_a_foreign_flow_infrastructure.py (base_scan_result fixture)
REASON: 여전히 module 당 1회 real Full Universe Scan(약 178초) 발생. 이미
  5개 test가 재사용하는 올바른 패턴이라 P1에서는 그대로 두었으나,
  target_tickers subset으로 더 줄이려면 run_foreign_flow_infrastructure_validation()의
  Gate 1 oracle 비교 로직이 subset과 호환되는지 별도 검증 필요.
RECOMMENDATION: 다음 성능 개선 라운드에서 RS와 동일한 prepare/evaluate 분리
  패턴 적용을 검토.

PRIORITY: P3 (보고만)
FILE: 전체 tests/ (§44)
REASON: Full Suite 기준 warning 1,122,695건 관측 기록(pandas/numpy
  FutureWarning/RuntimeWarning 다수, 이번 사이클에서도 test_a_fast_core_stock_report.py
  등에서 반복 관측). Runtime에 실질적 영향을 줄 가능성이 있음(OBSERVED/LIKELY).
RECOMMENDATION: warning root-cause 수정은 별도 작업. Production
  pandas/numpy semantics는 이번 사이클에서 변경하지 않았다.

PRIORITY: P3
FILE: tests/test_a_fast_core_stock_report.py 내 개별 테스트
  (예: test_a_fast_core_trade_history_matches_official_v02 25초,
  test_stock_report_market_cap_effective_date_pit 9초 등)
REASON: 서로 다른 ticker/as_of 또는 monkeypatch가 있어 §14/§15 원칙상
  fixture 공유 대상이 아니다(1회성 조합이거나 mutation-adjacent).
RECOMMENDATION: 현재 구조 유지. 억지로 fixture화하지 않는다.
```

## 9. Future recommendations

1. Foreign Flow의 `base_scan_result`를 RS와 동일한 prepare/evaluate 분리
   패턴으로 리팩토링하면 178초를 1초 미만으로 더 줄일 수 있다 — 단
   `run_foreign_flow_infrastructure_validation()`의 Gate 비교 로직이
   subset universe와 호환되는지 먼저 검증해야 한다(§8 P2).
2. 1,122,695건의 pandas/numpy warning(주로 `pct_change` `fill_method`
   deprecation, overflow encountered in scalar subtract)이 실제 CPU
   시간에 미치는 영향을 별도로 profiling해볼 가치가 있다 — 이번 범위
   밖으로 남긴다.
3. Normal Full Suite 실측은 사용자가 직접 진행한다(§29 정책). 이번
   사이클에서 확인된 개별 파일 개선분(RS/Foreign Flow/Investability/Stock
   Report 4개 파일)만으로도 66분 baseline 대비 상당한 시간이 줄었을
   것으로 예상되나, 정확한 전체 수치는 사용자의 Full Suite 실행 결과로
   확정한다.
