# FAST Core V2 Alignment + signal-day 500B — P3-1 실전형 포트폴리오 검증

- Work ID: `FAST_CORE_V2_ALIGNMENT_500B_P3_1_OFFICIAL_REALISTIC_PORTFOLIO_V01`
- Scope: P3-1 only; frozen FAST Core V2 CONTROL vs. the same strategy with a signal-day alignment and KRX market-cap entry filter.
- Status: policy and execution contract sealed before sample/full replay.

## Window and universe

- Evaluation, signal, and NAV window: 2022-01-03 through 2025-05-30, using the exact rolling KRX calendar (834 trading sessions).
- Support session: 2025-06-02. Only exits signaled on or before the cutoff may execute there. No post-cutoff signal, entry, NAV, return, or support-session costs are included in cutoff performance.
- Use exact PIT COMMON intervals and the identity active on the signal date. No current-survivor roster or hindsight membership.
- Apply the current permanent exclusions to the shared pre-signal universe, by exact `(ticker, standard ISU_CD)` pair, before splitting the groups.
- P3-2 independently confirmed that `(380440, KR7380440008)` overlaps P3-1 COMMON PIT (2021-05-21–2023-12-28) and its specified adjusted-price Parquet is absent. This confirms the user's conditional approval. Add only this exact pair to the permanent registry before sample/full execution. Keep all prior P3-2 outputs immutable; record a persisted-output policy consistency audit only.

## Frozen comparison

CONTROL uses frozen `PATTERN_A_FAST_FINAL_STRATEGY_V02` with no market-cap or alignment filter. Candidate uses the same evaluator and lifecycle, adding only this pre-entry gate:

1. Signal-day Repository V2 adjusted close `>` the arithmetic mean of the last 20 completed monthly adjusted closes `>` the last 60 completed monthly adjusted closes. Exclude the signal month; require all 60 monthly bars. For January 2022, the 60-month window is January 2017–December 2021.
2. Exact signal-date, market, PIT ticker and ISU KRX raw `market_cap >= KRW 500,000,000,000`. No date substitution. Missing, duplicate, invalid, or unverifiable cap rows reject the candidate signal with an explicit reason; CONTROL is unaffected.

Filter rejection occurs inside the V2 entry-signal gate before re-entry state advances. Signal ledgers are fixed before cash allocation; do not regenerate after a cash skip.

## Shared portfolio contract

- Initial cash KRW 200,000,000; each entry budget KRW 5,000,000 including commission; whole shares; reinvest realized proceeds; no position cap or partial fills.
- Next exact KRX session open fills; buy/sell adverse slippage 0.1% each way; commission 0.015% each way; tax excluded.
- Sale proceeds settle for use on the next normal session. No same-ticker overlap, pyramiding, or same-open exit/re-entry.
- Deterministic same-day order: ticker, ISU, signal date, execution date, trade ID. Portfolio event replay is single-threaded; ticker evaluation uses 10 workers.
- NAV = cash + unsettled sale proceeds + held whole shares × exact adjusted close. Carry is allowed only with exact official non-trading placeholder evidence; otherwise mark the entire day's NAV unresolved.

## Preflight, sample, full replay, audit

1. Record current HEAD/origin, source hashes for the official A–E criteria, common rules, lifecycle, frozen V2 README/plan, P3-2 reference code/contracts/results, P3-2 data-closure and 380440 policy artifacts, and the current permanent registry.
2. Verify exact dates/support, 2017 MA60 warm-up, all P3-1 PIT identity/date bounds against local Repository V2 price files, exact local KRX date/market partition availability, and the global exclusion count/hash. No external API calls.
3. Do not reuse prior CONTROL: available P3-1 artifacts are simple per-trade analyses and do not prove this run's portfolio, cash, PIT, permanent-exclusion, valuation, or cost contract. Regenerate CONTROL and candidate in the same replay.
4. Run a representative sample through the same evaluator, exact cap lookup, cash loop, and NAV path; record workers, errors, wall time, CPU and RSS. Stop on structural failure. Estimate full runtime; if at least two hours, identify only a minimal measured bottleneck before proceeding.
5. Run P3-1 full once with 10 evaluator workers. No P1/P2/P2-2/P3-2 full rerun, strategy/operations/web changes, adoption decision, or baseline promotion.
6. Independently reconcile exact identity/PIT/filter/trade keys, monthly windows, cap partitions and values, costs, integer shares, cash conservation, settlement, position overlap/cap, cutoff/support events, NAV coverage, valuation marks, and source/artifact hashes. Keep unresolved data visible.

## Gates and reporting

- A: zero material structural integrity errors; unresolved source or valuation evidence that can affect the comparison remains `CHECK_REQUIRED`.
- B: all filled sides include 0.015% commission and 0.1% adverse slippage; transaction tax is excluded.
- C: total return > 0 and CAGR > 0.
- D: each group's MDD >= -40%; candidate fails if `CONTROL MDD - candidate MDD >= +5.0 percentage points`.
- E: NAV coverage 100% = `EXACT`; 90% to below 100% = `OBSERVED`; below 90% = `CHECK_REQUIRED`.
- Report cash-shortage attempts/skips as diagnostics, not a gate; include returns, realized trade distribution, holding days, Loss Guard, PROGRESSED, exit reason, cutoff open positions, portfolio/capital usage, and CONTROL deltas.
- This single window is preliminary only: `NOT_FINAL_5WINDOW`; baseline promotion is `NOT_EVALUATED`; FAST Core V2 remains the default.

## Outputs and Git

Store the plan, contract, preflight, source manifest, code, replay ledgers, comparison, gates, integrity and hashes only in this directory. Write the user-facing detailed result to `/Users/june/Documents/projects/r.md`. Preserve all pre-existing untracked files. Commit/push only this work and the approved exact registry policy update; verify `HEAD == origin/main` and tracked tree clean.
