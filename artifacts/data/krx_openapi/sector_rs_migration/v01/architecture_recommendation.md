architecture_recommendation.md
================================================================================
SECTOR_RS_KRX_MIGRATION_V01
================================================================================

Sector index price source: KRX Open API (kospi_dd_trd / kosdaq_dd_trd).
Market index price source: existing source unchanged.
Ticker-to-sector membership source: existing source unchanged.
KRX branded 24 taxonomy is not used for native Sector RS.
Production cache is normalized and consumed by IndexPriceDataProvider without reading validation artifacts.
RECOMMENDATION: BLOCKED_KRX_QUOTA
