# KODEX200 V2 VS V3 SAME WINDOW BACKTEST V01

## 판정

- 최종 상태: `COMPLETE`
- 전략 공식 승격/폐기 판정: 이번 작업에서 하지 않음
- V4 / Julia: 실행하지 않음
- 네트워크 요청: `0` (연장 이후 backtest는 로컬 raw만 사용)

## Raw authority 연장

- target: `data/raw/stocks/069500.parquet`
- before: `3097 rows / 2014-01-02 ~ 2026-08-14`
- after: `3101 rows / 2014-01-02 ~ 2026-08-21`
- added trading dates: `['2026-08-18', '2026-08-19', '2026-08-20', '2026-08-21']`
- pre-extension values preserved: `True`
- same-source overlap: `1625 rows, 0 field mismatches`
- 8/15~8/17은 비거래일이며 8/18~8/21만 4행 추가했다.

## Evaluation contract

- data period: `2014-01-02 ~ 2026-08-21` (3101 rows)
- evaluation: `2021-04-01`
- signal cutoff: `2026-08-14`
- execution support end: `2026-08-21`
- final valuation: `2026-08-21 CLOSE`
- pre-2021 lookback: 유지
- cost model: `GROSS / NO_COST_MODEL`
- ETF historical market-cap authority: 기존과 동일한 research bypass만 적용

## Matched entry

- common entry count: `16`
- matched entry identity: `{'signal_date_match': True, 'execution_date_match': True, 'entry_open_match': True, 'duplicate_entries': 0}`
| strategy | trade_count | mean_return_pct | median_return_pct | win_rate_pct | mean_mfe_pct | mean_mae_pct | mean_holding_days |
| --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 16 | 55.563125 | -11.02 | 43.75 | 70.60875 | -11.98875 | 205.0625 |
| V3 | 16 | 157.990625 | 160.77 | 100.0 | 307.09875 | -12.5525 | 448.9375 |

### Return thresholds

| metric | V2 | V3 |
| --- | --- | --- |
| le_neg_15_pct | 2 | 0 |
| le_neg_30_pct | 0 | 0 |
| le_neg_40_pct | 0 | 0 |
| ge_pos_50_pct | 7 | 16 |
| ge_pos_100_pct | 7 | 16 |

- paired V3 - V2: `{'paired_count': 16, 'mean_v3_minus_v2_return_delta_pct': 102.4275, 'median_v3_minus_v2_return_delta_pct': 171.225, 'improved_count': 16, 'worsened_count': 0, 'same_count': 0}`

## Sequential actual path

| strategy | total_return_pct | cagr_pct | mdd_pct | trade_count | exposure_ratio_pct | final_equity | mean_trade_return_pct | median_trade_return_pct | win_rate_pct |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V2 | 125.509971 | 16.290871 | -22.436218 | 2 | 30.734292 | 2.2550997131 | 71.84 | 71.84 | 50.0 |
| V3 | 160.593392 | 19.453952 | -35.50942 | 1 | 40.953823 | 2.6059339177 | 160.59 | 160.59 | 100.0 |
| Buy & Hold | 158.867836 | 19.306753 | -40.928853 |  | 100.0 | 2.5886783571 |  |  |  |

### Exit reasons

- V2: `{'LOSS_GUARD_CLOSE_LE_NEG_15': 1, 'EXIT4_SCORE_DRAWDOWN_GE_15': 1}`
- V3: `{'HARD_EXIT': 1}`

## 핵심 질문 답변

1. 동일 구간에서 V3 total return > V2: `True`; CAGR > V2: `True`.
2. V3 median return > V2: `True`; win rate > V2: `True`.
3. V3의 <= -15/-30/-40% matched count는 `{'le_neg_15_pct': 0, 'le_neg_30_pct': 0, 'le_neg_40_pct': 0, 'ge_pos_50_pct': 16, 'ge_pos_100_pct': 16}`이며 V2는 `{'le_neg_15_pct': 2, 'le_neg_30_pct': 0, 'le_neg_40_pct': 0, 'ge_pos_50_pct': 7, 'ge_pos_100_pct': 7}`이다. Sequential MDD 차이는 `-13.073202%p`이다.
4. 수익 개선 대비 위험의 감수 가능 여부는 별도 투자판단으로 남기며, 이번 작업에서 공식 승격하지 않는다.
5. 개별주 비교의 전제(V2 우세)와 달리 KODEX200 same-window 결과는 V3 우세 방향이다: `True`.
6. 이전 장기 KODEX200 reference와 방향 일치: `True`.

## Buy & Hold reference

- `2021-04-01 OPEN` → `2026-08-21 CLOSE`: total `158.867836%`, CAGR `19.306753%`, MDD `-40.928853%`, final equity `2.5886783571`, exposure `100%`.

## 장기 reference 비교

- source: `artifacts/research/kodex200_four_strategy_reproduction_v01/summary.json`
- long-term V2: `{'total_return_pct': 166.541603, 'cagr_pct': 8.08248, 'mdd_pct': -35.962469, 'final_equity': 2.6654160323, 'exposure_ratio_pct': 44.365515, 'trade_count': 4}`
- long-term V3: `{'total_return_pct': 306.358047, 'cagr_pct': 11.757126, 'mdd_pct': -35.987929, 'final_equity': 4.0635804712, 'exposure_ratio_pct': 41.136584, 'trade_count': 3}`
- same direction: `True`

## Artifact

- `matched_trades.csv`
- `sequential_trades.csv`
- `daily_equity.csv`
- `summary.json`
- `report.md`
