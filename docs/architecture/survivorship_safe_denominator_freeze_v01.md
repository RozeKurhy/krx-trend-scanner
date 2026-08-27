survivorship_safe_denominator_freeze_v01.md

# Survivorship-Safe Historical Denominator Freeze (v01)

`SURVIVORSHIP_SAFE_DENOMINATOR_FREEZE_V01`: freezes the canonical
survivorship-safe universe contract that every future E2E consumer
(AdjustedPriceStore, FastCore/Julia backtest, Market Breadth) must use
instead of recomputing its own universe.

## 1. Two separate concepts — never one ticker list

**Population Universe**: every identity that was `COMMON` at least once,
anywhere in 2010-01-04..2026-08-21. Answers "should this identity ever be in
scope" — used for population-level consumers (AdjustedPriceStore population
target, coverage denominators, validation sampling universe).

**Point-In-Time (PIT) Common Denominator**: for each historical trading
date, the identities that were actually `COMMON` *on that date*. Answers
"what was the investable common-stock universe on date D" — used for
survivorship-safe backtests and date-specific market statistics (breadth,
advance/decline, new-high/new-low).

These are never merged into a single static ticker list. Example: a ticker
COMMON 2013-2015, then NOT_COMMON 2016-2018 belongs in the Population
Universe (it was common at some point) but must be *excluded* from the PIT
denominator for any date in 2016-2018.

## 2. Why they must be separate — survivorship bias

A backtest that reconstructs "the universe as of date D" using the *current*
common-stock list silently drops every identity that has since been
delisted, merged away, or reclassified — this is exactly what
survivorship bias is. The PIT denominator exists specifically so a
historical date's denominator never depends on what is true today.

Two failure modes this contract prevents:

- **Current-list broadcast**: taking today's ~2,557 currently-common tickers
  and treating them as the universe for every historical date. This drops
  every historical-only delisted common (605 identities in this freeze).
- **Historical-label broadcast**: taking a ticker's *final* classification
  label and applying it to its entire history. A ticker `COMMON_REQUIRED`
  overall may have had a `NOT_COMMON` interval (e.g. a SPAC phase) earlier in
  its life; applying `COMMON` to that phase retroactively is exactly the kind
  of look-ahead bias this freeze is built to prevent.

## 3. Identity-aware interval semantics

