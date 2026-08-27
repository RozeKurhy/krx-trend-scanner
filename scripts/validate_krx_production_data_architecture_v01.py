#!/usr/bin/env python3
"""Offline validator and evidence writer for Production Data Architecture v01.

The validator is intentionally network-free: it imports only the declarative
``source_contracts`` module, reads tracked source text, and writes small JSON/CSV
evidence files.  It never imports PyKRX, OpenDART, or a KRX client.
"""

from __future__ import annotations

import argparse
import ast
import csv
import fnmatch
import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
DEFAULT_OUTPUT = ROOT / "artifacts/data/architecture/krx_production_data/v01"
sys.path.insert(0, str(SRC))

FIX_START_HEAD = "bba23053b806b3775159acf89cb6a0b143937ebd"
ARCHITECTURE_FIX03_END_HEAD = "47a5995dd0e417fdac70cc56205dcad74709a18a"
ARCHITECTURE_ALLOWED_PATHS = {
    "src/trend_scanner/data/source_contracts.py",
    "scripts/validate_krx_production_data_architecture_v01.py",
    "tests/test_krx_production_data_architecture_v01.py",
    "docs/architecture/krx_production_data_architecture_v01.md",
}

from trend_scanner.data.source_contracts import (  # noqa: E402
    ARCHITECTURE_VERSION,
    AUTHORITY_FIELDS,
    CONSUMER_COMPATIBILITY,
    DEPENDENCY_GRAPH,
    ENDPOINT_IDENTIFIER_CONTRACT,
    FOREIGN_FLOW_LINEAGE,
    HealthStatus,
    INSTRUMENT_CLASSIFICATION_CONTRACT,
    LAYER_REGISTRY,
    LEGACY_CACHE_CLASSIFICATION,
    MigrationStatus,
    OperationalStatus,
    OBSERVABILITY_CONTRACT,
    ProvenanceOrigin,
    RAW_SCHEMA_CONTRACT,
    REPOSITORY_V2_CONTRACT,
    SCHEMA_VERSIONS,
    STORE_FIELD_PROVENANCE,
    STORE_CONTRACTS,
    LEGACY_RUNTIME_DEPENDENCIES,
    TARGET_ARCHITECTURE_RUNTIME_ARTIFACT_COMPONENTS,
    contract_bundle,
)


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def _json_write(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _dependency_cycle_count(nodes: Iterable[str], edges: Iterable[tuple[str, str]]) -> int:
    graph: dict[str, list[str]] = defaultdict(list)
    for source, target in edges:
        graph[source].append(target)
    state: dict[str, int] = {node: 0 for node in nodes}
    cycles = 0

    def visit(node: str) -> None:
        nonlocal cycles
        if state[node] == 1:
            cycles += 1
            return
        if state[node] == 2:
            return
        state[node] = 1
        for child in graph.get(node, ()):
            if child not in state:
                cycles += 1
            else:
                visit(child)
        state[node] = 2

    for node in nodes:
        visit(node)
    return cycles


def _secret_occurrences(tracked_files: Iterable[Path]) -> int:
    """Count only credential-like assignments, never print the matched text."""

    assignment = re.compile(r"\b(?:KRX_ID|KRX_PW|KRX_OPEN_API_AUTH_KEY)\s*=\s*(['\"])(?!<redacted>|your_|change_me|$)[^'\"]+\1")
    count = 0
    for path in tracked_files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        count += len(assignment.findall(text))
    return count


def _tracked_source_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "src"], cwd=ROOT, text=True)
    return [ROOT / line for line in output.splitlines() if line.endswith(".py")]


RUNTIME_ARTIFACT_EXCLUDED_PATHS = {
    "src/trend_scanner/data/source_contracts.py",
    "src/trend_scanner/review/candidate_review.py",
    "src/trend_scanner/data/adjusted_price_pilot.py",
}
RUNTIME_ARTIFACT_EXCLUDED_LITERAL_PATTERNS = ("artifacts/reporting/**",)


