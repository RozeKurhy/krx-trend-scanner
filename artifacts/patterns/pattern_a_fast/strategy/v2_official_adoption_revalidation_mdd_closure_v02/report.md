# V2 RAW_DATA_GAP 영구 제외 후 MDD 재평가

- 최종 판정: **HOLD**
- 기준 계획 commit: `930bf77d6d780c42d75254f75bb26f0e1003b283`
- 결과 commit: `SHA는 r.md 참고`
- 종료 HEAD / origin/main: `push 후 r.md에 확인 기록` / `push 후 r.md에 확인 기록`; clean: `push 후 확인 기록`
- 승인 정책 commit: `d3a7aced`
- 기존 V02 baseline은 보존: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_v02`
- 실행 모드: `EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY`; entry signal regeneration=false; strategy evaluation rerun=false; price-frame workers=10.
- 현재 상태 fallback은 permanent 정책으로 승격하지 않았고, 이번 재평가에 별도로 적용했어. 따라서 결과는 생존편향이 있어.

## 진단 및 fallback 범위

- V02 unresolved mark: 2446 window-day rows, 119 window-identity groups, 74 고유 identity.
- 원인별 고유 identity: `{'CURRENTLY_DELISTED': 6, 'CURRENTLY_SUSPENDED': 1, 'MERGER_OR_SUCCESSOR': 1, 'RAW_DATA_GAP': 66}`.
- 원인별 unresolved mark 수: `{'CURRENTLY_DELISTED': 18, 'CURRENTLY_SUSPENDED': 5, 'MERGER_OR_SUCCESSOR': 1327, 'RAW_DATA_GAP': 1096}`.
- 공통 permanent 정책은 기존 43개와 승인된 RAW_DATA_GAP 66개, 총 109 exact identities야.
- delta 66개는 `permanent_exclusion_delta.csv`에 기록했어. CURRENT_ROSTER_ABSENT 136개와 현재 거래정지/상폐 fallback은 permanent 목록에 넣지 않았어.
- fallback 제외: 138 exact identities — KRX current master 부재 136, 명시적 현재 거래정지 1, 명시적 현재 상폐 1.
- current-status fallback은 영구 정책과 분리했어. 기존 placeholder carry·비용·현금 규칙 및 인증 원장은 유지했고 신호/전략은 재생성하지 않았어.
- 거래량 0 또는 오래된 scanner cache만으로 거래정지 판정을 추가하지 않았어.

## 5개 표준 기간 재평가

| 기간 | 총수익률 | CAGR | MDD | peak | trough | recovery | unresolved marks | 현금 부족률(참고) | A | B | C | D | E |
|---|---:|---:|---:|---|---|---|---:|---:|---|---|---|---|---|
| P1 | 108.39% | 5.97% | 미산출 | N/A | N/A | 미회복 | 190 | 85.11% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |
| P2-1 | 57.33% | 10.85% | 미산출 | N/A | N/A | 미회복 | 2 | 77.29% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |
| P2-2 | 95.85% | 12.62% | 미산출 | N/A | N/A | 미회복 | 3 | 79.52% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED |
| P3-1 | 22.93% | 6.25% | -37.34% | 2023-04-07 | 2024-01-17 | 미회복 | 0 | 78.64% | PASS | PASS | PASS | FAIL | PASS |
| P3-2 | 49.54% | 9.02% | -38.46% | 2023-04-07 | 2025-04-09 | 2026-01-29 | 0 | 81.61% | PASS | PASS | PASS | FAIL | PASS |

현금 부족률은 참고 진단으로만 표시했고 A~E 판정에는 넣지 않았어. MDD 통과 기준은 -35% 이상이야.

## 재평가 후 남은 미해결

- 미해결 identity: 15개; 새 RAW_DATA_GAP exact identity: 15개.
- identity별 기간·일수·날짜·근거는 `unresolved_remaining.csv`에 있어. 새 identity는 자동 영구 제외하거나 반복 실행하지 않았어.

| ticker | ISU_CD | window | unresolved mark days | first date | last date |
|---|---|---|---:|---|---|
| 000520 | KR7000520007 | P1 | 48 | 2014-01-14 | 2016-11-25 |
| 002820 | KR7002820009 | P1 | 9 | 2014-02-21 | 2014-08-27 |
| 003690 | KR7003690005 | P1;P2-1;P2-2 | 6 | 2024-02-16 | 2024-06-27 |
| 004150 | KR7004150009 | P1 | 4 | 2015-05-27 | 2015-07-23 |
| 006120 | KR7006120000 | P1 | 27 | 2014-01-16 | 2017-11-02 |
| 007070 | KR7007070006 | P1 | 2 | 2015-07-31 | 2017-05-08 |
| 030530 | KR7030530000 | P1 | 15 | 2014-02-25 | 2016-02-01 |
| 033310 | KR7033310004 | P1 | 3 | 2019-01-31 | 2019-06-21 |
| 035200 | KR7035200005 | P1 | 2 | 2018-02-20 | 2018-03-09 |
| 053450 | KR7053450003 | P1 | 15 | 2016-02-15 | 2016-10-25 |
| 063160 | KR7063160006 | P1 | 29 | 2014-02-04 | 2015-02-13 |
| 086900 | KR7086900008 | P1 | 26 | 2017-04-20 | 2018-06-25 |
| 117670 | KR7117670000 | P1 | 3 | 2016-03-11 | 2016-06-21 |
| 128940 | KR7128940004 | P2-2 | 1 | 2022-07-05 | 2022-07-05 |
| 138080 | KR7138080007 | P1 | 5 | 2019-02-11 | 2019-08-20 |

## A~E 상세 판정

- P1 A: **PASS** — structural=0; unresolved=0
- P1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P1 C: **PASS** — total_return_pct=108.38683698690765; cagr_pct=5.971133616148516
- P1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=190; approved_valuation_carries=928
- P1 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=190; approved_placeholder_carries=928; unresolved_trade_events=0; other_issues=0
- P2-1 A: **PASS** — structural=0; unresolved=0
- P2-1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P2-1 C: **PASS** — total_return_pct=57.330690819868565; cagr_pct=10.849340323054712
- P2-1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=2; approved_valuation_carries=37
- P2-1 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=2; approved_placeholder_carries=37; unresolved_trade_events=0; other_issues=0
- P2-2 A: **PASS** — structural=0; unresolved=0
- P2-2 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P2-2 C: **PASS** — total_return_pct=95.84891593308286; cagr_pct=12.624791260150769
- P2-2 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=3; approved_valuation_carries=245
- P2-2 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=3; approved_placeholder_carries=245; unresolved_trade_events=0; other_issues=0
- P3-1 A: **PASS** — structural=0; unresolved=0
- P3-1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P3-1 C: **PASS** — total_return_pct=22.930500446235836; cagr_pct=6.2541955772908775
- P3-1 D: **FAIL** — mdd_pct=-37.34120963255192; unresolved_mark_gaps=0; approved_valuation_carries=42
- P3-1 E: **PASS** — portfolio_result_validity: unresolved_daily_marks=0; approved_placeholder_carries=42; unresolved_trade_events=0; other_issues=0
- P3-2 A: **PASS** — structural=0; unresolved=0
- P3-2 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P3-2 C: **PASS** — total_return_pct=49.538312300035095; cagr_pct=9.024476561359851
- P3-2 D: **FAIL** — mdd_pct=-38.460917722441614; unresolved_mark_gaps=0; approved_valuation_carries=62
- P3-2 E: **PASS** — portfolio_result_validity: unresolved_daily_marks=0; approved_placeholder_carries=62; unresolved_trade_events=0; other_issues=0

## 현재 상태 근거와 해석

- KRX 현재 상장 종목 원천: `data/reference/source/krx_instrument_metadata_source_snapshot_2026-09-04.json` (관측일 2026-09-04); KRX 시가총액 일별 원천: `artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20260922.csv` (2026-09-22).
- 005110 한창: KRX 2026-05-06 안내에는 상장폐지 결정 효력정지 가처분 결과에 따라 후속 절차가 진행된다고 되어 있고, 2026-09-22 로컬 KRX 시세 snapshot은 거래량 0이어서 현재 거래정지 fallback으로 분류했어.
- 068240 다원시스: KRX 시장조치 목록에 2026-09-15 상장폐지 및 정리매매 개시 관련 조치가 기록되어 있어 현재 상폐 fallback으로 분류했어.
- 그 외 KRX 현재 상장 equity master에 없는 identity는 `CURRENT_ROSTER_ABSENT`로 기록했어. 이는 현재 exact identity가 목록에 없다는 근거이며 successor 연결을 새로 추정하지 않았어.

## 재현 정보

- 실행 계약: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v02/execution_contract.json`.
- 원천 해시: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v02/source_hashes.json`.
- delta 및 unresolved 목록: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v02/permanent_exclusion_delta.csv`; `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v02/unresolved_remaining.csv`.
- 기간별 일별 equity, 거래, 현금, carry, missing mark 및 unresolved event CSV는 `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v02`에 있어.
