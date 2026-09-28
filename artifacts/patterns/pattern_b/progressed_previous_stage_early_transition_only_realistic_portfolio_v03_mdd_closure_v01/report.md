# Pattern B V03 Valuation-Only MDD Closure

- V03 original verdict: `HOLD` (preserved).
- Closure verdict: `OFFICIAL_STRATEGY_ADOPTED`.
- Only daily valuation, observed MDD, coverage, Gate D and Gate E were recalculated.
- Signals, states, entry/exit events, cash, costs, trade results, total return and CAGR were frozen.
- No full backtest, classifier, signal generation, order replay or terminal execution was run.

## Approved carry source validation

- Exact identities: 5.
- Exact candidate identity/date rows source-validated: 2057.
- Carry marks actually used in portfolio valuation: 3641.
- Every carry row used a prior normal adjusted close; KRX placeholder raw close was never used as the valuation price.
- Every carry record has `used_for_execution=False`.

| Ticker | ISU_CD | Approved dates validated | Portfolio valuation carry marks applied |
|---|---|---:|---:|
| 019490 | KR7019490002 | 396 | 1980 |
| 019570 | KR7019570001 | 37 | 37 |
| 066790 | KR7066790007 | 679 | 679 |
| 083660 | KR7083660001 | 422 | 422 |
| 103230 | KR7103230009 | 523 | 523 |

## Five-window closure

| Window | Coverage | MDD | MDD type | V2 MDD | Deterioration (pp) | D | E | Carry marks | Remaining unresolved marks |
|---|---:|---:|---|---:|---:|---|---|---:|---:|
| P1 | 95.27% | -16.2092% | OBSERVED | -52.2497% | -36.0405 | PASS | PASS | 2057 | 223 |
| P2-1 | 98.71% | -22.6397% | OBSERVED | -32.7090% | -10.0693 | PASS | PASS | 396 | 14 |
| P2-2 | 92.65% | -22.6397% | OBSERVED | -34.5353% | -11.8956 | PASS | PASS | 396 | 178 |
| P3-1 | 98.44% | -19.6158% | OBSERVED | -37.3412% | -17.7254 | PASS | PASS | 396 | 13 |
| P3-2 | 91.13% | -19.6158% | OBSERVED | -38.4609% | -18.8451 | PASS | PASS | 396 | 166 |

## Frozen return and control gates

The existing V03 Total Return, CAGR, terminal return/equity, and Gate A/B/C evidence were read-only inputs to this closure. Their source files are hash-recorded in `source_hashes.json`.

## Validation

`validation.json` records exact carry-date, PIT, raw predicate, prior-price, execution isolation, baseline valid-equity parity, cash-path, position-count, and 25-gate checks.
`unresolved_valuation_gaps.csv` lists 594 remaining unmarked held-position valuations; `unresolved_gap_spans.csv` records 52 identity/position spans with a maximum of 19 consecutive sessions. All remain unresolved as instructed.