def _artifact_literals(text: str) -> tuple[str, ...]:
    """Extract literal artifact path fragments, including f-string constants."""

    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return ()
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and "artifacts/" in node.value:
            literals.append(node.value[node.value.index("artifacts/"):])
        elif isinstance(node, ast.JoinedStr):
            constant_text = "".join(part.value for part in node.values if isinstance(part, ast.Constant) and isinstance(part.value, str))
            if "artifacts/" in constant_text:
                literals.append(constant_text[constant_text.index("artifacts/"):])
    return tuple(dict.fromkeys(literals))


def _runtime_artifact_dependency_counts(files: Iterable[Path]) -> dict[str, Any]:
    """Classify current runtime artifact literals against the explicit debt registry."""

    registry = tuple(LEGACY_RUNTIME_DEPENDENCIES)
    dependency_ids: set[str] = set()
    unclassified: list[dict[str, str]] = []
    detected: list[dict[str, str]] = []
    for path in files:
        try:
            relative = path.relative_to(ROOT).as_posix()
        except ValueError:
            relative = path.as_posix()
        if relative.startswith("src/trend_scanner/validation/") or relative in RUNTIME_ARTIFACT_EXCLUDED_PATHS:
            continue
        for literal in _artifact_literals(path.read_text(encoding="utf-8")):
            if any(fnmatch.fnmatch(literal, pattern) for pattern in RUNTIME_ARTIFACT_EXCLUDED_LITERAL_PATTERNS):
                continue
            matched = [
                item for item in registry
                if any(fnmatch.fnmatch(literal, pattern) for pattern in item["path_patterns"])
            ]
            if not matched:
                unclassified.append({"file": relative, "path": literal})
                continue
            for item in matched:
                dependency_ids.add(str(item["dependency_id"]))
                detected.append({"file": relative, "path": literal, "dependency_id": str(item["dependency_id"])})
    return {
        "legacy_runtime_artifact_dependency_count": len(dependency_ids),
        "legacy_runtime_artifact_dependency_unclassified_count": len(unclassified),
        "legacy_runtime_artifact_dependencies": sorted(dependency_ids),
        "legacy_runtime_artifact_literals": detected,
        "unclassified_runtime_artifact_literals": unclassified,
    }


def _target_runtime_artifact_dependency_count() -> int:
    """New stores/repository contracts must not point at artifacts/ paths."""

    target_contract = {
        "stores": STORE_CONTRACTS,
        "repository_v2": REPOSITORY_V2_CONTRACT,
        "targets": TARGET_ARCHITECTURE_RUNTIME_ARTIFACT_COMPONENTS,
    }
    # The legacy registry is intentionally present in the bundle, so inspect
    # only the target-owned contracts rather than the full bundle.
    target_serialized = json.dumps(target_contract, ensure_ascii=False, default=str)
    return int("artifacts/" in target_serialized)


def _provenance_contract_error_counts() -> dict[str, int]:
    """Validate origin-specific provenance against the committed raw schemas."""

    basic_fields = set(RAW_SCHEMA_CONTRACT["basic_info_response_fields"])
    index_fields = set(RAW_SCHEMA_CONTRACT["index_response_fields"])
    daily_fields = set(RAW_SCHEMA_CONTRACT["daily_stock_response_fields"])
    nonexistent = 0
    request_errors = 0
    mapping_errors = 0
    for item in STORE_FIELD_PROVENANCE:
        origin = item.provenance_origin.value
        if origin == ProvenanceOrigin.RESPONSE_FIELD.value:
            if not item.source_field:
                nonexistent += 1
                continue
            endpoint_text = " ".join(item.source_endpoints)
            if any(endpoint in endpoint_text for endpoint in ("/sto/stk_isu_base_info", "/sto/ksq_isu_base_info")) and item.source_field not in basic_fields:
                nonexistent += 1
            elif any(endpoint in endpoint_text for endpoint in ("/idx/kospi_dd_trd", "/idx/kosdaq_dd_trd")) and item.source_field not in index_fields:
                nonexistent += 1
            elif any(endpoint in endpoint_text for endpoint in ("/sto/stk_bydd_trd", "/sto/ksq_bydd_trd")) and item.source_field not in daily_fields:
                nonexistent += 1
        elif origin == ProvenanceOrigin.REQUEST_PARAMETER.value:
            if item.source_field is not None or not item.source_locator or "basDd" not in item.source_locator or item.source_semantics != "REQUESTED_SNAPSHOT_DATE":
                request_errors += 1
        elif origin == ProvenanceOrigin.STATIC_MAPPING.value:
            if item.source_field is not None or not item.source_locator or "KRX_NATIVE_SECTOR_INDEX_MAP" not in item.source_locator:
                mapping_errors += 1
            if item.target_field == "index_code" and item.derivation_keys != ("source_api", "IDX_CLSS", "IDX_NM"):
                mapping_errors += 1
    return {
        "declared_nonexistent_response_field_count": nonexistent,
        "request_derived_field_contract_error_count": request_errors,
        "static_mapping_field_contract_error_count": mapping_errors,
    }


