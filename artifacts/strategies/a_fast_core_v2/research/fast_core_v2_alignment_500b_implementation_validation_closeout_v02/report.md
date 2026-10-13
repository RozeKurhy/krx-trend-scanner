## 이슈 건수 및 최종 판정

| 등급 | 건수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | 확인된 치명 이슈 없음 |
| MAJOR | 2 | Phase4C 실제 corpus E2E 미완료; `tests/test_web_strategy.py` 전체 실행 미완료 |
| MINOR | 1 | 공식 V2 거래원장의 일부 lifecycle 표식이 청산 뒤 관측된 기간 분류이며, causal 재생 결과와 메타데이터 차이가 있음. 거래 경제성 영향은 확인되지 않음 |

**최종 판정: `IMPLEMENTATION_CHECK_REQUIRED`**. 운영 승격이나 배포를 권고하지 않아. 두 개의 전체 검증 gate가 끝나지 않았기 때문이야.

### V01 대비 변경

- V2 lifecycle 차이가 발생한 경계를 확인했고, 783건 정본 중 214건의 사후 PROGRESSED 표식이 모두 이미 종료된 Loss Guard 거래임을 확인했어. 거래 경제성 golden은 계속 엄격 비교하고 시간 범위가 다른 lifecycle 메타데이터만 별도 비교하도록 테스트를 정리했어.
- Phase4C 실제 corpus fixture에 단계 시간, deepcopy 비용, peak RSS, 000370 OPEN continuity 계측을 추가했어. 중복 payload/monitor 재생 검사는 실제 fixture 결과를 재사용하도록 줄였어.
- 웹 테스트의 낡은 cache/UI 문자열 및 B Select history fixture를 현재 구현 계약에 맞췄어. 실제 HTML/JS/CSS 동작은 수정하지 않았어.
- Phase4C와 웹 전체 테스트는 각각 같은 대형 strategy-monitor 재생 단계에서 제한 시간 안에 끝나지 않아 `CHECK_REQUIRED`로 남아 있어.

## 범위 및 안전 상태

- 기준/종료 `HEAD`: `a3a2a7ab9f634633760eb4992630608d0280e843`
- 기준/종료 `origin/main`: `a3a2a7ab9f634633760eb4992630608d0280e843`
- 작업 시작 시 기존 작업 트리는 dirty였어: 22 tracked 변경, 53 untracked status 항목(262 untracked leaf paths). 기존 연구 산출물을 삭제하거나 초기화하지 않았어.
- 종료 시: 22 tracked 변경, 기존 untracked leaf paths 262개 보존, 이 closeout 보고서 1개 추가. `web/data/`와 `artifacts/reporting/stock_reports/` 변경은 0건.
- promotion config 확인: `enabled=false`, `effective_signal_date=PENDING_USER_APPROVAL`, `operational_activation_approved=false`.
- 제외 정책: 정확한 `(ticker, standard ISU_CD)` 185쌍, 정본 hash `c0089f72ed390a2a1df9048d0dac1f309259422e3ff9e77c4f6d986517a5163c` 유지.
- 공식 5기간 백테스트, 신호 재생, Daily Update, canonical/static 발행, 배포 및 주문은 수행하지 않았어. commit/push도 하지 않았어.
- 임시 Phase4C staging 및 historical-authority 디렉터리는 종료 뒤 남지 않았어.

## A. V2 lifecycle golden 차이

### 재현 및 provenance

- 공식 정본: `artifacts/patterns/pattern_a_fast/production/core_v02_reentry/trades.csv` (783 rows), SHA-256 `2bd151d79ea628452cfca4e943fa1d1ec827d57952fad652f26a425439c40a33`.
- 삼성전자 가격 입력: `data/raw/stocks/005930.parquet`, SHA-256 `dafeb8f05b37670eb4fa3e7b7fef155aaf052bff61aa9be80785d752fd8cb36a`.
- 기존 V2 report 재생은 `as_of=2026-08-14`, gate 비활성, `save_artifacts=False`로 실행했어. 기준 HEAD 소스를 격리해 같은 입력을 준 결과도 현재 working tree와 거래 경제성 결과가 같았어. V2 simulator 파일은 이번 수정 대상이 아니야.
- 정본 783건 가운데 `first_progressed_date > exit_signal_date`는 214건, 159 ticker야. 214건 전부 `LOSS_GUARD_CLOSE_LE_NEG_15`로 실현 종료된 거래야. 이 숫자를 성과 오류나 lookahead 매매로 해석하지 않아.

