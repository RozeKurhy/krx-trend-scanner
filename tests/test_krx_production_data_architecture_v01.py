"""Offline contract tests for KRX Production Data Architecture v01."""

from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

from trend_scanner.data.source_contracts import (
    AUTHORITY_FIELDS,
    CONSUMER_COMPATIBILITY,
    DEPENDENCY_GRAPH,
    ENDPOINT_IDENTIFIER_CONTRACT,
    FOREIGN_FLOW_LINEAGE,
    HealthStatus,
    INSTRUMENT_CLASSIFICATION_CONTRACT,
    LEGACY_RUNTIME_DEPENDENCIES,
    LAYER_REGISTRY,
    LEGACY_CACHE_CLASSIFICATION,
    MigrationStatus,
    OperationalStatus,
    OBSERVABILITY_CONTRACT,
    ProvenanceOrigin,
    RAW_SCHEMA_CONTRACT,
    REPOSITORY_V2_CONTRACT,
    STORE_CONTRACTS,
    STORE_FIELD_PROVENANCE,
    contract_bundle,
)


def _has_cycle(nodes: tuple[str, ...], edges: tuple[tuple[str, str], ...]) -> bool:
    graph = {node: [] for node in nodes}
    for source, target in edges:
        graph[source].append(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(child) for child in graph[node]):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in nodes)


def test_each_authoritative_field_has_exactly_one_authority():
    authoritative = [item for item in AUTHORITY_FIELDS if item.authority_type.value == "AUTHORITATIVE"]
    assert authoritative
    assert len({(item.owner_store, item.target_field) for item in authoritative}) == len(authoritative)
    assert all(item.authority_id and item.source_name and item.owner_store for item in authoritative)


def test_adjusted_and_raw_store_ownership_is_disjoint():
    raw = next(item for item in STORE_CONTRACTS if item.store_id == "KRXRawStockStore")
    adjusted = next(item for item in STORE_CONTRACTS if item.store_id == "AdjustedPriceStore")
    assert set(adjusted.fields) == {"date", "ticker", "open", "high", "low", "close"}
    assert {"volume", "trading_value", "market_cap", "listed_shares"}.issubset(raw.fields)
    assert not {"volume", "trading_value", "market_cap", "listed_shares"}.intersection(adjusted.fields)


def test_endpoint_identifier_semantics_are_qualified():
    daily = ENDPOINT_IDENTIFIER_CONTRACT["DAILY_TRADING"]["fields"]["ISU_CD"]
    basic_code = ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]["ISU_CD"]
    basic_ticker = ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]["ISU_SRT_CD"]
    security_group = ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]["SECUGRP_NM"]
    sect = ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]["SECT_TP_NM"]
    assert daily["semantic"] == "ticker"
    assert basic_code["semantic"] == "standard_code"
    assert basic_ticker["semantic"] == "ticker"
    assert security_group["semantic"] == "security_group"
    assert security_group["target_field"] == "security_group"
    assert sect["semantic"] == "listing_section"
    assert sect["target_field"] == "listing_section"
    assert security_group["target_field"] != "sector_code"
    assert sect["target_field"] != "sector_code"
    assert security_group["identifier_namespace"] == "NOT_SECTOR_MEMBERSHIP"
    assert sect["identifier_namespace"] == "NOT_SECTOR_MEMBERSHIP"


def test_basic_info_response_has_no_bas_dd_contract():
    assert "BAS_DD" not in RAW_SCHEMA_CONTRACT["basic_info_response_fields"]
    as_of = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "StockMasterStore" and item.target_field == "as_of")
    assert as_of.source_field is None


def test_stock_master_as_of_is_request_parameter_derived():
    as_of = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "StockMasterStore" and item.target_field == "as_of")
    assert as_of.provenance_origin == ProvenanceOrigin.REQUEST_PARAMETER
    assert as_of.source_locator == "REQUEST_PARAMETER.basDd"
    assert as_of.source_semantics == "REQUESTED_SNAPSHOT_DATE"