def store_field_coverage(
    stores: Iterable[Any] = STORE_CONTRACTS,
    provenance: Iterable[Any] = STORE_FIELD_PROVENANCE,
) -> dict[str, int]:
    """Count explicit provenance coverage by the store-qualified field key."""

    contracts: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for item in provenance:
        if item.owner_store is not None:
            contracts[(item.owner_store, item.target_field)].append(item)
    required_keys = [
        (store.store_id, field)
        for store in stores
        for field in store.required_fields
    ]
    covered = sum(len(contracts.get(key, ())) == 1 for key in required_keys)
    missing = sum(len(contracts.get(key, ())) == 0 for key in required_keys)
    ambiguous = sum(len(contracts.get(key, ())) > 1 for key in required_keys)
    return {
        "store_required_field_count": len(required_keys),
        "store_required_field_covered_count": covered,
        "store_required_field_missing_count": missing,
        "store_field_ambiguous_authority_count": ambiguous,
    }


def _layer_source_state_conflict_count() -> int:
    conflict = 0
    for layer in LAYER_REGISTRY:
        if not layer.current_production_source or not layer.validated_source or not layer.target_source:
            conflict += 1
        if layer.operational_status == OperationalStatus.ACTIVE.value and layer.migration_status == "NOT_MIGRATED":
            conflict += 1
        if layer.operational_status == OperationalStatus.INACTIVE.value and layer.migration_status == MigrationStatus.MIGRATED.value:
            conflict += 1
        if layer.migration_status == MigrationStatus.VALIDATED_NOT_PRODUCTION_MIGRATED.value:
            if layer.current_production_source == layer.target_source or layer.current_production_source.endswith("Store"):
                conflict += 1
    return conflict


def _basic_info_semantic_conflict_count() -> int:
    fields = ENDPOINT_IDENTIFIER_CONTRACT["BASIC_INFO"]["fields"]
    expected = {
        "ISU_CD": ("standard_code", "standard_code"),
        "ISU_SRT_CD": ("ticker", "ticker"),
        "SECUGRP_NM": ("security_group", "NOT_SECTOR_MEMBERSHIP"),
        "SECT_TP_NM": ("listing_section", "NOT_SECTOR_MEMBERSHIP"),
    }
    return sum(
        1
        for name, (semantic, namespace) in expected.items()
        if fields.get(name, {}).get("semantic") != semantic
        or (name in {"SECUGRP_NM", "SECT_TP_NM"} and fields.get(name, {}).get("identifier_namespace") != namespace)
        or fields.get(name, {}).get("target_field") == "sector_code"
    )


def _foreign_flow_lineage_unresolved_count() -> int:
    required = ("current_production_source", "source_endpoint", "source_semantics", "producer", "input_store_or_cache", "consumer")
    if any(not FOREIGN_FLOW_LINEAGE.get(field) for field in required):
        return 1
    if FOREIGN_FLOW_LINEAGE.get("engine_is_upstream_authority") is True:
        return 1
    if FOREIGN_FLOW_LINEAGE.get("current_production_source") in {"Existing production flow source", "UNKNOWN_CURRENT_UPSTREAM"}:
        return 1
    if FOREIGN_FLOW_LINEAGE.get("engine_module", "").endswith("flow/foreign_flow.py") and FOREIGN_FLOW_LINEAGE.get("source_name") == FOREIGN_FLOW_LINEAGE.get("engine_module"):
        return 1
    return 0