### 삼성전자 4건 대조

| 거래 | 진입 신호 / 체결 / 시가 | 공식 청산 신호 / 체결 / 가격 | 상태 / 수익률 / 청산 이유 | 정본 lifecycle / first PROGRESSED | causal report lifecycle |
|---|---|---|---|---|---|
| `005930_01` | 2019-11-01 / 2019-11-04 / 51,700원 | 2020-03-19 / 2020-03-20 / 44,150원 | REALIZED / -14.60% / Loss Guard | NORMAL_EARLY_TREND_HANDOFF / 2021-03-31 (청산 후) | NEVER_PROGRESSED |
| `005930_02` | 2020-11-13 / 2020-11-16 / 64,000원 | 2022-02-28 / 2022-03-02 / 72,300원 | REALIZED / +12.97% / EXIT3_PROGRESSED_TO_TRANSITION | NORMAL_EARLY_TREND_HANDOFF / 2021-03-31 | NORMAL_EARLY_TREND_HANDOFF |
| `005930_03` | 2023-06-02 / 2023-06-05 / 72,700원 | 2024-09-30 / 2024-10-02 / 60,500원 | REALIZED / -16.78% / Loss Guard | NORMAL_EARLY_TREND_HANDOFF / 2026-02-28 (청산 후) | NEVER_PROGRESSED |
| `005930_04` | 2025-08-29 / 2025-09-01 / 68,400원 | cutoff 전 청산 없음 | OPEN_AT_CUTOFF / +301.32% / NO_EXIT_BEFORE_CUTOFF | NORMAL_EARLY_TREND_HANDOFF / 2026-02-28 | NORMAL_EARLY_TREND_HANDOFF |

네 건의 trade id/sequence, 진입·청산 신호일 및 체결일, 진입·청산 가격, 상태, 수익률, previous exit은 정본과 일치해. lifecycle만 `_01`, `_03`에서 의미 범위가 달라. 정본의 window label은 analysis cutoff까지의 관찰을 담고, causal 재생은 Loss Guard `stop_date`에서 중단하기 때문이야.

`_simulate_causal_lifecycle`에 Loss Guard 신호일 뒤의 PROGRESSED 관찰이 causal metadata를 갱신하지 않는 단위 테스트를 추가했어. 214건은 전부 REALIZED라 현재 OPEN의 Exit3 활성화나 현재 포지션 표시에는 영향을 주지 않아. 손익·청산 결과 비교를 약화하거나 simulator 규칙을 바꾸지 않았어.

## B. Phase4C 전체 corpus E2E

fixture에서 실행 단계를 계측하고, 000370의 report/monitor 결과를 같은 실제 실행에서 수집해 과거 테스트의 중복 전체 빌드를 제거했어. 제한 재시도에서도 필수 corpus나 검증을 축소하지 않았어.

| 측정 항목 | 결과 |
|---|---:|
| 전체 suite 벽시계 | 423.34초 후 수동 중단; 18 tests PASS, 실제 E2E fixture 미완료 |
| stock report payload | 23.37초 |
| market ranking | 0.27초 |
| strategy monitor (`build_strategy_monitor`) | 398.56초, 미완료 |
| 계측된 `stock_report_web.copy.deepcopy` | 17,844회 / 합계 0.22초 |
| 프로세스 peak RSS high-water mark | 시작 137.23MB → 중단 시 3,757.05MB |

별도 31.87초 계측 샘플에서는 stock payload 23.47초, strategy monitor 6.96초까지 측정됐지만 전체 실행에서 strategy monitor는 398.56초를 소비했어. 실행 환경과 단계의 비용 변동이 커서 31초 샘플을 완료 증거로 보지 않아. deepcopy는 관측된 병목이 아니며, 더 이상의 반복 최적화는 하지 않았어. 병목 단계는 전체 ticker/history용 strategy monitor 재생이야. 해당 builder는 B Select history의 exact-session 가격/보유기간 지표를 위해 Repository V2와 PIT/calendar projection을 조회해.

