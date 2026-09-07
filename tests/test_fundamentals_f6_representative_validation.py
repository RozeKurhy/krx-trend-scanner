"""Bounded F6 representative and negative validation matrix."""

from __future__ import annotations

from scripts.validate_fundamentals_f6 import run_validation


def test_f6_representative_and_negative_matrix_passes_without_artifact_writes():
    summary = run_validation(write_artifacts=False)
    assert summary["total_cases"] == 12
    assert len(summary["cases"]) == 12
    assert all(item["result"] == "PASS" for item in summary["cases"])
    assert all(item["non_integration_guard"] is True for item in summary["cases"])