def test_response_field_contracts_exist_in_known_raw_schema():
    validator = _load_validator("krx_architecture_schema_validator")
    assert validator._provenance_contract_error_counts() == {
        "declared_nonexistent_response_field_count": 0,
        "request_derived_field_contract_error_count": 0,
        "static_mapping_field_contract_error_count": 0,
    }


def test_native_index_response_has_no_idx_cd():
    native = ENDPOINT_IDENTIFIER_CONTRACT["NATIVE_SECTOR_INDEX"]
    assert "IDX_CD" not in RAW_SCHEMA_CONTRACT["index_response_fields"]
    assert "IDX_CD" not in native["raw_identity_fields"]
    assert "IDX_CD" not in native["fields"]
    assert next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "IndexStore" and item.target_field == "index_code").source_field is None


def test_index_code_is_static_mapping_derived():
    index_code = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "IndexStore" and item.target_field == "index_code")
    assert index_code.provenance_origin == ProvenanceOrigin.STATIC_MAPPING
    assert index_code.source_name == "KRX_NATIVE_SECTOR_INDEX_MAP"
    assert index_code.source_locator == "KRX_NATIVE_SECTOR_INDEX_MAP[(source_api, IDX_CLSS, IDX_NM)]"
    assert index_code.derivation_keys == ("source_api", "IDX_CLSS", "IDX_NM")


def test_index_identity_is_source_qualified():
    native = ENDPOINT_IDENTIFIER_CONTRACT["NATIVE_SECTOR_INDEX"]
    assert native["raw_identity_fields"] == ("source_api", "IDX_CLSS", "IDX_NM")
    assert native["canonical_identity"]["mapping_key"] == ("source_api", "IDX_CLSS", "IDX_NM")
    assert native["canonical_identity"]["index_namespace"] == "NATIVE_SECTOR_INDEX"


def test_internal_sector_code_remains_1005_etc_contract():
    examples = ENDPOINT_IDENTIFIER_CONTRACT["NATIVE_SECTOR_INDEX"]["canonical_identity"]["canonical_examples"]
    assert {"1005", "1006", "2012"}.issubset(examples)


def _load_validator(module_name: str):
    validator_path = Path(__file__).resolve().parents[1] / "scripts/validate_krx_production_data_architecture_v01.py"
    spec = importlib.util.spec_from_file_location(module_name, validator_path)
    assert spec and spec.loader
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    return validator


def test_legacy_runtime_artifact_dependencies_are_explicit():
    validator = _load_validator("krx_architecture_legacy_dependency_validator")
    scan = validator._runtime_artifact_dependency_counts(validator._tracked_source_files())
    assert scan["legacy_runtime_artifact_dependency_count"] >= 1
    assert scan["legacy_runtime_artifact_dependency_unclassified_count"] == 0
    assert set(scan["legacy_runtime_artifact_dependencies"]) == {item["dependency_id"] for item in LEGACY_RUNTIME_DEPENDENCIES}


def test_unclassified_runtime_artifact_dependency_is_blocked(tmp_path):
    validator = _load_validator("krx_architecture_unclassified_validator")
    synthetic = tmp_path / "synthetic_runtime.py"
    synthetic.write_text('path = Path("artifacts/patterns/unknown/data.csv")\n', encoding="utf-8")
    scan = validator._runtime_artifact_dependency_counts((synthetic,))
    assert scan["legacy_runtime_artifact_dependency_unclassified_count"] == 1
    assert scan["legacy_runtime_artifact_dependency_count"] == 0


def test_target_stores_have_zero_runtime_artifact_dependency():
    validator = _load_validator("krx_architecture_target_dependency_validator")
    assert validator._target_runtime_artifact_dependency_count() == 0


def test_network_request_and_static_import_counters_are_distinct():
    validator = _load_validator("krx_architecture_network_validator")
    result = validator._validate_contracts()
    assert result["network"]["network_request_count"] == 0
    assert result["network"]["static_forbidden_network_import_count"] == 0
    assert result["counters"]["network_request_count"] == 0
    assert result["counters"]["static_forbidden_network_import_count"] == 0


