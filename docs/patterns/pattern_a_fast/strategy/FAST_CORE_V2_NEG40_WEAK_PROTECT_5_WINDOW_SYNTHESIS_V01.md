# FAST Core V2 + NEG40 / WEAK Protect — 5-window synthesis V01

작성일: 2026-09-26 KST

## Executive verdict

Across the five available windows, Candidate consistently lowers the most severe `<= -50%` and `<= -60%` terminal-return tails. It does **not** consistently improve the entire loss distribution: `<= -30%` and `<= -40%` counts rise in every window. Mean terminal return is positive versus CONTROL in P2-1, P3-1, and P3-2, but lower in P2-2 and materially lower in the long P1 window. The `>= +100%` winner count is unchanged in P2-1, P2-2, P3-1, and P3-2, but falls by five in P1.

This pattern is consistent with describing Candidate as a **left-tail risk-control revision**, not a return-expansion strategy. The evidence is not uniformly favorable enough to decide promotion: medium-loss counts worsen throughout, P1 shows a mean-return and win-rate cost, and one portfolio-level test remains necessary. `A FAST Core V2.1` promotion is not decided here.

## Evidence selection and scope

Only the following completed final artifacts were used; no backtest or replay was run for this synthesis.

| Window | Selected authoritative result | Status used |
|---|---|---|
| P1 | `artifacts/backtests/p1_neg40_weak_protect_v01/run_20260925_standard_full_worker10_v01/raw_only_exclusion_closure_v02/p1_raw_only_certification_v02.json` + `summary.json` | `P1_CERTIFIED_PASS_WITH_AUTHORITATIVE_EXCLUSIONS` |
| P2-1 | `artifacts/backtests/p2_1_neg40_weak_protect_v01/run_20260924_cutoff_contract_recert_v01/p2_1_summary.json` | `COMPLETE` / `PROMISING`; ledger aggregate reconciliation PASS |
| P2-2 | `artifacts/backtests/p2_2_neg40_weak_protect_v01/run_20260924_final_corrective_v01/p2_2_summary.json` | `COMPLETE` / `PROMISING`; ledger aggregate reconciliation PASS |
| P3-1 | `artifacts/backtests/p3_1_neg40_weak_protect_v01/run_20260925_worker10_replay_v01/p3_1_summary.json` | `P3_1_REPLAY_PASS`; certified with authoritative exclusion |
| P3-2 | `artifacts/backtests/p3_2_neg40_weak_protect_v01/run_20260925_p3_2_worker10_corrective_v01/p3_2_summary.json` | `P3_2_REPLAY_PASS`; certified with authoritative exclusion |

Older CHECK_REQUIRED/intermediate artifacts were not used. In particular, the later P2-1 `run_20260925_corrective_full_recert_v02` is `CHECK_REQUIRED`, so its metrics are excluded; the passing P2-1 cutoff-contract result above retains `candidate_replay_matches_fix02=true` and all three ledger aggregate reconciliations. The older P2-2 and P3-1 CHECK_REQUIRED results were likewise excluded.

P1 is a raw-only exclusion-filtered certification: 43 exact permanent exclusions, 2,849 evaluation tickers, 2,867 identity segments, 4,983 matched pairs, and 4,982 numeric-comparable pairs. Its original full simulation remains `SIMULATION_PARTIAL` / raw `PARTIAL` after 12 worker failures; source raw SHA is preserved and simulation/recovery replay count is zero. The certification applies to the filtered evaluation population, not to a completed original simulation. The P1 summary's separate qualitative `strategy_assessment` field remains `CHECK_REQUIRED`; its scope-specific certification verdict is PASS, with zero effective remediable unresolved cases and only the allowed `096300_02` authoritative-final pair.

All rates/returns are percentages; paired delta is percentage points. Each pair is `CONTROL → Candidate`. “Numeric comparable” and paired-delta counts exclude an authoritative-final unresolved trade where present. The windows overlap and are not independent samples.

## 5-window comparison

### Returns and paired outcomes

