# FastCore / Julia Strategy Backtest V01

# Deferred Handoff

## Status

`FASTCORE_JULIA_BACKTEST_STATUS=PAUSED`

`USER_REQUESTED_PAUSE=true`

`PAUSED_CODE_HEAD=9d24e7502e0f91dec03a617dc3ba0b38d422d3c7`

`FINAL_FIX_HEAD=false`

`PHASE3_EXECUTED=false`

`STEP2_EXECUTED=false`

## Repository / Branch

Repository:

`RozeKurhy/krx-trend-scanner`

Branch:

`codex/fastcore-julia-strategy-backtest-v01`

Base main:

`6e8a36f2c118af6dd17336a1ea601b5b0d4a5956`

Relevant fix commits:

1. `dff3a993a1af39bfb175525fdeb960d79c681083`
2. `3e0b161a5c62e47e84228dc53e0d2020aa220bd5`
3. `9d24e7502e0f91dec03a617dc3ba0b38d422d3c7`

Latest paused code head:

`9d24e7502e0f91dec03a617dc3ba0b38d422d3c7`

## Purpose of STEP1

FastCore vs Julia pure-strategy historical comparison.

Unlimited-capital / per-trade analysis only.

STEP1 does NOT include:

* account cash constraints
* portfolio sizing
* CAGR
* portfolio MDD
* weekly buy scheduling
* portfolio-level opportunity cost

Those belong to later STEP2.

## Frozen Strategy Difference

FastCore and Julia must use the same:

* entry contract
* Pattern A conditions
* FAST conditions
* investability filter
* Exit3
* Exit4
* reentry rules
* PIT handling
* execution semantics

The only intended behavioral difference:

FastCore:

`loss_guard_enabled=true`

Julia:

`loss_guard_enabled=false`

FastCore Loss Guard threshold:

`-15%`

Do not alter strategy parameters when resuming this work unless explicitly instructed by the user.

## Entry-only investability filter

At every entry / reentry:

* `MKTCAP >= 300,000,000,000 KRW`
* trailing 20 trading-day average `ACC_TRDVAL >= 300,000,000 KRW`
* `TDD_CLSPRC >= 5,000 KRW`

Entry-only.

Never exit a position merely because these thresholds later fail.

## Historical PIT Authority

Canonical historical authority:

`EFFECTIVE_CORRECTED_AUTHORITY_V01`

Path:

`artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01_spac_corrected_effective_authority/effective_pit_common_denominator.json`

SHA256:

`a1952956427c214c21aa2fa293366d9ef092b36ae5afb3b110fd1ae556ccb3b0`

Coverage:

* start: `2010-01-04`
* end: `2026-08-21`

Counts:

* historical identities: `3149`
* PIT intervals: `3173`

Requested backtest end:

`2026-09-04`

Effective backtest end:

`2026-08-21`

Reason:

`HISTORICAL_PIT_UNIVERSE_AUTHORITY_BOUNDARY`

Do not extend the historical PIT authority automatically when resuming.

## Identity contract

Canonical identity:

`(ticker, isu_cd, market)`

Historical run must not use current-survivor universe as denominator.

Identity lifecycle isolation must apply to:

* adjusted daily price history
* raw investability history
* Pattern A / FAST feature history
* weekly/monthly context
* reentry evaluation

Previous or next identity history must not leak across a reused ticker lifecycle.

## Latest completed fixes at paused HEAD

Commit:

`9d24e7502e0f91dec03a617dc3ba0b38d422d3c7`

Implemented:

### 1. Identity-safe 20D trading-value average

20D average trading value is recomputed inside the clipped identity lifecycle.

A successor identity cannot borrow predecessor observations.

New identity:

* observations 1 to 19 → avg20 unavailable
* observation 20 → avg20 becomes available

### 2. Counterfactual Julia exit boundary

FastCore loss-cut counterfactual path is limited to the period Julia actually holds the position.

For realized Julia trades:

* include FastCore stop execution session
* end before Julia exit execution session

For Julia OPEN_AT_CUTOFF:

* end at cutoff

Prices after Julia exit must not affect recovery/drawdown statistics.

### 3. Deeper-loss direction fix

Julia better:

`julia_terminal_return > fastcore_loss_cut_return`

FastCore avoided deeper loss:

`julia_terminal_return < fastcore_loss_cut_return`

These are intentionally opposite conditions.

### 4. Pairable denominator fix

Julia-specific counterfactual metrics use only:

`pairable=true`

rows.

Unpairable FastCore-only reentries are excluded from:

* Julia eventually-positive rate
* recovered-above-entry rate
* never-recovered rate
* Julia-better rate
* FastCore-better rate
* deeper-loss-avoided rate

### 5. daily=None post-stop fallback removed

