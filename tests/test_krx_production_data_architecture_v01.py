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
    LAYER_REGISTRY,
    LEGACY_CACHE_CLASSIFICATION,
    MigrationStatus,
    OperationalStatus,
    OBSERVABILITY_CONTRACT,
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


def test_basic_info_security_group_and_listing_section_are_distinct():
    master = next(item for item in STORE_CONTRACTS if item.store_id == "StockMasterStore")
    assert {"security_group", "listing_section"}.issubset(master.fields)
    assert {"security_group", "listing_section"}.issubset(master.required_fields)
    by_field = {(item.owner_store, item.target_field): item for item in STORE_FIELD_PROVENANCE}
    assert by_field[("StockMasterStore", "security_group")].source_field == "SECUGRP_NM"
    assert by_field[("StockMasterStore", "listing_section")].source_field == "SECT_TP_NM"
    assert by_field[("StockMasterStore", "security_group")].source_semantics != by_field[("StockMasterStore", "listing_section")].source_semantics


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
    head = validator._git("rev-parse", "HEAD")
    guard = validator._production_behavior_diff_guard(validator.FIX_START_HEAD, head)
    assert guard["start_head"] == "9b232a4422afe4383125d0dd1c36b691b83ad421"
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
    expected = {"Pattern A", "FastCore", "Julia", "Relative Strength", "Foreign Flow", "Stock Report", "Resampler"}
    assert {item["consumer"] for item in CONSUMER_COMPATIBILITY} == expected
    assert all(item["required_columns"] and item["expected_behavior_change"] == "NONE" for item in CONSUMER_COMPATIBILITY)


def test_registered_store_and_layer_ids_are_unique():
    assert len({item.store_id for item in STORE_CONTRACTS}) == len(STORE_CONTRACTS)
    assert len({item.layer_id for item in LAYER_REGISTRY}) == len(LAYER_REGISTRY)


def test_contract_bundle_is_json_safe_and_network_free():
    bundle = contract_bundle()
    assert bundle["architecture_version"] == "KRX_PRODUCTION_DATA_ARCHITECTURE_V01_FIX01"
    assert bundle["endpoint_identifier_contract"]["BASIC_INFO"]["fields"]["ISU_CD"]["semantic"] == "standard_code"
    source = Path(__file__).resolve().parents[1] / "src/trend_scanner/data/source_contracts.py"
    source_text = source.read_text(encoding="utf-8")
    assert "from pykrx" not in source_text
    assert "OpenDART calls" not in source_text
    assert bundle["foreign_flow_lineage"]["engine_is_upstream_authority"] is False
