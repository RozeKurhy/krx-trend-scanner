# MARKET INDEX ETF FIVE UNIVERSE FOUR STRATEGY BACKTEST V01

## Result

- Status: `COMPLETE`
- Work date: `2026-09-15 KST`
- Starting HEAD: `ee94fa58c2d3d294d8cd5096c195f43502a15d8c`
- Branch: `codex/fastcore-fundamentals-simple-backtest-v01`
- Scope: 5 specified KODEX market-index ETFs, LONG RANGE + SAME WINDOW, frozen V2/V3/V4/Julia plus Buy & Hold reference
- Production strategy changes: none
- Full repository pytest: not run, per `w.md`

## Data authority

All final backtests used local raw KRX ETF price authority only. No adjusted/raw splice, synthetic values, interpolation, or broad refresh was used.

| Ticker | Authority period used | Rows through support | Action |
| --- | --- | ---: | --- |
| 229200 | 2015-10-01 ~ 2026-08-21 | 2,671 | Extended by 4 dates: 2026-08-18 ~ 2026-08-21 |
| 292190 | 2018-03-26 ~ 2026-08-21 | 2,063 | Existing support retained |
| 226490 | 2015-08-24 ~ 2026-08-21 | 2,697 | Existing support retained |
| 156080 | 2020-01-02 ~ 2026-08-21 | 1,594 | Created from local KRX raw source; 35 phantom holiday rows filtered using the existing provider rule |
| 226980 | 2020-01-02 ~ 2026-08-21 | 1,628 | Created from local KRX raw source; 1 phantom holiday row filtered using the existing provider rule |

All 10 ETF/run combinations completed. 156080 and 226980 had zero accepted common entries after the frozen 300M KRW 20-day average trading-value filter; they were recorded as valid zero-trade runs, with Buy & Hold still calculated.

## Strategy comparison summary

Counts are out of 5 ETFs. MDD wins use the less-negative value as the better result.

| Run | V3 sequential total / CAGR / MDD wins vs V2 | V4 total / CAGR / MDD | Julia total / CAGR / MDD |
| --- | --- | --- | --- |
| LONG RANGE | 1 / 1 / 0 | 0 / 0 / 1 | 1 / 1 / 0 |
| SAME WINDOW | 2 / 2 / 0 | 1 / 1 / 1 | 1 / 1 / 0 |

Matched-entry wins vs V2:

- LONG RANGE — V3 mean/median/win-rate: `2 / 2 / 2`; V4: `0 / 0 / 0`; Julia: `2 / 1 / 2`.
- SAME WINDOW — V3: `2 / 2 / 1`; V4: `1 / 2 / 1`; Julia: `1 / 1 / 1`.

The aggregate report answers the requested comparison questions without making an official promotion or retirement decision.

## Validation

- Runner syntax check: passed
- Focused validation: `6 passed`
- Raw authority: unique, ascending DatetimeIndex; required OHLCV + trading_value columns; support end `2026-08-21`; minimum five-year history
- Matched entry identity: 100%; duplicate matched entries: 0
- Sequential paths: no overlap; realized exit execution strictly after exit signal; open positions marked at support-end close
- Daily equity: total return, CAGR, and MDD reproduced from curves
- Backtest network requests under guard: `0`
- Final artifact files: `47`

## Network and background work

- Final artifact generation used local data and made no external API refresh request.
- Final backtest network audit: `0` requests.
- No background task was started by this work.
- API credentials or environment values were not read or printed.

## Artifacts

- Runner: `scripts/run_market_index_etf_four_strategy_v01.py`
- Focused tests: `tests/test_market_index_etf_four_strategy_v01.py`
- Aggregate report: `artifacts/research/market_index_etf_four_strategy_v01/aggregate_report.md`
- Aggregate summary: `artifacts/research/market_index_etf_four_strategy_v01/aggregate_summary.json`
- Per-ETF artifacts: `artifacts/research/market_index_etf_four_strategy_v01/<ticker>/`

## Git

- Commit/push: pending final commit.
- Unrelated pre-existing worktree changes were preserved and excluded from staging.

## Time summary

- Local authority inspection and minimal data preparation: completed
- Five-ETF backtest generation: completed
- Focused validation and report writing: completed
