# B Select Daily NORMAL Exit MDD valuation-only correction V02

- Verdict: `B_SELECT_DAILY_NORMAL_EXIT_CANDIDATE_VALIDATION_PASS`
- Frozen source study: `artifacts/strategies/b_select_core_v1/research/daily_normal_exit_permanent_exclusion_v01`
- Start HEAD / origin/main: `5a8ca5296bdf1050dc5e776813872c01ec567f9f` / `5a8ca5296bdf1050dc5e776813872c01ec567f9f`
- Signal replay: **not performed**
- Transaction/event replay: **not performed**
- Frozen event/trade ledger changes: **0**
- Raw carry lookup orders checked: ticker ascending, ticker descending, deterministic shuffle; mismatch **0**.
- The prior V01 MDDs remain in their original files and are superseded only for valuation by this V02 report.

## Severity counts

| Level | Count |
|---|---:|
| CRITICAL | 0 |
| MAJOR | 0 |
| MINOR | 0 |

## Corrected five-window MDD

| Window | Control old → corrected (coverage) | Test old → corrected (coverage) | CONTROL − TEST (pp) | Gate |
|---|---:|---:|---:|---|
| P1 | -17.3998% → -18.1128% (100.00%) | -13.5034% → -14.2655% (100.00%) | -3.8472 | PASS / PASS |
| P2-1 | -20.6218% → -20.6218% (100.00%) | -17.5878% → -17.5878% (100.00%) | -3.0339 | PASS / PASS |
| P2-2 | -23.4638% → -24.3623% (100.00%) | -18.2806% → -19.2619% (100.00%) | -5.1004 | PASS / PASS |
| P3-1 | -18.5200% → -18.5200% (100.00%) | -17.5818% → -17.5818% (100.00%) | -0.9382 | PASS / PASS |
| P3-2 | -24.0670% → -24.9592% (100.00%) | -19.8191% → -20.8783% (100.00%) | -4.0809 | PASS / PASS |

## Unchanged non-valuation evidence

Trade counts, realized win rates, total returns and CAGR are read from the unchanged sealed ledgers/terminal equity. The corrected daily series changes only rows that were unresolved in V01; execution-support terminal equity is checked for exact parity.

## Provenance

- Valuation audit rows: 5,297
- Frozen event ledgers: 10 hashes recorded; frozen trade ledgers: 10 hashes recorded.
- Carry authorization basis: 17 exact identities classified A/B by `artifacts/strategies/b_select_core_v1/research/daily_exit_mdd_coverage_remediation_v01/identity_corporate_action_audit.csv`.
- Raw mark and anchor partitions were loaded by market/date and looked up by the exact ticker only after exact `(ticker, ISU_CD, market)` PIT activity passed.
- No nearest date, proxy, interpolation, or generic forward-fill was used.