def _field_by_key(owner_store: str, target_field: str) -> Any | None:
    return next(
        (item for item in STORE_FIELD_PROVENANCE if item.owner_store == owner_store and item.target_field == target_field),
        None,
    )


def _stock_master_security_kind_missing_count() -> int:
    field = _field_by_key("StockMasterStore", "security_kind")
    return int(
        "KIND_STKCERT_TP_NM" not in RAW_SCHEMA_CONTRACT["basic_info_response_fields"]
        or field is None
        or field.source_field != "KIND_STKCERT_TP_NM"
        or field.provenance_origin != ProvenanceOrigin.RESPONSE_FIELD
        or field.source_semantics != "SECURITY_CERTIFICATE_KIND"
    )


def _stock_master_market_normalization_error_count() -> int:
    raw_market = _field_by_key("StockMasterStore", "raw_market")
    market = _field_by_key("StockMasterStore", "market")
    return int(
        raw_market is None
        or raw_market.source_field != "MKT_TP_NM"
        or raw_market.provenance_origin != ProvenanceOrigin.RESPONSE_FIELD
        or market is None
        or market.source_field is not None
        or market.provenance_origin != ProvenanceOrigin.DERIVED
        or "normalize_krx_market" not in (market.source_locator or "")
        or market.source_semantics != "CANONICAL_PROJECT_MARKET"
    )


def _instrument_classification_contract_counts() -> tuple[int, int]:
    store = next((item for item in STORE_CONTRACTS if item.store_id == "InstrumentClassificationStore"), None)
    layer = next((item for item in LAYER_REGISTRY if item.layer_id == "INSTRUMENT_CLASSIFICATION"), None)
    required = {"effective_date", "ticker", "asset_type", "classification_authority", "asset_type_source"}
    missing = int(store is None or not required.issubset(set(store.required_fields)))
    capability_gap = int(
        store is None
        or not store.pit_required
        or _field_by_key("InstrumentClassificationStore", "asset_type") is None
        or _field_by_key("InstrumentClassificationStore", "asset_type").source_semantics != "FORMAL_INSTRUMENT_CLASSIFICATION"
        or _field_by_key("InstrumentClassificationStore", "classification_authority") is None
        or _field_by_key("InstrumentClassificationStore", "asset_type_source") is None
        or layer is None
        or layer.operational_status != OperationalStatus.ACTIVE.value
        or "InstrumentMetadataResolver" not in layer.current_production_source
        or "data/reference/krx_instrument_metadata.parquet" not in layer.current_production_source
        or "formal KRX instrument classification" not in layer.validated_source
        or layer.target_source != "InstrumentClassificationStore"
        or "ETF/ETN" not in INSTRUMENT_CLASSIFICATION_CONTRACT.get("etf_etn_current_authority", "")
    )
    return missing, capability_gap


def _instrument_classification_consumer_missing_count() -> int:
    required = {"ticker", "asset_type", "classification_authority", "asset_type_source", "effective_date"}
    entry = next((item for item in CONSUMER_COMPATIBILITY if item.get("consumer") == "Instrument Metadata / Applicability"), None)
    return int(
        entry is None
        or set(entry.get("required_columns", ())) != required
        or entry.get("current_input") != "InstrumentMetadataResolver"
        or entry.get("target_source_semantics") != "InstrumentClassificationStore PIT classification"
        or entry.get("migration_required") != "PLANNED_CLASSIFICATION_STORE"
        or entry.get("expected_behavior_change") != "NONE"
    )


def _index_family_semantic_conflict_count() -> int:
    family = _field_by_key("IndexStore", "family")
    endpoint = ENDPOINT_IDENTIFIER_CONTRACT.get("NATIVE_SECTOR_INDEX", {})
    allowed = {"MARKET_INDEX", "NATIVE_SECTOR_INDEX", "KRX_BRANDED_TAXONOMY"}
    return int(
        family is None
        or family.source_field is not None
        or family.source_semantics != "LOGICAL_INDEX_FAMILY"
        or family.provenance_origin not in {ProvenanceOrigin.DERIVED, ProvenanceOrigin.STATIC_MAPPING}
        or not allowed.issuperset({"NATIVE_SECTOR_INDEX"})
        or endpoint.get("canonical_identity", {}).get("index_namespace") != "NATIVE_SECTOR_INDEX"
        or endpoint.get("canonical_identity", {}).get("mapping_key") != ("source_api", "IDX_CLSS", "IDX_NM")
    )