Whole-trade Julia MFE/MAE are not promoted to post-stop metrics.

Legacy values remain only in:

* `julia_mfe_legacy`
* `julia_mae_legacy`

### 6. PIT audit metadata expanded

Audit now records:

* authority
* authority SHA
* population count
* PIT interval count
* coverage start/end
* current survivor universe usage
* lifecycle isolation
* raw 20D identity isolation

## Latest focused validation

Command:

`./.venv/bin/pytest -q -p no:cacheprovider tests/test_fastcore_julia_strategy_backtest_v01.py`

Latest result:

`25 passed, 0 failed, 2 skipped`

Skipped tests:

1. `test_fastcore_and_julia_share_identical_entry_decisions`

   * synthetic series produced no FAST/Pattern A signal

2. `test_fastcore_loss_guard_can_trigger_on_large_drawdown`

   * synthetic series produced no FAST/Pattern A signal

These skips are not currently treated as blockers.

## Validation NOT performed after latest fix

The following were intentionally NOT executed:

* bounded identity sample
* authority full regression
* survivorship freeze full regression
* Full Repository Pytest
* Phase 3 full historical backtest
* STEP2 portfolio backtest

Therefore:

`FINAL_FIX_HEAD=false`

The paused code head must not automatically be treated as final validated production backtest head.

## Known deferred review item

When this work resumes, re-check:

`RAW MARKET IDENTITY DISCRIMINATOR / CROSS-MARKET TRANSITION SAFETY`

Current raw panel remains primarily ticker-keyed.

Same-day cross-market ambiguity is fail-closed, and lifecycle rolling is isolated, so this is not currently considered a blocker.

Do not overengineer unless a concrete failure appears.

## Missing / deferred metadata

Optional future metadata:

`EFFECTIVE_EARLIEST_EVALUABLE_DATE`

This is not currently a blocker.

Add only if useful during resumed full-run reporting.

# Resume Procedure

Do not resume automatically.

Resume only after explicit user instruction.

Recommended sequence:

## Phase A — review paused branch

1. confirm branch HEAD
2. read this handoff
3. inspect changes since `9d24e750...`
4. confirm strategy thresholds remain frozen

## Phase B — validation

1. focused tests
2. small deterministic bounded sample
3. verify:

   * historical identity isolation
   * raw 20D isolation
   * FastCore / Julia invariant
   * all loss cuts accounted for
   * pairable / unpairable counterfactual totals
   * no future information
4. external review

## Phase C — repository validation

If still required:

* run Full Repository Pytest once
* record any pre-existing missing-fixture failures separately

Do not regenerate old authority pipelines merely to satisfy missing generated fixtures unless explicitly necessary.

## Phase D — designate FINAL_FIX_HEAD

Only after review/validation:

`FINAL_FIX_HEAD=<approved SHA>`

## Phase E — Phase 3

Run corrected full historical STEP1 exactly once.

Historical universe:

3149 identities

Effective end:

2026-08-21

Use progress reporting/checkpointing.

No network.

## Phase F — review Phase 3 result

Review:

* FastCore trades
* Julia trades
* first entries vs reentries
* loss guard impact
* Julia recoveries
* large-loss tails
* holding period
* counterfactual
* best/worst trades

Do not tune parameters yet.

## Phase G — later STEP2

Only after STEP1 review.

STEP2 is realistic portfolio simulation and must use shared capital / chronological execution rather than ticker-parallel simulation.

Known future STEP2 direction:

* initial cash: 50,000,000 KRW
* max 10% allocation per ticker
* integer shares
* no cash → skip
* proceeds reusable
* no overlap/pyramiding
* buys only Monday open, or first local trading day of that week
* valid exits execute next local trading-day open
* FastCore loss guard exits next trading-day open
* strict no-lookahead
* exits before buys on same execution day
* portfolio engine chronological and serial per strategy

Still unresolved before STEP2:

* sizing denominator: current NAV vs fixed amount
* weekly signal queue semantics
* candidate ranking under congestion
* exact transaction costs/slippage
* same-open ordering final freeze

# Important Project Boundary

Market-price data validation is already considered complete.

Do not reopen historical market-price validation/hardening unless a concrete new discrepancy appears.

Avoid overengineering.

The project goal is strategy analysis and practical decision support, not formal data-integrity hardening.

# Current final status

`FASTCORE_JULIA_BACKTEST_STATUS=PAUSED`

`PAUSED_CODE_HEAD=9d24e7502e0f91dec03a617dc3ba0b38d422d3c7`

`FINAL_FIX_HEAD=false`

`PHASE3_EXECUTED=false`

`STEP2_EXECUTED=false`

`NEXT_ACTION=WAIT_FOR_EXPLICIT_USER_RESUME_INSTRUCTION`
