from __future__ import annotations

from scripts.validate_opendart_q1_canonical_duplicate_collapse import (
    evaluate_derived_readiness,
    evaluate_final_readiness,
    evaluate_periodization_readiness,
)


def _values() -> dict:
    return {
        "targeted_test_status": "PASS", "canonical_duplicate_collapse_status": "PASS",
        "context_scope_validation_status": "PASS", "production_missing_context_scope_count": 0,
        "production_primary_with_typed_dimension_count": 0, "production_primary_with_additional_dimension_count": 0,
        "different_scope_wrongly_collapsed_count": 0, "different_value_wrongly_collapsed_count": 0,
        "different_currency_wrongly_collapsed_count": 0, "different_basis_wrongly_collapsed_count": 0,
        "different_period_wrongly_collapsed_count": 0, "different_receipt_wrongly_collapsed_count": 0,
        "different_source_wrongly_collapsed_count": 0, "genuine_ambiguity_wrongly_ready_count": 0,
        "historical_detector_status": "PASS", "historical_production_violation_count": 0,
        "future_correction_leakage": "NO", "ready_future_source_count": 0,
        "source_provenance_alignment_status": "PASS",
        "q1_production_regression_status": "PASS", "known_duplicate_regression_count": 0,
        "secret_leak_count": 0, "raw_source_committed": False,
        "pykrx_krx_network_request_count": 0,
        "production_build_error_count": 0, "summary_consistency_status": "PASS",
        "production_ttm_ready_count": 140, "production_ttm_yoy_ready_count": 27,
        "production_ttm_margin_ready_count": 105, "production_ttm_margin_recalc_mismatch_count": 0,
        "validator_negative_control_status": "PASS",
    }


def test_all_pass_produces_ready():
    values = _values()
    assert evaluate_periodization_readiness(values) is True
    assert evaluate_derived_readiness(values, periodization_ready=True) is True
    assert evaluate_final_readiness(periodization_ready=True, derived_ready=True) is True


def test_periodization_scope_failure_blocks_final():
    values = _values(); values["context_scope_validation_status"] = "FAIL"
    assert evaluate_periodization_readiness(values) is False
    assert evaluate_final_readiness(periodization_ready=False, derived_ready=False) is False


def test_historical_and_future_failures_block_periodization():
    for key, value in (("historical_production_violation_count", 1), ("future_correction_leakage", "YES"),
                       ("source_provenance_alignment_status", "FAIL"), ("targeted_test_status", "FAIL"),
                       ("production_build_error_count", 1), ("summary_consistency_status", "FAIL")):
        values = _values(); values[key] = value
        assert evaluate_periodization_readiness(values) is False


def test_security_and_q1_closure_failures_block_periodization():
    for key, value in (
        ("secret_leak_count", 1),
        ("raw_source_committed", True),
        ("pykrx_krx_network_request_count", 1),
        ("q1_production_regression_status", "FAIL"),
        ("known_duplicate_regression_count", 1),
        ("ready_future_source_count", 1),
    ):
        values = _values(); values[key] = value
        assert evaluate_periodization_readiness(values) is False


def test_derived_evidence_failures_block_derived_and_final():
    for key, value in (("production_ttm_margin_ready_count", 0),
                       ("production_ttm_margin_recalc_mismatch_count", 1)):
        values = _values(); values[key] = value
        assert evaluate_derived_readiness(values, periodization_ready=True) is False
        assert evaluate_final_readiness(periodization_ready=True, derived_ready=False) is False
