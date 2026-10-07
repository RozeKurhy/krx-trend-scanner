| Level | Count |
|---|---:|
| CRITICAL | 0 |
| MAJOR | 1 |
| MINOR | 2 |

The MAJOR finding is the prior P3-2 NAV's use of prior closes for gaps without verified non-trading evidence; corrected MDD excludes those full portfolio dates. The two MINOR findings are that saved strategy ledgers were reused without replay and this diagnostic does not complete the official five-window review.

Final token: `FAST_CORE_V2_PORTFOLIO_VALUATION_GAP_CONTRACT_ALIGNMENT_V01_PASS`

## Scope and implementation audit

- The prior-close path now requires an exact `NON_TRADING_PLACEHOLDER` classification from the repository's narrow raw KRX predicate. `ADJUSTED_ANALYTICALLY_NONUSABLE` and `NEW_UNCLASSIFIED_GAP` never carry.
- Exact daily close remains first choice. One unobservable held position makes that entire day's portfolio NAV unobservable. MDD uses only valid NAV rows.
- Coverage uses official P3-2 daily equity dates through the effective end, excluding the execution-support-only date. The 90% gate is evaluated by integer numerator/denominator comparison before display rounding.
- Previous complete P3-2 artifacts were reused: CONTROL 405 trades, MA60 337 trades, ALIGNMENT 179 trades. No strategy signal, lifecycle, portfolio order replay, network call, or historical artifact rewrite was performed.

## Current-source gap reclassification

Exact local raw partitions were re-read for 116 unique ticker-market-date gaps: {'NEW_UNCLASSIFIED_GAP': 45, 'NON_TRADING_PLACEHOLDER': 71}.
The only carry-approved state is `NON_TRADING_PLACEHOLDER_V01`: exact complete KRX raw row with open/high/low zero, positive close, and volume/trading value zero. The adjusted-source-unusable state is not treated as non-trading proof.

## P3-2 MDD and coverage impact

| Strategy | Total days | Valid NAV | Unobservable | Coverage | Type | Saved MDD | Corrected MDD | Delta pp | Peak | Trough | Unclassified gaps | Affected tickers |
|---|---:|---:|---:|---:|---|---:|---:|---:|---|---|---:|---:|
| CONTROL | 1139 | 1104 | 35 | 96.9271% | OBSERVED | -15.135469% | -15.135469% | 0.000000 | 2022-05-02 | 2023-03-14 | 37 | 5 |
| MA60_FAIL_CLOSED | 1139 | 1099 | 40 | 96.4881% | OBSERVED | -14.641254% | -14.641254% | 0.000000 | 2026-02-26 | 2026-03-04 | 40 | 3 |
| BULLISH_ALIGNMENT | 1139 | 1099 | 40 | 96.4881% | OBSERVED | -11.375289% | -11.375289% | 0.000000 | 2023-07-31 | 2023-10-31 | 40 | 3 |

`Observed MDD` is based on the remaining observable days; it is not an exact full-period drawdown. The exact coverage numerator, denominator, peak/trough/recovery dates, gap intervals, and ticker/date audit are in the CSV and JSON artifacts.

## Regression parity and integrity

- Trade ledgers keep their original SHA-256 values before and after this diagnosis. Required entry/exit dates and prices, terminal return, PIT market-cap source, identity, lifecycle, and trade-status fields were present and unchanged.
- All saved entries retain exact-date KRX Open API market-cap source and satisfy the 1T PIT floor.
- Original saved equity, strategy trade, and carry-audit files remain untouched; corrected NAV is a separate derived file.
- Network/API calls: 0. Strategy replay: 0. Portfolio event replay: 0.
- Official adoption: not evaluated; a separate five-window review remains required.

## Artifacts

- `summary.json` — source hashes, strategy metrics, and integrity status.
- `strategy_mdd_coverage.csv` — per-strategy corrected MDD and coverage comparison.
- `valuation_gap_reclassification_audit.csv` — current raw-source evidence and carry decision for each saved gap mark.
- `corrected_daily_equity.csv` — source and corrected NAV observation status, with unverified-gap dates nulled at portfolio level.
- `regression_parity.csv` — immutable trade-ledger and PIT/lifecycle field parity.
- `run_valuation_gap_contract_alignment.py` — report-only diagnostic runner.

## Implementation verification

- Focused regression suite: 17 passed across P2-1, P2-2, and P3-2 tests.
- Python compilation: passed for the three portfolio runners and the diagnostic runner.
- `git diff --check`: passed.
