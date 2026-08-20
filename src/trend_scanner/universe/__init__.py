"""Pattern A Universe & Data Quality Package."""

from trend_scanner.universe.asset_classifier import classify_asset_type
from trend_scanner.universe.cache_population import (
    CachePopulationRecord,
    CachePopulationStatus,
    CachePopulationSummary,
    populate_common_stock_cache,
    populate_single_ticker,
)
from trend_scanner.universe.instrument_metadata import (
    InstrumentMetadata,
    InstrumentMetadataResolver,
    normalize_krx_market,
    resolve_instrument_metadata,
)
from trend_scanner.universe.krx_universe import (
    get_latest_market_trading_date,
    load_krx_equity_universe,
)
from trend_scanner.universe.models import (
    AssetType,
    FreshnessStatus,
    MarketType,
    QualityStatus,
    TickerQualityRecord,
    UniverseQualitySummary,
    UniverseSecurity,
)
from trend_scanner.universe.quality_auditor import (
    MIN_HISTORY_MONTHS,
    audit_ticker_quality,
    audit_universe_quality,
)

__all__ = [
    "AssetType",
    "CachePopulationRecord",
    "CachePopulationStatus",
    "CachePopulationSummary",
    "FreshnessStatus",
    "InstrumentMetadata",
    "InstrumentMetadataResolver",
    "MarketType",
    "QualityStatus",
    "TickerQualityRecord",
    "UniverseQualitySummary",
    "UniverseSecurity",
    "classify_asset_type",
    "get_latest_market_trading_date",
    "load_krx_equity_universe",
    "normalize_krx_market",
    "populate_common_stock_cache",
    "populate_single_ticker",
    "resolve_instrument_metadata",
    "MIN_HISTORY_MONTHS",
    "audit_ticker_quality",
    "audit_universe_quality",
]
