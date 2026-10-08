# P1 CONTROL / MA60 / ALIGNMENT 단순 백테스트 결과

## 상태 요약

| 레벨 | 개수 | 내용 |
|---|---:|---|
| CRITICAL | 0 | P1 거래 키, 필터, 순수익 재계산, frozen-input 해시, worker 오류 검증 실패 없음 |
| MAJOR | 0 | P1 세 전략의 저장 ledger와 집계 지표 검증 완료 |
| MINOR | 2 | 기존 PROGRESSED 집계에 종료 후 날짜가 섞여 보정 집계 저장; P1 완료 뒤 시작된 P2-1은 중단되어 최종 결과로 쓰지 않음 |

**최종 판정:** P1 단순 백테스트 비교를 완료했어. MA60과 Alignment은 CONTROL보다 승률과 평균·중앙 수익률이 높았지만 거래 수가 줄었고, 일부 손실 기준은 개선되지 않았어. 이 결과만으로 공식 전략 채택 여부는 판정하지 않았어.

## 범위와 계산 기준

- P1 기간은 2014-01-02부터 2026-08-31까지고, 실행 지원일은 2026-09-01이야.
- 저장된 P3-2 survivor roster 2,539종목과 frozen COMMON PIT 구간 2,541개를 사용했어. 워커는 10개야.
- 전략은 CONTROL, MA60 진입 필터, Bullish Alignment 세 개뿐이야. NEG40 조건은 포함하지 않았고 공식 FAST Core V2 lifecycle은 바꾸지 않았어.
- 아래 terminal 수익률은 원본 gross 열 terminal_return가 아니라 net_terminal_return_pct 기준이야. 편도 슬리피지 0.10%, 편도 수수료 0.015%를 반영했고 거래세는 제외했어. 실현 거래는 매수·매도 비용을 반영했고, cutoff 미종료 거래는 2026-08-31 가격으로 평가했어.
- 승률은 완료 거래 중 net_realized_return_pct가 양수인 비율이야. Terminal 양수율은 cutoff 미종료 평가까지 포함해. 평균·중앙 realized return은 완료 거래만, terminal return은 전체 거래를 포함해.
- +20/+50/+100%와 -10/-15/-20/-30%는 net terminal 기준이고 cutoff 미종료 거래도 포함해. 보유기간은 완료 및 cutoff 미종료 거래의 holding_days 기준이야.
- 단순 거래 단위 결과라 포트폴리오 비중·복리 수익률·MDD는 계산하지 않았어.

## P1 핵심 지표

| 전략 | 거래수 (완료/미종료) | 완료 승률 | 전체 terminal 양수율 | 평균 / 중앙 terminal net | 평균 / 중앙 realized net | 평균 / 중앙 보유일 |
|---|---:|---:|---:|---:|---:|---:|
| CONTROL | 826 (783/43) | 28.35% | 30.51% | +9.50% / -15.37% | +8.01% / -15.44% | 238.6 / 102.0 |
| MA60 | 615 (578/37) | 31.49% | 33.82% | +11.21% / -15.18% | +9.98% / -15.28% | 216.1 / 97.0 |
| ALIGNMENT | 344 (326/18) | 32.21% | 34.59% | +11.60% / -15.14% | +10.20% / -15.23% | 203.8 / 103.0 |

## 위험·생애주기 및 cutoff

| 전략 | Loss Guard | 보유 중 PROGRESSED* | 원본 필드 비어있지 않음 | 종료 후로 제외 | cutoff 미종료 | 최대 terminal 수익 / 손실 |
|---|---:|---:|---:|---:|---:|---:|
| CONTROL | 524 (63.44%) | 287 (34.75%) | 681 | 394 | 43 (5.21%) | +584.70% / -71.47% |
| MA60 | 369 (60.00%) | 234 (38.05%) | 518 | 284 | 37 (6.02%) | +584.70% / -71.47% |
| ALIGNMENT | 213 (61.92%) | 124 (36.05%) | 287 | 163 | 18 (5.23%) | +397.56% / -61.02% |

* 보유 중 PROGRESSED는 entry_execution_date 이후, 실현 거래는 exit_signal_date까지, cutoff 미종료 거래는 2026-08-31까지 first_progressed_effective_trading_date가 기록된 경우로 다시 셌어. 원본 메트릭은 날짜 필드가 비어있지 않은지만 세서 종료 뒤 이벤트도 포함했어. 원본 ledger상 필드가 비어있지 않은 건은 CONTROL 681, MA60 518, ALIGNMENT 287건이고, 종료 뒤라 per-trade PROGRESSED에서 제외한 건은 394, 284, 163건이야. 보정 집계는 p1_strategy_metrics_reconciled.csv에 저장했어.

