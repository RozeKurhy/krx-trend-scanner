# P2-1 현실적 포트폴리오 비교

판정: `P2_1_REALISTIC_PORTFOLIO_BACKTEST_CERTIFIED`
대상: P2-1 only, 2021-01-04 ~ 2025-05-30 (execution support 2025-06-02)
Universe: 최신 Daily Update 2026-09-21 기준 현재 COMMON identity survivor; 신규 진입은 exact raw PIT MKTCAP >= 1조원만 허용.

## 핵심 결과

| 지표 | CONTROL | Candidate | Candidate − CONTROL |
|---|---:|---:|---:|
| 최종 자산 (지원일 처리 후) | 230,372,654 | 230,676,556 | 303,902 |
| 누적수익률 | 15.19% | 15.34% | 0.15%p |
| CAGR | 3.27% | 3.30% | 0.03%p |
| MDD | -30.19% | -30.02% | 0.17%p |
| 체결 거래 수 | 199 | 201 | 2 |
| 승률 | 22.98% | 23.03% | 0.05%p |
| 평균 보유 거래일 | 120.70 | 132.69 | 12.00 |
| 평균 자본 사용률 | 86.37% | 86.12% | -0.24%p |
| 회전율 배수 | 8.845x | 8.954x | 0.110x |
| `<= -40%` 실현 거래 | 0 | 3 | 3 |
| `>= +50%` 실현 거래 | 11 | 10 | -1 |

## 감사 요약

- 기존 전략 trade ledger 355행씩을 그대로 재사용했고 전략·entry 신호 재계산은 하지 않았어.
- 40개 동시 보유 시 실제 후보/현금 부족/슬롯 cap 차단은 [hidden_position_cap_audit.json](hidden_position_cap_audit.json)에 기록했어. 설정 포지션 한도는 없음.
- exact PIT 시총 PASS 365건 중 ledger 미포함 10건은 모두 유효기간 마지막 신호일의 다음 로컬 실행일이 entry cutoff를 넘은 사유야. [mcap365_to_trade355_reason_audit.csv](mcap365_to_trade355_reason_audit.csv)에서 전체 365건을 확인할 수 있어.
- 기존 valuation gap 96 ticker-date는 raw non-trading placeholder 74건과 adjusted source OHLC 관계 위반 22건으로 원천 행을 다시 대조했어. 직전 valid adjusted close는 daily portfolio MTM에만 사용했고, 각 stale mark의 날짜·가격·stale age 및 source 근거는 [valuation_gap_closure_audit.csv](valuation_gap_closure_audit.csv)에 있어.
- 체결과 전략 feature에는 carry를 사용하지 않았어. 기준 가격은 effective cutoff exact close이며 execution-support 이후 close는 사용하지 않았어.

## 경계와 해석

- 실행 규칙·점수·threshold는 동결. Candidate는 기존 P2-1 matched-entry 계약에 따라 V2 신호 진입 집합을 공유하고 exit overlay만 다르게 적용했어.
- 시총 미달 신호는 V2 re-entry state를 소비하지 않게 신호 평가 단계에서 제외했어. 따라서 과거 거래 ledger를 사후 단순 필터링한 결과가 아니야.
- 포트폴리오 cash/equity event replay는 날짜순 단일 스레드로 수행했어. 매도대금은 다음 평가 가능한 로컬 거래일부터 사용했고, 같은 시가에서는 재사용하지 않았어.
- MDD와 daily valuation은 P2-1 effective cutoff close까지야. `execution_support`에서 허용된 exit fill은 반영하고, 미청산 보유는 cutoff의 exact close로 평가했어. support 이후의 종가를 가져오지 않았어.
- 모든 수치는 [summary.json](summary.json), 포트폴리오 event ledger, daily equity 및 exact-date PIT audit로 재검산할 수 있어.
