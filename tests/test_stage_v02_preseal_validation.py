"""Validation tests for Stage v0.2 PRESEAL Gate Matrix and Candidate Rules."""

from __future__ import annotations

from pathlib import Path
import pytest

from trend_scanner.data.cache import ParquetCache
from trend_scanner.validation.stage_v02.preseal_contracts import (
    CANDIDATE_FREEZE_PRESEAL_REQUIRED_GATE_INVENTORY_V02,
    GateStatus,
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