| Window | Matched / numeric comparable | Positive-return rate | Mean terminal return | Median terminal return | Paired mean / median delta (pp) | Improved / worsened / same |
|---|---:|---:|---:|---:|---:|---:|
| P1 | 4,983 / 4,982 | 30.0682 → 29.2854 | 9.5307 → 8.8012 | -15.29 → -15.33 | -0.7296 / 0.0000 | 45 / 80 / 4,857 |
| P2-1 | 1,834 / 1,834 | 32.5518 → 32.5518 | 4.0830 → 4.1447 | -15.145 → -15.160 | +0.0617 / 0.0000 | 17 / 9 / 1,808 |
| P2-2 | 2,424 / 2,424 | 30.7343 → 30.4868 | 7.9321 → 7.7792 | -15.16 → -15.19 | -0.1530 / 0.0000 | 25 / 23 / 2,376 |
| P3-1 | 1,174 / 1,173 | 29.2413 → 29.2413 | 0.7892 → 0.8218 | -15.29 → -15.29 | +0.0326 / 0.0000 | 8 / 3 / 1,162 |
| P3-2 | 1,793 / 1,792 | 27.9018 → 27.9018 | 6.4094 → 6.4623 | -15.265 → -15.270 | +0.0529 / 0.0000 | 13 / 8 / 1,771 |

### Loss tails, large winners, and holding time

Tail/winner counts are `CONTROL → Candidate`; mean holding days are rounded to four decimals.

| Window | ≤ -30% | ≤ -40% | ≤ -50% | ≤ -60% | ≥ +30% | ≥ +50% | ≥ +100% | Mean holding days | Median holding days |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| P1 | 109 → 169 | 66 → 119 | 42 → 17 | 31 → 6 | 1,025 → 997 | 757 → 738 | 320 → 315 | 218.1355 → 200.8021 | 86 → 86 |
| P2-1 | 40 → 44 | 26 → 30 | 13 → 5 | 8 → 3 | 302 → 302 | 190 → 190 | 67 → 67 | 130.5458 → 126.1265 | 74 → 74 |
| P2-2 | 57 → 72 | 37 → 45 | 22 → 9 | 13 → 4 | 462 → 457 | 336 → 333 | 134 → 134 | 150.9550 → 142.1209 | 82 → 82 |
| P3-1 | 22 → 24 | 14 → 16 | 7 → 3 | 4 → 2 | 165 → 165 | 106 → 106 | 30 → 30 | 99.5320 → 98.1057 | 52 → 52 |
| P3-2 | 37 → 41 | 22 → 23 | 8 → 3 | 5 → 0 | 322 → 322 | 249 → 249 | 96 → 96 | 123.6730 → 121.4939 | 69 → 69 |

## Interpretation of the required questions

1. **Do deep tails repeatably shrink?** Yes. Candidate reduces both `<= -50%` and `<= -60%` in all five windows. The reductions in `<= -60%` are 25 (P1), 5 (P2-1), 9 (P2-2), 2 (P3-1), and 5 (P3-2) trades.
2. **What happens in medium-loss bands?** Both `<= -30%` and `<= -40%` increase in every window. At the same time, the `<= -50%`/`<= -60%` counts fall. The observed profile is therefore a reshaping of the left tail, not uniform loss reduction.
3. **Is mean-return preservation consistent?** No. Mean paired delta is positive but small in P2-1, P3-1, and P3-2; negative in P2-2; and substantially negative in P1. The long window is the clearest return trade-off.
4. **How far is the `>= +100%` winner count preserved?** It is exactly preserved in P2-1, P2-2, P3-1, and P3-2. P1 falls from 320 to 315. In P2-2, the `>= +30%` and `>= +50%` counts also decline slightly; they are unchanged in P3-1 and P3-2.
5. **How does long P1 differ?** P1 has the largest deep-tail reduction, but also the largest mean-return cost (-0.7296 pp), a lower positive-return rate (-0.7828 pp), more `<= -30%` and `<= -40%` outcomes, five fewer `>= +100%` winners, and the largest mean holding-period reduction (17.3334 days). Its median holding period is unchanged.
6. **Does holding time fall repeatedly?** Mean holding days decline in all five windows, by 1.4277–17.3334 days. Median holding days are unchanged in every window.
7. **Does “left-tail risk-control revision” fit?** It fits the repeated `<= -50%`/`<= -60%` reductions, provided the medium-loss deterioration and P1 return cost stay explicit. The current evidence does not establish a broad improvement or justify promotion by itself.

The five windows overlap, so these counts and deltas are a consistency check across horizons, **not** independent observations. No simple pooled total or independent-sample inference is used. P1 is emphasized as the longest window without replacing or overriding the shorter-window results.

## Last portfolio-level validation

The next authorized portfolio backtest should evaluate the exact frozen candidate and threshold without adding windows or changing the strategy. It should validate transaction costs and slippage, position sizing and concurrent holdings, turnover/capacity, portfolio drawdown and tail-risk measures, and whether the trade-level left-tail reductions survive portfolio aggregation. This synthesis does not execute that backtest, begin new strategy research, or decide `A FAST Core V2.1` promotion.
