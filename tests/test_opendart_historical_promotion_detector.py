from __future__ import annotations

from scripts.audit_opendart_q1_context_ambiguity import _historical_controls


def test_historical_prior_source_positive_control_is_allowed():
    result = _historical_controls()
    assert result["positive_control_violation_count"] == 0
    assert result["positive_control_allowed_historical_prior_source_count"] >= 1


def test_ambiguous_current_historical_materialization_is_detected():
    result = _historical_controls()
    assert len(result["negative_control_ambiguous_current_records"]) >= 1


def test_non_selected_current_filing_is_detected():
    result = _historical_controls()
    assert len(result["negative_control_non_selected_current_records"]) >= 1


def test_negative_controls_detect_both_violation_shapes():
    result = _historical_controls()
    assert result["negative_control_detected_count"] >= 2
    assert result["status"] == "PASS"


def test_detector_control_suite_does_not_promote_historical_prior():
    result = _historical_controls()
    assert result["positive_control_records"][0]["historical_materialized_as_current_count"] == 0
