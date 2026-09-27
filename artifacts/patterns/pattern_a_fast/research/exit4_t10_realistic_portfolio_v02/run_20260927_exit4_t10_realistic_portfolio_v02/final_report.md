# Exit4 T10 realistic portfolio comparison

- Work: `PATTERN_A_FAST_CORE_V2_EXIT4_T10_REALISTIC_PORTFOLIO_V02`
- Control: `PATTERN_A_FAST_FINAL_STRATEGY_V02`, Exit4 HWM drawdown 15pt
- Test: identical frozen eligible entry rows and strategy rules; only Exit4 HWM drawdown changes to 10pt
- Execution: next local trading day open; KRW 200M initial capital; KRW 5M target position; T+1 sale-proceeds release; existing commission, tax, slippage and reinvestment rules
- Position cap: none. Market cap: exact signal-date KRX raw MKTCAP >= KRW 1T; current-common identity and permanent exclusions reused from certified source runs
- Portfolio and win/loss return metrics are net of actual modeled execution costs. MFE/MAE remain price-path percentages.
- T10 exits come from the existing T10/T15 path analysis; only T10 and T15 data columns were used. No threshold sweep was rerun.

## Verdict

**`MIXED_NO_CLEAR_PORTFOLIO_WINNER`**

Window rule: support requires higher Final Asset and CAGR, an improved net win/loss measure, MDD no more than 1pp worse with no increase in -30/-50 tail counts, and positive realized P/L from incremental T10 fills. The final rule requires at least two of three windows.

## Account performance

Final Asset uses the execution-support-inclusive equity reported by the certified replay; positions still open at effective cutoff remain valued at the cutoff close.

| Window | Strategy | Final Asset (KRW) | Cum. return | CAGR | MDD | Total realized P/L net (KRW) | Turnover | Filled / realized | Cash-short skips |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P2-1 | T15 | 230,372,654 | 15.19% | 3.27% | -30.19% | -8,809,402 | 8.84x | 199 / 161 | 156 |
| P2-1 | T10 | 220,459,851 | 10.23% | 2.24% | -29.53% | -19,296,060 | 9.29x | 208 / 172 | 147 |
| P2-2 | T15 | 369,288,643 | 84.64% | 11.46% | -30.80% | 139,733,515 | 12.08x | 242 / 218 | 243 |
| P2-2 | T10 | 362,404,967 | 81.20% | 11.09% | -30.84% | 139,014,455 | 12.82x | 254 / 236 | 231 |
| P3-2 | T15 | 371,154,514 | 85.58% | 14.20% | -15.14% | 149,026,077 | 11.51x | 228 / 207 | 177 |
| P3-2 | T10 | 385,224,724 | 92.61% | 15.11% | -15.14% | 164,338,040 | 12.42x | 245 / 224 | 160 |
| P2-1 | T10_MINUS_T15 | -9,912,802 | -4.96% | -1.03% | 0.67% | -10,486,659 | 0.44x | 9 / 11 | -9 |
| P2-2 | T10_MINUS_T15 | -6,883,676 | -3.44% | -0.37% | -0.04% | -719,060 | 0.74x | 12 / 18 | -12 |
| P3-2 | T10_MINUS_T15 | 14,070,210 | 7.04% | 0.92% | 0.00% | 15,311,964 | 0.92x | 17 / 17 | -17 |

## Win/Loss statistics

| Window | Strategy | Closed | Win / loss / flat | Win rate | Avg / median win | Avg / median loss | Payoff | Profit factor | Expectancy / trade |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P2-1 | T15 | 161 | 37 / 124 / 0 | 22.98% | 49.93% / 26.72% | -16.46% / -16.23% | 3.03 | 0.91 | -1.20%
| P2-1 | T10 | 172 | 39 / 133 / 0 | 22.67% | 46.10% / 28.84% | -16.57% / -16.35% | 2.78 | 0.82 | -2.36%
| P2-2 | T15 | 218 | 66 / 152 / 0 | 30.28% | 80.99% / 64.07% | -16.80% / -16.19% | 4.82 | 2.11 | 12.81%
| P2-2 | T10 | 236 | 68 / 168 / 0 | 28.81% | 82.15% / 61.95% | -16.69% / -16.27% | 4.92 | 2.00 | 11.79%
| P3-2 | T15 | 207 | 63 / 144 / 0 | 30.43% | 85.53% / 77.14% | -16.68% / -16.32% | 5.13 | 2.26 | 14.43%
| P3-2 | T10 | 224 | 69 / 155 / 0 | 30.80% | 84.54% / 70.77% | -16.35% / -16.34% | 5.17 | 2.31 | 14.73%