Both artifacts key identity as `(ticker, ISU_CD, market)`, never `ticker`
alone — a ticker string is not guaranteed unique across all of history (this
freeze observed 0 cases of ticker reuse in the current archive, but the
contract does not assume that stays true for future archive versions,
per `historical_authority_reconciliation`'s Section 6). Every COMMON interval
records `effective_from`/`effective_to` against the frozen trading calendar
(`historical_trading_calendar.json`, 4,095 dates, 2010-01-04..2026-08-21,
`trading_dates_sha256`-pinned).

## 4. Single-computation derivation

Both artifacts are derived from **one shared walk** over the full authority:

```
load_basic_info_snapshots()                       # 8,190 raw KRX Basic Info files
  -> build_pit_identity_timeline()                # per-identity chronological observations
  -> classify_full_universe()                     # row-pure classification + supplemental
                                                    #   authority override, for EVERY identity
                                                    #   ever observed (not just the frozen
                                                    #   1,116-target reconciliation set)
  -> derive_population_and_pit_records()           # single pass: any-ever-COMMON -> population,
                                                    #   COMMON intervals -> PIT denominator
```

`classify_full_universe` (in `historical_authority_reconciliation.py`) reuses
the exact same `_classify_observations`/`_intervalize` logic already reviewed
and tested for the frozen 1,116-target historical-only reconciliation — it
just removes the target-list filter. Population and PIT are never computed
independently; this is what makes the union invariant (Section 6 below) a
real property rather than two code paths happening to agree.

This module deliberately does **not** reconcile against the separate,
independently-maintained live `InstrumentMetadataResolver`
(`src/trend_scanner/universe/instrument_metadata.py`, documented in
`instrument_metadata_authority.md` §1-17). That system uses a different
upstream source (KRX MDC, not Basic Info) and different classification rules,
and reports current COMMON = 2,666 (numeric 2,641 / alpha 25) as of the
2026-08-21 snapshot — a different number from this freeze's independently
derived "currently common" figure of 2,557 (numeric 2,534 / alpha 23). This
gap is expected and is not a defect in either system: the two pipelines
answer different questions (current live MDC-verified asset type vs.
full-history Basic-Info-derived PIT classification) and are not required to
agree ticker-for-ticker. This freeze's Population/PIT figures come **only**
from the Basic Info + supplemental authority chain — never from the live
resolver's output, and never forced to match it.

## 5. Historical-only reconciliation as a subset

Of the 1,116-ticker frozen historical-only reconciliation target
(`HISTORICAL_UNIVERSE_AUTHORITY_RECONCILIATION_V01` and its residual
resolution rounds), the full-universe derivation splits cleanly:

| bucket | count | in Population? |
|---|---|---|
| Frozen target, `HISTORICAL_COMMON_REQUIRED` | 605 | yes (historical-only, not currently common) |
| Frozen target, `HISTORICAL_NOT_COMMON` | 511 | no |
| Outside frozen target (row-pure resolves cleanly without needing supplemental review) | 2,557 | yes (all currently common) |

`605 + 2,557 = 3,162` — the Population Universe total — matches exactly.
This is a consequence of the derivation, verified after the fact; it was not
used as a target the derivation was tuned to hit (Section 9's own caution).

### 5.1. Market Breakdown Accounting & Cross-Market Transitions

The Population Universe market breakdown:

- `kospi_ever_common_identity_count`: 982
- `kosdaq_ever_common_identity_count`: 2,202
- `cross_market_common_identity_count`: 22
- Total unique identities: `982 + 2,202 - 22 = 3,162`

The 22 difference between the simple sum (`3,184`) and the Population total (`3,162`) is the exact set of 22 cross-market companies (e.g. `035720` Kakao, `068270` Celltrion, `022100` POSCO DX) that migrated from KOSDAQ to KOSPI during the historical period.

**Accounting semantics:**
- KOSPI (982) and KOSDAQ (2,202) counts represent "ever-common by market" (identities that had at least one COMMON interval in that market during the historical period), **not** mutually-exclusive current snapshot buckets.
- Same-date dual-market membership is strictly zero across all 4,095 trading dates: no identity is ever in both KOSPI COMMON and KOSDAQ COMMON on the same date.
- Transition boundaries are strictly contiguous: for every migrating identity, the final trading date in the old market and the initial trading date in the new market are exactly consecutive trading days (trading day difference = 1, zero overlap, zero gap).

## 6. Population ⋃ PIT invariant

Every identity that appears in any PIT COMMON interval must appear in the
Population Universe, and vice versa — `evaluate_population_pit_union_invariant`
checks this at `(ticker, ISU_CD)` granularity and is a required, non-waivable
gate (`BLOCKED_UNION_MISMATCH` otherwise). Because both come from the same
walk (Section 4), a mismatch here would indicate a genuine bug in the
derivation, not an expected edge case.

## 7. Alpha membership vs. adjusted-price eligibility — separate questions

23 alphanumeric-identifier (e.g. `0008Z0`, `0009K0`, `0010F0`-shaped) tickers are in the Population Universe as legitimate historical COMMON identities (all currently active common stocks introduced under KRX's alphanumeric ticker issuance rules).

Conversely, prior supplemental authority confirmed that preferred-class alphanumeric tickers (e.g. `00781K` 코리아써키트2우선주(신형), along with all 14 preferred-class residual items and all 58 historical NOT_COMMON alpha items) are `HISTORICAL_NOT_COMMON` and are strictly **excluded** from both the Population Universe and the PIT COMMON intervals (intersection count = 0).

Whether `PyKRX adjusted=True` can actually source adjusted OHLC for these legitimate alphanumeric COMMON identifiers is a **separate, unverified** question — this freeze does not test it and does not exclude alpha identities because that eligibility is unknown. Silently dropping alpha membership here would itself be a survivorship-adjacent bug (quietly shrinking the historical universe for reasons unrelated to whether the security was actually common stock). Adjusted-price source eligibility is explicitly deferred to `ADJUSTED_PRICE_STORE_BOUNDED_LIVE_PILOT_V01`.

## 8. Future-event leakage

Neither `classify_full_universe` nor the population/PIT derivation has any
notion of "future" relative to some analysis date — every observation is
classified using only its own `effective_date`'s official fields (plus,
where applicable, a supplemental-authority record whose own cited evidence
is dated on/before the frozen historical cutoff, see
`instrument_metadata_authority.md` §20). A COMMON interval's `effective_from`
can never retroactively extend backward past the date it was actually
observed as COMMON.

## 9. Consumers must not compute their own universe

Historical consumers (backtest engines, market-breadth calculators) must
load this freeze's artifacts rather than deriving their own ticker list from
whatever "current" data source they already have. Recomputing per-consumer
risks each consumer disagreeing on which historical dates survivorship-bias
protection applies to.

## 10. Artifacts and loader contract

- `artifacts/data/end_to_end_data_parity/v01/survivorship_safe_denominator_freeze/v01/historical_common_population_v01.json`
  — Population Universe records + `population_manifest_sha256`.
- `.../pit_common_denominator_v01.json` — canonical COMMON interval records
  (not a per-date manifest — Section 3's interval-first design) +
  `pit_common_denominator_sha256` + the calendar's `trading_dates_sha256`.
- `.../survivorship_safe_denominator_freeze_v01.json` — closure summary:
  status, authority checkpoint SHA, supplemental authority provenance,
  trading calendar identity, population/PIT summary stats + hashes,
  historical-only reconciliation counts, gate results, `created_from_head`.

Loader API (`src/trend_scanner/universe/survivorship_safe_denominator_freeze.py`):

- `load_historical_common_population(path=...)` — Population Universe records.
- `load_pit_common_intervals(path=...)` — canonical COMMON interval records.
- `get_common_universe_as_of(date, market=None, *, intervals=None)` —
  identity-aware COMMON set as of an exact frozen trading date. Fail-closed:
  raises `FreezeContractError` for a date outside the frozen calendar range
  or a non-trading date — it never falls back to the nearest trading day and
  never falls back to the current universe.

Actual migration of AdjustedPriceStore/FastCore/Julia/Market Breadth to these
loaders is out of scope for this freeze (`ADJUSTED_PRICE_STORE_BOUNDED_LIVE_PILOT_V01`
and later stages); this freeze only provides the stable contract they will
consume.
