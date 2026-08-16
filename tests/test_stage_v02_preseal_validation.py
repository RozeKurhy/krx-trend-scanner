"""Validation tests and Corruption Verification for Stage v0.2 PRESEAL Gate Matrix."""

from __future__ import annotations

from pathlib import Path
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.stage_v02.allowlist import compute_canonical_sha256
from trend_scanner.validation.stage_v02.preseal_contracts import (
    CANDIDATE_FREEZE_PRESEAL_REQUIRED_GATE_INVENTORY_V02,
    GateContractRecord,
    GateStatus,
    MetricRegistryRecord,
    evaluate_frozen_gate_predicate,
)
from trend_scanner.validation.stage_v02.preseal_evaluator import (
    run_preseal_evaluation,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CACHE_DIR = _REPO_ROOT / "data" / "raw" / "stocks"


def _cache_available() -> bool:
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("001540")
    return daily is not None and not daily.empty


_HAS_CACHE = _cache_available()


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_preseal_gate_matrix_execution():
    """Verify all 60 PRESEAL gates evaluate deterministically and identify blocking gates."""
    res = run_preseal_evaluation(_REPO_ROOT)
    gate_matrix = res["gate_matrix"]
    preseal_manifest = res["preseal_manifest"]

    assert gate_matrix.payload.gate_count == len(CANDIDATE_FREEZE_PRESEAL_REQUIRED_GATE_INVENTORY_V02)
    assert gate_matrix.payload.passed_gate_count == 59
    assert gate_matrix.payload.failed_gate_count == 1
    assert gate_matrix.payload.not_executed_gate_count == 0
    assert gate_matrix.payload.overall_status == GateStatus.FAIL

    # Check that the single failing gate is exactly 026910 removal expectation
    failing_gates = [g for g in gate_matrix.payload.gate_results if g.status == GateStatus.FAIL]
    assert len(failing_gates) == 1
    assert failing_gates[0].gate_id == "HUMAN42_026910_TRANSITION_REMOVAL_EXPECTED"

    # Manifest verification
    assert preseal_manifest.payload.overall_status == GateStatus.FAIL
    assert preseal_manifest.manifest_hash != ""
    assert len(preseal_manifest.manifest_hash) == 64


def test_corruption_observed_metric_value_tampering():
    """Verify that tampering with an observed metric value converts predicate result from PASS to FAIL."""
    contract = GateContractRecord(
        gate_id="TEST_ISOLATION_GATE",
        metric_id="test_import_count",
        normative_predicate_definition="value == 0",
        normative_predicate_hash=compute_canonical_sha256({"gate_id": "TEST_ISOLATION_GATE", "predicate": "value == 0"}),
        evidence_schema="int",
        status_semantics="PASS if 0 else FAIL",
    )

    # Valid metric -> PASS
    valid_metric = MetricRegistryRecord(
        metric_id="test_import_count",
        source_artifact_id="test_artifact",
        extractor_identity="test_extractor",
        metric_value=0,
        record_hash="hash0",
    )
    assert evaluate_frozen_gate_predicate(contract, valid_metric).status == GateStatus.PASS

    # Corrupted / tampered metric -> FAIL
    corrupted_metric = MetricRegistryRecord(
        metric_id="test_import_count",
        source_artifact_id="test_artifact",
        extractor_identity="test_extractor",
        metric_value=1,
        record_hash="hash1",
    )
    assert evaluate_frozen_gate_predicate(contract, corrupted_metric).status == GateStatus.FAIL


def test_corruption_missing_metric_yields_not_executed():
    """Verify that missing / None metric value correctly yields NOT_EXECUTED status."""
    contract = GateContractRecord(
        gate_id="TEST_REGRESSION_GATE",
        metric_id="test_regression_count",
        normative_predicate_definition="value == 0",
        normative_predicate_hash=compute_canonical_sha256({"gate_id": "TEST_REGRESSION_GATE", "predicate": "value == 0"}),
        evidence_schema="int",
        status_semantics="PASS if 0 else FAIL",
    )
    missing_metric = MetricRegistryRecord(
        metric_id="test_regression_count",
        source_artifact_id="test_artifact",
        extractor_identity="test_extractor",
        metric_value=None,
        record_hash="",
    )
    assert evaluate_frozen_gate_predicate(contract, missing_metric).status == GateStatus.NOT_EXECUTED


def test_corruption_predicate_hash_tampering():
    """Verify that modifying the normative predicate alters the contract hash and binding identity."""
    orig_hash = compute_canonical_sha256({"gate_id": "GATE_A", "predicate": "value >= 38"})
    tampered_hash = compute_canonical_sha256({"gate_id": "GATE_A", "predicate": "value >= 30"})
    assert orig_hash != tampered_hash