## 대형 승리·손실 (net terminal)

| 기준 | CONTROL 건수 (비율) | MA60 건수 (비율) | MA60 대 CONTROL 비율차 | ALIGNMENT 건수 (비율) | ALIGNMENT 대 CONTROL 비율차 |
|---|---:|---:|---:|---:|---:|
| +20% | 202 (24.46%) | 161 (26.18%) | +1.72%p | 91 (26.45%) | +2.00%p |
| +50% | 139 (16.83%) | 108 (17.56%) | +0.73%p | 65 (18.90%) | +2.07%p |
| +100% | 52 (6.30%) | 38 (6.18%) | -0.12%p | 22 (6.40%) | +0.10%p |
| -10% 이하 | 548 (66.34%) | 387 (62.93%) | -3.42%p | 217 (63.08%) | -3.26%p |
| -15% 이하 | 467 (56.54%) | 323 (52.52%) | -4.02%p | 180 (52.33%) | -4.21%p |
| -20% 이하 | 51 (6.17%) | 40 (6.50%) | +0.33%p | 26 (7.56%) | +1.38%p |
| -30% 이하 | 12 (1.45%) | 12 (1.95%) | +0.50%p | 5 (1.45%) | +0.00%p |

## CONTROL 대비 후보 변화

| 지표 | MA60 (CONTROL 대비) | ALIGNMENT (CONTROL 대비) |
|---|---:|---:|
| 전체 거래수 | 615 (-211, -25.5%) | 344 (-482, -58.4%) |
| 완료 승률 | 31.49% (+3.14%p) | 32.21% (+3.86%p) |
| 평균 / 중앙 terminal net | +11.21% / -15.18% (+1.71 / +0.19%p) | +11.60% / -15.14% (+2.10 / +0.23%p) |
| 평균 / 중앙 realized net | +9.98% / -15.28% (+1.97 / +0.16%p) | +10.20% / -15.23% (+2.19 / +0.21%p) |
| 평균 / 중앙 보유기간 | 216.1 / 97.0일 (-22.5 / -5.0일) | 203.8 / 103.0일 (-34.8 / +1.0일) |
| Loss Guard 비율 | 60.00% (-3.44%p) | 61.92% (-1.52%p) |
| 보유 중 PROGRESSED 비율 | 38.05% (+3.30%p) | 36.05% (+1.30%p) |
| cutoff 미종료 비율 | 6.02% (+0.81%p) | 5.23% (+0.03%p) |
| 최대 terminal 수익 / 손실 | +584.70% / -71.47% (+0.00 / +0.00%p) | +397.56% / -61.02% (-187.14 / +10.45%p) |

threshold별 후보율 변화는 위 대형 승리·손실 표에 함께 표시했어. 두 후보 모두 완료 승률과 평균·중앙 수익률은 CONTROL보다 높지만 거래 수는 줄었어. 손실 꼬리는 전 구간에서 일관되게 개선된 건 아니야. -20% 이하 손실 비율은 MA60이 +0.33%p, ALIGNMENT가 +1.38%p로 CONTROL보다 높아. 이 표만으로 후보 채택을 결론내리지는 않아.

## Exit reason

| exit reason | CONTROL | MA60 (건수 차이) | ALIGNMENT (건수 차이) |
|---|---:|---:|---:|
| LOSS_GUARD_CLOSE_LE_NEG_15 | 524 | 369 (-155) | 213 (-311) |
| EXIT4_SCORE_DRAWDOWN_GE_15 | 222 | 181 (-41) | 95 (-127) |
| EXIT3_PROGRESSED_TO_EARLY_TREND | 8 | 6 (-2) | 4 (-4) |
| EXIT3_PROGRESSED_TO_TRANSITION | 24 | 20 (-4) | 13 (-11) |
| EXIT3_PROGRESSED_TO_WEAK | 5 | 2 (-3) | 1 (-4) |
| NO_EXIT_BEFORE_CUTOFF | 28 | 25 (-3) | 11 (-17) |
| NO_PROGRESSED_BEFORE_CUTOFF | 15 | 12 (-3) | 7 (-8) |

## 저장 및 무결성

