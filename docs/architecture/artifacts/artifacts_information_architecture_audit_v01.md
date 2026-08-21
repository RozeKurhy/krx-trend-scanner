artifacts_information_architecture_audit_v01.md

# Artifacts Information Architecture Audit V01

이 문서는 `artifacts/` 폴더 전체에 대한 AUDIT + DESIGN 문서다(STEP 1). 실제 `git mv`,
rename, 삭제, regeneration은 수행하지 않았다. 근거는 `find`/`rg`/`git log`를 통한
직접 조사이며, 판단이 불가능한 항목은 추측 대신 `UNKNOWN_REQUIRES_REVIEW`로
남기는 원칙으로 조사했다. STEP 1 FIX(Architect Review 반영)를 거친 현재,
`UNKNOWN_REQUIRES_REVIEW`/`BLOCKED`로 남은 항목은 없다 — §4/§18 전 항목이
확정 분류와 확정 이동 경로를 갖는다.

작업 시작 HEAD: `e4b53d6e88b73ab9a5d7d79e49e507c40fa88661`

===============================================================================
## 1. Executive Summary
===============================================================================

`artifacts/` 아래에는 총 **913개 파일**(png 464 / json 169 / csv 155 / md 122 /
parquet 3), **12개 top-level 폴더**가 있다. 그중 `pattern_a_fast/`(584 파일,
20개 하위 폴더)와 `stock_reports/`(216 파일)가 전체의 87%를 차지한다.

핵심 발견:

1. **production runtime이 "research" 이름의 폴더에서 파일을 직접 읽는다.**
   `src/trend_scanner/reporting/stock_report.py`와
   `src/trend_scanner/reporting/pattern_a_fast_report.py`가
   `artifacts/pattern_a_fast/research/pattern_a_fast_{score,stage}_prototype_v01.json`을
   **런타임에 직접 로드**한다. `research/`라는 이름만 보면 순수 연구 산출물처럼
   보이지만, 실제로는 CURRENT_PRODUCTION_EVIDENCE 2개 파일 + 순수 연구
   CSV/JSON 26개가 같은 레벨에 혼재해 있다. 이는 §6(w.md 작업 지시서)에서
   예상한 "폴더 이름과 실제 ownership 불일치"의 가장 명확한 사례다.
2. **`pattern_a_final_closure.py`/`pattern_a_investability_audit.py`가
   `artifacts/chart_review/`를 closure evidence로 직접 읽는다.** 이름만 보면
   research 산출물 같지만 실제로는 Pattern A Final Closure 감사 체인의
   일부다.
3. **`artifacts/pattern_a_fast/strategy_finalization_v01_corrected_pit/`는
   현재 base `strategy_finalization_v01/`와 byte-identical 중복**이고,
   `strategy_finalization_v01_legacy/`는 PIT 보정 이전(pre-fix) 값의 진짜
   historical 백업이다(diff로 직접 확인). Architect decision: canonical =
   `strategy_finalization_v01/`, `corrected_pit/` = REMOVE_DUPLICATE(STEP 2
   Phase E), `legacy/` = archive 유지(§19).
4. **6개 A FAST v0.2 계열 연구 산출물**(`entry_gate_v02a`, `coverage_hole_v02d`,
   `unavailable_v02c`, `weak_reversal_v02b`, `combined_exit_v01`,
   `architecture_v03`)은 repo 전체에서 docs/tests/src/scripts 어디에서도
   경로 참조가 발견되지 않았다 — 현재 A FAST Core V2 계약(`final_strategy_v02`)
   합성 이전의 연구 체크포인트로 판단되며 ARCHIVE_CANDIDATE.
5. **`artifacts/pattern_a_fast/fresh_oos_v03/`는 이미 문서 상
   `SUPERSEDED_HISTORICAL_PREREGISTRATION`으로 명시**되어 있고(
   `docs/patterns/pattern_a_fast/strategy/versions.md` §5), 어떤 코드/테스트도
   이 artifact JSON을 참조하지 않는다 — ARCHIVE_CANDIDATE로 가장 확실한 사례.
6. **frozen/hash 보호는 이미 명시적 sha256 중심으로 잘 정리되어 있다**
   (FIX_03에서 완료). 다만 그 hash들은 전부 **content identity**만 검증하며
   **path**는 어떤 hash에도 포함돼 있지 않다 — 즉 이동해도 hash 값은 그대로
   유효하지만, path를 하드코딩해 읽는 production/test 코드(§14/§15) 수만큼
   반드시 별도 path migration이 필요하다.
7. **`ground_truth/charts/`(240개 PNG)는 기존 canonical per-file sha256
   manifest가 없다는 finding은 유지하되, 이것이 이동 불가를 뜻하지는
   않는다.** STEP 2 이동 시 pre/post migration checksum snapshot(240개
   전체 relative path+size+sha256)으로 byte identity를 직접 증명하면
   된다 — 분류는 BLOCKED가 아니라 HIGH(§15/§21).

이번 STEP 1(FIX 포함)은 AUDIT + DESIGN만 수행했고 실제 이동/rename/삭제/
재생성은 0건이다. Architect Review에서 지적된 Major 3건/Minor 1건을 모두
반영했으며, `BLOCKED_MOVE_COUNT = 0`으로 확정해 STEP 2 실행 설계로
승격한다.

===============================================================================
## 2. Current Artifact Topology
===============================================================================

```
artifacts/                                   913 files, 12 top-level dirs
├── analysis/                                   3
├── cache_population/                           2
├── chart_review/                               3
├── flow/                                       6  (+ source/)
├── investability/                             10  (+ history/, source/)
│   ├── history/                                4  (+ normalized/ 26, source/ 26)
│   └── source/                                 2
├── pattern_a_fast/                           584  (20 하위 폴더, 아래 §7 상세)
├── pattern_a_final_closure/                     1
├── relative_strength/                           9  (+ source/)
├── scanner/                                     2
├── stage_v03_research/                          6
├── stage_v04_multi_year_research/              13
└── stock_reports/                             216  (20260814/ 108, archive/v0.1/20260814/ 108)
```

확장자 분포: png 464(대부분 pattern_a_fast 하위 blind-review/ground-truth
chart), json 169, csv 155, md 122(주로 stock_reports 개별 리포트 + A FAST
evaluation 요약), parquet 3(flow/relative_strength source 원본).

===============================================================================
## 3. Classification Rules
===============================================================================

w.md §5가 정의한 카테고리를 그대로 사용한다. 하나의 group이 여러 역할을
가지면 `Primary / Secondary`로 표기한다.

| 코드 | 의미 |
|---|---|
| CURRENT_PRODUCTION | 현재 production runtime이 직접 소비 |
| CURRENT_PRODUCTION_EVIDENCE | production 결과의 canonical 증빙(재계산 없이 신뢰되는 output) |
| CURRENT_VALIDATION | 현재 validation/closure 체인의 일부 |
| CURRENT_RESEARCH | 현재도 유효한 연구 결과(폐기 아님) |
| HISTORICAL_BASELINE | 공식 과거 버전 비교 기준(archive 아님) |
| SUPERSEDED | 현재 authority 아니고 다른 것으로 대체됨 |
| SOURCE_INPUT | 외부/캐시 원본 데이터 |
| GROUND_TRUTH | 사람이 만든 정답/라벨 데이터 |
| HUMAN_REVIEW | 사람이 직접 검토·입력한 원자료 |
| CLOSURE_EVIDENCE | Phase/Task 종료를 증빙하는 seal/manifest/audit |
| REPORT_OUTPUT | 최종 소비자용 리포트 산출물 |
| TEMPORARY_OR_DUPLICATE_CANDIDATE | 다른 canonical 파일과 내용이 중복 |
| UNKNOWN_REQUIRES_REVIEW | 판단 근거 불충분 |

Group 단위 조사 항목(각 group마다): current path / group 설명 / owning
domain·pattern / role(Primary/Secondary) / current authority 여부 /
production dependency / frozen 여부 / hash·seal·manifest 보호 / 코드·테스트·
docs·scripts 참조 여부 / proposed destination / move risk / 비고.

