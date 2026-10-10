# FAST Core V2 Lifecycle Prefix Invariance Fix V01

- 작성일: 2026-10-10 KST
- 작업 ID: `FAST_CORE_V2_LIFECYCLE_PREFIX_INVARIANCE_FIX_V01`
- 최종 판정: `FAST_CORE_V2_LIFECYCLE_PREFIX_INVARIANCE_FIX_V01_PASS`
- 검토 경계: 지시서 Step 5까지 완료. P1/P2-1 재실행, 5-window synthesis, realistic portfolio, 공식 전략 변경/승격은 실행하지 않았어.

## 1. 원인과 수정

기존 구현은 진입 후 백테스트 cutoff까지의 월별 snapshot 전체를 훑어 `NORMAL_EARLY_TREND_HANDOFF` 여부를 먼저 정했어. 먼 미래에 direct handoff가 한 번이라도 관측되면, 그 결과가 과거에 이미 발생한 Exit 3/Exit 4 조건에도 소급 적용될 수 있었어. 그 결과 기존 거래의 청산일·수익률이 cutoff 연장에 따라 바뀌고, 그 거래가 보유 중인 것으로 잘못 남아 재진입 기회도 사라졌어.

`pattern_a_fast_core_v02_reentry.py`에 날짜순 lifecycle state machine을 추가했어. 관측된 월별 stage와 점수만 사용해 lifecycle, direct handoff, Exit 3/Exit 4를 순차적으로 판단하고, 청산 신호가 확정되면 그 거래의 미래 snapshot은 더 이상 반영하지 않아. 거래별 effective trading date도 사용해 Loss Guard 이후의 lifecycle 이벤트가 결과에 들어오지 않게 했어. 기존 진입·Loss Guard·Exit 3/4 기준·재진입 정책·비용·달력·PIT·영구 제외 규칙은 유지했어.

변경 파일:

- `src/trend_scanner/validation/pattern_a_fast_core_v02_reentry.py`
- `tests/test_fast_core_v2_lifecycle_prefix_invariance_v01.py`
- 실행 및 결과물은 이 폴더의 `p3_1/`, `p3_2/`, `p2_2/`와 비교 산출물

## 2. P3 prefix invariance

P3-1과 P3-2는 같은 시작일(2022-01-03)을 사용했어. P3-1 종료일/지원일은 2025-05-30/2025-06-02, P3-2는 2026-08-31/2026-09-01이야.

| 전략 | P3-1 REALIZED | P3-1 OPEN_AT_CUTOFF | P3-2에서 누락 | exit 불일치 | 순실현수익률 불일치 | lifecycle 요약 불일치 | 결과 |
|---|---:|---:|---:|---:|---:|---:|---|
| CONTROL | 191 | 56 | 0 | 0 | 0 | 0 | PASS |
| MA60 | 161 | 46 | 0 | 0 | 0 | 0 | PASS |
| ALIGNMENT | 93 | 26 | 0 | 0 | 0 | 0 | PASS |

비교한 진입 키는 ticker, ISU, market, signal/execution date, entry price야. lifecycle 비교는 저장된 `lifecycle_class`, 최초 PROGRESSED 관측일/effective trading date, Loss Guard 여부/신호일을 포함해. REALIZED 거래의 exit type·signal/execution date·price와 순실현수익률도 전부 일치했어. P3-1의 OPEN_AT_CUTOFF 거래는 더 긴 구간에서 진행될 수 있으므로 동일 exit를 요구하지 않았어.

## 3. 지정 재현 종목 (P3-2 CONTROL, 이전 결과 → 수정 결과)

| 종목 | 동일 진입 | 이전 exit / 순수익률 | 수정 exit / 순수익률 | 확인 결과 |
|---|---|---|---|---|
| 039200 | 2024-04-26 | 2026-03-31 / +70.80% | 2024-08-31 / +41.07% | 앞선 no-handoff Exit 4를 유지하고, 그 뒤 재진입도 탐색 |
| 086790 | 2023-10-06 | 2025-11-30 / +118.50% | 2025-01-31 / +38.04% | 장래 handoff가 앞선 exit를 바꾸지 않음 |
| 122870 | 2023-04-14 | 2025-08-31 / +59.01% | 2023-10-31 / -15.08% | 지시서의 미래 horizon 소급 변경 재현 및 수정 확인 |
| 267270 | 2022-12-02 | 2026-01-31 / +84.61% | 2023-08-31 / +26.12% | 2025-01-24 재진입 복원. 해당 거래는 2025-04-07 Loss Guard 청산(-19.42%) |

267270은 이후 2025-07-25에도 재진입이 확인돼. 네 종목의 CONTROL/MA60/ALIGNMENT 및 두 기간의 전체 거래 내역은 `reproduction_cases.csv`에 있어.

## 4. P2-2 영향 확인 및 재실행

공통 lifecycle 모듈을 수정했으므로 P2-2도 전체 재생했어. 기간은 2021-01-04~2026-08-31, 실행 지원일은 2026-09-01이야. 다음은 이전 P2-2 결과와 새 결과의 비교야.

