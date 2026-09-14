# KODEX 200 Four Strategy Independent Reproduction V01

## 판정

- 최종 판정: `PARTIALLY_REPRODUCED`
- 상태: `COMPLETE`
- 네트워크 요청: `0`

## 데이터 계약

- source: `data/raw/stocks/069500.parquet`
- actual rows / period: `3097` / `2014-01-02 ~ 2026-08-14`
- classification: `NON_CANONICAL` / `PRICE_RETURN_ONLY`
- 분배금·배당 재투자: `미반영`
- 2014년 이전 lookback: `없음`
- evaluation: `2014-01-02`부터 실제 파일 범위, signal/execution support/final valuation은 `2026-08-14`
- 거래비용/세금/슬리피지: `GROSS / NO_COST_MODEL`

## ETF investability 예외

- historical market-cap authority가 없어 market-cap gate만 research bypass했다.
- 실제 parquet의 close와 trading_value로 price/20D liquidity 조건은 적용했다.
- synthetic market-cap 값은 output metric으로 보고하지 않았고, production 코드·applicability는 수정하지 않았다.

## Common entry

- common entry count: `35`
- weekly FAST evaluation errors: `0`
- entry identity: 4전략 matched replay에서 signal date / execution date / OPEN 모두 동일해야 통과한다.

## Matched 결과

| strategy | trade_count | mean_return_pct | median_return_pct | exit_reasons |
| --- | --- | --- | --- | --- |
| V2 | 35 | 24.100286 | -11.51 | {'LOSS_GUARD_CLOSE_LE_NEG_15': 20, 'EXIT4_SCORE_DRAWDOWN_GE_15': 15} |
| V3 | 35 | 94.699429 | 125.18 | {'SOFT_EXIT': 16, 'HARD_EXIT': 19} |
| V4 | 35 | 68.076 | 19.12 | {'WINNER_SOFT_WATCH_EXIT': 8, 'PRE_WINNER_PRICE_STRUCTURE_FAILURE': 11, 'WINNER_HARD_EXIT': 16} |
| Julia | 35 | 85.294286 | 57.77 | {'EXIT4_SCORE_DRAWDOWN_GE_15': 35} |

## Sequential 결과

| strategy | total_return_pct | cagr_pct | mdd_pct | trade_count | exposure_ratio_pct |
| --- | --- | --- | --- | --- | --- |
| V2 | 166.541603 | 8.08248 | -35.962469 | 4 | 44.365515 |
| V3 | 306.358047 | 11.757126 | -35.987929 | 3 | 41.136584 |
| V4 | 155.341036 | 7.715238 | -39.207744 | 4 | 39.489829 |
| Julia | 296.858678 | 11.547738 | -40.653863 | 2 | 50.403616 |
| Buy & Hold | 311.901198 | 11.877237 | -40.928853 | N/A | 100.0 |

## Exit reason

| strategy | exit_reason | count |
| --- | --- | --- |
| V2 | LOSS_GUARD_CLOSE_LE_NEG_15 | 2 |
| V2 | EXIT4_SCORE_DRAWDOWN_GE_15 | 2 |
| V3 | SOFT_EXIT | 2 |
| V3 | HARD_EXIT | 1 |
| V4 | WINNER_SOFT_WATCH_EXIT | 2 |
| V4 | PRE_WINNER_PRICE_STRUCTURE_FAILURE | 1 |
| V4 | WINNER_HARD_EXIT | 1 |
| Julia | EXIT4_SCORE_DRAWDOWN_GE_15 | 2 |

## 대표 best / worst trade

- V2 best: `{'entry_signal_date': '2025-05-30', 'terminal_return_pct': 155.37, 'exit_reason': 'EXIT4_SCORE_DRAWDOWN_GE_15'}`
- V2 worst: `{'entry_signal_date': '2017-01-06', 'terminal_return_pct': -16.35, 'exit_reason': 'LOSS_GUARD_CLOSE_LE_NEG_15'}`
- V3 best: `{'entry_signal_date': '2024-05-03', 'terminal_return_pct': 160.59, 'exit_reason': 'HARD_EXIT'}`
- V3 worst: `{'entry_signal_date': '2017-01-06', 'terminal_return_pct': 16.12, 'exit_reason': 'SOFT_EXIT'}`
- V4 best: `{'entry_signal_date': '2024-05-03', 'terminal_return_pct': 160.59, 'exit_reason': 'WINNER_HARD_EXIT'}`
- V4 worst: `{'entry_signal_date': '2019-11-15', 'terminal_return_pct': -29.62, 'exit_reason': 'PRE_WINNER_PRICE_STRUCTURE_FAILURE'}`
- Julia best: `{'entry_signal_date': '2024-05-03', 'terminal_return_pct': 148.24, 'exit_reason': 'EXIT4_SCORE_DRAWDOWN_GE_15'}`
- Julia worst: `{'entry_signal_date': '2017-01-06', 'terminal_return_pct': 59.87, 'exit_reason': 'EXIT4_SCORE_DRAWDOWN_GE_15'}`

## 이전 로컬 reference 비교

- reference metrics match: `False`
- first divergence: `{'label': 'V2.mdd_pct', 'cause': 'EQUITY_CURVE_MARKING_CONVENTION'}`
- reference 값은 맞추기 위한 목표가 아니라 독립 재현 후 비교 기준으로만 사용했다.

## 산출물

- `matched_trades.csv`: 35 common entries × 4 strategies
- `sequential_trades.csv`: 전략별 실제 순차 거래 경로
- `daily_equity.csv`: 전략별 및 Buy & Hold 일별 equity curve
- `summary.json`: 기간·계약·수치·reference 비교
- `report.md`: 감사용 요약