===============================================================================
## 4. Artifact Inventory
===============================================================================

파일 단위가 아니라 논리적 group 단위로 기록한다(w.md §5 허용). 전체
913개 파일이 아래 표의 group 중 하나에 속한다.

| # | Current Path | Files | Role | Owning Domain | Authority | Frozen/Hash | 참조처 |
|---|---|---|---|---|---|---|---|
| 1 | `analysis/` | 3 | CURRENT_RESEARCH | Pattern A (local stage filter audit) | 아니오 | 없음 | docs 1건 |
| 2 | `cache_population/` | 2 | CURRENT_VALIDATION(infra) | 공용 infra(캐시 적재 감사) | 아니오 | 없음 | scripts 1건 |
| 3 | `chart_review/` | 3 | **CLOSURE_EVIDENCE**/Primary, HUMAN_REVIEW/Secondary | Pattern A | **예(Final Closure 입력)** | 없음(hash 無) | src 3건(runtime 포함), docs 1건, scripts 1건 |
| 4 | `flow/` (+source/) | 6 | CURRENT_PRODUCTION_EVIDENCE | Pattern A (Foreign Flow, Phase11 CLOSED) | 예 | 없음 | src 4건, tests 1건, scripts 1건 |
| 5 | `investability/` top-level 10 | 10 | CURRENT_PRODUCTION_EVIDENCE | Pattern A (Investability, Phase10 CLOSED) | 예 | 없음(2개 canonical CSV는 tests/helpers/frozen_integrity.py에서 sha256) | src 6건, tests 다수, docs 다수 |
| 6 | `investability/history/` (+source/normalized, 56) | 56 | SOURCE_INPUT/Primary, CURRENT_VALIDATION/Secondary | Pattern A (Investability, KRX historical backfill) | 예 | **row-level sha256**(provenance CSV) | tests/test_krx_historical_market_cap_backfill.py |
| 7 | `investability/source/` | 2 | SOURCE_INPUT | Pattern A (Investability canonical PIT snapshot) | 예 | **explicit sha256**(FIX_03) | src(full_universe_scanner.py 런타임 로드), tests |
| 8 | `pattern_a_final_closure/` | 1 | CLOSURE_EVIDENCE | Pattern A | 예 | EXPECTED_FROZEN_HASHES(간접, source 파일 대상) | src(pattern_a_final_closure.py가 직접 write) |
| 9 | `relative_strength/` (+source/) | 9 | CURRENT_VALIDATION | Pattern A (RS, Phase12 `HOLD_RELATIVE_STRENGTH_INFRA`) | 예(HOLD 상태) | 없음 | src 3건, tests 2건 |
| 10 | `scanner/` | 2 | CURRENT_PRODUCTION_EVIDENCE | Pattern A (Full Universe Scan canonical output) | 예 | 없음 | src 1건, docs 다수, scripts 2건 |
| 11 | `stage_v03_research/` | 6 | CURRENT_VALIDATION/CURRENT_RESEARCH | Pattern A (Stage classifier 연구, 결정론적 재생성 가능) | 예(closed research) | 없음(deterministic regeneration test 존재) | src(stage_v03_research.py), tests |
| 12 | `stage_v04_multi_year_research/` | 13 | CURRENT_VALIDATION/CURRENT_RESEARCH | Pattern A (Stage classifier 다년도 연구, CLOSED) | 예(closed research) | 없음 | src(stage_v04_multi_year_research.py), tests |
| 13 | `stock_reports/20260814/` | 108 | REPORT_OUTPUT | 독립 Reporting 계층(Stock Report v0.2) | 예(current) | 없음 | src(stock_report.py), tests |
| 14 | `stock_reports/archive/v0.1/20260814/` | 108 | REPORT_OUTPUT/SUPERSEDED | 독립 Reporting 계층 | 아니오(v0.1, archived) | 없음 | docs 1건(contract_v01.md) |
| 15 | `pattern_a_fast/research/` — **score/stage prototype 2개** | 2 | **CURRENT_PRODUCTION** | Pattern A FAST | **예 — production runtime이 직접 로드** | 신규 explicit sha256(FIX_03, tests/helpers) | **src 2건(runtime), tests 다수** |
| 16 | `pattern_a_fast/research/` — 나머지 연구 CSV/JSON 26개 | 26 | CURRENT_RESEARCH | Pattern A FAST (Phase13H feature-role 연구) | 아니오(순수 연구) | 없음 | tests(연구 재현성 검증) |
| 17 | `pattern_a_fast/ground_truth/` (CSV 2 + charts 240 + json 2) | 244 | GROUND_TRUTH/HUMAN_REVIEW | Pattern A FAST (Phase13H) | 예(frozen) | **explicit sha256**(FIX_03, human_review/ground_truth_source) + per-chart 개별 hash 無(§15 참고) | tests(lead_time_failure_analysis 등) |
| 18 | `pattern_a_fast/human_anchors/` | 1 | GROUND_TRUTH | Pattern A FAST | 예 | 없음 | scripts(prepare_investable_oos) |
| 19 | `pattern_a_fast/oos/` (Phase13H 원본 OOS) | 94 | CLOSURE_EVIDENCE/HUMAN_REVIEW | Pattern A FAST | 예(frozen) | seal 기반(파일별) | tests(oos_ground_truth_seal, oos_evaluation) |
| 20 | `pattern_a_fast/investable_oos/` (Phase13J) | 155 | CLOSURE_EVIDENCE/HUMAN_REVIEW | Pattern A FAST | 예(frozen) | **explicit sha256 seal**(FROZEN_*_SHA256, 이미 FIX_03에서 재검증) | tests(preregistration/human_ground_truth/human_stage_freeze), src(evaluate_pattern_a_fast_oos_v01.py) |
| 21 | `pattern_a_fast/final_strategy_v01/` | 1 | **HISTORICAL_BASELINE** | Pattern A FAST (A FAST Core V1) | 예(공식 historical baseline, archive 아님) | 없음(explicit) | tests(strategy_finalization_provenance, final_strategy_v02_contract) |
| 22 | `pattern_a_fast/final_strategy_v02/` | 1 | **CURRENT_PRODUCTION_EVIDENCE** | Pattern A FAST (A FAST Core V2, 현재 공식 전략) | 예(current) | 없음 | tests(final_strategy_v02_contract), docs(versions.md) |
| 23 | `pattern_a_fast/strategy_finalization_v01/` | 4 | CURRENT_PRODUCTION_EVIDENCE(V1 재계산본, PIT 보정 후) | Pattern A FAST | 예(현재 base로 사용) | 없음 | tests(strategy_finalization_provenance) |
| 24 | `pattern_a_fast/strategy_finalization_v01_corrected_pit/` | 4 | **TEMPORARY_OR_DUPLICATE_CANDIDATE** | Pattern A FAST | 아니오(#23과 byte-identical) | 없음 | tests(strategy_finalization_provenance, **양쪽 경로를 모두 required로 열어 동일 provenance metadata를 각각 assert** — fallback이 아니라 이중 검증) |
| 25 | `pattern_a_fast/strategy_finalization_v01_legacy/` | 4 | **SUPERSEDED**(HISTORICAL_BASELINE 성격의 PIT-보정 이전 값) | Pattern A FAST | 아니오 | 없음 | 참조 없음(직접 검색 시 0건) |
| 26 | `pattern_a_fast/core_v02_reentry/` | 8 | CURRENT_PRODUCTION_EVIDENCE(V2 delta 근거) | Pattern A FAST | 예(V1→V2 재진입 규칙 변경의 직접 증거) | 없음 | docs(final_v02.md), tests(test_a_fast_core_stock_report.py가 trades.csv 로드) |
| 27 | `pattern_a_fast/progressed_downside_v01/` | 11 | CURRENT_RESEARCH(DEFERRED_RESEARCH) | Pattern A FAST | 예(공식 인용된 deferred research) | 없음 | docs(versions.md §4), tests(test_pattern_a_fast_progressed_downside_v01.py) |
| 28 | `pattern_a_fast/large_cap40_v01/` | 6 | CURRENT_RESEARCH | Pattern A FAST | 예(문서 인용) | 없음 | docs(large_cap40_entry_hypothesis_v01.md), tests |
| 29 | `pattern_a_fast/trading_policy_v01/` | 5 | CURRENT_RESEARCH | Pattern A FAST | 예(문서 인용) | 없음 | docs(prereg/trading_policy_entry_v01.md), tests |
| 30 | `pattern_a_fast/entry_gate_v02a/` | 3 | **SUPERSEDED(ARCHIVE_CANDIDATE)** | Pattern A FAST | 아니오 | 없음 | 참조 0건(docs/tests/src/scripts 전체 검색) |
| 31 | `pattern_a_fast/coverage_hole_v02d/` | 3 | **SUPERSEDED(ARCHIVE_CANDIDATE)** | Pattern A FAST | 아니오 | 없음 | 참조 0건 |
| 32 | `pattern_a_fast/unavailable_v02c/` | 3 | **SUPERSEDED(ARCHIVE_CANDIDATE)** | Pattern A FAST | 아니오 | 없음 | 참조 0건 |
| 33 | `pattern_a_fast/weak_reversal_v02b/` | 3 | **SUPERSEDED(ARCHIVE_CANDIDATE)** | Pattern A FAST | 아니오 | 없음 | 참조 0건 |
| 34 | `pattern_a_fast/combined_exit_v01/` | 4 | **SUPERSEDED(ARCHIVE_CANDIDATE)** | Pattern A FAST | 아니오 | 없음 | 참조 0건 |
| 35 | `pattern_a_fast/architecture_v03/` | 1 | **SUPERSEDED(ARCHIVE_CANDIDATE)** | Pattern A FAST | 아니오 | 없음 | 참조 0건 |
| 36 | `pattern_a_fast/fresh_oos_v03/` | 1 | **SUPERSEDED(ARCHIVE_CANDIDATE, 문서 명시)** | Pattern A FAST | 아니오(`docs/.../versions.md` §5가 명시적으로 `SUPERSEDED_HISTORICAL_PREREGISTRATION` 선언) | 없음 | 참조 0건(파트너 doc은 다른 test가 참조하지만 이 JSON 자체는 미참조) |

합계: 3+2+3+6+10+56+2+1+9+2+6+13+108+108+2+26+244+1+94+155+1+1+4+4+4+8+11+6+5+3+3+3+3+4+1+1 = **913** (전체 파일 수와 일치, 교차검증 완료).

===============================================================================
## 5. Current Authority Map
===============================================================================

| Pattern/축 | 현재 공식 상태 | Authority 파일/폴더 |
|---|---|---|
| Pattern A (Score/Stage/Candidate) | `FROZEN`/`KEEP_CURRENT_PRODUCTION` | 코드(`src/trend_scanner/patterns/*`)가 authority, artifacts는 evidence만 |
| Pattern A FAST (전략) | `FINAL_STRATEGY_FROZEN` (V2), V1은 `HISTORICAL_FROZEN_BASELINE` | `final_strategy_v02/`(current), `final_strategy_v01/`(historical baseline) |
| Investability (Phase10) | `CLOSED` | `investability/` top-level 10개 파일 + `investability/source/` 2개 canonical snapshot |
| Foreign Flow (Phase11) | `CLOSED` | `flow/` |
| Relative Strength (Phase12) | `HOLD_RELATIVE_STRENGTH_INFRA` | `relative_strength/` |
| Pattern A Final Closure | 10-gate 감사 결과(최신 실행 시점 기준) | `pattern_a_final_closure/pattern_a_final_closure.json` |
| Stock Report | v0.2 `CLOSED`, v0.1은 archive | `stock_reports/20260814/`(current), `stock_reports/archive/v0.1/`(archive) |
| Pattern A FAST 인간 검증(Phase13H/13J) | frozen(seal 기반) | `oos/`, `ground_truth/`, `investable_oos/` |

===============================================================================
## 6. Pattern A Audit
===============================================================================

Pattern A production evidence 6개 그룹으로 나뉜다: `scanner/`(canonical
Full Universe Scan 결과), `investability/`+`investability/source/`+
`investability/history/`(Phase10 evidence + KRX historical backfill),
`flow/`(Phase11), `relative_strength/`(Phase12, HOLD), `pattern_a_final_closure/`
(10-gate closure 감사 결과), `chart_review/`(인간 수동 차트 리뷰 — closure
체인의 입력).

`pattern_a_final_closure/pattern_a_final_closure.json`은 이름에 "closure"가
들어가지만 **archive 후보가 아니다** — `pattern_a_final_closure.py`가 매번
실행 시 이 파일을 새로 쓰는 현재 감사 결과물(재실행 가능한 evidence)이다.
w.md §7.1이 명시적으로 경고한 함정("closure라는 이름만 보고 archive 판단
금지")과 정확히 일치하는 사례이며, 이 audit에서 실제로 그렇게 처리했다.

`chart_review/`는 이름만 보면 순수 연구/QA 산출물처럼 보이지만
`pattern_a_final_closure.py`(line 207)와 `pattern_a_investability_audit.py`
(line 382)가 `pattern_a_candidate_manual_review_20260814.csv`를 **직접
읽는다** — CLOSURE_EVIDENCE + production dependency로 재분류.

`investability/history/`(56파일)는 `investability/source/`(2파일, canonical
PIT snapshot)와 **다른 역할**이다: `history/`는 22개 active + 4개 superseded
과거 시점 KRX 원본/정규화 스냅샷(row-level sha256으로 이미 보호), `source/`는
현재 production scanner가 `load_canonical_mcap_snapshot()`으로 매번 로드하는
2개의 PIT 시가총액 스냅샷(2025-01-31, 2026-08-14)이다. 두 폴더 모두
`investability/` 하위에 있지만 lifecycle이 다르므로 IA 설계에서 분리를
제안한다(§16).

===============================================================================
## 7. Pattern A FAST Audit
===============================================================================

`pattern_a_fast/`(584파일, 20개 하위 폴더)를 lifecycle 관점으로 재분류하면:

**A. Current Production Evidence(2 파일, 그러나 폴더 안에서 가장 중요)**
`research/pattern_a_fast_score_prototype_v01.json` +
`research/pattern_a_fast_stage_prototype_v01.json` — Stock Report/A FAST
Report 런타임이 직접 로드(§1 발견 1번). `research/`라는 이름 아래 있지만
실제로는 이 폴더에서 유일하게 "research"가 아니다.

**B. Current Research(약 26파일, `research/` 나머지)**
Phase13H feature-role 연구(monthly/weekly/daily timing feature matrix,
correlation, threshold candidate, lead-time summary 등). 순수 연구
재현성만 test로 검증된다.

**C. Human Review / Ground Truth / Closure Evidence(oos/, ground_truth/,
investable_oos/, human_anchors/ = 494파일)** Phase13H(oos, ground_truth)와
Phase13J(investable_oos)로 나뉘며, 모두 explicit sha256/seal로 보호된다
(FIX_03에서 6개 test 중 5개가 바로 이 영역).

**D. A FAST Core V1/V2 전략 계약(final_strategy_v01/, final_strategy_v02/,
strategy_finalization_v01*, core_v02_reentry/ = 21파일)**
`docs/patterns/pattern_a_fast/strategy/versions.md`가 공식 authority다.
V1은 `HISTORICAL_FROZEN_BASELINE`(archive 아님, 유지), V2는 현재 공식
전략. `strategy_finalization_v01_corrected_pit/`은 base와 byte-identical
중복(§1 발견 3), `strategy_finalization_v01_legacy/`는 PIT 보정 이전
진짜 historical 값(§19/§20 참고).

**E. 개별 연구 실험(progressed_downside_v01/, large_cap40_v01/,
trading_policy_v01/ = 22파일)** — 각각 docs에서 명시적으로 인용되는
CURRENT_RESEARCH.

**F. 참조되지 않는 V0.2 계열 연구 체크포인트(entry_gate_v02a/,
coverage_hole_v02d/, unavailable_v02c/, weak_reversal_v02b/,
combined_exit_v01/, architecture_v03/ = 17파일)** — repo 전체(docs/tests/
src/scripts) 어디에서도 artifact path 참조가 발견되지 않음. A FAST Core
V2 합성 이전 단계의 연구 이력으로 판단되며 ARCHIVE_CANDIDATE.

**G. 명시적으로 superseded된 preregistration(fresh_oos_v03/ = 1파일)** —
문서가 직접 `SUPERSEDED_HISTORICAL_PREREGISTRATION`이라고 선언.
ARCHIVE_CANDIDATE(가장 확실한 사례).

===============================================================================
## 8. Investability Audit
===============================================================================

Phase10 `CLOSED`. 현재 production contract: market cap >= 1,000억원, 20D
평균거래대금 >= 3억원(threshold 자체는 이번 audit에서 변경하지 않음).

역할 구분:
- threshold design/scenarios/scorecard(`threshold_design`, `scenarios`,
  `threshold_scorecard`, `threshold_summary`) = CURRENT_RESEARCH(threshold가
  왜 이 값인지의 연구 증거, production contract 자체는 아님)
- universe/candidates/integration/integration_summary/distribution/summary
  = CURRENT_PRODUCTION_EVIDENCE(Phase10 canonical 결과)
- `history/`(KRX 과거 시총 백필, 22 active+4 superseded) = SOURCE_INPUT,
  row-level sha256 보호
- `source/`(canonical PIT snapshot 2개) = SOURCE_INPUT, production
  runtime이 매번 로드, FIX_03에서 explicit sha256 신규 추가

design 산출물과 production evidence가 현재 같은 `investability/` 레벨에
평평하게 섞여 있다 — IA 설계에서 `production/`과 `research/`로 분리 제안.

===============================================================================
## 9. Foreign Flow Audit
===============================================================================

Phase11 `CLOSED`. `flow/`(6파일): features/distribution/summary(Pattern A
production evidence) + `source/`(원본 외국인 수급 csv/parquet/meta,
SOURCE_INPUT). 이름 자체(`pattern_a_foreign_flow_*`)가 이미 Pattern A
ownership을 명확히 표현하고 있어 재명명 불필요. OBV 등 향후 연구 아이디어는
이번 Task 범위 밖(w.md §7.5 명시).

===============================================================================
## 10. Relative Strength Audit
===============================================================================

Phase12 현재 verdict `HOLD_RELATIVE_STRENGTH_INFRA`(infra 존재, market-relative
RS 존재, sector RS 미해결). `relative_strength/`(9파일): features/
distribution/summary(infrastructure validation evidence, market-relative RS
포함) + `source/`(market index, sector index, sector mapping — 원본/메타).
Phase12를 "처음부터 다시 만드는" 방식으로 재해석하지 않았고, 현재 HOLD
상태 그대로 CURRENT_VALIDATION으로 유지 제안.

===============================================================================
## 11. Scanner / Analysis / Chart Review Audit
===============================================================================

- `scanner/`(2파일): canonical Full Universe Scan 결과(CSV+summary JSON).
  CURRENT_PRODUCTION_EVIDENCE, `pattern_a_investability_audit.py`/여러 docs가
  참조.
- `analysis/`(3파일): local stage filter 감사(전체/후보군 비교),
  `docs/patterns/pattern_a/validation/full_universe_stage_filter_audit_20260814.md`
  1건만 참조. CURRENT_RESEARCH, 낮은 위험.
- `chart_review/`(3파일): §6에서 다룬 대로 CLOSURE_EVIDENCE, HIGH risk(
  production/closure 코드 2곳이 하드코딩 경로로 직접 읽음).
- `cache_population/`(2파일): 캐시 적재 로그/품질 감사. Pattern에 종속되지
  않는 공용 infra 성격(`scripts/populate_krx_common_cache.py`가 유일한 참조).

===============================================================================
## 12. Stage Research Audit
===============================================================================

`stage_v03_research/`(6파일)와 `stage_v04_multi_year_research/`(13파일)는
각각 전용 validation 모듈(`src/trend_scanner/validation/stage_v03_research.py`,
`stage_v04_multi_year_research.py`)과 전용 test 파일을 가진 **결정론적으로
재생성 가능한** Stage 분류기 연구 증거다. git log 상 둘 다 "closure"
커밋으로 마무리되었다(CLOSED). 디렉터리 전체를 historical BASE와 byte
비교하는 방식은 (FIX_03에서 이미 확인한 것과 동일한 이유로) 부적절하며,
현재도 test가 "재생성 시 산출물이 결정론적으로 동일한가"를 검증하는
구조를 유지해야 한다 — v03은 `test_research_artifact_deterministic_regeneration`,
v04는 `test_deterministic_regeneration`/`test_same_snapshot_repeated_calculation_equality`로
둘 다 확인함(§21 Remaining Performance Debt와 연결된 영역이므로 이번
audit에서 그 test의 실행 방식 자체는 변경 대상이 아니다 — IA 이동 risk만
평가).

===============================================================================
## 13. Stock Report Audit
===============================================================================

```
stock_reports/
├── 20260814/           108 files (current, v0.2)
└── archive/v0.1/20260814/  108 files (superseded v0.1)
```

이미 current/archive/version-boundary가 잘 구분된 모범 사례(w.md §7.6
그대로 확인됨). `src/trend_scanner/reporting/stock_report.py`, 여러 test가
`stock_reports/`를 직접 참조하므로 HIGH risk. 향후 Web Stock Report Viewer가
이 경로를 소비할 가능성이 있어 path stability를 HIGH priority로 유지해야
한다(§21). `artifacts/reporting/stock_reports/`로의 이동은 "제안"만
가능하며 이번 STEP 1에서 실제 이동은 없다.

===============================================================================
## 14. Path Dependency Audit
===============================================================================

`rg "artifacts/"` 계열 검색을 `src/ tests/ scripts/ docs/` 전체에 대해
수행했다. 카테고리별 요약:

| 카테고리 | 대표 사례 | 개수(대략) |
|---|---|---|
| production runtime dependency | `stock_report.py`/`pattern_a_fast_report.py`(research/score,stage prototype), `full_universe_scanner.py`(investability/source, flow/source, relative_strength/source), `pattern_a_final_closure.py`(chart_review, EXPECTED_FROZEN_HASHES 대상 src 파일), `pattern_a_investability_audit.py`(chart_review) | 6개 파일, 다수 경로 |
| test dependency | `test_a_fast_core_stock_report.py`(core_v02_reentry/trades.csv), `test_strategy_finalization_provenance.py`, `test_pattern_a_fast_final_strategy_v02_contract.py`, `test_krx_historical_market_cap_backfill.py`, `test_full_universe_scanner.py`, `test_pattern_a_investability_*` 등 | 20개 이상 파일 |
| validation dependency | `pattern_a_investability_integration.py`, `pattern_a_relative_strength_infrastructure.py`, `pattern_a_foreign_flow_infrastructure.py` | 3개 |
| frozen-integrity dependency | `tests/helpers/frozen_integrity.py`(FIX_03에서 신설, investability/source 2개 + Pattern A source 4개 + evaluate/research/prepare script 6개 sha256) | 1개 파일, 13개 상수 |
| script output path | `scripts/evaluate_pattern_a_fast_*.py`(16개), `scripts/research_pattern_a_fast_*.py`(6개), `scripts/prepare_pattern_a_fast_*.py`(3개), `scripts/freeze_pattern_a_fast_*.py`(2개), `scripts/backfill_krx_historical_market_cap_v01.py`, `scripts/fetch_foreign_flow_20260814.py`, `scripts/populate_krx_common_cache.py` | 28개 이상 |
| script input path | `scripts/compare_pattern_a_fast_corrected_baseline.py`, `scripts/inspect_v02_evidence.py` 등 | 다수 |
| documentation link | `docs/patterns/pattern_a_fast/strategy/versions.md`, `final_v01.md`, `final_v02.md`, `docs/patterns/pattern_a/validation/*`, `docs/architecture/validation/test_suite_performance_audit_v01.md` 등 | 15개 이상 |
| manifest/seal path | `investable_oos`/`oos` 내부의 manifest/seal JSON이 자기 자신의 다른 파일(assets, charts)을 상대경로로 참조 | 다수(파일 내부 필드) |
| informational/comment only | `docs/roadmap.md`(scanner 언급) | 소수 |

**가장 중요한 발견**: `research/pattern_a_fast_score_prototype_v01.json`과
`stage_prototype_v01.json`은 유일하게 **production runtime dependency +
test dependency + frozen-integrity dependency**를 동시에 가진다. 이동 시
`src/trend_scanner/reporting/stock_report.py:941-942`,
`pattern_a_fast_report.py:78-79`, 그리고 여러 test 파일 전부를 갱신해야
하므로 STEP 2에서 최우선 검증 대상이다.

===============================================================================
## 15. Frozen / Hash / Seal / Manifest Audit
===============================================================================

`tests/helpers/frozen_integrity.py`(TEST_SUITE_PERFORMANCE_AUDIT_AND_REFACTOR_
FIX_03에서 신설)이 현재 explicit hash authority다:

- `PATTERN_A_EVALUATOR_SHA256`, `PATTERN_A_FEATURE_SET_SHA256` — Pattern A
  production source 2개(test-side, src에 authority 부재)
- `EVALUATE_PATTERN_A_FAST_OOS_V01_SHA256`,
  `RESEARCH_LEAD_TIME_FAILURE_SCRIPT_SHA256`,
  `RESEARCH_SCORE_STAGE_PROTOTYPE_SCRIPT_SHA256`,
  `PREPARE_INVESTABLE_OOS_SCRIPT_SHA256` — scripts 4개
- `SOURCE_MARKET_CAP_20250131_SHA256`, `SOURCE_MARKET_CAP_20260814_SHA256` —
  `investability/source/` canonical PIT snapshot 2개

`src/trend_scanner/validation/pattern_a_final_closure.py`의
`EXPECTED_FROZEN_HASHES`는 별도 authority이며 `pattern_a_score.py`/
`pattern_a_stage.py`/`historical_snapshot.py` 3개만 다룬다(재사용 원칙,
중복 생성 금지 — 이미 FIX_03에서 재사용 확인).

그 외 seal/manifest(모두 content-hash 기반, path는 언급하지 않음):
`investable_oos`의 4개 seal(pass_a_freeze, ground_truth, preregistration
+ 각 test 파일의 FROZEN_*_SHA256 상수), `oos`의 ground_truth_seal/
blindness_audit. `ground_truth/`의 남은 2개 JSON(`selection_manifest.json`,
`reserved_calibration_samples.json`)도 직접 확인했으나 hash 필드가 없다 —
즉 `ground_truth/charts/`(240개 PNG)는 **기존 canonical per-file SHA256
manifest가 없다**(이 finding 자체는 유지). 다만 기존 manifest 부재가 곧
relocation 불가를 뜻하지는 않는다: STEP 2에서 이동 직전/직후 임시
migration verification snapshot(relative path + size + sha256, 240개
전부)을 생성해 pre/post byte identity를 직접 증명하면 된다 — 이 snapshot은
verification 용도일 뿐 기존 ground-truth artifact에 새 manifest를
삽입하는 것이 아니다. 따라서 이 항목은 BLOCKED가 아니라 **HIGH +
migration checksum verification 필수**로 분류한다(§21).

**CONTENT IDENTITY vs PATH AUTHORITY**: 모든 sha256/seal은 content만
검증한다. path 자체를 authority contract의 일부로 사용하는 곳은 발견되지
않았다(즉 이동 자체가 hash 검증을 깨뜨리지는 않는다) — 단 §14에서 확인한
production/test/frozen-integrity dependency 코드들은 path 문자열을
하드코딩하므로, STEP 2에서 반드시 **그 코드들의 path 상수를 갱신**해야
frozen-integrity가 계속 통과한다. "hash가 같으므로 이동해도 안전"이라는
결론은 **코드 갱신을 전제로 할 때만** 성립한다.

===============================================================================
## 16. Proposed Canonical Artifact IA
===============================================================================

docs IA 철학(상위 영역 → Pattern/Domain → 역할)을 artifact lifecycle에 맞게
적용한다. docs와 달리 artifact는 "언제 계산됐는가"가 중요하므로 역할
레벨에 `production` / `validation` / `research` / `archive`를 명시적으로
둔다.

원칙:
1. Pattern A와 Pattern A FAST를 최상위에서 분리(docs와 동일).
2. 각 Pattern 아래 `production`(현재 authority가 직접 소비/생성),
   `validation`(closure/human-review/seal 체인), `research`(연구 산출물),
   `archive`(superseded)로 4분류.
3. Investability/Foreign Flow/Scanner는 Pattern A의 하위 confirmation
   axis이자 현재 CLOSED production evidence이므로
   `patterns/pattern_a/production/` 아래 각각 자기 이름의 폴더를 가진다
   (폴더 이름 자체가 이미 axis를 설명하므로 유지). **Relative Strength는
   여기 포함하지 않는다** — production code가 RS source/infrastructure를
   참조한다는 사실만으로 artifact lifecycle이 production-ready가 되는
   것은 아니다. 현재 Phase12 verdict는 `HOLD_RELATIVE_STRENGTH_INFRA`
   (Gate 7 Sector Mapping Contract, Gate 8 Sector RS Arithmetic Parity
   모두 unresolved, Final Closure 아님)이므로 PATH MUST EXPRESS
   AUTHORITY/LIFECYCLE 원칙에 따라 `patterns/pattern_a/validation/`
   아래 위치시킨다. Phase12 Final Closure 완료 후 별도 migration task로
   `validation/relative_strength/` → `production/relative_strength/`
   승격 가능(§9).
4. Reporting(Stock Report)은 Pattern에 종속되지 않는 독립 계층 — docs와
   동일하게 `reporting/`로 분리.
5. `chart_review/`/`analysis/`/`cache_population/`는 겉보기엔 비슷해
   보이지만 ownership이 서로 다르므로 하나로 묶지 않는다:
   `chart_review/`는 `pattern_a_final_closure.py`/
   `pattern_a_investability_audit.py`가 직접 읽는 Pattern A closure
   chain evidence이므로 `patterns/pattern_a/validation/chart_review/`로;
   `analysis/`는 Pattern A local stage filter 연구 산출물이므로
   `patterns/pattern_a/research/analysis/`로; `cache_population/`만
   특정 Pattern에 종속되지 않는 진짜 공용 infra이므로 `shared/`로
   이동한다.
6. `pattern_a_final_closure/`는 Pattern A의 `validation/closure/`로.

===============================================================================
## 17. Proposed Tree
===============================================================================

```
artifacts/
├── README.md                                (신규, Authority Index)
├── patterns/
│   ├── pattern_a/
│   │   ├── production/
│   │   │   ├── scanner/                     (← scanner/)
│   │   │   ├── investability/               (← investability/ top-level 10 + source/)
│   │   │   └── flow/                        (← flow/)
│   │   ├── validation/
│   │   │   ├── closure/                     (← pattern_a_final_closure/)
│   │   │   ├── chart_review/                (← chart_review/, closure chain evidence)
│   │   │   ├── investability_history/       (← investability/history/)
│   │   │   ├── relative_strength/           (← relative_strength/, Phase12 HOLD_RELATIVE_STRENGTH_INFRA — Final Closure 전까지 validation)
│   │   │   ├── stage_v03_research/          (← stage_v03_research/)
│   │   │   └── stage_v04_multi_year_research/ (← stage_v04_multi_year_research/)
│   │   └── research/
│   │       ├── analysis/                    (← analysis/, Pattern A local stage filter 연구)
│   │       └── investability_threshold_design/ (← investability/의 threshold_design·scenarios·scorecard·summary)
│   │
│   └── pattern_a_fast/
│       ├── production/
│       │   ├── contract_prototype/          (← research/의 score/stage prototype 2개만 — production dependency 명시)
│       │   ├── strategy_v01/                (← final_strategy_v01/, HISTORICAL_BASELINE 명시 유지)
│       │   ├── strategy_v02/                (← final_strategy_v02/)
│       │   └── strategy_finalization_v01/   (← strategy_finalization_v01/ = canonical. corrected_pit는 byte-identical duplicate로 REMOVE_DUPLICATE — §19)
│       ├── validation/
│       │   ├── oos/                         (← oos/)
│       │   ├── ground_truth/                (← ground_truth/)
│       │   ├── human_anchors/                (← human_anchors/)
│       │   └── investable_oos/              (← investable_oos/)
│       ├── research/
│       │   ├── feature_role/                (← research/의 나머지 26개 연구 산출물)
│       │   ├── core_v02_reentry/            (← core_v02_reentry/)
│       │   ├── progressed_downside_v01/     (← progressed_downside_v01/)
│       │   ├── large_cap40_v01/             (← large_cap40_v01/)
│       │   └── trading_policy_v01/          (← trading_policy_v01/)
│       └── archive/
│           ├── entry_gate_v02a/ coverage_hole_v02d/ unavailable_v02c/
│           │   weak_reversal_v02b/ combined_exit_v01/ architecture_v03/
│           ├── fresh_oos_v03/
│           └── strategy_finalization_v01_legacy/
│
├── reporting/
│   └── stock_reports/
│       ├── 20260814/                        (← stock_reports/20260814/)
│       └── archive/v0.1/20260814/           (← stock_reports/archive/v0.1/20260814/)
│
└── shared/
    └── cache_population/                    (← cache_population/, 유일한 진짜 공용 infra)

# strategies/ 는 이 트리의 노드가 아니다 — STEP 2에서 mkdir 대상이 아님.
# Julia Strategy 등 Pattern에 종속되지 않는 독립 전략의 첫 artifact가
# 생기는 시점에 별도 top-level로 실제 생성한다(docs/strategies/와 동일
# 명명 원칙). 그 전까지는 존재하지 않는 디렉터리다.
```

이 트리는 §10의 10개 질문에 답할 수 있다: Pattern A/Pattern A FAST
current production evidence는 각 `production/`, A FAST Core V1 baseline은
`pattern_a_fast/production/strategy_v01/`, validation evidence는 각
`validation/`, research는 각 `research/`, Phase12 HOLD는
`pattern_a/validation/relative_strength/`(PATH MUST EXPRESS
AUTHORITY/LIFECYCLE 원칙 — Final Closure 전까지는 production이 아니라
validation), superseded는 각 `archive/`, Stock Report current output은
`reporting/stock_reports/20260814/`. 향후 Julia Strategy는
`strategies/<name>/`(docs와 동일 원칙으로 별도 top-level 신설 제안,
빈 디렉터리는 Git이 유지하지 않으므로 첫 artifact가 생길 때 실제 생성),
Pattern B는 `patterns/pattern_b/`로 동일 4분류를 복제하면 확장 가능하다.

===============================================================================
## 18. Migration Table
===============================================================================

| Current Path | Role | Authority | Proposed Path | Risk | Path Dependencies | Action |
|---|---|---|---|---|---|---|
| `scanner/` | CURRENT_PRODUCTION_EVIDENCE | 예 | `patterns/pattern_a/production/scanner/` | MEDIUM | src 1, docs 다수 | MOVE |
| `investability/`(top-level 10) | CURRENT_PRODUCTION_EVIDENCE | 예 | `patterns/pattern_a/production/investability/` | HIGH | src 6+, tests 다수, docs 다수 | MOVE |
| `investability/source/` | SOURCE_INPUT | 예 | `patterns/pattern_a/production/investability/source/` | **HIGH** | src(full_universe_scanner.py 런타임), tests/helpers/frozen_integrity.py(hash 상수, path는 별도) | MOVE |
| `investability/history/` | SOURCE_INPUT | 예 | `patterns/pattern_a/validation/investability_history/` | MEDIUM | tests 1 | MOVE |
| `flow/` | CURRENT_PRODUCTION_EVIDENCE | 예 | `patterns/pattern_a/production/flow/` | HIGH | src 4, tests 1 | MOVE |
| `relative_strength/` | CURRENT_VALIDATION | 예(HOLD) | `patterns/pattern_a/validation/relative_strength/` | HIGH | src 3, tests 2 | MOVE(Phase12 Final Closure 후 별도 task로 production/ 승격 가능 — §9) |
| `pattern_a_final_closure/` | CLOSURE_EVIDENCE | 예 | `patterns/pattern_a/validation/closure/` | MEDIUM | src(pattern_a_final_closure.py가 write) | MOVE |
| `chart_review/` | CLOSURE_EVIDENCE | 예 | `patterns/pattern_a/validation/chart_review/` | **HIGH** | src 2(런타임 read), scripts 1 | MOVE |
| `analysis/` | CURRENT_RESEARCH | 아니오 | `patterns/pattern_a/research/analysis/` | LOW | docs 1 | MOVE |
| `cache_population/` | CURRENT_VALIDATION(infra) | 아니오 | `shared/cache_population/` | LOW | scripts 1 | MOVE |
| `stage_v03_research/` | CURRENT_VALIDATION | 예 | `patterns/pattern_a/validation/stage_v03_research/` | MEDIUM | src 1, tests(deterministic regen) | MOVE |
| `stage_v04_multi_year_research/` | CURRENT_VALIDATION | 예 | `patterns/pattern_a/validation/stage_v04_multi_year_research/` | MEDIUM | src 1, tests | MOVE |
| `pattern_a_fast/research/`(score/stage prototype 2개) | **CURRENT_PRODUCTION** | 예 | `patterns/pattern_a_fast/production/contract_prototype/` | **HIGH**(최우선 검증) | src 2(런타임), tests 다수, frozen_integrity.py | MOVE — STEP 2 1순위 |
| `pattern_a_fast/research/`(나머지 26개) | CURRENT_RESEARCH | 아니오 | `patterns/pattern_a_fast/research/feature_role/` | LOW | tests(재현성) | MOVE |
| `pattern_a_fast/ground_truth/` | GROUND_TRUTH | 예 | `patterns/pattern_a_fast/validation/ground_truth/` | HIGH | tests(sha256), frozen_integrity.py 無(직접 상수) | MOVE |
| `pattern_a_fast/human_anchors/` | GROUND_TRUTH | 예 | `patterns/pattern_a_fast/validation/human_anchors/` | LOW | scripts 1 | MOVE |
| `pattern_a_fast/oos/` | CLOSURE_EVIDENCE | 예 | `patterns/pattern_a_fast/validation/oos/` | HIGH | tests(seal) | MOVE |
| `pattern_a_fast/investable_oos/` | CLOSURE_EVIDENCE | 예 | `patterns/pattern_a_fast/validation/investable_oos/` | **HIGH** | tests(explicit sha256 seal 다수), src(evaluate_pattern_a_fast_oos_v01.py) | MOVE |
| `pattern_a_fast/final_strategy_v01/` | HISTORICAL_BASELINE | 예 | `patterns/pattern_a_fast/production/strategy_v01/` | HIGH | tests 2 | KEEP_AS_HISTORICAL_BASELINE (이동은 가능하나 삭제/archive 금지) |
| `pattern_a_fast/final_strategy_v02/` | CURRENT_PRODUCTION_EVIDENCE | 예 | `patterns/pattern_a_fast/production/strategy_v02/` | HIGH | tests 1, docs(versions.md) | MOVE |
| `pattern_a_fast/strategy_finalization_v01/` | CURRENT_PRODUCTION_EVIDENCE | 예 | `patterns/pattern_a_fast/production/strategy_finalization_v01/` | HIGH | tests(provenance) | MOVE |
| `pattern_a_fast/strategy_finalization_v01_corrected_pit/` | TEMPORARY_OR_DUPLICATE_CANDIDATE | 아니오 | (없음 — 삭제 대상) | MEDIUM | tests(provenance test가 두 경로 모두 required로 순회 — 제거 전 test를 canonical 1개 contract로 먼저 수정해야 함) | **REMOVE_DUPLICATE**(STEP 2 Phase E, §23 순서대로: identity 재확인 → test 수정 → green 확인 → 제거) |
| `pattern_a_fast/strategy_finalization_v01_legacy/` | SUPERSEDED | 아니오 | `patterns/pattern_a_fast/archive/strategy_finalization_v01_legacy/` | LOW | 참조 0건 | ARCHIVE_CANDIDATE |
| `pattern_a_fast/core_v02_reentry/` | CURRENT_PRODUCTION_EVIDENCE | 예 | `patterns/pattern_a_fast/research/core_v02_reentry/` | MEDIUM | docs 1, tests(trades.csv) | MOVE |
| `pattern_a_fast/progressed_downside_v01/` | CURRENT_RESEARCH(deferred) | 예 | `patterns/pattern_a_fast/research/progressed_downside_v01/` | LOW | docs 1, tests 1 | MOVE |
| `pattern_a_fast/large_cap40_v01/` | CURRENT_RESEARCH | 예 | `patterns/pattern_a_fast/research/large_cap40_v01/` | LOW | docs 1, tests 1 | MOVE |
| `pattern_a_fast/trading_policy_v01/` | CURRENT_RESEARCH | 예 | `patterns/pattern_a_fast/research/trading_policy_v01/` | LOW | docs 1, tests 1 | MOVE |
| `pattern_a_fast/entry_gate_v02a/` | SUPERSEDED | 아니오 | `patterns/pattern_a_fast/archive/entry_gate_v02a/` | LOW | 참조 0건 | ARCHIVE_CANDIDATE |
| `pattern_a_fast/coverage_hole_v02d/` | SUPERSEDED | 아니오 | `patterns/pattern_a_fast/archive/coverage_hole_v02d/` | LOW | 참조 0건 | ARCHIVE_CANDIDATE |
| `pattern_a_fast/unavailable_v02c/` | SUPERSEDED | 아니오 | `patterns/pattern_a_fast/archive/unavailable_v02c/` | LOW | 참조 0건 | ARCHIVE_CANDIDATE |
| `pattern_a_fast/weak_reversal_v02b/` | SUPERSEDED | 아니오 | `patterns/pattern_a_fast/archive/weak_reversal_v02b/` | LOW | 참조 0건 | ARCHIVE_CANDIDATE |
| `pattern_a_fast/combined_exit_v01/` | SUPERSEDED | 아니오 | `patterns/pattern_a_fast/archive/combined_exit_v01/` | LOW | 참조 0건 | ARCHIVE_CANDIDATE |
| `pattern_a_fast/architecture_v03/` | SUPERSEDED | 아니오 | `patterns/pattern_a_fast/archive/architecture_v03/` | LOW | 참조 0건 | ARCHIVE_CANDIDATE |
| `pattern_a_fast/fresh_oos_v03/` | SUPERSEDED(문서 명시) | 아니오 | `patterns/pattern_a_fast/archive/fresh_oos_v03/` | LOW | 참조 0건(JSON 자체) | ARCHIVE_CANDIDATE |
| `stock_reports/20260814/` | REPORT_OUTPUT | 예 | `reporting/stock_reports/20260814/` | **HIGH** | src, tests, 향후 Web Viewer | MOVE(가장 신중하게) |
| `stock_reports/archive/v0.1/` | REPORT_OUTPUT/SUPERSEDED | 아니오 | `reporting/stock_reports/archive/v0.1/` | MEDIUM | docs 1 | MOVE |

===============================================================================
## 19. Archive Candidates
===============================================================================

| Path | 이유 |
|---|---|
| `pattern_a_fast/entry_gate_v02a/` | repo 전체 참조 0건, A FAST V0.2 연구 체크포인트 |
| `pattern_a_fast/coverage_hole_v02d/` | 동일 |
| `pattern_a_fast/unavailable_v02c/` | 동일 |
| `pattern_a_fast/weak_reversal_v02b/` | 동일 |
| `pattern_a_fast/combined_exit_v01/` | 동일 |
| `pattern_a_fast/architecture_v03/` | 동일 |
| `pattern_a_fast/fresh_oos_v03/` | 문서(`versions.md` §5)가 직접 `SUPERSEDED_HISTORICAL_PREREGISTRATION` 선언, 참조 0건 |
| `pattern_a_fast/strategy_finalization_v01_legacy/` | PIT 보정 이전 값, diff로 pre-fix 상태와 byte-identical 확인, 참조 0건(historical 증빙 목적으로 archive 유지 — 완전 삭제 대상 아님) |

**`pattern_a_fast/strategy_finalization_v01_corrected_pit/`는 archive
후보가 아니다 — Architect decision: REMOVE_DUPLICATE.** base
`strategy_finalization_v01/`과 byte-identical하며(diff로 확인), 이
base가 canonical corrected V1 finalization이다.
`strategy_finalization_v01_legacy/`가 PIT 보정 이전 진짜 historical
값이므로, `corrected_pit/`는 git history가 이미 보존하는 중복 사본일
뿐 별도 historical archive로 보존할 이유가 없다. 다만 바로 삭제하지
않는다 — 현재
`test_strategy_finalization_provenance.py::test_provenance_consistency_across_artifacts`가
두 경로를 모두 필수로 순회하며 동일 provenance metadata를 assert하므로,
STEP 2 Phase E(§23) 순서(byte identity 재확인 → provenance parity
재확인 → 왜 두 경로를 요구하는지 확인 → canonical 확정 → test를
새 authority contract로 수정 → targeted test green → 그 후 제거)를
그대로 따른다.

===============================================================================
## 20. Historical Baselines That Must NOT Be Archived
===============================================================================

| Path | 이유 |
|---|---|
| `pattern_a_fast/final_strategy_v01/` | `docs/.../versions.md`가 명시적으로 `HISTORICAL_FROZEN_BASELINE`(공식 V1↔V2 비교 기준)로 선언, `test_pattern_a_fast_final_strategy_v02_contract.py::test_v01_frozen_baseline_preserved`가 존재 확인 |
| `stock_reports/archive/v0.1/20260814/` | 이미 정식 archive 위치에 있으나, "archive"라는 이름과 무관하게 v0.1 계약의 공식 historical 비교본으로 계속 유지되어야 함(단순 이동만 제안, 내용/이름 변경 없음) |
| `artifacts/investability/history/`의 SUPERSEDED_NON_REFERENCE_SOURCE 4건 | provenance 상 명시적으로 "superseded"라고 표시되어 있지만, 이는 각 시점의 대체 소스 존재를 뜻할 뿐 파일 자체는 KRX 원본 검증 체인(row-level sha256)의 일부이므로 archive 이동 대상이 아니라 `history/` 안에 그대로 유지 |

===============================================================================
## 21. High-Risk / Blocked Moves
===============================================================================

**HIGH:** (§18 표 기준 HIGH = 13 rows; 아래는 대표 그룹으로 묶은 것이며
이 목록의 항목 수와 13은 다른 숫자다 — 정확한 개별 row 집계는 §18/§24 참조)
- `pattern_a_fast/research/`의 score/stage prototype 2개 — production
  runtime(2개 src 파일) + 다수 test + frozen_integrity.py 동시 의존. STEP 2
  1순위 검증 대상.
- `investability/source/` — production runtime(full_universe_scanner.py)이
  `repo_root`로 매번 재계산 없이 로드.
- `chart_review/` — Final Closure 코드가 하드코딩 경로로 직접 read.
- `flow/`, `relative_strength/` — 다수 src 참조(단, `relative_strength/`는
  `validation/`로 이동 — 현재 HOLD 상태이므로 production 경로가 아님).
- `pattern_a_fast/ground_truth/`, `investable_oos/` — explicit sha256 seal
  다수, 각 test의 path 상수 갱신 필요.
- `pattern_a_fast/ground_truth/charts/`(240개) — 개별 asset별 canonical
  sha256 manifest가 발견되지 않는다는 finding은 유지하되(§15), 이 사실이
  곧 이동 불가를 뜻하지는 않는다. STEP 2 이동 시 반드시: 이동 전
  PRE_MOVE_ASSET_COUNT=240 + 각 파일의 relative path/size/sha256을
  임시 migration verification snapshot으로 계산 → `git mv` → 이동 후
  POST_MOVE_ASSET_COUNT=240 / SHA256_MISMATCH_COUNT=0 /
  MISSING_FILE_COUNT=0 / EXTRA_FILE_COUNT=0을 재계산해 증명. 이 snapshot은
  production artifact를 수정하지 않는 검증 전용 산출물이다.
- `stock_reports/20260814/` — 향후 Web Viewer 소비 가능성(§13).

**BLOCKED_MOVE_COUNT = 0.** `strategy_finalization_v01_corrected_pit/`는
"이동"이 아니라 §19의 Architect decision(REMOVE_DUPLICATE)에 따라
STEP 2 Phase E(§23)에서 canonical 단일화 후 제거 대상이며, 새로 발견된
blocker는 없다.

===============================================================================
## 22. Optional Future Filename Cleanup
===============================================================================

이번 STEP 1에서는 rename하지 않는다. 향후 경로 자체가 domain/pattern을
설명하게 되면 다음과 같은 단순화가 가능하다(`OPTIONAL_FUTURE_RENAME`):

| 현재 | 향후 제안(경로가 이미 의미를 주므로 접두사 생략) |
|---|---|
| `relative_strength/pattern_a_relative_strength_summary_20260814.json` | `.../relative_strength/summary_20260814.json` |
| `flow/pattern_a_foreign_flow_summary_20260814.json` | `.../flow/summary_20260814.json` |
| `investability/pattern_a_investability_summary_20260814.json` | `.../investability/summary_20260814.json` |
| `pattern_a_fast/research/pattern_a_fast_score_prototype_v01.json` | `.../contract_prototype/score_prototype_v01.json` |

DIRECTORY MOVE FIRST 원칙에 따라 STEP 2에서도 rename보다 이동을 우선하고,
위 표는 별도 후속(STEP 3+)에서만 검토한다.

===============================================================================
## 23. STEP 2 Reorganization Plan
===============================================================================

**Phase A — Authority Index 준비**
`artifacts/README.md` 작성 — Current Production Evidence / Current
Validation / Active Research / Reporting Outputs / Historical Baselines /
Archive / Naming-Lifecycle Rules 섹션.

**Phase B — HIGH risk production path migration**
Pattern A FAST contract prototype(score+stage 2개, `stock_report.py`/
`pattern_a_fast_report.py` 경로 갱신 포함) → Investability
source/current evidence → Chart Review → Foreign Flow → 기타
runtime-dependent current artifact. 각 move마다: `git mv` → path 참조
코드 갱신 → targeted test → content hash identity 검증.

**Phase C — Relative Strength**
`patterns/pattern_a/validation/relative_strength/`로 이동. Phase12 HOLD
상태 그대로 유지, 계산/validation verdict 변경 없음.

**Phase D — Ground Truth / OOS**
`ground_truth/charts/`(240개)는 이동 전/후 임시 SHA256 snapshot
comparison을 실행해 byte identity를 증명한다(PRE_MOVE_ASSET_COUNT=240,
이동 후 POST_MOVE_ASSET_COUNT=240 / SHA256_MISMATCH_COUNT=0 /
MISSING_FILE_COUNT=0 / EXTRA_FILE_COUNT=0 확인). BLOCKED 아님.

**Phase E — strategy_finalization duplicate normalization**
1) `strategy_finalization_v01/`와 `strategy_finalization_v01_corrected_pit/`
byte identity 재확인 → 2) provenance metadata parity 재확인 → 3)
`test_strategy_finalization_provenance.py`가 왜 두 경로를 모두 요구하는지
재확인 → 4) canonical path를 `strategy_finalization_v01/` 하나로 확정 →
5) 위 test를 새 authority contract(canonical 1개 + `archive/`의
`strategy_finalization_v01_legacy/`)에 맞게 수정 → 6) targeted test
green 확인 → 7) `strategy_finalization_v01_corrected_pit/` 제거(archive
이동이 아니라 삭제 — git history가 이미 duplication history를 보존하므로
동일 파일 집합을 별도 historical artifact로 보존할 필요 없음).

