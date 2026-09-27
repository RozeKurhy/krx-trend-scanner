# Pattern B E/T-only 후보: 기준 문서 compliance audit

검토일: 2026-09-28. 기준 문서는 `docs/validation/backtest_common_rules.md` 및 `docs/strategies/strategy_lifecycle.md`야.
저장된 원장·요약을 read-only로 확인했고 replay, V2 rerun, 규칙 변경, threshold 실험은 하지 않았어.
무결성 자체는 PASS지만 구조적으로 확인되지 않은 항목이 있어 전체 기준 적합성은 CHECK_REQUIRED야.

| 기준 | 상태 | 근거 / 판단 |
|---|---|---|
| 후보 전략 동결 | **PASS** | `docs/patterns/pattern_b/strategy/PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01.md` / 동결된 후보 규칙·실행 계약. 공식 검증 metadata의 freeze SHA 기록. |
| 검증 계획 사전 고정 | **CHECK_REQUIRED** | `docs/patterns/pattern_b/strategy/PATTERN_B_PROGRESSED_PREVIOUS_ET_ONLY_CANDIDATE_V01.md`와 기존 study metadata에 창·데이터·측정값은 있지만, 결과 확인 전 작성된 별도 go/no-go 기준 문서는 확인되지 않음. 기준을 소급 작성하지 않음. |
| Repository V2 | **PASS** | 각 window `summary.json.validations.repository_v2_silent_inner_drop_count = 0`; 공식 validator integrity audit. |
| PIT universe | **PASS** | rolling PIT/calendar authority SHA와 window `source_provenance`; `integrity_audit.csv`의 PIT/calendar·authority 검사. |
| completed observations only | **PASS** | 원장 `pattern_a_lookahead_free`; window summary `future_pattern_a_input_count = 0`; 기존 window별 lifecycle spotcheck 30/30. |
| cutoff / support contract | **PASS** | window summary `effective_end`, `execution_support`, support policy; cutoff 뒤 신규 진입 0. |
| next-session execution | **PASS** | `lifecycle_spot_checks.csv` 30/30 per window; exact KRX session/open reconciliation in official validator. |
| identity / lifecycle | **PASS** | stable ticker/ISU key, 43 exact identity exclusions, no duplicate/overlap/support contract violations; `integrity_audit.csv`. |
| missing / unresolved semantics | **PASS** | 미청산은 exact cutoff mark와 UNRESOLVED로 분리; proxy/forward-fill 없이 exact 52/43/52/39/50, unresolved 9/4/4/3/3 by window. |
| cost semantics | **CHECK_REQUIRED** | 실현 거래 pre-tax 비용 필드는 전부 존재하나 P1 full-standard net/tax는 521건 중 310건만 존재. primary resolved-terminal table은 gross이며 미청산 exact mark는 매도 청산으로 보지 않음. |
| 5 standard windows | **PASS** | P1, P2-1, P2-2, P3-1, P3-2의 저장 effective start/end/support가 `backtest_common_rules.md §3.1`과 일치. |
| float tolerance ±0.1pp | **PASS** | `summary.json.aggregate_tolerance_pp = 0.1`; 공식 aggregate check 1,098건, failed 0. |
| same-condition comparison | **PASS** | frozen Pattern B TEST와 변경된 stage gate 외의 execution/terminal 정책은 동일. FAST Core V2는 표본·lifecycle·terminal이 달라 unpaired 참고로 별도 표시. |
| failure / side-effect review | **PASS** | -30/-40/-50/-60, DEEP arrival, +30/+50/+100, unresolved/open tail, holding, 2025 cohort weakness를 이번 report에서 별도 공개. |
| robustness | **CHECK_REQUIRED** | 다섯 창의 mean/median/positive 방향은 반복되나 창끼리 겹침. P1 entry-year 2025 resolved cohort 27건 mean -8.92%; 2026은 부분 기간. 종목 집중도는 낮지만 시기 독립성은 확정되지 않음. |
| MDD / turnover / portfolio setup | **CHECK_REQUIRED** | `backtest_common_rules.md §3, §5`의 portfolio core 평가에 필요한 equity curve·초기자본·position sizing·동시 보유·현금 정책이 현재 trade-level 산출물에 없음. MDD/turnover는 계산하지 않음. |
| final strategy review | **HOLD** | trade-level 성과는 유망하나 기준상 필수 portfolio risk/cost evidence 및 기록된 사전 go/no-go plan이 부족해 공식 전략 채택을 보류. |

## 보정 판단

공식 validator의 `CERTIFIED_PASS`는 저장 산출물의 contract/integrity verdict만 뜻해. 전략 성과와 공식 채택은 별도로 평가했어.
MDD를 trade MAE에서 만들어내지 않았고, turnover도 trade count만으로 추정하지 않았어. portfolio sizing 및 historical tax coverage를 추가 재실행 없이 증명할 수 없어 채택은 HOLD로 기록해.
전략 규칙과 FAST Core V2의 기본 지위는 바꾸지 않았어. 향후 결정을 위해서는 사전 고정된 portfolio 설정과 비용 정책으로 필요한 risk/cost 지표를 평가해야 해.
