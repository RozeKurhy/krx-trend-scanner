# A FAST Core V2 공식 전략 공통 채택 기준 재심사 결과

- 최종 판정: **HOLD**
- 계획 commit: `930bf77d6d780c42d75254f75bb26f0e1003b283` (계획 SHA-256 `84f7c7ab2dfd3f3af049dc876925f103d1e8d04e391248a780cd9d0537c1501c`)

## 다섯 표준 기간 결과

| 기간 | 총수익률 | CAGR | MDD | 현금 부족률 | A | B | C | D | E | F |
|---|---:|---:|---:|---:|---|---|---|---|---|---|
| P1 | CHECK_REQUIRED | CHECK_REQUIRED | CHECK_REQUIRED | 84.65% | CHECK_REQUIRED | PASS | CHECK_REQUIRED | CHECK_REQUIRED | FAIL | CHECK_REQUIRED |
| P2-1 | 31.16% | 6.36% | CHECK_REQUIRED | 81.12% | PASS | PASS | PASS | CHECK_REQUIRED | FAIL | CHECK_REQUIRED |
| P2-2 | 79.95% | 10.95% | CHECK_REQUIRED | 82.75% | PASS | PASS | PASS | CHECK_REQUIRED | FAIL | CHECK_REQUIRED |
| P3-1 | 20.60% | 5.66% | CHECK_REQUIRED | 79.50% | PASS | PASS | PASS | CHECK_REQUIRED | FAIL | CHECK_REQUIRED |
| P3-2 | 43.28% | 8.03% | CHECK_REQUIRED | 82.58% | PASS | PASS | PASS | CHECK_REQUIRED | FAIL | CHECK_REQUIRED |

## 기간별 진단

| 기간 | 종료 자산 | MDD 최고점/저점/회복 | 적격 시도 | 현금 누락 | 활용도 평균/최대 | 보유 평균/최대 | 진입/청산/미청산 | 수수료 | 슬리피지 | 평가 carry | 미해결 |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | None | None / None / 미회복 | 4983 | 4218 / 4983 | 96.23% / 100.00% | 53.33 / 86 | 765 / 697 / 66 | 1122456.8053018507 | 7482929.834999558 | 1320 | 2243 |
| P2-1 | 262319350.78167474 | None / None / 미회복 | 1801 | 1461 / 1801 | 93.86% / 100.00% | 38.01 / 45 | 340 / 298 / 41 | 477840.41332544986 | 3185407.804999815 | 89 | 53 |
| P2-2 | 359905964.24686766 | None / None / 미회복 | 2394 | 1981 / 2394 | 93.69% / 99.97% | 42.21 / 71 | 413 / 365 / 48 | 601526.9831324992 | 4010081.769999782 | 133 | 59 |
| P3-1 | 241191218.57931316 | None / None / 미회복 | 1161 | 923 / 1161 | 91.26% / 100.00% | 32.89 / 40 | 238 / 200 / 38 | 325419.8046869996 | 2169271.61599987 | 84 | 46 |
| P3-2 | 286551136.6048149 | None / None / 미회복 | 1785 | 1474 / 1785 | 91.78% / 100.00% | 35.48 / 53 | 311 / 267 / 44 | 439297.7291852996 | 2928489.6659998377 | 117 | 46 |

## 기준 판정 근거

- P1 A: **CHECK_REQUIRED** — structural=0; unresolved=1
- P1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P1 C: **CHECK_REQUIRED** — total_return_pct=None; cagr_pct=None
- P1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=2242; approved_valuation_carries=1320
- P1 E: **FAIL** — cash_skipped=4218; eligible_attempts=4983; rate_pct=84.64780252859723
- P1 F: **CHECK_REQUIRED** — unresolved_daily_marks=2242; approved_placeholder_carries=1320; unresolved_trade_events=1; other_issues=1
- P2-1 A: **PASS** — structural=0; unresolved=0
- P2-1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P2-1 C: **PASS** — total_return_pct=31.15967539083737; cagr_pct=6.359054762552807
- P2-1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=53; approved_valuation_carries=89
- P2-1 E: **FAIL** — cash_skipped=1461; eligible_attempts=1801; rate_pct=81.12159911160465
- P2-1 F: **CHECK_REQUIRED** — unresolved_daily_marks=53; approved_placeholder_carries=89; unresolved_trade_events=0; other_issues=0
- P2-2 A: **PASS** — structural=0; unresolved=0
- P2-2 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P2-2 C: **PASS** — total_return_pct=79.95298212343383; cagr_pct=10.951107779942992
- P2-2 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=59; approved_valuation_carries=133
- P2-2 E: **FAIL** — cash_skipped=1981; eligible_attempts=2394; rate_pct=82.7485380116959
- P2-2 F: **CHECK_REQUIRED** — unresolved_daily_marks=59; approved_placeholder_carries=133; unresolved_trade_events=0; other_issues=0
- P3-1 A: **PASS** — structural=0; unresolved=0
- P3-1 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P3-1 C: **PASS** — total_return_pct=20.59560928965658; cagr_pct=5.657151250402848
- P3-1 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=46; approved_valuation_carries=84
- P3-1 E: **FAIL** — cash_skipped=923; eligible_attempts=1161; rate_pct=79.50043066322137
- P3-1 F: **CHECK_REQUIRED** — unresolved_daily_marks=46; approved_placeholder_carries=84; unresolved_trade_events=0; other_issues=0
- P3-2 A: **PASS** — structural=0; unresolved=0
- P3-2 B: **PASS** — All executed entries/exits use 0.015% commission and 0.1% directional slippage; tax=0% by contract.
- P3-2 C: **PASS** — total_return_pct=43.27556830240744; cagr_pct=8.027497969053066
- P3-2 D: **CHECK_REQUIRED** — mdd_pct=None; unresolved_mark_gaps=46; approved_valuation_carries=117
- P3-2 E: **FAIL** — cash_skipped=1474; eligible_attempts=1785; rate_pct=82.57703081232492
- P3-2 F: **CHECK_REQUIRED** — unresolved_daily_marks=46; approved_placeholder_carries=117; unresolved_trade_events=0; other_issues=0