- P1 거래 ledger, P1 alignment signal audit, P1 MA60 audit, 집계 CSV, 실행 audit가 저장돼 있어. P1 alignment accepted signal 344건과 거래 키가 일치해. MA60도 accepted signal 615건과 거래 키가 일치하고 모든 거래가 MA60 필터를 통과했어. Alignment 모든 거래가 signal_day_close > MA20 > MA60 조건을 통과했어.
- CONTROL은 완료 ledger를 재사용했고, MA60은 검증된 P1 MA60 correction V02 ledger를 재사용했어. ALIGNMENT는 2,539종목 전체를 실행했어. 전체 실행은 7360.6초, raw signal audit 22,709행이야.
- P1 worker 오류는 CONTROL 0, MA60 0, ALIGNMENT 0이야. 세 ledger의 거래키 중복도 0건이야.
- Hash 검증 PASS: 시작 HEAD와 origin/main이 2c615b2f1db8ebdd7e416d3a467f16faaac8369b로 같았고 frozen PIT·calendar·identity roster, 공식 strategy source, CONTROL 저장 source ledger, MA60 correction source ledger의 저장 hash가 일치했어. MA60 압축 audit도 correction manifest hash와 일치해. 전체 SHA-256은 p1_provenance.json에 있어.
- 거래키 중복은 세 전략 모두 0건이고 accepted signal ↔ trade key parity는 MA60·ALIGNMENT 모두 PASS야. 각 거래 net_terminal_return_pct를 entry/exit 및 비용 공식으로 다시 계산한 불일치도 0건이야.
- 기존 P3-2 gross/net 값과 혼동하지 않도록 P1 결과는 net_terminal_return_pct 기준으로 정리했어. P3-2를 재실행하지 않았어.
- `reconcile_p1_metrics.py`는 저장된 P1 거래 ledger와 원본 집계 CSV만 읽어 PROGRESSED를 종료일 안으로 한정해 다시 계산해. 백테스트나 P2 작업을 실행하지 않아.

## 커밋 전 재검증

- 저장 ledger 검증 PASS: CONTROL 826, MA60 615, ALIGNMENT 344건. 중복 거래 키 0건, MA60 accepted signal 615건 및 Alignment accepted signal 344건과 거래 키가 각각 일치해.
- 필터 및 순수익 재계산 PASS: MA60 필터 위반 0건, Alignment `signal_day_close > MA20 > MA60` 위반 0건, 세 전략 net terminal 공식 재계산 불일치 0건.
- 관련 테스트 PASS: `tests/test_pattern_a_fast_core_v02_reentry.py`, `tests/test_fastcore_v2_exit4_effectiveness_v01.py`, `tests/test_fastcore_v2_exit4_threshold_sensitivity_v01.py`, `tests/test_fastcore_v2_lifecycle_refinement_strict_handoff_v01.py` — 36 passed. 기존 pandas/NumPy 단위 관련 DeprecationWarning 1,299건이 표시됐지만 실패는 없었어.
- 수정 Python 파일 컴파일 PASS. `git diff --check` PASS.

## P2-1 중단 상태

P1 완료 뒤 이전 전체 재실행 흐름이 P2-1로 넘어간 상태에서 중단 지시를 받아 멈췄어. P2-1은 완결되지 않았고, partial 결과는 P1 비교에 사용하지 않았어. P2-1 출력 파일도 이번 commit 대상에서 제외해.

## P1 시작 기준

P1 사전검사 당시 branch는 main이었고 HEAD == origin/main, ahead/behind는 0/0이었어. 실행 시작 시점 provenance는 p1_provenance.json에 기록했어.

## 산출물

- p1_strategy_metrics_reconciled.csv — 보유 중 PROGRESSED 기준으로 재계산한 P1 집계
- p1_strategy_metrics.csv — runner 원본 집계
- p1_execution_audit.json — P1 실행 worker와 replay provenance
- p1_provenance.json — source/input/output SHA-256와 parity·cost 검증
- p1_control_trades.csv, p1_ma60_trades.csv, p1_alignment_trades.csv — 거래 ledger
- p1_alignment_signal_audit.csv.gz, p1_ma60_signal_audit.csv.gz — 신호 감사
- reconcile_p1_metrics.py — 저장된 P1 결과만 사용하는 PROGRESSED 재계산 스크립트
- `fast_core_v2_p1_ma60_005300_unavailable_diagnosis_correction_v02/p1_ma60_trades.csv` 및 `p1_ma60_run_manifest.json` — MA60 재사용 원본 ledger와 실행 manifest