| 전략 | 전체 거래 이전 → 수정 | REALIZED 이전 → 수정 | 기존 REALIZED 누락 | 기존 REALIZED 중 exit/수익률 변경 |
|---|---:|---:|---:|---:|
| CONTROL | 440 → 450 (+10) | 403 → 413 (+10) | 0 | 8 |
| MA60 | 363 → 373 (+10) | 333 → 343 (+10) | 0 | 8 |
| ALIGNMENT | 177 → 177 (0) | 162 → 162 (0) | 0 | 2 |

18건의 exit/수익률 차이는 이전 구현이 먼 미래 lifecycle을 소급 적용한 거래들이야. 기존 REALIZED entry key는 전부 새 원장에 남아 있어. P2-2 기존 REALIZED 원장 중 344건에서 lifecycle 요약 필드가 달라졌고, 326건에서 최초 PROGRESSED 일자/effective trading date가 달라졌어. 청산 이후의 미래 lifecycle 메타데이터가 과거 거래에 붙던 문제를 바로잡은 결과야. 상세 변경 거래는 `p2_2_changed_realized_trades.csv`, 추가 진입은 `p2_2_additional_entries.csv`, 전략별 차이는 `p2_2_impact_comparison.csv`에 있어.

## 5. Loss Guard와 재진입

이전부터 존재하던 모든 Loss Guard 거래에서 exit signal/execution date, exit price, 순실현수익률은 이전 결과와 동일했어. 전체 재생에서 확인한 이전 Loss Guard 건수 → 수정 후 건수는 다음과 같아. 건수 증가는 조기 청산 복구로 다시 가능해진 후속 진입에서 발생한 추가 손절이야.

| 구간 | CONTROL | MA60 | ALIGNMENT |
|---|---:|---:|---:|
| P3-1 | 140 → 140 | 115 → 115 | 61 → 61 |
| P3-2 | 206 → 207 | 163 → 164 | 78 → 78 |
| P2-2 | 238 → 242 | 191 → 195 | 87 → 87 |

267270의 2025-01-24 재진입도 P3-2에서 확인했어.

## 6. 실행 무결성 및 출처 검증

| 구간 | 기간 | 처리 identity | CONTROL / MA60 / ALIGNMENT 거래 | worker 오류 |
|---|---|---:|---:|---:|
| P3-1 | 2022-01-03~2025-05-30 | 2,336 | 247 / 207 / 119 | 0 / 0 / 0 |
| P3-2 | 2022-01-03~2026-08-31 | 2,424 | 374 / 312 / 166 | 0 / 0 / 0 |
| P2-2 | 2021-01-04~2026-08-31 | 2,424 | 450 / 373 / 177 | 0 / 0 / 0 |

- 각 재생은 전략당 worker 10개를 사용했고 network call은 0건이야.
- permanent exclusion은 exact `(ticker, ISU)` 181쌍, 중복 0. frozen survivor 2,539개 중 제외 overlap 115개, eligible universe 2,424개야. ticker-only 매칭은 쓰지 않았어.
- 세 기간의 영구 제외 leakage, cutoff 이후 신규 진입, 중복 거래 키, 순수익률 재계산 불일치는 모두 0이야. Exact-date MKTCAP unresolved는 0건이야.
- 비용은 매수/매도 수수료 각 0.015%, 매수/매도 슬리피지 각 0.10%, 거래세 제외야.
- 세 기간의 canonical source SHA-256은 현재 수정 파일과 일치해: `f045750c5fb5afcf0b8c132151ed7b8f387865f7653beb4e5b849c79b50f0dc1`.
- P3-1 19개, P3-2 20개, P2-2 20개 provenance artifact hash를 재검증했고 불일치는 0건이야.
- P3-1/P3-2/P2-2 execution audit 결과는 모두 PASS야.

## 7. 테스트

최종 소스 기준 실행:

```text
.venv/bin/python -m pytest -q \
  tests/test_fast_core_v2_lifecycle_prefix_invariance_v01.py \
  tests/test_pattern_a_fast_core_v02_reentry.py \
  tests/test_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py \
  tests/test_fastcore_open_at_cutoff_date_semantics_v01.py \
  tests/test_market_calendar_generator.py \
  tests/test_fastcore_simple_backtest_runner_cleanup_fix_v01.py \
  tests/test_score_v02_candidate_compare.py
```

결과: **67 passed, 5 skipped**. pandas timedelta 관련 DeprecationWarning 1,312건은 있었지만 테스트 실패는 없어.

## 8. 검토 파일

- `prefix_invariance_summary.json`
- `prefix_invariance_by_strategy.csv`
- `loss_guard_stability.csv`
- `reproduction_cases.csv`
- `p2_2_impact_comparison.csv`
- `p2_2_changed_realized_trades.csv`
- `p2_2_additional_entries.csv`
- `completion_manifest.json` (71개 scoped 파일의 SHA-256/크기 목록)
- 각 기간의 `report.md`, `*_execution_audit.json`, `*_provenance.json`

P1/P2-1, 5-window synthesis, realistic portfolio는 실행하지 않았어. 지시서 Step 5에 따라 여기서 결과 리뷰를 위해 멈췄고, 커밋/푸시는 하지 않았어. 작업 시작 기준 HEAD와 origin/main은 모두 `ecdad6366c4d84b8b4fbd1006645e1e7313e4124`였어. 다른 기존 로컬 변경/미추적 결과물은 건드리지 않았어.