def test_basic_info_security_group_and_listing_section_are_distinct():
    master = next(item for item in STORE_CONTRACTS if item.store_id == "StockMasterStore")
    assert {"security_group", "listing_section"}.issubset(master.fields)
    assert {"security_group", "listing_section"}.issubset(master.required_fields)
    by_field = {(item.owner_store, item.target_field): item for item in STORE_FIELD_PROVENANCE}
    assert by_field[("StockMasterStore", "security_group")].source_field == "SECUGRP_NM"
    assert by_field[("StockMasterStore", "listing_section")].source_field == "SECT_TP_NM"
    assert by_field[("StockMasterStore", "security_group")].source_semantics != by_field[("StockMasterStore", "listing_section")].source_semantics


def test_stock_master_security_kind_comes_from_kind_stkcert_tp_nm():
    master = next(item for item in STORE_CONTRACTS if item.store_id == "StockMasterStore")
    field = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "StockMasterStore" and item.target_field == "security_kind")
    assert "security_kind" in master.required_fields
    assert "KIND_STKCERT_TP_NM" in RAW_SCHEMA_CONTRACT["basic_info_response_fields"]
    assert field.source_field == "KIND_STKCERT_TP_NM"
    assert field.provenance_origin == ProvenanceOrigin.RESPONSE_FIELD
    assert field.source_semantics == "SECURITY_CERTIFICATE_KIND"


def test_stock_master_raw_market_is_response_field():
    field = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "StockMasterStore" and item.target_field == "raw_market")
    assert field.source_field == "MKT_TP_NM"
    assert field.provenance_origin == ProvenanceOrigin.RESPONSE_FIELD
    assert field.authority_type.value == "AUTHORITATIVE"
    assert field.source_semantics == "KRX_RAW_MARKET_TYPE"


def test_stock_master_market_is_canonical_derived_value():
    field = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "StockMasterStore" and item.target_field == "market")
    assert field.source_field is None
    assert field.provenance_origin == ProvenanceOrigin.DERIVED
    assert "normalize_krx_market" in (field.source_locator or "")
    assert field.source_semantics == "CANONICAL_PROJECT_MARKET"


def test_stock_master_does_not_own_final_asset_type():
    master = next(item for item in STORE_CONTRACTS if item.store_id == "StockMasterStore")
    assert "asset_type" not in master.fields
    assert "asset_type" not in master.required_fields
    assert "final asset_type" in master.description


def test_instrument_classification_store_exists():
    store = next(item for item in STORE_CONTRACTS if item.store_id == "InstrumentClassificationStore")
    assert set(("effective_date", "ticker", "asset_type", "classification_authority", "asset_type_source")).issubset(store.fields)
    assert set(("effective_date", "ticker", "asset_type", "classification_authority", "asset_type_source")).issubset(store.required_fields)


def test_instrument_classification_is_pit():
    store = next(item for item in STORE_CONTRACTS if item.store_id == "InstrumentClassificationStore")
    assert store.pit_required is True
    assert INSTRUMENT_CLASSIFICATION_CONTRACT["pit_key"] == ("effective_date", "ticker")
    assert "latest effective_date" in INSTRUMENT_CLASSIFICATION_CONTRACT["lookup"]


def test_instrument_classification_preserves_asset_type_provenance():
    by_field = {(item.owner_store, item.target_field): item for item in STORE_FIELD_PROVENANCE}
    asset_type = by_field[("InstrumentClassificationStore", "asset_type")]
    authority = by_field[("InstrumentClassificationStore", "classification_authority")]
    source = by_field[("InstrumentClassificationStore", "asset_type_source")]
    assert asset_type.authority_type.value == "DERIVED"
    assert asset_type.source_semantics == "FORMAL_INSTRUMENT_CLASSIFICATION"
    assert "security_group" in (asset_type.source_locator or "")
    assert authority.provenance_origin == ProvenanceOrigin.STATE
    assert source.provenance_origin == ProvenanceOrigin.PROVENANCE_METADATA


