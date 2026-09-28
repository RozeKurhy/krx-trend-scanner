# V2 MDD 미해결 평가값 — 현재 상태 fallback 재평가

- 최종 판정: **HOLD / SURVIVORSHIP_BIAS_FALLBACK_USED**
- 기준 계획 commit: `930bf77d6d780c42d75254f75bb26f0e1003b283`
- 결과 commit: `기록은 r.md 참고`
- 종료 HEAD / origin/main: `별도 push 단계에서 확인` / `별도 push 단계에서 확인`; clean: `None`
- 기존 V02 baseline은 보존: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_v02`
- 실행 모드: `EXISTING_STRATEGY_LEDGER_PORTFOLIO_ONLY`; entry signal regeneration=false; strategy evaluation rerun=false; price-frame workers=10.
- 주의: 이 결과는 현재 상태 기준 종목 제외를 사용해 생존편향이 있으며 무편향 역사 시뮬레이션이 아니야.

## 진단 및 fallback 범위

- V02 unresolved mark: 2446 window-day rows, 119 window-identity groups, 74 고유 identity.
- 원인별 고유 identity: `{'CURRENTLY_DELISTED': 6, 'CURRENTLY_SUSPENDED': 1, 'MERGER_OR_SUCCESSOR': 1, 'RAW_DATA_GAP': 66}`.
- 원인별 unresolved mark 수: `{'CURRENTLY_DELISTED': 18, 'CURRENTLY_SUSPENDED': 5, 'MERGER_OR_SUCCESSOR': 1327, 'RAW_DATA_GAP': 1096}`.
- 쉽게 해결한 valuation mark: 0건. 기존 placeholder carry 규칙은 그대로 유지했고, 새로 임의 carry한 값은 없어.
- fallback 제외: 138 exact identities — KRX current master 부재 136, 명시적 현재 거래정지 1, 명시적 현재 상폐 1.
- status evidence는 `fallback_exclusions.csv`; 진단 압축은 `unresolved_identity_summary.csv`.
- 거래량 0 또는 오래된 scanner cache만으로 거래정지 판정을 추가하지 않았어.

## 5개 표준 기간 재평가

| 기간 | 총수익률 | CAGR | MDD | 현금 부족률(참고) | A | B | C | D | E | 남은 unresolved mark |
|---|---:|---:|---:|---:|---|---|---|---|---|---:|
| P1 | 107.15% | 5.92% | 미산출 | 85.60% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | 925 |
| P2-1 | 62.17% | 11.61% | 미산출 | 79.13% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | 51 |
| P2-2 | 94.90% | 12.53% | 미산출 | 81.51% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | 57 |
| P3-1 | 30.53% | 8.14% | 미산출 | 78.38% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | 46 |
| P3-2 | 51.94% | 9.40% | 미산출 | 81.46% | PASS | PASS | PASS | CHECK_REQUIRED | CHECK_REQUIRED | 46 |

현금 부족률은 참고 진단으로만 표시했고 A~E 판정에는 넣지 않았어. 남은 missing mark나 unresolved event가 있으면 D/E를 CHECK_REQUIRED로 유지했어.

## A~E 상세 판정

- P1 A: **PASS** — structural=0; unresolved=0
- P1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P1 C: **PASS** — total_return_pct=107.14568908011076; cagr_pct=5.9211408323804005
- P1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=925; approved_valuation_carries=913
- P1 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=925; approved_placeholder_carries=913; unresolved_trade_events=0; other_issues=0
- P2-1 A: **PASS** — structural=0; unresolved=0
- P2-1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P2-1 C: **PASS** — total_return_pct=62.16610401370699; cagr_pct=11.614641866225583
- P2-1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=51; approved_valuation_carries=85
- P2-1 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=51; approved_placeholder_carries=85; unresolved_trade_events=0; other_issues=0
- P2-2 A: **PASS** — structural=0; unresolved=0
- P2-2 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P2-2 C: **PASS** — total_return_pct=94.90351959643274; cagr_pct=12.528439113831634
- P2-2 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=57; approved_valuation_carries=138
- P2-2 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=57; approved_placeholder_carries=138; unresolved_trade_events=0; other_issues=0
- P3-1 A: **PASS** — structural=0; unresolved=0
- P3-1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P3-1 C: **PASS** — total_return_pct=30.52822843131111; cagr_pct=8.1432044269798
- P3-1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=46; approved_valuation_carries=71
- P3-1 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=46; approved_placeholder_carries=71; unresolved_trade_events=0; other_issues=0
- P3-2 A: **PASS** — structural=0; unresolved=0
- P3-2 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P3-2 C: **PASS** — total_return_pct=51.941254651264; cagr_pct=9.398309957585615
- P3-2 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=46; approved_valuation_carries=99
- P3-2 E: **CHECK_REQUIRED** — portfolio_result_validity: unresolved_daily_marks=46; approved_placeholder_carries=99; unresolved_trade_events=0; other_issues=0

## 현재 상태 근거와 해석

- KRX 현재 상장 종목 원천: `data/reference/source/krx_instrument_metadata_source_snapshot_2026-09-04.json` (관측일 2026-09-04); KRX 시가총액 일별 원천: `artifacts/patterns/pattern_a/production/investability/source/krx_market_cap_20260922.csv` (2026-09-22).
- 005110 한창: KRX 2026-05-06 안내에는 상장폐지 결정 효력정지 가처분 결과에 따라 후속 절차가 진행된다고 되어 있고, 2026-09-22 로컬 KRX 시세 snapshot은 거래량 0이어서 현재 거래정지 fallback으로 분류했어.
- 068240 다원시스: KRX 시장조치 목록에 2026-09-15 상장폐지 및 정리매매 개시 관련 조치가 기록되어 있어 현재 상폐 fallback으로 분류했어.
- 그 외 KRX 현재 상장 equity master에 없는 identity는 `CURRENT_ROSTER_ABSENT`로 기록했어. 이는 현재 exact identity가 목록에 없다는 근거이며 successor 연결을 새로 추정하지 않았어.

## 재현 정보

- 실행 계약: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v01/execution_contract.json`.
- 원천 해시: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_mdd_closure_v01/source_hashes.json`.
- 기간별 가격 평가, 거래, 현금, carry, missing mark 및 unresolved event CSV는 이 디렉터리에 있어.
