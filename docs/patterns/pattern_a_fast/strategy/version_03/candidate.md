# Pattern A FAST Final Strategy V03 Candidate

## Frozen candidate identity

- Strategy ID: `PATTERN_A_FAST_FINAL_STRATEGY_V03`
- Alias: `A FAST Core V3` / `패스트 코어 V3`
- Exit contract: `WINNER_HWM_EXIT_V01`
- Status: `FROZEN_CANDIDATE_AWAITING_MATCHED_AB`
- Base strategy: `PATTERN_A_FAST_FINAL_STRATEGY_V02`
- V2 production default remains unchanged: `PATTERN_A_FAST_FINAL_STRATEGY_V02` / `A FAST Core V2`

This document freezes a candidate contract only. It does not promote V3, alter
production reports, or replace the V2 default. A matched-cohort V2 versus V3
exit-only A/B evaluation is required before any promotion decision.

## Entry contract

The entry contract is exactly the V2 contract (`SAME_AS_V02`):

- Pattern A eligible stage: `TRANSITION` or `EARLY_TREND`.
- FAST machine stage/status: `TRIGGER` / `READY`.
- Monthly regime permission: `PERMITTED_REGIME`.
- Daily risk permission: `NORMAL` or `ELEVATED`.
- FAST score status: `READY` or `PARTIAL`.
- Entry execution: `NEXT_LOCAL_TRADING_DAY_OPEN`.

No entry rule, universe filter, calendar semantic, or threshold is retuned in
this candidate.

## Winner HWM exit contract

Before Winner mode, `running_raw_MFE < +20%`, the position is always held and
there is no V3 exit. Winner mode activates inclusively at
`running_raw_MFE >= +20%`.

`running_raw_MFE = running_highest_HIGH / entry_open - 1`. The HWM is the
highest completed daily `HIGH` since entry. Each completed daily EOD decision
updates that HWM with the day's HIGH and compares the day's completed `CLOSE`
against it. There is no intraday decision and no look-ahead.

| Running raw MFE range | Soft drawdown | Hard drawdown |
| --- | ---: | ---: |
| `+20% <= MFE < +50%` | `-10%` | `-20%` |
| `+50% <= MFE < +100%` | `-15%` | `-25%` |
| `+100% <= MFE < +200%` | `-20%` | `-30%` |
| `+200% <= MFE < +400%` | `-25%` | `-35%` |
| `MFE >= +400%` | `-30%` | `-40%` |

Exact boundaries belong to the next band: `20/50/100/200/400` activate the
corresponding lower-bound band.

- Soft exit requires the active HWM drawdown threshold and completed FAST
  state `WATCH` or `SETUP`. It produces `SOFT EXIT SIGNAL` with no persistence
  or confirmation step.
- If the soft threshold is breached while FAST is not `WATCH`/`SETUP`, the
  result is `HOLD`.
- Hard exit is price-only: the active HWM drawdown threshold is sufficient and
  FAST state is irrelevant. If Soft and Hard are simultaneous, `HARD` wins and
  only one exit is executed.
- A signal is generated at completed daily EOD and executes at the next local
  trading day OPEN. If there is no supported next day, the position remains
  `OPEN_AT_CUTOFF`.

## Removed and excluded rules

V3 does not use the V2 fixed `-15%` Pre-PROGRESSED Loss Guard, V2 `EXIT3`
stage-transition exit, V2 `EXIT4` 15-point score-HWM exit, `W25`, `W30`,
`FAILURE_ARMED`, persistence exit, Peak Profit Floor, Soft Confirm, or any
other Pre-Winner stop. V3 generates no recovery, cooldown, or re-entry; V2
re-entry behavior is not modified.

## Capital trade-off

Pre-Winner에는 강제 청산이 없으므로 장기간 자본이 묶이거나 큰 미실현 손실이 발생할 수 있다.

This candidate is not a backtest result. The next task is an exit-only
matched-cohort A/B comparison with identical V2 entry points; the evaluator
must not re-evaluate entry filters or generate strategy-specific re-entry.