**Phase F — MEDIUM/LOW risk 일괄 이동**
scanner, analysis(→ `pattern_a/research/analysis/`), cache_population
(→ `shared/`), stage_v03/v04_research, A FAST research 계열, archive
후보 8개 그룹(entry_gate_v02a/coverage_hole_v02d/unavailable_v02c/
weak_reversal_v02b/combined_exit_v01/architecture_v03/fresh_oos_v03/
strategy_finalization_v01_legacy).

**Phase G — Stock Reports**
가장 마지막, 필요 시 별도 commit/task로 분리(Web Viewer 영향 재확인 후).

**Phase H — Final integrity**
repository 전역 stale artifact path 검색 → 관련 targeted test 실행 →
artifact 파일 수 reconciliation(913 유지 확인, corrected_pit 제거분
반영) → content hash 비교 → 의도치 않은 artifact content 변경 없음 확인.
Full Suite는 이번에도 사용자가 직접 실행하는 정책을 유지한다.

전체 완료 후 README/Roadmap refresh(이번 Task 범위 밖, w.md §26 순서
그대로 유지) → Julia Strategy → Phase12 Relative Strength Resume.

===============================================================================
## 24. Final Verdict
===============================================================================

**정확한 집계(§4 Artifact Inventory / §18 Migration Table을 single
source of truth로 기계적 재계산, 범위/추정 표현 없음).**

