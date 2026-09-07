"""Bounded F6 representative and negative validation matrix."""

from __future__ import annotations

from scripts.validate_fundamentals_f6 import run_validation


def test_f6_representative_and_negative_matrix_passes_without_artifact_writes():
    summary = run_validation(write_artifacts=False)
    assert summary["total_cases"] == 12
    assert len(summary["cases"]) == 12
    assert all(item["result"] == "PASS" for item in summary["cases"])

    representative_ids = {
        "CASE 01 — NORMAL PASS",
        "CASE 02 — FILTERED",
        "CASE 03 — FINANCIAL",
        "CASE 04 — ETF/NON-COMMON",
        "CASE 05 — INPUT ABSENT",
    }
    representative = [item for item in summary["cases"] if item["case_id"] in representative_ids]
    section_only = [item for item in summary["cases"] if item["case_id"] not in representative_ids]
    assert len(representative) == 5
    assert all(item["json_schema_valid"] is True for item in representative)
    assert all(item["markdown_valid"] is True for item in representative)
    assert all(item["summary_fundamentals_consistent"] is True for item in representative)
    assert all(item["as_of_consistent"] is True for item in representative)
    assert all(item["non_integration_guard"] is True for item in representative)
    assert all(item["json_schema_valid"] is None for item in section_only)
    assert all(item["markdown_valid"] is None for item in section_only)
    assert all(item["non_integration_guard"] is None for item in section_only)

    report_outputs = summary["report"]
    assert set(report_outputs) == representative_ids
    assert all(item["json_schema_valid"] is True for item in report_outputs.values())
    assert all(item["markdown_valid"] is True for item in report_outputs.values())
    assert all(item["summary_fundamentals_consistent"] is True for item in report_outputs.values())
    assert all(item["as_of_consistent"] is True for item in report_outputs.values())
    assert "FUNDAMENTALS_INPUT_NOT_PROVIDED" not in report_outputs["CASE 01 — NORMAL PASS"]["summary_bullet"]
    assert "FUNDAMENTALS_INPUT_NOT_PROVIDED" not in report_outputs["CASE 02 — FILTERED"]["summary_bullet"]
    assert "Filter PASS" in report_outputs["CASE 01 — NORMAL PASS"]["summary_bullet"]
    assert "Filter FILTERED_NET_LOSS" in report_outputs["CASE 02 — FILTERED"]["summary_bullet"]
    for item in report_outputs.values():
        assert item["report_requested_as_of"] == item["fundamentals_requested_as_of"] == "2026-06-30"
