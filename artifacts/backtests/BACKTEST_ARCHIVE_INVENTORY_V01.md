# A FAST Core V2 NEG40 — 인증 백테스트 8회 보관 Inventory V01

단순 백테스트 5회와 현실적 포트폴리오 백테스트 3회의 인증 산출물을 Git에 보관한 기록이다. 윈도우별 권위 run 선택은 `docs/patterns/pattern_a_fast/strategy/FAST_CORE_V2_NEG40_WEAK_PROTECT_5_WINDOW_SYNTHESIS_V01.md`와 각 실제형 run의 `summary.json` 판정을 따른다.

- **파일 단위 목록:** `backtest_archive_inventory_v01.csv`. 경로, 분류, 크기, SHA-256, 보관 전 추적 여부가 들어 있다.
- **run 단위 요약:** `backtest_archive_runs_v01.csv`. 보관 전 상태, 누락 항목, 무결성 검증 방법과 결과가 들어 있다.
- **생성 방법:** `python scripts/analyze_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py inventory`

`artifacts/backtests/`는 `.gitignore` 대상이다. 그래서 목록에 있는 파일만 경로를 지정해 강제로 추가했다. 원본 값은 수정하지 않았다.

## run별 상태

| run | 판정 | 보관 경로 | 보관 전 상태 | 무결성 검증 | 누락 |
|---|---|---|---|---|---|
| 단순 P1 | `P1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS` | `p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/`, `p1_neg40_weak_protect_v01/diagnostics/unavailable_stage_12_v01/` | PARTIALLY_TRACKED (closure 9개만 추적) | 인증서 `source_raw_sha256_before`, `source_run_manifest_sha256_before` 일치 | 없음 |
| 단순 P2-1 | `P2_1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS` | `p2_1_neg40_weak_protect_v01/run_20260925_corrective_full_recert_v02/`, `p2_1_neg40_weak_protect_v01/preflight_raw_mcap_source_correction_v01/` | PARTIALLY_TRACKED (closure 7개만 추적) | 인증서 `source_sha256_before` 일치 | soft-event 파일 없음(선택 run에 생성되지 않음) |
| 단순 P2-2 | `COMPLETE` / aggregate reconciliation PASS | `p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/`, `p2_2_neg40_weak_protect_v01/lifecycle_settlement_evidence_v01.json` | LOCAL_ONLY | 파일 SHA 기록 없음 → CONTROL 집계가 5-window synthesis와 정확히 일치 | 없음 |
| 단순 P3-1 | `P3_1_REPLAY_PASS` | `p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/` | LOCAL_ONLY | 같은 방식(synthesis 집계 재현) | 없음 |
| 단순 P3-2 | `P3_2_REPLAY_PASS` | `p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/` | LOCAL_ONLY | synthesis 집계 재현, `p3_2_summary.json` SHA가 실제형 P3-2에 기록된 값과 일치 | 없음 |
| 실제형 P2-1 | `P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED` | `p2_1_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/` | LOCAL_ONLY | CONTROL 건수 재현, `frozen_source_hashes_sha256` 3개 일치 | `final_report.md`, `run_manifest.json`(`comparison_report.md`, `execution_contract.json`이 대응 문서) |
| 실제형 P2-2 | `P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED` | `p2_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/` | LOCAL_ONLY | CONTROL 건수 재현 | 같음 |
| 실제형 P3-2 | `P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED` | `p3_2_neg40_weak_protect_v01/run_20260926_realistic_mcap1t_worker10_v01/` | LOCAL_ONLY | CONTROL 건수 재현(eligible 405, filled 228, 청산 207, 현금 스킵 177) | 없음 |

- 보관 전 `ALREADY_PUSHED`인 run은 없었다.
- **P1·P2-1 단순 run:** 인증 closure 하위 폴더만 이미 추적되고 있었다. 이번에 그 기반이 된 원천 raw run과 보조 증거만 추가했다. 이미 추적된 파일은 변경이 없었다.
- **단순 run의 최종 보고서:** run 폴더 밖의 5-window synthesis 문서가 최종 보고서 역할을 한다.

## 보관하지 않은 폴더

같은 윈도우 폴더의 아래 run은 synthesis 문서가 대체(superseded)되었거나 CHECK_REQUIRED로 분류한 것이다. 인증 권위가 아니어서 보관하지 않았다.

- P2-1: `run_20260923/`, `run_20260924_cutoff_contract_recert_v01/`, `run_20260925_corrective_recert_v01/`, `run_20260925_float_tol_01pp_v01/`, `run_20260925_control_agg_diag_v01/`
  - 빈 폴더 `run_20260925_control_agg_recheck_v01/`, `run_20260925_successor_final_contract_v01/`도 제외했다.
- P2-2: `run_20260923/`
- P3-1: `run_20260924_single_window_v01/`, `run_20260925_corrective_replay_v01/`
- P3-2: `run_20260925_p3_2_worker10_artifact_first_v01/`

## 분류 기준

각 파일은 `backtest_archive_inventory_v01.csv`의 `category` 열에 아래 기준으로 분류했다.

- **보고서·요약·실행 기록:** 최종 보고서(`*.md`), 요약(`summary*`), manifest/실행 계약, 인증서, preflight·검증(benchmark, preflight, failure, 감사 JSON)
- **원장:** CONTROL 원장, Candidate 원장, paired·matched·identity 감사
- **실행 흔적:** lifecycle·soft-event, 포트폴리오 이벤트·체결·스킵, 일별 자산
- **감사 자료:** PIT 시총 감사, 평가 carry·gap 감사, 생존·제외·identity 감사

임시 cache, bytecode, OS 파일은 포함하지 않았다. 50MB를 넘는 파일은 없다.
