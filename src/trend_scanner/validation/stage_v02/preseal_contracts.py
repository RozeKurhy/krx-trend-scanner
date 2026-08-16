"""PRESEAL Contracts, Gate Records, and Semantic Enforcement for Stage v0.2."""

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

PRESEAL_CONTRACT_VERSION: str = "2.2.0"


class GateStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EXECUTED = "NOT_EXECUTED"


@dataclass(frozen=True)
class GateContractRecord:
    """Semantic record defining a normative gate requirement in frozen contract."""

    gate_id: str
    metric_id: str
    normative_predicate_definition: str
    normative_predicate_hash: str
    evidence_schema: str
    status_semantics: str


@dataclass(frozen=True)
class GateEvaluationResult:
    """Evaluated result of a normative gate comparing contract and observed metric."""

    gate_id: str
    status: GateStatus
    observed_value: Any
    target_criteria: str
    evidence_source: str
    details: str = ""


@dataclass(frozen=True)
class PreSealGateContractPayload:
    contract_version: str
    candidate_spec_version: str
    serializer_contract_version: str
    feature_allowlist: tuple[str, ...]
    required_gate_records: tuple[GateContractRecord, ...]


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


# 60 Gate Definitions with Normative Predicate Specs
_GATE_DEFINITIONS: list[tuple[str, str, str, str, str]] = [
    ("PRODUCTION_ISOLATION_STAGE_IMPORT_COUNT", "production_stage_candidate_import_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PRODUCTION_ISOLATION_SCANNER_IMPORT_COUNT", "scanner_candidate_import_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PRODUCTION_ISOLATION_OFFICIAL_STAGE_MUTATION_COUNT", "official_stage_mutation_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PRODUCTION_ISOLATION_SCORE_DERIVED_INPUT_COUNT", "score_derived_input_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PRODUCTION_ISOLATION_ARTIFACT_OVERWRITE_COUNT", "production_artifact_overwrite_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PRODUCTION_ISOLATION_ARTIFACT_HASH_DRIFT_COUNT", "official_artifact_hash_drift_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("ALLOWLIST_MISSING_READ_COUNT", "allowlist_missing_read_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("ALLOWLIST_POSITIVE_SIGNAL_FROM_MISSING_COUNT", "positive_signal_from_missing_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("CANDIDATE_NEW_NODATA_COUNT", "candidate_new_nodata_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("OFFICIAL_COMPARATOR_CONTRACT_VIOLATION_COUNT", "official_comparator_contract_violation_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("COMPARATOR_CALIBRATION_PARITY", "comparator_calibration_parity_count", "value == 46", "int", "PASS if 46 else FAIL"),
    ("COMPARATOR_OOS_PARITY", "comparator_oos_parity_count", "value == 35", "int", "PASS if 35 else FAIL"),
    ("COMPARATOR_TOTAL_PARITY", "comparator_total_parity_count", "value == 81", "int", "PASS if 81 else FAIL"),
    ("AGGREGATE_COMPARATOR_PARITY", "aggregate_comparator_parity_status", "value == 'PASS'", "str", "PASS if 'PASS' else FAIL"),
    ("BENCHMARK_EXACT_REGRESSION_COUNT", "benchmark_exact_regression_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("BENCHMARK_ADJACENT_TO_SEVERE_COUNT", "benchmark_adjacent_to_severe_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("CALIBRATION_EXACT_COUNT", "calibration_exact_count", "value >= 38", "int", "PASS if >= 38 else FAIL"),
    ("CALIBRATION_SEVERE_COUNT", "calibration_severe_count", "value <= 3", "int", "PASS if <= 3 else FAIL"),
    ("OOS_EXACT_COUNT", "oos_exact_count", "value >= 24", "int", "PASS if >= 24 else FAIL"),
    ("OOS_SEVERE_COUNT", "oos_severe_count", "value <= 1", "int", "PASS if <= 1 else FAIL"),
    ("HUMAN42_TRANSITION_MATCH_PRESERVED", "human42_transition_match_preserved_count", "value == 13", "int", "PASS if 13 else FAIL"),
    ("HUMAN42_EARLY_MATCH_PRESERVED", "human42_early_match_preserved_count", "value == 4", "int", "PASS if 4 else FAIL"),
    ("HUMAN42_RECYCLED_TRANSITION_REMOVAL", "human42_recycled_transition_removal_count", "value == 3", "int", "PASS if 3 else FAIL"),
    ("HUMAN42_PREMATURE_TRANSITION_REMOVAL", "human42_premature_transition_removal_count", "value >= 4", "int", "PASS if >= 4 else FAIL"),
    ("HUMAN42_PREMATURE_FALSE_PROMOTION", "human42_premature_false_promotion_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("HUMAN42_026910_FULL_CLAUSE_TRACE_PRESENT", "human42_026910_full_clause_trace_present", "value is True", "bool", "PASS if True else FAIL"),
    ("HUMAN42_026910_HUMAN_COMPATIBILITY_CONCLUSION_PRESENT", "human42_026910_human_compatibility_conclusion_present", "value is True", "bool", "PASS if True else FAIL"),
    ("HUMAN42_026910_TRANSITION_REMOVAL_EXPECTED", "human42_026910_transition_removal_expected", "value is True", "bool", "PASS if True else FAIL"),
    ("CANONICAL_SCHEDULE_DETERMINISM", "canonical_schedule_determinism_status", "value == 'PASS'", "str", "PASS if 'PASS' else FAIL"),
    ("HISTORICAL_FEATURE_TIMELINE_PARITY_FAIL_COUNT", "historical_feature_timeline_parity_fail_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("HISTORICAL_FEATURE_TIMELINE_PARITY_COVERAGE_MATCH", "historical_feature_timeline_parity_coverage_match", "value is True", "bool", "PASS if True else FAIL"),
    ("SAME_EVENT_KEY_STATE_BEFORE_MISMATCH_COUNT", "same_event_key_state_before_mismatch_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("SAME_EVENT_KEY_TERMINATION_MISMATCH_COUNT", "same_event_key_termination_mismatch_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("SAME_EVENT_KEY_STATE_AFTER_MISMATCH_COUNT", "same_event_key_state_after_mismatch_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("SAME_EVENT_KEY_CANDIDATE_STAGE_MISMATCH_COUNT", "same_event_key_candidate_stage_mismatch_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("SAME_EVENT_KEY_REASON_CODE_MISMATCH_COUNT", "same_event_key_reason_code_mismatch_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("REQUEST_TEMPORAL_PROVENANCE_MISMATCH_COUNT", "request_temporal_provenance_mismatch_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("LIFECYCLE_CROSS_TICKER_EVENT_REUSE_COUNT", "lifecycle_cross_ticker_event_reuse_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("LIFECYCLE_OFF_BY_ONE_ERROR_COUNT", "lifecycle_off_by_one_error_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PROGRESSION_SEMANTIC_REVISION_REQUIRED_COUNT", "progression_semantic_revision_required_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("UNRESOLVED_CANDIDATE_SEMANTIC_CONFLICT_COUNT", "unresolved_candidate_semantic_conflict_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("LIFECYCLE_SEMANTIC_REVISION_REQUIRED_COUNT", "lifecycle_semantic_revision_required_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("SAME_EPISODE_PROGRESSION_UNRESOLVED_COUNT", "same_episode_progression_unresolved_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("UNRESOLVED_STRICT_ANCHOR_SEMANTIC_MISMATCH_COUNT", "unresolved_strict_anchor_semantic_mismatch_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("UNRESOLVED_PROGRESSED_ANCHOR_GAP_COUNT", "unresolved_progressed_anchor_gap_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PROGRESSED_WITH_INACTIVE_LIFECYCLE_STATE_COUNT", "progressed_with_inactive_lifecycle_state_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("MATURE_POST_BREAKOUT_DECISION_STATUS", "mature_post_breakout_decision_status", "value == 'DIAGNOSTIC_ONLY'", "str", "PASS if 'DIAGNOSTIC_ONLY' else FAIL"),
    ("MATURE_POST_BREAKOUT_BENCHMARK_REGRESSION_COUNT", "mature_post_breakout_benchmark_regression_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PHASE8_POSTHOC_KNOWN_LIMITATION_COUNT", "phase8_posthoc_known_limitation_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PHASE8_UNEXPLAINED_STAGE_CHANGE_COUNT", "phase8_unexplained_stage_change_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("PHASE8_TRANSITION_MATRIX_ARITHMETIC_CONSISTENCY", "phase8_transition_matrix_arithmetic_consistency", "value == 'PASS'", "str", "PASS if 'PASS' else FAIL"),
    ("PRESEAL_CONTRACT_ARTIFACT_CREATION_INTEGRITY", "preseal_contract_artifact_creation_integrity", "value == 'PASS'", "str", "PASS if 'PASS' else FAIL"),
    ("PRESEAL_EVIDENCE_ARTIFACT_CREATION_INTEGRITY", "preseal_evidence_artifact_creation_integrity", "value == 'PASS'", "str", "PASS if 'PASS' else FAIL"),
    ("OBSERVED_METRIC_REGISTRY_PROVENANCE_INTEGRITY", "observed_metric_registry_provenance_integrity", "value == 'PASS'", "str", "PASS if 'PASS' else FAIL"),
    ("CREATION_INTEGRITY_METRIC_SELF_DEPENDENCY_FREE", "creation_integrity_metric_self_dependency_free", "value is True", "bool", "PASS if True else FAIL"),
    ("FINAL_OBSERVED_METRIC_REGISTRY_COMPLETE", "final_observed_metric_registry_complete", "value is True", "bool", "PASS if True else FAIL"),
    ("REGISTRY_HASH_SELF_REFERENCE_FREE", "registry_hash_self_reference_free", "value is True", "bool", "PASS if True else FAIL"),
    ("REQUIRED_REGRESSION_BLOCKING_FAILURE_COUNT", "required_regression_blocking_failure_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("FULL_REPOSITORY_EXISTING_FAILURE_COUNT", "full_repository_existing_failure_count", "value == 0", "int", "PASS if 0 else FAIL"),
    ("FULL_REPOSITORY_TEST_EXIT_CODE", "full_repository_test_exit_code", "value == 0", "int", "PASS if 0 else FAIL"),
]

CANDIDATE_FREEZE_PRESEAL_REQUIRED_GATE_INVENTORY_V02: tuple[str, ...] = tuple(g[0] for g in _GATE_DEFINITIONS)


def build_preseal_gate_contract() -> PreSealGateContract:
    records = []
    for gate_id, metric_id, pred_def, schema, semantics in _GATE_DEFINITIONS:
        pred_hash = compute_canonical_sha256({"gate_id": gate_id, "predicate": pred_def})
        records.append(GateContractRecord(
            gate_id=gate_id,
            metric_id=metric_id,
            normative_predicate_definition=pred_def,
            normative_predicate_hash=pred_hash,
            evidence_schema=schema,
            status_semantics=semantics,
        ))

    payload = PreSealGateContractPayload(
        contract_version=PRESEAL_CONTRACT_VERSION,
        candidate_spec_version=CANDIDATE_RULE_SPEC_VERSION,
        serializer_contract_version=HASH_SERIALIZER_CONTRACT_VERSION,
        feature_allowlist=CANDIDATE_RAW_FEATURE_ALLOWLIST,
        required_gate_records=tuple(records),
    )
    contract_hash = compute_canonical_sha256(payload)
    return PreSealGateContract(payload=payload, contract_hash=contract_hash)


def _validate_schema(val: Any, expected_schema: str) -> bool:
    """Validate that observed metric value conforms strictly to expected schema."""
    if expected_schema == "int":
        return isinstance(val, int) and not isinstance(val, bool)
    elif expected_schema == "bool":
        return isinstance(val, bool)
    elif expected_schema == "str":
        return isinstance(val, str)
    return True


def evaluate_frozen_gate_predicate(
    contract_record: GateContractRecord,
    observed_metric: MetricRegistryRecord,
) -> GateEvaluationResult:
    """Evaluate frozen contract predicate with strict normative enforcement of schema, hash, and semantics."""
    gate_id = contract_record.gate_id
    pred_def = contract_record.normative_predicate_definition

    # 1. Enforcement: Recompute and verify predicate hash integrity
    expected_pred_hash = compute_canonical_sha256({"gate_id": gate_id, "predicate": pred_def})
    if expected_pred_hash != contract_record.normative_predicate_hash:
        return GateEvaluationResult(
            gate_id=gate_id,
            status=GateStatus.FAIL,
            observed_value=observed_metric.metric_value,
            target_criteria=pred_def,
            evidence_source=observed_metric.source_artifact_id,
            details=f"Predicate Hash Binding Violation: expected {expected_pred_hash} != {contract_record.normative_predicate_hash}",
        )

    # 2. Enforcement: Verify metric_id binding
    if observed_metric.metric_id != contract_record.metric_id:
        return GateEvaluationResult(
            gate_id=gate_id,
            status=GateStatus.FAIL,
            observed_value=observed_metric.metric_value,
            target_criteria=pred_def,
            evidence_source=observed_metric.source_artifact_id,
            details=f"Metric ID Binding Mismatch: expected {contract_record.metric_id} != {observed_metric.metric_id}",
        )

    val = observed_metric.metric_value

    # 3. Missing / None metric value -> NOT_EXECUTED
    if val is None:
        return GateEvaluationResult(
            gate_id=gate_id,
            status=GateStatus.NOT_EXECUTED,
            observed_value=None,
            target_criteria=pred_def,
            evidence_source=observed_metric.source_artifact_id,
            details="Observed value is None (Not Executed)",
        )

    # 4. Enforcement: Schema type check
    if not _validate_schema(val, contract_record.evidence_schema):
        return GateEvaluationResult(
            gate_id=gate_id,
            status=GateStatus.FAIL,
            observed_value=val,
            target_criteria=pred_def,
            evidence_source=observed_metric.source_artifact_id,
            details=f"Evidence Schema Mismatch: expected {contract_record.evidence_schema} but observed {type(val).__name__}",
        )

    # 5. Enforcement: Status semantics contradiction check
    if "PASS if 0" in contract_record.status_semantics and "value == 0" not in pred_def:
        return GateEvaluationResult(
            gate_id=gate_id,
            status=GateStatus.FAIL,
            observed_value=val,
            target_criteria=pred_def,
            evidence_source=observed_metric.source_artifact_id,
            details=f"Status Semantics Contradiction: {contract_record.status_semantics} vs {pred_def}",
        )

    # 6. Dynamic predicate evaluation
    try:
        passed = eval(pred_def, {"value": val})
    except Exception as e:
        return GateEvaluationResult(
            gate_id=gate_id,
            status=GateStatus.FAIL,
            observed_value=val,
            target_criteria=pred_def,
            evidence_source=observed_metric.source_artifact_id,
            details=f"Predicate evaluation error: {e}",
        )

    status = GateStatus.PASS if passed else GateStatus.FAIL
    return GateEvaluationResult(
        gate_id=gate_id,
        status=status,
        observed_value=val,
        target_criteria=pred_def,
        evidence_source=observed_metric.source_artifact_id,
        details=f"Evaluated predicate: {pred_def} -> {status.value}",
    )
