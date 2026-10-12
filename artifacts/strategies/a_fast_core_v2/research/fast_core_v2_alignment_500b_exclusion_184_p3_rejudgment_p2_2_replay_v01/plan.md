# FAST Core V2 exclusion-184 policy transition and P2-2 replay V01

- Work ID: FAST_CORE_V2_ALIGNMENT_500B_EXCLUDE_2_P3_READJUDGE_P2_2_REPLAY_V01
- Baseline: main 29ac6c85af0524c279a41cb0d820b9b646671a91; origin/main matched before the policy edit and replay.
- Add only exact pairs 138580/KR7138580006 and 003410/KR7003410008 to the global permanent-identity registry.
- Sequence: registry transition; read-only P3-1 and P3-2 impact audit and A-E re-judgment; then one P2-2 CONTROL and one ALIGNMENT + 500B portfolio replay from the verified frozen signal ledgers after deleting these exact identities.
- P1 and P2-1 are not run. No other identity is excluded; no strategy, filter, fill, cost, settlement, evaluator, web or operating code is changed; no automatic promotion.
- Period: 2021-01-04 through 2026-08-31, 1,387 exact KRX sessions. 2026-09-01 supports exits only. Completed monthly MA60/MA20 warmup remains 2016-01 through 2020-12.
- Contract: KRW 200,000,000 initial cash; KRW 5,000,000 inclusive buy budget; integer shares; no partial fills or artificial position cap; 0.1% adverse slippage and 0.015% commission each side; 0% tax; T+1 sale proceeds; no same-open reuse; deterministic entry order.
- No carry, interpolation, zero mark or invented corporate-action settlement. Coverage under 90% remains CHECK_REQUIRED.
- Saved V02 signal/filter ledgers are reused; no signal evaluator rerun. Full CONTROL and candidate portfolio replay runs once per group.
- Output: artifacts/strategies/a_fast_core_v2/research/fast_core_v2_alignment_500b_exclusion_184_p3_rejudgment_p2_2_replay_v01