def test_instrument_classification_layer_exists():
    layer = next(item for item in LAYER_REGISTRY if item.layer_id == "INSTRUMENT_CLASSIFICATION")
    assert layer.operational_status == OperationalStatus.ACTIVE.value
    assert layer.migration_status in {MigrationStatus.LEGACY_SOURCE.value, MigrationStatus.PLANNED.value}
    assert "InstrumentMetadataResolver" in layer.current_production_source
    assert layer.target_source == "InstrumentClassificationStore"


def test_instrument_classification_consumer_is_registered():
    entry = next(item for item in CONSUMER_COMPATIBILITY if item["consumer"] == "Instrument Metadata / Applicability")
    assert set(entry["required_columns"]) == {"ticker", "asset_type", "classification_authority", "asset_type_source", "effective_date"}
    assert entry["current_input"] == "InstrumentMetadataResolver"
    assert entry["target_source_semantics"] == "InstrumentClassificationStore PIT classification"
    assert entry["migration_required"] == "PLANNED_CLASSIFICATION_STORE"


def test_basic_info_not_falsely_declared_as_full_etf_etn_authority():
    basic = ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]
    assert "ETF" not in str(basic)
    assert "ETN" not in str(basic)
    assert "ETF/ETN" in INSTRUMENT_CLASSIFICATION_CONTRACT["etf_etn_current_authority"]
    assert "not a full ETF/ETN authority" in INSTRUMENT_CLASSIFICATION_CONTRACT["basic_info_scope"]


def test_index_family_is_logical_not_idx_clss():
    family = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "IndexStore" and item.target_field == "family")
    assert family.source_field is None
    assert family.source_semantics == "LOGICAL_INDEX_FAMILY"
    assert family.provenance_origin in {ProvenanceOrigin.DERIVED, ProvenanceOrigin.STATIC_MAPPING}


def test_index_source_index_class_comes_from_idx_clss():
    source_class = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "IndexStore" and item.target_field == "source_index_class")
    assert source_class.source_field == "IDX_CLSS"
    assert source_class.provenance_origin == ProvenanceOrigin.RESPONSE_FIELD
    assert source_class.source_semantics == "KRX_SOURCE_INDEX_CLASS"


def test_native_sector_canonical_key_is_family_plus_code():
    index = next(item for item in STORE_CONTRACTS if item.store_id == "IndexStore")
    endpoint = ENDPOINT_IDENTIFIER_CONTRACT["NATIVE_SECTOR_INDEX"]
    assert "family" in index.required_fields and "index_code" in index.required_fields
    assert "(family, index_code)" in index.ownership
    assert endpoint["canonical_identity"]["index_namespace"] == "NATIVE_SECTOR_INDEX"


def test_idx_clss_kospi_is_not_logical_family():
    family = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "IndexStore" and item.target_field == "family")
    assert family.source_field != "IDX_CLSS"
    assert family.source_semantics != "source_index_family"
    assert "KOSPI" not in {"MARKET_INDEX", "NATIVE_SECTOR_INDEX", "KRX_BRANDED_TAXONOMY"}


def test_target_classification_store_has_no_artifact_runtime_dependency():
    validator = _load_validator("krx_architecture_classification_target_dependency_validator")
    assert "InstrumentClassificationStore" in validator.TARGET_ARCHITECTURE_RUNTIME_ARTIFACT_COMPONENTS
    assert validator._target_runtime_artifact_dependency_count() == 0


def test_store_required_fields_have_store_qualified_provenance():
    keys = [(item.owner_store, item.target_field) for item in STORE_FIELD_PROVENANCE]
    assert len(keys) == len(set(keys))
    for store in STORE_CONTRACTS:
        assert all((store.store_id, field) in keys for field in store.required_fields)