## Return distribution

Counts use net realized trade returns after costs.

| Window | Strategy | Mean | Median | P25 / P75 | >= +20% | >= +30% | >= +50% | >= +100% | >= +200% | <= -15% | <= -30% | <= -50% | <= -60% |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P2-1 | T15 | -1.20% | -15.69% | -16.87% / -11.66% | 25 | 17 | 11 | 7 | 1 | 107 | 2 | 0 | 0 |
| P2-1 | T10 | -2.36% | -15.73% | -16.99% / -12.40% | 29 | 19 | 11 | 5 | 0 | 116 | 2 | 0 | 0 |
| P2-2 | T15 | 12.81% | -15.52% | -16.68% / 17.94% | 53 | 44 | 37 | 21 | 3 | 125 | 5 | 1 | 0 |
| P2-2 | T10 | 11.79% | -15.60% | -16.92% / 16.54% | 56 | 47 | 40 | 21 | 3 | 137 | 4 | 1 | 0 |
| P3-2 | T15 | 14.43% | -15.59% | -16.93% / 20.01% | 52 | 48 | 43 | 21 | 2 | 119 | 2 | 0 | 0 |
| P3-2 | T10 | 14.73% | -15.50% | -16.86% / 24.83% | 58 | 54 | 47 | 20 | 3 | 125 | 1 | 0 | 0 |

## MFE / MAE

Capture ratio is net realized return after costs divided by MFE, for closed fills with positive MFE. Giveback is MFE minus that net realized return. MFE/MAE distributions are across filled trades; capture and giveback use closed fills.

| Window | Strategy | MFE mean / median / P25 / P75 | MAE mean / median / P25 / P75 | Median net giveback | Median net capture | +50 / +100 capture |
|---|---|---:|---:|---:|---:|---:|
| P2-1 | T15 | 30.34% / 15.63% / 4.85% / 38.62% | -15.31% / -16.17% / -17.59% / -11.10% | 22.60pp | -1.32 | 0.73 / 0.87 |
| P2-1 | T10 | 28.58% / 14.02% / 4.77% / 36.92% | -14.91% / -16.14% / -17.27% / -11.48% | 22.36pp | -1.45 | 0.73 / 0.87 |
| P2-2 | T15 | 49.49% / 21.20% / 5.47% / 62.31% | -15.99% / -16.36% / -17.79% / -11.65% | 24.55pp | -0.93 | 0.80 / 0.87 |
| P2-2 | T10 | 45.32% / 19.24% / 5.08% / 53.83% | -16.24% / -16.49% / -18.01% / -12.27% | 24.16pp | -0.97 | 0.82 / 0.88 |
| P3-2 | T15 | 49.27% / 19.66% / 4.99% / 67.60% | -15.33% / -16.32% / -17.90% / -11.61% | 24.41pp | -0.90 | 0.80 / 0.87 |
| P3-2 | T10 | 48.79% / 19.60% / 4.78% / 68.22% | -15.07% / -16.33% / -17.82% / -11.28% | 24.55pp | -0.90 | 0.76 / 0.87 |

## Holding & capital rotation

