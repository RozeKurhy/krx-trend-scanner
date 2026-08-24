"""Offline contract tests for KRX Production Data Architecture v01."""

from __future__ import annotations

from pathlib import Path

from trend_scanner.data.source_contracts import (
    AUTHORITY_FIELDS,
    CONSUMER_COMPATIBILITY,
    DEPENDENCY_GRAPH,
    ENDPOINT_IDENTIFIER_CONTRACT,
    HealthStatus,
    LAYER_REGISTRY,
    LEGACY_CACHE_CLASSIFICATION,
    OBSERVABILITY_CONTRACT,
    REPOSITORY_V2_CONTRACT,
    STORE_CONTRACTS,
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
    assert len({item.field_name for item in authoritative}) == len(authoritative)
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
    sect = ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]["SECT_TP_NM"]
    assert daily["semantic"] == "ticker"
    assert basic_code["semantic"] == "standard_code"
    assert basic_ticker["semantic"] == "ticker"
    assert sect["target_field"] != "sector_code"
    assert sect["identifier_namespace"] == "NOT_SECTOR_MEMBERSHIP"


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
    assert bundle["architecture_version"] == "KRX_PRODUCTION_DATA_ARCHITECTURE_V01"
    assert bundle["endpoint_identifier_contract"]["BASIC_INFO"]["fields"]["ISU_CD"]["semantic"] == "standard_code"
    source = Path(__file__).resolve().parents[1] / "src/trend_scanner/data/source_contracts.py"
    source_text = source.read_text(encoding="utf-8")
    assert "from pykrx" not in source_text
    assert "OpenDART calls" not in source_text
    assert "artifacts/" not in source_text

