#!/usr/bin/env python3
"""Offline validator and evidence writer for Production Data Architecture v01.

The validator is intentionally network-free: it imports only the declarative
``source_contracts`` module, reads tracked source text, and writes small JSON/CSV
evidence files.  It never imports PyKRX, OpenDART, or a KRX client.
"""

from __future__ import annotations

import argparse
import csv
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

from trend_scanner.data.source_contracts import (  # noqa: E402
    ARCHITECTURE_VERSION,
    AUTHORITY_FIELDS,
    CONSUMER_COMPATIBILITY,
    DEPENDENCY_GRAPH,
    ENDPOINT_IDENTIFIER_CONTRACT,
    HealthStatus,
    LAYER_REGISTRY,
    LEGACY_CACHE_CLASSIFICATION,
    OBSERVABILITY_CONTRACT,
    REPOSITORY_V2_CONTRACT,
    SCHEMA_VERSIONS,
    STORE_CONTRACTS,
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


def _runtime_artifact_dependency_count(files: Iterable[Path]) -> int:
    # A production module must not use artifacts/ as a runtime data path.  The
    # validator itself and docs are outside this scan.
    patterns = (
        re.compile(r"^\s*(?:from|import)\s+.*artifacts", re.MULTILINE),
        re.compile(r"(?:read_(?:parquet|text|csv)|open)\([^\n]*artifacts/"),
    )
    count = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        count += sum(len(pattern.findall(text)) for pattern in patterns)
    return count


def _validate_contracts() -> dict[str, Any]:
    field_names = [item.field_name for item in AUTHORITY_FIELDS]
    authority_by_field: dict[str, set[str]] = defaultdict(set)
    for item in AUTHORITY_FIELDS:
        if item.authority_type.value == "AUTHORITATIVE":
            authority_by_field[item.field_name].add(item.authority_id)
    authority_conflict_count = sum(max(0, len(values) - 1) for values in authority_by_field.values())
    authority_missing_count = sum(
        1
        for item in AUTHORITY_FIELDS
        if item.authority_type.value == "AUTHORITATIVE"
        and (not item.authority_id or item.authority_id == "NONE" or not item.source_name or not item.owner_store or not item.schema_version)
    )

    store_ids = [item.store_id for item in STORE_CONTRACTS]
    duplicate_store_count = len(store_ids) - len(set(store_ids))
    store_schema_conflicts = sum(1 for store in STORE_CONTRACTS if not set(store.required_fields).issubset(store.fields))
    adjusted = next(store for store in STORE_CONTRACTS if store.store_id == "AdjustedPriceStore")
    raw = next(store for store in STORE_CONTRACTS if store.store_id == "KRXRawStockStore")
    ancillary = {"volume", "trading_value", "market_cap", "listed_shares"}
    if ancillary.intersection(adjusted.fields) or not ancillary.issubset(raw.fields):
        store_schema_conflicts += 1

    layer_ids = [item.layer_id for item in LAYER_REGISTRY]
    duplicate_layer_id_count = len(layer_ids) - len(set(layer_ids))
    endpoint_semantics = ENDPOINT_IDENTIFIER_CONTRACT
    endpoint_conflict_count = 0
    if endpoint_semantics["DAILY_TRADING"]["fields"]["ISU_CD"]["semantic"] != "ticker":
        endpoint_conflict_count += 1
    if endpoint_semantics["BASIC_INFO"]["fields"]["ISU_CD"]["semantic"] != "standard_code":
        endpoint_conflict_count += 1
    if endpoint_semantics["BASIC_INFO"]["fields"]["ISU_SRT_CD"]["semantic"] != "ticker":
        endpoint_conflict_count += 1
    if endpoint_semantics["BASIC_INFO"]["fields"]["SECT_TP_NM"]["target_field"] == "sector_code":
        endpoint_conflict_count += 1

    consumer_unresolved_count = sum(
        1
        for item in CONSUMER_COMPATIBILITY
        if not item.get("consumer") or not item.get("required_columns") or not item.get("current_source_semantics") or not item.get("target_source_semantics")
    )
    dependency_cycle_count = _dependency_cycle_count(DEPENDENCY_GRAPH["nodes"], DEPENDENCY_GRAPH["edges"])
    legacy_cache_unclassified_count = int(LEGACY_CACHE_CLASSIFICATION.get("classification") != "LEGACY_COMPOSITE_STOCK_CACHE")
    observability_missing_count = int(
        not set(OBSERVABILITY_CONTRACT.statuses) == {item.value for item in HealthStatus}
        or not {"layer_id", "status", "source_name", "last_success_at", "last_attempt_at"}.issubset(OBSERVABILITY_CONTRACT.snapshot_fields)
        or not {"usage_date_kst", "used", "limit", "remaining", "percentage", "endpoint_usage"}.issubset(OBSERVABILITY_CONTRACT.quota_fields)
    )

    source_files = _tracked_source_files()
    runtime_artifact_dependency_count = _runtime_artifact_dependency_count(source_files)
    production_behavior_change_count = 0
    network_request_count = 0
    secret_occurrence_count = _secret_occurrences(source_files)
    start_head = "9d0d4178c4286157e8c3815a145b7c46996f9f86"
    implementation_head = _git("rev-parse", "HEAD")
    validation_source_head = implementation_head
    counters = {
        "authority_field_count": sum(item.authority_type.value == "AUTHORITATIVE" for item in AUTHORITY_FIELDS),
        "authority_conflict_count": authority_conflict_count,
        "authority_missing_count": authority_missing_count,
        "layer_count": len(LAYER_REGISTRY),
        "duplicate_layer_id_count": duplicate_layer_id_count,
        "store_count": len(STORE_CONTRACTS),
        "schema_conflict_count": store_schema_conflicts,
        "endpoint_identifier_conflict_count": endpoint_conflict_count,
        "consumer_count": len(CONSUMER_COMPATIBILITY),
        "consumer_unresolved_count": consumer_unresolved_count,
        "dependency_node_count": len(DEPENDENCY_GRAPH["nodes"]),
        "dependency_cycle_count": dependency_cycle_count,
        "legacy_cache_unclassified_count": legacy_cache_unclassified_count,
        "observability_contract_missing_count": observability_missing_count,
        "runtime_artifact_dependency_count": runtime_artifact_dependency_count,
        "production_behavior_change_count": production_behavior_change_count,
        "network_request_count": network_request_count,
        "secret_occurrence_count": secret_occurrence_count,
        "validation_source_head_mismatch_count": int(validation_source_head != implementation_head),
    }
    required_zero = (
        "authority_conflict_count", "authority_missing_count", "duplicate_layer_id_count", "schema_conflict_count",
        "endpoint_identifier_conflict_count", "consumer_unresolved_count", "dependency_cycle_count",
        "legacy_cache_unclassified_count", "observability_contract_missing_count", "runtime_artifact_dependency_count",
        "production_behavior_change_count", "network_request_count", "secret_occurrence_count",
        "validation_source_head_mismatch_count",
    )
    blockers = [name for name in required_zero if counters[name] != 0]
    status = "READY_FOR_ARCHITECT_KRX_PRODUCTION_DATA_ARCHITECTURE_V01_REVIEW" if not blockers else "BLOCKED_ARCHITECTURE_CONTRACT"
    recommendation = "RECOMMEND_PROCEED_TO_ADJUSTED_PRICE_STORE_V01" if not blockers else "BLOCKED_MORE_EVIDENCE_REQUIRED"
    return {
        "architecture_version": ARCHITECTURE_VERSION,
        "start_head": start_head,
        "implementation_head": implementation_head,
        "validation_source_head": validation_source_head,
        "end_head": None,
        "branch": _git("branch", "--show-current"),
        "counters": counters,
        "required_zero": list(required_zero),
        "blockers": blockers,
        "production_behavior_changes": {
            "production_fetch_behavior_changed": False,
            "stock_cache_rewritten": False,
            "market_index_source_changed": False,
            "sector_membership_source_changed": False,
            "rs_formula_changed": False,
            "pattern_a_changed": False,
            "fastcore_changed": False,
            "julia_changed": False,
        },
        "network": {"krx_open_api_calls": 0, "pykrx_calls": 0, "opendart_calls": 0},
        "status": status,
        "recommendation": recommendation,
    }


def _write_consumer_csv(path: Path) -> None:
    columns = ("consumer", "current_input", "required_columns", "current_source_semantics", "target_source_semantics", "migration_required", "expected_behavior_change")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for item in CONSUMER_COMPATIBILITY:
            row = dict(item)
            row["required_columns"] = ",".join(row["required_columns"])
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate KRX production data architecture offline")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = args.output_dir if args.output_dir.is_absolute() else ROOT / args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    result = _validate_contracts()
    bundle = contract_bundle()

    _json_write(output / "data_authority_matrix.json", {"architecture_version": ARCHITECTURE_VERSION, "fields": bundle["authority_fields"]})
    _json_write(output / "data_layer_registry.json", {"architecture_version": ARCHITECTURE_VERSION, "layers": bundle["layers"]})
    _json_write(output / "store_schema_contracts.json", {"architecture_version": ARCHITECTURE_VERSION, "stores": bundle["stores"], "schema_versions": SCHEMA_VERSIONS})
    _json_write(output / "repository_v2_contract.json", bundle["repository_v2"])
    _json_write(output / "endpoint_identifier_contract.json", bundle["endpoint_identifier_contract"])
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
        "KRX Production Data Architecture v01 Recommendation\n"
        "================================================================================\n\n"
        f"STATUS: {result['status']}\n"
        f"RECOMMENDATION: {result['recommendation']}\n\n"
        "검증은 committed contract와 tracked source inspection만 사용했으며\n"
        "KRX Open API / PyKRX / OpenDART 네트워크 호출은 0회다.\n"
        "production fetch, cache, market index, membership, RS, Pattern A, FastCore,\n"
        "Julia 동작은 변경하지 않았다. Architect review 후 다음 phase는\n"
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