Classification counts — Primary Role 기준, 36 group 전수(§4):

| Primary Role | Count |
|---|---:|
| CURRENT_PRODUCTION_EVIDENCE | 6 |
| CURRENT_RESEARCH | 5 |
| CURRENT_VALIDATION | 4 |
| CLOSURE_EVIDENCE | 4 |
| SUPERSEDED | 8 |
| SOURCE_INPUT | 2 |
| REPORT_OUTPUT | 2 |
| GROUND_TRUTH | 2 |
| CURRENT_PRODUCTION | 1 |
| HISTORICAL_BASELINE | 1 |
| TEMPORARY_OR_DUPLICATE_CANDIDATE | 1 |
| **합계** | **36** |

Migration risk counts — 36 group 전수(§18):

| Risk | Count |
|---|---:|
| HIGH | 13 |
| MEDIUM | 8 |
| LOW | 15 |
| BLOCKED | **0** |
| **합계** | **36** |

ARTIFACTS_INVENTORY_STATUS = COMPLETE
AUTHORITY_CLASSIFICATION_STATUS = COMPLETE
PATH_DEPENDENCY_AUDIT_STATUS = COMPLETE
FROZEN_EVIDENCE_AUDIT_STATUS = COMPLETE
PROPOSED_IA_STATUS = READY_FOR_REORGANIZATION
STEP_2_REORGANIZATION_STATUS = READY
BLOCKED_MOVE_COUNT = 0
PRODUCTION_SEMANTICS_CHANGED = NO
ARTIFACT_CONTENT_CHANGED = NO
ARTIFACT_PATH_CHANGED = NO
