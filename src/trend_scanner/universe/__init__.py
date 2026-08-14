"""Pattern A Universe & Data Quality Package."""

from trend_scanner.universe.asset_classifier import classify_asset_type
from trend_scanner.universe.models import (
    AssetType,
    FreshnessStatus,
    MarketType,
    QualityStatus,
    TickerQualityRecord,
    UniverseQualitySummary,
)
from trend_scanner.universe.quality_auditor import (
    MIN_HISTORY_MONTHS,
    audit_ticker_quality,
    audit_universe_quality,
)

__all__ = [
    "AssetType",
    "FreshnessStatus",
    "MarketType",
    "QualityStatus",
    "TickerQualityRecord",
    "UniverseQualitySummary",
    "classify_asset_type",
    "MIN_HISTORY_MONTHS",
    "audit_ticker_quality",
    "audit_universe_quality",
]