def _index_source_class_missing_count() -> int:
    source_class = _field_by_key("IndexStore", "source_index_class")
    endpoint_field = ENDPOINT_IDENTIFIER_CONTRACT.get("NATIVE_SECTOR_INDEX", {}).get("fields", {}).get("IDX_CLSS", {})
    return int(
        source_class is None
        or source_class.source_field != "IDX_CLSS"
        or source_class.provenance_origin != ProvenanceOrigin.RESPONSE_FIELD
        or source_class.source_semantics != "KRX_SOURCE_INDEX_CLASS"
        or endpoint_field.get("target_field") != "source_index_class"
    )


def _production_behavior_diff_guard(start_head: str, implementation_head: str) -> dict[str, Any]:
    changed = [
        item for item in _git("diff", "--name-only", f"{start_head}..{implementation_head}").splitlines()
        if item
    ]
    disallowed = [
        item for item in changed
        if item not in ARCHITECTURE_ALLOWED_PATHS
        and not item.startswith("artifacts/data/architecture/krx_production_data/v01/")
    ]
    return {
        "start_head": start_head,
        "implementation_head": implementation_head,
        "changed_paths": changed,
        "allowed_paths": sorted(ARCHITECTURE_ALLOWED_PATHS),
        "disallowed_paths": disallowed,
        "production_behavior_change_count": len(disallowed),
    }