| Window | Strategy | Mean / median / P25 / P75 holding | <=60 / <=120 / >250 days | Avg invested / idle capital | Turnover | Cash skips | Early executed Exit4 | T10-only fills vs T15 cash skips | Their realized P/L (KRW) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| P2-1 | T15 | 170.81 / 78.00 / 32.00 / 183.50d | 80 / 124 / 35 | 86.37% / 13.63% | 8.84x | 156 | — | — | — |
| P2-1 | T10 | 158.34 / 79.50 / 31.75 / 177.50d | 85 / 132 / 35 | 84.92% / 15.08% | 9.29x | 147 | 19 | 23 | -7,914,255 |
| P2-2 | T15 | 196.81 / 90.50 / 35.00 / 215.25d | 94 / 145 / 51 | 87.72% / 12.28% | 12.08x | 243 | — | — | — |
| P2-2 | T10 | 180.65 / 78.00 / 29.25 / 193.50d | 107 / 158 / 46 | 86.74% / 13.26% | 12.82x | 231 | 26 | 35 | -1,206,818 |
| P3-2 | T15 | 155.58 / 79.00 / 32.75 / 205.00d | 96 / 141 / 49 | 77.81% / 22.19% | 11.51x | 177 | — | — | — |
| P3-2 | T10 | 144.92 / 73.00 / 31.00 / 189.00d | 108 / 157 / 47 | 77.38% / 22.62% | 12.42x | 160 | 25 | 23 | 17,952,369 |

Holding rows show mean / median / P25 / P75 in trading sessions. Incremental fills are eligible entries that T10 actually executed while T15 skipped for insufficient cash. Cash is fungible, so the comparison does not earmark an individual exit's proceeds to one entry.

## Exit structure

Path exit counts/returns use the strategy ledger for all eligible entries. Portfolio closed-fill columns show the subset that actually executed and realized; score drawdown is measured at the T15/T10 signal and is only available for Exit4 rows in the archived threshold comparison.

| Window | Strategy | Exit class | Path count | Closed fills | Path return avg / median | Path hold avg / median | Actual score drawdown avg / median |
|---|---|---|---:|---:|---:|---:|---:|
| P2-1 | T15 | Exit4 | 86 | 40 | 35.87% / 25.02% | 181.24 / 135.50d | 23.37 / 21.55pt (n=86) |
| P2-1 | T15 | Exit3 | 8 | 4 | 29.17% / 18.93% | 386.25 / 336.00d | — |
| P2-1 | T15 | Loss Guard | 197 | 117 | -16.46% / -15.94% | 87.06 / 46.00d | — |
| P2-1 | T15 | Other | 0 | 0 | —% / —% | — / —d | — |
| P2-1 | T15 | No exit | 64 | 0 | 23.74% / 20.68% | 397.97 / 292.00d | — |
| P2-1 | T10 | Exit4 | 96 | 45 | 33.21% / 24.39% | 182.86 / 136.50d | 18.85 / 16.39pt (n=96) |
| P2-1 | T10 | Exit3 | 5 | 2 | 11.54% / 12.19% | 394.00 / 304.00d | — |
| P2-1 | T10 | Loss Guard | 197 | 125 | -16.46% / -15.94% | 87.06 / 46.00d | — |
| P2-1 | T10 | Other | 0 | 0 | —% / —% | — / —d | — |
| P2-1 | T10 | No exit | 57 | 0 | 22.28% / 20.09% | 354.84 / 197.00d | — |
| P2-2 | T15 | Exit4 | 162 | 73 | 61.88% / 51.84% | 281.94 / 160.50d | 25.34 / 22.91pt (n=162) |
| P2-2 | T15 | Exit3 | 16 | 8 | 22.85% / 13.56% | 410.06 / 317.00d | — |
| P2-2 | T15 | Loss Guard | 268 | 137 | -16.17% / -15.80% | 79.96 / 42.00d | — |
| P2-2 | T15 | Other | 0 | 0 | —% / —% | — / —d | — |
| P2-2 | T15 | No exit | 39 | 0 | 35.74% / 17.05% | 412.72 / 287.00d | — |
| P2-2 | T10 | Exit4 | 174 | 78 | 59.05% / 48.88% | 270.24 / 156.00d | 20.75 / 18.55pt (n=174) |
| P2-2 | T10 | Exit3 | 11 | 7 | 14.17% / 4.97% | 387.36 / 302.00d | — |
| P2-2 | T10 | Loss Guard | 268 | 151 | -16.17% / -15.80% | 79.96 / 42.00d | — |
| P2-2 | T10 | Other | 0 | 0 | —% / —% | — / —d | — |
| P2-2 | T10 | No exit | 32 | 0 | 40.49% / 19.12% | 399.03 / 284.50d | — |
| P3-2 | T15 | Exit4 | 126 | 65 | 72.46% / 68.14% | 246.61 / 171.00d | 26.16 / 23.28pt (n=126) |
| P3-2 | T15 | Exit3 | 12 | 9 | 15.78% / 13.25% | 272.25 / 263.00d | — |
| P3-2 | T15 | Loss Guard | 231 | 133 | -16.15% / -15.75% | 71.24 / 40.00d | — |
| P3-2 | T15 | Other | 0 | 0 | —% / —% | — / —d | — |
| P3-2 | T15 | No exit | 36 | 0 | 40.47% / 19.12% | 284.00 / 240.50d | — |
| P3-2 | T10 | Exit4 | 135 | 73 | 69.13% / 59.02% | 232.76 / 167.00d | 21.15 / 18.77pt (n=135) |
| P3-2 | T10 | Exit3 | 9 | 6 | 15.56% / 12.19% | 269.00 / 224.00d | — |
| P3-2 | T10 | Loss Guard | 231 | 145 | -16.15% / -15.75% | 71.24 / 40.00d | — |
| P3-2 | T10 | Other | 0 | 0 | —% / —% | — / —d | — |
| P3-2 | T10 | No exit | 30 | 0 | 43.39% / 19.12% | 275.80 / 240.50d | — |

