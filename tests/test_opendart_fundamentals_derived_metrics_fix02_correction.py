from __future__ import annotations

from types import SimpleNamespace

import pytest

from trend_scanner.fundamentals.derived_metrics import BASIS_MISMATCH, CURRENCY_MISMATCH, DerivedMetricsEngine
from trend_scanner.fundamentals.period_models import PeriodizationFact, PeriodizationResult

from scripts.validate_opendart_derived_metrics_fix02_correction import (
    _coherence_validation,
    _historical_detector,
    _margin_samples,
    _recompute_margin,
    _synth,
    final_acceptance_gate,
)
from trend_scanner.fundamentals.periodization_provider import PeriodizationBuild


@pytest.mark.parametrize(
    ("metric_type", "rows", "metric", "period"),
    [
        ("QUARTERLY_YOY", [_synth("revenue", "2023", "Q2", 100, basis="CFS"),
                            _synth("revenue", "2024", "Q2", 120, basis="OFS")], "revenue", "Q2"),
        ("TTM", [_synth("revenue", "2024", p, 100, basis="OFS" if p == "Q4" else "CFS")
                  for p in ("Q1", "Q2", "Q3", "Q4")], "revenue", "Q4"),
    ],
)
def test_cases_a_b_basis_targets_are_explicitly_blocked(metric_type, rows, metric, period):
    item = DerivedMetricsEngine().derive(rows).get(metric, metric_type, "2024", period)
    assert item is not None and item.resolution_status == BASIS_MISMATCH and item.value is None


def test_cases_c_d_basis_margin_targets_are_explicitly_blocked():
    rows = []
    for period in ("Q1", "Q2", "Q3", "Q4"):
        rows.extend((_synth("revenue", "2024", period, 100, basis="OFS" if period == "Q4" else "CFS"),
                     _synth("operating_income", "2024", period, 10)))
    result = DerivedMetricsEngine().derive(rows)
    assert result.get("operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4").resolution_status == BASIS_MISMATCH
    quarter = DerivedMetricsEngine().derive([
        _synth("revenue", "2024", "Q2", 100, basis="OFS"),
        _synth("operating_income", "2024", "Q2", 10, basis="CFS"),
    ]).get("operating_income", "OPERATING_MARGIN", "2024", "Q2")
    assert quarter is not None and quarter.resolution_status == BASIS_MISMATCH and quarter.value is None


def test_cases_e_h_currency_targets_are_explicitly_blocked():
    result = DerivedMetricsEngine().derive([
        _synth("revenue", "2023", "Q2", 100), _synth("revenue", "2024", "Q2", 120, currency="USD")
    ])
    assert result.get("revenue", "QUARTERLY_YOY", "2024", "Q2").resolution_status == CURRENCY_MISMATCH
    rows = []
    for period in ("Q1", "Q2", "Q3", "Q4"):
        rows.extend((_synth("revenue", "2024", period, 100, currency="USD" if period == "Q4" else "KRW"),
                     _synth("operating_income", "2024", period, 10)))
    result = DerivedMetricsEngine().derive(rows)
    assert result.get("revenue", "TTM", "2024", "Q4").resolution_status == CURRENCY_MISMATCH
    assert result.get("operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4").resolution_status == CURRENCY_MISMATCH


def test_cases_i_j_measured_counters_are_from_target_cases():
    measured = _coherence_validation()
    assert measured["basis_status"] == "PASS"
    assert measured["currency_status"] == "PASS"
    assert measured["basis_mismatch_used_count"] == 0
    assert measured["currency_mismatch_used_count"] == 0
    assert all(item["target_exists"] for item in measured["basis_cases"] + measured["currency_cases"])


def test_case_k_summary_consistency_is_required_by_final_gate():
    base = {
        "targeted_test_status": "PASS", "basis_status": "PASS", "basis_mismatch_used_count": 0,
        "currency_status": "PASS", "currency_mismatch_used_count": 0,
        "summary_consistency_status": "PASS", "summary_consistency_mismatch_count": 0,
        "historical_materialized_as_current_count": 0, "ambiguous_input_used_count": 0,
        "mismatch_input_used_count": 0, "undefined_percentage_emitted_count": 0,
        "nonpositive_revenue_margin_count": 0, "financial_margin_wrongly_computed_count": 0,
        "ttm_yoy_incomplete_provenance_count": 0, "ready_missing_pit_available_count": 0,
        "ready_future_pit_available_count": 0, "production_future_source_count": 0,
        "provider_cutoff_mismatch_count": 0, "source_provenance_alignment_status": "PASS",
        "production_provider_status": "PASS", "production_ttm_ready_count": 1,
        "production_ttm_yoy_ready_count": 1, "production_ttm_margin_ready_count": 1,
        "production_ttm_margin_recalc_mismatch_count": 0, "pykrx_krx_network_request_count": 0,
        "secret_leak_count": 0, "raw_source_committed": False,
    }
    assert final_acceptance_gate(base)
    base["summary_consistency_status"] = "FAIL"
    assert not final_acceptance_gate(base)