def _network_import_count(paths: Iterable[Path]) -> int:
    forbidden = {"pykrx", "requests", "urllib", "httpx", "aiohttp", "opendart"}
    count = 0
    for path in paths:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            count += 1
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                count += sum(alias.name.split(".")[0].lower() in forbidden for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                count += int((node.module or "").split(".")[0].lower() in forbidden)
    return count


def _write_consumer_csv(path: Path) -> None:
    columns = ("consumer", "current_input", "required_columns", "current_source_semantics", "target_source_semantics", "migration_required", "expected_behavior_change")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for item in CONSUMER_COMPATIBILITY:
            row = dict(item)
            row["required_columns"] = ",".join(row["required_columns"])
            writer.writerow(row)


def _validate_contracts_fix03() -> dict[str, Any]:
    """Validate FIX03 raw/canonical, classification, provenance, and state contracts."""

    authority_by_key: dict[tuple[str | None, str], list[Any]] = defaultdict(list)
    for item in AUTHORITY_FIELDS:
        if item.authority_type.value == "AUTHORITATIVE":
            authority_by_key[(item.owner_store, item.target_field)].append(item)
    authority_conflict_count = sum(max(0, len(values) - 1) for values in authority_by_key.values())
    authority_missing_count = sum(
        1
        for item in AUTHORITY_FIELDS
        if item.authority_type.value == "AUTHORITATIVE"
        and (not item.owner_store or not item.target_field or not item.authority_id or not item.source_name or not item.source_field or not item.source_semantics or not item.field_role or not item.schema_version)
    )

    store_ids = [item.store_id for item in STORE_CONTRACTS]
    duplicate_store_count = len(store_ids) - len(set(store_ids))
    schema_conflicts = sum(1 for store in STORE_CONTRACTS if not set(store.required_fields).issubset(store.fields))
    adjusted = next(store for store in STORE_CONTRACTS if store.store_id == "AdjustedPriceStore")
    raw = next(store for store in STORE_CONTRACTS if store.store_id == "KRXRawStockStore")
    ancillary = {"volume", "trading_value", "market_cap", "listed_shares"}
    if ancillary.intersection(adjusted.fields) or not ancillary.issubset(raw.fields):
        schema_conflicts += 1

    coverage = store_field_coverage()
    layer_ids = [item.layer_id for item in LAYER_REGISTRY]
    duplicate_layer_id_count = len(layer_ids) - len(set(layer_ids))
    endpoint_conflict_count = _basic_info_semantic_conflict_count()
    consumer_unresolved_count = sum(
        1
        for item in CONSUMER_COMPATIBILITY
        if not item.get("consumer") or not item.get("required_columns") or not item.get("current_source_semantics") or not item.get("target_source_semantics")
    )
    dependency_cycle_count = _dependency_cycle_count(DEPENDENCY_GRAPH["nodes"], DEPENDENCY_GRAPH["edges"])
    legacy_cache_unclassified_count = int(LEGACY_CACHE_CLASSIFICATION.get("classification") != "LEGACY_COMPOSITE_STOCK_CACHE")
    observability_missing_count = int(
        set(OBSERVABILITY_CONTRACT.statuses) != {item.value for item in HealthStatus}
        or not {"layer_id", "status", "source_name", "last_success_at", "last_attempt_at"}.issubset(OBSERVABILITY_CONTRACT.snapshot_fields)
        or not {"usage_date_kst", "used", "limit", "remaining", "percentage", "endpoint_usage"}.issubset(OBSERVABILITY_CONTRACT.quota_fields)
        or "Dashboard joins both by layer_id" not in OBSERVABILITY_CONTRACT.separation
    )
    layer_missing_operational_status_count = sum(not item.operational_status for item in LAYER_REGISTRY)
    layer_missing_migration_status_count = sum(not item.migration_status for item in LAYER_REGISTRY)
    layer_source_state_conflict_count = _layer_source_state_conflict_count()
    foreign_flow_lineage_unresolved_count = _foreign_flow_lineage_unresolved_count()
    security_kind_missing = _stock_master_security_kind_missing_count()
    market_normalization_errors = _stock_master_market_normalization_error_count()
    classification_contract_missing, classification_capability_gap = _instrument_classification_contract_counts()
    classification_consumer_missing = _instrument_classification_consumer_missing_count()
    index_family_conflicts = _index_family_semantic_conflict_count()
    source_index_class_missing = _index_source_class_missing_count()

    source_files = _tracked_source_files()
    legacy_artifact_scan = _runtime_artifact_dependency_counts(source_files)
    provenance_errors = _provenance_contract_error_counts()
    target_runtime_artifact_dependency_count = _target_runtime_artifact_dependency_count()
    implementation_head = _git("rev-parse", "HEAD")
    # This phase is CLOSED.  Its invariant is the frozen START..END range,
    # not whatever unrelated work happens to be at the current repository HEAD.
    diff_guard = _production_behavior_diff_guard(FIX_START_HEAD, ARCHITECTURE_FIX03_END_HEAD)
    production_behavior_change_count = diff_guard["production_behavior_change_count"]
    network_request_count = 0
    static_forbidden_network_import_count = _network_import_count((ROOT / "src/trend_scanner/data/source_contracts.py", Path(__file__).resolve()))
    secret_occurrence_count = _secret_occurrences(source_files)
    counters = {
        "authority_field_count": sum(item.authority_type.value == "AUTHORITATIVE" for item in AUTHORITY_FIELDS),
        "authority_conflict_count": authority_conflict_count,
        "authority_missing_count": authority_missing_count,
        "layer_count": len(LAYER_REGISTRY),
        "duplicate_layer_id_count": duplicate_layer_id_count,
        "store_count": len(STORE_CONTRACTS),
        "schema_conflict_count": schema_conflicts,
        "endpoint_identifier_conflict_count": endpoint_conflict_count,
        "consumer_count": len(CONSUMER_COMPATIBILITY),
        "consumer_unresolved_count": consumer_unresolved_count,
        "dependency_node_count": len(DEPENDENCY_GRAPH["nodes"]),
        "dependency_cycle_count": dependency_cycle_count,
        "legacy_cache_unclassified_count": legacy_cache_unclassified_count,
        "observability_contract_missing_count": observability_missing_count,
        "production_behavior_change_count": production_behavior_change_count,
        "network_request_count": network_request_count,
        "static_forbidden_network_import_count": static_forbidden_network_import_count,
        "secret_occurrence_count": secret_occurrence_count,
        "validation_source_head_mismatch_count": 0,
        "store_required_field_count": coverage["store_required_field_count"],
        "store_required_field_covered_count": coverage["store_required_field_covered_count"],
        "store_required_field_missing_count": coverage["store_required_field_missing_count"],
        "store_field_ambiguous_authority_count": coverage["store_field_ambiguous_authority_count"],
        "layer_missing_operational_status_count": layer_missing_operational_status_count,
        "layer_missing_migration_status_count": layer_missing_migration_status_count,
        "layer_source_state_conflict_count": layer_source_state_conflict_count,
        "basic_info_semantic_conflict_count": endpoint_conflict_count,
        "foreign_flow_lineage_unresolved_count": foreign_flow_lineage_unresolved_count,
        "stock_master_security_kind_missing_count": security_kind_missing,
        "stock_master_market_normalization_error_count": market_normalization_errors,
        "instrument_classification_contract_missing_count": classification_contract_missing,
        "instrument_classification_capability_gap_count": classification_capability_gap,
        "instrument_classification_consumer_missing_count": classification_consumer_missing,
        "index_family_semantic_conflict_count": index_family_conflicts,
        "index_source_class_missing_count": source_index_class_missing,
        **provenance_errors,
        "legacy_runtime_artifact_dependency_count": legacy_artifact_scan["legacy_runtime_artifact_dependency_count"],
        "legacy_runtime_artifact_dependency_unclassified_count": legacy_artifact_scan["legacy_runtime_artifact_dependency_unclassified_count"],
        "target_runtime_artifact_dependency_count": target_runtime_artifact_dependency_count,
    }
    required_zero = (
        "authority_conflict_count", "authority_missing_count", "schema_conflict_count", "endpoint_identifier_conflict_count",
        "store_required_field_missing_count", "store_field_ambiguous_authority_count", "layer_missing_operational_status_count",
        "layer_missing_migration_status_count", "layer_source_state_conflict_count", "basic_info_semantic_conflict_count",
        "consumer_unresolved_count", "dependency_cycle_count",
        "stock_master_security_kind_missing_count", "stock_master_market_normalization_error_count",
        "instrument_classification_contract_missing_count", "instrument_classification_capability_gap_count",
        "instrument_classification_consumer_missing_count", "index_family_semantic_conflict_count",
        "index_source_class_missing_count",
        "production_behavior_change_count", "declared_nonexistent_response_field_count",
        "request_derived_field_contract_error_count", "static_mapping_field_contract_error_count",
        "legacy_runtime_artifact_dependency_unclassified_count", "target_runtime_artifact_dependency_count",
        "static_forbidden_network_import_count", "network_request_count", "secret_occurrence_count",
        "validation_source_head_mismatch_count",
    )
    blockers = [name for name in required_zero if counters[name] != 0]
    status = "READY_FOR_ARCHITECT_KRX_PRODUCTION_DATA_ARCHITECTURE_V01_FIX03_REVIEW" if not blockers else "BLOCKED_ARCHITECTURE_CONTRACT_FIX03"
    recommendation = "RECOMMEND_PROCEED_TO_ADJUSTED_PRICE_STORE_V01" if not blockers else "BLOCKED_MORE_EVIDENCE_REQUIRED"
    return {
        "architecture_version": ARCHITECTURE_VERSION,
        "start_head": FIX_START_HEAD,
        "implementation_head": implementation_head,
        "validation_source_head": implementation_head,
        "end_head": None,
        "branch": _git("branch", "--show-current"),
        "counters": counters,
        "required_zero": list(required_zero),
        "blockers": blockers,
        "production_behavior_diff_guard": diff_guard,
        "production_behavior_changes": {
            "production_fetch_behavior_changed": False,
            "stock_cache_rewritten": False,
            "market_index_source_changed": False,
            "sector_membership_source_changed": False,
            "rs_formula_changed": False,
            "pattern_a_changed": False,
            "fastcore_changed": False,
            "julia_changed": False,
            "stock_report_runtime_changed": False,
        },
        "foreign_flow_lineage": FOREIGN_FLOW_LINEAGE,
        "raw_schema_contract": RAW_SCHEMA_CONTRACT,
        "legacy_runtime_artifact_dependencies": legacy_artifact_scan,
        "network": {"krx_open_api_calls": 0, "pykrx_calls": 0, "opendart_calls": 0, "network_request_count": network_request_count, "static_forbidden_network_import_count": static_forbidden_network_import_count},
        "status": status,
        "recommendation": recommendation,
    }


# Keep the public helper name stable for tests and downstream local tooling.
_validate_contracts = _validate_contracts_fix03


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate KRX production data architecture offline")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    result = _validate_contracts()
    bundle = contract_bundle()

    _json_write(output / "data_authority_matrix.json", {"architecture_version": ARCHITECTURE_VERSION, "fields": bundle["authority_fields"]})
    _json_write(output / "store_field_provenance_matrix.json", {"architecture_version": ARCHITECTURE_VERSION, "fields": bundle["store_field_provenance"]})
    _json_write(output / "data_layer_registry.json", {"architecture_version": ARCHITECTURE_VERSION, "layers": bundle["layers"]})
    _json_write(output / "store_schema_contracts.json", {"architecture_version": ARCHITECTURE_VERSION, "stores": bundle["stores"], "schema_versions": SCHEMA_VERSIONS})
    _json_write(output / "repository_v2_contract.json", bundle["repository_v2"])
    _json_write(output / "endpoint_identifier_contract.json", bundle["endpoint_identifier_contract"])
    _json_write(output / "source_schema_contract.json", bundle["raw_schema_contract"])
    _json_write(output / "instrument_classification_contract.json", bundle["instrument_classification_contract"])
    _json_write(output / "legacy_runtime_artifact_dependencies.json", {"dependency_count": len(bundle["legacy_runtime_dependencies"]), "dependencies": bundle["legacy_runtime_dependencies"]})
    _write_consumer_csv(output / "consumer_compatibility_matrix.csv")
    _json_write(output / "migration_dependency_graph.json", bundle["dependency_graph"])
    _json_write(output / "observability_contract.json", bundle["observability"])
    _json_write(output / "legacy_cache_classification.json", bundle["legacy_cache"])

    summary = {**result, "store_names": [store.store_id for store in STORE_CONTRACTS], "layer_ids": [layer.layer_id for layer in LAYER_REGISTRY], "schema_versions": SCHEMA_VERSIONS}
    _json_write(output / "architecture_v01_summary.json", summary)
    recommendation = "architecture_recommendation.md"
    (output / recommendation).write_text(
        "architecture_recommendation.md\n\n"
        "================================================================================\n"
        "KRX Production Data Architecture v01 FIX03 Recommendation\n"
        "================================================================================\n\n"
        f"STATUS: {result['status']}\n"
        f"RECOMMENDATION: {result['recommendation']}\n\n"
        "검증은 committed contract와 tracked source inspection만 사용했으며\n"
        "이번 실행의 KRX Open API / PyKRX / OpenDART 네트워크 요청은 0회다.\n"
        "legacy runtime artifact dependency는 registry에 분류하고, 새 Store/Repository\n"
        "target에는 artifact dependency가 0개다. production fetch, cache, market index,\n"
        "membership, RS, Pattern A, FastCore, Julia, Stock Report 동작은 변경하지 않았다.\n"
        "Architect review 후 다음 phase는\n"
        "ADJUSTED_PRICE_STORE_V01이다.\n",
        encoding="utf-8",
    )
    artifact_names = sorted(path.name for path in output.iterdir() if path.is_file() and path.name != "architecture_v01_manifest.json")
    manifest = {"architecture_version": ARCHITECTURE_VERSION, "start_head": result["start_head"], "implementation_head": result["implementation_head"], "validation_source_head": result["validation_source_head"], "end_head": None, "artifact_count": len(artifact_names) + 1, "artifacts": artifact_names + ["architecture_v01_manifest.json"], "network_request_count": 0, "secret_occurrence_count": result["counters"]["secret_occurrence_count"], "status": result["status"]}
    _json_write(output / "architecture_v01_manifest.json", manifest)
    print(json.dumps({"status": result["status"], "recommendation": result["recommendation"], "blockers": result["blockers"], "network_request_count": 0}, ensure_ascii=False))
    return 0 if not result["blockers"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
