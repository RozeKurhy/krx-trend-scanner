# Pattern B E/T PROGRESSED Candidate V1: 공식 검증 및 전략 품질 검토

이번 재감사 시작 HEAD: `74a71b16b137dffd5eee20efc5d6cf45f4420e6e`. 원본 5-window replay 시작 HEAD: `7d5fbcd83273f644eb48ae3f595aaf1f23f54091`. 검토일: 2026-09-28.
무결성 인증: **PASS (`CERTIFIED_PASS`, 1,098 checks / 0 failures)**.
전체 기준 적합성: **CHECK_REQUIRED**. 최종 lifecycle 결정: **HOLD (공식 전략 채택 보류)**.
기존 저장 원장·terminal 산출물을 재사용했어. 5-window lifecycle replay와 FAST Core V2 rerun은 하지 않았고 전략 규칙/threshold도 바꾸지 않았어.
상세 기준별 근거는 [standards_compliance_audit.md](standards_compliance_audit.md)에 있어.

## Candidate NEW_TEST resolved-terminal 성과 및 위험

N은 realized gross 결과와 exact cutoff gross mark를 합친 resolved 수야. UNRESOLVED는 평균·비율에서 제외했고 실제 매도로 간주하지 않았어.

| Window | N / filled | Mean | Median | Positive | +30 / +50 / +100 | -30 / -40 / -50 / -60 | DEEP | Holding mean / median / P90 | Exact open / unresolved |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 573 / 582 | 9.45% | 11.00% | 74.87% | 95 / 34 / 6 | 50 (8.73%) / 36 (6.28%) / 26 (4.54%) / 21 (3.66%) | 106 | 168.8 / 43 / 474 sessions | 52 / 9 |
| P2-1 | 242 / 246 | 6.94% | 9.15% | 67.77% | 42 / 16 / 4 | 36 (14.88%) / 25 (10.33%) / 13 (5.37%) / 8 (3.31%) | 56 | 167.9 / 44 / 561 sessions | 43 / 4 |
| P2-2 | 349 / 353 | 8.05% | 10.59% | 71.92% | 59 / 23 / 4 | 37 (10.60%) / 27 (7.74%) / 19 (5.44%) / 16 (4.58%) | 69 | 155.4 / 43 / 471 sessions | 52 / 4 |
| P3-1 | 200 / 203 | 6.27% | 9.31% | 68.00% | 36 / 13 / 2 | 31 (15.50%) / 20 (10.00%) / 9 (4.50%) / 5 (2.50%) | 50 | 168.8 / 61 / 547 sessions | 39 / 3 |
| P3-2 | 307 / 310 | 7.84% | 10.79% | 72.64% | 53 / 20 / 2 | 32 (10.42%) / 22 (7.17%) / 15 (4.89%) / 13 (4.23%) | 63 | 150.9 / 43 / 456 sessions | 50 / 3 |

창 전체에서 mean 6.27–9.45%, median 9.15–11.00%, positive rate 67.77–74.87%로 방향은 반복돼. 하지만 이 5개 창은 서로 기간이 중첩돼 독립 표본 5개로 볼 수 없어.
후보는 frozen Pattern B TEST보다 mean과 median이 5/5 개선됐고, positive rate는 4/5 개선(나머지 P3-1은 -0.24pp), -30/-40/-50/-60 빈도도 각각 5/5 낮아졌어. 동시에 filled 수와 +50 winner count는 5/5 줄었고 +100 count는 모두 같거나 줄었어.
DEEP arrival는 window마다 50–106건(전체 filled 대비 약 18–25%)이야. 위험 꼬리는 frozen TEST보다 낮아졌어도 절대 수준이 작지 않아.

## FAST Core V2 참고 비교