def test_cases_n_o_basis_or_currency_fail_blocks_final_gate():
    base = {
        "targeted_test_status": "PASS", "basis_status": "PASS", "basis_mismatch_used_count": 0,
        "currency_status": "PASS", "currency_mismatch_used_count": 0,
        "summary_consistency_status": "PASS", "summary_consistency_mismatch_count": 0,
        "historical_materialized_as_current_count": 0, "ambiguous_input_used_count": 0,
        "mismatch_input_used_count": 0, "undefined_percentage_emitted_count": 0,
        "nonpositive_revenue_margin_count": 0, "financial_margin_wrongly_computed_count": 0,
        "ttm_yoy_incomplete_provenance_count": 0, "ready_missing_pit_available_count": 0,
        "ready_future_pit_available_count": 0, "production_future_source_count": 0,
        "provider_cutoff_mismatch_count": 0, "source_provenance_alignment_status": "PASS",
        "production_provider_status": "PASS", "production_ttm_ready_count": 1,
        "production_ttm_yoy_ready_count": 1, "production_ttm_margin_ready_count": 1,
        "production_ttm_margin_recalc_mismatch_count": 0, "pykrx_krx_network_request_count": 0,
        "secret_leak_count": 0, "raw_source_committed": False,
    }
    base["basis_status"] = "FAIL"
    assert not final_acceptance_gate(base)
    base["basis_status"] = "PASS"
    base["currency_status"] = "FAIL"
    assert not final_acceptance_gate(base)


def test_case_l_historical_only_fact_is_not_promoted_but_prior_source_is_allowed():
    current = _synth("revenue", "2024", "Q3", 120, no="Q3")
    historical = PeriodizationFact(
        ticker="FIX02", corp_code="FIX02", company_family="NON_FINANCIAL", fiscal_year="2024",
        metric="revenue", value=100, currency="KRW", reprt_code="11012", report_type="HALF_YEAR",
        rcept_no="H1-A", rcept_dt="2024-08-14", period_start="2024-01-01", period_end="2024-06-30",
    )
    period_build = PeriodizationBuild(
        ticker="FIX02", fiscal_year="2024", requested_as_of="2024-12-31", company_family="NON_FINANCIAL",
        filings=(), facts=(historical,), result=PeriodizationResult((current,)),
        anchor_selections=({"reprt_code": "11014", "status": "READY", "selected_rcept_no": "Q3",
                            "prior_pit": {"selected_rcept_no": "H1-A"}},), skipped_anchors=(),
    )
    derived_build = SimpleNamespace(periodization_builds=(period_build,))
    records, promoted = _historical_detector((derived_build,))
    assert promoted == 0
    assert records[0]["historical_only_materialized_rcept_nos"] == ["H1-A"]
    assert records[0]["promoted_anchor_rcept_nos"] == []


def test_case_p_production_ttm_margin_recalculation_matches_independent_sum():
    rows = []
    for period, revenue, operating in zip(("Q1", "Q2", "Q3", "Q4"), (100, 200, 300, 400), (10, 20, 30, 90)):
        rows.extend((_synth("revenue", "2024", period, revenue),
                     _synth("operating_income", "2024", period, operating)))
    result = DerivedMetricsEngine().derive(PeriodizationResult(tuple(rows)))
    sample = result.get("operating_income", "TTM_OPERATING_MARGIN", "2024", "Q4")
    assert sample is not None and sample.resolution_status == "READY"
    build = SimpleNamespace(canonical_observations=tuple(rows))
    recomputed = _recompute_margin(build, sample)
    assert recomputed["expected_margin"] == 15
    assert recomputed["derived_margin"] == 15
    assert recomputed["difference"] <= 1e-9
    assert recomputed["recalc_violation"] is False
