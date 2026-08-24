"""Production market-data authority and storage contracts.

This module is deliberately declarative.  It does not import a network client,
PyKRX, OpenDART, or any runtime artifact.  The architecture validator serializes
these immutable contracts into evidence files; production consumers may adopt the
contracts incrementally without changing today's data-fetch behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


class AuthorityType(str, Enum):
    AUTHORITATIVE = "AUTHORITATIVE"
    DERIVED = "DERIVED"
    LEGACY = "LEGACY"
    VALIDATION_ONLY = "VALIDATION_ONLY"
    FUTURE_MIGRATION = "FUTURE_MIGRATION"
    NOT_PROVIDED = "NOT_PROVIDED"


class MigrationStatus(str, Enum):
    MIGRATED = "MIGRATED"
    LEGACY_SOURCE = "LEGACY_SOURCE"
    VALIDATED_NOT_PRODUCTION_MIGRATED = "VALIDATED_NOT_PRODUCTION_MIGRATED"
    LEGACY_COMPOSITE_NOT_SPLIT = "LEGACY_COMPOSITE_NOT_SPLIT"
    CLOSED_AVAILABLE = "CLOSED / AVAILABLE"
    NOT_MIGRATED = "NOT_MIGRATED"


class HealthStatus(str, Enum):
    READY = "READY"
    STALE = "STALE"
    PARTIAL = "PARTIAL"
    MISSING = "MISSING"
    ERROR = "ERROR"
    NOT_MIGRATED = "NOT_MIGRATED"
    DIRTY = "DIRTY"


@dataclass(frozen=True)
class AuthorityFieldContract:
    field_name: str
    authority_id: str
    authority_type: AuthorityType
    source_name: str
    source_endpoints: tuple[str, ...]
    source_semantics: str
    owner_store: str | None
    schema_version: str


@dataclass(frozen=True)
class StoreContract:
    store_id: str
    description: str
    schema_version: str
    fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    ownership: str
    pit_required: bool
    write_policy: str


@dataclass(frozen=True)
class LayerContract:
    layer_id: str
    description: str
    authority: str
    current_source: str
    target_source: str
    storage_role: str
    pit_required: bool
    freshness_policy: str
    migration_status: str


@dataclass(frozen=True)
class ObservabilityContract:
    statuses: tuple[str, ...]
    snapshot_fields: tuple[str, ...]
    quota_fields: tuple[str, ...]


ARCHITECTURE_VERSION = "KRX_PRODUCTION_DATA_ARCHITECTURE_V01"


AUTHORITY_FIELDS: tuple[AuthorityFieldContract, ...] = (
    AuthorityFieldContract("raw_open", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "UNADJUSTED_RAW", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("raw_high", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "UNADJUSTED_RAW", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("raw_low", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "UNADJUSTED_RAW", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("raw_close", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "UNADJUSTED_RAW", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("volume", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "RAW_DAILY_VOLUME", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("trading_value", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "RAW_DAILY_TRADING_VALUE", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("market_cap", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "RAW_DAILY_MARKET_CAP", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("listed_shares", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"), "RAW_DAILY_LISTED_SHARES", "KRXRawStockStore", "KRX_RAW_STOCK_V01"),
    AuthorityFieldContract("adjusted_open", "PYKRX_ADJUSTED_PRICE", AuthorityType.AUTHORITATIVE, "PyKRX", ("stock.get_market_ohlcv_by_date(adjusted=True)",), "ADJUSTED_OHLC", "AdjustedPriceStore", "ADJUSTED_PRICE_V01"),
    AuthorityFieldContract("adjusted_high", "PYKRX_ADJUSTED_PRICE", AuthorityType.AUTHORITATIVE, "PyKRX", ("stock.get_market_ohlcv_by_date(adjusted=True)",), "ADJUSTED_OHLC", "AdjustedPriceStore", "ADJUSTED_PRICE_V01"),
    AuthorityFieldContract("adjusted_low", "PYKRX_ADJUSTED_PRICE", AuthorityType.AUTHORITATIVE, "PyKRX", ("stock.get_market_ohlcv_by_date(adjusted=True)",), "ADJUSTED_OHLC", "AdjustedPriceStore", "ADJUSTED_PRICE_V01"),
    AuthorityFieldContract("adjusted_close", "PYKRX_ADJUSTED_PRICE", AuthorityType.AUTHORITATIVE, "PyKRX", ("stock.get_market_ohlcv_by_date(adjusted=True)",), "ADJUSTED_OHLC", "AdjustedPriceStore", "ADJUSTED_PRICE_V01"),
    AuthorityFieldContract("adjusted_volume", "NONE", AuthorityType.NOT_PROVIDED, "NONE", (), "ADJUSTED_VOLUME_NOT_DECLARED", None, "ADJUSTED_PRICE_V01"),
    AuthorityFieldContract("ticker", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info"), "SIX_DIGIT_TICKER_FROM_ISU_SRT_CD", "StockMasterStore", "STOCK_MASTER_V01"),
    AuthorityFieldContract("standard_code", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info"), "KRX_STANDARD_CODE_FROM_ISU_CD", "StockMasterStore", "STOCK_MASTER_V01"),
    AuthorityFieldContract("name", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info"), "SECURITY_NAME", "StockMasterStore", "STOCK_MASTER_V01"),
    AuthorityFieldContract("market", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info"), "MARKET_NAMESPACE", "StockMasterStore", "STOCK_MASTER_V01"),
    AuthorityFieldContract("listing_date", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info"), "LISTING_DATE", "StockMasterStore", "STOCK_MASTER_V01"),
    AuthorityFieldContract("par_value", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info"), "PAR_VALUE", "StockMasterStore", "STOCK_MASTER_V01"),
    AuthorityFieldContract("native_sector_index_ohlc", "KRX_OPEN_API_NATIVE_SECTOR_INDEX", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"), "KRX_NATIVE_SECTOR_INDEX", "IndexStore", "INDEX_STORE_V01"),
    AuthorityFieldContract("market_index_ohlc", "PYKRX_MARKET_INDEX_CURRENT", AuthorityType.LEGACY, "PyKRX existing source", ("IndexPriceDataProvider.fetch_index_series",), "CURRENT_LEGACY_MARKET_INDEX", "IndexStore", "INDEX_STORE_V01"),
    AuthorityFieldContract("ticker_sector_membership", "PYKRX_SECTOR_MEMBERSHIP_CURRENT", AuthorityType.LEGACY, "PyKRX", ("stock.get_index_portfolio_deposit_file",), "CURRENT_PYKRX_MEMBERSHIP_NO_PIT_STORE", "SectorMembershipStore", "STOCK_MASTER_V01"),
    AuthorityFieldContract("fundamentals", "OPENDART_FUNDAMENTALS", AuthorityType.AUTHORITATIVE, "OpenDART", ("OpenDART financial statements",), "REPORTED_FINANCIAL_STATEMENTS", "FundamentalsStore", "FUNDAMENTALS_V01"),
    AuthorityFieldContract("foreign_institution_flow", "CURRENT_FOREIGN_FLOW_PROVIDER", AuthorityType.LEGACY, "Existing production flow source", ("src/trend_scanner/flow/foreign_flow.py",), "CURRENT_PRODUCTION_FLOW", None, "FLOW_V01"),
)


STORE_CONTRACTS: tuple[StoreContract, ...] = (
    StoreContract("KRXRawStockStore", "KRX unadjusted daily stock facts", "KRX_RAW_STOCK_V01", ("date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"), ("date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"), "Raw OHLC and raw ancillary are owned here; no adjustment", True, "New normalized store; no bulk migration in this phase"),
    StoreContract("AdjustedPriceStore", "Adjusted OHLC only", "ADJUSTED_PRICE_V01", ("date", "ticker", "open", "high", "low", "close"), ("date", "ticker", "open", "high", "low", "close"), "Adjusted OHLC only; ancillary fields are prohibited", True, "Mutable refresh state is tracked separately"),
    StoreContract("StockMasterStore", "Point-in-time KRX security master", "STOCK_MASTER_V01", ("as_of", "ticker", "standard_code", "name", "market", "listing_date", "security_group", "par_value", "listed_shares"), ("as_of", "ticker", "standard_code", "name", "market"), "Historical snapshots, not latest-only identity", True, "PIT snapshots; no replacement of current cache in this phase"),
    StoreContract("IndexStore", "Market and native sector index families", "INDEX_STORE_V01", ("date", "family", "index_code", "index_name", "open", "high", "low", "close", "volume", "trading_value"), ("date", "family", "index_code", "close"), "MARKET_INDEX, NATIVE_SECTOR_INDEX, and KRX_BRANDED_TAXONOMY namespaces stay distinct", True, "Sector index migrated; market index remains legacy"),
    StoreContract("SectorMembershipStore", "PIT ticker to sector membership", "SECTOR_MEMBERSHIP_V01", ("effective_date", "as_of", "ticker", "sector_code", "sector_name", "market", "source"), ("effective_date", "ticker", "sector_code", "market"), "Membership is an independent PIT store", True, "Future PIT membership phase; current PyKRX source remains"),
    StoreContract("FundamentalsStore", "PIT reported fundamentals", "FUNDAMENTALS_V01", ("ticker", "period_end", "report_date", "availability_date", "metric", "value", "source"), ("ticker", "period_end", "availability_date", "metric", "value"), "OpenDART facts are independent of price authority", True, "Existing OpenDART pipeline; no migration in this phase"),
    StoreContract("CorporateActionStateStore", "Adjusted-cache refresh state", "CORPORATE_ACTION_STATE_V01", ("ticker", "as_of", "status", "dirty_reason", "last_success_at", "last_attempt_at"), ("ticker", "as_of", "status"), "State is separate from immutable raw history and mutable adjusted cache", True, "Detector only; no custom adjustment engine"),
)


LAYER_REGISTRY: tuple[LayerContract, ...] = (
    LayerContract("STOCK_RAW_KRX", "Raw stock OHLC and ancillary", "KRX Open API", "KRX Open API", "KRX Open API", "KRXRawStockStore", True, "Daily trading session", MigrationStatus.VALIDATED_NOT_PRODUCTION_MIGRATED.value),
    LayerContract("STOCK_ADJUSTED_PYKRX", "Adjusted stock OHLC", "PyKRX adjusted=True", "Legacy composite cache", "AdjustedPriceStore", "AdjustedPriceStore", True, "Daily trading session", MigrationStatus.LEGACY_COMPOSITE_NOT_SPLIT.value),
    LayerContract("STOCK_MASTER_KRX", "PIT stock master", "KRX Open API Basic Info", "KRX Open API Basic Info", "StockMasterStore", "StockMasterStore", True, "Snapshot on source effective date", MigrationStatus.VALIDATED_NOT_PRODUCTION_MIGRATED.value),
    LayerContract("MARKET_INDEX", "KOSPI/KOSDAQ representative indexes", "KRX Open API", "PyKRX existing source", "KRX Open API", "IndexStore:MARKET_INDEX", True, "Daily trading session", MigrationStatus.LEGACY_SOURCE.value),
    LayerContract("SECTOR_INDEX_KRX", "Native 46 sector indexes", "KRX Open API", "KRX Open API", "KRX Open API", "IndexStore:NATIVE_SECTOR_INDEX", True, "Daily trading session", MigrationStatus.MIGRATED.value),
    LayerContract("SECTOR_MEMBERSHIP", "Ticker to sector membership", "PyKRX current source", "PyKRX get_index_portfolio_deposit_file", "SectorMembershipStore", "SectorMembershipStore", True, "Effective-date snapshot", MigrationStatus.LEGACY_SOURCE.value),
    LayerContract("FOREIGN_FLOW", "Foreign/institution flow", "Existing production flow source", "Existing production flow source", "Existing production flow source", "Flow store (existing)", True, "Provider-defined", MigrationStatus.LEGACY_SOURCE.value),
    LayerContract("FUNDAMENTALS_OPENDART", "Reported financial statements", "OpenDART", "OpenDART", "FundamentalsStore", "FundamentalsStore", True, "Availability-date/PIT", MigrationStatus.CLOSED_AVAILABLE.value),
    LayerContract("MARKET_RS", "Market relative strength", "Derived from stock and market index", "Existing analytics", "Existing analytics", "Analytics output", True, "As-of session", MigrationStatus.NOT_MIGRATED.value),
    LayerContract("SECTOR_RS", "Sector relative strength", "Derived from sector index", "Existing analytics", "Existing analytics", "Analytics output", True, "As-of session", MigrationStatus.NOT_MIGRATED.value),
    LayerContract("PATTERN_A", "Pattern A features and score", "Derived", "Existing analytics", "Existing analytics", "Analytics output", True, "As-of session", MigrationStatus.NOT_MIGRATED.value),
    LayerContract("FASTCORE", "FastCore features and score", "Derived", "Existing analytics", "Existing analytics", "Analytics output", True, "As-of session", MigrationStatus.NOT_MIGRATED.value),
    LayerContract("JULIA", "Julia strategy inputs and outputs", "Derived", "Existing analytics", "Existing analytics", "Analytics output", True, "As-of session", MigrationStatus.NOT_MIGRATED.value),
    LayerContract("STOCK_REPORT", "Stock report", "Derived", "Existing reporting", "Existing reporting", "Analytics output", True, "As-of session", MigrationStatus.NOT_MIGRATED.value),
)


ENDPOINT_IDENTIFIER_CONTRACT: dict[str, Any] = {
    "DAILY_TRADING": {
        "endpoints": ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd"),
        "fields": {"ISU_CD": {"semantic": "ticker", "target_field": "ticker", "identifier_namespace": "SIX_DIGIT_TICKER"}},
    },
    "BASIC_INFO": {
        "endpoints": ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info"),
        "fields": {
            "ISU_CD": {"semantic": "standard_code", "target_field": "standard_code", "identifier_namespace": "KRX_STANDARD_CODE"},
            "ISU_SRT_CD": {"semantic": "ticker", "target_field": "ticker", "identifier_namespace": "SIX_DIGIT_TICKER"},
            "SECT_TP_NM": {"semantic": "listing_section_or_security_group", "target_field": "security_group", "identifier_namespace": "NOT_SECTOR_MEMBERSHIP"},
        },
    },
    "NATIVE_SECTOR_INDEX": {
        "endpoints": ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"),
        "fields": {"IDX_CD": {"semantic": "native_sector_index_code", "target_field": "index_code", "identifier_namespace": "KRX_NATIVE_SECTOR_INDEX"}},
    },
}


REPOSITORY_V2_CONTRACT: dict[str, Any] = {
    "name": "MarketDataRepositoryV2",
    "get_daily": {
        "price_columns": ("open", "high", "low", "close"),
        "price_semantics": "ADJUSTED",
        "volume_column": "volume",
        "volume_semantics": "RAW",
        "trading_value_column": "trading_value",
        "trading_value_semantics": "RAW",
        "join_key": ("ticker", "date"),
        "join_type": "INNER_CONSISTENT_TRADING_SESSION_JOIN",
        "missing_side_behavior": "DATA_UNAVAILABLE",
        "forward_fill": False,
    },
    "ancillary_access": ("get_raw_daily", "get_daily_ancillary", "get_stock_snapshot"),
    "compatibility": "Existing get_daily consumers keep their current columns and receive no silent semantic change.",
}


CONSUMER_COMPATIBILITY: tuple[dict[str, Any], ...] = (
    {"consumer": "Pattern A", "current_input": "MarketDataRepository/get_daily or legacy cache", "required_columns": ("open", "high", "low", "close", "volume"), "current_source_semantics": "legacy composite adjusted OHLC + raw volume", "target_source_semantics": "adjusted OHLC + raw volume", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "FastCore", "current_input": "legacy composite cache", "required_columns": ("open", "high", "low", "close", "volume"), "current_source_semantics": "legacy composite", "target_source_semantics": "adjusted OHLC + raw volume", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "Julia", "current_input": "legacy composite cache", "required_columns": ("open", "high", "low", "close", "volume", "market_cap"), "current_source_semantics": "legacy cache plus ancillary", "target_source_semantics": "adjusted OHLC + raw ancillary", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "Relative Strength", "current_input": "stock/index daily frames", "required_columns": ("close",), "current_source_semantics": "current index providers", "target_source_semantics": "PIT repository/index stores", "migration_required": "PLANNED_INDEX_PIT", "expected_behavior_change": "NONE"},
    {"consumer": "Foreign Flow", "current_input": "existing flow provider", "required_columns": ("date", "ticker"), "current_source_semantics": "current production flow source", "target_source_semantics": "existing flow source", "migration_required": "NO_RUNTIME_CHANGE", "expected_behavior_change": "NONE"},
    {"consumer": "Stock Report", "current_input": "legacy cache and analytics", "required_columns": ("open", "high", "low", "close", "volume"), "current_source_semantics": "legacy composite", "target_source_semantics": "repository contract", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "Resampler", "current_input": "daily repository output", "required_columns": ("open", "high", "low", "close", "volume", "trading_value"), "current_source_semantics": "daily adjusted OHLC + raw ancillary", "target_source_semantics": "derived weekly/monthly", "migration_required": "NO_RUNTIME_CHANGE", "expected_behavior_change": "NONE"},
)


OBSERVABILITY_CONTRACT = ObservabilityContract(
    statuses=tuple(status.value for status in HealthStatus),
    snapshot_fields=("layer_id", "status", "source_name", "latest_data_date", "expected_latest_date", "date_min", "date_max", "row_count", "ticker_count", "missing_count", "stale_count", "error_count", "last_success_at", "last_attempt_at", "message"),
    quota_fields=("usage_date_kst", "used", "limit", "remaining", "percentage", "endpoint_usage"),
)


DEPENDENCY_GRAPH: dict[str, Any] = {
    "nodes": ("KRX_PRODUCTION_DATA_ARCHITECTURE_V01", "ADJUSTED_PRICE_STORE_V01", "CORPORATE_ACTION_DIRTY_REFRESH_V01", "KRX_HISTORICAL_BACKFILL_V01", "MARKET_DATA_REPOSITORY_V02", "KRX_INDEX_MIGRATION_V01", "END_TO_END_DATA_PARITY_V01"),
    "edges": (("KRX_PRODUCTION_DATA_ARCHITECTURE_V01", "ADJUSTED_PRICE_STORE_V01"), ("ADJUSTED_PRICE_STORE_V01", "CORPORATE_ACTION_DIRTY_REFRESH_V01"), ("CORPORATE_ACTION_DIRTY_REFRESH_V01", "KRX_HISTORICAL_BACKFILL_V01"), ("KRX_HISTORICAL_BACKFILL_V01", "MARKET_DATA_REPOSITORY_V02"), ("MARKET_DATA_REPOSITORY_V02", "KRX_INDEX_MIGRATION_V01"), ("KRX_INDEX_MIGRATION_V01", "END_TO_END_DATA_PARITY_V01")),
}


LEGACY_CACHE_CLASSIFICATION = {
    "path": "data/raw/stocks/<ticker>.parquet",
    "classification": "LEGACY_COMPOSITE_STOCK_CACHE",
    "contains": ("adjusted OHLC", "raw volume", "raw trading_value"),
    "raw_krx_store": False,
    "rewritten_in_this_phase": False,
    "write_protection": ("rewrite", "move", "delete", "bulk rename"),
}


SCHEMA_VERSIONS = {
    "KRXRawStockStore": "KRX_RAW_STOCK_V01",
    "AdjustedPriceStore": "ADJUSTED_PRICE_V01",
    "StockMasterStore": "STOCK_MASTER_V01",
    "IndexStore": "INDEX_STORE_V01",
    "DataHealthSnapshot": "DATA_HEALTH_V01",
}


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "__dataclass_fields__"):
        return {key: _jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def contract_bundle() -> dict[str, Any]:
    """Return a JSON-safe snapshot of every architecture contract."""

    return _jsonable({
        "architecture_version": ARCHITECTURE_VERSION,
        "authority_fields": AUTHORITY_FIELDS,
        "stores": STORE_CONTRACTS,
        "layers": LAYER_REGISTRY,
        "endpoint_identifier_contract": ENDPOINT_IDENTIFIER_CONTRACT,
        "repository_v2": REPOSITORY_V2_CONTRACT,
        "consumer_compatibility": CONSUMER_COMPATIBILITY,
        "observability": OBSERVABILITY_CONTRACT,
        "dependency_graph": DEPENDENCY_GRAPH,
        "legacy_cache": LEGACY_CACHE_CLASSIFICATION,
        "schema_versions": SCHEMA_VERSIONS,
    })