def test_missing_store_required_field_is_detected():
    validator_path = Path(__file__).resolve().parents[1] / "scripts/validate_krx_production_data_architecture_v01.py"
    spec = importlib.util.spec_from_file_location("krx_architecture_validator", validator_path)
    assert spec and spec.loader
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    first = STORE_CONTRACTS[0]
    synthetic = replace(first, required_fields=first.required_fields + ("synthetic_missing",))
    counters = validator.store_field_coverage((synthetic,) + STORE_CONTRACTS[1:], STORE_FIELD_PROVENANCE)
    assert counters["store_required_field_missing_count"] == 1
    assert counters["store_required_field_covered_count"] == counters["store_required_field_count"] - 1


def test_daily_and_master_listed_shares_are_semantically_distinct():
    raw = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "KRXRawStockStore" and item.target_field == "listed_shares")
    master = next(item for item in STORE_FIELD_PROVENANCE if item.owner_store == "StockMasterStore" and item.target_field == "listed_shares")
    assert raw.source_field == master.source_field == "LIST_SHRS"
    assert raw.source_semantics == "RAW_DAILY_LISTED_SHARES"
    assert master.source_semantics == "MASTER_SNAPSHOT_LISTED_SHARES"
    assert raw.contract_id != master.contract_id


def test_operational_and_migration_status_are_separate():
    assert {item.value for item in OperationalStatus} == {layer.operational_status for layer in LAYER_REGISTRY} | {"NOT_IMPLEMENTED", "DEGRADED", "VALIDATION_ONLY"}
    assert {item.value for item in MigrationStatus} == {layer.migration_status for layer in LAYER_REGISTRY} | {"PLANNED"}
    raw = next(layer for layer in LAYER_REGISTRY if layer.layer_id == "STOCK_RAW_KRX")
    assert raw.operational_status in {OperationalStatus.INACTIVE.value, OperationalStatus.NOT_IMPLEMENTED.value}
    assert raw.migration_status == MigrationStatus.VALIDATED_NOT_PRODUCTION_MIGRATED.value


def test_migrated_and_not_applicable_layer_states_are_explicit():
    sector_rs = next(layer for layer in LAYER_REGISTRY if layer.layer_id == "SECTOR_RS")
    pattern_a = next(layer for layer in LAYER_REGISTRY if layer.layer_id == "PATTERN_A")
    assert sector_rs.operational_status == OperationalStatus.ACTIVE.value
    assert sector_rs.migration_status == MigrationStatus.MIGRATED.value
    assert pattern_a.operational_status == OperationalStatus.ACTIVE.value
    assert pattern_a.migration_status == MigrationStatus.NOT_APPLICABLE.value


def test_raw_krx_is_not_falsely_current_production_source():
    raw = next(layer for layer in LAYER_REGISTRY if layer.layer_id == "STOCK_RAW_KRX")
    assert raw.current_production_source == "LEGACY_COMPOSITE_STOCK_CACHE"
    assert raw.validated_source == "KRX Open API"
    assert raw.target_source == "KRXRawStockStore"


def test_stock_master_current_source_matches_existing_repo_authority():
    master = next(layer for layer in LAYER_REGISTRY if layer.layer_id == "STOCK_MASTER_KRX")
    assert "InstrumentMetadataResolver" in master.current_production_source
    assert "data/reference/krx_instrument_metadata.parquet" in master.current_production_source
    assert "KRX Open API Basic Info" in master.validated_source


def test_foreign_flow_engine_is_not_upstream_authority():
    assert FOREIGN_FLOW_LINEAGE["current_production_source"] == "KRX_PYKRX_FOREIGN_FLOW"
    assert "get_market_net_purchases_of_equities_by_ticker" in FOREIGN_FLOW_LINEAGE["source_endpoint"]
    assert FOREIGN_FLOW_LINEAGE["engine_module"] == "src/trend_scanner/flow/foreign_flow.py"
    assert FOREIGN_FLOW_LINEAGE["engine_is_upstream_authority"] is False
    assert "ForeignFlowDataProvider" in FOREIGN_FLOW_LINEAGE["producer"]


