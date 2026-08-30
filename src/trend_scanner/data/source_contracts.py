"""Machine-readable production data authority contracts.

The module is declarative and network-free. It separates source authority,
field provenance, operational availability, migration state, and runtime health.
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


class ProvenanceOrigin(str, Enum):
    RESPONSE_FIELD = "RESPONSE_FIELD"
    REQUEST_PARAMETER = "REQUEST_PARAMETER"
    STATIC_MAPPING = "STATIC_MAPPING"
    DERIVED = "DERIVED"
    STATE = "STATE"
    PROVENANCE_METADATA = "PROVENANCE_METADATA"
    DERIVED_SOURCE_TRACE = "DERIVED_SOURCE_TRACE"
    LEGACY_SOURCE = "LEGACY_SOURCE"


class OperationalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    DEGRADED = "DEGRADED"
    VALIDATION_ONLY = "VALIDATION_ONLY"


class MigrationStatus(str, Enum):
    MIGRATED = "MIGRATED"
    LEGACY_SOURCE = "LEGACY_SOURCE"
    VALIDATED_NOT_PRODUCTION_MIGRATED = "VALIDATED_NOT_PRODUCTION_MIGRATED"
    LEGACY_COMPOSITE_NOT_SPLIT = "LEGACY_COMPOSITE_NOT_SPLIT"
    PARTIALLY_MIGRATED = "PARTIALLY_MIGRATED"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    PLANNED = "PLANNED"


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
    """One explicit (store, target_field) provenance contract."""

    contract_id: str
    owner_store: str | None
    target_field: str
    authority_id: str
    authority_type: AuthorityType
    source_name: str
    source_endpoints: tuple[str, ...]
    source_field: str | None
    source_semantics: str
    field_role: str
    schema_version: str
    provenance_origin: ProvenanceOrigin = ProvenanceOrigin.DERIVED
    source_locator: str | None = None
    derivation_keys: tuple[str, ...] = ()

    @property
    def field_name(self) -> str:
        """Compatibility alias; validation identity is owner_store + target_field."""

        return self.target_field


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
    current_production_source: str
    validated_source: str
    target_source: str
    storage_role: str
    pit_required: bool
    freshness_policy: str
    operational_status: str
    migration_status: str


@dataclass(frozen=True)
class ObservabilityContract:
    statuses: tuple[str, ...]
    snapshot_fields: tuple[str, ...]
    quota_fields: tuple[str, ...]
    separation: str


BASE_ARCHITECTURE_VERSION = "KRX_PRODUCTION_DATA_ARCHITECTURE_V01_FIX03"
ARCHITECTURE_VERSION = "KRX_PRODUCTION_DATA_ARCHITECTURE_V01_ERRATA02"

# Package-owned adjusted-price authority contract.  This is intentionally a
# pure, network-free declaration: Closure artifacts are audit evidence and are
# verified by offline tests, never read by production runtime initialization.
ADJUSTED_PRICE_AUTHORITY_CONTRACT: dict[str, Any] = {
    "authority_id": "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1",
    "source_name": "NAVER_DIRECT_DATE_RANGE_ADJUSTED",
    "source_endpoint": "https://fchart.stock.naver.com/sise.nhn",
    "request_type": 1,
    "timeframe": "day",
    "count": "5000",
    "source_semantics": "ADJUSTED_OHLC_ONLY",
    "authority_type": AuthorityType.AUTHORITATIVE.value,
    "schema_version": "ADJUSTED_PRICE_V02",
    "store_version": "ADJUSTED_PRICE_STORE_V02",
    "closure_version": "V02",
    "closure_artifact_head": "b5e785d92db7b24fadef21fd36602d305dd092de",
    "closure_artifact_tree": "65e6bb999f0fc83f1477912a127d53ed82cc7f77",
    "fix02_head": "99ce7d0b8127f48af3b8b002c246a6c4b0a4395d",
    "fix02_tree": "4dfacef5ffe750675f5fc224003c64504f620603",
    "authority_decision_sha256": "07d191f5e7cbf73a090945cd1751145bd131ca89e6e4d2cc948e2969fd943eba",
}


def _field(
    contract_id: str,
    store_id: str | None,
    target_field: str,
    authority_id: str,
    authority_type: AuthorityType,
    source_name: str,
    source_endpoints: tuple[str, ...],
    source_field: str | None,
    source_semantics: str,
    field_role: str,
    schema_version: str,
    *,
    provenance_origin: ProvenanceOrigin | None = None,
    source_locator: str | None = None,
    derivation_keys: tuple[str, ...] = (),
) -> AuthorityFieldContract:
    if provenance_origin is None:
        if authority_type == AuthorityType.LEGACY:
            provenance_origin = ProvenanceOrigin.LEGACY_SOURCE
        elif source_field is not None:
            provenance_origin = ProvenanceOrigin.RESPONSE_FIELD
        else:
            provenance_origin = ProvenanceOrigin.DERIVED
    return AuthorityFieldContract(
        contract_id,
        store_id,
        target_field,
        authority_id,
        authority_type,
        source_name,
        source_endpoints,
        source_field,
        source_semantics,
        field_role,
        schema_version,
        provenance_origin,
        source_locator,
        derivation_keys,
    )


_KRX_DAILY = ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd")
_KRX_BASIC = ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info")
_PYKRX_ADJUSTED = ("stock.get_market_ohlcv_by_date(adjusted=True)",)
_NAVER_ADJUSTED = ("https://fchart.stock.naver.com/sise.nhn",)


AUTHORITY_FIELDS: tuple[AuthorityFieldContract, ...] = (
    _field("raw.date", "KRXRawStockStore", "date", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.DERIVED, "KRX Open API", _KRX_DAILY, "BAS_DD", "SOURCE_OBSERVATION_DATE", "TEMPORAL_KEY", "KRX_RAW_STOCK_V01"),
    _field("raw.ticker", "KRXRawStockStore", "ticker", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "ISU_CD", "KRX_SHORT_CODE", "IDENTITY_KEY", "KRX_RAW_STOCK_V01"),
    _field("raw.open", "KRXRawStockStore", "open", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "TDD_OPNPRC", "UNADJUSTED_RAW", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("raw.high", "KRXRawStockStore", "high", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "TDD_HGPRC", "UNADJUSTED_RAW", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("raw.low", "KRXRawStockStore", "low", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "TDD_LWPRC", "UNADJUSTED_RAW", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("raw.close", "KRXRawStockStore", "close", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "TDD_CLSPRC", "UNADJUSTED_RAW", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("raw.volume", "KRXRawStockStore", "volume", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "ACC_TRDVOL", "RAW_DAILY_VOLUME", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("raw.trading_value", "KRXRawStockStore", "trading_value", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "ACC_TRDVAL", "RAW_DAILY_TRADING_VALUE", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("raw.market_cap", "KRXRawStockStore", "market_cap", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "MKTCAP", "RAW_DAILY_MARKET_CAP", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("raw.listed_shares", "KRXRawStockStore", "listed_shares", "KRX_OPEN_API_STOCK_DAILY", AuthorityType.AUTHORITATIVE, "KRX Open API", _KRX_DAILY, "LIST_SHRS", "RAW_DAILY_LISTED_SHARES", "AUTHORITATIVE_SOURCE", "KRX_RAW_STOCK_V01"),
    _field("adjusted.date", "AdjustedPriceStore", "date", "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1", AuthorityType.DERIVED, "NAVER_DIRECT_DATE_RANGE_ADJUSTED", _NAVER_ADJUSTED, "item@data[0]", "SOURCE_OBSERVATION_DATE", "TEMPORAL_KEY", "ADJUSTED_PRICE_V02", source_locator="Naver XML item@data positional field 0"),
    _field("adjusted.ticker", "AdjustedPriceStore", "ticker", "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1", AuthorityType.DERIVED, "NAVER_DIRECT_DATE_RANGE_ADJUSTED", _NAVER_ADJUSTED, None, "SIX_DIGIT_TICKER", "IDENTITY_KEY", "ADJUSTED_PRICE_V02", provenance_origin=ProvenanceOrigin.REQUEST_PARAMETER, source_locator="Naver request parameter symbol"),
    _field("adjusted.open", "AdjustedPriceStore", "open", "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1", AuthorityType.AUTHORITATIVE, "NAVER_DIRECT_DATE_RANGE_ADJUSTED", _NAVER_ADJUSTED, "item@data[1]", "ADJUSTED_OHLC", "AUTHORITATIVE_SOURCE", "ADJUSTED_PRICE_V02", source_locator="Naver XML item@data positional field 1"),
    _field("adjusted.high", "AdjustedPriceStore", "high", "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1", AuthorityType.AUTHORITATIVE, "NAVER_DIRECT_DATE_RANGE_ADJUSTED", _NAVER_ADJUSTED, "item@data[2]", "ADJUSTED_OHLC", "AUTHORITATIVE_SOURCE", "ADJUSTED_PRICE_V02", source_locator="Naver XML item@data positional field 2"),
    _field("adjusted.low", "AdjustedPriceStore", "low", "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1", AuthorityType.AUTHORITATIVE, "NAVER_DIRECT_DATE_RANGE_ADJUSTED", _NAVER_ADJUSTED, "item@data[3]", "ADJUSTED_OHLC", "AUTHORITATIVE_SOURCE", "ADJUSTED_PRICE_V02", source_locator="Naver XML item@data positional field 3"),
    _field("adjusted.close", "AdjustedPriceStore", "close", "NAVER_DIRECT_DATE_RANGE_ADJUSTED_V1", AuthorityType.AUTHORITATIVE, "NAVER_DIRECT_DATE_RANGE_ADJUSTED", _NAVER_ADJUSTED, "item@data[4]", "ADJUSTED_OHLC", "AUTHORITATIVE_SOURCE", "ADJUSTED_PRICE_V02", source_locator="Naver XML item@data positional field 4"),
    _field("master.as_of", "StockMasterStore", "as_of", "KRX_OPEN_API_BASIC_INFO", AuthorityType.DERIVED, "KRX Open API Basic Info", _KRX_BASIC, None, "REQUESTED_SNAPSHOT_DATE", "TEMPORAL_KEY", "STOCK_MASTER_V01", provenance_origin=ProvenanceOrigin.REQUEST_PARAMETER, source_locator="REQUEST_PARAMETER.basDd"),
    _field("master.ticker", "StockMasterStore", "ticker", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "ISU_SRT_CD", "KRX_SHORT_CODE", "IDENTITY_KEY", "STOCK_MASTER_V01"),
    _field("master.standard_code", "StockMasterStore", "standard_code", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "ISU_CD", "KRX_STANDARD_CODE", "IDENTITY_KEY", "STOCK_MASTER_V01"),
    _field("master.name", "StockMasterStore", "name", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "ISU_ABBRV", "SECURITY_NAME", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01"),
    _field("master.raw_market", "StockMasterStore", "raw_market", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "MKT_TP_NM", "KRX_RAW_MARKET_TYPE", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01", provenance_origin=ProvenanceOrigin.RESPONSE_FIELD),
    _field("master.market", "StockMasterStore", "market", "PROJECT_MARKET_NORMALIZATION", AuthorityType.DERIVED, "Project market normalization", ("normalize_krx_market",), None, "CANONICAL_PROJECT_MARKET", "DERIVED_CLASSIFICATION", "STOCK_MASTER_V01", source_locator="normalize_krx_market(raw_market)"),
    _field("master.listing_date", "StockMasterStore", "listing_date", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "LIST_DD", "LISTING_DATE", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01"),
    _field("master.security_group", "StockMasterStore", "security_group", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "SECUGRP_NM", "SECURITY_GROUP", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01"),
    _field("master.listing_section", "StockMasterStore", "listing_section", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "SECT_TP_NM", "LISTING_SECTION", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01"),
    _field("master.security_kind", "StockMasterStore", "security_kind", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "KIND_STKCERT_TP_NM", "SECURITY_CERTIFICATE_KIND", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01", provenance_origin=ProvenanceOrigin.RESPONSE_FIELD),
    _field("master.par_value", "StockMasterStore", "par_value", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "PARVAL", "PAR_VALUE", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01"),
    _field("master.listed_shares", "StockMasterStore", "listed_shares", "KRX_OPEN_API_BASIC_INFO", AuthorityType.AUTHORITATIVE, "KRX Open API Basic Info", _KRX_BASIC, "LIST_SHRS", "MASTER_SNAPSHOT_LISTED_SHARES", "AUTHORITATIVE_SOURCE", "STOCK_MASTER_V01"),
    _field("classification.effective_date", "InstrumentClassificationStore", "effective_date", "INSTRUMENT_CLASSIFICATION", AuthorityType.DERIVED, "InstrumentMetadataResolver", ("InstrumentMetadataResolver",), None, "CLASSIFICATION_EFFECTIVE_DATE", "TEMPORAL_KEY", "INSTRUMENT_CLASSIFICATION_V01", source_locator="InstrumentMetadataResolver.effective_date"),
    _field("classification.ticker", "InstrumentClassificationStore", "ticker", "INSTRUMENT_CLASSIFICATION", AuthorityType.DERIVED, "InstrumentMetadataResolver", ("InstrumentMetadataResolver",), None, "KRX_SHORT_CODE", "IDENTITY_KEY", "INSTRUMENT_CLASSIFICATION_V01", source_locator="InstrumentMetadataResolver.ticker (StockMasterStore KRX_SHORT_CODE namespace)"),
    _field("classification.asset_type", "InstrumentClassificationStore", "asset_type", "INSTRUMENT_CLASSIFICATION", AuthorityType.DERIVED, "Instrument classification pipeline", ("StockMasterStore", "formal product-master authority"), None, "FORMAL_INSTRUMENT_CLASSIFICATION", "DERIVED_CLASSIFICATION", "INSTRUMENT_CLASSIFICATION_V01", source_locator="StockMasterStore.security_group/listing_section/security_kind"),
    _field("classification.classification_authority", "InstrumentClassificationStore", "classification_authority", "INSTRUMENT_CLASSIFICATION", AuthorityType.DERIVED, "InstrumentMetadataResolver", ("InstrumentMetadataResolver",), None, "CLASSIFICATION_AUTHORITY", "PROVENANCE_METADATA", "INSTRUMENT_CLASSIFICATION_V01", provenance_origin=ProvenanceOrigin.STATE, source_locator="InstrumentMetadataResolver.classification_authority"),
    _field("classification.asset_type_source", "InstrumentClassificationStore", "asset_type_source", "INSTRUMENT_CLASSIFICATION", AuthorityType.DERIVED, "InstrumentMetadataResolver", ("InstrumentMetadataResolver",), None, "ASSET_TYPE_SOURCE", "PROVENANCE_METADATA", "INSTRUMENT_CLASSIFICATION_V01", provenance_origin=ProvenanceOrigin.PROVENANCE_METADATA, source_locator="InstrumentMetadataResolver.asset_type_source"),
    _field("classification.source_security_type", "InstrumentClassificationStore", "source_security_type", "INSTRUMENT_CLASSIFICATION", AuthorityType.DERIVED, "Instrument classification pipeline", ("StockMasterStore", "formal product-master authority"), None, "DERIVED_SOURCE_TRACE", "PROVENANCE_METADATA", "INSTRUMENT_CLASSIFICATION_V01", provenance_origin=ProvenanceOrigin.DERIVED_SOURCE_TRACE, source_locator="security_group/listing_section/security_kind and formal product-master evidence"),
    _field("classification.is_common_stock", "InstrumentClassificationStore", "is_common_stock", "INSTRUMENT_CLASSIFICATION", AuthorityType.DERIVED, "Instrument classification pipeline", ("InstrumentClassificationStore",), None, "DERIVED_COMMON_STOCK_FLAG", "DERIVED_CLASSIFICATION", "INSTRUMENT_CLASSIFICATION_V01", source_locator="asset_type == COMMON"),
    _field("index.date", "IndexStore", "date", "KRX_INDEX_SOURCE", AuthorityType.DERIVED, "KRX index source", ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"), "BAS_DD", "SOURCE_OBSERVATION_DATE", "TEMPORAL_KEY", "INDEX_STORE_V01"),
    _field("index.family", "IndexStore", "family", "KRX_INDEX_LOGICAL_FAMILY", AuthorityType.DERIVED, "KRX native sector mapping", ("KRX_NATIVE_SECTOR_INDEX_MAP",), None, "LOGICAL_INDEX_FAMILY", "IDENTITY_KEY", "INDEX_STORE_V01", provenance_origin=ProvenanceOrigin.STATIC_MAPPING, source_locator="KRX_NATIVE_SECTOR_INDEX_MAP -> native sector rows -> NATIVE_SECTOR_INDEX"),
    _field("index.source_index_class", "IndexStore", "source_index_class", "KRX_INDEX_SOURCE", AuthorityType.DERIVED, "KRX index source", ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"), "IDX_CLSS", "KRX_SOURCE_INDEX_CLASS", "PROVENANCE_METADATA", "INDEX_STORE_V01", provenance_origin=ProvenanceOrigin.RESPONSE_FIELD),
    _field("index.index_name", "IndexStore", "index_name", "KRX_INDEX_SOURCE", AuthorityType.AUTHORITATIVE, "KRX index source", ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"), "IDX_NM", "SOURCE_INDEX_NAME", "AUTHORITATIVE_SOURCE", "INDEX_STORE_V01", provenance_origin=ProvenanceOrigin.RESPONSE_FIELD),
    _field("index.index_code", "IndexStore", "index_code", "KRX_NATIVE_SECTOR_INDEX_MAP", AuthorityType.DERIVED, "KRX_NATIVE_SECTOR_INDEX_MAP", ("KRX_NATIVE_SECTOR_INDEX_MAP",), None, "INTERNAL_CANONICAL_INDEX_CODE_FROM_SOURCE_QUALIFIED_MAPPING", "IDENTITY_KEY", "INDEX_STORE_V01", provenance_origin=ProvenanceOrigin.STATIC_MAPPING, source_locator="KRX_NATIVE_SECTOR_INDEX_MAP[(source_api, IDX_CLSS, IDX_NM)]", derivation_keys=("source_api", "IDX_CLSS", "IDX_NM")),
    _field("index.close", "IndexStore", "close", "KRX_NATIVE_SECTOR_INDEX", AuthorityType.AUTHORITATIVE, "KRX Open API", ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"), "CLSPRC_IDX", "INDEX_CLOSE", "AUTHORITATIVE_SOURCE", "INDEX_STORE_V01"),
    _field("membership.effective_date", "SectorMembershipStore", "effective_date", "PYKRX_SECTOR_MEMBERSHIP_CURRENT", AuthorityType.LEGACY, "PyKRX", ("stock.get_index_portfolio_deposit_file",), "date", "MEMBERSHIP_EFFECTIVE_DATE", "TEMPORAL_KEY", "SECTOR_MEMBERSHIP_V01"),
    _field("membership.ticker", "SectorMembershipStore", "ticker", "PYKRX_SECTOR_MEMBERSHIP_CURRENT", AuthorityType.LEGACY, "PyKRX", ("stock.get_index_portfolio_deposit_file",), "ticker", "SIX_DIGIT_TICKER", "IDENTITY_KEY", "SECTOR_MEMBERSHIP_V01"),
    _field("membership.sector_code", "SectorMembershipStore", "sector_code", "KRX_NATIVE_SECTOR_INDEX", AuthorityType.DERIVED, "KRX native sector mapping", ("KRX_NATIVE_SECTOR_INDEX_MAP",), None, "NATIVE_SECTOR_CODE", "AUTHORITATIVE_SOURCE", "SECTOR_MEMBERSHIP_V01", provenance_origin=ProvenanceOrigin.STATIC_MAPPING, source_locator="KRX_NATIVE_SECTOR_INDEX_MAP.sector_code"),
    _field("membership.market", "SectorMembershipStore", "market", "KRX_NATIVE_SECTOR_INDEX", AuthorityType.DERIVED, "KRX native sector mapping", ("KRX_NATIVE_SECTOR_INDEX_MAP",), None, "MARKET_NAMESPACE", "AUTHORITATIVE_SOURCE", "SECTOR_MEMBERSHIP_V01", provenance_origin=ProvenanceOrigin.STATIC_MAPPING, source_locator="KRX_NATIVE_SECTOR_INDEX_MAP.market"),
    _field("fundamentals.ticker", "FundamentalsStore", "ticker", "OPENDART_FUNDAMENTALS", AuthorityType.AUTHORITATIVE, "OpenDART", ("OpenDART financial statements",), "stock_code", "SIX_DIGIT_TICKER", "IDENTITY_KEY", "FUNDAMENTALS_V01"),
    _field("fundamentals.period_end", "FundamentalsStore", "period_end", "OPENDART_FUNDAMENTALS", AuthorityType.AUTHORITATIVE, "OpenDART", ("OpenDART financial statements",), "period_end", "REPORTING_PERIOD_END", "TEMPORAL_KEY", "FUNDAMENTALS_V01"),
    _field("fundamentals.availability_date", "FundamentalsStore", "availability_date", "OPENDART_FUNDAMENTALS", AuthorityType.DERIVED, "OpenDART filing registry", ("filing_registry",), "receipt_date", "PIT_AVAILABILITY_DATE", "TEMPORAL_KEY", "FUNDAMENTALS_V01"),
    _field("fundamentals.metric", "FundamentalsStore", "metric", "OPENDART_FUNDAMENTALS", AuthorityType.AUTHORITATIVE, "OpenDART", ("OpenDART financial statements",), "account_id", "FINANCIAL_METRIC", "AUTHORITATIVE_SOURCE", "FUNDAMENTALS_V01"),
    _field("fundamentals.value", "FundamentalsStore", "value", "OPENDART_FUNDAMENTALS", AuthorityType.AUTHORITATIVE, "OpenDART", ("OpenDART financial statements",), "value", "REPORTED_FINANCIAL_VALUE", "AUTHORITATIVE_SOURCE", "FUNDAMENTALS_V01"),
    _field("corp_action.ticker", "CorporateActionStateStore", "ticker", "CORPORATE_ACTION_DETECTOR", AuthorityType.DERIVED, "Corporate action detector", ("LIST_SHRS/PARVAL comparison",), "ticker", "SIX_DIGIT_TICKER", "IDENTITY_KEY", "CORPORATE_ACTION_STATE_V01"),
    _field("corp_action.as_of", "CorporateActionStateStore", "as_of", "CORPORATE_ACTION_DETECTOR", AuthorityType.DERIVED, "Corporate action detector", ("LIST_SHRS/PARVAL comparison",), "as_of", "STATE_OBSERVATION_DATE", "TEMPORAL_KEY", "CORPORATE_ACTION_STATE_V01"),
    _field("corp_action.status", "CorporateActionStateStore", "status", "CORPORATE_ACTION_DETECTOR", AuthorityType.DERIVED, "Corporate action detector", ("LIST_SHRS/PARVAL comparison",), "status", "CLEAN_DIRTY_REFRESHING_FAILED", "STATE_METADATA", "CORPORATE_ACTION_STATE_V01"),
    AuthorityFieldContract("adjusted_volume.none", None, "adjusted_volume", "NONE", AuthorityType.NOT_PROVIDED, "NONE", (), None, "ADJUSTED_VOLUME_NOT_DECLARED", "PROVENANCE_METADATA", "ADJUSTED_PRICE_V02", ProvenanceOrigin.DERIVED),
)

# Every persisted required field is covered by exactly one entry in this
# store-qualified matrix.  The NONE adjusted-volume declaration is excluded.
STORE_FIELD_PROVENANCE: tuple[AuthorityFieldContract, ...] = tuple(
    item for item in AUTHORITY_FIELDS if item.owner_store is not None
)


STORE_CONTRACTS: tuple[StoreContract, ...] = (
    StoreContract("KRXRawStockStore", "KRX unadjusted daily stock facts", "KRX_RAW_STOCK_V01", ("date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"), ("date", "ticker", "open", "high", "low", "close", "volume", "trading_value", "market_cap", "listed_shares"), "Raw OHLC and raw ancillary are owned here; no adjustment", True, "New normalized store; no bulk migration in this phase"),
    StoreContract("AdjustedPriceStore", "Adjusted OHLC only; current authoritative writes use Naver V02 and legacy V01 remains readable but non-current", "ADJUSTED_PRICE_V02", ("date", "ticker", "open", "high", "low", "close"), ("date", "ticker", "open", "high", "low", "close"), "Adjusted OHLC only; ancillary fields are prohibited", True, "Current Naver V02 writes; legacy V01 readable but non-current; full-population refresh pending"),
    StoreContract("StockMasterStore", "Point-in-time KRX raw/canonical security master; final asset_type belongs to InstrumentClassificationStore", "STOCK_MASTER_V01", ("as_of", "ticker", "standard_code", "name", "raw_market", "market", "listing_date", "security_group", "listing_section", "security_kind", "par_value", "listed_shares"), ("as_of", "ticker", "standard_code", "name", "raw_market", "market", "listing_date", "security_group", "listing_section", "security_kind", "par_value", "listed_shares"), "Historical snapshots, not latest-only identity; no final asset_type authority", True, "PIT snapshots; no replacement of current frozen artifact in this phase"),
    StoreContract("InstrumentClassificationStore", "Point-in-time canonical instrument applicability and asset-type classification", "INSTRUMENT_CLASSIFICATION_V01", ("effective_date", "ticker", "asset_type", "classification_authority", "asset_type_source", "source_security_type", "is_common_stock"), ("effective_date", "ticker", "asset_type", "classification_authority", "asset_type_source"), "Derived classification authority; equity inputs come from StockMasterStore and ETF/ETN inputs retain formal product-master authority", True, "PIT classification snapshots; future migration from InstrumentMetadataResolver"),
    StoreContract("IndexStore", "Market and native sector index families", "INDEX_STORE_V01", ("date", "family", "source_index_class", "index_code", "index_name", "open", "high", "low", "close", "volume", "trading_value"), ("date", "family", "source_index_class", "index_code", "close"), "MARKET_INDEX, NATIVE_SECTOR_INDEX, and KRX_BRANDED_TAXONOMY namespaces stay distinct; canonical identity is (family, index_code)", True, "Sector index migrated; market index remains legacy"),
    StoreContract("SectorMembershipStore", "PIT ticker to sector membership", "SECTOR_MEMBERSHIP_V01", ("effective_date", "as_of", "ticker", "sector_code", "sector_name", "market", "source"), ("effective_date", "ticker", "sector_code", "market"), "Membership is an independent PIT store", True, "Future PIT membership phase; current PyKRX source remains"),
    StoreContract("FundamentalsStore", "PIT reported fundamentals", "FUNDAMENTALS_V01", ("ticker", "period_end", "report_date", "availability_date", "metric", "value", "source"), ("ticker", "period_end", "availability_date", "metric", "value"), "OpenDART facts are independent of price authority", True, "Existing OpenDART pipeline; no migration in this phase"),
    StoreContract("CorporateActionStateStore", "Adjusted-cache refresh state", "CORPORATE_ACTION_STATE_V01", ("ticker", "as_of", "status", "dirty_reason", "last_success_at", "last_attempt_at"), ("ticker", "as_of", "status"), "State is separate from immutable raw history and mutable adjusted cache", True, "Detector only; no custom adjustment engine"),
)


def _layer(layer_id: str, description: str, authority: str, current: str, validated: str, target: str, storage: str, freshness: str, operational: OperationalStatus, migration: MigrationStatus) -> LayerContract:
    return LayerContract(layer_id, description, authority, current, validated, target, storage, True, freshness, operational.value, migration.value)


LAYER_REGISTRY: tuple[LayerContract, ...] = (
    _layer("STOCK_RAW_KRX", "Raw stock OHLC and ancillary", "KRX Open API", "LEGACY_COMPOSITE_STOCK_CACHE", "KRX Open API", "KRXRawStockStore", "KRXRawStockStore", "Daily trading session", OperationalStatus.INACTIVE, MigrationStatus.VALIDATED_NOT_PRODUCTION_MIGRATED),
    _layer("STOCK_ADJUSTED", "Adjusted stock OHLC", "Naver Direct Date-Range Adjusted", "NaverDirectAdjustedPriceDataProvider -> AdjustedPriceStore V02", "Closure V02 authorized Naver direct date-range adjusted", "AdjustedPriceStore", "AdjustedPriceStore", "Daily trading session", OperationalStatus.ACTIVE, MigrationStatus.PARTIALLY_MIGRATED),
    _layer("STOCK_MASTER_KRX", "PIT raw/canonical KRX security master; asset_type authority is separate", "KRX Open API Basic Info", "InstrumentMetadataResolver -> data/reference/krx_instrument_metadata.parquet (frozen local KRX artifact; raw/master facts)", "KRX Open API Basic Info", "StockMasterStore", "StockMasterStore", "Snapshot on source effective date", OperationalStatus.ACTIVE, MigrationStatus.VALIDATED_NOT_PRODUCTION_MIGRATED),
    _layer("INSTRUMENT_CLASSIFICATION", "PIT canonical instrument asset-type and applicability classification", "InstrumentMetadataResolver formal instrument metadata authority", "InstrumentMetadataResolver -> data/reference/krx_instrument_metadata.parquet", "Existing formal KRX instrument classification pipeline", "InstrumentClassificationStore", "InstrumentClassificationStore", "Effective-date PIT lookup", OperationalStatus.ACTIVE, MigrationStatus.LEGACY_SOURCE),
    _layer("MARKET_INDEX", "KOSPI/KOSDAQ representative indexes", "KRX Open API", "PyKRX existing source", "KRX Open API validated index endpoints", "KRX Open API / IndexStore", "IndexStore:MARKET_INDEX", "Daily trading session", OperationalStatus.ACTIVE, MigrationStatus.LEGACY_SOURCE),
    _layer("SECTOR_INDEX_KRX", "Native 46 sector indexes", "KRX Open API", "KRX Open API", "KRX Open API", "KRX Open API / IndexStore", "IndexStore:NATIVE_SECTOR_INDEX", "Daily trading session", OperationalStatus.ACTIVE, MigrationStatus.MIGRATED),
    _layer("SECTOR_MEMBERSHIP", "Ticker to sector membership", "PyKRX current source", "PyKRX get_index_portfolio_deposit_file", "PyKRX get_index_portfolio_deposit_file", "SectorMembershipStore", "SectorMembershipStore", "Effective-date snapshot", OperationalStatus.ACTIVE, MigrationStatus.LEGACY_SOURCE),
    _layer("FOREIGN_FLOW", "Foreign/institution flow", "KRX_PYKRX_FOREIGN_FLOW", "KRX_PYKRX_FOREIGN_FLOW artifact-backed cache", "PyKRX get_market_net_purchases_of_equities_by_ticker", "ForeignFlowStore (future)", "Foreign flow artifact/cache", "Provider-defined daily batch", OperationalStatus.ACTIVE, MigrationStatus.LEGACY_SOURCE),
    _layer("FUNDAMENTALS_OPENDART", "Reported financial statements", "OpenDART", "OpenDART", "OpenDART", "FundamentalsStore", "FundamentalsStore", "Availability-date/PIT", OperationalStatus.ACTIVE, MigrationStatus.NOT_APPLICABLE),
    _layer("MARKET_RS", "Market relative strength", "Derived from stock and market index", "Existing analytics", "Existing analytics", "Existing analytics", "Analytics output", "As-of session", OperationalStatus.ACTIVE, MigrationStatus.PARTIALLY_MIGRATED),
    _layer("SECTOR_RS", "Sector relative strength", "Derived from KRX sector index", "Existing analytics", "KRX sector index migration", "Existing analytics", "Analytics output", "As-of session", OperationalStatus.ACTIVE, MigrationStatus.MIGRATED),
    _layer("PATTERN_A", "Pattern A features and score", "Derived", "Existing analytics", "Existing analytics", "Existing analytics", "Analytics output", "As-of session", OperationalStatus.ACTIVE, MigrationStatus.NOT_APPLICABLE),
    _layer("FASTCORE", "FastCore features and score", "Derived", "Existing analytics", "Existing analytics", "Existing analytics", "Analytics output", "As-of session", OperationalStatus.ACTIVE, MigrationStatus.NOT_APPLICABLE),
    _layer("JULIA", "Julia strategy inputs and outputs", "Derived", "Existing analytics", "Existing analytics", "Existing analytics", "Analytics output", "As-of session", OperationalStatus.ACTIVE, MigrationStatus.NOT_APPLICABLE),
    _layer("STOCK_REPORT", "Stock report", "Derived", "Existing reporting", "Existing reporting", "Existing reporting", "Analytics output", "As-of session", OperationalStatus.ACTIVE, MigrationStatus.NOT_APPLICABLE),
)


ENDPOINT_IDENTIFIER_CONTRACT: dict[str, Any] = {
    "DAILY_TRADING": {"endpoints": _KRX_DAILY, "fields": {"ISU_CD": {"semantic": "ticker", "target_field": "ticker", "identifier_namespace": "KRX_SHORT_CODE"}}},
    "BASIC_INFO": {"endpoints": _KRX_BASIC, "fields": {
        "ISU_CD": {"semantic": "standard_code", "target_field": "standard_code", "identifier_namespace": "KRX_STANDARD_CODE"},
        "ISU_SRT_CD": {"semantic": "ticker", "target_field": "ticker", "identifier_namespace": "KRX_SHORT_CODE"},
        "MKT_TP_NM": {"semantic": "raw_market", "target_field": "raw_market", "identifier_namespace": "KRX_RAW_MARKET_TYPE"},
        "SECUGRP_NM": {"semantic": "security_group", "target_field": "security_group", "identifier_namespace": "NOT_SECTOR_MEMBERSHIP"},
        "SECT_TP_NM": {"semantic": "listing_section", "target_field": "listing_section", "identifier_namespace": "NOT_SECTOR_MEMBERSHIP"},
        "KIND_STKCERT_TP_NM": {"semantic": "security_kind", "target_field": "security_kind", "identifier_namespace": "SECURITY_CERTIFICATE_KIND"},
        "snapshot_date_source": "REQUEST_PARAMETER.basDd",
    }},
    "NATIVE_SECTOR_INDEX": {
        "endpoints": ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd"),
        "raw_identity_fields": ("source_api", "IDX_CLSS", "IDX_NM"),
        "canonical_identity": {
            "target_field": "index_code",
            "provenance_origin": ProvenanceOrigin.STATIC_MAPPING.value,
            "derivation": "DERIVED_FROM_KRX_NATIVE_SECTOR_INDEX_MAP",
            "source_locator": "KRX_NATIVE_SECTOR_INDEX_MAP[(source_api, IDX_CLSS, IDX_NM)]",
            "mapping_key": ("source_api", "IDX_CLSS", "IDX_NM"),
            "index_namespace": "NATIVE_SECTOR_INDEX",
            "canonical_examples": ("1005", "1006", "2012"),
        },
        "fields": {
            "BAS_DD": {"semantic": "observation_date", "target_field": "date", "identifier_namespace": "KRX_INDEX_RESPONSE"},
            "IDX_CLSS": {"semantic": "source_index_class", "target_field": "source_index_class", "identifier_namespace": "KRX_INDEX_RESPONSE"},
            "IDX_NM": {"semantic": "source_index_name", "target_field": "index_name", "identifier_namespace": "KRX_INDEX_RESPONSE"},
        },
    },
}


INSTRUMENT_CLASSIFICATION_CONTRACT: dict[str, Any] = {
    "store_id": "InstrumentClassificationStore",
    "pit_key": ("effective_date", "ticker"),
    "lookup": "latest effective_date <= requested_as_of",
    "equity_source_inputs": ("StockMasterStore.security_group", "StockMasterStore.listing_section", "StockMasterStore.security_kind"),
    "current_production_authority": "InstrumentMetadataResolver -> data/reference/krx_instrument_metadata.parquet",
    "target_authority": "InstrumentClassificationStore",
    "etf_etn_current_authority": "Existing formal ETF/ETN product-master authority retained until separately migrated",
    "basic_info_scope": "KRX KOSPI/KOSDAQ stock Basic Info is not a full ETF/ETN authority",
}


RAW_SCHEMA_CONTRACT: dict[str, Any] = {
    "basic_info_response_fields": (
        "ISU_CD", "ISU_SRT_CD", "ISU_NM", "ISU_ABBRV", "ISU_ENG_NM", "LIST_DD",
        "MKT_TP_NM", "SECUGRP_NM", "SECT_TP_NM", "KIND_STKCERT_TP_NM", "PARVAL", "LIST_SHRS",
    ),
    "index_response_fields": (
        "BAS_DD", "IDX_CLSS", "IDX_NM", "OPNPRC_IDX", "HGPRC_IDX", "LWPRC_IDX", "CLSPRC_IDX",
        "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP",
    ),
    "daily_stock_response_fields": (
        "BAS_DD", "ISU_CD", "TDD_OPNPRC", "TDD_HGPRC", "TDD_LWPRC", "TDD_CLSPRC",
        "ACC_TRDVOL", "ACC_TRDVAL", "MKTCAP", "LIST_SHRS",
    ),
    "request_parameters": {"BASIC_INFO": ("basDd",)},
    "derived_identity_rules": {
        "StockMasterStore.as_of": "REQUEST_PARAMETER.basDd -> REQUESTED_SNAPSHOT_DATE",
        "IndexStore.index_code": "(source_api, IDX_CLSS, IDX_NM) -> KRX_NATIVE_SECTOR_INDEX_MAP -> canonical index_code",
    },
}


LEGACY_RUNTIME_DEPENDENCIES: tuple[dict[str, Any], ...] = (
    {
        "dependency_id": "FOREIGN_FLOW_ARTIFACT_CACHE",
        "consumer": ("full_universe_scanner", "stock_report"),
        "path_patterns": (
            "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_*.parquet",
            "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_*.csv",
            "artifacts/patterns/pattern_a/production/flow/source*",
        ),
        "purpose": "Foreign Flow daily cache consumption",
        "current_source": "KRX_PYKRX_FOREIGN_FLOW artifact-backed cache",
        "migration_target": "ForeignFlowStore",
        "migration_phase": "ADJUSTED_PRICE_STORE_V01+",
        "classification": "LEGACY_RUNTIME_ARTIFACT_DEPENDENCY",
    },
    {
        "dependency_id": "INVESTABILITY_MARKET_CAP_ARTIFACT_CACHE",
        "consumer": ("full_universe_scanner", "stock_report"),
        "path_patterns": (
            "artifacts/patterns/pattern_a/production/investability*",
            "artifacts/patterns/pattern_a/validation/investability_history/normalized*",
            "artifacts/patterns/pattern_a/production/scanner*",
        ),
        "purpose": "Investability universe and PIT market-cap snapshots",
        "current_source": "Pattern A investability/scanner artifact snapshots",
        "migration_target": "StockMasterStore + KRXRawStockStore ancillary access",
        "migration_phase": "ADJUSTED_PRICE_STORE_V01+",
        "classification": "LEGACY_RUNTIME_ARTIFACT_DEPENDENCY",
    },
    {
        "dependency_id": "RELATIVE_STRENGTH_ARTIFACT_CACHE",
        "consumer": ("full_universe_scanner", "relative_strength_report"),
        "path_patterns": ("artifacts/patterns/pattern_a/validation/relative_strength*",),
        "purpose": "Market/sector relative-strength snapshot consumption",
        "current_source": "Pattern A relative-strength validation artifacts",
        "migration_target": "Market/sector index stores and RS runtime source",
        "migration_phase": "INDEX_PIT_MIGRATION_V01",
        "classification": "LEGACY_RUNTIME_ARTIFACT_DEPENDENCY",
    },
    {
        "dependency_id": "PATTERN_A_FAST_CONTRACT_ARTIFACT",
        "consumer": ("pattern_a_fast_report", "stock_report"),
        "path_patterns": ("artifacts/patterns/pattern_a_fast/production/contract_prototype*",),
        "purpose": "Pattern A FAST score/stage contract loading",
        "current_source": "Pattern A FAST contract prototype artifacts",
        "migration_target": "Versioned package contract / Store-independent runtime configuration",
        "migration_phase": "FASTCORE_CONTRACT_MIGRATION_V01",
        "classification": "LEGACY_RUNTIME_ARTIFACT_DEPENDENCY",
    },
)


TARGET_ARCHITECTURE_RUNTIME_ARTIFACT_COMPONENTS: tuple[str, ...] = (
    "KRXRawStockStore", "AdjustedPriceStore", "StockMasterStore", "InstrumentClassificationStore", "IndexStore", "MarketDataRepositoryV2",
)


REPOSITORY_V2_CONTRACT: dict[str, Any] = {
    "name": "MarketDataRepositoryV2",
    "get_daily": {"price_columns": ("open", "high", "low", "close"), "price_semantics": "ADJUSTED", "volume_column": "volume", "volume_semantics": "RAW", "trading_value_column": "trading_value", "trading_value_semantics": "RAW", "join_key": ("ticker", "date"), "join_type": "INNER_CONSISTENT_TRADING_SESSION_JOIN", "missing_side_behavior": "DATA_UNAVAILABLE", "forward_fill": False},
    "ancillary_access": ("get_raw_daily", "get_daily_ancillary", "get_stock_snapshot"),
    "compatibility": "Existing get_daily consumers keep their current columns and receive no silent semantic change.",
}


CONSUMER_COMPATIBILITY: tuple[dict[str, Any], ...] = (
    {"consumer": "Pattern A", "current_input": "MarketDataRepository/get_daily or legacy cache", "required_columns": ("open", "high", "low", "close", "volume"), "current_source_semantics": "legacy composite adjusted OHLC + raw volume", "target_source_semantics": "adjusted OHLC + raw volume", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "FastCore", "current_input": "legacy composite cache", "required_columns": ("open", "high", "low", "close", "volume"), "current_source_semantics": "legacy composite", "target_source_semantics": "adjusted OHLC + raw volume", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "Julia", "current_input": "legacy composite cache", "required_columns": ("open", "high", "low", "close", "volume", "market_cap"), "current_source_semantics": "legacy cache plus ancillary", "target_source_semantics": "adjusted OHLC + raw ancillary", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "Relative Strength", "current_input": "stock/index daily frames", "required_columns": ("close",), "current_source_semantics": "current index providers", "target_source_semantics": "PIT repository/index stores", "migration_required": "PLANNED_INDEX_PIT", "expected_behavior_change": "NONE"},
    {"consumer": "Foreign Flow", "current_input": "foreign_flow_daily_<as_of>.parquet", "required_columns": ("date", "ticker", "foreign_net_buy_value"), "current_source_semantics": "KRX_PYKRX_FOREIGN_FLOW", "target_source_semantics": "ForeignFlowStore", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "Stock Report", "current_input": "legacy cache and analytics", "required_columns": ("open", "high", "low", "close", "volume"), "current_source_semantics": "legacy composite", "target_source_semantics": "repository contract", "migration_required": "PLANNED_REPOSITORY_V2", "expected_behavior_change": "NONE"},
    {"consumer": "Instrument Metadata / Applicability", "current_input": "InstrumentMetadataResolver", "required_columns": ("ticker", "asset_type", "classification_authority", "asset_type_source", "effective_date"), "current_source_semantics": "current formal InstrumentMetadata authority", "target_source_semantics": "InstrumentClassificationStore PIT classification", "migration_required": "PLANNED_CLASSIFICATION_STORE", "expected_behavior_change": "NONE"},
    {"consumer": "Resampler", "current_input": "daily repository output", "required_columns": ("open", "high", "low", "close", "volume", "trading_value"), "current_source_semantics": "daily adjusted OHLC + raw ancillary", "target_source_semantics": "derived weekly/monthly", "migration_required": "NO_RUNTIME_CHANGE", "expected_behavior_change": "NONE"},
)


FOREIGN_FLOW_LINEAGE: dict[str, Any] = {
    "current_production_source": "KRX_PYKRX_FOREIGN_FLOW",
    "authority_type": AuthorityType.LEGACY.value,
    "source_name": "KRX_PYKRX_FOREIGN_FLOW",
    "source_endpoint": "pykrx.stock.get_market_net_purchases_of_equities_by_ticker(date, date, 'ALL', '외국인')",
    "source_semantics": "daily foreign investor buy/sell/net-buy KRW values by ticker",
    "producer": "ForeignFlowDataProvider.fetch_date_batch -> build_historical_cache; scripts/fetch_foreign_flow_20260814.py",
    "input_store_or_cache": "artifacts/patterns/pattern_a/production/flow/source/foreign_flow_daily_<as_of>.parquet",
    "input_metadata": "foreign_flow_daily_<as_of>_meta.json (source_name, SHA-256, date/row/ticker counts)",
    "consumer": "compute_foreign_flow_features; full_universe_scanner; stock_report",
    "engine_module": "src/trend_scanner/flow/foreign_flow.py",
    "engine_is_upstream_authority": False,
    "lineage_status": "CONFIRMED_FROM_REPOSITORY",
}


OBSERVABILITY_CONTRACT = ObservabilityContract(
    statuses=tuple(status.value for status in HealthStatus),
    snapshot_fields=("layer_id", "status", "source_name", "latest_data_date", "expected_latest_date", "date_min", "date_max", "row_count", "ticker_count", "missing_count", "stale_count", "error_count", "last_success_at", "last_attempt_at", "message"),
    quota_fields=("usage_date_kst", "used", "limit", "remaining", "percentage", "endpoint_usage"),
    separation="LayerRegistry is static operational/migration architecture state; DataHealthSnapshot is runtime condition; Dashboard joins both by layer_id.",
)


DEPENDENCY_GRAPH: dict[str, Any] = {
    "nodes": ("KRX_PRODUCTION_DATA_ARCHITECTURE_V01", "ADJUSTED_PRICE_STORE_V02", "CORPORATE_ACTION_DIRTY_REFRESH_V01", "KRX_HISTORICAL_BACKFILL_V01", "MARKET_DATA_REPOSITORY_V02", "KRX_INDEX_MIGRATION_V01", "END_TO_END_DATA_PARITY_V01"),
    "edges": (("KRX_PRODUCTION_DATA_ARCHITECTURE_V01", "ADJUSTED_PRICE_STORE_V02"), ("ADJUSTED_PRICE_STORE_V02", "CORPORATE_ACTION_DIRTY_REFRESH_V01"), ("CORPORATE_ACTION_DIRTY_REFRESH_V01", "KRX_HISTORICAL_BACKFILL_V01"), ("KRX_HISTORICAL_BACKFILL_V01", "MARKET_DATA_REPOSITORY_V02"), ("MARKET_DATA_REPOSITORY_V02", "KRX_INDEX_MIGRATION_V01"), ("KRX_INDEX_MIGRATION_V01", "END_TO_END_DATA_PARITY_V01")),
}


LEGACY_CACHE_CLASSIFICATION = {"path": "data/raw/stocks/<ticker>.parquet", "classification": "LEGACY_COMPOSITE_STOCK_CACHE", "contains": ("adjusted OHLC", "raw volume", "raw trading_value"), "raw_krx_store": False, "rewritten_in_this_phase": False, "write_protection": ("rewrite", "move", "delete", "bulk rename")}
SCHEMA_VERSIONS = {"KRXRawStockStore": "KRX_RAW_STOCK_V01", "AdjustedPriceStore": "ADJUSTED_PRICE_V02", "StockMasterStore": "STOCK_MASTER_V01", "InstrumentClassificationStore": "INSTRUMENT_CLASSIFICATION_V01", "IndexStore": "INDEX_STORE_V01", "DataHealthSnapshot": "DATA_HEALTH_V01"}


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
    return _jsonable({
        "architecture_version": ARCHITECTURE_VERSION,
        "adjusted_price_authority_contract": ADJUSTED_PRICE_AUTHORITY_CONTRACT,
        "authority_fields": AUTHORITY_FIELDS,
        "store_field_provenance": STORE_FIELD_PROVENANCE,
        "stores": STORE_CONTRACTS,
        "layers": LAYER_REGISTRY,
        "endpoint_identifier_contract": ENDPOINT_IDENTIFIER_CONTRACT,
        "raw_schema_contract": RAW_SCHEMA_CONTRACT,
        "instrument_classification_contract": INSTRUMENT_CLASSIFICATION_CONTRACT,
        "repository_v2": REPOSITORY_V2_CONTRACT,
        "consumer_compatibility": CONSUMER_COMPATIBILITY,
        "foreign_flow_lineage": FOREIGN_FLOW_LINEAGE,
        "legacy_runtime_dependencies": LEGACY_RUNTIME_DEPENDENCIES,
        "target_architecture_runtime_artifact_components": TARGET_ARCHITECTURE_RUNTIME_ARTIFACT_COMPONENTS,
        "observability": OBSERVABILITY_CONTRACT,
        "dependency_graph": DEPENDENCY_GRAPH,
        "legacy_cache": LEGACY_CACHE_CLASSIFICATION,
        "schema_versions": SCHEMA_VERSIONS,
    })