## 미해결 평가 근거

| 기간 | 공식 placeholder carry | 조정 종가 미해결 | 추가 생애주기 미해결 |
|---|---:|---:|---|
| P1 | 1,320 | 915 | successor 사용 가능일을 확인하지 못한 원장 1건이 1,327거래일 평가에 영향 |
| P2-1 | 89 | 53 | 없음 |
| P2-2 | 133 | 59 | 없음 |
| P3-1 | 84 | 46 | 없음 |
| P3-2 | 117 | 46 | 없음 |

미해결 조정 종가 행은 같은 날짜·시장 `COMPLETE` KRX partition에 실제 ticker 행이 있으나 placeholder predicate를 만족하지 않았어. 따라서 직전 종가를 이월하지 않았고, MDD를 계산하지 않아 D/F를 `CHECK_REQUIRED`로 남겼어. P1 successor 문제도 임의 종목/가치로 대체하지 않았어.

## 사전 확정 원장 기준 E 및 평가 carry 감사

각 인증 CONTROL 원장 행은 최대 한 번만 포트폴리오에 전달했고, 현금 부족 뒤 신호나 종목 상태를 재생성하지 않았어. E는 정확한 체결 시가와 1주 이상 주문 가능성이 확인된 비차단 행만 분모로 삼았어. 일별 종가 carry는 같은 날짜·시장 KRX `COMPLETE` partition의 정확한 종목 행이 공식 `NON_TRADING_PLACEHOLDER_V01` 조건을 만족한 경우에만 적용했어. 모든 적용·미적용 확인은 `valuation_carry_audit_<window>.csv`에 원천 해시와 직전 조정 종가를 남겼어.

## 시가총액 1조 이상 기존 결과(참고 전용)

유니버스가 다른 참고 자료라 공식 A~F 판정이나 성과 우열 근거로 사용하지 않았어.

| 기간 | 상태 | 총수익률 | CAGR | MDD | 현금 누락 수 | 현금 누락률 | 미해결 | 유니버스 |
|---|---|---:|---:|---:|---:|---:|---:|---|
| P2-1 | P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED | 15.19% | 3.27% | -30.19% | 156 | N/A (기존 원천에 동일 분모가 없음) | 0 | 시총 >= 1조원 |
| P2-2 | P2_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED | 84.64% | 11.46% | -30.80% | 243 | N/A (기존 원천에 동일 분모가 없음) | 0 | 시총 >= 1조원 |
| P3-2 | P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED | 85.58% | 14.20% | -15.14% | 177 | N/A (기존 원천에 동일 분모가 없음) | 0 | 시총 >= 1조원 |

## 원천·재현 정보

- 계획 문서: [`docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md`](../../../../../docs/patterns/pattern_a_fast/strategy/version_02/OFFICIAL_ADOPTION_REVALIDATION_PLAN_V02.md), commit `930bf77d6d780c42d75254f75bb26f0e1003b283`, SHA-256 `84f7c7ab2dfd3f3af049dc876925f103d1e8d04e391248a780cd9d0537c1501c`.
- source hash manifest: `source_hashes.json`; 인증 원장·실제 로드한 일봉 canonical hash·조회한 KRX 원자료 partition 해시를 포함했어.
- execution contract: `execution_contract.json`; 상세 이벤트·현금·평가 carry는 기간별 CSV에 있어.
- 공식 산출물 경로: `artifacts/patterns/pattern_a_fast/strategy/v2_official_adoption_revalidation_v02`.
- 결과 commit/push 및 최종 `HEAD == origin/main` 확인: 사용자 지정 `r.md`에 기록.