def test_production_behavior_diff_guard_uses_fixed_git_diff():
    validator_path = Path(__file__).resolve().parents[1] / "scripts/validate_krx_production_data_architecture_v01.py"
    spec = importlib.util.spec_from_file_location("krx_architecture_validator_diff", validator_path)
    assert spec and spec.loader
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    guard = validator._production_behavior_diff_guard(validator.FIX_START_HEAD, validator.ARCHITECTURE_FIX03_END_HEAD)
    assert guard["start_head"] == "bba23053b806b3775159acf89cb6a0b143937ebd"
    assert guard["production_behavior_change_count"] == 0
    assert guard["disallowed_paths"] == []


def test_legacy_cache_is_explicitly_classified_and_protected():
    assert LEGACY_CACHE_CLASSIFICATION["classification"] == "LEGACY_COMPOSITE_STOCK_CACHE"
    assert LEGACY_CACHE_CLASSIFICATION["raw_krx_store"] is False
    assert LEGACY_CACHE_CLASSIFICATION["rewritten_in_this_phase"] is False
    assert set(LEGACY_CACHE_CLASSIFICATION["write_protection"]) == {"rewrite", "move", "delete", "bulk rename"}


def test_repository_v2_semantics_are_explicit():
    daily = REPOSITORY_V2_CONTRACT["get_daily"]
    assert daily["price_semantics"] == "ADJUSTED"
    assert daily["volume_semantics"] == "RAW"
    assert daily["trading_value_semantics"] == "RAW"
    assert daily["join_key"] == ("ticker", "date")
    assert daily["join_type"] == "INNER_CONSISTENT_TRADING_SESSION_JOIN"
    assert daily["missing_side_behavior"] == "DATA_UNAVAILABLE"
    assert daily["forward_fill"] is False


def test_health_contract_covers_all_statuses_and_required_fields():
    assert set(OBSERVABILITY_CONTRACT.statuses) == {item.value for item in HealthStatus}
    required = {"layer_id", "status", "source_name", "last_success_at", "last_attempt_at", "message"}
    assert required.issubset(OBSERVABILITY_CONTRACT.snapshot_fields)
    assert {"usage_date_kst", "used", "limit", "remaining", "percentage", "endpoint_usage"}.issubset(OBSERVABILITY_CONTRACT.quota_fields)
    assert all(layer.layer_id and layer.migration_status for layer in LAYER_REGISTRY)


def test_dependency_graph_is_acyclic():
    assert not _has_cycle(DEPENDENCY_GRAPH["nodes"], DEPENDENCY_GRAPH["edges"])


def test_consumer_compatibility_matrix_is_complete():
    expected = {"Pattern A", "FastCore", "Julia", "Relative Strength", "Foreign Flow", "Stock Report", "Instrument Metadata / Applicability", "Resampler"}
    assert {item["consumer"] for item in CONSUMER_COMPATIBILITY} == expected
    assert all(item["required_columns"] and item["expected_behavior_change"] == "NONE" for item in CONSUMER_COMPATIBILITY)


def test_registered_store_and_layer_ids_are_unique():
    assert len({item.store_id for item in STORE_CONTRACTS}) == len(STORE_CONTRACTS)
    assert len({item.layer_id for item in LAYER_REGISTRY}) == len(LAYER_REGISTRY)


def test_contract_bundle_is_json_safe_and_network_free():
    bundle = contract_bundle()
    assert bundle["architecture_version"] == "KRX_PRODUCTION_DATA_ARCHITECTURE_V01_ERRATA01"
    assert bundle["endpoint_identifier_contract"]["BASIC_INFO"]["fields"]["ISU_CD"]["semantic"] == "standard_code"
    source = Path(__file__).resolve().parents[1] / "src/trend_scanner/data/source_contracts.py"
    source_text = source.read_text(encoding="utf-8")
    assert "from pykrx" not in source_text
    assert "OpenDART calls" not in source_text
    assert bundle["foreign_flow_lineage"]["engine_is_upstream_authority"] is False
    assert bundle["raw_schema_contract"]["basic_info_response_fields"]
    assert bundle["legacy_runtime_dependencies"]
