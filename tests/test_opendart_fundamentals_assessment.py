from __future__ import annotations

import pytest

from trend_scanner.fundamentals.assessment import FundamentalsAssessmentEngine
from trend_scanner.fundamentals.assessment_models import FundamentalsAssessmentResult
from trend_scanner.fundamentals.derived_metrics import DerivedMetricObservation, DerivedMetricsResult
from trend_scanner.fundamentals.derived_metrics_provider import DerivedMetricsBuild
from trend_scanner.fundamentals.assessment_provider import FundamentalsAssessmentProvider


AS_OF = "2025-10-15"


def _item(metric: str, metric_type: str, value, *, status: str = "READY", metadata=None,
          family: str = "NON_FINANCIAL", period: str = "Q3", pit: str | None = AS_OF,
          source_dt: str = AS_OF, reason: str | None = None, year: str = "2025") -> DerivedMetricObservation:
    return DerivedMetricObservation(
        ticker="TEST", corp_code="TEST", company_family=family, fiscal_year=year,
        fiscal_period=period, metric=metric, metric_type=metric_type, value=value,
        resolution_status=status, reason=reason, period_end="2025-09-30",
        source_rcept_nos=(f"R-{metric}-{metric_type}",), source_rcept_dts=(source_dt,),
        source_sha256s=(f"sha-{metric}-{metric_type}",), requested_as_of=AS_OF,
        pit_available_from=pit, metadata=metadata or {},
    )


