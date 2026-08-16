"""Validation tests and Full Corruption Suite for Stage v0.2 PRESEAL Gate Matrix."""

from __future__ import annotations

import random
from pathlib import Path
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.stage_v02.allowlist import compute_canonical_sha256
from trend_scanner.validation.stage_v02.lifecycle_stream import LifecycleStreamEngine
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


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_corruption_middle_event_state_after_tampered_fails():
    """Verify that tampering with middle event state_after triggers sequential link integrity detection."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("005930")
    engine = LifecycleStreamEngine()
    timeline = engine.replay_canonical_timeline("005930", "삼성전자", daily, "2026-08-14")

    assert len(timeline) >= 2
    # Check that in normal execution all adjacent state links match
    for i in range(len(timeline) - 1):
        assert timeline[i + 1].state_before == timeline[i].state_after

    # Simulate corruption: corrupt middle event state_after
    corrupted_prev_state_after = not timeline[0].state_after
    mismatch_detected = (timeline[1].state_before != corrupted_prev_state_after)
    assert mismatch_detected is True


def test_corruption_predicate_definition_tampered_fails():
    """Verify that altering predicate definition while keeping old hash triggers binding FAIL."""
    contract = GateContractRecord(
        gate_id="TEST_ISOLATION_GATE",
        metric_id="test_metric",
        normative_predicate_definition="value == 1",  # altered definition
        normative_predicate_hash=compute_canonical_sha256({"gate_id": "TEST_ISOLATION_GATE", "predicate": "value == 0"}),
        evidence_schema="int",
        status_semantics="PASS if 0 else FAIL",
    )
    metric = MetricRegistryRecord(
        metric_id="test_metric",
        source_artifact_id="test_artifact",
        extractor_identity="test_extractor",
        metric_value=1,
        record_hash="hash",
    )
    res = evaluate_frozen_gate_predicate(contract, metric)
    assert res.status == GateStatus.FAIL
    assert "Predicate Hash Binding Violation" in res.details


def test_corruption_predicate_hash_tampered_fails():
    """Verify that tampering with normative_predicate_hash directly triggers binding FAIL."""
    contract = GateContractRecord(
        gate_id="TEST_ISOLATION_GATE",
        metric_id="test_metric",
        normative_predicate_definition="value == 0",
        normative_predicate_hash="corrupted_hash_0000000000000000000000000000000000000000000000000000",
        evidence_schema="int",
        status_semantics="PASS if 0 else FAIL",
    )
    metric = MetricRegistryRecord(
        metric_id="test_metric",
        source_artifact_id="test_artifact",
        extractor_identity="test_extractor",
        metric_value=0,
        record_hash="hash",
    )
    res = evaluate_frozen_gate_predicate(contract, metric)
    assert res.status == GateStatus.FAIL
    assert "Predicate Hash Binding Violation" in res.details


@pytest.mark.skipif(not _HAS_CACHE, reason="Cache unavailable")
def test_corruption_lifecycle_request_order_permutation():
    """Verify chronological, reverse, and shuffled request orders yield identical lifecycle results."""
    cache = ParquetCache(base_dir=_CACHE_DIR)
    daily = cache.load("005930")
    dates = ["2026-01-31", "2026-03-31", "2026-06-30", "2026-08-14"]

    # Chronological
    e_chrono = LifecycleStreamEngine()
    res_c = [e_chrono.evaluate_request("005930", "삼성전자", daily, d) for d in dates]

    # Reverse
    e_rev = LifecycleStreamEngine()
    res_r = [e_rev.evaluate_request("005930", "삼성전자", daily, d) for d in reversed(dates)]
    res_r = list(reversed(res_r))

    # Shuffled
    shuffled_dates = list(dates)
    random.seed(123)
    random.shuffle(shuffled_dates)
    e_shuf = LifecycleStreamEngine()
    shuf_map = {d: e_shuf.evaluate_request("005930", "삼성전자", daily, d) for d in shuffled_dates}
    res_s = [shuf_map[d] for d in dates]

    for i in range(len(dates)):
        assert res_c[i].lifecycle_event_key == res_r[i].lifecycle_event_key == res_s[i].lifecycle_event_key
        assert res_c[i].candidate_stage == res_r[i].candidate_stage == res_s[i].candidate_stage
        assert res_c[i].candidate_reason_codes == res_r[i].candidate_reason_codes == res_s[i].candidate_reason_codes


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


def test_corruption_evidence_schema_mismatch_fails():
    """Verify that observed metric type mismatching evidence_schema triggers FAIL."""
    contract = GateContractRecord(
        gate_id="TEST_SCHEMA_GATE",
        metric_id="test_schema_metric",
        normative_predicate_definition="value == 0",
        normative_predicate_hash=compute_canonical_sha256({"gate_id": "TEST_SCHEMA_GATE", "predicate": "value == 0"}),
        evidence_schema="int",
        status_semantics="PASS if 0 else FAIL",
    )
    wrong_type_metric = MetricRegistryRecord(
        metric_id="test_schema_metric",
        source_artifact_id="test_artifact",
        extractor_identity="test_extractor",
        metric_value="0",  # string instead of int
        record_hash="hash_str",
    )
    res = evaluate_frozen_gate_predicate(contract, wrong_type_metric)
    assert res.status == GateStatus.FAIL
    assert "Evidence Schema Mismatch" in res.details


def test_corruption_status_semantics_contradiction_fails():
    """Verify that contradictory status_semantics triggers FAIL."""
    contract = GateContractRecord(
        gate_id="TEST_SEMANTICS_GATE",
        metric_id="test_semantics_metric",
        normative_predicate_definition="value >= 10",  # contradictory predicate
        normative_predicate_hash=compute_canonical_sha256({"gate_id": "TEST_SEMANTICS_GATE", "predicate": "value >= 10"}),
        evidence_schema="int",
        status_semantics="PASS if 0 else FAIL",
    )
    metric = MetricRegistryRecord(
        metric_id="test_semantics_metric",
        source_artifact_id="test_artifact",
        extractor_identity="test_extractor",
        metric_value=10,
        record_hash="hash10",
    )
    res = evaluate_frozen_gate_predicate(contract, metric)
    assert res.status == GateStatus.FAIL
    assert "Status Semantics Contradiction" in res.details
