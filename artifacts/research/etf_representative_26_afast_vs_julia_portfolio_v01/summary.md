# ETF 대표 26 A FAST vs Julia 현실 포트폴리오 V01

- Verdict: `ETF_REPRESENTATIVE_26_AFAST_VS_JULIA_REALISTIC_PORTFOLIO_COMPLETE`
- Universe: 사용자 고정 대표 ETF 26개; 현재 대표 ETF 고정 목록이라 survivorship bias가 있어.
- 데이터: KRX raw OHLCV; RAW_PRICE_LIMITATION=TRUE; adjusted price 사용 안 함.
- 기간: 2014-01-02 ~ 2026-08-31 (체결 지원 2026-09-01).
- 표본: SAMPLE_PASS (5개); 전체 candidate worker 10개.
- 포트폴리오: 초기 2억원, 종목당 최대 500만원, 정수 수량, 무레버리지, 현금 부족 시 CASH_SKIP, 동시 보유 제한 없음.
- 비용: 매수·매도 수수료 각 0.015%; 매수 슬리피지 +0.1%, 매도 -0.1%; ETF 매도세 0%.
- 고정 universe 최초 notional 상한: 26 × 500만원 = 1억3천만원, 초기자본의 65%. 계좌자산이 커지면 실질 상한 비율은 더 낮아질 수 있어.
- 427개 V03의 최초 투자비중에는 이와 같은 65% 구조 상한이 없어. 최종자산/CAGR 차이는 universe와 자본 활용 차이도 포함해.
- 427개 V03은 기존 committed 산출물만 읽었고 재실행하지 않았어.

## 포트폴리오 결과

| 전략 | 최종자산 | 총수익률 | CAGR | MDD | 평균 투자비중 | 평균 현금비중 | 실현 승률 | 실현 중앙값 | 중앙 보유 세션 | CASH_SKIP | 체결률 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 299,779,692원 | 49.89% | 3.25% | -9.84% | 21.63% | 78.37% | 47.69% | -11.84% | 188.0 | 0 | 100.00% |
| JULIA_STRATEGY_V00 | 316,482,695원 | 58.24% | 3.69% | -16.73% | 24.73% | 75.27% | 90.62% | 58.71% | 826.5 | 0 | 100.00% |

## 기존 V03 427과 비교

| 전략 | 지표 | V03 427 | 대표 26 | 26−427 |
|---|---|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 최종자산 | 400,075,799 원 | 299,779,692 원 | -100,296,107 원 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | CAGR | 5.63 % | 3.25 % | -2.38 % |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | MDD | -29.72 % | -9.84 % | 19.88 % |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 평균 투자비중 | 60.89 % | 21.63 % | -39.26 % |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 평균 현금비중 | 39.11 % | 78.37 % | 39.26 % |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 실현 승률 | 40.85 % | 47.69 % | 6.85 % |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 실현 중앙값 | -14.85 % | -11.84 % | 3.01 % |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | 중앙 보유 세션 | 196.00 세션 | 188.00 세션 | -8.00 세션 |
| JULIA_STRATEGY_V00 | 최종자산 | 451,686,151 원 | 316,482,695 원 | -135,203,456 원 |
| JULIA_STRATEGY_V00 | CAGR | 6.65 % | 3.69 % | -2.95 % |
| JULIA_STRATEGY_V00 | MDD | -36.59 % | -16.73 % | 19.86 % |
| JULIA_STRATEGY_V00 | 평균 투자비중 | 64.01 % | 24.73 % | -39.27 % |
| JULIA_STRATEGY_V00 | 평균 현금비중 | 35.99 % | 75.27 % | 39.27 % |
| JULIA_STRATEGY_V00 | 실현 승률 | 90.77 % | 90.62 % | -0.14 % |
| JULIA_STRATEGY_V00 | 실현 중앙값 | 53.17 % | 58.71 % | 5.54 % |
| JULIA_STRATEGY_V00 | 중앙 보유 세션 | 770.00 세션 | 826.50 세션 | 56.50 세션 |

## 그룹별 실현 기여

| 전략 | 그룹 | candidate | 체결 | 실현 | 승률 | 실현 중앙값 | 실현 손익 기여 |
|---|---|---:|---:|---:|---:|---:|---:|
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | MARKET_DOMESTIC | 5 | 5 | 5 | 60.00% | 40.97% | 11,249,624원 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | SECTOR_DOMESTIC | 50 | 50 | 45 | 44.44% | -12.48% | 39,565,611원 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | FOREIGN_MARKET | 7 | 7 | 5 | 80.00% | 59.04% | 13,758,663원 |
| PATTERN_A_FAST_FINAL_STRATEGY_V02 | COMMODITY_RESOURCE | 11 | 11 | 10 | 40.00% | -15.66% | 9,783,144원 |
| JULIA_STRATEGY_V00 | MARKET_DOMESTIC | 3 | 3 | 3 | 100.00% | 59.50% | 13,235,563원 |
| JULIA_STRATEGY_V00 | SECTOR_DOMESTIC | 28 | 28 | 21 | 85.71% | 48.82% | 53,601,257원 |
| JULIA_STRATEGY_V00 | FOREIGN_MARKET | 6 | 6 | 4 | 100.00% | 74.76% | 13,261,996원 |
| JULIA_STRATEGY_V00 | COMMODITY_RESOURCE | 5 | 5 | 4 | 100.00% | 30.70% | 11,563,744원 |

## 비평가 종목

- `0072R0 TIGER KRX금현물`: LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF;A_FAST_JULIA_NOT_READY_BY_CUTOFF
- `0080G0 KODEX 방산TOP10`: LESS_THAN_TWO_YEARS_LISTED_AT_CUTOFF;A_FAST_JULIA_NOT_READY_BY_CUTOFF
- `487240 KODEX AI전력핵심설비`: A_FAST_JULIA_NOT_READY_BY_CUTOFF

## Validation

- 고정 목록: 26종목; 미확인/무단 ETF: 0/0.
- 비평가: 3종목 (정상 분리). 원시 OHLCV 결측/세션 간격 문제는 별도 차단 조건이야.
- candidate 필요 가격 누락: 0; 음수 현금 / 레버리지 / 500만원 초과: 0 / 0.0 / 0.
- cutoff 이후 진입 / 미래 날짜 fallback / nearest-date fallback: 0 / 0 / 0.
- eligibility / 실행일 / 가격 / no-trade / same-day ordering mismatch: 0 / 0 / 0 / 0 / 0.
- 전체 candidate replay: 1회; portfolio battle: 1회 (전략별 replay 2회).

## 산출물

- `fixed_universe.csv`
- `candidate_trade_ledger.csv`
- `candidate_summary.json`
- `portfolio_trade_ledger.csv`
- `portfolio_metrics.csv`
- `execution_summary.csv`
- `equity_curve.csv`
- `annual_returns.csv`
- `group_contribution.csv`
- `comparison_vs_v03_427.csv`
- `validation.json`
- `preflight_sample.json`