def _scenario(*, revenue=10, operating_income=10, net_income=10, ocf=10,
              op_margin=10, net_margin=5, ocf_margin=4,
              op_expansion="EXPANDING", net_expansion="EXPANDING",
              ocf_trend="IMPROVING", acceleration=1, streak=3,
              op_transition="PROFIT_GROWTH", net_transition="PROFIT_GROWTH"):
    rows = [
        _item("revenue", "QUARTERLY_YOY", revenue),
        _item("operating_income", "QUARTERLY_YOY", operating_income),
        _item("net_income", "QUARTERLY_YOY", net_income),
        _item("operating_cash_flow", "QUARTERLY_YOY", ocf),
        _item("operating_income", "OPERATING_MARGIN", op_margin),
        _item("net_income", "NET_MARGIN", net_margin),
        _item("operating_cash_flow", "OPERATING_CASH_FLOW_MARGIN", ocf_margin),
        _item("operating_income", "MARGIN_EXPANSION_TREND", 1 if op_expansion == "EXPANDING" else -1 if op_expansion == "CONTRACTING" else 0,
              metadata={"classification": op_expansion}),
        _item("net_income", "MARGIN_EXPANSION_TREND", 1 if net_expansion == "EXPANDING" else -1 if net_expansion == "CONTRACTING" else 0,
              metadata={"classification": net_expansion}),
        _item("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", ocf_trend),
        *[_item(metric, "YOY_GROWTH_ACCELERATION", acceleration) for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        *[_item(metric, "CONSECUTIVE_YOY_GROWTH", streak) for metric in ("revenue", "operating_income", "net_income", "operating_cash_flow")],
        _item("operating_income", "EARNINGS_TRANSITION", op_transition),
        _item("net_income", "EARNINGS_TRANSITION", net_transition),
    ]
    return DerivedMetricsResult(tuple(rows))


def test_broad_strong_is_deterministic_and_has_no_score():
    result = FundamentalsAssessmentEngine().assess(_scenario())
    assert isinstance(result, FundamentalsAssessmentResult)
    assert result.overall_state == "STRONG"
    assert result.matched_rule_id == "OVERALL_STRONG_V01"
    assert result.status == "READY"
    assert not any("score" in key.lower() for key in result.to_dict())


def test_turnaround_uses_transition_without_percentage_growth():
    result = FundamentalsAssessmentEngine().assess(_scenario(op_transition="LOSS_TO_PROFIT"))
    assert result.overall_state == "TURNAROUND"
    assert "LOSS_TO_PROFIT" in result.strengths
    transition = next(item for item in result.evidence if item.metric_type == "EARNINGS_TRANSITION" and item.metric == "operating_income")
    assert transition.explanation_code == "LOSS_TO_PROFIT"


def test_margin_warning_is_mixed_and_cash_divergence_is_a_risk():
    warning = FundamentalsAssessmentEngine().assess(_scenario(op_expansion="CONTRACTING", net_expansion="CONTRACTING", ocf=0, ocf_margin=-1, ocf_trend="DETERIORATING"))
    assert warning.overall_state in {"MIXED", "WEAKENING"}
    divergence = FundamentalsAssessmentEngine().assess(_scenario(ocf=-20, ocf_margin=-1, ocf_trend="DETERIORATING"))
    assert divergence.overall_state == "MIXED"
    assert any(code.startswith("OPERATING_CASH_FLOW") or code.startswith("OCF_") for code in divergence.risks)


def test_broad_weak_and_deceleration_are_not_positive():
    weak = FundamentalsAssessmentEngine().assess(_scenario(revenue=-10, operating_income=-20, net_income=-20, ocf=-20,
                                                            op_margin=-2, net_margin=-3, ocf_margin=-4,
                                                            op_expansion="CONTRACTING", net_expansion="CONTRACTING",
                                                            ocf_trend="DETERIORATING", acceleration=-1,
                                                            op_transition="PROFIT_DECLINE", net_transition="PROFIT_DECLINE"))
    assert weak.overall_state == "WEAK"
    slowing = FundamentalsAssessmentEngine().assess(_scenario(op_margin=-1, net_margin=-1, ocf=-10, ocf_margin=-1,
                                                               op_expansion="CONTRACTING", net_expansion="CONTRACTING",
                                                               ocf_trend="DETERIORATING", acceleration=-1))
    assert slowing.overall_state == "WEAKENING"
    assert slowing.momentum_state in {"DECELERATING", "DETERIORATING"}


def test_insufficient_data_does_not_backfill_previous_period():
    rows = (_item("revenue", "QUARTERLY_YOY", 10),)
    result = FundamentalsAssessmentEngine().assess(DerivedMetricsResult(rows), requested_as_of=AS_OF)
    assert result.status == "INSUFFICIENT_DATA"
    assert result.overall_state == "INSUFFICIENT_DATA"
    assert result.available_axis_count < 2


def test_unavailable_current_metric_is_not_zero_or_previous_period_fallback():
    rows = list(_scenario())
    index = next(i for i, item in enumerate(rows) if item.metric == "revenue" and item.metric_type == "QUARTERLY_YOY")
    rows[index] = _item("revenue", "QUARTERLY_YOY", None, status="INPUT_NOT_READY", reason="MARGIN_INPUT_UNAVAILABLE")
    result = FundamentalsAssessmentEngine().assess(DerivedMetricsResult(tuple(rows)))
    evidence = next(item for item in result.evidence if item.metric == "revenue" and item.axis == "GROWTH")
    assert evidence.status == "INPUT_NOT_READY"
    assert evidence.value is None
    assert evidence.direction == "NEUTRAL"


def test_sign_transition_and_zero_base_fail_closed():
    transition = FundamentalsAssessmentEngine().assess(_scenario(op_transition="LOSS_TO_PROFIT"))
    assert any(item.classification == "LOSS_TO_PROFIT" for item in transition.evidence)
    zero = FundamentalsAssessmentEngine().assess(
        DerivedMetricsResult((_item("revenue", "QUARTERLY_YOY", None, status="UNDEFINED_BASE", reason="NON_POSITIVE_OR_SIGN_TRANSITION_BASE"),
                              _item("operating_income", "QUARTERLY_YOY", 10),
                              _item("operating_cash_flow", "QUARTERLY_YOY", 10)))
    )
    assert not any(item.explanation_code == "REVENUE_YOY_POSITIVE" for item in zero.evidence)


def test_financial_is_explicitly_not_applicable():
    result = FundamentalsAssessmentEngine().assess(
        DerivedMetricsResult((_item("net_income", "QUARTERLY_YOY", 10, family="FINANCIAL"),))
    )
    assert result.status == "NOT_APPLICABLE"
    assert result.overall_state == "NOT_APPLICABLE"
    assert result.matched_rule_id == "FINANCIAL_PROFILE_NOT_IMPLEMENTED"


def test_pit_and_cutoff_fail_closed_without_future_evidence():
    future = FundamentalsAssessmentEngine().assess(
        DerivedMetricsResult((_item("revenue", "QUARTERLY_YOY", 10, source_dt="2025-10-20", pit="2025-10-20"),
                              _item("operating_income", "QUARTERLY_YOY", 10),
                              _item("operating_cash_flow", "QUARTERLY_YOY", 10))),
        requested_as_of=AS_OF,
    )
    assert future.status == "INPUT_NOT_READY"
    assert future.diagnostics["future_assessment_source_count"] > 0
    mismatch = FundamentalsAssessmentEngine().assess(_scenario(), requested_as_of="2025-11-01")
    assert mismatch.status == "INPUT_NOT_READY"
    assert mismatch.matched_rule_id == "INPUT_CUTOFF_MISMATCH"


def test_currentness_scope_and_stale_range_are_explicit():
    source = DerivedMetricsResult(tuple(_scenario().observations))
    build = DerivedMetricsBuild(
        ticker="TEST", requested_as_of=AS_OF, fiscal_years=("2023", "2024", "2025"),
        periodization_builds=(), canonical_observations=(), result=source,
    )
    current = FundamentalsAssessmentEngine().assess(
        build, requested_as_of=AS_OF, assessment_scope="CURRENT_AS_OF", expected_current_fiscal_year="2025",
    )
    assert current.assessment_scope == "CURRENT_AS_OF"
    assert current.currentness_status == "VERIFIED"
    stale_build = DerivedMetricsBuild(
        ticker="TEST", requested_as_of=AS_OF, fiscal_years=("2023", "2024"),
        periodization_builds=(), canonical_observations=(), result=source,
    )
    stale = FundamentalsAssessmentEngine().assess(
        stale_build, requested_as_of=AS_OF, assessment_scope="CURRENT_AS_OF", expected_current_fiscal_year="2025",
    )
    assert stale.currentness_status == "STALE_INPUT_RANGE"
    assert stale.status == "INPUT_NOT_READY"


def test_fy_wins_q4_and_input_order_is_invariant():
    q4 = [_item(item.metric, item.metric_type, item.value, metadata=dict(item.metadata), period="Q4") for item in _scenario()]
    fy = [_item(item.metric, item.metric_type, item.value, metadata=dict(item.metadata), period="FY") for item in _scenario()]
    engine = FundamentalsAssessmentEngine()
    first = engine.assess(DerivedMetricsResult(tuple(q4 + fy)))
    second = engine.assess(DerivedMetricsResult(tuple(reversed(fy + q4))))
    assert first.current_fiscal_period == "FY"
    assert second.current_fiscal_period == "FY"
    assert first.overall_state == second.overall_state
    assert first.matched_rule_id == second.matched_rule_id
    assert [item.to_dict() for item in first.evidence] == [item.to_dict() for item in second.evidence]


def test_level_and_direction_are_separate_for_positive_but_slowing():
    result = FundamentalsAssessmentEngine().assess(_scenario(
        acceleration=-1, op_expansion="CONTRACTING", net_expansion="CONTRACTING",
        ocf_trend="DETERIORATING",
    ))
    assert result.growth_state in {"POSITIVE", "STRONG", "MIXED"}
    assert result.growth_direction == "MIXED"
    assert result.profitability_direction == "DETERIORATING"
    assert result.cash_flow_direction == "DETERIORATING"
    assert result.overall_state != "IMPROVING"


def test_weak_level_can_have_improving_direction():
    result = FundamentalsAssessmentEngine().assess(_scenario(
        op_margin=-1, net_margin=-1, op_expansion="EXPANDING", net_expansion="EXPANDING",
        op_transition="LOSS_NARROWING", ocf_trend="IMPROVING",
    ))
    assert result.profitability_direction == "IMPROVING"
    assert result.cash_flow_direction == "IMPROVING"
    assert result.overall_state == "IMPROVING"
    assert result.negative_level_axis_count < 2


def test_expected_turnaround_overlap_is_diagnosed_without_conflict():
    result = FundamentalsAssessmentEngine().assess(_scenario(op_transition="LOSS_TO_PROFIT"))
    assert "OVERALL_TURNAROUND_V01" in result.matched_candidate_rules
    assert "OVERALL_IMPROVING_V01" in result.matched_candidate_rules
    assert result.assessment_rule_conflict_count == 0
    assert result.assessment_rule_mismatch_count == 0


def test_unexpected_turnaround_weak_overlap_is_counted_as_conflict():
    result = FundamentalsAssessmentEngine().assess(_scenario(
        revenue=-10, operating_income=-20, net_income=-20, ocf=-20,
        op_margin=-2, net_margin=-3, ocf_margin=-4,
        op_expansion="EXPANDING", net_expansion="FLAT", ocf_trend="IMPROVING",
        acceleration=0, streak=0, op_transition="LOSS_TO_PROFIT", net_transition="PROFIT_DECLINE",
    ))
    assert result.overall_state == "TURNAROUND"
    assert "OVERALL_WEAK_V01" in result.matched_candidate_rules
    assert result.assessment_rule_conflict_count >= 1


def test_strong_candidate_does_not_create_undocumented_improving_overlap():
    result = FundamentalsAssessmentEngine().assess(_scenario())
    assert result.overall_state == "STRONG"
    assert result.assessment_rule_conflict_count == 0


def test_provider_build_current_declares_requested_year_window():
    class FakeDerivedProvider:
        def __init__(self):
            self.calls = []

        def build(self, ticker, fiscal_years, requested_as_of, **kwargs):
            years = tuple(str(year) for year in fiscal_years)
            self.calls.append((ticker, years, requested_as_of))
            return DerivedMetricsBuild(
                ticker=str(ticker), requested_as_of=str(requested_as_of), fiscal_years=years,
                periodization_builds=(), canonical_observations=(), result=_scenario(),
            )

    fake = FakeDerivedProvider()
    result = FundamentalsAssessmentProvider(fake).build_current("005930", "2025-10-15")
    assert fake.calls == [("005930", ("2021", "2022", "2023", "2024", "2025"), "2025-10-15")]
    assert result.assessment_scope == "CURRENT_AS_OF"
    assert result.currentness_status == "VERIFIED"
    result_three = FundamentalsAssessmentProvider(fake).build_current(
        "005930", "2025-10-15", lookback_fiscal_years=3,
    )
    assert fake.calls[-1] == ("005930", ("2023", "2024", "2025"), "2025-10-15")
    assert result_three.currentness_status == "VERIFIED"


def _series_build(values, *, metric="revenue", years=("2022", "2023", "2024", "2025", "2026"),
                  observed_years=None, period="Q2"):
    observed_years = observed_years or years
    rows = [_item(metric, "QUARTERLY_YOY", value, year=year, period=period,
                  pit="2026-08-20", source_dt="2026-08-20")
            for year, value in zip(observed_years, values)]
    return DerivedMetricsBuild(
        ticker="TEST", requested_as_of="2026-08-20", fiscal_years=tuple(years),
        periodization_builds=(), canonical_observations=(), result=DerivedMetricsResult(tuple(rows)),
    )


@pytest.mark.parametrize("values, expected", [
    ((8, 14, 21, 28, 35), "ACCELERATING"),
    ((30, 24, 15, 7, 1), "DECELERATING"),
    ((8, 15, 24, 16, 14), "REVERSING_DOWN"),
    ((30, 20, 8, 14, 18), "REVERSING_UP"),
    ((10, 25, 15, 22, 30), "MIXED"),
])
def test_same_period_multi_year_trend_states(values, expected):
    result = FundamentalsAssessmentEngine().assess(
        _series_build(values), requested_as_of="2026-08-20",
        assessment_scope="CURRENT_AS_OF", expected_current_fiscal_year="2026",
    )
    series = result.same_period_yoy_series["revenue"]
    assert series.usable_yoy_point_count == 5
    assert series.trend_state == expected
    assert tuple(point.fiscal_period for point in series.points) == ("Q2",) * 5
    assert result.multi_year_trends["revenue"] == expected


def test_same_period_series_gap_breaks_continuity_and_missing_is_not_zero():
    build = _series_build((8, 21, 28), years=("2022", "2023", "2024", "2025", "2026"),
                          observed_years=("2023", "2025", "2026"))
    result = FundamentalsAssessmentEngine().assess(
        build, requested_as_of="2026-08-20", assessment_scope="CURRENT_AS_OF",
        expected_current_fiscal_year="2026",
    )
    series = result.same_period_yoy_series["revenue"]
    assert series.usable_yoy_point_count == 2
    assert series.trend_state == "INSUFFICIENT_DATA"
    assert series.points[2].resolution_status == "UNAVAILABLE"
    assert series.points[2].yoy_value is None


def test_same_period_series_ignores_other_fiscal_periods():
    rows = [_item("revenue", "QUARTERLY_YOY", value, year=year, period="Q2",
                   pit="2026-08-20", source_dt="2026-08-20")
            for year, value in zip(("2022", "2023", "2024", "2025", "2026"), (8, 14, 21, 28, 35))]
    rows.extend(_item("revenue", "QUARTERLY_YOY", value, year=year, period="Q1",
                      pit="2026-08-20", source_dt="2026-08-20")
                for year, value in zip(("2022", "2023", "2024", "2025", "2026"), (100, 1, 100, 1, 100)))
    build = DerivedMetricsBuild(
        ticker="TEST", requested_as_of="2026-08-20", fiscal_years=("2022", "2023", "2024", "2025", "2026"),
        periodization_builds=(), canonical_observations=(), result=DerivedMetricsResult(tuple(rows)),
    )
    result = FundamentalsAssessmentEngine().assess(build, requested_as_of="2026-08-20",
                                                   assessment_scope="CURRENT_AS_OF", expected_current_fiscal_year="2026")
    series = result.same_period_yoy_series["revenue"]
    assert [point.yoy_value for point in series.points] == [8.0, 14.0, 21.0, 28.0, 35.0]


def test_level_selectors_exclude_direction_evidence():
    rows = [
        _item("revenue", "QUARTERLY_YOY", -5),
        _item("revenue", "YOY_GROWTH_ACCELERATION", 30),
        _item("operating_income", "OPERATING_MARGIN", -2),
        _item("net_income", "NET_MARGIN", -1),
        _item("operating_income", "MARGIN_EXPANSION_TREND", 1, metadata={"classification": "EXPANDING"}),
        _item("operating_cash_flow", "QUARTERLY_YOY", -10),
        _item("operating_cash_flow", "OPERATING_CASH_FLOW_MARGIN", -2),
        _item("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", "IMPROVING"),
    ]
    result = FundamentalsAssessmentEngine().assess(DerivedMetricsResult(tuple(rows)))
    assert result.growth_state in {"NEGATIVE", "WEAK"}
    assert result.profitability_state in {"NEGATIVE", "WEAK"}
    assert result.cash_flow_state in {"NEGATIVE", "WEAK"}
    assert result.diagnostics["level_contaminated_by_direction_count"] == 0
    assert result.diagnostics["direction_contaminated_by_level_count"] == 0


def test_positive_streak_and_yoy_sign_do_not_create_direction():
    rows = [
        _item("revenue", "QUARTERLY_YOY", 10),
        _item("revenue", "CONSECUTIVE_YOY_GROWTH", 4),
        _item("operating_cash_flow", "QUARTERLY_YOY", 10),
        _item("operating_cash_flow", "TTM_YOY", 10),
    ]
    result = FundamentalsAssessmentEngine().assess(DerivedMetricsResult(tuple(rows)))
    assert result.growth_direction in {"UNAVAILABLE", "STABLE"}
    assert result.cash_flow_direction in {"UNAVAILABLE", "STABLE"}
    assert result.diagnostics["positive_streak_used_as_improvement_count"] == 0
    assert result.diagnostics["current_yoy_sign_used_as_direction_count"] == 0
    assert result.diagnostics["ttm_yoy_sign_used_as_direction_count"] == 0


def test_direction_components_are_permutation_invariant_and_do_not_overwrite():
    rows = [
        _item("operating_cash_flow", "QUARTERLY_YOY", -10),
        _item("operating_cash_flow", "OPERATING_CASH_FLOW_TREND", "DETERIORATING"),
        _item("operating_cash_flow", "MARGIN_EXPANSION_TREND", -1, metadata={"classification": "CONTRACTING"}),
        _item("operating_cash_flow", "TTM_YOY", 10),
    ]
    engine = FundamentalsAssessmentEngine()
    first = engine.assess(DerivedMetricsResult(tuple(rows)))
    second = engine.assess(DerivedMetricsResult(tuple(reversed(rows))))
    assert first.cash_flow_direction == second.cash_flow_direction == "DETERIORATING"
    assert first.direction_components == second.direction_components
    assert first.diagnostics["direction_component_overwrite_count"] == 0
    assert first.diagnostics["direction_order_dependence_count"] == 0
