docs/architecture/krx_index_migration_v01.md
================================================================================
KRX_INDEX_MIGRATION_V01 RECOMMENDATION
================================================================================

HISTORICAL SNAPSHOT — SUPERSEDED
--------------------------------
This artifact records the earlier quota-paused checkpoint. It is preserved as
historical evidence and is not the current migration status.

CURRENT AUTHORITATIVE STATUS
KRX_INDEX_MIGRATION_V01 = CLOSED_AND_MERGED
Main merge = 7d71d2a9d978d176afd1d737e66735eb5608a06a
Closure commit = c9bd2f9bf415cddacf04a339c1a1b8cb1aef75c5
See market_index_migration_v01_manifest.json, closure/, and finalization/.

FINAL STATUS
PARTIAL_RESUMABLE_KRX_INDEX_MIGRATION_V01

RECOMMENDATION
NOT READY_FOR_ARCHITECT_KRX_INDEX_MIGRATION_V01_REVIEW

BLOCKER
BACKFILL_PAUSED_QUOTA

WHY
The canonical quota database reached its global safety limit after the pilot
and whole-date historical staging tranche. Production IndexStore was not
published. Legacy OHLC parity and market RS parity remain blocked until the
full
2010-01-04 through 2026-08-21 target calendar is staged.

PRODUCTION
publish_count=0
consumer migration=0
PyKRX live market calls=0
/idx/krx_dd_trd calls=0

RESUME
next_pending_date=2012-08-16
pending_date_count=3439
resume must continue from the canonical quota database and staging manifest.