마지막 실행은 E2E fixture 도중 중단됐고 `test_real_run_status_pass` 결과는 미확정이야. 따라서 Phase4C suite는 **미완료**고 `PASS`로 보고하지 않아. Phase4B와 Phase4D의 별도 기존 완료 결과는 각각 60 PASS, 17 PASS야.

## C. 웹 테스트 stale 기대값

실제 현재 UI 소스와 대조해 테스트 기대값만 수정했어.

| 기대값 유형 | 현재 구현 근거 및 수정 |
|---|---|
| page/cache version | `web-strategy-price-order-history-age-v01`의 현재 HTML asset version에 맞춤 |
| fundamental filter markup | `<label id=...>` 및 `<details aria-labelledby=...>` 구조를 검증 |
| history fundamental matching | 단일 변수 비교 대신 `historyFundamentalFilters` Set의 `has(fundamentalStatus(trade))`를 검증 |
| CSS selector | 제거된 B Select 전용 margin 대신 현재 `.strategy-trade-row .strategy-item-exit-reason .strategy-item-value` clamp 규칙을 검증 |
| JS field signatures | 진입가와 Pattern B의 현재 CSS class 인수를 검증 |
| B Select stale-row fixture | validator가 검사하려는 구버전 lineage를 내부 일관성 있게 구성해, 정본 ID 거부 assertion까지 도달하도록 수정 |

전체 웹 suite 첫 실행은 398.12초에 18 PASS / 1 stale assertion FAIL 후 중단됐어. 해당 문자열 및 fixture를 수정한 뒤 느린 exporter projection 테스트 1개를 제외한 나머지 웹 테스트는 **25 PASS, 1 deselected (0.73초)**야. 느린 테스트 `test_strategy_monitor_json_matches_clean_exporter_projection`는 실제 corpus를 다시 `build_strategy_monitor`에 통과시키며, 전체 Phase4C 실행에서도 같은 strategy-monitor 단계가 398초를 넘겼어. 전체 `tests/test_web_strategy.py`는 수정 후 완주하지 않았으므로 PASS가 아니야.

## 검증 결과

| 검증 | 결과 |
|---|---|
| V2 reentry + 6 ticker official golden + 500B gate + Phase4B + Phase4D 관련 테스트 | **114 PASS, 42.78초**; pandas timedelta deprecation warning 2,041건, 실패 없음 |
| Web strategy 빠른 나머지 전체 (`-k 'not strategy_monitor_json_matches_clean_exporter_projection'`) | **25 PASS, 1 deselected, 0.73초** |
| Phase4C 전체 corpus suite | **미완료**; 18 PASS 후 실제 E2E 단계에서 423.34초에 중단 |
| Web strategy 전체 suite | **미완료**; 느린 clean-exporter corpus rebuild가 398초 이상 |
| `git diff --check` | PASS |
| Python `compileall` (영향받은 Python source/tests) | PASS |
| `node --check` (`web/js/strategy.js`, `web/js/report.js`) | PASS |
| operational config JSON parse | PASS |
| `web/data/`, canonical stock reports | 수정 0건 |

이번 closeout에서 실제로 수정한 파일은 `tests/test_a_fast_core_stock_report.py`, `tests/test_pattern_a_fast_core_v02_reentry.py`, `tests/test_daily_update_phase4c_v01.py`, `tests/test_web_strategy.py`, 그리고 이 보고서야. 기존 구현 및 untracked 연구 파일은 보존했어.

## 다음 단계

Phase4C 전체 corpus E2E와 `test_strategy_monitor_json_matches_clean_exporter_projection`를 완료할 수 있는 실행 환경/계산 예산에서 재검증해야 해. 완료 전에는 판정을 `IMPLEMENTATION_CHECK_REQUIRED`로 유지해. 운영 활성화, 적용일 지정, Daily Update, 발행/배포는 별도 승인이 필요해.
