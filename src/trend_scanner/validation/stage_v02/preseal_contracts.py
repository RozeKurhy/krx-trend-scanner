"""PRESEAL Contracts, Gate Inventory, and Registry Structures for Stage v0.2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from trend_scanner.validation.stage_v02.allowlist import (
    CANDIDATE_RAW_FEATURE_ALLOWLIST,
    CANDIDATE_RULE_SPEC_VERSION,
    HASH_SERIALIZER_CONTRACT_VERSION,
    compute_canonical_sha256,
)

PRESEAL_CONTRACT_VERSION: str = "1.0.0"

# Complete PRESEAL Required Gate Inventory (60 Normative Gates)
CANDIDATE_FREEZE_PRESEAL_REQUIRED_GATE_INVENTORY_V02: tuple[str, ...] = (
    "PRODUCTION_ISOLATION_STAGE_IMPORT_COUNT",
    "PRODUCTION_ISOLATION_SCANNER_IMPORT_COUNT",
    "PRODUCTION_ISOLATION_OFFICIAL_STAGE_MUTATION_COUNT",
    "PRODUCTION_ISOLATION_SCORE_DERIVED_INPUT_COUNT",
    "PRODUCTION_ISOLATION_ARTIFACT_OVERWRITE_COUNT",
    "PRODUCTION_ISOLATION_ARTIFACT_HASH_DRIFT_COUNT",
    "ALLOWLIST_MISSING_READ_COUNT",
    "ALLOWLIST_POSITIVE_SIGNAL_FROM_MISSING_COUNT",
    "CANDIDATE_NEW_NODATA_COUNT",
    "OFFICIAL_COMPARATOR_CONTRACT_VIOLATION_COUNT",
    "COMPARATOR_CALIBRATION_PARITY",
    "COMPARATOR_OOS_PARITY",
    "COMPARATOR_TOTAL_PARITY",
    "AGGREGATE_COMPARATOR_PARITY",
    "BENCHMARK_EXACT_REGRESSION_COUNT",
    "BENCHMARK_ADJACENT_TO_SEVERE_COUNT",
    "CALIBRATION_EXACT_COUNT",
    "CALIBRATION_SEVERE_COUNT",
    "OOS_EXACT_COUNT",
    "OOS_SEVERE_COUNT",
    "HUMAN42_TRANSITION_MATCH_PRESERVED",
    "HUMAN42_EARLY_MATCH_PRESERVED",
    "HUMAN42_RECYCLED_TRANSITION_REMOVAL",
    "HUMAN42_PREMATURE_TRANSITION_REMOVAL",
    "HUMAN42_PREMATURE_FALSE_PROMOTION",
    "HUMAN42_026910_FULL_CLAUSE_TRACE_PRESENT",
    "HUMAN42_026910_HUMAN_COMPATIBILITY_CONCLUSION_PRESENT",
    "HUMAN42_026910_TRANSITION_REMOVAL_EXPECTED",
    "CANONICAL_SCHEDULE_DETERMINISM",
    "HISTORICAL_FEATURE_TIMELINE_PARITY_FAIL_COUNT",
    "HISTORICAL_FEATURE_TIMELINE_PARITY_COVERAGE_MATCH",
    "SAME_EVENT_KEY_STATE_BEFORE_MISMATCH_COUNT",
    "SAME_EVENT_KEY_TERMINATION_MISMATCH_COUNT",
    "SAME_EVENT_KEY_STATE_AFTER_MISMATCH_COUNT",
    "SAME_EVENT_KEY_CANDIDATE_STAGE_MISMATCH_COUNT",
    "SAME_EVENT_KEY_REASON_CODE_MISMATCH_COUNT",
    "REQUEST_TEMPORAL_PROVENANCE_MISMATCH_COUNT",
    "LIFECYCLE_CROSS_TICKER_EVENT_REUSE_COUNT",
    "LIFECYCLE_OFF_BY_ONE_ERROR_COUNT",
    "PROGRESSION_SEMANTIC_REVISION_REQUIRED_COUNT",
    "UNRESOLVED_CANDIDATE_SEMANTIC_CONFLICT_COUNT",
    "LIFECYCLE_SEMANTIC_REVISION_REQUIRED_COUNT",
    "SAME_EPISODE_PROGRESSION_UNRESOLVED_COUNT",
    "UNRESOLVED_STRICT_ANCHOR_SEMANTIC_MISMATCH_COUNT",
    "UNRESOLVED_PROGRESSED_ANCHOR_GAP_COUNT",
    "PROGRESSED_WITH_INACTIVE_LIFECYCLE_STATE_COUNT",
    "MATURE_POST_BREAKOUT_DECISION_STATUS",
    "MATURE_POST_BREAKOUT_BENCHMARK_REGRESSION_COUNT",
    "PHASE8_POSTHOC_KNOWN_LIMITATION_COUNT",
    "PHASE8_UNEXPLAINED_STAGE_CHANGE_COUNT",
    "PHASE8_TRANSITION_MATRIX_ARITHMETIC_CONSISTENCY",
    "PRESEAL_CONTRACT_ARTIFACT_CREATION_INTEGRITY",
    "PRESEAL_EVIDENCE_ARTIFACT_CREATION_INTEGRITY",
    "OBSERVED_METRIC_REGISTRY_PROVENANCE_INTEGRITY",
    "CREATION_INTEGRITY_METRIC_SELF_DEPENDENCY_FREE",
    "FINAL_OBSERVED_METRIC_REGISTRY_COMPLETE",
    "REGISTRY_HASH_SELF_REFERENCE_FREE",
    "REQUIRED_REGRESSION_BLOCKING_FAILURE_COUNT",
    "FULL_REPOSITORY_EXISTING_FAILURE_COUNT",
    "FULL_REPOSITORY_TEST_EXIT_CODE",
)


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass(frozen=True)
class GateEvaluationResult:
    gate_id: str
    status: GateStatus
    observed_value: Any
    target_criteria: str
    evidence_source: str
    details: str = ""


@dataclass(frozen=True)
class PreSealGateContractPayload:
    contract_version: str
    required_gate_ids: tuple[str, ...]
    candidate_spec_version: str
    serializer_contract_version: str
    feature_allowlist: tuple[str, ...]


@dataclass(frozen=True)
class PreSealGateContract:
    payload: PreSealGateContractPayload
    contract_hash: str


@dataclass(frozen=True)
class ValidationInputIdentityManifestPayload:
    calibration46_count: int
    oos35_count: int
    human42_count: int
    phase8_candidate_count: int
    calibration46_sha256: str
    oos35_sha256: str
    human42_sha256: str
    phase8_candidates_sha256: str


@dataclass(frozen=True)
class ValidationInputIdentityManifest:
    payload: ValidationInputIdentityManifestPayload
    input_identity_hash: str


@dataclass(frozen=True)
class ArtifactRegistryRecord:
    artifact_id: str
    relative_path: str
    artifact_type: str
    schema_version: str
    content_hash: str
    file_sha256: str


@dataclass(frozen=True)
class MetricRegistryRecord:
    metric_id: str
    source_artifact_id: str
    extractor_identity: str
    metric_value: Any
    record_hash: str


@dataclass(frozen=True)
class PreSealGateMatrixPayload:
    contract_hash: str
    input_identity_hash: str
    gate_count: int
    passed_gate_count: int
    failed_gate_count: int
    not_executed_gate_count: int
    overall_status: GateStatus
    gate_results: list[GateEvaluationResult]


@dataclass(frozen=True)
class PreSealGateMatrix:
    payload: PreSealGateMatrixPayload
    matrix_hash: str


@dataclass(frozen=True)
class PreSealEvidenceManifestPayload:
    candidate_rule_hash: str
    validation_contract_hash: str
    validation_input_identity_hash: str
    contract_registry_hash: str
    evidence_registry_hash: str
    metric_registry_hash: str
    gate_matrix_hash: str
    required_coverage_status: str
    overall_status: GateStatus


@dataclass(frozen=True)
class PreSealEvidenceManifest:
    payload: PreSealEvidenceManifestPayload
    manifest_hash: str


def build_preseal_gate_contract() -> PreSealGateContract:
    payload = PreSealGateContractPayload(
        contract_version=PRESEAL_CONTRACT_VERSION,
        required_gate_ids=CANDIDATE_FREEZE_PRESEAL_REQUIRED_GATE_INVENTORY_V02,
        candidate_spec_version=CANDIDATE_RULE_SPEC_VERSION,
        serializer_contract_version=HASH_SERIALIZER_CONTRACT_VERSION,
        feature_allowlist=CANDIDATE_RAW_FEATURE_ALLOWLIST,
    )
    contract_hash = compute_canonical_sha256(payload)
    return PreSealGateContract(payload=payload, contract_hash=contract_hash)