## Winner impact

| Window | Both filled & closed | +50 gained / lost | +100 gained / lost | +200 gained / lost | T10 / T15 better paired trades | Median paired return delta |
|---|---:|---:|---:|---:|---:|---:|
| P2-1 | 152 | 2 / 1 | 0 / 1 | 0 / 1 | 9 / 6 | 0.00pp |
| P2-2 | 197 | 2 / 0 | 0 / 2 | 0 / 1 | 8 / 11 | 0.00pp |
| P3-2 | 202 | 2 / 1 | 0 / 3 | 0 / 0 | 8 / 10 | 0.00pp |

- P2-1: T15 winner → T10 loser/flat `0` (loser `0`, flat `0`); T15 loser/flat → T10 winner `0`. Paired P/L delta after excluding top 1 / top 5 T15 contributors: 1,226,936 / 2,833,282 KRW.
- P2-2: T15 winner → T10 loser/flat `0` (loser `0`, flat `0`); T15 loser/flat → T10 winner `0`. Paired P/L delta after excluding top 1 / top 5 T15 contributors: -2,574,554 / -255,840 KRW.
- P3-2: T15 winner → T10 loser/flat `0` (loser `0`, flat `0`); T15 loser/flat → T10 winner `0`. Paired P/L delta after excluding top 1 / top 5 T15 contributors: -2,712,844 / -2,712,844 KRW.

The two sensitivity totals use trades filled and closed in both portfolios and remove the largest T15 realized P/L contributors. They are paired-trade attribution checks, not recomputed account curves. The 10 largest T10 portfolio-contribution reductions are in `winner_impact.csv`; the full paired ledger includes exit reasons, exit dates and holding-day deltas.

## Tail impact

| Window | <=-30 T15 / T10 (loss P/L KRW) | <=-50 T15 / T10 (loss P/L KRW) | <=-60 T15 / T10 | T15 <=-30 improved to above -30 | T15 <=-50 improved to above -50 |
|---|---:|---:|---:|---:|---:|
| P2-1 | 2 / 2 (-3,245,534 / -3,245,534) | 0 / 0 (0 / 0) | 0 / 0 | 0 | 0 |
| P2-2 | 5 / 4 (-9,949,473 / -7,733,027) | 1 / 1 (-2,730,835 / -2,730,835) | 0 / 0 | 0 | 0 |
| P3-2 | 2 / 1 (-3,961,414 / -1,685,487) | 0 / 0 (0 / 0) | 0 / 0 | 0 | 0 |

