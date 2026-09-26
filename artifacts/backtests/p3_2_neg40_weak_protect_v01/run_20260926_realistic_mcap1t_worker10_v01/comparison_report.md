# P3-2 현실적 포트폴리오 백테스트

판정: `P3_2_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED`

기간: P3-2 effective 2022-01-03 ~ 2026-08-31 (execution support 2026-09-01)

최신 Daily Update: 2026-09-21

전략: CONTROL `PATTERN_A_FAST_FINAL_STRATEGY_V02` / Candidate `PATTERN_A_FAST_CORE_V2_NEG40_WEAK_PROTECT_SOFT_EXIT_V01`. Candidate는 공식 V2.1로 승격하지 않았어.

## CONTROL vs Candidate

| 지표 | CONTROL | Candidate | Candidate − CONTROL |
|---|---:|---:|---:|
| 최종 자산 (KRW) | 371,154,513.8211 | 371,514,427.2898 | 359,913.4688 |
| 누적수익률 (%) | 85.5773 | 85.7572 | 0.1800 |
| CAGR (%) | 14.1982 | 14.2220 | 0.0238 |
| MDD (%) | -15.1355 | -15.1355 | 0.0000 |
| 체결 진입 거래 수 | 228 | 228 | 0 |
| 실현 승률 (%) | 30.4348 | 30.4348 | 0.0000 |
| 평균 보유 거래일 | 143.3333 | 143.2705 | -0.0628 |
| 중앙 보유 거래일 | 72 | 72 | 0 |
| 평균 동시 보유 | 30.9622 | 30.9508 | -0.0114 |
| 최대 동시 보유 | 56 | 56 | 0 |
| 평균 자본 사용률 (%) | 77.8132 | 77.8033 | -0.0099 |
| 평균 현금 비율 (%) | 22.1868 | 22.1967 | 0.0099 |
| 회전율 (x) | 11.5081 | 11.5099 | 0.0018 |
| 총 수수료 (KRW) | 345,243.5143 | 345,297.6177 | 54.1033 |
| 매수 수수료 (KRW) | 168,986.5414 | 168,986.5414 | 0.0000 |
| 매도 수수료 (KRW) | 176,256.9729 | 176,311.0763 | 54.1033 |
| 매도 거래세 (KRW) | 2,260,446.4646 | 2,261,167.8425 | 721.3779 |
| 슬리피지 영향 (KRW) | 2,301,674.2000 | 2,302,035.2500 | 361.0500 |
| 현금 부족 진입 skip | 177 | 177 | 0 |
| cutoff 미청산 보유 수 | 24 | 24 | 0 |
| 실현 ≤ -30% | 2 | 2 | 0 |
| 실현 ≤ -40% | 1 | 0 | -1 |
| 실현 ≤ -50% | 0 | 0 | 0 |
| 실현 ≤ -60% | 0 | 0 | 0 |
| 실현 ≥ +50% | 43 | 43 | 0 |
| 실현 ≥ +100% | 21 | 21 | 0 |
| MDD peak / trough / recovery | 2022-05-02 / 2023-03-14 / 2023-07-31 | 2022-05-02 / 2023-03-14 / 2023-07-31 | — |

매수/매도 수수료는 portfolio event ledger의 진입/청산별 commission 합계로 재검산 가능해. 포트폴리오 거래 원장과 일별 equity는 별도 CSV로 저장했어.

## 세 window의 Candidate 결과

| 지표 | P2-1 | P2-2 | P3-2 |
|---|---:|---:|---:|
| 누적수익률 (%) | 15.3383 | 75.1127 | 85.7572 |
| CAGR (%) | 3.2965 | 10.4173 | 14.2220 |
| MDD (%) | -30.0210 | -31.8858 | -15.1355 |

세 window는 서로 다른 기간·모집단 조건의 독립 결과라서 차이를 기간 효과 하나로만 단정하지 않아.

## 실행 및 검증

- 파이프라인: PIT COMMON → latest Daily Update COMMON identity survivor → entry signal date의 exact raw KRX `MKTCAP >= 1조원` → 나머지에만 frozen FAST 신호 평가 → deterministic sequential portfolio replay.
- 기준 시점 이전/이후의 시총 대체값, 인접일, 보간, 전략 ledger 사후 필터는 사용하지 않았어. unresolved exact-cap signal은 인증 불가 조건이야.
- 초기 자본 2억원, 종목별 고정 매수예산 500만원, 종목 수 cap 없음, 현금 부족 시 전량 진입 skip, 기존 수수료/슬리피지/거래세와 valuation-only adjusted-close carry 계약을 적용했어.
- worker 10/10; 전략 평가 3501.0s, 순차 포트폴리오 재생 1.0s, 총 3623.8s; peak RSS 3191111680 (bytes on macOS; KiB on Linux).
- `validation`의 entry parity, exact MKTCAP, valuation carry, unresolved, daily-equity completeness, cash conservation, no-hidden-cap 검증을 모두 만족할 때만 인증 판정이야.
