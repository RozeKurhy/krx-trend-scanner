# Pattern B PROGRESSED / Previous E-T Candidate V1

> 역사적 상태: 공식 승격 전 당시 판정은 `HOLD`였다. 이 문서는 승격 전 후보와 당시 검증 이력을 보존한다. 현재 공식 전략은 [B Select Core V1](PATTERN_B_SELECT_CORE_V01.md) (`PATTERN_B_SELECT_CORE_V01`)이며, 규칙은 이 후보와 동일하다.

## 식별자

- 전략 ID: PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01
- 표시명: Pattern B E/T PROGRESSED Candidate V1
- 관련 독립 연구: artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_5window_v01/
- 공식 검증 결과: artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/

## 동결된 후보 규칙

신규 진입 이벤트는 아래 조건을 모두 충족해야 해.

1. Pattern B entry state는 DEPRESSED.
2. 현재 Pattern A Stage는 PROGRESSED.
3. entry 시점의 권위 있는 직전 Pattern A Stage는 EARLY_TREND 또는 TRANSITION.

BASE, WEAK, UNAVAILABLE 및 그 밖의 직전 stage는 제외해. 이 후보에서는 추가 조건이나 threshold sweep을 두지 않아.

## 실행 계약

기존 Pattern B lifecycle을 그대로 사용해.

- Entry signal은 매월 마지막 exact KRX 거래일 observation에서만 판정해. 그때 Pattern B가
  DEPRESSED이고, 현재 Pattern A가 PROGRESSED이며, 직전 Pattern A stage가 허용 목록에 있으면 신호야.
- Entry execution: 신호 날짜 다음의 첫 exact KRX session open.
- Exit signal도 매월 마지막 exact KRX 거래일 observation에서만 판정해. 보유 중 그 월말
  observation에서 Pattern B가 NORMAL이면 신호야. 월중 NORMAL만으로 청산하지 않고, 월말 전에
  다시 상태가 바뀌면 해당 월에는 청산 신호가 없어.
- Exit execution: exit signal 다음의 첫 exact KRX session open.
- 매일 실행되는 Daily Update와 Strategy Monitor는 현재 상태·가격·데이터 health를 표시할 수 있지만,
  월중 observation에서 ENTRY/EXIT를 만들지 않아. 기준은 요일이나 다음 월요일이 아니라 exact KRX
  거래일 달력이야.
- Effective cutoff 이후 신규 진입은 금지해.
- Execution support session은 cutoff 전까지 발생한 NORMAL exit의 정산에만 허용해.
- Carry-in은 허용하지 않고, 같은 ISU의 보유 기간 중 겹치는 거래도 허용하지 않아.
- 손절, DEEP exit, Pattern A exit, market cap, dwell threshold 및 추가 stage gate는 없어.

## 공식 검증 창

| Window | Effective range | Execution support |
|---|---|---|
| P1 | 2014-01-02 – 2026-08-31 | 2026-09-01 |
| P2-1 | 2021-01-04 – 2025-05-30 | 2025-06-02 |
| P2-2 | 2021-01-04 – 2026-08-31 | 2026-09-01 |
| P3-1 | 2022-01-03 – 2025-05-30 | 2025-06-02 |
| P3-2 | 2022-01-03 – 2026-08-31 | 2026-09-01 |

## 데이터·authority

- 가격 데이터는 기존 Repository V2 산출물에서 왔어. 공식 검증은 저장된 검증값과 source SHA를 확인하고 원장을 재실행하지 않아.
- PIT identity와 거래일 authority는 기존 rolling market PIT 및 merged calendar authority를 사용해.
- Pattern A 이전 stage authority는 artifacts/patterns/pattern_b/progressed_previous_pattern_a_stage_v01/candidate_signal_stage_history.csv야.
- Pattern A/Pattern B raw linkage 원본은 artifacts/patterns/pattern_b/depressed_entry_pattern_a_state_v01/signal_stage_path_trade_linkage.csv야.
- 프로젝트의 permanent exact-identity exclusion 43건을 그대로 적용해.

## 검증 구분과 한계

공식 무결성 인증은 저장된 5-window 거래 원장, exact identity, PIT stage linkage, lifecycle execution, cutoff terminal 처리, 기존 window별 30건 spotcheck, 집계 재현을 확인했어. 무결성은 PASS지만 전체 기준 적합성은 `CHECK_REQUIRED`이고, 최종 lifecycle 결정은 `HOLD`야.

Trade-level 결과에서 portfolio equity curve를 만들 수 없어 MDD와 회전율은 `NOT_AVAILABLE_IN_CURRENT_TRADE_LEVEL_VALIDATION`이야. P1 실현 거래 521건 중 역사적 매도세율을 포함한 full-standard net 값은 310건에서만 확인돼. 저장된 P1 연도별 집계에서 2025 진입 코호트는 27건 중 terminal resolved 평균 -8.92%였고, 2026 코호트는 부분 기간이며 97건 중 34건이 cutoff 미청산이야. 다섯 표준 창은 서로 겹치므로 독립 표본 다섯 개로 해석하지 않아.

`CERTIFIED_PASS`는 무결성 계약의 일치만 의미해. 수익성 보장이나 실거래 적합성 판단은 아니야. 최종 근거와 기준 대조는 `artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/report.md` 및 `standards_compliance_audit.md`에 있어. 기본 전략 V2 교체는 이번 결정 범위가 아니야.

## 산출물 연결

- 독립 연구와 window 원장: artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_5window_v01/
- read-only 공식 검증: artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/
- 공식 검증 요약: artifacts/patterns/pattern_b/progressed_previous_stage_early_transition_only_official_validation_v01/report.md