저장된 공식 `PATTERN_A_FAST_FINAL_STRATEGY_V02` 결과만 사용했어. FAST와 후보는 모집단·lifecycle·terminal이 달라 **unpaired 참고**이며 인과적 우열 비교가 아니야.
후보는 positive rate와 median이 5/5 높고, mean은 4/5 높아(P1은 9.45% 대 9.53%). 후보의 +50 비율은 대략 5.9–6.6%로 FAST의 9.0–15.2%보다 낮고, +100 비율도 후보 0.7–1.7% 대 FAST 2.6–6.4%야. 큰 승자 보존은 FAST가 더 강해. 반대로 FAST의 positive rate는 27.9–32.2%, median은 약 -15.3%야.
FAST의 -30 비율은 약 1.9–2.4%, -60은 0.28–0.62%로 후보보다 훨씬 낮아. 후보는 수익성·승률 특성이 다르고, FAST는 큰 승자와 하방 억제 특성이 다르다는 교환 관계가 있어.

## 시기·종목 집중도 및 보유 특성

P1 연도별 entry cohort 집계는 `annual_breakdown.csv`, 종목별 집계는 `ticker_concentration.csv`야. 계산은 realized gross와 exact cutoff gross mark만 사용하며 percentage-point 합은 자본가중 포트폴리오 기여가 아니야.
P1 resolved 573건은 463개 ticker에 분산됐고 한 ticker 최대 6건(1.05%)이야. 상위 5개 ticker는 양의 gross return point 합의 9.11%, 음의 절대 합의 10.76%를 차지해. 종목 하나에 성과가 좌우된 징후는 약해.
다만 2025 entry cohort는 27건 평균 -8.92%, positive 59.3%야. 2026 cohort는 부분 기간이라 97건 중 34건이 cutoff open mark야.
평균 보유는 151–169 KRX sessions, 중앙값 43–61, P90 약 456–561 sessions야. 장기 자본 고착이 분명한 약점이야.

## 비용 및 portfolio risk 한계

모든 realized ledger row에 commission/slippage pre-tax 값은 있지만, P1 실현 521건 중 full-standard net/tax 값은 310건(59.5%)뿐이야. 나머지 P1 역사 구간의 세후 비교를 완결할 근거가 부족해. Exact open 표시는 gross mark이며 매도 체결·exit tax로 가정하지 않았어.
현재 산출물은 trade-level ledger라 portfolio equity curve가 없어 MDD는 `NOT_AVAILABLE_IN_CURRENT_TRADE_LEVEL_VALIDATION`이야. Turnover도 같은 사유로 평가 불가야. Trade MAE를 MDD로 대체하거나 거래 건수를 turnover로 간주하지 않았어. 초기자본, 종목별 예산, 최대 동시 보유, 현금·체결 배분도 이 후보 산출물에 기록되어 있지 않아.
사전 고정된 전략별 go/no-go 기준 문서도 찾지 못했어. 결과를 본 뒤 이를 소급 작성하지 않았어.

## 최종 lifecycle 결정

**HOLD — 공식 전략 채택 보류.** 저장된 trade-level 자료는 수익성 및 frozen TEST 대비 개선 신호를 보여주지만, 현재 공통 기준이 요구하는 portfolio MDD·turnover와 P1 전체 비용 비교를 확인할 수 없어. 또한 2025 연도 cohort 약세와 창 중첩 때문에 robustness도 충분히 독립적으로 확인되지 않았어.
후보 규칙은 변경하지 않고 V01로 동결 보존해. 이 결정은 기본 전략 `A FAST Core V2`의 교체 여부와 무관하며, 이번 검토에서 V2를 교체하지 않아.
다음 평가 단계에는 사전 고정된 portfolio/cost 설정을 사용한 risk/cost 평가가 필요하지만, 이번에는 새 portfolio backtest를 시작하지 않았어.

## 근거 파일

- 무결성 상세: `artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/integrity_audit.csv`
- Standards audit: `artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/standards_compliance_audit.md`
- Window aggregate: `artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/five_window_validation.csv`
- 저장 FAST V2 비교: `artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/fast_core_v2_reference.csv`