## Window consistency

| Window | T10 advantage supported | Final asset up | CAGR up | Structure improved | MDD delta | Tail not worse | Incremental fill P/L positive |
|---|---|---|---|---|---:|---|---|
| P2-1 | False | False | False | False | 0.67pp | True | False |
| P2-2 | False | False | False | False | -0.04pp | True | False |
| P3-2 | True | True | True | True | 0.00pp | True | True |


## Window-specific T10 vs T15 metric table

Delta is T10 minus T15; win-rate delta is in percentage points. Windows overlap, so their account assets are not pooled.

### P2-1

| Metric | T15 | T10 | Delta |
|---|---:|---:|---:|
| Final Asset (KRW) | 230,372,654 | 220,459,851 | -9,912,802 |
| Cumulative return (%) | 15.19 | 10.23 | -4.96 |
| CAGR (%) | 3.27 | 2.24 | -1.03 |
| MDD (%) | -30.19 | -29.53 | 0.67 |
| Win rate (%) | 22.98 | 22.67 | -0.31 |
| Mean net realized return (%) | -1.20 | -2.36 | -1.15 |
| Median net realized return (%) | -15.69 | -15.73 | -0.04 |
| Profit factor | 0.91 | 0.82 | -0.09 |
| Median MFE (%) | 15.63 | 14.02 | -1.61 |
| Median MAE (%) | -16.17 | -16.14 | 0.03 |
| Median net profit capture | -1.32 | -1.45 | -0.13 |
| Median holding days | 78.00 | 79.50 | 1.50 |
| Mean holding days | 170.81 | 158.34 | -12.48 |
| Holding days P25 | 32.00 | 31.75 | -0.25 |
| Holding days P75 | 183.50 | 177.50 | -6.00 |
| Turnover multiple | 8.84 | 9.29 | 0.44 |
| Cash shortage skips | 156 | 147 | -9 |
| Net return >= +50% count | 11 | 11 | 0 |
| Net return >= +100% count | 7 | 5 | -2 |
| Net return <= -30% count | 2 | 2 | 0 |
| Net return <= -50% count | 0 | 0 | 0 |
| Average invested capital (%) | 86.37 | 84.92 | -1.45 |
| Average idle cash (%) | 13.63 | 15.08 | 1.45 |

### P2-2

| Metric | T15 | T10 | Delta |
|---|---:|---:|---:|
| Final Asset (KRW) | 369,288,643 | 362,404,967 | -6,883,676 |
| Cumulative return (%) | 84.64 | 81.20 | -3.44 |
| CAGR (%) | 11.46 | 11.09 | -0.37 |
| MDD (%) | -30.80 | -30.84 | -0.04 |
| Win rate (%) | 30.28 | 28.81 | -1.46 |
| Mean net realized return (%) | 12.81 | 11.79 | -1.02 |
| Median net realized return (%) | -15.52 | -15.60 | -0.08 |
| Profit factor | 2.11 | 2.00 | -0.10 |
| Median MFE (%) | 21.20 | 19.24 | -1.96 |
| Median MAE (%) | -16.36 | -16.49 | -0.13 |
| Median net profit capture | -0.93 | -0.97 | -0.03 |
| Median holding days | 90.50 | 78.00 | -12.50 |
| Mean holding days | 196.81 | 180.65 | -16.16 |
| Holding days P25 | 35.00 | 29.25 | -5.75 |
| Holding days P75 | 215.25 | 193.50 | -21.75 |
| Turnover multiple | 12.08 | 12.82 | 0.74 |
| Cash shortage skips | 243 | 231 | -12 |
| Net return >= +50% count | 37 | 40 | 3 |
| Net return >= +100% count | 21 | 21 | 0 |
| Net return <= -30% count | 5 | 4 | -1 |
| Net return <= -50% count | 1 | 1 | 0 |
| Average invested capital (%) | 87.72 | 86.74 | -0.97 |
| Average idle cash (%) | 12.28 | 13.26 | 0.97 |

### P3-2

| Metric | T15 | T10 | Delta |
|---|---:|---:|---:|
| Final Asset (KRW) | 371,154,514 | 385,224,724 | 14,070,210 |
| Cumulative return (%) | 85.58 | 92.61 | 7.04 |
| CAGR (%) | 14.20 | 15.11 | 0.92 |
| MDD (%) | -15.14 | -15.14 | 0.00 |
| Win rate (%) | 30.43 | 30.80 | 0.37 |
| Mean net realized return (%) | 14.43 | 14.73 | 0.30 |
| Median net realized return (%) | -15.59 | -15.50 | 0.09 |
| Profit factor | 2.26 | 2.31 | 0.06 |
| Median MFE (%) | 19.66 | 19.60 | -0.06 |
| Median MAE (%) | -16.32 | -16.33 | -0.01 |
| Median net profit capture | -0.90 | -0.90 | 0.00 |
| Median holding days | 79.00 | 73.00 | -6.00 |
| Mean holding days | 155.58 | 144.92 | -10.66 |
| Holding days P25 | 32.75 | 31.00 | -1.75 |
| Holding days P75 | 205.00 | 189.00 | -16.00 |
| Turnover multiple | 11.51 | 12.42 | 0.92 |
| Cash shortage skips | 177 | 160 | -17 |
| Net return >= +50% count | 43 | 47 | 4 |
| Net return >= +100% count | 21 | 20 | -1 |
| Net return <= -30% count | 2 | 1 | -1 |
| Net return <= -50% count | 0 | 0 | 0 |
| Average invested capital (%) | 77.81 | 77.38 | -0.43 |
| Average idle cash (%) | 22.19 | 22.62 | 0.43 |

## Final interpretation

Result: `MIXED_NO_CLEAR_PORTFOLIO_WINNER`. See each window table for win-rate pp, mean/median return, MFE/MAE, holding, turnover, tail and account deltas; the rotation and winner/tail sections quantify cash reuse and large-winner/loss transitions. This is a research comparison only; it does not promote or alter the production strategy.

## Validation & provenance

- P2-1: certified T15 replay parity PASS; archived T15 path alignment PASS (118 affected trades); entry identity parity PASS (355 rows); all non-exit strategy fields parity PASS; frozen execution/PIT contract PASS; unresolved=0; cash conservation=True.
- P2-2: certified T15 replay parity PASS; archived T15 path alignment PASS (202 affected trades); entry identity parity PASS (485 rows); all non-exit strategy fields parity PASS; frozen execution/PIT contract PASS; unresolved=0; cash conservation=True.
- P3-2: certified T15 replay parity PASS; archived T15 path alignment PASS (159 affected trades); entry identity parity PASS (405 rows); all non-exit strategy fields parity PASS; frozen execution/PIT contract PASS; unresolved=0; cash conservation=True.
- P2-2: RepositoryV2 returned no composite frame for 336570. Certified strategy-ledger entry opens were used only for cash checks; T15/T10 cash-skip entries=1/1; neither replay filled a fallback ticker, so no position mark or exit was simulated from that sparse row. Any such fill blocks validation.
- P3-2: RepositoryV2 returned no composite frame for 336570. Certified strategy-ledger entry opens were used only for cash checks; T15/T10 cash-skip entries=1/1; neither replay filled a fallback ticker, so no position mark or exit was simulated from that sparse row. Any such fill blocks validation.
- Source T15 strategy ledgers are the certified 2026-09-26 realistic portfolio artifacts; exact signal-date raw PIT market-cap audit was reused without network calls.
- Baseline source hashes and effective PIT authority hashes are recorded in `summary.json`.
- Pooled account-level performance is not summed because the windows overlap and each has its own start/end; cross-window consistency is reported instead.

## Git

- Start HEAD: `3c8a219ca620f828dfbf5068247e570de3f908aa`
- End HEAD: `3c8a219ca620f828dfbf5068247e570de3f908aa`
- Commit: not created
- Push: not performed
- HEAD == origin/main: `True`
